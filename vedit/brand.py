"""Brand kit și livrare: preseturi de platformă, familia unui font, claritatea unui cadru (thumbnail).

Logica de proiect (ce se salvează în timeline, undo, randare) e în Project; aici sunt doar date și calcule pure.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

LOGO_EXT = (".png", ".jpg", ".jpeg", ".webp")
FONT_EXT = (".ttf", ".otf")

# Limitele platformelor se schimbă des: le tratăm ca AVERTISMENTE, nu ca blocaje.
# Loudness: -14 LUFS peste tot. YouTube/Spotify normalizează la -14; LinkedIn și X nu publică o țintă,
# iar -16 (recomandarea AES pentru platforme fără normalizare) ar suna mai încet decât restul feed-ului.
# True peak -1.5 dB (din render) lasă loc pentru re-encodarea AAC a platformei.
PLATFORMS: dict[str, dict] = {
    "tiktok": {"fmt": "9:16", "max": 600, "note": "TikTok: ~10 min la upload din aplicație"},
    "reels": {"fmt": "9:16", "max": 180, "note": "Instagram Reels: ~3 min"},
    "shorts": {"fmt": "9:16", "max": 180, "note": "YouTube Shorts: ~3 min"},
    "youtube": {"fmt": "16:9", "max": 900, "note": "YouTube: peste 15 min cere cont verificat"},
    "instagram_feed": {"fmt": "4:5", "max": 3600, "note": "Instagram feed: ~60 min; sub 15 min apare ca Reel"},
    "linkedin": {"fmt": "1:1", "max": 600, "note": "LinkedIn: ~10 min (15 min de pe desktop)"},
    "x": {"fmt": "16:9", "max": 140, "note": "X: 2:20 pentru conturi fără abonament"},
}
LUFS = -14.0


def file_hash(path: str | Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:10]


def font_family(path: str | Path) -> str | None:
    """Numele de familie (name ID 1, cel după care caută libass) citit din font. None fără fontTools."""
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    font = TTFont(str(path), lazy=True, fontNumber=0)
    name = font["name"]
    for nid in (1, 16):
        rec = name.getName(nid, 3, 1, 0x409) or name.getName(nid, 1, 0, 0) or name.getDebugName(nid)
        if rec:
            return str(rec).strip()
    return None


def sharpness(rgb) -> float:
    """Varianța Laplacianului pe luminanță: mare = cadru clar, mic = neclar / motion blur."""
    import numpy as np

    g = rgb.astype(np.float32) @ np.array([0.299, 0.587, 0.114], np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def pick_best(cands: list[dict]) -> dict:
    """Cel mai clar cadru; unul cu fețe câștigă dacă e măcar pe jumătate de clar ca cel mai clar."""
    top = max(c["sharpness"] for c in cands)
    return max(cands, key=lambda c: (c["faces"] > 0 and c["sharpness"] >= 0.5 * top, c["sharpness"]))


def check_ext(path: str, allowed: tuple[str, ...], what: str) -> str:
    ext = Path(path).suffix.lower()
    if ext not in allowed:
        raise ValueError(f"{what}: doar {', '.join(allowed)}")
    return ext
