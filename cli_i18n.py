"""Small standard-library-only localization layer for the command-line interface."""
from __future__ import annotations

import os

LANG = "en"

TEXT = {
    "en": {
        "description": "Convert, validate and inspect Android Sparse images. The CLI uses only the Python standard library.",
        "epilog": "Validate an Android Sparse image:\n  python sparse_to_raw.py validate image.sparse --json-report validation.json\n\nCompare logical images:\n  python sparse_to_raw.py compare image.raw image.sparse\n\nQFIL XML examples:\n  python sparse_to_raw.py qfil-analyze rawprogram0.xml --patch-xml patch0.xml\n  python sparse_to_raw.py qfil-build rawprogram0.xml --output-dir raw\n\nExisting files are protected from overwrite by default; use --force to replace them.",
        "input": "input Android Sparse image", "output_pos": "destination RAW image",
        "merge": "merge 2+ independent Sparse files in the supplied order (requires --output)",
        "output": "destination RAW file for --merge-parts", "info": "validate the image and display detailed information without conversion",
        "verify": "validate structure and checksums without creating a RAW file", "force": "allow overwriting an existing output file or report",
        "sha": "calculate SHA-256 of the logical RAW contents", "verifyout": "re-read the completed RAW and verify its size and SHA-256 before commit",
        "json": "save results to a JSON file", "quiet": "hide the progress indicator", "lang": "CLI language",
        "merge_pos": "In --merge-parts mode, use --output only; do not supply positional arguments",
        "merge_need": "--merge-parts requires --output FILE", "merge_mode": "--merge-parts cannot be combined with --info or --verify-only",
        "need_input": "provide input_sparse or use --merge-parts", "output_only_merge": "--output can only be used with --merge-parts",
        "need_output": "provide output_raw for conversion; use --info or --verify-only to inspect without conversion",
        "no_output": "do not provide output_raw with --info or --verify-only", "verify_mode": "--verify-output is only available for conversion or --merge-parts",
        "json_collision": "the JSON report path must not match the input or output image path",
        "json_dir": "JSON report directory not found", "json_is_dir": "JSON report path points to a directory",
        "json_exists": "JSON report already exists (use --force to overwrite)",
        "summary_title": "sparse-to-raw | Android Sparse Image", "block_size": "Block size", "total_blocks": "Total blocks",
        "total_chunks": "Total chunks", "raw_size": "RAW size", "breakdown": "Chunk breakdown", "header_crc": "Header checksum",
        "chunks_checked": "Chunks checked", "computed_crc": "Computed CRC32", "verification": "RAW verification", "verified_sha": "Verified SHA-256",
        "disk_space": "Disk space", "success": "Validation successful.", "error": "ERROR", "json_saved": "JSON report saved",
        "compare_desc": "Compare logical contents of two RAW and/or Android Sparse images",
        "compare_left": "first RAW or Android Sparse image", "compare_right": "second RAW or Android Sparse image",
        "compare_json": "write a JSON comparison report", "compare_quiet": "hide comparison progress",
        "compare_progress": "Comparing logical contents",
        "validate_desc": "Validate Android Sparse structure and integrity without creating a RAW file",
        "validate_input": "Android Sparse image to validate",
        "validate_json": "write the validation report to JSON",
        "validate_no_sha": "skip logical-content SHA-256 calculation",
        "validate_progress": "Validating Sparse image",
        "validate_quiet": "hide validation progress",
        "qfil_analysis": "QFIL MANIFEST ANALYSIS", "rawprograms": "rawprogram XML files", "patches": "patch XML files",
        "program_ops": "program operations", "erase_ops": "erase operations", "patch_ops": "patch operations",
        "located": "located image files", "missing": "missing files", "partitions": "partitions", "partition_map": "PARTITION MAP",
        "file_resolution": "FILE RESOLUTION", "erase_zero": "ERASE (zero-filled)", "found": "FOUND", "found_search": "FOUND BY SEARCH",
        "no_name": "NO SOURCE NAME", "patch_not_applied": "PATCH OPERATIONS (NOT APPLIED)", "warnings": "WARNINGS",
        "patch_note": "Patch XML is shown for review; patch values were not written to the RAW data.",
        "unresolved": "Analysis completed with unresolved source files.", "analysis_done": "Analysis completed.",
        "qfil_assembly": "QFIL RAW ASSEMBLY", "programs": "programs", "erases": "erases", "total_output": "Total output",
        "assembly_done": "Assembly completed. Patch XML was not applied.", "output": "Output", "size": "size", "sha256": "SHA-256",
    },
    "ru": {
        "description": "Конвертация, проверка и анализ Android Sparse. CLI использует только стандартную библиотеку Python.",
        "epilog": "Проверка Android Sparse:\n  python sparse_to_raw.py validate image.sparse --json-report validation.json\n\nЛогическое сравнение образов:\n  python sparse_to_raw.py compare image.raw image.sparse\n\nПримеры QFIL XML:\n  python sparse_to_raw.py qfil-analyze rawprogram0.xml --patch-xml patch0.xml\n  python sparse_to_raw.py qfil-build rawprogram0.xml --output-dir raw\n\nСуществующие файлы защищены от перезаписи; для замены используйте --force.",
        "input": "исходный Android Sparse Image", "output_pos": "путь к выходному RAW-образу",
        "merge": "объединить 2+ самостоятельных Sparse-файла в указанном порядке (нужен --output)",
        "output": "выходной RAW-файл для --merge-parts", "info": "проверить образ и вывести подробную информацию без конвертации",
        "verify": "проверить структуру и контрольные суммы без создания RAW-файла", "force": "разрешить перезапись существующего выходного файла или отчёта",
        "sha": "вычислить SHA-256 логического RAW-содержимого", "verifyout": "повторно прочитать готовый RAW и сверить размер и SHA-256 перед сохранением",
        "json": "сохранить результаты в JSON-файл", "quiet": "не показывать индикатор прогресса", "lang": "язык CLI",
        "merge_pos": "В режиме --merge-parts используйте только --output, без позиционных аргументов",
        "merge_need": "для --merge-parts обязательно укажите --output FILE", "merge_mode": "--merge-parts нельзя совмещать с --info или --verify-only",
        "need_input": "укажите input_sparse либо используйте --merge-parts", "output_only_merge": "--output используется только вместе с --merge-parts",
        "need_output": "для конвертации укажите output_raw; для проверки используйте --info или --verify-only",
        "no_output": "не указывайте output_raw вместе с --info или --verify-only", "verify_mode": "--verify-output можно использовать только при конвертации или --merge-parts",
        "json_collision": "путь JSON-отчёта не должен совпадать с путём входного или выходного образа",
        "json_dir": "каталог для JSON-отчёта не найден", "json_is_dir": "путь JSON-отчёта указывает на каталог",
        "json_exists": "файл JSON-отчёта уже существует (используйте --force)",
        "summary_title": "sparse-to-raw | Android Sparse Image", "block_size": "Размер блока", "total_blocks": "Всего блоков",
        "total_chunks": "Всего чанков", "raw_size": "Размер RAW", "breakdown": "Состав чанков", "header_crc": "Контрольная сумма заголовка",
        "chunks_checked": "Проверено чанков", "computed_crc": "Вычисленный CRC32", "verification": "Проверка RAW", "verified_sha": "Проверенный SHA-256",
        "disk_space": "Место на диске", "success": "Проверка успешно завершена.", "error": "ОШИБКА", "json_saved": "JSON-отчёт сохранён",
        "compare_desc": "Сравнить логическое содержимое двух RAW- и/или Android Sparse-образов",
        "compare_left": "первый RAW- или Android Sparse-образ", "compare_right": "второй RAW- или Android Sparse-образ",
        "compare_json": "сохранить отчёт сравнения в JSON", "compare_quiet": "скрыть прогресс сравнения",
        "compare_progress": "Сравнение логического содержимого",
        "validate_desc": "Проверить структуру и целостность Android Sparse без создания RAW-файла",
        "validate_input": "Android Sparse-образ для проверки",
        "validate_json": "сохранить отчёт проверки в JSON",
        "validate_no_sha": "не вычислять SHA-256 логического содержимого",
        "validate_progress": "Проверка Sparse-образа",
        "validate_quiet": "скрыть прогресс проверки",
        "qfil_analysis": "АНАЛИЗ QFIL-МАНИФЕСТОВ", "rawprograms": "Файлов rawprogram XML", "patches": "Файлов patch XML",
        "program_ops": "Операций program", "erase_ops": "Операций erase", "patch_ops": "Операций patch",
        "located": "Найдено файлов образов", "missing": "Отсутствует файлов", "partitions": "Разделов", "partition_map": "КАРТА РАЗДЕЛОВ",
        "file_resolution": "ПОИСК ФАЙЛОВ", "erase_zero": "ERASE (заполнение нулями)", "found": "НАЙДЕН", "found_search": "НАЙДЕН ПОИСКОМ",
        "no_name": "ИМЯ ИСТОЧНИКА НЕ УКАЗАНО", "patch_not_applied": "ОПЕРАЦИИ PATCH (НЕ ПРИМЕНЯЮТСЯ)", "warnings": "ПРЕДУПРЕЖДЕНИЯ",
        "patch_note": "Patch XML показан для проверки; значения patch не записывались в RAW.",
        "unresolved": "Анализ завершён: остались неразрешённые исходные файлы.", "analysis_done": "Анализ завершён.",
        "qfil_assembly": "СБОРКА QFIL RAW", "programs": "операций program", "erases": "erase", "total_output": "Всего создано",
        "assembly_done": "Сборка завершена. Patch XML не применялся.", "output": "Результат", "size": "размер", "sha256": "SHA-256",
    },
}


def set_language(language: str | None = None) -> str:
    global LANG
    candidate = (language or os.environ.get("SPARSE_TO_RAW_LANG") or "en").lower()
    LANG = candidate if candidate in TEXT else "en"
    return LANG


def tr(key: str) -> str:
    return TEXT[LANG].get(key, TEXT["en"].get(key, key))


def localize_error(message: str) -> str:
    """Translate common CLI validation errors while preserving technical details."""
    if LANG == "en":
        return message
    replacements = {
        "File already exists:": "Файл уже существует:",
        "use --force to overwrite": "используйте --force для перезаписи",
        "Output directory not found:": "Каталог вывода не найден:",
        "Unexpected end of file while reading": "Неожиданный конец файла при чтении",
        "Invalid --disk-sectors value": "Недопустимое значение --disk-sectors",
        "expected LUN=COUNT": "ожидается LUN=COUNT",
        "JSON report already exists:": "JSON-отчёт уже существует:",
        "JSON report directory not found:": "Каталог JSON-отчёта не найден:",
        "QFIL XML file not found:": "Файл QFIL XML не найден:",
        "Invalid XML in": "Некорректный XML в",
        "No <program> or <erase> operations found in": "Не найдены операции <program> или <erase> в",
        "No <patch> operations found in": "Не найдены операции <patch> в",
        "Output file already exists:": "Выходной файл уже существует:",
        "Output path is not a directory:": "Путь вывода не является каталогом:",
        "Input file not found:": "Входной файл не найден:",
        "Invalid sparse magic:": "Неверная сигнатура Sparse:",
        "Invalid sparse magic in": "Неверная сигнатура Sparse в",
        "Unsupported sparse major version:": "Неподдерживаемая основная версия Sparse:",
        "Unsupported sparse major version in": "Неподдерживаемая основная версия Sparse в",
        "Invalid file header size:": "Неверный размер заголовка файла:",
        "Invalid file header size in": "Неверный размер заголовка файла в",
        "Invalid chunk header size:": "Неверный размер заголовка чанка:",
        "Invalid chunk header size in": "Неверный размер заголовка чанка в",
        "Invalid block size": "Неверный размер блока",
        "Unexpected trailing bytes after the final chunk": "После последнего чанка обнаружены лишние байты",
        "Input and output paths must be different": "Пути входного и выходного файлов должны различаться",
        "Input and output refer to the same file": "Входной и выходной пути указывают на один файл",
        "Output path points to a directory:": "Выходной путь указывает на каталог:",
        "RAW output verification requires an output path": "Для проверки RAW требуется путь выходного файла",
        "Chunk ": "Чанк ",
        "reserved field is not zero": "резервное поле не равно нулю",
        "output size is not a multiple of 4": "размер выходных данных не кратен 4",
        "must have zero blocks": "должен содержать ноль блоков",
        "output exceeds declared total blocks": "размер выходных данных превышает заявленное число блоков",
        "stored-size accounting mismatch": "несоответствие учёта сохранённого размера",
        "File already exists:": "Файл уже существует:",
    }
    for source, target in replacements.items():
        message = message.replace(source, target)
    return message
