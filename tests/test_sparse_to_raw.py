import hashlib
import json
import struct
import tempfile
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

from sparse_to_raw import (
    CHUNK_CRC32,
    CHUNK_DONT_CARE,
    CHUNK_FILL,
    CHUNK_RAW,
    ConversionCancelled,
    HEADER_FMT,
    MAGIC,
    SparseImageError,
    convert_sparse_to_raw,
    discover_sparse_parts,
    inspect_sparse,
    merge_sparse_to_raw,
    preflight_batch,
    preflight_output,
    read_sparse_chunk_page,
    export_sparse_structure,
    iter_sparse_chunk_metadata,
    InsufficientDiskSpaceError,
    OutputVerificationError,
    main,
)

BLOCK_SIZE = 4
CHUNK_FMT = "<HHII"


def chunk(kind: int, blocks: int, payload: bytes = b"") -> bytes:
    total_size = 12 + len(payload)
    return struct.pack(CHUNK_FMT, kind, 0, blocks, total_size) + payload


def crc_chunk(value: int) -> bytes:
    return chunk(CHUNK_CRC32, 0, struct.pack("<I", value))


def make_sparse(chunks: list[bytes], raw_bytes: bytes, image_checksum: int | None = None) -> bytes:
    if image_checksum is None:
        image_checksum = zlib.crc32(raw_bytes) & 0xFFFFFFFF
    total_blocks = len(raw_bytes) // BLOCK_SIZE
    header = struct.pack(
        HEADER_FMT,
        MAGIC,
        1,
        0,
        struct.calcsize(HEADER_FMT),
        struct.calcsize(CHUNK_FMT),
        BLOCK_SIZE,
        total_blocks,
        len(chunks),
        image_checksum,
    )
    return header + b"".join(chunks)


class SparseToRawTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.input_path = self.root / "sample.sparse"
        self.output_path = self.root / "sample.raw"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_all_chunk_types_and_checksums(self) -> None:
        raw_data = b"ABCD" + b"EFGH" + (b"\x00" * 4) + b"IJKL"
        crc_after_raw = zlib.crc32(b"ABCD") & 0xFFFFFFFF
        crc_after_fill = zlib.crc32(b"EFGH", crc_after_raw) & 0xFFFFFFFF
        crc_after_zero = zlib.crc32(b"\x00" * 4, crc_after_fill) & 0xFFFFFFFF
        chunks = [
            chunk(CHUNK_RAW, 1, b"ABCD"),
            crc_chunk(crc_after_raw),
            chunk(CHUNK_FILL, 1, b"EFGH"),
            crc_chunk(crc_after_fill),
            chunk(CHUNK_DONT_CARE, 1),
            crc_chunk(crc_after_zero),
            chunk(CHUNK_RAW, 1, b"IJKL"),
        ]
        self.input_path.write_bytes(make_sparse(chunks, raw_data))
        result = convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertTrue(result["preflight"]["passed"])
        self.assertEqual(result["preflight"]["operation"], "convert")
        self.assertEqual(self.output_path.read_bytes(), raw_data)
        self.assertEqual(self.output_path.stat().st_size, len(raw_data))
        self.assertEqual(result["total_blocks"], 4)
        self.assertEqual(result["computed_crc32"], f"0x{zlib.crc32(raw_data) & 0xFFFFFFFF:08X}")
        self.assertEqual(result["chunk_counts"]["CRC32"], 3)

    def test_trailing_dont_care_gets_correct_size(self) -> None:
        raw_data = b"DATA" + (b"\x00" * 8)
        chunks = [chunk(CHUNK_RAW, 1, b"DATA"), chunk(CHUNK_DONT_CARE, 2)]
        self.input_path.write_bytes(make_sparse(chunks, raw_data))
        convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertEqual(self.output_path.read_bytes(), raw_data)
        self.assertEqual(self.output_path.stat().st_size, 12)

    def test_bad_chunk_crc_is_rejected_and_output_not_committed(self) -> None:
        raw_data = b"ABCD"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data), crc_chunk(0x12345678)], raw_data))
        with self.assertRaisesRegex(SparseImageError, "CRC32 mismatch"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_bad_image_checksum_is_rejected(self) -> None:
        raw_data = b"ABCD"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data, image_checksum=0xDEADBEEF))
        with self.assertRaisesRegex(SparseImageError, "Image checksum mismatch"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_truncated_raw_payload_is_rejected(self) -> None:
        header = struct.pack(HEADER_FMT, MAGIC, 1, 0, 28, 12, 4, 1, 1, 0)
        truncated_chunk = struct.pack(CHUNK_FMT, CHUNK_RAW, 0, 1, 16) + b"AB"
        self.input_path.write_bytes(header + truncated_chunk)
        with self.assertRaisesRegex(SparseImageError, "Unexpected end of file"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_invalid_magic_is_rejected(self) -> None:
        self.input_path.write_bytes(b"NOPE" + b"\x00" * 24)
        with self.assertRaisesRegex(SparseImageError, "Invalid sparse magic"):
            convert_sparse_to_raw(self.input_path, self.output_path)

    def test_trailing_bytes_are_rejected(self) -> None:
        raw_data = b"ABCD"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data) + b"EXTRA")
        with self.assertRaisesRegex(SparseImageError, "Unexpected trailing bytes"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_existing_destination_survives_failed_conversion(self) -> None:
        self.output_path.write_bytes(b"KEEP")
        raw_data = b"ABCD"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data), crc_chunk(0x12345678)], raw_data))
        with self.assertRaisesRegex(SparseImageError, "CRC32 mismatch"):
            convert_sparse_to_raw(self.input_path, self.output_path, force=True)
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")

    def test_existing_destination_is_not_overwritten_by_default(self) -> None:
        self.output_path.write_bytes(b"KEEP")
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        with self.assertRaisesRegex(FileExistsError, "use --force"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")

    def test_force_replaces_existing_destination_after_validation(self) -> None:
        self.output_path.write_bytes(b"OLD!")
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        convert_sparse_to_raw(self.input_path, self.output_path, force=True)
        self.assertEqual(self.output_path.read_bytes(), raw_data)

    def test_info_verifies_without_creating_raw_output(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        result = inspect_sparse(self.input_path, mode="info")
        self.assertEqual(result["raw_size_bytes"], 4)
        self.assertEqual(result["chunk_counts"]["RAW"], 1)
        self.assertFalse(self.output_path.exists())

    def test_verify_only_rejects_bad_crc_without_output(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data), crc_chunk(0x12345678)], raw_data))
        with self.assertRaisesRegex(SparseImageError, "CRC32 mismatch"):
            inspect_sparse(self.input_path, mode="verify")
        self.assertFalse(self.output_path.exists())

    def test_sha256_matches_expanded_raw_contents(self) -> None:
        raw_data = b"DATA" + b"\x00" * 4
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"DATA"), chunk(CHUNK_DONT_CARE, 1)], raw_data))
        result = inspect_sparse(self.input_path, calculate_sha256=True)
        self.assertEqual(result["sha256"], hashlib.sha256(raw_data).hexdigest())


    def test_conversion_verifies_staged_raw_before_commit(self) -> None:
        raw_data = b"DATA" + b"\x00" * 4
        self.input_path.write_bytes(
            make_sparse([chunk(CHUNK_RAW, 1, b"DATA"), chunk(CHUNK_DONT_CARE, 1)], raw_data)
        )
        progress: list[dict] = []
        result = convert_sparse_to_raw(
            self.input_path, self.output_path, verify_output=True,
            progress_callback=progress.append,
        )
        verification = result["output_verification"]
        expected = hashlib.sha256(raw_data).hexdigest()
        self.assertTrue(verification["passed"])
        self.assertEqual(verification["expected_size_bytes"], len(raw_data))
        self.assertEqual(verification["actual_size_bytes"], len(raw_data))
        self.assertEqual(verification["expected_sha256"], expected)
        self.assertEqual(verification["actual_sha256"], expected)
        self.assertEqual(self.output_path.read_bytes(), raw_data)
        self.assertTrue(any(item.get("stage") == "verification" for item in progress))
        self.assertEqual([item["percent"] for item in progress], sorted(item["percent"] for item in progress))
        self.assertNotIn("sha256", result, "verification should not silently enable the optional --sha256 result field")

    def test_output_verification_failure_preserves_existing_destination(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        self.output_path.write_bytes(b"KEEP")
        from sparse_to_raw import _verify_raw_file as real_verify

        def corrupt_then_verify(path, *args, **kwargs):
            Path(path).write_bytes(b"EVIL")
            return real_verify(path, *args, **kwargs)

        with patch("sparse_to_raw._verify_raw_file", side_effect=corrupt_then_verify):
            with self.assertRaisesRegex(OutputVerificationError, "SHA-256 mismatch"):
                convert_sparse_to_raw(self.input_path, self.output_path, force=True, verify_output=True)
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")
        self.assertEqual(list(self.root.glob(".sample.raw.*.tmp")), [])

    def test_output_verification_rejects_truncated_staging_file(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        self.output_path.write_bytes(b"KEEP")
        from sparse_to_raw import _verify_raw_file as real_verify

        def truncate_then_verify(path, *args, **kwargs):
            Path(path).write_bytes(b"DAT")
            return real_verify(path, *args, **kwargs)

        with patch("sparse_to_raw._verify_raw_file", side_effect=truncate_then_verify):
            with self.assertRaisesRegex(OutputVerificationError, "size mismatch"):
                convert_sparse_to_raw(self.input_path, self.output_path, force=True, verify_output=True)
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")
        self.assertEqual(list(self.root.glob(".sample.raw.*.tmp")), [])

    def test_merge_verification_failure_preserves_existing_destination(self) -> None:
        first = self.root / "part0.sparse"
        second = self.root / "part1.sparse"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"AAAA")], b"AAAA"))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"BBBB")], b"BBBB"))
        self.output_path.write_bytes(b"KEEP")
        from sparse_to_raw import _verify_raw_file as real_verify

        def corrupt_then_verify(path, *args, **kwargs):
            Path(path).write_bytes(b"EVILEVIL")
            return real_verify(path, *args, **kwargs)

        with patch("sparse_to_raw._verify_raw_file", side_effect=corrupt_then_verify):
            with self.assertRaises(OutputVerificationError):
                merge_sparse_to_raw([first, second], self.output_path, force=True, verify_output=True)
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")
        self.assertEqual(list(self.root.glob(".sample.raw.*.tmp")), [])

    def test_output_verification_cancellation_preserves_destination(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        self.output_path.write_bytes(b"KEEP")
        verify_started = {"value": False}

        def on_event(_level: str, message: str) -> None:
            if "Re-reading staged RAW output" in message:
                verify_started["value"] = True

        with self.assertRaises(ConversionCancelled):
            convert_sparse_to_raw(
                self.input_path, self.output_path, force=True, verify_output=True,
                event_callback=on_event,
                cancel_requested=lambda: verify_started["value"],
            )
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")
        self.assertEqual(list(self.root.glob(".sample.raw.*.tmp")), [])

    def test_merge_verifies_final_combined_raw_output(self) -> None:
        first = self.root / "part0.sparse"
        second = self.root / "part1.sparse"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"AAAA")], b"AAAA"))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"BBBB")], b"BBBB"))
        progress: list[dict] = []
        result = merge_sparse_to_raw(
            [first, second], self.output_path, verify_output=True,
            progress_callback=progress.append,
        )
        expected = hashlib.sha256(b"AAAABBBB").hexdigest()
        self.assertEqual(self.output_path.read_bytes(), b"AAAABBBB")
        self.assertTrue(result["output_verification"]["passed"])
        self.assertEqual(result["output_verification"]["actual_sha256"], expected)
        self.assertTrue(any(item.get("stage") == "verification" for item in progress))
        percentages = [item["percent"] for item in progress]
        self.assertEqual(percentages, sorted(percentages))

    def test_cli_verify_output_is_in_json_report(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        report = self.root / "verify-report.json"
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                str(self.input_path), str(self.output_path), "--verify-output",
                "--json-report", str(report), "--quiet",
            ])
        self.assertEqual(code, 0, stderr.getvalue())
        payload = json.loads(report.read_text(encoding="utf-8"))
        self.assertTrue(payload["output_verification"]["passed"])
        self.assertIn("RAW verification : PASSED", stdout.getvalue())

    def test_cli_rejects_verify_output_for_inspection(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        stderr = StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main([str(self.input_path), "--info", "--verify-output"])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("is only available", stderr.getvalue())

    def _write_discoverable_part(
        self,
        path: Path,
        *,
        block_size: int = BLOCK_SIZE,
        raw_data: bytes | None = None,
    ) -> None:
        raw = raw_data if raw_data is not None else b"DATA" * (block_size // 4)
        header = struct.pack(
            HEADER_FMT,
            MAGIC,
            1,
            0,
            struct.calcsize(HEADER_FMT),
            struct.calcsize(CHUNK_FMT),
            block_size,
            len(raw) // block_size,
            1,
            zlib.crc32(raw) & 0xFFFFFFFF,
        )
        payload = chunk(CHUNK_RAW, len(raw) // block_size, raw)
        path.write_bytes(header + payload)


    def test_sparse_structure_page_reports_offsets_types_and_checksums(self) -> None:
        raw = b"ABCD" + b"EFGH" + (b"\x00" * 4)
        crc_after_raw = zlib.crc32(b"ABCD") & 0xFFFFFFFF
        chunks = [
            chunk(CHUNK_RAW, 1, b"ABCD"),
            crc_chunk(crc_after_raw),
            chunk(CHUNK_FILL, 1, b"EFGH"),
            chunk(CHUNK_DONT_CARE, 1),
        ]
        self.input_path.write_bytes(make_sparse(chunks, raw))
        validated = inspect_sparse(self.input_path, calculate_sha256=True)
        page = read_sparse_chunk_page(self.input_path, offset=0, limit=2)

        self.assertEqual(page["total_matches"], 4)
        self.assertEqual(page["next_offset"], 2)
        self.assertEqual([row["type"] for row in page["rows"]], ["RAW", "CRC32"])
        self.assertEqual(page["rows"][0]["file_offset"], 28)
        self.assertEqual(page["rows"][0]["output_offset_bytes"], 0)
        self.assertEqual(page["rows"][0]["stored_size_bytes"], 16)
        self.assertEqual(page["rows"][1]["checksum"], f"0x{crc_after_raw:08X}")
        self.assertEqual(page["rows"][1]["output_offset_bytes"], 4)
        self.assertEqual(validated["total_chunks"], page["header"]["total_chunks"])

    def test_sparse_structure_page_supports_type_search_and_pagination(self) -> None:
        raw = b"ABCD" + b"EFGH" + (b"\x00" * 4)
        chunks = [chunk(CHUNK_RAW, 1, b"ABCD"), chunk(CHUNK_FILL, 1, b"EFGH"), chunk(CHUNK_DONT_CARE, 1)]
        self.input_path.write_bytes(make_sparse(chunks, raw))
        inspect_sparse(self.input_path)

        fill = read_sparse_chunk_page(self.input_path, chunk_type="fill")
        self.assertEqual(fill["total_matches"], 1)
        self.assertEqual(fill["rows"][0]["type"], "FILL")
        self.assertEqual(fill["rows"][0]["fill_pattern"], "45 46 47 48")

        searched = read_sparse_chunk_page(self.input_path, search="0x3C")
        self.assertEqual(searched["total_matches"], 1)
        self.assertEqual(searched["rows"][0]["type"], "DONT_CARE")

        second_page = read_sparse_chunk_page(self.input_path, offset=2, limit=2)
        self.assertEqual([row["type"] for row in second_page["rows"]], ["DONT_CARE"])
        self.assertIsNone(second_page["next_offset"])

    def test_sparse_structure_export_streams_json_and_csv(self) -> None:
        raw = b"ABCD" + b"EFGH"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 2, raw)], raw))
        json_path = self.root / "structure.json"
        csv_path = self.root / "structure.csv"

        json_result = export_sparse_structure(self.input_path, json_path, format="json")
        csv_result = export_sparse_structure(self.input_path, csv_path, format="csv")

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(json_result["chunks_exported"], 1)
        self.assertEqual(payload["metadata"]["total_chunks"], 1)
        self.assertEqual(payload["chunks"][0]["type"], "RAW")
        self.assertEqual(csv_result["chunks_exported"], 1)
        self.assertIn("file_offset", csv_path.read_text(encoding="utf-8"))

    def test_sparse_structure_export_coalesces_progress_for_large_chunk_tables(self) -> None:
        raw_data = b"ABCD" * 300
        chunks = [chunk(CHUNK_RAW, 1, b"ABCD") for _ in range(300)]
        self.input_path.write_bytes(make_sparse(chunks, raw_data))
        progress: list[dict] = []
        result = export_sparse_structure(
            self.input_path, self.root / "large-structure.json", format="json",
            progress_callback=progress.append,
        )
        percentages = [int(item["percent"]) for item in progress]
        self.assertEqual(percentages, sorted(percentages))
        self.assertEqual(percentages[0], 0)
        self.assertEqual(percentages[-1], 100)
        self.assertLessEqual(len(progress), 102)
        self.assertEqual(result["chunks_exported"], 300)

    def test_sparse_structure_export_preserves_existing_file_on_cancel(self) -> None:
        raw = b"ABCD"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw)], raw))
        destination = self.root / "structure.json"
        destination.write_text("keep", encoding="utf-8")
        with self.assertRaises(ConversionCancelled):
            export_sparse_structure(
                self.input_path, destination, format="json", force=True,
                cancel_requested=lambda: True,
            )
        self.assertEqual(destination.read_text(encoding="utf-8"), "keep")

    def test_sparse_structure_export_reports_monotonic_progress(self) -> None:
        raw_data = b"ABCD" + b"EFGH"
        self.input_path.write_bytes(make_sparse([
            chunk(CHUNK_RAW, 1, b"ABCD"),
            chunk(CHUNK_RAW, 1, b"EFGH"),
        ], raw_data))
        progress: list[dict] = []
        export_sparse_structure(
            self.input_path,
            self.root / "progress.json",
            format="json",
            progress_callback=progress.append,
        )
        percentages = [int(item["percent"]) for item in progress]
        self.assertEqual(percentages, sorted(percentages))
        self.assertEqual(percentages[-1], 100)
        self.assertEqual(progress[-1]["chunks_exported"], 2)

    def test_sparse_structure_rejects_malformed_chunk_header(self) -> None:
        header = struct.pack(HEADER_FMT, MAGIC, 1, 0, 28, 12, BLOCK_SIZE, 1, 1, 0)
        malformed = struct.pack(CHUNK_FMT, 0x1234, 0, 1, 16) + b"ABCD"
        self.input_path.write_bytes(header + malformed)
        with self.assertRaisesRegex(SparseImageError, "unsupported type"):
            list(iter_sparse_chunk_metadata(self.input_path))

    def test_discover_sparse_parts_sorts_indices_numerically(self) -> None:
        for index in [10, 2, 1, 0, 9, 8, 7, 6, 5, 4, 3]:
            self._write_discoverable_part(self.root / f"super.img_sparsechunk.{index}")
        (self.root / "notes.txt").write_text("ignore", encoding="utf-8")
        result = discover_sparse_parts(self.root)
        self.assertEqual(result["group_count"], 1)
        self.assertEqual(result["part_count"], 11)
        group = result["groups"][0]
        self.assertTrue(group["ready"])
        self.assertEqual(group["indices"], list(range(11)))
        self.assertEqual(
            [Path(part["path"]).name for part in group["parts"]],
            [f"super.img_sparsechunk.{index}" for index in range(11)],
        )
        self.assertEqual(group["total_raw_size_bytes"], 11 * len(b"DATA"))

    def test_discover_sparse_parts_reports_missing_indices(self) -> None:
        for index in [0, 2, 3]:
            self._write_discoverable_part(self.root / f"super.img_sparsechunk.{index}")
        group = discover_sparse_parts(self.root)["groups"][0]
        self.assertEqual(group["missing_indices"], [1])
        self.assertFalse(group["ready"])
        self.assertTrue(any("Missing part indices: 1" in item for item in group["warnings"]))

    def test_discover_sparse_parts_reports_duplicate_numeric_indices(self) -> None:
        for name in ["super.img_sparsechunk.0", "super.img_sparsechunk.1", "super.img_sparsechunk.01"]:
            self._write_discoverable_part(self.root / name)
        group = discover_sparse_parts(self.root)["groups"][0]
        self.assertEqual(group["duplicate_indices"], [1])
        self.assertFalse(group["ready"])

    def test_discover_sparse_parts_groups_different_prefixes(self) -> None:
        for name in ["super.img_sparsechunk.0", "super.img_sparsechunk.1", "system.img_sparsechunk.0", "system.img_sparsechunk.1"]:
            self._write_discoverable_part(self.root / name)
        result = discover_sparse_parts(self.root)
        self.assertEqual(result["group_count"], 2)
        self.assertEqual([group["prefix"] for group in result["groups"]], ["super.img", "system.img"])
        self.assertTrue(all(group["ready"] for group in result["groups"]))

    def test_discover_sparse_parts_rejects_invalid_headers(self) -> None:
        self._write_discoverable_part(self.root / "super.img_sparsechunk.0")
        (self.root / "super.img_sparsechunk.1").write_bytes(b"NOPE" + b"\x00" * 24)
        group = discover_sparse_parts(self.root)["groups"][0]
        self.assertFalse(group["ready"])
        self.assertEqual(len(group["errors"]), 1)
        self.assertIn("Invalid sparse magic", group["errors"][0])

    def test_discover_sparse_parts_rejects_mixed_block_sizes(self) -> None:
        self._write_discoverable_part(self.root / "super.img_sparsechunk.0", block_size=4)
        self._write_discoverable_part(self.root / "super.img_sparsechunk.1", block_size=8)
        group = discover_sparse_parts(self.root)["groups"][0]
        self.assertFalse(group["ready"])
        self.assertTrue(any("different block sizes" in item for item in group["errors"]))

    def test_discovered_sparse_parts_merge_in_numeric_order(self) -> None:
        self._write_discoverable_part(self.root / "super.img_sparsechunk.1", raw_data=b"BBBB")
        self._write_discoverable_part(self.root / "super.img_sparsechunk.0", raw_data=b"AAAA")
        discovery = discover_sparse_parts(self.root)
        sources = [part["path"] for part in discovery["groups"][0]["parts"]]
        merge_sparse_to_raw(sources, self.output_path)
        self.assertEqual(self.output_path.read_bytes(), b"AAAABBBB")

    def test_discover_sparse_parts_supports_alternative_marker(self) -> None:
        for index in [0, 1]:
            self._write_discoverable_part(self.root / f"vendor.img.sparsechunk.{index}")
        group = discover_sparse_parts(self.root)["groups"][0]
        self.assertTrue(group["ready"])
        self.assertEqual(group["marker"], ".sparsechunk.")

    def test_discover_sparse_parts_bounds_missing_index_preview(self) -> None:
        self._write_discoverable_part(self.root / "super.img_sparsechunk.0")
        self._write_discoverable_part(self.root / "super.img_sparsechunk.1000000000")
        group = discover_sparse_parts(self.root)["groups"][0]
        self.assertFalse(group["ready"])
        self.assertEqual(group["missing_count"], 999_999_999)
        self.assertEqual(len(group["missing_indices"]), 256)
        self.assertEqual(group["missing_ranges"], [[1, 999_999_999]])

    def test_discover_sparse_parts_requires_directory(self) -> None:
        file_path = self.root / "file.txt"
        file_path.write_text("x", encoding="utf-8")
        with self.assertRaises(NotADirectoryError):
            discover_sparse_parts(file_path)
        with self.assertRaises(FileNotFoundError):
            discover_sparse_parts(self.root / "missing")

    def test_merge_independent_sparse_parts_in_supplied_order(self) -> None:
        first = self.root / "super.img_sparsechunk.0"
        second = self.root / "super.img_sparsechunk.1"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"AAAA")], b"AAAA"))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"BBBB")], b"BBBB"))
        result = merge_sparse_to_raw([first, second], self.output_path, calculate_sha256=True)
        expected = b"AAAABBBB"
        self.assertEqual(self.output_path.read_bytes(), expected)
        self.assertEqual(result["raw_size_bytes"], len(expected))
        self.assertEqual(result["sha256"], hashlib.sha256(expected).hexdigest())
        self.assertEqual(len(result["parts"]), 2)

    def test_merge_does_not_commit_if_any_part_is_invalid(self) -> None:
        first = self.root / "good.sparse"
        second = self.root / "bad.sparse"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"AAAA")], b"AAAA"))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"BBBB"), crc_chunk(0x12345678)], b"BBBB"))
        with self.assertRaisesRegex(SparseImageError, "CRC32 mismatch"):
            merge_sparse_to_raw([first, second], self.output_path)
        self.assertFalse(self.output_path.exists())


    def test_merge_progress_is_monotonic_and_finishes_after_commit(self) -> None:
        first = self.root / "part0.sparse"
        second = self.root / "part1.sparse"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"AAAA")], b"AAAA"))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"BBBB")], b"BBBB"))
        updates: list[dict] = []
        events: list[tuple[str, str]] = []
        result = merge_sparse_to_raw(
            [first, second], self.output_path,
            progress_callback=updates.append,
            event_callback=lambda level, message: events.append((level, message)),
        )
        percentages = [item["percent"] for item in updates]
        self.assertEqual(percentages[-1], 100)
        self.assertEqual(percentages, sorted(percentages))
        self.assertEqual(result["output_size_bytes"], 8)
        self.assertTrue(any(item.get("stage") == "merge" for item in updates))
        self.assertTrue(any("Merging 2" in message for _, message in events))

    def test_merge_cancellation_preserves_existing_destination(self) -> None:
        first = self.root / "part0.sparse"
        second = self.root / "part1.sparse"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"AAAA")], b"AAAA"))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"BBBB")], b"BBBB"))
        self.output_path.write_bytes(b"KEEP")
        with self.assertRaises(ConversionCancelled):
            merge_sparse_to_raw([first, second], self.output_path, force=True, cancel_requested=lambda: True)
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")
        self.assertEqual(sorted(path.name for path in self.root.iterdir()),
                         ["part0.sparse", "part1.sparse", "sample.raw"])

    def test_cli_merge_parts_syntax(self) -> None:
        first = self.root / "part0.sparse"
        second = self.root / "part1.sparse"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"AAAA")], b"AAAA"))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, b"BBBB")], b"BBBB"))
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([
                "--merge-parts", str(first), str(second), "--output", str(self.output_path), "--quiet"
            ])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertEqual(self.output_path.read_bytes(), b"AAAABBBB")



    def test_preflight_conversion_reports_sizes_and_cleans_probe_file(self) -> None:
        raw = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw)], raw))

        report = preflight_output([self.input_path], self.output_path)

        self.assertTrue(report["passed"])
        self.assertEqual(report["operation"], "convert")
        self.assertEqual(report["expected_output_bytes"], len(raw))
        self.assertEqual(report["peak_additional_bytes"], len(raw))
        self.assertGreaterEqual(report["required_free_bytes"], len(raw))
        self.assertGreater(report["available_free_bytes"], 0)
        self.assertEqual(report["write_probe"], "passed")
        self.assertEqual(list(self.root.glob(".sparse-to-raw-preflight-*.tmp")), [])

    def test_preflight_rejects_insufficient_free_space_before_output_creation(self) -> None:
        raw = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw)], raw))
        with patch("sparse_to_raw.shutil.disk_usage", return_value=SimpleNamespace(total=100, used=100, free=0)):
            with self.assertRaises(InsufficientDiskSpaceError):
                convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertFalse(self.output_path.exists())
        self.assertEqual(list(self.root.glob(".sparse-to-raw-preflight-*.tmp")), [])

    def test_preflight_reports_output_directory_write_failure(self) -> None:
        raw = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw)], raw))
        with patch("sparse_to_raw.tempfile.mkstemp", side_effect=PermissionError("access denied")):
            with self.assertRaisesRegex(PermissionError, "Cannot create a temporary file"):
                preflight_output([self.input_path], self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_preflight_merge_accounts_for_final_stage_and_largest_part(self) -> None:
        first = self.root / "part0.sparse"
        second = self.root / "part1.sparse"
        first_raw = b"AAAA"
        second_raw = b"BBBBCCCC"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, first_raw)], first_raw))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 2, second_raw)], second_raw))

        report = preflight_output([first, second], self.output_path, operation="merge")

        self.assertEqual(report["operation"], "merge")
        self.assertEqual(report["expected_output_bytes"], 12)
        self.assertEqual(report["part_raw_sizes_bytes"], [4, 8])
        self.assertEqual(report["peak_additional_bytes"], 20)
        self.assertEqual(report["outputs"][0]["path"], str(self.output_path.resolve()))

    def test_preflight_batch_accounts_for_all_outputs(self) -> None:
        first = self.root / "first.sparse"
        second = self.root / "second.sparse"
        first_raw = b"AAAA"
        second_raw = b"BBBBCCCC"
        first.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, first_raw)], first_raw))
        second.write_bytes(make_sparse([chunk(CHUNK_RAW, 2, second_raw)], second_raw))
        output_dir = self.root / "batch-output"
        output_dir.mkdir()

        report = preflight_batch([first, second], output_dir)

        self.assertEqual(report["operation"], "batch")
        self.assertEqual(report["expected_output_bytes"], 12)
        self.assertEqual(report["peak_additional_bytes"], 12)
        self.assertEqual([Path(item["output"]).name for item in report["outputs"]],
                         ["first_raw.img", "second_raw.img"])

    def test_preflight_batch_rejects_colliding_output_names_before_work(self) -> None:
        one = self.root / "one"
        two = self.root / "two"
        output_dir = self.root / "batch-output"
        one.mkdir(); two.mkdir(); output_dir.mkdir()
        raw = b"DATA"
        payload = make_sparse([chunk(CHUNK_RAW, 1, raw)], raw)
        first = one / "same.sparse"
        second = two / "same.sparse"
        first.write_bytes(payload); second.write_bytes(payload)

        with self.assertRaisesRegex(ValueError, "output-name collision"):
            preflight_batch([first, second], output_dir)
        self.assertEqual(list(output_dir.iterdir()), [])


    def test_preflight_batch_rejects_output_that_is_another_input(self) -> None:
        first = self.root / "sample.sparse"
        second = self.root / "sample_raw.img"
        raw = b"DATA"
        payload = make_sparse([chunk(CHUNK_RAW, 1, raw)], raw)
        first.write_bytes(payload)
        second.write_bytes(payload)
        output_dir = self.root

        with self.assertRaisesRegex(ValueError, "would overwrite an input file"):
            preflight_batch([first, second], output_dir, overwrite=True)
        self.assertEqual(second.read_bytes(), payload)


    def test_preflight_batch_rejects_existing_output_without_overwrite(self) -> None:
        raw = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw)], raw))
        output_dir = self.root / "batch-output"
        output_dir.mkdir()
        existing = output_dir / "sample_raw.img"
        existing.write_bytes(b"KEEP")

        with self.assertRaises(FileExistsError):
            preflight_batch([self.input_path], output_dir, overwrite=False)
        self.assertEqual(existing.read_bytes(), b"KEEP")


    def test_zero_byte_image_reports_100_percent_only_after_validation(self) -> None:
        self.input_path.write_bytes(make_sparse([], b""))
        updates: list[dict] = []
        result = inspect_sparse(self.input_path, progress_callback=updates.append)
        self.assertEqual(result["raw_size_bytes"], 0)
        self.assertGreaterEqual(len(updates), 2)
        self.assertEqual(updates[0]["percent"], 0)
        self.assertEqual(updates[-1]["percent"], 100)

    def test_progress_callback_reports_real_chunk_and_byte_progress(self) -> None:
        raw_data = b"DATA" + b"NEXT"
        crc = zlib.crc32(raw_data) & 0xFFFFFFFF
        chunks = [
            chunk(CHUNK_RAW, 1, b"DATA"),
            chunk(CHUNK_RAW, 1, b"NEXT"),
            crc_chunk(crc),
        ]
        self.input_path.write_bytes(make_sparse(chunks, raw_data))
        progress_events: list[dict] = []
        log_events: list[tuple[str, str]] = []

        result = convert_sparse_to_raw(
            self.input_path,
            self.output_path,
            progress_callback=progress_events.append,
            event_callback=lambda level, message: log_events.append((level, message)),
        )

        self.assertEqual(self.output_path.read_bytes(), raw_data)
        self.assertGreaterEqual(len(progress_events), 4)
        self.assertEqual(progress_events[-1]["percent"], 100)
        self.assertEqual(progress_events[-1]["processed_chunks"], result["total_chunks"])
        self.assertEqual(progress_events[-1]["total_chunks"], 3)
        processed = [event["processed_bytes"] for event in progress_events]
        self.assertEqual(processed, sorted(processed))
        self.assertTrue(any("Проверка заголовка: OK" in message for _, message in log_events))
        self.assertTrue(any("Проверка CRC32 чанка 3: OK" in message for _, message in log_events))
        self.assertTrue(any("Результат сохранён" in message for _, message in log_events))

    def test_cancellation_keeps_existing_output_and_removes_temporary_file(self) -> None:
        original = b"KEEP"
        self.output_path.write_bytes(original)
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))

        with self.assertRaises(ConversionCancelled):
            convert_sparse_to_raw(
                self.input_path,
                self.output_path,
                force=True,
                cancel_requested=lambda: True,
            )

        self.assertEqual(self.output_path.read_bytes(), original)
        self.assertEqual(
            sorted(path.name for path in self.root.iterdir()),
            ["sample.raw", "sample.sparse"],
        )

    def test_failed_crc_is_reported_to_event_callback(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(
            make_sparse([chunk(CHUNK_RAW, 1, raw_data), crc_chunk(0xDEADBEEF)], raw_data)
        )
        events: list[tuple[str, str]] = []
        with self.assertRaisesRegex(SparseImageError, "CRC32 mismatch"):
            convert_sparse_to_raw(
                self.input_path,
                self.output_path,
                event_callback=lambda level, message: events.append((level, message)),
            )
        self.assertTrue(any(level == "error" and "CRC32 mismatch" in message for level, message in events))
        self.assertFalse(self.output_path.exists())

    def test_cli_info_and_json_report(self) -> None:
        raw_data = b"DATA"
        self.input_path.write_bytes(make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data))
        report = self.root / "report.json"
        stdout = StringIO()
        stderr = StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main([str(self.input_path), "--info", "--quiet", "--json-report", str(report), "--sha256"])
        self.assertEqual(code, 0)
        self.assertIn("Validation successful", stdout.getvalue())
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["sha256"], hashlib.sha256(raw_data).hexdigest())
        self.assertFalse(self.output_path.exists())


if __name__ == "__main__":
    unittest.main()
