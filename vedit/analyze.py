"""Analize deterministe (fără LLM): liniște, tăieturi de scenă, loudness, cadre negre, contact sheet.

Principiu: agentul NU se uită la video cadru cu cadru. Primește rezumate numerice
compacte + un singur contact sheet (grilă de cadre) când are nevoie de ochi.
"""
from __future__ import annotations

import json
import re

from .ff import run

Range = tuple[float, float]


def silences(path: str, noise_db: float = -35.0, min_dur: float = 0.4) -> list[Range]:
    err = run(["-i", path, "-vn", "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    out: list[Range] = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        if e is None:  # liniște până la final
            m = re.findall(r"time=(\d+):(\d+):([\d.]+)", err)
            e = int(m[-1][0]) * 3600 + int(m[-1][1]) * 60 + float(m[-1][2]) if m else s
        out.append((round(max(0.0, s), 3), round(e, 3)))
    return out


def speech_ranges(duration: float, silence: list[Range], padding: float = 0.08, min_keep: float = 0.25) -> list[Range]:
    """Inversul liniștii: intervalele de păstrat, cu puțin padding ca să nu tai silabe."""
    keep: list[Range] = []
    cur = 0.0
    for s, e in silence:
        if s > cur:
            keep.append((cur, s))
        cur = max(cur, e)
    if cur < duration:
        keep.append((cur, duration))
    padded = [(max(0.0, a - padding), min(duration, b + padding)) for a, b in keep]
    merged: list[Range] = []
    for a, b in padded:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return [(round(a, 3), round(b, 3)) for a, b in merged if b - a >= min_keep]


def scenes(path: str, threshold: float = 0.3) -> list[float]:
    err = run(["-i", path, "-an", "-vf", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]).stderr
    return [round(float(t), 3) for t in re.findall(r"pts_time:([\d.]+)", err)]


def black_frames(path: str, min_dur: float = 0.1) -> list[Range]:
    err = run(["-i", path, "-an", "-vf", f"blackdetect=d={min_dur}:pix_th=0.10", "-f", "null", "-"]).stderr
    return [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", err)]


def loudness(path: str) -> dict:
    """Integrated loudness (LUFS), true peak, LRA — măsurat cu loudnorm."""
    err = run(["-i", path, "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"]).stderr
    blob = err[err.rfind("{"): err.rfind("}") + 1]
    d = json.loads(blob)
    return {
        "lufs": float(d["input_i"]),
        "true_peak_db": float(d["input_tp"]),
        "lra": float(d["input_lra"]),
    }


def contact_sheet(path: str, out_png: str, duration: float, cols: int = 4, rows: int = 4,
                  start: float = 0.0, end: float | None = None, thumb_w: int = 320) -> list[float]:
    """O singură imagine cu cols*rows cadre egal distanțate. Returnează timestamp-ul fiecărei celule.

    Asta e "ochiul" agentului: 1 imagine ≈ 1 apel vision, în loc de 16.
    """
    end = duration if end is None else min(end, duration)
    n = cols * rows
    span = max(end - start, 0.01)
    step = span / n
    times = [round(start + step * (i + 0.5), 2) for i in range(n)]
    run([
        "-y", "-ss", f"{start:.3f}", "-t", f"{span:.3f}", "-i", path,
        "-vf", f"fps={n / span:.6f},scale={thumb_w}:-2,tile={cols}x{rows}:padding=4:color=black",
        "-frames:v", "1", out_png,
    ])
    return times


def frame_at(path: str, t: float, out_png: str, width: int = 640) -> None:
    run(["-y", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1", "-vf", f"scale={width}:-2", out_png])
