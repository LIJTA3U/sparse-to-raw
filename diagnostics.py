"""Privacy-conscious local diagnostic event storage and ZIP export.

The module uses only the Python standard library and deliberately does not
collect input-image contents, environment variables, account names, hostnames,
or arbitrary system configuration. Exported text fields have user paths and
common credential-shaped values redacted.
"""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


DEFAULT_MAX_FILE_BYTES = 1024 * 1024
DEFAULT_BACKUPS = 2
DEFAULT_MAX_EVENTS = 5000
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|passphrase|client[_-]?secret|secret|private[_-]?key|"
    r"(?:api[_-]?)?token|access[_-]?token|refresh[_-]?token|api[_-]?key|"
    r"authorization)\s*([:=])\s*([^\s,;]+)"
)
_WINDOWS_USER_HOME_RE = re.compile(r"(?i)([A-Z]:\\Users\\)[^\\\r\n]+")
_POSIX_USER_HOME_RE = re.compile(r"(?<![A-Za-z0-9:])(/(?:home|Users)/)[^/\s\"']+")


def redact_text(value: str, *, home_path: str | Path | None = None) -> str:
    """Redact profile roots, absolute paths, and credential-shaped values."""
    text = str(value)
    home = str(home_path or Path.home())
    if home:
        # String replacement handles profile names containing spaces.
        text = text.replace(home, "<USER_HOME>")
        if "\\" in home:
            text = re.sub(re.escape(home), "<USER_HOME>", text, flags=re.IGNORECASE)
    text = _WINDOWS_USER_HOME_RE.sub(r"\1<USER>", text)
    text = _POSIX_USER_HOME_RE.sub(r"\1<USER>", text)
    text = _SECRET_RE.sub(r"\1\2<REDACTED>", text)
    return text


def sanitize_for_export(value: Any, *, home_path: str | Path | None = None, key: str = "") -> Any:
    """Return JSON-safe values with sensitive-key values and paths redacted."""
    key_lower = key.casefold()
    if any(part in key_lower for part in ("password", "passwd", "secret", "token", "credential", "api_key", "apikey", "authorization", "source_name", "filename", "file_name")):
        return "<REDACTED>"
    if isinstance(value, Mapping):
        return {
            str(k): sanitize_for_export(v, home_path=home_path, key=str(k))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_for_export(item, home_path=home_path) for item in value]
    if isinstance(value, Path):
        return redact_text(str(value), home_path=home_path)
    if isinstance(value, str):
        return redact_text(value, home_path=home_path)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_text(str(value), home_path=home_path)


class DiagnosticStore:
    """Small rotating JSONL diagnostic store for one desktop application.

    Local logs are retained for troubleshooting. The export method creates a
    separate sanitized archive and never copies source Sparse/RAW files.
    """

    def __init__(
        self,
        directory: str | Path,
        *,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        backups: int = DEFAULT_BACKUPS,
        max_events: int = DEFAULT_MAX_EVENTS,
    ) -> None:
        self.directory = Path(directory).expanduser()
        self.path = self.directory / "diagnostics.jsonl"
        self.max_file_bytes = max(4096, int(max_file_bytes))
        self.backups = max(0, int(backups))
        self.max_events = max(1, int(max_events))
        self._lock = threading.RLock()
        self.last_error: str | None = None

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().astimezone().isoformat(timespec="milliseconds")

    @staticmethod
    def _safe_details(details: Mapping[str, Any] | None) -> dict[str, Any]:
        """Keep bounded JSON-like detail structures for recursive export redaction."""
        if not details:
            return {}

        def normalize(value: Any, depth: int = 0) -> Any:
            if value is None or isinstance(value, (bool, int, float)):
                return value
            if isinstance(value, str):
                return value[:1000]
            if depth >= 5:
                return str(value)[:500]
            if isinstance(value, Mapping):
                return {
                    str(key)[:100]: normalize(item, depth + 1)
                    for index, (key, item) in enumerate(value.items())
                    if index < 100
                }
            if isinstance(value, (list, tuple, set)):
                return [normalize(item, depth + 1) for item in list(value)[:100]]
            return str(value)[:1000]

        return {str(key)[:100]: normalize(value) for key, value in list(details.items())[:100]}

    def append(
        self,
        level: str,
        category: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> bool:
        event = {
            "timestamp": self._timestamp(),
            "level": str(level).lower() if str(level).lower() in {"debug", "info", "success", "warning", "error"} else "info",
            "category": str(category).lower()[:40],
            "message": str(message)[:8000],
            "details": self._safe_details(details),
        }
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed(len(encoded.encode("utf-8")))
                with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(encoded)
                    stream.flush()
                self.last_error = None
                return True
            except OSError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return False

    def _rotate_if_needed(self, incoming_bytes: int) -> None:
        if not self.path.exists() or self.path.stat().st_size + incoming_bytes <= self.max_file_bytes:
            return
        if self.backups <= 0:
            self.path.unlink(missing_ok=True)
            return
        oldest = self.directory / f"diagnostics.{self.backups}.jsonl"
        oldest.unlink(missing_ok=True)
        for index in range(self.backups - 1, 0, -1):
            source = self.directory / f"diagnostics.{index}.jsonl"
            if source.exists():
                source.replace(self.directory / f"diagnostics.{index + 1}.jsonl")
        self.path.replace(self.directory / "diagnostics.1.jsonl")

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            paths = [self.directory / f"diagnostics.{index}.jsonl" for index in range(self.backups, 0, -1)]
            paths.append(self.path)
            collected: list[dict[str, Any]] = []
            for path in paths:
                try:
                    with path.open("r", encoding="utf-8") as stream:
                        for line in stream:
                            try:
                                event = json.loads(line)
                            except (json.JSONDecodeError, TypeError):
                                continue
                            if isinstance(event, dict) and {"timestamp", "level", "category", "message"}.issubset(event):
                                collected.append(event)
                except OSError:
                    continue
        collected.sort(key=lambda event: str(event.get("timestamp", "")))
        return collected[-self.max_events:]

    def clear(self) -> bool:
        with self._lock:
            try:
                for path in [self.path, *(self.directory / f"diagnostics.{i}.jsonl" for i in range(1, self.backups + 1))]:
                    path.unlink(missing_ok=True)
                self.last_error = None
                return True
            except OSError as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                return False

    def export_zip(
        self,
        destination: str | Path,
        *,
        app_version: str,
        qt_version: str = "unavailable",
        pyside_version: str = "unavailable",
        home_path: str | Path | None = None,
    ) -> Path:
        """Write a sanitized diagnostic archive. No user data files are copied."""
        target = Path(destination).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        events = [sanitize_for_export(event, home_path=home_path) for event in self.entries()]
        system_info = {
            "application_version": str(app_version),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "pyside_version": str(pyside_version),
            "qt_version": str(qt_version),
            "operating_system": platform.system(),
            "os_release": platform.release(),
            "architecture": platform.machine(),
            "generated_at": self._timestamp(),
        }
        readme = (
            "sparse-to-raw diagnostic bundle\n\n"
            "Included: sanitized application event log and basic runtime versions.\n"
            "Not included: Sparse/RAW input files, converted output files, recent-file lists,\n"
            "environment variables, account names, hostnames, or full system inventories.\n"
            "User profile paths and common credential-shaped values are redacted from log text.\n"
        )
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("diagnostics.jsonl", "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in events))
            archive.writestr("system-info.json", json.dumps(system_info, ensure_ascii=False, indent=2) + "\n")
            archive.writestr("README.txt", readme)
        return target


def default_diagnostics_directory(app_data_directory: str | Path) -> Path:
    """Return the diagnostic subdirectory beneath Qt's app-local data folder."""
    return Path(app_data_directory).expanduser() / "diagnostics"
