"""Озвучка чата Twitch в реальном времени.

Запуск:
    python main.py                      # канал берётся из config.toml
    python main.py --channel имя_канала
    python main.py --say "Проверка связи"  # проверить голос без чата
    python main.py --list-devices       # список аудиовыходов

Управление во время работы (ввод в консоли + Enter):
    s - пропустить текущее сообщение
    c - очистить очередь
    p - пауза / продолжить
    q - выход
"""

import argparse
import asyncio
import logging
import queue
import sys
import threading
import tomllib
from pathlib import Path

from text_filter import MessageFilter
from tts_engine import PiperEngine, Player, list_output_devices
from twitch_chat import read_chat

log = logging.getLogger("tts")


class Speaker:
    """Очередь сообщений + фоновый поток, который синтезирует и проигрывает их по одному."""

    def __init__(self, engine: PiperEngine, player: Player, max_queue: int):
        self.engine = engine
        self.player = player
        self.queue: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=max_queue)
        self.resumed = threading.Event()
        self.resumed.set()
        threading.Thread(target=self._worker, daemon=True).start()

    def say(self, text: str, user: str = "") -> None:
        try:
            self.queue.put_nowait((user, text))
        except queue.Full:
            # чат слишком быстрый: выкидываем самое старое сообщение
            try:
                self.queue.get_nowait()
            except queue.Empty:
                pass
            self.queue.put_nowait((user, text))

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

    def _worker(self) -> None:
        while True:
            user, text = self.queue.get()
            self.resumed.wait()
            try:
                audio, sr = self.engine.synthesize(text, user)
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


async def run(channel: str, msg_filter: MessageFilter, speaker: Speaker, stop: threading.Event):
    async def consume():
        async for msg in read_chat(channel):
            text = msg_filter.process(msg)
            if text is None:
                log.debug("пропущено: %s: %s", msg.display_name, msg.text)
                continue
            print(f"{msg.display_name}: {msg.text}")
            speaker.say(text, msg.user)

    task = asyncio.create_task(consume())
    while not stop.is_set() and not task.done():
        await asyncio.sleep(0.2)
    task.cancel()


def load_config(path: Path) -> dict:
    if not path.exists():
        sys.exit(f"Не найден файл настроек {path}")
    with path.open("rb") as f:
        return tomllib.load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Озвучка чата Twitch")
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.toml"))
    parser.add_argument("--channel", help="канал Twitch (перекрывает config.toml)")
    parser.add_argument("--say", help="озвучить текст и выйти (проверка голоса)")
    parser.add_argument("--list-devices", action="store_true", help="показать аудиовыходы")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if args.list_devices:
        list_output_devices()
        return

    cfg = load_config(args.config)
    tts_cfg = cfg.get("tts", {})
    voices_dir = Path(tts_cfg.get("voices_dir", "voices"))
    if not voices_dir.is_absolute():
        tts_cfg["voices_dir"] = str(args.config.parent / voices_dir)

    engine = PiperEngine(tts_cfg)
    player = Player(cfg.get("audio", {}).get("output_device"))

    if args.say:
        audio, sr = engine.synthesize(args.say)
        player.play(audio, sr)
        return

    channel = args.channel or cfg.get("twitch", {}).get("channel", "")
    if not channel:
        sys.exit("Укажите канал: --channel имя или [twitch] channel в config.toml")

    speaker = Speaker(engine, player, cfg.get("chat", {}).get("max_queue", 10))
    msg_filter = MessageFilter(cfg.get("chat", {}))
    stop = threading.Event()
    threading.Thread(target=console_controls, args=(speaker, stop), daemon=True).start()

    print("Управление: s - пропуск, c - очистить очередь, p - пауза, q - выход")
    try:
        asyncio.run(run(channel, msg_filter, speaker, stop))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
