"""Generator de pattern de tobe realist pentru testele de beat: kick cu atac, snare pe 2 și 4, hi-hat pe optimi."""
from __future__ import annotations

import wave

import numpy as np


def drum_track(path: str, bpm: float, dur: float = 20.0, offset: float = 0.37, sr: int = 22050,
               seed: int = 1, hat_level: float = 0.12) -> np.ndarray:
    rng = np.random.default_rng(seed)
    y = 0.01 * rng.standard_normal(int(sr * dur))
    t = np.arange(int(0.25 * sr)) / sr
    f = 110 * np.exp(-t * 25) + 45  # kick: sweep 155 -> 45 Hz + click de atac
    kick = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 12)
    kick[: int(0.004 * sr)] += rng.standard_normal(int(0.004 * sr)) * 0.6
    snare = (rng.standard_normal(len(t)) * 0.5 + np.sin(2 * np.pi * 190 * t)) * np.exp(-t * 22)
    th = np.arange(int(0.05 * sr)) / sr
    hat = np.diff(rng.standard_normal(len(th) + 1)) * np.exp(-th * 90) * hat_level

    def add(sig, at, gain=1.0):
        i = int(at * sr)
        if i < len(y):
            n = min(len(sig), len(y) - i)
            y[i:i + n] += gain * sig[:n]

    per = 60 / bpm
    beats = np.arange(offset, dur - 0.3, per)
    for k, b in enumerate(beats):
        add(kick, b, 1.0 if k % 4 == 0 else 0.85)
        if k % 2 == 1:
            add(snare, b, 0.7)
        add(hat, b)
        add(hat, b + per / 2)
    y = y / np.abs(y).max() * 0.8
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    return beats
