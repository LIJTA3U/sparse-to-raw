from __future__ import annotations

import bz2
import contextlib
import gzip
import io
import json
import lzma
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from boot_inspector import BOOT_MAGIC, VENDOR_BOOT_MAGIC
from ramdisk_inspector import (
    MAX_UNPACKED_BYTES,
    RamdiskCancelled,
    RamdiskError,
    _xxhash32,
    extract_ramdisk,
    inspect_ramdisk,
    read_ramdisk_file,
    run_ramdisk_cli,
)


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary * boundary


def cpio_record(name: str, data: bytes = b"", *, mode: int = 0o100644,
                inode: int = 1, nlink: int = 1, crc: bool = False) -> bytes:
    name_bytes = name.encode("utf-8") + b"\x00"
    magic = b"070702" if crc else b"070701"
    fields = [inode, mode, 0, 0, nlink, 1_700_000_000, len(data),
              0, 0, 0, 0, len(name_bytes), (sum(data) & 0xFFFFFFFF) if crc else 0]
    header = magic + b"".join(f"{value:08X}".encode("ascii") for value in fields)
    record = header + name_bytes
    record += b"\x00" * ((-len(record)) % 4)
    record += data
    record += b"\x00" * ((-len(record)) % 4)
    return record


def cpio_archive(records: list[tuple[str, bytes, int, int, int]], *, crc: bool = False) -> bytes:
    body = b"".join(cpio_record(name, data, mode=mode, inode=inode, nlink=nlink, crc=crc)
                    for name, data, mode, inode, nlink in records)
    return body + cpio_record("TRAILER!!!", b"", mode=0, inode=0, nlink=1, crc=crc)


def make_boot_v2(path: Path, ramdisk_payload: bytes) -> None:
    page = 2048
    kernel = bytearray(64)
    kernel[0x38:0x3C] = b"ARM\x64"
    ramdisk_offset = page * 2
    header_size = 1660
    blob = bytearray(ramdisk_offset + len(ramdisk_payload))
    os_version = (10 << 25) | ((2021 - 2000) << 4) | 8
    struct.pack_into("<8s10I", blob, 0, BOOT_MAGIC,
                     len(kernel), 0x10008000, len(ramdisk_payload), 0x11000000,
                     0, 0x11000000, 0x10000100, page, 2, os_version)
    blob[48:64] = b"test-device\x00".ljust(16, b"\x00")
    blob[64:576] = b"console=ttyS0\x00".ljust(512, b"\x00")
    blob[608:1632] = b"androidboot.test=1\x00".ljust(1024, b"\x00")
    struct.pack_into("<IQI", blob, 1632, 0, 0, header_size)
    struct.pack_into("<IQ", blob, 1648, 0, 0x12000000)
    blob[page:page + len(kernel)] = kernel
    blob[ramdisk_offset:ramdisk_offset + len(ramdisk_payload)] = ramdisk_payload
    path.write_bytes(blob)


def make_vendor_boot_v4(path: Path, fragments: list[tuple[str, bytes, int]]) -> None:
    page = 4096
    header_size = 2128
    dtb = b"DTB-TEST"
    bootconfig = b"androidboot.test=1\n"
    ramdisk_parts: list[bytes] = []
    entries: list[bytes] = []
    cursor = 0
    for name, payload, kind in fragments:
        ramdisk_parts.append(payload)
        name_bytes = name.encode("ascii")[:31] + b"\x00"
        name_bytes = name_bytes.ljust(32, b"\x00")
        entries.append(struct.pack("<III32s16I", len(payload), cursor, kind,
                                   name_bytes, *([0] * 16)))
        cursor += len(payload)
    vendor_ramdisk = b"".join(ramdisk_parts)
    table = b"".join(entries)
    ramdisk_offset = align(header_size, page)
    dtb_offset = align(ramdisk_offset + len(vendor_ramdisk), page)
    table_offset = align(dtb_offset + len(dtb), page)
    bootconfig_offset = align(table_offset + len(table), page)
    blob = bytearray(bootconfig_offset + len(bootconfig))
    struct.pack_into("<8s5I", blob, 0, VENDOR_BOOT_MAGIC, 4, page,
                     0x10008000, 0x11000000, len(vendor_ramdisk))
    blob[28:28 + 2048] = b"vendor_cmdline=1\x00".ljust(2048, b"\x00")
    blob[2080:2096] = b"test-board\x00".ljust(16, b"\x00")
    struct.pack_into("<IIQ", blob, 2096, header_size, len(dtb), 0x12000000)
    struct.pack_into("<4I", blob, 2112, len(table), len(entries), 108, len(bootconfig))
    blob[ramdisk_offset:ramdisk_offset + len(vendor_ramdisk)] = vendor_ramdisk
    blob[dtb_offset:dtb_offset + len(dtb)] = dtb
    blob[table_offset:table_offset + len(table)] = table
    blob[bootconfig_offset:bootconfig_offset + len(bootconfig)] = bootconfig
    path.write_bytes(blob)


def lz4_uncompressed_frame(payload: bytes) -> bytes:
    flg = 0x7C  # v1, independent blocks, block checksum, content size, content checksum
    bd = 0x40   # 64 KiB maximum block
    descriptor = bytes((flg, bd)) + struct.pack("<Q", len(payload))
    hc = (_xxhash32(descriptor) >> 8) & 0xFF
    block = struct.pack("<I", 0x80000000 | len(payload)) + payload
    block += struct.pack("<I", _xxhash32(payload))
    return (b"\x04\x22\x4d\x18" + descriptor + bytes((hc,)) + block
            + b"\x00\x00\x00\x00" + struct.pack("<I", _xxhash32(payload)))


class RamdiskInspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.records = [
            (".", b"", 0o040755, 1, 2),
            ("init", b"#!/init\n", 0o100755, 2, 1),
            ("etc", b"", 0o040755, 3, 2),
            ("etc/fstab", b"/dev/block/test / ext4 ro 0 0\n", 0o100644, 4, 1),
            ("sbin", b"../system/bin", 0o120777, 5, 1),
        ]
        self.cpio = cpio_archive(self.records)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_xxhash32_known_vectors(self) -> None:
        self.assertEqual(_xxhash32(b""), 0x02CC5D05)
        self.assertEqual(_xxhash32(b"a"), 0x550D7456)
        self.assertEqual(_xxhash32(b"abc"), 0x32D153FF)

    def test_inspect_standalone_gzip_newc(self) -> None:
        image = self.root / "ramdisk.cpio.gz"
        image.write_bytes(gzip.compress(self.cpio))
        report = inspect_ramdisk(image)
        self.assertEqual(report["compression_format"], "gzip")
        self.assertEqual(report["cpio_formats"], ["newc"])
        self.assertEqual(report["entry_count"], len(self.records))
        self.assertEqual(report["file_count"], 2)
        self.assertEqual(report["directory_count"], 2)
        self.assertEqual(report["symlink_count"], 1)
        self.assertNotIn("data_offset_bytes", report["entries"][0])

    def test_inspect_ramdisk_inside_boot_img(self) -> None:
        image = self.root / "boot.img"
        make_boot_v2(image, gzip.compress(self.cpio))
        report = inspect_ramdisk(image)
        self.assertEqual(report["image_type"], "ANDROID_BOOT")
        self.assertEqual(report["section_name"], "ramdisk")
        self.assertEqual(report["compression_format"], "gzip")
        self.assertEqual(report["entry_count"], len(self.records))

    def test_inspect_vendor_boot_v4_fragment_by_index(self) -> None:
        image = self.root / "vendor_boot.img"
        first = gzip.compress(cpio_archive([("first", b"A", 0o100644, 1, 1)]))
        second = gzip.compress(cpio_archive([("second", b"B", 0o100644, 2, 1)]))
        make_vendor_boot_v4(image, [("platform", first, 1), ("recovery", second, 2)])
        with self.assertRaisesRegex(RamdiskError, "select one"):
            inspect_ramdisk(image)
        report = inspect_ramdisk(image, fragment_index=1)
        self.assertEqual(report["fragment_name"], "recovery")
        self.assertEqual(report["fragment_type"], "RECOVERY")
        self.assertEqual(report["entries"][0]["path"], "second")


    def test_preview_reads_text_file_without_extracting_archive(self) -> None:
        image = self.root / "ramdisk-preview.gz"
        image.write_bytes(gzip.compress(self.cpio))

        result = read_ramdisk_file(image, "etc/fstab")

        self.assertTrue(result["is_text"])
        self.assertEqual(result["path"], "etc/fstab")
        self.assertIn("/dev/block/test / ext4 ro 0 0", result["text_preview"])
        self.assertFalse(result["truncated"])
        self.assertFalse((self.root / "etc").exists())

    def test_preview_recognizes_vendor_fstab_names_as_text(self) -> None:
        content = (
            b"# Android fstab for vendor device\r\n"
            b"/dev/block/by-name/system /system ext4 ro wait,logical\r\n"
            b"/dev/block/by-name/vendor /vendor ext4 ro wait,logical\r\n"
        )
        archive = cpio_archive([
            ("fstab.mt6762", content, 0o100640, 1, 1),
            ("fstab.mt6765", content.replace(b"mt6762", b"mt6765"), 0o100640, 2, 1),
        ])
        image = self.root / "blackview-fstab.cpio.gz"
        image.write_bytes(gzip.compress(archive))

        for name in ("fstab.mt6762", "fstab.mt6765"):
            with self.subTest(name=name):
                result = read_ramdisk_file(image, name)
                self.assertTrue(result["is_text"])
                self.assertTrue(result["text_detection_hint"])
                self.assertIn("/system ext4", result["text_preview"])
                self.assertFalse(result["truncated"])

    def test_preview_uses_text_hint_for_vendor_config_with_non_utf8_bytes(self) -> None:
        content = b"# vendor config\nkey=value-\xff\n"
        archive = cpio_archive([("fstab.vendor", content, 0o100640, 1, 1)])
        image = self.root / "vendor-config-bytes.cpio.gz"
        image.write_bytes(gzip.compress(archive))

        result = read_ramdisk_file(image, "fstab.vendor")

        self.assertTrue(result["is_text"])
        self.assertIn("key=value-", result["text_preview"])
        self.assertIn("replacement characters", result["encoding"])

    def test_preview_is_bounded_and_marks_truncated_text(self) -> None:
        large_text = b"line=1\n" * 200
        archive = cpio_archive([("large.rc", large_text, 0o100644, 1, 1)])
        image = self.root / "large.gz"
        image.write_bytes(gzip.compress(archive))

        result = read_ramdisk_file(image, "large.rc", preview_limit_bytes=128)

        self.assertTrue(result["is_text"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["preview_bytes"], 128)
        self.assertLessEqual(len(result["text_preview"].encode("utf-8")), 128)

    def test_preview_supports_bom_marked_utf16_text(self) -> None:
        content = "ro.secure=1\r\nro.debuggable=0\r\n".encode("utf-16-le")
        archive = cpio_archive([("default.prop", b"\xff\xfe" + content, 0o100644, 1, 1)])
        image = self.root / "utf16.gz"
        image.write_bytes(gzip.compress(archive))

        result = read_ramdisk_file(image, "default.prop")

        self.assertTrue(result["is_text"])
        self.assertEqual(result["encoding"], "utf-16-le")
        self.assertIn("ro.secure=1", result["text_preview"])

    def test_preview_binary_file_returns_hex_not_decoded_text(self) -> None:
        archive = cpio_archive([("logo.bin", b"\x00\xff\x01ABC", 0o100644, 1, 1)])
        image = self.root / "binary.gz"
        image.write_bytes(gzip.compress(archive))

        result = read_ramdisk_file(image, "logo.bin")

        self.assertFalse(result["is_text"])
        self.assertIn("00 FF 01 41 42 43", result["hex_preview"])
        self.assertIsNone(result["text_preview"])

    def test_preview_rejects_directory_symlink_and_unsafe_path(self) -> None:
        image = self.root / "ramdisk-preview.gz"
        image.write_bytes(gzip.compress(self.cpio))
        with self.assertRaisesRegex(RamdiskError, "Only regular files"):
            read_ramdisk_file(image, "etc")
        with self.assertRaisesRegex(RamdiskError, "Only regular files"):
            read_ramdisk_file(image, "sbin")
        with self.assertRaisesRegex(RamdiskError, "Unsafe or empty"):
            read_ramdisk_file(image, "../outside")

    def test_preview_uses_last_entry_from_concatenated_archives(self) -> None:
        first = cpio_archive([("init.rc", b"first\n", 0o100644, 1, 1)])
        second = cpio_archive([("init.rc", b"second\n", 0o100644, 2, 1)])
        image = self.root / "overlay.gz"
        image.write_bytes(gzip.compress(first + second))

        result = read_ramdisk_file(image, "init.rc")

        self.assertEqual(result["text_preview"], "second\n")

    def test_preview_reads_text_file_without_extracting_archive(self) -> None:
        image = self.root / "ramdisk-preview.gz"
        image.write_bytes(gzip.compress(self.cpio))

        result = read_ramdisk_file(image, "etc/fstab")

        self.assertTrue(result["is_text"])
        self.assertEqual(result["path"], "etc/fstab")
        self.assertIn("/dev/block/test / ext4 ro 0 0", result["text_preview"])
        self.assertFalse(result["truncated"])
        self.assertFalse((self.root / "etc").exists())

    def test_preview_is_bounded_and_marks_truncated_text(self) -> None:
        large_text = b"line=1\n" * 200
        archive = cpio_archive([("large.rc", large_text, 0o100644, 1, 1)])
        image = self.root / "large.gz"
        image.write_bytes(gzip.compress(archive))

        result = read_ramdisk_file(image, "large.rc", preview_limit_bytes=128)

        self.assertTrue(result["is_text"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["preview_bytes"], 128)
        self.assertLessEqual(len(result["text_preview"].encode("utf-8")), 128)

    def test_preview_binary_file_returns_hex_not_decoded_text(self) -> None:
        archive = cpio_archive([("logo.bin", b"\x00\xff\x01ABC", 0o100644, 1, 1)])
        image = self.root / "binary.gz"
        image.write_bytes(gzip.compress(archive))

        result = read_ramdisk_file(image, "logo.bin")

        self.assertFalse(result["is_text"])
        self.assertIn("00 FF 01 41 42 43", result["hex_preview"])
        self.assertIsNone(result["text_preview"])

    def test_preview_rejects_directory_symlink_and_unsafe_path(self) -> None:
        image = self.root / "ramdisk-preview.gz"
        image.write_bytes(gzip.compress(self.cpio))
        with self.assertRaisesRegex(RamdiskError, "Only regular files"):
            read_ramdisk_file(image, "etc")
        with self.assertRaisesRegex(RamdiskError, "Only regular files"):
            read_ramdisk_file(image, "sbin")
        with self.assertRaisesRegex(RamdiskError, "Unsafe or empty"):
            read_ramdisk_file(image, "../outside")

    def test_preview_uses_last_entry_from_concatenated_archives(self) -> None:
        first = cpio_archive([("init.rc", b"first\n", 0o100644, 1, 1)])
        second = cpio_archive([("init.rc", b"second\n", 0o100644, 2, 1)])
        image = self.root / "overlay.gz"
        image.write_bytes(gzip.compress(first + second))

        result = read_ramdisk_file(image, "init.rc")

        self.assertEqual(result["text_preview"], "second\n")

    def test_inspect_standalone_uncompressed_cpio(self) -> None:
        image = self.root / "ramdisk.cpio"
        image.write_bytes(self.cpio)
        report = inspect_ramdisk(image)
        self.assertEqual(report["compression_format"], "CPIO newc")
        self.assertEqual(report["cpio_formats"], ["newc"])
        self.assertEqual(report["entry_count"], len(self.records))

    def test_lz4_legacy_uncompressed_block(self) -> None:
        image = self.root / "ramdisk-legacy.lz4"
        payload = self.cpio
        image.write_bytes(b"\x02\x21\x4c\x18" + struct.pack("<I", 0x80000000 | len(payload))
                          + payload + b"\x00\x00\x00\x00")
        report = inspect_ramdisk(image)
        self.assertEqual(report["compression_format"], "LZ4 legacy frame")
        self.assertEqual(report["entry_count"], len(self.records))

    def test_inspection_cancellation_is_propagated(self) -> None:
        image = self.root / "cancel.cpio"
        image.write_bytes(self.cpio)
        with self.assertRaises(RamdiskCancelled):
            inspect_ramdisk(image, cancel_requested=lambda: True)

    def test_bzip2_and_xz_and_lzma_alone(self) -> None:
        for suffix, payload, expected in (
            ("bz2", bz2.compress(self.cpio), "bzip2"),
            ("xz", lzma.compress(self.cpio, format=lzma.FORMAT_XZ), "XZ"),
            ("lzma", lzma.compress(self.cpio, format=lzma.FORMAT_ALONE), "LZMA-alone"),
        ):
            image = self.root / f"ramdisk.{suffix}"
            image.write_bytes(payload)
            report = inspect_ramdisk(image)
            self.assertEqual(report["compression_format"], expected)

    def test_lz4_frame_uncompressed_block(self) -> None:
        image = self.root / "ramdisk.lz4"
        image.write_bytes(lz4_uncompressed_frame(self.cpio))
        report = inspect_ramdisk(image)
        self.assertEqual(report["compression_format"], "LZ4 frame")
        self.assertEqual(report["entry_count"], len(self.records))

    def test_crc_cpio_checksum_is_verified(self) -> None:
        archive = cpio_archive([("hello", b"content", 0o100644, 1, 1)], crc=True)
        image = self.root / "ramdisk.cpio"
        image.write_bytes(archive)
        report = inspect_ramdisk(image)
        self.assertEqual(report["cpio_formats"], ["crc"])
        self.assertEqual(report["entries"][0]["checksum_status"], "match")
        damaged = bytearray(archive)
        damaged[archive.index(b"content")] ^= 1
        image.write_bytes(damaged)
        with self.assertRaisesRegex(RamdiskError, "CRC checksum mismatch"):
            inspect_ramdisk(image)

    def test_concatenated_cpio_archives_are_listed(self) -> None:
        first = cpio_archive([("first", b"1", 0o100644, 1, 1)])
        second = cpio_archive([("second", b"2", 0o100644, 2, 1)])
        image = self.root / "joined.cpio.gz"
        image.write_bytes(gzip.compress(first + second))
        report = inspect_ramdisk(image)
        self.assertEqual(report["archive_count"], 2)
        self.assertEqual([item["path"] for item in report["entries"]], ["first", "second"])

    def test_extract_files_and_symlink_manifest_safely(self) -> None:
        image = self.root / "ramdisk.gz"
        image.write_bytes(gzip.compress(self.cpio))
        output = self.root / "extracted"
        result = extract_ramdisk(image, output)
        self.assertTrue((output / "init").is_file())
        self.assertEqual((output / "init").read_bytes(), b"#!/init\n")
        self.assertEqual((output / "etc" / "fstab").read_bytes(), b"/dev/block/test / ext4 ro 0 0\n")
        self.assertTrue((output / "SYMLINKS.txt").is_file())
        self.assertIn("sbin -> ../system/bin", (output / "SYMLINKS.txt").read_text(encoding="utf-8"))
        self.assertEqual(result["extracted_files"], 2)
        self.assertEqual(result["symlinks_listed"], 1)

    def test_extract_selected_directory_includes_descendants(self) -> None:
        image = self.root / "ramdisk-directory-selection.gz"
        image.write_bytes(gzip.compress(self.cpio))
        output = self.root / "selected-directory"

        result = extract_ramdisk(image, output, include_paths={"etc"})

        self.assertTrue((output / "etc" / "fstab").is_file())
        self.assertFalse((output / "init").exists())
        self.assertEqual(result["extracted_files"], 1)

    def test_extract_selected_file_only(self) -> None:
        image = self.root / "ramdisk.gz"
        image.write_bytes(gzip.compress(self.cpio))
        output = self.root / "selected"
        extract_ramdisk(image, output, include_paths={"etc/fstab"})
        self.assertTrue((output / "etc" / "fstab").is_file())
        self.assertFalse((output / "init").exists())

    def test_unsafe_paths_are_not_extracted(self) -> None:
        archive = cpio_archive([
            ("../escape.txt", b"bad", 0o100644, 1, 1),
            ("safe.txt", b"ok", 0o100644, 2, 1),
        ])
        image = self.root / "unsafe.cpio.gz"
        image.write_bytes(gzip.compress(archive))
        report = inspect_ramdisk(image)
        self.assertTrue(any(entry["unsafe_path"] for entry in report["entries"]))
        output = self.root / "safe-output"
        result = extract_ramdisk(image, output)
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertTrue((output / "safe.txt").is_file())
        self.assertTrue((output / "SPECIAL_FILES.txt").is_file())
        self.assertEqual(result["special_entries_skipped"], 1)

    def test_extract_existing_nonempty_directory_is_protected(self) -> None:
        image = self.root / "ramdisk.gz"
        image.write_bytes(gzip.compress(self.cpio))
        output = self.root / "existing"
        output.mkdir()
        (output / "keep.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "not empty"):
            extract_ramdisk(image, output)
        self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "keep")

    def test_decompression_limit_is_enforced(self) -> None:
        image = self.root / "large.gz"
        image.write_bytes(gzip.compress(self.cpio))
        with self.assertRaisesRegex(RamdiskError, "safety limit"):
            inspect_ramdisk(image, max_unpacked_bytes=32)

    def test_unknown_and_truncated_cpio_are_rejected(self) -> None:
        for payload in (b"not a ramdisk", b"070701short"):
            image = self.root / "bad.ramdisk"
            image.write_bytes(payload)
            with self.assertRaises(RamdiskError):
                inspect_ramdisk(image)

    def test_json_cli_info(self) -> None:
        image = self.root / "ramdisk.gz"
        image.write_bytes(gzip.compress(self.cpio))
        report = self.root / "report.json"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = run_ramdisk_cli("ramdisk-info", [str(image), "--json-report", str(report)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["entry_count"], len(self.records))
        self.assertIn("android-ramdisk-inspect", stdout.getvalue())

    def test_cli_extract(self) -> None:
        image = self.root / "ramdisk.gz"
        image.write_bytes(gzip.compress(self.cpio))
        output = self.root / "cli-extracted"
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = run_ramdisk_cli("ramdisk-extract", [str(image), "--output-dir", str(output), "--include", "init"])
        self.assertEqual(code, 0)
        self.assertTrue((output / "init").is_file())
        self.assertFalse((output / "etc" / "fstab").exists())


    def test_extracts_hardlink_entries_with_shared_payload(self) -> None:
        archive = cpio_archive([
            ("bin/tool-link", b"", 0o100755, 77, 2),
            ("bin/tool", b"ELF-test", 0o100755, 77, 2),
        ])
        image = self.root / "hardlinks.cpio.gz"
        image.write_bytes(gzip.compress(archive))
        output = self.root / "hardlinks-out"
        result = extract_ramdisk(image, output)
        self.assertEqual((output / "bin" / "tool-link").read_bytes(), b"ELF-test")
        self.assertEqual((output / "bin" / "tool").read_bytes(), b"ELF-test")
        self.assertEqual(result["extracted_files"], 2)

    def test_output_directory_must_not_contain_source_image(self) -> None:
        image = self.root / "inside-source-dir.cpio.gz"
        image.write_bytes(gzip.compress(self.cpio))
        with self.assertRaisesRegex(RamdiskError, "must not contain"):
            extract_ramdisk(image, self.root)

    def test_existing_json_report_is_rejected_before_extraction(self) -> None:
        image = self.root / "ramdisk.gz"
        image.write_bytes(gzip.compress(self.cpio))
        output = self.root / "must-not-be-created"
        report = self.root / "existing-report.json"
        report.write_text("keep", encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = run_ramdisk_cli("ramdisk-extract", [
                str(image), "--output-dir", str(output), "--json-report", str(report)
            ])
        self.assertEqual(code, 1)
        self.assertFalse(output.exists())
        self.assertEqual(report.read_text(encoding="utf-8"), "keep")

    def test_json_report_cannot_overwrite_input(self) -> None:
        image = self.root / "ramdisk.gz"
        payload = gzip.compress(self.cpio)
        image.write_bytes(payload)
        with contextlib.redirect_stderr(io.StringIO()):
            code = run_ramdisk_cli("ramdisk-info", [str(image), "--json-report", str(image)])
        self.assertEqual(code, 1)
        self.assertEqual(image.read_bytes(), payload)


if __name__ == "__main__":
    unittest.main()
