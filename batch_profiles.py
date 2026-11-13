"""Portable, versioned JSON profiles for the GUI Batch Queue.

Profiles persist task definitions and queue-level options, not runtime statuses.
Paths are stored relative to the profile file whenever possible so a profile and
its related project/firmware folder can be moved together.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROFILE_FORMAT = "sparse-to-raw.batch-profile"
PROFILE_VERSION = 1
MAX_PROFILE_BYTES = 5 * 1024 * 1024
MAX_TASKS = 10_000


class BatchProfileError(ValueError):
    """Raised when a batch profile is malformed or unsupported."""


def _absolute_lexical_path(value: str | Path) -> str:
    """Return an absolute normalized path without resolving filesystem aliases.

    Path.resolve() follows symlinks and, on Windows, can expand an 8.3 short
    name (for example ``DOOMSL~1``) to its long spelling. Profiles should
    preserve the caller's path identity and spelling, so use abspath/normpath
    rather than realpath/Path.resolve here.
    """
    return os.path.abspath(os.path.expanduser(os.fspath(value)))


def _encode_path(value: Any, base_dir: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchProfileError("Profile path values must be non-empty strings")
    absolute_path = _absolute_lexical_path(value)
    absolute_base = _absolute_lexical_path(base_dir)
    try:
        return Path(os.path.relpath(absolute_path, absolute_base)).as_posix()
    except (OSError, ValueError):
        # Different Windows drives cannot be represented by a relative path.
        return absolute_path


def _decode_path(value: Any, base_dir: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchProfileError("Profile path values must be non-empty strings")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return _absolute_lexical_path(path)


def _encode_path_list(values: Any, base_dir: Path, *, required: bool = False) -> list[str]:
    if not isinstance(values, list) or (required and not values):
        raise BatchProfileError("Profile path list is invalid")
    return [_encode_path(value, base_dir) for value in values]


def _contains_symlink_component(path: Path) -> bool:
    """Return True when the path or one of its parents is a symlink.

    A directory alias is part of the path the user deliberately selected. On
    Windows, ordinary 8.3 short names are not symlinks and should still be
    expanded to their canonical long spelling for task paths.
    """
    for candidate in (path, *path.parents):
        try:
            if candidate.is_symlink():
                return True
        except OSError:
            continue
    return False


def _decode_task_path(value: Any, base_dir: Path) -> str:
    """Decode a task path, canonicalizing short names but preserving symlinks."""
    decoded = _decode_path(value, base_dir)
    path = Path(decoded)
    if _contains_symlink_component(path):
        return decoded
    try:
        # strict=False also canonicalizes an output path that does not exist yet,
        # while resolving existing Windows 8.3 components to their long names.
        return str(path.resolve(strict=False))
    except (OSError, RuntimeError):
        return decoded


def _decode_task_path_list(values: Any, base_dir: Path, *, required: bool = False) -> list[str]:
    if not isinstance(values, list) or (required and not values):
        raise BatchProfileError("Profile path list is invalid")
    return [_decode_task_path(value, base_dir) for value in values]


def _encode_task(task: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise BatchProfileError("Each profile task must be an object")
    task_type = task.get("type")
    if task_type == "sparse":
        return {"type": "sparse", "source": _encode_path(task.get("source"), base_dir)}
    if task_type == "raw_to_sparse":
        config = task.get("config")
        if not isinstance(config, dict):
            raise BatchProfileError("RAW → Sparse task config is missing")
        block_size = config.get("block_size", 4096)
        if isinstance(block_size, bool) or not isinstance(block_size, int) or not 4 <= block_size <= 1_048_576 or block_size % 4:
            raise BatchProfileError("RAW → Sparse block size must be a multiple of 4 from 4 to 1048576")
        return {
            "type": "raw_to_sparse",
            "source": _encode_path(task.get("source"), base_dir),
            "config": {"output": _encode_path(config.get("output"), base_dir), "block_size": block_size},
        }
    if task_type == "qfil":
        config = task.get("config")
        if not isinstance(config, dict):
            raise BatchProfileError("QFIL task config is missing")
        label = task.get("label", "QFIL task")
        if not isinstance(label, str) or not label.strip():
            raise BatchProfileError("QFIL task label must be a non-empty string")
        allow_overlaps = config.get("allow_overlaps", False)
        if not isinstance(allow_overlaps, bool):
            raise BatchProfileError("QFIL allow_overlaps must be a boolean")
        return {
            "type": "qfil",
            "label": label,
            "config": {
                "rawprogram_files": _encode_path_list(config.get("rawprogram_files"), base_dir, required=True),
                "patch_files": _encode_path_list(config.get("patch_files", []), base_dir),
                "search_dirs": _encode_path_list(config.get("search_dirs", []), base_dir),
                "output_dir": _encode_path(config.get("output_dir"), base_dir),
                "allow_overlaps": allow_overlaps,
            },
        }
    raise BatchProfileError(f"Unsupported batch task type: {task_type!r}")


def _decode_task(task: Any, base_dir: Path) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise BatchProfileError("Each profile task must be an object")
    task_type = task.get("type")
    if task_type == "sparse":
        return {"type": "sparse", "source": _decode_task_path(task.get("source"), base_dir)}
    if task_type == "raw_to_sparse":
        config = task.get("config")
        if not isinstance(config, dict):
            raise BatchProfileError("RAW → Sparse task config is missing")
        block_size = config.get("block_size", 4096)
        if isinstance(block_size, bool) or not isinstance(block_size, int) or not 4 <= block_size <= 1_048_576 or block_size % 4:
            raise BatchProfileError("RAW → Sparse block size must be a multiple of 4 from 4 to 1048576")
        return {
            "type": "raw_to_sparse",
            "source": _decode_task_path(task.get("source"), base_dir),
            "config": {"output": _decode_task_path(config.get("output"), base_dir), "block_size": block_size},
        }
    if task_type == "qfil":
        config = task.get("config")
        if not isinstance(config, dict):
            raise BatchProfileError("QFIL task config is missing")
        label = task.get("label", "QFIL task")
        if not isinstance(label, str) or not label.strip():
            raise BatchProfileError("QFIL task label must be a non-empty string")
        allow_overlaps = config.get("allow_overlaps", False)
        if not isinstance(allow_overlaps, bool):
            raise BatchProfileError("QFIL allow_overlaps must be a boolean")
        return {
            "type": "qfil", "label": label,
            "config": {
                "rawprogram_files": _decode_task_path_list(config.get("rawprogram_files"), base_dir, required=True),
                "patch_files": _decode_task_path_list(config.get("patch_files", []), base_dir),
                "search_dirs": _decode_task_path_list(config.get("search_dirs", []), base_dir),
                "output_dir": _decode_task_path(config.get("output_dir"), base_dir),
                "allow_overlaps": allow_overlaps,
            },
        }
    raise BatchProfileError(f"Unsupported batch task type: {task_type!r}")


def save_batch_profile(
    profile_path: str | Path,
    tasks: list[dict[str, Any]],
    options: dict[str, Any],
    *,
    name: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Atomically save a profile. Existing files are preserved unless overwrite=True."""
    path = Path(_absolute_lexical_path(Path(profile_path).expanduser()))
    if len(tasks) > MAX_TASKS:
        raise BatchProfileError(f"A profile cannot contain more than {MAX_TASKS} tasks")
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    base_dir = path.parent
    options = options if isinstance(options, dict) else {}
    payload = {
        "format": PROFILE_FORMAT,
        "version": PROFILE_VERSION,
        "name": (name or path.stem).strip() or path.stem,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "options": {
            "output_dir": _encode_path(str(options.get("output_dir") or (base_dir / "output")), base_dir),
            "overwrite": bool(options.get("overwrite", False)),
            "verify_output": bool(options.get("verify_output", True)),
        },
        "tasks": [_encode_task(task, base_dir) for task in tasks],
    }
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_PROFILE_BYTES:
        raise BatchProfileError("Batch profile exceeds the 5 MiB size limit")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() and not overwrite:
            raise FileExistsError(path)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return payload


def load_batch_profile(profile_path: str | Path) -> dict[str, Any]:
    """Load and validate a profile without changing any caller state."""
    path = Path(_absolute_lexical_path(Path(profile_path).expanduser()))
    try:
        size = path.stat().st_size
        if size > MAX_PROFILE_BYTES:
            raise BatchProfileError("Batch profile exceeds the 5 MiB size limit")
        raw = path.read_text(encoding="utf-8-sig")
        payload = json.loads(raw)
    except BatchProfileError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BatchProfileError(f"Cannot read batch profile: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("format") != PROFILE_FORMAT:
        raise BatchProfileError("This file is not a sparse-to-raw batch profile")
    if payload.get("version") != PROFILE_VERSION:
        raise BatchProfileError(f"Unsupported batch profile version: {payload.get('version')!r}")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or len(tasks) > MAX_TASKS:
        raise BatchProfileError("Profile tasks must be a list with no more than 10000 entries")
    options = payload.get("options")
    if not isinstance(options, dict):
        raise BatchProfileError("Profile options are missing or malformed")
    output_dir = _decode_path(options.get("output_dir"), path.parent)
    decoded_options = {
        "output_dir": output_dir,
        "overwrite": options.get("overwrite", False),
        "verify_output": options.get("verify_output", True),
    }
    if not isinstance(decoded_options["overwrite"], bool) or not isinstance(decoded_options["verify_output"], bool):
        raise BatchProfileError("Profile overwrite and verify_output options must be booleans")
    decoded_tasks = [_decode_task(task, path.parent) for task in tasks]
    return {
        "format": PROFILE_FORMAT,
        "version": PROFILE_VERSION,
        "name": str(payload.get("name") or path.stem),
        "options": decoded_options,
        "tasks": decoded_tasks,
    }
