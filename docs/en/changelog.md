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

- Centralized the application version used by CLI and GUI to prevent version drift.
- Updated the Windows release workflow to run the full unit suite and Python compilation before packaging.
- Added smoke checks for the packaged CLI version/help output; retained self-tests for both GUI package formats.
- Expanded the Python CI matrix to 3.14 and added ignore rules for Sparse and split firmware image files.
- Refreshed installation, task-queue, and release-history documentation.

## v0.6.0-dev11-hotfix2 — Windows batch-profile path handling

- Canonicalize restored task paths so Windows 8.3 short names expand to their long spelling, while selected symlink aliases preserve their spelling.
- Keep queue-level option paths lexical and preserve profile-relative path support.
- Add regression tests for Windows path round-tripping.

## v0.6.0-dev11 — batch profiles

- Added JSON Batch Queue profiles for task order, Sparse → RAW / RAW → Sparse / QFIL task definitions, output folder, overwrite, and verification settings.
- Paths are stored relative to the profile when possible; the loader validates the format, version, task types, and options before replacing the active queue.
- Loading requires confirmation; restored tasks start in the waiting state, and missing input files are reported.
- Added atomic profile writes, overwrite protection, file/task limits, and round-trip/malformed-profile tests.

## v0.6.0-dev10 — Sparse Validator

- Add a dedicated streaming Sparse Validator to the CLI and GUI.
- Validate headers, chunk structure and payload lengths, block accounting, trailing data, CRC32 checkpoints, and the optional image checksum without creating a RAW file.
- Provide structured results, integrity assessment, chunk counts, warnings, optional logical SHA-256, and JSON reports.
- Add GUI progress, cancellation, and a standalone validation dialog.

## v0.6.0-dev9 — logical RAW/Sparse comparison

- Added streaming logical comparison for RAW ↔ RAW, RAW ↔ Sparse, and Sparse ↔ Sparse inputs.
- Sparse streams are structurally validated, including chunk CRC32 checkpoints and the optional image checksum; no expanded intermediate RAW file is created.
- Reports include both logical SHA-256 hashes, logical sizes, formats, and the first differing byte offset.
- Added the `compare` CLI subcommand and a background GUI comparison dialog with progress, cancellation, and JSON export.
- Added regression tests for matching images, differences, length mismatch, malformed checksums, cancellation, and CLI exit codes.

## v0.6.0-dev8

- Added a dedicated streaming RAW → Android Sparse GUI dialog with file selection, block-size configuration, progress, cancellation, CRC32, and SHA-256.
- RAW → Sparse jobs are now supported in Batch Queue and can share a sequential queue with Sparse → RAW and QFIL tasks.
- Updated GUI guides and synchronized CLI/GUI version strings.

## v0.6.0-dev6 — regression stabilization

### Fixed
- Synchronized the CLI `--version` output with the GUI/application version. The CLI previously reported an older development build even when the GUI showed a newer one.

### Tests
- Added a regression test that checks the CLI version string.
- Re-ran the full dependency-free unit test suite; GUI smoke tests remain a separate PySide6-enabled check.

## v0.6.0-dev5 — toolbar layout refinement

### Changed
- Split the main toolbar into two rows to prevent action labels and icons from colliding with recent-file and language controls.
- Slightly reduced toolbar icon size and tightened button padding while preserving readable text.

### Tests
- Added a GUI smoke test that checks the two-row layout at the minimum supported window width.

## v0.6.0-dev4-hotfix1

### Fixed
- Added the missing `MainWindow.qfil_icon()` implementation used by the main toolbar and Batch Queue actions.
- Made `tests/gui_smoke_tests.py` add the repository root to `sys.path`, so it can be launched directly from the project root on Windows.
- Extended the GUI smoke test to verify that the QFIL icon is created and assigned to the main toolbar button.

## v0.6.0-dev4

- Added mixed sequential Sparse and QFIL jobs to Batch Queue.
- Added a dedicated QFIL XML document icon to the main toolbar and queue actions.
- QFIL queue items retain rawprogram/patch manifest paths, search folder, output folder, and overlap policy in their item metadata.
- Extended batch JSON reports with QFIL task metadata. QFIL patch commands remain analysis-only.


## v0.6.0-dev3 — QFIL GUI integration

- Added a dedicated QFIL XML dialog to the main toolbar and Batch Queue window.
- Added GUI workflows for selecting rawprogram/patch manifests, choosing a firmware search folder, analyzing partitions and warnings, and assembling RAW images per LUN.
- Kept patch operations inspection-only; the application does not execute patch instructions or flash devices.
- QFIL processing is currently a separate workflow and is not yet a task type in the Sparse conversion queue.
# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — v0.6.0 development

### Changed
- Bumped the development build to `v0.6.0-dev2` after adding bilingual CLI localization.


### Added
- CLI localization: English by default, `--lang en|ru` per command, and `SPARSE_TO_RAW_LANG` shell default; Sparse and QFIL help, summaries, and common validation errors follow the selected language.
- Qualcomm QFIL `rawprogram*.xml` / `patch*.xml` analysis, partition/LUN summaries, referenced-file discovery, and JSON reporting.
- Streaming RAW assembly per physical partition, including `program`/`erase`, `file_sector_offset`, `SECTOR_SIZE_IN_BYTES`, Sparse sources, and `NUM_DISK_SECTORS-N` expressions.
- Guards for ambiguous sources, overlapping ranges, XML DTD/entities, low disk space, and accidental overwrite. Patch XML is inspected but not applied.
- Larger vector drag-and-drop icon and a clearer CLI summary/help layout.
- Dedicated QFIL tests for XML parsing, file resolution, RAW assembly, failure cases, and CLI commands.


## [0.5.0] — 2026-11-02

### Added
- CLI localization: English by default, `--lang en|ru` per command, and `SPARSE_TO_RAW_LANG` shell default; Sparse and QFIL help, summaries, and common validation errors follow the selected language.
- Paged Sparse Structure Viewer with full validation before browsing, chunk offsets/sizes/checksums, type filters, search, and streaming CSV/JSON export.
- Background cancellable structure export with atomic publication and source-file change detection.
- Windows taskbar identity and application icon initialization for the running GUI.
- Localized operation-log messages and diagnostic categories for Russian/English UI modes.
- Antialiased angular window frame with smoother left-side transitions while retaining the existing dark/cyan/yellow design.
- Interactive batch queue controls: drag reordering, task-level cancel/skip, pause/resume between files, retry selected failures, and status filters.
- Queue progress and JSON summaries include waiting/running/success/failed/cancelled/skipped task states.
- Local rotating JSONL diagnostic history with severity/operation/date filters and text search.
- Diagnostic Center ZIP export with runtime-version information and redaction of user-profile paths and credential-shaped values.
- Operation metrics for completed conversion, inspection, merge, and batch tasks: duration, processed/output bytes, chunk count, and average throughput where available.
- GUI discovery of independent Sparse part groups with numeric ordering and validation of gaps, duplicate indices, headers, and block sizes.
- Shared preflight checks for output paths, write access, free disk space, merge staging needs, and batch output collisions.
- Optional RAW read-back verification: verify staged output size and SHA-256 against expected logical contents before atomic commit.
- `--verify-output` for CLI conversion and `--merge-parts`; verification details are included in JSON reports.
- Saved GUI verification preference for single conversion, batch conversion, and Sparse merging.

### Changed
- The existing UI layout and color palette remain intact; the frameless shell uses smooth painter paths rather than a pixelated region mask.
- Verification progress is reported as a separate read-back phase; failed or cancelled verification preserves an existing destination.

## [0.4.0] — released

### Added
- CLI localization: English by default, `--lang en|ru` per command, and `SPARSE_TO_RAW_LANG` shell default; Sparse and QFIL help, summaries, and common validation errors follow the selected language.
- Russian/English GUI language switching with saved preference.
- Decimal MB/s, binary MiB/s, and Mbit/s speed display options.
- Application icon and larger action icons.
- Persistent window geometry, paths, settings, and recent-file history.
- Sparse image analysis with JSON export and no RAW output.
- Sequential batch conversion queue with cancellation and a JSON summary.
- Visual merging of independent Sparse parts with manual ordering.
- Detailed conversion and merge reports.
- Progress, event, and cancellation callbacks for Sparse merging.
- Tests for monotonic merge progress and safe merge cancellation.

### Changed
- Expanded the GUI while retaining the existing CLI interface and core conversion implementation.
- Windows packages include the application icon and the GUI resource.

## [0.3.0] — released

### Added
- CLI localization: English by default, `--lang en|ru` per command, and `SPARSE_TO_RAW_LANG` shell default; Sparse and QFIL help, summaries, and common validation errors follow the selected language.
- Experimental PySide6 desktop GUI with a frameless geometric window.
- Progress based on processed bytes and completed chunks, operation log, and SHA-256.
- Background worker thread and safe cancellation through staging-file removal.
- Windows folder ZIP package and standalone GUI executable.
- GUI smoke tests on Windows and Linux.

### Changed
- The converter exposes optional progress, event, and cancellation callbacks; the CLI keeps its previous default behavior.

## [0.2.0] — released

### Added
- CLI localization: English by default, `--lang en|ru` per command, and `SPARSE_TO_RAW_LANG` shell default; Sparse and QFIL help, summaries, and common validation errors follow the selected language.
- `--info` mode for metadata and verification without creating RAW output.
- `--verify-only` mode for separate structure/checksum validation.
- Protection against accidental overwrite; `--force` enables explicit replacement.
- Progress indicator, processing speed, and processed byte count.
- Logical RAW SHA-256 with `--sha256`.
- JSON reports with `--json-report`.
- Explicitly ordered merging of independent Sparse files with `--merge-parts`.
- GitHub Actions core tests on Windows and Linux.
- README localization, badges, contributing guidance, and issue templates.
