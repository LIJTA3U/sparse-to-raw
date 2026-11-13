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
