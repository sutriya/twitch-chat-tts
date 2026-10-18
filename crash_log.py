"""Запись ошибок и вылетов в crash.log, чтобы их можно было разобрать после закрытия окна.

Модуль подключается первым в main.py, до PyTorch и остальных зависимостей, поэтому
в лог попадают и ошибки запуска (нет библиотек, старый Python и т.п.).

Аварийные падения внутри библиотек (PyTorch, звуковой драйвер) мимо Python-обработчиков
не проходят: их ловит faulthandler в crash_native.tmp, а run.bat после такого падения
переносит дамп в crash.log вместе с кодом выхода.

Синтаксис намеренно простой, чтобы модуль работал даже на старых версиях Python.
"""

import faulthandler
import logging
import os
import platform
import sys
import threading

log = logging.getLogger("crash")
LOG_PATH = None
_native_file = None


def environment():
    parts = [
        "Python " + sys.version.split()[0] + " (" + sys.executable + ")",
        platform.platform(),
        "папка: " + os.getcwd(),
    ]
    torch = sys.modules.get("torch")
    if torch is not None:
        parts.append("torch " + str(getattr(torch, "__version__", "?")))
    return " | ".join(parts)


def install(path, verbose=False):
    """Настраивает вывод в консоль и в файл, перехватывает необработанные исключения."""
    global LOG_PATH, _native_file
    LOG_PATH = path

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    root.addHandler(console)

    file_handler = logging.FileHandler(path, encoding="utf-8", delay=True)
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    root.addHandler(file_handler)

    try:
        # файл перезаписывается при каждом запуске; run.bat забирает его только после падения
        _native_file = open(os.path.join(os.path.dirname(str(path)), "crash_native.tmp"), "w")
        faulthandler.enable(_native_file, all_threads=True)
    except OSError:
        log.warning("Не удалось включить запись аварийных падений рядом с %s", path)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    log.critical("Скрипт упал | %s", environment(), exc_info=(exc_type, exc, tb))
    print("\nСкрипт упал. Подробности записаны в " + str(LOG_PATH), file=sys.stderr)


def _thread_excepthook(args):
    if issubclass(args.exc_type, SystemExit):
        return
    log.error("Ошибка в потоке %s | %s", args.thread.name if args.thread else "?", environment(),
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
