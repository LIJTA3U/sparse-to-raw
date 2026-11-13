import json
import struct
import tempfile
import unittest
import zlib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from sparse_to_raw import ConversionCancelled, MAGIC, HEADER_FMT, CHUNK_RAW, CHUNK_CRC32
from sparse_validator import validate_sparse
from sparse_to_raw import main

CHUNK_FMT = "<HHII"


def make_sparse(path: Path, payload: bytes, *, checksum=True, checkpoint=False):
    block_size = 4
    blocks = len(payload) // block_size
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    chunks = [struct.pack(CHUNK_FMT, CHUNK_RAW, 0, blocks, 12 + len(payload)) + payload]
    if checkpoint:
        chunks.append(struct.pack(CHUNK_FMT, CHUNK_CRC32, 0, 0, 16) + struct.pack("<I", crc))
    header = struct.pack(
        HEADER_FMT, MAGIC, 1, 0, struct.calcsize(HEADER_FMT), struct.calcsize(CHUNK_FMT),
        block_size, blocks, len(chunks), crc if checksum else 0,
    )
    path.write_bytes(header + b"".join(chunks))


class SparseValidatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.path = self.root / "sample.sparse"

    def tearDown(self):
        self.temp.cleanup()

    def test_validates_structure_checksum_and_sha256(self):
        make_sparse(self.path, b"ANDROID-SPARSE-VALIDATE!")
        result = validate_sparse(self.path)
        self.assertTrue(result["valid"])
        self.assertFalse(result["raw_output_created"])
        self.assertEqual(result["validation_mode"], "streaming")
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["header"]["major_version"], 1)
        self.assertEqual(result["computed_crc32"], result["header_checksum"])
        self.assertEqual(len(result["logical_sha256"]), 64)
        self.assertTrue(all(item["status"] in {"passed", "computed", "not_present"} for item in result["checks"]))

    def test_reports_missing_integrity_values_as_warning_not_format_error(self):
        make_sparse(self.path, b"ABCD" * 8, checksum=False, checkpoint=False)
        result = validate_sparse(self.path)
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "valid_with_warnings")
        self.assertEqual(result["integrity_level"], "structure-only")
        self.assertTrue(result["warnings"])

    def test_validates_per_chunk_crc_checkpoint(self):
        make_sparse(self.path, b"DATA" * 4, checksum=False, checkpoint=True)
        result = validate_sparse(self.path)
        self.assertTrue(result["valid"])
        self.assertEqual(result["chunk_counts"]["CRC32"], 1)
        crc_check = next(x for x in result["checks"] if x["name"] == "crc32_checkpoints")
        self.assertEqual(crc_check["status"], "passed")
        self.assertEqual(result["integrity_level"], "CRC32-protected")

    def test_corrupted_crc_returns_invalid_report(self):
        make_sparse(self.path, b"ABCDEFGH", checksum=False, checkpoint=True)
        data = bytearray(self.path.read_bytes())
        data[-1] ^= 1
        self.path.write_bytes(data)
        result = validate_sparse(self.path)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "invalid")
        self.assertIn("CRC32 mismatch", result["errors"][0])

    def test_truncated_header_returns_structured_invalid_report(self):
        self.path.write_bytes(b"short")
        result = validate_sparse(self.path)
        self.assertFalse(result["valid"])
        self.assertEqual(result["checks"][0]["name"], "fixed_header")

    def test_sha256_can_be_skipped_and_no_raw_file_is_created(self):
        make_sparse(self.path, b"ABCD" * 16)
        before = set(self.root.iterdir())
        result = validate_sparse(self.path, calculate_sha256=False)
        after = set(self.root.iterdir())
        self.assertTrue(result["valid"])
        self.assertNotIn("logical_sha256", result)
        self.assertEqual(before, after)

    def test_cli_refuses_to_overwrite_existing_json_report(self):
        make_sparse(self.path, b"ABCDEFGH")
        report = self.root / "report.json"
        report.write_text("KEEP", encoding="utf-8")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(["validate", str(self.path), "--quiet", "--json-report", str(report)])
        self.assertEqual(code, 2)
        self.assertEqual(report.read_text(encoding="utf-8"), "KEEP")

    def test_cancel_is_propagated(self):
        make_sparse(self.path, b"A" * 4096)
        with self.assertRaises(ConversionCancelled):
            validate_sparse(self.path, cancel_requested=lambda: True)

    def test_cli_validate_success_and_invalid_exit_codes_and_report(self):
        make_sparse(self.path, b"ABCDEFGH")
        report = self.root / "report.json"
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(["validate", str(self.path), "--quiet", "--json-report", str(report)])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(report.read_text(encoding="utf-8"))["valid"])
        damaged = self.root / "damaged.sparse"
        raw = bytearray(self.path.read_bytes()); raw[-1] ^= 1; damaged.write_bytes(raw)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(["validate", str(damaged), "--quiet"])
        self.assertEqual(code, 1)

    def test_cli_refuses_report_path_collision(self):
        make_sparse(self.path, b"ABCDEFGH")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(["validate", str(self.path), "--json-report", str(self.path)])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
