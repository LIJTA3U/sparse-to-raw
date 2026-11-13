"""Headless smoke tests for the optional PySide6 desktop interface."""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import zlib
from pathlib import Path

# Support both `python tests/gui_smoke_tests.py` and unittest discovery from
# the repository root on Windows, where sys.path[0] is the tests directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sparse_to_raw import APP_VERSION as CORE_APP_VERSION, ConversionCancelled, inspect_sparse, read_sparse_chunk_page  # noqa: E402
from diagnostics import DiagnosticStore  # noqa: E402

from sparse_to_raw_gui import (  # noqa: E402
    BatchQueueDialog,
    ImageComparisonDialog,
    SparseValidatorDialog,
    SparseValidatorWorker,
    RawToSparseDialog,
    DiagnosticCenterDialog,
    BatchWorkerObject,
    ConversionWorkerObject,
    MainWindow,
    MergeDialog,
    SparseStructureDialog,
    SparseStructureWorker,
    SparseStructureExportWorker,
    APP_USER_MODEL_ID,
    APP_VERSION,
    localize_log_message,
    format_speed,
    resource_path,
    suggested_output_path,
    validate_paths,
)

SPARSE_HEADER = struct.Struct("<IHHHHIIII")
SPARSE_MAGIC = 0xED26FF3A


def write_sparse_header(path: Path, *, blocks: int = 4, block_size: int = 4096) -> None:
    """Write a minimal declared header for path-validation tests."""
    path.write_bytes(
        SPARSE_HEADER.pack(
            SPARSE_MAGIC,
            1,
            0,
            SPARSE_HEADER.size,
            12,
            block_size,
            blocks,
            1,
            0,
        )
    )


def write_valid_sparse_image(path: Path) -> None:
    """Write a tiny complete Sparse v1 image with one RAW chunk and valid CRC."""
    raw = b"DATA"
    header = SPARSE_HEADER.pack(
        SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1,
        zlib.crc32(raw) & 0xFFFFFFFF,
    )
    path.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)


class SparseToRawGuiTests(unittest.TestCase):
    def test_gui_and_cli_share_application_version(self) -> None:
        self.assertEqual(APP_VERSION, CORE_APP_VERSION)

    @classmethod
    def setUpClass(cls) -> None:
        cls._diagnostics_temp = tempfile.TemporaryDirectory()
        cls._previous_diagnostics_dir = os.environ.get("SPARSE_TO_RAW_DIAGNOSTICS_DIR")
        os.environ["SPARSE_TO_RAW_DIAGNOSTICS_DIR"] = cls._diagnostics_temp.name
        cls.app = QApplication.instance() or QApplication(["sparse-to-raw-gui-tests"])

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._previous_diagnostics_dir is None:
            os.environ.pop("SPARSE_TO_RAW_DIAGNOSTICS_DIR", None)
        else:
            os.environ["SPARSE_TO_RAW_DIAGNOSTICS_DIR"] = cls._previous_diagnostics_dir
        cls._diagnostics_temp.cleanup()

    def test_main_window_builds_diagnostics_button(self) -> None:
        window = MainWindow()
        try:
            self.assertTrue(hasattr(window, "diagnostics_button"))
            self.assertTrue(hasattr(window, "validator_button"))
            self.assertEqual(window.validator_button.text(), window.t("validator_button"))
            self.assertEqual(window.diagnostics_button.text(), window.t("diagnostics_button"))
            self.assertIsInstance(window.diagnostic_store, DiagnosticStore)
        finally:
            window.close()

    def test_image_comparison_dialog_is_available_from_main_window(self) -> None:
        window = MainWindow()
        dialog = ImageComparisonDialog(window)
        try:
            self.assertTrue(hasattr(window, "compare_button"))
            self.assertEqual(window.compare_button.text(), window.t("compare_button"))
            self.assertEqual(dialog.compare_button.text(), window.t("compare_start"))
            self.assertFalse(dialog.cancel_button.isEnabled())
            self.assertFalse(dialog.save_button.isEnabled())
        finally:
            dialog.close()
            window.close()

    def test_sparse_validator_dialog_is_available_from_main_window(self) -> None:
        window = MainWindow()
        dialog = SparseValidatorDialog(window)
        try:
            self.assertEqual(window.validator_button.text(), window.t("validator_button"))
            self.assertEqual(dialog.validate_button.text(), window.t("validator_start"))
            self.assertFalse(dialog.cancel_button.isEnabled())
            self.assertFalse(dialog.save_button.isEnabled())
        finally:
            dialog.close()
            window.close()

    def test_sparse_validator_worker_returns_validation_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "valid.sparse"
            write_valid_sparse_image(source)
            worker = SparseValidatorWorker(source)
            results: list[dict] = []
            failures: list[str] = []
            worker.succeeded.connect(results.append)
            worker.failed.connect(failures.append)
            worker.run()
            self.assertEqual(failures, [])
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["valid"])
            self.assertEqual(results[0]["operation"], "sparse-validation")

    def test_main_window_sets_application_icon_and_keeps_smooth_custom_frame(self) -> None:
        window = MainWindow()
        try:
            self.assertEqual(APP_USER_MODEL_ID, "LIJTA3U.sparse-to-raw")
            self.assertFalse(window.windowIcon().isNull())
            self.assertFalse(self.app.windowIcon().isNull())
            self.assertFalse(window.qfil_icon().isNull())
            self.assertFalse(window.qfil_button.icon().isNull())
            outer, inner = window._frame_paths()
            self.assertGreater(outer.elementCount(), 8)
            self.assertGreater(inner.elementCount(), 8)
            # The shell is painted with QPainter antialiasing rather than an integer QRegion clip.
            self.assertTrue(window.mask().isEmpty())
        finally:
            window.close()

    def test_main_toolbar_uses_two_rows_for_actions_and_controls(self) -> None:
        window = MainWindow()
        try:
            window.resize(1120, 760)
            window.show()
            self.app.processEvents()
            self.assertEqual(window.toolbar_layout.count(), 2)
            self.assertEqual(window.toolbar_actions_top.count(), 4)
            self.assertGreaterEqual(window.toolbar_actions_bottom.count(), 8)
            top_buttons = [window.qfil_button, window.analyze_button,
                           window.structure_button, window.queue_button]
            bottom_buttons = [window.validator_button, window.raw_sparse_button, window.compare_button,
                              window.merge_button, window.report_button, window.diagnostics_button]
            self.assertTrue(all(button.isVisible() for button in top_buttons + bottom_buttons))
            self.assertLess(max(button.geometry().bottom() for button in top_buttons),
                            min(button.geometry().top() for button in bottom_buttons))
        finally:
            window.close()

    def test_operation_log_retranslates_known_messages_when_language_changes(self) -> None:
        window = MainWindow()
        try:
            window.language = "ru"
            window.append_log("info", "Interface ready. Choose an Android Sparse Image.")
            self.assertIn("Интерфейс готов", window.log_view.toPlainText())
            window.append_log("info", "Batch started: 3 file(s).", category="queue")
            self.assertIn("Пакетная обработка начата", window.log_view.toPlainText())
            window.language = "en"
            window._render_log_history()
            self.assertIn("Interface ready. Choose an Android Sparse Image.", window.log_view.toPlainText())
            self.assertIn("Batch started: 3 file(s).", window.log_view.toPlainText())
            self.assertIn("Задание", localize_log_message("Conversion task success", "ru"))
            self.assertEqual(
                localize_log_message("Queue paused between tasks.", "ru"),
                "Очередь приостановлена между заданиями.",
            )
            self.assertEqual(
                localize_log_message("Merge cancelled; staged output discarded.", "ru"),
                "Объединение отменено; временный результат удалён.",
            )
            self.assertIn(
                "Нет доступа",
                localize_log_message("Preflight failed: PermissionError: denied", "ru"),
            )
            self.assertEqual(
                localize_log_message("Очередь продолжена.", "en"),
                "Queue resumed.",
            )
            self.assertEqual(
                localize_log_message("Отмена запрошена; временный результат будет удалён.", "en"),
                "Cancellation requested; the temporary output will be removed.",
            )
        finally:
            window.close()

    def test_sparse_structure_viewer_displays_verified_chunk_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "viewer.sparse"
            write_valid_sparse_image(source)
            window = MainWindow()
            dialog = SparseStructureDialog(window, str(source))
            try:
                window.language = "ru"
                summary = inspect_sparse(source, calculate_sha256=True)
                page = read_sparse_chunk_page(source, offset=0, limit=dialog.PAGE_SIZE)
                signature = dialog._file_signature(source)
                dialog._on_loaded({"summary": summary, "page": page, "signature": signature})
                self.assertEqual(dialog.table.rowCount(), 1)
                self.assertEqual(dialog.table.item(0, 1).text(), "RAW")
                self.assertEqual(dialog.table.item(0, 8).text(), "Проверено")
                self.assertTrue(dialog.export_csv_button.isEnabled())
                self.assertTrue(dialog.export_json_button.isEnabled())
                self.assertIn("RAW", dialog.details_view.toPlainText())
            finally:
                dialog.close()
                window.close()

    def test_sparse_structure_worker_rejects_input_changed_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "changed.sparse"
            write_valid_sparse_image(source)
            signature = SparseStructureWorker._signature(source)
            worker = SparseStructureWorker(
                source, offset=0, limit=200, chunk_type="ALL", search="",
                validate=False, validated_metadata={"total_chunks": 1},
                expected_signature=signature,
            )
            loaded: list[dict] = []
            failed: list[str] = []
            worker.loaded.connect(loaded.append)
            worker.failed.connect(failed.append)
            source.write_bytes(source.read_bytes() + b"changed")
            worker.run()
            self.assertEqual(loaded, [])
            self.assertTrue(failed)
            self.assertIn("changed after validation", failed[0])

    def test_sparse_structure_export_worker_rejects_source_changed_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "changed-export.sparse"
            output = root / "changed-export.csv"
            write_valid_sparse_image(source)
            summary = inspect_sparse(source, calculate_sha256=True)
            signature = SparseStructureWorker._signature(source)
            worker = SparseStructureExportWorker(source, output, "csv", summary, signature, False)
            failures: list[str] = []
            worker.failed.connect(failures.append)
            source.write_bytes(source.read_bytes() + b"changed")
            worker.run()
            self.assertTrue(failures)
            self.assertIn("changed after validation", failures[0])
            self.assertFalse(output.exists())

    def test_sparse_structure_export_worker_exports_in_background_and_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "export.sparse"
            output = root / "export.csv"
            write_valid_sparse_image(source)
            summary = inspect_sparse(source, calculate_sha256=True)
            signature = SparseStructureWorker._signature(source)
            worker = SparseStructureExportWorker(source, output, "csv", summary, signature, False)
            reports: list[dict] = []
            failures: list[str] = []
            progress: list[dict] = []
            worker.succeeded.connect(reports.append)
            worker.failed.connect(failures.append)
            worker.progress.connect(progress.append)
            worker.run()
            self.assertEqual(failures, [])
            self.assertEqual(len(reports), 1)
            self.assertTrue(output.is_file())
            self.assertEqual(reports[0]["chunks_exported"], 1)
            self.assertEqual(progress[-1]["percent"], 100)

    def test_diagnostic_center_filters_and_displays_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            window = MainWindow()
            window.diagnostic_store = DiagnosticStore(Path(temporary) / "diagnostics")
            try:
                window.diagnostic_store.append("error", "conversion", "Bad image header", {"chunks": 2})
                window.diagnostic_store.append("info", "queue", "Queue started", {"total": 3})
                dialog = DiagnosticCenterDialog(window)
                try:
                    self.assertEqual(dialog.table.rowCount(), 2)
                    dialog.level_combo.setCurrentIndex(dialog.level_combo.findData("error"))
                    self.assertEqual(dialog.table.rowCount(), 1)
                    self.assertEqual(dialog.table.item(0, 1).text(), "ERROR")
                    dialog.level_combo.setCurrentIndex(dialog.level_combo.findData("all"))
                    dialog.category_combo.setCurrentIndex(dialog.category_combo.findData("queue"))
                    self.assertEqual(dialog.table.rowCount(), 1)
                    dialog.search_edit.setText("started")
                    self.assertEqual(dialog.table.rowCount(), 1)
                    dialog.search_edit.setText("not-found")
                    self.assertEqual(dialog.table.rowCount(), 0)
                finally:
                    dialog.close()
            finally:
                window.close()

    def test_suggested_output_name(self) -> None:
        self.assertEqual(
            Path(suggested_output_path(r"C:\firmware\super.img")),
            Path(r"C:\firmware\super_raw.img"),
        )
        self.assertEqual(
            Path(suggested_output_path("/tmp/system.sparse")),
            Path("/tmp/system_raw.img"),
        )

    def test_validate_paths_returns_expected_raw_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "super.img"
            destination = root / "super_raw.img"
            write_sparse_header(source, blocks=8, block_size=4096)
            checked_source, checked_destination, expected_size = validate_paths(str(source), str(destination))
            self.assertEqual(checked_source, source.resolve())
            self.assertEqual(checked_destination, destination.resolve())
            self.assertEqual(expected_size, 8 * 4096)
            self.assertFalse(destination.exists())

    def test_validate_paths_rejects_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "super.img"
            write_sparse_header(source)
            with self.assertRaisesRegex(ValueError, "различаться|один файл"):
                validate_paths(str(source), str(source))

    def test_validate_paths_rejects_missing_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "out.img"
            with self.assertRaisesRegex(FileNotFoundError, "не найден"):
                validate_paths(str(Path(temporary) / "missing.img"), str(output))

    def test_main_window_builds_with_drag_drop_and_expected_controls(self) -> None:
        window = MainWindow()
        try:
            self.assertEqual(window.windowTitle(), "sparse-to-raw")
            self.assertTrue(window.drop_zone.acceptDrops())
            self.assertEqual(window.convert_button.text(), "ПРЕОБРАЗОВАТЬ")
            self.assertTrue(window.source_edit.isEnabled())
            self.assertEqual(window.progress_bar.value(), 0)
            self.assertIn("Журнал операций", [label.text() for label in window.findChildren(type(window.status_label))])
        finally:
            window.close()


    def test_worker_integrates_existing_converter_and_emits_real_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "sample.sparse"
            destination = root / "sample_raw.img"
            raw = b"DATA"
            header = SPARSE_HEADER.pack(
                SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF
            )
            chunk_header = struct.pack("<HHII", 0xCAC1, 0, 1, 16)
            source.write_bytes(header + chunk_header + raw)

            worker = ConversionWorkerObject(source, destination, False)
            results: list[dict] = []
            failures: list[str] = []
            progress: list[dict] = []
            events: list[tuple[str, str]] = []
            worker.succeeded.connect(results.append)
            worker.failed.connect(failures.append)
            worker.progress.connect(progress.append)
            worker.log.connect(lambda level, message: events.append((level, message)))

            # Run the worker synchronously in this smoke test; production moves it to QThread.
            worker.run()

            self.assertEqual(failures, [])
            self.assertEqual(len(results), 1)
            self.assertEqual(destination.read_bytes(), raw)
            self.assertEqual(results[0]["output_size_bytes"], len(raw))
            self.assertTrue(any(item.get("percent") == 100 for item in progress))
            self.assertTrue(any("общей контрольной суммы" in message.lower() for _, message in events))


    def test_speed_units_support_decimal_binary_and_bits(self) -> None:
        self.assertEqual(format_speed(1_000_000, "MB/s", "en"), "1.00 MB/s")
        self.assertEqual(format_speed(1_048_576, "MiB/s", "en"), "1.00 MiB/s")
        self.assertEqual(format_speed(1_000_000, "Mbit/s", "en"), "8.00 Mbit/s")

    def test_language_switch_and_settings_widgets(self) -> None:
        window = MainWindow()
        try:
            english_index = window.language_combo.findData("en")
            window.language_combo.setCurrentIndex(english_index)
            self.assertEqual(window.main_heading.text(), "Image conversion")
            self.assertEqual(window.convert_button.text(), "CONVERT")
            window.speed_combo.setCurrentIndex(window.speed_combo.findData("Mbit/s"))
            window.language_combo.setCurrentIndex(window.language_combo.findData("ru"))
            self.assertEqual(window.main_heading.text(), "Преобразование образа")
            self.assertIn(window.speed_combo.currentData(), {"MB/s", "MiB/s", "Mbit/s"})
            self.assertGreaterEqual(window.source_browse_button.iconSize().width(), 20)
            self.assertTrue(resource_path("assets/sparse-to-raw.ico").is_file())
        finally:
            window.close()
        reopened = MainWindow()
        try:
            self.assertEqual(reopened.language, "ru")
            self.assertEqual(reopened.speed_unit, "Mbit/s")
            reopened.speed_combo.setCurrentIndex(reopened.speed_combo.findData("MiB/s"))
        finally:
            reopened.close()

    def test_merge_dialog_discovers_and_numerically_orders_sparse_parts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index in [10, 2, 1, 0, 9, 8, 7, 6, 5, 4, 3]:
                write_sparse_header(root / f"super.img_sparsechunk.{index}")

            window = MainWindow()
            dialog = MergeDialog(window)
            try:
                self.assertTrue(any(button.text() == window.t("discover_folder") for button in dialog.part_controls))
                from unittest.mock import patch
                with patch("sparse_to_raw_gui.QFileDialog.getExistingDirectory", return_value=str(root)):
                    dialog._discover()
                names = [Path(dialog.parts.item(i).data(Qt.ItemDataRole.UserRole)).name for i in range(dialog.parts.count())]
                self.assertEqual(names, [f"super.img_sparsechunk.{index}" for index in range(11)])
            finally:
                dialog.close()
                window.close()

    def test_merge_dialog_does_not_auto_add_incomplete_sparse_set(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_sparse_header(root / "super.img_sparsechunk.0")
            write_sparse_header(root / "super.img_sparsechunk.2")

            window = MainWindow()
            dialog = MergeDialog(window)
            try:
                from unittest.mock import patch
                from PySide6.QtWidgets import QMessageBox
                with patch("sparse_to_raw_gui.QFileDialog.getExistingDirectory", return_value=str(root)), \
                     patch("sparse_to_raw_gui.QMessageBox.warning") as warning:
                    dialog._discover()
                self.assertEqual(dialog.parts.count(), 0)
                warning.assert_called_once()
                self.assertIn("1", warning.call_args.args[2])
            finally:
                dialog.close()
                window.close()

    def test_main_window_verification_option_is_enabled_by_default(self) -> None:
        window = MainWindow()
        try:
            current = window.verify_output_check.isChecked()
            self.assertTrue(window.verify_output_check.text())
            window.verify_output_check.setChecked(not current)
            self.assertEqual(window.settings.value("verify_output", type=bool), not current)
            window.verify_output_check.setChecked(current)
        finally:
            window.close()

    def test_main_conversion_passes_verification_setting_to_worker(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.sparse"
            output = root / "output.raw"
            window = MainWindow()
            window.source_edit.setText(str(source))
            window.output_edit.setText(str(output))
            window.verify_output_check.setChecked(True)
            fake_thread = SimpleNamespace(start=lambda: None, isRunning=lambda: False)
            try:
                with patch("sparse_to_raw_gui.validate_paths", return_value=(source, output, 4096)), \
                     patch("sparse_to_raw_gui.preflight_output", return_value={"available_free_bytes": 8192, "required_free_bytes": 4096}), \
                     patch("sparse_to_raw_gui.ConversionWorkerObject") as worker_factory, \
                     patch("sparse_to_raw_gui.connect_worker", return_value=fake_thread):
                    window._start_conversion()
                    worker_factory.assert_called_once_with(source, output, False, verify_output=True)
                    self.assertFalse(window.verify_output_check.isEnabled())
            finally:
                window._set_busy(False)
                window._thread = None
                window._worker = None
                window.close()

    def test_conversion_worker_returns_output_verification_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.sparse"
            output = root / "output.raw"
            raw_data = b"A" * (4 * 4096)
            header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4096, 4, 1, zlib.crc32(raw_data) & 0xFFFFFFFF)
            source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 4, 12 + len(raw_data)) + raw_data)
            worker = ConversionWorkerObject(source, output, False, verify_output=True)
            results: list[dict] = []
            errors: list[str] = []
            worker.succeeded.connect(results.append)
            worker.failed.connect(errors.append)
            worker.run()
            self.assertFalse(errors, errors)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["output_verification"]["passed"])

    def test_raw_to_sparse_worker_encodes_and_reports_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.raw"
            output = root / "output.sparse"
            source.write_bytes(b"A" * 4096 + b"\0" * 4096)
            worker = ConversionWorkerObject(source, output, False, operation="raw_to_sparse")
            worker.block_size = 4096
            results: list[dict] = []
            failures: list[str] = []
            worker.succeeded.connect(results.append)
            worker.failed.connect(failures.append)
            worker.run()
            self.assertEqual(failures, [])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["input_size_bytes"], 8192)
            self.assertEqual(results[0]["chunk_counts"]["FILL"], 1)
            self.assertEqual(results[0]["chunk_counts"]["DONT_CARE"], 1)
            self.assertEqual(output.read_bytes()[:4], struct.pack("<I", SPARSE_MAGIC))

    def test_batch_worker_supports_raw_to_sparse_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "queued.raw"
            output = root / "queued.sparse"
            source.write_bytes(b"Z" * 4096)
            worker = BatchWorkerObject([source], root / "unused", False,
                task_ids=["raw-task"], raw_to_sparse_configs={"raw-task": {"output": str(output), "block_size": 4096}})
            reports: list[dict] = []
            worker.finished_report.connect(reports.append)
            worker.run()
            self.assertTrue(output.is_file())
            self.assertEqual(reports[0]["summary"]["success"], 1)
            self.assertEqual(reports[0]["items"][0]["task_type"], "raw_to_sparse")

    def test_main_window_exposes_raw_to_sparse_action(self) -> None:
        window = MainWindow()
        try:
            self.assertTrue(hasattr(window, "raw_sparse_button"))
            self.assertEqual(window.raw_sparse_button.text(), window.t("raw_sparse"))
        finally:
            window.close()

    def test_recent_file_list_is_most_recent_first_and_bounded(self) -> None:
        window = MainWindow()
        try:
            for i in range(15):
                window.add_recent(str(Path(tempfile.gettempdir()) / f"recent-{i}.img"))
            self.assertEqual(len(window.recent_files), 12)
            self.assertTrue(window.recent_files[0].endswith("recent-14.img"))
            self.assertTrue(window.recent_files[-1].endswith("recent-3.img"))
        finally:
            window.close()

    def test_inspection_worker_returns_metadata_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.sparse"
            raw = b"DATA"
            header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
            source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
            worker = ConversionWorkerObject(source, None, False, operation="inspect")
            results: list[dict] = []
            failures: list[str] = []
            worker.succeeded.connect(results.append)
            worker.failed.connect(failures.append)
            worker.run()
            self.assertEqual(failures, [])
            self.assertEqual(results[0]["raw_size_bytes"], 4)
            self.assertEqual(results[0]["chunk_counts"]["RAW"], 1)
            self.assertFalse((root / "input_raw.img").exists())

    def test_batch_worker_converts_sequentially_and_writes_json_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "queued.sparse"
            raw = b"DATA"
            header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
            source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
            output = root / "out"
            output.mkdir()
            worker = BatchWorkerObject([source], output, False)
            reports: list[dict] = []
            worker.finished_report.connect(reports.append)
            worker.run()
            self.assertEqual((output / "queued_raw.img").read_bytes(), raw)
            self.assertEqual(reports[0]["summary"]["success"], 1)
            self.assertTrue(Path(reports[0]["report_path"]).is_file())
            saved = __import__("json").loads(Path(reports[0]["report_path"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["items"][0]["status"], "success")


    def test_batch_worker_can_verify_each_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "batch.sparse"
            output_dir = root / "out"
            output_dir.mkdir()
            raw_data = b"B" * (4 * 4096)
            header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4096, 4, 1, zlib.crc32(raw_data) & 0xFFFFFFFF)
            source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 4, 12 + len(raw_data)) + raw_data)
            worker = BatchWorkerObject([source], output_dir, False, verify_output=True)
            reports: list[dict] = []
            worker.finished_report.connect(reports.append)
            worker.run()
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0]["summary"]["success"], 1)
            verification = reports[0]["items"][0]["result"]["output_verification"]
            self.assertTrue(verification["passed"])

    def test_batch_worker_rejects_duplicate_output_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_dir = root / "one"
            second_dir = root / "two"
            output = root / "out"
            first_dir.mkdir(); second_dir.mkdir(); output.mkdir()
            raw = b"DATA"
            header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
            payload = header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw
            first = first_dir / "same.sparse"; second = second_dir / "same.sparse"
            first.write_bytes(payload); second.write_bytes(payload)
            worker = BatchWorkerObject([first, second], output, True)
            reports: list[dict] = []
            worker.finished_report.connect(reports.append)
            worker.run()
            self.assertEqual(reports[0]["summary"]["failed"], 2)
            self.assertFalse((output / "same_raw.img").exists())


    def test_batch_worker_preflight_failure_prevents_partial_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "queued.sparse"
            raw = b"DATA"
            header = SPARSE_HEADER.pack(
                SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF
            )
            source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
            output = root / "out"
            output.mkdir()
            worker = BatchWorkerObject([source], output, False)
            reports: list[dict] = []
            worker.finished_report.connect(reports.append)

            with patch(
                "sparse_to_raw.shutil.disk_usage",
                return_value=SimpleNamespace(total=1, used=1, free=0),
            ):
                worker.run()

            self.assertEqual(reports[0]["summary"]["success"], 0)
            self.assertEqual(reports[0]["summary"]["failed"], 1)
            self.assertIsNone(reports[0]["preflight"])
            self.assertFalse((output / "queued_raw.img").exists())
            self.assertIn("Insufficient free disk space", reports[0]["items"][0]["error"])



    def test_batch_worker_can_cancel_one_pending_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            sources = []
            for name in ("first", "second"):
                source = root / f"{name}.sparse"
                raw = b"DATA"
                header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
                source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
                sources.append(source)
            worker = BatchWorkerObject(sources, output, False, task_ids=["first", "second"])
            reports: list[dict] = []
            worker.finished_report.connect(reports.append)
            self.assertTrue(worker.cancel_task("second"))
            worker.run()
            self.assertEqual(reports[0]["summary"]["success"], 1)
            self.assertEqual(reports[0]["summary"]["cancelled"], 1)
            self.assertEqual(reports[0]["items"][1]["status"], "cancelled")
            self.assertFalse((output / "second_raw.img").exists())

    def test_batch_worker_can_skip_one_pending_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            sources = []
            for name in ("first", "second"):
                source = root / f"{name}.sparse"
                raw = b"DATA"
                header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
                source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
                sources.append(source)
            worker = BatchWorkerObject(sources, output, False, task_ids=["first", "second"])
            reports: list[dict] = []
            worker.finished_report.connect(reports.append)
            self.assertTrue(worker.skip_task("second"))
            worker.run()
            self.assertEqual(reports[0]["summary"]["success"], 1)
            self.assertEqual(reports[0]["summary"]["skipped"], 1)
            self.assertEqual(reports[0]["items"][1]["status"], "skipped")
            self.assertFalse((output / "second_raw.img").exists())

    def test_batch_worker_pause_takes_effect_between_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            sources = []
            for name in ("first", "second"):
                source = root / f"{name}.sparse"
                raw = b"DATA"
                header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
                source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
                sources.append(source)

            first_started = threading.Event()
            release_first = threading.Event()
            paused = threading.Event()
            calls: list[str] = []

            def fake_convert(source, destination, **kwargs):
                calls.append(Path(source).name)
                if Path(source) == sources[0]:
                    first_started.set()
                    self.assertTrue(release_first.wait(5), "test did not release the first task")
                return {"output_size_bytes": 4}

            worker = BatchWorkerObject(sources, output, False, task_ids=["first", "second"])
            reports: list[dict] = []
            # The worker is invoked from a plain Python thread in this test (not a
            # running QThread event loop). DirectConnection makes the test observer
            # synchronous instead of queuing callbacks to the idle GUI thread.
            worker.finished_report.connect(reports.append, Qt.ConnectionType.DirectConnection)
            worker.pause_changed.connect(
                lambda state: paused.set() if state else None,
                Qt.ConnectionType.DirectConnection,
            )
            with patch("sparse_to_raw_gui.convert_sparse_to_raw", side_effect=fake_convert):
                thread = threading.Thread(target=worker.run, daemon=True)
                thread.start()
                self.assertTrue(first_started.wait(5), "first task did not start")
                worker.request_pause()
                release_first.set()
                self.assertTrue(paused.wait(5), "queue did not pause at the task boundary")
                self.assertEqual(calls, ["first.sparse"])
                worker.resume()
                thread.join(5)
            self.assertFalse(thread.is_alive(), "queue worker did not finish")
            self.assertEqual(calls, ["first.sparse", "second.sparse"])
            self.assertEqual(reports[0]["summary"]["success"], 2)

    def test_batch_worker_can_cancel_active_task_individually(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            source = root / "active.sparse"
            raw = b"DATA"
            header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
            source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
            started = threading.Event()
            worker = BatchWorkerObject([source], output, False, task_ids=["active"])
            reports: list[dict] = []
            # This worker runs on threading.Thread without a Qt event loop; observe
            # its final report synchronously from the worker thread.
            worker.finished_report.connect(reports.append, Qt.ConnectionType.DirectConnection)

            def wait_for_cancel(_source, _destination, **kwargs):
                started.set()
                cancel_requested = kwargs["cancel_requested"]
                deadline = threading.Event()
                for _ in range(100):
                    if cancel_requested():
                        raise ConversionCancelled("Cancelled by test")
                    deadline.wait(0.01)
                raise AssertionError("task was not cancelled")

            with patch("sparse_to_raw_gui.convert_sparse_to_raw", side_effect=wait_for_cancel):
                thread = threading.Thread(target=worker.run, daemon=True)
                thread.start()
                self.assertTrue(started.wait(5), "task did not start")
                self.assertTrue(worker.cancel_task("active"))
                thread.join(5)
            self.assertFalse(thread.is_alive(), "queue worker did not finish")
            self.assertEqual(reports[0]["summary"]["cancelled"], 1)
            self.assertEqual(reports[0]["items"][0]["status"], "cancelled")

    def test_batch_worker_can_skip_active_task_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "out"
            output.mkdir()
            source = root / "active-skip.sparse"
            raw = b"DATA"
            header = SPARSE_HEADER.pack(SPARSE_MAGIC, 1, 0, SPARSE_HEADER.size, 12, 4, 1, 1, zlib.crc32(raw) & 0xFFFFFFFF)
            source.write_bytes(header + struct.pack("<HHII", 0xCAC1, 0, 1, 16) + raw)
            started = threading.Event()
            worker = BatchWorkerObject([source], output, False, task_ids=["active-skip"])
            reports: list[dict] = []
            # This worker runs on threading.Thread without a Qt event loop; observe
            # its final report synchronously from the worker thread.
            worker.finished_report.connect(reports.append, Qt.ConnectionType.DirectConnection)

            def wait_for_skip(_source, _destination, **kwargs):
                started.set()
                cancel_requested = kwargs["cancel_requested"]
                deadline = threading.Event()
                for _ in range(100):
                    if cancel_requested():
                        raise ConversionCancelled("Skipped by test")
                    deadline.wait(0.01)
                raise AssertionError("task was not skipped")

            with patch("sparse_to_raw_gui.convert_sparse_to_raw", side_effect=wait_for_skip):
                thread = threading.Thread(target=worker.run, daemon=True)
                thread.start()
                self.assertTrue(started.wait(5), "task did not start")
                self.assertTrue(worker.skip_task("active-skip"))
                thread.join(5)
            self.assertFalse(thread.is_alive(), "queue worker did not finish")
            self.assertEqual(reports[0]["summary"]["skipped"], 1)
            self.assertEqual(reports[0]["items"][0]["status"], "skipped")

    def test_batch_queue_exposes_load_and_save_profile_controls(self) -> None:
        window = MainWindow()
        dialog = BatchQueueDialog(window)
        try:
            self.assertEqual(dialog.load_profile_button.text(), window.t("profile_load"))
            self.assertEqual(dialog.save_profile_button.text(), window.t("profile_save"))
            self.assertTrue(dialog.load_profile_button.isEnabled())
            self.assertTrue(dialog.save_profile_button.isEnabled())
        finally:
            dialog.close()
            window.close()

    def test_batch_profile_replaces_queue_and_restores_mixed_task_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sparse = root / "system.sparse"
            raw = root / "boot.img"
            rawprogram = root / "rawprogram0.xml"
            sparse.write_bytes(b"sparse")
            raw.write_bytes(b"raw")
            rawprogram.write_text("<data />", encoding="utf-8")
            window = MainWindow()
            dialog = BatchQueueDialog(window)
            try:
                profile = {
                    "options": {"output_dir": str(root / "batch-out"), "overwrite": True, "verify_output": False},
                    "tasks": [
                        {"type": "sparse", "source": str(sparse)},
                        {"type": "raw_to_sparse", "source": str(raw),
                         "config": {"output": str(root / "boot.sparse"), "block_size": 4096}},
                        {"type": "qfil", "label": "test package",
                         "config": {"rawprogram_files": [str(rawprogram)], "patch_files": [],
                                    "search_dirs": [str(root)], "output_dir": str(root / "qfil-out"),
                                    "allow_overlaps": False}},
                    ],
                }
                missing = dialog._apply_profile(profile)
                self.assertEqual(missing, 0)
                self.assertEqual(dialog.list.count(), 3)
                self.assertEqual([dialog.list.item(i).data(dialog.ROLE_TASK_TYPE) for i in range(3)],
                                 ["sparse", "raw_to_sparse", "qfil"])
                self.assertTrue(dialog.overwrite.isChecked())
                self.assertFalse(dialog.verify_output.isChecked())
                self.assertEqual(Path(dialog.folder_edit.text()), root / "batch-out")
                captured = dialog._collect_profile_tasks()
                self.assertEqual([task["type"] for task in captured], ["sparse", "raw_to_sparse", "qfil"])
                self.assertEqual(captured[1]["config"]["block_size"], 4096)
                self.assertEqual(captured[2]["config"]["rawprogram_files"], [str(rawprogram)])
                self.assertTrue(all(dialog.list.item(i).data(dialog.ROLE_STATUS) == "waiting" for i in range(3)))
            finally:
                dialog.close()
                window.close()

    def test_batch_queue_supports_internal_drag_reordering_and_status_filter(self) -> None:
        window = MainWindow()
        dialog = BatchQueueDialog(window)
        try:
            from PySide6.QtWidgets import QAbstractItemView
            self.assertEqual(dialog.list.dragDropMode(), QAbstractItemView.DragDropMode.InternalMove)
            dialog._new_item("/tmp/first.sparse")
            dialog._new_item("/tmp/second.sparse")
            first_id = dialog.list.item(0).data(dialog.ROLE_TASK_ID)
            second_id = dialog.list.item(1).data(dialog.ROLE_TASK_ID)
            dialog._set_item_status(first_id, "success")
            dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("waiting"))
            self.assertTrue(dialog.list.item(0).isHidden())
            self.assertFalse(dialog.list.item(1).isHidden())
            dialog.filter_combo.setCurrentIndex(dialog.filter_combo.findData("all"))
            dialog.list.item(1).setSelected(True)
            dialog._move_selected(-1)
            self.assertEqual(dialog.list.item(0).data(dialog.ROLE_TASK_ID), second_id)
        finally:
            dialog.close()
            window.close()

    def test_batch_queue_retries_only_selected_failed_items(self) -> None:
        window = MainWindow()
        dialog = BatchQueueDialog(window)
        try:
            dialog._new_item("/tmp/failed.sparse")
            dialog._new_item("/tmp/waiting.sparse")
            failed_id = dialog.list.item(0).data(dialog.ROLE_TASK_ID)
            dialog._set_item_status(failed_id, "failed", "test failure")
            dialog.list.item(0).setSelected(True)
            captured: list[set[str] | None] = []
            with patch.object(dialog, "_run", side_effect=lambda only_task_ids=None: captured.append(only_task_ids)):
                dialog._retry_selected()
            self.assertEqual(captured, [{failed_id}])
            self.assertEqual(dialog.list.item(0).data(dialog.ROLE_STATUS), "waiting")
            self.assertEqual(dialog.list.item(1).data(dialog.ROLE_STATUS), "waiting")
        finally:
            dialog.close()
            window.close()

    def test_batch_queue_updates_overall_progress(self) -> None:
        window = MainWindow()
        dialog = BatchQueueDialog(window)
        try:
            dialog._new_item("/tmp/progress-one.sparse")
            dialog._new_item("/tmp/progress-two.sparse")
            first_id = dialog.list.item(0).data(dialog.ROLE_TASK_ID)
            dialog._run_task_ids = [first_id, "second-task"]
            dialog._progress({
                "queue_index": 0,
                "queue_total": 2,
                "queue_percent": 25,
                "percent": 50,
                "queue_current_file": "/tmp/progress-one.sparse",
            })
            self.assertEqual(dialog.progress.value(), 25)
            dialog._item_finished(0, {"task_id": first_id, "status": "success"})
            self.assertEqual(dialog.progress.value(), 50)
        finally:
            dialog.close()
            window.close()

    def test_batch_queue_skip_selected_marks_waiting_item_skipped(self) -> None:
        window = MainWindow()
        dialog = BatchQueueDialog(window)
        try:
            dialog._new_item("/tmp/to-skip.sparse")
            item = dialog.list.item(0)
            item.setSelected(True)
            dialog._skip_selected()
            self.assertEqual(item.data(dialog.ROLE_STATUS), "skipped")
            self.assertEqual(dialog.summary_label.text().split("·")[0].strip().split(":")[-1].strip(), "1")
        finally:
            dialog.close()
            window.close()

    def test_drop_zone_uses_large_vector_icon(self) -> None:
        window = MainWindow()
        try:
            self.assertEqual(window.drop_zone.icon.width(), 72)
            self.assertEqual(window.drop_zone.icon.height(), 72)
            self.assertGreaterEqual(window.drop_zone.minimumHeight(), 96)
        finally:
            window.close()

    def test_bundled_self_test_entrypoint(self) -> None:
        # Reuse the existing QApplication so a GUI package can be smoke-tested headlessly.
        from sparse_to_raw_gui import main
        self.assertEqual(main(["--self-test"]), 0)


if __name__ == "__main__":
    unittest.main()
