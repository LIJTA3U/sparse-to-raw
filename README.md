# sparse-to-raw

A streaming Android Sparse Image v1 inspector and converter that expands Sparse images to logical RAW content. The project provides a dependency-free Python CLI and a PySide6 desktop GUI for Windows.

[![Tests](https://img.shields.io/github/actions/workflow/status/LIJTA3U/sparse-to-raw/tests.yml?branch=main&label=tests)](https://github.com/LIJTA3U/sparse-to-raw/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CLI has no dependencies](https://img.shields.io/badge/CLI-no%20extra%20dependencies-brightgreen.svg)](#requirements)

**Language:** English · [Русский](README.ru.md)

> **Status: experimental.** The implementation was compared byte-for-byte with `simg2img.exe` using two Android images: `super.img` (approximately 3.6 GB) from Blackview factory firmware and `userdata_exp.ai.img` (approximately 6.83 GB) from Google Pixel factory firmware. No differences were found in either comparison. These results apply to those two files and do not replace independent testing on other images and devices.

## Features

- Convert Android Sparse Image format v1 to logical RAW output.
- Support `RAW`, `FILL`, `DONT_CARE`, and `CRC32` chunks.
- Validate per-chunk CRC32, the image checksum, headers, block sizes/counts, truncation, and trailing bytes.
- Inspect or verify an image without creating a RAW file (`--info`, `--verify-only`).
- Protect existing output files by default; `--force` is required to replace them.
- Report progress, throughput, processed bytes, and chunk counts.
- Optionally calculate SHA-256 over the logical RAW contents and export JSON reports.
- Merge independent Sparse images in an explicitly supplied order (`--merge-parts`).
- Stream large images without loading the complete input or output into memory.
- Use only the Python standard library for the CLI.
- Provide a PySide6 GUI with Russian/English language selection, saved preferences, recent files, image analysis, sequential batch conversion, visual ordered merging, and JSON reports.

`DONT_CARE` ranges are interpreted as zero bytes. The resulting logical RAW contents and size are correct; the filesystem may store zero ranges as sparse holes.

## Download for Windows

**Release:** [sparse-to-raw v0.4.0](https://github.com/LIJTA3U/sparse-to-raw/releases/tag/v0.4.0)

The release provides:

- `sparse-to-raw-gui-windows.zip` — recommended GUI package. Extract the entire folder and run `sparse-to-raw-gui.exe` from inside it.
- `sparse-to-raw-gui.exe` — standalone GUI executable.
- `sparse-to-raw.exe` — standalone CLI executable.

End users do not need to install Python to run the packaged Windows applications. The folder ZIP is recommended for normal use; keep the extracted directory structure intact.

## Windows GUI

The GUI uses a dark theme with an angular yellow frame and cyan accents. It supports drag-and-drop, progress statistics, an operation log, saved settings, recent input files, and speed display in decimal MB/s, binary MiB/s, or Mbit/s.

![Main window of sparse-to-raw GUI](docs/screenshots/main-window-en.png)

The **Analyze image** action verifies metadata without creating a RAW output. **Task queue** processes multiple files sequentially and writes a JSON summary. **Merge Sparse** lets the user reorder independent Sparse images before merging. Conversion and analysis run in Qt worker threads; cancellation removes staging output and preserves an existing destination.

See the [GUI guide](docs/en/gui-guide.md) and [Windows installation guide](docs/en/installation.md).

## Quick start (CLI)

Python 3.10 or newer is required when running from source. The CLI has no third-party package dependencies.

```bash
python sparse_to_raw.py input_sparse.img output_raw.img
```

On Windows Command Prompt:

```bat
py sparse_to_raw.py super.img super_raw.img
```

If the destination exists, conversion stops without replacing it. To explicitly allow replacement:

```bat
py sparse_to_raw.py super.img super_raw.img --force
```

Inspect and validate without conversion:

```bash
python sparse_to_raw.py super.img --info
python sparse_to_raw.py super.img --verify-only
```

Calculate the logical RAW SHA-256 and save a report:

```bash
python sparse_to_raw.py super.img super_raw.img --sha256 --json-report report.json
```

Merge independent Sparse files in the order supplied:

```bat
py sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --sha256
```

Each merge input must be a complete, independent Sparse image with its own header. This mode is not intended for arbitrary byte-level pieces cut from one Sparse file. The current release does not automatically discover or numerically sort `super.img_sparsechunk.*` files.

For all CLI options, examples, and exit behavior, see the [CLI guide](docs/en/cli-guide.md).

## Documentation

- [Installation](docs/en/installation.md)
- [CLI guide](docs/en/cli-guide.md)
- [GUI guide](docs/en/gui-guide.md)
- [Development and packaging](docs/en/development.md)
- [Changelog](docs/en/changelog.md)
- [Contributing](docs/CONTRIBUTING.md)
- [Security policy](docs/SECURITY.md)
- [Screenshots](docs/screenshots/)

The [Russian README](README.ru.md) links to the Russian documentation in `docs/ru/`.

## Tests

Run the complete test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

The core suite covers chunk types, checksums, malformed and truncated data, safe output handling, info/verification modes, merging, SHA-256, JSON reports, progress callbacks, and cancellation. GUI smoke tests cover path validation, widgets, language and speed settings, recent files, worker integration, analysis, batch conversion, and the packaged self-test entry point. GitHub Actions runs core tests on Python 3.10–3.13 on Windows and Linux; GUI smoke tests run on Windows and Linux with PySide6.

## Limitations and safety

- This is an experimental project, not an official AOSP `simg2img` replacement.
- Independent byte-for-byte comparisons were performed on the two real images named above. Verify outputs independently before using them for critical work.
- The utility works with files only. It does not communicate with phones or flash device partitions.
- Check input/output paths and available disk space before conversion. Merging needs staging space for the combined output and the currently expanded part.
- Sparse part discovery and automatic numeric ordering are not included in v0.4.0; provide independent files to `--merge-parts` in the correct order.

## References

- [AOSP `sparse_format.h`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/include/sparse/sparse_format.h)
- [AOSP `sparse_read.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/sparse_read.cpp)
- [AOSP `simg2img.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/simg2img.cpp)

## License

[MIT](LICENSE).
