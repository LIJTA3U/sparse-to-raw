# sparse_to_raw.py

A small, dependency-free Python converter for Android Sparse Image files. It expands Android sparse images into raw images and validates the input structure and supported checksums.

**Languages:** [На русском README.ru.md](README.ru.md) · English

**Status: experimental v0.1.** It was compared byte-for-byte against `simg2img.exe` using one 3.6 GB Android `super.img` test image. That comparison matched; broader independent testing is still recommended before relying on this tool for other images.

## Features

- Supports Android sparse format major version 1.
- Supports `RAW`, `FILL`, `DONT_CARE`, and `CRC32` chunks.
- Validates every CRC32 chunk.
- Validates the image-level checksum when `image_checksum` is non-zero.
- Checks header/chunk sizes, truncated payloads, block-count mismatches, unsupported chunk types, and trailing data.
- Writes to a temporary file first and replaces the destination only after validation succeeds, so a failed conversion will not replace an existing output.
- Uses only the Python standard library; works on Python 3.10+ on Windows, macOS, and Linux.

`DONT_CARE` regions read back as zero bytes. Filesystems may represent these regions as sparse holes rather than allocating every zero byte physically; the logical output size and contents remain correct.

## Usage

```bash
python sparse_to_raw.py input_sparse.img output_raw.img
```

Example for Windows Command Prompt:

```bat
python sparse_to_raw.py super.img super_raw.img
```

Ensure the destination drive has enough free space for the expanded image. The converter reports the expected raw size and CRC32 at completion.

## Tests

Run from the project directory:

```bash
python -m unittest discover -s tests -v
```

The tests cover all supported chunk types, successful CRC validation, checksum failures, malformed/truncated input, trailing data, output sizing for trailing `DONT_CARE` chunks, and keeping an existing destination intact if conversion fails.

## Safety notes

This utility only reads an input file and creates an output file. It does not access devices, partitions, or flash storage. Review paths carefully, preserve backups, and independently verify important images before using them in firmware operations.

## Format references

- Android sparse format header and chunk types: [AOSP `sparse_format.h`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/include/sparse/sparse_format.h)
- AOSP sparse image parser and CRC checks: [AOSP `sparse_read.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/sparse_read.cpp)
- AOSP `simg2img`: [AOSP `simg2img.cpp`](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/simg2img.cpp)

## License

MIT. See [LICENSE](LICENSE).
