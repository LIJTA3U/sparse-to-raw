# CLI guide

The command-line converter is `sparse_to_raw.py`. It supports Android Sparse Image format v1 and uses only the Python standard library.

## Basic conversion

```bash
python sparse_to_raw.py input_sparse.img output_raw.img
```

Windows example:

```bat
py sparse_to_raw.py super.img super_raw.img
```

The tool validates the Sparse structure and applicable checksums while expanding the logical RAW contents. Existing destination files are not replaced by default.

## Inspect without producing RAW

```bash
python sparse_to_raw.py super.img --info
```

`--info` validates the image and prints format information, block size, expected RAW size, and chunk counts without creating an output image.

## Verify without producing RAW

```bash
python sparse_to_raw.py super.img --verify-only
```

`--verify-only` checks the structure and checksums without writing a RAW file. A validation failure returns a non-zero exit code.

## Replace an existing destination explicitly

```bash
python sparse_to_raw.py super.img super_raw.img --force
```

`--force` permits replacing an existing output file. Without it, an existing destination is preserved.

## Calculate SHA-256 and write JSON

```bash
python sparse_to_raw.py super.img super_raw.img --sha256 --json-report report.json
```

SHA-256 is calculated over the logical RAW contents, including zero-filled `DONT_CARE` ranges; it is not the hash of the compressed Sparse input. Existing report files are also protected unless `--force` is supplied.

## Merge independent Sparse images

```bat
py sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --sha256
```

Pass all parts in the intended order. Every input must be a complete, independently valid Sparse image with its own header. The command validates the parts and does not publish the final output if a part fails. It is not an arbitrary byte-split reassembler.

Version 0.4.0 does not discover or numerically sort `super.img_sparsechunk.*` files automatically; the order must be specified by the user.

## Verify the written RAW output (development branch)

```bash
python sparse_to_raw.py super.img super_raw.img --verify-output
```

For a merge:

```bash
python sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --verify-output
```

`--verify-output` is available on the current development branch. After the Sparse data and checksums have been validated and the RAW staging file has been closed, the program reads the staged RAW file again in bounded chunks. It compares the actual byte count and SHA-256 with the expected logical RAW contents computed while expanding the Sparse input. The destination is published only after this check succeeds. On mismatch, read error, or cancellation, the staging file is discarded and an existing destination is preserved.

This verification adds a complete read pass and therefore increases disk I/O and elapsed time. It is separate from, and does not replace, validation of the Sparse headers and checksums. With `--json-report`, the `output_verification` object records the expected and actual sizes and hashes, verified byte count, duration, and result. The option is valid for conversion and `--merge-parts`, not `--info` or `--verify-only`. The published v0.4.0 binary does not include this development option.

## Hide the progress indicator

```bash
python sparse_to_raw.py super.img super_raw.img --quiet
```

## Options

```text
usage: sparse_to_raw.py [-h] [--merge-parts SPARSE_FILE [SPARSE_FILE ...]]
                        [--output FILE] [--info | --verify-only] [--force]
                        [--sha256] [--verify-output] [--json-report FILE] [--quiet]
                        [input_sparse] [output_raw]
```

| Option | Description |
|---|---|
| `input_sparse` | Input Android Sparse image |
| `output_raw` | Destination RAW image for normal conversion |
| `--merge-parts FILE...` | Merge two or more independent Sparse files in the supplied order |
| `--output FILE` | Destination RAW path for `--merge-parts` |
| `--info` | Validate and print image metadata without conversion |
| `--verify-only` | Validate structure/checksums without creating RAW |
| `--force` | Allow replacing an existing destination or report |
| `--sha256` | Calculate SHA-256 of logical RAW contents |
| `--verify-output` | Re-read staged RAW and verify its size and logical-content SHA-256 before commit (development branch) |
| `--json-report FILE` | Write a JSON report |
| `--quiet` | Hide the progress indicator |

Run `python sparse_to_raw.py --help` for the help text shipped with your checkout.
