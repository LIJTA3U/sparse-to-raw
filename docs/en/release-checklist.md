# v0.6.0 release verification checklist

This checklist records the final verification gates for the stable v0.6.0 release and can be reused for maintenance rebuilds.

## 1. Verify the source version and tests

From the repository root on Windows:

```powershell
py -m compileall -q .
py -m unittest discover -s tests -v
py tests\gui_smoke_tests.py
py sparse_to_raw.py --version
py sparse_to_raw.py --help
```

Expected application version: `sparse-to-raw v0.6.0`.

## 2. Verify CI and release build

Confirm successful GitHub Actions runs for:

- Core tests on Python 3.10–3.14 for Windows and Linux.
- GUI smoke tests with PySide6 for Windows and Linux.
- Windows packaging workflow, including packaged CLI `--version` / `--help` checks and GUI `--self-test` with Python directories removed from `PATH`.

The release workflow must attach `sparse-to-raw.exe`, `sparse-to-raw-gui.exe`, `sparse-to-raw-gui-windows.zip`, and `SHA256SUMS.txt`.

## 3. Test the downloaded Windows assets

- Run the CLI `--version` and `--help` commands.
- Launch the standalone GUI executable.
- Extract the GUI ZIP completely and launch the GUI from its extracted application folder. Keep the packaged folder structure intact.
- Test on a Windows account or machine without Python installed.
- Verify each downloaded asset against `SHA256SUMS.txt`.

## 4. Compatibility scope

Independent byte-for-byte comparison against `simg2img.exe` was completed on two real Android Sparse images: Blackview factory `super.img` (about 3.6 GB) and Google Pixel factory `userdata_exp.ai.img` (about 6.83 GB). This is a limited sample. Android Dynamic Partitions `super` containers and arbitrary multi-file `super_*` layouts are not covered by that comparison and are not parsed as Dynamic Partitions by this application. See the [4PDA discussion of the ten-file Vivo V70 Elite `super` layout](https://4pda.to/forum/index.php?showtopic=496786&st=5460).

## 5. Safety and release hygiene

- Keep firmware dumps, `.img`, `.raw`, `.sparse`, `.simg`, and local build/cache files out of source archives.
- Preserve the warning that the application only processes files and does not flash devices.
- Preserve the warning that QFIL patch commands are reported but not executed.
- Before a maintenance release, update `APP_VERSION`, changelog entries, README links, create a tag from the exact tested commit, and verify the newly published artifacts.
