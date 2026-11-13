# v0.6.0 release checklist

This checklist separates source validation from Windows binary packaging and GitHub publication. Do not mark v0.6.0 stable until every required gate is complete.

## 1. Validate the release-candidate source

From the repository root on Windows:

```powershell
py -m compileall -q .
py -m unittest discover -s tests -v
py tests\gui_smoke_tests.py
py sparse_to_raw.py --version
py sparse_to_raw.py --help
```

Expected version: `sparse-to-raw v0.6.0-rc1`.

## 2. Push the candidate and inspect CI

Push the reviewed source to `main` and confirm these workflows succeed:

- `Tests`: Python 3.10–3.14 on Windows and Linux.
- `GUI smoke tests`: PySide6 GUI tests on Windows and Linux.

Resolve any failure before creating the candidate release.

## 3. Build Windows assets through GitHub Actions

Create a GitHub prerelease tagged `v0.6.0-rc1` from the tested commit. Publishing the prerelease triggers `.github/workflows/build-windows-release.yml`.

The workflow must produce and attach:

- `sparse-to-raw.exe` — standalone CLI.
- `sparse-to-raw-gui.exe` — standalone GUI.
- `sparse-to-raw-gui-windows.zip` — folder-based GUI package.

The workflow runs tests and Python compilation, smoke-tests the packaged CLI, and runs the GUI `--self-test` for both GUI packages with Python directories removed from `PATH`.

Download all three assets from the prerelease and test them on a clean Windows account or machine without Python installed. Keep the GUI folder ZIP extracted as a complete folder; do not move the executable away from its bundled libraries.

## 4. Promote to stable v0.6.0

After RC validation:

1. Change `APP_VERSION` in `sparse_to_raw.py` from `v0.6.0-rc1` to `v0.6.0`.
2. Add a final `v0.6.0` entry at the top of `CHANGELOG.md`, `docs/en/changelog.md`, and `docs/ru/changelog.md`.
3. Update README and installation links to the stable `v0.6.0` release.
4. Run the full test and GUI commands again, commit, and push.
5. Create and push the `v0.6.0` tag from that exact tested commit, then publish the GitHub Release. The Windows workflow builds and attaches the three assets automatically.
6. Download and smoke-test the published stable assets before announcing the release.

## 5. Release hygiene

- Verify the release ZIP contains source, documentation, assets, tests, and workflows, but no user firmware images, RAW dumps, Sparse images, Python caches, or local build output.
- Generate SHA-256 checksums for all published assets and include them in the release notes.
- Keep the safety note: the tool processes files only and does not flash devices; QFIL patch commands are reported, not executed.
