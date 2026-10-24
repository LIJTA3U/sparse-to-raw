#!/usr/bin/env python3
"""Futuristic PySide6 desktop GUI for Android Sparse Image conversion.

Conversion and image validation are delegated to sparse_to_raw.py. This module
adds localization, persistent preferences, recent files, image analysis, a batch
queue, visual merge ordering, and JSON reports without changing the CLI API.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QSize, QSettings, Qt, QThread, Signal, Slot
from PySide6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
    QPen, QRegion, QTextCharFormat, QTextCursor,
)
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QProgressBar, QPushButton, QSizePolicy, QTableWidget,
    QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget, QAbstractItemView,
    QDialogButtonBox, QFormLayout, QInputDialog, QStyle,
)

from sparse_to_raw import (
    ConversionCancelled,
    _read_declared_raw_size,
    convert_sparse_to_raw,
    inspect_sparse,
    merge_sparse_to_raw,
)

APP_VERSION = "v0.4.0"
ORG_NAME = "LIJTA3U"
APP_NAME = "sparse-to-raw"
MAX_RECENT = 12

COLORS = {
    "background": "#070d16", "panel": "#0b1520", "panel_alt": "#0d1c29",
    "border": "#243a47", "cyan": "#21d9ef", "cyan_dim": "#147b91",
    "yellow": "#ffc928", "yellow_light": "#ffe789", "text": "#edf4f7",
    "muted": "#8fa4b1", "green": "#65e58b", "red": "#ff6375", "amber": "#ffc46b",
}

I18N: dict[str, dict[str, str]] = {
    "ru": {
        "window_title": "sparse-to-raw", "main_heading": "Преобразование образа",
        "source_label": "Исходный Sparse-образ", "output_label": "Выходной RAW-образ",
        "source_placeholder": "Выберите файл…", "output_placeholder": "Путь сохранения RAW-образа…",
        "browse": "Обзор", "drop_title": "Перетащите файл сюда", "drop_subtitle": "или выберите файл вручную",
        "convert": "ПРЕОБРАЗОВАТЬ", "cancel": "ОТМЕНИТЬ", "progress": "Прогресс преобразования",
        "stats": "СТАТИСТИКА", "chunks": "Обработано чанков", "size": "Размер результата",
        "status_idle": "ОЖИДАНИЕ", "log": "Журнал операций", "clear_log": "Очистить журнал",
        "analyze": "Анализ образа", "queue": "Очередь задач", "merge": "Объединить Sparse",
        "save_report": "Сохранить отчёт…", "recent": "Последние файлы", "language": "Язык",
        "speed_unit": "Единицы скорости", "status_preparing": "ПОДГОТОВКА",
        "status_success": "УСПЕШНО ЗАВЕРШЕНО", "status_error": "ОШИБКА ПРЕОБРАЗОВАНИЯ",
        "status_cancelled": "ОТМЕНЕНО", "ready": "Ожидание", "done": "Готово",
        "analyze_title": "Анализ Sparse-образа", "queue_title": "Пакетная конвертация",
        "merge_title": "Объединение Sparse-частей", "add_files": "Добавить файлы…",
        "remove": "Удалить", "clear": "Очистить", "move_up": "Вверх", "move_down": "Вниз",
        "output_folder": "Папка назначения", "choose_folder": "Выбрать…", "run_queue": "Запустить очередь",
        "start_analysis": "Проверить образ", "start_merge": "Объединить части", "source_file": "Входной файл",
        "save_json": "Сохранить JSON…", "overwrite": "Разрешить перезапись существующих файлов",
        "queue_hint": "Файлы будут обрабатываться последовательно. Ошибка одного файла не остановит остальные.",
        "merge_hint": "Добавьте самостоятельные Sparse-файлы в правильном порядке. Каждый файл должен иметь собственный заголовок.",
        "analysis_ready": "Выберите файл и нажмите «Проверить образ».", "result": "Результат",
        "file": "Файл", "state": "Состояние", "raw_size": "RAW-размер", "chunks_count": "Чанков",
        "language_ru": "Русский", "language_en": "English", "speed_mb": "МБ/с (десятичные)",
        "speed_mib": "МиБ/с (двоичные)", "speed_mbit": "Мбит/с", "status": "СТАТУС",
        "recent_empty": "Нет недавних файлов", "analysis_ok": "Проверка завершена успешно.",
        "report_saved": "Отчёт сохранён", "confirm_overwrite": "Файл уже существует:\n{path}\n\nЗаменить его только после успешной проверки?",
        "confirm_title": "Подтверждение перезаписи", "missing_source": "Исходный файл не найден или не является файлом:\n{path}",
        "same_path": "Пути исходного и выходного файлов должны различаться.",
        "another_operation": "Другая операция уже выполняется. Дождитесь её завершения.",
        "merge_min_parts": "Для объединения нужно выбрать не менее двух независимых Sparse-файлов.",
        "merge_same_output": "Выходной путь должен отличаться от путей всех входных файлов.",
        "output_collision": "Несколько входных файлов дают одинаковое имя результата. Переименуйте файлы или измените папку назначения.",
    },
    "en": {
        "window_title": "sparse-to-raw", "main_heading": "Image conversion",
        "source_label": "Input Sparse image", "output_label": "Output RAW image",
        "source_placeholder": "Choose a file…", "output_placeholder": "RAW output path…",
        "browse": "Browse", "drop_title": "Drop a file here", "drop_subtitle": "or select a file manually",
        "convert": "CONVERT", "cancel": "CANCEL", "progress": "Conversion progress",
        "stats": "STATISTICS", "chunks": "Processed chunks", "size": "Output size",
        "status_idle": "IDLE", "log": "Operation log", "clear_log": "Clear log",
        "analyze": "Analyze image", "queue": "Task queue", "merge": "Merge Sparse",
        "save_report": "Save report…", "recent": "Recent files", "language": "Language",
        "speed_unit": "Speed units", "status_preparing": "PREPARING",
        "status_success": "COMPLETED SUCCESSFULLY", "status_error": "CONVERSION ERROR",
        "status_cancelled": "CANCELLED", "ready": "Ready", "done": "Done",
        "analyze_title": "Sparse image analysis", "queue_title": "Batch conversion",
        "merge_title": "Merge Sparse parts", "add_files": "Add files…",
        "remove": "Remove", "clear": "Clear", "move_up": "Move up", "move_down": "Move down",
        "output_folder": "Output folder", "choose_folder": "Choose…", "run_queue": "Run queue",
        "start_analysis": "Verify image", "start_merge": "Merge parts", "source_file": "Input file",
        "save_json": "Save JSON…", "overwrite": "Allow overwriting existing files",
        "queue_hint": "Files are processed sequentially. A failed file will not stop the remaining queue.",
        "merge_hint": "Add standalone Sparse files in the correct order. Each file must have its own header.",
        "analysis_ready": "Choose a file and click “Verify image”.", "result": "Result",
        "file": "File", "state": "State", "raw_size": "RAW size", "chunks_count": "Chunks",
        "language_ru": "Русский", "language_en": "English", "speed_mb": "MB/s (decimal)",
        "speed_mib": "MiB/s (binary)", "speed_mbit": "Mbit/s", "status": "STATUS",
        "recent_empty": "No recent files", "analysis_ok": "Validation completed successfully.",
        "report_saved": "Report saved", "confirm_overwrite": "The file already exists:\n{path}\n\nReplace it only after successful validation?",
        "confirm_title": "Confirm overwrite", "missing_source": "Input file does not exist or is not a file:\n{path}",
        "same_path": "Input and output paths must be different.",
        "another_operation": "Another operation is already running. Wait for it to finish.",
        "merge_min_parts": "Select at least two independent Sparse files to merge.",
        "merge_same_output": "The output path must differ from every input path.",
        "output_collision": "Multiple inputs would produce the same output name. Rename the files or change the output folder.",
    },
}


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


def format_bytes(value: int, language: str = "ru") -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB") if language == "en" else ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ", "ПиБ")
    number = float(max(0, value))
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:,.2f} {unit}".replace(",", " ")
        number /= 1024
    return f"{value} B"


def format_speed(bytes_per_second: float, unit: str, language: str = "ru") -> str:
    value = max(0.0, float(bytes_per_second))
    if unit == "Mbit/s":
        return f"{value * 8 / 1_000_000:,.2f} Mbit/s".replace(",", " ")
    if unit == "MiB/s":
        return f"{value / (1024 * 1024):,.2f} MiB/s".replace(",", " ")
    label = "MB/s" if language == "en" else "МБ/с"
    return f"{value / 1_000_000:,.2f} {label}".replace(",", " ")


def suggested_output_path(input_path: str | Path) -> str:
    source = Path(input_path).expanduser()
    return str(source.with_name(f"{source.stem}_raw.img"))


def friendly_error(message: str, language: str = "ru") -> str:
    """Turn common format/filesystem failures into actionable UI diagnostics."""
    low = message.lower()
    diagnostics = [
        (("invalid sparse magic", "not a sparse image", "не является android sparse"),
         "Файл не распознан как Android Sparse-образ. Проверь тип входного файла и его заголовок.",
         "The input is not recognized as an Android Sparse image. Check the file type and header."),
        (("crc32 mismatch", "crc32 mismatch"),
         "Контрольная сумма CRC32 не совпадает. Исходный образ может быть повреждён.",
         "The CRC32 checksum does not match. The input image may be corrupted."),
        (("image checksum mismatch", "общая контрольная сумма"),
         "Общая контрольная сумма образа не совпадает. Результат не был опубликован.",
         "The image-level checksum does not match. The output was not committed."),
        (("unexpected end of file", "truncated", "обрезан"),
         "Файл обрезан: данных меньше, чем требуется по заголовку.",
         "The file is truncated: it contains less data than declared by its header."),
        (("no space left", "disk full", "not enough space"),
         "Недостаточно свободного места для завершения операции.",
         "There is not enough free disk space to complete the operation."),
        (("output file already exists", "file already exists", "already exists"),
         "Выходной файл уже существует. Выбери другое имя или подтверди перезапись.",
         "The output file already exists. Choose another path or confirm overwrite."),
        (("permission denied", "access is denied", "cannot write", "нет возможности записывать"),
         "Нет доступа для записи в выбранный каталог. Проверь права и путь назначения.",
         "The output folder is not writable. Check the destination path and permissions."),
        (("input file not found", "does not exist or is not a file", "не найден"),
         "Исходный файл не найден. Проверь путь и подключение накопителя.",
         "The input file was not found. Check the path and whether the drive is available."),
    ]
    for needles, ru, en in diagnostics:
        if any(needle in low for needle in needles):
            return en if language == "en" else ru
    return message


def validate_paths(input_text: str, output_text: str) -> tuple[Path, Path, int]:
    if not input_text.strip():
        raise ValueError("Выбери исходный Sparse-образ.")
    if not output_text.strip():
        raise ValueError("Укажи путь для выходного RAW-образа.")
    source = Path(input_text).expanduser().resolve()
    destination = Path(output_text).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Исходный файл не найден или не является файлом:\n{source}")
    if source == destination:
        raise ValueError("Пути исходного и выходного файлов должны различаться.")
    if destination.exists():
        try:
            if os.path.samefile(source, destination):
                raise ValueError("Исходный и выходной пути ссылаются на один файл.")
        except OSError:
            pass
    if destination.is_dir():
        raise IsADirectoryError(f"Output path is a directory:\n{destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Output directory does not exist:\n{destination.parent}")
    probe_fd = None
    probe_path: Path | None = None
    try:
        probe_fd, probe_name = tempfile.mkstemp(prefix=".sparse-to-raw-write-test-", dir=destination.parent)
        probe_path = Path(probe_name)
    except OSError as exc:
        raise PermissionError(f"Нет возможности записывать в каталог результата:\n{destination.parent}\n{exc}") from exc
    finally:
        if probe_fd is not None:
            os.close(probe_fd)
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass
    expected_size = _read_declared_raw_size(source)
    return source, destination, expected_size


class AngularButton(QPushButton):
    """Custom-painted beveled yellow action button."""
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.setStyleSheet("background: transparent; border: 0; color: #10141a;")

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        cut = min(24.0, rect.height() * 0.42)
        path = QPainterPath()
        path.moveTo(rect.left() + cut, rect.top())
        path.lineTo(rect.right() - cut, rect.top())
        path.lineTo(rect.right(), rect.center().y())
        path.lineTo(rect.right() - cut, rect.bottom())
        path.lineTo(rect.left() + cut, rect.bottom())
        path.lineTo(rect.left(), rect.center().y())
        path.closeSubpath()
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        if not self.isEnabled():
            gradient.setColorAt(0, QColor("#6b674e")); gradient.setColorAt(1, QColor("#3d3b34"))
            text_color = QColor("#a3a19a")
        else:
            gradient.setColorAt(0, QColor("#fff08e" if self.underMouse() else "#ffe36d"))
            gradient.setColorAt(0.48, QColor("#ffc928")); gradient.setColorAt(1, QColor("#e7a909"))
            text_color = QColor("#10141a")
        painter.setPen(QPen(QColor("#ffe99a") if self.isEnabled() else QColor("#5e5843"), 1.2))
        painter.setBrush(QBrush(gradient)); painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 220, 155), 1))
        painter.drawLine(QPointF(rect.left()+cut+8, rect.top()+5), QPointF(rect.right()-cut-8, rect.top()+5))
        painter.setPen(text_color); painter.setFont(self.font())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class DropZone(QFrame):
    fileDropped = Signal(str)
    browseRequested = Signal()
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True); self.setObjectName("dropZone"); self.setMinimumHeight(78); self.setMaximumHeight(94)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self); layout.setContentsMargins(14, 8, 14, 8); layout.setSpacing(12)
        self.icon = QLabel("⇩"); self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter); self.icon.setFixedWidth(60)
        self.icon.setFont(QFont("Segoe UI Symbol", 34)); self.icon.setStyleSheet(f"color:{COLORS['cyan']};background:transparent")
        layout.addWidget(self.icon)
        labels = QVBoxLayout(); labels.setSpacing(2)
        self.title = QLabel(); self.title.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold)); self.title.setStyleSheet(f"color:{COLORS['cyan']};background:transparent")
        self.subtitle = QLabel(); self.subtitle.setStyleSheet(f"color:{COLORS['muted']};background:transparent")
        labels.addWidget(self.title); labels.addWidget(self.subtitle); layout.addLayout(labels, 1)
        self.setStyleSheet(f"QFrame#dropZone{{background:#07131d;border:1px dashed {COLORS['cyan']};border-radius:5px}}")

    def set_language(self, language: str) -> None:
        self.title.setText(I18N[language]["drop_title"])
        self.subtitle.setText(I18N[language]["drop_subtitle"])

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.browseRequested.emit(); event.accept()
        else: super().mousePressEvent(event)
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction(); self.title.setText("Отпустите файл для выбора" if self.title.text().startswith("Перетащите") else "Drop to select file")
        else: event.ignore()
    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self.set_language("en" if self.subtitle.text().startswith("or ") else "ru"); event.accept()
    def dropEvent(self, event) -> None:  # noqa: N802
        files = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile() and Path(u.toLocalFile()).is_file()]
        if files:
            self.fileDropped.emit(files[0]); self.title.setText("Файл выбран" if self.subtitle.text().startswith("или") else "File selected"); event.acceptProposedAction()
        else: event.ignore()


class HeaderBar(QWidget):
    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent); self._drag_offset: QPoint | None = None; self.setFixedHeight(56)
        layout = QHBoxLayout(self); layout.setContentsMargins(8, 1, 8, 0); layout.setSpacing(10)
        self.brand = QLabel("sparse-to-raw"); self.brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.brand.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold)); self.brand.setStyleSheet(f"color:{COLORS['text']};background:transparent")
        self.version = QLabel(version); self.version.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.version.setFont(QFont("Consolas", 10)); self.version.setStyleSheet(f"color:{COLORS['cyan']};background:transparent")
        layout.addWidget(self.brand); layout.addWidget(self.version); layout.addStretch(1)
        self.minimize_button = QPushButton("—"); self.minimize_button.setObjectName("windowControl"); self.minimize_button.setFixedSize(42, 32)
        self.minimize_button.setToolTip("Minimize / Свернуть"); self.minimize_button.clicked.connect(lambda: self.window().showMinimized())
        self.close_button = QPushButton("×"); self.close_button.setObjectName("closeControl"); self.close_button.setFixedSize(42, 32)
        self.close_button.setToolTip("Close / Закрыть"); self.close_button.clicked.connect(lambda: self.window().close())
        layout.addWidget(self.minimize_button); layout.addWidget(self.close_button)
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft(); event.accept()
        else: super().mousePressEvent(event)
    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset); event.accept()
        else: super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_offset = None; super().mouseReleaseEvent(event)


class ConversionWorkerObject(QObject):
    """Qt worker for conversion, inspection or ordered merge."""
    progress = Signal(dict); log = Signal(str, str); succeeded = Signal(dict); failed = Signal(str); cancelled = Signal(); finished = Signal()
    def __init__(self, source: Path | None, destination: Path | None, force: bool,
                 operation: str = "convert", merge_sources: list[Path] | None = None) -> None:
        super().__init__(); self.source = source; self.destination = destination; self.force = force
        self.operation = operation; self.merge_sources = merge_sources or []; self._cancel_event = threading.Event()
    @Slot()
    def run(self) -> None:
        try:
            kwargs = {"progress_callback": self.progress.emit, "event_callback": self.log.emit,
                      "cancel_requested": self._cancel_event.is_set, "calculate_sha256": True}
            if self.operation == "convert":
                assert self.source is not None and self.destination is not None
                result = convert_sparse_to_raw(self.source, self.destination, force=self.force, **kwargs)
            elif self.operation == "inspect":
                assert self.source is not None
                result = inspect_sparse(self.source, mode="info", **kwargs)
            elif self.operation == "merge":
                assert self.destination is not None
                result = merge_sparse_to_raw(self.merge_sources, self.destination, force=self.force, **kwargs)
            else:
                raise ValueError(f"Unknown worker operation: {self.operation}")
        except ConversionCancelled: self.cancelled.emit()
        except Exception as exc:
            self.log.emit("error", f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"); self.failed.emit(str(exc))
        else: self.succeeded.emit(result)
        finally: self.finished.emit()
    def request_cancel(self) -> None: self._cancel_event.set()


class BatchWorkerObject(QObject):
    progress = Signal(dict); log = Signal(str, str); item_finished = Signal(int, dict); finished_report = Signal(dict); finished = Signal()
    def __init__(self, sources: list[Path], output_dir: Path, overwrite: bool) -> None:
        super().__init__(); self.sources = sources; self.output_dir = output_dir; self.overwrite = overwrite
        self._cancel_event = threading.Event()
    @Slot()
    def run(self) -> None:
        from sparse_to_raw import _format_duration
        started = datetime.now(); rows: list[dict[str, Any]] = []; total = len(self.sources)
        planned_outputs: dict[str, list[int]] = {}
        for i, source_item in enumerate(self.sources):
            planned_outputs.setdefault(str((self.output_dir / f"{source_item.stem}_raw.img").resolve()).casefold(), []).append(i)
        collision_indices = {i for indices in planned_outputs.values() if len(indices) > 1 for i in indices}
        self.log.emit("info", f"Batch started: {total} file(s).")
        try:
            for index, source in enumerate(self.sources):
                if self._cancel_event.is_set():
                    rows.append({"input": str(source), "status": "cancelled", "error": "Cancelled before start"})
                    self.item_finished.emit(index, rows[-1]); continue
                destination = self.output_dir / f"{source.stem}_raw.img"
                self.log.emit("info", f"[{index+1}/{total}] {source}")
                row: dict[str, Any] = {"input": str(source), "output": str(destination), "status": "failed"}
                try:
                    if index in collision_indices:
                        raise ValueError(f"Output-name collision: multiple input files map to {destination}. Use different file names or output folders.")
                    if destination.exists() and not self.overwrite:
                        raise FileExistsError(f"Output exists; skipped to prevent overwrite: {destination}")
                    def per_file_progress(data: dict[str, Any], *, _idx=index) -> None:
                        current = int(data.get("percent", 0))
                        self.progress.emit({**data, "queue_index": _idx, "queue_total": total,
                                            "queue_percent": int((_idx + current / 100) * 100 / max(total, 1)),
                                            "queue_current_file": str(source)})
                    result = convert_sparse_to_raw(source, destination, force=self.overwrite, calculate_sha256=True,
                        progress_callback=per_file_progress, event_callback=self.log.emit,
                        cancel_requested=self._cancel_event.is_set)
                    row.update({"status": "success", "result": result})
                    self.log.emit("success", f"[{index+1}/{total}] Completed: {destination}")
                except ConversionCancelled:
                    row.update({"status": "cancelled", "error": "Cancelled by user"})
                    self.log.emit("warning", f"[{index+1}/{total}] Cancelled: {source}")
                except Exception as exc:
                    row.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
                    self.log.emit("error", f"[{index+1}/{total}] Failed: {source}\n{type(exc).__name__}: {exc}")
                rows.append(row); self.item_finished.emit(index, row)
                if self._cancel_event.is_set():
                    for later in self.sources[index+1:]:
                        row2 = {"input": str(later), "status": "cancelled", "error": "Cancelled before start"}
                        rows.append(row2); self.item_finished.emit(len(rows)-1, row2)
                    break
            report = {"application": APP_NAME, "version": APP_VERSION, "generated_at": datetime.now().astimezone().isoformat(),
                      "started_at": started.astimezone().isoformat(), "output_directory": str(self.output_dir),
                      "summary": {"total": len(self.sources), "success": sum(r["status"] == "success" for r in rows),
                                  "failed": sum(r["status"] == "failed" for r in rows),
                                  "cancelled": sum(r["status"] == "cancelled" for r in rows)}, "items": rows}
            report_path = self.output_dir / f"sparse-to-raw-batch-report-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
            try:
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                report["report_path"] = str(report_path); self.log.emit("success", f"Batch report saved: {report_path}")
            except OSError as exc:
                self.log.emit("warning", f"Could not save batch JSON report: {exc}")
            self.finished_report.emit(report)
        finally: self.finished.emit()
    def request_cancel(self) -> None: self._cancel_event.set()


def connect_worker(worker: ConversionWorkerObject, parent: QWidget, finished_callback) -> QThread:
    thread = QThread(parent); worker.moveToThread(thread); thread.started.connect(worker.run)
    worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater); thread.finished.connect(finished_callback)
    return thread


class AnalysisDialog(QDialog):
    def __init__(self, parent: "MainWindow", initial_path: str = "") -> None:
        super().__init__(parent); self.main = parent; self.result: dict[str, Any] | None = None
        self.thread: QThread | None = None; self.worker: ConversionWorkerObject | None = None; self._close_when_finished = False
        self.setWindowTitle(parent.t("analyze_title")); self.resize(760, 560); self.setModal(False)
        layout = QVBoxLayout(self); form = QHBoxLayout()
        self.input_edit = QLineEdit(initial_path); self.input_edit.setPlaceholderText(parent.t("source_placeholder")); form.addWidget(self.input_edit, 1)
        browse = QPushButton(parent.t("browse")); browse.setIcon(parent.icon_for("SP_DialogOpenButton")); browse.setIconSize(parent.icon_size); form.addWidget(browse)
        browse.clicked.connect(self._browse); layout.addLayout(form)
        self.analyze_button = QPushButton(parent.t("start_analysis")); self.analyze_button.setIcon(parent.icon_for("SP_FileDialogContentsView")); self.analyze_button.setIconSize(parent.icon_size); layout.addWidget(self.analyze_button)
        self.progress = QProgressBar(); self.progress.setRange(0,100); layout.addWidget(self.progress)
        self.output = QTextEdit(); self.output.setReadOnly(True); self.output.setFont(QFont("Consolas", 9)); self.output.setPlaceholderText(parent.t("analysis_ready")); layout.addWidget(self.output, 1)
        self.save_button = QPushButton(parent.t("save_json")); self.save_button.setIcon(parent.icon_for("SP_DialogSaveButton")); self.save_button.setIconSize(parent.icon_size); self.save_button.setEnabled(False)
        controls = QHBoxLayout(); controls.addWidget(self.save_button); controls.addStretch(); close = QPushButton("Close" if parent.language == "en" else "Закрыть"); close.clicked.connect(self.close); controls.addWidget(close); layout.addLayout(controls)
        self.analyze_button.clicked.connect(self._start); self.save_button.clicked.connect(self._save_report)
        self._apply_style()
    def _apply_style(self) -> None:
        self.setStyleSheet(f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:7px;border-radius:4px}} QLineEdit,QTextEdit{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f;padding:6px}} QProgressBar{{background:#111d28;border:1px solid #24414e;height:14px}} QProgressBar::chunk{{background:{COLORS['cyan']}}}")
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, self.main.t("source_file"), self.input_edit.text() or str(Path.home()), "Image files (*)")
        if path: self.input_edit.setText(path)
    def _start(self) -> None:
        if self.thread and self.thread.isRunning(): return
        if self.main.operation_running(exclude=self):
            QMessageBox.information(self, self.main.t("window_title"), self.main.t("another_operation")); return
        path = Path(self.input_edit.text().strip()).expanduser().resolve()
        if not path.is_file():
            QMessageBox.warning(self, self.main.t("analyze_title"), f"File not found:\n{path}"); return
        self.output.clear(); self.progress.setValue(0); self.analyze_button.setEnabled(False); self.result = None; self.save_button.setEnabled(False)
        worker = ConversionWorkerObject(path, None, False, operation="inspect"); self.worker = worker
        worker.log.connect(self._log); worker.progress.connect(lambda d: self.progress.setValue(int(d.get("percent",0))))
        worker.succeeded.connect(self._success); worker.failed.connect(self._failure)
        thread = connect_worker(worker, self, self._thread_finished); self.thread = thread; thread.start()
    def _log(self, level: str, message: str) -> None: self.output.append(f"[{level.upper()}] {message}")
    def _success(self, result: dict) -> None:
        self.result = result; self.progress.setValue(100); self.save_button.setEnabled(True)
        self.output.append("\n" + json.dumps(result, ensure_ascii=False, indent=2))
    def _failure(self, message: str) -> None:
        self.output.append(f"\n{self.main.t('status_error')}: {friendly_error(message, self.main.language)}\nDetails: {message}")
    def _thread_finished(self) -> None:
        self.thread = None; self.worker = None; self.analyze_button.setEnabled(True)
        if self._close_when_finished: self.close()
        self.main._check_close_after_workers()
    def closeEvent(self, event) -> None:  # noqa: N802
        if self.thread is not None and self.thread.isRunning():
            self._close_when_finished = True
            if self.worker is not None: self.worker.request_cancel()
            event.ignore(); return
        event.accept()
    def _save_report(self) -> None:
        if not self.result: return
        path, _ = QFileDialog.getSaveFileName(self, self.main.t("save_json"), f"{Path(self.input_edit.text()).stem}-analysis.json", "JSON (*.json)")
        if not path: return
        try: Path(path).write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc: QMessageBox.critical(self, "Error", str(exc)); return
        QMessageBox.information(self, self.main.t("report_saved"), path)


class BatchQueueDialog(QDialog):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent); self.main = parent; self.thread: QThread | None = None; self.worker: BatchWorkerObject | None = None; self._close_when_finished = False
        self.setWindowTitle(parent.t("queue_title")); self.resize(900, 620); self.setModal(False)
        root = QVBoxLayout(self)
        hint = QLabel(parent.t("queue_hint")); hint.setWordWrap(True); hint.setStyleSheet(f"color:{COLORS['muted']};"); root.addWidget(hint)
        self.list = QListWidget(); self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); root.addWidget(self.list, 1)
        row = QHBoxLayout(); self.queue_mutation_buttons = []
        for text, icon, callback in [(parent.t("add_files"), "SP_DialogOpenButton", self._add_files), (parent.t("remove"), "SP_TrashIcon", self._remove), (parent.t("clear"), "SP_DialogResetButton", self.list.clear)]:
            btn = QPushButton(text); btn.setIcon(parent.icon_for(icon)); btn.setIconSize(parent.icon_size); btn.clicked.connect(callback); row.addWidget(btn); self.queue_mutation_buttons.append(btn)
        root.addLayout(row)
        folder_row = QHBoxLayout(); self.folder_edit = QLineEdit(str(parent.settings.value("queue_output_dir", str(Path.home() / "sparse-to-raw-output")))); folder_row.addWidget(QLabel(parent.t("output_folder"))); folder_row.addWidget(self.folder_edit,1)
        browse = QPushButton(parent.t("choose_folder")); browse.setIcon(parent.icon_for("SP_DirOpenIcon")); browse.setIconSize(parent.icon_size); browse.clicked.connect(self._browse_folder); folder_row.addWidget(browse); root.addLayout(folder_row)
        self.overwrite = QCheckBox(parent.t("overwrite")); root.addWidget(self.overwrite)
        self.progress = QProgressBar(); self.progress.setRange(0,100); root.addWidget(self.progress)
        self.log_view = QTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(135); self.log_view.document().setMaximumBlockCount(1000); root.addWidget(self.log_view)
        buttons = QHBoxLayout(); self.run_button = QPushButton(parent.t("run_queue")); self.run_button.setIcon(parent.icon_for("SP_MediaPlay")); self.run_button.setIconSize(parent.icon_size); buttons.addWidget(self.run_button)
        self.cancel_button = QPushButton(parent.t("cancel")); self.cancel_button.setIcon(parent.icon_for("SP_MediaStop")); self.cancel_button.setIconSize(parent.icon_size); self.cancel_button.setEnabled(False); buttons.addWidget(self.cancel_button); buttons.addStretch()
        close = QPushButton("Close" if parent.language == "en" else "Закрыть"); close.clicked.connect(self.close); buttons.addWidget(close); root.addLayout(buttons)
        self.run_button.clicked.connect(self._run); self.cancel_button.clicked.connect(self._cancel); self._apply_style()
    def _apply_style(self) -> None:
        self.setStyleSheet(f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} QListWidget,QTextEdit,QLineEdit{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f}} QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:6px;border-radius:4px}} QProgressBar{{background:#111d28;border:1px solid #24414e;height:14px}} QProgressBar::chunk{{background:{COLORS['cyan']}}}")
    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self.main.t("add_files"), str(Path.home()), "Images (*)")
        known = {self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())}
        for p in paths:
            if p not in known:
                item = QListWidgetItem(f"WAITING  ·  {p}"); item.setData(Qt.ItemDataRole.UserRole, p); self.list.addItem(item); known.add(p)
                self.main.add_recent(p)
                if self.list.count() == 1: self.folder_edit.setText(str(Path(p).parent / "sparse-to-raw-output"))
    def _remove(self) -> None:
        for item in self.list.selectedItems(): self.list.takeItem(self.list.row(item))
    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.main.t("output_folder"), self.folder_edit.text())
        if path:
            self.folder_edit.setText(path); self.main.settings.setValue("queue_output_dir", path)
    def _run(self) -> None:
        if self.thread and self.thread.isRunning(): return
        if self.main.operation_running(exclude=self):
            QMessageBox.information(self, self.main.t("queue_title"), self.main.t("another_operation")); return
        sources = [Path(self.list.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.list.count())]
        if not sources: QMessageBox.information(self, self.main.t("queue_title"), self.main.t("add_files")); return
        output_dir = Path(self.folder_edit.text()).expanduser().resolve()
        try: output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc: QMessageBox.critical(self, "Error", str(exc)); return
        self.main.settings.setValue("queue_output_dir", str(output_dir))
        self.list.setEnabled(False); self.folder_edit.setEnabled(False); self.overwrite.setEnabled(False)
        for button in self.queue_mutation_buttons: button.setEnabled(False)
        self.run_button.setEnabled(False); self.cancel_button.setEnabled(True); self.progress.setValue(0)
        for i in range(self.list.count()): self.list.item(i).setText(f"{'ОЖИДАНИЕ' if self.main.language == 'ru' else 'WAITING'}  ·  {sources[i]}")
        worker = BatchWorkerObject(sources, output_dir, self.overwrite.isChecked()); self.worker = worker
        worker.log.connect(self._log); worker.progress.connect(self._progress); worker.item_finished.connect(self._item_finished); worker.finished_report.connect(self._report_done)
        thread = QThread(self); worker.moveToThread(thread); thread.started.connect(worker.run); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater); thread.finished.connect(thread.deleteLater); thread.finished.connect(self._thread_finished)
        self.thread = thread; thread.start()
    def _log(self, level: str, message: str) -> None: self.log_view.append(f"[{level.upper()}] {message}"); self.main.append_log(level, message)
    def _progress(self, data: dict) -> None: self.progress.setValue(int(data.get("queue_percent", data.get("percent",0))))
    def _item_finished(self, index: int, row: dict) -> None:
        if 0 <= index < self.list.count():
            status = row.get("status", "unknown").lower()
            states_ru = {"success": "УСПЕШНО", "failed": "ОШИБКА", "cancelled": "ОТМЕНЕНО"}
            states_en = {"success": "SUCCESS", "failed": "FAILED", "cancelled": "CANCELLED"}
            state = (states_ru if self.main.language == "ru" else states_en).get(status, status.upper())
            self.list.item(index).setText(f"{state}  ·  {row.get('input','')}")
            self.list.item(index).setForeground(QColor(COLORS["green"] if status == "success" else COLORS["amber"] if status == "cancelled" else COLORS["red"]))
    def _report_done(self, report: dict) -> None:
        summary = report.get("summary", {}); self.progress.setValue(100 if summary.get("success",0) and not summary.get("failed",0) else self.progress.value())
        self.log_view.append("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
        if report.get("report_path"): self.log_view.append(f"Report: {report['report_path']}")
    def _thread_finished(self) -> None:
        self.thread = None; self.worker = None; self.run_button.setEnabled(True); self.cancel_button.setEnabled(False)
        self.list.setEnabled(True); self.folder_edit.setEnabled(True); self.overwrite.setEnabled(True)
        for button in self.queue_mutation_buttons: button.setEnabled(True)
        if self._close_when_finished: self.close()
        self.main._check_close_after_workers()
    def closeEvent(self, event) -> None:  # noqa: N802
        if self.thread is not None and self.thread.isRunning():
            self._close_when_finished = True
            if self.worker is not None: self.worker.request_cancel()
            event.ignore(); return
        event.accept()
    def _cancel(self) -> None:
        if self.worker: self.cancel_button.setEnabled(False); self.worker.request_cancel(); self._log("warning", "Cancellation requested; current file will stop at a safe boundary.")


class MergeDialog(QDialog):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent); self.main = parent; self.thread: QThread | None = None; self.worker: ConversionWorkerObject | None = None; self.result: dict | None = None; self._close_when_finished = False
        self.setWindowTitle(parent.t("merge_title")); self.resize(850, 590); self.setModal(False)
        root = QVBoxLayout(self); hint = QLabel(parent.t("merge_hint")); hint.setWordWrap(True); hint.setStyleSheet(f"color:{COLORS['muted']}"); root.addWidget(hint)
        self.parts = QListWidget(); self.parts.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); root.addWidget(self.parts,1)
        actions = QHBoxLayout(); self.part_controls = []
        controls = [(parent.t("add_files"), "SP_DialogOpenButton", self._add), (parent.t("remove"), "SP_TrashIcon", self._remove), (parent.t("move_up"), "SP_ArrowUp", self._up), (parent.t("move_down"), "SP_ArrowDown", self._down)]
        for label, icon_name, callback in controls:
            button = QPushButton(label); button.setIcon(parent.icon_for(icon_name)); button.setIconSize(parent.icon_size); button.clicked.connect(callback); actions.addWidget(button); self.part_controls.append(button)
        root.addLayout(actions)
        out = QHBoxLayout(); out.addWidget(QLabel(parent.t("output_label"))); self.output_edit = QLineEdit(str(parent.settings.value("merge_output_path", str(Path.home()/"merged_raw.img")))); self.output_edit.textChanged.connect(lambda value: parent.settings.setValue("merge_output_path", value)); out.addWidget(self.output_edit,1)
        browse = QPushButton(parent.t("browse")); browse.setIcon(parent.icon_for("SP_DialogSaveButton")); browse.setIconSize(parent.icon_size); browse.clicked.connect(self._browse_output); out.addWidget(browse); root.addLayout(out)
        self.progress = QProgressBar(); self.progress.setRange(0,100); root.addWidget(self.progress)
        self.log_view = QTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(125); root.addWidget(self.log_view)
        buttons = QHBoxLayout(); self.run_button = QPushButton(parent.t("start_merge")); self.run_button.setIcon(parent.icon_for("SP_DialogApplyButton")); self.run_button.setIconSize(parent.icon_size); buttons.addWidget(self.run_button)
        self.cancel_button = QPushButton(parent.t("cancel")); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self._cancel); buttons.addWidget(self.cancel_button); self.save_report = QPushButton(parent.t("save_json")); self.save_report.setEnabled(False); self.save_report.clicked.connect(self._save_report); buttons.addWidget(self.save_report); buttons.addStretch()
        close = QPushButton("Close" if parent.language == "en" else "Закрыть"); close.clicked.connect(self.close); buttons.addWidget(close); root.addLayout(buttons)
        self.run_button.clicked.connect(self._run); self._apply_style()
    def _apply_style(self) -> None:
        self.setStyleSheet(f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} QListWidget,QTextEdit,QLineEdit{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f}} QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:6px;border-radius:4px}} QProgressBar{{background:#111d28;border:1px solid #24414e;height:14px}} QProgressBar::chunk{{background:{COLORS['cyan']}}}")
    def _add(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self.main.t("add_files"), str(Path.home()), "Sparse images (*)")
        known = {self.parts.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.parts.count())}
        for p in paths:
            if p not in known:
                self.parts.addItem(QListWidgetItem(p)); self.parts.item(self.parts.count()-1).setData(Qt.ItemDataRole.UserRole,p); self.main.add_recent(p); known.add(p); self.main.settings.setValue("merge_output_path", str(Path(p).parent/"merged_raw.img"))
                if self.parts.count()==1: self.output_edit.setText(str(Path(p).parent/"merged_raw.img"))
    def _remove(self) -> None:
        for item in self.parts.selectedItems(): self.parts.takeItem(self.parts.row(item))
    def _move(self, delta: int) -> None:
        row = self.parts.currentRow()
        if row < 0 or row+delta < 0 or row+delta >= self.parts.count(): return
        item = self.parts.takeItem(row); self.parts.insertItem(row+delta,item); self.parts.setCurrentRow(row+delta)
    def _up(self) -> None: self._move(-1)
    def _down(self) -> None: self._move(1)
    def _browse_output(self) -> None:
        path,_=QFileDialog.getSaveFileName(self,self.main.t("output_label"),self.output_edit.text(),"RAW images (*.img *.raw);;All files (*)")
        if path: self.output_edit.setText(path)
    def _run(self) -> None:
        if self.thread and self.thread.isRunning(): return
        if self.main.operation_running(exclude=self):
            QMessageBox.information(self, self.main.t("merge_title"), self.main.t("another_operation")); return
        sources = [Path(self.parts.item(i).data(Qt.ItemDataRole.UserRole)) for i in range(self.parts.count())]
        if len(sources)<2: QMessageBox.warning(self,self.main.t("merge_title"),self.main.t("merge_min_parts")); return
        out = Path(self.output_edit.text()).expanduser().resolve()
        if out in [p.resolve() for p in sources]: QMessageBox.warning(self,self.main.t("merge_title"),self.main.t("merge_same_output")); return
        force=False
        if out.exists():
            answer=QMessageBox.question(self,self.main.t("confirm_title"),self.main.t("confirm_overwrite").format(path=out),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer!=QMessageBox.StandardButton.Yes: return
            force=True
        self.parts.setEnabled(False); self.output_edit.setEnabled(False)
        for button in self.part_controls: button.setEnabled(False)
        self.run_button.setEnabled(False); self.cancel_button.setEnabled(True); self.progress.setValue(0); self.log_view.clear(); self.result=None; self.save_report.setEnabled(False)
        worker=ConversionWorkerObject(None,out,force,operation="merge",merge_sources=sources); self.worker=worker
        worker.progress.connect(lambda d:self.progress.setValue(int(d.get("percent",0))))
        worker.log.connect(self._log); worker.succeeded.connect(self._success); worker.failed.connect(self._failure); worker.cancelled.connect(lambda:self._log("warning","Merge cancelled; staged output discarded."))
        thread=connect_worker(worker,self,self._thread_finished); self.thread=thread; thread.start()
    def _log(self, level: str, message: str) -> None: self.log_view.append(f"[{level.upper()}] {message}"); self.main.append_log(level,message)
    def _success(self,result:dict) -> None:
        self.result=result; self.progress.setValue(100); self.save_report.setEnabled(True); self.log_view.append("\n"+json.dumps(result,ensure_ascii=False,indent=2))
    def _failure(self,message:str) -> None:
        self._log("error",message)
        friendly = friendly_error(message, self.main.language)
        QMessageBox.critical(self,self.main.t("merge_title"),f"{friendly}\n\nDetails: {message}")
    def _thread_finished(self) -> None:
        self.thread=None; self.worker=None; self.run_button.setEnabled(True); self.cancel_button.setEnabled(False)
        self.parts.setEnabled(True); self.output_edit.setEnabled(True)
        for button in self.part_controls: button.setEnabled(True)
        if self._close_when_finished: self.close()
        self.main._check_close_after_workers()
    def closeEvent(self, event) -> None:  # noqa: N802
        if self.thread is not None and self.thread.isRunning():
            self._close_when_finished = True
            if self.worker is not None: self.worker.request_cancel()
            event.ignore(); return
        event.accept()
    def _cancel(self) -> None:
        if self.worker: self.cancel_button.setEnabled(False); self.worker.request_cancel()
    def _save_report(self) -> None:
        if not self.result: return
        path,_=QFileDialog.getSaveFileName(self,self.main.t("save_json"),"merge-report.json","JSON (*.json)")
        if path:
            try: Path(path).write_text(json.dumps(self.result,ensure_ascii=False,indent=2),encoding="utf-8")
            except OSError as exc: QMessageBox.critical(self,"Error",str(exc))


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.language = str(self.settings.value("language", "ru"))
        if self.language not in I18N: self.language = "ru"
        self.speed_unit = str(self.settings.value("speed_unit", "MiB/s"))
        if self.speed_unit not in ("MB/s", "MiB/s", "Mbit/s"): self.speed_unit = "MiB/s"
        self.recent_files = [str(x) for x in self.settings.value("recent_files", [], type=list) if str(x)]
        self._last_progress = {}; self.last_result: dict[str, Any] | None = None
        self._status_label = I18N[self.language]["status_idle"]; self._status_color = "muted"
        self._close_after_worker = False
        self.setWindowTitle(APP_NAME); self.setWindowIcon(QIcon(str(resource_path("assets/sparse-to-raw.ico")))); self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True); self.setAcceptDrops(True)
        self.setMinimumSize(1120, 760); self.resize(1420, 900)
        self._thread: QThread | None=None; self._worker: ConversionWorkerObject | None=None
        self._output_manual=False; self._setting_output=False; self._close_after_worker=False; self._expected_size=0; self._total_chunks=0
        self.icon_size = self.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize) + 10
        self._build_ui(); self._apply_styles(); self.retranslate_ui(); self._restore_settings()
        self.append_log("info", "Interface ready. Choose an Android Sparse Image.")
        self._update_shape_mask()

    def t(self,key:str) -> str: return I18N[self.language].get(key,key)
    def icon_for(self, standard_name: str) -> QIcon:
        attr = getattr(QStyle.StandardPixmap, standard_name, None)
        return self.style().standardIcon(attr) if attr is not None else QIcon()

    def _build_ui(self) -> None:
        outer=QVBoxLayout(self); outer.setContentsMargins(70,8,68,22); outer.setSpacing(8)
        self.header=HeaderBar(APP_VERSION,self); outer.addWidget(self.header)
        separator=QFrame(); separator.setObjectName("cyanSeparator"); separator.setFixedHeight(2); outer.addWidget(separator)
        toolbar=QHBoxLayout(); toolbar.setSpacing(7)
        self.analyze_button=QPushButton(); self.analyze_button.setIcon(self.icon_for("SP_FileDialogContentsView")); self.analyze_button.setIconSize(QSize(24,24)); self.analyze_button.clicked.connect(self._open_analysis); toolbar.addWidget(self.analyze_button)
        self.queue_button=QPushButton(); self.queue_button.setIcon(self.icon_for("SP_FileDialogListView")); self.queue_button.setIconSize(QSize(24,24)); self.queue_button.clicked.connect(self._open_queue); toolbar.addWidget(self.queue_button)
        self.merge_button=QPushButton(); self.merge_button.setIcon(self.icon_for("SP_DirLinkIcon")); self.merge_button.setIconSize(QSize(24,24)); self.merge_button.clicked.connect(self._open_merge); toolbar.addWidget(self.merge_button)
        self.report_button=QPushButton(); self.report_button.setIcon(self.icon_for("SP_DialogSaveButton")); self.report_button.setIconSize(QSize(24,24)); self.report_button.clicked.connect(self._save_last_report); self.report_button.setEnabled(False); toolbar.addWidget(self.report_button)
        toolbar.addSpacing(8); self.recent_label=QLabel(); toolbar.addWidget(self.recent_label)
        self.recent_combo=QComboBox(); self.recent_combo.setMinimumWidth(140); self.recent_combo.setMaximumWidth(340); self.recent_combo.currentIndexChanged.connect(self._recent_selected); toolbar.addWidget(self.recent_combo,1)
        self.language_label=QLabel(); toolbar.addWidget(self.language_label)
        self.language_combo=QComboBox(); self.language_combo.addItem("Русский","ru"); self.language_combo.addItem("English","en"); self.language_combo.setMaximumWidth(130); self.language_combo.currentIndexChanged.connect(self._language_changed); toolbar.addWidget(self.language_combo)
        outer.addLayout(toolbar)
        title_row=QHBoxLayout(); title_row.setContentsMargins(70,0,70,0); title_row.setSpacing(18)
        self.title_line_left=QFrame(); self.title_line_left.setObjectName("titleLine"); self.title_line_left.setFixedHeight(2)
        self.main_heading=QLabel(); self.main_heading.setAlignment(Qt.AlignmentFlag.AlignCenter); self.main_heading.setFont(QFont("Segoe UI",19,QFont.Weight.DemiBold)); self.main_heading.setStyleSheet(f"color:{COLORS['text']};background:transparent")
        self.title_line_right=QFrame(); self.title_line_right.setObjectName("titleLine"); self.title_line_right.setFixedHeight(2)
        title_row.addWidget(self.title_line_left,1); title_row.addWidget(self.main_heading); title_row.addWidget(self.title_line_right,1); outer.addLayout(title_row)
        self.source_edit=QLineEdit(); self.source_edit.setClearButtonEnabled(True); self.source_edit.textChanged.connect(self._source_path_changed)
        self.output_edit=QLineEdit(); self.output_edit.setClearButtonEnabled(True); self.output_edit.textChanged.connect(self._output_path_changed)
        self.source_row=self._file_row("source_label",self.source_edit,self._browse_source,"source_browse_button")
        self.output_row=self._file_row("output_label",self.output_edit,self._browse_output,"output_browse_button")
        outer.addWidget(self.source_row); outer.addWidget(self.output_row)
        self.drop_zone=DropZone(); self.drop_zone.fileDropped.connect(self._set_source_path); self.drop_zone.browseRequested.connect(self._browse_source); outer.addWidget(self.drop_zone)
        action=QHBoxLayout(); action.setContentsMargins(130,0,130,0); action.setSpacing(12)
        self.convert_button=AngularButton(); self.convert_button.setToolTip("Validate Android Sparse Image and convert to RAW"); self.convert_button.clicked.connect(self._start_conversion)
        self.cancel_button=QPushButton(); self.cancel_button.setObjectName("cancelButton"); self.cancel_button.setIcon(self.icon_for("SP_MediaStop")); self.cancel_button.setIconSize(QSize(22,22)); self.cancel_button.setVisible(False); self.cancel_button.clicked.connect(self._request_cancel)
        action.addWidget(self.convert_button,1); action.addWidget(self.cancel_button); outer.addLayout(action)
        panel=QFrame(); panel.setObjectName("progressPanel"); pl=QVBoxLayout(panel); pl.setContentsMargins(14,8,14,9); pl.setSpacing(7)
        ph=QHBoxLayout(); self.progress_title=QLabel(); self.progress_title.setStyleSheet(f"color:{COLORS['text']};background:transparent")
        self.speed_label=QLabel(); self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); self.speed_label.setStyleSheet(f"color:{COLORS['muted']};background:transparent")
        self.speed_combo=QComboBox(); self.speed_combo.addItem("МБ/с (десятичные)","MB/s"); self.speed_combo.addItem("МиБ/с (двоичные)","MiB/s"); self.speed_combo.addItem("Мбит/с","Mbit/s"); self.speed_combo.setMaximumWidth(170); self.speed_combo.currentIndexChanged.connect(self._speed_unit_changed)
        self.progress_percent=QLabel("0%"); self.progress_percent.setAlignment(Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter); self.progress_percent.setFont(QFont("Consolas",11,QFont.Weight.Bold)); self.progress_percent.setStyleSheet(f"color:{COLORS['cyan']};background:transparent")
        ph.addWidget(self.progress_title,1); ph.addWidget(self.speed_label); ph.addWidget(self.speed_combo); ph.addWidget(self.progress_percent); pl.addLayout(ph)
        self.progress_bar=QProgressBar(); self.progress_bar.setRange(0,100); self.progress_bar.setValue(0); self.progress_bar.setTextVisible(False); self.progress_bar.setFixedHeight(14); pl.addWidget(self.progress_bar); outer.addWidget(panel)
        bottom=QHBoxLayout(); bottom.setSpacing(12)
        stats=QFrame(); stats.setObjectName("infoPanel"); stats.setMinimumWidth(285); stats.setMaximumWidth(360); sl=QVBoxLayout(stats); sl.setContentsMargins(16,12,16,12); sl.setSpacing(10)
        self.stats_title=QLabel(); self.stats_title.setObjectName("panelHeading"); sl.addWidget(self.stats_title)
        self.chunks_label=QLabel("0 / —"); self.chunks_label.setObjectName("statValue"); self.chunks_label.setWordWrap(True); sl.addWidget(self.chunks_label)
        sep=QFrame(); sep.setObjectName("panelSeparator"); sep.setFixedHeight(1); sl.addWidget(sep)
        self.size_label=QLabel("0 B / —"); self.size_label.setObjectName("statValue"); self.size_label.setWordWrap(True); sl.addWidget(self.size_label)
        self.status_label=QLabel(); self.status_label.setObjectName("statusIdle"); self.status_label.setWordWrap(True); sl.addWidget(self.status_label); bottom.addWidget(stats)
        log_panel=QFrame(); log_panel.setObjectName("logPanel"); ll=QVBoxLayout(log_panel); ll.setContentsMargins(12,9,12,10); ll.setSpacing(7)
        lh=QHBoxLayout(); self.log_title=QLabel(); self.log_title.setObjectName("panelHeading"); self.clear_log_button=QPushButton(); self.clear_log_button.setObjectName("clearButton"); self.clear_log_button.setIcon(self.icon_for("SP_DialogResetButton")); self.clear_log_button.setIconSize(QSize(20,20)); self.clear_log_button.setFixedHeight(30); self.clear_log_button.clicked.connect(self._clear_log); lh.addWidget(self.log_title,1); lh.addWidget(self.clear_log_button); ll.addLayout(lh)
        self.log_view=QTextEdit(); self.log_view.setReadOnly(True); self.log_view.document().setMaximumBlockCount(2500); self.log_view.setFont(QFont("Consolas",9)); ll.addWidget(self.log_view,1)
        bottom.addWidget(log_panel,1); bottom.setStretch(1,1); outer.addLayout(bottom,1)

    def _file_row(self,key:str,line_edit:QLineEdit,callback,button_attr:str)->QWidget:
        wrapper=QWidget(); wrapper.setStyleSheet("background:transparent"); layout=QVBoxLayout(wrapper); layout.setContentsMargins(0,0,0,0); layout.setSpacing(5)
        label=QLabel(); label.setObjectName("fieldLabel"); setattr(self, key, label); layout.addWidget(label)
        row=QHBoxLayout(); row.setContentsMargins(0,0,0,0); row.setSpacing(8); row.addWidget(line_edit,1)
        browse=QPushButton(); browse.setObjectName("browseButton"); browse.setIcon(self.icon_for("SP_DialogOpenButton")); browse.setIconSize(QSize(23,23)); browse.setMinimumWidth(118); browse.setFixedHeight(40); browse.clicked.connect(callback); setattr(self,button_attr,browse); row.addWidget(browse); layout.addLayout(row)
        return wrapper

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{ color:{COLORS['text']}; font-family:'Segoe UI'; font-size:10pt; }}
            QLineEdit,QComboBox {{ background:#07111b; border:1px solid #29434f; border-radius:4px; padding:7px 9px; color:{COLORS['text']}; selection-background-color:#146b7d; min-height:21px; }}
            QLineEdit:focus,QComboBox:focus {{ border:1px solid {COLORS['cyan']}; }}
            QLineEdit:disabled {{ color:#657580; background:#0b1219; border-color:#1c2c35; }}
            QLabel#fieldLabel {{ color:#dce8ee; font-weight:600; background:transparent; }}
            QFrame#cyanSeparator {{ background:{COLORS['cyan']}; border:none; }} QFrame#titleLine {{ background:{COLORS['cyan_dim']}; border:none; }}
            QFrame#progressPanel,QFrame#infoPanel,QFrame#logPanel {{ background:rgba(8,19,29,245); border:1px solid #243c49; border-radius:5px; }}
            QLabel#panelHeading {{ color:{COLORS['cyan']}; font-size:9pt; font-weight:700; letter-spacing:1px; }}
            QLabel#statValue {{ color:#d5e2e8; background:transparent; line-height:1.2; }} QLabel#statusIdle {{ color:{COLORS['muted']}; font-family:Consolas; font-size:9pt; }}
            QFrame#panelSeparator {{ background:#203946; border:none; }}
            QPushButton {{ background:#0a1b27; color:{COLORS['cyan']}; border:1px solid #24505e; border-radius:4px; padding:6px 10px; }}
            QPushButton:hover {{ background:#102e3e; border-color:{COLORS['cyan']}; }} QPushButton:pressed {{ background:#164456; }}
            QPushButton:disabled {{ color:#526570; background:#0b1219; border-color:#1c2c35; }}
            QPushButton#browseButton,QPushButton#clearButton {{ background:#0a1b27; color:{COLORS['cyan']}; border:1px solid #24505e; border-radius:4px; padding:6px 10px; }}
            QPushButton#cancelButton {{ color:{COLORS['red']}; border-color:#693342; }} QPushButton#windowControl {{ font-size:17pt; padding:0; }} QPushButton#closeControl {{ font-size:19pt; color:{COLORS['cyan']}; padding:0; }}
            QProgressBar {{ border:1px solid #254450; border-radius:3px; background:#07111b; }} QProgressBar::chunk {{ background:{COLORS['cyan']}; border-radius:2px; }}
            QComboBox QAbstractItemView {{ background:#0b1520; color:{COLORS['text']}; selection-background-color:#146b7d; }}
        """)

    def retranslate_ui(self) -> None:
        d=I18N[self.language]
        self.setWindowTitle(d["window_title"]); self.main_heading.setText(d["main_heading"])
        self.source_label.setText(d["source_label"]); self.output_label.setText(d["output_label"])
        self.source_edit.setPlaceholderText(d["source_placeholder"]); self.output_edit.setPlaceholderText(d["output_placeholder"])
        self.source_browse_button.setText(f"  {d['browse']}"); self.output_browse_button.setText(f"  {d['browse']}")
        self.drop_zone.set_language(self.language); self.convert_button.setText(d["convert"]); self.cancel_button.setText(d["cancel"])
        self.progress_title.setText(d["progress"]); self.stats_title.setText(d["stats"]); self.chunks_label.setText(f"{d['chunks']}\n0 / —"); self.size_label.setText(f"{d['size']}\n0 B / —")
        self.log_title.setText(d["log"]); self.clear_log_button.setText(d["clear_log"])
        self.analyze_button.setText(d["analyze"]); self.queue_button.setText(d["queue"]); self.merge_button.setText(d["merge"]); self.report_button.setText(d["save_report"])
        self.recent_label.setText(d["recent"]); self.language_label.setText(d["language"])
        self._rebuild_recents()
        current=self.language_combo.findData(self.language)
        if current >= 0 and self.language_combo.currentIndex()!=current:
            self.language_combo.blockSignals(True); self.language_combo.setCurrentIndex(current); self.language_combo.blockSignals(False)
        self._update_speed_combo()
        self._set_status(d["status_idle"],"muted")

    def _restore_settings(self) -> None:
        input_path=str(self.settings.value("last_input", "")); output_path=str(self.settings.value("last_output", ""))
        if input_path: self.source_edit.setText(input_path)
        if output_path: self._output_manual=True; self.output_edit.setText(output_path)
        size=self.settings.value("window_size")
        try:
            if size: self.resize(size)
        except Exception: pass
        pos=self.settings.value("window_position")
        try:
            if pos: self.move(pos)
        except Exception: pass

    def _save_settings(self) -> None:
        self.settings.setValue("language",self.language); self.settings.setValue("speed_unit",self.speed_unit)
        self.settings.setValue("last_input",self.source_edit.text().strip()); self.settings.setValue("last_output",self.output_edit.text().strip())
        self.settings.setValue("recent_files",self.recent_files[:MAX_RECENT]); self.settings.setValue("window_size",self.size()); self.settings.setValue("window_position",self.pos()); self.settings.sync()

    def _language_changed(self,index:int) -> None:
        lang=self.language_combo.itemData(index)
        if lang in I18N and lang!=self.language:
            self.language=lang; self.retranslate_ui(); self.settings.setValue("language",lang)
    def _speed_unit_changed(self,index:int) -> None:
        unit=self.speed_combo.itemData(index)
        if unit in ("MB/s","MiB/s","Mbit/s"):
            self.speed_unit=unit; self.settings.setValue("speed_unit",unit)
            if self._last_progress: self._on_progress(self._last_progress)
    def _update_speed_combo(self) -> None:
        labels={"MB/s":I18N[self.language]["speed_mb"],"MiB/s":I18N[self.language]["speed_mib"],"Mbit/s":I18N[self.language]["speed_mbit"]}
        self.speed_combo.blockSignals(True)
        for i in range(self.speed_combo.count()): self.speed_combo.setItemText(i,labels[self.speed_combo.itemData(i)])
        ix=self.speed_combo.findData(self.speed_unit); self.speed_combo.setCurrentIndex(max(0,ix)); self.speed_combo.blockSignals(False)

    def add_recent(self,path:str) -> None:
        resolved=str(Path(path).expanduser().resolve())
        self.recent_files=[p for p in self.recent_files if p!=resolved]
        self.recent_files.insert(0,resolved); self.recent_files=self.recent_files[:MAX_RECENT]
        self.settings.setValue("recent_files",self.recent_files); self._rebuild_recents()
    def _rebuild_recents(self) -> None:
        if not hasattr(self,"recent_combo"): return
        self.recent_combo.blockSignals(True); self.recent_combo.clear()
        if not self.recent_files: self.recent_combo.addItem(I18N[self.language]["recent_empty"],"")
        else:
            for path in self.recent_files:
                self.recent_combo.addItem(path,path); self.recent_combo.setItemData(self.recent_combo.count()-1,path,Qt.ItemDataRole.ToolTipRole)
        self.recent_combo.setCurrentIndex(-1); self.recent_combo.blockSignals(False)
    def _recent_selected(self,index:int) -> None:
        if index<0: return
        path=self.recent_combo.itemData(index)
        if path and Path(str(path)).is_file(): self._set_source_path(str(path))

    def _update_shape_mask(self) -> None:
        w,h=self.width(),self.height()
        from PySide6.QtGui import QPolygon
        polygon=QPolygon([QPoint(60,0),QPoint(w-28,0),QPoint(w,18),QPoint(w-52,h-58),QPoint(w-20,h-22),QPoint(w-190,h),QPoint(58,h),QPoint(0,h-20),QPoint(36,int(h*.67)),QPoint(0,int(h*.47)),QPoint(35,int(h*.23))])
        self.setMask(QRegion(polygon))
    def resizeEvent(self,event) -> None:  # noqa: N802
        self._update_shape_mask(); super().resizeEvent(event)
    def paintEvent(self,event) -> None:  # noqa: N802
        painter=QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing); w,h=self.width(),self.height()
        path=QPainterPath(); pts=[QPointF(60,3),QPointF(w-30,3),QPointF(w-3,19),QPointF(w-55,h-58),QPointF(w-24,h-23),QPointF(w-190,h-3),QPointF(58,h-3),QPointF(3,h-21),QPointF(37,h*.67),QPointF(3,h*.47),QPointF(35,h*.23)]
        path.moveTo(pts[0]); [path.lineTo(pt) for pt in pts[1:]]; path.closeSubpath()
        gradient=QLinearGradient(0,0,w,h); gradient.setColorAt(0,QColor("#0b1420")); gradient.setColorAt(.48,QColor("#07111b")); gradient.setColorAt(1,QColor("#101e2b"))
        painter.fillPath(path,QBrush(gradient)); painter.setPen(QPen(QColor("#0c1721"),8)); painter.drawPath(path); painter.setPen(QPen(QColor(COLORS["yellow"]),3.2)); painter.drawPath(path)
        inner=QPainterPath(); inner_pts=[QPointF(61,13),QPointF(w-40,13),QPointF(w-22,25),QPointF(w-47,h-80),QPointF(w-25,h-34),QPointF(w-160,h-19),QPointF(57,h-19),QPointF(37,h-31),QPointF(72,h*.68),QPointF(28,h*.47),QPointF(47,h*.24)]
        inner.moveTo(inner_pts[0]); [inner.lineTo(pt) for pt in inner_pts[1:]]; inner.closeSubpath()
        painter.setPen(QPen(QColor(255,225,123,120),1)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(inner)
        painter.setPen(QPen(QColor(33,217,239,70),1)); painter.drawLine(QPointF(70,h*.31),QPointF(46,h*.38)); painter.drawLine(QPointF(46,h*.38),QPointF(46,h*.49)); painter.drawLine(QPointF(w-52,h*.33),QPointF(w-36,h*.38)); painter.drawLine(QPointF(w-36,h*.38),QPointF(w-48,h*.52))
        painter.setPen(QPen(QColor(33,217,239,140),2)); painter.drawLine(QPointF(36,h*.47),QPointF(62,h*.47)); painter.drawLine(QPointF(w-60,h*.47),QPointF(w-38,h*.47))

    def append_log(self,level:str,message:str) -> None:
        timestamp=datetime.now().strftime("%H:%M:%S"); colors={"success":COLORS["green"],"error":COLORS["red"],"warning":COLORS["amber"],"info":COLORS["cyan"]}
        # Keep detailed original exception text while translating familiar labels only.
        replacements={"Проверка заголовка":"Header validation","Обработка чанков":"Processing chunks","Преобразование завершено успешно":"Conversion completed successfully","Открытие входного файла":"Opening input file","Проверка общей контрольной суммы":"Image checksum validation","Операция отменена пользователем":"Operation cancelled by user"}
        if self.language=="en":
            for ru,en in replacements.items(): message=message.replace(ru,en)
        cursor=self.log_view.textCursor(); cursor.movePosition(QTextCursor.MoveOperation.End)
        dot=QTextCharFormat(); dot.setForeground(QColor(colors.get(level,COLORS["text"])))
        timefmt=QTextCharFormat(); timefmt.setForeground(QColor(COLORS["muted"]))
        msgfmt=QTextCharFormat(); msgfmt.setForeground(QColor(COLORS["text"]))
        cursor.insertText("● ",dot); cursor.insertText(f"[{timestamp}] ",timefmt); cursor.insertText(str(message),msgfmt); cursor.insertText("\n"); self.log_view.setTextCursor(cursor); self.log_view.ensureCursorVisible()
    def _clear_log(self) -> None: self.log_view.clear(); self.append_log("info","Log cleared." if self.language=="en" else "Журнал очищен.")
    def _browse_source(self) -> None:
        start=self.source_edit.text().strip(); start_dir=str(Path(start).expanduser().parent) if start and Path(start).exists() else str(Path.home())
        filename,_=QFileDialog.getOpenFileName(self,self.t("source_file"),start_dir,"Images and all files (*);;Android images (*.img *.sparse *.bin)")
        if filename: self._set_source_path(filename)
    def _browse_output(self) -> None:
        suggested=self.output_edit.text().strip() or (suggested_output_path(self.source_edit.text().strip()) if self.source_edit.text().strip() else str(Path.home()/"output_raw.img"))
        filename,_=QFileDialog.getSaveFileName(self,self.t("output_label"),suggested,"RAW image (*.img *.raw);;All files (*)")
        if filename: self._output_manual=True; self.output_edit.setText(filename)
    def _set_source_path(self,filename:str) -> None:
        self.source_edit.setText(filename); self.add_recent(filename); self.append_log("info",f"Input file: {filename}")
    def _source_path_changed(self,value:str) -> None:
        if not value.strip(): return
        if not self._output_manual and not self._setting_output:
            self._setting_output=True; self.output_edit.setText(suggested_output_path(value)); self._setting_output=False
        self.settings.setValue("last_input",value)
    def _output_path_changed(self,value:str) -> None:
        if not self._setting_output: self._output_manual=bool(value.strip())
        self.settings.setValue("last_output",value)
    def _set_busy(self,busy:bool) -> None:
        self.source_edit.setEnabled(not busy); self.output_edit.setEnabled(not busy); self.convert_button.setEnabled(not busy)
        self.source_browse_button.setEnabled(not busy); self.output_browse_button.setEnabled(not busy)
        self.analyze_button.setEnabled(not busy); self.queue_button.setEnabled(not busy); self.merge_button.setEnabled(not busy); self.recent_combo.setEnabled(not busy)
        self.cancel_button.setVisible(busy); self.cancel_button.setEnabled(busy and self._worker is not None)

    def operation_running(self, exclude: QDialog | None = None) -> bool:
        if self._thread is not None and self._thread.isRunning(): return True
        for dialog in getattr(self, "_dialogs", []):
            if dialog is exclude: continue
            thread = getattr(dialog, "thread", None)
            if thread is not None and thread.isRunning(): return True
        return False

    def _start_conversion(self) -> None:
        if self._thread is not None and self._thread.isRunning(): return
        if self.operation_running():
            QMessageBox.information(self, self.t("window_title"), self.t("another_operation")); return
        try: source,destination,expected_size=validate_paths(self.source_edit.text(),self.output_edit.text())
        except Exception as exc:
            self.append_log("error",f"Validation error: {type(exc).__name__}: {exc}"); self._set_status(I18N[self.language]["status_error"],"red"); QMessageBox.warning(self,self.t("window_title"),str(exc)); return
        self._expected_size=expected_size; self._total_chunks=0
        free_bytes=shutil.disk_usage(destination.parent).free
        if free_bytes<expected_size:
            question=f"Free space: {format_bytes(free_bytes,self.language)}\nExpected RAW size: {format_bytes(expected_size,self.language)}\n\nContinue anyway?"
            if QMessageBox.warning(self,"Low disk space",question,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)!=QMessageBox.StandardButton.Yes: return
        force=False
        if destination.exists():
            if QMessageBox.question(self,self.t("confirm_title"),self.t("confirm_overwrite").format(path=destination),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                self.append_log("warning","Conversion cancelled; existing output preserved."); return
            force=True
        self.last_result=None; self.report_button.setEnabled(False); self.progress_bar.setValue(0); self.progress_percent.setText("0%"); self.speed_label.setText("Preparing…" if self.language=="en" else "Подготовка…")
        self.chunks_label.setText(f"{self.t('chunks')}\n0 / reading header…"); self.size_label.setText(f"{self.t('size')}\n0 B / {format_bytes(expected_size,self.language)}"); self._set_status(I18N[self.language]["status_preparing"],"cyan")
        self.append_log("info",f"Input: {source}"); self.append_log("info",f"Output: {destination}"); self.append_log("info",f"Expected RAW size: {format_bytes(expected_size,self.language)}")
        worker=ConversionWorkerObject(source,destination,force); self._worker=worker; worker.progress.connect(self._on_progress); worker.log.connect(self.append_log); worker.succeeded.connect(self._on_success); worker.failed.connect(self._on_failure); worker.cancelled.connect(self._on_cancelled)
        thread=connect_worker(worker,self,self._on_thread_finished); self._thread=thread; self._set_busy(True); thread.start()

    @Slot(dict)
    def _on_progress(self,data:dict) -> None:
        self._last_progress=data; percent=int(data.get("percent",0)); self.progress_bar.setValue(max(0,min(100,percent))); self.progress_percent.setText(f"{percent}%")
        chunks=int(data.get("processed_chunks",0)); total=int(data.get("total_chunks",0)); self._total_chunks=total
        self.chunks_label.setText(f"{self.t('chunks')}\n{chunks:,} / {total:,}".replace(","," "))
        processed=int(data.get("processed_bytes",0)); expected=int(data.get("expected_bytes",self._expected_size)); self.size_label.setText(f"{self.t('size')}\n{format_bytes(processed,self.language)} / {format_bytes(expected,self.language)}")
        speed=float(data.get("speed_bytes_per_second",0)); self.speed_label.setText(format_speed(speed,self.speed_unit,self.language) if speed>0 else ("Preparing…" if self.language=="en" else "Подготовка…"))

    @Slot(dict)
    def _on_success(self,result:dict) -> None:
        self.last_result=result; self.report_button.setEnabled(True); size=int(result.get("output_size_bytes",result.get("raw_size_bytes",0))); expected=int(result.get("raw_size_bytes",self._expected_size)); chunks=int(result.get("total_chunks",self._total_chunks))
        old_speed = float(self._last_progress.get("speed_bytes_per_second", 0.0))
        self._last_progress = {"percent": 100, "processed_chunks": chunks, "total_chunks": chunks,
                               "processed_bytes": size, "expected_bytes": expected,
                               "speed_bytes_per_second": old_speed}
        self.progress_bar.setValue(100); self.progress_percent.setText("100%"); self.chunks_label.setText(f"{self.t('chunks')}\n{chunks:,} / {chunks:,}".replace(","," ")); self.size_label.setText(f"{self.t('size')}\n{format_bytes(size,self.language)} / {format_bytes(expected,self.language)}"); self.speed_label.setText(self.t("done"))
        destination=result.get("output") or self.output_edit.text(); self._set_status(I18N[self.language]["status_success"],"green"); self.append_log("success",f"Output verified: {destination}")
        if result.get("sha256"): self.append_log("success",f"SHA-256: {result['sha256']}")
        self.add_recent(str(self.source_edit.text()))
        QMessageBox.information(self,self.t("window_title"),f"{self.t('analysis_ok')}\n\n{destination}\n\n{format_bytes(size,self.language)}")
    @Slot(str)
    def _on_failure(self,message:str) -> None:
        self._set_status(I18N[self.language]["status_error"],"red"); self.append_log("error",f"Conversion failed: {message}")
        friendly = friendly_error(message, self.language)
        QMessageBox.critical(self,self.t("window_title"),f"{friendly}\n\nDetails: {message}\n\nThe existing destination was not replaced.")
    @Slot()
    def _on_cancelled(self) -> None: self._set_status(I18N[self.language]["status_cancelled"],"amber"); self.append_log("warning","Operation cancelled. Temporary output removed; destination was not modified.")
    @Slot()
    def _on_thread_finished(self) -> None:
        self._set_busy(False); self._worker=None; self._thread=None
        self._check_close_after_workers()

    def _check_close_after_workers(self) -> None:
        if not self._close_after_worker: return
        if self._thread is not None and self._thread.isRunning(): return
        for dialog in getattr(self, "_dialogs", []):
            thread = getattr(dialog, "thread", None)
            if thread is not None and thread.isRunning(): return
        self._close_after_worker = False
        self.close()
    @Slot()
    def _request_cancel(self) -> None:
        if self._worker: self.cancel_button.setEnabled(False); self.cancel_button.setText("Cancelling…" if self.language=="en" else "ОТМЕНА…"); self.append_log("warning","Safe cancellation requested."); self._worker.request_cancel()
    def _set_status(self,label:str,color_name:str) -> None:
        status_pairs = {
            "ОЖИДАНИЕ": "IDLE", "ПОДГОТОВКА": "PREPARING",
            "УСПЕШНО ЗАВЕРШЕНО": "COMPLETED SUCCESSFULLY",
            "ОШИБКА ПРЕОБРАЗОВАНИЯ": "CONVERSION ERROR", "ОТМЕНЕНО": "CANCELLED",
            "ОШИБКА ВХОДНЫХ ДАННЫХ": "INPUT VALIDATION ERROR",
        }
        for ru_label, en_label in status_pairs.items():
            if label in (ru_label, en_label):
                label = en_label if self.language == "en" else ru_label
                break
        self._status_label=label; self._status_color=color_name
        color=COLORS.get(color_name,COLORS["muted"]); self.status_label.setText(f"{I18N[self.language]['status']}: {label}"); self.status_label.setStyleSheet(f"color:{color};font-family:Consolas;font-size:9pt")
    def _open_analysis(self) -> None:
        dialog=AnalysisDialog(self,self.source_edit.text().strip()); dialog.show(); self._keep_dialog(dialog)
    def _open_queue(self) -> None:
        dialog=BatchQueueDialog(self); dialog.show(); self._keep_dialog(dialog)
    def _open_merge(self) -> None:
        dialog=MergeDialog(self); dialog.show(); self._keep_dialog(dialog)
    def _keep_dialog(self,dialog:QDialog) -> None:
        if not hasattr(self,"_dialogs"): self._dialogs=[]
        self._dialogs.append(dialog); dialog.finished.connect(lambda _=0,d=dialog:self._dialogs.remove(d) if d in self._dialogs else None)
    def _save_last_report(self) -> None:
        if not self.last_result: return
        default=f"{Path(str(self.last_result.get('input','image')).split(',')[0]).stem}-report.json"
        path,_=QFileDialog.getSaveFileName(self,self.t("save_report"),default,"JSON (*.json)")
        if not path: return
        payload={"application":APP_NAME,"version":APP_VERSION,"generated_at":datetime.now().astimezone().isoformat(),"result":self.last_result}
        try: Path(path).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        except OSError as exc: QMessageBox.critical(self,"Error",f"Could not save report:\n{exc}"); return
        self.append_log("success",f"Report saved: {path}"); QMessageBox.information(self,self.t("report_saved"),path)
    def dragEnterEvent(self,event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() and any(u.isLocalFile() and Path(u.toLocalFile()).is_file() for u in event.mimeData().urls()): event.acceptProposedAction()
        else: event.ignore()
    def dropEvent(self,event) -> None:  # noqa: N802
        files=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile() and Path(u.toLocalFile()).is_file()]
        if files: self._set_source_path(files[0]); event.acceptProposedAction()
        else: event.ignore()
    def closeEvent(self,event) -> None:  # noqa: N802
        active_dialogs=[d for d in getattr(self,"_dialogs",[]) if getattr(d,"thread",None) is not None and d.thread.isRunning()]
        own_active=self._thread is not None and self._thread.isRunning()
        if own_active or active_dialogs:
            answer=QMessageBox.question(self,self.t("window_title"),"A task is running. Cancel safely and close?",QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)
            if answer==QMessageBox.StandardButton.Yes:
                self._close_after_worker=True
                if own_active: self._request_cancel()
                for dialog in active_dialogs:
                    dialog._close_when_finished=True
                    if getattr(dialog,"worker",None) is not None: dialog.worker.request_cancel()
            event.ignore(); return
        self._save_settings(); event.accept()


def main(argv:list[str]|None=None)->int:
    args=list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        try:
            if QApplication.instance() is None: QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
            app=QApplication.instance() or QApplication([sys.argv[0]])
            app.setOrganizationName(ORG_NAME); app.setApplicationName(APP_NAME); app.setApplicationVersion(APP_VERSION)
            app.setWindowIcon(QIcon(str(resource_path("assets/sparse-to-raw.ico"))))
            window=MainWindow(); window.show(); app.processEvents(); window.close(); app.processEvents(); return 0
        except Exception:
            details=traceback.format_exc(); log_path=Path(os.environ.get("TEMP",tempfile.gettempdir()))/"sparse-to-raw-gui-self-test.log"
            try: log_path.write_text(details,encoding="utf-8")
            except OSError: pass
            if sys.stderr is not None: print(details,file=sys.stderr)
            return 1
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication([sys.argv[0],*args]); app.setOrganizationName(ORG_NAME); app.setApplicationName(APP_NAME); app.setApplicationVersion(APP_VERSION); app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(resource_path("assets/sparse-to-raw.ico"))))
    window=MainWindow(); window.show(); return app.exec()

if __name__=="__main__": raise SystemExit(main())
