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
