# Android Super Image inspection and extraction

The **Super Image** module reads Android Dynamic Partitions metadata from `super.img` and extracts logical partitions as separate RAW files.

RAW and Android Sparse inputs are accepted. Sparse images are expanded into a temporary RAW file for LP metadata parsing; the original input is never modified, and the temporary file is removed after the operation.

## Features and limitations

- Read LP geometry and primary/backup metadata copies.
- Verify SHA-256 checksums for geometry, header, and tables.
- List logical partitions, sizes, groups, extent counts, and attributes.
- Select a metadata slot.
- Extract one, several, or all partitions into separate `NAME.img` files.
- Stream data with bounded memory, progress reporting, and cancellation.
- Existing files are protected unless replacement is explicitly confirmed or `--force` is supplied.

The current implementation supports LP metadata versions 10.0–10.2. For extraction, linear extents must reference block device index `0`, meaning a single input `super` file. Retrofit configurations with partition data spread across multiple physical images are not supported yet. Unknown or damaged metadata is rejected.

This is a file-only utility. It does not communicate with phones, unlock bootloaders, or flash device partitions. Independently verify outputs before relying on them in critical workflows.

Each partition is written and published separately. If extraction is cancelled or fails, files already completed remain in the output directory.

## GUI

Open **Super Image** from the top toolbar. Select a RAW or Sparse `super.img`, choose a metadata slot, and click **Read structure**. After the partition table appears, select the required partitions, choose an output directory, and click **Extract selected**. All detected partitions are selected by default.

Changing the source path or slot invalidates the loaded table; inspect the image again before extraction. If output files already exist, the application asks for confirmation before replacing them.

## CLI

Inspect metadata without extracting partitions:

```powershell
py sparse_to_raw.py super-info super.img --slot 0
```

Write the inspection result to JSON:

```powershell
py sparse_to_raw.py super-info super.img --slot 0 --json-report super-info.json
```

Extract all partitions:

```powershell
py sparse_to_raw.py super-extract super.img --output-dir extracted
```

Extract selected partitions only:

```powershell
py sparse_to_raw.py super-extract super.img --output-dir extracted --partition system --partition vendor
```

Add `--force` to replace existing files. Repeat `--partition` to select multiple partitions; omit it to extract all partitions in the selected slot. `--slot` defaults to `0`.
