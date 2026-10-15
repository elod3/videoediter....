"""Blocuri de motion: HTML + GSAP, randate în Chromium (engine.py), puse peste montaj de render.py.

Agentul alege un BLOC (șablon din blocks/) și un STIL (pachet din styles/), și dă doar parametri.
Culorile „auto” vin din filmare (palette_from_frames): accentul e culoarea dominantă a cadrului, iar
dark / light sunt aceeași nuanță, foarte închisă și foarte deschisă (regula 60 / 30 / 10).
"""
from __future__ import annotations

import colorsys
import json
import re
from pathlib import Path

from .engine import BLOCKS, MotionError, cache_key, render_frames, still  # noqa: F401

STYLES = Path(__file__).parent / "styles"

# Ce face fiecare bloc și ce parametri primește. Validarea de aici e singura poartă dintre agent și pagină.
BLOCK_HELP: dict[str, dict] = {
    "headline": {
        "help": "titlu care apare cuvânt cu cuvânt din blur; cuvintele din highlight primesc marker/linie/culoare",
        "params": {"text": "str*", "kicker": "str", "sub": "str", "highlight": "list", "mark": "marker|line|color",
                   "position": "top|center|bottom", "align": "left|center", "shade": "bool", "size": "num"},
        "dur": (1.5, 5),
    },
    "stat": {
        "help": "cifră mare care urcă (0 -> value), cu etichetă și, opțional, comparația „înainte”",
        "params": {"value": "num*", "from": "num", "prefix": "str", "suffix": "str", "decimals": "num",
                   "label": "str", "before": "str", "position": "top|center|bottom"},
        "dur": (2, 5),
    },
    "lower_third": {
        "help": "nume + rol, cu linie de accent care se desenează; stânga-jos (sau sus pe vertical)",
        "params": {"name": "str*", "role": "str", "position": "bottom|top"},
        "dur": (2.5, 5),
    },
    "list": {
        "help": "listă (2-5 puncte) care apar pe rând, cu bifă sau număr; titlu opțional",
        "params": {"title": "str", "items": "list*", "style": "check|number|dot", "times": "list"},
        "dur": (3, 12),
    },
    "compare": {
        "help": "două carduri față în față (înainte / după, A / B), cu etichete și valori",
        "params": {"left_label": "str*", "left_value": "str", "right_label": "str*", "right_value": "str",
                   "title": "str", "winner": "left|right|none"},
        "dur": (3, 7),
    },
    "chapter": {
        "help": "capitol pe tot ecranul: număr + titlu care se descifrează, pe fundal cu grilă",
        "params": {"number": "str", "title": "str*", "sub": "str"},
        "dur": (2, 4), "full": True,
    },
    "bars": {
        "help": "grafic cu bare care cresc (2-6 valori), cu etichete și valoarea pe fiecare bară",
        "params": {"title": "str", "labels": "list*", "values": "list*", "suffix": "str", "highlight": "num"},
        "dur": (3, 7),
    },
    "line_chart": {
        "help": "linie care se desenează (creștere în timp), cu punctul final și valoarea lui",
        "params": {"title": "str", "values": "list*", "labels": "list", "suffix": "str", "prefix": "str"},
        "dur": (3, 7),
    },
    "quote": {
        "help": "citat mare cu ghilimele, autor dedesubt; serif elegant",
        "params": {"text": "str*", "author": "str"},
        "dur": (3, 7),
    },
    "notification": {
        "help": "notificare de telefon / card UI care alunecă de sus (aplicație, titlu, mesaj)",
        "params": {"app": "str", "title": "str*", "body": "str", "time": "str", "icon": "str"},
        "dur": (2, 5),
    },
    "image_card": {
        "help": "poză din proiect (captură, produs, logo) într-un card cu umbră, cu zoom lent și înclinare 3D",
        "params": {"caption": "str", "tilt": "bool", "position": "center|left|right"},
        "images": ["image"], "dur": (2, 6),
    },
    "cta": {
        "help": "îndemn final: pastilă cu iconiță (abonare / urmărire / link) și cursor care apasă",
        "params": {"text": "str*", "sub": "str", "icon": "bell|plus|link|phone|cart"},
        "dur": (2, 5),
    },
    "pin": {
        "help": "cerc + etichetă legată de un punct (x, y din cadru); cu track (track_point) urmărește obiectul",
        "params": {"label": "str*", "x": "num", "y": "num"},
        "dur": (2, 6),
    },
    "steps": {
        "help": "pași 1-2-3 legați de o linie care se desenează, fiecare cu titlu scurt",
        "params": {"title": "str", "items": "list*"},
        "dur": (3, 9),
    },
}

ICONS = ("bell", "plus", "link", "phone", "cart", "check", "star", "bolt", "chat", "play")


def blocks_help() -> str:
    lines = []
    for name, b in BLOCK_HELP.items():
        req = [k.rstrip("*") for k, v in b["params"].items() if v.endswith("*")]
        opt = [k for k, v in b["params"].items() if not v.endswith("*")]
        lines.append(f"- {name}: {b['help']} | obligatoriu: {', '.join(req) or '-'} | opțional: {', '.join(opt)}"
                     f" | {b['dur'][0]}-{b['dur'][1]} s" + (" | images: " + ", ".join(b["images"]) if b.get("images") else ""))
    return "\n".join(lines)


def styles_list() -> dict[str, dict]:
    out = {}
    for f in sorted(STYLES.glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[f.stem] = d
    return out


def validate(block: str, params: dict, duration: float, images: dict[str, str]) -> list[str]:
    """Verifică parametrii unui bloc. ValueError la erori; întoarce avertismente."""
    if block not in BLOCK_HELP:
        raise ValueError(f"bloc necunoscut {block!r}; disponibile: {', '.join(BLOCK_HELP)}")
    spec = BLOCK_HELP[block]["params"]
    warn = []
    for k in params:
        if k not in spec:
            raise ValueError(f"{block}: parametru necunoscut {k!r} (merg: {', '.join(x.rstrip('*') for x in spec)})")
    for k, kind in spec.items():
        need = kind.endswith("*")
        kind = kind.rstrip("*")
        v = params.get(k)
        if v is None or v == "" or v == []:
            if need:
                raise ValueError(f"{block}: lipsește {k}")
            continue
        if kind == "str":
            if not isinstance(v, str):
                raise ValueError(f"{block}.{k}: text")
            if len(v) > (90 if k in ("text", "title", "body") else 48):
                raise ValueError(f"{block}.{k}: prea lung ({len(v)} caractere); pe ecran se citește puțin")
        elif kind == "num":
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ValueError(f"{block}.{k}: număr")
        elif kind == "bool":
            if not isinstance(v, bool):
                raise ValueError(f"{block}.{k}: true sau false")
        elif kind == "list":
            if not isinstance(v, list) or not 1 <= len(v) <= 6:
                raise ValueError(f"{block}.{k}: listă cu 1-6 elemente")
            if any(len(str(x)) > 40 for x in v):
                raise ValueError(f"{block}.{k}: fiecare element maxim 40 de caractere")
        else:  # opțiuni a|b|c
            if v not in kind.split("|"):
                raise ValueError(f"{block}.{k}: una din {kind.replace('|', ', ')}")
    if block in ("bars",) and len(params.get("labels", [])) != len(params.get("values", [])):
        raise ValueError("bars: labels și values trebuie să aibă aceeași lungime")
    if block in ("bars", "line_chart") and not all(isinstance(x, (int, float)) for x in params.get("values", [])):
        raise ValueError(f"{block}.values: doar numere")
    if block == "line_chart" and len(params.get("values", [])) < 2:
        raise ValueError("line_chart: cel puțin 2 valori")
    if block == "cta" and params.get("icon") and params["icon"] not in ICONS:
        raise ValueError(f"cta.icon: {', '.join(ICONS)}")
    if block == "notification" and params.get("icon") and params["icon"] not in ICONS:
        raise ValueError(f"notification.icon: {', '.join(ICONS)}")
    need_img = BLOCK_HELP[block].get("images", [])
    for k in need_img:
        if k not in images:
            raise ValueError(f"{block}: lipsește imaginea {k!r} (images={{'{k}': 'a3'}})")
    lo, hi = BLOCK_HELP[block]["dur"]
    if duration < 0.8:
        raise ValueError("blocul trebuie să dureze cel puțin 0.8 s")
    if duration < lo:
        warn.append(f"{block}: {duration:.1f} s e scurt; se citește bine de la {lo} s")
    if duration > hi * 1.5:
        warn.append(f"{block}: {duration:.1f} s e lung; peste {hi} s ecranul devine static")
    return warn


def _hex(rgb) -> str:
    return "#" + "".join(f"{int(round(max(0, min(1, c)) * 255)):02X}" for c in rgb)


def palette_from_frames(frames) -> dict[str, str]:
    """Culoarea dominantă (nu gri) din cadre RGB -> accent + varianta închisă și cea deschisă."""
    import numpy as np

    px = np.concatenate([f.reshape(-1, 3) for f in frames if f is not None]).astype(np.float32) / 255.0
    mx, mn = px.max(1), px.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    keep = px[(sat > 0.22) & (mx > 0.18)]
    if len(keep) < 200:  # cadre aproape fără culoare: accent cald, neutru
        h = 0.11
    else:
        hsv = np.array([colorsys.rgb_to_hsv(*p) for p in keep[:: max(1, len(keep) // 6000)]])
        hist, edges = np.histogram(hsv[:, 0], bins=36, range=(0, 1), weights=hsv[:, 1])
        i = int(hist.argmax())
        h = float((edges[i] + edges[i + 1]) / 2)
    return {"accent": _hex(colorsys.hsv_to_rgb(h, 0.74, 0.96)),
            "dark": _hex(colorsys.hsv_to_rgb(h, 0.38, 0.09)),
            "dark2": _hex(colorsys.hsv_to_rgb(h, 0.30, 0.15)),
            "light": _hex(colorsys.hsv_to_rgb(h, 0.10, 0.96))}


def resolve_style(name: str, palette: dict[str, str] | None = None, brand_accent: str | None = None) -> dict:
    """Pachetul de stil cu culorile „auto” înlocuite: brandul clientului > culorile din filmare > implicit."""
    all_ = styles_list()
    if name not in all_:
        raise ValueError(f"stil necunoscut {name!r}; disponibile: {', '.join(all_)}")
    st = json.loads(json.dumps(all_[name]))
    pal = palette or {}
    c = st.setdefault("colors", {})
    if c.get("accent") == "auto":
        c["accent"] = brand_accent or pal.get("accent") or "#E8B04B"
    if c.get("bg") == "auto":
        c["bg"] = pal.get("dark", "#0B0C0F")
    if c.get("bg2") == "auto":
        c["bg2"] = pal.get("dark2", "#15171C")
    for k, v in list(c.items()):
        if isinstance(v, str) and not re.fullmatch(r"#[0-9A-Fa-f]{6}|rgba?\([0-9., ]+\)", v):
            raise ValueError(f"stilul {name}: culoare invalidă {k}={v}")
    return st
