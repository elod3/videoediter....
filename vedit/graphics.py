"""Motion graphics: șabloane animate (Graphic) -> document ASS randat de libass (filtrul `ass`).

Fără drawtext: formele sunt desene ASS (\\p1), animațiile sunt tag-uri de override (\\t, \\move, \\clip, \\fad).
Totul e determinist și scalat după W/H (dimensiunile după latura mică), deci merge și la preview (540p).
"""
from __future__ import annotations

import re

from .captions import _ts, ass_color, norm_hex
from .timeline import GRAPHICS, Graphic, Timeline

KINDS_HELP = {
    "lower_third": "bară cu nume (text) și rol (subtext), intră din stânga; implicit stânga-jos",
    "title_card": "titlu mare cu pop (115% -> 100%) și subtitlu opțional (subtext)",
    "callout": "casetă cu text care arată spre punctul (x, y), cu linie și punct accent",
    "counter": "număr animat de la value_from la value_to (prefix/suffix/decimals), text = eticheta",
    "progress_bar": "bară subțire de progres sus (sau jos cu position=bottom), crește pe durata graficului",
    "cta": "pastilă call-to-action cu bounce (implicit „Urmărește pentru mai mult”), implicit jos",
    "list": "listă cu puncte (items, 1-6), apar pe rând; text = titlu opțional",
    "kinetic": "text cinetic: cuvintele apar unul câte unul cu pop, centrat",
    "circle": "cerc accent în jurul punctului (x, y), raza = size din latura mică, cu puls",
    "line_grid": "linii/grilă care se desenează progresiv (hartă, schemă, structură, tabel); text = titlul, opțional",
    "spec_card": "card de date: text = titlu, items = rânduri etichetă/valoare care apar pe rând",
    "quote_card": "citat: text = citatul, subtext = autorul; semn de citat mare, intră lin (fără pop)",
    "before_after": "compară cadrul: mască care culisează între două jumătăți; text = eticheta stânga, subtext = dreapta",
    "chapter_num": "număr mare de capitol (value_to, 1-99) cu linie subțire, intră cu wipe; text = titlul",
    "mask_reveal": "titlu dezvăluit de o mască care culisează (nu pop, nu fade simplu); text = titlul",
    "typewriter": "text scris literă cu literă, cu cursor care clipește la final; text = fraza",
    "stat_badge": "pastilă mică cu o valoare/etichetă, intrare calmă, fără zgomot vizual; text = valoarea",
}
DEFAULT_ACCENT = "#C8FF3D"
PANEL_ALPHA = "&H50&"   # panouri negre semi-transparente (implicit; vezi compose.panel_alpha pentru adaptare)
K = 0.5523              # bezier pentru sfert de cerc
TOP = ("top", "upper_left", "upper_right")
BOTTOM = ("bottom", "lower_left", "lower_right")


def _panel(g: Graphic) -> str:
    """Alpha-ul panoului negru: cel calculat după luminozitatea zonei, altfel implicitul."""
    return g.panel_alpha or PANEL_ALPHA


def validate(g: Graphic) -> None:
    """Verifică un grafic înainte să intre pe timeline. ValueError cu mesaj clar în română."""
    if g.kind not in GRAPHICS:
        raise ValueError(f"tip de grafic necunoscut {g.kind!r}; disponibile: {', '.join(GRAPHICS)}")
    if g.end <= g.start or g.start < 0:
        raise ValueError("graficul trebuie să aibă start >= 0 și end > start")
    if g.duration < 0.5:
        raise ValueError("graficul trebuie să dureze cel puțin 0.5 s")
    limit = 100 if g.kind in ("kinetic", "quote_card", "typewriter", "mask_reveal", "spec_card", "line_grid") else 60
    if len(g.text) > limit:
        raise ValueError(f"textul e prea lung ({len(g.text)} caractere, maxim {limit} pentru {g.kind})")
    if len(g.subtext) > 80:
        raise ValueError("subtext prea lung (maxim 80 de caractere)")
    if g.kind in ("lower_third", "title_card", "callout", "kinetic", "line_grid", "quote_card", "before_after",
                  "chapter_num", "mask_reveal", "typewriter", "stat_badge", "spec_card") and not g.text.strip():
        raise ValueError(f"{g.kind} are nevoie de text")
    if g.kind == "counter":
        if g.value_from == g.value_to:
            raise ValueError("counter are nevoie de value_from diferit de value_to")
        if not 0 <= g.decimals <= 3:
            raise ValueError("decimals trebuie să fie între 0 și 3")
        if len(g.prefix) > 8 or len(g.suffix) > 8:
            raise ValueError("prefix/suffix: maxim 8 caractere")
    if g.kind == "list":
        items = [i for i in g.items if i.strip()]
        if not 1 <= len(items) <= 6 or len(items) != len(g.items):
            raise ValueError("list are nevoie de 1-6 rânduri (items), fără rânduri goale")
        if any(len(i) > 40 for i in items):
            raise ValueError("fiecare rând din listă: maxim 40 de caractere")
    if g.kind == "spec_card":
        items = [i for i in g.items if i.strip()]
        if not 1 <= len(items) <= 8 or len(items) != len(g.items):
            raise ValueError("spec_card are nevoie de 1-8 rânduri (items), fără rânduri goale")
        if any(len(i) > 48 for i in items):
            raise ValueError("fiecare rând din spec_card: maxim 48 de caractere")
    if g.kind == "chapter_num":
        if not 1 <= g.value_to <= 99 or abs(g.value_to - round(g.value_to)) > 1e-6:
            raise ValueError("chapter_num: value_to trebuie să fie un număr întreg între 1 și 99")
        if len(g.prefix) > 6:
            raise ValueError("chapter_num: prefix maxim 6 caractere")
    if not (0 <= g.x <= 1 and 0 <= g.y <= 1):
        raise ValueError("x și y sunt normalizate: între 0 și 1")
    if not 0.02 <= g.size <= 0.5:
        raise ValueError("size (raza cercului) trebuie să fie între 0.02 și 0.5 din latura mică")
    if g.panel_alpha is not None and not re.fullmatch(r"&H[0-9A-Fa-f]{2}&", g.panel_alpha):
        raise ValueError("panel_alpha trebuie să fie de forma &Hxx& (ex. &H40&)")
    if g.color is not None:
        norm_hex(g.color)


def _txt(s: str, keep_spaces: bool = False) -> str:
    """Text de la utilizator/agent -> text ASS sigur: fără caractere de control, fără override-uri."""
    s = "".join(ch if ch.isprintable() else " " for ch in s or "")
    s = s.replace("\\", "/").replace("{", "(").replace("}", ")")
    return s if keep_spaces else s.strip()


def _wrap(text: str, width: int) -> list[str]:
    """Rupere greedy pe cuvinte (cuvintele prea lungi se taie)."""
    lines: list[str] = []
    for w in _txt(text).split():
        while len(w) > width:
            lines, w = lines + [w[:width]], w[width:]
        if lines and len(lines[-1]) + 1 + len(w) <= width:
            lines[-1] += " " + w
        else:
            lines.append(w)
    return lines or [""]


def _est(text: str, size: float, heavy: bool = True) -> float:
    """Lățimea estimată a textului (fără măsurare reală; Archivo Black e lat)."""
    return len(text) * size * (0.54 if heavy else 0.44)


def _chars(width: float, size: float) -> int:
    """Câte caractere încap pe un rând de lățime dată (pentru rupere)."""
    return max(8, int(width / (size * 0.54)))


def _n(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _rect(w: float, h: float, r: float = 0) -> str:
    if r <= 0:
        return f"m 0 0 l {_n(w)} 0 l {_n(w)} {_n(h)} l 0 {_n(h)}"
    r = min(r, w / 2, h / 2)
    c = r * (1 - K)
    pts = [("m", r, 0), ("l", w - r, 0), ("b", w - c, 0, w, c, w, r), ("l", w, h - r), ("b", w, h - c, w - c, h, w - r, h),
           ("l", r, h), ("b", c, h, 0, h - c, 0, h - r), ("l", 0, r), ("b", 0, c, c, 0, r, 0)]
    return " ".join(p[0] + " " + " ".join(_n(v) for v in p[1:]) for p in pts)


def _circle(cx: float, cy: float, r: float, rev: bool = False) -> str:
    k, s = K * r, (-1 if rev else 1)
    q = [(cx + r, cy + s * k, cx + k, cy + s * r, cx, cy + s * r), (cx - k, cy + s * r, cx - r, cy + s * k, cx - r, cy),
         (cx - r, cy - s * k, cx - k, cy - s * r, cx, cy - s * r), (cx + k, cy - s * r, cx + r, cy - s * k, cx + r, cy)]
    return f"m {_n(cx + r)} {_n(cy)} " + " ".join("b " + " ".join(_n(v) for v in b) for b in q)


class _Doc:
    def __init__(self, tl: Timeline, W: int, H: int):
        self.W, self.H, self.U = W, H, min(W, H)
        self.lines: list[str] = []

    def ev(self, layer: int, a: float, b: float, style: str, tags: str, body: str = "") -> None:
        self.lines.append(f"Dialogue: {layer},{_ts(a)},{_ts(b)},{style},,0,0,0,,{{{tags}}}{body}")

    def shape(self, layer, a, b, tags, draw, col, alpha="&H00&") -> None:
        self.ev(layer, a, b, "D", f"{tags}\\1c{col}\\1a{alpha}\\p1", draw)

    def place(self, pos: str, bw: float, bh: float) -> tuple[float, float]:
        """Colțul stânga-sus al unui bloc bw x bh pentru o poziție, cu margini sigure."""
        W, H = self.W, self.H
        mx, my = 0.06 * W, 0.08 * H
        x = mx if "left" in pos else W - mx - bw if "right" in pos else (W - bw) / 2
        y = my if pos in TOP else H - 1.4 * my - bh if pos in BOTTOM else (H - bh) / 2
        return max(0.0, x), max(0.0, y)


def _pop(t: int = 0) -> str:
    """Apariție cu bounce: 0 -> 112% -> 96% -> 100%, începând la t ms."""
    return (f"\\fscx0\\fscy0\\t({t},{t + 160},\\fscx112\\fscy112)\\t({t + 160},{t + 280},\\fscx96\\fscy96)"
            f"\\t({t + 280},{t + 360},\\fscx100\\fscy100)")


def _lower_third(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, pos = d.U, ("lower_left" if g.position == "center" else g.position)
    s1, s2, pad, th = 0.062 * U, 0.04 * U, 0.03 * U, max(2, round(0.014 * U))
    name = _wrap(g.text, _chars(0.8 * d.W, s1))
    s1 = min(s1, 0.8 * d.W / max(1, max(len(x) for x in name)) / 0.54)
    sub = _wrap(g.subtext, 40) if g.subtext.strip() else []
    tw = max([_est(x, s1) for x in name] + [_est(x, s2, False) for x in sub])
    pw = tw + 2 * pad
    ph = th + pad + len(name) * s1 * 1.2 + (len(sub) * s2 * 1.3 + 0.3 * pad if sub else 0) + pad
    x, y = d.place(pos, pw, ph)
    a, b, D = g.start, g.end, int(g.duration * 1000)

    def wipe(y1):  # intră din stânga, iese spre dreapta în ultimele 0.3 s
        return (f"\\an7\\pos({_n(x)},{_n(y)})\\clip({_n(x)},{_n(y)},{_n(x)},{_n(y1)})"
                f"\\t(0,350,\\clip({_n(x)},{_n(y)},{_n(x + pw)},{_n(y1)}))"
                f"\\t({D - 300},{D},\\clip({_n(x + pw)},{_n(y)},{_n(x + pw)},{_n(y1)}))")
    d.shape(L, a, b, wipe(y + ph), _rect(pw, ph), "&H000000&", _panel(g))
    d.shape(L + 1, a, b, wipe(y + th), _rect(pw, th), acc)
    tx, ty, dx = x + pad, y + th + pad, 0.05 * U
    out = (f"\\clip({_n(x)},{_n(y)},{_n(x + pw)},{_n(y + ph)})"
           f"\\t({D - 300},{D},\\clip({_n(x + pw)},{_n(y)},{_n(x + pw)},{_n(y + ph)}))")
    d.ev(L + 2, a, b, "H", f"\\an7\\move({_n(tx - dx)},{_n(ty)},{_n(tx)},{_n(ty)},100,450)\\fs{_n(s1)}{out}\\fad(250,0)",
         "\\N".join(name))
    if sub:
        sy = ty + len(name) * s1 * 1.2 + 0.3 * pad
        d.ev(L + 2, a, b, "S", f"\\an7\\move({_n(tx - dx)},{_n(sy)},{_n(tx)},{_n(sy)},250,600)\\fs{_n(s2)}"
             f"{out}\\fad(450,0)", "\\N".join(sub))


def _title_card(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W = d.U, d.W
    big = 0.42 * U if g.behind else 0.11 * U  # în spatele persoanei: text uriaș, ca să treacă prin spatele ei
    lines = _wrap(g.text, _chars(0.94 * W, big))
    size = min(big, 0.94 * W / max(1, max(len(x) for x in lines)) / 0.54)
    sub = _wrap(g.subtext, 44) if g.subtext.strip() else []
    s2, gap = 0.045 * U, 0.035 * U
    th = len(lines) * size * 1.15
    bh = th + gap * 2 + (len(sub) * s2 * 1.3 if sub else 0)
    x, y = d.place(g.position, max(_est(x, size) for x in lines), bh)
    cx, a, b = W / 2 if g.position in ("top", "center", "bottom") else x + max(_est(x, size) for x in lines) / 2, g.start, g.end
    d.ev(L + 2, a, b, "H", f"\\an5\\pos({_n(cx)},{_n(y + th / 2)})\\fs{_n(size)}\\fscx70\\fscy70"
         "\\t(0,180,\\fscx115\\fscy115)\\t(180,340,\\fscx100\\fscy100)\\fad(150,300)", "\\N".join(lines))
    bw, bt = 0.12 * W, max(2, round(0.012 * U))
    d.shape(L + 1, a, b, f"\\an5\\pos({_n(cx)},{_n(y + th + gap)})\\fscx0\\t(200,500,\\fscx100)\\fad(0,300)",
            _rect(bw, bt), acc)
    if sub:
        d.ev(L + 2, a, b, "S", f"\\an8\\pos({_n(cx)},{_n(y + th + gap * 2)})\\fs{_n(s2)}\\fad(450,300)", "\\N".join(sub))


def _callout(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W, H = d.U, d.W, d.H
    s, pad, off, m = 0.045 * U, 0.03 * U, 0.07 * U, 0.03 * U
    lines = _wrap(g.text, 24)
    bw = max(_est(x, s) for x in lines) + 2 * pad
    bh = len(lines) * s * 1.25 + 2 * pad
    px, py = g.x * W, g.y * H
    bx = px + off if px + off + bw <= W - m else px - off - bw
    by = py - off - bh if py - off - bh >= m else py + off
    bx, by = min(max(bx, m), max(m, W - m - bw)), min(max(by, m), max(m, H - m - bh))
    cx, cy, a, b = bx + bw / 2, by + bh / 2, g.start, g.end
    # linia de la punct la cel mai apropiat colț al casetei (poligon subțire)
    qx, qy = min(max(px, bx), bx + bw), min(max(py, by), by + bh)
    ln = max(((qx - px) ** 2 + (qy - py) ** 2) ** 0.5, 1e-6)
    t = max(1.0, 0.005 * U)
    nx, ny = -(qy - py) / ln * t, (qx - px) / ln * t
    pts = [(px + nx, py + ny), (qx + nx, qy + ny), (qx - nx, qy - ny), (px - nx, py - ny)]
    ox, oy = min(p[0] for p in pts), min(p[1] for p in pts)
    draw = "m " + " l ".join(f"{_n(p[0] - ox)} {_n(p[1] - oy)}" for p in pts)
    if ln > 1:
        d.shape(L, a, b, f"\\an7\\pos({_n(ox)},{_n(oy)})\\fad(200,250)", draw, acc)
    r = 0.018 * U
    d.shape(L + 1, a, b, f"\\an5\\pos({_n(px)},{_n(py)}){_pop()}\\fad(0,250)", _circle(r, r, r), acc)
    box = f"\\an5\\pos({_n(cx)},{_n(cy)}){_pop(120)}"
    d.ev(L + 1, a, b, "D", f"{box}\\1c&H000000&\\1a&H30&\\3c{acc}\\bord{_n(max(1, 0.004 * U))}\\fad(0,250)\\p1",
         _rect(bw, bh, 0.02 * U))
    d.ev(L + 2, a, b, "H", f"{box}\\fs{_n(s)}\\fad(0,250)", "\\N".join(lines))


def _fmt(v: float, dec: int) -> str:
    s = f"{abs(v):,.{dec}f}".replace(",", " ").replace(".", ",").replace(" ", ".")  # 12.345,6 (ro)
    return ("-" if v < 0 and float(f"{abs(v):.{dec}f}") else "") + s


def _counter(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U = d.U
    size, s2 = 0.14 * U, 0.045 * U
    pre, suf = _txt(g.prefix, True), _txt(g.suffix, True)  # „12.500 lei”: spațiul contează
    longest = max(len(_fmt(g.value_from, g.decimals)), len(_fmt(g.value_to, g.decimals))) + len(pre + suf)
    size = min(size, 0.9 * d.W / max(1, longest) / 0.54)
    label = _wrap(g.text, 40) if g.text.strip() else []
    bh = size * 1.1 + (len(label) * s2 * 1.3 if label else 0)
    x, y = d.place(g.position, _est("0" * longest, size), bh)
    cx, cy = x + _est("0" * longest, size) / 2, y + size * 0.55
    ramp = 0.7 * g.duration
    n = max(2, int(ramp * 14))
    for i in range(n + 1):
        a = g.start + ramp * i / n
        b = g.start + ramp * (i + 1) / n if i < n else g.end
        p = 1 - (1 - i / n) ** 3  # ease-out
        v = g.value_to if i == n else g.value_from + (g.value_to - g.value_from) * p
        fad = "\\fad(150,0)" if i == 0 else "\\fad(0,300)" if i == n else ""
        d.ev(L + 2, a, b, "H", f"\\an5\\pos({_n(cx)},{_n(cy)})\\fs{_n(size)}\\1c{acc}{fad}",
             pre + _fmt(v, g.decimals) + suf)
    if label:
        d.ev(L + 2, g.start, g.end, "S", f"\\an8\\pos({_n(cx)},{_n(y + size * 1.15)})\\fs{_n(s2)}\\fad(300,300)",
             "\\N".join(label))


def _progress_bar(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    W, th = d.W, max(2, round(0.012 * d.U))
    y = d.H - th if g.position == "bottom" else 0
    D = int(g.duration * 1000)
    d.shape(L, g.start, g.end, f"\\an7\\pos(0,{y})", _rect(W, th), "&H000000&", "&H80&")
    d.shape(L + 1, g.start, g.end, f"\\an7\\pos(0,{y})\\clip(0,{y},0,{y + th})\\t(0,{D},\\clip(0,{y},{W},{y + th}))",
            _rect(W, th), acc)


def _cta(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U = d.U
    text = _txt(g.text) or "Urmărește pentru mai mult"
    s = min(0.05 * U, 0.8 * d.W / max(1, len(text)) / 0.54)
    pw, ph = _est(text, s) + 2.4 * s, 1.9 * s
    x, y = d.place("bottom" if g.position == "center" else g.position, pw, ph)
    tags = f"\\an5\\pos({_n(x + pw / 2)},{_n(y + ph / 2)}){_pop()}\\fad(0,250)"
    d.shape(L + 1, g.start, g.end, tags, _rect(pw, ph, ph / 2), acc)
    d.ev(L + 2, g.start, g.end, "H", f"{tags}\\fs{_n(s)}\\1c&H101010&\\bord0", text)


def _list(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U = d.U
    s, st = 0.062 * U, 0.075 * U  # lizibil și pe telefon (9:16: U = lățimea)
    items = [_txt(i) for i in g.items if i.strip()][:6]
    title = _txt(g.text)
    lh, r = s * 1.6, 0.18 * s
    bw = max([_est(i, s, False) + 3 * r + 0.8 * s for i in items] + [_est(title, st)])
    bh = (st * 1.6 if title else 0) + len(items) * lh
    x, y = d.place(g.position, bw, bh)
    steps = len(items) + (1 if title else 0)
    step = 0.6 * g.duration / max(1, steps)
    if title:
        d.ev(L + 2, g.start, g.end, "H", f"\\an7\\pos({_n(x)},{_n(y)})\\fs{_n(st)}\\fad(250,300)", title)
        y += st * 1.6
    for i, item in enumerate(items):
        a = g.start + step * (i + (1 if title else 0))
        iy = y + i * lh
        d.shape(L + 1, a, g.end, f"\\an5\\pos({_n(x + r)},{_n(iy + s * 0.6)}){_pop()}\\fad(0,300)", _circle(r, r, r), acc)
        tx = x + 2 * r + 0.8 * s
        d.ev(L + 2, a, g.end, "S", f"\\an7\\move({_n(tx - 0.04 * U)},{_n(iy)},{_n(tx)},{_n(iy)},0,250)\\fs{_n(s)}"
             "\\fad(200,300)", item)


def _kinetic(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    lines = _wrap(g.text, min(16, _chars(0.9 * d.W, 0.1 * d.U)))
    words = sum(len(x.split()) for x in lines)
    size = min(0.1 * d.U, 0.9 * d.W / max(1, max(len(x) for x in lines)) / 0.54)
    bh = len(lines) * size * 1.15
    x, y = d.place(g.position, max(_est(x, size) for x in lines), bh)
    cx = d.W / 2 if g.position in ("top", "center", "bottom") else x + max(_est(x, size) for x in lines) / 2
    step, k, out = 0.7 * g.duration * 1000 / max(1, words), 0, []
    for line in lines:
        ws = []
        for w in line.split():
            t = int(k * step)
            ws.append(f"{{\\alpha&HFF&\\t({t},{t + 100},\\alpha&H00&\\fscy125)\\t({t + 100},{t + 220},\\fscy100)}}{w}")
            k += 1
        out.append(" ".join(ws))
    d.ev(L + 2, g.start, g.end, "H", f"\\an5\\pos({_n(cx)},{_n(y + bh / 2)})\\fs{_n(size)}\\fad(0,300)",
         "\\N".join(out))


def _circle_g(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U = d.U
    R = g.size * U
    th = max(2.0, 0.018 * U, R * 0.08)
    px, py, D = g.x * d.W, g.y * d.H, int(g.duration * 1000)
    anim = "\\fscx0\\fscy0\\t(0,280,\\fscx112\\fscy112)\\t(280,420,\\fscx100\\fscy100)"
    t = 600
    while t + 1200 <= D - 300:  # puls blând
        anim += f"\\t({t},{t + 600},\\fscx106\\fscy106)\\t({t + 600},{t + 1200},\\fscx100\\fscy100)"
        t += 1200
    ring = _circle(R, R, R) + " " + _circle(R, R, R - th, rev=True)
    d.shape(L + 1, g.start, g.end, f"\\an5\\pos({_n(px)},{_n(py)}){anim}\\fad(0,250)\\bord0\\shad0", ring, acc)
    if g.text.strip():
        s = 0.045 * U
        ly = py + R + 0.02 * U if py + R + 0.02 * U + s * 1.3 <= d.H else py - R - 0.02 * U - s * 1.3
        d.ev(L + 2, g.start, g.end, "H", f"\\an8\\pos({_n(px)},{_n(ly)})\\fs{_n(s)}\\fad(300,250)", _txt(g.text)[:60])


# ---------------------------------------------------------------- forme de date, linii care se desenează, carduri și reveal-uri
def _rect_at(x0: float, y0: float, w: float, h: float, rev: bool = False) -> str:
    """Dreptunghi umplut la poziția (x0, y0); rev=True inversează sensul (devine gaură într-un cadru)."""
    if rev:
        return (f"m {_n(x0)} {_n(y0)} l {_n(x0)} {_n(y0 + h)} l {_n(x0 + w)} {_n(y0 + h)} l {_n(x0 + w)} {_n(y0)}")
    return f"m {_n(x0)} {_n(y0)} l {_n(x0 + w)} {_n(y0)} l {_n(x0 + w)} {_n(y0 + h)} l {_n(x0)} {_n(y0 + h)}"


def _frame(w: float, h: float, t: float) -> str:
    """Ramă subțire: dreptunghi plin + dreptunghi interior cu sens invers (gaură)."""
    return _rect_at(0, 0, w, h) + " " + _rect_at(t, t, max(w - 2 * t, 0.1), max(h - 2 * t, 0.1), rev=True)


def _grid(w: float, h: float, cols: int, rows: int, t: float) -> str:
    """Ramă + grilă interioară (linii subțiri desenate ca dreptunghiuri), un singur desen ASS."""
    d = _frame(w, h, t)
    for i in range(1, cols):
        d += " " + _rect_at(i * w / cols - t / 2, 0, t, h)
    for j in range(1, rows):
        d += " " + _rect_at(0, j * h / rows - t / 2, w, t)
    return d


def _line_grid(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W, H = d.U, d.W, d.H
    bw = bh = 0.54 * U
    x, y = d.place(g.position, bw, bh)
    th = max(1.5, 0.0035 * U)
    a, b, D = g.start, g.end, int(g.duration * 1000)
    d.shape(L + 1, a, b, f"\\an7\\pos({_n(x)},{_n(y)})"
            f"\\clip({_n(x)},{_n(y)},{_n(x)},{_n(y + bh)})"
            f"\\t(0,{int(0.7 * D)},\\clip({_n(x)},{_n(y)},{_n(x + bw)},{_n(y + bh)}))\\fad(150,300)",
            _grid(bw, bh, 4, 3, th), acc)
    # o zonă a grilei se aprinde (accent discret)
    d.shape(L + 2, a + 0.55 * g.duration, b, f"\\an7\\pos({_n(x + bw / 4)},{_n(y + bh / 3)})\\fad(350,300)",
            _rect(bw / 4, bh / 3), acc, "&H88&")
    if g.text.strip():
        s = min(0.03 * U, 0.5 * W / max(1, len(g.text)) / 0.54)
        ly = y - s * 1.4 if y - s * 1.4 >= 0.02 * H else y + bh + 0.02 * U
        d.ev(L + 2, a, b, "S", f"\\an7\\pos({_n(x)},{_n(ly)})\\fs{_n(s)}\\1c{acc}\\fad(450,300)", _txt(g.text))


def _spec_card(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W = d.U, d.W
    s, pad, ts = 0.04 * U, 0.035 * U, 0.055 * U
    title = _txt(g.text)
    rows = [_txt(i) for i in g.items if i.strip()][:8]
    tw = max([_est(r, s, False) for r in rows] + [_est(title, ts)])
    bw = min(tw + 3.4 * pad, 0.9 * W)
    lh, r = s * 1.7, 0.02 * U
    bh = ts * 1.6 + 0.02 * U + len(rows) * lh + 1.6 * pad
    x, y = d.place(g.position, bw, bh)
    a, b = g.start, g.end
    d.shape(L, a, b, f"\\an7\\pos({_n(x)},{_n(y)})\\fad(200,300)", _rect(bw, bh, r), "&H000000&", _panel(g))
    d.shape(L + 1, a, b, f"\\an7\\pos({_n(x)},{_n(y)})\\fad(200,300)", _rect(max(2.0, 0.012 * U), bh), acc)
    px, py = x + 1.5 * pad, y + 0.8 * pad
    d.ev(L + 2, a, b, "H", f"\\an7\\pos({_n(px)},{_n(py)})\\fs{_n(ts)}\\1c{acc}\\fad(250,300)", title)
    ry = py + ts * 1.55
    for i, row in enumerate(rows):
        ra = a + 0.35 + 0.15 * i
        if i:
            d.shape(L + 1, ra, b, f"\\an7\\pos({_n(px)},{_n(ry - 0.15 * s)})",
                    _rect(bw - 2.6 * pad, max(1.0, 0.0016 * U)), acc, "&H66&")
        d.ev(L + 2, ra, b, "S", f"\\an7\\move({_n(px - 0.02 * U)},{_n(ry)},{_n(px)},{_n(ry)},0,300)"
             f"\\fs{_n(s)}\\fad(250,300)", row)
        ry += lh


def _quote_card(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W = d.U, d.W
    size = (0.115 * U if g.behind else 0.062 * U)
    lines = _wrap(g.text, _chars(0.72 * W, size))
    size = min(size, 0.72 * W / max(1, max(len(x) for x in lines)) / 0.54)
    au = _wrap(g.subtext, 40) if g.subtext.strip() else []
    s2, gap = 0.036 * U, 0.045 * U
    th = len(lines) * size * 1.2
    bw = max([_est(x, size) for x in lines] + [_est(x, s2, False) for x in au]) + 0.06 * U
    bh = th + gap + (len(au) * s2 * 1.3 if au else 0)
    x, y = d.place(g.position, bw, bh)
    cx = W / 2 if g.position in ("top", "center", "bottom") else x + bw / 2
    a, b = g.start, g.end
    if not g.behind:  # card pe imagine: panou pentru contrast garantat (fără el, textul dispare pe fundal luminos)
        pad = 0.035 * U
        px0, py0 = cx - bw / 2 - pad, y - size * 1.7 - pad
        d.shape(L, a, b, f"\\an7\\pos({_n(px0)},{_n(py0)})\\fad(500,400)",
                _rect(bw + 2 * pad, bh + size * 1.7 + 2 * pad, 0.02 * U), "&H000000&", _panel(g))
    # „ are cerneala jos în glif: ancorat de jos (\an2), deasupra primului rând, nu centrat pe el (intra peste text)
    d.ev(L + 1, a, b, "H", f"\\an2\\pos({_n(cx)},{_n(y - 0.1 * size)})\\fs{_n(size * 2.2)}\\1c{acc}\\alpha&H55&\\fad(500,400)",
         "\u201E")
    d.ev(L + 2, a, b, "H", f"\\an5\\move({_n(cx)},{_n(y + th / 2 + 0.03 * U)},{_n(cx)},{_n(y + th / 2)},400,700)"
         f"\\fs{_n(size)}\\fad(500,400)", "\\N".join(lines))
    if au:
        ay = y + th + gap
        lw = 0.06 * W
        d.shape(L + 1, a, b, f"\\an5\\pos({_n(cx - _est(au[0], s2, False) / 2 - lw)},{_n(ay + s2 * 0.55)})"
                f"\\fad(700,400)", _rect(lw, max(1.5, 0.003 * U)), acc, "&H40&")
        d.ev(L + 2, a, b, "S", f"\\an5\\pos({_n(cx)},{_n(ay)})\\fs{_n(s2)}\\1c{acc}\\fad(700,400)", "\\N".join(au))


def _before_after(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W, H = d.U, d.W, d.H
    left = _txt(g.text) or "RENDER"
    right = _txt(g.subtext) or "REALITATE"
    a, b, D = g.start, g.end, int(g.duration * 1000)
    th = max(3.0, 0.006 * U)
    # văl întunecat pe jumătatea stângă; divizor accent care culisează din mijloc spre stânga
    d.shape(L, a, b, f"\\an7\\pos(0,0)\\fad(300,300)", _rect(0.5 * W, H), "&H000000&", "&H38&")
    x1, x2 = 0.5 * W, 0.34 * W
    d.shape(L + 1, a, b, f"\\an7\\move({_n(x1 - th / 2)},0,{_n(x2 - th / 2)},0,0,{D})\\fad(200,300)",
            _rect(th, H), acc)
    d.shape(L + 1, a, b, f"\\an5\\pos({_n(x1)},{_n(H / 2)}){_pop(150)}\\fad(0,300)",
            _circle(0.02 * U, 0.02 * U, 0.02 * U), acc)
    s = min(0.036 * U, 0.3 * W / max(1, len(left)) / 0.54)
    pad, py = 0.045 * U, 0.08 * H
    d.ev(L + 2, a, b, "H", f"\\an7\\pos({_n(pad)},{_n(py)})\\fs{_n(s)}\\fad(350,300)", left)
    d.ev(L + 2, a, b, "H", f"\\an7\\pos({_n(W - pad - _est(right, s))},{_n(py)})\\fs{_n(s)}\\1c{acc}\\fad(350,300)", right)


def _chapter_num(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W = d.U, d.W
    num = f"{int(round(g.value_to)):02d}"
    if g.prefix.strip():
        num = f"{_txt(g.prefix)}{num}"
    title = _txt(g.text)
    size = (0.44 * U if g.behind else 0.26 * U)
    size = min(size, 0.86 * W / max(1, len(num)) / 0.54)
    s2 = 0.04 * U
    nw = _est(num, size)
    x, y = d.place(g.position, nw, size * 1.15 + 0.08 * U + s2 * 1.3)
    cx = W / 2 if g.position in ("top", "center", "bottom") else x + nw / 2
    a, b, D = g.start, g.end, int(g.duration * 1000)
    top, bot = _n(y), _n(y + size * 1.15)
    d.ev(L + 2, a, b, "H", f"\\an5\\pos({_n(cx)},{_n(y + size * 0.55)})\\fs{_n(size)}"
         f"\\clip({_n(cx - nw / 2)},{top},{_n(cx - nw / 2)},{bot})"
         f"\\t(0,{int(0.55 * D)},\\clip({_n(cx - nw / 2)},{top},{_n(cx + nw / 2)},{bot}))\\fad(150,300)", num)
    ly, lw = y + size * 1.15, 0.22 * W
    d.shape(L + 1, a, b, f"\\an5\\pos({_n(cx)},{_n(ly)})"
            f"\\clip({_n(cx - lw / 2)},{_n(ly - 4)},{_n(cx - lw / 2)},{_n(ly + 4)})"
            f"\\t({int(0.4 * D)},{int(0.75 * D)},\\clip({_n(cx - lw / 2)},{_n(ly - 4)},{_n(cx + lw / 2)},{_n(ly + 4)}))",
            _rect(lw, max(2.0, 0.004 * U)), acc)
    d.ev(L + 2, a, b, "S", f"\\an5\\pos({_n(cx)},{_n(ly + 0.05 * U)})\\fs{_n(s2)}\\fad(700,400)", title)


def _mask_reveal(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W = d.U, d.W
    size = (0.3 * U if g.behind else 0.11 * U)
    lines = _wrap(g.text, _chars(0.86 * W, size))
    size = min(size, 0.86 * W / max(1, max(len(x) for x in lines)) / 0.54)
    th = len(lines) * size * 1.15
    bw = max(_est(x, size) for x in lines)
    x, y = d.place(g.position, bw, th + 0.03 * U)
    cx = W / 2 if g.position in ("top", "center", "bottom") else x + bw / 2
    a, b, D = g.start, g.end, int(g.duration * 1000)
    x0, x1 = _n(cx - bw / 2), _n(cx + bw / 2)
    d.ev(L + 2, a, b, "H", f"\\an5\\pos({_n(cx)},{_n(y + th / 2)})\\fs{_n(size)}"
         f"\\clip({x0},{_n(y)},{x0},{_n(y + th)})"
         f"\\t(0,{int(0.6 * D)},\\clip({x0},{_n(y)},{x1},{_n(y + th)}))\\fad(0,300)", "\\N".join(lines))
    by, bwid = y + th + 0.02 * U, min(bw, 0.5 * W)
    bx0 = cx - bwid / 2
    d.shape(L + 1, a, b, f"\\an5\\pos({_n(cx)},{_n(by)})"
            f"\\clip({_n(bx0)},{_n(by - 6)},{_n(bx0)},{_n(by + 6)})"
            f"\\t({int(0.35 * D)},{int(0.8 * D)},\\clip({_n(bx0)},{_n(by - 6)},{_n(bx0 + bwid)},{_n(by + 6)}))",
            _rect(bwid, max(2.0, 0.006 * U)), acc)


def _typewriter(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W = d.U, d.W
    text = _txt(g.text)
    n = max(1, len(text))
    size = min(0.075 * U, 0.84 * W / n / 0.54)
    tw = _est(text, size)
    x, y = d.place(g.position, tw, size * 1.3)
    a, b = g.start, g.end
    T = 0.6 * g.duration
    step = T / n
    for i in range(1, len(text) + 1):
        sa = a + (i - 1) * step
        sb = a + i * step if i < len(text) else b
        d.ev(L + 2, sa, sb, "H", f"\\an7\\pos({_n(x)},{_n(y)})\\fs{_n(size)}", text[:i])
    # cursor: bară care alunecă odată cu textul, apoi clipește pe loc
    cw, ch = max(2.0, 0.008 * U), size * 1.15
    tags = f"\\an7\\move({_n(x)},{_n(y)},{_n(x + tw)},{_n(y)},0,{int(T * 1000)})"
    t0 = int(T * 1000) + 200
    for k in range(min(int(max(g.duration - T, 0.0) / 0.34), 6)):
        t = t0 + k * 340
        tags += f"\\t({t},{t + 20},\\alpha&HFF&)\\t({t + 170},{t + 190},\\alpha&H00&)"
    d.shape(L + 1, a, b, tags, _rect(cw, ch), acc)


def _stat_badge(d: _Doc, g: Graphic, L: int, acc: str) -> None:
    U, W = d.U, d.W
    text = _txt(g.text)
    s = min(0.034 * U, 0.5 * W / max(1, len(text)) / 0.54)
    pw, ph = _est(text, s) + 2.7 * s, 1.9 * s
    x, y = d.place("upper_left" if g.position == "center" else g.position, pw, ph)
    a, b = g.start, g.end
    d.shape(L, a, b, f"\\an7\\pos({_n(x)},{_n(y)})\\fad(350,300)", _rect(pw, ph, ph / 2), "&H000000&", _panel(g))
    d.shape(L + 1, a, b, f"\\an5\\pos({_n(x + 1.15 * s)},{_n(y + ph / 2)})\\fad(400,300)",
            _circle(0.32 * s, 0.32 * s, 0.32 * s), acc)
    d.ev(L + 2, a, b, "S", f"\\an7\\move({_n(x + 2.0 * s)},{_n(y + ph / 2 - s * 0.62)},{_n(x + 2.0 * s)},"
         f"{_n(y + ph / 2 - s * 0.62)},0,350)\\fs{_n(s)}\\fad(350,300)", text)


RENDER = {"lower_third": _lower_third, "title_card": _title_card, "callout": _callout, "counter": _counter,
          "progress_bar": _progress_bar, "cta": _cta, "list": _list, "kinetic": _kinetic, "circle": _circle_g,
          "line_grid": _line_grid, "spec_card": _spec_card, "quote_card": _quote_card, "before_after": _before_after,
          "chapter_num": _chapter_num, "mask_reveal": _mask_reveal, "typewriter": _typewriter, "stat_badge": _stat_badge}


def graphic_box(g: Graphic, W: int, H: int, width: int = 240) -> tuple[float, float, float, float] | None:
    """Cutia ocupată efectiv de graficul g (x0, y0, x1, y1 normalizat), măsurată pe un cadru randat.

    Randăm documentul ASS al graficului peste un fundal gri și căutăm pixelii care ies din fundal
    (text alb + panouri negre), ca să știm cât spațiu ocupă cu adevărat — nu o estimare pe tip.
    """
    import tempfile
    from pathlib import Path

    import numpy as np

    from .captions import fonts_dir
    from .ff import run

    w = width
    h = max(2, int(round(w * H / W / 2)) * 2)
    tl = Timeline(width=W, height=H, graphics=[g])
    run_t = g.start + g.duration / 2
    with tempfile.TemporaryDirectory() as wd:
        Path(wd, "g.ass").write_text(graphics_ass(tl, W, H), encoding="utf-8")
        run(["-y", "-f", "lavfi", "-i", f"color=c=0x606060:s={W}x{H}:d={max(g.end, 0.05):.3f}:r=25",
             "-vf", f"ass=filename=g.ass:fontsdir={fonts_dir(tl, wd)},scale={w}:{h}",
             "-ss", f"{run_t:.3f}", "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "f.raw"], cwd=wd)
        raw = Path(wd, "f.raw")
        if not raw.exists():
            return None
        arr = np.fromfile(raw, np.uint8)
    if arr.size < w * h * 3:
        return None
    arr = arr[: w * h * 3].reshape(h, w, 3)
    mx = arr.max(axis=2)
    mask = (mx > 140) | (mx < 80)   # text/accent (alb) SAU panou (negru), față de fundalul gri 0x60
    ys, xs = np.nonzero(mask)
    if len(xs) < 10:
        return None
    return (float(xs.min()) / w, float(ys.min()) / h, float(xs.max() + 1) / w, float(ys.max() + 1) / h)


def graphics_ass(tl: Timeline, W: int, H: int) -> str:
    """Documentul ASS cu toate graficele timeline-ului (\"\" dacă nu există). W/H = dimensiunea randării."""
    if not tl.graphics:
        return ""
    d = _Doc(tl, W, H)
    U = d.U
    head = tl.caption_font or "Archivo Black"
    bord = _n(max(1.0, 0.004 * U))
    col = ass_color(tl.brand.primary) if tl.brand.primary else "&H00FFFFFF"
    fmt = ("Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
           "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
           "Alignment, MarginL, MarginR, MarginV, Encoding")
    styles = [
        f"Style: H,{head},{int(0.06 * U)},{col},{col},&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{bord},0,7,0,0,0,1",
        f"Style: S,Archivo,{int(0.04 * U)},{col},{col},&H00000000,&H80000000,0,0,0,0,100,100,0,0,1,{bord},0,7,0,0,0,1",
        "Style: D,Archivo,20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1",
    ]
    for i, g in enumerate(sorted(tl.graphics, key=lambda g: g.start)):
        acc = g.color or tl.brand.highlight or DEFAULT_ACCENT
        RENDER[g.kind](d, g, 10 + 3 * i, ass_color(acc, inline=True))
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]", fmt, *styles, "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text", *d.lines,
    ]) + "\n"
