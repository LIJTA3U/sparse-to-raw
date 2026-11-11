#!/usr/bin/env python3
"""Streaming RAW to Android Sparse Image encoder (stdlib only)."""
from __future__ import annotations
import hashlib, os, struct, tempfile, zlib
from pathlib import Path
from typing import Any, Callable, BinaryIO

MAGIC = 0xED26FF3A
CHUNK_RAW, CHUNK_FILL, CHUNK_DONT_CARE = 0xCAC1, 0xCAC2, 0xCAC3
FILE_HEADER = struct.Struct('<IHHHHIIII')
CHUNK_HEADER = struct.Struct('<HHII')
COPY_BUFFER_SIZE = 1024 * 1024
Progress = Callable[[dict[str, Any]], None]
Cancel = Callable[[], bool]

class RawToSparseError(ValueError):
    """Invalid RAW input or Sparse output parameters."""


def _classify(block: bytes) -> tuple[int, bytes]:
    if not any(block):
        return CHUNK_DONT_CARE, b''
    if len(block) >= 4 and block == block[:4] * (len(block) // 4):
        return CHUNK_FILL, block[:4]
    return CHUNK_RAW, block


def raw_to_sparse(input_path: str | Path, output_path: str | Path, *, block_size: int = 4096,
                  force: bool = False, progress_callback: Progress | None = None,
                  cancel_requested: Cancel | None = None, calculate_sha256: bool = False) -> dict[str, Any]:
    """Encode a RAW image into Android Sparse v1.0 using bounded memory and atomic output."""
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f'Input RAW file not found: {source}')
    if source == destination:
        raise RawToSparseError('Input and output paths must be different')
    if not destination.parent.is_dir():
        raise FileNotFoundError(f'Output directory not found: {destination.parent}')
    if destination.exists() and not force:
        raise FileExistsError(f'File already exists: {destination} (use --force to overwrite)')
    if not isinstance(block_size, int) or block_size < 4 or block_size > 1024 * 1024 or block_size % 4:
        raise RawToSparseError('Block size must be a multiple of 4 between 4 and 1048576 bytes')
    size = source.stat().st_size
    if size == 0 or size % block_size:
        raise RawToSparseError(f'RAW size ({size}) must be non-zero and divisible by block size ({block_size})')
    total_blocks = size // block_size
    if total_blocks > 0xFFFFFFFF:
        raise RawToSparseError('RAW image exceeds Android Sparse v1.0 block-count limit')
    fd, temp_name = tempfile.mkstemp(prefix=f'.{destination.name}.', suffix='.tmp', dir=destination.parent)
    temp = Path(temp_name)
    counts = {'RAW': 0, 'FILL': 0, 'DONT_CARE': 0}
    sha = hashlib.sha256() if calculate_sha256 else None
    crc = 0
    chunks = 0
    done = 0
    current_kind = None
    current_fill = None
    current_blocks = 0
    raw_payload = bytearray()
    raw_blocks = 0
    last_report = 0

    def emit(kind: int, blocks: int, payload: bytes = b'') -> None:
        nonlocal chunks
        total_sz = CHUNK_HEADER.size + len(payload)
        if blocks <= 0 or total_sz > 0xFFFFFFFF:
            raise RawToSparseError('Sparse chunk exceeds format limits')
        stream.write(CHUNK_HEADER.pack(kind, 0, blocks, total_sz))
        if payload:
            stream.write(payload)
        chunks += 1
        counts[{CHUNK_RAW:'RAW', CHUNK_FILL:'FILL', CHUNK_DONT_CARE:'DONT_CARE'}[kind]] += 1

    try:
        with os.fdopen(fd, 'w+b') as stream, source.open('rb') as src:
            stream.write(b'\0' * FILE_HEADER.size)
            while True:
                block = src.read(block_size)
                if not block:
                    break
                if len(block) != block_size:
                    raise RawToSparseError('Input RAW changed or ended during conversion')
                if cancel_requested and cancel_requested():
                    raise InterruptedError('Conversion cancelled')
                crc = zlib.crc32(block, crc)
                if sha:
                    sha.update(block)
                kind, fill = _classify(block)
                if kind == CHUNK_RAW:
                    if current_kind in (CHUNK_FILL, CHUNK_DONT_CARE):
                        emit(current_kind, current_blocks, current_fill or b'')
                        current_kind = None; current_blocks = 0; current_fill = None
                    if current_kind != CHUNK_RAW:
                        if raw_blocks:
                            emit(CHUNK_RAW, raw_blocks, bytes(raw_payload))
                            raw_payload.clear(); raw_blocks = 0
                        current_kind = CHUNK_RAW
                    raw_payload.extend(block); raw_blocks += 1
                    if len(raw_payload) >= COPY_BUFFER_SIZE:
                        emit(CHUNK_RAW, raw_blocks, bytes(raw_payload))
                        raw_payload.clear(); raw_blocks = 0; current_kind = None
                else:
                    if raw_blocks:
                        emit(CHUNK_RAW, raw_blocks, bytes(raw_payload))
                        raw_payload.clear(); raw_blocks = 0
                    if current_kind == kind and (kind != CHUNK_FILL or current_fill == fill):
                        current_blocks += 1
                    else:
                        if current_kind in (CHUNK_FILL, CHUNK_DONT_CARE):
                            emit(current_kind, current_blocks, current_fill or b'')
                        current_kind, current_blocks, current_fill = kind, 1, (fill if kind == CHUNK_FILL else None)
                done += 1
                if progress_callback and (done == total_blocks or done - last_report >= max(1, total_blocks // 200)):
                    progress_callback({'stage':'encoding','completed_blocks':done,'total_blocks':total_blocks,'percent':done*100/total_blocks})
                    last_report = done
            if done != total_blocks:
                raise RawToSparseError('Input RAW size changed during conversion')
            if raw_blocks:
                emit(CHUNK_RAW, raw_blocks, bytes(raw_payload))
            if current_kind in (CHUNK_FILL, CHUNK_DONT_CARE):
                emit(current_kind, current_blocks, current_fill or b'')
            header = FILE_HEADER.pack(MAGIC, 1, 0, FILE_HEADER.size, CHUNK_HEADER.size,
                                      block_size, total_blocks, chunks, crc & 0xFFFFFFFF)
            stream.seek(0); stream.write(header); stream.flush(); os.fsync(stream.fileno())
        if destination.exists() and not force:
            raise FileExistsError(f'File already exists: {destination} (use --force to overwrite)')
        if force:
            os.replace(temp, destination)
        else:
            os.link(temp, destination); temp.unlink()
        result = {'input':str(source),'output':str(destination),'input_size_bytes':size,
                  'sparse_size_bytes':destination.stat().st_size,'block_size':block_size,
                  'total_blocks':total_blocks,'total_chunks':chunks,'chunk_counts':counts,
                  'computed_crc32':f'0x{crc & 0xFFFFFFFF:08X}','sha256':sha.hexdigest() if sha else None}
        if progress_callback:
            progress_callback({'stage':'completed','completed_blocks':total_blocks,'total_blocks':total_blocks,'percent':100.0})
        return result
    finally:
        try: temp.unlink(missing_ok=True)
        except OSError: pass
