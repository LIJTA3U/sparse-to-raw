"""Headless smoke tests for the optional PySide6 desktop interface."""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sparse_to_raw_gui import (  # noqa: E402
    BatchWorkerObject,
    ConversionWorkerObject,
    MainWindow,
    MergeDialog,
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


class SparseToRawGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(["sparse-to-raw-gui-tests"])

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

    def test_bundled_self_test_entrypoint(self) -> None:
        # Reuse the existing QApplication so a GUI package can be smoke-tested headlessly.
        from sparse_to_raw_gui import main
        self.assertEqual(main(["--self-test"]), 0)


if __name__ == "__main__":
    unittest.main()
