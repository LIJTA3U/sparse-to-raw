# Android Ramdisk Inspector

`sparse-to-raw` can inspect CPIO archives stored in Android boot images or supplied as standalone ramdisk files, and safely extract selected entries. The CLI commands are `ramdisk-info` and `ramdisk-extract`; the GUI dialog is available from **Tools → Ramdisk Inspector**.

## Supported input layouts

- Legacy and generic Android boot images supported by Boot Image Inspector, including `boot.img`, `recovery.img`, and `init_boot.img`.
- `vendor_boot` v3/v4. For v4 images with multiple vendor ramdisk fragments, select one fragment by its zero-based index. If there is only one fragment, it is selected automatically.
- Standalone raw or compressed CPIO archives.

For `vendor_boot` v4, the selected fragment is read using the range described by the vendor ramdisk table. A fragment is inspected independently; the tool does not merge all fragments into a synthetic filesystem view. See the AOSP [vendor boot partitions](https://source.android.com/docs/core/architecture/partitions/vendor-boot-partitions) documentation for the purpose of the v4 fragment table.

## Supported compression and archive formats

The inspector recognizes and decompresses:

- Uncompressed CPIO `newc` (`070701`) and CRC CPIO `070702`.
- gzip, bzip2, XZ, LZMA-alone.
- LZ4 frame and LZ4 legacy frame.

The `070702` CPIO checksum is validated. `newc` does not contain a per-file data checksum. Concatenated CPIO archives and zero padding between archives are supported; later archives overlay earlier paths during extraction, so the last occurrence of a pathname wins.

Zstandard and LZO/lzop signatures are recognized, but decompression for these formats is not included in the dependency-free build. The CLI does not install or invoke external decompression tools.

## Inspect from the CLI

Inspect a boot image and print the CPIO inventory:

```powershell
py sparse_to_raw.py ramdisk-info boot.img
py sparse_to_raw.py ramdisk-info init_boot.img --json-report init-ramdisk.json
```

Inspect a specific `vendor_boot` v4 fragment (indexes start at zero):

```powershell
py sparse_to_raw.py ramdisk-info vendor_boot.img --fragment-index 1
```

Inspect a standalone compressed archive:

```powershell
py sparse_to_raw.py ramdisk-info vendor-ramdisk.cpio.gz
```

The report lists the input image type and selected section/fragment, compression format, CPIO format(s), archive and entry counts, file/directory/symlink counts, total file bytes, warnings, and per-entry path, type, size, mode, owner IDs, timestamps, inode/link information, and checksum status. `--json-report FILE` saves the inventory. Existing reports are protected unless `--force` is supplied.

## Extract all entries or selected paths

Extract the selected ramdisk archive to a new directory:

```powershell
py sparse_to_raw.py ramdisk-extract boot.img --output-dir ramdisk-files
```

Extract only selected entries. Repeat `--include` for multiple paths; selecting a directory includes its descendants:

```powershell
py sparse_to_raw.py ramdisk-extract boot.img --output-dir selected --include init --include etc
```

For a multi-fragment `vendor_boot` v4 image:

```powershell
py sparse_to_raw.py ramdisk-extract vendor_boot.img --fragment-index 1 --output-dir recovery-ramdisk
```

The default decompression limit is 512 MiB. Adjust it when needed:

```powershell
py sparse_to_raw.py ramdisk-info boot.img --max-unpacked-mib 1024
```

The decompressed CPIO stream is staged in a temporary file and parsed with bounded memory. The default maximum is 200,000 CPIO entries. Extraction creates regular files and directories only. Existing non-empty output directories are protected by default; `--force` allows merging into the directory and replacing colliding files. A JSON report can be written with `--json-report`.

## Safe extraction behavior

- Absolute paths, parent traversal (`..`), Windows drive/alternate-stream syntax, reserved device names, and other unsafe path forms are skipped and reported.
- Symbolic links are not created as filesystem links. Their stored targets are written to `SYMLINKS.txt`.
- Device nodes, sockets, FIFOs, and other special entries are not created. They are listed in `SPECIAL_FILES.txt`.
- Hard-linked CPIO entries receive the same file contents, but are extracted as separate files rather than recreating filesystem hard-link relationships.
- File permission bits are applied where the host platform permits. Ownership, timestamps, directory permissions, SELinux labels, capabilities, and other filesystem metadata are not restored.
- The source boot image or standalone CPIO file is never modified.

## GUI

Open **Tools → Ramdisk Inspector**, choose a boot image or standalone CPIO archive, and click **Inspect contents**. For a `vendor_boot` v4 image with multiple fragments, enable the fragment selector and enter the zero-based index. The table lists each CPIO path, entry type, size, mode, and checksum status. Select one or more rows and use **Extract selected**, or use **Extract all**. A selected directory includes its child entries.

The dialog performs decompression, parsing, preview, and extraction in a worker thread. The operation can be cancelled. The decompression limit is configurable.

- **Search** matches CPIO paths case-insensitively.
- **Filters** show all entries, regular files, directories, symlinks, executable files (any execute bit set), or likely configuration files (for example `.rc`, `.prop`, `.fstab`, `.conf`, `.xml`, and `build.prop`). The configuration filter is heuristic, not a semantic parser.
- The inventory table shows path, CPIO type, size, permission bits, UID, GID, and checksum state.
- Selecting a regular file automatically loads its content in the **Preview** tab on a background worker. The **Preview text** button can reload the selected entry. Up to 256 KiB is displayed without extracting it to the destination. UTF-8 and BOM-marked UTF-16 are supported; Android configuration names such as `fstab`, `fstab.mt6762`, `fstab.mt6765`, `init.rc`, and `build.prop` are treated as text even when vendor data contains unusual bytes (NUL bytes still indicate binary data). Data identified as binary is shown as a short HEX preview. Large files are marked as truncated. The preview is read-only.
- Select one or more rows and use **Extract selected**. Selecting a directory includes all descendants. Search/filter changes clear the selection so hidden rows cannot be extracted accidentally.
- **Extract all** and **Export JSON** remain available.

Changing the source path or vendor fragment selection clears the previous inventory so that paths from one archive cannot accidentally be applied to another.

## Limitations

- Zstandard and LZO/lzop are detected but not decompressed in the dependency-free implementation.
- This tool reads CPIO newc/crc; it is not a general-purpose archive manager and does not repack boot images.
- It does not create symbolic links or special device nodes, restore ownership/SELinux metadata, or guarantee that extracted files form a bootable ramdisk.
- The decompression limit and CPIO entry limit are safety controls, not estimates of a device's available memory.
