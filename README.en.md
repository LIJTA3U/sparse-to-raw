# sparse-to-raw

A small command-line utility to inspect Android Sparse Images and convert them to raw images. It is written in Python and uses only the standard library.

[![Tests](https://img.shields.io/github/actions/workflow/status/LIJTA3U/sparse-to-raw/tests.yml?branch=main&label=tests)](https://github.com/LIJTA3U/sparse-to-raw/actions/workflows/tests.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen.svg)](#requirements)

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
- Python standard library only; no third-party dependencies.

`DONT_CARE` ranges are interpreted as zero bytes. The filesystem may store them as sparse file holes, while the logical output size and readable contents remain correct.

## Requirements

- Python 3.10 or newer.
- Enough free disk space for the expanded image.

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

## Build a Windows `.exe`

PyInstaller is needed only for packaging, not for normal use:

```bat
py -m pip install pyinstaller
py -m PyInstaller --clean --onefile --name sparse-to-raw sparse_to_raw.py
```

The executable is created at `dist\sparse-to-raw.exe`. The **Build Windows executable** workflow attaches it to published GitHub Releases; a manual workflow run uploads it as an Actions artifact.

## Tests

```bash
python -m unittest discover -s tests -v
```

The tests cover all supported chunk types, CRC and image-checksum failures, malformed/truncated data, trailing `DONT_CARE`, safe overwrite behavior, inspection/verification modes, multi-part merging, SHA-256, and JSON reporting. GitHub Actions runs the test suite on multiple Python versions on Windows and Linux.

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
