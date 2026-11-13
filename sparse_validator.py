#!/usr/bin/env python3
"""Detailed, streaming validation for Android Sparse images."""
from __future__ import annotations

import struct
import time
from pathlib import Path
from typing import Any, Callable

from sparse_to_raw import (
    ConversionCancelled,
    SparseImageError,
    inspect_sparse,
)

SPARSE_HEADER = struct.Struct("<IHHHHIIII")
SPARSE_MAGIC = 0xED26FF3A

ProgressCallback = Callable[[dict[str, Any]], None]
CancelCallback = Callable[[], bool]


def _read_header(path: Path) -> dict[str, Any]:
    """Read the fixed header for a useful partial report, even on failure."""
    with path.open("rb") as stream:
        data = stream.read(SPARSE_HEADER.size)
    if len(data) != SPARSE_HEADER.size:
        raise SparseImageError(
            f"Sparse file header is truncated (needed {SPARSE_HEADER.size} bytes, got {len(data)})"
        )
    magic, major, minor, file_header_size, chunk_header_size, block_size, total_blocks, total_chunks, checksum = SPARSE_HEADER.unpack(data)
    return {
        "magic": f"0x{magic:08X}",
        "magic_valid": magic == SPARSE_MAGIC,
        "major_version": major,
        "minor_version": minor,
        "file_header_size": file_header_size,
        "chunk_header_size": chunk_header_size,
        "block_size": block_size,
        "total_blocks": total_blocks,
        "total_chunks": total_chunks,
        "header_checksum": f"0x{checksum:08X}",
        "header_checksum_present": checksum != 0,
    }


def validate_sparse(
    input_path: str | Path,
    *,
    calculate_sha256: bool = True,
    progress_callback: ProgressCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Validate the complete Sparse structure and integrity checks in a stream.

    The underlying parser reads payloads in bounded chunks and never creates a
    RAW output. Malformed images return a structured invalid report; filesystem
    errors and cancellation are raised to the caller.
    """
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    started = time.perf_counter()
    file_size = source.stat().st_size
    header: dict[str, Any] = {}
    try:
        header = _read_header(source)
    except SparseImageError as exc:
        elapsed = time.perf_counter() - started
        return {
            "operation": "sparse-validation",
            "input": str(source),
            "validation_mode": "streaming",
            "raw_output_created": False,
            "valid": False,
            "status": "invalid",
            "file_size_bytes": file_size,
            "header": header,
            "checks": [{"name": "fixed_header", "status": "failed", "details": str(exc)}],
            "errors": [str(exc)],
            "warnings": [],
            "duration_seconds": round(elapsed, 6),
        }

    def relay_progress(item: dict[str, Any]) -> None:
        if progress_callback is not None:
            data = dict(item)
            data.setdefault("stage", "validating")
            progress_callback(data)

    try:
        parsed = inspect_sparse(
            source,
            calculate_sha256=calculate_sha256,
            mode="verify",
            progress_callback=relay_progress,
            cancel_requested=cancel_requested,
        )
    except ConversionCancelled:
        raise
    except SparseImageError as exc:
        elapsed = time.perf_counter() - started
        return {
            "operation": "sparse-validation",
            "input": str(source),
            "validation_mode": "streaming",
            "raw_output_created": False,
            "valid": False,
            "status": "invalid",
            "file_size_bytes": file_size,
            "header": header,
            "checks": [
                {"name": "fixed_header_read", "status": "passed"},
                {"name": "full_sparse_validation", "status": "failed", "details": str(exc)},
            ],
            "errors": [str(exc)],
            "warnings": [],
            "duration_seconds": round(elapsed, 6),
        }

    elapsed = time.perf_counter() - started
    counts = parsed.get("chunk_counts", {})
    crc_chunks = int(counts.get("CRC32", 0))
    checksum_present = int(parsed.get("header_checksum", "0x00000000"), 16) != 0
    warnings: list[str] = []
    notes: list[str] = []
    if not checksum_present:
        notes.append("The header image checksum is not set.")
    if crc_chunks == 0:
        notes.append("The image contains no CRC32 checkpoint chunks.")
    if not checksum_present and crc_chunks == 0:
        warnings.append(
            "No stored CRC32 integrity values are present. The structure and payload were read successfully, "
            "but the file does not provide an internal checksum for independent corruption detection."
        )

    raw_size = int(parsed.get("raw_size_bytes", parsed.get("raw_size", 0)))
    saved_percent = (1.0 - file_size / raw_size) * 100.0 if raw_size > 0 else 0.0
    checks = [
        {"name": "sparse_header", "status": "passed"},
        {"name": "chunk_headers_and_payload_sizes", "status": "passed"},
        {"name": "supported_chunk_types", "status": "passed"},
        {"name": "expanded_block_accounting", "status": "passed"},
        {"name": "file_boundary_and_trailing_data", "status": "passed"},
        {
            "name": "crc32_checkpoints",
            "status": "passed" if crc_chunks else "not_present",
            "count": crc_chunks,
        },
        {
            "name": "header_image_checksum",
            "status": "passed" if checksum_present else "not_present",
            "stored": parsed.get("header_checksum"),
            "computed": parsed.get("computed_crc32"),
        },
    ]
    if calculate_sha256 and parsed.get("sha256"):
        checks.append({"name": "logical_sha256", "status": "computed"})

    result: dict[str, Any] = {
        "operation": "sparse-validation",
        "input": str(source),
        "validation_mode": "streaming",
        "raw_output_created": False,
        "valid": True,
        "status": "valid_with_warnings" if warnings else "valid",
        "file_size_bytes": file_size,
        "raw_size_bytes": raw_size,
        "space_savings_percent": round(saved_percent, 3),
        "format": parsed.get("format"),
        "header": header,
        "chunk_counts": counts,
        "total_chunks": int(parsed.get("total_chunks", 0)),
        "total_blocks": int(parsed.get("total_blocks", parsed.get("blocks", 0))),
        "computed_crc32": parsed.get("computed_crc32"),
        "header_checksum": parsed.get("header_checksum"),
        "integrity_level": "CRC32-protected" if checksum_present or crc_chunks else "structure-only",
        "checks": checks,
        "notes": notes,
        "warnings": warnings,
        "errors": [],
        "duration_seconds": round(elapsed, 6),
    }
    if calculate_sha256 and parsed.get("sha256"):
        result["logical_sha256"] = parsed["sha256"]
    return result
