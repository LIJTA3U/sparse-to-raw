from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from raw_to_sparse import raw_to_sparse
from sparse_to_raw import main
from super_image import (
    LP_METADATA_GEOMETRY_MAGIC,
    LP_METADATA_HEADER_MAGIC,
    SuperImageError,
    extract_super_partitions,
    inspect_super_image,
)


def _make_geometry(metadata_max_size: int = 4096, slots: int = 2, logical_block_size: int = 4096) -> bytes:
    raw = bytearray(struct.pack(
        "<II32sIII", LP_METADATA_GEOMETRY_MAGIC, 52, b"\0" * 32,
        metadata_max_size, slots, logical_block_size,
    ))
    raw[8:40] = hashlib.sha256(raw).digest()
    return bytes(raw)


def _make_metadata(*, system_name: str = "system", vendor_name: str = "vendor", first_logical_sector: int = 64, system_target_sector: int = 64) -> bytes:
    partitions = (
        struct.pack("<36sIIII", system_name.encode().ljust(36, b"\0"), 1, 0, 1, 0)
        + struct.pack("<36sIIII", vendor_name.encode().ljust(36, b"\0"), 0, 1, 1, 0)
    )
    extents = (
        struct.pack("<QIQI", 8, 0, system_target_sector, 0)
        + struct.pack("<QIQI", 8, 0, 72, 0)
    )
    groups = struct.pack("<36sIQ", b"default\0".ljust(36, b"\0"), 0, 0)
    block_devices = struct.pack("<QIIQ36sI", first_logical_sector, 4096, 0, 65536, b"super\0".ljust(36, b"\0"), 0)
    tables = partitions + extents + groups + block_devices
    descriptors = (
        struct.pack("<III", 0, 2, 52)
        + struct.pack("<III", len(partitions), 2, 24)
        + struct.pack("<III", len(partitions) + len(extents), 1, 48)
        + struct.pack("<III", len(partitions) + len(extents) + len(groups), 1, 64)
    )
    header = bytearray(struct.pack(
        "<IHHI32sI32s", LP_METADATA_HEADER_MAGIC, 10, 0, 128,
        b"\0" * 32, len(tables), hashlib.sha256(tables).digest(),
    ) + descriptors)
    header[12:44] = hashlib.sha256(header).digest()
    return bytes(header) + tables


def make_super_image(path: Path, *, corrupt_primary: bool = False) -> None:
    data = bytearray(128 * 1024)
    geometry = _make_geometry()
    data[4096:4096 + len(geometry)] = geometry
    data[8192:8192 + len(geometry)] = geometry
    metadata = _make_metadata()
    primary_offset = 4096 + 2 * 4096
    backup_offset = primary_offset + 4096 * 2
    data[primary_offset:primary_offset + len(metadata)] = metadata
    data[backup_offset:backup_offset + len(metadata)] = metadata
    if corrupt_primary:
        data[primary_offset + 12] ^= 0xFF
    data[64 * 512:64 * 512 + 4096] = b"S" * 4096
    data[72 * 512:72 * 512 + 4096] = b"V" * 4096
    path.write_bytes(data)


def make_multi_extent_super_image(path: Path) -> bytes:
    """Create a small LP image whose system partition uses two disjoint extents.

    The vendor extent is physically stored between the two system extents. A
    correct extractor must concatenate the system data in metadata order rather
    than physical block-device order.
    """
    data = bytearray(128 * 1024)
    geometry = _make_geometry()
    data[4096:4096 + len(geometry)] = geometry
    data[8192:8192 + len(geometry)] = geometry

    partitions = (
        struct.pack("<36sIIII", b"system\0".ljust(36, b"\0"), 1, 0, 2, 0)
        + struct.pack("<36sIIII", b"vendor\0".ljust(36, b"\0"), 0, 2, 1, 0)
    )
    # system = sectors 64..71 + sectors 88..95; vendor = sectors 72..79.
    extents = (
        struct.pack("<QIQI", 8, 0, 64, 0)
        + struct.pack("<QIQI", 8, 0, 88, 0)
        + struct.pack("<QIQI", 8, 0, 72, 0)
    )
    groups = struct.pack("<36sIQ", b"default\0".ljust(36, b"\0"), 0, 0)
    block_devices = struct.pack(
        "<QIIQ36sI", 64, 4096, 0, 65536, b"super\0".ljust(36, b"\0"), 0
    )
    tables = partitions + extents + groups + block_devices
    descriptors = (
        struct.pack("<III", 0, 2, 52)
        + struct.pack("<III", len(partitions), 3, 24)
        + struct.pack("<III", len(partitions) + len(extents), 1, 48)
        + struct.pack("<III", len(partitions) + len(extents) + len(groups), 1, 64)
    )
    header = bytearray(struct.pack(
        "<IHHI32sI32s", LP_METADATA_HEADER_MAGIC, 10, 0, 128,
        b"\0" * 32, len(tables), hashlib.sha256(tables).digest(),
    ) + descriptors)
    header[12:44] = hashlib.sha256(header).digest()
    metadata = bytes(header) + tables

    primary_offset = 4096 + 2 * 4096
    backup_offset = primary_offset + 4096 * 2
    data[primary_offset:primary_offset + len(metadata)] = metadata
    data[backup_offset:backup_offset + len(metadata)] = metadata

    first_system_extent = b"A" * 4096
    vendor_extent = b"V" * 4096
    second_system_extent = b"B" * 4096
    data[64 * 512:72 * 512] = first_system_extent
    data[72 * 512:80 * 512] = vendor_extent
    data[88 * 512:96 * 512] = second_system_extent
    path.write_bytes(data)
    return first_system_extent + second_system_extent


class SuperImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.super = self.root / "super.img"
        make_super_image(self.super)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_inspects_geometry_metadata_groups_and_partitions(self) -> None:
        result = inspect_super_image(self.super)
        self.assertEqual(result["metadata_version"], "10.0")
        self.assertEqual(result["geometry"]["metadata_slot_count"], 2)
        self.assertEqual(result["partition_count"], 2)
        self.assertEqual(result["partitions"][0]["name"], "system")
        self.assertEqual(result["partitions"][0]["size_bytes"], 4096)
        self.assertEqual(result["partitions"][1]["group"], "default")
        self.assertEqual(result["metadata_copy"], "primary")

    def test_falls_back_to_backup_metadata(self) -> None:
        damaged = self.root / "damaged-primary.img"
        make_super_image(damaged, corrupt_primary=True)
        result = inspect_super_image(damaged)
        self.assertEqual(result["metadata_copy"], "backup")
        self.assertEqual(result["partition_count"], 2)

    def test_falls_back_to_backup_geometry(self) -> None:
        damaged = bytearray(self.super.read_bytes())
        # Invalidate the primary geometry checksum; the backup geometry remains intact.
        damaged[4096 + 8] ^= 0x01
        path = self.root / "damaged-primary-geometry.img"
        path.write_bytes(damaged)

        result = inspect_super_image(path)

        self.assertEqual(result["geometry"]["geometry_copy"], "backup")
        self.assertEqual(result["metadata_copy"], "primary")
        self.assertEqual(result["partition_count"], 2)

    def test_rejects_image_when_both_geometry_copies_are_invalid(self) -> None:
        damaged = bytearray(self.super.read_bytes())
        damaged[4096 + 8] ^= 0x01
        damaged[8192 + 8] ^= 0x01
        path = self.root / "both-geometries-damaged.img"
        path.write_bytes(damaged)

        with self.assertRaisesRegex(SuperImageError, "valid LP metadata geometry"):
            inspect_super_image(path)

    def test_extracts_selected_partitions_without_modifying_source(self) -> None:
        before = self.super.read_bytes()
        output = self.root / "out"
        report = extract_super_partitions(self.super, output, ["vendor"])
        self.assertEqual(report["extracted_count"], 1)
        self.assertEqual((output / "vendor.img").read_bytes(), b"V" * 4096)
        self.assertEqual(self.super.read_bytes(), before)

    def test_extracts_all_partitions_when_selection_is_omitted(self) -> None:
        output = self.root / "all"
        report = extract_super_partitions(self.super, output)
        self.assertEqual(report["extracted_count"], 2)
        self.assertEqual((output / "system.img").read_bytes(), b"S" * 4096)
        self.assertEqual((output / "vendor.img").read_bytes(), b"V" * 4096)

    def test_existing_output_is_preserved_without_force(self) -> None:
        output = self.root / "existing"
        output.mkdir()
        target = output / "system.img"
        target.write_bytes(b"KEEP")
        with self.assertRaises(FileExistsError):
            extract_super_partitions(self.super, output, ["system"])
        self.assertEqual(target.read_bytes(), b"KEEP")

    def test_force_replaces_existing_output_only_after_success(self) -> None:
        output = self.root / "replace"
        output.mkdir()
        target = output / "system.img"
        target.write_bytes(b"OLD")
        extract_super_partitions(self.super, output, ["system"], force=True)
        self.assertEqual(target.read_bytes(), b"S" * 4096)

    def test_sparse_super_input_is_expanded_automatically(self) -> None:
        sparse = self.root / "super.sparse"
        raw_to_sparse(self.super, sparse, block_size=4096)
        self.assertEqual(inspect_super_image(sparse)["source_format"], "Android Sparse")
        output = self.root / "sparse-out"
        extract_super_partitions(sparse, output, ["system"])
        self.assertEqual((output / "system.img").read_bytes(), b"S" * 4096)

    def test_extracts_partition_from_two_disjoint_linear_extents_in_metadata_order(self) -> None:
        multi_extent_image = self.root / "multi-extent-super.img"
        expected_system = make_multi_extent_super_image(multi_extent_image)

        info = inspect_super_image(multi_extent_image)
        system = next(item for item in info["partitions"] if item["name"] == "system")
        self.assertEqual(system["num_extents"], 2)
        self.assertEqual(system["size_bytes"], len(expected_system))
        self.assertEqual(
            [item["target_data_sector"] for item in system["extents"]],
            [64, 88],
        )

        output = self.root / "multi-extent-out"
        report = extract_super_partitions(multi_extent_image, output, ["system"])
        extracted = (output / "system.img").read_bytes()
        self.assertEqual(report["extracted"][0]["extent_count"], 2)
        self.assertEqual(extracted, expected_system)
        self.assertEqual(
            hashlib.sha256(extracted).hexdigest(),
            hashlib.sha256(expected_system).hexdigest(),
        )

    def test_sparse_input_extracts_partition_from_multiple_extents(self) -> None:
        multi_extent_image = self.root / "multi-extent-super.img"
        expected_system = make_multi_extent_super_image(multi_extent_image)
        sparse = self.root / "multi-extent-super.sparse.img"
        raw_to_sparse(multi_extent_image, sparse, block_size=4096)

        info = inspect_super_image(sparse)
        self.assertEqual(info["source_format"], "Android Sparse")
        system = next(item for item in info["partitions"] if item["name"] == "system")
        self.assertEqual(system["num_extents"], 2)

        output = self.root / "multi-extent-sparse-out"
        report = extract_super_partitions(sparse, output, ["system"])
        extracted = (output / "system.img").read_bytes()
        self.assertEqual(report["extracted"][0]["extent_count"], 2)
        self.assertEqual(extracted, expected_system)

    def test_cli_extracts_partition_from_multiple_extents(self) -> None:
        multi_extent_image = self.root / "multi-extent-cli-super.img"
        expected_system = make_multi_extent_super_image(multi_extent_image)
        output = self.root / "multi-extent-cli-out"
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                "super-extract", str(multi_extent_image),
                "--output-dir", str(output), "--partition", "system", "--quiet",
            ])

        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIn('"extent_count": 2', stdout.getvalue())
        self.assertEqual((output / "system.img").read_bytes(), expected_system)

    def test_packaged_multi_extent_fixture_matches_expected_partition_files(self) -> None:
        fixture_dir = Path(__file__).parent / "fixtures"
        fixture = fixture_dir / "super_multi_extent.img"
        expected_system_path = fixture_dir / "expected_system.img"
        expected_vendor_path = fixture_dir / "expected_vendor.img"
        missing = [path.name for path in (fixture, expected_system_path, expected_vendor_path)
                   if not path.is_file()]
        self.assertFalse(
            missing,
            "Required test fixture file(s) missing: " + ", ".join(missing)
            + ". Check that .gitignore permits tests/fixtures/*.img and commit the fixture files.",
        )
        info = inspect_super_image(fixture)
        self.assertEqual(info["partition_count"], 2)
        system = next(item for item in info["partitions"] if item["name"] == "system")
        self.assertEqual(system["num_extents"], 2)

        output = self.root / "packaged-fixture-out"
        report = extract_super_partitions(fixture, output)
        self.assertEqual(report["extracted_count"], 2)
        self.assertEqual(
            (output / "system.img").read_bytes(),
            expected_system_path.read_bytes(),
        )
        self.assertEqual(
            (output / "vendor.img").read_bytes(),
            expected_vendor_path.read_bytes(),
        )

    def test_invalid_metadata_checksum_is_rejected_when_both_copies_fail(self) -> None:
        damaged = bytearray(self.super.read_bytes())
        primary_offset = 4096 + 2 * 4096
        backup_offset = primary_offset + 4096 * 2
        damaged[primary_offset + 12] ^= 0x01
        damaged[backup_offset + 12] ^= 0x01
        path = self.root / "both-damaged.img"
        path.write_bytes(damaged)
        with self.assertRaisesRegex(SuperImageError, "metadata"):
            inspect_super_image(path)

    def test_invalid_slot_is_rejected(self) -> None:
        with self.assertRaisesRegex(SuperImageError, "slot"):
            inspect_super_image(self.super, slot=2)

    def test_rejects_extent_before_first_logical_sector(self) -> None:
        damaged = bytearray(self.super.read_bytes())
        metadata = _make_metadata(first_logical_sector=64, system_target_sector=63)
        primary_offset = 4096 + 2 * 4096
        backup_offset = primary_offset + 4096 * 2
        damaged[primary_offset:primary_offset + 4096] = b"\0" * 4096
        damaged[primary_offset:primary_offset + len(metadata)] = metadata
        damaged[backup_offset:backup_offset + 4096] = b"\0" * 4096
        damaged[backup_offset:backup_offset + len(metadata)] = metadata
        path = self.root / "reserved-area-extent.img"
        path.write_bytes(damaged)
        with self.assertRaisesRegex(SuperImageError, "before the first logical sector"):
            inspect_super_image(path)

    def test_rejects_unsafe_partition_name(self) -> None:
        unsafe = self.root / "unsafe.img"
        data = bytearray(self.super.read_bytes())
        metadata = _make_metadata(system_name="../escape")
        primary_offset = 4096 + 2 * 4096
        backup_offset = primary_offset + 4096 * 2
        data[primary_offset:primary_offset + 4096] = b"\0" * 4096
        data[primary_offset:primary_offset + len(metadata)] = metadata
        data[backup_offset:backup_offset + 4096] = b"\0" * 4096
        data[backup_offset:backup_offset + len(metadata)] = metadata
        unsafe.write_bytes(data)
        with self.assertRaisesRegex(SuperImageError, "unsafe name"):
            inspect_super_image(unsafe)

    def test_refuses_to_overwrite_input_super_image(self) -> None:
        source = self.root / "system.img"
        make_super_image(source)
        before = source.read_bytes()
        with self.assertRaisesRegex(SuperImageError, "overwrite the input"):
            extract_super_partitions(source, self.root, ["system"], force=True)
        self.assertEqual(source.read_bytes(), before)

    def test_cancel_is_supported(self) -> None:
        with self.assertRaises(InterruptedError):
            inspect_super_image(self.super, cancel_requested=lambda: True)

    def test_cli_json_report_cannot_overwrite_an_extracted_partition(self) -> None:
        output = self.root / "cli-output"
        output.mkdir()
        report_target = output / "system.img"
        stderr = StringIO()
        with redirect_stderr(stderr):
            code = main([
                "super-extract", str(self.super), "--output-dir", str(output),
                "--partition", "system", "--json-report", str(report_target),
            ])
        self.assertEqual(code, 2)
        self.assertFalse(report_target.exists())
        self.assertIn("conflicts", stderr.getvalue())

    def test_cli_existing_json_report_is_rejected_before_extraction(self) -> None:
        output = self.root / "existing-report-output"
        report = self.root / "existing-report.json"
        report.write_text("KEEP", encoding="utf-8")
        stderr = StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as caught:
                main([
                    "super-extract", str(self.super), "--output-dir", str(output),
                    "--partition", "system", "--json-report", str(report),
                ])
        self.assertEqual(caught.exception.code, 2)
        self.assertEqual(report.read_text(encoding="utf-8"), "KEEP")
        self.assertFalse((output / "system.img").exists())

    def test_cli_info_and_extract(self) -> None:
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["super-info", str(self.super), "--quiet"])
        self.assertEqual(code, 0)
        self.assertIn('"metadata_version": "10.0"', out.getvalue())
        output_dir = self.root / "cli-out"
        with redirect_stdout(out := StringIO()), redirect_stderr(err := StringIO()):
            code = main(["super-extract", str(self.super), "--output-dir", str(output_dir), "--partition", "vendor", "--quiet"])
        self.assertEqual(code, 0)
        self.assertIn('"extracted_count": 1', out.getvalue())
        self.assertEqual((output_dir / "vendor.img").read_bytes(), b"V" * 4096)


if __name__ == "__main__":
    unittest.main()
