# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased] — v0.5.0 development

### Added
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
- Experimental PySide6 desktop GUI with a frameless geometric window.
- Progress based on processed bytes and completed chunks, operation log, and SHA-256.
- Background worker thread and safe cancellation through staging-file removal.
- Windows folder ZIP package and standalone GUI executable.
- GUI smoke tests on Windows and Linux.

### Changed
- The converter exposes optional progress, event, and cancellation callbacks; the CLI keeps its previous default behavior.

## [0.2.0] — released

### Added
- `--info` mode for metadata and verification without creating RAW output.
- `--verify-only` mode for separate structure/checksum validation.
- Protection against accidental overwrite; `--force` enables explicit replacement.
- Progress indicator, processing speed, and processed byte count.
- Logical RAW SHA-256 with `--sha256`.
- JSON reports with `--json-report`.
- Explicitly ordered merging of independent Sparse files with `--merge-parts`.
- GitHub Actions core tests on Windows and Linux.
- README localization, badges, contributing guidance, and issue templates.
