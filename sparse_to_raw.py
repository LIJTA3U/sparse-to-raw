#!/usr/bin/env python3
"""Convert and inspect Android Sparse Image files using only the stdlib."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def _process_sparse(
    input_path: str | Path,
    output_path: str | Path | None,
    *,
    force: bool = False,
    show_progress: bool = False,
    calculate_sha256: bool = False,
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
        if raw_size == 0:
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
            sha256 = hashlib.sha256() if calculate_sha256 else None

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
            if sha256 is not None:
                result["sha256"] = sha256.hexdigest()
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



def _read_declared_raw_size(input_path: str | Path) -> int:
    """Read only enough of a sparse header to estimate the expanded size."""
    source = Path(input_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Input file not found: {source}")
    with source.open("rb") as stream:
        header = _read_exact(stream, HEADER_SIZE, "sparse header")
        magic, major, _minor, file_header_size, chunk_header_size, block_size, total_blocks, _chunks, _checksum = struct.unpack(
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
        return total_blocks * block_size


def merge_sparse_to_raw(
    input_paths: list[str | Path],
    output_path: str | Path,
    *,
    force: bool = False,
    show_progress: bool = False,
    calculate_sha256: bool = False,
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

    # Header sizes give us a progress denominator; the converter below still fully
    # validates every part before its raw bytes are appended to the staging file.
    declared_sizes = [_read_declared_raw_size(source) for source in sources]
    expected_size = sum(declared_sizes)
    started = time.monotonic()
    # A merge performs two real I/O passes: decoding each sparse part to a
    # temporary RAW file, then concatenating those RAW files into the staged
    # final output. Progress therefore uses 2 * expected_size work bytes.
    processed = 0
    converted_bytes = 0
    copied_bytes = 0
    work_total = max(1, expected_size * 2)
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
    sha256 = hashlib.sha256() if calculate_sha256 else None

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
            "stage": "merge",
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
        }
        if sha256 is not None:
            result["sha256"] = sha256.hexdigest()
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
    if result.get("output"):
        print(f"Output           : {result['output']}")
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
            )
        elif mode == "convert":
            result = convert_sparse_to_raw(
                args.input_sparse,
                args.output_raw,
                force=args.force,
                show_progress=not args.quiet,
                calculate_sha256=args.sha256,
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
