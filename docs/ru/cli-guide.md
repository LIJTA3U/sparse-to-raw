# Руководство CLI

Консольная утилита находится в файле `sparse_to_raw.py`. Она поддерживает Android Sparse Image v1 и использует только стандартную библиотеку Python.

## Обычная конвертация

```bash
python sparse_to_raw.py input_sparse.img output_raw.img
```

Пример для Windows:

```bat
py sparse_to_raw.py super.img super_raw.img
```

Во время раскрытия логического RAW-содержимого программа проверяет структуру Sparse и соответствующие контрольные суммы. Существующий выходной файл по умолчанию не заменяется.

## Информация без создания RAW

```bash
python sparse_to_raw.py super.img --info
```

`--info` проверяет образ и выводит сведения о формате, размере блока, ожидаемом RAW-размере и количестве чанков, не создавая выходной файл.

## Проверка без создания RAW

```bash
python sparse_to_raw.py super.img --verify-only
```

`--verify-only` проверяет структуру и контрольные суммы без записи RAW. При ошибке проверки программа возвращает ненулевой код завершения.

## Явное разрешение перезаписи

```bash
python sparse_to_raw.py super.img super_raw.img --force
```

`--force` разрешает заменить существующий выходной файл. Без этого параметра существующий результат сохраняется.

## SHA-256 и JSON-отчёт

```bash
python sparse_to_raw.py super.img super_raw.img --sha256 --json-report report.json
```

SHA-256 вычисляется по логическому RAW-содержимому, включая нулевые области `DONT_CARE`; это не хеш исходного Sparse-файла. Существующий файл отчёта также защищён от перезаписи, если не указан `--force`.

## Объединение независимых Sparse-образов

```bat
py sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --sha256
```

Передавайте все части в нужном порядке. Каждый вход должен быть самостоятельным корректным Sparse-образом с собственным заголовком. Части проверяются; итоговый файл не публикуется, если хотя бы одна часть не прошла проверку. Это не средство объединения произвольных байтовых фрагментов одного файла.

В версии 0.4.0 файлы `super.img_sparsechunk.*` автоматически не обнаруживаются и не сортируются по номеру: порядок нужно указать самостоятельно.

## Отключение индикатора прогресса

```bash
python sparse_to_raw.py super.img super_raw.img --quiet
```

## Параметры

```text
usage: sparse_to_raw.py [-h] [--merge-parts SPARSE_FILE [SPARSE_FILE ...]]
                        [--output FILE] [--info | --verify-only] [--force]
                        [--sha256] [--json-report FILE] [--quiet]
                        [input_sparse] [output_raw]
```

| Параметр | Описание |
|---|---|
| `input_sparse` | Входной Android Sparse Image |
| `output_raw` | Путь выходного RAW при обычной конвертации |
| `--merge-parts FILE...` | Объединить два или более независимых Sparse-файла в указанном порядке |
| `--output FILE` | Путь RAW для режима `--merge-parts` |
| `--info` | Проверить и вывести метаданные без конвертации |
| `--verify-only` | Проверить структуру и контрольные суммы без RAW |
| `--force` | Разрешить замену существующего выходного файла или отчёта |
| `--sha256` | Вычислить SHA-256 логического RAW-содержимого |
| `--json-report FILE` | Сохранить JSON-отчёт |
| `--quiet` | Скрыть индикатор прогресса |

Полный текст справки доступен через `python sparse_to_raw.py --help`.
