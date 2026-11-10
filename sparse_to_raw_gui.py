#!/usr/bin/env python3
"""Futuristic PySide6 desktop GUI for Android Sparse Image conversion.

Conversion and image validation are delegated to sparse_to_raw.py. This module
adds localization, persistent preferences, recent files, image analysis, a batch
queue, visual merge ordering, and JSON reports without changing the CLI API.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import sys
import time
import tempfile
import zipfile
import threading
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QPoint, QPointF, QRectF, QSize, QSettings, QStandardPaths, Qt, QThread, Signal, Slot, qVersion
from PySide6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
    QPen, QTextCharFormat, QTextCursor,
)
from PySide6.QtCore import QUrl
import PySide6

from diagnostics import DiagnosticStore, default_diagnostics_directory
from qfil_xml import analyze_qfil_package, build_qfil_raw_images

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
    discover_sparse_parts,
    inspect_sparse,
    merge_sparse_to_raw,
    preflight_batch,
    preflight_output,
    read_sparse_chunk_page,
    export_sparse_structure,
)

APP_VERSION = "v0.6.0-dev2"
ORG_NAME = "LIJTA3U"
APP_NAME = "sparse-to-raw"
APP_USER_MODEL_ID = "LIJTA3U.sparse-to-raw"
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
        "discover_folder": "Найти части в папке…", "discover_no_groups": "В выбранной папке не найдены файлы с шаблоном Sparsechunk.",
        "discover_choose_title": "Найдено несколько наборов", "discover_choose_prompt": "Выберите набор Sparse-частей:",
        "discover_ready_status": "ЗАГОЛОВКИ ПРОВЕРЕНЫ", "discover_check_status": "НУЖНА ПРОВЕРКА",
        "discover_not_ready": "Автоматически добавить этот набор нельзя: найдены пропуски, дубликаты или некорректные заголовки.\n\n{details}\n\nПроверьте файлы и добавьте их вручную только после проверки.",
        "discover_loaded": "Автоматически найдено и добавлено частей: {count}\nНабор: {label}\nОжидаемый RAW-размер по заголовкам: {size}\nЗаголовки проверены; полная проверка данных и CRC32 выполняется при объединении.",
        "discover_missing": "Пропущены индексы частей: {indices}", "discover_duplicates": "Повторяющиеся индексы частей: {indices}",
        "discover_header_errors": "Ошибки заголовков:\n{details}", "discover_block_sizes": "Обнаружены разные размеры блока: {sizes}",
        "discover_min_parts_issue": "Для объединения нужны минимум два независимых Sparse-файла.", "discover_unknown_issue": "Неизвестная ошибка проверки.",
        "discover_nothing_new": "Подходящий набор найден, но все его файлы уже добавлены.",
        "remove": "Удалить", "clear": "Очистить", "move_up": "Вверх", "move_down": "Вниз",
        "output_folder": "Папка назначения", "choose_folder": "Выбрать…", "run_queue": "Запустить очередь",
        "start_analysis": "Проверить образ", "start_merge": "Объединить части", "source_file": "Входной файл",
        "save_json": "Сохранить JSON…", "overwrite": "Разрешить перезапись существующих файлов",
        "queue_hint": "Файлы обрабатываются последовательно. Можно менять порядок перетаскиванием, приостанавливать очередь между файлами, отменять отдельные задания и повторять ошибки.",
        "queue_filter": "Фильтр статуса", "filter_all": "Все задания", "filter_waiting": "Ожидают",
        "filter_running": "Выполняются", "filter_success": "Успешные", "filter_failed": "Ошибки",
        "filter_cancelled": "Отменённые", "filter_skipped": "Пропущенные",
        "queue_add": "Добавить файлы…", "queue_remove": "Удалить выбранные", "queue_clear": "Очистить очередь",
        "queue_move_up": "Вверх", "queue_move_down": "Вниз", "queue_retry": "Повторить выбранные",
        "queue_skip": "Пропустить выбранные", "queue_cancel_selected": "Отменить выбранные",
        "queue_pause": "Пауза", "queue_resume": "Продолжить", "queue_pausing": "Пауза после текущего файла…",
        "queue_cancel_all": "Отменить очередь", "queue_status_waiting": "ОЖИДАНИЕ", "queue_status_running": "ВЫПОЛНЯЕТСЯ",
        "queue_status_success": "УСПЕШНО", "queue_status_failed": "ОШИБКА", "queue_status_cancelled": "ОТМЕНЕНО",
        "queue_status_skipped": "ПРОПУЩЕНО", "queue_status_cancel_requested": "ОТМЕНА ЗАПРОШЕНА",
        "queue_status_skip_requested": "ПРОПУСК ЗАПРОШЕН",
        "queue_summary": "Всего: {total} · Ожидают: {waiting} · Выполняются: {running} · Выполнено: {success} · Ошибки: {failed} · Отменено: {cancelled} · Пропущено: {skipped}",
        "queue_retry_hint": "Повторно запускаются только выбранные задания со статусом «Ошибка», «Отменено» или «Пропущено».",
        "queue_no_retry": "Выберите задания со статусом «Ошибка», «Отменено» или «Пропущено».",
        "queue_pause_hint": "Пауза применяется между файлами. Текущая конвертация будет завершена или отменена отдельно.",
        "queue_item_cancel_requested": "Запрошена отмена задания: {path}",
        "queue_item_skip_requested": "Запрошен пропуск задания: {path}",
        "queue_paused_log": "Очередь приостановлена между заданиями.", "queue_resumed_log": "Очередь продолжена.",
        "merge_hint": "Добавьте независимые Sparse-файлы вручную или найдите набор в папке. Каждый файл должен иметь собственный заголовок.",
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
        "verify_output": "Проверять RAW после записи (дополнительное чтение)",
        "verify_output_tooltip": "Повторно прочитать временный RAW и сравнить размер и SHA-256 с ожидаемым логическим содержимым. Увеличивает объём чтения с диска.",
        "verify_progress": "Проверка записанного RAW",
        "verify_passed": "Проверка записанного RAW пройдена",
        "structure_button": "Структура Sparse",
        "structure_title": "Структура Sparse-образа",
        "structure_input": "Исходный Sparse-образ",
        "structure_load": "Проверить и загрузить",
        "structure_loading": "Проверка и чтение структуры…",
        "structure_filter_type": "Тип чанка",
        "structure_all_types": "Все типы",
        "structure_search": "Поиск по индексу, смещению, размеру…",
        "structure_apply_filter": "Применить фильтр",
        "structure_previous": "Назад",
        "structure_next": "Далее",
        "structure_page": "Строки {start}–{end} из {total}",
        "structure_summary": "{format} · блок: {block_size} · блоков: {blocks} · чанков: {chunks} · RAW: {raw_size} · CRC32: {checksum}",
        "structure_col_index": "№",
        "structure_col_type": "Тип",
        "structure_col_file_offset": "Смещение файла",
        "structure_col_output_offset": "Смещение RAW",
        "structure_col_blocks": "Блоки",
        "structure_col_stored": "В файле",
        "structure_col_expanded": "После распаковки",
        "structure_col_checksum": "Контрольная сумма",
        "structure_col_status": "Проверка",
        "structure_status_ok": "Проверено",
        "structure_status_crc_ok": "CRC32 OK",
        "structure_details_title": "Сведения о выбранном чанке",
        "structure_details_empty": "Выберите чанк в таблице, чтобы посмотреть подробности.",
        "structure_export_csv": "Экспорт CSV…",
        "structure_export_json": "Экспорт JSON…",
        "structure_export_progress": "Экспорт чанков: {done} / {total}",
        "structure_export_success": "Структура экспортирована:",
        "structure_export_error": "Не удалось экспортировать структуру:",
        "structure_validation_required": "Сначала выполните полную проверку Sparse-образа.",
        "structure_source_changed": "Исходный файл изменился после проверки. Загрузите его заново.",
        "structure_cancel": "Отменить проверку",
        "structure_close": "Закрыть",
        "structure_detail_index": "Индекс чанка",
        "structure_detail_type": "Тип",
        "structure_detail_file_offset": "Смещение в файле",
        "structure_detail_payload_offset": "Смещение данных",
        "structure_detail_output_offset": "Смещение в RAW",
        "structure_detail_blocks": "Количество блоков",
        "structure_detail_stored": "Размер в Sparse",
        "structure_detail_payload": "Размер полезных данных",
        "structure_detail_expanded": "Размер в RAW",
        "structure_detail_checksum": "Значение CRC32",
        "structure_detail_fill": "Шаблон FILL",
        "log_interface_ready": "Интерфейс готов. Выберите Android Sparse-образ.",
        "log_input_file": "Входной файл: {value}",
        "log_output_file": "Выходной файл: {value}",
        "log_expected_size": "Ожидаемый размер RAW: {value}",
        "log_open_input": "Открытие входного файла: {value}",
        "log_streaming_started": "Начата потоковая обработка чанков.",
        "log_header_ok": "Проверка заголовка: OK · Android Sparse {version} · чанков: {chunks} · ожидаемый RAW: {size}",
        "log_output_saved": "Результат сохранён: {value}",
        "log_conversion_failed": "Ошибка преобразования: {value}",
        "log_validation_error": "Ошибка проверки: {value}",
        "log_preflight_failed": "Предварительная проверка не пройдена: {value}",
        "log_report_saved": "Отчёт сохранён: {value}",
        "log_cancel_requested": "Запрошена безопасная отмена.",
        "log_operation_cancelled": "Операция отменена. Временный результат удалён; существующий файл не изменён.",
        "diagnostics_button": "Диагностика",
        "diagnostics_title": "Центр диагностики",
        "diagnostics_filter_level": "Уровень",
        "diagnostics_filter_category": "Операция",
        "diagnostics_filter_period": "Период",
        "diagnostics_search": "Поиск по журналу…",
        "diagnostics_all": "Все",
        "diagnostics_level_debug": "Отладка",
        "diagnostics_level_info": "Информация",
        "diagnostics_level_success": "Успех",
        "diagnostics_level_warning": "Предупреждение",
        "diagnostics_level_error": "Ошибка",
        "diagnostics_cat_application": "Приложение",
        "diagnostics_cat_conversion": "Конвертация",
        "diagnostics_cat_analysis": "Анализ",
        "diagnostics_cat_queue": "Очередь",
        "diagnostics_cat_merge": "Объединение",
        "diagnostics_cat_preflight": "Предварительная проверка",
        "diagnostics_cat_verification": "Проверка RAW",
        "diagnostics_cat_diagnostics": "Диагностика",
        "diagnostics_cat_structure": "Структура Sparse",
        "diagnostics_period_today": "Сегодня",
        "diagnostics_period_week": "Последние 7 дней",
        "diagnostics_time": "Время",
        "diagnostics_level": "Уровень",
        "diagnostics_category": "Операция",
        "diagnostics_message": "Событие",
        "diagnostics_count": "Событий: {count}",
        "diagnostics_export": "Экспорт ZIP…",
        "diagnostics_clear": "Очистить историю…",
        "diagnostics_close": "Закрыть",
        "diagnostics_empty": "Нет событий, соответствующих фильтрам.",
        "diagnostics_exported": "Диагностический архив сохранён:",
        "diagnostics_export_failed": "Не удалось создать диагностический архив:",
        "diagnostics_clear_confirm": "Удалить локальную историю диагностики? Это действие нельзя отменить.",
        "diagnostics_privacy": "Экспорт содержит обезличенный журнал и базовые версии среды. Исходные Sparse/RAW-файлы, списки недавних файлов, переменные окружения, имя пользователя и имя компьютера не включаются. Пути профиля и похожие на секреты значения маскируются.",
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
        "discover_folder": "Find parts in folder…", "discover_no_groups": "No files matching a Sparsechunk naming pattern were found in the selected folder.",
        "discover_choose_title": "Multiple sets found", "discover_choose_prompt": "Choose a Sparse part set:",
        "discover_ready_status": "HEADERS CHECKED", "discover_check_status": "CHECK REQUIRED",
        "discover_not_ready": "This set cannot be added automatically: missing indices, duplicate indices or invalid headers were detected.\n\n{details}\n\nReview the files and add them manually only after checking them.",
        "discover_loaded": "Automatically found and added parts: {count}\nSet: {label}\nHeader-declared RAW size: {size}\nHeaders were checked; full payload and CRC32 validation will run during merge.",
        "discover_missing": "Missing part indices: {indices}", "discover_duplicates": "Duplicate part indices: {indices}",
        "discover_header_errors": "Sparse header errors:\n{details}", "discover_block_sizes": "Different block sizes were found: {sizes}",
        "discover_min_parts_issue": "At least two independent Sparse files are required.", "discover_unknown_issue": "Unknown validation issue.",
        "discover_nothing_new": "A matching set was found, but all of its files are already in the list.",
        "remove": "Remove", "clear": "Clear", "move_up": "Move up", "move_down": "Move down",
        "output_folder": "Output folder", "choose_folder": "Choose…", "run_queue": "Run queue",
        "start_analysis": "Verify image", "start_merge": "Merge parts", "source_file": "Input file",
        "save_json": "Save JSON…", "overwrite": "Allow overwriting existing files",
        "queue_hint": "Files are processed sequentially. Reorder by dragging, pause between files, cancel individual tasks, and retry failures.",
        "queue_filter": "Status filter", "filter_all": "All tasks", "filter_waiting": "Waiting",
        "filter_running": "Running", "filter_success": "Successful", "filter_failed": "Failed",
        "filter_cancelled": "Cancelled", "filter_skipped": "Skipped",
        "queue_add": "Add files…", "queue_remove": "Remove selected", "queue_clear": "Clear queue",
        "queue_move_up": "Move up", "queue_move_down": "Move down", "queue_retry": "Retry selected",
        "queue_skip": "Skip selected", "queue_cancel_selected": "Cancel selected",
        "queue_pause": "Pause", "queue_resume": "Resume", "queue_pausing": "Pausing after current file…",
        "queue_cancel_all": "Cancel queue", "queue_status_waiting": "WAITING", "queue_status_running": "RUNNING",
        "queue_status_success": "SUCCESS", "queue_status_failed": "FAILED", "queue_status_cancelled": "CANCELLED",
        "queue_status_skipped": "SKIPPED", "queue_status_cancel_requested": "CANCEL REQUESTED",
        "queue_status_skip_requested": "SKIP REQUESTED",
        "queue_summary": "Total: {total} · Waiting: {waiting} · Running: {running} · Done: {success} · Failed: {failed} · Cancelled: {cancelled} · Skipped: {skipped}",
        "queue_retry_hint": "Only selected tasks with Failed, Cancelled, or Skipped status will be retried.",
        "queue_no_retry": "Select tasks with Failed, Cancelled, or Skipped status.",
        "queue_pause_hint": "Pause takes effect between files. The current conversion will finish unless cancelled separately.",
        "queue_item_cancel_requested": "Cancellation requested for: {path}",
        "queue_item_skip_requested": "Skip requested for: {path}",
        "queue_paused_log": "Queue paused between tasks.", "queue_resumed_log": "Queue resumed.",
        "merge_hint": "Add standalone Sparse files manually or find a set in a folder. Each file must have its own header.",
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
        "verify_output": "Verify RAW after writing (additional read)",
        "verify_output_tooltip": "Re-read the staged RAW file and compare its size and SHA-256 with the expected logical contents. This adds disk I/O.",
        "verify_progress": "Verifying written RAW output",
        "verify_passed": "Written RAW verification passed",
        "structure_button": "Sparse structure",
        "structure_title": "Sparse image structure",
        "structure_input": "Input Sparse image",
        "structure_load": "Validate and load",
        "structure_loading": "Validating and reading structure…",
        "structure_filter_type": "Chunk type",
        "structure_all_types": "All types",
        "structure_search": "Search index, offset or size…",
        "structure_apply_filter": "Apply filter",
        "structure_previous": "Previous",
        "structure_next": "Next",
        "structure_page": "Rows {start}–{end} of {total}",
        "structure_summary": "{format} · block: {block_size} · blocks: {blocks} · chunks: {chunks} · RAW: {raw_size} · CRC32: {checksum}",
        "structure_col_index": "#",
        "structure_col_type": "Type",
        "structure_col_file_offset": "File offset",
        "structure_col_output_offset": "RAW offset",
        "structure_col_blocks": "Blocks",
        "structure_col_stored": "Stored",
        "structure_col_expanded": "Expanded",
        "structure_col_checksum": "Checksum",
        "structure_col_status": "Status",
        "structure_status_ok": "Verified",
        "structure_status_crc_ok": "CRC32 OK",
        "structure_details_title": "Selected chunk details",
        "structure_details_empty": "Select a chunk in the table to inspect its details.",
        "structure_export_csv": "Export CSV…",
        "structure_export_json": "Export JSON…",
        "structure_export_progress": "Exporting chunks: {done} / {total}",
        "structure_export_success": "Structure exported:",
        "structure_export_error": "Could not export structure:",
        "structure_validation_required": "Run a full Sparse image validation first.",
        "structure_source_changed": "The input file changed after validation. Load it again.",
        "structure_cancel": "Cancel validation",
        "structure_close": "Close",
        "structure_detail_index": "Chunk index",
        "structure_detail_type": "Type",
        "structure_detail_file_offset": "File offset",
        "structure_detail_payload_offset": "Payload offset",
        "structure_detail_output_offset": "RAW offset",
        "structure_detail_blocks": "Block count",
        "structure_detail_stored": "Sparse stored size",
        "structure_detail_payload": "Payload size",
        "structure_detail_expanded": "RAW expanded size",
        "structure_detail_checksum": "Stored CRC32 value",
        "structure_detail_fill": "FILL pattern",
        "log_interface_ready": "Interface ready. Choose an Android Sparse Image.",
        "log_input_file": "Input file: {value}",
        "log_output_file": "Output file: {value}",
        "log_expected_size": "Expected RAW size: {value}",
        "log_open_input": "Opening input file: {value}",
        "log_streaming_started": "Streaming chunk processing started.",
        "log_header_ok": "Header validation: OK · Android Sparse {version} · chunks: {chunks} · expected RAW: {size}",
        "log_output_saved": "Output saved: {value}",
        "log_conversion_failed": "Conversion failed: {value}",
        "log_validation_error": "Validation error: {value}",
        "log_preflight_failed": "Preflight failed: {value}",
        "log_report_saved": "Report saved: {value}",
        "log_cancel_requested": "Safe cancellation requested.",
        "log_operation_cancelled": "Operation cancelled. Temporary output removed; the existing file was not modified.",
        "diagnostics_button": "Diagnostics",
        "diagnostics_title": "Diagnostic Center",
        "diagnostics_filter_level": "Level",
        "diagnostics_filter_category": "Operation",
        "diagnostics_filter_period": "Period",
        "diagnostics_search": "Search events…",
        "diagnostics_all": "All",
        "diagnostics_level_debug": "Debug",
        "diagnostics_level_info": "Info",
        "diagnostics_level_success": "Success",
        "diagnostics_level_warning": "Warning",
        "diagnostics_level_error": "Error",
        "diagnostics_cat_application": "Application",
        "diagnostics_cat_conversion": "Conversion",
        "diagnostics_cat_analysis": "Analysis",
        "diagnostics_cat_queue": "Queue",
        "diagnostics_cat_merge": "Merge",
        "diagnostics_cat_preflight": "Preflight",
        "diagnostics_cat_verification": "RAW verification",
        "diagnostics_cat_diagnostics": "Diagnostics",
        "diagnostics_cat_structure": "Sparse structure",
        "diagnostics_period_today": "Today",
        "diagnostics_period_week": "Last 7 days",
        "diagnostics_time": "Time",
        "diagnostics_level": "Level",
        "diagnostics_category": "Operation",
        "diagnostics_message": "Event",
        "diagnostics_count": "Events: {count}",
        "diagnostics_export": "Export ZIP…",
        "diagnostics_clear": "Clear history…",
        "diagnostics_close": "Close",
        "diagnostics_empty": "No events match the selected filters.",
        "diagnostics_exported": "Diagnostic archive saved:",
        "diagnostics_export_failed": "Could not create diagnostic archive:",
        "diagnostics_clear_confirm": "Delete the local diagnostic history? This cannot be undone.",
        "diagnostics_privacy": "The export contains a sanitized event log and basic runtime versions. Sparse/RAW input files, recent-file lists, environment variables, account names, and computer names are not included. User profile paths and credential-shaped values are redacted.",
    },
}


_LOG_TRANSLATION_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^(?:Interface ready\. Choose an Android Sparse Image\.|Интерфейс готов\. Выберите Android Sparse-образ\.)$", re.I),
     "Интерфейс готов. Выберите Android Sparse-образ.", "Interface ready. Choose an Android Sparse Image."),
    (re.compile(r"^(?:Opening input file:|Открытие входного файла:)\s*(?P<value>.*)$", re.I),
     "Открытие входного файла: {value}", "Opening input file: {value}"),
    (re.compile(r"^(?:Input file:|Входной файл:)\s*(?P<value>.*)$", re.I),
     "Входной файл: {value}", "Input file: {value}"),
    (re.compile(r"^(?:Input:|Входной образ:)\s*(?P<value>.*)$", re.I),
     "Входной образ: {value}", "Input: {value}"),
    (re.compile(r"^(?:Output:|Выходной файл:)\s*(?P<value>.*)$", re.I),
     "Выходной файл: {value}", "Output: {value}"),
    (re.compile(r"^(?:Expected RAW size:|Ожидаемый размер RAW:)\s*(?P<value>.*)$", re.I),
     "Ожидаемый размер RAW: {value}", "Expected RAW size: {value}"),
    (re.compile(r"^(?:Начата потоковая обработка чанков\.|Streaming chunk processing started\.)$", re.I),
     "Начата потоковая обработка чанков.", "Streaming chunk processing started."),
    (re.compile(r"^(?:Проверка заголовка: OK|Header validation: OK)\s*·\s*Android Sparse (?P<version>[0-9.]+)\s*·\s*(?:чанков|chunks):\s*(?P<chunks>[^·]+)\s*·\s*(?:ожидаемый RAW|expected RAW):\s*(?P<size>.*)$", re.I),
     "Проверка заголовка: OK · Android Sparse {version} · чанков: {chunks} · ожидаемый RAW: {size}",
     "Header validation: OK · Android Sparse {version} · chunks: {chunks} · expected RAW: {size}"),
    (re.compile(r"^(?:Проверка CRC32 чанка|CRC32 chunk check)\s*(?P<index>\d+):\s*OK$", re.I),
     "Проверка CRC32 чанка {index}: OK", "CRC32 chunk check {index}: OK"),
    (re.compile(r"^(?:CRC32 mismatch в чанке|CRC32 mismatch in chunk)\s*(?P<index>\d+)\.?$", re.I),
     "Несовпадение CRC32 в чанке {index}.", "CRC32 mismatch in chunk {index}."),
    (re.compile(r"^(?:Итоговый размер временного RAW|Staged RAW output size):\s*(?P<value>.*)$", re.I),
     "Итоговый размер временного RAW: {value}", "Staged RAW output size: {value}"),
    (re.compile(r"^(?:Проверка числа блоков и структуры: OK|Block count and structure check: OK)\s*·\s*(?P<value>.*)$", re.I),
     "Проверка числа блоков и структуры: OK · {value}", "Block count and structure check: OK · {value}"),
    (re.compile(r"^(?:CRC32-чанков успешно проверено|CRC32 chunks successfully checked):\s*(?P<value>.*)$", re.I),
     "CRC32-чанков успешно проверено: {value}", "CRC32 chunks successfully checked: {value}"),
    (re.compile(r"^(?:Проверка общей контрольной суммы образа|Image checksum validation)\.{0,3}$", re.I),
     "Проверка общей контрольной суммы образа…", "Image checksum validation…"),
    (re.compile(r"^(?:Проверка общей контрольной суммы: OK|Image checksum validation: OK)\s*·\s*(?P<value>.*)$", re.I),
     "Проверка общей контрольной суммы: OK · {value}", "Image checksum validation: OK · {value}"),
    (re.compile(r"^(?:Общая контрольная сумма образа не совпадает\.|Image checksum mismatch\.)$", re.I),
     "Общая контрольная сумма образа не совпадает.", "Image checksum mismatch."),
    (re.compile(r"^(?:Общая контрольная сумма не задана в заголовке; проверка пропущена\.|No image checksum is present in the header; validation skipped\.)$", re.I),
     "Общая контрольная сумма не задана в заголовке; проверка пропущена.",
     "No image checksum is present in the header; validation skipped."),
    (re.compile(r"^(?:Обнаружены лишние байты после последнего чанка\.|Unexpected trailing bytes after the final chunk\.)$", re.I),
     "Обнаружены лишние байты после последнего чанка.", "Unexpected trailing bytes after the final chunk."),
    (re.compile(r"^(?:Результат сохранён:|Output saved:)\s*(?P<value>.*)$", re.I),
     "Результат сохранён: {value}", "Output saved: {value}"),
    (re.compile(r"^(?:Output saved:|Результат сохранён:)\s*(?P<value>.*)$", re.I),
     "Результат сохранён: {value}", "Output saved: {value}"),
    (re.compile(r"^(?:Re-reading staged RAW output for SHA-256 verification:|Повторное чтение временного RAW для проверки SHA-256:)\s*(?P<value>.*)$", re.I),
     "Повторное чтение временного RAW для проверки SHA-256: {value}",
     "Re-reading staged RAW output for SHA-256 verification: {value}"),
    (re.compile(r"^(?:RAW output SHA-256 does not match the logical Sparse contents\.|SHA-256 выходного RAW не совпадает с логическим содержимым Sparse\.)$", re.I),
     "SHA-256 выходного RAW не совпадает с логическим содержимым Sparse.",
     "RAW output SHA-256 does not match the logical Sparse contents."),
    (re.compile(r"^(?:RAW output verification passed:|Проверка записанного RAW пройдена:)\s*(?P<value>.*)$", re.I),
     "Проверка записанного RAW пройдена: {value}", "RAW output verification passed: {value}"),
    (re.compile(r"^(?:RAW output verification cancelled; staged output will be discarded\.|Проверка выходного RAW отменена; временный результат будет удалён\.)$", re.I),
     "Проверка выходного RAW отменена; временный результат будет удалён.",
     "RAW output verification cancelled; staged output will be discarded."),
    (re.compile(r"^(?:Merging|Объединение) (?P<count>\d+) (?:independent Sparse parts in the supplied order|независимых Sparse-частей в указанном порядке)\.$", re.I),
     "Объединение {count} независимых Sparse-частей в указанном порядке.",
     "Merging {count} independent Sparse parts in the supplied order."),
    (re.compile(r"^(?:Part|Часть) (?P<index>\d+)/(?P<total>\d+): (?:validating|проверка) (?P<name>.*)$", re.I),
     "Часть {index}/{total}: проверка {name}", "Part {index}/{total}: validating {name}"),
    (re.compile(r"^(?:Verifying the completed merged RAW staging file before commit\.|Проверка временного объединённого RAW перед сохранением\.)$", re.I),
     "Проверка временного объединённого RAW перед сохранением.",
     "Verifying the completed merged RAW staging file before commit."),
    (re.compile(r"^(?:Merge cancelled; temporary outputs will be removed\.|Объединение отменено; временные файлы будут удалены\.)$", re.I),
     "Объединение отменено; временные файлы будут удалены.",
     "Merge cancelled; temporary outputs will be removed."),
    (re.compile(r"^(?:Validation error:|Ошибка проверки:)\s*(?P<value>.*)$", re.I),
     "Ошибка проверки: {value}", "Validation error: {value}"),
    (re.compile(r"^(?:Preflight failed:|Предварительная проверка не пройдена:)\s*(?P<value>.*)$", re.I),
     "Предварительная проверка не пройдена: {value}", "Preflight failed: {value}"),
    (re.compile(r"^Preflight passed: (?P<free>.+) free; (?P<required>.+) required including merge staging and safety margin\.$", re.I),
     "Предварительная проверка пройдена: свободно {free}; требуется {required} с учётом временного файла и запаса.",
     "Preflight passed: {free} free; {required} required including merge staging and safety margin."),
    (re.compile(r"^(?:Проверка образа завершена успешно; выходной файл не создавался\.|Image inspection completed successfully; no output file was created\.)$", re.I),
     "Проверка образа завершена успешно; выходной файл не создавался.",
     "Image inspection completed successfully; no output file was created."),
    (re.compile(r"^(?:Conversion failed:|Ошибка преобразования:)\s*(?P<value>.*)$", re.I),
     "Ошибка преобразования: {value}", "Conversion failed: {value}"),
    (re.compile(r"^(?:Safe cancellation requested\.|Запрошена безопасная отмена\.)$", re.I),
     "Запрошена безопасная отмена.", "Safe cancellation requested."),
    (re.compile(r"^(?:Отмена запрошена; временный результат будет удалён\.|Cancellation requested; the temporary output will be removed\.)$", re.I),
     "Отмена запрошена; временный результат будет удалён.",
     "Cancellation requested; the temporary output will be removed."),
    (re.compile(r"^(?:Operation cancelled\. Temporary output removed; the existing file was not modified\.|Операция отменена\. Временный результат удалён; существующий файл не изменён\.)$", re.I),
     "Операция отменена. Временный результат удалён; существующий файл не изменён.",
     "Operation cancelled. Temporary output removed; the existing file was not modified."),
    (re.compile(r"^(?:Report saved:|Отчёт сохранён:)\s*(?P<value>.*)$", re.I),
     "Отчёт сохранён: {value}", "Report saved: {value}"),
    (re.compile(r"^(?:Logical RAW SHA-256:|SHA-256 логического RAW:)\s*(?P<value>.*)$", re.I),
     "SHA-256 логического RAW: {value}", "Logical RAW SHA-256: {value}"),
    (re.compile(r"^(?:Verified output SHA-256:|SHA-256 проверенного RAW:)\s*(?P<value>.*)$", re.I),
     "SHA-256 проверенного RAW: {value}", "Verified output SHA-256: {value}"),
    (re.compile(r"^(?:Diagnostic ZIP exported:|Диагностический ZIP экспортирован:)\s*(?P<value>.*)$", re.I),
     "Диагностический ZIP экспортирован: {value}", "Diagnostic ZIP exported: {value}"),
    (re.compile(r"^(?:Diagnostic history cleared\.|История диагностики очищена\.)$", re.I),
     "История диагностики очищена.", "Diagnostic history cleared."),
    (re.compile(r"^(?:Log cleared\.|Журнал очищен\.)$", re.I),
     "Журнал очищен.", "Log cleared."),
    (re.compile(r"^Batch started: (?P<total>\d+) file\(s\)\.$", re.I),
     "Пакетная обработка начата. Файлов: {total}.", "Batch started: {total} file(s)."),
    (re.compile(r"^Batch preflight passed: (?P<free>.+) free; (?P<required>.+) required including safety margin\.$", re.I),
     "Предварительная проверка очереди пройдена: свободно {free}; требуется {required} с учётом запаса.",
     "Batch preflight passed: {free} free; {required} required including safety margin."),
    (re.compile(r"^Batch preflight failed; no files were converted: (?P<value>.*)$", re.I),
     "Предварительная проверка очереди не пройдена; файлы не преобразованы: {value}",
     "Batch preflight failed; no files were converted: {value}"),
    (re.compile(r"^\[(?P<index>\d+)/(?P<total>\d+)\] Skipped: (?P<value>.*)$", re.I),
     "[{index}/{total}] Пропущено: {value}", "[{index}/{total}] Skipped: {value}"),
    (re.compile(r"^\[(?P<index>\d+)/(?P<total>\d+)\] Cancelled before start: (?P<value>.*)$", re.I),
     "[{index}/{total}] Отменено до начала: {value}", "[{index}/{total}] Cancelled before start: {value}"),
    (re.compile(r"^\[(?P<index>\d+)/(?P<total>\d+)\] Cancelled: (?P<value>.*)$", re.I),
     "[{index}/{total}] Отменено: {value}", "[{index}/{total}] Cancelled: {value}"),
    (re.compile(r"^\[(?P<index>\d+)/(?P<total>\d+)\] Completed: (?P<value>.*)$", re.I),
     "[{index}/{total}] Завершено: {value}", "[{index}/{total}] Completed: {value}"),
    (re.compile(r"^\[(?P<index>\d+)/(?P<total>\d+)\] Failed: (?P<value>[^\n]+)(?:\n(?P<details>.*))?$", re.I),
     "[{index}/{total}] Ошибка: {value}{details}", "[{index}/{total}] Failed: {value}{details}"),
    (re.compile(r"^Batch report saved: (?P<value>.*)$", re.I),
     "Отчёт пакетной обработки сохранён: {value}", "Batch report saved: {value}"),
    (re.compile(r"^Could not save batch JSON report: (?P<value>.*)$", re.I),
     "Не удалось сохранить JSON-отчёт пакетной обработки: {value}", "Could not save batch JSON report: {value}"),
    (re.compile(r"^Analysis failed: (?P<value>.*)$", re.I),
     "Ошибка анализа: {value}", "Analysis failed: {value}"),
    (re.compile(r"^Sparse structure loaded: (?P<count>\d+) chunk\(s\)$", re.I),
     "Структура Sparse загружена. Чанков: {count}.", "Sparse structure loaded: {count} chunk(s)"),
    (re.compile(r"^Sparse structure scan failed: (?P<value>.*)$", re.I),
     "Не удалось прочитать структуру Sparse: {value}", "Sparse structure scan failed: {value}"),
    (re.compile(r"^Sparse structure scan cancelled\.$", re.I),
     "Чтение структуры Sparse отменено.", "Sparse structure scan cancelled."),
    (re.compile(r"^Sparse structure export failed: (?P<value>.*)$", re.I),
     "Не удалось экспортировать структуру Sparse: {value}", "Sparse structure export failed: {value}"),
    (re.compile(r"^Sparse structure exported: (?P<value>.*)$", re.I),
     "Структура Sparse экспортирована: {value}", "Sparse structure exported: {value}"),
    (re.compile(r"^Diagnostic ZIP export failed: (?P<value>.*)$", re.I),
     "Не удалось экспортировать диагностический ZIP: {value}", "Diagnostic ZIP export failed: {value}"),
    (re.compile(r"^Diagnostic ZIP exported: (?P<value>.*)$", re.I),
     "Диагностический ZIP экспортирован: {value}", "Diagnostic ZIP exported: {value}"),
    (re.compile(r"^Input file: (?P<value>.*)$", re.I),
     "Входной файл: {value}", "Input file: {value}"),
    (re.compile(r"^Output file: (?P<value>.*)$", re.I),
     "Выходной файл: {value}", "Output file: {value}"),
    (re.compile(r"^Input: (?P<value>.*)$", re.I),
     "Входной образ: {value}", "Input: {value}"),
    (re.compile(r"^Output: (?P<value>.*)$", re.I),
     "Выходной файл: {value}", "Output: {value}"),
    (re.compile(r"^Expected RAW size: (?P<value>.*)$", re.I),
     "Ожидаемый размер RAW: {value}", "Expected RAW size: {value}"),
    (re.compile(r"^Logical RAW SHA-256: (?P<value>.*)$", re.I),
     "SHA-256 логического RAW: {value}", "Logical RAW SHA-256: {value}"),
    (re.compile(r"^Verified output SHA-256: (?P<value>.*)$", re.I),
     "SHA-256 проверенного RAW: {value}", "Verified output SHA-256: {value}"),
    (re.compile(r"^Conversion cancelled; existing output preserved\.$", re.I),
     "Конвертация отменена; существующий выходной файл сохранён.", "Conversion cancelled; existing output preserved."),
    (re.compile(r"^Operation cancelled\. Temporary output removed; destination was not modified\.$", re.I),
     "Операция отменена. Временный файл удалён; файл назначения не изменён.",
     "Operation cancelled. Temporary output removed; destination was not modified."),
    (re.compile(r"^Safe cancellation requested\.$", re.I),
     "Запрошена безопасная отмена.", "Safe cancellation requested."),
    (re.compile(r"^Sparse structure export cancelled\.$", re.I),
     "Экспорт структуры Sparse отменён.", "Sparse structure export cancelled."),
    (re.compile(r"^(?:Queue paused between tasks\.|Очередь приостановлена между заданиями\.)$", re.I),
     "Очередь приостановлена между заданиями.", "Queue paused between tasks."),
    (re.compile(r"^(?:Queue resumed\.|Очередь продолжена\.)$", re.I),
     "Очередь продолжена.", "Queue resumed."),
    (re.compile(r"^(?:Cancellation requested for:|Запрошена отмена задания:)\s*(?P<value>.*)$", re.I),
     "Запрошена отмена задания: {value}", "Cancellation requested for: {value}"),
    (re.compile(r"^(?:Skip requested for:|Запрошен пропуск задания:)\s*(?P<value>.*)$", re.I),
     "Запрошен пропуск задания: {value}", "Skip requested for: {value}"),
    (re.compile(r"^(?:Only selected tasks with Failed, Cancelled, or Skipped status will be retried\.|Повторно запускаются только выбранные задания со статусом «Ошибка», «Отменено» или «Пропущено»\.)$", re.I),
     "Повторно запускаются только выбранные задания со статусом «Ошибка», «Отменено» или «Пропущено».",
     "Only selected tasks with Failed, Cancelled, or Skipped status will be retried."),
    (re.compile(r"^(?:Queue cancellation requested; the current file will stop at a safe boundary\.|Запрошена отмена очереди; текущая задача остановится на безопасной границе\.)$", re.I),
     "Запрошена отмена очереди; текущая задача остановится на безопасной границе.",
     "Queue cancellation requested; the current file will stop at a safe boundary."),
    (re.compile(r"^(?:Merge cancelled; staged output discarded\.|Объединение отменено; временный результат удалён\.)$", re.I),
     "Объединение отменено; временный результат удалён.", "Merge cancelled; staged output discarded."),
    (re.compile(r"^(?:Batch preflight failed:|Предварительная проверка очереди не пройдена:)\s*(?P<value>.*)$", re.I),
     "Предварительная проверка очереди не пройдена: {value}", "Batch preflight failed: {value}"),
    (re.compile(r"^(?:Merge preflight failed:|Предварительная проверка объединения не пройдена:)\s*(?P<value>.*)$", re.I),
     "Предварительная проверка объединения не пройдена: {value}", "Merge preflight failed: {value}"),
)


def localize_log_message(message: str, language: str) -> str:
    """Render known operation-log messages in the selected UI language."""
    text = str(message)
    index = 1 if language == "en" else 0
    for pattern, ru_template, en_template in _LOG_TRANSLATION_RULES:
        match = pattern.match(text)
        if match:
            template = en_template if index else ru_template
            fields = {key: (value or "") for key, value in match.groupdict().items()}
            if language != "en":
                exception_names = {
                    "FileNotFoundError": "Файл не найден",
                    "PermissionError": "Нет доступа",
                    "IsADirectoryError": "Указан каталог",
                    "FileExistsError": "Файл уже существует",
                    "ValueError": "Недопустимое значение",
                    "OSError": "Ошибка ввода-вывода",
                    "OutputVerificationError": "Ошибка проверки выходного RAW",
                    "SparseImageError": "Ошибка структуры Sparse",
                    "ConversionCancelled": "Операция отменена",
                }
                for key, value in tuple(fields.items()):
                    for english_name, russian_name in exception_names.items():
                        value = re.sub(rf"\b{re.escape(english_name)}\b", russian_name, value)
                    fields[key] = value
            try:
                return template.format(**fields)
            except (KeyError, IndexError, ValueError):
                return template
    metric_match = re.fullmatch(
        r"(?P<operation>[A-Za-z_-]+) task (?P<status>success|failed|cancelled|skipped)",
        text,
        re.I,
    )
    if metric_match and language != "en":
        operations = {
            "conversion": "Конвертация", "analysis": "Анализ", "merge": "Объединение",
            "batch": "Пакетная обработка", "queue": "Очередь", "preflight": "Предварительная проверка",
            "verification": "Проверка RAW", "diagnostics": "Диагностика",
            "structure": "Структура Sparse", "application": "Приложение",
        }
        statuses = {"success": "успешно", "failed": "с ошибкой", "cancelled": "отменено", "skipped": "пропущено"}
        operation = operations.get(metric_match.group("operation").casefold(), metric_match.group("operation"))
        status = statuses[metric_match.group("status").casefold()]
        return f"Задание: {operation} — {status}."
    return text


def set_windows_app_user_model_id() -> bool:
    """Set a stable Windows AppUserModelID so the taskbar groups the app icon correctly."""
    if sys.platform != "win32":
        return False
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        return True
    except (AttributeError, OSError, TypeError):
        return False


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
        (("insufficient free disk space", "no space left", "disk full", "not enough space"),
         "Недостаточно свободного места для операции. Освободи место или выбери другой диск.",
         "There is not enough free disk space. Free some space or choose another drive."),
        (("batch output-name collision", "would overwrite an input file"),
         "В очереди есть конфликт имён выходных файлов. Измени имена или выбери другую папку.",
         "The batch contains an output-name conflict. Rename the inputs or choose another folder."),
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


class DropZoneIcon(QWidget):
    """Crisp, scalable file/download glyph for the main drag-and-drop area."""
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(72, 72)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(33, 217, 239, 13))
        painter.drawEllipse(QRectF(3, 3, 66, 66))

        # Document outline with a folded corner.
        document = QPainterPath()
        document.moveTo(21, 10)
        document.lineTo(42, 10)
        document.lineTo(54, 22)
        document.lineTo(54, 57)
        document.quadTo(54, 61, 50, 61)
        document.lineTo(21, 61)
        document.quadTo(17, 61, 17, 57)
        document.lineTo(17, 14)
        document.quadTo(17, 10, 21, 10)
        document.closeSubpath()
        painter.setBrush(QColor(9, 31, 43, 235))
        painter.setPen(QPen(QColor(COLORS["cyan"]), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(document)

        fold = QPainterPath()
        fold.moveTo(42, 11)
        fold.lineTo(42, 20)
        fold.quadTo(42, 22, 45, 22)
        fold.lineTo(53, 22)
        painter.setPen(QPen(QColor(COLORS["cyan"]), 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(fold)

        # Down arrow and short tray line make the drop action obvious at 1x scale.
        arrow = QPainterPath()
        arrow.moveTo(35.5, 25)
        arrow.lineTo(35.5, 45)
        arrow.moveTo(27.5, 37)
        arrow.lineTo(35.5, 45)
        arrow.lineTo(43.5, 37)
        painter.setPen(QPen(QColor(COLORS["yellow"]), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(arrow)
        painter.setPen(QPen(QColor(COLORS["yellow"]), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(26, 51), QPointF(45, 51))
        painter.end()


class DropZone(QFrame):
    fileDropped = Signal(str)
    browseRequested = Signal()
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True); self.setObjectName("dropZone"); self.setMinimumHeight(96); self.setMaximumHeight(112)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self); layout.setContentsMargins(16, 10, 18, 10); layout.setSpacing(16)
        self.icon = DropZoneIcon(self)
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignVCenter)
        labels = QVBoxLayout(); labels.setSpacing(3)
        self.title = QLabel(); self.title.setFont(QFont("Segoe UI", 14, QFont.Weight.DemiBold)); self.title.setStyleSheet(f"color:{COLORS['cyan']};background:transparent")
        self.subtitle = QLabel(); self.subtitle.setStyleSheet(f"color:{COLORS['muted']};background:transparent")
        labels.addWidget(self.title); labels.addWidget(self.subtitle); labels.addStretch(1); layout.addLayout(labels, 1)
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
                 operation: str = "convert", merge_sources: list[Path] | None = None,
                 verify_output: bool = False) -> None:
        super().__init__(); self.source = source; self.destination = destination; self.force = force
        self.operation = operation; self.merge_sources = merge_sources or []
        self.verify_output = bool(verify_output); self._cancel_event = threading.Event()
    @Slot()
    def run(self) -> None:
        started_at = time.perf_counter()
        try:
            kwargs = {"progress_callback": self.progress.emit, "event_callback": self.log.emit,
                      "cancel_requested": self._cancel_event.is_set, "calculate_sha256": True}
            if self.operation == "convert":
                assert self.source is not None and self.destination is not None
                result = convert_sparse_to_raw(
                    self.source, self.destination, force=self.force,
                    verify_output=self.verify_output, **kwargs
                )
            elif self.operation == "inspect":
                assert self.source is not None
                result = inspect_sparse(self.source, mode="info", **kwargs)
            elif self.operation == "merge":
                assert self.destination is not None
                result = merge_sparse_to_raw(
                    self.merge_sources, self.destination, force=self.force,
                    verify_output=self.verify_output, **kwargs
                )
            else:
                raise ValueError(f"Unknown worker operation: {self.operation}")
        except ConversionCancelled: self.cancelled.emit()
        except Exception as exc:
            self.log.emit("error", f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}"); self.failed.emit(str(exc))
        else:
            elapsed = max(time.perf_counter() - started_at, 0.0)
            processed_bytes = int(result.get("raw_size_bytes", result.get("output_size_bytes", 0)) or 0)
            result["operation_metrics"] = {
                "operation": self.operation,
                "duration_seconds": round(elapsed, 6),
                "processed_bytes": processed_bytes,
                "output_bytes": int(result.get("output_size_bytes", 0) or 0),
                "chunks": int(result.get("total_chunks", 0) or 0),
                "average_bytes_per_second": round(processed_bytes / elapsed, 2) if elapsed > 0 else 0.0,
            }
            self.succeeded.emit(result)
        finally: self.finished.emit()
    def request_cancel(self) -> None: self._cancel_event.set()


class BatchWorkerObject(QObject):
    """Sequential batch worker with per-task control and boundary-based pause."""
    progress = Signal(dict)
    log = Signal(str, str)
    item_started = Signal(str)
    item_finished = Signal(int, dict)
    pause_changed = Signal(bool)
    finished_report = Signal(dict)
    finished = Signal()

    def __init__(self, sources: list[Path], output_dir: Path, overwrite: bool,
                 verify_output: bool = False, task_ids: list[str] | None = None) -> None:
        super().__init__()
        self.sources = list(sources)
        self.output_dir = output_dir
        self.overwrite = overwrite
        self.verify_output = bool(verify_output)
        self.task_ids = list(task_ids) if task_ids is not None else [str(i) for i in range(len(self.sources))]
        if len(self.task_ids) != len(self.sources):
            raise ValueError("task_ids must contain exactly one ID per source")

        self._cancel_event = threading.Event()
        self._control = threading.Condition()
        self._pause_requested = False
        self._is_paused = False
        self._cancelled_task_ids: set[str] = set()
        self._skipped_task_ids: set[str] = set()
        self._finished_task_ids: set[str] = set()
        self._current_task_id: str | None = None
        self._current_task_cancel: threading.Event | None = None

    def request_pause(self) -> None:
        """Pause after the current file reaches a safe completion boundary."""
        with self._control:
            if not self._cancel_event.is_set():
                self._pause_requested = True
                self._control.notify_all()

    def resume(self) -> None:
        with self._control:
            self._pause_requested = False
            self._control.notify_all()

    def is_pause_requested(self) -> bool:
        with self._control:
            return self._pause_requested

    def is_paused(self) -> bool:
        with self._control:
            return self._is_paused

    def cancel_task(self, task_id: str) -> bool:
        """Cancel one pending or active task without stopping the whole queue."""
        with self._control:
            if task_id in self._finished_task_ids:
                return False
            self._cancelled_task_ids.add(task_id)
            if task_id == self._current_task_id and self._current_task_cancel is not None:
                self._current_task_cancel.set()
            self._control.notify_all()
            return True

    def skip_task(self, task_id: str) -> bool:
        """Skip one pending task, or safely cancel the active task as skipped."""
        with self._control:
            if task_id in self._finished_task_ids:
                return False
            self._skipped_task_ids.add(task_id)
            self._cancelled_task_ids.discard(task_id)
            if task_id == self._current_task_id and self._current_task_cancel is not None:
                self._current_task_cancel.set()
            self._control.notify_all()
            return True

    def request_cancel(self) -> None:
        """Cancel the active task and all remaining tasks."""
        self._cancel_event.set()
        with self._control:
            self._pause_requested = False
            self._control.notify_all()
            if self._current_task_cancel is not None:
                self._current_task_cancel.set()

    def _wait_at_task_boundary(self) -> bool:
        """Wait for resume before starting a new task; return false on queue cancel."""
        with self._control:
            if self._pause_requested and not self._cancel_event.is_set():
                if not self._is_paused:
                    self._is_paused = True
                    self.pause_changed.emit(True)
                while self._pause_requested and not self._cancel_event.is_set():
                    self._control.wait(timeout=0.25)
                if self._is_paused:
                    self._is_paused = False
                    self.pause_changed.emit(False)
            return not self._cancel_event.is_set()

    def _emit_item_finished(self, index: int, source: Path, row: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        task_id = self.task_ids[index]
        row.setdefault("task_id", task_id)
        rows.append(row)
        with self._control:
            self._finished_task_ids.add(task_id)
            if self._current_task_id == task_id:
                self._current_task_id = None
                self._current_task_cancel = None
        self.item_finished.emit(index, row)

    @Slot()
    def run(self) -> None:
        started = datetime.now()
        rows: list[dict[str, Any]] = []
        total = len(self.sources)
        preflight_report: dict[str, Any] | None = None
        planned_outputs: dict[str, list[int]] = {}
        for i, source_item in enumerate(self.sources):
            key = str((self.output_dir / f"{source_item.stem}_raw.img").resolve()).casefold()
            planned_outputs.setdefault(key, []).append(i)
        collision_indices = {
            index for indices in planned_outputs.values() if len(indices) > 1 for index in indices
        }
        self.log.emit("info", f"Batch started: {total} file(s).")
        try:
            try:
                preflight_report = preflight_batch(
                    self.sources, self.output_dir, overwrite=self.overwrite
                )
                self.log.emit(
                    "success",
                    "Batch preflight passed: "
                    f"{format_bytes(preflight_report['available_free_bytes'], 'en')} free; "
                    f"{format_bytes(preflight_report['required_free_bytes'], 'en')} required including safety margin.",
                )
            except Exception as exc:
                message = (
                    "Batch preflight failed; no files were converted: "
                    f"{type(exc).__name__}: {exc}"
                )
                self.log.emit("error", message)
                for index, source in enumerate(self.sources):
                    row = {"input": str(source), "status": "failed", "error": message, "task_id": self.task_ids[index]}
                    self._emit_item_finished(index, source, row, rows)

            if preflight_report is not None:
                for index, source in enumerate(self.sources):
                    task_id = self.task_ids[index]
                    if not self._wait_at_task_boundary():
                        row = {"input": str(source), "status": "cancelled", "error": "Queue cancelled before start", "task_id": task_id}
                        self._emit_item_finished(index, source, row, rows)
                        continue

                    with self._control:
                        skip_before_start = task_id in self._skipped_task_ids
                        cancel_before_start = task_id in self._cancelled_task_ids
                    if skip_before_start:
                        row = {"input": str(source), "status": "skipped", "error": "Skipped before start", "task_id": task_id}
                        self.log.emit("warning", f"[{index+1}/{total}] Skipped: {source}")
                        self._emit_item_finished(index, source, row, rows)
                        continue
                    if cancel_before_start:
                        row = {"input": str(source), "status": "cancelled", "error": "Cancelled before start", "task_id": task_id}
                        self.log.emit("warning", f"[{index+1}/{total}] Cancelled before start: {source}")
                        self._emit_item_finished(index, source, row, rows)
                        continue

                    destination = self.output_dir / f"{source.stem}_raw.img"
                    self.log.emit("info", f"[{index+1}/{total}] {source}")
                    row: dict[str, Any] = {"input": str(source), "output": str(destination), "status": "failed", "task_id": task_id}
                    task_cancel = threading.Event()
                    with self._control:
                        self._current_task_id = task_id
                        self._current_task_cancel = task_cancel
                    self.item_started.emit(task_id)
                    task_started_at = time.perf_counter()
                    try:
                        if index in collision_indices:
                            raise ValueError(
                                f"Output-name collision: multiple input files map to {destination}. "
                                "Use different file names or output folders."
                            )
                        if destination.exists() and not self.overwrite:
                            raise FileExistsError(
                                f"Output exists; skipped to prevent overwrite: {destination}"
                            )

                        def per_file_progress(data: dict[str, Any], *, _idx=index, _task_id=task_id) -> None:
                            current = int(data.get("percent", 0))
                            self.progress.emit({
                                **data,
                                "queue_index": _idx,
                                "queue_total": total,
                                "queue_percent": int((_idx + current / 100) * 100 / max(total, 1)),
                                "queue_current_file": str(source),
                                "queue_task_id": _task_id,
                            })

                        def cancel_requested() -> bool:
                            return self._cancel_event.is_set() or task_cancel.is_set()

                        result = convert_sparse_to_raw(
                            source, destination, force=self.overwrite, calculate_sha256=True,
                            verify_output=self.verify_output,
                            progress_callback=per_file_progress, event_callback=self.log.emit,
                            cancel_requested=cancel_requested,
                        )
                        row.update({"status": "success", "result": result})
                        self.log.emit("success", f"[{index+1}/{total}] Completed: {destination}")
                    except ConversionCancelled:
                        with self._control:
                            skipped = task_id in self._skipped_task_ids
                        if skipped:
                            row.update({"status": "skipped", "error": "Skipped during processing"})
                            self.log.emit("warning", f"[{index+1}/{total}] Skipped: {source}")
                        else:
                            row.update({"status": "cancelled", "error": "Cancelled by user"})
                            self.log.emit("warning", f"[{index+1}/{total}] Cancelled: {source}")
                    except Exception as exc:
                        row.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
                        self.log.emit("error", f"[{index+1}/{total}] Failed: {source}\n{type(exc).__name__}: {exc}")
                    elapsed = max(time.perf_counter() - task_started_at, 0.0)
                    result_metrics = row.get("result", {}).get("operation_metrics", {}) if isinstance(row.get("result"), dict) else {}
                    successful_result = row.get("result", {}) if isinstance(row.get("result"), dict) else {}
                    processed_bytes = int(result_metrics.get("processed_bytes", successful_result.get("raw_size_bytes", 0)) or 0)
                    row["operation_metrics"] = {
                        "operation": "batch-convert",
                        "duration_seconds": round(elapsed, 6),
                        "processed_bytes": processed_bytes,
                        "output_bytes": int(result_metrics.get("output_bytes", successful_result.get("output_size_bytes", 0)) or 0),
                        "chunks": int(result_metrics.get("chunks", successful_result.get("total_chunks", 0)) or 0),
                        "average_bytes_per_second": round(processed_bytes / elapsed, 2) if elapsed > 0 else 0.0,
                    }
                    self._emit_item_finished(index, source, row, rows)

                    if self._cancel_event.is_set():
                        for later_index in range(index + 1, total):
                            later = self.sources[later_index]
                            task_id = self.task_ids[later_index]
                            with self._control:
                                skipped = task_id in self._skipped_task_ids
                                cancelled = task_id in self._cancelled_task_ids
                            status = "skipped" if skipped else "cancelled"
                            error = "Skipped before start" if skipped else "Cancelled before start"
                            row2 = {"input": str(later), "status": status, "error": error, "task_id": task_id}
                            self._emit_item_finished(later_index, later, row2, rows)
                        break

            report = {
                "application": APP_NAME,
                "version": APP_VERSION,
                "generated_at": datetime.now().astimezone().isoformat(),
                "started_at": started.astimezone().isoformat(),
                "output_directory": str(self.output_dir),
                "preflight": preflight_report,
                "summary": {
                    "total": len(self.sources),
                    "success": sum(row["status"] == "success" for row in rows),
                    "failed": sum(row["status"] == "failed" for row in rows),
                    "cancelled": sum(row["status"] == "cancelled" for row in rows),
                    "skipped": sum(row["status"] == "skipped" for row in rows),
                },
                "items": rows,
            }
            report_path = self.output_dir / f"sparse-to-raw-batch-report-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
            try:
                report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                report["report_path"] = str(report_path)
                self.log.emit("success", f"Batch report saved: {report_path}")
            except OSError as exc:
                self.log.emit("warning", f"Could not save batch JSON report: {exc}")
            self.finished_report.emit(report)
        finally:
            self.finished.emit()


def connect_worker(worker: ConversionWorkerObject, parent: QWidget, finished_callback) -> QThread:
    thread = QThread(parent); worker.moveToThread(thread); thread.started.connect(worker.run)
    worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater); thread.finished.connect(finished_callback)
    return thread


class SparseStructureWorker(QObject):
    """Validate a Sparse file once, then read one bounded page of chunk metadata."""
    progress = Signal(dict)
    log = Signal(str, str)
    loaded = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        source: Path,
        *,
        offset: int,
        limit: int,
        chunk_type: str,
        search: str,
        validate: bool,
        validated_metadata: dict[str, Any] | None = None,
        expected_signature: tuple[int, int, int] | None = None,
    ) -> None:
        super().__init__()
        self.source = source
        self.offset = offset
        self.limit = limit
        self.chunk_type = chunk_type
        self.search = search
        self.validate = validate
        self.validated_metadata = validated_metadata
        self.expected_signature = expected_signature
        self._cancel_event = threading.Event()

    @staticmethod
    def _signature(path: Path) -> tuple[int, int, int]:
        stat = path.stat()
        return (stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))

    @Slot()
    def run(self) -> None:
        try:
            if self._cancel_event.is_set():
                raise ConversionCancelled("Sparse structure scan cancelled")
            signature_before = self._signature(self.source)
            if self.validate:
                summary = inspect_sparse(
                    self.source,
                    calculate_sha256=True,
                    progress_callback=self.progress.emit,
                    event_callback=self.log.emit,
                    cancel_requested=self._cancel_event.is_set,
                )
            else:
                if self.validated_metadata is None or self.expected_signature is None:
                    raise ValueError("A successful full validation is required before paging")
                summary = self.validated_metadata
                if signature_before != self.expected_signature:
                    raise ValueError("Sparse input changed after validation; validate it again")
            signature = self._signature(self.source)
            if signature != signature_before:
                raise ValueError("Sparse input changed during validation; validate it again")
            page = read_sparse_chunk_page(
                self.source,
                offset=self.offset,
                limit=self.limit,
                chunk_type=self.chunk_type,
                search=self.search,
                cancel_requested=self._cancel_event.is_set,
            )
            if self._signature(self.source) != signature:
                raise ValueError("Sparse input changed while its structure was being read")
            self.loaded.emit({"summary": summary, "page": page, "signature": signature})
        except ConversionCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.finished.emit()

    def request_cancel(self) -> None:
        self._cancel_event.set()


class SparseStructureExportWorker(QObject):
    """Export a previously validated Sparse structure without blocking the GUI."""
    progress = Signal(dict)
    succeeded = Signal(dict)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(
        self,
        source: Path,
        destination: Path,
        selected_format: str,
        validated_metadata: dict[str, Any],
        expected_signature: tuple[int, int, int],
        force: bool,
    ) -> None:
        super().__init__()
        self.source = source
        self.destination = destination
        self.selected_format = selected_format
        self.validated_metadata = validated_metadata
        self.expected_signature = expected_signature
        self.force = force
        self._cancel_event = threading.Event()

    @staticmethod
    def _signature(path: Path) -> tuple[int, int, int]:
        stat = path.stat()
        return (stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))

    @Slot()
    def run(self) -> None:
        try:
            if self._signature(self.source) != self.expected_signature:
                raise ValueError("Sparse input changed after validation; validate it again")
            result = export_sparse_structure(
                self.source,
                self.destination,
                format=self.selected_format,
                validated_metadata=self.validated_metadata,
                force=self.force,
                cancel_requested=self._cancel_event.is_set,
                progress_callback=self.progress.emit,
            )
        except ConversionCancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.succeeded.emit(result)
        finally:
            self.finished.emit()

    def request_cancel(self) -> None:
        self._cancel_event.set()


class SparseStructureDialog(QDialog):
    """Paged, verified Sparse chunk viewer with streaming CSV/JSON export."""
    PAGE_SIZE = 200

    def __init__(self, parent: "MainWindow", initial_path: str = "") -> None:
        super().__init__(parent)
        self.main = parent
        self.thread: QThread | None = None
        self.worker: SparseStructureWorker | None = None
        self.export_thread: QThread | None = None
        self.export_worker: SparseStructureExportWorker | None = None
        self._export_target: Path | None = None
        self._close_when_finished = False
        self._validated_summary: dict[str, Any] | None = None
        self._source_signature: tuple[int, int, int] | None = None
        self._page_offset = 0
        self._page_data: dict[str, Any] | None = None
        self._visible_rows: list[dict[str, Any]] = []
        self.setWindowTitle(parent.t("structure_title"))
        self.resize(1220, 790)
        self.setModal(False)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(9)

        source_row = QHBoxLayout()
        self.input_edit = QLineEdit(initial_path)
        self.input_edit.setPlaceholderText(parent.t("structure_input"))
        self.browse_button = QPushButton(parent.t("browse"))
        self.browse_button.setIcon(parent.icon_for("SP_DialogOpenButton"))
        self.browse_button.setIconSize(QSize(parent.icon_size, parent.icon_size))
        self.load_button = QPushButton(parent.t("structure_load"))
        self.load_button.setIcon(parent.icon_for("SP_FileDialogContentsView"))
        self.load_button.setIconSize(QSize(parent.icon_size, parent.icon_size))
        self.cancel_button = QPushButton(parent.t("structure_cancel"))
        self.cancel_button.setEnabled(False)
        source_row.addWidget(self.input_edit, 1)
        source_row.addWidget(self.browse_button)
        source_row.addWidget(self.load_button)
        source_row.addWidget(self.cancel_button)
        root.addLayout(source_row)

        self.summary_label = QLabel(parent.t("structure_validation_required"))
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(f"color:{COLORS['cyan']};background:#0b1520;border:1px solid {COLORS['border']};padding:8px")
        root.addWidget(self.summary_label)

        filters = QHBoxLayout()
        self.filter_label = QLabel(parent.t("structure_filter_type"))
        filters.addWidget(self.filter_label)
        self.type_combo = QComboBox()
        for label, value in (
            (parent.t("structure_all_types"), "ALL"),
            ("RAW", "RAW"), ("FILL", "FILL"),
            ("DONT_CARE", "DONT_CARE"), ("CRC32", "CRC32"),
        ):
            self.type_combo.addItem(label, value)
        filters.addWidget(self.type_combo)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(parent.t("structure_search"))
        filters.addWidget(self.search_edit, 1)
        self.filter_button = QPushButton(parent.t("structure_apply_filter"))
        self.filter_button.setIcon(parent.icon_for("SP_FileDialogDetailedView"))
        filters.addWidget(self.filter_button)
        root.addLayout(filters)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            parent.t("structure_col_index"), parent.t("structure_col_type"),
            parent.t("structure_col_file_offset"), parent.t("structure_col_output_offset"),
            parent.t("structure_col_blocks"), parent.t("structure_col_stored"),
            parent.t("structure_col_expanded"), parent.t("structure_col_checksum"),
            parent.t("structure_col_status"),
        ])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(8, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.details_title = QLabel(parent.t("structure_details_title"))
        self.details_title.setStyleSheet(f"color:{COLORS['cyan']};font-weight:700")
        root.addWidget(self.details_title)
        self.details_view = QTextEdit()
        self.details_view.setReadOnly(True)
        self.details_view.setMaximumHeight(138)
        self.details_view.setPlaceholderText(parent.t("structure_details_empty"))
        self.details_view.setFont(QFont("Consolas", 9))
        root.addWidget(self.details_view)

        footer = QHBoxLayout()
        self.previous_button = QPushButton(parent.t("structure_previous"))
        self.next_button = QPushButton(parent.t("structure_next"))
        self.page_label = QLabel("—")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.addWidget(self.previous_button)
        footer.addStretch()
        footer.addWidget(self.page_label, 1)
        footer.addStretch()
        footer.addWidget(self.next_button)
        root.addLayout(footer)

        export_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(13)
        self.export_csv_button = QPushButton(parent.t("structure_export_csv"))
        self.export_json_button = QPushButton(parent.t("structure_export_json"))
        self.export_csv_button.setEnabled(False)
        self.export_json_button.setEnabled(False)
        close_button = QPushButton(parent.t("structure_close"))
        export_row.addWidget(self.progress, 1)
        export_row.addWidget(self.export_csv_button)
        export_row.addWidget(self.export_json_button)
        export_row.addWidget(close_button)
        root.addLayout(export_row)

        self.browse_button.clicked.connect(self._browse)
        self.load_button.clicked.connect(lambda: self._start_load(validate=True, reset_page=True))
        self.cancel_button.clicked.connect(self._cancel)
        self.filter_button.clicked.connect(self._apply_filter)
        self.search_edit.returnPressed.connect(self._apply_filter)
        self.type_combo.currentIndexChanged.connect(self._apply_filter)
        self.previous_button.clicked.connect(self._previous_page)
        self.next_button.clicked.connect(self._next_page)
        self.table.itemSelectionChanged.connect(self._show_selected_details)
        self.export_csv_button.clicked.connect(lambda: self._export("csv"))
        self.export_json_button.clicked.connect(lambda: self._export("json"))
        close_button.clicked.connect(self.close)
        self.previous_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.setStyleSheet(
            f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} "
            f"QTableWidget,QLineEdit,QComboBox,QTextEdit{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f;gridline-color:#203946}} "
            f"QHeaderView::section{{background:#0d1c29;color:{COLORS['cyan']};padding:6px;border:1px solid #243a47}} "
            f"QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:7px;border-radius:4px}} "
            f"QPushButton:disabled{{color:#526570;background:#0b1219;border-color:#1c2c35}} "
            f"QProgressBar{{background:#111d28;border:1px solid #24414e}} QProgressBar::chunk{{background:{COLORS['cyan']}}}"
        )

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self.main.t("structure_input"), self.input_edit.text() or str(Path.home()),
            "Android Sparse images (*)",
        )
        if path:
            self.input_edit.setText(path)
            self._validated_summary = None
            self._source_signature = None
            self._page_data = None
            self._visible_rows = []
            self.table.setRowCount(0)
            self.page_label.setText("—")
            self.export_csv_button.setEnabled(False)
            self.export_json_button.setEnabled(False)

    def _set_busy(self, busy: bool) -> None:
        self.input_edit.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.load_button.setEnabled(not busy)
        self.filter_button.setEnabled(not busy)
        self.type_combo.setEnabled(not busy)
        self.search_edit.setEnabled(not busy)
        self.previous_button.setEnabled(not busy and bool(self._page_data and self._page_data.get("previous_offset") is not None))
        self.next_button.setEnabled(not busy and bool(self._page_data and self._page_data.get("next_offset") is not None))
        self.cancel_button.setEnabled(busy)
        self.export_csv_button.setEnabled(not busy and self._validated_summary is not None)
        self.export_json_button.setEnabled(not busy and self._validated_summary is not None)

    def _start_load(self, *, validate: bool, reset_page: bool = False, offset: int | None = None) -> None:
        if (self.thread is not None and self.thread.isRunning()) or (self.export_thread is not None and self.export_thread.isRunning()):
            return
        if self.main.operation_running(exclude=self):
            QMessageBox.information(self, self.main.t("structure_title"), self.main.t("another_operation"))
            return
        source = Path(self.input_edit.text().strip()).expanduser().resolve()
        if not source.is_file():
            QMessageBox.warning(self, self.main.t("structure_title"), self.main.t("missing_source").format(path=source))
            return
        if reset_page:
            self._page_offset = 0
        if offset is not None:
            self._page_offset = max(0, int(offset))
        if validate:
            self._validated_summary = None
            self._source_signature = None
            self._page_data = None
            self._visible_rows = []
            self.table.setRowCount(0)
            self.export_csv_button.setEnabled(False)
            self.export_json_button.setEnabled(False)
        try:
            signature = self._file_signature(source)
        except OSError as exc:
            self._validated_summary = None
            self._source_signature = None
            self._page_data = None
            self._visible_rows = []
            self.table.setRowCount(0)
            self.export_csv_button.setEnabled(False)
            self.export_json_button.setEnabled(False)
            QMessageBox.warning(self, self.main.t("structure_title"), str(exc))
            return
        if not validate:
            if self._validated_summary is None or self._source_signature != signature:
                validate = True
                self._validated_summary = None
                self._source_signature = None
                self._page_offset = 0
        self.progress.setValue(0)
        self.summary_label.setText(self.main.t("structure_loading"))
        self._set_busy(True)
        worker = SparseStructureWorker(
            source,
            offset=self._page_offset,
            limit=self.PAGE_SIZE,
            chunk_type=str(self.type_combo.currentData() or "ALL"),
            search=self.search_edit.text(),
            validate=validate,
            validated_metadata=self._validated_summary,
            expected_signature=self._source_signature,
        )
        self.worker = worker
        worker.progress.connect(self._on_progress)
        worker.log.connect(self._on_log)
        worker.loaded.connect(self._on_loaded)
        worker.failed.connect(self._on_failed)
        worker.cancelled.connect(self._on_cancelled)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self.thread = thread
        thread.start()

    @staticmethod
    def _file_signature(path: Path) -> tuple[int, int, int]:
        stat = path.stat()
        return (stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))

    @Slot(dict)
    def _on_progress(self, data: dict[str, Any]) -> None:
        self.progress.setValue(max(0, min(100, int(data.get("percent", 0)))))

    @Slot(str, str)
    def _on_log(self, level: str, message: str) -> None:
        self.main.append_log(level, message, category="structure")

    @Slot(dict)
    def _on_loaded(self, result: dict[str, Any]) -> None:
        self._validated_summary = result["summary"]
        self._source_signature = result["signature"]
        self._page_data = result["page"]
        self._render_page()
        self.progress.setValue(100)
        self.export_csv_button.setEnabled(True)
        self.export_json_button.setEnabled(True)
        self.main.append_log(
            "success",
            f"Sparse structure loaded: {self._validated_summary.get('total_chunks', 0)} chunk(s)",
            category="structure",
            details={"chunks": int(self._validated_summary.get("total_chunks", 0)), "block_size": int(self._validated_summary.get("block_size", 0))},
        )

    def _render_page(self) -> None:
        if not self._page_data or not self._validated_summary:
            return
        header = self._page_data["header"]
        summary = self._validated_summary
        self.summary_label.setText(self.main.t("structure_summary").format(
            format=header["format"],
            block_size=format_bytes(int(header["block_size"]), self.main.language),
            blocks=f"{int(header['total_blocks']):,}".replace(",", " "),
            chunks=f"{int(header['total_chunks']):,}".replace(",", " "),
            raw_size=format_bytes(int(header["raw_size_bytes"]), self.main.language),
            checksum=summary.get("computed_crc32", header.get("header_checksum", "—")),
        ))
        rows = self._page_data["rows"]
        self._visible_rows = rows
        self.table.setRowCount(len(rows))
        for row_index, record in enumerate(rows):
            status = self.main.t("structure_status_crc_ok") if record["type"] == "CRC32" else self.main.t("structure_status_ok")
            values = (
                str(int(record["index"]) + 1),
                str(record["type"]),
                str(record["file_offset_hex"]),
                str(record["output_offset_hex"]),
                str(record["block_count"]),
                format_bytes(int(record["stored_size_bytes"]), self.main.language),
                format_bytes(int(record["expanded_size_bytes"]), self.main.language),
                str(record["checksum"] or "—"),
                status,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 8:
                    item.setForeground(QColor(COLORS["green"]))
                self.table.setItem(row_index, column, item)
        offset = int(self._page_data["offset"])
        total = int(self._page_data["total_matches"])
        start = offset + 1 if total else 0
        end = min(offset + len(rows), total)
        self.page_label.setText(self.main.t("structure_page").format(start=start, end=end, total=total))
        self.previous_button.setEnabled(offset > 0)
        self.next_button.setEnabled(self._page_data.get("next_offset") is not None)
        self.details_view.clear()
        self.details_view.setPlaceholderText(self.main.t("structure_details_empty"))
        if rows:
            self.table.selectRow(0)

    def _show_selected_details(self) -> None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            self.details_view.clear()
            return
        row = selected[0].row()
        if row < 0 or row >= len(self._visible_rows):
            return
        record = self._visible_rows[row]
        lines = [
            f"{self.main.t('structure_detail_index')}: {int(record['index']) + 1}",
            f"{self.main.t('structure_detail_type')}: {record['type']} ({record['type_code']})",
            f"{self.main.t('structure_detail_file_offset')}: {record['file_offset_hex']} ({record['file_offset']:,} B)",
            f"{self.main.t('structure_detail_payload_offset')}: 0x{int(record['payload_offset']):X}",
            f"{self.main.t('structure_detail_output_offset')}: {record['output_offset_hex']}",
            f"{self.main.t('structure_detail_blocks')}: {record['block_count']}",
            f"{self.main.t('structure_detail_stored')}: {format_bytes(int(record['stored_size_bytes']), self.main.language)}",
            f"{self.main.t('structure_detail_payload')}: {format_bytes(int(record['payload_size_bytes']), self.main.language)}",
            f"{self.main.t('structure_detail_expanded')}: {format_bytes(int(record['expanded_size_bytes']), self.main.language)}",
        ]
        if record.get("checksum"):
            lines.append(f"{self.main.t('structure_detail_checksum')}: {record['checksum']}")
        if record.get("fill_pattern"):
            lines.append(f"{self.main.t('structure_detail_fill')}: {record['fill_pattern']}")
        self.details_view.setPlainText("\n".join(lines))

    def _apply_filter(self, *_args) -> None:
        self._start_load(validate=False, reset_page=True)

    def _previous_page(self) -> None:
        if self._page_data and self._page_data.get("previous_offset") is not None:
            self._start_load(validate=False, offset=int(self._page_data["previous_offset"]))

    def _next_page(self) -> None:
        if self._page_data and self._page_data.get("next_offset") is not None:
            self._start_load(validate=False, offset=int(self._page_data["next_offset"]))

    def _cancel(self) -> None:
        if self.worker is not None:
            self.worker.request_cancel()
            self.cancel_button.setEnabled(False)
        if self.export_worker is not None:
            self.export_worker.request_cancel()
            self.cancel_button.setEnabled(False)

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self.summary_label.setText(f"{self.main.t('status_error')}: {friendly_error(message, self.main.language)}")
        self.main.append_log("error", f"Sparse structure scan failed: {message}", category="structure")
        QMessageBox.warning(self, self.main.t("structure_title"), f"{friendly_error(message, self.main.language)}\n\n{message}")

    @Slot()
    def _on_cancelled(self) -> None:
        self.summary_label.setText(self.main.t("status_cancelled"))
        self.main.append_log("warning", "Sparse structure scan cancelled.", category="structure")

    @Slot()
    def _thread_finished(self) -> None:
        self.thread = None
        self.worker = None
        self._set_busy(False)
        if self._close_when_finished:
            self.close()
        self.main._check_close_after_workers()

    def _export(self, selected_format: str) -> None:
        if self._validated_summary is None or self._source_signature is None:
            QMessageBox.information(self, self.main.t("structure_title"), self.main.t("structure_validation_required"))
            return
        if (self.export_thread is not None and self.export_thread.isRunning()) or (self.thread is not None and self.thread.isRunning()):
            return
        source = Path(self.input_edit.text().strip()).expanduser().resolve()
        try:
            if self._file_signature(source) != self._source_signature:
                raise ValueError(self.main.t("structure_source_changed"))
        except OSError as exc:
            QMessageBox.warning(self, self.main.t("structure_title"), str(exc))
            return
        suffix = selected_format
        default = f"{source.stem}-structure.{suffix}"
        filename, _ = QFileDialog.getSaveFileName(
            self, self.main.t("structure_export_json" if suffix == "json" else "structure_export_csv"),
            default, "JSON (*.json)" if suffix == "json" else "CSV (*.csv)",
        )
        if not filename:
            return
        target = Path(filename).expanduser().resolve()
        if target.suffix.casefold() != f".{suffix}":
            target = target.with_suffix(f".{suffix}")
        force = False
        if target.exists():
            answer = QMessageBox.question(
                self, self.main.t("structure_title"), self.main.t("confirm_overwrite").format(path=target),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            force = True

        self._export_target = target
        self.progress.setValue(0)
        self.page_label.setText(self.main.t("structure_export_progress").format(done=0, total=self._validated_summary.get("total_chunks", 0)))
        self._set_busy(True)
        worker = SparseStructureExportWorker(
            source, target, suffix, self._validated_summary, self._source_signature, force
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_export_progress)
        worker.succeeded.connect(self._on_export_succeeded)
        worker.failed.connect(self._on_export_failed)
        worker.cancelled.connect(self._on_export_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._export_thread_finished)
        self.export_worker = worker
        self.export_thread = thread
        thread.start()

    @Slot(dict)
    def _on_export_progress(self, data: dict[str, Any]) -> None:
        done = int(data.get("chunks_exported", 0))
        total = int(data.get("total_chunks", 0))
        self.progress.setValue(max(0, min(100, int(data.get("percent", 0)))))
        self.page_label.setText(self.main.t("structure_export_progress").format(done=done, total=total))

    @Slot(dict)
    def _on_export_succeeded(self, result: dict[str, Any]) -> None:
        self.progress.setValue(100)
        target = Path(str(result.get("output", self._export_target or "")))
        self.main.append_log(
            "success", f"Sparse structure exported: {target.name}", category="structure",
            details={"format": result.get("format"), "chunks": result.get("chunks_exported")},
        )
        QMessageBox.information(
            self, self.main.t("structure_title"),
            f"{self.main.t('structure_export_success')}\n{target}",
        )

    @Slot(str)
    def _on_export_failed(self, message: str) -> None:
        self.main.append_log("error", f"Sparse structure export failed: {message}", category="structure")
        QMessageBox.critical(
            self, self.main.t("structure_title"),
            f"{self.main.t('structure_export_error')}\n{friendly_error(message, self.main.language)}\n\n{message}",
        )

    @Slot()
    def _on_export_cancelled(self) -> None:
        self.main.append_log("warning", "Sparse structure export cancelled.", category="structure")
        self.page_label.setText(self.main.t("structure_cancel"))

    @Slot()
    def _export_thread_finished(self) -> None:
        self.export_thread = None
        self.export_worker = None
        self._set_busy(False)
        if self._close_when_finished:
            self.close()
        self.main._check_close_after_workers()

    def closeEvent(self, event) -> None:  # noqa: N802
        scan_running = self.thread is not None and self.thread.isRunning()
        export_running = self.export_thread is not None and self.export_thread.isRunning()
        if scan_running or export_running:
            self._close_when_finished = True
            if self.worker is not None:
                self.worker.request_cancel()
            if self.export_worker is not None:
                self.export_worker.request_cancel()
            event.ignore()
            return
        event.accept()


class AnalysisDialog(QDialog):
    def __init__(self, parent: "MainWindow", initial_path: str = "") -> None:
        super().__init__(parent); self.main = parent; self.result: dict[str, Any] | None = None
        self.thread: QThread | None = None; self.worker: ConversionWorkerObject | None = None; self._close_when_finished = False
        self.setWindowTitle(parent.t("analyze_title")); self.resize(760, 560); self.setModal(False)
        layout = QVBoxLayout(self); form = QHBoxLayout()
        self.input_edit = QLineEdit(initial_path); self.input_edit.setPlaceholderText(parent.t("source_placeholder")); form.addWidget(self.input_edit, 1)
        browse = QPushButton(parent.t("browse")); browse.setIcon(parent.icon_for("SP_DialogOpenButton")); browse.setIconSize(QSize(parent.icon_size, parent.icon_size)); form.addWidget(browse)
        browse.clicked.connect(self._browse); layout.addLayout(form)
        self.analyze_button = QPushButton(parent.t("start_analysis")); self.analyze_button.setIcon(parent.icon_for("SP_FileDialogContentsView")); self.analyze_button.setIconSize(QSize(parent.icon_size, parent.icon_size)); layout.addWidget(self.analyze_button)
        self.progress = QProgressBar(); self.progress.setRange(0,100); layout.addWidget(self.progress)
        self.output = QTextEdit(); self.output.setReadOnly(True); self.output.setFont(QFont("Consolas", 9)); self.output.setPlaceholderText(parent.t("analysis_ready")); layout.addWidget(self.output, 1)
        self.save_button = QPushButton(parent.t("save_json")); self.save_button.setIcon(parent.icon_for("SP_DialogSaveButton")); self.save_button.setIconSize(QSize(parent.icon_size, parent.icon_size)); self.save_button.setEnabled(False)
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
    def _log(self, level: str, message: str) -> None:
        self.output.append(f"[{level.upper()}] {localize_log_message(message, self.main.language)}")
        self.main.append_log(level, message, category="analysis")
    def _success(self, result: dict) -> None:
        self.result = result; self.progress.setValue(100); self.save_button.setEnabled(True)
        self.main.record_operation_metrics("analysis", "success", result.get("operation_metrics", {}), source=Path(str(result.get("input", "image"))).name)
        self.output.append("\n" + json.dumps(result, ensure_ascii=False, indent=2))
    def _failure(self, message: str) -> None:
        self.output.append(f"\n{self.main.t('status_error')}: {friendly_error(message, self.main.language)}\nDetails: {message}")
        self.main.append_log("error", f"Analysis failed: {message}", category="analysis")
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


class QFILDialog(QDialog):
    """GUI for inspecting QFIL manifests and assembling RAW images; never flashes devices."""
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main = parent
        self.rawprograms: list[str] = []
        self.patches: list[str] = []
        self.setWindowTitle("QFIL XML — " + ("Manifest tools" if parent.language == "en" else "Работа с манифестами"))
        self.resize(900, 680)
        root = QVBoxLayout(self)
        intro = QLabel("Inspect rawprogram/patch XML and reconstruct partition RAW images. Patch commands are reported, not executed. This tool does not flash devices." if parent.language == "en" else "Анализ rawprogram/patch XML и сборка RAW-образов разделов. Команды patch только анализируются и не выполняются. Программа не прошивает устройства.")
        intro.setWordWrap(True); root.addWidget(intro)
        self.raw_label = QLabel("Rawprogram XML: —"); root.addWidget(self.raw_label)
        row = QHBoxLayout(); add_raw = QPushButton("Add rawprogram XML…" if parent.language == "en" else "Добавить rawprogram XML…")
        add_raw.clicked.connect(self._add_raw); clear_raw = QPushButton("Clear" if parent.language == "en" else "Очистить"); clear_raw.clicked.connect(lambda: self._set_raw([])); row.addWidget(add_raw); row.addWidget(clear_raw); root.addLayout(row)
        self.patch_label = QLabel("Patch XML: —"); root.addWidget(self.patch_label)
        row = QHBoxLayout(); add_patch = QPushButton("Add patch XML…" if parent.language == "en" else "Добавить patch XML…"); add_patch.clicked.connect(self._add_patch); clear_patch = QPushButton("Clear" if parent.language == "en" else "Очистить"); clear_patch.clicked.connect(lambda: self._set_patch([])); row.addWidget(add_patch); row.addWidget(clear_patch); root.addLayout(row)
        form = QFormLayout()
        self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText("Optional firmware folder" if parent.language == "en" else "Необязательная папка с прошивкой")
        search_row = QHBoxLayout(); search_row.addWidget(self.search_edit, 1); browse_search = QPushButton("Browse…" if parent.language == "en" else "Обзор…"); browse_search.clicked.connect(self._browse_search); search_row.addWidget(browse_search); form.addRow("Search folder:" if parent.language == "en" else "Папка поиска:", search_row)
        self.output_edit = QLineEdit(str(Path.home() / "qfil-raw-output")); output_row = QHBoxLayout(); output_row.addWidget(self.output_edit, 1); browse_out = QPushButton("Browse…" if parent.language == "en" else "Обзор…"); browse_out.clicked.connect(self._browse_output); output_row.addWidget(browse_out); form.addRow("Output folder:" if parent.language == "en" else "Папка результата:", output_row)
        root.addLayout(form)
        self.allow_overlap = QCheckBox("Allow overlapping program ranges (advanced)" if parent.language == "en" else "Разрешить пересекающиеся диапазоны (дополнительно)"); root.addWidget(self.allow_overlap)
        actions = QHBoxLayout(); analyze = QPushButton("Analyze package" if parent.language == "en" else "Анализировать пакет"); analyze.clicked.connect(self._analyze); build = QPushButton("Build RAW images" if parent.language == "en" else "Собрать RAW-образы"); build.clicked.connect(self._build); actions.addWidget(analyze); actions.addWidget(build); root.addLayout(actions)
        self.output = QTextEdit(); self.output.setReadOnly(True); self.output.setMinimumHeight(260); root.addWidget(self.output, 1)
        close = QPushButton("Close" if parent.language == "en" else "Закрыть"); close.clicked.connect(self.close); root.addWidget(close)
        self.setStyleSheet(f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} QLineEdit,QTextEdit{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f}} QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:6px}}")

    def _set_raw(self, paths: list[str]) -> None:
        self.rawprograms = paths; self.raw_label.setText(("Rawprogram XML: " if self.main.language == "en" else "Rawprogram XML: ") + ("; ".join(Path(x).name for x in paths) or "—"))
    def _set_patch(self, paths: list[str]) -> None:
        self.patches = paths; self.patch_label.setText(("Patch XML: " if self.main.language == "en" else "Patch XML: ") + ("; ".join(Path(x).name for x in paths) or "—"))
    def _add_raw(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Rawprogram XML", str(Path.home()), "XML files (*.xml)")
        if paths: self._set_raw(list(dict.fromkeys(self.rawprograms + paths)))
    def _add_patch(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Patch XML", str(Path.home()), "XML files (*.xml)")
        if paths: self._set_patch(list(dict.fromkeys(self.patches + paths)))
    def _browse_search(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Search folder", self.search_edit.text() or str(Path.home()))
        if path: self.search_edit.setText(path)
    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Output folder", self.output_edit.text() or str(Path.home()))
        if path: self.output_edit.setText(path)
    def _inputs(self) -> dict[str, Any]:
        if not self.rawprograms: raise ValueError("Select at least one rawprogram XML file")
        roots = [self.search_edit.text().strip()] if self.search_edit.text().strip() else []
        return {"rawprogram_files": self.rawprograms, "patch_files": self.patches, "search_dirs": roots}
    def _analyze(self) -> None:
        try:
            report = analyze_qfil_package(**self._inputs())
            summary = report.get("summary", {})
            lines = ["QFIL package analysis", json.dumps(summary, ensure_ascii=False, indent=2), "", "Programs:"]
            for item in report.get("programs", []):
                lines.append(f"LUN {item.get('physical_partition_number')} | {item.get('action')} | {item.get('filename') or '(no file)'} | {item.get('source_status')} | sector {item.get('start_sector')} + {item.get('num_partition_sectors')}")
            if report.get("warnings"):
                lines.extend(["", "Warnings:", *[f"• {x}" for x in report["warnings"]]])
            self.output.setPlainText("\n".join(lines))
        except Exception as exc:
            QMessageBox.warning(self, "QFIL", f"{type(exc).__name__}: {exc}")
    def _build(self) -> None:
        try:
            if not self.output_edit.text().strip(): raise ValueError("Select an output folder")
            args = self._inputs()
            result = build_qfil_raw_images(**args, output_dir=self.output_edit.text().strip(), force=False, allow_overlaps=self.allow_overlap.isChecked())
            self.output.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
            QMessageBox.information(self, "QFIL", "RAW image assembly completed." if self.main.language == "en" else "Сборка RAW-образов завершена.")
        except Exception as exc:
            QMessageBox.critical(self, "QFIL", f"{type(exc).__name__}: {exc}")


class BatchQueueDialog(QDialog):
    """Interactive sequential queue with task-level control and status filtering."""
    ROLE_SOURCE = int(Qt.ItemDataRole.UserRole)
    ROLE_TASK_ID = ROLE_SOURCE + 1
    ROLE_STATUS = ROLE_SOURCE + 2
    ROLE_ERROR = ROLE_SOURCE + 3
    ROLE_REQUEST_ORIGINAL_STATUS = ROLE_SOURCE + 4

    STATUS_COLORS = {
        "waiting": COLORS["muted"], "running": COLORS["cyan"],
        "success": COLORS["green"], "failed": COLORS["red"],
        "cancelled": COLORS["amber"], "skipped": COLORS["muted"],
    }

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main = parent
        self.thread: QThread | None = None
        self.worker: BatchWorkerObject | None = None
        self._close_when_finished = False
        self._run_task_ids: list[str] = []
        self._run_finished_count = 0
        self._pause_active = False
        self._last_progress_label = parent.t("ready")
        self._running = False

        self.setWindowTitle(parent.t("queue_title"))
        self.resize(980, 720)
        self.setModal(False)
        root = QVBoxLayout(self)

        hint = QLabel(parent.t("queue_hint"))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{COLORS['muted']};")
        root.addWidget(hint)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(parent.t("queue_filter")))
        self.filter_combo = QComboBox()
        self.filter_combo.addItem(parent.t("filter_all"), "all")
        self.filter_combo.addItem(parent.t("filter_waiting"), "waiting")
        self.filter_combo.addItem(parent.t("filter_running"), "running")
        self.filter_combo.addItem(parent.t("filter_success"), "success")
        self.filter_combo.addItem(parent.t("filter_failed"), "failed")
        self.filter_combo.addItem(parent.t("filter_cancelled"), "cancelled")
        self.filter_combo.addItem(parent.t("filter_skipped"), "skipped")
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch()
        self.summary_label = QLabel()
        self.summary_label.setStyleSheet(f"color:{COLORS['muted']};")
        filter_row.addWidget(self.summary_label)
        root.addLayout(filter_row)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.list.setDragDropOverwriteMode(False)
        self.list.setToolTip(parent.t("queue_hint"))
        self.list.itemSelectionChanged.connect(self._update_action_states)
        self.list.model().rowsMoved.connect(self._refresh_summary)
        root.addWidget(self.list, 1)

        row = QHBoxLayout()
        self.queue_mutation_buttons: list[QPushButton] = []
        controls = [
            (("QFIL XML tools" if parent.language == "en" else "Инструменты QFIL XML"), "SP_FileDialogContentsView", parent._open_qfil),
            (parent.t("queue_add"), "SP_DialogOpenButton", self._add_files),
            (parent.t("queue_remove"), "SP_TrashIcon", self._remove),
            (parent.t("queue_clear"), "SP_DialogResetButton", self._clear),
            (parent.t("queue_move_up"), "SP_ArrowUp", lambda: self._move_selected(-1)),
            (parent.t("queue_move_down"), "SP_ArrowDown", lambda: self._move_selected(1)),
        ]
        for label, icon, callback in controls:
            button = QPushButton(label)
            button.setIcon(parent.icon_for(icon))
            button.setIconSize(QSize(parent.icon_size, parent.icon_size))
            button.clicked.connect(callback)
            row.addWidget(button)
            self.queue_mutation_buttons.append(button)
        root.addLayout(row)

        task_controls = QHBoxLayout()
        self.cancel_selected_button = QPushButton(parent.t("queue_cancel_selected"))
        self.skip_selected_button = QPushButton(parent.t("queue_skip"))
        self.retry_selected_button = QPushButton(parent.t("queue_retry"))
        for button in (self.cancel_selected_button, self.skip_selected_button, self.retry_selected_button):
            task_controls.addWidget(button)
        self.cancel_selected_button.clicked.connect(self._cancel_selected)
        self.skip_selected_button.clicked.connect(self._skip_selected)
        self.retry_selected_button.clicked.connect(self._retry_selected)
        root.addLayout(task_controls)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit(str(parent.settings.value("queue_output_dir", str(Path.home() / "sparse-to-raw-output"))))
        folder_row.addWidget(QLabel(parent.t("output_folder")))
        folder_row.addWidget(self.folder_edit, 1)
        browse = QPushButton(parent.t("choose_folder"))
        browse.setIcon(parent.icon_for("SP_DirOpenIcon"))
        browse.setIconSize(QSize(parent.icon_size, parent.icon_size))
        browse.clicked.connect(self._browse_folder)
        folder_row.addWidget(browse)
        root.addLayout(folder_row)

        self.overwrite = QCheckBox(parent.t("overwrite"))
        root.addWidget(self.overwrite)
        self.verify_output = QCheckBox(parent.t("verify_output"))
        self.verify_output.setChecked(bool(parent.settings.value("verify_output", True, type=bool)))
        self.verify_output.setToolTip(parent.t("verify_output_tooltip"))
        self.verify_output.toggled.connect(lambda checked: parent.settings.setValue("verify_output", checked))
        root.addWidget(self.verify_output)

        self.progress_label = QLabel(parent.t("ready"))
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress_label)
        root.addWidget(self.progress)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(135)
        self.log_view.document().setMaximumBlockCount(1000)
        root.addWidget(self.log_view)

        buttons = QHBoxLayout()
        self.run_button = QPushButton(parent.t("run_queue"))
        self.run_button.setIcon(parent.icon_for("SP_MediaPlay"))
        self.run_button.setIconSize(QSize(parent.icon_size, parent.icon_size))
        buttons.addWidget(self.run_button)
        self.pause_button = QPushButton(parent.t("queue_pause"))
        self.pause_button.setIcon(parent.icon_for("SP_MediaPause"))
        self.pause_button.setIconSize(QSize(parent.icon_size, parent.icon_size))
        self.pause_button.setEnabled(False)
        buttons.addWidget(self.pause_button)
        self.cancel_button = QPushButton(parent.t("queue_cancel_all"))
        self.cancel_button.setIcon(parent.icon_for("SP_MediaStop"))
        self.cancel_button.setIconSize(QSize(parent.icon_size, parent.icon_size))
        self.cancel_button.setEnabled(False)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        close = QPushButton("Close" if parent.language == "en" else "Закрыть")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.run_button.clicked.connect(lambda _checked=False: self._run())
        self.pause_button.clicked.connect(self._toggle_pause)
        self.cancel_button.clicked.connect(self._cancel)
        self._apply_style()
        self._refresh_summary()
        self._update_action_states()

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} "
            f"QListWidget,QTextEdit,QLineEdit,QComboBox{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f}} "
            f"QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:6px;border-radius:4px}} "
            f"QProgressBar{{background:#111d28;border:1px solid #24414e;height:14px}} "
            f"QProgressBar::chunk{{background:{COLORS['cyan']}}}"
        )

    def _status_label(self, status: str) -> str:
        keys = {
            "waiting": "queue_status_waiting", "running": "queue_status_running",
            "success": "queue_status_success", "failed": "queue_status_failed",
            "cancelled": "queue_status_cancelled", "skipped": "queue_status_skipped",
            "cancel_requested": "queue_status_cancel_requested", "skip_requested": "queue_status_skip_requested",
        }
        return self.main.t(keys.get(status, "queue_status_waiting"))

    def _find_item(self, task_id: str) -> QListWidgetItem | None:
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.data(self.ROLE_TASK_ID) == task_id:
                return item
        return None

    def _set_item_status(self, task_id: str, status: str, error: str = "") -> None:
        item = self._find_item(task_id)
        if item is None:
            return
        previous_status = item.data(self.ROLE_STATUS) or "waiting"
        if status in {"cancel_requested", "skip_requested"}:
            item.setData(self.ROLE_REQUEST_ORIGINAL_STATUS, previous_status)
        else:
            item.setData(self.ROLE_REQUEST_ORIGINAL_STATUS, None)
        item.setData(self.ROLE_STATUS, status)
        item.setData(self.ROLE_ERROR, error)
        source = str(item.data(self.ROLE_SOURCE) or "")
        item.setText(f"{self._status_label(status)}  ·  {source}")
        item.setForeground(QColor(self.STATUS_COLORS.get(status, COLORS["muted"])))
        item.setToolTip(error or source)
        self._refresh_summary()
        self._apply_filter()

    def _new_item(self, path: str) -> None:
        if self.filter_combo.currentData() != "all":
            self.filter_combo.setCurrentIndex(self.filter_combo.findData("all"))
        resolved = str(Path(path).expanduser().resolve())
        known = {
            str(Path(self.list.item(i).data(self.ROLE_SOURCE)).expanduser().resolve()).casefold()
            for i in range(self.list.count())
        }
        if resolved.casefold() in known:
            return
        task_id = uuid.uuid4().hex
        item = QListWidgetItem()
        item.setData(self.ROLE_SOURCE, resolved)
        item.setData(self.ROLE_TASK_ID, task_id)
        item.setData(self.ROLE_STATUS, "waiting")
        self.list.addItem(item)
        self._set_item_status(task_id, "waiting")
        self.main.add_recent(resolved)
        if self.list.count() == 1:
            self.folder_edit.setText(str(Path(resolved).parent / "sparse-to-raw-output"))

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, self.main.t("add_files"), str(Path.home()), "Images (*)")
        for path in paths:
            self._new_item(path)
        self._refresh_summary()
        self._update_action_states()

    def _remove(self) -> None:
        if self._is_running():
            return
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._refresh_summary()
        self._update_action_states()

    def _clear(self) -> None:
        if self._is_running():
            return
        self.list.clear()
        self.progress.setValue(0)
        self.progress_label.setText(self.main.t("ready"))
        self._last_progress_label = self.main.t("ready")
        self._refresh_summary()
        self._update_action_states()

    def _move_selected(self, delta: int) -> None:
        if self._is_running():
            return
        selected_rows = sorted((self.list.row(item) for item in self.list.selectedItems()), reverse=(delta > 0))
        for row in selected_rows:
            target = row + delta
            if 0 <= target < self.list.count():
                item = self.list.takeItem(row)
                self.list.insertItem(target, item)
                item.setSelected(True)
        self._update_action_states()

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.main.t("output_folder"), self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)
            self.main.settings.setValue("queue_output_dir", path)

    def _is_running(self) -> bool:
        return self._running

    def _update_action_states(self) -> None:
        running = self._is_running()
        selected = self.list.selectedItems()
        selected_statuses = [str(item.data(self.ROLE_STATUS) or "waiting") for item in selected]
        for button in self.queue_mutation_buttons:
            button.setEnabled(not running and bool(self.list.count()))
        if self.queue_mutation_buttons:
            self.queue_mutation_buttons[0].setEnabled(not running)
            self.queue_mutation_buttons[1].setEnabled(not running and bool(selected))
            self.queue_mutation_buttons[2].setEnabled(not running and bool(self.list.count()))
            self.queue_mutation_buttons[3].setEnabled(not running and bool(selected))
            self.queue_mutation_buttons[4].setEnabled(not running and bool(selected))
        self.list.setDragEnabled(not running)
        self.list.setDragDropMode(
            QAbstractItemView.DragDropMode.NoDragDrop if running
            else QAbstractItemView.DragDropMode.InternalMove
        )
        self.folder_edit.setEnabled(not running)
        self.overwrite.setEnabled(not running)
        self.verify_output.setEnabled(not running)
        self.filter_combo.setEnabled(True)
        self.run_button.setEnabled(not running and any(
            self.list.item(i).data(self.ROLE_STATUS) == "waiting" for i in range(self.list.count())
        ))
        self.pause_button.setEnabled(running)
        self.cancel_button.setEnabled(running)
        self.cancel_selected_button.setEnabled(running and any(s in {"waiting", "running"} for s in selected_statuses))
        self.skip_selected_button.setEnabled((running and any(s in {"waiting", "running"} for s in selected_statuses)) or (not running and any(s == "waiting" for s in selected_statuses)))
        self.retry_selected_button.setEnabled(not running and any(s in {"failed", "cancelled", "skipped"} for s in selected_statuses))

    def _apply_filter(self, *_args) -> None:
        wanted = self.filter_combo.currentData()
        for index in range(self.list.count()):
            item = self.list.item(index)
            status = item.data(self.ROLE_STATUS) or "waiting"
            filter_status = item.data(self.ROLE_REQUEST_ORIGINAL_STATUS) if status in {"cancel_requested", "skip_requested"} else status
            hidden = wanted != "all" and filter_status != wanted
            item.setHidden(hidden)
            if hidden and item.isSelected():
                item.setSelected(False)
        self._update_action_states()

    def _refresh_summary(self, *_args) -> None:
        counts = {name: 0 for name in ("waiting", "running", "success", "failed", "cancelled", "skipped")}
        for index in range(self.list.count()):
            item = self.list.item(index)
            status = item.data(self.ROLE_STATUS) or "waiting"
            if status in {"cancel_requested", "skip_requested"}:
                status = item.data(self.ROLE_REQUEST_ORIGINAL_STATUS) or "waiting"
            if status in counts:
                counts[status] += 1
        self.summary_label.setText(self.main.t("queue_summary").format(total=self.list.count(), **counts))

    def _run(self, only_task_ids: set[str] | None = None) -> None:
        if self._is_running():
            return
        if self.main.operation_running(exclude=self):
            QMessageBox.information(self, self.main.t("queue_title"), self.main.t("another_operation"))
            return

        selected_rows: list[tuple[str, Path]] = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            task_id = str(item.data(self.ROLE_TASK_ID))
            status = str(item.data(self.ROLE_STATUS) or "waiting")
            if status == "waiting" and (only_task_ids is None or task_id in only_task_ids):
                selected_rows.append((task_id, Path(str(item.data(self.ROLE_SOURCE)))))
        if not selected_rows:
            QMessageBox.information(self, self.main.t("queue_title"), self.main.t("add_files"))
            return

        sources = [source for _, source in selected_rows]
        task_ids = [task_id for task_id, _ in selected_rows]
        output_dir = Path(self.folder_edit.text()).expanduser().resolve()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Error", str(exc))
            return
        try:
            preflight_batch(sources, output_dir, overwrite=self.overwrite.isChecked())
        except Exception as exc:
            QMessageBox.warning(
                self, self.main.t("queue_title"),
                f"{friendly_error(str(exc), self.main.language)}\n\nDetails: {exc}",
            )
            self._log("error", f"Batch preflight failed: {type(exc).__name__}: {exc}")
            return

        self.filter_combo.setCurrentIndex(self.filter_combo.findData("all"))
        self.main.settings.setValue("queue_output_dir", str(output_dir))
        self._run_task_ids = task_ids
        self._run_finished_count = 0
        self._running = True
        self._pause_active = False
        self.list.setDragEnabled(False)
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.folder_edit.setEnabled(False)
        self.overwrite.setEnabled(False)
        self.verify_output.setEnabled(False)
        for button in self.queue_mutation_buttons:
            button.setEnabled(False)
        self.run_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.pause_button.setText(self.main.t("queue_pause"))
        self.cancel_button.setEnabled(True)
        self.progress.setValue(0)
        self.progress_label.setText(f"0 / {len(sources)}")
        self._last_progress_label = self.progress_label.text()

        worker = BatchWorkerObject(
            sources, output_dir, self.overwrite.isChecked(),
            verify_output=self.verify_output.isChecked(), task_ids=task_ids,
        )
        self.worker = worker
        worker.log.connect(self._log)
        worker.progress.connect(self._progress)
        worker.item_started.connect(self._item_started)
        worker.item_finished.connect(self._item_finished)
        worker.pause_changed.connect(self._pause_changed)
        worker.finished_report.connect(self._report_done)

        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self.thread = thread
        self._update_action_states()
        thread.start()

    def _retry_selected(self) -> None:
        retry_ids: set[str] = set()
        for item in self.list.selectedItems():
            status = item.data(self.ROLE_STATUS)
            if status in {"failed", "cancelled", "skipped"}:
                retry_ids.add(str(item.data(self.ROLE_TASK_ID)))
        if not retry_ids:
            QMessageBox.information(self, self.main.t("queue_title"), self.main.t("queue_no_retry"))
            return
        self.filter_combo.setCurrentIndex(self.filter_combo.findData("all"))
        for task_id in retry_ids:
            self._set_item_status(task_id, "waiting")
        self._log("info", self.main.t("queue_retry_hint"))
        self._run(only_task_ids=retry_ids)

    def _cancel_selected(self) -> None:
        if not self.worker or not self._is_running():
            return
        for item in self.list.selectedItems():
            status = str(item.data(self.ROLE_STATUS) or "waiting")
            if status not in {"waiting", "running"}:
                continue
            task_id = str(item.data(self.ROLE_TASK_ID))
            if self.worker.cancel_task(task_id):
                self._set_item_status(task_id, "cancel_requested")
                self._log("warning", self.main.t("queue_item_cancel_requested").format(path=item.data(self.ROLE_SOURCE)))

    def _skip_selected(self) -> None:
        selected = self.list.selectedItems()
        if self._is_running() and self.worker:
            for item in selected:
                status = str(item.data(self.ROLE_STATUS) or "waiting")
                if status not in {"waiting", "running"}:
                    continue
                task_id = str(item.data(self.ROLE_TASK_ID))
                if self.worker.skip_task(task_id):
                    self._set_item_status(task_id, "skip_requested")
                    self._log("warning", self.main.t("queue_item_skip_requested").format(path=item.data(self.ROLE_SOURCE)))
        else:
            for item in selected:
                if item.data(self.ROLE_STATUS) == "waiting":
                    self._set_item_status(str(item.data(self.ROLE_TASK_ID)), "skipped", "Skipped by user")
        self._update_action_states()

    def _add_files(self) -> None:
        if self._is_running():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, self.main.t("add_files"), str(Path.home()), "Images (*)")
        for path in paths:
            self._new_item(path)
        self._refresh_summary()
        self._update_action_states()

    def _remove(self) -> None:
        if self._is_running():
            return
        for item in self.list.selectedItems():
            self.list.takeItem(self.list.row(item))
        self._refresh_summary()
        self._update_action_states()

    def _clear(self) -> None:
        if self._is_running():
            return
        self.list.clear()
        self.progress.setValue(0)
        self.progress_label.setText(self.main.t("ready"))
        self._last_progress_label = self.main.t("ready")
        self._refresh_summary()
        self._update_action_states()

    def _move_selected(self, delta: int) -> None:
        if self._is_running():
            return
        rows = sorted((self.list.row(item) for item in self.list.selectedItems()), reverse=(delta > 0))
        for row in rows:
            target = row + delta
            if 0 <= target < self.list.count():
                item = self.list.takeItem(row)
                self.list.insertItem(target, item)
                item.setSelected(True)
        self._update_action_states()

    def _browse_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, self.main.t("output_folder"), self.folder_edit.text())
        if path:
            self.folder_edit.setText(path)
            self.main.settings.setValue("queue_output_dir", path)

    def _log(self, level: str, message: str) -> None:
        self.log_view.append(f"[{level.upper()}] {localize_log_message(message, self.main.language)}")
        self.main.append_log(level, message, category="queue")

    def _item_started(self, task_id: str) -> None:
        self._set_item_status(task_id, "running")
        self._update_action_states()

    def _progress(self, data: dict) -> None:
        self.progress.setValue(int(data.get("queue_percent", data.get("percent", 0))))
        index = int(data.get("queue_index", 0)) + 1
        total = int(data.get("queue_total", len(self._run_task_ids)))
        current = Path(str(data.get("queue_current_file", ""))).name
        self.progress_label.setText(f"{index}/{total} · {current} · {int(data.get('percent', 0))}%")
        self._last_progress_label = self.progress_label.text()

    def _item_finished(self, index: int, row: dict) -> None:
        task_id = str(row.get("task_id", self._run_task_ids[index] if index < len(self._run_task_ids) else ""))
        status = str(row.get("status", "failed"))
        self._set_item_status(task_id, status, str(row.get("error", "")))
        self.main.record_operation_metrics("queue", status, row.get("operation_metrics", {}), source=Path(str(row.get("input", ""))).name, error=str(row.get("error", "")))
        self._run_finished_count += 1
        total = max(1, len(self._run_task_ids))
        self.progress.setValue(min(100, int(self._run_finished_count * 100 / total)))
        self.progress_label.setText(f"{self._run_finished_count}/{total}")
        self._last_progress_label = self.progress_label.text()
        self._update_action_states()

    def _pause_changed(self, paused: bool) -> None:
        self._pause_active = paused
        self.pause_button.setText(self.main.t("queue_resume" if paused else "queue_pause"))
        self.pause_button.setIcon(self.main.icon_for("SP_MediaPlay" if paused else "SP_MediaPause"))
        self.progress_label.setText(self.main.t("queue_paused_log") if paused else self._last_progress_label)
        self._log("info", self.main.t("queue_paused_log" if paused else "queue_resumed_log"))
        self._update_action_states()

    def _toggle_pause(self) -> None:
        if not self.worker or not self._is_running():
            return
        if self.worker.is_pause_requested():
            self.worker.resume()
            self.pause_button.setText(self.main.t("queue_pause"))
            self.pause_button.setIcon(self.main.icon_for("SP_MediaPause"))
        else:
            self.worker.request_pause()
            self.pause_button.setText(self.main.t("queue_pausing"))

    def _report_done(self, report: dict) -> None:
        summary = report.get("summary", {})
        self.progress.setValue(100)
        self.progress_label.setText(self.main.t("queue_summary").format(
            total=summary.get("total", 0), waiting=0, running=0, success=summary.get("success", 0),
            failed=summary.get("failed", 0), cancelled=summary.get("cancelled", 0),
            skipped=summary.get("skipped", 0),
        ))
        self._last_progress_label = self.progress_label.text()
        self.log_view.append("\n" + json.dumps(summary, ensure_ascii=False, indent=2))
        if report.get("report_path"):
            self.log_view.append(f"Report: {report['report_path']}")

    def _thread_finished(self) -> None:
        self._running = False
        self.thread = None
        self.worker = None
        self.run_button.setEnabled(True)
        self.pause_button.setEnabled(False)
        self.pause_button.setText(self.main.t("queue_pause"))
        self.cancel_button.setEnabled(False)
        self.list.setDragEnabled(True)
        self.folder_edit.setEnabled(True)
        self.overwrite.setEnabled(True)
        self.verify_output.setEnabled(True)
        for button in self.queue_mutation_buttons:
            button.setEnabled(True)
        self._update_action_states()
        if self._close_when_finished:
            self.close()
        self.main._check_close_after_workers()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._is_running():
            self._close_when_finished = True
            if self.worker is not None:
                self.worker.request_cancel()
            event.ignore()
            return
        event.accept()

    def _cancel(self) -> None:
        if self.worker:
            self.cancel_button.setEnabled(False)
            self.worker.request_cancel()
            self._log("warning", "Queue cancellation requested; the current file will stop at a safe boundary.")


class MergeDialog(QDialog):
    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent); self.main = parent; self.thread: QThread | None = None; self.worker: ConversionWorkerObject | None = None; self.result: dict | None = None; self._close_when_finished = False
        self.setWindowTitle(parent.t("merge_title")); self.resize(850, 590); self.setModal(False)
        root = QVBoxLayout(self); hint = QLabel(parent.t("merge_hint")); hint.setWordWrap(True); hint.setStyleSheet(f"color:{COLORS['muted']}"); root.addWidget(hint)
        self.parts = QListWidget(); self.parts.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection); root.addWidget(self.parts,1)
        actions = QHBoxLayout(); self.part_controls = []
        controls = [
            (parent.t("discover_folder"), "SP_DirOpenIcon", self._discover),
            (parent.t("add_files"), "SP_DialogOpenButton", self._add),
            (parent.t("remove"), "SP_TrashIcon", self._remove),
            (parent.t("move_up"), "SP_ArrowUp", self._up),
            (parent.t("move_down"), "SP_ArrowDown", self._down),
        ]
        for label, icon_name, callback in controls:
            button = QPushButton(label); button.setIcon(parent.icon_for(icon_name)); button.setIconSize(QSize(parent.icon_size, parent.icon_size)); button.clicked.connect(callback); actions.addWidget(button); self.part_controls.append(button)
        root.addLayout(actions)
        out = QHBoxLayout(); out.addWidget(QLabel(parent.t("output_label"))); self.output_edit = QLineEdit(str(parent.settings.value("merge_output_path", str(Path.home()/"merged_raw.img")))); self.output_edit.textChanged.connect(lambda value: parent.settings.setValue("merge_output_path", value)); out.addWidget(self.output_edit,1)
        browse = QPushButton(parent.t("browse")); browse.setIcon(parent.icon_for("SP_DialogSaveButton")); browse.setIconSize(QSize(parent.icon_size, parent.icon_size)); browse.clicked.connect(self._browse_output); out.addWidget(browse); root.addLayout(out)
        self.verify_output = QCheckBox(parent.t("verify_output"))
        self.verify_output.setChecked(bool(parent.settings.value("verify_output", True, type=bool)))
        self.verify_output.setToolTip(parent.t("verify_output_tooltip"))
        self.verify_output.toggled.connect(lambda checked: parent.settings.setValue("verify_output", checked))
        root.addWidget(self.verify_output)
        self.progress = QProgressBar(); self.progress.setRange(0,100); root.addWidget(self.progress)
        self.log_view = QTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumHeight(125); root.addWidget(self.log_view)
        buttons = QHBoxLayout(); self.run_button = QPushButton(parent.t("start_merge")); self.run_button.setIcon(parent.icon_for("SP_DialogApplyButton")); self.run_button.setIconSize(QSize(parent.icon_size, parent.icon_size)); buttons.addWidget(self.run_button)
        self.cancel_button = QPushButton(parent.t("cancel")); self.cancel_button.setEnabled(False); self.cancel_button.clicked.connect(self._cancel); buttons.addWidget(self.cancel_button); self.save_report = QPushButton(parent.t("save_json")); self.save_report.setEnabled(False); self.save_report.clicked.connect(self._save_report); buttons.addWidget(self.save_report); buttons.addStretch()
        close = QPushButton("Close" if parent.language == "en" else "Закрыть"); close.clicked.connect(self.close); buttons.addWidget(close); root.addLayout(buttons)
        self.run_button.clicked.connect(self._run); self._apply_style()
    def _apply_style(self) -> None:
        self.setStyleSheet(f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} QListWidget,QTextEdit,QLineEdit{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f}} QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:6px;border-radius:4px}} QProgressBar{{background:#111d28;border:1px solid #24414e;height:14px}} QProgressBar::chunk{{background:{COLORS['cyan']}}}")
    def _discover(self) -> None:
        start_folder = str(self.main.settings.value("merge_source_folder", str(Path.home())))
        folder = QFileDialog.getExistingDirectory(self, self.main.t("discover_folder"), start_folder)
        if not folder:
            return
        self.main.settings.setValue("merge_source_folder", folder)
        try:
            result = discover_sparse_parts(folder)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, self.main.t("merge_title"), str(exc))
            return

        groups = result.get("groups", [])
        if not groups:
            QMessageBox.information(self, self.main.t("merge_title"), self.main.t("discover_no_groups"))
            return

        def describe(group: dict) -> str:
            count = len(group.get("parts", []))
            status_key = "discover_ready_status" if group.get("ready") else "discover_check_status"
            status = self.main.t(status_key)
            return f"{group['label']} — {count} — {status}"

        selected_group = groups[0]
        if len(groups) > 1:
            choice, accepted = QInputDialog.getItem(
                self,
                self.main.t("discover_choose_title"),
                self.main.t("discover_choose_prompt"),
                [describe(group) for group in groups],
                0,
                False,
            )
            if not accepted:
                return
            selected_group = groups[[describe(group) for group in groups].index(choice)]

        if not selected_group.get("ready"):
            details = []
            missing_ranges = selected_group.get("missing_ranges", [])
            if missing_ranges:
                labels = [str(start) if start == end else f"{start}-{end}" for start, end in missing_ranges]
                details.append(self.main.t("discover_missing").format(indices=", ".join(labels)))
            if selected_group.get("duplicate_indices"):
                details.append(self.main.t("discover_duplicates").format(
                    indices=", ".join(map(str, selected_group["duplicate_indices"]))
                ))
            if selected_group.get("header_errors"):
                details.append(self.main.t("discover_header_errors").format(
                    details="\n".join(selected_group["header_errors"])
                ))
            if len(selected_group.get("block_sizes", [])) > 1:
                details.append(self.main.t("discover_block_sizes").format(
                    sizes=", ".join(map(str, selected_group["block_sizes"]))
                ))
            if len(selected_group.get("parts", [])) < 2:
                details.append(self.main.t("discover_min_parts_issue"))
            QMessageBox.warning(
                self,
                self.main.t("merge_title"),
                self.main.t("discover_not_ready").format(details="\n".join(details) or self.main.t("discover_unknown_issue")),
            )
            return

        was_empty = self.parts.count() == 0
        known = {
            os.path.normcase(str(Path(self.parts.item(index).data(Qt.ItemDataRole.UserRole)).resolve()))
            for index in range(self.parts.count())
        }
        added_paths: list[str] = []
        for part in selected_group["parts"]:
            path = str(Path(part["path"]).resolve())
            path_key = os.path.normcase(path)
            if path_key in known:
                continue
            item = QListWidgetItem(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.parts.addItem(item)
            known.add(path_key)
            added_paths.append(path)

        for path in reversed(added_paths):
            self.main.add_recent(path)

        if added_paths:
            if was_empty:
                first_path = Path(selected_group["parts"][0]["path"])
                output_path = str(first_path.parent / "merged_raw.img")
                self.output_edit.setText(output_path)
                self.main.settings.setValue("merge_output_path", output_path)
            self.log_view.append(
                self.main.t("discover_loaded").format(
                    count=len(added_paths),
                    label=selected_group["label"],
                    size=format_bytes(selected_group["total_raw_size_bytes"], self.main.language),
                )
            )
        else:
            QMessageBox.information(self, self.main.t("merge_title"), self.main.t("discover_nothing_new"))

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
        self.log_view.clear()
        try:
            preflight = preflight_output(sources, out, operation="merge", force=force)
        except Exception as exc:
            self._log("error", f"Merge preflight failed: {type(exc).__name__}: {exc}")
            QMessageBox.warning(
                self, self.main.t("merge_title"),
                f"{friendly_error(str(exc), self.main.language)}\n\nDetails: {exc}",
            )
            return
        self._log(
            "success",
            "Preflight passed: "
            f"{format_bytes(preflight['available_free_bytes'], self.main.language)} free; "
            f"{format_bytes(preflight['required_free_bytes'], self.main.language)} required including merge staging and safety margin.",
        )
        self.parts.setEnabled(False); self.output_edit.setEnabled(False); self.verify_output.setEnabled(False)
        for button in self.part_controls: button.setEnabled(False)
        self.run_button.setEnabled(False); self.cancel_button.setEnabled(True); self.progress.setValue(0); self.result=None; self.save_report.setEnabled(False)
        worker=ConversionWorkerObject(
            None, out, force, operation="merge", merge_sources=sources,
            verify_output=self.verify_output.isChecked(),
        ); self.worker=worker
        worker.progress.connect(lambda d:self.progress.setValue(int(d.get("percent",0))))
        worker.log.connect(self._log); worker.succeeded.connect(self._success); worker.failed.connect(self._failure); worker.cancelled.connect(lambda:self._log("warning","Merge cancelled; staged output discarded."))
        thread=connect_worker(worker,self,self._thread_finished); self.thread=thread; thread.start()
    def _log(self, level: str, message: str) -> None: self.log_view.append(f"[{level.upper()}] {localize_log_message(message, self.main.language)}"); self.main.append_log(level,message,category="merge")
    def _success(self,result:dict) -> None:
        self.result=result; self.progress.setValue(100); self.save_report.setEnabled(True); self.log_view.append("\n"+json.dumps(result,ensure_ascii=False,indent=2))
        self.main.record_operation_metrics("merge", "success", result.get("operation_metrics", {}), source=Path(str(result.get("output", "merge"))).name)
    def _failure(self,message:str) -> None:
        self._log("error",message)
        friendly = friendly_error(message, self.main.language)
        QMessageBox.critical(self,self.main.t("merge_title"),f"{friendly}\n\nDetails: {message}")
    def _thread_finished(self) -> None:
        self.thread=None; self.worker=None; self.run_button.setEnabled(True); self.cancel_button.setEnabled(False)
        self.parts.setEnabled(True); self.output_edit.setEnabled(True); self.verify_output.setEnabled(True)
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


class DiagnosticCenterDialog(QDialog):
    """Searchable diagnostic history with privacy-conscious ZIP export."""
    LEVELS = ("debug", "info", "success", "warning", "error")
    CATEGORIES = ("application", "conversion", "analysis", "queue", "merge", "preflight", "verification", "diagnostics", "structure")

    def __init__(self, parent: "MainWindow") -> None:
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle(parent.t("diagnostics_title"))
        self.resize(1080, 680)
        self.setModal(False)
        root = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.level_combo = QComboBox()
        self.level_combo.addItem(parent.t("diagnostics_all"), "all")
        for level in self.LEVELS:
            self.level_combo.addItem(parent.t(f"diagnostics_level_{level}"), level)
        self.category_combo = QComboBox()
        self.category_combo.addItem(parent.t("diagnostics_all"), "all")
        for category in self.CATEGORIES:
            self.category_combo.addItem(parent.t(f"diagnostics_cat_{category}"), category)
        self.period_combo = QComboBox()
        self.period_combo.addItem(parent.t("diagnostics_all"), "all")
        self.period_combo.addItem(parent.t("diagnostics_period_today"), "today")
        self.period_combo.addItem(parent.t("diagnostics_period_week"), "7d")
        for label, control in (("diagnostics_filter_level", self.level_combo), ("diagnostics_filter_category", self.category_combo), ("diagnostics_filter_period", self.period_combo)):
            filters.addWidget(QLabel(parent.t(label)))
            filters.addWidget(control)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(parent.t("diagnostics_search"))
        filters.addWidget(self.search_edit, 1)
        root.addLayout(filters)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([parent.t("diagnostics_time"), parent.t("diagnostics_level"), parent.t("diagnostics_category"), parent.t("diagnostics_message")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)
        self.count_label = QLabel()
        self.count_label.setStyleSheet(f"color:{COLORS['muted']};")
        root.addWidget(self.count_label)
        privacy = QLabel(parent.t("diagnostics_privacy"))
        privacy.setWordWrap(True)
        privacy.setStyleSheet(f"color:{COLORS['muted']};font-size:9pt;")
        root.addWidget(privacy)

        buttons = QHBoxLayout()
        self.export_button = QPushButton(parent.t("diagnostics_export"))
        self.clear_button = QPushButton(parent.t("diagnostics_clear"))
        close_button = QPushButton(parent.t("diagnostics_close"))
        self.export_button.clicked.connect(self._export)
        self.clear_button.clicked.connect(self._clear)
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.clear_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        root.addLayout(buttons)
        for control in (self.level_combo, self.category_combo, self.period_combo):
            control.currentIndexChanged.connect(self.refresh)
        self.search_edit.textChanged.connect(self.refresh)
        self.setStyleSheet(
            f"QDialog{{background:{COLORS['background']};color:{COLORS['text']}}} "
            f"QTableWidget,QLineEdit,QComboBox{{background:#07111b;color:{COLORS['text']};border:1px solid #29434f;gridline-color:#203946}} "
            f"QHeaderView::section{{background:#0d1c29;color:{COLORS['cyan']};padding:6px;border:1px solid #243a47}} "
            f"QPushButton{{background:#0a1b27;color:{COLORS['cyan']};border:1px solid #24505e;padding:7px;border-radius:4px}}"
        )
        self.refresh()

    def _filtered_events(self) -> list[dict[str, Any]]:
        events = self.main.diagnostic_store.entries()
        level = self.level_combo.currentData()
        category = self.category_combo.currentData()
        period = self.period_combo.currentData()
        search = self.search_edit.text().strip().casefold()
        now = datetime.now().astimezone()
        filtered: list[dict[str, Any]] = []
        for event in reversed(events):
            if level != "all" and event.get("level") != level:
                continue
            if category != "all" and event.get("category") != category:
                continue
            if period != "all":
                try:
                    timestamp = datetime.fromisoformat(str(event.get("timestamp", "")))
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.astimezone()
                except ValueError:
                    continue
                if period == "today" and timestamp.date() != now.date():
                    continue
                if period == "7d" and timestamp < now - timedelta(days=7):
                    continue
            searchable = " ".join((str(event.get("message", "")), json.dumps(event.get("details", {}), ensure_ascii=False), str(event.get("category", "")), str(event.get("level", "")))).casefold()
            if search and search not in searchable:
                continue
            filtered.append(event)
        return filtered

    def refresh(self, *_args) -> None:
        events = self._filtered_events()
        self.table.setRowCount(len(events))
        level_colors = {"success": COLORS["green"], "error": COLORS["red"], "warning": COLORS["amber"], "info": COLORS["cyan"], "debug": COLORS["muted"]}
        for row, event in enumerate(events):
            category = str(event.get("category", ""))
            category_label = self.main.t(f"diagnostics_cat_{category}")
            values = (str(event.get("timestamp", "")), str(event.get("level", "")).upper(), category_label, localize_log_message(str(event.get("message", "")), self.main.language))
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 1:
                    item.setForeground(QColor(level_colors.get(str(event.get("level", "")), COLORS["text"])))
                if column == 3 and event.get("details"):
                    item.setToolTip(value + "\n\n" + json.dumps(event["details"], ensure_ascii=False, indent=2))
                self.table.setItem(row, column, item)
        self.count_label.setText(self.main.t("diagnostics_count").format(count=len(events)))

    def _export(self) -> None:
        default_name = f"sparse-to-raw-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.zip"
        filename, _ = QFileDialog.getSaveFileName(self, self.main.t("diagnostics_export"), default_name, "ZIP archive (*.zip)")
        if not filename:
            return
        target = Path(filename)
        if target.suffix.casefold() != ".zip":
            target = target.with_suffix(".zip")
        try:
            archive = self.main.diagnostic_store.export_zip(
                target,
                app_version=APP_VERSION,
                qt_version=qVersion(),
                pyside_version=getattr(PySide6, "__version__", "unavailable"),
            )
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            QMessageBox.critical(self, self.main.t("diagnostics_title"), f"{self.main.t('diagnostics_export_failed')}\n{exc}")
            self.main.append_log("error", f"Diagnostic ZIP export failed: {type(exc).__name__}: {exc}", category="diagnostics")
            return
        self.main.append_log("success", f"Diagnostic ZIP exported: {archive.name}", category="diagnostics", details={"archive_name": archive.name})
        self.refresh()
        QMessageBox.information(self, self.main.t("diagnostics_title"), f"{self.main.t('diagnostics_exported')}\n{archive}")

    def _clear(self) -> None:
        answer = QMessageBox.question(
            self, self.main.t("diagnostics_title"), self.main.t("diagnostics_clear_confirm"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self.main.diagnostic_store.clear():
            QMessageBox.warning(self, self.main.t("diagnostics_title"), self.main.diagnostic_store.last_error or "Could not clear diagnostic history.")
            return
        self.main.log_view.clear()
        self.main.append_log("info", "Diagnostic history cleared.", category="diagnostics")
        self.refresh()


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        app = QApplication.instance()
        if app is not None:
            app.setOrganizationName(ORG_NAME)
            app.setApplicationName(APP_NAME)
            app.setApplicationVersion(APP_VERSION)
        diagnostics_override = os.environ.get("SPARSE_TO_RAW_DIAGNOSTICS_DIR", "").strip()
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        if diagnostics_override:
            diagnostics_directory = Path(diagnostics_override).expanduser()
        else:
            if not app_data:
                app_data = str(Path.home() / ".local" / "share" / APP_NAME)
            diagnostics_directory = default_diagnostics_directory(app_data)
        self.diagnostic_store = DiagnosticStore(diagnostics_directory)
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.language = str(self.settings.value("language", "ru"))
        if self.language not in I18N: self.language = "ru"
        self.speed_unit = str(self.settings.value("speed_unit", "MiB/s"))
        if self.speed_unit not in ("MB/s", "MiB/s", "Mbit/s"): self.speed_unit = "MiB/s"
        self.verify_output_default = bool(self.settings.value("verify_output", True, type=bool))
        self.recent_files = [str(x) for x in self.settings.value("recent_files", [], type=list) if str(x)]
        self._last_progress = {}; self.last_result: dict[str, Any] | None = None
        self._status_label = I18N[self.language]["status_idle"]; self._status_color = "muted"
        self._close_after_worker = False
        app_icon = QIcon(str(resource_path("assets/sparse-to-raw.ico")))
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon)
        if app is not None:
            app.setWindowIcon(app_icon)
            if hasattr(app, "setApplicationDisplayName"):
                app.setApplicationDisplayName(APP_NAME)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True); self.setAcceptDrops(True)
        self.setMinimumSize(1120, 760); self.resize(1420, 900)
        self._thread: QThread | None=None; self._worker: ConversionWorkerObject | None=None
        self._output_manual=False; self._setting_output=False; self._close_after_worker=False; self._expected_size=0; self._total_chunks=0
        self.icon_size = self.style().pixelMetric(QStyle.PixelMetric.PM_SmallIconSize) + 10
        self._build_ui(); self._apply_styles(); self.retranslate_ui(); self._restore_settings()
        self.append_log("info", "Interface ready. Choose an Android Sparse Image.")
    def t(self,key:str) -> str: return I18N[self.language].get(key,key)
    def icon_for(self, standard_name: str) -> QIcon:
        attr = getattr(QStyle.StandardPixmap, standard_name, None)
        return self.style().standardIcon(attr) if attr is not None else QIcon()

    def _build_ui(self) -> None:
        outer=QVBoxLayout(self); outer.setContentsMargins(78,12,78,34); outer.setSpacing(8)
        self.header=HeaderBar(APP_VERSION,self); outer.addWidget(self.header)
        separator=QFrame(); separator.setObjectName("cyanSeparator"); separator.setFixedHeight(2); outer.addWidget(separator)
        toolbar=QHBoxLayout(); toolbar.setSpacing(7)
        self.qfil_button=QPushButton("QFIL XML"); self.qfil_button.clicked.connect(self._open_qfil); toolbar.addWidget(self.qfil_button)
        self.analyze_button=QPushButton(); self.analyze_button.setIcon(self.icon_for("SP_FileDialogContentsView")); self.analyze_button.setIconSize(QSize(24,24)); self.analyze_button.clicked.connect(self._open_analysis); toolbar.addWidget(self.analyze_button)
        self.structure_button=QPushButton(); self.structure_button.setIcon(self.icon_for("SP_FileDialogDetailedView")); self.structure_button.setIconSize(QSize(24,24)); self.structure_button.clicked.connect(self._open_structure); toolbar.addWidget(self.structure_button)
        self.queue_button=QPushButton(); self.queue_button.setIcon(self.icon_for("SP_FileDialogListView")); self.queue_button.setIconSize(QSize(24,24)); self.queue_button.clicked.connect(self._open_queue); toolbar.addWidget(self.queue_button)
        self.merge_button=QPushButton(); self.merge_button.setIcon(self.icon_for("SP_DirLinkIcon")); self.merge_button.setIconSize(QSize(24,24)); self.merge_button.clicked.connect(self._open_merge); toolbar.addWidget(self.merge_button)
        self.report_button=QPushButton(); self.report_button.setIcon(self.icon_for("SP_DialogSaveButton")); self.report_button.setIconSize(QSize(24,24)); self.report_button.clicked.connect(self._save_last_report); self.report_button.setEnabled(False); toolbar.addWidget(self.report_button)
        self.diagnostics_button=QPushButton(); self.diagnostics_button.setIcon(self.icon_for("SP_MessageBoxInformation")); self.diagnostics_button.setIconSize(QSize(24,24)); self.diagnostics_button.clicked.connect(self._open_diagnostics); toolbar.addWidget(self.diagnostics_button)
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
        self.verify_output_check=QCheckBox()
        self.verify_output_check.setChecked(self.verify_output_default)
        self.verify_output_check.toggled.connect(self._verify_output_changed)
        outer.addWidget(self.verify_output_check)
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
        self.verify_output_check.setText(d["verify_output"])
        self.verify_output_check.setToolTip(d["verify_output_tooltip"])
        self.progress_title.setText(d["progress"]); self.stats_title.setText(d["stats"]); self.chunks_label.setText(f"{d['chunks']}\n0 / —"); self.size_label.setText(f"{d['size']}\n0 B / —")
        self.log_title.setText(d["log"]); self.clear_log_button.setText(d["clear_log"])
        self.analyze_button.setText(d["analyze"]); self.structure_button.setText(d["structure_button"]); self.queue_button.setText(d["queue"]); self.merge_button.setText(d["merge"]); self.report_button.setText(d["save_report"]); self.diagnostics_button.setText(d["diagnostics_button"])
        self.recent_label.setText(d["recent"]); self.language_label.setText(d["language"])
        self._rebuild_recents()
        current=self.language_combo.findData(self.language)
        if current >= 0 and self.language_combo.currentIndex()!=current:
            self.language_combo.blockSignals(True); self.language_combo.setCurrentIndex(current); self.language_combo.blockSignals(False)
        self._update_speed_combo()
        self._set_status(d["status_idle"],"muted")
        self._render_log_history()

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
        self.settings.setValue("recent_files",self.recent_files[:MAX_RECENT]); self.settings.setValue("verify_output",self.verify_output_check.isChecked()); self.settings.setValue("window_size",self.size()); self.settings.setValue("window_position",self.pos()); self.settings.sync()

    def _verify_output_changed(self, checked: bool) -> None:
        self.verify_output_default = bool(checked)
        self.settings.setValue("verify_output", self.verify_output_default)

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

    @staticmethod
    def _rounded_polygon_path(
        points: list[QPointF], rounded_vertices: set[int], radius: float
    ) -> QPainterPath:
        """Keep a polygon's original silhouette while softly rounding selected corners."""
        count = len(points)
        path = QPainterPath()
        if count < 3:
            return path

        def distance(first: QPointF, second: QPointF) -> float:
            dx = second.x() - first.x()
            dy = second.y() - first.y()
            return (dx * dx + dy * dy) ** 0.5

        def toward(vertex: QPointF, neighbor: QPointF, amount: float) -> QPointF:
            length = distance(vertex, neighbor)
            if length <= 1e-9:
                return QPointF(vertex)
            factor = min(1.0, amount / length)
            return QPointF(
                vertex.x() + (neighbor.x() - vertex.x()) * factor,
                vertex.y() + (neighbor.y() - vertex.y()) * factor,
            )

        def corner_points(index: int) -> tuple[QPointF, QPointF]:
            previous = points[(index - 1) % count]
            vertex = points[index]
            following = points[(index + 1) % count]
            # A short radius softens the join without moving the adjoining edges.
            cut = min(
                radius,
                distance(vertex, previous) * 0.22,
                distance(vertex, following) * 0.22,
            )
            return toward(vertex, previous, cut), toward(vertex, following, cut)

        if 0 in rounded_vertices:
            first_start, first_end = corner_points(0)
            path.moveTo(first_start)
            path.quadTo(points[0], first_end)
        else:
            path.moveTo(points[0])

        for index in range(1, count):
            if index in rounded_vertices:
                corner_start, corner_end = corner_points(index)
                path.lineTo(corner_start)
                path.quadTo(points[index], corner_end)
            else:
                path.lineTo(points[index])

        path.closeSubpath()
        return path

    def _frame_paths(self) -> tuple[QPainterPath, QPainterPath]:
        """Return the original angular shell, with only its left corners softened."""
        w, h = float(self.width()), float(self.height())

        # Preserve the pre-Stage-6 outer silhouette and coordinates. Only the
        # left-side joins receive a small 8 px radius; the right/top/bottom
        # geometry remains angular as in the previous application design.
        outer_points = [
            QPointF(60, 3),
            QPointF(w - 30, 3),
            QPointF(w - 3, 19),
            QPointF(w - 55, h - 58),
            QPointF(w - 24, h - 23),
            QPointF(w - 190, h - 3),
            QPointF(58, h - 3),
            QPointF(3, h - 21),
            QPointF(37, h * 0.67),
            QPointF(3, h * 0.47),
            QPointF(35, h * 0.23),
        ]
        left_corners = {0, 6, 7, 8, 9, 10}
        outer = self._rounded_polygon_path(outer_points, left_corners, 8.0)

        # Keep the original inset line, with a smaller radius to follow the
        # outer contour without changing the visible frame thickness.
        inner_points = [
            QPointF(61, 13),
            QPointF(w - 40, 13),
            QPointF(w - 22, 25),
            QPointF(w - 47, h - 80),
            QPointF(w - 25, h - 34),
            QPointF(w - 160, h - 19),
            QPointF(57, h - 19),
            QPointF(37, h - 31),
            QPointF(72, h * 0.68),
            QPointF(28, h * 0.47),
            QPointF(47, h * 0.24),
        ]
        inner = self._rounded_polygon_path(inner_points, left_corners, 5.0)
        return outer, inner

    def resizeEvent(self, event) -> None:  # noqa: N802
        # Keep the widget unmasked so Qt can antialias the slanted outline.
        # The original polygon layout margins keep child controls inside it.
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        w, h = self.width(), self.height()
        outer, inner = self._frame_paths()

        gradient = QLinearGradient(0, 0, w, h)
        gradient.setColorAt(0, QColor("#0b1420"))
        gradient.setColorAt(0.48, QColor("#07111b"))
        gradient.setColorAt(1, QColor("#101e2b"))
        painter.fillPath(outer, QBrush(gradient))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # Keep all dark/secondary frame strokes strictly inside the yellow
        # silhouette. A wide stroke centered on the outer path used to extend
        # several pixels beyond the yellow contour near the lower-right bevel.
        # Clipping it to the filled outer path preserves the dark inner edge
        # while preventing any blue pixels from escaping past the yellow line.
        painter.save()
        painter.setClipPath(outer, Qt.ClipOperation.IntersectClip)
        painter.setPen(QPen(
            QColor("#0c1721"), 8.0, Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin,
        ))
        painter.drawPath(outer)
        painter.setPen(QPen(
            QColor(255, 225, 123, 120), 1.0, Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin,
        ))
        painter.drawPath(inner)
        painter.restore()

        # The yellow outline is the outermost visible frame edge.
        painter.setPen(QPen(
            QColor(COLORS["yellow"]), 3.2, Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.MiterJoin,
        ))
        painter.drawPath(outer)

        # Original cyan corner accents and center ticks are retained.
        painter.setPen(QPen(QColor(33, 217, 239, 70), 1.0))
        painter.drawLine(QPointF(70, h * 0.31), QPointF(46, h * 0.38))
        painter.drawLine(QPointF(46, h * 0.38), QPointF(46, h * 0.49))
        painter.drawLine(QPointF(w - 52, h * 0.33), QPointF(w - 36, h * 0.38))
        painter.drawLine(QPointF(w - 36, h * 0.38), QPointF(w - 48, h * 0.52))
        painter.setPen(QPen(
            QColor(33, 217, 239, 140), 2.0,
            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
        ))
        painter.drawLine(QPointF(36, h * 0.47), QPointF(62, h * 0.47))
        painter.drawLine(QPointF(w - 60, h * 0.47), QPointF(w - 38, h * 0.47))

    def _infer_log_category(self, message: str) -> str:
        text = str(message).casefold()
        if "preflight" in text or "предварительн" in text:
            return "preflight"
        if "verify" in text or "verification" in text or "провер" in text and "raw" in text:
            return "verification"
        if "merge" in text or "объедин" in text:
            return "merge"
        if "queue" in text or "batch" in text or "очеред" in text or "пакетн" in text:
            return "queue"
        if "analysis" in text or "inspect" in text or "анализ" in text:
            return "analysis"
        if "convert" in text or "conversion" in text or "конверт" in text or "преобраз" in text:
            return "conversion"
        return "application"

    def _insert_log_line(self, level: str, message: str, timestamp: str) -> None:
        colors = {"success": COLORS["green"], "error": COLORS["red"], "warning": COLORS["amber"], "info": COLORS["cyan"], "debug": COLORS["muted"]}
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        dot = QTextCharFormat(); dot.setForeground(QColor(colors.get(level, COLORS["text"])))
        timefmt = QTextCharFormat(); timefmt.setForeground(QColor(COLORS["muted"]))
        msgfmt = QTextCharFormat(); msgfmt.setForeground(QColor(COLORS["text"]))
        cursor.insertText("● ", dot)
        cursor.insertText(f"[{timestamp}] ", timefmt)
        cursor.insertText(localize_log_message(message, self.language), msgfmt)
        cursor.insertText("\n")
        self.log_view.setTextCursor(cursor)
        self.log_view.ensureCursorVisible()

    def _render_log_history(self) -> None:
        if not hasattr(self, "log_view"):
            return
        self.log_view.clear()
        events = self.diagnostic_store.entries()[-2500:]
        for event in events:
            try:
                timestamp = datetime.fromisoformat(str(event.get("timestamp", ""))).strftime("%H:%M:%S")
            except (ValueError, TypeError):
                timestamp = "--:--:--"
            self._insert_log_line(
                str(event.get("level", "info")),
                str(event.get("message", "")),
                timestamp,
            )

    def append_log(self, level: str, message: str, *, category: str | None = None, details: dict[str, Any] | None = None) -> None:
        original_message = str(message)
        timestamp = datetime.now().strftime("%H:%M:%S")
        resolved_category = category or self._infer_log_category(original_message)
        self.diagnostic_store.append(level, resolved_category, original_message, details)
        self._insert_log_line(level, original_message, timestamp)

    def record_operation_metrics(self, category: str, status: str, metrics: dict[str, Any] | None, *, source: str = "", error: str = "") -> None:
        metrics = metrics or {}
        duration = float(metrics.get("duration_seconds", 0.0) or 0.0)
        processed = int(metrics.get("processed_bytes", 0) or 0)
        output_bytes = int(metrics.get("output_bytes", 0) or 0)
        chunks = int(metrics.get("chunks", 0) or 0)
        speed = float(metrics.get("average_bytes_per_second", (processed / duration if duration > 0 else 0.0)) or 0.0)
        details = {
            "status": status,
            "duration_seconds": round(max(duration, 0.0), 6),
            "processed_bytes": max(processed, 0),
            "output_bytes": max(output_bytes, 0),
            "chunks": max(chunks, 0),
            "average_bytes_per_second": round(max(speed, 0.0), 2),
            "source_name": Path(source).name if source else "",
        }
        if error:
            details["error"] = error[:2000]
        level = "success" if status == "success" else "warning" if status in {"cancelled", "skipped"} else "error"
        self.append_log(level, f"{category.title()} task {status}", category=category, details=details)

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
        self.analyze_button.setEnabled(not busy); self.structure_button.setEnabled(not busy); self.queue_button.setEnabled(not busy); self.merge_button.setEnabled(not busy); self.recent_combo.setEnabled(not busy)
        self.verify_output_check.setEnabled(not busy)
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
        force=False
        if destination.exists():
            if QMessageBox.question(self,self.t("confirm_title"),self.t("confirm_overwrite").format(path=destination),QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)!=QMessageBox.StandardButton.Yes:
                self.append_log("warning","Conversion cancelled; existing output preserved."); return
            force=True
        try:
            preflight = preflight_output([source], destination, operation="convert", force=force)
        except Exception as exc:
            self.append_log("error", f"Preflight failed: {type(exc).__name__}: {exc}")
            self._set_status(I18N[self.language]["status_error"],"red")
            QMessageBox.warning(
                self, self.t("window_title"),
                f"{friendly_error(str(exc), self.language)}\n\nDetails: {exc}",
            )
            return
        self.append_log(
            "success",
            "Preflight passed: "
            f"{format_bytes(preflight['available_free_bytes'], self.language)} free; "
            f"{format_bytes(preflight['required_free_bytes'], self.language)} required including safety margin.",
        )
        self.last_result=None; self.report_button.setEnabled(False); self.progress_bar.setValue(0); self.progress_percent.setText("0%"); self.speed_label.setText("Preparing…" if self.language=="en" else "Подготовка…")
        self.chunks_label.setText(f"{self.t('chunks')}\n0 / reading header…"); self.size_label.setText(f"{self.t('size')}\n0 B / {format_bytes(expected_size,self.language)}"); self._set_status(I18N[self.language]["status_preparing"],"cyan")
        self.append_log("info",f"Input: {source}"); self.append_log("info",f"Output: {destination}"); self.append_log("info",f"Expected RAW size: {format_bytes(expected_size,self.language)}")
        worker=ConversionWorkerObject(source,destination,force,verify_output=self.verify_output_check.isChecked()); self._worker=worker; worker.progress.connect(self._on_progress); worker.log.connect(self.append_log); worker.succeeded.connect(self._on_success); worker.failed.connect(self._on_failure); worker.cancelled.connect(self._on_cancelled)
        thread=connect_worker(worker,self,self._on_thread_finished); self._thread=thread; self._set_busy(True); thread.start()

    @Slot(dict)
    def _on_progress(self,data:dict) -> None:
        self._last_progress=data; percent=int(data.get("percent",0)); self.progress_bar.setValue(max(0,min(100,percent))); self.progress_percent.setText(f"{percent}%")
        chunks=int(data.get("processed_chunks",0)); total=int(data.get("total_chunks",0)); self._total_chunks=total
        self.chunks_label.setText(f"{self.t('chunks')}\n{chunks:,} / {total:,}".replace(","," "))
        processed=int(data.get("processed_bytes",0)); expected=int(data.get("expected_bytes",self._expected_size))
        if data.get("stage") == "verification":
            self.size_label.setText(f"{self.t('verify_progress')}\n{format_bytes(processed,self.language)} / {format_bytes(expected,self.language)}")
        else:
            self.size_label.setText(f"{self.t('size')}\n{format_bytes(processed,self.language)} / {format_bytes(expected,self.language)}")
        speed=float(data.get("speed_bytes_per_second",0)); self.speed_label.setText(format_speed(speed,self.speed_unit,self.language) if speed>0 else ("Preparing…" if self.language=="en" else "Подготовка…"))

    @Slot(dict)
    def _on_success(self,result:dict) -> None:
        self.last_result=result; self.report_button.setEnabled(True); size=int(result.get("output_size_bytes",result.get("raw_size_bytes",0))); expected=int(result.get("raw_size_bytes",self._expected_size)); chunks=int(result.get("total_chunks",self._total_chunks))
        self.record_operation_metrics("conversion", "success", result.get("operation_metrics", {}), source=Path(str(result.get("input", self.source_edit.text()))).name)
        old_speed = float(self._last_progress.get("speed_bytes_per_second", 0.0))
        self._last_progress = {"percent": 100, "processed_chunks": chunks, "total_chunks": chunks,
                               "processed_bytes": size, "expected_bytes": expected,
                               "speed_bytes_per_second": old_speed}
        self.progress_bar.setValue(100); self.progress_percent.setText("100%"); self.chunks_label.setText(f"{self.t('chunks')}\n{chunks:,} / {chunks:,}".replace(","," ")); self.size_label.setText(f"{self.t('size')}\n{format_bytes(size,self.language)} / {format_bytes(expected,self.language)}"); self.speed_label.setText(self.t("done"))
        destination=result.get("output") or self.output_edit.text(); self._set_status(I18N[self.language]["status_success"],"green"); self.append_log("success",f"Output saved: {destination}")
        verification=result.get("output_verification")
        if verification and verification.get("passed"):
            self.append_log("success", f"{self.t('verify_passed')}: {format_bytes(verification['verified_bytes'], self.language)}")
            self.append_log("success", f"Verified output SHA-256: {verification['actual_sha256']}")
        if result.get("sha256"): self.append_log("success",f"Logical RAW SHA-256: {result['sha256']}")
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
    def _open_diagnostics(self) -> None:
        dialog = DiagnosticCenterDialog(self)
        dialog.show()
        self._keep_dialog(dialog)

    def _open_qfil(self) -> None:
        dialog=QFILDialog(self); dialog.show(); self._keep_dialog(dialog)
    def _open_analysis(self) -> None:
        dialog=AnalysisDialog(self,self.source_edit.text().strip()); dialog.show(); self._keep_dialog(dialog)
    def _open_structure(self) -> None:
        dialog=SparseStructureDialog(self,self.source_edit.text().strip()); dialog.show(); self._keep_dialog(dialog)
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
    set_windows_app_user_model_id()
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
