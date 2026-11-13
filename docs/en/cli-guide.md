# CLI guide

The command-line converter is `sparse_to_raw.py`. It supports Android Sparse Image format v1 and uses only the Python standard library.

## CLI language

The CLI uses English by default. Select Russian for one command with `--lang ru`; use `--lang en` to explicitly select English. The option works with normal Sparse commands and QFIL commands, and may appear before or after the QFIL subcommand.

```powershell
py sparse_to_raw.py --help
py sparse_to_raw.py --lang ru --help
py sparse_to_raw.py qfil-analyze rawprogram0.xml --lang ru
```

To set the default language for the current shell session, use `SPARSE_TO_RAW_LANG=ru` (PowerShell: `$env:SPARSE_TO_RAW_LANG = "ru"`). The explicit `--lang` option takes precedence over the environment variable. Supported values are `en` and `ru`.

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

## Compare logical image contents

Compare two RAW and/or Android Sparse images without creating an intermediate RAW file:

```powershell
py sparse_to_raw.py compare super_raw.img super.img --json-report comparison.json
```

Each Sparse input is expanded in bounded 1 MiB windows while its structure, per-chunk CRC32 values, and optional image checksum are validated. RAW inputs are read directly. Both logical SHA-256 hashes are calculated. The report identifies the input formats and logical sizes and, when contents differ, the offset of the first differing byte. Comparison is streaming and does not require disk space for an expanded image.

Exit codes: `0` means the logical contents are identical, `1` means they differ, and `2` means an input or comparison error occurred. `--quiet` hides progress. `--json-report FILE` writes a machine-readable report and does not overwrite an existing report.

## Merge independent Sparse images

```bat
py sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --sha256
```

Pass all parts in the intended order. Every input must be a complete, independently valid Sparse image with its own header. The command validates the parts and does not publish the final output if a part fails. It is not an arbitrary byte-split reassembler.

The CLI accepts an explicitly ordered list and does not auto-discover split images. The GUI can discover `super.img_sparsechunk.*` groups and sort their numeric indexes.

## Verify the written RAW output (development branch)

```bash
python sparse_to_raw.py super.img super_raw.img --verify-output
```

For a merge:

```bash
python sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --verify-output
```

`--verify-output` is available on the current development branch. After the Sparse data and checksums have been validated and the RAW staging file has been closed, the program reads the staged RAW file again in bounded chunks. It compares the actual byte count and SHA-256 with the expected logical RAW contents computed while expanding the Sparse input. The destination is published only after this check succeeds. On mismatch, read error, or cancellation, the staging file is discarded and an existing destination is preserved.

This verification adds a complete read pass and therefore increases disk I/O and elapsed time. It is separate from, and does not replace, validation of the Sparse headers and checksums. With `--json-report`, the `output_verification` object records the expected and actual sizes and hashes, verified byte count, duration, and result. The option is valid for conversion and `--merge-parts`, not `--info` or `--verify-only`. The option is included in the published v0.5.0 release line and the v0.6.0 release candidate and release line.

## Qualcomm QFIL manifests

Analyze Qualcomm manifests and locate the referenced firmware files:

```bat
py sparse_to_raw.py qfil-analyze rawprogram0.xml --patch-xml patch0.xml --search-dir . --json-report qfil-analysis.json
```

Assemble one RAW image per physical partition/LUN:

```bat
py sparse_to_raw.py qfil-build rawprogram0.xml --patch-xml patch0.xml --search-dir . --output-dir raw-output --json-report qfil-build.json
```

Pass multiple rawprogram manifests as positional arguments and repeat `--patch-xml` / `--search-dir` for additional files and folders. The file resolver checks paths relative to each XML, then searches the manifest folder and selected search directories recursively. Ambiguous matches stop the build rather than choosing a file arbitrarily.

The assembler supports `<program>` and `<erase>` operations, sector sizes, file-sector offsets, physical partition numbers, raw input files, and sources marked `sparse="true"`. Sparse data is validated and expanded directly into the staged output. `DONT_CARE` and erase ranges are zero-filled. Patch XML is included in the report but is not applied.

For coordinates such as `NUM_DISK_SECTORS-33`, provide the disk size in sectors for that LUN:

```bat
py sparse_to_raw.py qfil-build rawprogram0.xml --search-dir . --output-dir raw-output --disk-sectors 0=61071360
```

Overlapping ranges are rejected unless `--allow-overlap` is supplied after review. `--force` is needed to replace existing RAW outputs or JSON reports. The complete QFIL behavior and safety boundaries are described in the [QFIL XML guide](qfil-xml.md).

## Hide the progress indicator

```bash
python sparse_to_raw.py super.img super_raw.img --quiet
```

## Options

```text
usage: sparse_to_raw.py [-h] [--lang {en,ru}] [--version] [--merge-parts SPARSE_FILE ...]
                        [--output FILE] [--info | --verify-only] [--force]
                        [--sha256] [--verify-output] [--json-report FILE] [--quiet]
                        [input_sparse] [output_raw]

Subcommands: compare LEFT RIGHT | raw-to-sparse INPUT_RAW OUTPUT_SPARSE
QFIL commands: qfil-analyze RAWPROGRAM.XML ... | qfil-build RAWPROGRAM.XML ... --output-dir DIR
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
| `--version` | Print the CLI version |
| `--lang {en,ru}` | Select the CLI language; English is the default |

Run `python sparse_to_raw.py --help` for the help text shipped with your checkout.

## Sparse Validator

Validate an Android Sparse image without creating a RAW output:

```powershell
py sparse_to_raw.py validate input.sparse
py sparse_to_raw.py validate input.sparse --json-report validation.json
py sparse_to_raw.py validate input.sparse --no-sha256 --quiet
```

Exit codes: `0` means valid, `1` means the image failed validation, and `2` means an execution or filesystem error. Existing JSON reports are not overwritten unless `--force` is specified. The validator checks the complete stream and calculates logical SHA-256 by default; `--no-sha256` skips only the SHA-256 calculation. No intermediate RAW file is written.
