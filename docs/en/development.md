# Development and packaging

## Architecture

- `sparse_to_raw.py` contains the CLI, Sparse parsing, validation, conversion, inspection, merging, checksum, progress, and cancellation logic.
- `sparse_to_raw_gui.py` provides the PySide6 interface and delegates format processing to the core module.
- Long-running GUI operations use Qt worker threads. Do not duplicate Sparse parsing or checksum logic in the GUI.
- `tests/test_sparse_to_raw.py` contains core tests; `tests/gui_smoke_tests.py` contains GUI smoke tests.

Keep changes focused and preserve the existing public CLI options unless a separately documented compatibility change is approved.

## Set up a development environment (Windows PowerShell)

```powershell
py --version
py -m pip install -r requirements-gui.txt
```

The CLI itself does not need third-party packages. PySide6 is needed for GUI development and GUI tests.

## Run the core tests

```powershell
py -m unittest discover -s tests -p "test_sparse_to_raw.py" -v
```

## Run GUI smoke tests

```powershell
py -m pip install -r requirements-gui.txt
$env:QT_QPA_PLATFORM = "offscreen"
py -m unittest discover -s tests -p "gui_smoke_tests.py" -v
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
```

The `offscreen` platform is for headless tests only. Remove the environment variable before launching the GUI normally.

## Run the complete suite

```powershell
py -m unittest discover -s tests -v
```

## Linux GUI test dependencies

On headless Ubuntu runners, install Qt runtime libraries before importing PySide6:

```bash
sudo apt-get update
sudo apt-get install -y libegl1 libgl1 libdbus-1-3 libxkbcommon-x11-0 libxcb-cursor0
```

## Build Windows applications locally

Install packaging requirements:

```powershell
py -m pip install -r requirements-build.txt
```

Build the CLI:

```powershell
py -m PyInstaller --noconfirm --clean --onefile --name sparse-to-raw sparse_to_raw.py
```

Build the GUI folder package:

```powershell
py -m PyInstaller --noconfirm --clean --windowed --onedir --name sparse-to-raw-gui --icon assets/sparse-to-raw.ico --add-data "assets/sparse-to-raw.ico;assets" sparse_to_raw_gui.py
```

Build the standalone GUI executable:

```powershell
py -m PyInstaller --noconfirm --clean --windowed --onefile --name sparse-to-raw-gui --icon assets/sparse-to-raw.ico --add-data "assets/sparse-to-raw.ico;assets" sparse_to_raw_gui.py
```

Run PyInstaller from the repository root so the relative icon/resource paths resolve. The GitHub Actions release workflow uses an absolute icon path because its `.spec` files are stored under separate build directories.

## Packaged GUI self-test

The GUI supports a `--self-test` entry point used by the release workflow. The workflow builds both folder and one-file packages, then starts each package with Python directories removed from `PATH` to check that the bundled app can run independently of a system Python installation.

## Current GUI behavior to preserve

- User preferences and recent files are persisted through `QSettings`.
- Speed is stored internally in bytes per second and converted only for display.
- Conversion, analysis, and merging run off the GUI thread.
- Batch processing is sequential and duplicate output names are rejected.
- Merge inputs are independent complete Sparse images displayed in the user-selected order.
- Output is published only after validation; cancellation discards staging output and preserves any existing destination.
