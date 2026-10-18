"""Rame pentru B-roll: colțuri rotunde cu umbră, telefon, laptop. Fișierele (PNG) se fac o dată și stau în cache.

Rama telefonului / laptopului e desenată în Chromium (bloc intern `device`), cu ecranul negru; aici ecranul devine
transparent pe exact dreptunghiul lui, ca video-ul pus dedesubt să se vadă prin el (insula telefonului rămâne).
"""
from __future__ import annotations

import os
from pathlib import Path

FRAMES = ("rounded", "phone", "laptop")


def _root() -> Path:
    d = Path(os.environ.get("VEDIT_HOME", "./vedit_projects")).resolve() / ".motion" / "frames"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def geometry(kind: str, W: int, H: int, scale: float, src_aspect: float) -> dict:
    """Pânza ramei (w, h) și dreptunghiul ecranului (sx, sy, sw, sh, sr), în pixeli de randare."""
    if kind == "phone":
        ch = _even(H * (0.8 if H > W else 0.84) * min(max(scale / 0.38, 0.6), 1.2))
        cw = _even(ch * 0.49)
        sx, sy = _even(cw * 0.042), _even(cw * 0.042)
        return {"w": cw, "h": ch, "sx": sx, "sy": sy, "sw": cw - 2 * sx, "sh": ch - 2 * sy, "sr": int(cw * 0.13)}
    if kind == "laptop":
        cw = _even(W * (0.86 if H > W else 0.68) * min(max(scale / 0.38, 0.6), 1.3))
        sw = _even(cw * 0.86)
        sh = _even(sw * 0.625)
        sx, sy = (cw - sw) // 2, _even(cw * 0.026)
        return {"w": cw, "h": _even(2 * sy + sh + cw * 0.042), "sx": sx, "sy": sy, "sw": sw, "sh": sh, "sr": 2}
    w = _even(W * scale)  # rounded: cât fereastra picture-in-picture, cu aspectul sursei
    h = _even(w / max(src_aspect, 0.2))
    return {"w": w, "h": h, "sx": 0, "sy": 0, "sw": w, "sh": h, "sr": int(min(w, h) * 0.07)}


def _rounded_alpha(w: int, h: int, r: int):
    import cv2
    import numpy as np

    a = np.zeros((h * 4, w * 4), np.uint8)  # 4x pentru margini netede, apoi micșorat
    R = r * 4
    cv2.rectangle(a, (R, 0), (w * 4 - R, h * 4), 255, -1)
    cv2.rectangle(a, (0, R), (w * 4, h * 4 - R), 255, -1)
    for cx, cy in ((R, R), (w * 4 - R, R), (R, h * 4 - R), (w * 4 - R, h * 4 - R)):
        cv2.circle(a, (cx, cy), R, 255, -1)
    return cv2.resize(a, (w, h), interpolation=cv2.INTER_AREA)


def assets(kind: str, g: dict) -> dict:
    """{mask: PNG gri pentru video (ecran), shadow: PNG cu umbră + pad, frame: PNG cu rama (sau None)}."""
    import cv2
    import numpy as np

    key = f"{kind}_{g['w']}x{g['h']}_{g['sw']}x{g['sh']}_{g['sr']}"
    root = _root()
    out = {"mask": root / f"{key}.mask.png", "shadow": root / f"{key}.shadow.png",
           "frame": root / f"{key}.frame.png" if kind != "rounded" else None}
    if not out["mask"].exists():
        cv2.imwrite(str(out["mask"]), _rounded_alpha(g["sw"], g["sh"], max(g["sr"], 1)))
    pad = int(max(g["w"], g["h"]) * 0.08)
    if not out["shadow"].exists():  # umbră moale sub toată rama
        r = int(min(g["w"], g["h"]) * (0.17 if kind == "phone" else 0.07 if kind == "rounded" else 0.03))
        a = np.zeros((g["h"] + 2 * pad, g["w"] + 2 * pad), np.uint8)
        a[pad:pad + g["h"], pad:pad + g["w"]] = _rounded_alpha(g["w"], g["h"], max(r, 1))
        a = cv2.GaussianBlur(a, (0, 0), pad / 2.6)
        a = np.roll(a, int(pad * 0.35), axis=0)
        rgba = np.zeros(a.shape + (4,), np.uint8)
        rgba[..., 3] = (a.astype(np.float32) * 0.55).astype(np.uint8)
        cv2.imwrite(str(out["shadow"]), rgba)
    if out["frame"] is not None and not out["frame"].exists():
        from .motion import still

        png = still("device", {"kind": kind, "sx": g["sx"], "sy": g["sy"], "sw": g["sw"], "sh": g["sh"], "sr": g["sr"]},
                    {}, g["w"], g["h"], 1.0, 0.0)
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
        if img.shape[2] == 3:
            img = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
        hole = np.zeros(img.shape[:2], np.uint8)
        hole[g["sy"]:g["sy"] + g["sh"], g["sx"]:g["sx"] + g["sw"]] = _rounded_alpha(g["sw"], g["sh"], max(g["sr"], 1))
        black = img[..., :3].max(2) <= 2   # ecranul e #000; insula (#050505) rămâne
        img[..., 3] = np.where((hole > 127) & black, 0, img[..., 3])
        cv2.imwrite(str(out["frame"]), img)
    out["pad"] = pad
    return out
