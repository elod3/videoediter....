"""Urmărirea unui punct în video (flux optic Lucas-Kanade, OpenCV), ca un bloc de motion să stea lipit de un obiect.

Se urmăresc câteva puncte bune din jurul punctului ales (colțuri Shi-Tomasi într-o fereastră), fiecare verificat
înainte-înapoi: un punct care, urmărit înapoi, nu se întoarce unde a plecat, e aruncat. Mișcarea obiectului e
mediana punctelor rămase. Calea se netezește ușor (fără tremur) și se oprește singură dacă obiectul se pierde.
"""
from __future__ import annotations

import numpy as np


def track(path: str, src_w: int, src_h: int, t0: float, x: float, y: float, duration: float, fps: float = 15.0,
          width: int = 640, box: float = 0.07) -> list[tuple[float, float, float]]:
    """[(secunde de la t0, x, y)] normalizat 0..1 în cadrul sursei. Se oprește mai devreme dacă obiectul se pierde."""
    import cv2

    from .faces import sample_frames

    frames = sample_frames(path, src_w, src_h, fps=fps, width=width, start=t0, end=t0 + duration)
    first = next(frames, None)
    if first is None:
        raise ValueError("nu pot citi cadre la momentul ăla")
    _, prev = first
    g0 = cv2.cvtColor(prev, cv2.COLOR_BGR2GRAY)
    H, W = g0.shape
    cx, cy = x * W, y * H
    r = max(8, int(box * max(W, H)))
    mask = np.zeros_like(g0)
    cv2.rectangle(mask, (int(cx - r), int(cy - r)), (int(cx + r), int(cy + r)), 255, -1)
    pts = cv2.goodFeaturesToTrack(g0, maxCorners=40, qualityLevel=0.01, minDistance=3, mask=mask)
    if pts is None or len(pts) < 3:
        raise ValueError("zona aleasă n-are destule detalii de urmărit (alege un punct cu contrast: margine, logo, față)")
    lk = dict(winSize=(21, 21), maxLevel=3, criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
    out = [(0.0, x, y)]
    i = 0
    for _, frame in frames:
        i += 1
        g1 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        nxt, st, _ = cv2.calcOpticalFlowPyrLK(g0, g1, pts, None, **lk)
        back, st2, _ = cv2.calcOpticalFlowPyrLK(g1, g0, nxt, None, **lk)
        fb = np.linalg.norm((pts - back).reshape(-1, 2), axis=1)
        good = (st.reshape(-1) == 1) & (st2.reshape(-1) == 1) & (fb < 1.5)
        if good.sum() < 3:
            break  # obiectul s-a pierdut (ieșit din cadru, acoperit, tăietură)
        d = np.median((nxt - pts).reshape(-1, 2)[good], axis=0)
        cx, cy = cx + d[0], cy + d[1]
        if not (0 <= cx < W and 0 <= cy < H):
            break
        pts = nxt[good].reshape(-1, 1, 2)
        if len(pts) < 8:  # reîmprospătăm punctele din jurul poziției curente
            mask[:] = 0
            cv2.rectangle(mask, (int(cx - r), int(cy - r)), (int(cx + r), int(cy + r)), 255, -1)
            fresh = cv2.goodFeaturesToTrack(g1, maxCorners=40, qualityLevel=0.01, minDistance=3, mask=mask)
            if fresh is not None:
                pts = np.vstack([pts, fresh]).astype(np.float32)
        g0 = g1
        out.append((round(i / fps, 4), cx / W, cy / H))
    return smooth(out)


def smooth(path: list[tuple[float, float, float]], k: int = 2) -> list[tuple[float, float, float]]:
    """Medie mobilă mică pe x/y (scoate tremurul sub-pixel, păstrează mișcarea)."""
    if len(path) < 3:
        return path
    t = [p[0] for p in path]
    xs = np.array([p[1] for p in path])
    ys = np.array([p[2] for p in path])
    pad = lambda a: np.concatenate([[a[0]] * k, a, [a[-1]] * k])  # noqa: E731
    ker = np.ones(2 * k + 1) / (2 * k + 1)
    xs, ys = np.convolve(pad(xs), ker, "valid"), np.convolve(pad(ys), ker, "valid")
    return [(t[i], round(float(xs[i]), 5), round(float(ys[i]), 5)) for i in range(len(t))]


def at(path: list, t: float) -> tuple[float, float]:
    """Poziția la timpul t (interpolare liniară; după final rămâne pe ultimul punct)."""
    if t <= path[0][0]:
        return path[0][1], path[0][2]
    for a, b in zip(path, path[1:]):
        if t <= b[0]:
            u = (t - a[0]) / max(b[0] - a[0], 1e-6)
            return a[1] + (b[1] - a[1]) * u, a[2] + (b[2] - a[2]) * u
    return path[-1][1], path[-1][2]
