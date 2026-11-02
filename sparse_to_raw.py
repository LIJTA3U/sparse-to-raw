#!/usr/bin/env python3
"""Convert and inspect Android Sparse Image files using only the stdlib."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import BinaryIO, Any, Callable

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
CHUNK_NAMES = {
    CHUNK_RAW: "RAW",
    CHUNK_FILL: "FILL",
    CHUNK_DONT_CARE: "DONT_CARE",
    CHUNK_CRC32: "CRC32",
}


class SparseImageError(ValueError):
    """Raised when a sparse image is malformed or fails checksum checks."""


class ConversionCancelled(Exception):
    """Raised when a caller safely cancels an operation before commit."""


class InsufficientDiskSpaceError(OSError):
    """Raised when preflight estimates that an operation will not fit."""


class OutputVerificationError(OSError):
    """Raised when the staged RAW output does not match the expected contents."""


ProgressCallback = Callable[[dict[str, Any]], None]
EventCallback = Callable[[str, str], None]
CancelCallback = Callable[[], bool]


def _read_exact(stream: BinaryIO, count: int, what: str) -> bytes:
    """Read exactly ``count`` bytes or raise a useful format error."""
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


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if value < 1024 or unit == "PiB":
            return f"{size:,} B" if unit == "B" else f"{value:.2f} {unit}"
        value /= 1024
    return f"{size:,} B"


def _format_duration(seconds: float) -> str:
    """Format elapsed seconds as MM:SS or HH:MM:SS."""
    value = max(0, int(seconds))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _atomic_write_text(path: Path, content: str, *, force: bool) -> None:
    """Atomically write UTF-8 text without clobbering files unless forced."""
    if path.exists() and not force:
        raise FileExistsError(f"File already exists: {path} (use --force to overwrite)")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Output directory not found: {path.parent}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if force:
            os.replace(temp_path, path)
        else:
            # A hard link gives us an atomic no-clobber commit on the same filesystem.
            try:
                os.link(temp_path, path)
            except FileExistsError:
                raise FileExistsError(
                    f"File already exists: {path} (use --force to overwrite)"
                ) from None
            temp_path.unlink()
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _verify_raw_file(
    path: str | Path,
    expected_size_bytes: int,
    expected_sha256: str,
    *,
    progress_callback: ProgressCallback | None = None,
    event_callback: EventCallback | None = None,
    cancel_requested: CancelCallback | None = None,
    show_progress: bool = False,
) -> dict[str, Any]:
    """Re-read a staged RAW file and verify its exact size and logical-content SHA-256.

    The file is read in bounded chunks. Callers must run this before atomically
    publishing the staging file so a failed verification never replaces an
    existing destination.
    """
    target = Path(path)
    started = time.monotonic()

    def notify(level: str, message: str) -> None:
        if event_callback is not None:
            event_callback(level, message)

    def check_cancelled() -> None:
        if cancel_requested is not None and cancel_requested():
            notify("warning", "RAW output verification cancelled; staged output will be discarded.")
            raise ConversionCancelled("Output verification cancelled by user")

    try:
        before = target.stat()
    except OSError as exc:
        raise OutputVerificationError(f"Cannot inspect staged RAW output {target}: {exc}") from exc

    if not target.is_file():
        raise OutputVerificationError(f"Staged RAW output is not a regular file: {target}")
    if before.st_size != expected_size_bytes:
        raise OutputVerificationError(
            f"RAW output size mismatch before verification: got {before.st_size} bytes, "
            f"expected {expected_size_bytes} bytes"
        )

    digest = hashlib.sha256()
    verified_bytes = 0
    notify("info", f"Re-reading staged RAW output for SHA-256 verification: {target}")

    def report_progress() -> None:
        elapsed = max(time.monotonic() - started, 0.001)
        if progress_callback is not None:
            progress_callback({
                "stage": "verification",
                "verified_bytes": verified_bytes,
                "expected_bytes": expected_size_bytes,
                "speed_bytes_per_second": verified_bytes / elapsed,
                "elapsed_seconds": elapsed,
            })
        if show_progress:
            percent = 100 if expected_size_bytes == 0 else min(99, int(verified_bytes * 100 / expected_size_bytes))
            print(
                f"\rRAW verification: {percent:3d}% | {_format_size(verified_bytes)} / "
                f"{_format_size(expected_size_bytes)} | {_format_size(int(verified_bytes / elapsed))}/s",
                end="",
                file=sys.stderr,
                flush=True,
            )

    report_progress()
    try:
        with target.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if opened.st_size != expected_size_bytes:
                raise OutputVerificationError(
                    f"RAW output size changed before verification: got {opened.st_size} bytes, "
                    f"expected {expected_size_bytes} bytes"
                )
            while True:
                check_cancelled()
                data = stream.read(COPY_BUFFER_SIZE)
                if not data:
                    break
                verified_bytes += len(data)
                if verified_bytes > expected_size_bytes:
                    raise OutputVerificationError(
                        f"RAW output grew during verification: read more than {expected_size_bytes} bytes"
                    )
                digest.update(data)
                report_progress()
            finished_fd = os.fstat(stream.fileno())
    except OutputVerificationError:
        raise
    except OSError as exc:
        raise OutputVerificationError(f"Could not read staged RAW output {target}: {exc}") from exc

    actual_sha256 = digest.hexdigest()
    try:
        after = target.stat()
    except OSError as exc:
        raise OutputVerificationError(f"Cannot re-inspect staged RAW output {target}: {exc}") from exc

    identity_before = (getattr(before, "st_ino", 0), before.st_size, before.st_mtime_ns)
    identity_after = (getattr(after, "st_ino", 0), after.st_size, after.st_mtime_ns)
    identity_fd = (getattr(finished_fd, "st_ino", 0), finished_fd.st_size, finished_fd.st_mtime_ns)
    if identity_before != identity_after or identity_fd != identity_after:
        raise OutputVerificationError("RAW output changed while it was being verified")
    if verified_bytes != expected_size_bytes:
        raise OutputVerificationError(
            f"RAW output verification read {verified_bytes} bytes, expected {expected_size_bytes} bytes"
        )
    if actual_sha256 != expected_sha256:
        notify("error", "RAW output SHA-256 does not match the logical Sparse contents.")
        raise OutputVerificationError(
            f"RAW output SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )

    elapsed = max(time.monotonic() - started, 0.0)
    report = {
        "enabled": True,
        "passed": True,
        "method": "sha256",
        "expected_size_bytes": expected_size_bytes,
        "actual_size_bytes": verified_bytes,
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "verified_bytes": verified_bytes,
        "duration_seconds": round(elapsed, 6),
    }
    notify("success", f"RAW output verification passed: {_format_size(verified_bytes)} · SHA-256 {actual_sha256}")
    return report


def _process_sparse(
    input_path: str | Path,
    output_path: str | Path | None,
    *,
    force: bool = False,
    show_progress: bool = False,
    calculate_sha256: bool = False,
    verify_output: bool = False,
    mode: str = "convert",
    progress_callback: ProgressCallback | None = None,
    event_callback: EventCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Validate an Android sparse image and optionally expand it to a raw image.

    Callbacks are optional and are intended for GUI/integration clients. Progress is
    reported from actual processed logical bytes and completed chunks. Cancellation
    is checked between bounded read/write operations; temporary output is discarded
    before commit so the destination remains untouched.
    """
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")

    if verify_output and output_path is None:
        raise ValueError("RAW output verification requires an output path")

    destination: Path | None = None
    if output_path is not None:
        destination = Path(output_path).expanduser().resolve()
        if source == destination:
            raise ValueError("Input and output paths must be different")
        if not destination.parent.is_dir():
            raise FileNotFoundError(f"Output directory not found: {destination.parent}")
        try:
            if destination.exists() and os.path.samefile(source, destination):
                raise ValueError("Input and output refer to the same file")
        except OSError:
            pass
        if destination.is_dir():
            raise IsADirectoryError(f"Output path points to a directory: {destination}")
        if destination.exists() and not force:
            raise FileExistsError(
                f"Output file already exists: {destination} (use --force to overwrite)"
            )

    temp_path: Path | None = None
    temp_fd: int | None = None
    output_stream: BinaryIO | None = None
    start_time = time.monotonic()
    processed_bytes = 0
    last_percent = -1
    last_progress_time = start_time
    last_callback_percent = -1
    last_callback_time = start_time
    raw_size = 0
    total_chunks = 0
    completed_chunks = 0
    active_chunk_index = 0
    active_chunk_type = "—"

    def notify(level: str, message: str) -> None:
        if event_callback is not None:
            event_callback(level, message)

    def check_cancelled() -> None:
        if cancel_requested is not None and cancel_requested():
            notify("warning", "Отмена запрошена; временный результат будет удалён.")
            raise ConversionCancelled("Операция отменена пользователем")

    def emit_progress(*, force: bool = False, completed: bool = False) -> None:
        nonlocal last_callback_percent, last_callback_time
        if progress_callback is None:
            return
        now = time.monotonic()
        if verify_output:
            # Reserve the second half of the progress range for the RAW re-read.
            percent = 0 if raw_size == 0 else min(49, int(processed_bytes * 50 / raw_size))
            if completed:
                percent = 100
        elif raw_size == 0:
            # A zero-byte image is only complete after its structural checks pass.
            percent = 100 if completed else 0
        else:
            percent = min(99, int(processed_bytes * 100 / raw_size))
            if completed:
                percent = 100
        if not force and percent == last_callback_percent and now - last_callback_time < 0.10:
            return
        elapsed = max(now - start_time, 0.001)
        progress_callback({
            "processed_chunks": completed_chunks,
            "total_chunks": total_chunks,
            "current_chunk": active_chunk_index + 1 if total_chunks else 0,
            "current_chunk_type": active_chunk_type,
            "processed_bytes": processed_bytes,
            "expected_bytes": raw_size,
            "percent": percent,
            "speed_bytes_per_second": processed_bytes / elapsed,
            "elapsed_seconds": elapsed,
        })
        last_callback_percent = percent
        last_callback_time = now

    notify("info", f"Открытие входного файла: {source}")

    def advance(amount: int) -> None:
        nonlocal processed_bytes, last_percent, last_progress_time
        check_cancelled()
        processed_bytes += amount
        emit_progress()
        if not show_progress:
            return
        percent = 100 if raw_size == 0 else min(99, int(processed_bytes * 100 / raw_size))
        now = time.monotonic()
        if percent != last_percent or now - last_progress_time >= 0.25:
            elapsed = max(now - start_time, 0.001)
            speed = processed_bytes / elapsed / (1024 * 1024)
            print(
                f"\rProgress: {percent:3d}% | {_format_size(processed_bytes)} / "
                f"{_format_size(raw_size)} | {speed:.1f} MiB/s | elapsed {_format_duration(now - start_time)}",
                end="",
                file=sys.stderr,
                flush=True,
            )
            last_percent = percent
            last_progress_time = now

    preflight_report: dict[str, Any] | None = None
    try:
        if destination is not None:
            preflight_report = preflight_output([source], destination, operation="convert", force=force)
            if show_progress:
                print(
                    "Preflight: "
                    f"{_format_size(preflight_report['available_free_bytes'])} free; "
                    f"{_format_size(preflight_report['required_free_bytes'])} required including safety margin.",
                    file=sys.stderr,
                )
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
                raise SparseImageError(f"Unsupported sparse major version: {major_version}")
            if file_header_size < HEADER_SIZE:
                raise SparseImageError(f"Invalid file header size: {file_header_size}")
            if chunk_header_size < CHUNK_HEADER_SIZE:
                raise SparseImageError(f"Invalid chunk header size: {chunk_header_size}")
            if block_size == 0 or block_size % 4 != 0:
                raise SparseImageError(
                    f"Invalid block size {block_size}; it must be positive and divisible by 4"
                )
            _read_exact(input_stream, file_header_size - HEADER_SIZE, "extended sparse header")
            raw_size = total_blocks * block_size
            notify(
                "success",
                f"Проверка заголовка: OK · Android Sparse {major_version}.{minor_version} · "
                f"чанков: {total_chunks:,} · ожидаемый RAW: {_format_size(raw_size)}",
            )
            emit_progress(force=True)
            notify("info", "Начата потоковая обработка чанков.")

            if destination is not None:
                temp_fd, temporary_name = tempfile.mkstemp(
                    prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
                )
                temp_path = Path(temporary_name)
                output_stream = os.fdopen(temp_fd, "wb")
                temp_fd = None

            running_crc = 0
            output_blocks = 0
            chunk_counts = {name: 0 for name in CHUNK_NAMES.values()}
            sha256 = hashlib.sha256() if (calculate_sha256 or verify_output) else None

            def consume_zeros(count: int) -> None:
                nonlocal running_crc
                remaining = count
                while remaining:
                    amount = min(COPY_BUFFER_SIZE, remaining)
                    zeros = ZERO_BUFFER[:amount]
                    running_crc = zlib.crc32(zeros, running_crc)
                    if sha256 is not None:
                        sha256.update(zeros)
                    remaining -= amount
                    advance(amount)

            for chunk_index in range(total_chunks):
                check_cancelled()
                active_chunk_index = chunk_index
                chunk_header = _read_exact(
                    input_stream, chunk_header_size, f"chunk {chunk_index} header"
                )
                chunk_type, reserved, chunk_blocks, total_size = struct.unpack(
                    CHUNK_HEADER_FMT, chunk_header[:CHUNK_HEADER_SIZE]
                )
                if reserved != 0:
                    raise SparseImageError(f"Chunk {chunk_index}: reserved field is not zero")
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
                        f"Chunk {chunk_index}: invalid total_sz (got {total_size}, expected {expected_size})"
                    )
                if chunk_type != CHUNK_CRC32 and output_blocks + chunk_blocks > total_blocks:
                    raise SparseImageError(
                        f"Chunk {chunk_index}: output exceeds declared total blocks"
                    )
                active_chunk_type = CHUNK_NAMES[chunk_type]
                chunk_counts[active_chunk_type] += 1

                if chunk_type == CHUNK_RAW:
                    remaining = data_size
                    while remaining:
                        amount = min(COPY_BUFFER_SIZE, remaining)
                        data = _read_exact(input_stream, amount, f"RAW data in chunk {chunk_index}")
                        if output_stream is not None:
                            output_stream.write(data)
                        running_crc = zlib.crc32(data, running_crc)
                        if sha256 is not None:
                            sha256.update(data)
                        remaining -= len(data)
                        advance(len(data))
                elif chunk_type == CHUNK_FILL:
                    pattern = _read_exact(input_stream, 4, f"FILL pattern in chunk {chunk_index}")
                    if data_size % 4:
                        raise SparseImageError("FILL chunk output size is not a multiple of 4")
                    repeated = pattern * (COPY_BUFFER_SIZE // 4)
                    remaining = data_size
                    while remaining:
                        amount = min(COPY_BUFFER_SIZE, remaining)
                        block = repeated[:amount]
                        if output_stream is not None:
                            output_stream.write(block)
                        running_crc = zlib.crc32(block, running_crc)
                        if sha256 is not None:
                            sha256.update(block)
                        remaining -= amount
                        advance(amount)
                elif chunk_type == CHUNK_DONT_CARE:
                    consume_zeros(data_size)
                    if output_stream is not None:
                        output_stream.seek(data_size, os.SEEK_CUR)
                else:  # CRC32 chunk
                    stored_crc = struct.unpack(
                        "<I", _read_exact(input_stream, 4, f"CRC32 value in chunk {chunk_index}")
                    )[0]
                    computed_crc = running_crc & 0xFFFFFFFF
                    if stored_crc != computed_crc:
                        notify("error", f"CRC32 mismatch в чанке {chunk_index + 1}.")
                        raise SparseImageError(
                            f"CRC32 mismatch in chunk {chunk_index}: computed 0x{computed_crc:08X}, stored 0x{stored_crc:08X}"
                        )
                    crc_chunks_checked = chunk_counts["CRC32"]
                    if crc_chunks_checked == 1 or crc_chunks_checked % 128 == 0:
                        notify("success", f"Проверка CRC32 чанка {chunk_index + 1}: OK")

                if chunk_type != CHUNK_CRC32:
                    output_blocks += chunk_blocks
                completed_chunks = chunk_index + 1
                emit_progress(
                    force=(completed_chunks == total_chunks or completed_chunks % 256 == 0)
                )

            if output_stream is not None:
                # Extends trailing DONT_CARE ranges and zero-sized images correctly.
                output_stream.truncate(raw_size)
                output_stream.flush()
                os.fsync(output_stream.fileno())
                output_stream.close()
                output_stream = None

            if temp_path is not None:
                actual_temp_size = temp_path.stat().st_size
                if actual_temp_size != raw_size:
                    raise SparseImageError(
                        f"Output size mismatch: got {actual_temp_size} bytes, expected {raw_size}"
                    )
                notify("success", f"Итоговый размер временного RAW: {_format_size(actual_temp_size)} · OK")

            if output_blocks != total_blocks:
                raise SparseImageError(
                    f"Block count mismatch: wrote {output_blocks}, expected {total_blocks}"
                )
            if input_stream.read(1):
                notify("error", "Обнаружены лишние байты после последнего чанка.")
                raise SparseImageError("Unexpected trailing bytes after the final chunk")
            notify("success", f"Проверка числа блоков и структуры: OK · {output_blocks:,}/{total_blocks:,}")
            if chunk_counts["CRC32"]:
                notify("success", f"CRC32-чанков успешно проверено: {chunk_counts['CRC32']:,}")

            running_crc &= 0xFFFFFFFF
            if image_checksum:
                notify("info", "Проверка общей контрольной суммы образа…")
                if image_checksum != running_crc:
                    notify("error", "Общая контрольная сумма образа не совпадает.")
                    raise SparseImageError(
                        f"Image checksum mismatch: computed 0x{running_crc:08X}, header says 0x{image_checksum:08X}"
                    )
                notify("success", f"Проверка общей контрольной суммы: OK · 0x{running_crc:08X}")
            else:
                notify("warning", "Общая контрольная сумма не задана в заголовке; проверка пропущена.")
            check_cancelled()

            if show_progress:
                elapsed = max(time.monotonic() - start_time, 0.001)
                speed = processed_bytes / elapsed / (1024 * 1024)
                print(
                    f"\rProgress: 100% | {_format_size(raw_size)} / {_format_size(raw_size)} | {speed:.1f} MiB/s",
                    file=sys.stderr,
                )

            output_verification: dict[str, Any] | None = None
            if verify_output:
                if temp_path is None or sha256 is None:
                    raise OutputVerificationError("A staged RAW output is unavailable for verification")
                expected_digest = sha256.hexdigest()

                def verification_progress(data: dict[str, Any]) -> None:
                    if progress_callback is None:
                        return
                    verified = int(data["verified_bytes"])
                    percent = 99 if raw_size == 0 else 50 + min(49, int(verified * 49 / raw_size))
                    progress_callback({
                        "processed_chunks": completed_chunks,
                        "total_chunks": total_chunks,
                        "processed_bytes": verified,
                        "expected_bytes": raw_size,
                        "percent": percent,
                        "speed_bytes_per_second": data["speed_bytes_per_second"],
                        "elapsed_seconds": data["elapsed_seconds"],
                        "stage": "verification",
                    })

                output_verification = _verify_raw_file(
                    temp_path,
                    raw_size,
                    expected_digest,
                    progress_callback=verification_progress,
                    event_callback=event_callback,
                    cancel_requested=cancel_requested,
                    show_progress=show_progress,
                )
                if show_progress:
                    print(file=sys.stderr)

            result: dict[str, Any] = {
                "mode": mode,
                "input": str(source),
                "input_size_bytes": source.stat().st_size,
                "format": f"Android Sparse {major_version}.{minor_version}",
                "major_version": major_version,
                "minor_version": minor_version,
                "file_header_size": file_header_size,
                "chunk_header_size": chunk_header_size,
                "block_size": block_size,
                "total_blocks": total_blocks,
                "total_chunks": total_chunks,
                "chunk_counts": chunk_counts,
                "raw_size_bytes": raw_size,
                "raw_size_human": _format_size(raw_size),
                "header_checksum": f"0x{image_checksum:08X}",
                "computed_crc32": f"0x{running_crc:08X}",
                "output": str(destination) if destination else None,
                # Backwards-compatible keys retained for callers of the original v0.1 API.
                "blocks": output_blocks,
                "raw_size": raw_size,
                "crc32": running_crc,
                "chunks": total_chunks,
            }
            if preflight_report is not None:
                result["preflight"] = preflight_report
            if calculate_sha256 and sha256 is not None:
                result["sha256"] = sha256.hexdigest()
            if output_verification is not None:
                result["output_verification"] = output_verification
            if destination is not None:
                result["output_size_bytes"] = destination.stat().st_size if destination.exists() else raw_size

        if temp_path is not None and destination is not None:
            check_cancelled()
            if force:
                os.replace(temp_path, destination)
            else:
                # Link the completed temporary file into place atomically and never clobber.
                try:
                    os.link(temp_path, destination)
                except FileExistsError:
                    raise FileExistsError(
                        f"Output file already exists: {destination} (use --force to overwrite)"
                    ) from None
                except OSError as exc:
                    raise OSError(
                        f"Cannot safely create output without overwriting ({exc}). "
                        "Choose another output path or use --force if replacement is intended."
                    ) from exc
                temp_path.unlink()
            temp_path = None
            result["output_size_bytes"] = destination.stat().st_size
            if show_progress and verify_output:
                print(
                    f"\rProgress: 100% | {_format_size(raw_size)} / {_format_size(raw_size)}",
                    file=sys.stderr,
                )
            notify("success", f"Результат сохранён: {destination}")
        elif destination is None:
            notify("success", "Проверка образа завершена успешно; выходной файл не создавался.")

        emit_progress(force=True, completed=True)
        return result
    finally:
        if output_stream is not None:
            try:
                output_stream.close()
            except OSError:
                pass
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def convert_sparse_to_raw(
    input_path: str | Path,
    output_path: str | Path,
    *,
    force: bool = False,
    show_progress: bool = False,
    calculate_sha256: bool = False,
    verify_output: bool = False,
    progress_callback: ProgressCallback | None = None,
    event_callback: EventCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Convert a sparse image to raw. Existing output is preserved unless ``force=True``.

    Optional callbacks allow desktop frontends to receive genuine progress/events and
    request safe cancellation without changing the command-line interface.
    """
    return _process_sparse(
        input_path,
        output_path,
        force=force,
        show_progress=show_progress,
        calculate_sha256=calculate_sha256,
        verify_output=verify_output,
        mode="convert",
        progress_callback=progress_callback,
        event_callback=event_callback,
        cancel_requested=cancel_requested,
    )


def inspect_sparse(
    input_path: str | Path,
    *,
    calculate_sha256: bool = False,
    show_progress: bool = False,
    mode: str = "info",
    progress_callback: ProgressCallback | None = None,
    event_callback: EventCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Validate a sparse image without creating a RAW file and return its metadata."""
    return _process_sparse(
        input_path,
        None,
        show_progress=show_progress,
        calculate_sha256=calculate_sha256,
        mode=mode,
        progress_callback=progress_callback,
        event_callback=event_callback,
        cancel_requested=cancel_requested,
    )



STRUCTURE_PAGE_SIZE = 200
STRUCTURE_MAX_PAGE_SIZE = 2000
STRUCTURE_CSV_FIELDS = (
    "index", "type", "type_code", "file_offset", "output_offset_bytes",
    "block_count", "stored_size_bytes", "payload_size_bytes",
    "expanded_size_bytes", "checksum", "fill_pattern",
)


def _read_sparse_structure_header(stream: BinaryIO, source: Path) -> dict[str, Any]:
    """Read and validate the Sparse file header for structural inspection."""
    header_bytes = _read_exact(stream, HEADER_SIZE, "sparse header")
    (
        magic, major, minor, file_header_size, chunk_header_size,
        block_size, total_blocks, total_chunks, image_checksum,
    ) = struct.unpack(HEADER_FMT, header_bytes)
    if magic != MAGIC:
        raise SparseImageError(f"Invalid sparse magic: 0x{magic:08X}")
    if major != 1:
        raise SparseImageError(f"Unsupported sparse major version: {major}")
    if file_header_size < HEADER_SIZE:
        raise SparseImageError(f"Invalid file header size: {file_header_size}")
    if chunk_header_size < CHUNK_HEADER_SIZE:
        raise SparseImageError(f"Invalid chunk header size: {chunk_header_size}")
    if block_size == 0 or block_size % 4:
        raise SparseImageError(f"Invalid block size {block_size}; it must be positive and divisible by 4")
    _read_exact(stream, file_header_size - HEADER_SIZE, "extended sparse header")
    return {
        "input": str(source),
        "input_size_bytes": source.stat().st_size,
        "format": f"Android Sparse {major}.{minor}",
        "major_version": major,
        "minor_version": minor,
        "file_header_size": file_header_size,
        "chunk_header_size": chunk_header_size,
        "block_size": block_size,
        "total_blocks": total_blocks,
        "total_chunks": total_chunks,
        "raw_size_bytes": total_blocks * block_size,
        "header_checksum": f"0x{image_checksum:08X}",
    }


def iter_sparse_chunk_metadata(input_path: str | Path, *, cancel_requested: CancelCallback | None = None):
    """Yield one bounded metadata record per Sparse chunk.

    This iterator parses chunk headers and seeks over payloads; it does not claim
    payload/checksum validation. Run :func:`inspect_sparse` first when a verified
    status is required. Memory use is constant regardless of image size.
    """
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    file_size = source.stat().st_size
    with source.open("rb") as stream:
        header = _read_sparse_structure_header(stream, source)
        block_size = int(header["block_size"])
        total_blocks = int(header["total_blocks"])
        total_chunks = int(header["total_chunks"])
        output_blocks = 0

        for chunk_index in range(total_chunks):
            if cancel_requested is not None and cancel_requested():
                raise ConversionCancelled("Sparse structure scan cancelled")
            chunk_file_offset = stream.tell()
            chunk_header_size = int(header["chunk_header_size"])
            chunk_header = _read_exact(stream, chunk_header_size, f"chunk {chunk_index} header")
            chunk_type, reserved, chunk_blocks, total_size = struct.unpack(
                CHUNK_HEADER_FMT, chunk_header[:CHUNK_HEADER_SIZE]
            )
            if reserved != 0:
                raise SparseImageError(f"Chunk {chunk_index}: reserved field is not zero")
            if chunk_type not in CHUNK_NAMES:
                raise SparseImageError(f"Chunk {chunk_index}: unsupported type 0x{chunk_type:04X}")

            expanded_size = chunk_blocks * block_size
            if chunk_type == CHUNK_RAW:
                payload_size = expanded_size
            elif chunk_type == CHUNK_FILL:
                payload_size = 4
                if expanded_size % 4:
                    raise SparseImageError(f"Chunk {chunk_index}: FILL output size is not a multiple of 4")
            elif chunk_type == CHUNK_DONT_CARE:
                payload_size = 0
            else:
                payload_size = 4
                if chunk_blocks != 0:
                    raise SparseImageError(f"Chunk {chunk_index}: CRC32 chunk must have zero blocks")
                expanded_size = 0

            expected_total_size = chunk_header_size + payload_size
            if total_size != expected_total_size:
                raise SparseImageError(
                    f"Chunk {chunk_index}: invalid total_sz (got {total_size}, expected {expected_total_size})"
                )
            if chunk_type != CHUNK_CRC32 and output_blocks + chunk_blocks > total_blocks:
                raise SparseImageError(f"Chunk {chunk_index}: output exceeds declared total blocks")

            payload_offset = stream.tell()
            checksum = ""
            fill_pattern = ""
            if chunk_type == CHUNK_RAW:
                payload_end = payload_offset + payload_size
                if payload_end > file_size:
                    raise SparseImageError(f"Unexpected end of file while reading RAW data in chunk {chunk_index}")
                stream.seek(payload_size, os.SEEK_CUR)
            elif chunk_type == CHUNK_FILL:
                pattern = _read_exact(stream, 4, f"FILL pattern in chunk {chunk_index}")
                fill_pattern = pattern.hex(" ").upper()
            elif chunk_type == CHUNK_CRC32:
                stored_crc = struct.unpack("<I", _read_exact(stream, 4, f"CRC32 value in chunk {chunk_index}"))[0]
                checksum = f"0x{stored_crc:08X}"

            expected_position = chunk_file_offset + total_size
            if stream.tell() != expected_position:
                raise SparseImageError(f"Chunk {chunk_index}: stored-size accounting mismatch")

            record = {
                "index": chunk_index,
                "type": CHUNK_NAMES[chunk_type],
                "type_code": f"0x{chunk_type:04X}",
                "file_offset": chunk_file_offset,
                "file_offset_hex": f"0x{chunk_file_offset:X}",
                "payload_offset": payload_offset,
                "output_offset_bytes": output_blocks * block_size,
                "output_offset_hex": f"0x{output_blocks * block_size:X}",
                "block_count": chunk_blocks,
                "stored_size_bytes": total_size,
                "payload_size_bytes": payload_size,
                "expanded_size_bytes": expanded_size,
                "checksum": checksum,
                "fill_pattern": fill_pattern,
            }
            yield record
            if chunk_type != CHUNK_CRC32:
                output_blocks += chunk_blocks

        if output_blocks != total_blocks:
            raise SparseImageError(
                f"Block count mismatch: found {output_blocks}, expected {total_blocks}"
            )
        if stream.read(1):
            raise SparseImageError("Unexpected trailing bytes after the final chunk")


def read_sparse_chunk_page(
    input_path: str | Path,
    *,
    offset: int = 0,
    limit: int = STRUCTURE_PAGE_SIZE,
    chunk_type: str | None = None,
    search: str = "",
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Return a filtered page of chunk metadata without retaining the full table.

    The caller should first run :func:`inspect_sparse` to validate every payload
    and checksum. Subsequent page reads only scan chunk headers and seek over data.
    """
    if offset < 0:
        raise ValueError("Page offset must not be negative")
    if limit < 1 or limit > STRUCTURE_MAX_PAGE_SIZE:
        raise ValueError(f"Page size must be between 1 and {STRUCTURE_MAX_PAGE_SIZE}")
    normalized_type = str(chunk_type or "all").upper()
    if normalized_type not in {"ALL", *CHUNK_NAMES.values()}:
        raise ValueError(f"Unknown Sparse chunk type filter: {chunk_type}")
    query = str(search or "").strip().casefold()

    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    with source.open("rb") as stream:
        header = _read_sparse_structure_header(stream, source)

    matched_rows: list[dict[str, Any]] = []
    total_matches = 0
    page_end = offset + limit
    for record in iter_sparse_chunk_metadata(source, cancel_requested=cancel_requested):
        if normalized_type != "ALL" and record["type"] != normalized_type:
            continue
        if query:
            searchable = " ".join(
                str(record.get(key, ""))
                for key in (
                    "index", "type", "type_code", "file_offset", "file_offset_hex",
                    "output_offset_bytes", "output_offset_hex", "block_count",
                    "stored_size_bytes", "expanded_size_bytes", "checksum", "fill_pattern",
                )
            ).casefold()
            if query not in searchable:
                continue
        if offset <= total_matches < page_end:
            matched_rows.append(record)
        total_matches += 1

    return {
        "header": header,
        "rows": matched_rows,
        "offset": offset,
        "limit": limit,
        "total_matches": total_matches,
        "next_offset": page_end if page_end < total_matches else None,
        "previous_offset": max(0, offset - limit) if offset > 0 else None,
    }


def export_sparse_structure(
    input_path: str | Path,
    output_path: str | Path,
    *,
    format: str | None = None,
    validated_metadata: dict[str, Any] | None = None,
    force: bool = False,
    cancel_requested: CancelCallback | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Stream the complete chunk table to JSON or CSV using an atomic output.

    When ``validated_metadata`` is supplied it must be the result of a successful
    :func:`inspect_sparse` call for the unchanged source file. Otherwise this
    function performs full validation before exporting.
    """
    source = Path(input_path).expanduser().resolve()
    destination = Path(output_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    if source == destination:
        raise ValueError("Input and export paths must be different")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Export directory not found: {destination.parent}")
    if destination.exists() and not force:
        raise FileExistsError(f"Export file already exists: {destination}")

    selected_format = (format or destination.suffix.lstrip(".") or "json").casefold()
    if selected_format not in {"json", "csv"}:
        raise ValueError("Structure export format must be JSON or CSV")
    if validated_metadata is None:
        validated_metadata = inspect_sparse(source, calculate_sha256=True, cancel_requested=cancel_requested)

    initial_stat = source.stat()
    metadata_input = validated_metadata.get("input")
    if metadata_input and Path(str(metadata_input)).expanduser().resolve() != source:
        raise SparseImageError("Validated metadata belongs to a different Sparse input file")
    declared_input_size = validated_metadata.get("input_size_bytes")
    if declared_input_size is not None and int(declared_input_size) != initial_stat.st_size:
        raise SparseImageError("Sparse input size changed after validation")
    total_chunks = max(0, int(validated_metadata.get("total_chunks", 0) or 0))

    count = 0
    last_reported_percent = -1

    def report_progress(*, final: bool = False, force: bool = False) -> None:
        nonlocal last_reported_percent
        if progress_callback is None:
            return
        percent = 100 if final else (0 if total_chunks == 0 else min(99, int(count * 100 / total_chunks)))
        # Emit only when the visible percentage changes. Large Sparse images may
        # contain millions of chunks; per-chunk Qt signals would flood the UI queue.
        if force or percent != last_reported_percent:
            progress_callback({
                "chunks_exported": count,
                "total_chunks": total_chunks,
                "percent": percent,
            })
            last_reported_percent = percent

    report_progress(force=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="" if selected_format == "csv" else "\n") as stream:
            if selected_format == "csv":
                writer = csv.DictWriter(stream, fieldnames=STRUCTURE_CSV_FIELDS, extrasaction="ignore")
                writer.writeheader()
                for record in iter_sparse_chunk_metadata(source, cancel_requested=cancel_requested):
                    if cancel_requested is not None and cancel_requested():
                        raise ConversionCancelled("Sparse structure export cancelled")
                    writer.writerow(record)
                    count += 1
                    report_progress()
            else:
                summary_keys = (
                    "format", "input_size_bytes", "block_size", "total_blocks", "total_chunks",
                    "raw_size_bytes", "header_checksum", "computed_crc32", "sha256",
                )
                summary = {key: validated_metadata.get(key) for key in summary_keys if key in validated_metadata}
                stream.write('{\n  "metadata": ')
                json.dump(summary, stream, ensure_ascii=False, indent=2)
                stream.write(',\n  "chunks": [\n')
                first = True
                for record in iter_sparse_chunk_metadata(source, cancel_requested=cancel_requested):
                    if cancel_requested is not None and cancel_requested():
                        raise ConversionCancelled("Sparse structure export cancelled")
                    if not first:
                        stream.write(',\n')
                    stream.write('    ')
                    json.dump(record, stream, ensure_ascii=False)
                    first = False
                    count += 1
                    report_progress()
                stream.write('\n  ]\n}\n')
            stream.flush()
            os.fsync(stream.fileno())

        if cancel_requested is not None and cancel_requested():
            raise ConversionCancelled("Sparse structure export cancelled")
        current_stat = source.stat()
        if (initial_stat.st_size, initial_stat.st_mtime_ns) != (current_stat.st_size, current_stat.st_mtime_ns):
            raise SparseImageError("Sparse input changed while its structure was being exported")
        if force:
            os.replace(temporary_path, destination)
        else:
            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                raise FileExistsError(f"Export file already exists: {destination}") from None
            temporary_path.unlink()
        report_progress(final=True, force=True)
        return {
            "output": str(destination),
            "format": selected_format,
            "chunks_exported": count,
            "output_size_bytes": destination.stat().st_size,
        }
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


_SPARSE_PART_NAME_RE = re.compile(
    r"^(?P<prefix>.+?)(?P<marker>_sparsechunk\.|\.sparsechunk\.|_sparse_chunk\.)(?P<index>\d+)$",
    re.IGNORECASE,
)


def _read_sparse_part_header(input_path: str | Path) -> dict[str, int]:
    """Read and validate the fixed/extended header of one independent Sparse part."""
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    with source.open("rb") as stream:
        header = _read_exact(stream, HEADER_SIZE, "sparse header")
        magic, major, minor, file_header_size, chunk_header_size, block_size, total_blocks, total_chunks, checksum = struct.unpack(
            HEADER_FMT, header
        )
        if magic != MAGIC:
            raise SparseImageError(f"Invalid sparse magic in {source}: 0x{magic:08X}")
        if major != 1:
            raise SparseImageError(f"Unsupported sparse major version in {source}: {major}")
        if file_header_size < HEADER_SIZE:
            raise SparseImageError(f"Invalid file header size in {source}: {file_header_size}")
        if chunk_header_size < CHUNK_HEADER_SIZE:
            raise SparseImageError(f"Invalid chunk header size in {source}: {chunk_header_size}")
        if block_size == 0 or block_size % 4:
            raise SparseImageError(f"Invalid block size in {source}: {block_size}")
        _read_exact(stream, file_header_size - HEADER_SIZE, "extended sparse header")
        return {
            "major_version": major,
            "minor_version": minor,
            "file_header_size": file_header_size,
            "chunk_header_size": chunk_header_size,
            "block_size": block_size,
            "total_blocks": total_blocks,
            "total_chunks": total_chunks,
            "image_checksum": checksum,
            "raw_size_bytes": total_blocks * block_size,
            "input_size_bytes": source.stat().st_size,
        }


def _read_declared_raw_size(input_path: str | Path) -> int:
    """Read only enough of a sparse header to estimate the expanded size."""
    return _read_sparse_part_header(input_path)["raw_size_bytes"]


PREFLIGHT_MIN_MARGIN_BYTES = 1 * 1024 * 1024
PREFLIGHT_MAX_MARGIN_BYTES = 64 * 1024 * 1024


def _preflight_safety_margin(expected_output_bytes: int) -> int:
    """Reserve a modest safety margin for filesystem metadata and reporting."""
    proportional = max(0, expected_output_bytes // 100)
    return max(
        PREFLIGHT_MIN_MARGIN_BYTES,
        min(PREFLIGHT_MAX_MARGIN_BYTES, proportional),
    )


def _probe_writable_directory(directory: Path) -> None:
    """Create, write, sync and remove a tiny temporary file in ``directory``."""
    fd: int | None = None
    probe_path: Path | None = None
    try:
        fd, name = tempfile.mkstemp(prefix=".sparse-to-raw-preflight-", suffix=".tmp", dir=directory)
        probe_path = Path(name)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(b"preflight\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise PermissionError(
            f"Cannot create a temporary file in the output directory {directory}: {exc}"
        ) from exc
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError as exc:
                raise PermissionError(
                    f"Cannot remove the preflight test file {probe_path}: {exc}"
                ) from exc


def _assess_output_space(
    directory: Path,
    *,
    operation: str,
    outputs: list[dict[str, Any]],
    expected_output_bytes: int,
    peak_additional_bytes: int,
) -> dict[str, Any]:
    """Validate write access and available bytes before starting disk-heavy work."""
    try:
        available = shutil.disk_usage(directory).free
    except OSError as exc:
        raise OSError(f"Cannot determine free disk space for {directory}: {exc}") from exc

    margin = _preflight_safety_margin(expected_output_bytes)
    required = peak_additional_bytes + margin
    if available < required:
        raise InsufficientDiskSpaceError(
            "Insufficient free disk space for this operation: "
            f"available {_format_size(available)}, estimated required {_format_size(required)} "
            f"(peak new data {_format_size(peak_additional_bytes)} plus safety margin {_format_size(margin)}). "
            "Choose another output drive or free up disk space before retrying."
        )

    _probe_writable_directory(directory)

    return {
        "passed": True,
        "operation": operation,
        "output_directory": str(directory),
        "outputs": outputs,
        "expected_output_bytes": expected_output_bytes,
        "peak_additional_bytes": peak_additional_bytes,
        "safety_margin_bytes": margin,
        "required_free_bytes": required,
        "available_free_bytes": available,
        "estimated_remaining_free_bytes": available - peak_additional_bytes,
        "write_probe": "passed",
    }


def preflight_output(
    input_paths: list[str | Path],
    output_path: str | Path,
    *,
    operation: str = "convert",
    force: bool = False,
) -> dict[str, Any]:
    """Preflight one conversion or a merge before creating output data.

    Conversion reserves one expanded RAW file. Merge reserves the final staged
    RAW plus the largest per-part RAW staging file, because those coexist while
    a merge is in progress. Estimates deliberately use logical RAW sizes and are
    conservative for filesystems that can represent DONT_CARE ranges as holes.
    """
    if operation not in {"convert", "merge"}:
        raise ValueError("operation must be 'convert' or 'merge'")
    if not input_paths:
        raise ValueError("At least one input Sparse file is required for preflight")
    if operation == "convert" and len(input_paths) != 1:
        raise ValueError("A conversion preflight requires exactly one input file")
    if operation == "merge" and len(input_paths) < 2:
        raise ValueError("A merge preflight requires at least two input parts")

    sources = [Path(item).expanduser().resolve() for item in input_paths]
    if len(set(sources)) != len(sources):
        raise ValueError("The same input file was specified more than once")
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Input file not found: {source}")

    destination = Path(output_path).expanduser().resolve()
    if destination in sources:
        raise ValueError("Output path must be different from every input file")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Output directory not found: {destination.parent}")
    if destination.exists() and destination.is_dir():
        raise IsADirectoryError(f"Output path points to a directory: {destination}")
    if destination.exists() and not force:
        raise FileExistsError(
            f"Output file already exists: {destination} (use --force to overwrite)"
        )
    if destination.exists():
        try:
            if any(os.path.samefile(source, destination) for source in sources):
                raise ValueError("Output path refers to one of the input files")
        except OSError:
            pass

    part_sizes = [_read_declared_raw_size(source) for source in sources]
    expected_output = sum(part_sizes)
    # For a merge, the combined stage and one expanded part coexist. For a
    # single conversion the one output staging file is the peak allocation.
    peak_additional = expected_output + (max(part_sizes) if operation == "merge" else 0)
    output_entry = {
        "path": str(destination),
        "expected_size_bytes": expected_output,
    }
    report = _assess_output_space(
        destination.parent,
        operation=operation,
        outputs=[output_entry],
        expected_output_bytes=expected_output,
        peak_additional_bytes=peak_additional,
    )
    report.update({
        "inputs": [str(source) for source in sources],
        "output": str(destination),
        "part_raw_sizes_bytes": part_sizes,
    })
    return report


def preflight_batch(
    input_paths: list[str | Path],
    output_directory: str | Path,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Preflight every output in a sequential batch to avoid partial queues.

    Output names match the GUI queue convention: ``<input-stem>_raw.img``.
    The complete set is checked for path collisions and existing destinations
    before any item is converted.
    """
    if not input_paths:
        raise ValueError("Add at least one input Sparse file to the batch")
    output_dir = Path(output_directory).expanduser().resolve()
    if not output_dir.exists():
        raise FileNotFoundError(f"Output directory not found: {output_dir}")
    if not output_dir.is_dir():
        raise NotADirectoryError(f"Not an output directory: {output_dir}")

    sources = [Path(item).expanduser().resolve() for item in input_paths]
    source_set = set(sources)
    outputs: list[dict[str, Any]] = []
    seen_destinations: dict[str, Path] = {}
    total_size = 0
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Input file not found: {source}")
        destination = (output_dir / f"{source.stem}_raw.img").resolve()
        key = os.path.normcase(str(destination)).casefold()
        if key in seen_destinations:
            raise ValueError(
                "Batch output-name collision: multiple input files map to "
                f"{destination}. Use different file names or output folders."
            )
        seen_destinations[key] = source
        if destination in source_set:
            raise ValueError(
                f"Batch output path would overwrite an input file in the same queue: {destination}. "
                "Choose another output folder or remove the conflicting input."
            )
        if destination.exists() and destination.is_dir():
            raise IsADirectoryError(f"Batch output path points to a directory: {destination}")
        if destination.exists() and not overwrite:
            raise FileExistsError(
                f"Batch output already exists: {destination} (enable overwrite to replace it)"
            )
        raw_size = _read_declared_raw_size(source)
        total_size += raw_size
        outputs.append({
            "input": str(source),
            "output": str(destination),
            "expected_size_bytes": raw_size,
        })

    report = _assess_output_space(
        output_dir,
        operation="batch",
        outputs=outputs,
        expected_output_bytes=total_size,
        # Each output is committed before the next item starts, so the total
        # size of all final outputs is the maximum additional allocation.
        peak_additional_bytes=total_size,
    )
    report.update({"inputs": [str(source) for source in sources], "output_directory": str(output_dir)})
    return report


def discover_sparse_parts(directory: str | Path) -> dict[str, Any]:
    """Discover and numerically order conventional Android sparsechunk files.

    Only the selected directory is scanned (no recursive traversal). Supported
    names include ``super.img_sparsechunk.0``, ``super.img.sparsechunk.0`` and
    ``super.img_sparse_chunk.0``. Files are grouped by their shared prefix so
    unrelated partition sets are never mixed.

    The function validates each candidate's Sparse header and reports missing
    or duplicate numeric indices. It does not fully decode payloads or validate
    their CRCs; the normal merge operation remains responsible for full checks.
    """
    folder = Path(directory).expanduser().resolve()
    if not folder.exists():
        raise FileNotFoundError(f"Directory not found: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder}")

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for candidate in sorted(folder.iterdir(), key=lambda item: item.name.casefold()):
        if not candidate.is_file():
            continue
        match = _SPARSE_PART_NAME_RE.match(candidate.name)
        if match is None:
            continue
        prefix = match.group("prefix")
        marker = match.group("marker")
        key = (os.path.normcase(prefix), marker.casefold())
        group = grouped.setdefault(key, {
            "prefix": prefix,
            "marker": marker,
            "parts": [],
        })
        entry: dict[str, Any] = {
            "path": str(candidate.resolve()),
            "name": candidate.name,
            "index": int(match.group("index")),
            "input_size_bytes": candidate.stat().st_size,
        }
        try:
            entry.update(_read_sparse_part_header(candidate))
            entry["valid_header"] = True
            entry["error"] = None
        except (OSError, SparseImageError, ValueError) as exc:
            entry["valid_header"] = False
            entry["error"] = str(exc)
        group["parts"].append(entry)

    groups: list[dict[str, Any]] = []
    for group in grouped.values():
        parts = sorted(group["parts"], key=lambda part: (part["index"], part["name"].casefold(), part["name"]))
        indices = [part["index"] for part in parts]
        unique_indices = sorted(set(indices))
        index_counts: dict[int, int] = {}
        for index in indices:
            index_counts[index] = index_counts.get(index, 0) + 1
        duplicate_indices = sorted(index for index, count in index_counts.items() if count > 1)

        # Keep the report bounded even if a malformed filename contains an enormous index.
        missing_ranges: list[list[int]] = []
        next_expected = 0
        missing_indices: list[int] = []
        missing_count = 0
        for index in unique_indices:
            if index > next_expected:
                missing_ranges.append([next_expected, index - 1])
                gap_size = index - next_expected
                missing_count += gap_size
                if len(missing_indices) < 256:
                    take = min(gap_size, 256 - len(missing_indices))
                    missing_indices.extend(range(next_expected, next_expected + take))
            next_expected = index + 1

        header_errors = [f"{part['name']}: {part['error']}" for part in parts if not part["valid_header"]]
        errors = list(header_errors)
        warnings: list[str] = []
        if missing_count:
            range_labels = [str(start) if start == end else f"{start}-{end}" for start, end in missing_ranges]
            suffix = f" (+{missing_count - len(missing_indices)} more)" if missing_count > len(missing_indices) else ""
            warnings.append("Missing part indices: " + ", ".join(range_labels) + suffix)
        if duplicate_indices:
            warnings.append("Duplicate part indices: " + ", ".join(map(str, duplicate_indices)))
        block_sizes = sorted({part["block_size"] for part in parts if part.get("valid_header")})
        if len(block_sizes) > 1:
            errors.append("Sparse parts use different block sizes: " + ", ".join(map(str, block_sizes)))
        valid_parts = [part for part in parts if part.get("valid_header")]
        ready = len(parts) >= 2 and not errors and not missing_count and not duplicate_indices and len(valid_parts) == len(parts)
        groups.append({
            "prefix": group["prefix"],
            "marker": group["marker"],
            "label": f"{group['prefix']}{group['marker']}*",
            "parts": parts,
            "indices": indices,
            "missing_indices": missing_indices,
            "missing_ranges": missing_ranges,
            "missing_count": missing_count,
            "duplicate_indices": duplicate_indices,
            "block_size": block_sizes[0] if len(block_sizes) == 1 else None,
            "block_sizes": block_sizes,
            "header_errors": header_errors,
            "total_input_size_bytes": sum(part["input_size_bytes"] for part in parts),
            "total_raw_size_bytes": sum(part.get("raw_size_bytes", 0) for part in valid_parts),
            "errors": errors,
            "warnings": warnings,
            "ready": ready,
        })

    groups.sort(key=lambda group: (group["prefix"].casefold(), group["marker"].casefold()))
    return {
        "directory": str(folder),
        "groups": groups,
        "group_count": len(groups),
        "part_count": sum(len(group["parts"]) for group in groups),
    }


def merge_sparse_to_raw(
    input_paths: list[str | Path],
    output_path: str | Path,
    *,
    force: bool = False,
    show_progress: bool = False,
    calculate_sha256: bool = False,
    verify_output: bool = False,
    progress_callback: ProgressCallback | None = None,
    event_callback: EventCallback | None = None,
    cancel_requested: CancelCallback | None = None,
) -> dict[str, Any]:
    """Convert multiple independent sparse parts and concatenate them in supplied order.

    Each input must be a complete Android Sparse Image with its own valid header.
    The final output is committed only after every part has validated successfully.
    """
    if len(input_paths) < 2:
        raise ValueError("At least two input parts are required for --merge-parts")
    sources = [Path(item).expanduser().resolve() for item in input_paths]
    if len(set(sources)) != len(sources):
        raise ValueError("The same input part was specified more than once")
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Input file not found: {source}")

    destination = Path(output_path).expanduser().resolve()
    if destination in sources:
        raise ValueError("Output path must be different from every input part")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Output directory not found: {destination.parent}")
    if destination.is_dir():
        raise IsADirectoryError(f"Output path points to a directory: {destination}")
    if destination.exists() and not force:
        raise FileExistsError(
            f"Output file already exists: {destination} (use --force to overwrite)"
        )

    preflight_report = preflight_output(sources, destination, operation="merge", force=force)

    # Header sizes give us a progress denominator; the converter below still fully
    # validates every part before its raw bytes are appended to the staging file.
    declared_sizes = [_read_declared_raw_size(source) for source in sources]
    expected_size = sum(declared_sizes)
    started = time.monotonic()
    # A merge performs two real I/O passes; optional output verification adds
    # a third bounded read of the completed staging file.
    processed = 0
    converted_bytes = 0
    copied_bytes = 0
    work_total = max(1, expected_size * (3 if verify_output else 2))
    last_percent = -1
    last_update = started
    last_callback_percent = -1
    last_callback_time = started
    stage_path: Path | None = None
    stage_fd: int | None = None
    part_summaries: list[dict[str, Any]] = []
    chunk_counts = {name: 0 for name in CHUNK_NAMES.values()}
    total_blocks = 0
    total_chunks = 0
    total_input_bytes = 0
    running_crc = 0
    sha256 = hashlib.sha256() if (calculate_sha256 or verify_output) else None
    verification_in_progress = False

    def notify(level: str, message: str) -> None:
        if event_callback is not None:
            event_callback(level, message)

    def check_cancelled() -> None:
        if cancel_requested is not None and cancel_requested():
            notify("warning", "Merge cancelled; temporary outputs will be removed.")
            raise ConversionCancelled("Operation cancelled by user")

    def emit_progress(*, force_update: bool = False, complete: bool = False) -> None:
        nonlocal last_callback_percent, last_callback_time
        if progress_callback is None:
            return
        now = time.monotonic()
        done = min(work_total, processed)
        percent = 100 if complete else min(99, int(done * 100 / work_total))
        if not force_update and percent == last_callback_percent and now - last_callback_time < 0.10:
            return
        elapsed = max(now - started, 0.001)
        progress_callback({
            "processed_chunks": total_chunks,
            "total_chunks": total_chunks,
            "processed_bytes": done,
            "expected_bytes": work_total,
            "output_bytes": min(expected_size, copied_bytes),
            "expected_output_bytes": expected_size,
            "percent": percent,
            "speed_bytes_per_second": done / elapsed,
            "elapsed_seconds": elapsed,
            "stage": "verification" if verification_in_progress else "merge",
        })
        last_callback_percent = percent
        last_callback_time = now

    def advance_copy(amount: int) -> None:
        nonlocal processed, copied_bytes, last_percent, last_update
        check_cancelled()
        copied_bytes += amount
        processed += amount
        emit_progress()
        if not show_progress:
            return
        percent = min(99, int(processed * 100 / work_total))
        now = time.monotonic()
        if percent != last_percent or now - last_update >= 0.25:
            speed = processed / max(now - started, 0.001) / (1024 * 1024)
            print(
                f"\rMerge: {percent:3d}% | {_format_size(processed)} / "
                f"{_format_size(work_total)} I/O | {speed:.1f} MiB/s | elapsed {_format_duration(now - started)}",
                end="",
                file=sys.stderr,
                flush=True,
            )
            last_percent = percent
            last_update = now

    if show_progress:
        print(
            "Preflight: "
            f"{_format_size(preflight_report['available_free_bytes'])} free; "
            f"{_format_size(preflight_report['required_free_bytes'])} required including merge staging and safety margin.",
            file=sys.stderr,
        )
    notify("info", f"Merging {len(sources)} independent Sparse parts in the supplied order.")
    emit_progress(force_update=True)

    try:
        stage_fd, stage_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
        stage_path = Path(stage_name)
        with os.fdopen(stage_fd, "wb") as combined:
            stage_fd = None
            with tempfile.TemporaryDirectory(prefix="sparse-to-raw-parts-", dir=destination.parent) as work_dir:
                for index, (source, part_size) in enumerate(zip(sources, declared_sizes), start=1):
                    part_raw = Path(work_dir) / f"part-{index:04d}.raw"
                    if show_progress:
                        print(
                            f"\nPart {index}/{len(sources)}: validating and expanding {source.name}",
                            file=sys.stderr,
                        )
                    notify("info", f"Part {index}/{len(sources)}: validating {source.name}")

                    def part_progress(data: dict[str, Any], *, _index: int = index) -> None:
                        nonlocal processed, converted_bytes
                        check_cancelled()
                        part_done = min(part_size, int(data.get("processed_bytes", 0)))
                        before = sum(declared_sizes[:_index - 1])
                        converted_bytes = before + part_done
                        processed = converted_bytes + copied_bytes
                        emit_progress()

                    part_result = convert_sparse_to_raw(
                        source,
                        part_raw,
                        force=False,
                        show_progress=show_progress,
                        calculate_sha256=False,
                        progress_callback=part_progress,
                        event_callback=event_callback,
                        cancel_requested=cancel_requested,
                    )
                    if part_result["raw_size_bytes"] != part_size:
                        raise SparseImageError(
                            f"Expanded size mismatch for {source}: header declared {part_size}, "
                            f"converter produced {part_result['raw_size_bytes']}"
                        )
                    with part_raw.open("rb") as part_stream:
                        while True:
                            data = part_stream.read(COPY_BUFFER_SIZE)
                            if not data:
                                break
                            check_cancelled()
                            combined.write(data)
                            running_crc = zlib.crc32(data, running_crc)
                            if sha256 is not None:
                                sha256.update(data)
                            advance_copy(len(data))
                    part_raw.unlink(missing_ok=True)
                    total_input_bytes += source.stat().st_size
                    total_blocks += part_result["total_blocks"]
                    total_chunks += part_result["total_chunks"]
                    for name, count in part_result["chunk_counts"].items():
                        chunk_counts[name] += count
                    part_summaries.append({
                        "input": str(source),
                        "input_size_bytes": source.stat().st_size,
                        "raw_size_bytes": part_result["raw_size_bytes"],
                        "total_blocks": part_result["total_blocks"],
                        "total_chunks": part_result["total_chunks"],
                        "computed_crc32": part_result["computed_crc32"],
                    })
            combined.flush()
            os.fsync(combined.fileno())

        if copied_bytes != expected_size or stage_path.stat().st_size != expected_size:
            raise OSError(
                f"Merged size mismatch: expected {expected_size} bytes, wrote {stage_path.stat().st_size}"
            )

        output_verification: dict[str, Any] | None = None
        if verify_output:
            if sha256 is None:
                raise OutputVerificationError("Expected logical SHA-256 is unavailable for merge verification")
            verification_in_progress = True
            expected_digest = sha256.hexdigest()
            notify("info", "Verifying the completed merged RAW staging file before commit.")

            def merge_verification_progress(data: dict[str, Any]) -> None:
                nonlocal processed
                processed = expected_size * 2 + int(data["verified_bytes"])
                emit_progress(force_update=True)

            output_verification = _verify_raw_file(
                stage_path,
                expected_size,
                expected_digest,
                progress_callback=merge_verification_progress,
                event_callback=event_callback,
                cancel_requested=cancel_requested,
                show_progress=show_progress,
            )
            if show_progress:
                print(file=sys.stderr)
            verification_in_progress = False

        check_cancelled()
        if force:
            os.replace(stage_path, destination)
        else:
            try:
                os.link(stage_path, destination)
            except FileExistsError:
                raise FileExistsError(
                    f"Output file already exists: {destination} (use --force to overwrite)"
                ) from None
            except OSError as exc:
                raise OSError(
                    f"Cannot safely create output without overwriting ({exc}). "
                    "Choose another output path or use --force if replacement is intended."
                ) from exc
            stage_path.unlink()
        stage_path = None
        processed = work_total
        emit_progress(force_update=True, complete=True)
        if show_progress:
            elapsed = max(time.monotonic() - started, 0.001)
            speed = processed / elapsed / (1024 * 1024)
            print(
                f"\rMerge: 100% | {_format_size(processed)} / {_format_size(work_total)} I/O | {speed:.1f} MiB/s | elapsed {_format_duration(time.monotonic() - started)}",
                file=sys.stderr,
            )

        result: dict[str, Any] = {
            "mode": "merge",
            "input": ", ".join(str(source) for source in sources),
            "inputs": [str(source) for source in sources],
            "parts": part_summaries,
            "input_size_bytes": total_input_bytes,
            "format": "Combined Android Sparse Image parts",
            "block_size": None,
            "total_blocks": total_blocks,
            "total_chunks": total_chunks,
            "chunk_counts": chunk_counts,
            "raw_size_bytes": expected_size,
            "raw_size_human": _format_size(expected_size),
            "header_checksum": "each part validated independently",
            "computed_crc32": f"0x{running_crc & 0xFFFFFFFF:08X}",
            "output": str(destination),
            "output_size_bytes": destination.stat().st_size,
            # Original v0.1 aliases retained for script callers.
            "blocks": total_blocks,
            "raw_size": expected_size,
            "crc32": running_crc & 0xFFFFFFFF,
            "chunks": total_chunks,
            "preflight": preflight_report,
        }
        if calculate_sha256 and sha256 is not None:
            result["sha256"] = sha256.hexdigest()
        if output_verification is not None:
            result["output_verification"] = output_verification
        return result
    finally:
        if stage_fd is not None:
            try:
                os.close(stage_fd)
            except OSError:
                pass
        if stage_path is not None:
            try:
                stage_path.unlink(missing_ok=True)
            except OSError:
                pass

def print_summary(result: dict[str, Any], *, verbose: bool) -> None:
    """Print a human-readable verification/conversion summary."""
    if verbose:
        print(f"Input            : {result['input']}")
        print(f"Format           : {result['format']}")
        print(f"Block size       : {result['block_size']} bytes")
        print(f"Total blocks     : {result['total_blocks']:,}")
        print(f"Total chunks     : {result['total_chunks']:,}")
        print(f"RAW size         : {result['raw_size_human']}")
        print("Chunk breakdown  : " + ", ".join(
            f"{name}={count}" for name, count in result["chunk_counts"].items()
        ))
        print(f"Header checksum  : {result['header_checksum']}")
    else:
        print(f"Input: {result['input']}")
        print(f"RAW size: {result['raw_size_human']}")
        print(f"Chunks validated: {result['total_chunks']:,}")

    print(f"Computed CRC32   : {result['computed_crc32']}")
    if "sha256" in result:
        print(f"RAW SHA-256      : {result['sha256']}")
    verification = result.get("output_verification")
    if verification and verification.get("passed"):
        print(f"RAW verification : PASSED ({_format_size(verification['verified_bytes'])} re-read)")
        print(f"Verified SHA-256 : {verification['actual_sha256']}")
    if result.get("output"):
        print(f"Output           : {result['output']}")
    preflight = result.get("preflight")
    if preflight:
        print(
            "Preflight space  : "
            f"{_format_size(preflight['available_free_bytes'])} free / "
            f"{_format_size(preflight['required_free_bytes'])} required"
        )
    print("Validation successful.")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Конвертация и проверка Android Sparse Image без сторонних библиотек.",
        epilog=(
            "По умолчанию существующие файлы не перезаписываются. "
            "Для явной перезаписи используйте --force."
        ),
    )
    parser.add_argument("input_sparse", nargs="?", help="исходный Android Sparse Image")
    parser.add_argument("output_raw", nargs="?", help="путь к выходному RAW-образу")
    parser.add_argument(
        "--merge-parts", nargs="+", metavar="SPARSE_FILE",
        help="объединить 2+ независимых Sparse-файла в указанном порядке (нужен --output)",
    )
    parser.add_argument("--output", dest="merge_output", metavar="FILE", help="RAW-файл для режима --merge-parts")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--info", action="store_true", help="проверить образ и вывести подробную информацию без конвертации")
    modes.add_argument("--verify-only", action="store_true", help="проверить структуру и контрольные суммы без создания RAW-файла")
    parser.add_argument("--force", action="store_true", help="разрешить перезапись существующего выходного файла или отчёта")
    parser.add_argument("--sha256", action="store_true", help="вычислить SHA-256 логического RAW-содержимого")
    parser.add_argument("--verify-output", action="store_true", help="повторно прочитать готовый RAW и сверить размер и SHA-256 перед сохранением")
    parser.add_argument("--json-report", metavar="FILE", help="сохранить результаты в JSON-файл")
    parser.add_argument("--quiet", action="store_true", help="не показывать индикатор прогресса")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    mode = "info" if args.info else "verify" if args.verify_only else "convert"
    merging = bool(args.merge_parts)

    if merging:
        if args.input_sparse or args.output_raw:
            parser.error("в режиме --merge-parts используйте только --output, без позиционных аргументов")
        if not args.merge_output:
            parser.error("для --merge-parts обязательно укажите --output FILE")
        if mode != "convert":
            parser.error("--merge-parts нельзя совмещать с --info или --verify-only")
    else:
        if not args.input_sparse:
            parser.error("укажите input_sparse либо используйте --merge-parts")
        if args.merge_output:
            parser.error("--output используется только вместе с --merge-parts")
        if mode == "convert" and not args.output_raw:
            parser.error("для конвертации нужно указать output_raw; для проверки используйте --info или --verify-only")
        if mode != "convert" and args.output_raw:
            parser.error("не указывайте output_raw вместе с --info или --verify-only")

    output_arg = args.merge_output if merging else args.output_raw
    input_args = args.merge_parts if merging else [args.input_sparse]
    if args.verify_output and mode != "convert":
        parser.error("--verify-output можно использовать только при конвертации или --merge-parts")
    report_path: Path | None = None
    if args.json_report:
        report_path = Path(args.json_report).expanduser().resolve()
        resolved_inputs = {Path(item).expanduser().resolve() for item in input_args}
        output_resolved = Path(output_arg).expanduser().resolve() if output_arg else None
        if report_path in resolved_inputs or report_path == output_resolved:
            parser.error("JSON-отчёт не может совпадать с путём входного или выходного образа")
        if not report_path.parent.is_dir():
            print(f"ERROR: Каталог для JSON-отчёта не найден: {report_path.parent}", file=sys.stderr)
            return 2
        if report_path.is_dir():
            print(f"ERROR: Путь JSON-отчёта указывает на каталог: {report_path}", file=sys.stderr)
            return 2
        if report_path.exists() and not args.force:
            print(f"ERROR: Файл отчёта уже существует: {report_path} (используйте --force)", file=sys.stderr)
            return 2

    try:
        if merging:
            result = merge_sparse_to_raw(
                args.merge_parts,
                args.merge_output,
                force=args.force,
                show_progress=not args.quiet,
                calculate_sha256=args.sha256,
                verify_output=args.verify_output,
            )
        elif mode == "convert":
            result = convert_sparse_to_raw(
                args.input_sparse,
                args.output_raw,
                force=args.force,
                show_progress=not args.quiet,
                calculate_sha256=args.sha256,
                verify_output=args.verify_output,
            )
        else:
            result = inspect_sparse(
                args.input_sparse,
                calculate_sha256=args.sha256,
                show_progress=not args.quiet,
                mode=mode,
            )
        print_summary(result, verbose=(args.info or mode == "convert"))
        if report_path is not None:
            _atomic_write_text(
                report_path,
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                force=args.force,
            )
            print(f"JSON report saved: {report_path}")
    except (OSError, ValueError, struct.error) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
