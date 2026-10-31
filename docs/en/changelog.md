# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
