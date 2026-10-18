"""Синтез речи через Silero и воспроизведение звука."""

import logging
import time
import urllib.request
from pathlib import Path

import numpy as np
import sounddevice as sd
import torch

from text_normalize import for_cyrillic_tts

log = logging.getLogger(__name__)

SILERO_URL = "https://models.silero.ai/models/tts/ru/{model}.pt"
# Silero понимает только 5 ступеней скорости
SILERO_RATES = [(0.75, "x-slow"), (0.92, "slow"), (1.15, "medium"), (1.3, "fast")]
PLAY_GRACE = 3.0  # с сверх длины звука, после которых считаем, что воспроизведение зависло


class SileroEngine:
    """Нейросетевой синтез Silero (PyTorch, CPU)."""

    def __init__(self, cfg: dict, base_dir: Path):
        model_name = cfg.get("model", "v5_6_ru")
        path = base_dir / cfg.get("models_dir", "models") / f"{model_name}.pt"
        if not path.exists():
            _download(SILERO_URL.format(model=model_name), path)

        torch.set_num_threads(cfg.get("threads", 4))
        self.model = torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
        self.model.to(torch.device("cpu"))
        log.info("Загружена модель Silero %s", model_name)

        available = list(getattr(self.model, "speakers", []))
        wanted = cfg.get("speakers", ["xenia"])
        if wanted == "all":
            wanted = available
        missing = [s for s in wanted if s not in available]
        if missing:
            log.warning("В модели %s нет голосов: %s", model_name, ", ".join(missing))
        self.voice_names = [s for s in wanted if s in available]
        if not self.voice_names:
            raise ValueError(f"В модели {model_name} нет таких голосов. Доступны: {', '.join(available)}")
        self.sample_rate = cfg.get("sample_rate", 48000)
        self.volume = cfg.get("volume", 1.0)

        speed = cfg.get("speed", 1.0)
        self.rate = next((name for limit, name in SILERO_RATES if speed < limit), "x-fast")

    def synthesize(self, text: str, voice_name: str | None = None) -> tuple[np.ndarray, int]:
        text = for_cyrillic_tts(text)
        speaker = voice_name if voice_name in self.voice_names else self.voice_names[0]
        kwargs = {"speaker": speaker, "sample_rate": self.sample_rate}
        if self.rate == "medium":
            kwargs["text"] = text
        else:
            escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            kwargs["ssml_text"] = f'<speak><prosody rate="{self.rate}">{escaped}</prosody></speak>'

        try:
            with torch.no_grad():
                audio = self.model.apply_tts(**kwargs).numpy()
        except ValueError:
            # в тексте не осталось ничего, что Silero умеет произносить
            log.debug("Silero не смог озвучить: %r", text)
            return np.zeros(0, dtype=np.float32), self.sample_rate
        audio = np.clip(audio * self.volume, -1.0, 1.0)
        return audio.astype(np.float32), self.sample_rate


def _download(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Скачиваю %s (один раз, ~150 МБ)...", url)
    tmp = path.with_suffix(".part")
    try:
        urllib.request.urlretrieve(url, tmp)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"Не удалось скачать модель {url}: {e}\n"
            f"Проверьте интернет и название модели или скопируйте файл {path.name} "
            f"в папку {path.parent} с другого компьютера."
        ) from e
    tmp.replace(path)


class Player:
    def __init__(self, device: str | int | None = None):
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        self.device = device or None

    def play(self, audio: np.ndarray, sample_rate: int) -> None:
        """Играет звук и блокирует поток до конца (или до stop())."""
        if audio.size == 0:
            return
        sd.play(audio, sample_rate, device=self.device)
        # sd.wait() без таймаута: если аудиодрайвер завис, встала бы вся озвучка
        deadline = time.monotonic() + len(audio) / sample_rate + PLAY_GRACE
        while sd.get_stream().active:
            if time.monotonic() > deadline:
                log.warning("Звук не доиграл вовремя, аудиоустройство зависло? Останавливаем")
                sd.stop()
                break
            time.sleep(0.05)

    def stop(self) -> None:
        sd.stop()


def list_output_devices() -> None:
    default_out = sd.default.device[1]
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            mark = "*" if i == default_out else " "
            hostapi = sd.query_hostapis(dev["hostapi"])["name"]
            print(f"{mark} {i:3d}: {dev['name']}  [{hostapi}]")
