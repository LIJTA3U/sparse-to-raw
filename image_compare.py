#!/usr/bin/env python3
"""Compare logical contents of Android Sparse and RAW images, streaming."""
from __future__ import annotations

import hashlib
import os
import struct
import time
import zlib
from pathlib import Path
from typing import Any, Callable, Iterator, BinaryIO

SPARSE_MAGIC = 0xED26FF3A
FILE_HEADER = struct.Struct('<IHHHHIIII')
CHUNK_HEADER = struct.Struct('<HHII')
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT_CARE = 0xCAC3
CHUNK_CRC32 = 0xCAC4
BUFFER_SIZE = 1024 * 1024
ZERO_BUFFER = b'\0' * BUFFER_SIZE


class ImageCompareError(ValueError):
    """An input image is malformed or cannot be logically compared."""


class ComparisonCancelled(InterruptedError):
    """The caller cancelled the comparison."""


ProgressCallback = Callable[[dict[str, Any]], None]
CancelCallback = Callable[[], bool]


def _read_exact(stream: BinaryIO, size: int, label: str) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise ImageCompareError(
                f'Unexpected end of file while reading {label} '
                f'(needed {size} bytes, got {len(chunks)})'
            )
        chunks.extend(part)
    return bytes(chunks)


def _is_sparse(path: Path) -> bool:
    with path.open('rb') as stream:
        marker = stream.read(4)
    return len(marker) == 4 and struct.unpack('<I', marker)[0] == SPARSE_MAGIC


def _sparse_logical_size(path: Path) -> int:
    with path.open('rb') as stream:
        header = _read_exact(stream, FILE_HEADER.size, 'Sparse file header')
    magic, major, _minor, file_header_size, chunk_header_size, block_size, total_blocks, _chunks, _crc = FILE_HEADER.unpack(header)
    if magic != SPARSE_MAGIC:
        raise ImageCompareError(f'Invalid Android Sparse magic: 0x{magic:08X}')
    if major != 1:
        raise ImageCompareError(f'Unsupported Android Sparse major version: {major}')
    if file_header_size < FILE_HEADER.size or chunk_header_size < CHUNK_HEADER.size:
        raise ImageCompareError('Invalid Android Sparse header size')
    if block_size == 0 or block_size % 4:
        raise ImageCompareError(f'Invalid Android Sparse block size: {block_size}')
    return block_size * total_blocks


class _LogicalReader:
    """Buffered logical byte reader over either a RAW file or Sparse stream."""
    def __init__(self, path: Path, cancel_requested: CancelCallback | None = None) -> None:
        self.path = path
        self.cancel_requested = cancel_requested
        self.format = 'Android Sparse' if _is_sparse(path) else 'RAW'
        self.logical_size = _sparse_logical_size(path) if self.format == 'Android Sparse' else path.stat().st_size
        self._stream = path.open('rb')
        self._iterator = self._raw_chunks() if self.format == 'RAW' else self._sparse_chunks()
        self._pending = b''
        self._eof = False
        self._raw_read = 0

    def close(self) -> None:
        self._stream.close()

    def _check_cancel(self) -> None:
        if self.cancel_requested and self.cancel_requested():
            raise ComparisonCancelled('Comparison cancelled by user')

    def _raw_chunks(self) -> Iterator[bytes]:
        while True:
            self._check_cancel()
            data = self._stream.read(BUFFER_SIZE)
            if not data:
                break
            self._raw_read += len(data)
            yield data
        if self._raw_read != self.logical_size:
            raise ImageCompareError('RAW input size changed while it was being compared')

    def _sparse_chunks(self) -> Iterator[bytes]:
        stream = self._stream
        header = _read_exact(stream, FILE_HEADER.size, 'Sparse file header')
        (magic, major, _minor, file_header_size, chunk_header_size,
         block_size, total_blocks, total_chunks, image_checksum) = FILE_HEADER.unpack(header)
        if block_size * total_blocks != self.logical_size:
            raise ImageCompareError('Sparse input changed while it was being compared')
        if magic != SPARSE_MAGIC:
            raise ImageCompareError(f'Invalid Android Sparse magic: 0x{magic:08X}')
        if major != 1:
            raise ImageCompareError(f'Unsupported Android Sparse major version: {major}')
        if file_header_size < FILE_HEADER.size or chunk_header_size < CHUNK_HEADER.size:
            raise ImageCompareError('Invalid Android Sparse header size')
        if block_size == 0 or block_size % 4:
            raise ImageCompareError(f'Invalid Android Sparse block size: {block_size}')
        _read_exact(stream, file_header_size - FILE_HEADER.size, 'extended Sparse file header')

        output_blocks = 0
        running_crc = 0
        for index in range(total_chunks):
            self._check_cancel()
            chunk_data = _read_exact(stream, chunk_header_size, f'chunk {index} header')
            chunk_type, reserved, chunk_blocks, total_size = CHUNK_HEADER.unpack(chunk_data[:CHUNK_HEADER.size])
            if reserved != 0:
                raise ImageCompareError(f'Chunk {index}: reserved field is not zero')
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
                    raise ImageCompareError(f'Chunk {index}: CRC32 chunk must have zero blocks')
            else:
                raise ImageCompareError(f'Chunk {index}: unsupported type 0x{chunk_type:04X}')
            if total_size != expected_size:
                raise ImageCompareError(
                    f'Chunk {index}: invalid total_sz (got {total_size}, expected {expected_size})'
                )
            if chunk_type != CHUNK_CRC32 and output_blocks + chunk_blocks > total_blocks:
                raise ImageCompareError(f'Chunk {index}: output exceeds declared total blocks')

            if chunk_type == CHUNK_RAW:
                remaining = data_size
                while remaining:
                    self._check_cancel()
                    part = _read_exact(stream, min(BUFFER_SIZE, remaining), f'RAW data in chunk {index}')
                    running_crc = zlib.crc32(part, running_crc)
                    remaining -= len(part)
                    yield part
            elif chunk_type == CHUNK_FILL:
                pattern = _read_exact(stream, 4, f'FILL pattern in chunk {index}')
                if data_size % 4:
                    raise ImageCompareError(f'Chunk {index}: FILL output size is not divisible by 4')
                repeated = pattern * (BUFFER_SIZE // 4)
                remaining = data_size
                while remaining:
                    self._check_cancel()
                    amount = min(BUFFER_SIZE, remaining)
                    part = repeated[:amount]
                    running_crc = zlib.crc32(part, running_crc)
                    remaining -= amount
                    yield part
            elif chunk_type == CHUNK_DONT_CARE:
                remaining = data_size
                while remaining:
                    self._check_cancel()
                    amount = min(BUFFER_SIZE, remaining)
                    part = ZERO_BUFFER[:amount]
                    running_crc = zlib.crc32(part, running_crc)
                    remaining -= amount
                    yield part
            else:
                stored_crc = struct.unpack('<I', _read_exact(stream, 4, f'CRC32 value in chunk {index}'))[0]
                computed_crc = running_crc & 0xFFFFFFFF
                if stored_crc != computed_crc:
                    raise ImageCompareError(
                        f'CRC32 mismatch in chunk {index}: computed 0x{computed_crc:08X}, stored 0x{stored_crc:08X}'
                    )

            if chunk_type != CHUNK_CRC32:
                output_blocks += chunk_blocks

        if output_blocks != total_blocks:
            raise ImageCompareError(
                f'Block count mismatch: expanded {output_blocks}, expected {total_blocks}'
            )
        if stream.read(1):
            raise ImageCompareError('Unexpected trailing bytes after the final Sparse chunk')
        computed = running_crc & 0xFFFFFFFF
        if image_checksum and image_checksum != computed:
            raise ImageCompareError(
                f'Image checksum mismatch: computed 0x{computed:08X}, header says 0x{image_checksum:08X}'
            )

    def read(self, size: int) -> bytes:
        if size <= 0 or self._eof:
            return b''
        output = bytearray()
        while len(output) < size:
            self._check_cancel()
            if self._pending:
                take = min(size - len(output), len(self._pending))
                output.extend(self._pending[:take])
                self._pending = self._pending[take:]
                continue
            try:
                self._pending = next(self._iterator)
            except StopIteration:
                self._eof = True
                break
        return bytes(output)


def compare_images(
    left_path: str | Path,
    right_path: str | Path,
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Compare logical content of two RAW/Sparse files with bounded memory.

    Sparse chunks are expanded in memory only in 1 MiB windows. The function
    validates Sparse structure, chunk CRCs and the optional image checksum while
    calculating SHA-256 over both logical byte streams.
    """
    left = Path(left_path).expanduser().resolve()
    right = Path(right_path).expanduser().resolve()
    if not left.is_file():
        raise FileNotFoundError(f'Left input file not found: {left}')
    if not right.is_file():
        raise FileNotFoundError(f'Right input file not found: {right}')
    start = time.perf_counter()
    readers: list[_LogicalReader] = []
    try:
        readers = [_LogicalReader(left, cancel_requested), _LogicalReader(right, cancel_requested)]
        a, b = readers
        total = max(a.logical_size, b.logical_size)
        hashes = [hashlib.sha256(), hashlib.sha256()]
        offset = 0
        first_difference: int | None = None
        differing_windows = 0
        while True:
            if cancel_requested and cancel_requested():
                raise ComparisonCancelled('Comparison cancelled by user')
            left_data = a.read(BUFFER_SIZE)
            right_data = b.read(BUFFER_SIZE)
            if not left_data and not right_data:
                break
            hashes[0].update(left_data)
            hashes[1].update(right_data)
            common = min(len(left_data), len(right_data))
            different = len(left_data) != len(right_data)
            if common and left_data[:common] != right_data[:common]:
                different = True
                if first_difference is None:
                    first_difference = offset + next(
                        i for i, (x, y) in enumerate(zip(left_data[:common], right_data[:common])) if x != y
                    )
            if len(left_data) != len(right_data) and first_difference is None:
                first_difference = offset + common
            if different:
                differing_windows += 1
            offset += max(len(left_data), len(right_data))
            processed = min(offset, total)
            if progress_callback:
                elapsed = max(time.perf_counter() - start, 0.001)
                progress_callback({
                    'stage': 'comparing', 'processed_bytes': processed,
                    'total_bytes': total, 'percent': 100.0 if total == 0 else min(100.0, processed * 100.0 / total),
                    'speed_bytes_per_second': processed / elapsed,
                    'elapsed_seconds': elapsed,
                })
        # If one logical stream ended first, consume the remainder to finalize its
        # structure/checksums and the other side's digest.
        if a.logical_size != b.logical_size and first_difference is None:
            first_difference = min(a.logical_size, b.logical_size)
        identical = a.logical_size == b.logical_size and first_difference is None and hashes[0].digest() == hashes[1].digest()
        elapsed = max(time.perf_counter() - start, 0.0)
        result = {
            'operation': 'logical-image-comparison',
            'left': str(left), 'right': str(right),
            'left_format': a.format, 'right_format': b.format,
            'left_file_size_bytes': left.stat().st_size,
            'right_file_size_bytes': right.stat().st_size,
            'left_logical_size_bytes': a.logical_size,
            'right_logical_size_bytes': b.logical_size,
            'logical_size_bytes': a.logical_size if a.logical_size == b.logical_size else None,
            'identical': identical,
            'first_difference_offset': first_difference,
            'differing_windows': differing_windows,
            'left_sha256': hashes[0].hexdigest(),
            'right_sha256': hashes[1].hexdigest(),
            'processed_bytes': min(a.logical_size, b.logical_size),
            'duration_seconds': round(elapsed, 6),
            'average_bytes_per_second': round(min(a.logical_size, b.logical_size) / elapsed, 2) if elapsed else 0.0,
        }
        if progress_callback:
            progress_callback({
                'stage': 'completed', 'processed_bytes': max(a.logical_size, b.logical_size),
                'total_bytes': total, 'percent': 100.0,
                'speed_bytes_per_second': result['average_bytes_per_second'],
                'elapsed_seconds': elapsed,
            })
        return result
    finally:
        for reader in readers:
            try:
                reader.close()
            except OSError:
                pass
