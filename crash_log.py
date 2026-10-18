"""Запись ошибок и вылетов в crash.log, чтобы их можно было разобрать после закрытия окна.

Модуль подключается первым в main.py, до PyTorch и остальных зависимостей, поэтому
в лог попадают и ошибки запуска (нет библиотек, старый Python и т.п.).
Синтаксис намеренно простой, чтобы модуль работал даже на старых версиях Python.
"""

import datetime
import logging
import logging.handlers
import os
import platform
import sys
import threading

log = logging.getLogger("crash")
LOG_PATH = None


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


class _CrashFileHandler(logging.handlers.RotatingFileHandler):
    """Пишет предупреждения и ошибки; перед первой записью за запуск — сведения о системе."""

    header_written = False

    def emit(self, record):
        if not self.header_written:
            self.header_written = True
            stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            header = logging.makeLogRecord({
                "name": "crash", "levelno": logging.WARNING, "levelname": "INFO",
                "msg": "===== запуск " + stamp + " | " + environment() + " =====",
            })
            super().emit(header)
        super().emit(record)


def install(path, verbose=False):
    """Настраивает вывод в консоль и в файл, перехватывает необработанные исключения."""
    global LOG_PATH
    LOG_PATH = path

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
    root.addHandler(console)

    try:
        file_handler = _CrashFileHandler(path, maxBytes=1_000_000, backupCount=1, encoding="utf-8", delay=True)
        file_handler.setLevel(logging.WARNING)
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
        root.addHandler(file_handler)
    except OSError:
        log.warning("Не удалось открыть %s, ошибки будут только в консоли", path)

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook


def _excepthook(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    log.critical("Скрипт упал", exc_info=(exc_type, exc, tb))
    print("\nСкрипт упал. Подробности записаны в " + str(LOG_PATH), file=sys.stderr)


def _thread_excepthook(args):
    if issubclass(args.exc_type, SystemExit):
        return
    log.error("Ошибка в потоке %s", args.thread.name if args.thread else "?",
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
