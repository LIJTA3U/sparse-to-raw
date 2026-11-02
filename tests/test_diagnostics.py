from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from diagnostics import DiagnosticStore, redact_text, sanitize_for_export


class DiagnosticStoreTests(unittest.TestCase):
    def test_append_and_read_structured_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = DiagnosticStore(temporary)
            self.assertTrue(store.append("ERROR", "conversion", "Conversion failed", {"chunks": 4, "duration_seconds": 1.25}))
            events = store.entries()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["level"], "error")
            self.assertEqual(events[0]["category"], "conversion")
            self.assertEqual(events[0]["message"], "Conversion failed")
            self.assertEqual(events[0]["details"]["chunks"], 4)
            self.assertTrue(events[0]["timestamp"])

    def test_rotation_keeps_recent_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = DiagnosticStore(temporary, max_file_bytes=4096, backups=2, max_events=100)
            for index in range(8):
                self.assertTrue(store.append("info", "application", f"event-{index}-" + ("x" * 1200)))
            self.assertTrue((Path(temporary) / "diagnostics.1.jsonl").exists())
            events = store.entries()
            self.assertGreater(len(events), 1)
            self.assertIn("event-7-", events[-1]["message"])

    def test_clear_removes_current_and_rotated_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = DiagnosticStore(temporary, max_file_bytes=4096, backups=2)
            store.append("info", "application", "first" + ("x" * 1500))
            store.append("info", "application", "second" + ("x" * 1500))
            self.assertTrue(store.clear())
            self.assertEqual(store.entries(), [])
            self.assertFalse(store.path.exists())

    def test_export_redacts_user_paths_and_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = DiagnosticStore(root / "logs")
            store.append(
                "error",
                "conversion",
                r"Cannot read C:\Users\DooM Slayer\Desktop\firmware\super.img; token=abc123",
                {"source_path": r"C:\Users\DooM Slayer\Desktop\firmware\super.img", "api_token": "very-secret", "chunks": 3},
            )
            source_file = root / "secret-input.img"
            source_file.write_bytes(b"THIS MUST NOT BE INCLUDED IN THE DIAGNOSTIC ZIP")
            archive_path = root / "diagnostics.zip"
            store.export_zip(
                archive_path,
                app_version="v0.5.0-dev",
                qt_version="6.x",
                pyside_version="6.x",
                home_path=r"C:\Users\DooM Slayer",
            )
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(set(archive.namelist()), {"diagnostics.jsonl", "system-info.json", "README.txt"})
                log_text = archive.read("diagnostics.jsonl").decode("utf-8")
                system_info = json.loads(archive.read("system-info.json"))
                readme = archive.read("README.txt").decode("utf-8")
            self.assertNotIn("DooM Slayer", log_text)
            self.assertNotIn("abc123", log_text)
            self.assertNotIn("very-secret", log_text)
            self.assertIn("<USER_HOME>", log_text)
            self.assertIn("<REDACTED>", log_text)
            self.assertNotIn("THIS MUST NOT BE INCLUDED", log_text + readme)
            self.assertEqual(system_info["application_version"], "v0.5.0-dev")
            self.assertNotIn("username", system_info)
            self.assertNotIn("hostname", system_info)
            self.assertNotIn("environment", system_info)

    def test_posix_profile_path_is_redacted(self) -> None:
        text = "/home/alice/projects/firmware/system.img"
        redacted = redact_text(text, home_path="/non-matching/home")
        self.assertNotIn("alice", redacted)
        self.assertIn("<USER>", redacted)


    def test_nested_sensitive_details_are_redacted_after_append(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = DiagnosticStore(temporary)
            store.append(
                "error",
                "application",
                "Request failed",
                {"request": {"client_secret": "nested-secret", "api_token": "nested-token", "safe": "visible"}},
            )
            archive_path = Path(temporary) / "nested.zip"
            store.export_zip(archive_path, app_version="test", home_path="/non-matching/home")
            with zipfile.ZipFile(archive_path) as archive:
                text = archive.read("diagnostics.jsonl").decode("utf-8")
            self.assertNotIn("nested-secret", text)
            self.assertNotIn("nested-token", text)
            self.assertIn("<REDACTED>", text)
            self.assertIn("visible", text)

    def test_sensitive_detail_keys_are_redacted_recursively(self) -> None:
        value = {"outer": [{"access_token": "secret", "safe": "ok"}]}
        result = sanitize_for_export(value, home_path="/non-matching/home")
        self.assertEqual(result["outer"][0]["access_token"], "<REDACTED>")
        self.assertEqual(result["outer"][0]["safe"], "ok")


if __name__ == "__main__":
    unittest.main()
