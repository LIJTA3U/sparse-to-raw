# Qualcomm QFIL XML support

The CLI can inspect Qualcomm Firehose/QFIL `rawprogram*.xml` and `patch*.xml` manifests and reconstruct one RAW image per physical partition (LUN).

## Analyze a firmware package

```bat
py sparse_to_raw.py qfil-analyze rawprogram0.xml --patch-xml patch0.xml --search-dir .
```

Pass additional `rawprogram*.xml` files as positional arguments and repeat `--patch-xml` or `--search-dir` when needed:

```bat
py sparse_to_raw.py qfil-analyze rawprogram0.xml rawprogram1.xml --patch-xml patch0.xml --patch-xml patch1.xml --search-dir . --json-report qfil-analysis.json
```

The report includes operation type, label, LUN, sector coordinates, sector size, source filename, source-resolution result, partition summary and patch attributes. File lookup first checks the path relative to the XML manifest, then searches the manifest folder and each `--search-dir` recursively by filename. A name with multiple matching files is marked ambiguous; the tool does not choose one arbitrarily.

## Full package preflight validation

`qfil-analyze` quickly parses the XML and reports resolved/missing files. Before assembly, run the dedicated `qfil-validate` command:

```bat
py sparse_to_raw.py qfil-validate rawprogram0.xml rawprogram1.xml --patch-xml patch0.xml --search-dir . --output-dir raw-output
```

This runs the same preflight checks as assembly but **does not create the output directory or any RAW files**. It checks:

- resolution of every file referenced by a `<program>` operation;
- whether ordinary RAW sources are long enough after applying `file_sector_offset` and the requested sector count;
- the complete structure of every `sparse="true"` source, including CRC32 checkpoints and the image checksum when present;
- sector expressions, sector-size consistency, range boundaries and overlaps;
- planned RAW sizes per LUN, existing output paths and available disk space.

For coordinates relative to the end of a device, pass its sector count separately for each LUN. In the GUI, enter values separated by semicolons or commas, for example `0=61071360; 1=30535680`. Full Sparse validation runs in a background worker, and the progress bar reports progress for the current file.

Save the detailed result with `--json-report`. Patch XML is still inspection-only and is never executed. A successful preflight does not replace independent verification of the RAW images after assembly.

## Assemble RAW images

```bat
py sparse_to_raw.py qfil-build rawprogram0.xml --patch-xml patch0.xml --search-dir . --output-dir raw-output --json-report qfil-build.json
```

The command writes `physical_partition_0.raw`, `physical_partition_1.raw`, and so on, one output per LUN present in the manifests. `SECTOR_SIZE_IN_BYTES`, `start_sector`, `num_partition_sectors`, `file_sector_offset`, `physical_partition_number`, `filename`, and the `sparse` flag are used to place content. Raw files are copied in bounded chunks. A source marked `sparse="true"` is expanded directly into the staged RAW output and undergoes the normal Sparse structural and checksum validation; no intermediate expanded RAW file is created.

The output is initialized as zero-filled storage. `DONT_CARE` data and `<erase>` ranges therefore remain zero-filled; an erase operation is also applied in manifest order if overlaps have explicitly been allowed. The destination is staged before publication, existing files are not overwritten unless `--force` is used, and free space is checked before assembly.

## Sector expressions and overlaps

Some manifests use end-relative coordinates such as `NUM_DISK_SECTORS-33`. The disk capacity is not encoded in that expression, so supply the sector count for the corresponding LUN:

```bat
py sparse_to_raw.py qfil-build rawprogram0.xml --search-dir . --output-dir raw-output --disk-sectors 0=61071360
```

Specify one `--disk-sectors LUN=COUNT` value per LUN that uses an end-relative expression. The value is a sector count, not a byte size.

Overlapping write/erase ranges are rejected by default. After reviewing the manifest, explicitly permit intentional overlaps with `--allow-overlap`. Operations are then applied in XML order, and later operations replace earlier bytes.

## Patch XML safety

`patch*.xml` is parsed and included in analysis/JSON reports, but patch values are **not applied** to reconstructed RAW files. QFIL patch instructions can depend on a matching Firehose programmer, device geometry, and other build-specific state. Applying their values without that context could produce an incorrect image. Treat the patch report as a review checklist and use the original vendor package/programmer for any device-specific patching.

## Exit codes and dependencies

- `0` — XML analysis or RAW assembly completed.
- `2` — invalid XML, unresolved/ambiguous source, unsupported sector expression, overlap, insufficient disk space, or an I/O error.

QFIL support uses only Python's standard library. The optional GUI still requires PySide6; the CLI does not.
