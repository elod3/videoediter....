"""Detecția beat-ului din muzică: tempo (BPM), beat-uri, downbeat-uri. Doar numpy + ffmpeg.

Metoda (clasică, ca în librosa): anvelopa de onset din fluxul spectral → tempo prin autocorelație
cu o preferință ușoară pentru ~120 BPM → beat-uri prin programare dinamică (Ellis, 2007),
care urmează tempo-ul dar se lipește de lovituri reale.
"""
from __future__ import annotations

import subprocess

from pydantic import BaseModel

from .ff import ffmpeg_bin

SR = 22050
HOP = 512


class Beats(BaseModel):
    bpm: float
    beats: list[float]
    downbeats: list[float]
    confidence: float  # 0..1: cât de clar e pulsul (autocorelația la tempo ales)

    def summary(self, max_items: int = 16) -> str:
        more = f" … (+{len(self.beats) - max_items})" if len(self.beats) > max_items else ""
        return (f"{self.bpm:.1f} BPM · {len(self.beats)} beat-uri · încredere {self.confidence:.0%}\n"
                f"beat-uri: {', '.join(f'{b:.2f}' for b in self.beats[:max_items])}{more}\n"
                f"downbeat-uri (începutul măsurii): {', '.join(f'{b:.2f}' for b in self.downbeats[:8])}")


def load_mono(path: str, sr: int = SR, start: float = 0.0, duration: float | None = None):
    import numpy as np

    args = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{start:.3f}"]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    raw = subprocess.run([*args, "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype("float64")


def mel_filterbank(n_fft: int, sr: int = SR, n_mels: int = 64, fmax: float = 8000):
    import numpy as np

    def hz2mel(f):
        return 2595 * np.log10(1 + f / 700)

    def mel2hz(m):
        return 700 * (10 ** (m / 2595) - 1)

    pts = mel2hz(np.linspace(hz2mel(30), hz2mel(fmax), n_mels + 2))
    bins = np.fft.rfftfreq(n_fft, 1 / sr)
    fb = np.zeros((n_mels, len(bins)))
    for i in range(n_mels):
        lo, c, hi = pts[i], pts[i + 1], pts[i + 2]
        fb[i] = np.clip(np.minimum((bins - lo) / (c - lo), (hi - bins) / (hi - c)), 0, None)
    return fb


LOW_BANDS = 3  # primele benzi mel (~30-120 Hz): kick-ul, fără corpul snare-ului


def onset_envelope(y, n_fft: int = 2048, hop: int = HOP, low: bool = False):
    """Flux pe benzi mel în dB (media pe benzi): kick-ul și snare-ul cântăresc cât trebuie, hi-hat-ul nu domină."""
    import numpy as np

    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    n = 1 + (len(y) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    power = np.abs(np.fft.rfft(y[idx] * np.hanning(n_fft), axis=1)) ** 2
    mel_db = 10 * np.log10(power @ mel_filterbank(n_fft).T + 1e-10)
    mel_db = np.maximum(mel_db, mel_db.max() - 80)
    diff = np.maximum(0, np.diff(mel_db, axis=0))
    # cadrul i acoperă [i*hop, i*hop+n_fft); onset-ul e în centrul ferestrei => deplasare cu n_fft/2
    shift = int(round(n_fft / 2 / hop)) + 1
    pad = np.zeros((1 + shift, diff.shape[1]))
    diff = np.concatenate([pad, diff])[:n]
    if low:
        return diff[:, :LOW_BANDS].mean(1)
    flux = diff.mean(1)
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # scoate trendul lent
    flux = np.maximum(flux, 0)
    return flux / (flux.std() + 1e-9)


def estimate_tempo(env, fps: float, lo: float = 60, hi: float = 200) -> tuple[float, float]:
    import numpy as np

    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac /= ac[0] + 1e-9
    lags = np.arange(len(ac))
    bpm = 60 * fps / np.maximum(lags, 1)
    ok = (bpm >= lo) & (bpm <= hi)
    prior = np.exp(-0.5 * (np.log2(bpm / 120) / 1.0) ** 2)  # preferință blândă pentru ~120 BPM
    score = np.where(ok, ac * prior, -np.inf)
    lag = int(np.argmax(score))
    # erori de octavă: dacă pulsul de două ori mai rapid e aproape la fel de clar, el e beat-ul
    # (kick+snare se repetă la 2 beat-uri și trage autocorelația spre jumătate de tempo)
    half = int(round(lag / 2))
    if half >= 2 and 60 * fps / half <= hi and ac[half - 1: half + 2].max() >= 0.5 * ac[lag]:
        lag = half - 1 + int(np.argmax(ac[half - 1: half + 2]))
    if 1 <= lag < len(ac) - 1:  # interpolare parabolică pentru tempo fracționar
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        denom = a - 2 * b + c
        lag_f = lag + (0.5 * (a - c) / denom if denom else 0)
    else:
        lag_f = lag
    return float(60 * fps / lag_f), float(max(0.0, ac[lag]))


def track_beats(env, fps: float, bpm: float, tightness: float = 100.0):
    import numpy as np

    period = 60 * fps / bpm
    n = len(env)
    score = env.copy()
    back = -np.ones(n, dtype=int)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    for t in range(lo, n):
        prev = np.arange(max(0, t - hi), t - lo + 1)
        if len(prev) == 0:
            continue
        pen = -tightness * np.log((t - prev) / period) ** 2
        cand = score[prev] + pen
        k = int(np.argmax(cand))
        if cand[k] > 0:          # continuă un lanț de beat-uri
            score[t] = env[t] + cand[k]
            back[t] = prev[k]
        # altfel t poate ÎNCEPE un lanț (primul beat din piesă nu are predecesor)
    # pornim din cel mai bun punct din ultima perioadă și mergem înapoi
    tail = np.arange(max(0, n - int(period) - 1), n)
    t = int(tail[np.argmax(score[tail])])
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    beats = np.array(beats[::-1])
    if not len(beats):
        return beats
    # aruncă beat-urile din liniștea de la început și de la final (acolo nu există lovituri reale)
    local = np.array([env[max(0, b - 2): b + 3].max() for b in beats])
    strong = np.flatnonzero(local > 0.25 * np.median(local))
    return beats[strong[0]: strong[-1] + 1] if len(strong) else beats


def detect(path: str, start: float = 0.0, duration: float | None = None) -> Beats:
    import numpy as np

    y = load_mono(path, start=start, duration=duration)
    if len(y) < SR:
        raise ValueError("audio prea scurt pentru detecția beat-ului (< 1 s)")
    fps = SR / HOP
    env = onset_envelope(y)
    bpm, conf = estimate_tempo(env, fps)
    frames = track_beats(env, fps, bpm)
    times = frames / fps + start
    # downbeat: faza (din 4) cu cel mai puternic kick (energie joasă), nu cu cel mai tare snare
    if len(frames) >= 8:
        low = onset_envelope(y, low=True)
        near = np.array([low[max(0, f - 2): f + 3].max() for f in frames])
        phase = int(np.argmax([near[p::4].mean() for p in range(4)]))
    else:
        phase = 0
    # tempo final: panta beat-urilor urmărite (regresie liniară, fără cuantizarea pe cadre)
    if len(times) > 4:
        slope = np.polyfit(np.arange(len(times)), times, 1)[0]
        bpm = float(60 / slope)
    return Beats(bpm=round(bpm, 2), beats=[round(float(t), 3) for t in times],
                 downbeats=[round(float(t), 3) for t in times[phase::4]], confidence=round(conf, 3))
