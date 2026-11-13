import tempfile
import unittest
import zlib
from pathlib import Path

from image_compare import ComparisonCancelled, ImageCompareError, compare_images
from raw_to_sparse import raw_to_sparse
from sparse_to_raw import main
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO


class ImageCompareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / 'image.raw'
        self.sparse = self.root / 'image.sparse'
        self.other = self.root / 'other.raw'

    def tearDown(self):
        self.tmp.cleanup()

    def make_pair(self, data):
        self.raw.write_bytes(data)
        raw_to_sparse(self.raw, self.sparse, block_size=4, calculate_sha256=True)

    def test_raw_matches_sparse_logically(self):
        data = b'ABCD' * 32 + b'\0' * 64 + bytes(range(64))
        self.make_pair(data)
        result = compare_images(self.raw, self.sparse)
        self.assertTrue(result['identical'])
        self.assertEqual(result['left_sha256'], result['right_sha256'])
        self.assertEqual(result['left_format'], 'RAW')
        self.assertEqual(result['right_format'], 'Android Sparse')
        self.assertIsNone(result['first_difference_offset'])

    def test_reports_first_difference_offset(self):
        self.make_pair(b'ABCDEFGH')
        self.other.write_bytes(b'ABXDEFGH')
        result = compare_images(self.raw, self.other)
        self.assertFalse(result['identical'])
        self.assertEqual(result['first_difference_offset'], 2)

    def test_reports_different_logical_lengths(self):
        self.make_pair(b'ABCDEFGH')
        self.other.write_bytes(b'ABCD')
        result = compare_images(self.raw, self.other)
        self.assertFalse(result['identical'])
        self.assertEqual(result['first_difference_offset'], 4)
        self.assertEqual(result['left_logical_size_bytes'], 8)
        self.assertEqual(result['right_logical_size_bytes'], 4)

    def test_sparse_to_sparse_comparison(self):
        self.make_pair(b'\x00' * 128)
        second_raw = self.root / 'second.raw'
        second_sparse = self.root / 'second.sparse'
        second_raw.write_bytes(b'\x00' * 128)
        raw_to_sparse(second_raw, second_sparse, block_size=16)
        self.assertTrue(compare_images(self.sparse, second_sparse)['identical'])

    def test_extended_sparse_chunk_header_is_supported(self):
        import struct
        self.make_pair(b"ABCD")
        data = bytearray(self.sparse.read_bytes())
        # Extend the file header and the chunk header; the payload must remain aligned.
        file_header = list(struct.unpack("<IHHHHIIII", data[:28]))
        file_header[3] = 32
        file_header[4] = 16
        data = bytearray(struct.pack("<IHHHHIIII", *file_header) + b"FILE" + data[28:])
        chunk = list(struct.unpack("<HHII", data[32:44]))
        chunk[3] = 20
        data[32:44] = struct.pack("<HHII", *chunk)
        data = data[:44] + b"CHNK" + data[44:]
        self.sparse.write_bytes(data)
        self.assertTrue(compare_images(self.raw, self.sparse)["identical"])

    def test_sparse_crc32_checkpoint_is_validated(self):
        import struct
        data = b"ABCDEFGH"
        self.raw.write_bytes(data)
        crc = zlib.crc32(data) & 0xFFFFFFFF
        header = struct.pack("<IHHHHIIII", 0xED26FF3A, 1, 0, 28, 12, 4, 2, 2, crc)
        raw_chunk = struct.pack("<HHII", 0xCAC1, 0, 2, 20) + data
        crc_chunk = struct.pack("<HHII", 0xCAC4, 0, 0, 16) + struct.pack("<I", crc)
        self.sparse.write_bytes(header + raw_chunk + crc_chunk)
        self.assertTrue(compare_images(self.raw, self.sparse)["identical"])
        damaged = bytearray(self.sparse.read_bytes())
        damaged[-1] ^= 0x01
        self.sparse.write_bytes(damaged)
        with self.assertRaisesRegex(ImageCompareError, "CRC32 mismatch"):
            compare_images(self.raw, self.sparse)

    def test_corrupt_sparse_checksum_is_rejected(self):
        self.make_pair(b'ABCD')
        data = bytearray(self.sparse.read_bytes())
        data[28 + 12] ^= 0x01
        self.sparse.write_bytes(data)
        with self.assertRaises(ImageCompareError):
            compare_images(self.raw, self.sparse)

    def test_cancel_is_supported(self):
        self.make_pair(b'ABCD' * 1024)
        with self.assertRaises(ComparisonCancelled):
            compare_images(self.raw, self.sparse, cancel_requested=lambda: True)

    def test_cli_writes_json_report_without_overwriting(self):
        self.make_pair(b"ABCDEFGH")
        report = self.root / "comparison.json"
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(["compare", str(self.raw), str(self.sparse), "--quiet", "--json-report", str(report)])
        self.assertEqual(code, 0)
        self.assertTrue(report.is_file())
        report.write_text("KEEP", encoding="utf-8")
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = main(["compare", str(self.raw), str(self.sparse), "--quiet", "--json-report", str(report)])
        self.assertEqual(code, 2)
        self.assertEqual(report.read_text(encoding="utf-8"), "KEEP")

    def test_cli_compare_success_and_difference_exit_codes(self):
        self.make_pair(b'ABCDEFGH')
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(['compare', str(self.raw), str(self.sparse), '--quiet'])
        self.assertEqual(code, 0)
        self.assertIn('"identical": true', out.getvalue())
        self.other.write_bytes(b'ABCXEFGH')
        with redirect_stdout(out := StringIO()), redirect_stderr(err := StringIO()):
            code = main(['compare', str(self.raw), str(self.other), '--quiet'])
        self.assertEqual(code, 1)
        self.assertIn('"identical": false', out.getvalue())


if __name__ == '__main__':
    unittest.main()
