"""Efecte sonore sintetizate procedural (numpy), deterministe: whoosh, pop, click, impact etc.

Fiecare efect se generează o singură dată ca WAV 48 kHz stereo 16-bit în `VEDIT_HOME/.sfx/<tip>.wav`
și e refolosit de randare. Fără scipy: filtrele (state-variable, one-pole, FFT) sunt scrise aici.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 48000
PEAK_DB = -3.0
SEED = 20240611

SFX_HELP: dict[str, str] = {
    "whoosh": "trecere rapidă de aer - pe tranziții, schimbări de scenă, text care intră în cadru",
    "pop": "bulă scurtă - la apariția unui text, emoji, sticker sau a unui element grafic",
    "click": "clic sec - la apăsări pe ecran, liste, bife, tutoriale de aplicații",
    "impact": "lovitură grea și joasă - pe momentul-cheie, reveal, cuvântul important din hook",
    "riser": "tensiune care crește și se oprește brusc - înainte de un drop, reveal sau tăietură mare",
    "ding": "clopoțel - pe idei bune, bifă, răspuns corect, „notificare”",
    "swipe": "alunecare scurtă și ascuțită - pe slide-uri, schimbări rapide de imagine, zoom-uri",
    "bass_drop": "cădere de bas - pe începutul refrenului, reveal dramatic, trecerea la partea principală",
    "bleep": "bipul de cenzură TV (1 kHz) - peste înjurături; pus automat de censor_words",
}

durations: dict[str, float] = {
    "whoosh": 0.6, "pop": 0.12, "click": 0.03, "impact": 1.0,
    "riser": 1.5, "ding": 0.8, "swipe": 0.25, "bass_drop": 1.2, "bleep": 3.0,
}


def duration(kind: str) -> float:
    _check(kind)
    return durations[kind]


def _check(kind: str) -> None:
    if kind not in durations:
        raise ValueError(f"Efect sonor necunoscut: „{kind}”. Disponibile: {', '.join(durations)}.")


# ---------- utilitare DSP ----------

def _t(dur: float) -> np.ndarray:
    return np.arange(int(round(dur * SR))) / SR


def _rng(kind: str) -> np.random.Generator:
    return np.random.default_rng(SEED + sum(map(ord, kind)))


def _phase(freq: np.ndarray) -> np.ndarray:
    """Faza integrată pentru o frecvență variabilă în timp (Hz per eșantion)."""
    return 2 * np.pi * np.cumsum(freq) / SR


def _svf(x: np.ndarray, fc: np.ndarray | float, q: float = 1.0, mode: str = "bp") -> np.ndarray:
    """Filtru state-variable (Chamberlin, varianta stabilă cu 2 iterații) cu frecvență variabilă."""
    fc = np.broadcast_to(np.asarray(fc, float), x.shape)
    # f = 2 sin(pi fc / (2 sr)) la oversampling 2x -> stabil până aproape de Nyquist
    f = 2 * np.sin(np.pi * np.clip(fc, 10, SR * 0.24) / (2 * SR))
    damp = 1.0 / q
    low = band = 0.0
    out = np.empty_like(x)
    lo_i = mode == "lp"
    hi_i = mode == "hp"
    for i in range(len(x)):
        fi = f[i]
        xi = x[i]
        for _ in range(2):
            low += fi * band
            high = xi - low - damp * band
            band += fi * high
        out[i] = low if lo_i else (high if hi_i else band)
    return out


def _onepole_lp(x: np.ndarray, fc: float) -> np.ndarray:
    a = np.exp(-2 * np.pi * fc / SR)
    out = np.empty_like(x)
    y = 0.0
    for i in range(len(x)):
        y = (1 - a) * x[i] + a * y
        out[i] = y
    return out


def _fft_band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Trece-bandă prin FFT cu margini netede (cosinus) ca să nu sune metalic."""
    spec = np.fft.rfft(x)
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    w = np.ones_like(fr)
    if lo > 0:
        w *= np.clip((fr - lo * 0.7) / (lo * 0.3), 0, 1)
    if hi < SR / 2:
        w *= np.clip((hi * 1.3 - fr) / (hi * 0.3), 0, 1)
    return np.fft.irfft(spec * w, len(x))


def _fade(x: np.ndarray, fin: float = 0.002, fout: float = 0.005) -> np.ndarray:
    n_in, n_out = max(1, int(fin * SR)), max(1, int(fout * SR))
    x = x.copy()
    x[:n_in] *= np.linspace(0, 1, n_in)
    x[-n_out:] *= np.linspace(1, 0, n_out)
    return x


def _stereo(x: np.ndarray, pan: np.ndarray | float = 0.0) -> np.ndarray:
    """pan în -1..1 (constant-power)."""
    pan = np.broadcast_to(np.asarray(pan, float), x.shape)
    ang = (pan + 1) * np.pi / 4
    return np.stack([x * np.cos(ang), x * np.sin(ang)], axis=1) * np.sqrt(2)


def _widen(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    return np.stack([left, right], axis=1)


# ---------- efectele ----------

def _whoosh(rng):
    t = _t(durations["whoosh"])
    u = t / t[-1]
    noise = rng.standard_normal(len(t))
    # centrul urcă spre mijloc apoi coboară (efect Doppler)
    fc = 350 + 2600 * np.sin(np.pi * u) ** 1.5
    x = _svf(noise, fc, q=2.2) + 0.35 * _svf(noise, fc * 0.5, q=1.2, mode="lp")
    env = np.exp(-((u - 0.5) / 0.2) ** 2)
    x = _fade(x * env, 0.01, 0.03)
    return _stereo(x, 0.6 * np.sin(np.pi * (u - 0.5)))   # trece de la stânga la dreapta


def _pop(rng):
    t = _t(durations["pop"])
    freq = 300 + 600 * np.exp(-t / 0.018)
    x = np.sin(_phase(freq)) * np.exp(-t / 0.035)
    click = rng.standard_normal(len(t)) * np.exp(-t / 0.0015) * 0.5
    x = _fade(x + _fft_band(click, 1500, 9000), 0.0005, 0.01)
    return _stereo(x)


def _click(rng):
    t = _t(durations["click"])
    noise = rng.standard_normal(len(t))
    x = _fft_band(noise, 1800, 7000) * np.exp(-t / 0.003)
    x += 0.6 * np.sin(2 * np.pi * 2200 * t) * np.exp(-t / 0.004)
    return _stereo(_fade(x, 0.0002, 0.004))


def _impact(rng):
    t = _t(durations["impact"])
    freq = 45 + 45 * np.exp(-t / 0.06)
    boom = np.sin(_phase(freq)) * np.exp(-t / 0.28)
    sub = 0.4 * np.sin(_phase(freq * 0.5)) * np.exp(-t / 0.4)
    burst = rng.standard_normal(len(t)) * np.exp(-t / 0.02)
    burst = _onepole_lp(burst, 900) * 1.8
    x = _fade(boom + sub + burst, 0.0005, 0.08)
    return _stereo(x)


def _riser(rng):
    t = _t(durations["riser"])
    u = t / t[-1]
    freq = 180 * (2 ** (3 * u))                      # 3 octave în sus
    ph = _phase(freq)
    saw = 2 * ((ph / (2 * np.pi)) % 1.0) - 1
    saw = _onepole_lp(saw, 4000)
    tone = 0.5 * saw + 0.5 * np.sin(ph)
    nl, nr = rng.standard_normal(len(t)), rng.standard_normal(len(t))
    fc = 400 + 7000 * u ** 2
    noise_l, noise_r = _svf(nl, fc, q=1.5), _svf(nr, fc, q=1.5)
    env = u ** 2.2
    left = (0.55 * tone + 0.8 * noise_l) * env
    right = (0.55 * tone + 0.8 * noise_r) * env
    # se termină brusc: doar 3 ms de fade ca să nu pocnească
    return _widen(_fade(left, 0.005, 0.003), _fade(right, 0.005, 0.003))


def _ding(rng):
    t = _t(durations["ding"])
    f0 = 1320.0
    partials = [(1.0, 1.0, 0.5), (2.76, 0.45, 0.25), (5.40, 0.25, 0.12), (8.93, 0.12, 0.07), (0.5, 0.2, 0.6)]
    x = np.zeros_like(t)
    for ratio, amp, tau in partials:
        x += amp * np.sin(2 * np.pi * f0 * ratio * t + rng.uniform(0, 2 * np.pi)) * np.exp(-t / tau)
    strike = rng.standard_normal(len(t)) * np.exp(-t / 0.001) * 0.2
    x = _fade(x + strike, 0.0005, 0.02)
    # ușoară diferență L/R: al doilea canal întârziat 0.4 ms
    d = int(0.0004 * SR)
    return _widen(x, np.concatenate([np.zeros(d), x[:-d]]))


def _swipe(rng):
    t = _t(durations["swipe"])
    u = t / t[-1]
    noise = rng.standard_normal(len(t))
    fc = 1500 + 7500 * u
    x = _svf(noise, fc, q=0.9, mode="hp")
    x = _svf(x, fc * 1.4, q=1.4)
    env = np.sin(np.pi * u) ** 0.8 * (0.4 + 0.6 * u)
    x = _fade(x * env, 0.003, 0.02)
    return _stereo(x, -0.5 + u)


def _bass_drop(rng):
    t = _t(durations["bass_drop"])
    freq = 35 + 85 * np.exp(-t / 0.3)               # 120 -> ~35 Hz
    x = np.sin(_phase(freq)) * np.exp(-t / 0.55)
    x += 0.15 * np.sin(_phase(freq * 2)) * np.exp(-t / 0.3)  # armonică pt. difuzoare mici
    return _stereo(_fade(x, 0.003, 0.1))


def _bleep(rng):
    # ton continuu, tăiat la randare cât cuvântul (Sfx.dur); vârful la -3 dBFS ca restul
    return _stereo(_fade(np.sin(2 * np.pi * 1000 * _t(durations["bleep"])), 0.004, 0.004))


_SYNTH = {
    "whoosh": _whoosh, "pop": _pop, "click": _click, "impact": _impact,
    "riser": _riser, "ding": _ding, "swipe": _swipe, "bass_drop": _bass_drop, "bleep": _bleep,
}


def synth(kind: str) -> np.ndarray:
    """Efectul ca float32 (n, 2) la 48 kHz, cu vârful la -3 dBFS."""
    _check(kind)
    x = np.asarray(_SYNTH[kind](_rng(kind)), dtype=np.float64)
    peak = float(np.max(np.abs(x))) or 1.0
    x *= 10 ** (PEAK_DB / 20) / peak
    return x.astype(np.float32)


def write_wav(path: Path | str, x: np.ndarray, sr: int = SR) -> None:
    path = Path(path)
    pcm = (np.clip(x, -1, 1) * 32767).round().astype("<i2")
    tmp = path.with_suffix(".tmp.wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(pcm.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    tmp.replace(path)


def sfx_path(kind: str) -> Path:
    """Fișierul WAV al efectului (generat la prima cerere, apoi din cache)."""
    _check(kind)
    from .project import home

    d = home() / ".sfx"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{kind}.wav"
    if not p.exists() or p.stat().st_size < 100:
        write_wav(p, synth(kind))
    return p
