"""Detectarea vorbitorului activ (fără modele în plus): mișcarea gurii × prezența vorbirii în audio.

Pentru fiecare față urmărită:
  activitate(t) = mișcarea zonei gurii − mișcarea zonei ochilor (anulează mișcarea capului / lumina)
Contează doar când se aude vorbire. Scorul e netezit pe ~0.8s, iar schimbarea de vorbitor are
histerezis (noul vorbitor trebuie să domine ≥ min_hold secunde), ca încadrarea să nu "sară".
"""
from __future__ import annotations

import subprocess

from pydantic import BaseModel

from .faces import Face, get_detector, sample_frames
from .ff import ffmpeg_bin

ROI = (32, 16)  # dimensiunea la care se compară zonele (w, h)


class Track(BaseModel):
    id: int
    cx: float
    cy: float
    w: float
    hits: int = 0


class SpeakerSeg(BaseModel):
    t0: float
    t1: float
    track: int
    cx: float
    cy: float


def _roi(gray, face: Face, which: str, W: int, H: int):
    import cv2

    lm = face.lm
    if which == "mouth":
        ax, ay, bx, by = lm[6] * W, lm[7] * H, lm[8] * W, lm[9] * H
        top, bottom = 0.35, 0.75
    else:  # ochi
        ax, ay, bx, by = lm[0] * W, lm[1] * H, lm[2] * W, lm[3] * H
        top, bottom = 0.45, 0.45
    mx, my = (ax + bx) / 2, (ay + by) / 2
    span = max(abs(bx - ax), face.w * W * 0.3)
    x0, x1 = int(mx - 0.8 * span), int(mx + 0.8 * span)
    y0, y1 = int(my - top * span), int(my + bottom * span)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, W), min(y1, H)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return cv2.resize(gray[y0:y1, x0:x1], ROI, interpolation=cv2.INTER_AREA).astype("float32")


def audio_speech(path: str, t0: float, t1: float, times: list[float], fps: float) -> list[bool]:
    """Vorbire prezentă în fereastra fiecărui cadru (prag adaptiv față de nivelul clipului)."""
    import numpy as np

    sr = 16000
    raw = subprocess.run(
        [ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{t0:.3f}", "-t", f"{t1 - t0:.3f}",
         "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True).stdout
    pcm = np.frombuffer(raw, np.int16).astype("float32") / 32768
    if pcm.size == 0:
        return [True] * len(times)
    half = int(sr / fps / 2)
    db = []
    for t in times:
        c = int((t - t0) * sr)
        w = pcm[max(c - half, 0): c + half]
        db.append(20 * np.log10(np.sqrt(np.mean(w ** 2)) + 1e-9) if w.size else -120.0)
    ref = float(np.percentile(db, 90))
    return [d > max(ref - 18, -50) for d in db]


def activity(path: str, src_w: int, src_h: int, t0: float, t1: float, fps: float = 8.0,
             width: int = 640) -> dict:
    """Mișcarea gurii per față urmărită, la fiecare cadru eșantionat din [t0, t1)."""
    import cv2
    import numpy as np

    det = get_detector("yunet")
    tracks: list[Track] = []
    prev: dict[int, tuple[int, object, object]] = {}
    times: list[float] = []
    act: dict[int, dict[int, float]] = {}
    for i, (t, frame) in enumerate(sample_frames(path, src_w, src_h, fps, width, start=t0, end=t1)):
        times.append(t)
        H, W = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        for f in det(frame):
            if not f.lm:
                continue
            tr = min(tracks, key=lambda k: abs(k.cx - f.cx), default=None)
            if tr is None or abs(tr.cx - f.cx) > max(tr.w, f.w) * 0.8:
                tr = Track(id=len(tracks), cx=f.cx, cy=f.cy, w=f.w)
                tracks.append(tr)
            tr.hits += 1
            a = 1 / tr.hits if tr.hits < 20 else 0.05  # medie mobilă a poziției
            tr.cx, tr.cy, tr.w = tr.cx + a * (f.cx - tr.cx), tr.cy + a * (f.cy - tr.cy), tr.w + a * (f.w - tr.w)
            mouth, eyes = _roi(gray, f, "mouth", W, H), _roi(gray, f, "eyes", W, H)
            if mouth is None or eyes is None:
                continue
            if tr.id in prev and prev[tr.id][0] == i - 1:
                _, pm, pe = prev[tr.id]
                dm = float(np.mean(np.abs(mouth - pm))) / 255
                de = float(np.mean(np.abs(eyes - pe))) / 255
                act.setdefault(tr.id, {})[i] = max(0.0, dm - de)
            prev[tr.id] = (i, mouth, eyes)
    n = len(times)
    keep = [tr for tr in tracks if tr.hits >= 0.3 * max(n, 1)]  # ignoră detecții sporadice
    return {
        "times": times,
        "tracks": [tr.model_dump() for tr in keep],
        "act": {tr.id: [act.get(tr.id, {}).get(i, 0.0) for i in range(n)] for tr in keep},
    }


def assign(times: list[float], act: dict[int, list[float]], speech: list[bool], t0: float, t1: float,
           fps: float = 8.0, smooth: float = 0.8, min_hold: float = 1.0, margin: float = 1.3) -> list[tuple[float, float, int]]:
    """Cine vorbește când: [(t0, t1, track_id)], cu netezire și histerezis."""
    import numpy as np

    ids = list(act)
    if not ids or not times:
        return []
    if len(ids) == 1:
        return [(t0, t1, ids[0])]
    gated = np.array([[a * s for a, s in zip(act[k], speech)] for k in ids])
    win = max(1, int(round(smooth * fps)))
    kern = np.ones(win) / win
    sm = np.array([np.convolve(row, kern, mode="same") for row in gated])
    cur = int(np.argmax(sm[:, : max(win * 2, 1)].sum(axis=1)))  # cine vorbește la început
    hold = int(round(min_hold * fps))
    segs: list[tuple[float, float, int]] = []
    seg_start = t0
    streak_from, streak_cand = None, None
    for i in range(len(times)):
        cand = int(np.argmax(sm[:, i]))
        if cand != cur and sm[cand, i] > margin * sm[cur, i] + 1e-4:
            if streak_cand != cand:
                streak_from, streak_cand = i, cand
            if i - streak_from + 1 >= hold:
                b = times[streak_from] - 0.5 / fps  # comutăm unde a început noul vorbitor
                b = max(b, seg_start)
                if b > seg_start:
                    segs.append((round(seg_start, 3), round(b, 3), ids[cur]))
                seg_start, cur = b, cand
                streak_from = streak_cand = None
        else:
            streak_from = streak_cand = None
    segs.append((round(seg_start, 3), round(t1, 3), ids[cur]))
    return segs


def speakers(path: str, src_w: int, src_h: int, t0: float, t1: float, fps: float = 8.0,
             min_hold: float = 1.0) -> dict:
    a = activity(path, src_w, src_h, t0, t1, fps)
    speech = audio_speech(path, t0, t1, a["times"], fps)
    # renumerotare stânga -> dreapta: S0 = cel mai din stânga, stabil între clipuri cu cameră fixă
    order = {tr["id"]: i for i, tr in enumerate(sorted(a["tracks"], key=lambda tr: tr["cx"]))}
    act = {order[int(k)]: v for k, v in a["act"].items()}
    tracks = {order[tr["id"]]: {**tr, "id": order[tr["id"]]} for tr in a["tracks"]}
    segs = [SpeakerSeg(t0=s, t1=e, track=k, cx=round(tracks[k]["cx"], 3), cy=round(tracks[k]["cy"], 3))
            for s, e, k in assign(a["times"], act, speech, t0, t1, fps, min_hold=min_hold)]
    return {"tracks": [tracks[k] for k in sorted(tracks)], "segments": [s.model_dump() for s in segs]}
