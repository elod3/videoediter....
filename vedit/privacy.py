"""Confidențialitate: masca fețelor de ascuns (blur / pixelare), din urmărirea fețelor (faces.py).

Masca e un video gri mic (alb = de ascuns), la `rate` cadre/s, cât tot asset-ul; randarea o scalează la sursă și
amestecă o copie încețoșată doar acolo. Ca să nu scape nimic între eșantioanele detectorului, fiecare cadru ia
reuniunea fețelor din eșantionul dinainte și de după, și ține o față ~`hold` s după ce detectorul o pierde.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import numpy as np

from .ff import FFError, ffmpeg_bin


def _boxes_at(samples: list, t: float, hold: float) -> list[dict]:
    """Fețele de acoperit la momentul t: eșantioanele vecine + cele din urmă cu până la `hold` s."""
    times = [s[0] for s in samples]
    i = int(np.searchsorted(times, t))
    out = []
    for j in (i - 1, i):
        if 0 <= j < len(samples):
            out += samples[j][1]
    k = i - 1
    while not out and k >= 0 and t - samples[k][0] <= hold:  # detectorul a pierdut fața: o ținem un pic
        out = samples[k][1]
        k -= 1
    return out


def face_mask_video(samples: list, src_w: int, src_h: int, duration: float, out: str, keep_largest: bool = False,
                    grow: float = 0.5, hold: float = 1.0, rate: float = 10.0, width: int = 320) -> int:
    """Scrie masca (video gri) și întoarce numărul de cadre cu cel puțin o față ascunsă.

    samples: [[t, [{"x","y","w","h"} normalizate]], ...] din Project.face_track.
    keep_largest: fața cea mai mare din fiecare eșantion rămâne vizibilă (persoana principală)."""
    import cv2

    samples = sorted(([t, [f for f in faces if f["w"] > 0 and f["h"] > 0]] for t, faces in samples),
                      key=lambda s: s[0])
    if keep_largest:
        samples = [[t, sorted(faces, key=lambda f: f["w"] * f["h"])[:-1]] for t, faces in samples]
    mw = width // 2 * 2
    mh = max(2, int(round(width * src_h / src_w / 2)) * 2)
    n = max(1, int(np.ceil(duration * rate)))
    tmp = str(Path(out).with_name("." + Path(out).name))
    enc = subprocess.Popen([ffmpeg_bin(), "-v", "error", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "gray",
                            "-s", f"{mw}x{mh}", "-r", f"{rate:g}", "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "10", "-pix_fmt", "yuv420p", tmp], stdin=subprocess.PIPE)
    hit = 0
    soft = max(3, int(mw * 0.02) | 1)
    try:
        for i in range(n):
            img = np.zeros((mh, mw), np.uint8)
            faces = _boxes_at(samples, (i + 0.5) / rate, hold) if samples else []
            for f in faces:
                cx, cy = (f["x"] + f["w"] / 2) * mw, (f["y"] + f["h"] / 2) * mh
                ax, ay = f["w"] * mw * (0.5 + grow / 2), f["h"] * mh * (0.5 + grow / 2) * 1.15  # și fruntea, bărbia
                cv2.ellipse(img, (int(cx), int(cy)), (max(2, int(ax)), max(2, int(ay))), 0, 0, 360, 255, -1)
            if faces:
                hit += 1
                img = cv2.GaussianBlur(img, (soft, soft), 0)
            enc.stdin.write(img.tobytes())
    finally:
        enc.stdin.close()
        enc.wait()
    if enc.returncode != 0:
        Path(tmp).unlink(missing_ok=True)
        raise FFError("nu am putut scrie masca fețelor")
    os.replace(tmp, out)
    return hit
