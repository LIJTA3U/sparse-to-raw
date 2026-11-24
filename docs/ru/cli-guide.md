# Руководство CLI

Консольная утилита находится в файле `sparse_to_raw.py`. Она поддерживает Android Sparse Image v1 и использует только стандартную библиотеку Python.

## Язык CLI

По умолчанию CLI использует английский язык. Для отдельной команды укажите `--lang ru`; параметр `--lang en` явно включает английский. Переключатель работает с обычными командами Sparse и командами QFIL; в QFIL его можно поставить до или после подкоманды.

```powershell
py sparse_to_raw.py --help
py sparse_to_raw.py --lang ru --help
py sparse_to_raw.py qfil-analyze rawprogram0.xml --lang ru
```

Чтобы задать язык по умолчанию для текущего сеанса PowerShell, используйте `$env:SPARSE_TO_RAW_LANG = "ru"`. Явный параметр `--lang` имеет приоритет над переменной окружения. Поддерживаются значения `en` и `ru`.

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

## Логическое сравнение образов

Сравните два RAW- и/или Android Sparse-образа без создания промежуточного RAW-файла:

```powershell
py sparse_to_raw.py compare super_raw.img super.img --json-report comparison.json
```

Каждый Sparse-вход раскрывается потоково окнами до 1 МиБ; одновременно проверяются структура, CRC32 чанков и заданная в заголовке общая контрольная сумма. RAW-файлы читаются напрямую. Для обоих логических содержимых рассчитывается SHA-256. Отчёт содержит форматы входов, логические размеры и смещение первого отличающегося байта, если данные различаются. Сравнение не создаёт временный RAW-файл и не требует свободного места под его полную распаковку.

Коды завершения: `0` — логическое содержимое совпадает, `1` — образы различаются, `2` — ошибка входного файла или сравнения. `--quiet` скрывает прогресс. `--json-report FILE` сохраняет машиночитаемый отчёт и не перезаписывает существующий файл.

## Объединение независимых Sparse-образов

```bat
py sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --sha256
```

Передавайте все части в нужном порядке. Каждый вход должен быть самостоятельным корректным Sparse-образом с собственным заголовком. Части проверяются; итоговый файл не публикуется, если хотя бы одна часть не прошла проверку. Это не средство объединения произвольных байтовых фрагментов одного файла.

CLI принимает явно заданный список и не ищет части автоматически. GUI умеет находить группы `super.img_sparsechunk.*` и сортировать их по числовым индексам.

## Проверка записанного RAW (ветка разработки)

```bash
python sparse_to_raw.py super.img super_raw.img --verify-output
```

Для объединения:

```bash
python sparse_to_raw.py --merge-parts super.img_sparsechunk.0 super.img_sparsechunk.1 --output super_raw.img --verify-output
```

Параметр `--verify-output` доступен в текущей ветке разработки. После проверки Sparse-данных и контрольных сумм, а также закрытия временного RAW, программа повторно читает этот файл ограниченными блоками. Фактическое количество байтов и SHA-256 сравниваются с ожидаемым логическим RAW-содержимым, вычисленным во время раскрытия Sparse. Выходной файл публикуется только после успешной проверки. При несовпадении хеша, ошибке чтения или отмене временный файл удаляется, а существующий результат сохраняется.

Проверка добавляет полный проход чтения и увеличивает дисковую нагрузку и время операции. Она не заменяет проверку заголовков Sparse и контрольных сумм. При использовании `--json-report` объект `output_verification` содержит ожидаемый и фактический размеры и хеши, число проверенных байтов, длительность и результат. Параметр разрешён для обычной конвертации и `--merge-parts`, но не для `--info` или `--verify-only`. Параметр входит в опубликованную ветку релизов v0.5.0 и кандидат релиза v0.6.0 и релизную ветку.

## Манифесты Qualcomm QFIL

Анализ манифестов и поиск файлов прошивки:

```bat
py sparse_to_raw.py qfil-analyze rawprogram0.xml --patch-xml patch0.xml --search-dir . --json-report qfil-analysis.json
```

Полная предварительная проверка перед созданием выходных файлов:

```bat
py sparse_to_raw.py qfil-validate rawprogram0.xml rawprogram1.xml --patch-xml patch0.xml --search-dir . --output-dir raw-output
```

`qfil-validate` проверяет длины и смещения исходных файлов, полностью валидирует каждый Sparse-источник и его контрольные суммы без раскрытия в RAW, разрешает секторные диапазоны, обнаруживает пересечения, проверяет конфликты имён и оценивает свободное место. Команда не создаёт каталог результата или RAW-образы. Путь `--output-dir` нужен только для расчёта планируемых имён и проверки свободного места на целевом томе.

Сборка отдельного RAW-образа для каждой физической партиции/LUN:

```bat
py sparse_to_raw.py qfil-build rawprogram0.xml --patch-xml patch0.xml --search-dir . --output-dir raw-output --json-report qfil-build.json
```

Передавайте несколько rawprogram-манифестов позиционными аргументами; `--patch-xml` и `--search-dir` можно повторять. Сначала файлы ищутся относительно XML, затем папка манифеста и выбранные каталоги рекурсивно сканируются. При нескольких совпадениях сборка останавливается, не выбирая файл наугад.

Сборщик поддерживает операции `<program>` и `<erase>`, размер сектора, смещение файла в секторах, номер физической партиции, обычные RAW-файлы и источники с `sparse="true"`. Sparse-данные проверяются и раскрываются непосредственно во временный итоговый образ. Диапазоны `DONT_CARE` и erase заполняются нулями. Patch XML включается в отчёт, но не применяется.

Для координат вида `NUM_DISK_SECTORS-33` укажите размер накопителя в секторах для нужного LUN:

```bat
py sparse_to_raw.py qfil-build rawprogram0.xml --search-dir . --output-dir raw-output --disk-sectors 0=61071360
```

Пересекающиеся диапазоны по умолчанию запрещены; параметр `--allow-overlap` разрешает их только после проверки манифеста. Для замены существующих RAW-файлов или JSON-отчётов требуется `--force`. Подробное описание ограничений и мер безопасности находится в [руководстве QFIL XML](qfil-xml.md).

## Отключение индикатора прогресса

```bash
python sparse_to_raw.py super.img super_raw.img --quiet
```

## Параметры

```text
usage: sparse_to_raw.py [-h] [--lang {en,ru}] [--version] [--merge-parts SPARSE_FILE ...]
                        [--output FILE] [--info | --verify-only] [--force]
                        [--sha256] [--verify-output] [--json-report FILE] [--quiet]
                        [input_sparse] [output_raw]

Подкоманды: compare LEFT RIGHT | raw-to-sparse INPUT_RAW OUTPUT_SPARSE
Команды QFIL: qfil-analyze RAWPROGRAM.XML ... | qfil-validate RAWPROGRAM.XML ... --output-dir DIR | qfil-build RAWPROGRAM.XML ... --output-dir DIR
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
| `--verify-output` | Повторно прочитать временный RAW и проверить размер и SHA-256 перед сохранением (ветка разработки) |
| `--json-report FILE` | Сохранить JSON-отчёт |
| `--quiet` | Скрыть индикатор прогресса |
| `--version` | Показать версию CLI |
| `--lang {en,ru}` | Выбрать язык CLI; по умолчанию используется английский |

Полный текст справки доступен через `python sparse_to_raw.py --help`.

## Sparse Validator

Проверка Android Sparse без создания выходного RAW-файла:

```powershell
py sparse_to_raw.py validate input.sparse
py sparse_to_raw.py validate input.sparse --json-report validation.json
py sparse_to_raw.py validate input.sparse --no-sha256 --quiet
```

Коды завершения: `0` — образ корректен, `1` — проверка образа не пройдена, `2` — ошибка выполнения или файловой системы. Существующий JSON-отчёт не перезаписывается без `--force`. По умолчанию валидатор проверяет весь поток и вычисляет SHA-256 логического содержимого; `--no-sha256` отключает только вычисление SHA-256. Промежуточный RAW-файл не создаётся.

## Android Super Image: просмотр метаданных и извлечение

Просмотреть разделы, группы и extents без создания выходных файлов:

```powershell
py sparse_to_raw.py super-info super.img --slot 0 --json-report super-info.json
```

Извлечь все логические разделы в выбранную папку:

```powershell
py sparse_to_raw.py super-extract super.img --output-dir extracted
```

Извлечь только указанные разделы:

```powershell
py sparse_to_raw.py super-extract super.img --output-dir extracted --partition system --partition vendor
```

`--partition` можно повторять. По умолчанию извлекаются все разделы. `--slot` по умолчанию равен `0`. Для RAW и Android Sparse входов используется один интерфейс; Sparse временно раскрывается в RAW. `--force` разрешает замену выходных файлов и JSON-отчёта. Текущая реализация поддерживает LP metadata 10.0–10.2 и извлечение extents только с block device index 0.


## Анализ метаданных Android Verified Boot

Команда `vbmeta-info` анализирует самостоятельный `vbmeta.img` или образ раздела с AVB footer:

```powershell
py sparse_to_raw.py vbmeta-info vbmeta.img
py sparse_to_raw.py vbmeta-info system.img --json-report system-vbmeta.json
py sparse_to_raw.py --lang en vbmeta-info vbmeta.img
```

Отчёт содержит требуемую версию libavb, алгоритм, rollback index и его расположение, флаги заголовка, release string, размерность и отпечатки публичного ключа, а также поддерживаемые descriptors типов Property, Hash, Hashtree, Kernel Cmdline и Chain Partition. Для поддерживаемого алгоритма инспектор вычисляет встроенный хеш VBMeta по заголовку и auxiliary block и сравнивает его с сохранённым значением. Несовпадение отражается в отчёте и не трактуется как результат проверки подписи.

**Ограничение безопасности:** команда не проверяет RSA-подпись, не сравнивает публичный ключ с доверенным ключом или хранилищем устройства и не сопоставляет rollback index со значением, сохранённым на устройстве. Совпадение встроенного хеша само по себе не доказывает подлинность или доверие. Команда только читает входной файл и не изменяет его.

## Анализ Android Boot Image

Просмотр метаданных legacy `boot.img`, generic `boot.img` / `init_boot.img` или `vendor_boot.img`:

```powershell
py sparse_to_raw.py boot-info boot.img
py sparse_to_raw.py boot-info vendor_boot.img
py sparse_to_raw.py boot-info init_boot.img --json-report init-boot-report.json
py sparse_to_raw.py --lang ru boot-info recovery.img
```

Поддерживаются legacy boot header v0–v2, generic boot header v3–v4 и `vendor_boot` header v3–v4. Отчёт содержит версию заголовка, размеры страницы и заголовка, разобранные поля, смещения и размеры компонентов, подсказки о формате Kernel/Ramdisk, наличие AVB footer, а для `vendor_boot` v4 — таблицу фрагментов vendor ramdisk и bootconfig. `--force` разрешает заменить существующий JSON-отчёт. Подробности и ограничения интерпретации приведены в [руководстве Boot Image Inspector](boot-image.md).

## Анализ и извлечение Android Ramdisk

Просмотреть список CPIO-записей внутри boot-образа или отдельного архива:

```powershell
py sparse_to_raw.py ramdisk-info boot.img --json-report ramdisk-report.json
py sparse_to_raw.py ramdisk-info init_boot.img
py sparse_to_raw.py ramdisk-info vendor_boot.img --fragment-index 1
py sparse_to_raw.py ramdisk-info vendor-ramdisk.cpio.gz
```

Извлечь все обычные файлы/каталоги или выбрать отдельные пути повторяемым параметром `--include`:

```powershell
py sparse_to_raw.py ramdisk-extract boot.img --output-dir ramdisk-files
py sparse_to_raw.py ramdisk-extract boot.img --output-dir selected --include init --include etc
```

`ramdisk-extract` поддерживает legacy/generic boot-образы, `vendor_boot` v3/v4 и отдельные CPIO-архивы. Если в `vendor_boot` v4 несколько фрагментов ramdisk, требуется `--fragment-index`. Выбранный каталог включает вложенные записи. Лимит распакованных данных по умолчанию — 512 МиБ; он меняется параметром `--max-unpacked-mib`. Сборка без сторонних зависимостей распаковывает gzip, bzip2, XZ, LZMA-alone и LZ4 frame/legacy. Сигнатуры Zstandard и LZO/lzop распознаются, но эти форматы не распаковываются. Поддерживаются CPIO `newc` и `crc`; checksum формата `crc` проверяется.

Извлечение проверяет пути и не изменяет исходный образ. Существующие непустые каталоги защищены, если не указан `--force`. Символические ссылки перечисляются в `SYMLINKS.txt`, но не создаются как реальные ссылки; специальные узлы устройств/сокеты/FIFO записываются в `SPECIAL_FILES.txt`. Содержимое hardlink копируется в отдельные файлы; владелец, временные метки, права каталогов, SELinux labels и capabilities не восстанавливаются. Подробности приведены в [руководстве Ramdisk Inspector](ramdisk-inspector.md).
