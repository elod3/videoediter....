"""Multicam: sincronizarea camerelor după sunet și planul de schimbare a unghiurilor.

- `find_offset`: decalajul dintre două înregistrări ale aceluiași moment (corelație pe anvelopa de
  onset la 100 Hz, apoi rafinare GCC-PHAT pe audio brut pentru precizie de milisecunde).
- `plan_switches`: vorbitor activ -> unghiul lui, cu plan larg la suprapuneri / liniște.
- `rotate_switches`: alternare simplă a unghiurilor, cu tăieturi lipite de granițe (capete de cuvânt).
- `mic_segments`: cine vorbește, după microfonul care aude mai tare (fiecare cameră are microfonul ei).
"""
from __future__ import annotations

import numpy as np

from .beats import load_mono

FPS = 100          # rata anvelopei (cadre / s)
_LOAD_EXTRA = 120.0  # secunde de audio dincolo de max_offset folosite la sincronizare


# ---------------------------------------------------------------- sincronizare

def _envelope(y: np.ndarray, sr: int) -> np.ndarray:
    """Anvelopa de onset: diferența pozitivă a log-energiei pe cadre de 10 ms, fără trend lent."""
    hop = sr // FPS
    n = len(y) // hop
    if n < 4:
        return np.zeros(max(n, 1))
    # pre-emfază: scoate zumzetul de joasă frecvență care diferă între microfoane
    y = np.append(y[0], y[1:] - 0.97 * y[:-1])
    frames = y[: n * hop].reshape(n, hop)
    e = 10 * np.log10(np.mean(frames ** 2, axis=1) + 1e-10)
    # podeaua de zgomot (a microfonului mai slab / mai zgomotos) nu trebuie să producă "onset-uri"
    e = np.convolve(e, np.ones(3) / 3, mode="same")
    e = np.maximum(e, max(e.max() - 60, np.percentile(e, 15) + 3))
    d = np.maximum(0.0, np.diff(e, prepend=e[0]))
    k = FPS // 2
    trend = np.convolve(d, np.ones(2 * k + 1) / (2 * k + 1), mode="same")
    d = np.maximum(0.0, d - trend)
    s = d.std()
    return (d - d.mean()) / s if s > 0 else d * 0


def _xcorr(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, int]:
    """c[k + zero] = sum a[n] b[n + k] pentru k în [-(len(a)-1), len(b)-1]."""
    n = len(a) + len(b) - 1
    size = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.conj(np.fft.rfft(a, size)) * np.fft.rfft(b, size), size)
    # lag-urile negative sunt la coada vectorului circular
    c = np.concatenate([c[size - (len(a) - 1):], c[: len(b)]]) if len(a) > 1 else c[: len(b)]
    return c, len(a) - 1


def _parabolic(c: np.ndarray, i: int) -> float:
    if 0 < i < len(c) - 1:
        y0, y1, y2 = c[i - 1], c[i], c[i + 1]
        den = y0 - 2 * y1 + y2
        if den != 0:
            return float(i + 0.5 * (y0 - y2) / den)
    return float(i)


def _gcc_phat(a: np.ndarray, b: np.ndarray, sr: int, center: float, radius: float) -> tuple[float, float] | None:
    """Rafinează lag-ul (în s) în jurul `center` ± `radius` prin GCC-PHAT. Întoarce (lag, claritate)."""
    n = len(a) + len(b)
    size = 1 << (n - 1).bit_length()
    A, B = np.fft.rfft(a, size), np.fft.rfft(b, size)
    cross = np.conj(A) * B
    mag = np.abs(cross)
    cross = cross / (mag + 1e-3 * mag.max() + 1e-20)
    c = np.fft.irfft(cross, size)
    lo, hi = int(np.floor((center - radius) * sr)), int(np.ceil((center + radius) * sr))
    lags = np.arange(lo, hi + 1)
    vals = c[lags % size]
    if not len(vals):
        return None
    i = int(np.argmax(vals))
    frac = _parabolic(vals, i) - i
    sharp = float(vals[i] / (np.abs(c).mean() * 10 + 1e-20))
    return (lags[i] + frac) / sr, sharp


def find_offset(ref_path: str, other_path: str, max_offset: float = 60.0, sr: int = 8000) -> tuple[float, float]:
    """Decalajul `offset = t_other - t_ref` pentru același moment + încrederea (0..1).

    Momentul de la secunda t din `ref` e la secunda t + offset în `other`.
    """
    load_dur = max_offset + _LOAD_EXTRA
    ya = load_mono(ref_path, sr=sr, duration=load_dur)
    yb = load_mono(other_path, sr=sr, duration=load_dur)
    if len(ya) < sr or len(yb) < sr:
        raise ValueError("Audio prea scurt pentru sincronizare (minimum 1 s în fiecare fișier).")

    # 1) grosier: anvelope de onset, lag-uri limitate la ±max_offset
    ea, eb = _envelope(ya, sr), _envelope(yb, sr)
    c, zero = _xcorr(ea, eb)
    lim = int(max_offset * FPS)
    lo, hi = max(0, zero - lim), min(len(c), zero + lim + 1)
    win = c[lo:hi]
    if not len(win) or not np.any(win > 0):
        return 0.0, 0.0
    i = int(np.argmax(win))
    peak = float(win[i])
    # al doilea vârf, în afara a ±0.15 s de cel principal
    mask = np.ones(len(win), bool)
    mask[max(0, i - 15): i + 16] = False
    second = float(win[mask].max()) if mask.any() else 0.0
    coarse = (lo + i - zero) / FPS
    confidence = float(np.clip(1.0 - max(second, 0.0) / peak, 0.0, 1.0)) if peak > 0 else 0.0

    # 2) fin: GCC-PHAT pe audio brut, pe o fereastră din zona suprapusă
    offset = coarse
    t0 = max(0.0, -coarse)                              # prima secundă din ref prezentă și în other
    t1 = min(len(ya) / sr, len(yb) / sr - coarse)
    if t1 - t0 >= 1.0:
        w = min(30.0, t1 - t0)
        s = t0 + (t1 - t0 - w) / 2
        margin = 0.15
        a = ya[int(s * sr): int((s + w) * sr)]
        bs = max(0, int((s + coarse - margin) * sr))
        b = yb[bs: int((s + coarse + w + margin) * sr)]
        base = bs / sr - s                               # lag-ul ferestrelor, în s, pentru indexul 0
        r = _gcc_phat(a - a.mean(), b - b.mean(), sr, coarse - base, 0.1)
        if r is not None:
            offset = r[0] + base
    return round(float(offset), 4), round(confidence, 3)


# ---------------------------------------------------------------- planul de unghiuri

Range = tuple[float, float, str]


def _merge_same(ranges: list[list]) -> list[list]:
    out: list[list] = []
    for r in ranges:
        if out and out[-1][2] == r[2]:
            out[-1][1] = r[1]
        elif r[1] > r[0]:
            out.append(list(r))
    return out


def _enforce_min(ranges: list[list], min_shot: float) -> list[list]:
    ranges = _merge_same(ranges)
    while len(ranges) > 1:
        lens = [r[1] - r[0] for r in ranges]
        i = int(np.argmin(lens))
        if lens[i] >= min_shot - 1e-9:
            break
        prev = ranges[i - 1] if i > 0 else None
        nxt = ranges[i + 1] if i + 1 < len(ranges) else None
        if prev and nxt and prev[2] == nxt[2]:
            prev[1] = nxt[1]
            del ranges[i: i + 2]
            continue
        # îl înghite vecinul mai lung (la egalitate, cel dinainte: plan continuat)
        if nxt is None or (prev is not None and prev[1] - prev[0] >= nxt[1] - nxt[0]):
            prev[1] = ranges[i][1]
        else:
            nxt[0] = ranges[i][0]
        del ranges[i]
        ranges = _merge_same(ranges)
    return ranges


def _finish(ranges: list[list], duration: float) -> list[Range]:
    ranges[0][0], ranges[-1][1] = 0.0, duration
    for a, b in zip(ranges, ranges[1:]):
        b[0] = a[1]
    return [(round(r[0], 3), round(r[1], 3), r[2]) for r in ranges]


def plan_switches(segments: list[tuple[float, float, str]], mapping: dict[str, str], duration: float,
                  wide: str | None = None, min_shot: float = 1.5, wide_every: float = 0.0) -> list[Range]:
    """Intervale contigue [0, duration] cu unghiul (id de asset) de arătat în fiecare."""
    if duration <= 0:
        return []
    if not mapping and not wide:
        raise ValueError("Trebuie dat cel puțin un unghi: mapping vorbitor -> unghi sau un plan larg (wide).")
    segs = [(max(0.0, s), min(duration, e), spk) for s, e, spk in segments
            if spk in mapping and min(duration, e) > max(0.0, s)]
    cuts = sorted({0.0, duration, *(s for s, _, _ in segs), *(e for _, e, _ in segs)})

    raw: list[list] = []
    for a, b in zip(cuts, cuts[1:]):
        mid = (a + b) / 2
        angles = {mapping[spk] for s, e, spk in segs if s <= mid < e}
        raw.append([a, b, angles.pop() if len(angles) == 1 else wide])

    # golurile fără plan larg: continuă unghiul anterior (la început, primul unghi cunoscut)
    first = next((r[2] for r in raw if r[2] is not None), None) or next(iter(mapping.values()))
    prev = first
    for r in raw:
        if r[2] is None:
            r[2] = prev
        prev = r[2]
    ranges = _merge_same(raw)

    if wide and wide_every > 0:
        wide_len = 2.0
        out: list[list] = []
        last_wide = 0.0
        for r in ranges:
            if r[2] == wide:
                last_wide = r[1]
                out.append(r)
                continue
            if r[0] - last_wide >= wide_every and r[1] - r[0] >= wide_len + min_shot:
                out.append([r[0], r[0] + wide_len, wide])
                out.append([r[0] + wide_len, r[1], r[2]])
                last_wide = r[0] + wide_len
            else:
                out.append(r)
        ranges = out

    return _finish(_enforce_min(ranges, min_shot), duration)


def rotate_switches(duration: float, angles: list[str], every: float,
                    boundaries: list[float] | None = None) -> list[Range]:
    """Alternează unghiurile la ~`every` secunde; tăieturile se lipesc de cea mai apropiată graniță."""
    if duration <= 0:
        return []
    if not angles:
        raise ValueError("Lista de unghiuri e goală.")
    if every <= 0 or len(angles) == 1:
        return [(0.0, round(duration, 3), angles[0])]
    bnd = np.array(sorted(b for b in (boundaries or []) if 0 < b < duration))
    cuts: list[float] = []
    last = 0.0
    while True:
        target = last + every
        if target >= duration - every * 0.5:
            break
        cut = target
        if len(bnd):
            near = bnd[(np.abs(bnd - target) <= 0.4 * every) & (bnd > last + 0.3 * every)]
            if len(near):
                cut = float(near[np.argmin(np.abs(near - target))])
        cuts.append(cut)
        last = cut
    edges = [0.0, *cuts, duration]
    return [(round(a, 3), round(b, 3), angles[i % len(angles)]) for i, (a, b) in enumerate(zip(edges, edges[1:]))]


def level_db(y: np.ndarray, sr: int, rate: int = 20) -> np.ndarray:
    """Nivelul vocii (dB RMS) pe ferestre de 1/rate s, doar banda de voce (fără bas/zumzet)."""
    y = np.append(y[0], y[1:] - 0.95 * y[:-1]) if len(y) else y
    hop = sr // rate
    n = len(y) // hop
    if n < 1:
        return np.full(1, -100.0)
    e = np.mean(y[: n * hop].reshape(n, hop) ** 2, axis=1)
    e = np.convolve(e, np.ones(3) / 3, mode="same")          # ~150 ms: nu sare între silabe
    return 10 * np.log10(e + 1e-10)


def mic_segments(levels: dict[str, np.ndarray], rate: int = 20, margin: float = 4.0,
                 floor: float = 8.0, hold: float = 1.2) -> list[tuple[float, float, str]]:
    """levels: nivelul (dB) al fiecărei camere, aliniat pe timpul montajului. Un moment e al camerei care aude
    cu `margin` dB mai tare decât toate celelalte și e la cel puțin `floor` dB peste propria liniște.
    Pauzele sub `hold` s rămân pe același vorbitor (respirații); restul momentelor fără câștigător (liniște,
    vorbesc amândoi) rămân libere (plan larg sau cadrul anterior)."""
    ids = list(levels)
    n = min(len(v) for v in levels.values())
    if not ids or n == 0:
        return []
    m = np.stack([levels[i][:n] for i in ids])
    noise = np.percentile(m, 10, axis=1, keepdims=True)
    order = np.sort(m, axis=0)
    top = np.argmax(m, axis=0)
    lead = order[-1] - (order[-2] if len(ids) > 1 else noise[0])
    loud = m[top, np.arange(n)] - noise[top, 0] >= floor
    who = np.where((lead >= margin) & loud, top, -1)
    segs: list[list] = []
    for k, w in enumerate(who):
        if w < 0:
            continue
        a, b = k / rate, (k + 1) / rate
        if segs and segs[-1][2] == ids[w] and a - segs[-1][1] < hold:
            segs[-1][1] = b
        else:
            segs.append([a, b, ids[w]])
    return [(round(a, 3), round(b, 3), s) for a, b, s in segs if b - a >= 0.3]
