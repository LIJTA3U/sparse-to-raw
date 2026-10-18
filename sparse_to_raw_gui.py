#!/usr/bin/env python3
"""Futuristic Windows desktop interface for the sparse-to-raw converter.

The conversion algorithm remains in ``sparse_to_raw.py``. This module only
provides the Qt user interface, input validation and thread-safe progress UI.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, Qt, QThread, Signal, Slot
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRegion,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sparse_to_raw import (
    ConversionCancelled,
    _read_declared_raw_size,
    convert_sparse_to_raw,
)

APP_VERSION = "v0.3.0-dev"

COLORS = {
    "background": "#070d16",
    "panel": "#0b1520",
    "panel_alt": "#0d1c29",
    "border": "#243a47",
    "cyan": "#21d9ef",
    "cyan_dim": "#147b91",
    "yellow": "#ffc928",
    "yellow_light": "#ffe789",
    "text": "#edf4f7",
    "muted": "#8fa4b1",
    "green": "#65e58b",
    "red": "#ff6375",
    "amber": "#ffc46b",
}


def format_bytes(value: int) -> str:
    """Human-readable binary size, using Russian-friendly unit labels."""
    units = ("Б", "КиБ", "МиБ", "ГиБ", "ТиБ", "ПиБ")
    number = float(max(0, value))
    for unit in units:
        if number < 1024 or unit == units[-1]:
            return f"{number:,.2f} {unit}".replace(",", " ")
        number /= 1024
    return f"{value} Б"


def suggested_output_path(input_path: str | Path) -> str:
    """Build ``<stem>_raw.img`` next to the selected input file."""
    source = Path(input_path).expanduser()
    return str(source.with_name(f"{source.stem}_raw.img"))


def validate_paths(input_text: str, output_text: str) -> tuple[Path, Path, int]:
    """Validate paths and estimate the logical RAW size before starting work.

    A temporary file is created and removed in the target directory as a more
    reliable write-permission check than ``os.access`` alone, especially on Windows.
    """
    if not input_text.strip():
        raise ValueError("Выбери исходный sparse-образ.")
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
        raise IsADirectoryError(f"Путь результата указывает на каталог:\n{destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Каталог для результата не найден:\n{destination.parent}")

    probe_fd = None
    probe_path: Path | None = None
    try:
        probe_fd, probe_name = tempfile.mkstemp(
            prefix=".sparse-to-raw-write-test-", dir=destination.parent
        )
        probe_path = Path(probe_name)
    except OSError as exc:
        raise PermissionError(
            f"Нет возможности записывать в каталог результата:\n{destination.parent}\n{exc}"
        ) from exc
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

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.setStyleSheet("background: transparent; border: 0; color: #10141a;")

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
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

        if not self.isEnabled():
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, QColor("#6b674e"))
            gradient.setColorAt(1, QColor("#3d3b34"))
            text_color = QColor("#a3a19a")
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            if self.isDown():
                gradient.setColorAt(0, QColor("#c38b05"))
                gradient.setColorAt(1, QColor("#f4bf21"))
            elif self.underMouse():
                gradient.setColorAt(0, QColor("#fff08e"))
                gradient.setColorAt(1, QColor("#ffca2b"))
            else:
                gradient.setColorAt(0, QColor("#ffe36d"))
                gradient.setColorAt(0.45, QColor("#ffc928"))
                gradient.setColorAt(1, QColor("#e7a909"))
            text_color = QColor("#10141a")

        painter.setPen(QPen(QColor("#ffe99a") if self.isEnabled() else QColor("#5e5843"), 1.2))
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 220, 155), 1))
        painter.drawLine(QPointF(rect.left() + cut + 8, rect.top() + 5), QPointF(rect.right() - cut - 8, rect.top() + 5))
        painter.setPen(QPen(QColor(120, 87, 8, 170), 1))
        painter.drawLine(QPointF(rect.left() + cut + 8, rect.bottom() - 5), QPointF(rect.right() - cut - 8, rect.bottom() - 5))
        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())


class DropZone(QFrame):
    fileDropped = Signal(str)
    browseRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        self.setMinimumHeight(86)
        self.setMaximumHeight(100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 14, 9)
        layout.setSpacing(15)
        self.icon = QLabel("⇩")
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setFixedWidth(58)
        self.icon.setFont(QFont("Segoe UI Symbol", 32))
        self.icon.setStyleSheet(f"color: {COLORS['cyan']}; background: transparent;")
        layout.addWidget(self.icon)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        self.title = QLabel("Перетащите файл сюда")
        self.title.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold))
        self.title.setStyleSheet(f"color: {COLORS['cyan']}; background: transparent;")
        self.subtitle = QLabel("или выберите файл вручную")
        self.subtitle.setStyleSheet(f"color: {COLORS['muted']}; background: transparent;")
        labels.addWidget(self.title)
        labels.addWidget(self.subtitle)
        layout.addLayout(labels, 1)
        self.setStyleSheet(
            f"QFrame#dropZone {{ background: #07131d; border: 1px dashed {COLORS['cyan']}; border-radius: 5px; }}"
        )

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self.browseRequested.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
            self.title.setText("Отпустите файл для выбора")
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.title.setText("Перетащите файл сюда")
        event.accept()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt override
        local_paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        files = [path for path in local_paths if Path(path).is_file()]
        if files:
            self.fileDropped.emit(files[0])
            self.title.setText("Файл выбран")
            event.acceptProposedAction()
        else:
            self.title.setText("Перетащите файл сюда")
            event.ignore()


class HeaderBar(QWidget):
    def __init__(self, version: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drag_offset: QPoint | None = None
        self.setFixedHeight(56)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 8, 0)
        layout.setSpacing(10)
        self.brand = QLabel("sparse-to-raw")
        self.brand.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.brand.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        self.brand.setStyleSheet(f"color: {COLORS['text']}; background: transparent;")
        self.version = QLabel(version)
        self.version.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.version.setFont(QFont("Consolas", 10))
        self.version.setStyleSheet(f"color: {COLORS['cyan']}; background: transparent;")
        layout.addWidget(self.brand)
        layout.addWidget(self.version)
        layout.addStretch(1)

        self.minimize_button = QPushButton("—")
        self.minimize_button.setObjectName("windowControl")
        self.minimize_button.setFixedSize(42, 32)
        self.minimize_button.setToolTip("Свернуть окно")
        self.minimize_button.clicked.connect(self.window().showMinimized)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("closeControl")
        self.close_button.setFixedSize(42, 32)
        self.close_button.setToolTip("Закрыть приложение")
        self.close_button.clicked.connect(self.window().close)
        layout.addWidget(self.minimize_button)
        layout.addWidget(self.close_button)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._drag_offset = None
        super().mouseReleaseEvent(event)


class ConversionWorkerObject(QObject):
    progress = Signal(dict)
    log = Signal(str, str)
    succeeded = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, source: Path, destination: Path, force: bool) -> None:
        super().__init__()
        self.source = source
        self.destination = destination
        self.force = force
        import threading
        self._cancel_event = threading.Event()

    @Slot()
    def run(self) -> None:
        try:
            result = convert_sparse_to_raw(
                self.source,
                self.destination,
                force=self.force,
                calculate_sha256=True,
                progress_callback=self.progress.emit,
                event_callback=self.log.emit,
                cancel_requested=self._cancel_event.is_set,
            )
        except ConversionCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.log.emit("error", f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
            self.failed.emit(str(exc))
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()

    def request_cancel(self) -> None:
        self._cancel_event.set()


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("sparse-to-raw")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAcceptDrops(True)
        self.setMinimumSize(1060, 730)
        self.resize(1360, 830)

        self._thread: QThread | None = None
        self._worker: ConversionWorkerObject | None = None
        self._output_manual = False
        self._setting_output = False
        self._close_after_worker = False
        self._expected_size = 0
        self._total_chunks = 0

        self._build_ui()
        self._apply_styles()
        self.append_log("info", "Интерфейс готов. Выберите Android Sparse Image для начала.")
        self._update_shape_mask()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(70, 8, 68, 22)
        outer.setSpacing(9)

        self.header = HeaderBar(APP_VERSION, self)
        outer.addWidget(self.header)

        separator = QFrame()
        separator.setObjectName("cyanSeparator")
        separator.setFixedHeight(2)
        outer.addWidget(separator)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(70, 0, 70, 0)
        title_row.setSpacing(18)
        left_line = QFrame()
        left_line.setObjectName("titleLine")
        left_line.setFixedHeight(2)
        title = QLabel("Преобразование образа")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Segoe UI", 19, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {COLORS['text']}; background: transparent;")
        right_line = QFrame()
        right_line.setObjectName("titleLine")
        right_line.setFixedHeight(2)
        title_row.addWidget(left_line, 1)
        title_row.addWidget(title, 0)
        title_row.addWidget(right_line, 1)
        outer.addLayout(title_row)

        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Выберите файл…")
        self.source_edit.setClearButtonEnabled(True)
        self.source_edit.setToolTip("Полный путь к исходному Android Sparse Image")
        self.source_edit.textChanged.connect(self._source_path_changed)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Путь сохранения RAW-образа…")
        self.output_edit.setClearButtonEnabled(True)
        self.output_edit.setToolTip("Полный путь к будущему RAW-образу")
        self.output_edit.textChanged.connect(self._output_path_changed)

        outer.addWidget(self._file_row("Исходный sparse-образ", self.source_edit, self._browse_source))
        outer.addWidget(self._file_row("Выходной RAW-образ", self.output_edit, self._browse_output))

        self.drop_zone = DropZone()
        self.drop_zone.fileDropped.connect(self._set_source_path)
        self.drop_zone.browseRequested.connect(self._browse_source)
        outer.addWidget(self.drop_zone)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(130, 0, 130, 0)
        action_row.setSpacing(12)
        self.convert_button = AngularButton("ПРЕОБРАЗОВАТЬ")
        self.convert_button.setToolTip("Проверить Sparse-образ и преобразовать его в RAW")
        self.convert_button.clicked.connect(self._start_conversion)
        self.cancel_button = QPushButton("ОТМЕНИТЬ")
        self.cancel_button.setObjectName("cancelButton")
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self._request_cancel)
        action_row.addWidget(self.convert_button, 1)
        action_row.addWidget(self.cancel_button, 0)
        outer.addLayout(action_row)

        progress_panel = QFrame()
        progress_panel.setObjectName("progressPanel")
        p_layout = QVBoxLayout(progress_panel)
        p_layout.setContentsMargins(14, 8, 14, 9)
        p_layout.setSpacing(7)
        progress_header = QHBoxLayout()
        self.progress_title = QLabel("Прогресс преобразования")
        self.progress_title.setStyleSheet(f"color: {COLORS['text']}; background: transparent;")
        self.progress_percent = QLabel("0%")
        self.progress_percent.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.progress_percent.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        self.progress_percent.setStyleSheet(f"color: {COLORS['cyan']}; background: transparent;")
        self.speed_label = QLabel("Ожидание")
        self.speed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.speed_label.setStyleSheet(f"color: {COLORS['muted']}; background: transparent;")
        progress_header.addWidget(self.progress_title, 1)
        progress_header.addWidget(self.speed_label, 0)
        progress_header.addSpacing(16)
        progress_header.addWidget(self.progress_percent, 0)
        p_layout.addLayout(progress_header)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(14)
        p_layout.addWidget(self.progress_bar)
        outer.addWidget(progress_panel)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        stats = QFrame()
        stats.setObjectName("infoPanel")
        stats.setMinimumWidth(285)
        stats.setMaximumWidth(360)
        stats_layout = QVBoxLayout(stats)
        stats_layout.setContentsMargins(16, 12, 16, 12)
        stats_layout.setSpacing(10)
        stats_title = QLabel("СТАТИСТИКА")
        stats_title.setObjectName("panelHeading")
        stats_layout.addWidget(stats_title)

        self.chunks_label = QLabel("Обработано чанков\n0 / —")
        self.chunks_label.setObjectName("statValue")
        self.chunks_label.setWordWrap(True)
        stats_layout.addWidget(self.chunks_label)
        split = QFrame()
        split.setObjectName("panelSeparator")
        split.setFixedHeight(1)
        stats_layout.addWidget(split)
        self.size_label = QLabel("Размер результата\n0 Б / —")
        self.size_label.setObjectName("statValue")
        self.size_label.setWordWrap(True)
        stats_layout.addWidget(self.size_label)
        self.status_label = QLabel("СТАТУС: ОЖИДАНИЕ")
        self.status_label.setObjectName("statusIdle")
        self.status_label.setWordWrap(True)
        stats_layout.addWidget(self.status_label)
        bottom.addWidget(stats, 0)

        log_panel = QFrame()
        log_panel.setObjectName("logPanel")
        log_layout = QVBoxLayout(log_panel)
        log_layout.setContentsMargins(12, 9, 12, 10)
        log_layout.setSpacing(7)
        log_header = QHBoxLayout()
        log_title = QLabel("Журнал операций")
        log_title.setObjectName("panelHeading")
        self.clear_log_button = QPushButton("Очистить журнал")
        self.clear_log_button.setObjectName("clearButton")
        self.clear_log_button.setFixedHeight(28)
        self.clear_log_button.clicked.connect(self._clear_log)
        log_header.addWidget(log_title, 1)
        log_header.addWidget(self.clear_log_button, 0)
        log_layout.addLayout(log_header)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(1500)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setPlaceholderText("Этапы обработки и сообщения проверки появятся здесь.")
        log_layout.addWidget(self.log_view, 1)
        bottom.addWidget(log_panel, 1)
        bottom.setStretch(0, 0)
        bottom.setStretch(1, 1)
        outer.addLayout(bottom, 1)

    def _file_row(self, label: str, line_edit: QLineEdit, browse_callback) -> QWidget:
        wrapper = QWidget()
        wrapper.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        field_label = QLabel(label)
        field_label.setObjectName("fieldLabel")
        layout.addWidget(field_label)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(line_edit, 1)
        browse = QPushButton("▰  Обзор")
        browse.setObjectName("browseButton")
        browse.setFixedSize(122, 38)
        browse.clicked.connect(browse_callback)
        row.addWidget(browse)
        layout.addLayout(row)
        return wrapper

    def _apply_styles(self) -> None:
        self.setStyleSheet(f"""
            QWidget {{ color: {COLORS['text']}; font-family: 'Segoe UI'; font-size: 10pt; }}
            QLineEdit {{ background: #07111b; border: 1px solid #29434f; border-radius: 4px;
                padding: 8px 10px; color: {COLORS['text']}; selection-background-color: #146b7d; }}
            QLineEdit:focus {{ border: 1px solid {COLORS['cyan']}; }}
            QLineEdit:disabled {{ color: #657580; background: #0b1219; border-color: #1c2c35; }}
            QLabel#fieldLabel {{ color: #dce8ee; font-weight: 600; background: transparent; }}
            QFrame#cyanSeparator {{ background: {COLORS['cyan']}; border: none; }}
            QFrame#titleLine {{ background: {COLORS['cyan_dim']}; border: none; }}
            QFrame#progressPanel, QFrame#infoPanel, QFrame#logPanel {{
                background: rgba(8, 19, 29, 245); border: 1px solid #243c49; border-radius: 5px; }}
            QLabel#panelHeading {{ color: {COLORS['cyan']}; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }}
            QLabel#statValue {{ color: #d5e2e8; background: transparent; line-height: 1.2; }}
            QLabel#statusIdle {{ color: {COLORS['muted']}; font-family: Consolas; font-size: 9pt; }}
            QFrame#panelSeparator {{ background: #203946; border: none; }}
            QPushButton#browseButton, QPushButton#clearButton {{
                background: #0a1b27; color: {COLORS['cyan']}; border: 1px solid #27889a; border-radius: 4px;
                padding: 5px 10px; font-weight: 600; }}
            QPushButton#browseButton:hover, QPushButton#clearButton:hover {{ background: #103140; border-color: #55f0ff; }}
            QPushButton#browseButton:pressed, QPushButton#clearButton:pressed {{ background: #06212c; }}
            QPushButton#browseButton:disabled, QPushButton#clearButton:disabled {{ color: #617681; border-color: #24343c; }}
            QPushButton#cancelButton {{ background: #3a1119; color: {COLORS['red']}; border: 1px solid #a33848;
                border-radius: 4px; padding: 8px 15px; font-weight: 700; }}
            QPushButton#cancelButton:hover {{ background: #591823; }}
            QPushButton#windowControl, QPushButton#closeControl {{ background: #0b1824; color: {COLORS['cyan']};
                border: 1px solid #243f4d; border-radius: 3px; font-size: 17pt; }}
            QPushButton#windowControl:hover {{ background: #12303c; border-color: {COLORS['cyan']}; }}
            QPushButton#closeControl:hover {{ color: #ffffff; background: #9c2436; border-color: #ff596d; }}
            QProgressBar {{ border: 1px solid #2b4b57; border-radius: 3px; background: #07111b; padding: 1px; }}
            QProgressBar::chunk {{ border-radius: 2px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #03a9b8, stop:0.5 #21d9ef, stop:1 #36bddc); }}
            QTextEdit {{ background: #050c13; color: #c1d2da; border: 1px solid #1d303b;
                border-radius: 3px; selection-background-color: #145d6d; padding: 5px; }}
            QScrollBar:vertical {{ background: #07111b; width: 10px; margin: 2px; border: none; }}
            QScrollBar::handle:vertical {{ background: #244b59; min-height: 24px; border-radius: 3px; }}
            QScrollBar::handle:vertical:hover {{ background: {COLORS['cyan_dim']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar:horizontal {{ background: #07111b; height: 10px; margin: 2px; border: none; }}
            QScrollBar::handle:horizontal {{ background: #244b59; min-width: 24px; border-radius: 3px; }}
        """)

    def _window_path(self) -> QPainterPath:
        w, h = float(self.width()), float(self.height())
        points = [
            QPointF(53, 3), QPointF(w - 33, 3), QPointF(w - 10, 20),
            QPointF(w - 36, h - 75), QPointF(w - 9, h - 28),
            QPointF(w - 155, h - 9), QPointF(52, h - 9), QPointF(25, h - 25),
            QPointF(60, h * 0.68), QPointF(15, h * 0.47), QPointF(36, h * 0.22),
        ]
        path = QPainterPath()
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        path.closeSubpath()
        return path

    def _update_shape_mask(self) -> None:
        path = self._window_path()
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._update_shape_mask()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self._window_path()
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0, QColor("#0d1723"))
        gradient.setColorAt(0.48, QColor("#07111b"))
        gradient.setColorAt(1, QColor("#101e2b"))
        painter.fillPath(path, QBrush(gradient))
        painter.setPen(QPen(QColor("#0c1721"), 8))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(COLORS["yellow"]), 3.2))
        painter.drawPath(path)

        # Inner metallic bevel and restrained circuit-like lines stay behind widgets.
        inner = QPainterPath()
        w, h = float(self.width()), float(self.height())
        inner_points = [
            QPointF(61, 13), QPointF(w - 40, 13), QPointF(w - 22, 25),
            QPointF(w - 47, h - 80), QPointF(w - 25, h - 34),
            QPointF(w - 160, h - 19), QPointF(57, h - 19), QPointF(37, h - 31),
            QPointF(72, h * 0.68), QPointF(28, h * 0.47), QPointF(47, h * 0.24),
        ]
        inner.moveTo(inner_points[0])
        for point in inner_points[1:]:
            inner.lineTo(point)
        inner.closeSubpath()
        painter.setPen(QPen(QColor(255, 225, 123, 120), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(inner)

        painter.setPen(QPen(QColor(33, 217, 239, 70), 1))
        painter.drawLine(QPointF(70, h * 0.31), QPointF(46, h * 0.38))
        painter.drawLine(QPointF(46, h * 0.38), QPointF(46, h * 0.49))
        painter.drawLine(QPointF(w - 52, h * 0.33), QPointF(w - 36, h * 0.38))
        painter.drawLine(QPointF(w - 36, h * 0.38), QPointF(w - 48, h * 0.52))
        painter.setPen(QPen(QColor(33, 217, 239, 140), 2))
        painter.drawLine(QPointF(36, h * 0.47), QPointF(62, h * 0.47))
        painter.drawLine(QPointF(w - 60, h * 0.47), QPointF(w - 38, h * 0.47))

    def append_log(self, level: str, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "success": COLORS["green"],
            "error": COLORS["red"],
            "warning": COLORS["amber"],
            "info": COLORS["cyan"],
        }
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        dot_format = QTextCharFormat()
        dot_format.setForeground(QColor(colors.get(level, COLORS["text"])))
        time_format = QTextCharFormat()
        time_format.setForeground(QColor(COLORS["muted"]))
        message_format = QTextCharFormat()
        message_format.setForeground(QColor(COLORS["text"]))
        cursor.insertText("● ", dot_format)
        cursor.insertText(f"[{timestamp}] ", time_format)
        cursor.insertText(str(message), message_format)
        cursor.insertText("\n")
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _clear_log(self) -> None:
        self.log_view.clear()
        self.append_log("info", "Журнал очищен.")

    def _browse_source(self) -> None:
        start = self.source_edit.text().strip()
        if start and Path(start).exists():
            start_dir = str(Path(start).expanduser().parent)
        else:
            start_dir = str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Выбрать Android Sparse Image",
            start_dir,
            "Образы и все файлы (*);;Образы Android (*.img *.sparse *.bin)",
        )
        if filename:
            self._set_source_path(filename)

    def _browse_output(self) -> None:
        suggested = self.output_edit.text().strip()
        if not suggested and self.source_edit.text().strip():
            suggested = suggested_output_path(self.source_edit.text().strip())
        if not suggested:
            suggested = str(Path.home() / "output_raw.img")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить RAW-образ",
            suggested,
            "RAW-образ (*.img *.raw);;Все файлы (*)",
        )
        if filename:
            self._output_manual = True
            self.output_edit.setText(filename)

    def _set_source_path(self, filename: str) -> None:
        self.source_edit.setText(filename)
        self.append_log("info", f"Выбран входной файл: {filename}")

    def _source_path_changed(self, value: str) -> None:
        if not value.strip():
            return
        if not self._output_manual and not self._setting_output:
            self._setting_output = True
            self.output_edit.setText(suggested_output_path(value))
            self._setting_output = False

    def _output_path_changed(self, value: str) -> None:
        if not self._setting_output:
            self._output_manual = bool(value.strip())

    def _set_busy(self, busy: bool) -> None:
        self.source_edit.setEnabled(not busy)
        self.output_edit.setEnabled(not busy)
        self.convert_button.setEnabled(not busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy and self._worker is not None)

    def _start_conversion(self) -> None:
        if self._thread is not None and self._thread.isRunning():
            return  # Prevent a second job, including rapid double-clicks.
        try:
            source, destination, expected_size = validate_paths(
                self.source_edit.text(), self.output_edit.text()
            )
        except Exception as exc:
            self.append_log("error", str(exc))
            self._set_status("ОШИБКА ВХОДНЫХ ДАННЫХ", "red")
            QMessageBox.warning(self, "Невозможно начать", str(exc))
            return

        self._expected_size = expected_size
        self._total_chunks = 0
        free_bytes = shutil.disk_usage(destination.parent).free
        if free_bytes < expected_size:
            message = (
                f"Свободно: {format_bytes(free_bytes)}\n"
                f"Логический размер RAW: {format_bytes(expected_size)}\n\n"
                "Области DONT_CARE иногда занимают меньше физического места, но запись может "
                "завершиться ошибкой. Продолжить?"
            )
            if QMessageBox.warning(
                self, "Мало свободного места", message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            ) != QMessageBox.StandardButton.Yes:
                self.append_log("warning", "Операция отменена до запуска из-за проверки свободного места.")
                return

        force = False
        if destination.exists():
            answer = QMessageBox.question(
                self,
                "Файл уже существует",
                f"Файл уже существует:\n{destination}\n\nЗаменить его после успешной проверки нового образа?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.append_log("warning", "Конвертация отменена: существующий выходной файл сохранён.")
                return
            force = True

        self.convert_button.setText("ПРЕОБРАЗОВАТЬ")
        self.cancel_button.setText("ОТМЕНИТЬ")
        self.progress_bar.setValue(0)
        self.progress_percent.setText("0%")
        self.speed_label.setText("Подготовка…")
        self.chunks_label.setText("Обработано чанков\n0 / чтение заголовка…")
        self.size_label.setText(f"Размер результата\n0 Б / {format_bytes(expected_size)}")
        self._set_status("ПОДГОТОВКА", "cyan")
        self.append_log("info", f"Исходный файл: {source}")
        self.append_log("info", f"Файл результата: {destination}")
        self.append_log("info", f"Ожидаемый RAW-размер: {format_bytes(expected_size)}")

        thread = QThread(self)
        worker = ConversionWorkerObject(source, destination, force)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_progress)
        worker.log.connect(self.append_log)
        worker.succeeded.connect(self._on_success)
        worker.failed.connect(self._on_failure)
        worker.cancelled.connect(self._on_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread
        self._worker = worker
        self._set_busy(True)
        thread.start()

    @Slot(dict)
    def _on_progress(self, data: dict) -> None:
        percent = int(data.get("percent", 0))
        self.progress_bar.setValue(max(0, min(100, percent)))
        self.progress_percent.setText(f"{percent}%")
        processed_chunks = int(data.get("processed_chunks", 0))
        total_chunks = int(data.get("total_chunks", 0))
        self._total_chunks = total_chunks
        self.chunks_label.setText(
            f"Обработано чанков\n{processed_chunks:,} / {total_chunks:,}".replace(",", " ")
        )
        processed_bytes = int(data.get("processed_bytes", 0))
        expected_bytes = int(data.get("expected_bytes", self._expected_size))
        self.size_label.setText(
            f"Размер результата\n{format_bytes(processed_bytes)} / {format_bytes(expected_bytes)}"
        )
        speed = float(data.get("speed_bytes_per_second", 0.0))
        self.speed_label.setText(f"{format_bytes(int(speed))}/с" if speed > 0 else "Подготовка…")

    @Slot(dict)
    def _on_success(self, result: dict) -> None:
        size = int(result.get("output_size_bytes", result.get("raw_size_bytes", 0)))
        expected = int(result.get("raw_size_bytes", self._expected_size))
        chunks = int(result.get("total_chunks", self._total_chunks))
        self.progress_bar.setValue(100)
        self.progress_percent.setText("100%")
        self.chunks_label.setText(
            f"Обработано чанков\n{chunks:,} / {chunks:,}".replace(",", " ")
        )
        self.size_label.setText(f"Размер результата\n{format_bytes(size)} / {format_bytes(expected)}")
        self.speed_label.setText("Готово")
        destination = result.get("output") or str(self.output_edit.text())
        digest = result.get("sha256")
        self._set_status("УСПЕШНО ЗАВЕРШЕНО", "green")
        self.append_log("success", f"Преобразование завершено успешно: {destination}")
        if digest:
            self.append_log("success", f"SHA-256 RAW-содержимого: {digest}")
        QMessageBox.information(
            self,
            "Преобразование завершено",
            f"RAW-образ создан и проверен.\n\n{destination}\n\nРазмер: {format_bytes(size)}",
        )

    @Slot(str)
    def _on_failure(self, message: str) -> None:
        self._set_status("ОШИБКА ПРЕОБРАЗОВАНИЯ", "red")
        self.append_log("error", f"Преобразование не выполнено: {message}")
        QMessageBox.critical(
            self,
            "Ошибка преобразования",
            f"Конвертация не завершилась успешно. Существующий результат не заменён.\n\n{message}",
        )

    @Slot()
    def _on_cancelled(self) -> None:
        self._set_status("ОТМЕНЕНО", "amber")
        self.append_log("warning", "Операция отменена. Временный файл удалён; итоговый файл не изменён.")

    @Slot()
    def _on_thread_finished(self) -> None:
        self._set_busy(False)
        self._worker = None
        self._thread = None
        if self._close_after_worker:
            self._close_after_worker = False
            self.close()

    @Slot()
    def _request_cancel(self) -> None:
        if self._worker is not None:
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("ОТМЕНА…")
            self.append_log("warning", "Запрошена безопасная отмена; ожидание ближайшей границы обработки.")
            self._worker.request_cancel()

    def _set_status(self, label: str, color_name: str) -> None:
        color = COLORS.get(color_name, COLORS["muted"])
        self.status_label.setText(f"СТАТУС: {label}")
        self.status_label.setStyleSheet(f"color: {color}; font-family: Consolas; font-size: 9pt;")

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._thread is not None and self._thread.isRunning():
            answer = QMessageBox.question(
                self,
                "Идёт преобразование",
                "Операция ещё выполняется. Безопасно отменить её и закрыть приложение?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                self._close_after_worker = True
                self._request_cancel()
            event.ignore()
            return
        event.accept()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--self-test" in args:
        # Smoke-test Qt widget creation in a bundled build; no CLI conversion is run.
        try:
            if QApplication.instance() is None:
                QApplication.setHighDpiScaleFactorRoundingPolicy(
                    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
                )
            app = QApplication.instance() or QApplication([sys.argv[0]])
            window = MainWindow()
            window.show()
            app.processEvents()
            window.close()
            app.processEvents()
            return 0
except Exception:
    details = traceback.format_exc()

    log_path = (
        Path(os.environ.get("TEMP", tempfile.gettempdir()))
        / "sparse-to-raw-gui-self-test.log"
    )

    try:
        log_path.write_text(details, encoding="utf-8")
    except OSError:
        pass

    if sys.stderr is not None:
        print(details, file=sys.stderr)

    return 1

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([sys.argv[0], *args])
    app.setApplicationName("sparse-to-raw")
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
