import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path

from raw_to_sparse import RawToSparseError, raw_to_sparse
from sparse_to_raw import convert_sparse_to_raw, main

class RawToSparseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw = self.root / 'source.raw'
        self.sparse = self.root / 'source.sparse'
        self.restored = self.root / 'restored.raw'

    def tearDown(self):
        self.tmp.cleanup()

    def roundtrip(self, data, block_size=4):
        self.raw.write_bytes(data)
        result = raw_to_sparse(self.raw, self.sparse, block_size=block_size, calculate_sha256=True)
        convert_sparse_to_raw(self.sparse, self.restored)
        self.assertEqual(self.restored.read_bytes(), data)
        self.assertEqual(result['input_size_bytes'], len(data))
        return result

    def test_raw_fill_dont_care_and_mixed_roundtrip(self):
        data = (b'ABCD' * 4) + (b'\0' * 16) + (b'WXYZ' * 4) + bytes(range(16))
        result = self.roundtrip(data, block_size=16)
        self.assertGreater(result['chunk_counts']['FILL'], 0)
        self.assertGreater(result['chunk_counts']['DONT_CARE'], 0)
        self.assertGreater(result['chunk_counts']['RAW'], 0)

    def test_block_size_is_configurable(self):
        data = b'ABCD' * 32
        result = self.roundtrip(data, block_size=16)
        self.assertEqual(result['block_size'], 16)

    def test_all_zero_image_uses_dont_care(self):
        result = self.roundtrip(b'\0' * 64)
        self.assertEqual(result['chunk_counts']['DONT_CARE'], 1)
        self.assertLess(result['sparse_size_bytes'], result['input_size_bytes'])

    def test_fill_image_uses_fill_chunk(self):
        result = self.roundtrip(b'\x12\x34\x56\x78' * 32)
        self.assertEqual(result['chunk_counts']['FILL'], 1)

    def test_rejects_invalid_block_sizes(self):
        self.raw.write_bytes(b'12345678')
        for size in (0, 2, 3, 6, 2 * 1024 * 1024):
            with self.subTest(size=size), self.assertRaises(RawToSparseError):
                raw_to_sparse(self.raw, self.sparse, block_size=size)

    def test_rejects_non_aligned_and_empty_input(self):
        for data in (b'', b'12345'):
            self.raw.write_bytes(data)
            with self.subTest(data=data), self.assertRaises(RawToSparseError):
                raw_to_sparse(self.raw, self.sparse, block_size=4)

    def test_existing_output_is_protected(self):
        self.raw.write_bytes(b'ABCD')
        self.sparse.write_bytes(b'KEEP')
        with self.assertRaises(FileExistsError):
            raw_to_sparse(self.raw, self.sparse)
        self.assertEqual(self.sparse.read_bytes(), b'KEEP')


    def test_cli_raw_to_sparse_roundtrip(self):
        self.raw.write_bytes((b'ABCD' * 16) + (b'\0' * 64))
        stdout, stderr = StringIO(), StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(['raw-to-sparse', str(self.raw), str(self.sparse), '--block-size', '16', '--quiet'])
        self.assertEqual(code, 0)
        self.assertIn('sparse_size_bytes', stdout.getvalue())
        convert_sparse_to_raw(self.sparse, self.restored)
        self.assertEqual(self.restored.read_bytes(), self.raw.read_bytes())

    def test_cancel_does_not_commit_partial_output(self):
        self.raw.write_bytes(b'ABCD' * 64)
        with self.assertRaises(InterruptedError):
            raw_to_sparse(self.raw, self.sparse, block_size=4, cancel_requested=lambda: True)
        self.assertFalse(self.sparse.exists())

if __name__ == '__main__':
    unittest.main()
