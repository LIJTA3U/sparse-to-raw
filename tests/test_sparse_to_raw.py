import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from sparse_to_raw import (
    CHUNK_CRC32,
    CHUNK_DONT_CARE,
    CHUNK_FILL,
    CHUNK_RAW,
    HEADER_FMT,
    MAGIC,
    SparseImageError,
    convert_sparse_to_raw,
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
        # Four 4-byte blocks: RAW, FILL, DONT_CARE-as-zero, RAW.
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
        self.assertEqual(result["blocks"], 4)
        self.assertEqual(result["crc32"], zlib.crc32(raw_data) & 0xFFFFFFFF)

    def test_trailing_dont_care_gets_correct_size(self) -> None:
        raw_data = b"DATA" + (b"\x00" * 8)
        chunks = [chunk(CHUNK_RAW, 1, b"DATA"), chunk(CHUNK_DONT_CARE, 2)]
        self.input_path.write_bytes(make_sparse(chunks, raw_data))

        convert_sparse_to_raw(self.input_path, self.output_path)

        self.assertEqual(self.output_path.read_bytes(), raw_data)
        self.assertEqual(self.output_path.stat().st_size, 12)

    def test_bad_chunk_crc_is_rejected_and_output_not_committed(self) -> None:
        raw_data = b"ABCD"
        chunks = [chunk(CHUNK_RAW, 1, raw_data), crc_chunk(0x12345678)]
        self.input_path.write_bytes(make_sparse(chunks, raw_data))

        with self.assertRaisesRegex(SparseImageError, "CRC32 mismatch"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_bad_image_checksum_is_rejected(self) -> None:
        raw_data = b"ABCD"
        chunks = [chunk(CHUNK_RAW, 1, raw_data)]
        self.input_path.write_bytes(make_sparse(chunks, raw_data, image_checksum=0xDEADBEEF))

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
        sparse = make_sparse([chunk(CHUNK_RAW, 1, raw_data)], raw_data) + b"EXTRA"
        self.input_path.write_bytes(sparse)
        with self.assertRaisesRegex(SparseImageError, "Unexpected trailing bytes"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertFalse(self.output_path.exists())

    def test_existing_destination_survives_failed_conversion(self) -> None:
        self.output_path.write_bytes(b"KEEP")
        raw_data = b"ABCD"
        chunks = [chunk(CHUNK_RAW, 1, raw_data), crc_chunk(0x12345678)]
        self.input_path.write_bytes(make_sparse(chunks, raw_data))
        with self.assertRaisesRegex(SparseImageError, "CRC32 mismatch"):
            convert_sparse_to_raw(self.input_path, self.output_path)
        self.assertEqual(self.output_path.read_bytes(), b"KEEP")


if __name__ == "__main__":
    unittest.main()
