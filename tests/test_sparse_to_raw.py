import hashlib
import json
import struct
import tempfile
import unittest
import zlib
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
    inspect_sparse,
    merge_sparse_to_raw,
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
