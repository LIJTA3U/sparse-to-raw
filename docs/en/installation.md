# Installation

## Windows release (recommended for end users)

1. Open the [v0.4.0 GitHub Release](https://github.com/LIJTA3U/sparse-to-raw/releases/tag/v0.4.0).
2. Download `sparse-to-raw-gui-windows.zip`.
3. Extract the complete ZIP archive to a folder of your choice.
4. Run `sparse-to-raw-gui.exe` from the extracted application folder.

Keep the extracted folder structure intact. The ZIP contains the executable and the libraries/resources required by the GUI. Python and PySide6 do not need to be installed separately.

The release also includes `sparse-to-raw-gui.exe` as a one-file build and `sparse-to-raw.exe` for command-line use.

## Run the CLI from source

Requirements: Python 3.10 or newer. The CLI uses only the Python standard library.

```powershell
py --version
py sparse_to_raw.py --help
```

No `pip install` step is required for the CLI.

## Run the GUI from source

Install Python 3.10 or newer, open a terminal in the repository folder, then run:

```powershell
py -m pip install -r requirements-gui.txt
py sparse_to_raw_gui.py
```

The GUI dependency is PySide6. The CLI remains independent of PySide6.

## Build applications yourself

For PyInstaller packaging, install the build requirements:

```powershell
py -m pip install -r requirements-build.txt
```

See [Development and packaging](development.md) for the exact build commands.

## Disk space

The expanded RAW image may be much larger than the Sparse input. Check the expected RAW size and ensure that the destination drive has enough free space before conversion. Multi-part merging also uses staging files; see the [GUI guide](gui-guide.md) and [CLI guide](cli-guide.md).
