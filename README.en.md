# CLI UTF-8 and GitHub Actions Node.js 24 fix

This patch targets the current `main` branch after the Windows build-only workflow was added. It is a patch, not a full project archive.

## Changes

- Configure CLI `stdout` and `stderr` as UTF-8 before argument parsing, preventing localized `argparse` help from raising `UnicodeEncodeError` when Windows provides a legacy stream encoding such as `cp1252`.
- Add `tests/test_cli_console_encoding.py`, a regression test that simulates `cp1252` streams and verifies Russian QFIL help output.
- Upgrade `actions/checkout` to v7 and `actions/setup-python` to v7 in all three workflows.
- Upgrade the release-only steps in the Windows workflow to `actions/github-script@v8` and `softprops/action-gh-release@v3`.

## Apply

Extract the archive. From the repository root in PowerShell, run:

```powershell
git apply --check .\cli-utf8-and-node24.patch
if ($LASTEXITCODE -ne 0) { throw "Patch check failed" }
git apply .\cli-utf8-and-node24.patch
if ($LASTEXITCODE -ne 0) { throw "Patch apply failed" }
```

Then run the tests and `git diff --check` listed in `README.ru.md`, commit, and push.

After pushing, rerun **Build Windows applications** with build-only settings (`source_ref=main`, `upload_to_release=false`, empty `release_tag`). The workflow already tests `--lang ru qfil-validate --help`.

`actions/upload-artifact@v4` is intentionally unchanged. At the time this patch was prepared, no Node.js 24-native runtime release was available for that action, so a separate Node.js runtime warning may still appear when the artifact upload step is reached. It is independent of the CLI encoding failure and does not by itself fail the build.
