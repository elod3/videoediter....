"""Efecte pe noduri (ca Fusion din Resolve): un graf per clip, compilat într-un fragment de filter_complex.

Graful e DATE, nu cod: fiecare nod are un tip din CATALOG și parametri numerici / enumerări / culori
validate aici. Niciun text de la utilizator sau de la agent nu ajunge nefiltrat în comanda ffmpeg.

Fragmentul se lipește în lanțul video al clipului (vezi render._fx): primește imaginea deja încadrată
la W×H și lasă la final un lanț deschis, pe care randarea îl continuă (setsar, fps, format...).
Parametrii spațiali sunt relativi la cadru (procente), ca preview-ul mic și finalul să arate la fel.
"""
from __future__ import annotations

import math
import re

MAX_NODES = 48

# tip -> descriere. `inputs`: porturile de intrare (în ordine); `mask`: ieșirea e o mască (gri).
# Parametri: {"min", "max", "def"} numeric, {"enum": [...], "def"} sau {"color": True, "def": "#RRGGBB"}.
CATALOG: dict[str, dict] = {
    "in": {"label": "Intrare (clipul)", "cat": "flux", "inputs": [], "params": {}},
    "out": {"label": "Ieșire", "cat": "flux", "inputs": ["in"], "params": {}},
    # ---- culoare ----
    "color": {"label": "Corecție primară", "cat": "culoare", "inputs": ["in"], "params": {
        "exposure": {"min": -3, "max": 3, "def": 0, "label": "expunere (stopuri)"},
        "contrast": {"min": 0, "max": 2, "def": 1, "label": "contrast"},
        "saturation": {"min": 0, "max": 3, "def": 1, "label": "saturație"},
        "gamma": {"min": 0.2, "max": 3, "def": 1, "label": "gamma"},
        "temperature": {"min": 2000, "max": 12000, "def": 6500, "label": "temperatură (K)"},
        "tint": {"min": -1, "max": 1, "def": 0, "label": "tentă (verde ↔ magenta)"},
    }},
    "wheels": {"label": "Roți lift / gamma / gain", "cat": "culoare", "inputs": ["in"], "params": {
        **{f"lift_{c}": {"min": -0.5, "max": 0.5, "def": 0, "label": f"lift {c}"} for c in "rgby"},
        **{f"gamma_{c}": {"min": -0.5, "max": 0.5, "def": 0, "label": f"gamma {c}"} for c in "rgby"},
        **{f"gain_{c}": {"min": -0.5, "max": 0.5, "def": 0, "label": f"gain {c}"} for c in "rgby"},
    }},
    "curves": {"label": "Curbe", "cat": "culoare", "inputs": ["in"], "params": {
        **{f"p{i}": {"min": 0, "max": 1, "def": i / 4, "label": f"punct {i * 25}%"} for i in range(5)},
        "channel": {"enum": ["master", "red", "green", "blue"], "def": "master", "label": "canal"},
    }},
    "hue": {"label": "Nuanță / saturație", "cat": "culoare", "inputs": ["in"], "params": {
        "hue": {"min": -180, "max": 180, "def": 0, "label": "rotire nuanță (°)"},
        "saturation": {"min": 0, "max": 3, "def": 1, "label": "saturație"},
        "brightness": {"min": -1, "max": 1, "def": 0, "label": "luminozitate"},
    }},
    # ---- blur și detaliu ----
    "blur": {"label": "Blur", "cat": "detaliu", "inputs": ["in"], "params": {
        "size": {"min": 0, "max": 10, "def": 1.5, "label": "rază (% din cadru)"},
    }},
    "sharpen": {"label": "Claritate", "cat": "detaliu", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 3, "def": 0.8, "label": "intensitate"},
    }},
    "glow": {"label": "Glow", "cat": "detaliu", "inputs": ["in"], "params": {
        "threshold": {"min": 0, "max": 1, "def": 0.7, "label": "prag de lumină"},
        "size": {"min": 0.1, "max": 10, "def": 2, "label": "rază (% din cadru)"},
        "intensity": {"min": 0, "max": 1, "def": 0.6, "label": "intensitate"},
    }},
    # ---- stil ----
    "vignette": {"label": "Vignetă", "cat": "stil", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 1, "def": 0.5, "label": "intensitate"},
    }},
    "grain": {"label": "Granulație", "cat": "stil", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 60, "def": 12, "label": "cantitate"},
    }},
    "chromatic": {"label": "Aberație cromatică", "cat": "stil", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 3, "def": 0.6, "label": "decalaj (% din cadru)"},
    }},
    "pixelate": {"label": "Pixelare", "cat": "stil", "inputs": ["in"], "params": {
        "size": {"min": 0.2, "max": 10, "def": 2, "label": "pixel (% din cadru)"},
    }},
    "edges": {"label": "Contururi", "cat": "stil", "inputs": ["in"], "params": {}},
    "invert": {"label": "Negativ", "cat": "stil", "inputs": ["in"], "params": {}},
    "mirror": {"label": "Oglindă", "cat": "stil", "inputs": ["in"], "params": {
        "axis": {"enum": ["horizontal", "vertical", "both"], "def": "horizontal", "label": "axă"},
    }},
    # ---- transformare ----
    "transform": {"label": "Transformare", "cat": "transformare", "inputs": ["in"], "params": {
        "zoom": {"min": 0.25, "max": 4, "def": 1, "label": "zoom"},
        "x": {"min": -1, "max": 1, "def": 0, "label": "poziție X"},
        "y": {"min": -1, "max": 1, "def": 0, "label": "poziție Y"},
        "rotate": {"min": -180, "max": 180, "def": 0, "label": "rotire (°)"},
    }},
    # ---- măști, chei, compoziție ----
    "window": {"label": "Fereastră (mască elipsă)", "cat": "mască", "inputs": [], "mask": True, "params": {
        "cx": {"min": 0, "max": 1, "def": 0.5, "label": "centru X"},
        "cy": {"min": 0, "max": 1, "def": 0.5, "label": "centru Y"},
        "w": {"min": 0.02, "max": 2, "def": 0.5, "label": "lățime"},
        "h": {"min": 0.02, "max": 2, "def": 0.5, "label": "înălțime"},
        "soft": {"min": 0, "max": 1, "def": 0.3, "label": "margine moale"},
        "invert": {"enum": ["nu", "da"], "def": "nu", "label": "inversată"},
    }},
    "luma_mask": {"label": "Mască după lumină", "cat": "mască", "inputs": ["in"], "mask": True, "params": {
        "low": {"min": 0, "max": 1, "def": 0.6, "label": "de la"},
        "high": {"min": 0, "max": 1, "def": 0.9, "label": "până la"},
        "invert": {"enum": ["nu", "da"], "def": "nu", "label": "inversată"},
    }},
    "chroma_key": {"label": "Cheie de culoare (green screen)", "cat": "mască", "inputs": ["in"], "params": {
        "color": {"color": True, "def": "#00FF00", "label": "culoarea scoasă"},
        "similarity": {"min": 0.01, "max": 1, "def": 0.2, "label": "toleranță"},
        "blend": {"min": 0, "max": 1, "def": 0.08, "label": "margine"},
    }},
    "solid": {"label": "Culoare plină", "cat": "compoziție", "inputs": [], "params": {
        "color": {"color": True, "def": "#000000", "label": "culoare"},
    }},
    "merge": {"label": "Amestec (merge)", "cat": "compoziție", "inputs": ["bg", "fg", "mask"], "params": {
        "mode": {"enum": ["normal", "screen", "multiply", "overlay", "add", "lighten", "darken", "difference",
                          "softlight"], "def": "normal", "label": "mod"},
        "opacity": {"min": 0, "max": 1, "def": 1, "label": "opacitate"},
    }},
}

OPTIONAL_PORTS = {("merge", "mask")}
_ID = re.compile(r"[A-Za-z0-9_]{1,24}")
_HEX = re.compile(r"#?[0-9A-Fa-f]{6}")


def clean_params(kind: str, params: dict) -> dict:
    """Parametrii validați: numerele se limitează la interval, enumerările și culorile se verifică.
    Cheile necunoscute se ignoră; lipsurile rămân la valoarea implicită (nu se scriu)."""
    spec = CATALOG[kind]["params"]
    out = {}
    for k, v in (params or {}).items():
        if k not in spec:
            continue
        s = spec[k]
        if "enum" in s:
            if v not in s["enum"]:
                raise ValueError(f"nodul {kind}: {k} trebuie să fie unul din {', '.join(s['enum'])}")
            out[k] = v
        elif s.get("color"):
            if not isinstance(v, str) or not _HEX.fullmatch(v):
                raise ValueError(f"nodul {kind}: {k} trebuie să fie o culoare #RRGGBB")
            out[k] = "#" + v.lstrip("#").upper()
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise ValueError(f"nodul {kind}: {k} trebuie să fie un număr")
            out[k] = min(max(float(v), s["min"]), s["max"])
    return out


def check_graph(nodes: list, edges: list) -> None:
    """Graful e valid: id-uri unice, exact o intrare și o ieșire, porturi existente, câte o legătură pe port,
    fără cicluri. `nodes`/`edges` sunt modelele din timeline (atribute id/type, src/dst/port)."""
    if len(nodes) > MAX_NODES:
        raise ValueError(f"cel mult {MAX_NODES} de noduri pe un clip")
    ids = {}
    for n in nodes:
        if not _ID.fullmatch(n.id):
            raise ValueError(f"id de nod invalid: {n.id!r}")
        if n.id in ids:
            raise ValueError(f"id de nod dublat: {n.id}")
        if n.type not in CATALOG:
            raise ValueError(f"tip de nod necunoscut: {n.type}. Există: {', '.join(CATALOG)}")
        ids[n.id] = n.type
    for kind in ("in", "out"):
        if sum(1 for t in ids.values() if t == kind) != 1:
            raise ValueError(f"graful trebuie să aibă exact un nod „{kind}”")
    taken = set()
    for e in edges:
        if e.src not in ids or e.dst not in ids:
            raise ValueError(f"legătură spre un nod inexistent: {e.src} → {e.dst}")
        if e.port not in CATALOG[ids[e.dst]]["inputs"]:
            raise ValueError(f"nodul {e.dst} ({ids[e.dst]}) nu are intrarea „{e.port}”")
        if ids[e.src] == "out":
            raise ValueError("nodul de ieșire nu are ieșire")
        if (e.dst, e.port) in taken:
            raise ValueError(f"intrarea {e.dst}.{e.port} are deja o legătură")
        taken.add((e.dst, e.port))
    feeds: dict[str, list[str]] = {}
    for e in edges:
        feeds.setdefault(e.dst, []).append(e.src)
    state: dict[str, int] = {}

    def visit(i: str) -> None:
        if state.get(i) == 1:
            raise ValueError("graful are un ciclu (un nod ajunge înapoi în el însuși)")
        if state.get(i) == 2:
            return
        state[i] = 1
        for j in feeds.get(i, []):
            visit(j)
        state[i] = 2

    for i in ids:
        visit(i)


def _num(x: float) -> str:
    return f"{x:.5g}"


def _rgb(h: str) -> str:
    return "0x" + h.lstrip("#").upper()


class _Ctx:
    def __init__(self, prefix: str, W: int, H: int, fps: float):
        self.p, self.W, self.H, self.fps = prefix, W, H, fps
        self.short = min(W, H)
        self.chains: list[str] = []
        self.n = 0

    def tmp(self) -> str:
        self.n += 1
        return f"{self.p}t{self.n}"


def _lgg(p: dict, ch: str) -> str:
    """lift / gamma / gain pe un canal (0..1): out = (in·(1+gain) + lift·(1-in)) ^ (1/(1+gamma))."""
    lift = p.get(f"lift_{ch}", 0) + p.get("lift_y", 0)
    gamma = p.get(f"gamma_{ch}", 0) + p.get("gamma_y", 0)
    gain = p.get(f"gain_{ch}", 0) + p.get("gain_y", 0)
    g = max(0.2, 1 + gamma * 2)
    return (f"'clip(pow(clip((val/maxval)*{_num(1 + gain * 2)}+{_num(lift)}*(1-val/maxval),0,1),"
            f"{_num(1 / g)}),0,1)*maxval'")


def _node(cx: _Ctx, kind: str, p: dict, ins: dict[str, str], out: str, src: str | None) -> None:
    """Adaugă lanțurile unui nod: din etichetele `ins` (port -> etichetă) în eticheta `out`."""
    W, H, short = cx.W, cx.H, cx.short
    i = ins.get("in")
    get = lambda k: p.get(k, CATALOG[kind]["params"][k]["def"])  # noqa: E731
    simple = None
    if kind == "color":
        parts = []
        if get("exposure"):
            parts.append(f"lutrgb=r='val*{_num(2 ** get('exposure'))}':g='val*{_num(2 ** get('exposure'))}'"
                         f":b='val*{_num(2 ** get('exposure'))}'")
        parts.append(f"eq=contrast={_num(get('contrast'))}:saturation={_num(get('saturation'))}"
                     f":gamma={_num(get('gamma'))}")
        if get("temperature") != 6500:
            parts.append(f"colortemperature=temperature={_num(get('temperature'))}")
        if get("tint"):
            parts.append(f"colorbalance=gm={_num(-get('tint') * 0.4)}")
        simple = ",".join(parts)
    elif kind == "wheels":
        simple = f"lutrgb=r={_lgg(p, 'r')}:g={_lgg(p, 'g')}:b={_lgg(p, 'b')}"
    elif kind == "curves":
        pts = " ".join(f"{k / 4:g}/{_num(get(f'p{k}'))}" for k in range(5))
        simple = f"curves={get('channel') if get('channel') != 'master' else 'master'}='{pts}'"
    elif kind == "hue":
        simple = f"hue=h={_num(get('hue'))}:s={_num(get('saturation'))}:b={_num(get('brightness') * 10)}"
    elif kind == "blur":
        simple = f"gblur=sigma={_num(max(0.01, short * get('size') / 100))}"
    elif kind == "sharpen":
        simple = f"unsharp=5:5:{_num(get('amount'))}"
    elif kind == "glow":
        a, b, g = cx.tmp(), cx.tmp(), cx.tmp()
        t = get("threshold")
        cx.chains.append(f"[{i}]format=gbrp,split[{a}][{b}]")
        cx.chains.append(f"[{b}]lutrgb=r='if(gt(val,{_num(t)}*maxval),val,0)':g='if(gt(val,{_num(t)}*maxval),val,0)'"
                         f":b='if(gt(val,{_num(t)}*maxval),val,0)',gblur=sigma={_num(short * get('size') / 100)}[{g}]")
        cx.chains.append(f"[{a}][{g}]blend=all_mode=screen:all_opacity={_num(get('intensity'))}[{out}]")
        return
    elif kind == "vignette":
        simple = f"vignette=angle={_num(max(0.01, get('amount')) * math.pi / 2.2)}"
    elif kind == "grain":
        simple = f"noise=alls={round(get('amount'))}:allf=t"
    elif kind == "chromatic":
        px = max(1, round(short * get("amount") / 100))
        simple = f"rgbashift=rh=-{px}:bh={px}"
    elif kind == "pixelate":
        n = max(2, round(short * get("size") / 100))
        simple = f"scale={max(2, W // n)}:{max(2, H // n)}:flags=area,scale={W}:{H}:flags=neighbor"
    elif kind == "edges":
        simple = "edgedetect=mode=colormix:high=0.2:low=0.05"
    elif kind == "invert":
        simple = "negate"
    elif kind == "mirror":
        simple = {"horizontal": "hflip", "vertical": "vflip", "both": "hflip,vflip"}[get("axis")]
    elif kind == "transform":
        z, x, y, r = get("zoom"), get("x"), get("y"), get("rotate")
        sw, sh = max(2, round(W * z / 2) * 2), max(2, round(H * z / 2) * 2)
        parts = [f"scale={sw}:{sh}"]
        if z >= 1:  # fereastra W×H mutată în imaginea mărită
            ox, oy = (sw - W) / 2 * (1 - x), (sh - H) / 2 * (1 - y)
            parts.append(f"crop={W}:{H}:{_num(ox)}:{_num(oy)}")
        else:  # imaginea micșorată, pe negru, deplasată
            ox, oy = (W - sw) / 2 * (1 + x), (H - sh) / 2 * (1 + y)
            parts.append(f"pad={W}:{H}:{_num(ox)}:{_num(oy)}:black")
        if r:
            parts.append(f"rotate=a={_num(r * math.pi / 180)}:fillcolor=black")
        simple = ",".join(parts)
    elif kind == "window":  # elipsă moale, calculată la 1/4 din rezoluție (masca e oricum moale)
        qw, qh = max(8, W // 4), max(8, H // 4)
        rx, ry = max(0.01, get("w") / 2), max(0.01, get("h") / 2)
        soft = max(0.001, get("soft"))
        d = f"hypot((X/W-{_num(get('cx'))})/{_num(rx)},(Y/H-{_num(get('cy'))})/{_num(ry)})"
        v = f"clip((1-{d})/{_num(soft)}+0.5,0,1)"  # 1 înăuntru, 0 afară, trecere de lățime `soft` pe margine
        if get("invert") == "da":
            v = f"(1-{v})"
        cx.chains.append(f"[{src}]scale={qw}:{qh},format=gray,geq=lum='255*{v}',scale={W}:{H}:flags=bilinear[{out}]")
        return
    elif kind == "luma_mask":
        lo, hi = sorted((get("low"), get("high")))
        hi = max(hi, lo + 0.01)
        v = f"clip((val/maxval-{_num(lo)})/{_num(hi - lo)},0,1)"
        if get("invert") == "da":
            v = f"(1-{v})"
        simple = f"format=gray,lut=y='{v}*maxval'"
    elif kind == "chroma_key":
        simple = (f"format=yuva420p,chromakey=color={_rgb(get('color'))}:similarity={_num(get('similarity'))}"
                  f":blend={_num(get('blend'))}")
    elif kind == "solid":
        cx.chains.append(f"[{src}]drawbox=x=0:y=0:w=iw:h=ih:color={_rgb(get('color'))}:t=fill[{out}]")
        return
    elif kind == "merge":
        bg, fg, m = ins.get("bg"), ins.get("fg"), ins.get("mask")
        if not bg or not fg:  # un singur strat legat: trece mai departe neschimbat
            cx.chains.append(f"[{bg or fg}]null[{out}]")
            return
        mode, op = get("mode"), get("opacity")
        if m:
            b1, b2, mixed, mk = cx.tmp(), cx.tmp(), cx.tmp(), cx.tmp()
            cx.chains.append(f"[{bg}]format=gbrp,split[{b1}][{b2}]")
            if mode == "normal":
                cx.chains.append(f"[{fg}]format=gbrp[{mixed}]")
            else:
                f2 = cx.tmp()
                cx.chains.append(f"[{fg}]format=gbrp[{f2}]")
                cx.chains.append(f"[{b2}][{f2}]blend=all_mode={mode}[{mixed}]")
                b2 = None
            cx.chains.append(f"[{m}]format=gray,lut=y='val*{_num(op)}',format=gbrp[{mk}]")
            if b2:  # bg-ul nefolosit de blend: îl închidem curat
                cx.chains.append(f"[{b2}]nullsink")
            cx.chains.append(f"[{b1}][{mixed}][{mk}]maskedmerge[{out}]")
        elif mode == "normal":
            f2 = cx.tmp()
            cx.chains.append(f"[{fg}]format=yuva420p,colorchannelmixer=aa={_num(op)}[{f2}]")
            cx.chains.append(f"[{bg}][{f2}]overlay=format=auto:shortest=1,format=yuv420p[{out}]")
        else:
            b2, f2 = cx.tmp(), cx.tmp()
            cx.chains.append(f"[{bg}]format=gbrp[{b2}]")
            cx.chains.append(f"[{fg}]format=gbrp[{f2}]")
            cx.chains.append(f"[{b2}][{f2}]blend=all_mode={mode}:all_opacity={_num(op)}[{out}]")
        return
    cx.chains.append(f"[{i}]{simple}[{out}]")


def compile_graph(graph, prefix: str, W: int, H: int, fps: float = 30.0, view: str | None = None) -> str:
    """Fragmentul de filter_complex pentru graf: începe cu „,” (continuă lanțul clipului) și se termină cu un
    lanț deschis. `view`: id-ul nodului a cărui ieșire se vrea (preview pe nod), altfel nodul „out”.
    Graf gol sau doar in → out: șir gol."""
    if graph is None:
        return ""
    types = {n.id: n.type for n in graph.nodes}
    params = {n.id: n.params for n in graph.nodes}
    feeds: dict[str, dict[str, str]] = {}
    for e in graph.edges:
        feeds.setdefault(e.dst, {})[e.port] = e.src
    target = view or next(i for i, t in types.items() if t == "out")
    if target not in types:
        raise ValueError(f"nod inexistent: {target}")
    root = next(i for i, t in types.items() if t == "in")

    # nodurile care contează: cele din care se ajunge la țintă; sursele (window, solid) cer o copie din „in”
    order: list[str] = []
    seen: set[str] = set()

    def visit(i: str) -> None:
        if i in seen:
            return
        seen.add(i)
        for port in CATALOG[types[i]]["inputs"]:
            if port in feeds.get(i, {}):
                visit(feeds[i][port])
        if types[i] in ("window", "solid"):
            visit(root)
        order.append(i)

    visit(target)
    if types[target] == "out" and feeds.get(target, {}).get("in") in (None, root):
        return ""  # nimic între intrare și ieșire
    if types[target] == "in":
        return ""

    uses: dict[str, int] = {i: 0 for i in order}
    for i in order:
        for port in CATALOG[types[i]]["inputs"]:
            if port in feeds.get(i, {}):
                uses[feeds[i][port]] += 1
        if types[i] in ("window", "solid"):
            uses[root] += 1
    cx = _Ctx(prefix, W, H, fps)
    labels: dict[str, list[str]] = {}

    def produce(i: str, label: str) -> None:
        n = uses[i]
        if n <= 1:
            labels[i] = [label]
            return
        copies = [f"{label}_{k}" for k in range(n)]
        cx.chains.append(f"[{label}]split={n}{''.join(f'[{c}]' for c in copies)}")
        labels[i] = copies

    def take(i: str) -> str:
        return labels[i].pop()

    head = f"{prefix}in"
    produce(root, head)
    for i in order:
        kind = types[i]
        if kind in ("in",):
            continue
        ins = {port: take(feeds[i][port]) for port in CATALOG[kind]["inputs"] if port in feeds.get(i, {})}
        src = take(root) if kind in ("window", "solid") else None
        if kind == "out":
            final = ins.get("in")
            break
        if kind != "merge" and CATALOG[kind]["inputs"] and "in" not in ins:
            # nod fără intrare legată: nu are ce procesa, se comportă ca un nod gol pe intrarea clipului
            raise ValueError(f"nodul {i} ({CATALOG[kind]['label']}) nu are intrarea legată")
        if kind == "merge" and not ins:
            raise ValueError(f"nodul {i} (merge) nu are nicio intrare legată")
        lab = f"{prefix}{i}"
        _node(cx, kind, params[i], ins, lab, src)
        produce(i, lab)
    else:
        final = take(target)
    # copiile rămase nefolosite (ex. „in” ramificat spre noduri care nu ajung la țintă) se închid
    for rest in labels.values():
        for lab in rest:
            cx.chains.append(f"[{lab}]nullsink")
    body = ";".join(cx.chains)
    return f",null[{head}];{body}{';' if body else ''}[{final}]format=yuv420p"
