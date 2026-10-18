"""Headless smoke tests for the optional PySide6 desktop interface."""
from __future__ import annotations

import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from sparse_to_raw_gui import (  # noqa: E402
    ConversionWorkerObject,
    MainWindow,
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

    def test_bundled_self_test_entrypoint(self) -> None:
        # Reuse the existing QApplication so a GUI package can be smoke-tested headlessly.
        from sparse_to_raw_gui import main
        self.assertEqual(main(["--self-test"]), 0)


if __name__ == "__main__":
    unittest.main()
