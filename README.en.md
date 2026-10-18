# sparse-to-raw

A small command-line utility to inspect Android Sparse Images and convert them to raw images. It is written in Python and uses only the standard library.

[![Tests](https://img.shields.io/github/actions/workflow/status/LIJTA3U/sparse-to-raw/tests.yml?branch=main&label=tests)](https://github.com/LIJTA3U/sparse-to-raw/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CLI has no dependencies](https://img.shields.io/badge/CLI-no%20extra%20dependencies-brightgreen.svg)](#requirements)

**Language:** [Русский](README.md) · English

> **Status: experimental.** The implementation was compared byte-for-byte with `simg2img.exe` on one Android `super.img` image of about 3.6 GB. This is evidence for that test file, not a replacement for independent testing across more images and devices.

## Features

- Convert Android Sparse Image format version 1 to raw.
- Support for `RAW`, `FILL`, `DONT_CARE`, and `CRC32` chunks.
- Validation of per-chunk CRC32 and the image-level checksum.
- Structural checks for headers, block sizes and counts, truncated data, and trailing bytes.
- Inspection and verification without creating a raw image: `--info` and `--verify-only`.
- Safe output handling: existing files are not overwritten unless `--force` is supplied.
- Progress indicator, throughput, and processed size.
- Optional SHA-256 of the logical raw content and JSON report.
- Explicitly ordered merging of independent sparse parts via `--merge-parts`.
- Streaming implementation suitable for large images without loading the entire file into memory.
- The CLI uses only the Python standard library.
- Optional PySide6 desktop GUI with a separate Windows build.

`DONT_CARE` ranges are interpreted as zero bytes. The filesystem may store them as sparse file holes, while the logical output size and readable contents remain correct.

## Requirements

- Python 3.10 or newer when running from source.
- The CLI has no third-party package requirements.
- Developers who want the GUI need PySide6: `python -m pip install -r requirements-gui.txt`.
- Enough free disk space for the expanded image.

## Windows desktop GUI

The project includes an experimental PySide6 desktop interface with a dark futuristic theme, angular yellow frame, cyan accents, drag-and-drop, progress statistics, and an operation log. It calls the same conversion and validation functions as the CLI.

Run it from source:

```bat
py -m pip install -r requirements-gui.txt
py sparse_to_raw_gui.py
```

Conversion runs in a Qt worker thread. The UI reports actual processed bytes and chunks, CRC32 and image-checksum validation; cancellation discards the temporary output and leaves an existing destination intact. If the output file already exists, the app asks for explicit confirmation before replacing it.

End users do not need Python installed. The [Releases](https://github.com/LIJTA3U/sparse-to-raw/releases) page will provide `sparse-to-raw-gui-windows.zip`, containing the EXE and its bundled libraries. A standalone `sparse-to-raw-gui.exe` is also built; the folder ZIP is the recommended package for easier diagnostics and faster startup.

## Quick start

```bash
python sparse_to_raw.py input_sparse.img output_raw.img
```

On Windows Command Prompt:

```bat
py sparse_to_raw.py super.img super_raw.img
```

If the output already exists, the program stops without changing it. To explicitly allow replacement:

```bat
py sparse_to_raw.py super.img super_raw.img --force
```

## Commands

Inspect and validate the image without conversion:

```bash
python sparse_to_raw.py super.img --info
```

Verify the file structure and checksums without creating a raw image:

```bash
python sparse_to_raw.py super.img --verify-only
```

Calculate the logical RAW SHA-256 and save a JSON report:

```bash
python sparse_to_raw.py super.img super_raw.img --sha256 --json-report report.json
```

SHA-256 includes zero-filled `DONT_CARE` ranges. Existing report files also require `--force` to be replaced. To hide the progress indicator, add `--quiet`.

Merge independent sparse parts in the order you specify:

```bat
py sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --sha256
```

List all parts in the correct numeric order. Each input must be a complete Android Sparse Image with its own header. Every part is validated independently, and the final output is not published if any part fails validation. Do not use this mode for arbitrary byte-level splits of one sparse file.

## Build for Windows

PyInstaller and PySide6 are required only for development and packaging, not for end users:

```bat
py -m pip install -r requirements-build.txt
py -m PyInstaller --clean --onefile --name sparse-to-raw sparse_to_raw.py
py -m PyInstaller --clean --windowed --onedir --name sparse-to-raw-gui sparse_to_raw_gui.py
```

The CLI EXE is created at `dist\sparse-to-raw.exe`, and the GUI folder at `dist\sparse-to-raw-gui`. The Windows build workflow also creates a ZIP of the GUI folder and a standalone GUI EXE. **Build Windows applications** attaches all assets to GitHub Releases and smoke-tests the bundled GUI with Python hidden from `PATH`.

## Tests

```bash
python -m unittest discover -s tests -v
```

Core tests cover all supported chunk types, CRC and image-checksum failures, malformed/truncated data, trailing `DONT_CARE`, safe overwrite behavior, inspection/verification modes, multi-part merging, SHA-256, JSON reporting, progress callbacks, and safe cancellation. GitHub Actions runs the core suite on multiple Python versions on Windows and Linux. A separate GUI workflow installs PySide6 and runs headless widget/path-validation smoke tests on Windows and Linux.

## Limitations and safety

- This is an experimental project, not an official AOSP `simg2img` replacement.
- Independent comparison was performed on one large real `super.img`; independently verify images used for critical work.
- This utility does not communicate with a phone or flash partitions. It only reads an input file and optionally creates an output file.
- Check paths and free disk space before running. Multi-part merging temporarily needs space for the combined staging file plus the currently expanded part. Do not use an image after a validation error.
- `super.img_sparsechunk.*` files are not auto-detected; use `--merge-parts` only for independent Sparse files and specify the correct part order manually.

## Format references

- [AOSP `sparse_format.h`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/include/sparse/sparse_format.h)
- [AOSP `sparse_read.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/sparse_read.cpp)
- [AOSP `simg2img.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/simg2img.cpp)

## Contributing

Bug reports, privacy-safe test files, and pull requests are welcome. Run the tests first and see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE).
