## [Unreleased] — v0.7.0 development

### Added
- Added the read-only `vbmeta-info` CLI command and AVB / VBMeta Inspector in the GUI Tools menu. It parses standalone VBMeta and AVB-footer images, header flags, rollback metadata, public-key fingerprints, and supported Property, Hash, Hashtree, Kernel Cmdline, and Chain Partition descriptors.
- Added bounded parsing, block-overlap checks, and embedded SHA-256 / SHA-512 digest comparison for supported AVB algorithms. RSA signature verification, trusted-key validation, and device rollback-state comparison are intentionally not performed.
- Added `qfil-validate` for a complete no-output QFIL preflight: source-range checks, full streaming validation of referenced Sparse files and CRCs, per-LUN output planning, collision checks, and available-space checks.
- Added QFIL GUI controls for per-LUN disk sector counts and a background **Validate package** action with progress reporting before RAW assembly.
- Android Super Image inspection and extraction for RAW and Android Sparse inputs: LP geometry/metadata checksum validation, primary/backup metadata fallback, slot selection, partition/group/extent listing, and extraction of selected logical partitions.
- `super-info` and `super-extract` CLI commands with optional JSON reports.
- Regression fixtures for LP partitions assembled from multiple physically separated extents, covering RAW, Android Sparse, and CLI extraction paths.
- Dedicated bilingual Super Image GUI dialog with background inspection/extraction, progress, cancellation, and source/slot change invalidation.

### Changed
- Reorganized the main GUI toolbar into a five-item primary row and a compact secondary row. Less-frequent actions (Sparse merge, report export, and diagnostics) are grouped under an icon-bearing Tools menu.
- Added icons/tooltips consistently to visible toolbar actions and tightened spacing to prevent clipped labels.
- Super Image extraction now uses an atomic no-clobber commit when overwrite is not explicitly enabled.

### Limitations
- LP metadata versions 10.0–10.2 are supported. Extraction currently requires extents to reference block device index 0; multi-image retrofit layouts are not supported.

---

## v0.6.0 — stable release

The v0.6.0 feature line is now released as a stable version. Windows packages were built by GitHub Actions; the packaged application was confirmed to run on a Windows computer without Python installed.

### Included functionality

- Streaming RAW → Android Sparse v1.0 conversion with configurable block size, `RAW` / `FILL` / `DONT_CARE` chunks, CRC32, optional SHA-256, atomic output, cancellation, and JSON reports.
- Standalone streaming Sparse Validator for headers, chunk layout and lengths, block accounting, CRC32 checkpoints, optional image checksum, and trailing data — without creating a RAW file.
- Logical comparison for RAW ↔ RAW, RAW ↔ Sparse, and Sparse ↔ Sparse, including first-difference offset and logical SHA-256 — without an intermediate RAW file.
- Qualcomm QFIL XML analysis and RAW assembly by physical partition. Patch instructions are reported but are not executed.
- Mixed sequential Batch Queue and reusable, versioned JSON Batch Profiles for Sparse → RAW, RAW → Sparse, and QFIL.
- Structured JSON reports for conversions, verification, validation, comparison, QFIL, and batch operations.
- Bilingual CLI/GUI and automated Windows CLI/GUI packaging with SHA-256 manifest.

### Compatibility scope

Byte-for-byte comparison against `simg2img.exe` was completed on two real Android Sparse images: Blackview factory `super.img` (about 3.6 GB) and Google Pixel factory `userdata_exp.ai.img` (about 6.83 GB). Both comparisons matched. These two images are a limited validation sample, not comprehensive compatibility certification. Dynamic Partitions `super` containers and arbitrary multi-file `super_*` layouts are outside the tested scope. The [4PDA discussion of a ten-file Vivo V70 Elite `super` layout](https://4pda.to/forum/index.php?showtopic=496786&st=5460) illustrates why such containers must be distinguished from standalone Sparse v1 files; that scenario has not been tested with this application.

### Safety notes

- The application operates on files and does not flash devices or communicate with connected phones.
- QFIL patch commands are parsed and reported but never executed.
- Verify critical output independently before using it in firmware workflows.

---

## v0.6.0-rc1 — release candidate

This release candidate consolidates the v0.6.0 feature line and is intended for final cross-platform and Windows-package verification.

### Image conversion and integrity

- Added streaming RAW → Android Sparse v1.0 conversion with configurable block size, `RAW` / `FILL` / `DONT_CARE` chunks, CRC32, optional SHA-256, atomic output, cancellation, and JSON reports.
- Added a dedicated streaming Sparse Validator for headers, chunk layout and lengths, block accounting, CRC32 checkpoints, optional image checksum, and trailing data — without creating a RAW file.
- Added streaming logical comparison for RAW ↔ RAW, RAW ↔ Sparse, and Sparse ↔ Sparse, including the first differing byte and logical SHA-256 hashes — without creating an intermediate RAW file.
- Retained Sparse → RAW conversion, read-back output verification, image inspection, and ordered merge support.

### QFIL and batch processing

- Added Qualcomm QFIL `rawprogram*.xml` / `patch*.xml` analysis and RAW assembly by physical partition. Patch instructions are reported but are not executed.
- Added mixed sequential Batch Queue support for Sparse → RAW, RAW → Sparse, and QFIL tasks.
- Added versioned JSON Batch Profiles with task order, operation settings, portable relative paths where possible, validation, overwrite protection, and safe queue replacement.
- Added JSON reports for conversion, validation, comparison, QFIL processing, and batch runs.

### Desktop app and release engineering

- Added dedicated GUI workflows for RAW → Sparse, logical comparison, and Sparse validation, with progress and cancellation where supported.
- Centralized the CLI/GUI application version.
- Added Windows release automation for a standalone CLI executable, a folder-based GUI package, and a one-file GUI executable. The workflow runs tests, compilation, packaged CLI checks, and packaged GUI self-tests before uploading assets and a SHA-256 manifest to an existing GitHub Release.
- CI covers Python 3.10–3.14 on Windows and Linux; GUI smoke tests run with PySide6 on Windows and Linux.

### Compatibility and safety notes

- The CLI uses only the Python standard library; the GUI requires PySide6 when run from source.
- The application works with image files and does not flash devices or communicate with connected phones.
- QFIL patch commands are analyzed and reported, not executed.
- Verify important outputs independently before using them for device repair or other critical work.

### Release-candidate validation

- Core unit tests: 125 passed in the preparation environment.
- Python compilation and CLI `--version` / `--help`: passed.
- Windows GUI smoke tests were also run by the project maintainer against the preceding dev12 build; the RC must be checked through GitHub Actions and on a clean Windows system before marking v0.6.0 stable.
- Windows executables are built by `.github/workflows/build-windows-release.yml`; they are not included in this source archive.

## v0.6.0-dev12 — release stabilization

- Centralized the CLI/GUI application version so both entry points report the same build identifier.
- Expanded the Windows packaging workflow to run the complete unit-test suite and Python compilation before building.
- Added packaged CLI `--version` and `--help` smoke checks alongside the existing bundled GUI self-tests.
- Expanded CI coverage to Python 3.14 and added ignore rules for Android Sparse images and common split-image files.
- Refreshed installation, task-queue, and bilingual release-history documentation for the v0.6.0 development line.

## v0.6.0-dev11-hotfix2 — Windows batch-profile path handling

- Canonicalize restored task paths so Windows 8.3 short names are expanded to their long spelling, while deliberately selected symlink aliases retain their spelling.
- Keep queue-level option paths lexical so their exact text round-trips; preserve relative-path portability.
- Add regression coverage for the Windows path and symlink cases.

## v0.6.0-dev11 — batch profiles

- Added JSON Batch Queue profiles for task order, Sparse → RAW / RAW → Sparse / QFIL task definitions, output folder, overwrite, and verification settings.
- Paths are stored relative to the profile when possible; the loader validates the format, version, task types, and options before replacing the active queue.
- Loading requires confirmation; restored tasks start in the waiting state, and missing input files are reported.
- Added atomic profile writes, overwrite protection, file/task limits, and round-trip/malformed-profile tests.

## v0.6.0-dev10 — Sparse Validator

- Add a dedicated streaming Sparse Validator to the CLI and GUI.
- Validate Sparse headers, chunk types and lengths, block accounting, end-of-file boundaries, CRC32 checkpoints, and the optional image checksum without producing a RAW file.
- Generate a structured validation report with integrity assessment, chunk counts, warnings, optional logical SHA-256, and JSON export.
- Add cancellation and progress reporting in the GUI; retain separate analysis and structure-viewer tools.

## v0.6.0-dev9 — logical RAW/Sparse comparison

- Added streaming logical comparison for RAW ↔ RAW, RAW ↔ Sparse, and Sparse ↔ Sparse inputs.
- Sparse streams are structurally validated, including chunk CRC32 checkpoints and the optional image checksum; no expanded intermediate RAW file is created.
- Reports include both logical SHA-256 hashes, logical sizes, formats, and the first differing byte offset.
- Added the `compare` CLI subcommand and a background GUI comparison dialog with progress, cancellation, and JSON export.
- Added regression tests for matching images, differences, length mismatch, malformed checksums, cancellation, and CLI exit codes.

## v0.6.0-dev8 — RAW → Sparse GUI and queue integration

- Added a dedicated RAW → Sparse GUI dialog with input/output selection, configurable block size, progress, cancellation, CRC32 and SHA-256 summary.
- Added RAW → Sparse tasks to Batch Queue, including mixed sequential queues with Sparse → RAW and QFIL tasks.
- Kept conversion streaming and atomic; cancellation removes temporary output.
- Updated GUI documentation and synchronized CLI/GUI version strings.

### Validation
- Full standard-library/unit test suite and Python compilation are run for this development archive.
- PySide6 GUI smoke tests require a PySide6-enabled environment.

## v0.6.0-dev6 — regression stabilization

### Fixed
- Synchronized the CLI `--version` output with the GUI/application version. The CLI previously reported an older development build even when the GUI showed a newer one.

### Tests
- Added a regression test that checks the CLI version string.
- Re-ran the full dependency-free unit test suite; GUI smoke tests remain a separate PySide6-enabled check.

## v0.6.0-dev5 — toolbar layout refinement

- Split the crowded main toolbar into two rows so action labels, icons, recent files, and language controls have dedicated space.
- Reduced toolbar icon dimensions slightly while retaining readable labels and the existing dark/cyan styling.
- Added a GUI smoke test for the two-row toolbar layout at the minimum supported window width.

## v0.6.0-dev4-hotfix1

Fixed the missing QFIL icon method in the GUI and corrected the project-root import path in the directly executable GUI smoke test.

# Changelog

The maintained change history is available in both languages:

- [English changelog](docs/en/changelog.md)
- [История изменений на русском](docs/ru/changelog.md)

## v0.6.0-dev3

Added a dedicated QFIL XML GUI workflow accessible from the main toolbar and Batch Queue window. QFIL processing remains separate from the Sparse conversion queue.


## v0.6.0-dev7

- Added streaming RAW → Android Sparse v1.0 encoding in the standard-library CLI.
- Added configurable block size, `RAW`/`FILL`/`DONT_CARE` chunk selection, CRC32, optional SHA-256, atomic output and JSON summary.
- Added RAW → Sparse round-trip and validation tests.
