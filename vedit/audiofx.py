"""Curățarea vocii: diagnostic măsurat + preseturi de filtre ffmpeg.

Diagnosticul compară nivelul vorbirii cu zgomotul din pauze (SNR) și caută clipping, iar recomandarea
decurge din cifre. Preseturile sunt lanțuri clasice de post-producție: high-pass (zgomot de joasă
frecvență, vânt, trafic) → reducere de zgomot spectrală (afftdn, care învață profilul zgomotului) →
de-esser → compresor → prezență (EQ ușor la 3 kHz). Loudness-ul final rămâne la loudnorm-ul din render.
"""
from __future__ import annotations

from pydantic import BaseModel

PRESETS = ("light", "medium", "strong", "voice")


class AudioFx(BaseModel):
    preset: str
    noise_db: float = -60.0  # zgomotul măsurat în pauze (audio_check); calibrează filtrele


def chain(fx: AudioFx) -> str:
    """Lanțul de filtre, calibrat pe zgomotul MĂSURAT al sursei (praguri fixe nu merg: am măsurat)."""
    nf = max(-80, min(-20, round(fx.noise_db)))
    gate_thr = 10 ** ((fx.noise_db + 10) / 20)  # poarta se închide sub zgomot + 10 dB
    denoise = f"afftdn=nr={{nr}}:nf={nf}"
    gate = "agate=threshold={t:.5f}:ratio=4:range={r}:attack=5:release=160"
    comp = "acompressor=threshold=-22dB:ratio=3:attack=8:release=160"
    if fx.preset == "light":
        return f"highpass=f=80,{denoise.format(nr=12)}"
    if fx.preset == "medium":
        return f"highpass=f=90,{denoise.format(nr=20)},{gate.format(t=gate_thr, r=0.25)},deesser=i=0.3,{comp}"
    if fx.preset == "strong":
        return (f"highpass=f=100,{denoise.format(nr=28)},{gate.format(t=gate_thr, r=0.08)},"
                f"deesser=i=0.4,{comp}")
    if fx.preset == "voice":
        return (f"highpass=f=80,{denoise.format(nr=10)},equalizer=f=250:t=q:w=1:g=-2,"
                f"equalizer=f=3200:t=q:w=1.2:g=3,{comp}")
    raise ValueError(f"preset necunoscut: {fx.preset}")


class AudioCheck(BaseModel):
    speech_db: float
    noise_db: float
    snr_db: float
    clipping_pct: float
    recommendation: str

    def summary(self) -> str:
        return (f"vorbire {self.speech_db:.1f} dBFS · zgomot în pauze {self.noise_db:.1f} dBFS · "
                f"SNR {self.snr_db:.0f} dB · clipping {self.clipping_pct:.2f}%\n→ {self.recommendation}")


def check(path: str, silences: list[tuple[float, float]]) -> AudioCheck:
    import numpy as np

    from .beats import load_mono

    sr = 16000
    y = load_mono(path, sr=sr)
    if y.size == 0:
        raise ValueError("fără audio")
    mask = np.zeros(len(y), bool)
    for a, b in silences:
        mask[int(a * sr): int(b * sr)] = True

    def rms_db(x):
        return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)) if x.size else -120.0

    speech, noise = rms_db(y[~mask]), rms_db(y[mask]) if mask.any() else -120.0
    if not mask.any():  # fără pauze: estimăm zgomotul din cele mai liniștite 10% ferestre
        win = y[: len(y) // 1600 * 1600].reshape(-1, 1600)
        levels = np.sort(20 * np.log10(np.sqrt((win ** 2).mean(1)) + 1e-9))
        noise = float(levels[: max(1, len(levels) // 10)].mean())
    snr = speech - noise
    clip = float((np.abs(y) > 0.99).mean() * 100)
    if snr < 15:
        rec = "zgomot mare: audio_clean(preset='strong'); verifică după, poate suna „metalic”"
    elif snr < 25:
        rec = "zgomot vizibil: audio_clean(preset='medium')"
    elif snr < 35:
        rec = "zgomot ușor: audio_clean(preset='light')"
    else:
        rec = "curat; dacă vocea sună subțire sau înfundată: audio_clean(preset='voice')"
    if clip > 0.1:
        rec += ". ATENȚIE: clipping; distorsiunea nu se poate repara, spune-i clientului"
    return AudioCheck(speech_db=round(speech, 1), noise_db=round(noise, 1), snr_db=round(snr, 1),
                      clipping_pct=round(clip, 3), recommendation=rec)
