"""Stilul unui clip de referință, măsurat (nu ghicit), și color grading prin LUT 3D.

* profil de stil: ritmul tăieturilor, culoarea (în spațiul LAB), audio, format
* color match: transfer statistic de culoare (Reinhard, în LAB) de la referință la sursă,
  „copt” într-un LUT .cube pe care ffmpeg îl aplică la randare (`lut3d`)
* preseturi și reglaje manuale (expunere, contrast, saturație, temperatură), tot prin LUT

Doar numpy + ffmpeg. Agentul primește cifre și sfaturi, nu impresii.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel

from .ff import ffmpeg_bin

# ---------------------------------------------------------------- sRGB <-> LAB (D65)
_M = [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
_WHITE = (0.95047, 1.0, 1.08883)
_D = 6 / 29


def rgb_to_lab(rgb):
    """rgb: array (..., 3) în 0..1 (sRGB) -> LAB (L 0..100)."""
    import numpy as np

    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    xyz = c @ np.array(_M).T / np.array(_WHITE)
    f = np.where(xyz > _D ** 3, np.cbrt(xyz), xyz / (3 * _D ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_rgb(lab):
    import numpy as np

    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > _D, f ** 3, 3 * _D ** 2 * (f - 4 / 29)) * np.array(_WHITE)
    lin = xyz @ np.linalg.inv(np.array(_M)).T
    lin = np.clip(lin, 0, None)
    return np.clip(np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055), 0, 1)


# ---------------------------------------------------------------- statistici de culoare
class ColorStats(BaseModel):
    mean: list[float]      # L, a, b
    std: list[float]
    l_p5: float            # umbre
    l_p95: float           # lumini
    chroma: float          # saturație medie (sqrt(a²+b²))

    def summary(self) -> str:
        L, a, b = self.mean
        temp = "cald" if b > 8 else "rece" if b < 0 else "neutru"
        tint = " spre magenta" if a > 4 else " spre verde" if a < -3 else ""
        return (f"luminozitate {L:.0f}/100 · contrast {self.l_p95 - self.l_p5:.0f} (umbre {self.l_p5:.0f}, "
                f"lumini {self.l_p95:.0f}) · saturație {self.chroma:.0f} · {temp}{tint} (a {a:+.1f}, b {b:+.1f})")


def grab_frame(path: str, t: float, src_w: int, src_h: int, width: int = 160):
    import numpy as np

    h = max(2, int(round(width * src_h / max(src_w, 1) / 2)) * 2)
    raw = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{t:.3f}", "-i", path,
                          "-frames:v", "1", "-vf", f"scale={width}:{h}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True).stdout
    if len(raw) < width * h * 3:
        return None
    return np.frombuffer(raw[: width * h * 3], np.uint8).reshape(h, width, 3)


def color_stats(path: str, duration: float, src_w: int, src_h: int, n: int = 12,
                start: float = 0.0, end: float | None = None) -> ColorStats:
    """Statistici LAB pe n cadre egal distanțate (căutare rapidă, nu decodează tot fișierul)."""
    import numpy as np

    end = duration if end is None else min(end, duration)
    span = max(end - start, 0.04)
    frames = [grab_frame(path, start + span * (i + 0.5) / n, src_w, src_h) for i in range(n)]
    frames = [f for f in frames if f is not None]
    if not frames:
        raise ValueError("nu am putut citi cadre din video")
    lab = rgb_to_lab(np.concatenate([f.reshape(-1, 3) for f in frames]).astype("float64") / 255)
    return ColorStats(
        mean=[round(float(x), 3) for x in lab.mean(0)], std=[round(float(x), 3) for x in lab.std(0)],
        l_p5=round(float(np.percentile(lab[:, 0], 5)), 2), l_p95=round(float(np.percentile(lab[:, 0], 95)), 2),
        chroma=round(float(np.sqrt(lab[:, 1] ** 2 + lab[:, 2] ** 2).mean()), 2),
    )


# ---------------------------------------------------------------- LUT 3D
class Adjust(BaseModel):
    """Reglaje manuale, aplicate după potrivirea cu referința."""
    exposure: float = 0.0      # puncte de L (-20..20)
    contrast: float = 1.0      # 0.5..1.6, în jurul lui L=50
    saturation: float = 1.0    # 0..2
    temperature: float = 0.0   # + cald / - rece (unități b)
    tint: float = 0.0          # + magenta / - verde (unități a)
    teal_orange: float = 0.0   # 0..1: umbre spre teal, lumini/piele spre portocaliu


PRESETS: dict[str, Adjust] = {
    "cald": Adjust(temperature=7, tint=1.5),
    "rece": Adjust(temperature=-7, tint=-1),
    "contrast": Adjust(contrast=1.18, saturation=1.1),
    "desaturat": Adjust(saturation=0.72, contrast=1.05),
    "alb_negru": Adjust(saturation=0, contrast=1.15),
    "cinematic": Adjust(teal_orange=0.7, contrast=1.1, saturation=0.95),
    "luminos": Adjust(exposure=6, contrast=0.95, saturation=1.08),
}


def _transfer(lab, src: ColorStats | None, ref: ColorStats | None, strength: float, adj: Adjust):
    import numpy as np

    out = lab.copy()
    if src is not None and ref is not None:
        mu_s, mu_r = np.array(src.mean), np.array(ref.mean)
        sd_s, sd_r = np.maximum(np.array(src.std), 1e-3), np.array(ref.std)
        k = sd_r / sd_s
        k[0] = np.clip(k[0], 0.6, 1.6)          # luminanța: fără contrast extrem
        k[1:] = np.clip(k[1:], 0.0, 2.2)        # culoarea: poate ajunge la alb-negru, nu la neon
        matched = (lab - mu_s) * k + mu_r
        out = lab + strength * (matched - lab)
    L, a, b = out[..., 0], out[..., 1], out[..., 2]
    L = (L - 50) * adj.contrast + 50 + adj.exposure
    a, b = a * adj.saturation + adj.tint, b * adj.saturation + adj.temperature
    if adj.teal_orange:
        w = np.clip((L - 50) / 40, -1, 1) * adj.teal_orange   # -1 umbre .. +1 lumini
        a = a + np.where(w < 0, 5 * w, 4 * w)                  # umbre -> verde-albastru, lumini -> cald
        b = b + np.where(w < 0, 9 * w, 8 * w)
    return np.stack([np.clip(L, 0, 100), a, b], -1)


def write_lut(path: Path, src: ColorStats | None = None, ref: ColorStats | None = None, strength: float = 0.8,
              adj: Adjust | None = None, size: int = 33) -> Path:
    import numpy as np

    g = np.linspace(0, 1, size)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # .cube: R variază cel mai repede
    rgb = np.stack([r, gg, b], -1).reshape(-1, 3)
    out = lab_to_rgb(_transfer(rgb_to_lab(rgb), src, ref, max(0.0, min(strength, 1.0)), adj or Adjust()))
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(f'TITLE "vedit"\nLUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        fh.write("\n".join(f"{x:.6f} {y:.6f} {z:.6f}" for x, y, z in out))
        fh.write("\n")
    return path


# ---------------------------------------------------------------- ritm
class Rhythm(BaseModel):
    cuts: int
    cuts_per_min: float
    shot_median: float
    shot_p10: float
    shot_p90: float
    hook_cuts_3s: int

    def summary(self) -> str:
        return (f"{self.cuts_per_min:.0f} tăieturi/min · shot median {self.shot_median:.1f} s "
                f"(scurte {self.shot_p10:.1f} s, lungi {self.shot_p90:.1f} s) · {self.hook_cuts_3s} tăieturi în primele 3 s")


def rhythm_from_cuts(cut_times: list[float], duration: float) -> Rhythm:
    import numpy as np

    edges = [0.0, *sorted(t for t in cut_times if 0.05 < t < duration - 0.05), duration]
    shots = np.diff(edges)
    return Rhythm(cuts=len(edges) - 2, cuts_per_min=round((len(edges) - 2) / max(duration, 1e-3) * 60, 1),
                  shot_median=round(float(np.median(shots)), 2), shot_p10=round(float(np.percentile(shots, 10)), 2),
                  shot_p90=round(float(np.percentile(shots, 90)), 2),
                  hook_cuts_3s=sum(1 for t in edges[1:-1] if t < 3.0))


def compare(ours: dict, ref: dict) -> list[str]:
    """Sfaturi concrete: unde e montajul departe de referință și ce tool mută acul."""
    tips: list[str] = []
    ro, rr = ours.get("rhythm"), ref.get("rhythm")
    if ro and rr and rr["cuts_per_min"] > 0:
        ratio = ro["cuts_per_min"] / rr["cuts_per_min"]
        if ratio < 0.7:
            tips.append(f"ritm prea lent: {ro['cuts_per_min']:.0f} vs {rr['cuts_per_min']:.0f} tăieturi/min → "
                        f"cut_silences cu min_silence mai mic, cut_words pe umpluturi, sau punch-in alternat (auto_reframe punch_in)")
        elif ratio > 1.4:
            tips.append(f"ritm prea alert: {ro['cuts_per_min']:.0f} vs {rr['cuts_per_min']:.0f} tăieturi/min → "
                        f"min_silence mai mare sau fără punch-in")
        if rr["hook_cuts_3s"] >= 2 and ro["hook_cuts_3s"] < rr["hook_cuts_3s"] - 1:
            tips.append(f"hook: referința are {rr['hook_cuts_3s']} tăieturi în primele 3 s, tu {ro['hook_cuts_3s']} → "
                        f"deschide cu fraza cea mai tare (keep_words / clip_move) și taie mai des la început")
    co, cr = ours.get("color"), ref.get("color")
    if co and cr:
        dist = sum((x - y) ** 2 for x, y in zip(co["mean"], cr["mean"])) ** 0.5
        if dist > 6:
            tips.append(f"culoarea diferă (ΔE mediu {dist:.0f}) → color_match cu referința")
        if abs((co["l_p95"] - co["l_p5"]) - (cr["l_p95"] - cr["l_p5"])) > 12:
            tips.append("contrastul diferă mult → color_match sau color_grade(contrast=...)")
    lo, lr = ours.get("lufs"), ref.get("lufs")
    if lo is not None and lr is not None and abs(lo - lr) > 2:
        tips.append(f"volum {lo:.1f} vs {lr:.1f} LUFS → e normal dacă platforma cere -14; altfel ajustează loudness")
    return tips or ["aproape de referință pe toate măsurătorile; restul se judecă vizual (subtitrări, text, B-roll)"]
