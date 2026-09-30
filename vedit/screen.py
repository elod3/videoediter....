"""Înregistrări de ecran (tutoriale, demo-uri de aplicații): unde se întâmplă ceva și planul de zoom automat.

`activity` compară cadre succesive (gri, mici): pixelii schimbați arată cursorul, click-urile, textul tastat.
`plan_zoom` transformă activitatea în segmente: zoom pe zona activă când acțiunea stă într-un colț al ecranului,
cadru întreg la scroll / schimbare de pagină / pauze lungi. Fără ML, determinist.
"""
from __future__ import annotations

import subprocess

import numpy as np

from .ff import ffmpeg_bin

Sample = tuple[float, str, float, float, float, float]  # (t, stare, cx, cy, w, h); stare: idle | local | wide


def activity(path: str, src_w: int, src_h: int, fps: float = 5.0, width: int = 320,
             until: float | None = None) -> list[list]:
    """Pentru fiecare cadru eșantionat: [t, stare, cx, cy, w, h] (zona schimbată, normalizată 0..1)."""
    h = max(2, int(round(width * src_h / src_w / 2)) * 2)
    lim = ["-t", f"{until:.3f}"] if until else []
    dec = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-nostdin", *lim, "-i", path, "-vf",
                            f"fps={fps:g},scale={width}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"],
                           stdout=subprocess.PIPE)
    n = width * h
    out: list[list] = []
    prev = None
    k = 0
    try:
        while True:
            buf = dec.stdout.read(n)
            if len(buf) < n:
                break
            img = np.frombuffer(buf, np.uint8).reshape(h, width).astype(np.int16)
            t = round(k / fps, 3)
            k += 1
            if prev is None:
                prev = img
                continue
            diff = np.abs(img - prev) > 18
            prev = img
            frac = float(diff.mean())
            if diff.sum() < 4:                      # nimic (zgomot de compresie izolat)
                out.append([t, "idle", 0.5, 0.5, 1.0, 1.0])
                continue
            if frac > 0.25:                         # scroll, pagină nouă, video pe ecran
                out.append([t, "wide", 0.5, 0.5, 1.0, 1.0])
                continue
            ys, xs = np.nonzero(diff)
            x0, x1 = np.percentile(xs, [3, 97])     # fără pixeli izolați (zgomot de compresie)
            y0, y1 = np.percentile(ys, [3, 97])
            bw, bh = (x1 - x0 + 1) / width, (y1 - y0 + 1) / h
            state = "wide" if bw * bh > 0.35 or max(bw, bh) > 0.5 else "local"
            out.append([t, state, round((x0 + x1) / 2 / width, 4), round((y0 + y1) / 2 / h, 4),
                        round(bw, 4), round(bh, 4)])
    finally:
        dec.stdout.close()
        dec.wait()
    return out


def plan_zoom(samples: list[list], duration: float, max_zoom: float = 1.8, min_hold: float = 1.5,
              idle_out: float = 2.5, margin: float = 0.18, travel_step: float = 0.025) -> list[tuple[float, float, float, float, float]]:
    """Segmente (start, end, zoom, cx, cy) în timpul sursei, care acoperă [0, duration].
    zoom=1 = ecranul întreg. Un zoom ține cel puțin `min_hold` s; după `idle_out` s fără acțiune se revine."""
    if duration <= 0:
        return []
    segs: list[list] = []  # [start, end, x0, y0, x1, y1]
    cur = None             # zoom-ul activ: [start, x0, y0, x1, y1, ultima activitate, ultima pe loc]
    prev_c = None          # centrul activității din eșantionul anterior
    pending = None         # unde a ajuns cursorul care se mută (ținta, până se oprește)

    def settle(box, t, arrived=False):
        """Activitate într-o zonă. arrived=True: cursorul tocmai a ajuns aici după un drum."""
        nonlocal cur
        if cur is None:
            cur = [t, *box, t, t]  # + ultima activitate, ultima activitate pe loc
            return
        ux0, uy0 = min(cur[1], box[0]), min(cur[2], box[1])
        ux1, uy1 = max(cur[3], box[2]), max(cur[4], box[3])
        far = np.hypot((box[0] + box[2] - cur[1] - cur[3]) / 2, (box[1] + box[3] - cur[2] - cur[4]) / 2) > 0.15
        # zona crește cu acțiunea; dacă acțiunea s-a mutat altundeva, închidem zoom-ul vechi și pornim altul
        if max(ux1 - ux0, uy1 - uy0) > 0.45 or (arrived and far):
            if cur[6] - cur[0] >= min_hold * 0.5:  # în zona veche chiar s-a lucrat: o păstrăm
                segs.append([cur[0], t, *cur[1:5]])
            cur = [t, *box, t, t]                  # altfel era doar punctul de plecare
            return
        cur[1:5] = [ux0, uy0, ux1, uy1]
        cur[5] = cur[6] = t

    for t, state, cx, cy, w, h in samples:
        if state == "local":
            box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            moving = prev_c is not None and np.hypot(cx - prev_c[0], cy - prev_c[1]) > travel_step
            prev_c = (cx, cy)
            if moving:  # cursorul e în drum: nu decide zoom-ul, doar reține ținta
                pending = ((cx - 0.02, cy - 0.02, cx + 0.02, cy + 0.02), t)
                if cur is not None:
                    cur[5] = t
                continue
            if pending:
                settle(*pending, arrived=True)
                pending = None
            settle(box, t)
            continue
        prev_c = None
        if pending:                                  # cursorul s-a oprit: acolo lucrează
            settle(*pending, arrived=True)
            pending = None
        if cur is not None and (state == "wide" or t - cur[5] > idle_out):
            segs.append([cur[0], max(t, cur[0] + min_hold) if state != "wide" else t, *cur[1:5]])
            cur = None
    if cur is not None:
        segs.append([cur[0], duration, *cur[1:5]])

    out: list[tuple[float, float, float, float, float]] = []
    for a, b, x0, y0, x1, y1 in segs:
        a, b = max(0.0, a - 0.3), min(duration, b + 0.5)   # zoom-ul pornește puțin înainte de acțiune
        if b - a < min_hold:
            continue
        w, h = x1 - x0 + margin, y1 - y0 + margin
        z = float(np.clip(1.0 / max(w, h, 1e-3), 1.0, max_zoom))
        if z < 1.2:                                     # zona e aproape tot ecranul: nu merită
            continue
        if out and a < out[-1][1]:
            a = out[-1][1]
        out.append((round(a, 3), round(b, 3), round(z, 3), round((x0 + x1) / 2, 4), round((y0 + y1) / 2, 4)))
    # completăm golurile cu ecranul întreg
    full: list[tuple[float, float, float, float, float]] = []
    t = 0.0
    for a, b, z, cx, cy in out:
        if a - t > 1e-3:
            full.append((round(t, 3), a, 1.0, 0.5, 0.5))
        full.append((a, b, z, cx, cy))
        t = b
    if duration - t > 1e-3:
        full.append((round(t, 3), round(duration, 3), 1.0, 0.5, 0.5))
    return full
