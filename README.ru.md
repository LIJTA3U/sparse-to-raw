# Исправление CLI UTF-8 и GitHub Actions Node.js 24

Этот пакет рассчитан на текущую ветку `main` после добавления build-only режима Windows-сборки.
Он содержит patch, а не полную копию проекта.

## Что исправлено

1. `sparse_to_raw.py`: до обработки аргументов CLI оба текстовых потока `stdout` и `stderr` переводятся на UTF-8 через `reconfigure()`. Это предотвращает `UnicodeEncodeError` при показе локализованной справки `argparse` в Windows-сборке, когда исходная кодировка потока — например, `cp1252`.
2. Добавлен `tests/test_cli_console_encoding.py`: регрессионный тест имитирует потоки `cp1252` и проверяет вывод русской QFIL-справки.
3. Во всех трёх workflow обновлены `actions/checkout` до v7 и `actions/setup-python` до v7.
4. В Windows release workflow отложенные шаги публикации обновлены: `actions/github-script` до v8 и `softprops/action-gh-release` до v3.

## Применение

Распакуйте этот архив в любую временную папку. Откройте PowerShell в корне клонированного репозитория и выполните команды, указав путь к patch-файлу, если он находится не в текущем каталоге:

```powershell
git apply --check .\cli-utf8-and-node24.patch
if ($LASTEXITCODE -ne 0) { throw "Patch check failed" }
git apply .\cli-utf8-and-node24.patch
if ($LASTEXITCODE -ne 0) { throw "Patch apply failed" }
```

Затем проверьте:

```powershell
py -m unittest discover -s tests -p "test_cli_console_encoding.py" -v
py -m unittest discover -s tests -p "test_cli_i18n.py" -v
py -m compileall -q .
git diff --check
```

Проверьте, что patch не создал конфликтов, затем сохраните изменения:

```powershell
git status --short
git add sparse_to_raw.py tests/test_cli_console_encoding.py .github/workflows/build-windows-release.yml .github/workflows/tests.yml .github/workflows/gui-tests.yml
git commit -m "Fix UTF-8 output in packaged CLI"
git push
```

После push повторно запустите **Build Windows applications** в режиме build-only (`source_ref=main`, `upload_to_release=false`, `release_tag` пустой). Smoke-test уже содержит проверку `--lang ru qfil-validate --help`.

## Примечание по Node.js warning

На дату подготовки пакет переводит `checkout`, `setup-python`, `github-script` и `action-gh-release` на версии с нативной поддержкой Node.js 24. `actions/upload-artifact@v4` оставлен без изменения: на момент подготовки у него нет опубликованной Node.js 24 runtime-версии, поэтому предупреждение для этого шага ещё может появиться, когда workflow дойдёт до загрузки Artifact. Оно не связано с ошибкой CLI и само по себе не означает провал сборки.
