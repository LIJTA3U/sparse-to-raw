# v0.7.0 release verification checklist

Use this checklist for the final stable v0.7.0 release. Run it from the exact commit intended for the release; do not create a release tag until every required check has passed.

## 1. Verify the source version and tests

From the repository root on Windows:

```powershell
py -m compileall -q .
py -m unittest discover -s tests -p "test_*.py" -v
py tests\gui_smoke_tests.py
py sparse_to_raw.py --version
py sparse_to_raw.py --help
```

The release commit must report `sparse-to-raw v0.7.0`. Before changing `APP_VERSION` from `v0.7.0-dev`, finish all development work and update both changelogs and release notes.

Check the help output for the integrated commands: `qfil-analyze`, `qfil-validate`, `qfil-build`, `super-info`, `super-extract`, `vbmeta-info`, `boot-info`, `ramdisk-info`, `ramdisk-extract`, `validate`, `compare`, and `raw-to-sparse`.

The three small synthetic Super Image fixtures in `tests/fixtures/` (`super_multi_extent.img`, `expected_system.img`, and `expected_vendor.img`) must be present in the repository. They are regression test data, not firmware dumps.

## 2. Verify CI and release build

Confirm successful GitHub Actions runs for:

- Core tests on Python 3.10–3.14 on Windows and Linux.
- GUI smoke tests with PySide6 on Windows and Linux.
- The Windows packaging workflow, including packaged CLI checks for the new QFIL and Super Image commands and the GUI `--self-test` with Python directories removed from `PATH`.

The release workflow must attach `sparse-to-raw.exe`, `sparse-to-raw-gui.exe`, `sparse-to-raw-gui-windows.zip`, and `SHA256SUMS.txt`.

## 3. Test the downloaded Windows assets

- Run the packaged CLI `--version` and `--help` commands, plus `qfil-validate --help` and `super-info --help`.
- Launch the standalone GUI executable.
- Extract the GUI ZIP completely and launch the GUI from its extracted application folder. Keep the packaged folder structure intact.
- Test the GUI on a Windows account or machine without Python installed.
- Open Ramdisk Inspector and compare two text configuration files, such as `fstab.mt6762` and `fstab.mt6765`.
- Verify every downloaded asset against `SHA256SUMS.txt`.

## 4. Compatibility scope and known limitations

The Sparse-to-RAW converter was compared byte-for-byte with AOSP `simg2img.exe` on two real factory Sparse images: Blackview `super.img` and Google Pixel `userdata_exp.ai.img`. Both comparisons matched; this is a limited sample, not comprehensive certification for every Sparse producer or firmware.

The Super Image Inspector was exercised on Blackview RAW and factory Sparse `super.img` inputs and on a synthetic multi-extent fixture. CLI and GUI extraction results matched by SHA-256. LP metadata versions 10.0–10.2 are supported. Extraction currently requires linear extents to reference block device index `0`; multi-image retrofit layouts and arbitrary `super_*` sets are not supported.

Other important limitations must remain documented:

- QFIL patch instructions are parsed and reported but are never executed.
- AVB / VBMeta inspection does not verify RSA signatures, trusted-key status, or device rollback state.
- Boot Image Inspector reports structure and format hints; it does not unpack kernel/ramdisk payloads or verify AVB signatures.
- Ramdisk Inspector detects Zstandard and LZO/lzop but does not decompress them in the dependency-free build. Symlinks and special filesystem nodes are listed in the manifest rather than created during extraction.

## 5. Safety and release hygiene

- Keep firmware dumps, device-specific `.img` / `.raw` / `.sparse` files, local build outputs, and Python caches out of source archives. Keep only the three small synthetic fixtures in `tests/fixtures/`.
- Preserve the warning that the application processes files and does not flash devices or communicate with connected phones.
- Verify critical outputs independently before using them in firmware workflows.
- Set `APP_VERSION` to `v0.7.0`, update README release links and changelog entries, create the tag from the exact tested commit, publish the GitHub Release, and verify the newly attached artifacts and checksums.
