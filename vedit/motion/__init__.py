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
        "params": {"name": "str*", "role": "str", "position": "bottom|top|middle"},
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
        "params": {"title": "str", "labels": "list*", "values": "list*", "suffix": "str", "highlight": "num", "full": "bool"},
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
        "params": {"text": "str*", "sub": "str", "icon": "bell|plus|link|phone|cart", "position": "bottom|center|top"},
        "dur": (2, 5),
    },
    "kinetic": {
        "help": "text cinetic mare, fără casetă: literă cu literă din blur; cuvintele din italic în serif italic (accent)",
        "params": {"text": "str*", "italic": "list", "kicker": "str", "small": "str", "position": "top|center|bottom",
                   "align": "left|center", "size": "num"},
        "dur": (1.2, 4),
    },
    "map": {
        "help": "conturul României care se desenează, cu un oraș marcat (pulsează); bun pe „în România”, „la noi”",
        "params": {"title": "str", "italic": "list", "city": "str", "sub": "str", "full": "bool"},
        "dur": (2, 5),
    },
    "logo_reveal": {
        "help": "intro / outro cu logo-ul clientului (poză PNG din proiect): mască, dungă de lumină, slogan",
        "params": {"tagline": "str", "transparent": "bool"},
        "images": ["logo"], "dur": (2, 4), "full": True,
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
    "stack_title": {
        "help": "tipografie de reel în 3 registre: rând mic sans (top) + CUVÂNT uriaș condensat (word) + scris de mână "
                "în accent (accent) + rând mic (bottom); cu behind=true capul acoperă cuvântul. Pe cuvântul-cheie al frazei",
        "params": {"word": "str*", "top": "str", "accent": "str", "bottom": "str", "reveal": "blur|pixel|slide|mask",
                   "tone": "ink|accent|dark", "font": "condensed|heavy", "position": "top|center|bottom", "size": "num"},
        "dur": (1.2, 4), "front": True,
    },
    "orbit_words": {
        "help": "fraza spusă, cuvânt cu cuvânt, cu literele pe un cerc în jurul capului (fața e găsită singură); "
                "layout around|arc|tilt|stack|fly (din adânc, 3D, trec pe lângă cameră); times = momentele cuvintelor din transcript; emphasis = cuvintele mari în accent",
        "params": {"text": "str*", "times": "list", "emphasis": "list", "layout": "around|arc|tilt|stack|fly",
                   "x": "num", "y": "num", "radius": "num", "from": "num", "spin": "num"},
        "dur": (1.2, 6),
    },
    "float_cards": {
        "help": "1-3 poze din proiect în carduri care plutesc în jurul vorbitorului (ocolesc fața), intră cu whip și blur; "
                "layout around|stack|fan; labels pe pastile; glow = halou în accent. Dovezi: capturi, produse, rezultate",
        "params": {"layout": "around|stack|fan", "labels": "list", "glow": "bool"},
        "images": ["card1"], "optional_images": ["card2", "card3"], "dur": (1.5, 6),
    },
    "day_counter": {
        "help": "calendar care se rupe pagină cu pagină (from -> to) cu label sub cifră, title de mână deasupra, sub; "
                "full = scenă pe tot ecranul pe fundal în accent cu grilă. Pe „în 3 zile”, „după 30 de zile”",
        "params": {"to": "num*", "from": "num", "label": "str", "title": "str", "sub": "str", "full": "bool"},
        "dur": (1.5, 5),
    },
    "speed_lines": {
        "help": "linii de viteză de benzi desenate pe tot ecranul, desenate din nou la 2 cadre; cu behind=true = "
                "persoana pe fundal „comic burst” (moment de șoc, reacție, dezvăluire). tone light|dark|accent",
        "params": {"x": "num", "y": "num", "tone": "light|dark|accent", "density": "num"},
        "dur": (0.6, 3), "full": True, "behind_ok": True,
    },
    "pixel_wipe": {
        "help": "tranziție din blocuri de pixeli în accent (sau color #RRGGBB), pusă peste o tăietură (0.4-0.8 s, "
                "centrată pe tăietură); mode wipe (acoperă tot, de la from) | burst (nor de pixeli în jurul feței)",
        "params": {"mode": "wipe|burst", "from": "left|right|top|bottom", "color": "str", "cell": "num"},
        "dur": (0.3, 1.2),
    },
    "bubble": {
        "help": "balon de chat / gând lângă vorbitor, cu coada spre el, pop cu overshoot; text scurt (o întrebare, o "
                "replică, „ce mi-a zis clientul”); tone light|accent|dark, think = bule de gând",
        "params": {"text": "str*", "sub": "str", "side": "left|right", "tone": "light|accent|dark", "think": "bool"},
        "dur": (1.5, 5),
    },
    "scene_card": {
        "help": "(pus de tool-ul scene_card) ultimul cadru al scenei de dinainte se strânge într-un card cu ramă albă "
                "și zboară spre un colț, peste scena nouă; corner tl|tr|bl|br, size 0.25-0.5, exit",
        "params": {"corner": "tl|tr|bl|br", "size": "num", "exit": "bool"},
        "images": ["image"], "dur": (0.8, 4),
    },
}

ICONS = ("bell", "plus", "link", "phone", "cart", "check", "star", "bolt", "chat", "play")


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


def image_file(path: str) -> str | None:
    """Poza din spatele unui asset: fișierul însuși sau, la o poză importată (clip fix `X.still.mp4`), originalul
    `X.png/jpg/webp` păstrat lângă el. None dacă asset-ul nu e o poză."""
    p = Path(path)
    if p.suffix.lower() in IMAGE_EXT:
        return str(p)
    if p.name.endswith(".still.mp4"):
        stem = p.name[: -len(".still.mp4")]
        for ext in IMAGE_EXT + tuple(e.upper() for e in IMAGE_EXT):
            q = p.with_name(stem + ext)
            if q.exists():
                return str(q)
    return None


def hits(block: str, params: dict, start: float, dur: float) -> list[tuple[str, float, float]]:
    """Momentele de lovitură ale unui bloc (sunet, timp de montaj, dB în plus față de nivelul de bază), după aceeași
    cronologie ca animația din blocks/*.html. sfx_auto pune sunetul exact acolo, nu „cam la început”."""
    P = params
    out: list[tuple[str, float, float]] = []
    if block == "stack_title":
        at = start + (0.12 if P.get("top") else 0.0)
        out.append(("whoosh", start - 0.12, -4))
        out.append(("glitch" if P.get("reveal") == "pixel" else "impact", at + 0.15, 0))
    elif block == "orbit_words":
        words = str(P.get("text", "")).split()
        times = list(P.get("times") or [])
        span = max(0.6, min(dur - 0.6, dur * 0.65))
        while len(times) < len(words):
            times.append(times[-1] + span / max(len(words), 1) if times else 0.0)
        em = {str(w).lower() for w in P.get("emphasis") or []}
        for i, (w, t) in enumerate(zip(words, times)):
            big = w.lower().strip(".,!?") in em
            if big or i % 2 == 0:  # nu pe fiecare cuvânt: pe cele mari și din două în două
                out.append(("impact" if big else ("pop" if i % 4 == 0 else "click"), start + t, 0 if big else -5))
    elif block == "float_cards":
        n = max(1, len(P.get("labels") or []) or 2)
        out += [("whoosh", start + i * 0.14, -3) for i in range(min(n, 3))]
    elif block == "day_counter":
        a, b = int(P.get("from", 1) or 1), int(P.get("to", 1))
        pages = min(abs(b - a) + 1, 12)
        out.append(("pop", start + 0.05, -2))
        span = max(0.3, dur - 0.45 - 0.7 - 0.5)
        each = span / max(pages - 1, 1)
        out += [("click", start + 0.7 + i * each, -4) for i in range(pages - 1)]
    elif block == "speed_lines":
        out.append(("impact", start, 0))
    elif block == "pixel_wipe":
        out.append(("glitch", start + dur * 0.2, -2))
    elif block == "bubble":
        out.append(("pop", start + 0.08, -2))
    elif block == "scene_card":
        out += [("whoosh", start - 0.05, -2), ("pop", start + 0.45, -6)]
    elif block == "stat":
        out += [("whoosh", start - 0.1, -4), ("ding", start + 0.7 * dur, -2)]
    elif block in ("list", "steps"):
        items = P.get("items") or []
        times = P.get("times") or [0.4 + i * 0.6 * dur / max(len(items), 1) for i in range(len(items))]
        out += [("pop", start + t, -3) for t in times[:len(items)]]
    elif block == "chapter":
        out += [("riser", start - 1.0, -4), ("impact", start, 0)]
    elif block in ("lower_third", "notification", "cta", "pin"):
        out.append(({"lower_third": "swipe", "notification": "ding", "cta": "click", "pin": "pop"}[block], start + 0.1, -2))
    elif block == "logo_reveal":
        out.append(("impact", start + 0.3, 0))
    elif block in ("headline", "kinetic", "image_card", "compare", "bars", "line_chart", "map"):
        out.append(("whoosh", start - 0.1, -3))
    return [(k, max(0.0, round(t, 3)), e) for k, t, e in out]


def blocks_help() -> str:
    lines = []
    for name, b in BLOCK_HELP.items():
        req = [k.rstrip("*") for k, v in b["params"].items() if v.endswith("*")]
        opt = [k for k, v in b["params"].items() if not v.endswith("*")]
        lines.append(f"- {name}: {b['help']} | obligatoriu: {', '.join(req) or '-'} | opțional: {', '.join(opt)}"
                     f" | {b['dur'][0]}-{b['dur'][1]} s" + (" | images: " + ", ".join(b["images"] + b.get("optional_images", []))
                                                          if b.get("images") else ""))
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
            if k == "word" and len(v) > 14:
                raise ValueError(f"{block}.word: un singur cuvânt scurt (maxim 14 litere); restul frazei merge în top/bottom")
            if len(v) > (90 if k in ("text", "title", "body") else 48):
                raise ValueError(f"{block}.{k}: prea lung ({len(v)} caractere); pe ecran se citește puțin")
        elif kind == "num":
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise ValueError(f"{block}.{k}: număr")
        elif kind == "bool":
            if not isinstance(v, bool):
                raise ValueError(f"{block}.{k}: true sau false")
        elif kind == "list":
            most = 9 if k == "times" else 6
            if not isinstance(v, list) or not 1 <= len(v) <= most:
                raise ValueError(f"{block}.{k}: listă cu 1-{most} elemente")
            if any(len(str(x)) > 40 for x in v):
                raise ValueError(f"{block}.{k}: fiecare element maxim 40 de caractere")
        else:  # opțiuni a|b|c
            if v not in kind.split("|"):
                raise ValueError(f"{block}.{k}: una din {kind.replace('|', ', ')}")
    if block in ("bars",) and len(params.get("labels", [])) != len(params.get("values", [])):
        raise ValueError("bars: labels și values trebuie să aibă aceeași lungime")
    if block in ("bars", "line_chart") and not all(isinstance(x, (int, float)) for x in params.get("values", [])):
        raise ValueError(f"{block}.values: doar numere")
    if block == "orbit_words":
        if len(str(params.get("text", "")).split()) > 9:
            raise ValueError("orbit_words: maxim 9 cuvinte; o frază lungă pe cerc nu se mai citește")
        if not all(isinstance(x, (int, float)) and 0 <= x <= duration for x in params.get("times", [])):
            raise ValueError("orbit_words.times: secunde din bloc (0..durata), câte una pe cuvânt")
    if block == "line_chart" and len(params.get("values", [])) < 2:
        raise ValueError("line_chart: cel puțin 2 valori")
    if block == "cta" and params.get("icon") and params["icon"] not in ICONS:
        raise ValueError(f"cta.icon: {', '.join(ICONS)}")
    if block == "notification" and params.get("icon") and params["icon"] not in ICONS:
        raise ValueError(f"notification.icon: {', '.join(ICONS)}")
    lo, hi = BLOCK_HELP[block]["dur"]
    need_img = BLOCK_HELP[block].get("images", [])
    for k in need_img:
        if k not in images:
            raise ValueError(f"{block}: lipsește imaginea {k!r} (images={{'{k}': 'a3'}})")
    known = set(need_img) | set(BLOCK_HELP[block].get("optional_images", []))
    for k in images:
        if k not in known:
            raise ValueError(f"{block}: imagine necunoscută {k!r} (merg: {', '.join(sorted(known)) or 'niciuna'})")
    if block == "pixel_wipe" and params.get("color") and not re.fullmatch(r"#[0-9A-Fa-f]{6}", params["color"]):
        raise ValueError("pixel_wipe.color: #RRGGBB")
    if duration < min(0.8, lo) - 1e-3:  # 0.8 s rotunjit la cadre poate ieși 0.7999
        raise ValueError(f"blocul trebuie să dureze cel puțin {min(0.8, lo):g} s")
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
