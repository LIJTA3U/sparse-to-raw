#!/usr/bin/env python3
"""Dependency-free Qualcomm QFIL rawprogram/patch XML inspection and RAW assembly.

The module intentionally treats patch XML files as instructions to inspect, not as
writes to replay. A patch can be programmer-, target- and build-specific; applying it
without the matching device metadata would make a reconstructed image misleading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from typing import Any, BinaryIO, Iterable

from cli_i18n import tr, localize_error

from sparse_to_raw import (
    SparseImageError,
    _format_size,
    _read_declared_raw_size,
    write_sparse_to_stream,
)

COPY_BUFFER_SIZE = 1024 * 1024
MAX_XML_BYTES = 32 * 1024 * 1024
_DISK_EXPR_RE = re.compile(r"^\(?\s*NUM_DISK_SECTORS\s*\)?\s*([+-])\s*(\d+)\s*\.?$", re.I)


class QFILManifestError(ValueError):
    """Raised when a QFIL manifest is malformed, incomplete or unsafe to assemble."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_int(value: str | None, field: str, *, default: int | None = None) -> int:
    if value is None or value.strip() == "":
        if default is not None:
            return default
        raise QFILManifestError(f"Missing required XML attribute: {field}")
    raw = value.strip().replace("_", "")
    try:
        if raw.lower().startswith("0x"):
            return int(raw, 16)
        return int(raw, 10)
    except ValueError as exc:
        raise QFILManifestError(f"Invalid integer for {field}: {value!r}") from exc


def _parse_start_sector(value: str | None) -> dict[str, Any]:
    if value is None or value.strip() == "":
        raise QFILManifestError("Missing required XML attribute: start_sector")
    raw = value.strip()
    try:
        number = _parse_int(raw, "start_sector")
        if number < 0:
            raise QFILManifestError(
                f"Negative start_sector {raw!r} is ambiguous; use NUM_DISK_SECTORS-N"
            )
        return {"value": raw, "absolute": number, "end_relative": None}
    except QFILManifestError as numeric_error:
        match = _DISK_EXPR_RE.fullmatch(raw)
        if not match:
            raise numeric_error
        distance = int(match.group(2))
        relative = -distance if match.group(1) == "-" else distance
        return {"value": raw, "absolute": None, "end_relative": relative}


def _resolve_start_sector(start: dict[str, Any], disk_sectors: int | None) -> int | None:
    if start["absolute"] is not None:
        return int(start["absolute"])
    if disk_sectors is None:
        return None
    resolved = disk_sectors + int(start["end_relative"])
    if resolved < 0:
        raise QFILManifestError(
            f"start_sector {start['value']!r} resolves before sector 0 for disk size {disk_sectors}"
        )
    return resolved


def _load_xml(path: Path) -> ET.Element:
    source = path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"QFIL XML file not found: {source}")
    size = source.stat().st_size
    if size > MAX_XML_BYTES:
        raise QFILManifestError(
            f"XML manifest is too large ({_format_size(size)}; limit {_format_size(MAX_XML_BYTES)}): {source}"
        )
    data = source.read_bytes()
    # XML permits UTF-16/UTF-32 encodings; remove NUL bytes as well so a DTD
    # declaration cannot bypass this guard by interleaving zero bytes.
    upper = data.upper().replace(b"\x00", b"")
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise QFILManifestError(f"DTD/entity declarations are not allowed in QFIL XML: {source}")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise QFILManifestError(f"Invalid XML in {source}: {exc}") from exc
    if _local_name(root.tag) != "data":
        raise QFILManifestError(
            f"Unexpected root element <{_local_name(root.tag)}> in {source}; expected <data>"
        )
    return root


def _attrs(element: ET.Element) -> dict[str, str]:
    return {str(k): str(v) for k, v in element.attrib.items()}


def _attr(attrs: dict[str, str], name: str, default: str | None = None) -> str | None:
    # QFIL manifests conventionally use uppercase sector-size attribute names.
    if name in attrs:
        return attrs[name]
    lower = name.lower()
    for key, value in attrs.items():
        if key.lower() == lower:
            return value
    return default


def _parse_rawprogram(path: Path) -> list[dict[str, Any]]:
    root = _load_xml(path)
    root_attrs = _attrs(root)
    entries: list[dict[str, Any]] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag not in {"program", "erase"}:
            continue
        attrs = _attrs(element)
        sector_size = _parse_int(
            _attr(attrs, "SECTOR_SIZE_IN_BYTES") or _attr(root_attrs, "SECTOR_SIZE_IN_BYTES"),
            "SECTOR_SIZE_IN_BYTES",
            default=512,
        )
        if sector_size <= 0 or sector_size > 1024 * 1024:
            raise QFILManifestError(
                f"Invalid SECTOR_SIZE_IN_BYTES={sector_size} in {path}; expected 1..1048576"
            )
        start = _parse_start_sector(_attr(attrs, "start_sector"))
        sectors_value = _attr(attrs, "num_partition_sectors")
        if sectors_value is None or sectors_value.strip() == "":
            size_kb = _attr(attrs, "size_in_KB")
            if size_kb is not None:
                bytes_value = _parse_int(size_kb, "size_in_KB") * 1024
                if bytes_value % sector_size:
                    raise QFILManifestError(
                        f"size_in_KB in {path} is not aligned to {sector_size}-byte sectors"
                    )
                sectors = bytes_value // sector_size
            else:
                sectors = 0
        else:
            sectors = _parse_int(sectors_value, "num_partition_sectors")
        if sectors < 0:
            raise QFILManifestError(f"num_partition_sectors cannot be negative in {path}")
        lun = _parse_int(
            _attr(attrs, "physical_partition_number"),
            "physical_partition_number",
            default=0,
        )
        if lun < 0:
            raise QFILManifestError(f"physical_partition_number cannot be negative in {path}")
        file_offset = _parse_int(
            _attr(attrs, "file_sector_offset"), "file_sector_offset", default=0
        )
        if file_offset < 0:
            raise QFILManifestError(f"file_sector_offset cannot be negative in {path}")
        filename = (_attr(attrs, "filename") or "").strip()
        sparse_value = (_attr(attrs, "sparse") or "false").strip().lower()
        sparse = sparse_value in {"true", "1", "yes", "on"}
        label = (_attr(attrs, "label") or "").strip()
        if not label:
            label = Path(filename.replace("\\", "/")).stem if filename else f"entry_{len(entries)}"
        entries.append({
            "manifest": str(path.expanduser().resolve()),
            "index": len(entries),
            "action": tag,
            "filename": filename,
            "label": label,
            "start": start,
            "num_partition_sectors": sectors,
            "file_sector_offset": file_offset,
            "sector_size_bytes": sector_size,
            "physical_partition_number": lun,
            "sparse": sparse,
            "attributes": attrs,
            "source": None,
            "source_status": "erase" if tag == "erase" else ("no_filename" if not filename else "not_searched"),
            "source_size_bytes": None,
        })
    if not entries:
        raise QFILManifestError(f"No <program> or <erase> operations found in {path}")
    return entries


def _parse_patch(path: Path) -> list[dict[str, Any]]:
    root = _load_xml(path)
    patches = []
    for element in root.iter():
        if _local_name(element.tag) != "patch":
            continue
        attrs = _attrs(element)
        patch = {"manifest": str(path.expanduser().resolve()), "index": len(patches), "attributes": attrs}
        for key in ("physical_partition_number", "start_sector", "byte_offset", "size_in_bytes", "value", "filename", "what", "SECTOR_SIZE_IN_BYTES"):
            value = _attr(attrs, key)
            if value is not None:
                patch[key] = value
        if "physical_partition_number" in patch:
            patch["physical_partition_number"] = _parse_int(
                patch["physical_partition_number"], "patch physical_partition_number"
            )
        if "size_in_bytes" in patch:
            patch["size_in_bytes"] = _parse_int(patch["size_in_bytes"], "patch size_in_bytes")
            if patch["size_in_bytes"] <= 0:
                raise QFILManifestError(f"Patch size_in_bytes must be positive in {path}")
        patches.append(patch)
    if not patches:
        raise QFILManifestError(f"No <patch> operations found in {path}")
    return patches


def _build_file_index(roots: Iterable[Path]) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = defaultdict(list)
    visited: set[Path] = set()
    for root in roots:
        root = root.expanduser().resolve()
        if not root.is_dir() or root in visited:
            continue
        visited.add(root)
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name not in {".git", "__pycache__", ".svn"}]
            for name in files:
                try:
                    path = Path(current, name).resolve()
                    if path.is_file():
                        index[name.casefold()].append(path)
                except OSError:
                    continue
    return index


def _resolve_source(
    filename: str,
    manifest_path: Path,
    search_index: dict[str, list[Path]],
) -> tuple[Path | None, str, list[str]]:
    raw = filename.replace("\\", os.sep)
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        direct_candidates = [candidate]
    else:
        direct_candidates = [manifest_path.parent / candidate]
    for direct in direct_candidates:
        try:
            resolved = direct.resolve()
            if resolved.is_file():
                return resolved, "found", [str(resolved)]
        except OSError:
            pass
    matches = list(dict.fromkeys(search_index.get(Path(raw).name.casefold(), [])))
    if len(matches) == 1:
        return matches[0], "found_by_search", [str(matches[0])]
    if len(matches) > 1:
        return None, "ambiguous", [str(path) for path in matches]
    return None, "missing", []


def _resolve_program_sources(
    programs: list[dict[str, Any]], search_dirs: Iterable[str | Path] | None
) -> None:
    roots = [Path(item) for item in (search_dirs or [])]
    roots.extend(Path(item["manifest"]).parent for item in programs)
    search_index = _build_file_index(roots)
    for item in programs:
        if item["action"] == "erase" or not item["filename"]:
            continue
        manifest = Path(item["manifest"])
        source, status, candidates = _resolve_source(item["filename"], manifest, search_index)
        item["source"] = str(source) if source else None
        item["source_status"] = status
        item["source_candidates"] = candidates
        if source is not None:
            try:
                item["source_size_bytes"] = source.stat().st_size
            except OSError:
                item["source"] = None
                item["source_status"] = "missing"


def _validate_overlaps(programs: list[dict[str, Any]], disk_sectors: dict[int, int]) -> list[str]:
    warnings: list[str] = []
    grouped: dict[int, list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
    for item in programs:
        if not item["num_partition_sectors"]:
            continue
        lun = item["physical_partition_number"]
        disk_size = disk_sectors.get(lun)
        start = _resolve_start_sector(item["start"], disk_size)
        if start is None:
            continue
        end = start + item["num_partition_sectors"]
        grouped[lun].append((start, end, item))
    for lun, windows in grouped.items():
        windows.sort(key=lambda row: (row[0], row[1]))
        furthest_end = -1
        furthest_item: dict[str, Any] | None = None
        for start, end, item in windows:
            if start < furthest_end and furthest_item is not None:
                warnings.append(
                    f"LUN {lun}: overlapping writes {furthest_item['label']!r} and {item['label']!r} "
                    f"near sector {start:,}"
                )
            if end > furthest_end:
                furthest_end, furthest_item = end, item
    return warnings


def _disk_size_map(values: dict[int, int] | None) -> dict[int, int]:
    result = dict(values or {})
    for lun, sectors in result.items():
        if lun < 0 or sectors <= 0:
            raise QFILManifestError("Disk sizes must be positive sector counts keyed by non-negative LUNs")
    return result


def analyze_qfil_package(
    rawprogram_files: Iterable[str | Path],
    patch_files: Iterable[str | Path] | None = None,
    *,
    search_dirs: Iterable[str | Path] | None = None,
    disk_sectors: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Parse rawprogram/patch XML, resolve image files and summarize partition writes."""
    raw_paths = [Path(item).expanduser().resolve() for item in rawprogram_files]
    patch_paths = [Path(item).expanduser().resolve() for item in (patch_files or [])]
    if not raw_paths:
        raise QFILManifestError("Select at least one rawprogram XML file")
    if len(set(raw_paths)) != len(raw_paths):
        raise QFILManifestError("The same rawprogram XML file was supplied more than once")
    sizes = _disk_size_map(disk_sectors)
    programs: list[dict[str, Any]] = []
    for path in raw_paths:
        programs.extend(_parse_rawprogram(path))
    patches: list[dict[str, Any]] = []
    for path in patch_paths:
        patches.extend(_parse_patch(path))
    _resolve_program_sources(programs, search_dirs)

    warnings = _validate_overlaps(programs, sizes)
    for item in programs:
        if item["source_status"] in {"missing", "ambiguous"}:
            details = "" if not item.get("source_candidates") else ": " + "; ".join(item["source_candidates"])
            warnings.append(
                f"{item['manifest']} · {item['label']}: source file {item['filename']!r} "
                f"{item['source_status']}{details}"
            )
        if item["start"]["absolute"] is None and item["physical_partition_number"] not in sizes:
            warnings.append(
                f"{item['manifest']} · {item['label']}: {item['start']['value']!r} needs "
                f"--disk-sectors {item['physical_partition_number']}=COUNT for RAW assembly"
            )

    partitions: list[dict[str, Any]] = []
    by_partition: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    for item in programs:
        by_partition[(item["physical_partition_number"], item["label"])].append(item)
    for (lun, label), items in sorted(by_partition.items()):
        sector_sizes = sorted({item["sector_size_bytes"] for item in items})
        starts = [
            _resolve_start_sector(item["start"], sizes.get(lun))
            for item in items
        ]
        known_starts = [value for value in starts if value is not None]
        ends = [
            start + item["num_partition_sectors"]
            for item, start in zip(items, starts)
            if start is not None and item["num_partition_sectors"]
        ]
        partitions.append({
            "label": label,
            "physical_partition_number": lun,
            "operation_count": len(items),
            "sector_size_bytes": sector_sizes[0] if len(sector_sizes) == 1 else None,
            "sector_sizes_bytes": sector_sizes,
            "start_sector": min(known_starts) if known_starts else None,
            "end_sector_exclusive": max(ends) if ends else None,
            "source_files": sorted({item["filename"] for item in items if item["filename"]}),
            "source_statuses": sorted({item["source_status"] for item in items}),
        })

    summary = {
        "rawprogram_count": len(raw_paths),
        "patch_count": len(patch_paths),
        "program_operations": sum(item["action"] == "program" for item in programs),
        "erase_operations": sum(item["action"] == "erase" for item in programs),
        "patch_operations": len(patches),
        "resolved_files": sum(item["source_status"] in {"found", "found_by_search"} for item in programs),
        "missing_files": sum(item["source_status"] == "missing" for item in programs),
        "ambiguous_files": sum(item["source_status"] == "ambiguous" for item in programs),
        "partition_count": len(partitions),
        "physical_partitions": sorted({item["physical_partition_number"] for item in programs}),
    }
    # XML nodes and patch operations are not instructions to replay blindly.
    return {
        "format": "Qualcomm QFIL XML",
        "rawprogram_files": [str(path) for path in raw_paths],
        "patch_files": [str(path) for path in patch_paths],
        "patches_applied": False,
        "patches_note": (
            "Patch XML operations are reported but not applied. Their effects depend on "
            "the matching Firehose programmer and target storage layout."
        ),
        "summary": summary,
        "partitions": partitions,
        "programs": programs,
        "patches": patches,
        "warnings": warnings,
    }


def _program_range(item: dict[str, Any], disk_sizes: dict[int, int]) -> tuple[int, int, int]:
    lun = item["physical_partition_number"]
    sector_size = item["sector_size_bytes"]
    start = _resolve_start_sector(item["start"], disk_sizes.get(lun))
    if start is None:
        raise QFILManifestError(
            f"Cannot resolve {item['start']['value']!r} for LUN {lun}; provide --disk-sectors {lun}=COUNT"
        )
    return start, item["num_partition_sectors"], sector_size


def _copy_exact(source: Path, destination: BinaryIO, source_offset: int, target_offset: int, count: int) -> None:
    if source_offset < 0 or target_offset < 0 or count < 0:
        raise QFILManifestError("File offsets and copy lengths must be non-negative")
    source_size = source.stat().st_size
    if source_offset + count > source_size:
        raise QFILManifestError(
            f"Source file is too small: {source} has {_format_size(source_size)}, "
            f"but { _format_size(source_offset + count) } bytes are required"
        )
    destination.seek(target_offset)
    copied = 0
    with source.open("rb") as stream:
        stream.seek(source_offset)
        while copied < count:
            data = stream.read(min(COPY_BUFFER_SIZE, count - copied))
            if not data:
                raise QFILManifestError(f"Unexpected end of file while reading {source}")
            destination.write(data)
            copied += len(data)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            data = stream.read(COPY_BUFFER_SIZE)
            if not data:
                break
            digest.update(data)
    return digest.hexdigest()


def build_qfil_raw_images(
    rawprogram_files: Iterable[str | Path],
    output_dir: str | Path,
    patch_files: Iterable[str | Path] | None = None,
    *,
    search_dirs: Iterable[str | Path] | None = None,
    disk_sectors: dict[int, int] | None = None,
    force: bool = False,
    allow_overlaps: bool = False,
) -> dict[str, Any]:
    """Build one zero-initialized RAW image for each physical partition/LUN.

    Files are assembled into temporary output files first. They are published only
    after every program source has been found and every Sparse input has validated.
    DONT_CARE areas and explicitly erased ranges are left zero-filled.
    """
    output_root = Path(output_dir).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    if not output_root.is_dir():
        raise NotADirectoryError(f"Output path is not a directory: {output_root}")
    disk_sizes = _disk_size_map(disk_sectors)
    analysis = analyze_qfil_package(
        rawprogram_files,
        patch_files,
        search_dirs=search_dirs,
        disk_sectors=disk_sizes,
    )
    overlaps = [item for item in analysis["warnings"] if "overlapping writes" in item]
    if overlaps and not allow_overlaps:
        raise QFILManifestError(
            "Overlapping program operations were detected. Review the manifest; "
            "use --allow-overlap only when the overlap is intentional.\n- " + "\n- ".join(overlaps)
        )
    unresolved = [
        item for item in analysis["programs"]
        if item["action"] == "program" and item["filename"]
        and item["source_status"] not in {"found", "found_by_search"}
    ]
    if unresolved:
        raise QFILManifestError(
            "Some input files could not be resolved. Use --search-dir to select the firmware folder:\n- "
            + "\n- ".join(
                f"{item['filename']} ({item['source_status']}) in {item['manifest']}"
                for item in unresolved
            )
        )
    unnamed = [
        item for item in analysis["programs"]
        if item["action"] == "program" and not item["filename"] and item["num_partition_sectors"]
    ]
    if unnamed:
        raise QFILManifestError(
            "A <program> operation has no filename; the source data is unknown. "
            "Do not build an incomplete image from this manifest."
        )

    rawprogram_paths = [Path(item) for item in analysis["rawprogram_files"]]
    parsed_programs: list[dict[str, Any]] = []
    for path in rawprogram_paths:
        parsed_programs.extend(_parse_rawprogram(path))
    # Keep the already-resolved paths and source status from analysis.
    resolved_lookup = {
        (item["manifest"], item["index"]): item
        for item in analysis["programs"]
    }
    for item in parsed_programs:
        resolved = resolved_lookup[(item["manifest"], item["index"])]
        item["source"] = resolved.get("source")
        item["source_status"] = resolved.get("source_status")
        item["source_size_bytes"] = resolved.get("source_size_bytes")

    by_lun: dict[int, list[dict[str, Any]]] = defaultdict(list)
    effective_windows: dict[int, list[tuple[int, int, dict[str, Any]]]] = defaultdict(list)
    ends_by_lun: dict[int, int] = defaultdict(int)
    output_sector_size: dict[int, int] = {}
    for item in parsed_programs:
        lun = item["physical_partition_number"]
        start, sectors, sector_size = _program_range(item, disk_sizes)
        if lun in output_sector_size and output_sector_size[lun] != sector_size:
            raise QFILManifestError(
                f"LUN {lun} uses mixed sector sizes ({output_sector_size[lun]} and {sector_size} bytes). "
                "A single RAW image cannot represent both coordinate systems."
            )
        output_sector_size[lun] = sector_size
        source = Path(item["source"]) if item.get("source") else None
        if item["action"] == "program":
            if source is None:
                if sectors == 0:
                    continue
                raise QFILManifestError(
                    f"No source file for program operation {item['label']!r} in {item['manifest']}"
                )
            source_offset = item["file_sector_offset"] * sector_size
            if item["sparse"]:
                if item["file_sector_offset"] != 0:
                    raise QFILManifestError(
                        f"Sparse source {source.name} uses file_sector_offset={item['file_sector_offset']}; "
                        "non-zero offsets in compressed Sparse files are not supported"
                    )
                expanded_size = _read_declared_raw_size(source)
                if expanded_size % sector_size:
                    raise QFILManifestError(
                        f"Expanded Sparse size for {source.name} is not aligned to {sector_size}-byte sectors"
                    )
                required_sectors = expanded_size // sector_size
                target_sectors = sectors or required_sectors
                if required_sectors > target_sectors:
                    raise QFILManifestError(
                        f"Sparse file {source.name} expands to {required_sectors:,} sectors, "
                        f"but the manifest allows {target_sectors:,}"
                    )
            else:
                source_size = source.stat().st_size
                if source_offset > source_size:
                    raise QFILManifestError(
                        f"file_sector_offset is beyond the end of {source}: {source_offset} bytes"
                    )
                remaining = source_size - source_offset
                if sectors:
                    target_sectors = sectors
                    required_bytes = target_sectors * sector_size
                    if remaining < required_bytes:
                        raise QFILManifestError(
                            f"Source file {source.name} is shorter than the manifest range: "
                            f"need {_format_size(required_bytes)}, have {_format_size(remaining)}"
                        )
                else:
                    if remaining % sector_size:
                        raise QFILManifestError(
                            f"Source size after file_sector_offset is not aligned to {sector_size}-byte sectors: {source}"
                        )
                    target_sectors = remaining // sector_size
            item["resolved_start_sector"] = start
            item["resolved_sector_count"] = target_sectors
            item["expanded_source_bytes"] = (
                _read_declared_raw_size(source) if item["sparse"] else target_sectors * sector_size
            )
        else:
            if sectors <= 0:
                raise QFILManifestError(
                    f"Erase operation {item['label']!r} has no positive num_partition_sectors"
                )
            target_sectors = sectors
            item["resolved_start_sector"] = start
            item["resolved_sector_count"] = target_sectors
        by_lun[lun].append(item)
        effective_windows[lun].append((start, start + target_sectors, item))
        ends_by_lun[lun] = max(ends_by_lun[lun], start + target_sectors)

    # Recheck ranges after resolving count=0 entries from actual source-file lengths.
    if not allow_overlaps:
        effective_overlaps: list[str] = []
        for lun, windows in effective_windows.items():
            ordered = sorted(windows, key=lambda row: (row[0], row[1]))
            furthest_end = -1
            furthest_item: dict[str, Any] | None = None
            for start, end, item in ordered:
                if start < furthest_end and furthest_item is not None:
                    effective_overlaps.append(
                        f"LUN {lun}: overlapping writes {furthest_item['label']!r} and {item['label']!r} "
                        f"near sector {start:,}"
                    )
                if end > furthest_end:
                    furthest_end, furthest_item = end, item
        if effective_overlaps:
            raise QFILManifestError(
                "Overlapping program operations were detected after resolving source sizes. "
                "Use --allow-overlap only when intentional:\n- " + "\n- ".join(effective_overlaps)
            )

    for lun, requested_size in disk_sizes.items():
        if lun in by_lun:
            if requested_size < ends_by_lun[lun]:
                raise QFILManifestError(
                    f"--disk-sectors {lun}={requested_size} is smaller than the required end sector {ends_by_lun[lun]}"
                )
            ends_by_lun[lun] = max(ends_by_lun[lun], requested_size)

    if not by_lun:
        raise QFILManifestError("No RAW output ranges were found in the selected manifests")

    output_specs: list[dict[str, Any]] = []
    total_bytes = 0
    # Protect every input globally, not only files used by the same LUN. A source
    # referenced by LUN 0 could otherwise be overwritten by the LUN 1 output name.
    protected_inputs = {
        Path(value).expanduser().resolve()
        for item in parsed_programs
        for value in (item.get("source"), item.get("manifest"))
        if value
    }
    for lun, items in sorted(by_lun.items()):
        target = output_root / f"physical_partition_{lun}.raw"
        if target.resolve() in protected_inputs:
            raise QFILManifestError(f"Output path would overwrite an input file: {target}")
        if target.exists() and not force:
            raise FileExistsError(f"Output file already exists: {target} (use --force to overwrite)")
        size_bytes = ends_by_lun[lun] * output_sector_size[lun]
        output_specs.append({
            "physical_partition_number": lun,
            "output": str(target),
            "size_bytes": size_bytes,
            "sector_size_bytes": output_sector_size[lun],
            "sector_count": ends_by_lun[lun],
            "program_count": sum(item["action"] == "program" for item in items),
            "erase_count": sum(item["action"] == "erase" for item in items),
            "_items": items,
            "_stage": None,
        })
        total_bytes += size_bytes

    usage = shutil.disk_usage(output_root)
    margin = max(16 * 1024 * 1024, total_bytes // 100)
    required = total_bytes + margin
    if usage.free < required:
        raise OSError(
            f"Not enough free space in {output_root}: {_format_size(usage.free)} available, "
            f"about {_format_size(required)} required (including a safety margin)"
        )

    staged_paths: list[Path] = []
    committed: list[Path] = []
    started = time.monotonic()
    try:
        for spec in output_specs:
            target = Path(spec["output"])
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".tmp", dir=output_root
            )
            stage = Path(temp_name)
            spec["_stage"] = stage
            staged_paths.append(stage)
            with os.fdopen(fd, "w+b") as destination:
                destination.truncate(spec["size_bytes"])
                for item in spec["_items"]:
                    start = item["resolved_start_sector"]
                    offset = start * item["sector_size_bytes"]
                    source = Path(item["source"]) if item.get("source") else None
                    if item["action"] == "erase":
                        # Honour the erase operation in manifest order, including when it overlaps a prior write.
                        destination.seek(offset)
                        remaining = item["resolved_sector_count"] * item["sector_size_bytes"]
                        zero_block = b"\x00" * COPY_BUFFER_SIZE
                        while remaining:
                            amount = min(COPY_BUFFER_SIZE, remaining)
                            destination.write(zero_block[:amount])
                            remaining -= amount
                        continue
                    if source is None:
                        continue
                    if item["sparse"]:
                        result = write_sparse_to_stream(source, destination, offset)
                        expected_size = item["expanded_source_bytes"]
                        if result["raw_size_bytes"] != expected_size:
                            raise QFILManifestError(
                                f"Sparse size changed while processing {source}: "
                                f"expected {expected_size} bytes, got {result['raw_size_bytes']}"
                            )
                    else:
                        count = item["resolved_sector_count"] * item["sector_size_bytes"]
                        source_offset = item["file_sector_offset"] * item["sector_size_bytes"]
                        _copy_exact(source, destination, source_offset, offset, count)
                destination.flush()
                os.fsync(destination.fileno())

        for spec in output_specs:
            target = Path(spec["output"])
            stage = Path(spec["_stage"])
            if force:
                os.replace(stage, target)
            else:
                try:
                    os.link(stage, target)
                except FileExistsError:
                    raise FileExistsError(
                        f"Output file already exists: {target} (use --force to overwrite)"
                    ) from None
                stage.unlink()
            spec["_stage"] = None
            committed.append(target)
            spec["sha256"] = _hash_file(target)
            spec["size_human"] = _format_size(target.stat().st_size)

        elapsed = max(time.monotonic() - started, 0.0)
        for spec in output_specs:
            spec.pop("_items", None)
            spec.pop("_stage", None)
        return {
            "format": "Qualcomm QFIL RAW assembly",
            "outputs": output_specs,
            "output_count": len(output_specs),
            "total_output_bytes": total_bytes,
            "total_output_human": _format_size(total_bytes),
            "duration_seconds": round(elapsed, 6),
            "overlaps_allowed": bool(allow_overlaps),
            "analysis": analysis,
            "patches_applied": False,
        }
    finally:
        for stage in staged_paths:
            try:
                stage.unlink(missing_ok=True)
            except OSError:
                pass


def _parse_disk_sizes(values: list[str] | None) -> dict[int, int]:
    result: dict[int, int] = {}
    for value in values or []:
        if "=" not in value:
            raise QFILManifestError(f"Invalid --disk-sectors value {value!r}; expected LUN=COUNT")
        lun_text, sectors_text = value.split("=", 1)
        lun = _parse_int(lun_text, "disk LUN")
        sectors = _parse_int(sectors_text, "disk sector count")
        if lun in result:
            raise QFILManifestError(f"--disk-sectors was specified more than once for LUN {lun}")
        result[lun] = sectors
    return _disk_size_map(result)


def _write_json_report(path_text: str | None, report: dict[str, Any], force: bool) -> None:
    if not path_text:
        return
    target = Path(path_text).expanduser().resolve()
    if target.exists() and not force:
        raise FileExistsError(f"JSON report already exists: {target} (use --force to overwrite)")
    if not target.parent.is_dir():
        raise FileNotFoundError(f"JSON report directory not found: {target.parent}")
    data = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    stage = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(stage, target)
        else:
            os.link(stage, target)
            stage.unlink()
    finally:
        stage.unlink(missing_ok=True)


def _add_common_cli_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lang", choices=("en", "ru"), default=("ru" if tr("lang") == "язык CLI" else "en"), help=tr("lang"))
    parser.add_argument("rawprogram_xml", nargs="+", metavar="RAWPROGRAM.XML", help=("манифест(ы) rawprogram*.xml" if tr("lang") == "язык CLI" else "rawprogram*.xml manifest(s)"))
    parser.add_argument("--patch-xml", action="append", default=[], metavar="PATCH.XML", help=("манифест patch*.xml (можно повторять; анализируется, но не применяется)" if tr("lang") == "язык CLI" else "patch*.xml manifest (repeatable; reported, not applied)"))
    parser.add_argument("--search-dir", action="append", default=[], metavar="DIR", help=("каталог прошивки для рекурсивного поиска файлов (можно повторять)" if tr("lang") == "язык CLI" else "firmware folder to search recursively for referenced files (repeatable)"))
    parser.add_argument("--disk-sectors", action="append", default=[], metavar="LUN=COUNT", help=("размер диска для выражений NUM_DISK_SECTORS-N, например 0=61071360" if tr("lang") == "язык CLI" else "disk size for NUM_DISK_SECTORS-N expressions, e.g. 0=61071360"))
    parser.add_argument("--json-report", metavar="FILE", help=("сохранить подробный JSON-отчёт UTF-8" if tr("lang") == "язык CLI" else "write a detailed UTF-8 JSON report"))
    parser.add_argument("--force", action="store_true", help=("разрешить замену выходных файлов и отчётов" if tr("lang") == "язык CLI" else "allow replacing output/report files"))


def run_qfil_cli(command: str, argv: list[str] | None = None) -> int:
    """Run a QFIL-specific command; imported lazily by sparse_to_raw.main()."""
    if command == "qfil-analyze":
        parser = argparse.ArgumentParser(
            prog="sparse_to_raw.py qfil-analyze",
            description=("Анализировать манифесты Qualcomm QFIL rawprogram/patch XML и искать файлы образов." if tr("lang") == "язык CLI" else "Analyze Qualcomm QFIL rawprogram/patch XML manifests and locate their image files."),
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        _add_common_cli_options(parser)
    elif command == "qfil-build":
        parser = argparse.ArgumentParser(
            prog="sparse_to_raw.py qfil-build",
            description=("Собирать RAW-образы из QFIL rawprogram-манифестов с заполнением незаданных областей нулями." if tr("lang") == "язык CLI" else "Assemble zero-initialized RAW images from QFIL rawprogram manifests."),
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )
        _add_common_cli_options(parser)
        parser.add_argument("--output-dir", required=True, metavar="DIR", help=("каталог для файлов physical_partition_N.raw" if tr("lang") == "язык CLI" else "folder for physical_partition_N.raw outputs"))
        parser.add_argument("--allow-overlap", action="store_true", help=("разрешить пересечения диапазонов; более поздние XML-записи перезаписывают ранние байты" if tr("lang") == "язык CLI" else "allow overlapping program ranges; later XML entries overwrite earlier bytes"))
    else:
        raise ValueError(f"Unknown QFIL command: {command}")

    args = parser.parse_args(argv)
    try:
        sizes = _parse_disk_sizes(args.disk_sectors)
        if command == "qfil-analyze":
            report = analyze_qfil_package(
                args.rawprogram_xml,
                args.patch_xml,
                search_dirs=args.search_dir,
                disk_sectors=sizes,
            )
            print("\n" + tr("qfil_analysis"))
            print("=" * 72)
            print(f"{tr('rawprograms'):<21}: {report['summary']['rawprogram_count']}")
            print(f"{tr('patches'):<21}: {report['summary']['patch_count']}")
            print(f"{tr('program_ops'):<21}: {report['summary']['program_operations']}")
            print(f"{tr('erase_ops'):<21}: {report['summary']['erase_operations']}")
            print(f"{tr('patch_ops'):<21}: {report['summary']['patch_operations']}")
            print(f"{tr('located'):<21}: {report['summary']['resolved_files']}")
            print(f"{tr('missing'):<21}: {report['summary']['missing_files']}")
            print(f"{tr('partitions'):<21}: {report['summary']['partition_count']}")
            print("\n" + tr("partition_map"))
            for item in report["partitions"]:
                start = "unresolved" if item["start_sector"] is None else f"{item['start_sector']:,}"
                end = "unknown" if item["end_sector_exclusive"] is None else f"{item['end_sector_exclusive']:,}"
                sector = item["sector_size_bytes"] or "mixed"
                print(
                    f"  LUN {item['physical_partition_number']}  {item['label']:<24.24} "
                    f"sectors {start}..{end}  sector={sector}B  files={','.join(item['source_files']) or '—'}"
                )
            print("\n" + tr("file_resolution"))
            for item in report["programs"]:
                if item["action"] == "erase":
                    status = tr("erase_zero")
                elif item["source_status"] in {"found", "found_by_search"}:
                    status = tr("found") if item["source_status"] == "found" else tr("found_search")
                elif item["source_status"] == "no_filename":
                    status = tr("no_name")
                else:
                    status = item["source_status"].upper()
                source_text = item.get("source") or item.get("filename") or "—"
                print(f"  [{status}] LUN {item['physical_partition_number']} · {item['label']}: {source_text}")
            if report["patches"]:
                print("\n" + tr("patch_not_applied"))
                for item in report["patches"]:
                    attrs = item["attributes"]
                    print(
                        f"  LUN {item.get('physical_partition_number', '?')} · "
                        f"sector={attrs.get('start_sector', '?')} · "
                        f"offset={attrs.get('byte_offset', '?')} · "
                        f"value={attrs.get('value', '?')} · "
                        f"{attrs.get('what', '')}"
                    )
            if report["warnings"]:
                print("\n" + tr("warnings"))
                for warning in report["warnings"]:
                    print(f"  ! {warning}")
            print("\n" + tr("patch_note"))
            if report["summary"]["missing_files"] or report["summary"]["ambiguous_files"]:
                print(tr("unresolved"))
            else:
                print(tr("analysis_done"))
        else:
            report = build_qfil_raw_images(
                args.rawprogram_xml,
                args.output_dir,
                args.patch_xml,
                search_dirs=args.search_dir,
                disk_sectors=sizes,
                force=args.force,
                allow_overlaps=args.allow_overlap,
            )
            print("\n" + tr("qfil_assembly"))
            print("=" * 72)
            for item in report["outputs"]:
                print(f"  LUN {item['physical_partition_number']}: {item['output']}")
                print(f"    {tr('size'):<8}: {item['size_human']}")
                print(f"    {tr('programs')} : {item['program_count']} · {tr('erases')}: {item['erase_count']}")
                print(f"    {tr('sha256'):<8}: {item['sha256']}")
            print(f"\n{tr('total_output')}: {report['total_output_human']} ({report['output_count']} RAW)")
            print(tr("assembly_done"))

        if args.json_report:
            report_target = Path(args.json_report).expanduser().resolve()
            protected = [Path(item).expanduser().resolve() for item in args.rawprogram_xml + args.patch_xml]
            protected.extend(Path(item["source"]).expanduser().resolve() for item in report.get("programs", []) if item.get("source"))
            protected.extend(Path(item["output"]).expanduser().resolve() for item in report.get("outputs", []))
            if report_target in protected:
                raise QFILManifestError("JSON report path must not overwrite a manifest, source image or RAW output")
        _write_json_report(args.json_report, report, args.force)
        if args.json_report:
            print(f"{tr('json_saved')}: {Path(args.json_report).expanduser().resolve()}")
        return 0
    except (OSError, ValueError, ET.ParseError, SparseImageError) as exc:
        print(f"\n{tr('error')}: {localize_error(str(exc))}", file=sys.stderr)
        return 2
