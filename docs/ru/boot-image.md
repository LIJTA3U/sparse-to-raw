# Android Boot Image Inspector

В `sparse-to-raw` добавлен просмотрщик заголовков Android boot- и vendor boot-образов, работающий только на чтение. Команда CLI — `boot-info`; в GUI диалог находится в меню **«Инструменты» → Boot Image Inspector**.

## Поддерживаемые форматы

- Legacy Android boot image header v0, v1 и v2 (`ANDROID!`).
- Generic boot image header v3 и v4 (`ANDROID!`).
- `vendor_boot` header v3 и v4 (`VNDRBOOT`).

Версия заголовка определяет структуру разбираемых полей. Согласно документации AOSP, v0 применяется для Android 8 и старше, v1 — Android 9, v2 — Android 10, v3 — Android 11, а v3/v4 встречаются на устройствах Android 12 и новее в зависимости от поколения устройства и конфигурации GKI. `vendor_boot` появился вместе с разделением GKI; в v4 добавлена таблица описания нескольких фрагментов vendor ramdisk. См. официальную документацию [boot image header](https://source.android.com/docs/core/architecture/bootloader/boot-image-header), [vendor boot partitions](https://source.android.com/docs/core/architecture/partitions/vendor-boot-partitions), [generic boot partition](https://source.android.com/docs/core/architecture/partitions/generic-boot) и исходный заголовок AOSP [`bootimg.h`](https://android.googlesource.com/platform/system/tools/mkbootimg/+/refs/heads/android17-release/include/bootimg/bootimg.h).

## CLI

Просмотреть структуру образа:

```powershell
py sparse_to_raw.py boot-info boot.img
py sparse_to_raw.py boot-info vendor_boot.img
py sparse_to_raw.py boot-info init_boot.img --json-report init-boot-report.json
py sparse_to_raw.py --lang ru boot-info recovery.img
```

Существующий JSON-отчёт защищён от перезаписи. Используйте `--force`, только если действительно нужно заменить файл:

```powershell
py sparse_to_raw.py boot-info boot.img --json-report boot-report.json --force
```

JSON-отчёт содержит обнаруженный тип образа, версию и размер заголовка, размер страницы, длину файла, разобранные поля заголовка, смещения и размеры компонентов, предварительные подсказки о формате Kernel/Ramdisk, размер завершающих данных, сведения об AVB footer и предупреждения. Если в конце файла найден 64-байтовый AVB footer, инспектор показывает его версию, исходный размер образа, смещение и размер VBMeta-блока, наличие сигнатуры `AVB0`, состояние зарезервированных байтов и результат структурной проверки диапазонов. Область после последнего компонента дополнительно разбивается на неинтерпретированные данные перед VBMeta, сам VBMeta-блок и неинтерпретированные данные после VBMeta до footer, когда эти диапазоны согласованы. Структура 64-байтового footer соответствует определению AOSP [`AvbFooter`](https://android.googlesource.com/platform/external/avb/+/refs/heads/main/libavb/avb_footer.h); расположение footer и VBMeta также описано в [AOSP avbtool](https://android.googlesource.com/platform/external/avb/+/refs/heads/main/avbtool). Для `vendor_boot` v4 дополнительно выводятся записи таблицы vendor ramdisk: имена и типы фрагментов, диапазоны байтов и board ID.

## Какие сведения показывает инспектор

Для legacy boot v0–v2 отображаются размер страницы, адреса загрузки, имя платы, командная строка ядра, версия ОС и месяц security patch, закодированные в заголовке, legacy image ID, а также положения kernel, ramdisk, second-stage, recovery DTBO и DTB, если соответствующие компоненты присутствуют.

Для generic boot v3–v4 отображаются размеры и смещения kernel и ramdisk, поля версии ОС, командная строка и размер boot signature для v4. Содержимое boot signature криптографически не проверяется.

Для `vendor_boot` v3–v4 показываются vendor ramdisk, DTB, имя платы, адреса загрузки, vendor command line, а для v4 — таблица фрагментов vendor ramdisk и секция bootconfig. Определение формата по первым байтам компонента является только подсказкой.

Распознавание Kernel и Ramdisk эвристическое. Для Kernel проверяются сигнатуры ARM64 Image, ARM32 zImage, x86 bzImage и распространённых сжатых payload: gzip, bzip2, XZ, Zstandard, LZ4 frame/legacy, LZO/lzop и LZMA. Для Ramdisk дополнительно распознаются CPIO newc/crc. Сигнатура должна находиться в начале соответствующего компонента.

## GUI

Откройте **«Инструменты» → Boot Image Inspector**, выберите `boot.img`, `init_boot.img`, `recovery.img` или `vendor_boot.img` и нажмите **«Прочитать структуру»**. Таблица показывает абсолютное смещение каждого компонента в файле, его размер и распознанный формат. Выберите строку, чтобы посмотреть разобранные сведения. Кнопка **«Экспорт JSON»** сохраняет полный отчёт.

Диалог не изменяет выбранный образ. Файл открывается для чтения; отдельные файлы извлечённых компонентов не создаются.

## Интерпретация и ограничения

- Имя раздела не записывается в Android boot header. `boot.img` и `recovery.img` могут использовать одинаковый формат заголовка, поэтому инспектор не пытается определить одно из этих имён только по заголовку.
- `init_boot` указывается только как вероятная роль, если generic boot v3/v4 содержит пустой kernel и непустой ramdisk. Это вывод по структуре образа, а не достоверное имя раздела из заголовка. На устройствах, выпускаемых с Android 13 и использующих GKI, generic ramdisk размещается в `init_boot`; обновлённые с более ранних версий устройства могут сохранять другую схему. См. документацию AOSP [generic boot partition](https://source.android.com/docs/core/architecture/partitions/generic-boot).
- Статус `valid` означает только согласованную структуру footer/VBMeta: допустимые границы, заголовок `AVB0`, нулевые reserved bytes и поддерживаемую major-версию footer. `warning` сообщает о замечаниях (например, неизвестной major-версии или несоответствии magic), `invalid` — о некорректных диапазонах или нулевом размере VBMeta. AVB footer проверяется только структурно: это не проверка целостности содержимого VBMeta, не проверка встроенного хеша или криптографической подписи и не подтверждение доверия к ключу. Для полной AVB-проверки используйте AVB / VBMeta Inspector или `avbtool`.
- Инспектор не распаковывает и не извлекает Kernel/Ramdisk, не разбирает архивы CPIO, не интерпретирует содержимое DTB/FDT, не пересобирает образы и не прошивает устройства.
- Перед чтением небольших фрагментов проверяются границы заголовка и компонентов. Формат определяется по сигнатурам; это не доказывает целостность или загрузоспособность всего компонента.
- Вендорские и перепакованные форматы, не использующие поддерживаемые AOSP magic/header layouts, не распознаются.

Для распаковки ramdisk, анализа device tree или проверки подлинности используйте отдельные специализированные инструменты и независимую процедуру проверки.
