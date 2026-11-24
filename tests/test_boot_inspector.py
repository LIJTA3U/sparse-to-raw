from __future__ import annotations

import contextlib
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

from boot_inspector import (
    BOOT_MAGIC,
    VENDOR_BOOT_MAGIC,
    BootImageError,
    inspect_boot_image,
    run_boot_cli,
    _detect_kernel_format,
)


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary * boundary


def _write_legacy_boot(path: Path, version: int = 0) -> dict[str, bytes]:
    page = 2048
    kernel = bytearray(64)
    kernel[0x38:0x3C] = b"ARM\x64"
    ramdisk = b"\x1f\x8bRAMDISK"
    second = b"SECOND"
    kernel_off = page
    ramdisk_off = align(kernel_off + len(kernel), page)
    second_off = align(ramdisk_off + len(ramdisk), page)
    cursor = align(second_off + len(second), page)
    recovery = b"DTBO" if version >= 1 else b""
    recovery_off = cursor if recovery else 0
    if recovery:
        cursor = align(recovery_off + len(recovery), page)
    dtb = b"DTB!!" if version >= 2 else b""
    dtb_off = cursor

    header_size = {0: 1632, 1: 1648, 2: 1660}[version]
    blob = bytearray(max(page, dtb_off + len(dtb)))
    struct.pack_into(
        "<8s10I", blob, 0, BOOT_MAGIC,
        len(kernel), 0x10008000,
        len(ramdisk), 0x11000000,
        len(second), 0x11000000,
        0x10000100, page, version,
        (13 << 25) | (0 << 18) | (0 << 11) | (2024 - 2000) << 4 | 5,
    )
    blob[48:48 + 16] = b"test-device\x00".ljust(16, b"\x00")
    blob[64:64 + 512] = b"console=ttyS0 root=/dev/ram0\x00".ljust(512, b"\x00")
    blob[576:608] = bytes(range(32))
    blob[608:1632] = b"androidboot.test=1\x00".ljust(1024, b"\x00")
    if version >= 1:
        struct.pack_into("<IQI", blob, 1632, len(recovery), recovery_off, header_size)
    if version >= 2:
        struct.pack_into("<IQ", blob, 1648, len(dtb), 0x12000000)
    blob[kernel_off:kernel_off + len(kernel)] = kernel
    blob[ramdisk_off:ramdisk_off + len(ramdisk)] = ramdisk
    blob[second_off:second_off + len(second)] = second
    if recovery:
        blob[recovery_off:recovery_off + len(recovery)] = recovery
    if dtb:
        blob[dtb_off:dtb_off + len(dtb)] = dtb
    path.write_bytes(blob)
    return {"kernel": bytes(kernel), "ramdisk": ramdisk, "second": second, "recovery": recovery, "dtb": dtb}


def _write_modern_boot(path: Path, version: int = 3, *, kernel_size: int = 64, ramdisk: bytes = b"\x1f\x8bGENERIC") -> None:
    header_size = 1580 if version == 3 else 1584
    kernel = bytearray(kernel_size)
    if kernel_size >= 0x3C:
        kernel[0x38:0x3C] = b"ARM\x64"
    page = 4096
    kernel_off = page
    ramdisk_off = align(kernel_off + len(kernel), page)
    signature = b"SIGNATURE" if version == 4 else b""
    signature_off = align(ramdisk_off + len(ramdisk), page)
    blob = bytearray(signature_off + len(signature))
    struct.pack_into("<8s4I4II", blob, 0,
                     BOOT_MAGIC, len(kernel), len(ramdisk), 0, header_size,
                     0, 0, 0, 0, version)
    cmdline = b"androidboot.hardware=test\x00".ljust(1536, b"\x00")
    blob[44:44 + 1536] = cmdline
    if version == 4:
        struct.pack_into("<I", blob, 1580, len(signature))
    blob[kernel_off:kernel_off + len(kernel)] = kernel
    blob[ramdisk_off:ramdisk_off + len(ramdisk)] = ramdisk
    if signature:
        blob[signature_off:signature_off + len(signature)] = signature
    path.write_bytes(blob)


def _write_vendor_boot(path: Path, version: int = 3) -> None:
    page = 4096
    ramdisk_a = b"\x1f\x8bPLATFORM"
    ramdisk_b = b"\x04\x22\x4d\x18RECOVERY"
    vendor_ramdisk = ramdisk_a + ramdisk_b
    dtb = b"DTB-DATA"
    table_entries = b""
    bootconfig = b"androidboot.vendor=test\n"
    entry_size = 108
    if version == 4:
        entry_a = struct.pack("<III32s16I", len(ramdisk_a), 0, 1,
                              b"platform\x00".ljust(32, b"\x00"), *([1] + [0] * 15))
        entry_b = struct.pack("<III32s16I", len(ramdisk_b), len(ramdisk_a), 2,
                              b"recovery\x00".ljust(32, b"\x00"), *([2] + [0] * 15))
        table_entries = entry_a + entry_b
    header_size = 2112 if version == 3 else 2128
    ramdisk_off = align(header_size, page)
    dtb_off = align(ramdisk_off + len(vendor_ramdisk), page)
    table_off = align(dtb_off + len(dtb), page)
    bootconfig_off = align(table_off + len(table_entries), page)
    total = bootconfig_off + (len(bootconfig) if version == 4 else 0)
    blob = bytearray(total)
    struct.pack_into("<8s5I", blob, 0,
                     VENDOR_BOOT_MAGIC, version, page, 0x10008000, 0x11000000,
                     len(vendor_ramdisk))
    struct.pack_into("<I", blob, 2076, 0x10000100)
    blob[28:28 + 2048] = b"vendor_cmdline=1\x00".ljust(2048, b"\x00")
    blob[2080:2096] = b"test-board\x00".ljust(16, b"\x00")
    struct.pack_into("<IIQ", blob, 2096, header_size, len(dtb), 0x12000000)
    if version == 4:
        struct.pack_into("<4I", blob, 2112, len(table_entries), 2, entry_size, len(bootconfig))
    blob[ramdisk_off:ramdisk_off + len(vendor_ramdisk)] = vendor_ramdisk
    blob[dtb_off:dtb_off + len(dtb)] = dtb
    if version == 4:
        blob[table_off:table_off + len(table_entries)] = table_entries
        blob[bootconfig_off:bootconfig_off + len(bootconfig)] = bootconfig
    path.write_bytes(blob)


def _append_avb_footer(path: Path, *, vbmeta_magic: bytes = b"AVB0",
                       reserved: bytes = b"\x00" * 28, padding_after_vbmeta: bytes = b"",
                       version_major: int = 1, version_minor: int = 0) -> dict[str, int]:
    original = path.read_bytes()
    original_size = len(original)
    vbmeta_offset = align(original_size, 64)
    vbmeta = vbmeta_magic + b"V" * 60
    footer_offset = vbmeta_offset + len(vbmeta) + len(padding_after_vbmeta)
    footer = struct.pack(
        ">4sIIQQQ28s", b"AVBf", version_major, version_minor, original_size, vbmeta_offset, len(vbmeta), reserved
    )
    path.write_bytes(
        original + b"\x00" * (align(original_size, 64) - original_size)
        + vbmeta + padding_after_vbmeta + footer
    )
    return {
        "original_size": original_size,
        "vbmeta_offset": align(original_size, 64),
        "vbmeta_size": len(vbmeta),
        "footer_offset": footer_offset,
        "padding_after_vbmeta": len(padding_after_vbmeta),
    }


class BootInspectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_legacy_boot_v0_sections_and_fields(self) -> None:
        image = self.root / "boot-v0.img"
        _write_legacy_boot(image, 0)
        result = inspect_boot_image(image)
        self.assertEqual(result["image_type"], "ANDROID_BOOT")
        self.assertEqual(result["header_version"], 0)
        self.assertEqual(result["page_size_bytes"], 2048)
        self.assertEqual(result["fields"]["name"], "test-device")
        self.assertEqual(result["fields"]["os_version"]["version"], "13.0.0")
        self.assertEqual(result["fields"]["os_version"]["security_patch_level"], "2024-05")
        sections = {item["name"]: item for item in result["sections"]}
        self.assertEqual(sections["kernel"]["offset_bytes"], 2048)
        self.assertEqual(sections["kernel"]["detected_format"], "ARM64 Linux Image")
        self.assertEqual(sections["ramdisk"]["detected_format"], "gzip")

    def test_legacy_boot_v1_recovery_dtbo_offset(self) -> None:
        image = self.root / "boot-v1.img"
        _write_legacy_boot(image, 1)
        result = inspect_boot_image(image)
        sections = {item["name"]: item for item in result["sections"]}
        self.assertEqual(sections["recovery_dtbo"]["size_bytes"], 4)
        self.assertTrue(sections["second"]["present"])

    def test_legacy_boot_v2_dtb(self) -> None:
        image = self.root / "boot-v2.img"
        _write_legacy_boot(image, 2)
        result = inspect_boot_image(image)
        sections = {item["name"]: item for item in result["sections"]}
        self.assertEqual(sections["dtb"]["size_bytes"], 5)
        self.assertEqual(result["fields"]["dtb_addr"], 0x12000000)

    def test_modern_boot_v3(self) -> None:
        image = self.root / "boot-v3.img"
        _write_modern_boot(image, 3)
        result = inspect_boot_image(image)
        self.assertEqual(result["header_version"], 3)
        self.assertEqual(result["page_size_bytes"], 4096)
        self.assertEqual(result["fields"]["cmdline"], "androidboot.hardware=test")
        self.assertFalse(any(item["name"] == "boot_signature" and item["present"] for item in result["sections"]))

    def test_modern_boot_v4_signature(self) -> None:
        image = self.root / "boot-v4.img"
        _write_modern_boot(image, 4)
        result = inspect_boot_image(image)
        sections = {item["name"]: item for item in result["sections"]}
        self.assertEqual(sections["boot_signature"]["size_bytes"], 9)

    def test_kernel_gzip_signature_is_recognized(self) -> None:
        image = self.root / "boot-gzip-kernel.img"
        _write_legacy_boot(image, 2)
        blob = bytearray(image.read_bytes())
        blob[2048:2048 + 64] = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\x03".ljust(64, b"K")
        image.write_bytes(blob)
        result = inspect_boot_image(image)
        kernel = next(item for item in result["sections"] if item["name"] == "kernel")
        self.assertEqual(kernel["detected_format"], "gzip-compressed kernel payload")

    def test_kernel_compression_signatures(self) -> None:
        cases = [
            (b"\x1f\x8b\x08", "gzip-compressed kernel payload"),
            (b"BZh9", "bzip2-compressed kernel payload"),
            (b"\xfd7zXZ\x00", "XZ-compressed kernel payload"),
            (b"\x28\xb5\x2f\xfd", "Zstandard-compressed kernel payload"),
            (b"\x04\x22\x4d\x18", "LZ4 frame-compressed kernel payload"),
            (b"\x02\x21\x4c\x18", "LZ4 legacy frame-compressed kernel payload"),
            (b"\x89LZO\x00\r\n\x1a\n", "LZO (lzop)-compressed kernel payload"),
            (b"\x5d\x00\x00", "LZMA (probable)-compressed kernel payload"),
        ]
        for signature, expected in cases:
            with self.subTest(signature=signature.hex()):
                self.assertEqual(_detect_kernel_format(signature), expected)

    def test_avb_footer_fields_and_vbmeta_range_are_reported(self) -> None:
        image = self.root / "boot-with-footer.img"
        _write_legacy_boot(image, 2)
        expected = _append_avb_footer(image)
        result = inspect_boot_image(image)
        footer = result["avb_footer"]
        self.assertTrue(result["avb_footer_present"])
        self.assertEqual(footer["version_major"], 1)
        self.assertEqual(footer["version_minor"], 0)
        self.assertEqual(footer["original_image_size_bytes"], expected["original_size"])
        self.assertEqual(footer["vbmeta_offset_bytes"], expected["vbmeta_offset"])
        self.assertEqual(footer["vbmeta_size_bytes"], expected["vbmeta_size"])
        self.assertEqual(footer["vbmeta_header_magic"], "AVB0")
        self.assertTrue(footer["vbmeta_header_present"])
        self.assertEqual(footer["structural_status"], "valid")
        self.assertEqual(result["trailing_region"]["vbmeta"]["offset_bytes"], expected["vbmeta_offset"])
        self.assertEqual(result["trailing_region"]["footer_offset_bytes"], expected["footer_offset"])

    def test_avb_footer_reports_unclassified_bytes_after_vbmeta(self) -> None:
        image = self.root / "boot-footer-padding.img"
        _write_legacy_boot(image, 2)
        expected = _append_avb_footer(image, padding_after_vbmeta=b"\x00" * 4096)
        result = inspect_boot_image(image)
        self.assertEqual(
            result["trailing_region"]["unclassified_after_vbmeta_bytes"],
            expected["padding_after_vbmeta"],
        )

    def test_avb_footer_newer_major_version_is_reported_as_warning(self) -> None:
        image = self.root / "boot-footer-new-major.img"
        _write_legacy_boot(image, 2)
        _append_avb_footer(image, version_major=2)
        result = inspect_boot_image(image)
        self.assertEqual(result["avb_footer"]["structural_status"], "warning")
        self.assertTrue(any("newer than the supported" in item for item in result["avb_footer"]["warnings"]))

    def test_avb_footer_rejects_vbmeta_range_overlapping_footer(self) -> None:
        image = self.root / "boot-bad-footer-range.img"
        _write_legacy_boot(image, 2)
        original = image.read_bytes()
        vbmeta_offset = align(len(original), 64)
        vbmeta = b"AVB0" + b"V" * 60
        footer = struct.pack(
            ">4sIIQQQ28s", b"AVBf", 1, 0, len(original), vbmeta_offset, 0x10000, b"\x00" * 28
        )
        image.write_bytes(original + b"\x00" * (vbmeta_offset - len(original)) + vbmeta + footer)
        result = inspect_boot_image(image)
        self.assertEqual(result["avb_footer"]["structural_status"], "invalid")
        self.assertTrue(any("VBMeta block extends" in item for item in result["avb_footer"]["validation_errors"]))

    def test_avb_footer_rejects_vbmeta_overlapping_parsed_components(self) -> None:
        image = self.root / "boot-footer-overlaps-component.img"
        _write_legacy_boot(image, 2)
        original = image.read_bytes()
        vbmeta_offset = 2048
        vbmeta = b"AVB0" + b"V" * 60
        footer = struct.pack(
            ">4sIIQQQ28s", b"AVBf", 1, 0, len(original), vbmeta_offset, len(vbmeta), b"\x00" * 28
        )
        image.write_bytes(original + vbmeta + footer)
        result = inspect_boot_image(image)
        self.assertEqual(result["avb_footer"]["structural_status"], "invalid")
        self.assertTrue(any("overlaps the parsed boot image components" in item
                            for item in result["avb_footer"]["validation_errors"]))

    def test_avb_footer_warns_on_nonzero_reserved_bytes_and_wrong_vbmeta_magic(self) -> None:
        image = self.root / "boot-footer-warnings.img"
        _write_legacy_boot(image, 2)
        _append_avb_footer(image, vbmeta_magic=b"NOPE", reserved=b"\x01" + b"\x00" * 27)
        result = inspect_boot_image(image)
        footer = result["avb_footer"]
        self.assertEqual(footer["structural_status"], "warning")
        self.assertFalse(footer["reserved_bytes_zero"])
        self.assertFalse(footer["vbmeta_header_present"])
        self.assertGreaterEqual(len(footer["warnings"]), 2)

    def test_no_avb_footer_is_explicitly_reported(self) -> None:
        image = self.root / "boot-no-footer.img"
        _write_modern_boot(image, 3)
        result = inspect_boot_image(image)
        self.assertFalse(result["avb_footer_present"])
        self.assertIsNone(result["avb_footer"])

    def test_init_boot_role_is_marked_as_inferred(self) -> None:
        image = self.root / "init_boot.img"
        _write_modern_boot(image, 4, kernel_size=0, ramdisk=b"070701CPIO")
        result = inspect_boot_image(image)
        self.assertIn("probable init_boot", result["image_role"])
        ramdisk = next(item for item in result["sections"] if item["name"] == "ramdisk")
        self.assertEqual(ramdisk["detected_format"], "CPIO newc")

    def test_vendor_boot_v3(self) -> None:
        image = self.root / "vendor_boot-v3.img"
        _write_vendor_boot(image, 3)
        result = inspect_boot_image(image)
        self.assertEqual(result["image_type"], "VENDOR_BOOT")
        self.assertEqual(result["header_version"], 3)
        self.assertEqual(result["fields"]["name"], "test-board")
        self.assertEqual(len(result["sections"]), 2)

    def test_vendor_boot_v4_ramdisk_table_and_bootconfig(self) -> None:
        image = self.root / "vendor_boot-v4.img"
        _write_vendor_boot(image, 4)
        result = inspect_boot_image(image)
        self.assertEqual(result["header_version"], 4)
        self.assertEqual(result["fields"]["vendor_ramdisk_table_entry_count"], 2)
        fragments = result["vendor_ramdisk_fragments"]
        self.assertEqual([item["name"] for item in fragments], ["platform", "recovery"])
        self.assertEqual([item["type"] for item in fragments], ["PLATFORM", "RECOVERY"])
        self.assertEqual([item["detected_format"] for item in fragments], ["gzip", "LZ4 frame"])
        sections = {item["name"]: item for item in result["sections"]}
        self.assertTrue(sections["bootconfig"]["present"])

    def test_rejects_unknown_magic(self) -> None:
        image = self.root / "unknown.img"
        image.write_bytes(b"NOTANDROID" + b"\x00" * 2000)
        with self.assertRaises(BootImageError):
            inspect_boot_image(image)

    def test_rejects_invalid_page_size(self) -> None:
        image = self.root / "bad-page.img"
        _write_legacy_boot(image, 0)
        blob = bytearray(image.read_bytes())
        struct.pack_into("<I", blob, 36, 3000)
        image.write_bytes(blob)
        with self.assertRaisesRegex(BootImageError, "page size"):
            inspect_boot_image(image)

    def test_rejects_section_outside_file(self) -> None:
        image = self.root / "truncated.img"
        _write_legacy_boot(image, 0)
        blob = bytearray(image.read_bytes())
        struct.pack_into("<I", blob, 8, 0xFFFFFFF0)
        image.write_bytes(blob)
        with self.assertRaises(BootImageError):
            inspect_boot_image(image)

    def test_rejects_legacy_header_size_mismatch(self) -> None:
        image = self.root / "bad-header-size.img"
        _write_legacy_boot(image, 2)
        blob = bytearray(image.read_bytes())
        struct.pack_into("<I", blob, 1644, 1650)
        image.write_bytes(blob)
        with self.assertRaisesRegex(BootImageError, "header_size for v2"):
            inspect_boot_image(image)

    def test_rejects_invalid_recovery_dtbo_offset(self) -> None:
        image = self.root / "bad-dtbo-offset.img"
        _write_legacy_boot(image, 1)
        blob = bytearray(image.read_bytes())
        struct.pack_into("<Q", blob, 1636, 1024)
        image.write_bytes(blob)
        with self.assertRaisesRegex(BootImageError, "recovery_dtbo_offset"):
            inspect_boot_image(image)

    def test_rejects_vendor_boot_table_entry_outside_ramdisk(self) -> None:
        image = self.root / "bad-vendor-table.img"
        _write_vendor_boot(image, 4)
        blob = bytearray(image.read_bytes())
        # The first table entry starts after the aligned header, ramdisk and DTB.
        table_offset = align(align(2128, 4096) + len(b"\x1f\x8bPLATFORM\x04\x22\x4d\x18RECOVERY"), 4096)
        table_offset = align(table_offset + len(b"DTB-DATA"), 4096)
        struct.pack_into("<I", blob, table_offset + 4, 0xFFFFFF00)
        image.write_bytes(blob)
        with self.assertRaisesRegex(BootImageError, "outside the vendor ramdisk"):
            inspect_boot_image(image)

    def test_cli_writes_json_report_without_overwriting(self) -> None:
        image = self.root / "boot.img"
        _write_modern_boot(image, 4)
        report = self.root / "boot-report.json"
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(run_boot_cli([str(image), "--json-report", str(report)]), 0)
        parsed = json.loads(report.read_text(encoding="utf-8"))
        self.assertEqual(parsed["operation"], "android-boot-image-inspect")
        self.assertIn('"header_version": 4', output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_boot_cli([str(image), "--json-report", str(report)]), 1)

    def test_cli_rejects_report_path_equal_to_input(self) -> None:
        image = self.root / "boot.img"
        _write_modern_boot(image, 3)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_boot_cli([str(image), "--json-report", str(image)]), 1)


if __name__ == "__main__":
    unittest.main()
