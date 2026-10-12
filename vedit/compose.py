"""Compoziție: zone libere (față, subtitrare), unde încape un text/grafic și cât de opac e panoul.

Ajutoare mici și deterministe (fără LLM), în coordonate normalizate 0..1 ale cadrului **randat**.
Le folosesc: `Project._visual_qa` (text peste gura feței), `EditOps.graphic_add` (unde cade un grafic),
`graphics.py` (opacitatea panoului după luminozitatea zonei) și `hooklib` (suspendarea subtitrării).
"""
from __future__ import annotations

# linia de ancorare pentru un grafic sus / jos (aceeași folosită de _Doc.place)
TOP_Y = 0.08
BOTTOM_Y = 0.888
DEFAULT_BOX_H = 0.2      # înălțimea presupusă a graficului când nu o putem măsura
# gura/bărbia = treimea de jos a feței (vezi defectul „subtitrarea peste gură”)
MOUTH_FROM = 2 / 3
# prag: cât din treimea de jos a feței poate fi acoperită de text înainte să raportăm problema
MOUTH_LIMIT = 0.15
# stilurile care stau centrat-jos și pot cădea peste gură
CENTER_STYLES = ("bold_center", "karaoke", "word_pop")


def caption_band(style: str) -> tuple[float, float]:
    """(sus, jos) normalizat al benzii de subtitrare pentru un stil. Implicit bold_center dacă e necunoscut."""
    from .captions import STYLES

    s = STYLES.get(style) or STYLES["bold_center"]
    bottom = 1 - s["margin_v"]
    return bottom - 2.4 * s["size"], bottom


def mouth_overlap(face_y0: float, face_y1: float, band: tuple[float, float]) -> float:
    """Cât din treimea de jos a feței (gura/bărbia) e acoperit de banda de text, raportat la acea zonă.

    Raportul e față de treimea de jos, nu față de fața întreagă — de asta QA-ul vechi (prag pe fața
    întreagă) lăsa să treacă un selfie încadrat pe față cu textul peste buze.
    """
    h = max(face_y1 - face_y0, 1e-6)
    z0, z1 = face_y0 + MOUTH_FROM * h, face_y1
    inter = min(z1, band[1]) - max(z0, band[0])
    return max(0.0, inter) / (z1 - z0)


def caption_over_mouth(face_y0: float, face_y1: float, band: tuple[float, float]) -> bool:
    """True dacă banda de text acoperă prea mult din gura/bărbia feței."""
    return mouth_overlap(face_y0, face_y1, band) > MOUTH_LIMIT


def _hit(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def zone_band(pos: str, box_h: float | None = None) -> tuple[float, float]:
    """Banda (sus, jos) ocupată de un grafic de înălțime `box_h` (fracțiune din înălțime) la o poziție."""
    bh = min(max(box_h if box_h else DEFAULT_BOX_H, 0.02), 0.9)
    if pos == "top":
        return TOP_Y, min(TOP_Y + bh, 1.0)
    if pos == "bottom":
        return max(BOTTOM_Y - bh, 0.0), BOTTOM_Y
    return 0.5 - bh / 2, 0.5 + bh / 2


def pick_zone(face_boxes: list[tuple], band: tuple[float, float] | None,
              box_h: float | None = None) -> tuple[str | None, str]:
    """Alege 'top'/'bottom' pentru un grafic, ca să nu calce fața (nici subtitrarea).

    `face_boxes`: dreptunghiuri (x0, y0, x1, y1) normalizate, în coordonatele cadrului randat.
    `band`: banda subtitrării (sus, jos) sau None dacă în interval nu există subtitrări.
    `box_h`: înălțimea reală a graficului (fracțiune din înălțime), măsurată cu `graphics.graphic_box`.
    Întoarce (poziție sau None, motiv în română). None = nicio zonă liberă (apelantul avertizează).
    """
    if not face_boxes:
        return None, "fără față detectată în interval"
    f0 = min(b[1] for b in face_boxes)
    f1 = max(b[3] for b in face_boxes)
    face = (0.0, f0, 1.0, f1)
    cap = None if band is None else (0.0, band[0], 1.0, band[1])
    for name in ("top", "bottom"):
        zb = zone_band(name, box_h)
        zbox = (0.0, zb[0], 1.0, zb[1])
        if not _hit(face, zbox) and (cap is None or not _hit(cap, zbox)):
            return name, ("zonă liberă sus (fața e mai jos)" if name == "top"
                          else "zonă liberă jos (fața e mai sus)")
    extra = "" if band is None else f", subtitrarea ocupă {band[0]:.2f}-{band[1]:.2f}"
    return None, (f"nicio zonă liberă pentru un grafic de {zone_band('center', box_h)[1] - zone_band('center', box_h)[0]:.0%} "
                   f"din înălțime; fața ocupă {f0:.2f}-{f1:.2f}{extra}")


# ---------------------------------------------------------------- contrast de panou (luminozitate)
_ZONE_ROWS = {"top": (0.04, 0.40), "upper_left": (0.04, 0.40), "upper_right": (0.04, 0.40),
              "bottom": (0.60, 0.96), "lower_left": (0.60, 0.96), "lower_right": (0.60, 0.96),
              "center": (0.30, 0.70)}


def zone_luma(path: str, t: float, src_w: int, src_h: int, pos: str = "center", width: int = 200) -> float | None:
    """Luminozitatea medie (0..100) a zonei unde cade graficul, dintr-un cadru al sursei (grab_frame).

    Folosită ca să adaptăm opacitatea panoului: pe fundal luminos panoul trebuie să fie mai opac.
    """
    import numpy as np

    from .style import grab_frame

    rgb = grab_frame(path, t, src_w, src_h, width=width)
    if rgb is None:
        return None
    h = rgb.shape[0]
    lo, hi = _ZONE_ROWS.get(pos, _ZONE_ROWS["center"])
    y0, y1 = int(lo * h), max(int(hi * h), int(lo * h) + 1)
    band = np.asarray(rgb[y0:y1], dtype="float32")
    luma = 0.299 * band[..., 0] + 0.587 * band[..., 1] + 0.114 * band[..., 2]
    return round(float(luma.mean()) / 255 * 100, 1)


def panel_alpha(luma: float) -> str:
    """Alpha ASS (`\\1a`) pentru panoul negru: mai opac pe fundal luminos, mai transparent pe închis.

    55% opac la negru (L=0) -> 95% opac la alb (L=100); implicitul vechi `&H50&` era ~69%.
    """
    op = min(max(0.55 + 0.40 * (luma / 100.0), 0.55), 0.95)
    return f"&H{int(round((1 - op) * 255)):02X}&"
