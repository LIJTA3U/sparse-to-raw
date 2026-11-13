from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from batch_profiles import (
    BatchProfileError,
    PROFILE_FORMAT,
    load_batch_profile,
    save_batch_profile,
)


class BatchProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.profile_dir = self.root / "profiles"
        self.profile_dir.mkdir()
        self.firmware = self.root / "firmware"
        self.firmware.mkdir()
        self.raw = self.firmware / "boot.img"
        self.raw.write_bytes(b"raw")
        self.sparse = self.firmware / "system.sparse"
        self.sparse.write_bytes(b"sparse")
        self.rawprogram = self.firmware / "rawprogram0.xml"
        self.rawprogram.write_text("<data />", encoding="utf-8")
        self.patch = self.firmware / "patch0.xml"
        self.patch.write_text("<data />", encoding="utf-8")
        self.profile = self.profile_dir / "daily-build.json"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_round_trip_preserves_all_task_types_and_queue_options(self) -> None:
        tasks = [
            {"type": "sparse", "source": str(self.sparse)},
            {"type": "raw_to_sparse", "source": str(self.raw),
             "config": {"output": str(self.firmware / "boot_out.sparse"), "block_size": 4096}},
            {"type": "qfil", "label": "Factory firmware (1 rawprogram)",
             "config": {"rawprogram_files": [str(self.rawprogram)], "patch_files": [str(self.patch)],
                        "search_dirs": [str(self.firmware)], "output_dir": str(self.root / "qfil-out"),
                        "allow_overlaps": True}},
        ]
        options = {"output_dir": str(self.root / "batch-output"), "overwrite": True, "verify_output": False}
        saved = save_batch_profile(self.profile, tasks, options, name="Daily build")
        self.assertEqual(saved["format"], PROFILE_FORMAT)
        on_disk = json.loads(self.profile.read_text(encoding="utf-8"))
        self.assertNotIn(str(self.root), json.dumps(on_disk))

        loaded = load_batch_profile(self.profile)
        self.assertEqual(loaded["name"], "Daily build")
        self.assertEqual(loaded["options"], options)
        self.assertEqual([task["type"] for task in loaded["tasks"]], ["sparse", "raw_to_sparse", "qfil"])
        self.assertEqual(loaded["tasks"][0]["source"], str(self.sparse.resolve()))
        self.assertEqual(loaded["tasks"][1]["config"]["block_size"], 4096)
        self.assertEqual(loaded["tasks"][1]["config"]["output"], str((self.firmware / "boot_out.sparse").resolve()))
        self.assertTrue(loaded["tasks"][2]["config"]["allow_overlaps"])
        self.assertEqual(loaded["tasks"][2]["config"]["rawprogram_files"], [str(self.rawprogram.resolve())])

    def test_round_trip_preserves_symlink_path_spelling(self) -> None:
        alias = self.root / "firmware-alias"
        try:
            alias.symlink_to(self.firmware, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"Directory symlinks are unavailable: {exc}")

        output_dir = str(alias / "batch-output")
        tasks = [{"type": "sparse", "source": str(alias / self.sparse.name)}]
        options = {"output_dir": output_dir, "overwrite": False, "verify_output": True}
        save_batch_profile(self.profile, tasks, options)
        loaded = load_batch_profile(self.profile)

        # Path.resolve() would follow the alias and change the path spelling.
        self.assertEqual(loaded["options"]["output_dir"], output_dir)
        self.assertEqual(loaded["tasks"][0]["source"], str(alias / self.sparse.name))

    def test_profile_refuses_overwrite_by_default_and_preserves_existing_file(self) -> None:
        self.profile.write_text("KEEP", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            save_batch_profile(self.profile, [], {"output_dir": str(self.root)})
        self.assertEqual(self.profile.read_text(encoding="utf-8"), "KEEP")

    def test_profile_can_be_overwritten_explicitly(self) -> None:
        self.profile.write_text("old", encoding="utf-8")
        save_batch_profile(self.profile, [], {"output_dir": str(self.root)}, overwrite=True)
        self.assertEqual(load_batch_profile(self.profile)["tasks"], [])

    def test_rejects_unknown_format_and_version(self) -> None:
        self.profile.write_text(json.dumps({"format": "other", "version": 1, "options": {}, "tasks": []}), encoding="utf-8")
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)
        self.profile.write_text(json.dumps({"format": PROFILE_FORMAT, "version": 99, "options": {}, "tasks": []}), encoding="utf-8")
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)

    def test_rejects_unknown_task_and_bad_block_size(self) -> None:
        payload = {"format": PROFILE_FORMAT, "version": 1,
                   "options": {"output_dir": ".", "overwrite": False, "verify_output": True},
                   "tasks": [{"type": "execute", "source": "something"}]}
        self.profile.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)
        payload["tasks"] = [{"type": "raw_to_sparse", "source": "boot.img",
                             "config": {"output": "boot.sparse", "block_size": 4097}}]
        self.profile.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)

    def test_rejects_malformed_qfil_profile(self) -> None:
        payload = {"format": PROFILE_FORMAT, "version": 1,
                   "options": {"output_dir": ".", "overwrite": False, "verify_output": True},
                   "tasks": [{"type": "qfil", "label": "QFIL", "config": {"rawprogram_files": [], "output_dir": "out"}}]}
        self.profile.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)

    def test_rejects_non_boolean_qfil_allow_overlaps(self) -> None:
        payload = {"format": PROFILE_FORMAT, "version": 1,
                   "options": {"output_dir": ".", "overwrite": False, "verify_output": True},
                   "tasks": [{"type": "qfil", "label": "QFIL",
                              "config": {"rawprogram_files": ["rawprogram.xml"], "output_dir": "out",
                                         "allow_overlaps": "false"}}]}
        self.profile.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)

    def test_rejects_non_boolean_queue_options(self) -> None:
        payload = {"format": PROFILE_FORMAT, "version": 1,
                   "options": {"output_dir": ".", "overwrite": "yes", "verify_output": True}, "tasks": []}
        self.profile.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)

    def test_rejects_oversized_profile(self) -> None:
        self.profile.write_bytes(b" " * (5 * 1024 * 1024 + 1))
        with self.assertRaises(BatchProfileError):
            load_batch_profile(self.profile)


if __name__ == "__main__":
    unittest.main()
