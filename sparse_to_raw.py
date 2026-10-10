#!/usr/bin/env python3
"""Convert Android Sparse Image files to raw images.

Uses only Python's standard library. Supports Android sparse format major
version 1, including RAW, FILL, DONT_CARE and CRC32 chunks. CRC32 chunks and
non-zero image-level checksums are validated before the output is committed.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
import zlib
from pathlib import Path
from typing import BinaryIO

MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4

HEADER_FMT = "<IHHHHIIII"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 28 bytes
CHUNK_HEADER_FMT = "<HHII"
CHUNK_HEADER_SIZE = struct.calcsize(CHUNK_HEADER_FMT)  # 12 bytes
COPY_BUFFER_SIZE = 1024 * 1024
ZERO_BUFFER = b"\x00" * COPY_BUFFER_SIZE


class SparseImageError(ValueError):
    """Raised when a sparse image is malformed or fails checksum checks."""


def _read_exact(stream: BinaryIO, count: int, what: str) -> bytes:
    """Read exactly count bytes or raise a useful format error."""
    chunks = bytearray()
    while len(chunks) < count:
        part = stream.read(count - len(chunks))
        if not part:
            raise SparseImageError(
                f"Unexpected end of file while reading {what} "
                f"(needed {count} bytes, got {len(chunks)})"
            )
        chunks.extend(part)
    return bytes(chunks)


def _update_crc_with_zeros(crc: int, count: int) -> int:
    """Update CRC32 as though count zero bytes were present, in bounded memory."""
    while count:
        part_len = min(COPY_BUFFER_SIZE, count)
        crc = zlib.crc32(ZERO_BUFFER[:part_len], crc)
        count -= part_len
    return crc & 0xFFFFFFFF


def _write_fill(
    output: BinaryIO, pattern: bytes, count: int, crc: int
) -> int:
    """Write count bytes made from a four-byte sparse FILL pattern."""
    if count % 4:
        raise SparseImageError("FILL chunk output size is not a multiple of 4")
    repeated = pattern * (COPY_BUFFER_SIZE // 4)
    while count:
        size = min(COPY_BUFFER_SIZE, count)
        # count and COPY_BUFFER_SIZE are multiples of four.
        block = repeated[:size]
        output.write(block)
        crc = zlib.crc32(block, crc)
        count -= size
    return crc & 0xFFFFFFFF


def convert_sparse_to_raw(input_path: str | Path, output_path: str | Path) -> dict[str, int]:
    """Convert a sparse image to raw format.

    The output is written to a temporary sibling file first and replaces the
    destination only after all structural and checksum validations succeed.
    DONT_CARE ranges read back as zero bytes; the OS may represent these ranges
    as sparse file holes, which preserves the correct logical file contents.
    """
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()

    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    if source == destination:
        raise ValueError("Input and output paths must be different")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Output directory not found: {destination.parent}")
    try:
        if destination.exists() and os.path.samefile(source, destination):
            raise ValueError("Input and output refer to the same file")
    except OSError:
        # samefile can fail for paths that do not exist; other path checks
        # above and opening the files below will provide the actionable error.
        pass

    temp_path: Path | None = None
    try:
        with source.open("rb") as input_stream:
            header_bytes = _read_exact(input_stream, HEADER_SIZE, "sparse header")
            (
                magic,
                major_version,
                minor_version,
                file_header_size,
                chunk_header_size,
                block_size,
                total_blocks,
                total_chunks,
                image_checksum,
            ) = struct.unpack(HEADER_FMT, header_bytes)

            if magic != MAGIC:
                raise SparseImageError(f"Invalid sparse magic: 0x{magic:08X}")
            if major_version != 1:
                raise SparseImageError(
                    f"Unsupported sparse major version: {major_version}"
                )
            if file_header_size < HEADER_SIZE:
                raise SparseImageError(
                    f"Invalid file header size: {file_header_size}"
                )
            if chunk_header_size < CHUNK_HEADER_SIZE:
                raise SparseImageError(
                    f"Invalid chunk header size: {chunk_header_size}"
                )
            if block_size == 0 or block_size % 4 != 0:
                raise SparseImageError(
                    f"Invalid block size {block_size}; it must be positive and divisible by 4"
                )

            _read_exact(
                input_stream,
                file_header_size - HEADER_SIZE,
                "extended sparse header",
            )

            raw_size = total_blocks * block_size
            print(f"Sparse input : {source}")
            print(f"Output       : {destination}")
            print(f"Block size   : {block_size}")
            print(f"Total blocks : {total_blocks}")
            print(f"Chunks       : {total_chunks}")
            print(f"Raw size     : {raw_size:,} bytes")
            print()

            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
            )
            temp_path = Path(temporary_name)
            running_crc = 0
            output_blocks = 0

            with os.fdopen(fd, "wb") as output_stream:
                for chunk_index in range(total_chunks):
                    chunk_header = _read_exact(
                        input_stream, chunk_header_size, f"chunk {chunk_index} header"
                    )
                    chunk_type, reserved, chunk_blocks, total_size = struct.unpack(
                        CHUNK_HEADER_FMT, chunk_header[:CHUNK_HEADER_SIZE]
                    )
                    if reserved != 0:
                        raise SparseImageError(
                            f"Chunk {chunk_index}: reserved field is not zero"
                        )

                    data_size = chunk_blocks * block_size
                    if chunk_type == CHUNK_RAW:
                        expected_size = chunk_header_size + data_size
                    elif chunk_type == CHUNK_FILL:
                        expected_size = chunk_header_size + 4
                    elif chunk_type == CHUNK_DONT_CARE:
                        expected_size = chunk_header_size
                    elif chunk_type == CHUNK_CRC32:
                        expected_size = chunk_header_size + 4
                        if chunk_blocks != 0:
                            raise SparseImageError(
                                f"Chunk {chunk_index}: CRC32 chunk must have zero blocks"
                            )
                    else:
                        raise SparseImageError(
                            f"Chunk {chunk_index}: unsupported type 0x{chunk_type:04X}"
                        )

                    if total_size != expected_size:
                        raise SparseImageError(
                            f"Chunk {chunk_index}: invalid total_sz "
                            f"(got {total_size}, expected {expected_size})"
                        )

                    if chunk_type != CHUNK_CRC32:
                        if output_blocks + chunk_blocks > total_blocks:
                            raise SparseImageError(
                                f"Chunk {chunk_index}: output exceeds declared total blocks"
                            )

                    if chunk_type == CHUNK_RAW:
                        remaining = data_size
                        while remaining:
                            amount = min(COPY_BUFFER_SIZE, remaining)
                            data = _read_exact(
                                input_stream, amount, f"RAW data in chunk {chunk_index}"
                            )
                            output_stream.write(data)
                            running_crc = zlib.crc32(data, running_crc)
                            remaining -= len(data)

                    elif chunk_type == CHUNK_FILL:
                        pattern = _read_exact(
                            input_stream, 4, f"FILL pattern in chunk {chunk_index}"
                        )
                        running_crc = _write_fill(
                            output_stream, pattern, data_size, running_crc
                        )

                    elif chunk_type == CHUNK_DONT_CARE:
                        # Sparse format CRCs treat DONT_CARE regions as zeroes.
                        running_crc = _update_crc_with_zeros(running_crc, data_size)
                        output_stream.seek(data_size, os.SEEK_CUR)

                    elif chunk_type == CHUNK_CRC32:
                        stored_crc = struct.unpack(
                            "<I",
                            _read_exact(
                                input_stream, 4, f"CRC32 value in chunk {chunk_index}"
                            ),
                        )[0]
                        if stored_crc != (running_crc & 0xFFFFFFFF):
                            raise SparseImageError(
                                f"CRC32 mismatch in chunk {chunk_index}: "
                                f"computed 0x{running_crc & 0xFFFFFFFF:08X}, "
                                f"stored 0x{stored_crc:08X}"
                            )

                    if chunk_type != CHUNK_CRC32:
                        output_blocks += chunk_blocks

                    print(
                        f"\rProcessed chunk {chunk_index + 1}/{total_chunks}",
                        end="",
                        flush=True,
                    )

                # Ensure trailing DONT_CARE blocks contribute to logical file size.
                output_stream.truncate(raw_size)

            print()
            print()

            if output_blocks != total_blocks:
                raise SparseImageError(
                    f"Block count mismatch: wrote {output_blocks}, expected {total_blocks}"
                )

            trailing = input_stream.read(1)
            if trailing:
                raise SparseImageError("Unexpected trailing bytes after the final chunk")

            running_crc &= 0xFFFFFFFF
            if image_checksum and image_checksum != running_crc:
                raise SparseImageError(
                    f"Image checksum mismatch: computed 0x{running_crc:08X}, "
                    f"header says 0x{image_checksum:08X}"
                )

        # Only replace the destination after all checks above have passed.
        os.replace(temp_path, destination)
        temp_path = None
        result = {
            "blocks": output_blocks,
            "raw_size": raw_size,
            "crc32": running_crc,
            "chunks": total_chunks,
        }
        print(f"Logical blocks written: {output_blocks}")
        print(f"Expected blocks:        {total_blocks}")
        print(f"Output size:            {destination.stat().st_size:,} bytes")
        print(f"Expected raw size:      {raw_size:,} bytes")
        print(f"Output CRC32:           0x{running_crc:08X}")
        print()
        print("Conversion completed successfully.")
        return result

    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert an Android Sparse Image (sparse) to a raw image."
    )
    parser.add_argument("input_sparse", help="input Android sparse image")
    parser.add_argument("output_raw", help="output raw image path")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    try:
        convert_sparse_to_raw(args.input_sparse, args.output_raw)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
