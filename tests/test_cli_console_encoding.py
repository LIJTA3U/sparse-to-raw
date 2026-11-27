from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import sparse_to_raw


class CLIConsoleEncodingTests(unittest.TestCase):
    def test_russian_qfil_validate_help_is_safe_from_cp1252_streams(self) -> None:
        stdout_bytes = io.BytesIO()
        stderr_bytes = io.BytesIO()
        stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252", errors="strict")
        stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252", errors="strict")

        try:
            with patch.object(sparse_to_raw.sys, "stdout", stdout), patch.object(
                sparse_to_raw.sys, "stderr", stderr
            ):
                with self.assertRaises(SystemExit) as raised:
                    sparse_to_raw.main(["--lang", "ru", "qfil-validate", "--help"])

            self.assertEqual(raised.exception.code, 0)
            stdout.flush()
            output = stdout_bytes.getvalue().decode("utf-8")
            self.assertIn("Полностью проверить комплект QFIL", output)
            self.assertEqual(stdout.encoding.lower().replace("-", ""), "utf8")
            self.assertEqual(stderr.encoding.lower().replace("-", ""), "utf8")
        finally:
            stdout.close()
            stderr.close()


if __name__ == "__main__":
    unittest.main()
