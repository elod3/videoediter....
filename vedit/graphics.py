"""Motion graphics: șabloane animate (Graphic) -> document ASS randat de libass (filtrul `ass`).

Fără drawtext: formele sunt desene ASS (\\p1), animațiile sunt tag-uri de override (\\t, \\move, \\clip, \\fad).
Totul e determinist și scalat după W/H (dimensiunile după latura mică), deci merge și la preview (540p).
"""
from __future__ import annotations

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
}
DEFAULT_ACCENT = "#C8FF3D"
PANEL_ALPHA = "&H50&"   # panouri negre semi-transparente
K = 0.5523              # bezier pentru sfert de cerc
TOP = ("top", "upper_left", "upper_right")
BOTTOM = ("bottom", "lower_left", "lower_right")


def validate(g: Graphic) -> None:
    """Verifică un grafic înainte să intre pe timeline. ValueError cu mesaj clar în română."""
    if g.kind not in GRAPHICS:
        raise ValueError(f"tip de grafic necunoscut {g.kind!r}; disponibile: {', '.join(GRAPHICS)}")
    if g.end <= g.start or g.start < 0:
        raise ValueError("graficul trebuie să aibă start >= 0 și end > start")
    if g.duration < 0.5:
        raise ValueError("graficul trebuie să dureze cel puțin 0.5 s")
    limit = 100 if g.kind == "kinetic" else 60
    if len(g.text) > limit:
        raise ValueError(f"textul e prea lung ({len(g.text)} caractere, maxim {limit} pentru {g.kind})")
    if len(g.subtext) > 80:
        raise ValueError("subtext prea lung (maxim 80 de caractere)")
    if g.kind in ("lower_third", "title_card", "callout", "kinetic") and not g.text.strip():
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
    if not (0 <= g.x <= 1 and 0 <= g.y <= 1):
        raise ValueError("x și y sunt normalizate: între 0 și 1")
    if not 0.02 <= g.size <= 0.5:
        raise ValueError("size (raza cercului) trebuie să fie între 0.02 și 0.5 din latura mică")
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
    d.shape(L, a, b, wipe(y + ph), _rect(pw, ph), "&H000000&", PANEL_ALPHA)
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
    lines = _wrap(g.text, _chars(0.88 * W, 0.11 * U))
    size = min(0.11 * U, 0.88 * W / max(1, max(len(x) for x in lines)) / 0.54)
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


RENDER = {"lower_third": _lower_third, "title_card": _title_card, "callout": _callout, "counter": _counter,
          "progress_bar": _progress_bar, "cta": _cta, "list": _list, "kinetic": _kinetic, "circle": _circle_g}


def graphics_ass(tl: Timeline, W: int, H: int) -> str:
    """Documentul ASS cu toate graficele timeline-ului ("" dacă nu există). W/H = dimensiunea randării."""
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
