"""Planificarea încadrării automate: fețe detectate -> segmente cu (cx, cy) stabile.

Stilul e cel de "cameraman virtual" cu tăieturi, nu panoramare continuă: fiecare segment are
încadrare fixă, iar când subiectul se mută semnificativ (sau se schimbă scena) clipul e împărțit.
Asta arată natural pe jump-cut-uri și nu produce "tremurat".
"""
from __future__ import annotations

from statistics import median
from typing import Callable

from pydantic import BaseModel

from .faces import Face

HEADROOM = 0.10  # fața stă ~10% din înălțimea crop-ului deasupra centrului


class Segment(BaseModel):
    t0: float
    t1: float
    cx: float = 0.5
    cy: float = 0.5
    faces: int = 0
    flag: str = ""  # "" | "wide" (fețele nu încap împreună) | "no_face"


def crop_fraction(src_w: int, src_h: int, out_w: int, out_h: int, zoom: float = 1.0) -> tuple[float, float]:
    """Ce fracție din lățimea/înălțimea sursei acoperă crop-ul (aceeași logică ca render.crop_box)."""
    ar = out_w / out_h
    if src_w / src_h > ar:
        cw, ch = src_h * ar, src_h
    else:
        cw, ch = src_w, src_w / ar
    z = max(zoom, 1.0)
    return min(cw / z / src_w, 1.0), min(ch / z / src_h, 1.0)


def target(faces: list[Face], cwf: float, chf: float) -> tuple[float, float, int, bool] | None:
    """Unde ar trebui centrat crop-ul pentru un cadru: (cx, cy, nr_fețe, wide)."""
    if not faces:
        return None
    big = max(faces, key=lambda f: f.area)
    group = [f for f in faces if f.area >= 0.35 * big.area]  # ignoră fețele mici din fundal
    left, right = min(f.x for f in group), max(f.x + f.w for f in group)
    if right - left <= cwf * 0.9:
        cx, fcy, wide = (left + right) / 2, median(f.cy for f in group), False
    else:
        cx, fcy, wide = big.cx, big.cy, True
    return cx, fcy + chf * HEADROOM, len(group), wide


def plan(samples: list[tuple[float, list[Face]]], t0: float, t1: float, cwf: float, chf: float, *,
         split: bool = True, shift: float = 0.25, persist: int = 2, min_seg: float = 1.0,
         scene_cuts: list[float] | None = None,
         refine: Callable[[float, float, float, float], float] | None = None) -> list[Segment]:
    """refine(prev_t, cur_t, cx_vechi, cx_nou) -> momentul exact al schimbării (caută cadre mai dese)."""
    pts = [(t, target(fs, cwf, chf)) for t, fs in samples if t0 - 1e-6 <= t < t1]
    if not any(p for _, p in pts):
        return [Segment(t0=t0, t1=t1, flag="no_face")]
    # completează cadrele fără față cu vecinul cel mai apropiat (înainte, apoi înapoi)
    detected = [p is not None for _, p in pts]
    last = None
    filled = []
    for t, p in pts:
        last = p or last
        filled.append((t, last))
    first = next(p for _, p in filled if p)
    filled = [(t, p or first) for t, p in filled]

    cx = [p[0] for _, p in filled]
    thr = shift * cwf
    groups: list[list[int]] = [[0]]
    for j in range(1, len(filled)):
        anchor = median(cx[k] for k in groups[-1])
        run = range(j, min(len(filled), j + persist))
        if split and len(run) == persist and all(abs(cx[k] - anchor) > thr for k in run):
            groups.append([j])
        else:
            groups[-1].append(j)

    # limite de segment: la tăietura de scenă dacă există una între eșantioane, altfel la mijloc
    bounds = [t0]
    for gi, g in enumerate(groups[1:], 1):
        prev_t, cur_t = filled[g[0] - 1][0], filled[g[0]][0]
        cuts = [c for c in (scene_cuts or []) if prev_t < c <= cur_t]
        if cuts:
            b = cuts[0]
        elif refine:
            b = refine(prev_t, cur_t, median(cx[k] for k in groups[gi - 1]), median(cx[k] for k in g))
        else:
            b = (prev_t + cur_t) / 2
        bounds.append(round(b, 3))
    bounds.append(t1)

    segs = []
    for i, g in enumerate(groups):
        ps = [filled[k][1] for k in g]
        segs.append(Segment(
            t0=bounds[i], t1=bounds[i + 1],
            cx=round(median(p[0] for p in ps), 3), cy=round(median(p[1] for p in ps), 3),
            faces=max(p[2] for p in ps),
            flag="no_face" if not any(detected[k] for k in g)
            else "wide" if sum(p[3] for p in ps) * 2 > len(ps) else "",
        ))
    # segmentele prea scurte arată ca un glitch => lipește-le de vecin
    merged: list[Segment] = []
    for s in segs:
        if merged and (s.t1 - s.t0 < min_seg or merged[-1].t1 - merged[-1].t0 < min_seg):
            keep = merged[-1] if merged[-1].t1 - merged[-1].t0 >= s.t1 - s.t0 else s
            merged[-1] = keep.model_copy(update={"t0": merged[-1].t0, "t1": s.t1})
        else:
            merged.append(s)
    return merged
