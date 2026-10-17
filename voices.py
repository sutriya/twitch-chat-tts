"""Какой голос у какого зрителя: выбор командой в чате, сохранение между запусками."""

import json
import logging
import threading
import zlib
from pathlib import Path

log = logging.getLogger(__name__)

RESET_WORDS = {"reset", "сброс", "default", "стандарт"}


class VoiceSelector:
    def __init__(self, voices: list[str], per_user: bool, aliases: dict[str, str], store_path: Path):
        self.voices = voices
        self.per_user = per_user
        self.aliases = {a.lower(): v for a, v in aliases.items() if v in voices}
        self.store_path = store_path
        self._lock = threading.Lock()
        self.chosen: dict[str, str] = {}
        if store_path.exists():
            try:
                saved = json.loads(store_path.read_text(encoding="utf-8"))
                self.chosen = {u: v for u, v in saved.items() if v in voices}
            except (OSError, ValueError):
                log.warning("Не удалось прочитать %s, выбор голосов сброшен", store_path)

    def voice_for(self, user: str) -> str:
        if user in self.chosen:
            return self.chosen[user]
        if self.per_user and user and len(self.voices) > 1:
            # у одного и того же зрителя всегда один и тот же голос
            return self.voices[zlib.crc32(user.encode()) % len(self.voices)]
        return self.voices[0]

    def resolve(self, arg: str) -> str | None:
        arg = arg.strip().lower()
        if arg.isdigit() and 1 <= int(arg) <= len(self.voices):
            return self.voices[int(arg) - 1]
        if arg in self.voices:
            return arg
        if f"ru_{arg}" in self.voices:
            return f"ru_{arg}"  # голоса модели v5_cis_base: igor -> ru_igor
        return self.aliases.get(arg)

    def set_voice(self, user: str, arg: str) -> str | None:
        """Меняет голос зрителя. Возвращает новый голос или None, если такого нет."""
        if arg.strip().lower() in RESET_WORDS:
            with self._lock:
                self.chosen.pop(user, None)
                self._save()
            return self.voice_for(user)
        voice = self.resolve(arg)
        if voice:
            with self._lock:
                self.chosen[user] = voice
                self._save()
        return voice

    def describe(self) -> str:
        return ", ".join(f"{i} - {v}" for i, v in enumerate(self.voices, 1))

    def _save(self) -> None:
        try:
            self.store_path.write_text(json.dumps(self.chosen, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            log.exception("Не удалось сохранить выбор голосов")
