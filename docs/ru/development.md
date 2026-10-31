# Разработка и сборка

## Архитектура

- `sparse_to_raw.py` содержит CLI, разбор Sparse, проверку, конвертацию, анализ, объединение, контрольные суммы, прогресс и отмену.
- `sparse_to_raw_gui.py` реализует интерфейс PySide6 и передаёт обработку формата основному модулю.
- Длительные операции GUI выполняются в рабочих потоках Qt. Не дублируйте разбор Sparse и вычисление контрольных сумм в GUI.
- `tests/test_sparse_to_raw.py` содержит основные тесты; `tests/gui_smoke_tests.py` — smoke-тесты GUI.

Старайтесь делать изменения локальными и сохранять существующие CLI-параметры, если отдельное изменение совместимости не согласовано.

## Подготовка среды разработки (Windows PowerShell)

```powershell
py --version
py -m pip install -r requirements-gui.txt
```

CLI не требует сторонних пакетов. PySide6 нужен для разработки GUI и запуска GUI-тестов.

## Основные тесты

```powershell
py -m unittest discover -s tests -p "test_sparse_to_raw.py" -v
```

## GUI smoke-тесты

```powershell
py -m pip install -r requirements-gui.txt
$env:QT_QPA_PLATFORM = "offscreen"
py -m unittest discover -s tests -p "gui_smoke_tests.py" -v
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
```

Платформа `offscreen` нужна только для тестирования без настоящего окна. Перед обычным запуском GUI удалите эту переменную окружения.

## Полный набор тестов

```powershell
py -m unittest discover -s tests -v
```

## Системные зависимости GUI-тестов в Linux

В headless Ubuntu установите системные библиотеки Qt до импорта PySide6:

```bash
sudo apt-get update
sudo apt-get install -y libegl1 libgl1 libdbus-1-3 libxkbcommon-x11-0 libxcb-cursor0
```

## Локальная сборка Windows-приложений

Установите зависимости упаковки:

```powershell
py -m pip install -r requirements-build.txt
```

Сборка CLI:

```powershell
py -m PyInstaller --noconfirm --clean --onefile --name sparse-to-raw sparse_to_raw.py
```

Сборка GUI-папки:

```powershell
py -m PyInstaller --noconfirm --clean --windowed --onedir --name sparse-to-raw-gui --icon assets/sparse-to-raw.ico --add-data "assets/sparse-to-raw.ico;assets" sparse_to_raw_gui.py
```

Сборка однофайлового GUI:

```powershell
py -m PyInstaller --noconfirm --clean --windowed --onefile --name sparse-to-raw-gui --icon assets/sparse-to-raw.ico --add-data "assets/sparse-to-raw.ico;assets" sparse_to_raw_gui.py
```

Запускайте PyInstaller из корня репозитория, чтобы относительные пути к иконке и ресурсам разрешались корректно. В GitHub Actions используется абсолютный путь к иконке, поскольку `.spec` хранятся в отдельных каталогах сборки.

## Self-test упакованного GUI

У GUI есть точка входа `--self-test`, которая используется workflow релиза. Workflow собирает варианты folder и one-file, а затем запускает каждый из них с удалёнными из `PATH` каталогами Python, чтобы проверить автономный запуск.

## Поведение GUI, которое нужно сохранять

- Настройки и последние файлы сохраняются через `QSettings`.
- Скорость хранится внутри программы в байтах в секунду и конвертируется только для отображения.
- Конвертация, анализ и объединение не блокируют GUI-поток.
- Пакетная обработка последовательная; повторяющиеся имена результатов отклоняются.
- Для объединения используются независимые Sparse-файлы в порядке, выбранном пользователем.
- Результат публикуется только после проверки; отмена удаляет временные файлы и сохраняет существующий результат.
