from __future__ import annotations

import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from qfil_xml import (
    QFILManifestError,
    analyze_qfil_package,
    build_qfil_raw_images,
)
from sparse_to_raw import HEADER_FMT, MAGIC, main


CHUNK_FMT = "<HHII"


def _make_sparse(raw: bytes, block_size: int = 4) -> bytes:
    if len(raw) % block_size:
        raise ValueError("test payload must be block aligned")
    total_blocks = len(raw) // block_size
    chunks = struct.pack(CHUNK_FMT, 0xCAC1, 0, total_blocks, 12 + len(raw)) + raw
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        1,
        0,
        struct.calcsize(HEADER_FMT),
        struct.calcsize(CHUNK_FMT),
        block_size,
        total_blocks,
        1,
        zlib.crc32(raw) & 0xFFFFFFFF,
    )
    return header + chunks


class QFILXMLTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.manifest_dir = self.root / "firmware" / "xml"
        self.images_dir = self.root / "firmware" / "images"
        self.manifest_dir.mkdir(parents=True)
        self.images_dir.mkdir(parents=True)
        self.raw_program = self.manifest_dir / "rawprogram0.xml"
        self.patch_xml = self.manifest_dir / "patch0.xml"
        self.raw_source = self.images_dir / "boot.img"
        self.sparse_source = self.images_dir / "system.img"
        self.raw_data = b"RAWDATA!"
        self.sparse_data = b"SPARSE!!"
        self.raw_source.write_bytes(self.raw_data)
        self.sparse_source.write_bytes(_make_sparse(self.sparse_data))
        self.raw_program.write_text(
            '''<?xml version="1.0"?>
<data>
  <program SECTOR_SIZE_IN_BYTES="4" filename="boot.img" label="boot" num_partition_sectors="2" physical_partition_number="0" start_sector="1" file_sector_offset="0" sparse="false" />
  <program SECTOR_SIZE_IN_BYTES="4" filename="system.img" label="system" num_partition_sectors="2" physical_partition_number="0" start_sector="4" file_sector_offset="0" sparse="true" />
  <erase SECTOR_SIZE_IN_BYTES="4" label="userdata-wipe" num_partition_sectors="1" physical_partition_number="0" start_sector="0" />
</data>
''',
            encoding="utf-8",
        )
        self.patch_xml.write_text(
            '''<?xml version="1.0"?>
<data><patch SECTOR_SIZE_IN_BYTES="4" byte_offset="0" filename="DISK" physical_partition_number="0" size_in_bytes="4" start_sector="0" value="0x12345678" what="test patch" /></data>
''',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_analyze_program_erase_patch_and_search(self) -> None:
        report = analyze_qfil_package(
            [self.raw_program],
            [self.patch_xml],
            search_dirs=[self.root / "firmware"],
        )
        self.assertEqual(report["format"], "Qualcomm QFIL XML")
        self.assertEqual(report["summary"]["program_operations"], 2)
        self.assertEqual(report["summary"]["erase_operations"], 1)
        self.assertEqual(report["summary"]["resolved_files"], 2)
        self.assertEqual(report["summary"]["patch_operations"], 1)
        self.assertFalse(report["patches_applied"])
        self.assertEqual(report["programs"][0]["source_status"], "found_by_search")
        self.assertEqual(report["programs"][1]["source"], str(self.sparse_source.resolve()))
        self.assertEqual(report["partitions"][0]["label"], "boot")

    def test_build_raw_image_with_raw_sparse_and_erase_ranges(self) -> None:
        out_dir = self.root / "out"
        report = build_qfil_raw_images(
            [self.raw_program],
            out_dir,
            [self.patch_xml],
            search_dirs=[self.root / "firmware"],
        )
        self.assertEqual(report["output_count"], 1)
        self.assertFalse(report["patches_applied"])
        output = out_dir / "physical_partition_0.raw"
        expected = b"\x00" * 4 + self.raw_data + b"\x00" * 4 + self.sparse_data
        self.assertEqual(output.read_bytes(), expected)
        self.assertEqual(report["outputs"][0]["size_bytes"], len(expected))
        self.assertEqual(len(report["outputs"][0]["sha256"]), 64)

    def test_existing_output_is_preserved_without_force(self) -> None:
        out_dir = self.root / "out"
        out_dir.mkdir()
        target = out_dir / "physical_partition_0.raw"
        target.write_bytes(b"KEEP")
        with self.assertRaises(FileExistsError):
            build_qfil_raw_images(
                [self.raw_program], out_dir, search_dirs=[self.root / "firmware"]
            )
        self.assertEqual(target.read_bytes(), b"KEEP")

    def test_force_replaces_existing_output_after_successful_assembly(self) -> None:
        out_dir = self.root / "out"
        out_dir.mkdir()
        target = out_dir / "physical_partition_0.raw"
        target.write_bytes(b"OLD")
        build_qfil_raw_images(
            [self.raw_program], out_dir, search_dirs=[self.root / "firmware"], force=True
        )
        self.assertNotEqual(target.read_bytes(), b"OLD")

    def test_missing_source_is_reported_and_blocks_assembly(self) -> None:
        xml = self.manifest_dir / "missing.xml"
        xml.write_text(
            '<data><program filename="absent.bin" start_sector="0" num_partition_sectors="1" /></data>',
            encoding="utf-8",
        )
        report = analyze_qfil_package([xml])
        self.assertEqual(report["summary"]["missing_files"], 1)
        with self.assertRaisesRegex(QFILManifestError, "could not be resolved"):
            build_qfil_raw_images([xml], self.root / "out")

    def test_ambiguous_search_result_is_not_chosen_arbitrarily(self) -> None:
        duplicate = self.root / "second" / "boot.img"
        duplicate.parent.mkdir()
        duplicate.write_bytes(b"ANOTHER!")
        report = analyze_qfil_package(
            [self.raw_program], search_dirs=[self.root / "firmware", self.root / "second"]
        )
        entry = next(item for item in report["programs"] if item["label"] == "boot")
        self.assertEqual(entry["source_status"], "ambiguous")
        self.assertEqual(len(entry["source_candidates"]), 2)

    def test_end_relative_sector_expression_requires_disk_size_for_build(self) -> None:
        xml = self.manifest_dir / "end-relative.xml"
        xml.write_text(
            '<data><program filename="boot.img" start_sector="NUM_DISK_SECTORS-2" num_partition_sectors="2" physical_partition_number="0" SECTOR_SIZE_IN_BYTES="4" /></data>',
            encoding="utf-8",
        )
        report = analyze_qfil_package([xml], search_dirs=[self.root / "firmware"])
        self.assertTrue(any("--disk-sectors 0=COUNT" in item for item in report["warnings"]))
        with self.assertRaisesRegex(QFILManifestError, "provide --disk-sectors"):
            build_qfil_raw_images([xml], self.root / "out", search_dirs=[self.root / "firmware"])
        out = build_qfil_raw_images(
            [xml], self.root / "out", search_dirs=[self.root / "firmware"], disk_sectors={0: 10}
        )
        self.assertEqual(out["outputs"][0]["sector_count"], 10)
        self.assertEqual((self.root / "out" / "physical_partition_0.raw").stat().st_size, 40)

    def test_overlapping_program_ranges_are_rejected_by_default(self) -> None:
        xml = self.manifest_dir / "overlap.xml"
        xml.write_text(
            '''<data>
<program filename="boot.img" label="one" start_sector="0" num_partition_sectors="2" SECTOR_SIZE_IN_BYTES="4" />
<program filename="boot.img" label="two" start_sector="1" num_partition_sectors="2" SECTOR_SIZE_IN_BYTES="4" />
</data>''',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(QFILManifestError, "Overlapping"):
            build_qfil_raw_images([xml], self.root / "out", search_dirs=[self.root / "firmware"])

    def test_dtd_and_entity_declarations_are_rejected(self) -> None:
        xml = self.manifest_dir / "unsafe.xml"
        xml.write_text(
            '<!DOCTYPE data [<!ENTITY x "boom">]><data><program filename="&x;" start_sector="0" num_partition_sectors="1" /></data>',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(QFILManifestError, "DTD/entity"):
            analyze_qfil_package([xml])

    def test_utf16_dtd_and_entity_declarations_are_rejected(self) -> None:
        xml = self.manifest_dir / "unsafe-utf16.xml"
        xml.write_text(
            '<!DOCTYPE data [<!ENTITY x "boom">]><data><program filename="&x;" start_sector="0" num_partition_sectors="1" /></data>',
            encoding="utf-16",
        )
        with self.assertRaisesRegex(QFILManifestError, "DTD/entity"):
            analyze_qfil_package([xml])

    def test_erase_overwrite_is_applied_in_manifest_order_when_allowed(self) -> None:
        xml = self.manifest_dir / "program-then-erase.xml"
        xml.write_text(
            "<data>"
            '<program filename="boot.img" label="boot" start_sector="0" num_partition_sectors="2" SECTOR_SIZE_IN_BYTES="4" />'
            '<erase label="wipe" start_sector="0" num_partition_sectors="2" SECTOR_SIZE_IN_BYTES="4" />'
            "</data>",
            encoding="utf-8",
        )
        output_dir = self.root / "ordered-out"
        build_qfil_raw_images(
            [xml], output_dir, search_dirs=[self.root / "firmware"], allow_overlaps=True
        )
        self.assertEqual((output_dir / "physical_partition_0.raw").read_bytes(), b"\x00" * 8)

    def test_output_for_one_lun_never_overwrites_another_luns_source(self) -> None:
        cross_lun_source = self.images_dir / "physical_partition_1.raw"
        cross_lun_source.write_bytes(b"SAFE")
        xml = self.manifest_dir / "cross-lun-collision.xml"
        xml.write_text(
            "<data>"
            '<program filename="physical_partition_1.raw" label="lun0-source" start_sector="0" num_partition_sectors="1" physical_partition_number="0" SECTOR_SIZE_IN_BYTES="4" />'
            '<program filename="boot.img" label="lun1-source" start_sector="0" num_partition_sectors="2" physical_partition_number="1" SECTOR_SIZE_IN_BYTES="4" />'
            "</data>",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(QFILManifestError, "overwrite an input file"):
            build_qfil_raw_images(
                [xml], self.images_dir, search_dirs=[self.images_dir], force=True
            )
        self.assertEqual(cross_lun_source.read_bytes(), b"SAFE")

    def test_malformed_xml_is_reported(self) -> None:
        xml = self.manifest_dir / "broken.xml"
        xml.write_text("<data><program></data>", encoding="utf-8")
        with self.assertRaisesRegex(QFILManifestError, "Invalid XML"):
            analyze_qfil_package([xml])

    def test_cli_qfil_analyze_command(self) -> None:
        out = StringIO()
        err = StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main([
                "qfil-analyze", str(self.raw_program), "--patch-xml", str(self.patch_xml),
                "--search-dir", str(self.root / "firmware"),
            ])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("QFIL MANIFEST ANALYSIS", out.getvalue())
        self.assertIn("PATCH OPERATIONS (NOT APPLIED)", out.getvalue())

    def test_cli_qfil_build_command_and_json_report(self) -> None:
        out = StringIO()
        err = StringIO()
        output_dir = self.root / "cli-out"
        report_path = self.root / "qfil-report.json"
        with redirect_stdout(out), redirect_stderr(err):
            code = main([
                "qfil-build", str(self.raw_program), "--output-dir", str(output_dir),
                "--search-dir", str(self.root / "firmware"), "--json-report", str(report_path),
            ])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("QFIL RAW ASSEMBLY", out.getvalue())
        self.assertEqual(json.loads(report_path.read_text(encoding="utf-8"))["output_count"], 1)


if __name__ == "__main__":
    unittest.main()
