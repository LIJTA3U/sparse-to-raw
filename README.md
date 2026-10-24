# sparse-to-raw

A small command-line utility to inspect Android Sparse Images and convert them to raw images. It is written in Python and uses only the standard library.

> A streaming Android Sparse Image to RAW converter with a CLI and PySide6 GUI for Windows.

[![Tests](https://img.shields.io/github/actions/workflow/status/LIJTA3U/sparse-to-raw/tests.yml?branch=main&label=tests)](https://github.com/LIJTA3U/sparse-to-raw/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CLI has no dependencies](https://img.shields.io/badge/CLI-no%20extra%20dependencies-brightgreen.svg)](#requirements)

**Language:** English · [Русский](README.ru.md)

<<<<<<< HEAD
> **Статус: экспериментальная версия.** Реализация была побайтно сравнена с `simg2img.exe` на двух Android-образах: `super.img` размером около 3,6 ГБ из заводской прошивки Blackview и `userdata_exp.ai.img` размером около 6,83 ГБ из заводской прошивки Google Pixel. В обоих случаях различий не обнаружено. Это подтверждает корректность преобразования для данных файлов, но не заменяет независимое тестирование на разных образах и устройствах.
=======
> **Status: experimental.** The implementation was compared byte-for-byte with `simg2img.exe` using two Android images: `super.img` (approximately 3.6 GB) and `userdata_exp.ai.img` (approximately 6.83 GB) from Google Pixel factory firmware. No differences were found in either comparison. This confirms correct conversion for these specific files, but does not replace independent testing across different images and devices.
>>>>>>> 58855c0 (Release v0.4.0 with GUI improvements and new features)

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
- PySide6 GUI with Russian/English language selection and persistent settings.
- Switchable speed display: decimal MB/s, binary MiB/s, or Mbit/s.
- Sparse-image analysis without producing a RAW output, with JSON export.
- Sequential batch queue with a detailed JSON run report.
- Visual merging of independent Sparse parts with manual ordering.
- Application icon, larger action icons, recent-file history, and saved paths/window geometry.

`DONT_CARE` ranges are interpreted as zero bytes. The filesystem may store them as sparse file holes, while the logical output size and readable contents remain correct.

## Requirements

- Python 3.10 or newer when running from source.
- The CLI has no third-party package requirements.
- Developers who want the GUI need PySide6: `python -m pip install -r requirements-gui.txt`.
- Enough free disk space for the expanded image.

## Windows desktop GUI

The PySide6 GUI includes a dark futuristic theme, angular yellow frame, cyan accents, drag-and-drop, progress statistics, and diagnostics. Version `v0.4.0` adds Russian/English switching, saved preferences and recent files, speed units (MB/s, MiB/s, Mbit/s), Sparse analysis, a sequential batch queue, visual ordered merging of independent Sparse parts, a bundled application icon, and detailed JSON reports. It calls the same conversion and validation functions as the CLI.

<<<<<<< HEAD
![Главное окно sparse-to-raw GUI](sparse-to-raw-gui.png)

Запуск GUI из исходников:
=======
![Main window of sparse-to-raw GUI](sparse-to-raw-gui.png)

For developer setup, headless tests, and PyInstaller packaging, see [GUI_DEVELOPMENT.md](GUI_DEVELOPMENT.md).

Run it from source:
>>>>>>> 58855c0 (Release v0.4.0 with GUI improvements and new features)

```bat
py -m pip install -r requirements-gui.txt
py sparse_to_raw_gui.py
```

The icon resource is `assets/sparse-to-raw.ico`. Use the language and speed selectors in the main window to change UI language and throughput units. The **Analyze image** action verifies metadata and exports JSON; **Task queue** converts multiple images sequentially; **Merge Sparse** lets you reorder independent parts before merging.

Conversion and analysis run in Qt worker threads. The UI reports actual processing progress, throughput, CRC32 and image-checksum validation; cancellation discards temporary output and leaves an existing destination intact. Language, speed units, recent input files, last paths and window geometry are saved between launches. The batch queue writes a detailed JSON summary to the output directory, and analysis/conversion/merge reports can be exported manually. If the output file already exists, the app asks for confirmation before replacing it.

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
py -m PyInstaller --clean --windowed --onedir --name sparse-to-raw-gui --icon assets/sparse-to-raw.ico --add-data "assets/sparse-to-raw.ico;assets" sparse_to_raw_gui.py
```

The CLI EXE is created at `dist\sparse-to-raw.exe`, and the GUI folder at `dist\sparse-to-raw-gui`. The Windows build workflow also creates a ZIP of the GUI folder and a standalone GUI EXE. **Build Windows applications** attaches all assets to GitHub Releases and smoke-tests the bundled GUI with Python hidden from `PATH`.

## Tests

```bash
python -m unittest discover -s tests -v
```

Core tests cover all supported chunk types, CRC and image-checksum failures, malformed/truncated data, trailing `DONT_CARE`, safe overwrite behavior, inspection/verification modes, multi-part merging, SHA-256, JSON reporting, progress callbacks, monotonic merge progress, and safe cancellation. GUI smoke tests cover path validation, language/speed settings, recent-file persistence, analysis worker results, batch conversion, and JSON report generation. GitHub Actions runs the core suite on multiple Python versions on Windows and Linux. A separate GUI workflow installs PySide6 and runs headless widget/path-validation smoke tests on Windows and Linux.

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
