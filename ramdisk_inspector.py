#!/usr/bin/env python3
"""Read-only Android ramdisk inspector and safe CPIO extractor.

The module uses only the Python standard library. It can inspect ramdisk
sections inside boot/vendor_boot images or standalone compressed CPIO files.
It never modifies the source image.
"""
from __future__ import annotations

import argparse
import bz2
import gzip
import hashlib
import io
import json
import lzma
import os
import shutil
import stat
import struct
import sys
import tempfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Callable

from boot_inspector import BOOT_MAGIC, VENDOR_BOOT_MAGIC, inspect_boot_image
from cli_i18n import tr

CPIO_NEWC = b"070701"
CPIO_CRC = b"070702"
CPIO_HEADER_SIZE = 110
CPIO_TRAILER = "TRAILER!!!"
COPY_BUFFER_SIZE = 1024 * 1024
MAX_UNPACKED_BYTES = 512 * 1024 * 1024
MAX_CPIO_ENTRIES = 200_000
MAX_CPIO_NAME_BYTES = 16 * 1024
MAX_LZ4_BLOCK_BYTES = 4 * 1024 * 1024


class RamdiskError(ValueError):
    """Raised when a ramdisk or CPIO archive is malformed or unsupported."""


class RamdiskCancelled(RamdiskError):
    """Raised when a Ramdisk operation is cancelled by the caller."""


class LimitedReader:
    """Restrict a file-like object to a declared byte range."""

    def __init__(self, stream: BinaryIO, length: int) -> None:
        self.stream = stream
        self.remaining = length

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        if size is None or size < 0 or size > self.remaining:
            size = self.remaining
        data = self.stream.read(size)
        self.remaining -= len(data)
        return data

    def readinto(self, buffer: bytearray | memoryview) -> int:
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)

    def readable(self) -> bool:
        return True


class XXHash32:
    """Small incremental xxHash32 implementation used for LZ4 frame checksums."""

    P1 = 2654435761
    P2 = 2246822519
    P3 = 3266489917
    P4 = 668265263
    P5 = 374761393
    MASK = 0xFFFFFFFF

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed & self.MASK
        self.total = 0
        self.buffer = bytearray()
        self.v1 = (self.seed + self.P1 + self.P2) & self.MASK
        self.v2 = (self.seed + self.P2) & self.MASK
        self.v3 = self.seed
        self.v4 = (self.seed - self.P1) & self.MASK

    @classmethod
    def _rotl(cls, value: int, count: int) -> int:
        return ((value << count) | (value >> (32 - count))) & cls.MASK

    @classmethod
    def _round(cls, accumulator: int, lane: int) -> int:
        accumulator = (accumulator + lane * cls.P2) & cls.MASK
        accumulator = cls._rotl(accumulator, 13)
        return (accumulator * cls.P1) & cls.MASK

    def _stripe(self, data: bytes) -> None:
        self.v1 = self._round(self.v1, int.from_bytes(data[0:4], "little"))
        self.v2 = self._round(self.v2, int.from_bytes(data[4:8], "little"))
        self.v3 = self._round(self.v3, int.from_bytes(data[8:12], "little"))
        self.v4 = self._round(self.v4, int.from_bytes(data[12:16], "little"))

    def update(self, data: bytes) -> None:
        if not data:
            return
        self.total += len(data)
        if self.buffer:
            needed = 16 - len(self.buffer)
            self.buffer.extend(data[:needed])
            data = data[needed:]
            if len(self.buffer) == 16:
                self._stripe(bytes(self.buffer))
                self.buffer.clear()
        end = len(data) - (len(data) % 16)
        for offset in range(0, end, 16):
            self._stripe(data[offset:offset + 16])
        if end < len(data):
            self.buffer.extend(data[end:])

    def digest_int(self) -> int:
        if self.total >= 16:
            value = (self._rotl(self.v1, 1) + self._rotl(self.v2, 7)
                     + self._rotl(self.v3, 12) + self._rotl(self.v4, 18)) & self.MASK
        else:
            value = (self.seed + self.P5) & self.MASK
        value = (value + self.total) & self.MASK
        data = bytes(self.buffer)
        offset = 0
        while offset + 4 <= len(data):
            lane = int.from_bytes(data[offset:offset + 4], "little")
            value = (value + lane * self.P3) & self.MASK
            value = (self._rotl(value, 17) * self.P4) & self.MASK
            offset += 4
        while offset < len(data):
            value = (value + data[offset] * self.P5) & self.MASK
            value = (self._rotl(value, 11) * self.P1) & self.MASK
            offset += 1
        value ^= value >> 15
        value = (value * self.P2) & self.MASK
        value ^= value >> 13
        value = (value * self.P3) & self.MASK
        value ^= value >> 16
        return value & self.MASK


def _xxhash32(data: bytes, seed: int = 0) -> int:
    hasher = XXHash32(seed)
    hasher.update(data)
    return hasher.digest_int()


def _detect_format(prefix: bytes) -> str:
    if prefix.startswith(CPIO_NEWC):
        return "CPIO newc"
    if prefix.startswith(CPIO_CRC):
        return "CPIO crc"
    if prefix.startswith(b"\x1f\x8b"):
        return "gzip"
    if prefix.startswith(b"BZh") and len(prefix) >= 4 and prefix[3:4] in b"123456789":
        return "bzip2"
    if prefix.startswith(b"\xfd7zXZ\x00"):
        return "XZ"
    if prefix.startswith(b"\x5d\x00\x00"):
        return "LZMA-alone"
    if prefix.startswith(b"\x04\x22\x4d\x18"):
        return "LZ4 frame"
    if prefix.startswith(b"\x02\x21\x4c\x18"):
        return "LZ4 legacy frame"
    if prefix.startswith(b"\x28\xb5\x2f\xfd"):
        return "Zstandard"
    if prefix.startswith(b"\x89LZO\x00\r\n\x1a\n"):
        return "LZO (lzop)"
    return "unknown"


def _copy_limited(source: BinaryIO, destination: BinaryIO, limit: int,
                  cancel_requested: Callable[[], bool] | None = None) -> int:
    total = 0
    while True:
        if cancel_requested is not None and cancel_requested():
            raise RamdiskCancelled("Ramdisk operation cancelled")
        chunk = source.read(COPY_BUFFER_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise RamdiskError(f"Decompressed ramdisk exceeds the safety limit ({limit:,} bytes)")
        destination.write(chunk)
    return total


def _decompress_lz4_block(data: bytes, history: bytes, limit: int) -> bytes:
    output = bytearray()
    cursor = 0
    while cursor < len(data):
        token = data[cursor]
        cursor += 1
        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if cursor >= len(data):
                    raise RamdiskError("Truncated LZ4 literal length")
                value = data[cursor]
                cursor += 1
                literal_length += value
                if value != 255:
                    break
        if literal_length > len(data) - cursor:
            raise RamdiskError("LZ4 literal extends beyond its block")
        output.extend(data[cursor:cursor + literal_length])
        cursor += literal_length
        if len(output) > limit:
            raise RamdiskError("LZ4 output exceeds the safety limit")
        if cursor == len(data):
            break
        if cursor + 2 > len(data):
            raise RamdiskError("Truncated LZ4 match offset")
        match_offset = int.from_bytes(data[cursor:cursor + 2], "little")
        cursor += 2
        combined_length = len(history) + len(output)
        if match_offset == 0 or match_offset > combined_length:
            raise RamdiskError("Invalid LZ4 match offset")
        match_length = token & 0x0F
        if match_length == 15:
            while True:
                if cursor >= len(data):
                    raise RamdiskError("Truncated LZ4 match length")
                value = data[cursor]
                cursor += 1
                match_length += value
                if value != 255:
                    break
        match_length += 4
        if len(output) + match_length > limit:
            raise RamdiskError("LZ4 output exceeds the safety limit")
        for _ in range(match_length):
            absolute = len(history) + len(output) - match_offset
            if absolute < len(history):
                byte = history[absolute]
            else:
                byte = output[absolute - len(history)]
            output.append(byte)
    return bytes(output)


def _decompress_lz4_frame(source: BinaryIO, destination: BinaryIO, limit: int, *,
                          legacy: bool = False, cancel_requested: Callable[[], bool] | None = None) -> int:
    magic = source.read(4)
    expected_magic = b"\x02\x21\x4c\x18" if legacy else b"\x04\x22\x4d\x18"
    if magic != expected_magic:
        raise RamdiskError("Invalid LZ4 frame magic")
    total = 0
    history = b""
    content_hash = XXHash32()

    if legacy:
        while True:
            if cancel_requested is not None and cancel_requested():
                raise RamdiskCancelled("Ramdisk operation cancelled")
            raw_size = source.read(4)
            if len(raw_size) != 4:
                raise RamdiskError("Truncated LZ4 legacy block header")
            block_word = int.from_bytes(raw_size, "little")
            if block_word == 0:
                break
            uncompressed = bool(block_word & 0x80000000)
            block_size = block_word & 0x7FFFFFFF
            if block_size == 0 or block_size > MAX_LZ4_BLOCK_BYTES:
                raise RamdiskError("Invalid LZ4 legacy block size")
            block = source.read(block_size)
            if len(block) != block_size:
                raise RamdiskError("Truncated LZ4 legacy block")
            decoded = block if uncompressed else _decompress_lz4_block(block, history, limit - total)
            total += len(decoded)
            if total > limit:
                raise RamdiskError("LZ4 output exceeds the safety limit")
            destination.write(decoded)
            content_hash.update(decoded)
            history = (history + decoded)[-65536:]
        return total

    descriptor = bytearray()
    flg_raw = source.read(1)
    bd_raw = source.read(1)
    if len(flg_raw) != 1 or len(bd_raw) != 1:
        raise RamdiskError("Truncated LZ4 frame descriptor")
    flg, bd = flg_raw[0], bd_raw[0]
    descriptor.extend(flg_raw + bd_raw)
    if (flg >> 6) != 1 or (flg & 0x02):
        raise RamdiskError("Unsupported or invalid LZ4 frame flags")
    if bd & 0x8F:
        raise RamdiskError("Reserved LZ4 block descriptor bits are set")
    block_code = (bd >> 4) & 0x07
    block_limit = {4: 64 * 1024, 5: 256 * 1024, 6: 1024 * 1024, 7: 4 * 1024 * 1024}.get(block_code)
    if block_limit is None:
        raise RamdiskError("Invalid LZ4 maximum block-size code")
    independent = bool(flg & 0x20)
    block_checksum = bool(flg & 0x10)
    content_size: int | None = None
    if flg & 0x08:
        raw = source.read(8)
        if len(raw) != 8:
            raise RamdiskError("Truncated LZ4 content-size field")
        content_size = int.from_bytes(raw, "little")
        descriptor.extend(raw)
    if flg & 0x01:
        raise RamdiskError("LZ4 dictionary frames are not supported")
    header_checksum = source.read(1)
    if len(header_checksum) != 1:
        raise RamdiskError("Truncated LZ4 header checksum")
    expected_hc = (_xxhash32(bytes(descriptor)) >> 8) & 0xFF
    if header_checksum[0] != expected_hc:
        raise RamdiskError("LZ4 frame header checksum mismatch")

    while True:
        if cancel_requested is not None and cancel_requested():
            raise RamdiskCancelled("Ramdisk operation cancelled")
        raw_size = source.read(4)
        if len(raw_size) != 4:
            raise RamdiskError("Truncated LZ4 frame block header")
        block_word = int.from_bytes(raw_size, "little")
        if block_word == 0:
            break
        uncompressed = bool(block_word & 0x80000000)
        block_size = block_word & 0x7FFFFFFF
        if block_size == 0 or block_size > block_limit:
            raise RamdiskError("LZ4 frame block exceeds its declared maximum")
        block = source.read(block_size)
        if len(block) != block_size:
            raise RamdiskError("Truncated LZ4 frame block")
        if block_checksum:
            checksum_raw = source.read(4)
            if len(checksum_raw) != 4:
                raise RamdiskError("Truncated LZ4 block checksum")
            if int.from_bytes(checksum_raw, "little") != _xxhash32(block):
                raise RamdiskError("LZ4 block checksum mismatch")
        decoded = block if uncompressed else _decompress_lz4_block(
            block, b"" if independent else history, limit - total
        )
        total += len(decoded)
        if total > limit:
            raise RamdiskError("LZ4 output exceeds the safety limit")
        destination.write(decoded)
        content_hash.update(decoded)
        history = (history + decoded)[-65536:]
    if flg & 0x04:
        checksum_raw = source.read(4)
        if len(checksum_raw) != 4:
            raise RamdiskError("Truncated LZ4 content checksum")
        if int.from_bytes(checksum_raw, "little") != content_hash.digest_int():
            raise RamdiskError("LZ4 content checksum mismatch")
    if content_size is not None and content_size != total:
        raise RamdiskError(f"LZ4 content size mismatch: got {total}, expected {content_size}")
    if source.read(1):
        raise RamdiskError("Unexpected bytes after the LZ4 frame")
    return total


def _copy_section_to_temp(
    image_path: Path, offset: int, size: int, destination: Path, *, max_unpacked_bytes: int,
    cancel_requested: Callable[[], bool] | None = None,
) -> tuple[str, int]:
    if size <= 0:
        raise RamdiskError("The selected ramdisk section is empty")
    with image_path.open("rb") as source:
        source.seek(offset)
        limited = LimitedReader(source, size)
        prefix = limited.read(min(16, size))
        limited.remaining += len(prefix)
        source.seek(offset)
        fmt = _detect_format(prefix)
        with destination.open("wb") as output:
            if fmt in {"CPIO newc", "CPIO crc"}:
                expanded = _copy_limited(limited, output, max_unpacked_bytes, cancel_requested)
            elif fmt == "gzip":
                try:
                    with gzip.GzipFile(fileobj=limited, mode="rb") as decoder:
                        expanded = _copy_limited(decoder, output, max_unpacked_bytes, cancel_requested)
                except (OSError, EOFError, zlib.error) as exc:
                    raise RamdiskError(f"Invalid gzip ramdisk: {exc}") from exc
            elif fmt == "bzip2":
                try:
                    with bz2.BZ2File(limited, mode="rb") as decoder:
                        expanded = _copy_limited(decoder, output, max_unpacked_bytes, cancel_requested)
                except (OSError, EOFError) as exc:
                    raise RamdiskError(f"Invalid bzip2 ramdisk: {exc}") from exc
            elif fmt in {"XZ", "LZMA-alone"}:
                try:
                    with lzma.LZMAFile(limited, mode="rb") as decoder:
                        expanded = _copy_limited(decoder, output, max_unpacked_bytes, cancel_requested)
                except (lzma.LZMAError, EOFError) as exc:
                    raise RamdiskError(f"Invalid {fmt} ramdisk: {exc}") from exc
            elif fmt in {"LZ4 frame", "LZ4 legacy frame"}:
                try:
                    expanded = _decompress_lz4_frame(
                        limited, output, max_unpacked_bytes, legacy=(fmt == "LZ4 legacy frame"),
                        cancel_requested=cancel_requested,
                    )
                except (OSError, EOFError, struct.error) as exc:
                    raise RamdiskError(f"Invalid {fmt} ramdisk: {exc}") from exc
            elif fmt in {"Zstandard", "LZO (lzop)"}:
                raise RamdiskError(
                    f"{fmt} was detected, but decompression is not included in the dependency-free build"
                )
            else:
                raise RamdiskError(
                    f"Unknown ramdisk format. Expected CPIO newc/crc or a supported compressed CPIO archive; found {prefix[:8].hex()}"
                )
            output.flush()
            os.fsync(output.fileno())
    return fmt, expanded


def _source_section(image_path: Path, fragment_index: int | None) -> dict[str, Any]:
    size = image_path.stat().st_size
    with image_path.open("rb") as stream:
        magic = stream.read(8)
    if magic not in (BOOT_MAGIC, VENDOR_BOOT_MAGIC):
        return {
            "source_kind": "standalone_ramdisk",
            "image_type": "STANDALONE_RAMDISK",
            "section_name": "ramdisk",
            "offset_bytes": 0,
            "size_bytes": size,
            "fragment_index": None,
            "fragment_name": None,
            "fragment_type": None,
            "boot_header_version": None,
        }

    boot = inspect_boot_image(image_path)
    section_name = "vendor_ramdisk" if boot["image_type"] == "VENDOR_BOOT" else "ramdisk"
    section = next((item for item in boot.get("sections", []) if item.get("name") == section_name), None)
    if section is None or not section.get("present"):
        raise RamdiskError(f"The image does not contain a non-empty {section_name} section")
    section_offset = int(section["offset_bytes"])
    section_size = int(section["size_bytes"])
    fragments = boot.get("vendor_ramdisk_fragments", [])
    fragment_info = None
    if boot["image_type"] == "VENDOR_BOOT" and fragments:
        if fragment_index is None:
            if len(fragments) != 1:
                raise RamdiskError(
                    f"vendor_boot contains {len(fragments)} ramdisk fragments; select one with --fragment-index"
                )
            fragment_index = 0
        if fragment_index < 0 or fragment_index >= len(fragments):
            raise RamdiskError(
                f"Vendor ramdisk fragment index {fragment_index} is out of range (0..{len(fragments) - 1})"
            )
        fragment_info = fragments[fragment_index]
        offset = section_offset + int(fragment_info["offset_bytes"])
        length = int(fragment_info["size_bytes"])
        section_name = f"vendor_ramdisk_fragment_{fragment_index}"
    else:
        if fragment_index not in (None, 0):
            raise RamdiskError("--fragment-index applies only to vendor_boot v4 images with a fragment table")
        offset, length = section_offset, section_size
    if offset < 0 or length <= 0 or offset > size or length > size - offset:
        raise RamdiskError("Selected ramdisk section is outside the source image bounds")
    return {
        "source_kind": "boot_image_section",
        "image_type": boot["image_type"],
        "section_name": section_name,
        "offset_bytes": offset,
        "size_bytes": length,
        "fragment_index": None if fragment_info is None else int(fragment_info["index"]),
        "fragment_name": None if fragment_info is None else fragment_info.get("name"),
        "fragment_type": None if fragment_info is None else fragment_info.get("type"),
        "boot_header_version": boot.get("header_version"),
    }


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _skip_zero_padding(stream: BinaryIO, cursor: int, file_size: int) -> int:
    stream.seek(cursor)
    while cursor < file_size:
        chunk = stream.read(min(COPY_BUFFER_SIZE, file_size - cursor))
        if not chunk:
            return cursor
        nonzero = next((index for index, byte in enumerate(chunk) if byte != 0), None)
        if nonzero is not None:
            return cursor + nonzero
        cursor += len(chunk)
    return cursor


def _parse_cpio(stream: BinaryIO, cancel_requested: Callable[[], bool] | None = None
                ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    file_size = os.fstat(stream.fileno()).st_size
    cursor = 0
    entries: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []
    current_archive: dict[str, Any] | None = None
    archive_format: str | None = None
    while cursor < file_size:
        if cancel_requested is not None and cancel_requested():
            raise RamdiskCancelled("Ramdisk operation cancelled")
        cursor = _skip_zero_padding(stream, cursor, file_size)
        if cursor >= file_size:
            break
        stream.seek(cursor)
        magic = stream.read(6)
        if magic not in (CPIO_NEWC, CPIO_CRC):
            raise RamdiskError(f"Invalid CPIO magic at offset {cursor}: {magic.hex()}")
        current_format = "newc" if magic == CPIO_NEWC else "crc"
        if current_archive is None or archive_format != current_format:
            current_archive = {
                "index": len(archives), "format": current_format,
                "start_offset_bytes": cursor, "entry_count": 0,
                "trailer_found": False,
            }
            archives.append(current_archive)
            archive_format = current_format
        while True:
            if cancel_requested is not None and cancel_requested():
                raise RamdiskCancelled("Ramdisk operation cancelled")
            if len(entries) >= MAX_CPIO_ENTRIES:
                raise RamdiskError(f"CPIO entry count exceeds the safety limit ({MAX_CPIO_ENTRIES})")
            stream.seek(cursor)
            header = stream.read(CPIO_HEADER_SIZE)
            if len(header) != CPIO_HEADER_SIZE:
                raise RamdiskError(f"Truncated CPIO header at offset {cursor}")
            magic = header[:6]
            if magic not in (CPIO_NEWC, CPIO_CRC):
                raise RamdiskError(f"Invalid CPIO header magic at offset {cursor}")
            try:
                fields = [int(header[6 + index * 8:14 + index * 8], 16) for index in range(13)]
            except ValueError as exc:
                raise RamdiskError(f"Invalid hexadecimal field in CPIO header at offset {cursor}") from exc
            (ino, mode, uid, gid, nlink, mtime, file_bytes, devmajor, devminor,
             rdevmajor, rdevminor, namesize, checksum) = fields
            if namesize < 1 or namesize > MAX_CPIO_NAME_BYTES:
                raise RamdiskError(f"Invalid CPIO name size {namesize} at offset {cursor}")
            name_offset = cursor + CPIO_HEADER_SIZE
            stream.seek(name_offset)
            raw_name = stream.read(namesize)
            if len(raw_name) != namesize or raw_name[-1:] != b"\x00" or b"\x00" in raw_name[:-1]:
                raise RamdiskError(f"Invalid or truncated CPIO pathname at offset {cursor}")
            name = raw_name[:-1].decode("utf-8", errors="replace")
            data_offset = _align4(name_offset + namesize)
            data_end = data_offset + file_bytes
            if data_end > file_size:
                raise RamdiskError(f"CPIO entry {name!r} extends beyond the archive")
            if magic == CPIO_CRC and file_bytes:
                crc = 0
                stream.seek(data_offset)
                remaining = file_bytes
                while remaining:
                    if cancel_requested is not None and cancel_requested():
                        raise RamdiskCancelled("Ramdisk operation cancelled")
                    chunk = stream.read(min(COPY_BUFFER_SIZE, remaining))
                    if not chunk:
                        raise RamdiskError(f"Truncated data in CPIO entry {name!r}")
                    crc = (crc + sum(chunk)) & 0xFFFFFFFF
                    remaining -= len(chunk)
                if crc != checksum:
                    raise RamdiskError(f"CPIO CRC checksum mismatch for {name!r}")
                checksum_status = "match"
            else:
                if magic == CPIO_CRC and checksum != 0:
                    raise RamdiskError(f"CPIO CRC checksum mismatch for empty entry {name!r}")
                checksum_status = "not-present" if magic == CPIO_NEWC else "match"
            next_cursor = _align4(data_end)
            if name == CPIO_TRAILER:
                current_archive["trailer_found"] = True
                current_archive["end_offset_bytes"] = next_cursor
                current_archive["format"] = "newc" if magic == CPIO_NEWC else "crc"
                cursor = next_cursor
                break
            file_type = stat.S_IFMT(mode)
            if stat.S_ISREG(mode):
                type_name = "file"
            elif stat.S_ISDIR(mode):
                type_name = "directory"
            elif stat.S_ISLNK(mode):
                type_name = "symlink"
            elif stat.S_ISCHR(mode):
                type_name = "character-device"
            elif stat.S_ISBLK(mode):
                type_name = "block-device"
            elif stat.S_ISFIFO(mode):
                type_name = "fifo"
            elif stat.S_ISSOCK(mode):
                type_name = "socket"
            else:
                type_name = "unknown"
            entries.append({
                "path": name, "type": type_name, "mode": mode, "mode_octal": f"{mode:06o}",
                "permissions_octal": f"{stat.S_IMODE(mode):04o}", "uid": uid, "gid": gid,
                "inode": ino, "nlink": nlink, "mtime": mtime,
                "size_bytes": file_bytes, "data_offset_bytes": data_offset,
                "devmajor": devmajor, "devminor": devminor,
                "rdevmajor": rdevmajor, "rdevminor": rdevminor,
                "archive_index": len(archives) - 1, "checksum_status": checksum_status,
                "unsafe_path": _unsafe_path(name),
            })
            current_archive["entry_count"] += 1
            cursor = next_cursor
        if not current_archive["trailer_found"]:
            raise RamdiskError("CPIO archive ended without TRAILER!!!")
        current_archive = None
        archive_format = None
    if not archives:
        raise RamdiskError("No CPIO newc/crc archive was found after decompression")
    return entries, archives


def _unsafe_path(name: str) -> bool:
    if not name or "\x00" in name or "\\" in name or ":" in name:
        return True
    if name.startswith("/") or name.startswith("//"):
        return True
    if any(ord(char) < 32 or char in '<>"|?*' for char in name):
        return True
    parts = name.split("/")
    if any(part == ".." for part in parts):
        return True
    # Avoid Windows device names and path aliases when extracting on Windows.
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                *(f"LPT{i}" for i in range(1, 10))}
    for part in parts:
        stem = part.rstrip(" .").split(".", 1)[0].upper()
        if stem in reserved or part.endswith((".", " ")):
            return True
    return False


def _prepare_report(image_path: Path, fragment_index: int | None,
                    max_unpacked_bytes: int, cancel_requested: Callable[[], bool] | None = None
                    ) -> tuple[dict[str, Any], tempfile.TemporaryDirectory[str]]:
    source = _source_section(image_path, fragment_index)
    temp_dir = tempfile.TemporaryDirectory(prefix="sparse-to-raw-ramdisk-")
    unpacked_path = Path(temp_dir.name) / "ramdisk.cpio"
    try:
        compression, unpacked_size = _copy_section_to_temp(
            image_path, source["offset_bytes"], source["size_bytes"], unpacked_path,
            max_unpacked_bytes=max_unpacked_bytes, cancel_requested=cancel_requested,
        )
        with unpacked_path.open("rb") as stream:
            entries, archives = _parse_cpio(stream, cancel_requested=cancel_requested)
        counts = {key: sum(1 for item in entries if item["type"] == key)
                  for key in ("file", "directory", "symlink")}
        total_file_bytes = sum(item["size_bytes"] for item in entries if item["type"] == "file")
        report = {
            "operation": "android-ramdisk-inspect",
            "input": str(image_path),
            **source,
            "compression_format": compression,
            "cpio_formats": sorted({archive["format"] for archive in archives}),
            "archive_count": len(archives),
            "entry_count": len(entries),
            "file_count": counts["file"],
            "directory_count": counts["directory"],
            "symlink_count": counts["symlink"],
            "special_entry_count": len(entries) - counts["file"] - counts["directory"] - counts["symlink"],
            "total_file_bytes": total_file_bytes,
            "unpacked_size_bytes": unpacked_size,
            "max_unpacked_bytes": max_unpacked_bytes,
            "archives": archives,
            "entries": entries,
            "warnings": [],
        }
        if any(entry["unsafe_path"] for entry in entries):
            report["warnings"].append("One or more CPIO paths are unsafe and will be skipped during extraction.")
        if report["symlink_count"]:
            report["warnings"].append("Symlinks are listed in SYMLINKS.txt rather than created on disk.")
        if report["special_entry_count"]:
            report["warnings"].append("Special device/socket/FIFO entries are listed in SPECIAL_FILES.txt and not created.")
        return report, temp_dir
    except Exception:
        temp_dir.cleanup()
        raise


def inspect_ramdisk(
    image_path: str | os.PathLike[str], *, fragment_index: int | None = None,
    max_unpacked_bytes: int = MAX_UNPACKED_BYTES,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Ramdisk image not found: {path}")
    if max_unpacked_bytes <= 0:
        raise RamdiskError("max_unpacked_bytes must be positive")
    report, temp_dir = _prepare_report(path, fragment_index, max_unpacked_bytes, cancel_requested)
    temp_dir.cleanup()
    # Internal file offsets belong to the temporary expanded archive and are not
    # useful to callers; they are removed from the public inventory.
    for entry in report["entries"]:
        entry.pop("data_offset_bytes", None)
    report["source_size_bytes"] = path.stat().st_size
    return report


MAX_TEXT_PREVIEW_BYTES = 256 * 1024


def read_ramdisk_file(
    image_path: str | os.PathLike[str], cpio_path: str, *,
    fragment_index: int | None = None,
    max_unpacked_bytes: int = MAX_UNPACKED_BYTES,
    preview_limit_bytes: int = MAX_TEXT_PREVIEW_BYTES,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Read a bounded preview of one regular file from a ramdisk CPIO archive.

    The archive is expanded only into a private temporary directory. The source
    image is never modified and no CPIO path is materialized on the filesystem.
    Unsafe paths and non-regular entries are rejected.
    """
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Ramdisk image not found: {path}")
    if not isinstance(cpio_path, str) or not cpio_path or _unsafe_path(cpio_path):
        raise RamdiskError(f"Unsafe or empty CPIO path rejected: {cpio_path!r}")
    if preview_limit_bytes <= 0 or preview_limit_bytes > 2 * 1024 * 1024:
        raise RamdiskError("preview_limit_bytes must be between 1 and 2 MiB")

    requested = _normalize_cpio_path(cpio_path)
    report, temp_dir = _prepare_report(
        path, fragment_index, max_unpacked_bytes, cancel_requested
    )
    try:
        # CPIO archives can be concatenated; the last entry for a path wins.
        final_entries: dict[str, dict[str, Any]] = {}
        for entry in report["entries"]:
            final_entries[_normalize_cpio_path(entry["path"])] = entry
        entry = final_entries.get(requested)
        if entry is None:
            raise RamdiskError(f"CPIO path not found: {cpio_path}")
        if entry.get("unsafe_path"):
            raise RamdiskError(f"Unsafe CPIO path cannot be previewed: {cpio_path!r}")
        if entry.get("type") != "file":
            raise RamdiskError(f"Only regular files can be previewed: {cpio_path!r}")

        data_offset = int(entry["data_offset_bytes"])
        data_size = int(entry["size_bytes"])
        if data_size == 0 and int(entry.get("nlink", 1)) > 1:
            key = (entry["devmajor"], entry["devminor"], entry["inode"])
            linked = next((candidate for candidate in reversed(report["entries"])
                           if candidate.get("type") == "file"
                           and (candidate["devmajor"], candidate["devminor"], candidate["inode"]) == key
                           and int(candidate.get("size_bytes", 0)) > 0), None)
            if linked is not None:
                data_offset = int(linked["data_offset_bytes"])
                data_size = int(linked["size_bytes"])

        preview_size = min(data_size, preview_limit_bytes)
        if cancel_requested is not None and cancel_requested():
            raise RamdiskCancelled("Ramdisk operation cancelled")
        unpacked_path = Path(temp_dir.name) / "ramdisk.cpio"
        with unpacked_path.open("rb") as stream:
            stream.seek(data_offset)
            data = stream.read(preview_size)
        if len(data) != preview_size:
            raise RamdiskError(f"Unexpected end of CPIO data while previewing {cpio_path!r}")

        encoding = "utf-8"
        text_data = data
        utf16_bom = False
        if data.startswith(b"\xef\xbb\xbf"):
            encoding, text_data = "utf-8-sig", data
        elif data.startswith(b"\xff\xfe"):
            encoding, utf16_bom = "utf-16-le", True
        elif data.startswith(b"\xfe\xff"):
            encoding, utf16_bom = "utf-16-be", True

        probe = text_data[:8192]
        has_nul = b"\x00" in probe and not utf16_bom
        control_count = sum(1 for byte in probe if byte < 9 or 13 < byte < 32)
        is_text = utf16_bom or (not has_nul and (not probe or control_count <= max(1, len(probe) // 100)))
        text_preview: str | None = None
        hex_preview: str | None = None
        if is_text:
            try:
                text_preview = data.decode(encoding)
            except UnicodeDecodeError:
                try:
                    text_preview = data.decode("utf-8", errors="replace")
                    encoding = "utf-8 (replacement characters)"
                except Exception:
                    is_text = False
        if not is_text:
            hex_preview = " ".join(f"{byte:02X}" for byte in data[:512])

        return {
            "operation": "android-ramdisk-preview",
            "input": str(path),
            "path": requested,
            "type": entry["type"],
            "size_bytes": data_size,
            "preview_bytes": len(data),
            "truncated": data_size > len(data),
            "is_text": is_text,
            "encoding": encoding if is_text else None,
            "text_preview": text_preview,
            "hex_preview": hex_preview,
            "fragment_index": report.get("fragment_index"),
            "compression_format": report.get("compression_format"),
        }
    finally:
        temp_dir.cleanup()


def _normalize_cpio_path(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    return name


def _safe_relative_path(name: str) -> Path:
    if _unsafe_path(name):
        raise RamdiskError(f"Unsafe CPIO path rejected: {name!r}")
    name = _normalize_cpio_path(name)
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if not parts:
        raise RamdiskError(f"Empty CPIO path rejected: {name!r}")
    return Path(*parts)


def _is_selected(name: str, include_paths: set[str] | None, entries: list[dict[str, Any]]) -> bool:
    if include_paths is None:
        return True
    name = _normalize_cpio_path(name)
    include_paths = {_normalize_cpio_path(item) for item in include_paths}
    if name in include_paths:
        return True
    # Selecting a directory includes all descendants, including entries that
    # occur in a later concatenated CPIO archive.
    for selected in include_paths:
        normalized = selected.rstrip("/")
        if normalized and name.startswith(normalized + "/"):
            return True
    return False


def _extract_entries(unpacked_path: Path, report: dict[str, Any], output_dir: Path,
                     include_paths: set[str] | None, *, force: bool,
                     cancel_requested: Callable[[], bool] | None = None) -> dict[str, Any]:
    if output_dir.exists() and not output_dir.is_dir():
        raise FileExistsError(f"Output path is not a directory: {output_dir}")
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise FileExistsError(f"Output directory is not empty: {output_dir} (use --force to merge/replace)")

    # CPIO archives are overlaid in sequence. The last occurrence of a pathname
    # wins, matching initramfs extraction semantics.
    final_entries: dict[str, dict[str, Any]] = {}
    for entry in report["entries"]:
        if _is_selected(entry["path"], include_paths, report["entries"]):
            final_entries[_normalize_cpio_path(entry["path"])] = entry
    # Ensure selected paths are a subset of known entries.
    if include_paths is not None:
        known = {_normalize_cpio_path(entry["path"]) for entry in report["entries"]}
        requested = {_normalize_cpio_path(item) for item in include_paths}
        missing = requested - known
        if missing:
            raise RamdiskError(f"Selected CPIO path not found: {sorted(missing)[0]}")

    output_dir.mkdir(parents=True, exist_ok=True)
    root = output_dir.resolve()

    hardlink_data: dict[tuple[int, int, int], tuple[int, int]] = {}
    for entry in report["entries"]:
        if entry["type"] == "file" and entry["size_bytes"]:
            key = (entry["devmajor"], entry["devminor"], entry["inode"])
            hardlink_data.setdefault(key, (entry["data_offset_bytes"], entry["size_bytes"]))

    directories: list[tuple[str, dict[str, Any]]] = []
    files: list[tuple[str, dict[str, Any]]] = []
    symlinks: list[tuple[str, dict[str, Any]]] = []
    special: list[tuple[str, str]] = []
    for name, entry in final_entries.items():
        if name in ("", ".") and entry["type"] == "directory":
            continue
        if entry["unsafe_path"]:
            special.append((name, "unsafe path skipped"))
            continue
        try:
            rel = _safe_relative_path(name)
        except RamdiskError:
            special.append((name, "unsafe path skipped"))
            continue
        target = (root / rel).resolve(strict=False)
        try:
            target.relative_to(root)
        except ValueError:
            special.append((name, "path escapes output directory"))
            continue
        if entry["type"] == "directory":
            directories.append((name, entry))
        elif entry["type"] == "file":
            files.append((name, entry))
        elif entry["type"] == "symlink":
            symlinks.append((name, entry))
        else:
            special.append((name, entry["type"]))

    with unpacked_path.open("rb") as source:
        for name, entry in directories:
            if cancel_requested is not None and cancel_requested():
                raise RamdiskCancelled("Ramdisk operation cancelled")
            rel = _safe_relative_path(name)
            target = root / rel
            if target.exists() and not target.is_dir():
                raise RamdiskError(f"CPIO path type conflict at {name!r}")
            target.mkdir(parents=True, exist_ok=True)
        for name, entry in files:
            if cancel_requested is not None and cancel_requested():
                raise RamdiskCancelled("Ramdisk operation cancelled")
            rel = _safe_relative_path(name)
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # Never follow a pre-existing symlink inside the destination tree.
            cursor = target.parent
            while cursor != root:
                if cursor.is_symlink():
                    raise RamdiskError(f"Destination parent is a symlink: {cursor}")
                cursor = cursor.parent
            if target.exists() and target.is_dir():
                raise RamdiskError(f"CPIO path type conflict at {name!r}")
            data_offset = entry["data_offset_bytes"]
            data_size = entry["size_bytes"]
            if data_size == 0 and entry["nlink"] > 1:
                key = (entry["devmajor"], entry["devminor"], entry["inode"])
                if key in hardlink_data:
                    data_offset, data_size = hardlink_data[key]
            source.seek(data_offset)
            remaining = data_size
            with target.open("wb") as output:
                while remaining:
                    if cancel_requested is not None and cancel_requested():
                        raise RamdiskCancelled("Ramdisk operation cancelled")
                    chunk = source.read(min(COPY_BUFFER_SIZE, remaining))
                    if not chunk:
                        raise RamdiskError(f"Unexpected end of CPIO data for {name!r}")
                    output.write(chunk)
                    remaining -= len(chunk)
            if os.name != "nt":
                try:
                    os.chmod(target, stat.S_IMODE(entry["mode"]))
                except OSError:
                    pass
        symlink_manifest: list[tuple[str, str]] = []
        for name, entry in symlinks:
            source.seek(entry["data_offset_bytes"])
            link_data = source.read(entry["size_bytes"])
            symlink_manifest.append((name, link_data.decode("utf-8", errors="replace")))

    def write_sidecar(preferred_name: str, content: str) -> None:
        candidate = root / preferred_name
        if candidate.exists():
            candidate = root / f"{preferred_name}.sparse-to-raw.txt"
            suffix = 2
            while candidate.exists():
                candidate = root / f"{preferred_name}.sparse-to-raw-{suffix}.txt"
                suffix += 1
        candidate.write_text(content, encoding="utf-8")

    if symlinks:
        write_sidecar(
            "SYMLINKS.txt",
            "\n".join(f"{name} -> {target}" for name, target in symlink_manifest) + "\n",
        )
    if special:
        write_sidecar(
            "SPECIAL_FILES.txt",
            "\n".join(f"{name}: {kind}" for name, kind in special) + "\n",
        )
    return {
        "output_dir": str(output_dir),
        "extracted_files": len(files),
        "created_directories": len(directories),
        "symlinks_listed": len(symlinks),
        "special_entries_skipped": len(special),
        "total_file_bytes": sum(entry["size_bytes"] for _, entry in files),
        "selected_entry_count": len(final_entries),
    }


def extract_ramdisk(
    image_path: str | os.PathLike[str], output_dir: str | os.PathLike[str], *,
    fragment_index: int | None = None, include_paths: set[str] | None = None,
    max_unpacked_bytes: int = MAX_UNPACKED_BYTES, force: bool = False,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    path = Path(image_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Ramdisk image not found: {path}")
    if path == destination or destination in path.parents:
        raise RamdiskError("Output directory must not contain or replace the input image")
    if max_unpacked_bytes <= 0:
        raise RamdiskError("max_unpacked_bytes must be positive")
    report, temp_dir = _prepare_report(path, fragment_index, max_unpacked_bytes, cancel_requested)
    try:
        unpacked_path = Path(temp_dir.name) / "ramdisk.cpio"
        result = _extract_entries(
            unpacked_path, report, destination, include_paths, force=force,
            cancel_requested=cancel_requested,
        )
        return {"operation": "android-ramdisk-extract", "input": str(path), **result,
                "compression_format": report["compression_format"],
                "cpio_formats": report["cpio_formats"], "archive_count": report["archive_count"],
                "fragment_index": report["fragment_index"], "warnings": report["warnings"]}
    finally:
        temp_dir.cleanup()


def _write_json(path: Path, report: dict[str, Any], force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"JSON report already exists: {path} (use --force to overwrite)")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"JSON report directory not found: {path.parent}")
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    temp_fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temp_path, path)
        else:
            os.link(temp_path, path)
            temp_path.unlink()
    finally:
        temp_path.unlink(missing_ok=True)


def run_ramdisk_cli(command_name: str, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog=f"sparse-to-raw {command_name}",
        description=tr("ramdisk_info_desc" if command_name == "ramdisk-info" else "ramdisk_extract_desc"),
    )
    parser.add_argument("image", help=tr("ramdisk_input"))
    parser.add_argument("--fragment-index", type=int, help=tr("ramdisk_fragment"))
    parser.add_argument("--max-unpacked-mib", type=int, default=512, help=tr("ramdisk_limit"))
    parser.add_argument("--json-report", metavar="FILE", help=tr("ramdisk_json"))
    parser.add_argument("--force", action="store_true", help=tr("ramdisk_force"))
    if command_name == "ramdisk-extract":
        parser.add_argument("--output-dir", required=True, help=tr("ramdisk_output"))
        parser.add_argument("--include", action="append", dest="include_paths", help=tr("ramdisk_include"))
    options = parser.parse_args(argv)
    try:
        source = Path(options.image).expanduser().resolve()
        report_path = Path(options.json_report).expanduser().resolve() if options.json_report else None
        if report_path is not None and report_path == source:
            raise RamdiskError("JSON report path must differ from the input image")
        if report_path is not None:
            if report_path.exists() and not options.force:
                raise FileExistsError(f"JSON report already exists: {report_path} (use --force to overwrite)")
            if not report_path.parent.is_dir():
                raise FileNotFoundError(f"JSON report directory not found: {report_path.parent}")
            if report_path.is_dir():
                raise IsADirectoryError(f"JSON report path points to a directory: {report_path}")
        maximum = options.max_unpacked_mib * 1024 * 1024
        if command_name == "ramdisk-info":
            result = inspect_ramdisk(source, fragment_index=options.fragment_index,
                                     max_unpacked_bytes=maximum)
        else:
            output_dir = Path(options.output_dir).expanduser().resolve()
            if report_path is not None and (report_path == output_dir or output_dir in report_path.parents):
                raise RamdiskError("JSON report path must be outside the extracted output directory")
            result = extract_ramdisk(
                source, output_dir, fragment_index=options.fragment_index,
                include_paths=set(options.include_paths) if options.include_paths else None,
                max_unpacked_bytes=maximum, force=options.force,
            )
        if report_path is not None:
            _write_json(report_path, result, options.force)
            result["json_report"] = str(report_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"{tr('error')}: {exc}", file=sys.stderr)
        return 1
