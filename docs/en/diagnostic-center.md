# Diagnostic Center

The Diagnostic Center keeps a local, searchable history of application events and can export a privacy-conscious ZIP bundle for troubleshooting.

## Open the Diagnostic Center

Select **Diagnostics** in the main toolbar. The window displays the most recent events first. Each event has a timestamp, severity, operation category, message, and optional structured details.

## Filters and search

Use the filters to narrow the event list by:

- **Level:** Debug, Info, Success, Warning, or Error.
- **Operation:** Application, Conversion, Analysis, Queue, Merge, Preflight, RAW verification, or Diagnostics.
- **Period:** All history, Today, or the Last 7 days.
- **Search:** Match text in the event message and structured details.

The local history is stored under the application's Qt AppLocalDataLocation in `diagnostics/`. The JSON Lines log is rotated at approximately 1 MiB per file, with two backup files, and the viewer is bounded to the most recent 5,000 events.

## Operation statistics

Completed conversion, analysis, merge, and batch tasks record available metrics such as duration, logical bytes processed, output bytes, chunk count, and average throughput. Some failed or cancelled operations may not have complete metrics because processing stopped before a result was available.

## Export a diagnostic ZIP

Select **Export ZIP** and choose a destination. The bundle contains:

- `diagnostics.jsonl` — sanitized event history.
- `system-info.json` — application, Python, PySide6, Qt, operating-system family/release, and architecture versions.
- `README.txt` — a summary of the bundle contents and privacy behavior.

The export does **not** include Sparse or RAW input/output files, conversion reports, recent-file lists, environment variables, account names, computer names, or a full system inventory. User profile roots and common credential-shaped values in log text are redacted. Review the ZIP before sharing it, because event messages can still contain useful filenames or other context that you may consider private.

## Clear local history

Select **Clear history** and confirm. This removes the current diagnostic log and its rotated backups. It does not delete conversion outputs, JSON reports, settings, or recent-file preferences.
