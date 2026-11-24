# Boot Image Inspector GUI display fix

This is a focused source update for the v0.7.0 development branch.

## Apply

Extract this archive into the project root and allow the listed files to be replaced:

- `sparse_to_raw_gui.py`
- `tests/gui_smoke_tests.py`
- `CHANGELOG.md`
- `docs/ru/changelog.md`

The update does not replace the Git repository or any other project files.

## Changes

- Compressed kernel sections are labelled explicitly, e.g. `Kernel (GZIP)` / `Ядро (GZIP)`.
- The bytes between the last boot component and VBMeta are shown as `Unclassified data before VBMeta`.
- The bytes between VBMeta and the AVB footer are shown as `Unclassified data after VBMeta`.
- The two regions display their exact byte ranges and explanatory text; table cells also show detailed tooltips.
- A GUI regression test checks these rows in both Russian and English.

## Verification

Core/CLI tests and Python compilation pass in the build environment. GUI runtime tests require PySide6 and should be run on the target Windows system:

```powershell
py tests\gui_smoke_tests.py
```
