from __future__ import annotations

import contextlib
import io
import os
import unittest
from unittest.mock import patch

import sparse_to_raw
from cli_i18n import set_language


class CLILanguageTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_language("en")

    def test_english_is_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(SystemExit) as raised:
                    sparse_to_raw.main(["--help"])
            self.assertEqual(raised.exception.code, 0)
            self.assertIn("Convert, validate and inspect", stdout.getvalue())

    def test_russian_help_can_be_selected(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                sparse_to_raw.main(["--lang", "ru", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Конвертация, проверка и анализ", stdout.getvalue())

    def test_language_environment_variable(self) -> None:
        with patch.dict(os.environ, {"SPARSE_TO_RAW_LANG": "ru"}, clear=True):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(SystemExit):
                    sparse_to_raw.main(["--help"])
            self.assertIn("Конвертация, проверка и анализ", stdout.getvalue())

    def test_explicit_language_overrides_environment(self) -> None:
        with patch.dict(os.environ, {"SPARSE_TO_RAW_LANG": "ru"}, clear=True):
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                with self.assertRaises(SystemExit):
                    sparse_to_raw.main(["--lang", "en", "--help"])
            self.assertIn("Convert, validate and inspect", stdout.getvalue())

    def test_russian_cli_errors_are_localized(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = sparse_to_raw.main(["--lang", "ru", "missing-input.img", "out.raw"])
        self.assertEqual(result, 2)
        self.assertIn("ОШИБКА: Входной файл не найден", stderr.getvalue())

    def test_qfil_help_uses_selected_language(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                sparse_to_raw.main(["--lang", "ru", "qfil-analyze", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Анализировать манифесты", stdout.getvalue())
        self.assertIn("каталог прошивки", stdout.getvalue())

    def test_language_option_is_removed_before_qfil_dispatch(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                sparse_to_raw.main(["qfil-analyze", "--help", "--lang=ru"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("Анализировать манифесты", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
