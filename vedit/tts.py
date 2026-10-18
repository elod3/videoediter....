"""Voice-over local și gratuit (Piper TTS): textul scris devine voce, cu timpii fiecărui cuvânt.

Vocea se descarcă o dată (~60 MB) în `VEDIT_HOME/.models/piper`. Piper sintetizează propoziție cu propoziție,
deci știm exact unde începe și se termină fiecare frază; în interiorul frazei, cuvintele primesc timpi
proporționali cu lungimea lor (suficient pentru subtitrări pe grupuri de cuvinte).

Env:
  VEDIT_TTS_VOICES   JSON {"ro": "ro/ro_RO/mihai/medium/ro_RO-mihai-medium", ...} (căi din rhasspy/piper-voices)
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import wave
from pathlib import Path

import numpy as np

VOICES = {
    "ro": "ro/ro_RO/mihai/medium/ro_RO-mihai-medium",
    "en": "en/en_US/ryan/medium/en_US-ryan-medium",
    "hu": "hu/hu_HU/anna/medium/hu_HU-anna-medium",
    "de": "de/de_DE/thorsten/medium/de_DE-thorsten-medium",
    "es": "es/es_ES/davefx/medium/es_ES-davefx-medium",
    "fr": "fr/fr_FR/siwis/medium/fr_FR-siwis-medium",
    "it": "it/it_IT/riccardo/x_low/it_IT-riccardo-x_low",
}
BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
SR_OUT = 48000


def voices() -> dict[str, str]:
    try:
        extra = json.loads(os.environ.get("VEDIT_TTS_VOICES", "") or "{}")
    except json.JSONDecodeError:
        extra = {}
    return {**VOICES, **{k: v for k, v in extra.items() if isinstance(v, str)}}


def _voice_file(lang: str) -> Path:
    from .project import home

    table = voices()
    if lang not in table:
        raise ValueError(f"limbă fără voce: {lang}; disponibile: {', '.join(sorted(table))}")
    rel = table[lang]
    dst = home() / ".models" / "piper" / f"{Path(rel).name}.onnx"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        for ext in (".onnx.json", ".onnx"):
            tmp = dst.with_name(dst.name.replace(".onnx", ext) + ".part")
            try:
                urllib.request.urlretrieve(f"{BASE}/{rel}{ext}", tmp)  # noqa: S310 (URL fix din config)
            except OSError as e:
                raise RuntimeError(f"nu pot descărca vocea {lang} ({e})") from e
            tmp.replace(dst.with_name(dst.name.replace(".onnx", ext)))
    return dst


def sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    parts = re.split(r"(?<=[.!?…])\s+", text)
    return [p for p in parts if p.strip()]


def synth(text: str, lang: str, out: str, speed: float = 1.0, pause: float = 0.28) -> list[tuple[float, float, str]]:
    """Scrie vocea în `out` (WAV 48 kHz mono) și întoarce cuvintele cu timpi: [(start, end, cuvânt)]."""
    try:
        from piper import PiperVoice
        from piper.config import SynthesisConfig
    except ImportError as e:
        raise RuntimeError("voice-over-ul cere Piper: pip install 'vedit[tts]'") from e
    if not 0.6 <= speed <= 1.6:
        raise ValueError("speed între 0.6 și 1.6")
    voice = PiperVoice.load(str(_voice_file(lang)))
    cfg = SynthesisConfig(length_scale=1.0 / speed)
    audio: list[np.ndarray] = []
    words: list[tuple[float, float, str]] = []
    t = 0.15
    audio.append(np.zeros(int(0.15 * SR_OUT), np.float32))
    for sent in sentences(text):
        chunks = list(voice.synthesize(sent, syn_config=cfg))
        if not chunks:
            continue
        sr = chunks[0].sample_rate
        y = np.concatenate([c.audio_float_array for c in chunks]).astype(np.float32)
        # reeșantionare liniară la 48 kHz (sunetul final merge oricum prin aresample în ffmpeg)
        n = int(len(y) * SR_OUT / sr)
        y = np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y).astype(np.float32)
        # liniștea de la capete nu intră în timpii cuvintelor
        loud = np.flatnonzero(np.abs(y) > 0.02)
        a, b = (loud[0], loud[-1]) if loud.size else (0, len(y))
        s0, s1 = t + a / SR_OUT, t + b / SR_OUT
        toks = sent.split()
        weights = np.array([len(re.sub(r"\W", "", w)) + 2 for w in toks], float)
        edges = s0 + (s1 - s0) * np.concatenate([[0], np.cumsum(weights) / weights.sum()])
        words += [(round(edges[i], 3), round(edges[i + 1] - 0.02, 3), w) for i, w in enumerate(toks)]
        audio.append(y)
        audio.append(np.zeros(int(pause * SR_OUT), np.float32))
        t += (len(y) + int(pause * SR_OUT)) / SR_OUT
    if not words:
        raise ValueError("textul e gol")
    pcm = (np.clip(np.concatenate(audio), -1, 1) * 32767).astype("<i2")
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR_OUT)
        w.writeframes(pcm.tobytes())
    return words
