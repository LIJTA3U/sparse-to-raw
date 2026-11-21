#!/usr/bin/env python3
"""Inspect and extract Android dynamic partitions from super images.

The module implements the read-only liblp metadata reader and a bounded-memory
extractor using only the Python standard library. Android Sparse inputs are
expanded to a temporary RAW file through the project's existing validator and
converter; the source image is never modified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from sparse_to_raw import ConversionCancelled, convert_sparse_to_raw

LP_SECTOR_SIZE = 512
LP_PARTITION_RESERVED_BYTES = 4096
LP_METADATA_GEOMETRY_SIZE = 4096
LP_METADATA_GEOMETRY_MAGIC = 0x616C4467
LP_METADATA_HEADER_MAGIC = 0x414C5030
LP_PARTITION_ATTR_READONLY = 1 << 0
LP_PARTITION_ATTR_SLOT_SUFFIXED = 1 << 1
LP_PARTITION_ATTR_UPDATED = 1 << 2
LP_PARTITION_ATTR_DISABLED = 1 << 3
LP_PARTITION_ATTR_MASK = 0x0F
LP_GROUP_SLOT_SUFFIXED = 1 << 0
LP_GROUP_FLAGS_MASK = LP_GROUP_SLOT_SUFFIXED
LP_BLOCK_DEVICE_SLOT_SUFFIXED = 1 << 0
LP_BLOCK_DEVICE_FLAGS_MASK = LP_BLOCK_DEVICE_SLOT_SUFFIXED
LP_TARGET_TYPE_LINEAR = 0
LP_TARGET_TYPE_ZERO = 1
SPARSE_MAGIC = 0xED26FF3A
COPY_BUFFER_SIZE = 1024 * 1024

GEOMETRY_STRUCT = struct.Struct("<II32sIII")
HEADER_PREFIX = struct.Struct("<IHHI32sI32s")
TABLE_DESCRIPTOR = struct.Struct("<III")
PARTITION_STRUCT = struct.Struct("<36sIIII")
EXTENT_STRUCT = struct.Struct("<QIQI")
GROUP_STRUCT = struct.Struct("<36sIQ")
BLOCK_DEVICE_STRUCT = struct.Struct("<QIIQ36sI")

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCallback = Callable[[], bool]


class SuperImageError(ValueError):
    """Invalid, unsupported, or inconsistent Android super image."""


class SuperImageCancelled(InterruptedError):
    """Super image inspection/extraction was cancelled by the caller."""


def _read_exact(stream, size: int, label: str) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise SuperImageError(
            f"Unexpected end of file while reading {label}: expected {size} bytes, got {len(data)}"
        )
    return data


def _source_signature(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {
        "size_bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "inode": int(getattr(stat, "st_ino", 0)),
    }


def _decode_name(raw: bytes, label: str) -> str:
    value = raw.split(b"\0", 1)[0].decode("ascii", "strict")
    if not value:
        raise SuperImageError(f"{label} has an empty name")
    return value


def _slot_suffix(slot: int) -> str:
    if 0 <= slot < 26:
        return "_" + chr(ord("a") + slot)
    return f"_slot{slot}"


def _read_geometry(stream, file_size: int) -> tuple[dict[str, Any], int]:
    errors: list[str] = []
    for offset, label in (
        (LP_PARTITION_RESERVED_BYTES, "primary"),
        (LP_PARTITION_RESERVED_BYTES + LP_METADATA_GEOMETRY_SIZE, "backup"),
    ):
        if offset + GEOMETRY_STRUCT.size > file_size:
            errors.append(f"{label} geometry is outside the image")
            continue
        stream.seek(offset)
        fixed = _read_exact(stream, GEOMETRY_STRUCT.size, f"{label} LP geometry")
        magic, struct_size, stored_checksum, metadata_max_size, slot_count, logical_block_size = GEOMETRY_STRUCT.unpack(fixed)
        if magic != LP_METADATA_GEOMETRY_MAGIC:
            errors.append(f"{label} geometry magic is invalid (0x{magic:08X})")
            continue
        if struct_size < GEOMETRY_STRUCT.size or struct_size > LP_METADATA_GEOMETRY_SIZE:
            errors.append(f"{label} geometry has an unsupported structure size: {struct_size}")
            continue
        stream.seek(offset)
        geometry_data = bytearray(_read_exact(stream, struct_size, f"{label} LP geometry body"))
        geometry_data[8:40] = b"\0" * 32
        computed_checksum = hashlib.sha256(geometry_data).digest()
        if computed_checksum != stored_checksum:
            errors.append(f"{label} geometry SHA-256 checksum mismatch")
            continue
        if metadata_max_size <= 0 or metadata_max_size % LP_SECTOR_SIZE:
            errors.append(f"{label} geometry has an invalid metadata_max_size: {metadata_max_size}")
            continue
        if not 1 <= slot_count <= 32:
            errors.append(f"{label} geometry has an invalid metadata_slot_count: {slot_count}")
            continue
        if logical_block_size < LP_SECTOR_SIZE or logical_block_size % LP_SECTOR_SIZE:
            errors.append(f"{label} geometry has an invalid logical_block_size: {logical_block_size}")
            continue
        return ({
            "metadata_max_size": metadata_max_size,
            "metadata_slot_count": slot_count,
            "logical_block_size": logical_block_size,
            "geometry_copy": label,
            "geometry_offset": offset,
        }, offset)
    raise SuperImageError("Could not read valid LP metadata geometry: " + "; ".join(errors))


def _parse_metadata_at(stream, metadata_offset: int, geometry: dict[str, Any], file_size: int) -> dict[str, Any]:
    max_size = int(geometry["metadata_max_size"])
    if metadata_offset < 0 or metadata_offset + max_size > file_size:
        raise SuperImageError("LP metadata area extends beyond the image boundary")
    stream.seek(metadata_offset)
    fixed = _read_exact(stream, HEADER_PREFIX.size + TABLE_DESCRIPTOR.size * 4, "LP metadata header")
    magic, major, minor, header_size, header_checksum, tables_size, tables_checksum = HEADER_PREFIX.unpack_from(fixed)
    if magic != LP_METADATA_HEADER_MAGIC:
        raise SuperImageError(f"Invalid LP metadata magic: 0x{magic:08X}")
    if major != 10 or minor > 2:
        raise SuperImageError(f"Unsupported LP metadata version {major}.{minor}; supported versions are 10.0–10.2")
    if header_size < len(fixed) or header_size > max_size:
        raise SuperImageError(f"Invalid LP metadata header size: {header_size}")
    if tables_size > max_size - header_size:
        raise SuperImageError("LP metadata tables exceed the reserved metadata area")

    stream.seek(metadata_offset)
    header_data = bytearray(_read_exact(stream, header_size, "complete LP metadata header"))
    header_data[12:44] = b"\0" * 32
    if hashlib.sha256(header_data).digest() != header_checksum:
        raise SuperImageError("LP metadata header SHA-256 checksum mismatch")
    tables_data = _read_exact(stream, tables_size, "LP metadata tables")
    if hashlib.sha256(tables_data).digest() != tables_checksum:
        raise SuperImageError("LP metadata tables SHA-256 checksum mismatch")

    descriptors: dict[str, dict[str, int]] = {}
    for index, name in enumerate(("partitions", "extents", "groups", "block_devices")):
        offset, count, entry_size = TABLE_DESCRIPTOR.unpack_from(fixed, HEADER_PREFIX.size + index * TABLE_DESCRIPTOR.size)
        minimum_size = {
            "partitions": PARTITION_STRUCT.size,
            "extents": EXTENT_STRUCT.size,
            "groups": GROUP_STRUCT.size,
            "block_devices": BLOCK_DEVICE_STRUCT.size,
        }[name]
        if count and entry_size < minimum_size:
            raise SuperImageError(f"LP {name} table entry size {entry_size} is smaller than {minimum_size}")
        if count > 1_000_000:
            raise SuperImageError(f"LP {name} table contains an unreasonable number of entries: {count}")
        table_length = count * entry_size
        if offset > tables_size or table_length > tables_size - offset:
            raise SuperImageError(f"LP {name} table is outside the metadata table area")
        if count and entry_size == 0:
            raise SuperImageError(f"LP {name} table has a zero entry size")
        descriptors[name] = {"offset": offset, "count": count, "entry_size": entry_size}

    def entries(name: str, layout: struct.Struct) -> list[bytes]:
        descriptor = descriptors[name]
        start = descriptor["offset"]
        step = descriptor["entry_size"]
        return [tables_data[start + i * step:start + i * step + layout.size] for i in range(descriptor["count"])]

    groups: list[dict[str, Any]] = []
    for raw in entries("groups", GROUP_STRUCT):
        name, flags, maximum_size = GROUP_STRUCT.unpack(raw)
        if flags & ~LP_GROUP_FLAGS_MASK:
            raise SuperImageError(f"LP group contains unknown flag bits: 0x{flags:X}")
        groups.append({"name": _decode_name(name, "LP partition group"), "flags": flags, "maximum_size_bytes": maximum_size})

    block_devices: list[dict[str, Any]] = []
    slot_suffix = _slot_suffix(int(geometry.get("selected_slot", 0)))
    for raw in entries("block_devices", BLOCK_DEVICE_STRUCT):
        first_sector, alignment, alignment_offset, size, name, flags = BLOCK_DEVICE_STRUCT.unpack(raw)
        if flags & ~LP_BLOCK_DEVICE_FLAGS_MASK:
            raise SuperImageError(f"LP block device contains unknown flag bits: 0x{flags:X}")
        if size and first_sector * LP_SECTOR_SIZE > size:
            raise SuperImageError("LP block device first logical sector exceeds its declared size")
        device_name = _decode_name(name, "LP block device")
        if flags & LP_BLOCK_DEVICE_SLOT_SUFFIXED:
            device_name += slot_suffix
        block_devices.append({
            "first_logical_sector": first_sector,
            "alignment_bytes": alignment,
            "alignment_offset_bytes": alignment_offset,
            "size_bytes": size,
            "partition_name": device_name,
            "flags": flags,
        })
    if not block_devices:
        raise SuperImageError("LP metadata contains no block-device entries")

    extents: list[dict[str, Any]] = []
    for raw in entries("extents", EXTENT_STRUCT):
        sectors, target_type, target_data, target_source = EXTENT_STRUCT.unpack(raw)
        if sectors <= 0:
            raise SuperImageError("LP metadata contains a zero-length extent")
        if target_type not in (LP_TARGET_TYPE_LINEAR, LP_TARGET_TYPE_ZERO):
            raise SuperImageError(f"Unsupported LP extent target type: {target_type}")
        if target_type == LP_TARGET_TYPE_ZERO and (target_data != 0 or target_source != 0):
            raise SuperImageError("LP zero extent contains non-zero target fields")
        if target_type == LP_TARGET_TYPE_LINEAR and target_source >= len(block_devices):
            raise SuperImageError(f"LP extent references missing block device index {target_source}")
        extents.append({
            "num_sectors": sectors,
            "target_type": target_type,
            "target_data_sector": target_data,
            "target_source": target_source,
        })

    slot_suffix = _slot_suffix(int(geometry.get("selected_slot", 0)))
    for group in groups:
        if group["flags"] & LP_GROUP_SLOT_SUFFIXED:
            group["name"] += slot_suffix

    partitions: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for raw in entries("partitions", PARTITION_STRUCT):
        raw_name, attributes, first_extent, extent_count, group_index = PARTITION_STRUCT.unpack(raw)
        name = _decode_name(raw_name, "LP partition")
        # AOSP LP partition names are ASCII alphanumeric/underscore only.
        # Enforce this before using the name as an output filename.
        if not re.fullmatch(r"[A-Za-z0-9_]{1,36}", name):
            raise SuperImageError(f"LP partition has an invalid or unsafe name: {name!r}")
        if attributes & ~LP_PARTITION_ATTR_MASK:
            raise SuperImageError(f"Partition {name} contains unknown attribute bits: 0x{attributes:X}")
        if extent_count < 1 or first_extent + extent_count > len(extents):
            raise SuperImageError(f"Partition {name} has an invalid extent range")
        if group_index >= len(groups):
            raise SuperImageError(f"Partition {name} references missing group index {group_index}")
        if attributes & LP_PARTITION_ATTR_SLOT_SUFFIXED:
            name += slot_suffix
        if name in seen_names:
            raise SuperImageError(f"Duplicate LP partition name after slot adjustment: {name}")
        seen_names.add(name)
        partition_extents = extents[first_extent:first_extent + extent_count]
        size_bytes = sum(int(extent["num_sectors"]) * LP_SECTOR_SIZE for extent in partition_extents)
        partitions.append({
            "name": name,
            "attributes": attributes,
            "readonly": bool(attributes & LP_PARTITION_ATTR_READONLY),
            "slot_suffixed": bool(attributes & LP_PARTITION_ATTR_SLOT_SUFFIXED),
            "updated": bool(attributes & LP_PARTITION_ATTR_UPDATED),
            "disabled": bool(attributes & LP_PARTITION_ATTR_DISABLED),
            "first_extent_index": first_extent,
            "num_extents": extent_count,
            "group": groups[group_index]["name"],
            "group_index": group_index,
            "size_bytes": size_bytes,
            "extents": partition_extents,
        })

    flags = struct.unpack_from("<I", header_data, 128)[0] if header_size >= 132 else 0
    return {
        "metadata_version": f"{major}.{minor}",
        "metadata_offset": metadata_offset,
        "metadata_copy": "primary" if metadata_offset < (LP_PARTITION_RESERVED_BYTES + 2 * LP_METADATA_GEOMETRY_SIZE + max_size * int(geometry["metadata_slot_count"])) else "backup",
        "header_size": header_size,
        "tables_size": tables_size,
        "header_flags": flags,
        "virtual_ab_device": bool(flags & 0x1),
        "overlays_active": bool(flags & 0x2),
        "partitions": partitions,
        "groups": groups,
        "block_devices": block_devices,
        "metadata_sha256": hashlib.sha256(header_data + tables_data).hexdigest(),
    }


def _parse_super_raw(path: Path, slot: int) -> dict[str, Any]:
    file_size = path.stat().st_size
    with path.open("rb") as stream:
        geometry, _ = _read_geometry(stream, file_size)
        slot_count = int(geometry["metadata_slot_count"])
        if not 0 <= slot < slot_count:
            raise SuperImageError(f"Selected metadata slot {slot} is invalid; image contains {slot_count} slot(s)")
        geometry["selected_slot"] = slot
        base = LP_PARTITION_RESERVED_BYTES + 2 * LP_METADATA_GEOMETRY_SIZE
        offsets = (
            base + int(geometry["metadata_max_size"]) * slot,
            base + int(geometry["metadata_max_size"]) * slot_count + int(geometry["metadata_max_size"]) * slot,
        )
        failures: list[str] = []
        metadata: dict[str, Any] | None = None
        for offset in offsets:
            try:
                metadata = _parse_metadata_at(stream, offset, geometry, file_size)
                break
            except SuperImageError as exc:
                failures.append(f"offset {offset}: {exc}")
        if metadata is None:
            raise SuperImageError("Could not read valid LP metadata (primary and backup copies failed): " + "; ".join(failures))

    # Check the physical-source ranges before exposing metadata to the UI.
    for partition in metadata["partitions"]:
        for extent in partition["extents"]:
            if extent["target_type"] != LP_TARGET_TYPE_LINEAR:
                continue
            source_index = int(extent["target_source"])
            device_size = int(metadata["block_devices"][source_index]["size_bytes"])
            source_start = int(extent["target_data_sector"]) * LP_SECTOR_SIZE
            extent_size = int(extent["num_sectors"]) * LP_SECTOR_SIZE
            device = metadata["block_devices"][source_index]
            first_logical_byte = int(device["first_logical_sector"]) * LP_SECTOR_SIZE
            if source_start < first_logical_byte:
                raise SuperImageError(
                    f"Partition {partition['name']} contains an extent before the first logical sector "
                    f"of block device {source_index}"
                )
            if device_size and source_start + extent_size > device_size:
                raise SuperImageError(f"Partition {partition['name']} contains an extent outside block device {source_index}")
            if source_index == 0 and source_start + extent_size > file_size:
                raise SuperImageError(f"Partition {partition['name']} contains an extent outside the input image")
    metadata.update({
        "geometry": geometry,
        "input_size_bytes": file_size,
        "source_format": "RAW",
    })
    return metadata


def _is_android_sparse(path: Path) -> bool:
    with path.open("rb") as stream:
        marker = stream.read(4)
    return len(marker) == 4 and struct.unpack("<I", marker)[0] == SPARSE_MAGIC


class _PreparedSuperImage:
    """Context manager that expands Sparse to temporary RAW when needed."""
    def __init__(
        self,
        source: Path,
        *,
        progress_callback: ProgressCallback | None = None,
        cancel_requested: CancelCallback | None = None,
    ) -> None:
        self.source = source
        self.progress_callback = progress_callback
        self.cancel_requested = cancel_requested
        self.temp_dir: tempfile.TemporaryDirectory[str] | None = None
        self.raw_path = source
        self.source_format = "RAW"

    def __enter__(self) -> tuple[Path, str]:
        if _is_android_sparse(self.source):
            self.source_format = "Android Sparse"
            self.temp_dir = tempfile.TemporaryDirectory(prefix="sparse-to-raw-super-")
            self.raw_path = Path(self.temp_dir.name) / "super.raw"
            def report_progress(data: dict[str, Any]) -> None:
                if self.progress_callback:
                    self.progress_callback({
                        "stage": "preparing",
                        "partition": "Sparse input",
                        "percent": int(data.get("percent", 0)),
                        "processed_bytes": int(data.get("processed_bytes", 0)),
                        "total_bytes": int(data.get("expected_bytes", 0)),
                    })
            try:
                convert_sparse_to_raw(
                    self.source, self.raw_path, force=False, calculate_sha256=False,
                    progress_callback=report_progress if self.progress_callback else None,
                    cancel_requested=self.cancel_requested,
                )
            except ConversionCancelled as exc:
                raise SuperImageCancelled(str(exc)) from exc
        return self.raw_path, self.source_format

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.temp_dir is not None:
            self.temp_dir.cleanup()


def inspect_super_image(
    input_path: str | Path,
    *,
    slot: int = 0,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Read and validate dynamic-partition metadata without modifying the input."""
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Super image not found: {source}")
    signature_before = _source_signature(source)
    if cancel_requested and cancel_requested():
        raise SuperImageCancelled("Super image inspection cancelled")
    with _PreparedSuperImage(
        source, progress_callback=progress_callback, cancel_requested=cancel_requested,
    ) as (raw_path, source_format):
        result = _parse_super_raw(raw_path, slot)
        result["source_format"] = source_format
    if _source_signature(source) != signature_before:
        raise SuperImageError("The input image changed while its metadata was being read")
    result["input"] = str(source)
    result["source_signature"] = signature_before
    result["partition_count"] = len(result["partitions"])
    result["group_count"] = len(result["groups"])
    result["block_device_count"] = len(result["block_devices"])
    result["total_partition_bytes"] = sum(int(item["size_bytes"]) for item in result["partitions"])
    return result


def _check_cancel(cancel_requested: CancelCallback | None) -> None:
    if cancel_requested and cancel_requested():
        raise SuperImageCancelled("Super image extraction cancelled")


def extract_super_partitions(
    input_path: str | Path,
    output_dir: str | Path,
    partitions: Iterable[str] | None = None,
    *,
    slot: int = 0,
    force: bool = False,
    expected_signature: dict[str, int] | None = None,
    expected_metadata_sha256: str | None = None,
    reserved_output_paths: Iterable[str | Path] | None = None,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Extract selected logical partitions as RAW images using bounded memory.

    Existing files are preserved unless ``force=True``. Each output is assembled
    in a temporary file in the destination directory and published only after
    all extents for that partition have been read successfully.
    """
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Super image not found: {source}")
    signature_before = _source_signature(source)
    if expected_signature is not None and signature_before != expected_signature:
        raise SuperImageError("The source image changed after inspection. Analyze it again before extraction.")
    destination.mkdir(parents=True, exist_ok=True)
    if not destination.is_dir():
        raise NotADirectoryError(f"Output path is not a directory: {destination}")

    sparse_input = _is_android_sparse(source)
    def preparation_progress(data: dict[str, Any]) -> None:
        if progress_callback:
            progress_callback({
                **data,
                "percent": int(data.get("percent", 0) * 0.5) if sparse_input else int(data.get("percent", 0)),
            })
    with _PreparedSuperImage(
        source,
        progress_callback=preparation_progress if progress_callback else None,
        cancel_requested=cancel_requested,
    ) as (raw_path, source_format):
        metadata = _parse_super_raw(raw_path, slot)
        if expected_metadata_sha256 and metadata["metadata_sha256"] != expected_metadata_sha256:
            raise SuperImageError("LP metadata changed after inspection. Analyze the image again before extraction.")
        available = {item["name"]: item for item in metadata["partitions"]}
        requested = list(dict.fromkeys(partitions)) if partitions is not None else list(available)
        if not requested:
            raise SuperImageError("Select at least one logical partition to extract")
        missing = [name for name in requested if name not in available]
        if missing:
            raise SuperImageError("Partition(s) not found in the selected metadata slot: " + ", ".join(missing))
        selected = [available[name] for name in requested]
        for partition in selected:
            for extent in partition["extents"]:
                if extent["target_type"] == LP_TARGET_TYPE_LINEAR and extent["target_source"] != 0:
                    raise SuperImageError(
                        f"Partition {partition['name']} uses block device {extent['target_source']}. "
                        "This build accepts one super image file; multi-image retrofit layouts are not supported yet."
                    )

        total_bytes = sum(int(item["size_bytes"]) for item in selected)
        free_bytes = shutil.disk_usage(destination).free
        # A sparse output may consume less disk space, but requiring the logical
        # size avoids starting an extraction that cannot be completed safely.
        if free_bytes < total_bytes:
            raise OSError(
                f"Not enough free space in {destination}: {free_bytes} bytes available, "
                f"{total_bytes} bytes required (logical size)"
            )
        output_paths = [destination / f"{item['name']}.img" for item in selected]
        reserved = {Path(path).expanduser().resolve() for path in (reserved_output_paths or [])}
        for partition, output_path in zip(selected, output_paths):
            resolved_output = output_path.resolve()
            if resolved_output == source:
                raise SuperImageError(
                    f"Refusing to overwrite the input super image with extracted partition {partition['name']}"
                )
            if resolved_output in reserved:
                raise SuperImageError(
                    f"Output path for partition {partition['name']} conflicts with another requested output: {resolved_output}"
                )
        existing = [path for path in output_paths if path.exists()]
        if existing and not force:
            raise FileExistsError("Output file(s) already exist: " + ", ".join(str(path) for path in existing))

        extracted: list[dict[str, Any]] = []
        processed_total = 0
        with raw_path.open("rb") as input_stream:
            for partition in selected:
                _check_cancel(cancel_requested)
                output_path = destination / f"{partition['name']}.img"
                fd, temp_name = tempfile.mkstemp(prefix=f".{partition['name']}.", suffix=".tmp", dir=destination)
                temp_path = Path(temp_name)
                try:
                    with os.fdopen(fd, "wb") as output_stream:
                        partition_processed = 0
                        for extent_index, extent in enumerate(partition["extents"], start=1):
                            _check_cancel(cancel_requested)
                            extent_bytes = int(extent["num_sectors"]) * LP_SECTOR_SIZE
                            if extent_bytes % int(metadata["geometry"]["logical_block_size"]):
                                raise SuperImageError(
                                    f"Partition {partition['name']} extent {extent_index} is not aligned "
                                    "to the logical block size"
                                )
                            if extent["target_type"] == LP_TARGET_TYPE_ZERO:
                                output_stream.seek(extent_bytes, os.SEEK_CUR)
                                partition_processed += extent_bytes
                                processed_total += extent_bytes
                            else:
                                source_offset = int(extent["target_data_sector"]) * LP_SECTOR_SIZE
                                remaining = extent_bytes
                                input_stream.seek(source_offset)
                                while remaining:
                                    _check_cancel(cancel_requested)
                                    chunk = input_stream.read(min(COPY_BUFFER_SIZE, remaining))
                                    if not chunk:
                                        raise SuperImageError(
                                            f"Unexpected end of super image while extracting {partition['name']}"
                                        )
                                    output_stream.write(chunk)
                                    amount = len(chunk)
                                    remaining -= amount
                                    partition_processed += amount
                                    processed_total += amount
                                    if progress_callback:
                                        extraction_percent = min(100, int(processed_total * 100 / max(total_bytes, 1)))
                                        progress_callback({
                                            "stage": "extracting",
                                            "partition": partition["name"],
                                            "processed_bytes": processed_total,
                                            "partition_processed_bytes": partition_processed,
                                            "total_bytes": total_bytes,
                                            "percent": 50 + int(extraction_percent * 0.5) if sparse_input else extraction_percent,
                                        })
                        output_stream.truncate(int(partition["size_bytes"]))
                        output_stream.flush()
                        os.fsync(output_stream.fileno())
                    _check_cancel(cancel_requested)
                    if _source_signature(source) != signature_before:
                        raise SuperImageError("The source image changed during extraction; staged output was discarded")
                    if force:
                        os.replace(temp_path, output_path)
                    else:
                        # Publish without clobbering a file created after the
                        # initial existence check. The temporary file lives in
                        # the same directory, so the hard-link commit is atomic.
                        try:
                            os.link(temp_path, output_path)
                        except FileExistsError:
                            raise FileExistsError(
                                f"Output file appeared during extraction: {output_path}"
                            ) from None
                        temp_path.unlink()
                except Exception:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
                extracted.append({
                    "partition": partition["name"],
                    "output": str(output_path),
                    "size_bytes": int(partition["size_bytes"]),
                    "extent_count": int(partition["num_extents"]),
                })
                if progress_callback:
                    progress_callback({
                        "stage": "extracting",
                        "partition": partition["name"],
                        "processed_bytes": processed_total,
                        "partition_processed_bytes": partition_processed,
                        "total_bytes": total_bytes,
                        "percent": 50 + int(min(100, processed_total * 100 / max(total_bytes, 1)) * 0.5) if sparse_input else min(100, int(processed_total * 100 / max(total_bytes, 1))),
                    })

    if _source_signature(source) != signature_before:
        raise SuperImageError("The source image changed during extraction")
    return {
        "operation": "super-image-extract",
        "input": str(source),
        "input_format": source_format,
        "output_dir": str(destination),
        "slot": slot,
        "metadata_version": metadata["metadata_version"],
        "extracted": extracted,
        "extracted_count": len(extracted),
        "total_output_bytes": sum(item["size_bytes"] for item in extracted),
    }


def _write_json_report(path: Path, payload: dict[str, Any], force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"JSON report already exists: {path} (use --force to overwrite)")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"JSON report directory not found: {path.parent}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temp_path, path)
        else:
            try:
                os.link(temp_path, path)
            except FileExistsError:
                raise FileExistsError(f"JSON report appeared while it was being written: {path}") from None
            temp_path.unlink()
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def run_super_cli(command_name: str, arguments: list[str]) -> int:
    """CLI entry point for `super-info` and `super-extract` subcommands."""
    from cli_i18n import tr

    parser = argparse.ArgumentParser(
        prog=f"sparse-to-raw {command_name}",
        description=tr("super_info_desc" if command_name == "super-info" else "super_extract_desc"),
    )
    parser.add_argument("input_super", help=tr("super_input"))
    parser.add_argument("--slot", type=int, default=0, help=tr("super_slot"))
    parser.add_argument("--json-report", metavar="FILE", help=tr("super_json"))
    parser.add_argument("--force", action="store_true", help=tr("super_force"))
    if command_name == "super-extract":
        parser.add_argument("--output-dir", required=True, help=tr("super_output_dir"))
        parser.add_argument("--partition", action="append", dest="partitions", help=tr("super_partition"))
    parser.add_argument("--quiet", action="store_true", help=tr("super_quiet"))
    opts = parser.parse_args(arguments)
    try:
        report_path = Path(opts.json_report).expanduser().resolve() if opts.json_report else None
        input_path = Path(opts.input_super).expanduser().resolve()
        if report_path and report_path == input_path:
            parser.error("JSON report path must differ from the input image")
        if report_path and not report_path.parent.is_dir():
            parser.error(f"JSON report directory not found: {report_path.parent}")
        if report_path and report_path.is_dir():
            parser.error(f"JSON report path is a directory: {report_path}")
        if report_path and report_path.exists() and not opts.force:
            parser.error(f"JSON report already exists: {report_path} (use --force to overwrite)")

        progress_was_printed = False
        def progress(data: dict[str, Any]) -> None:
            nonlocal progress_was_printed
            if opts.quiet:
                return
            stage = data.get("stage")
            if stage not in ("preparing", "extracting"):
                return
            progress_was_printed = True
            label = tr("super_prepare_progress") if stage == "preparing" else tr("super_extract_progress")
            suffix = "" if stage == "preparing" else f" {data.get('partition', '')}"
            details = ""
            if data.get("total_bytes"):
                details = f" ({data.get('processed_bytes', 0):,}/{data.get('total_bytes', 0):,} bytes)"
            print(
                f"\r{label}{suffix}: {data.get('percent', 0):3d}%{details}",
                end="", file=sys.stderr, flush=True,
            )
        if command_name == "super-info":
            result = inspect_super_image(input_path, slot=opts.slot, progress_callback=progress)
        else:
            result = extract_super_partitions(
                input_path, opts.output_dir, opts.partitions, slot=opts.slot,
                force=opts.force, reserved_output_paths=[report_path] if report_path else None,
                progress_callback=progress,
            )
        if progress_was_printed:
            print(file=sys.stderr)
        payload = json.dumps(result, ensure_ascii=False, indent=2)
        print(payload)
        if report_path:
            _write_json_report(report_path, result, opts.force)
        return 0
    except (OSError, ValueError, SuperImageCancelled) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "SuperImageError", "SuperImageCancelled", "inspect_super_image",
    "extract_super_partitions", "run_super_cli",
]
