"""Озвучка чата Twitch в реальном времени.

Запуск:
    python main.py                      # канал берётся из config.toml
    python main.py --channel имя_канала
    python main.py --say "Проверка связи"  # проверить голос без чата
    python main.py --say "Привет" --voice all  # послушать все голоса по очереди
    python main.py --list-devices       # список аудиовыходов

Зрители меняют себе голос командой в чате: !голос 2, !голос baya, !голос сброс

Управление во время работы (ввод в консоли + Enter):
    s - пропустить текущее сообщение
    c - очистить очередь
    p - пауза / продолжить
    q - выход
"""

import sys
from pathlib import Path

import crash_log

# до остальных импортов, чтобы в crash.log попали и ошибки загрузки PyTorch и библиотек
crash_log.install(Path(__file__).with_name("crash.log"), verbose="-v" in sys.argv or "--verbose" in sys.argv)

if "--crash-test" in sys.argv:
    # проверка диагностики: аварийное падение процесса, как при сбое внутри PyTorch или драйвера
    import faulthandler

    faulthandler._sigsegv()

import argparse
import asyncio
import logging
import queue
import threading
import tomllib
import warnings

from text_filter import MessageFilter
from tts_engine import Player, SileroEngine, list_output_devices
from twitch_chat import read_chat
from voices import VoiceSelector

log = logging.getLogger("tts")


def disable_console_quick_edit() -> None:
    """Щелчок мышью в окне консоли Windows включает выделение текста и замораживает
    весь вывод, а с ним и скрипт, пока не нажать Esc. Отключаем это для своего окна."""
    if sys.platform != "win32":
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
    mode = ctypes.c_uint32()
    if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
        ENABLE_QUICK_EDIT_MODE, ENABLE_EXTENDED_FLAGS = 0x0040, 0x0080
        kernel32.SetConsoleMode(handle, (mode.value & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
# код модели Silero сыпет SyntaxWarning на новых версиях Python
warnings.filterwarnings("ignore", category=SyntaxWarning)


class Speaker:
    """Очередь сообщений; run() синтезирует и проигрывает их по одному.

    run() должен работать в главном потоке: PyTorch 2.14 на Python 3.15 под Windows
    падает (access violation) на любой операции с тензорами в неглавном потоке.
    """

    def __init__(self, engine, player: Player, max_queue: int):
        self.engine = engine
        self.player = player
        self.queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=max_queue)
        self.resumed = threading.Event()
        self.resumed.set()

    def say(self, text: str, voice: str | None = None) -> None:
        try:
            self.queue.put_nowait((voice, text))
        except queue.Full:
            # чат слишком быстрый: выкидываем самое старое сообщение
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.queue.put_nowait((voice, text))

    def skip(self) -> None:
        self.player.stop()

    def clear(self) -> None:
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.player.stop()

    def toggle_pause(self) -> bool:
        if self.resumed.is_set():
            self.resumed.clear()
            self.player.stop()
            return True
        self.resumed.set()
        return False

    def run(self, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                voice, text = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            while not self.resumed.wait(timeout=0.2):
                if stop.is_set():
                    return
            try:
                audio, sr = self.engine.synthesize(text, voice)
                self.player.play(audio, sr)
            except Exception:
                log.exception("Не удалось озвучить сообщение")


def console_controls(speaker: Speaker, stop: threading.Event) -> None:
    for line in sys.stdin:
        cmd = line.strip().lower()
        if cmd in ("s", "skip"):
            speaker.skip()
            print("[пропущено]")
        elif cmd in ("c", "clear"):
            speaker.clear()
            print("[очередь очищена]")
        elif cmd in ("p", "pause"):
            print("[пауза]" if speaker.toggle_pause() else "[продолжаем]")
        elif cmd in ("q", "quit", "exit"):
            stop.set()
            return


def handle_voice_command(msg, cmd_cfg: dict, selector: VoiceSelector, speaker: Speaker) -> bool:
    """Обрабатывает "!голос 2" и т.п. Возвращает True, если сообщение было командой."""
    if not cmd_cfg.get("enabled", True):
        return False
    word, _, arg = msg.text.strip().partition(" ")
    if word.lower() not in [c.lower() for c in cmd_cfg.get("commands", ["!voice", "!голос"])]:
        return False
    if not arg.strip():
        print(f"[{msg.display_name} спрашивает голоса] {selector.describe()}")
        return True
    voice = selector.set_voice(msg.user, arg)
    if voice is None:
        print(f"[{msg.display_name}: нет голоса {arg.strip()!r}] есть: {selector.describe()}")
        return True
    print(f"[{msg.display_name} -> голос {voice}]")
    if confirm := cmd_cfg.get("confirm_text", ""):
        speaker.say(confirm.format(name=msg.display_name, voice=voice), voice)
    return True


async def run(channel: str, msg_filter: MessageFilter, speaker: Speaker, selector: VoiceSelector,
              cmd_cfg: dict, stop: threading.Event):
    def handle(msg):
        if msg.user in msg_filter.ignore_users:
            return
        if handle_voice_command(msg, cmd_cfg, selector, speaker):
            return
        text = msg_filter.process(msg)
        if text is None:
            log.debug("пропущено: %s: %s", msg.display_name, msg.text)
            return
        print(f"{msg.display_name}: {msg.text}")
        speaker.say(text, selector.voice_for(msg.user))

    async def consume():
        async for msg in read_chat(channel):
            try:
                handle(msg)
            except Exception:
                # одно кривое сообщение не должно ронять всю озвучку
                log.exception("Ошибка при обработке сообщения %s: %r", msg.display_name, msg.text)

    while not stop.is_set():
        task = asyncio.create_task(consume())
        while not stop.is_set() and not task.done():
            await asyncio.sleep(0.2)
        if task.done() and not task.cancelled() and task.exception():
            log.error("Чтение чата упало, перезапуск через 3 с", exc_info=task.exception())
            await asyncio.sleep(3)
        else:
            task.cancel()


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"Не найден файл настроек {path}")
    # utf-8-sig: Блокнот и PowerShell могут сохранить файл с BOM, tomllib на нём падает
    text = path.read_bytes().decode("utf-8-sig")
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        log.critical("Ошибка в %s: %s", path, e)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Озвучка чата Twitch")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.toml"))
    parser.add_argument("--channel", help="канал Twitch (перекрывает config.toml)")
    parser.add_argument("--say", help="озвучить текст и выйти (проверка голоса)")
    parser.add_argument("--voice", help="каким голосом озвучить --say (имя, псевдоним или номер; all - всеми)")
    parser.add_argument("--list-devices", action="store_true", help="показать аудиовыходы")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.list_devices:
        list_output_devices()
        return

    cfg = load_config(args.config)
    tts_cfg = cfg.get("tts", {})
    cmd_cfg = cfg.get("voice_command", {})
    engine = SileroEngine(tts_cfg, args.config.parent)
    player = Player(cfg.get("audio", {}).get("output_device"))
    selector = VoiceSelector(
        engine.voice_names,
        per_user=tts_cfg.get("voice_per_user", False),
        aliases=cmd_cfg.get("aliases", {}),
        store_path=args.config.parent / "user_voices.json",
    )
    print(f"Голоса: {selector.describe()}")

    if args.say:
        if args.voice == "all":
            voices = engine.voice_names
        else:
            voices = [selector.resolve(args.voice) if args.voice else engine.voice_names[0]]
            if voices[0] is None:
                sys.exit(f"Нет голоса {args.voice!r}")
        for voice in voices:
            print(f"-> {voice}")
            audio, sr = engine.synthesize(args.say, voice)
            player.play(audio, sr)
        return

    channel = args.channel or cfg.get("twitch", {}).get("channel", "")
    if not channel:
        sys.exit("Укажите канал: --channel имя или [twitch] channel в config.toml")

    speaker = Speaker(engine, player, cfg.get("chat", {}).get("max_queue", 10))
    msg_filter = MessageFilter(cfg.get("chat", {}))
    stop = threading.Event()
    threading.Thread(target=console_controls, args=(speaker, stop), daemon=True).start()

    def chat_thread():
        try:
            asyncio.run(run(channel, msg_filter, speaker, selector, cmd_cfg, stop))
        finally:
            stop.set()

    # чат читается в фоне, а синтез идёт в главном потоке (см. Speaker)
    threading.Thread(target=chat_thread, name="chat", daemon=True).start()

    disable_console_quick_edit()
    print("Управление: s - пропуск, c - очистить очередь, p - пауза, q - выход")
    try:
        speaker.run(stop)
    except KeyboardInterrupt:
        stop.set()


if __name__ == "__main__":
    main()
