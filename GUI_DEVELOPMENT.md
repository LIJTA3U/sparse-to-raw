# GUI development and packaging

## Run from source

```powershell
py -m pip install -r requirements-gui.txt
py sparse_to_raw_gui.py
```

The GUI uses the existing `sparse_to_raw.py` implementation. It must not contain a second implementation of Sparse chunk parsing or checksum validation.

## Run tests

```powershell
py -m unittest discover -s tests -p test_sparse_to_raw.py -v
py -m pip install -r requirements-gui.txt
$env:QT_QPA_PLATFORM = "offscreen"
py -m unittest discover -s tests -p gui_smoke_tests.py -v
```

On headless Ubuntu, install the Qt runtime libraries before importing PySide6:

```bash
sudo apt-get update
sudo apt-get install -y libegl1 libgl1 libdbus-1-3 libxkbcommon-x11-0 libxcb-cursor0
```

## Windows packaging

```powershell
py -m pip install -r requirements-build.txt
py -m PyInstaller --noconfirm --clean --windowed --onedir --name sparse-to-raw-gui --icon assets/sparse-to-raw.ico --add-data "assets/sparse-to-raw.ico;assets" sparse_to_raw_gui.py
py -m PyInstaller --noconfirm --clean --windowed --onefile --name sparse-to-raw-gui --icon assets/sparse-to-raw.ico --add-data "assets/sparse-to-raw.ico;assets" sparse_to_raw_gui.py
```

The release workflow creates both the folder ZIP and the one-file executable, then runs their `--self-test` entry points with Python removed from `PATH`.

## GUI behavior

- Language, speed units, recent input paths, last input/output paths, and window geometry are persisted with `QSettings`.
- Speeds are stored internally in bytes/second and converted only for display: decimal MB/s, binary MiB/s, or megabits/s.
- Analysis and conversion use Qt worker threads; long operations must not run on the GUI thread.
- Batch items run sequentially. Items that would map to the same output filename are rejected to avoid accidental overwrites.
- Merging accepts independent Sparse images with their own headers, in the exact order displayed by the user. It is not an arbitrary byte-split reassembler.
- Output is only committed after input validation succeeds. Cancellation discards staging files and preserves any pre-existing destination.
- JSON reports contain paths and diagnostic text supplied by the user/system; review them before sharing.
