"""Синтез речи (Piper) и воспроизведение звука."""

import logging
import zlib
from pathlib import Path

import numpy as np
import sounddevice as sd
from piper import PiperVoice, SynthesisConfig

log = logging.getLogger(__name__)


class PiperEngine:
    """Офлайн-синтез через Piper. Можно загрузить несколько голосов."""

    def __init__(self, cfg: dict):
        voices_dir = Path(cfg.get("voices_dir", "voices"))
        names = cfg.get("voices") or ["ru_RU-irina-medium"]
        self.voices: list[PiperVoice] = []
        for name in names:
            path = voices_dir / f"{name}.onnx"
            if not path.exists():
                raise FileNotFoundError(
                    f"Голос {path} не найден. Скачайте его:\n"
                    f"  python -m piper.download_voices --download-dir {voices_dir} {name}"
                )
            self.voices.append(PiperVoice.load(path))
            log.info("Загружен голос %s", name)

        self.voice_per_user = cfg.get("voice_per_user", False)
        self.syn_config = SynthesisConfig(
            length_scale=1.0 / cfg.get("speed", 1.0),
            volume=cfg.get("volume", 1.0),
        )

    def _pick_voice(self, user: str) -> PiperVoice:
        if self.voice_per_user and len(self.voices) > 1:
            # у одного и того же зрителя всегда один и тот же голос
            return self.voices[zlib.crc32(user.encode()) % len(self.voices)]
        return self.voices[0]

    def synthesize(self, text: str, user: str = "") -> tuple[np.ndarray, int]:
        voice = self._pick_voice(user)
        chunks = [c.audio_float_array for c in voice.synthesize(text, self.syn_config)]
        audio = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
        return audio.astype(np.float32), voice.config.sample_rate


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
        sd.wait()

    def stop(self) -> None:
        sd.stop()


def list_output_devices() -> None:
    default_out = sd.default.device[1]
    for i, dev in enumerate(sd.query_devices()):
        if dev["max_output_channels"] > 0:
            mark = "*" if i == default_out else " "
            hostapi = sd.query_hostapis(dev["hostapi"])["name"]
            print(f"{mark} {i:3d}: {dev['name']}  [{hostapi}]")
