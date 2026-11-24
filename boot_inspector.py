#!/usr/bin/env python3
"""Read-only inspector for Android boot and vendor_boot images.

Supports legacy boot header v0-v2, generic boot header v3-v4 and
vendor_boot header v3-v4. The module uses only the Python standard library
and never modifies the source image.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import Any, BinaryIO

from cli_i18n import tr

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"
BOOT_HEADER_V0_SIZE = 1632
BOOT_HEADER_V1_SIZE = 1648
BOOT_HEADER_V2_SIZE = 1660
BOOT_HEADER_V3_SIZE = 1580
BOOT_HEADER_V4_SIZE = 1584
VENDOR_BOOT_HEADER_V3_SIZE = 2112
VENDOR_BOOT_HEADER_V4_SIZE = 2128
VENDOR_RAMDISK_TABLE_ENTRY_SIZE = 108
MAX_VENDOR_RAMDISK_TABLE_SIZE = 16 * 1024 * 1024
MAX_PAGE_SIZE = 65536
PREVIEW_SIZE = 32
KERNEL_PREVIEW_SIZE = 64
AVB_FOOTER_SIZE = 64
AVB_FOOTER_FORMAT = ">4sIIQQQ28s"
AVB_FOOTER_SUPPORTED_MAJOR = 1

VENDOR_RAMDISK_TYPES = {
    0: "NONE",
    1: "PLATFORM",
    2: "RECOVERY",
    3: "DLKM",
}


class BootImageError(ValueError):
    """Raised when a boot image is malformed or unsupported."""


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def _read_at(stream: BinaryIO, offset: int, size: int, *, what: str, file_size: int) -> bytes:
    if offset < 0 or size < 0 or offset > file_size or size > file_size - offset:
        raise BootImageError(
            f"{what} is outside the image bounds (offset={offset}, size={size}, image={file_size})"
        )
    stream.seek(offset)
    data = stream.read(size)
    if len(data) != size:
        raise BootImageError(f"Unexpected end of file while reading {what}")
    return data


def _u32(data: bytes, offset: int, what: str) -> int:
    if offset < 0 or offset + 4 > len(data):
        raise BootImageError(f"Truncated header while reading {what}")
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int, what: str) -> int:
    if offset < 0 or offset + 8 > len(data):
        raise BootImageError(f"Truncated header while reading {what}")
    return struct.unpack_from("<Q", data, offset)[0]


def _cstring(data: bytes) -> str:
    return data.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()


def _check_page_size(page_size: int, *, kind: str) -> None:
    if page_size < 512 or page_size > MAX_PAGE_SIZE or page_size & (page_size - 1):
        raise BootImageError(f"Invalid {kind} page size: {page_size}")


def decode_os_version(value: int) -> dict[str, Any]:
    """Decode Android's packed A.B.C and YYYY-MM OS version field."""
    major = (value >> 25) & 0x7F
    minor = (value >> 18) & 0x7F
    patch = (value >> 11) & 0x7F
    year = ((value >> 4) & 0x7F) + 2000
    month = value & 0x0F
    if value == 0:
        return {"raw": 0, "version": None, "security_patch_level": None}
    version = f"{major}.{minor}.{patch}"
    patch_level = f"{year:04d}-{month:02d}" if 1 <= month <= 12 else None
    return {"raw": value, "version": version, "security_patch_level": patch_level}


def _detect_compression_format(prefix: bytes) -> str | None:
    """Return a compression/container hint based on a leading magic signature."""
    if prefix.startswith(b"\x1f\x8b"):
        return "gzip"
    if prefix.startswith(b"BZh") and len(prefix) >= 4 and prefix[3:4] in b"123456789":
        return "bzip2"
    if prefix.startswith(b"\xfd7zXZ\x00"):
        return "XZ"
    if prefix.startswith(b"\x28\xb5\x2f\xfd"):
        return "Zstandard"
    if prefix.startswith(b"\x04\x22\x4d\x18"):
        return "LZ4 frame"
    if prefix.startswith(b"\x02\x21\x4c\x18"):
        return "LZ4 legacy frame"
    if prefix.startswith(b"\x89LZO\x00\r\n\x1a\n"):
        return "LZO (lzop)"
    if prefix.startswith(b"\x5d\x00\x00"):
        return "LZMA (probable)"
    return None


def _detect_kernel_format(prefix: bytes) -> str:
    # Uncompressed Linux kernel headers are more specific than generic
    # compression signatures, so check them first. Some vendor images store
    # the compressed kernel payload directly in the Android boot section.
    if len(prefix) >= 0x3C and prefix[0x38:0x3C] == b"ARM\x64":
        return "ARM64 Linux Image"
    if len(prefix) >= 0x28 and prefix[0x24:0x28] == b"\x18\x28\x6f\x01":
        return "ARM32 zImage"
    if len(prefix) >= 0x206 and prefix[0x202:0x206] == b"HdrS":
        return "x86 bzImage"
    compression = _detect_compression_format(prefix)
    if compression:
        return f"{compression}-compressed kernel payload"
    return "Unknown / vendor-specific kernel format"


def _detect_ramdisk_format(prefix: bytes) -> str:
    if not prefix:
        return "Empty"
    if prefix.startswith(b"070701"):
        return "CPIO newc"
    if prefix.startswith(b"070702"):
        return "CPIO crc"
    compression = _detect_compression_format(prefix)
    if compression:
        return compression
    return "Unknown / uncompressed or vendor-specific data"


def _section(
    stream: BinaryIO,
    *,
    name: str,
    offset: int,
    size: int,
    file_size: int,
    kind: str = "binary",
) -> dict[str, Any]:
    if size < 0:
        raise BootImageError(f"Negative size for {name}")
    if size == 0:
        return {"name": name, "offset_bytes": offset, "size_bytes": 0, "present": False}
    preview_size = KERNEL_PREVIEW_SIZE if kind == "kernel" else PREVIEW_SIZE
    prefix = _read_at(stream, offset, min(size, preview_size), what=name, file_size=file_size)
    if kind == "kernel":
        detected = _detect_kernel_format(prefix)
    elif kind == "ramdisk":
        detected = _detect_ramdisk_format(prefix)
    else:
        detected = "binary data"
    return {
        "name": name,
        "offset_bytes": offset,
        "size_bytes": size,
        "present": True,
        "detected_format": detected,
        "first_bytes_hex": prefix[:16].hex(" "),
    }


def _inspect_avb_footer(
    stream: BinaryIO, file_size: int, *, minimum_component_end: int | None = None
) -> dict[str, Any] | None:
    """Parse the 64-byte AVB footer at the end of an image, if present.

    This is structural inspection only. It does not authenticate VBMeta,
    verify its signature, or establish trust in the embedded key.
    """
    if file_size < AVB_FOOTER_SIZE:
        return None
    footer_offset = file_size - AVB_FOOTER_SIZE
    raw = _read_at(
        stream, footer_offset, AVB_FOOTER_SIZE,
        what="possible AVB footer", file_size=file_size,
    )
    magic, version_major, version_minor, original_image_size, vbmeta_offset, vbmeta_size, reserved = struct.unpack(
        AVB_FOOTER_FORMAT, raw
    )
    if magic != b"AVBf":
        return None

    errors: list[str] = []
    warnings: list[str] = []
    vbmeta_end: int | None = None
    vbmeta_header_magic: str | None = None
    vbmeta_header_present = False

    if version_major > AVB_FOOTER_SUPPORTED_MAJOR:
        warnings.append(
            f"AVB footer major version {version_major} is newer than the supported major version "
            f"{AVB_FOOTER_SUPPORTED_MAJOR}."
        )
    if original_image_size > footer_offset:
        errors.append("original_image_size extends into or beyond the AVB footer.")
    if minimum_component_end is not None and original_image_size < minimum_component_end:
        errors.append("original_image_size ends before the last parsed image component.")
    if vbmeta_size == 0:
        errors.append("vbmeta_size is zero.")
    if minimum_component_end is not None and vbmeta_offset < minimum_component_end:
        errors.append("vbmeta_offset overlaps the parsed boot image components.")
    if vbmeta_offset > footer_offset:
        errors.append("vbmeta_offset points beyond the start of the AVB footer.")
    elif vbmeta_size > footer_offset - vbmeta_offset:
        errors.append("The VBMeta block extends into or beyond the AVB footer.")
    else:
        vbmeta_end = vbmeta_offset + vbmeta_size
        if vbmeta_offset < original_image_size:
            warnings.append("vbmeta_offset is before original_image_size; verify this layout against the image producer.")
        if vbmeta_size >= 4:
            header_magic = _read_at(
                stream, vbmeta_offset, 4, what="VBMeta header magic", file_size=file_size
            )
            try:
                vbmeta_header_magic = header_magic.decode("ascii")
            except UnicodeDecodeError:
                vbmeta_header_magic = header_magic.hex()
            vbmeta_header_present = header_magic == b"AVB0"
            if not vbmeta_header_present:
                warnings.append(
                    f"The VBMeta block does not start with the expected AVB0 magic (found {header_magic.hex()})."
                )
        else:
            warnings.append("The declared VBMeta block is smaller than its 4-byte header magic.")

    reserved_zero = not any(reserved)
    if not reserved_zero:
        warnings.append("The AVB footer reserved bytes are not all zero.")

    status = "invalid" if errors else ("warning" if warnings else "valid")
    return {
        "magic": "AVBf",
        "offset_bytes": footer_offset,
        "size_bytes": AVB_FOOTER_SIZE,
        "version_major": version_major,
        "version_minor": version_minor,
        "original_image_size_bytes": original_image_size,
        "vbmeta_offset_bytes": vbmeta_offset,
        "vbmeta_size_bytes": vbmeta_size,
        "vbmeta_end_bytes": vbmeta_end,
        "vbmeta_header_magic": vbmeta_header_magic,
        "vbmeta_header_present": vbmeta_header_present,
        "reserved_bytes_zero": reserved_zero,
        "reserved_hex": reserved.hex(),
        "structural_status": status,
        "validation_errors": errors,
        "warnings": warnings,
        "signature_verified": False,
    }

def _build_trailing_region(
    *, last_component_end: int, file_size: int, footer: dict[str, Any] | None
) -> dict[str, Any]:
    """Describe bytes after parsed boot components without treating them as padding."""
    region: dict[str, Any] = {
        "offset_bytes": last_component_end,
        "size_bytes": max(0, file_size - last_component_end),
    }
    if footer is None:
        region["unclassified_data_bytes"] = region["size_bytes"]
        return region

    footer_offset = int(footer["offset_bytes"])
    vbmeta_offset = int(footer["vbmeta_offset_bytes"])
    vbmeta_size = int(footer["vbmeta_size_bytes"])
    vbmeta_end = footer.get("vbmeta_end_bytes")
    region["footer_offset_bytes"] = footer_offset
    if vbmeta_end is not None and vbmeta_offset >= last_component_end:
        region["unclassified_before_vbmeta_bytes"] = vbmeta_offset - last_component_end
        region["vbmeta"] = {
            "offset_bytes": vbmeta_offset,
            "size_bytes": vbmeta_size,
            "end_bytes": int(vbmeta_end),
            "header_magic": footer.get("vbmeta_header_magic"),
            "header_present": bool(footer.get("vbmeta_header_present")),
        }
        region["unclassified_after_vbmeta_bytes"] = max(0, footer_offset - int(vbmeta_end))
    else:
        region["unclassified_data_bytes"] = region["size_bytes"]
    return region

def _parse_boot_image(stream: BinaryIO, path: Path, file_size: int) -> dict[str, Any]:
    version_probe = _read_at(stream, 0, 44, what="boot header prefix", file_size=file_size)
    version = _u32(version_probe, 40, "header_version")
    if version not in (0, 1, 2, 3, 4):
        raise BootImageError(f"Unsupported Android boot header version: {version}")
    required = {
        0: BOOT_HEADER_V0_SIZE,
        1: BOOT_HEADER_V1_SIZE,
        2: BOOT_HEADER_V2_SIZE,
        3: BOOT_HEADER_V3_SIZE,
        4: BOOT_HEADER_V4_SIZE,
    }[version]
    if file_size < required:
        raise BootImageError(f"Boot header v{version} is truncated (need at least {required} bytes)")
    header = _read_at(stream, 0, required, what="boot header", file_size=file_size)

    sections: list[dict[str, Any]] = []
    fields: dict[str, Any] = {}
    warnings: list[str] = []
    if version <= 2:
        required = {0: BOOT_HEADER_V0_SIZE, 1: BOOT_HEADER_V1_SIZE, 2: BOOT_HEADER_V2_SIZE}[version]
        page_size = _u32(header, 36, "page_size")
        _check_page_size(page_size, kind="boot")
        if page_size < required:
            raise BootImageError(f"Page size {page_size} is smaller than the v{version} header ({required})")
        kernel_size = _u32(header, 8, "kernel_size")
        kernel_addr = _u32(header, 12, "kernel_addr")
        ramdisk_size = _u32(header, 16, "ramdisk_size")
        ramdisk_addr = _u32(header, 20, "ramdisk_addr")
        second_size = _u32(header, 24, "second_size")
        second_addr = _u32(header, 28, "second_addr")
        tags_addr = _u32(header, 32, "tags_addr")
        os_version_raw = _u32(header, 44, "os_version")
        name = _cstring(header[48:64])
        cmdline = _cstring(header[64:576])
        image_id = header[576:608].hex() if len(header) >= 608 else ""
        extra_cmdline = _cstring(header[608:1632]) if len(header) >= 1632 else ""
        header_size = required
        fields.update({
            "kernel_addr": kernel_addr,
            "ramdisk_addr": ramdisk_addr,
            "second_size_bytes": second_size,
            "second_addr": second_addr,
            "tags_addr": tags_addr,
            "name": name,
            "cmdline": cmdline,
            "extra_cmdline": extra_cmdline,
            "image_id_hex": image_id,
        })
        cursor = page_size
        kernel_offset = cursor
        sections.append(_section(stream, name="kernel", offset=kernel_offset, size=kernel_size,
                                 file_size=file_size, kind="kernel"))
        cursor = _align(kernel_offset + kernel_size, page_size)
        ramdisk_offset = cursor
        sections.append(_section(stream, name="ramdisk", offset=ramdisk_offset, size=ramdisk_size,
                                 file_size=file_size, kind="ramdisk"))
        cursor = _align(ramdisk_offset + ramdisk_size, page_size)
        second_offset = cursor
        sections.append(_section(stream, name="second", offset=second_offset, size=second_size,
                                 file_size=file_size))
        cursor = _align(second_offset + second_size, page_size)
        recovery_dtbo_size = 0
        recovery_dtbo_offset = 0
        dtb_size = 0
        dtb_addr = 0
        if version >= 1:
            recovery_dtbo_size = _u32(header, 1632, "recovery_dtbo_size")
            recovery_dtbo_offset = _u64(header, 1636, "recovery_dtbo_offset")
            header_size_field = _u32(header, 1644, "header_size")
            expected_header_size = BOOT_HEADER_V1_SIZE if version == 1 else BOOT_HEADER_V2_SIZE
            if header_size_field != expected_header_size or header_size_field > page_size:
                raise BootImageError(
                    f"Invalid boot header_size for v{version}: {header_size_field} "
                    f"(expected {expected_header_size})"
                )
            header_size = header_size_field
            if recovery_dtbo_size:
                if recovery_dtbo_offset == 0:
                    raise BootImageError("recovery_dtbo_size is non-zero but recovery_dtbo_offset is zero")
                if recovery_dtbo_offset < cursor or recovery_dtbo_offset % page_size:
                    raise BootImageError("recovery_dtbo_offset overlaps the previous section or is not page-aligned")
                recovery_offset = recovery_dtbo_offset
                sections.append(_section(stream, name="recovery_dtbo", offset=recovery_offset,
                                         size=recovery_dtbo_size, file_size=file_size))
                cursor = _align(recovery_offset + recovery_dtbo_size, page_size)
            else:
                sections.append(_section(stream, name="recovery_dtbo", offset=cursor,
                                         size=0, file_size=file_size))
        if version >= 2:
            dtb_size = _u32(header, 1648, "dtb_size")
            dtb_addr = _u64(header, 1652, "dtb_addr")
            sections.append(_section(stream, name="dtb", offset=cursor, size=dtb_size,
                                     file_size=file_size))
            fields.update({"dtb_size_bytes": dtb_size, "dtb_addr": dtb_addr})
        fields.update({
            "recovery_dtbo_size_bytes": recovery_dtbo_size,
            "recovery_dtbo_offset_bytes": recovery_dtbo_offset,
            "os_version": decode_os_version(os_version_raw),
        })
        role = "boot or recovery (the header alone does not identify the partition role)"
        data_end = cursor + dtb_size
        if not kernel_size and ramdisk_size:
            warnings.append("The image has no kernel but contains a ramdisk; it may be an init_boot-style image, but the partition role cannot be proven from the header alone.")
    else:
        kernel_size = _u32(header, 8, "kernel_size")
        ramdisk_size = _u32(header, 12, "ramdisk_size")
        os_version_raw = _u32(header, 16, "os_version")
        header_size = _u32(header, 20, "header_size")
        if header_size not in (BOOT_HEADER_V3_SIZE, BOOT_HEADER_V4_SIZE):
            raise BootImageError(f"Invalid boot header_size for v{version}: {header_size}")
        if version == 3 and header_size != BOOT_HEADER_V3_SIZE:
            raise BootImageError("Boot header v3 must declare a 1580-byte header")
        if version == 4 and header_size != BOOT_HEADER_V4_SIZE:
            raise BootImageError("Boot header v4 must declare a 1584-byte header")
        page_size = 4096
        cmdline = _cstring(header[44:44 + 1536])
        reserved = list(struct.unpack_from("<4I", header, 24))
        fields.update({
            "cmdline": cmdline,
            "reserved": reserved,
            "os_version": decode_os_version(os_version_raw),
            "kernel_addr": None,
            "ramdisk_addr": None,
        })
        cursor = page_size
        kernel_offset = cursor
        sections.append(_section(stream, name="kernel", offset=kernel_offset, size=kernel_size,
                                 file_size=file_size, kind="kernel"))
        cursor = _align(kernel_offset + kernel_size, page_size)
        ramdisk_offset = cursor
        sections.append(_section(stream, name="ramdisk", offset=ramdisk_offset, size=ramdisk_size,
                                 file_size=file_size, kind="ramdisk"))
        cursor = _align(ramdisk_offset + ramdisk_size, page_size)
        signature_size = _u32(header, BOOT_HEADER_V3_SIZE, "signature_size") if version >= 4 else 0
        sections.append(_section(stream, name="boot_signature", offset=cursor, size=signature_size,
                                 file_size=file_size))
        data_end = cursor + signature_size
        fields["signature_size_bytes"] = signature_size
        role = "generic boot image"
        if not kernel_size and ramdisk_size:
            role = "probable init_boot image (kernel is empty; role inferred from contents)"
            warnings.append("init_boot is inferred from an empty kernel and non-empty ramdisk; a boot header does not encode the partition name.")
    last_end = max((int(s["offset_bytes"]) + int(s["size_bytes"]) for s in sections if s.get("present")), default=page_size)
    trailing_bytes = max(0, file_size - last_end)
    footer = _inspect_avb_footer(stream, file_size, minimum_component_end=last_end)
    if footer:
        warnings.extend(footer["validation_errors"])
        warnings.extend(footer["warnings"])
    trailing_region = _build_trailing_region(
        last_component_end=last_end, file_size=file_size, footer=footer
    )
    return {
        "operation": "android-boot-image-inspect",
        "input": str(path),
        "image_type": "ANDROID_BOOT",
        "image_role": role,
        "header_version": version,
        "header_version_name": f"v{version}",
        "header_size_bytes": header_size,
        "page_size_bytes": page_size,
        "file_size_bytes": file_size,
        "fields": fields,
        "sections": sections,
        "trailing_data_bytes": trailing_bytes,
        "trailing_region": trailing_region,
        "avb_footer_present": footer is not None,
        "avb_footer": footer,
        "warnings": warnings,
    }


def _parse_vendor_boot(stream: BinaryIO, path: Path, file_size: int) -> dict[str, Any]:
    base_header_size = VENDOR_BOOT_HEADER_V3_SIZE
    if file_size < base_header_size:
        raise BootImageError("Vendor boot header is truncated")
    header = _read_at(stream, 0, min(file_size, VENDOR_BOOT_HEADER_V4_SIZE),
                      what="vendor boot header", file_size=file_size)
    version = _u32(header, 8, "vendor_boot header_version")
    if version not in (3, 4):
        raise BootImageError(f"Unsupported vendor_boot header version: {version}")
    expected_header_size = VENDOR_BOOT_HEADER_V3_SIZE if version == 3 else VENDOR_BOOT_HEADER_V4_SIZE
    page_size = _u32(header, 12, "vendor_boot page_size")
    _check_page_size(page_size, kind="vendor_boot")
    kernel_addr = _u32(header, 16, "kernel_addr")
    ramdisk_addr = _u32(header, 20, "ramdisk_addr")
    vendor_ramdisk_size = _u32(header, 24, "vendor_ramdisk_size")
    cmdline = _cstring(header[28:2076])
    tags_addr = _u32(header, 2076, "tags_addr")
    name = _cstring(header[2080:2096])
    header_size = _u32(header, 2096, "header_size")
    if header_size != expected_header_size:
        raise BootImageError(
            f"Invalid vendor_boot header_size for v{version}: {header_size} (expected {expected_header_size})"
        )
    dtb_size = _u32(header, 2100, "dtb_size")
    dtb_addr = _u64(header, 2104, "dtb_addr")
    fields: dict[str, Any] = {
        "kernel_addr": kernel_addr,
        "ramdisk_addr": ramdisk_addr,
        "tags_addr": tags_addr,
        "name": name,
        "cmdline": cmdline,
        "dtb_addr": dtb_addr,
    }
    sections: list[dict[str, Any]] = []
    cursor = _align(header_size, page_size)
    vendor_ramdisk_offset = cursor
    sections.append(_section(stream, name="vendor_ramdisk", offset=vendor_ramdisk_offset,
                             size=vendor_ramdisk_size, file_size=file_size, kind="ramdisk"))
    cursor = _align(vendor_ramdisk_offset + vendor_ramdisk_size, page_size)
    dtb_offset = cursor
    sections.append(_section(stream, name="dtb", offset=dtb_offset, size=dtb_size, file_size=file_size))
    cursor = _align(dtb_offset + dtb_size, page_size)
    fragments: list[dict[str, Any]] = []
    table_size = 0
    table_entry_count = 0
    table_entry_size = 0
    bootconfig_size = 0
    if version >= 4:
        table_size = _u32(header, 2112, "vendor_ramdisk_table_size")
        table_entry_count = _u32(header, 2116, "vendor_ramdisk_table_entry_num")
        table_entry_size = _u32(header, 2120, "vendor_ramdisk_table_entry_size")
        bootconfig_size = _u32(header, 2124, "bootconfig_size")
        if table_size > MAX_VENDOR_RAMDISK_TABLE_SIZE:
            raise BootImageError(f"Vendor ramdisk table exceeds the safety limit ({MAX_VENDOR_RAMDISK_TABLE_SIZE} bytes)")
        if table_entry_count:
            if table_entry_size < VENDOR_RAMDISK_TABLE_ENTRY_SIZE:
                raise BootImageError(f"Vendor ramdisk table entry size is too small: {table_entry_size}")
            expected_table_bytes = table_entry_count * table_entry_size
            if expected_table_bytes > table_size:
                raise BootImageError("Vendor ramdisk table entries exceed the declared table size")
        elif table_size:
            raise BootImageError("Vendor ramdisk table has data but zero entries")
        table_offset = cursor
        sections.append(_section(stream, name="vendor_ramdisk_table", offset=table_offset,
                                 size=table_size, file_size=file_size))
        if table_size:
            table = _read_at(stream, table_offset, table_size, what="vendor ramdisk table", file_size=file_size)
            for index in range(table_entry_count):
                entry = table[index * table_entry_size:index * table_entry_size + VENDOR_RAMDISK_TABLE_ENTRY_SIZE]
                ramdisk_size, ramdisk_offset, ramdisk_type = struct.unpack_from("<III", entry, 0)
                ramdisk_name = _cstring(entry[12:44])
                board_id = list(struct.unpack_from("<16I", entry, 44))
                if ramdisk_offset > vendor_ramdisk_size or ramdisk_size > vendor_ramdisk_size - ramdisk_offset:
                    raise BootImageError(f"Vendor ramdisk table entry {index} points outside the vendor ramdisk section")
                prefix = _read_at(stream, vendor_ramdisk_offset + ramdisk_offset,
                                  min(ramdisk_size, PREVIEW_SIZE),
                                  what=f"vendor ramdisk fragment {index}", file_size=file_size) if ramdisk_size else b""
                fragments.append({
                    "index": index,
                    "name": ramdisk_name,
                    "type": VENDOR_RAMDISK_TYPES.get(ramdisk_type, f"UNKNOWN ({ramdisk_type})"),
                    "type_value": ramdisk_type,
                    "offset_bytes": ramdisk_offset,
                    "size_bytes": ramdisk_size,
                    "detected_format": _detect_ramdisk_format(prefix),
                    "board_id": board_id,
                })
        cursor = _align(table_offset + table_size, page_size)
        sections.append(_section(stream, name="bootconfig", offset=cursor, size=bootconfig_size,
                                 file_size=file_size))
        fields.update({
            "vendor_ramdisk_table_size_bytes": table_size,
            "vendor_ramdisk_table_entry_count": table_entry_count,
            "vendor_ramdisk_table_entry_size_bytes": table_entry_size,
            "bootconfig_size_bytes": bootconfig_size,
        })
        cursor = _align(cursor + bootconfig_size, page_size)
    last_end = max((int(s["offset_bytes"]) + int(s["size_bytes"]) for s in sections if s.get("present")), default=_align(header_size, page_size))
    footer = _inspect_avb_footer(stream, file_size, minimum_component_end=last_end)
    trailing_region = _build_trailing_region(
        last_component_end=last_end, file_size=file_size, footer=footer
    )
    footer_warnings = [] if footer is None else [*footer["validation_errors"], *footer["warnings"]]
    return {
        "operation": "android-boot-image-inspect",
        "input": str(path),
        "image_type": "VENDOR_BOOT",
        "image_role": "vendor_boot",
        "header_version": version,
        "header_version_name": f"v{version}",
        "header_size_bytes": header_size,
        "page_size_bytes": page_size,
        "file_size_bytes": file_size,
        "fields": fields,
        "sections": sections,
        "vendor_ramdisk_fragments": fragments,
        "trailing_data_bytes": max(0, file_size - last_end),
        "trailing_region": trailing_region,
        "avb_footer_present": footer is not None,
        "avb_footer": footer,
        "warnings": footer_warnings,
    }


def inspect_boot_image(image_path: str | os.PathLike[str]) -> dict[str, Any]:
    """Inspect an Android boot.img / init_boot.img / recovery.img / vendor_boot.img."""
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Boot image not found: {path}")
    file_size = path.stat().st_size
    if file_size < 8:
        raise BootImageError("File is too small to contain an Android boot image magic")
    with path.open("rb") as stream:
        magic = _read_at(stream, 0, 8, what="image magic", file_size=file_size)
        if magic == BOOT_MAGIC:
            return _parse_boot_image(stream, path, file_size)
        if magic == VENDOR_BOOT_MAGIC:
            return _parse_vendor_boot(stream, path, file_size)
    raise BootImageError(
        f"Unrecognized image magic. Expected {BOOT_MAGIC!r} (boot) or {VENDOR_BOOT_MAGIC!r} (vendor_boot)."
    )


def _write_json_report(path: Path, content: str, *, force: bool) -> None:
    if path.exists() and not force:
        raise FileExistsError(f"Report already exists: {path} (use --force to overwrite)")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Report directory not found: {path.parent}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temp_path, path)
        else:
            try:
                os.link(temp_path, path)
            except FileExistsError:
                raise FileExistsError(f"Report already exists: {path} (use --force to overwrite)") from None
            temp_path.unlink()
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def run_boot_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="sparse-to-raw boot-info",
        description=tr("boot_info_desc"),
    )
    parser.add_argument("image", help=tr("boot_info_input"))
    parser.add_argument("--json-report", metavar="FILE", help=tr("boot_info_json"))
    parser.add_argument("--force", action="store_true", help=tr("boot_info_force"))
    options = parser.parse_args(argv)
    try:
        source = Path(options.image).expanduser().resolve()
        report_path = Path(options.json_report).expanduser().resolve() if options.json_report else None
        if report_path is not None and report_path == source:
            raise BootImageError("JSON report path must differ from the input image")
        result = inspect_boot_image(source)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if report_path is not None:
            _write_json_report(report_path, payload, force=options.force)
            result["json_report"] = str(report_path)
            payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        print(payload, end="")
        return 0
    except (OSError, ValueError) as exc:
        print(f"{tr('error')}: {exc}", file=sys.stderr)
        return 1
