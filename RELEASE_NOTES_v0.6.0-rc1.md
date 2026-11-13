# sparse-to-raw v0.6.0-rc1

This release candidate consolidates the v0.6.0 feature line for final testing.

## Highlights

- Streaming conversion from RAW to Android Sparse v1.0 with RAW, FILL, and DONT_CARE chunks, CRC32, optional SHA-256, cancellation, and JSON reports.
- Logical RAW/Sparse comparison without creating intermediate RAW files, with first-difference offsets and logical SHA-256 hashes.
- Standalone Sparse Validator for headers, chunk sizes, block accounting, CRC32 checkpoints, image checksum, and trailing data.
- Reusable JSON Batch Profiles for mixed Sparse → RAW, RAW → Sparse, and QFIL queues.
- Qualcomm QFIL XML analysis and RAW assembly by physical partition. Patch commands are reported but not executed.
- Structured JSON reports for conversion, verification, validation, comparison, QFIL, and batch operations.
- Bilingual English/Russian CLI and GUI.

## Windows downloads

The Windows release workflow builds and attaches:

- `sparse-to-raw.exe` — standalone CLI.
- `sparse-to-raw-gui.exe` — standalone GUI.
- `sparse-to-raw-gui-windows.zip` — folder-based GUI package.
- `SHA256SUMS.txt` — SHA-256 checksums for the three application packages.

The GUI ZIP must be extracted as a complete folder. The CLI and GUI binaries are built and smoke-tested by GitHub Actions on Windows; the executables are not part of the source archive.

## Important notes

- Python 3.10+ is required when running from source. The CLI uses only the Python standard library; the GUI requires PySide6.
- The utility processes files only. It does not flash devices or communicate with connected phones.
- QFIL patch commands are parsed and reported, not executed.
- This is a release candidate. Please report regressions before the stable v0.6.0 release.
