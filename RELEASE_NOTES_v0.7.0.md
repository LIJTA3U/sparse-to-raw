# sparse-to-raw v0.7.0

Stable release of the v0.7.0 feature line.

Version 0.7.0 expands `sparse-to-raw` from a Sparse image converter into a broader Android firmware image inspection toolkit while retaining the dependency-free Python CLI and the PySide6 desktop GUI.

## Highlights

### Android Super Image Inspector and Extractor

- Inspect Android Dynamic Partitions metadata in RAW and Android Sparse `super.img` inputs.
- Validate LP geometry and metadata checksums, inspect primary metadata and fall back to backup metadata when necessary.
- List logical partitions, groups, slots, and extents; extract selected logical partitions.
- Use the `super-info` and `super-extract` CLI commands or the dedicated GUI tool.

### Qualcomm QFIL package preflight

- Use `qfil-validate` to inspect a QFIL package without creating output images.
- Check referenced source files, RAW source ranges, Sparse structure and CRCs, sector ranges, overlaps, planned per-LUN outputs, output-name conflicts, and available disk space.
- Run the same preflight from the GUI before assembling RAW outputs. Patch instructions are parsed and reported, not executed.

### AVB / VBMeta Inspector

- Inspect standalone VBMeta images and images containing an AVB footer.
- Review header flags, rollback metadata, public-key fingerprints, and supported Property, Hash, Hashtree, Kernel Cmdline, and Chain Partition descriptors.
- Compare embedded SHA-256 / SHA-512 digests for supported algorithms.
- Available through `vbmeta-info` and the GUI Tools menu.

### Android Boot Image Inspector

- Inspect legacy boot headers v0–v2, generic boot headers v3–v4, and `vendor_boot` v3–v4.
- Display component sizes and offsets, OS/build fields, kernel and ramdisk format hints, DTB, recovery DTBO, vendor ramdisk fragments, bootconfig, and structural AVB-footer/VBMeta ranges.
- Available through `boot-info` and the GUI Tools menu.

### Android Ramdisk Inspector

- Inventory CPIO entries in `boot`, `init_boot`, `recovery`, `vendor_boot` fragments, and standalone ramdisk archives.
- Support CPIO `newc` / `crc`, CRC checks, concatenated archives, and built-in decompression for gzip, bzip2, XZ, LZMA-alone, and LZ4 frame / legacy streams.
- Search paths, filter entry categories, preview text and HEX data, inspect UID/GID, export JSON, and safely extract selected paths or the complete archive.
- Compare two text configuration files side by side in the GUI, highlighting added, deleted, and modified lines.
- Available through `ramdisk-info`, `ramdisk-extract`, and the GUI Tools menu.

### GUI and release engineering

- Keep the main toolbar compact, with less-frequently used tools grouped in the Tools menu.
- Run long inspection and extraction tasks in background workers with progress and cancellation where supported.
- Build standalone Windows CLI, one-file GUI, and folder-based GUI packages with a SHA-256 manifest through GitHub Actions.

## Windows downloads

The GitHub Release contains:

- `sparse-to-raw.exe` — standalone command-line utility.
- `sparse-to-raw-gui.exe` — standalone one-file GUI application.
- `sparse-to-raw-gui-windows.zip` — folder-based GUI package. Extract the complete archive and keep its directory structure intact.
- `SHA256SUMS.txt` — SHA-256 checksums for the three application packages.

The packaged Windows applications do not require Python or PySide6 to be installed separately. For normal GUI use, the folder-based ZIP package is recommended.

## Compatibility validation scope

- Sparse-to-RAW output was compared byte-for-byte with AOSP `simg2img.exe` on two real factory images: Blackview `super.img` and Google Pixel `userdata_exp.ai.img`; both comparisons matched.
- Super Image inspection and extraction were exercised on Blackview RAW and factory Sparse `super.img` inputs through both CLI and GUI, with extracted partition SHA-256 values matching between the interfaces.
- A synthetic multi-extent Super Image fixture covers logical partitions whose extents are physically separated.
- These checks cover specific inputs and workflows; they are not comprehensive certification for every Sparse producer, Android device, firmware, or Dynamic Partitions layout.

## Known limitations

- Super Image LP metadata versions 10.0–10.2 are supported. Extraction currently requires linear extents to reference block device index `0`; multi-image retrofit layouts and arbitrary `super_*` sets are not supported.
- The VBMeta Inspector checks supported embedded digests and parses metadata, but does not verify RSA signatures, establish trusted-key authenticity, or compare rollback state with a device.
- The Boot Image Inspector is read-only. It does not unpack kernel or ramdisk payloads and does not verify AVB signatures.
- Ramdisk inspection supports CPIO `newc` / `crc`. Zstandard and LZO/lzop signatures are detected but those streams are not decompressed in the dependency-free build. Symlinks and special device/socket/FIFO entries are reported in manifests rather than created; ownership, timestamps, directory permissions, SELinux labels, and capabilities are not restored.
- Ramdisk configuration comparison is limited to text files up to 256 KiB per file; binary and truncated inputs are rejected.
- QFIL Patch commands are analyzed and reported, not replayed.
- The application processes files only. It does not flash devices or communicate with connected phones.

For critical firmware workflows, independently verify output images before using them.
