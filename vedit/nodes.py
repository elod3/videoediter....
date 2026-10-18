"""Efecte pe noduri (ca Fusion din Resolve): un graf per clip, compilat într-un fragment de filter_complex.

Graful e DATE, nu cod: fiecare nod are un tip din CATALOG și parametri numerici / enumerări / culori / id-uri
de asset validate aici. Niciun text de la utilizator sau de la agent nu ajunge nefiltrat în comanda ffmpeg.

Fragmentul se lipește în lanțul video al clipului (vezi render._fx): primește imaginea deja încadrată
la W×H și lasă la final un lanț deschis, pe care randarea îl continuă (setsar, fps, format...).
Parametrii spațiali sunt relativi la cadru (procente), ca preview-ul mic și finalul să arate la fel.

Keyframe-uri: `Node.anim[param]` = chei {t, v, ease}, cu `t` în secunde din SURSA clipului (nu din timeline):
o tăietură sau un trim nu mută animația de pe imagine. La compilare cheile trec în timpul lanțului
(t = (sursă - src0) / rate) și devin fie expresii în `t` (filtrele care evaluează pe fiecare cadru),
fie comenzi `sendcmd` cadru cu cadru (filtrele care acceptă comenzi). Parametrii marcați `anim` în catalog.
"""
from __future__ import annotations

import math
import re
from typing import Callable

MAX_NODES = 48
MAX_KEYS = 64

# tip -> descriere. `inputs`: porturile de intrare (în ordine); `mask`: ieșirea e o mască (gri).
# Parametri: {"min", "max", "def"} numeric (+ "anim": se poate anima), {"enum": [...], "def"},
# {"color": True, "def": "#RRGGBB"} sau {"asset": True, "def": ""} (id-ul unui fișier din proiect).
CATALOG: dict[str, dict] = {
    "in": {"label": "Intrare (clipul)", "cat": "flux", "inputs": [], "params": {}},
    "out": {"label": "Ieșire", "cat": "flux", "inputs": ["in"], "params": {}},
    # ---- culoare ----
    "color": {"label": "Corecție primară", "cat": "culoare", "inputs": ["in"], "params": {
        "exposure": {"min": -3, "max": 3, "def": 0, "label": "expunere (stopuri)", "anim": True},
        "contrast": {"min": 0, "max": 2, "def": 1, "label": "contrast", "anim": True},
        "saturation": {"min": 0, "max": 3, "def": 1, "label": "saturație", "anim": True},
        "gamma": {"min": 0.2, "max": 3, "def": 1, "label": "gamma", "anim": True},
        "temperature": {"min": 2000, "max": 12000, "def": 6500, "label": "temperatură (K)", "anim": True},
        "tint": {"min": -1, "max": 1, "def": 0, "label": "tentă (verde ↔ magenta)", "anim": True},
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
        "hue": {"min": -180, "max": 180, "def": 0, "label": "rotire nuanță (°)", "anim": True},
        "saturation": {"min": 0, "max": 3, "def": 1, "label": "saturație", "anim": True},
        "brightness": {"min": -1, "max": 1, "def": 0, "label": "luminozitate", "anim": True},
    }},
    # ---- blur și detaliu ----
    "blur": {"label": "Blur", "cat": "detaliu", "inputs": ["in"], "params": {
        "size": {"min": 0, "max": 10, "def": 1.5, "label": "rază (% din cadru)", "anim": True},
    }},
    "sharpen": {"label": "Claritate", "cat": "detaliu", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 3, "def": 0.8, "label": "intensitate"},
    }},
    "glow": {"label": "Glow", "cat": "detaliu", "inputs": ["in"], "params": {
        "threshold": {"min": 0, "max": 1, "def": 0.7, "label": "prag de lumină"},
        "size": {"min": 0.1, "max": 10, "def": 2, "label": "rază (% din cadru)", "anim": True},
        "intensity": {"min": 0, "max": 1, "def": 0.6, "label": "intensitate", "anim": True},
    }},
    # ---- stil ----
    "vignette": {"label": "Vignetă", "cat": "stil", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 1, "def": 0.5, "label": "intensitate", "anim": True},
    }},
    "grain": {"label": "Granulație", "cat": "stil", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 60, "def": 12, "label": "cantitate"},
    }},
    "chromatic": {"label": "Aberație cromatică", "cat": "stil", "inputs": ["in"], "params": {
        "amount": {"min": 0, "max": 3, "def": 0.6, "label": "decalaj (% din cadru)", "anim": True},
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
        "zoom": {"min": 0.25, "max": 4, "def": 1, "label": "zoom (animat: de la 1 în sus)", "anim": True},
        "x": {"min": -1, "max": 1, "def": 0, "label": "poziție X", "anim": True},
        "y": {"min": -1, "max": 1, "def": 0, "label": "poziție Y", "anim": True},
        "rotate": {"min": -180, "max": 180, "def": 0, "label": "rotire (°)", "anim": True},
    }},
    # ---- măști, chei, compoziție ----
    "window": {"label": "Fereastră (mască elipsă)", "cat": "mască", "inputs": [], "mask": True, "params": {
        "cx": {"min": 0, "max": 1, "def": 0.5, "label": "centru X", "anim": True},
        "cy": {"min": 0, "max": 1, "def": 0.5, "label": "centru Y", "anim": True},
        "w": {"min": 0.02, "max": 2, "def": 0.5, "label": "lățime", "anim": True},
        "h": {"min": 0.02, "max": 2, "def": 0.5, "label": "înălțime", "anim": True},
        "soft": {"min": 0, "max": 1, "def": 0.3, "label": "margine moale", "anim": True},
        "invert": {"enum": ["nu", "da"], "def": "nu", "label": "inversată"},
    }},
    "luma_mask": {"label": "Mască după lumină", "cat": "mască", "inputs": ["in"], "mask": True, "params": {
        "low": {"min": 0, "max": 1, "def": 0.6, "label": "de la"},
        "high": {"min": 0, "max": 1, "def": 0.9, "label": "până la"},
        "invert": {"enum": ["nu", "da"], "def": "nu", "label": "inversată"},
    }},
    "chroma_key": {"label": "Cheie de culoare (green screen)", "cat": "mască", "inputs": ["in"], "params": {
        "color": {"color": True, "def": "#00FF00", "label": "culoarea scoasă"},
        "similarity": {"min": 0.01, "max": 1, "def": 0.2, "label": "toleranță", "anim": True},
        "blend": {"min": 0, "max": 1, "def": 0.08, "label": "margine", "anim": True},
    }},
    "solid": {"label": "Culoare plină", "cat": "compoziție", "inputs": [], "params": {
        "color": {"color": True, "def": "#000000", "label": "culoare"},
    }},
    "media": {"label": "Alt clip (media)", "cat": "compoziție", "inputs": [], "params": {
        "asset": {"asset": True, "def": "", "label": "fișier"},
        "offset": {"min": 0, "max": 36000, "def": 0, "label": "pornește de la secunda"},
        "fit": {"enum": ["umple", "încadrează"], "def": "umple", "label": "în cadru"},
    }},
    "merge": {"label": "Amestec (merge)", "cat": "compoziție", "inputs": ["bg", "fg", "mask"], "params": {
        "mode": {"enum": ["normal", "screen", "multiply", "overlay", "add", "lighten", "darken", "difference",
                          "softlight"], "def": "normal", "label": "mod"},
        "opacity": {"min": 0, "max": 1, "def": 1, "label": "opacitate", "anim": True},
    }},
}

SOURCES = ("window", "solid", "media")  # noduri fără intrare: primesc o copie din „in” (timp, dimensiune)
EASES = ("smooth", "linear", "hold")
_ID = re.compile(r"[A-Za-z0-9_]{1,24}")
_ASSET = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_HEX = re.compile(r"#?[0-9A-Fa-f]{6}")


def clean_params(kind: str, params: dict) -> dict:
    """Parametrii validați: numerele se limitează la interval, enumerările, culorile și id-urile se verifică.
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
        elif s.get("asset"):
            if v in ("", None):
                continue
            if not isinstance(v, str) or not _ASSET.fullmatch(v):
                raise ValueError(f"nodul {kind}: {k} trebuie să fie id-ul unui fișier din proiect (ex. a2)")
            out[k] = v
        else:
            out[k] = _clamp_num(kind, k, v)
    return out


def _clamp_num(kind: str, k: str, v) -> float:
    s = CATALOG[kind]["params"][k]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"nodul {kind}: {k} trebuie să fie un număr")
    return min(max(float(v), s["min"]), s["max"])


def clean_anim(kind: str, anim: dict) -> dict:
    """Keyframe-urile validate: doar parametri animabili, valori limitate, chei sortate după timp, fără dubluri."""
    spec = CATALOG[kind]["params"]
    out = {}
    for k, keys in (anim or {}).items():
        if k not in spec or not spec[k].get("anim"):
            raise ValueError(f"nodul {kind}: parametrul „{k}” nu se poate anima")
        if not isinstance(keys, list) or not keys:
            continue
        if len(keys) > MAX_KEYS:
            raise ValueError(f"cel mult {MAX_KEYS} de keyframe-uri pe un parametru")
        rows = {}
        for key in keys:
            t, v, ease = key["t"], key["v"], key.get("ease", "smooth")
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0:
                raise ValueError(f"nodul {kind}: timpul unui keyframe trebuie să fie un număr ≥ 0")
            if ease not in EASES:
                raise ValueError(f"nodul {kind}: ease trebuie să fie {', '.join(EASES)}")
            rows[round(float(t), 3)] = {"t": round(float(t), 3), "v": _clamp_num(kind, k, v), "ease": ease}
        out[k] = [rows[t] for t in sorted(rows)]
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


def media_assets(graph) -> set[str]:
    """Fișierele din proiect folosite de nodurile „media” (pentru verificarea referințelor)."""
    if graph is None:
        return set()
    return {n.params["asset"] for n in graph.nodes if n.type == "media" and n.params.get("asset")}


def _num(x: float) -> str:
    return f"{x:.6g}"


def _rgb(h: str) -> str:
    return "0x" + h.lstrip("#").upper()


def interp(keys: list[tuple[float, float, str]], t: float) -> float:
    """Valoarea animată la momentul t (cheile: (t, v, ease) sortate)."""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, v0, e), (t1, v1, _) in zip(keys, keys[1:]):
        if t < t1:
            if e == "hold" or t1 <= t0:
                return v0
            p = (t - t0) / (t1 - t0)
            if e == "smooth":
                p = p * p * (3 - 2 * p)
            return v0 + (v1 - v0) * p
    return keys[-1][1]


def curve_expr(keys: list[tuple[float, float, str]], var: str = "t") -> str:
    """Aceeași curbă ca `interp`, ca expresie ffmpeg în variabila de timp `var`."""
    if len(keys) == 1:
        return _num(keys[0][1])
    expr = _num(keys[-1][1])
    for (t0, v0, e), (t1, v1, _) in reversed(list(zip(keys, keys[1:]))):
        if e == "hold" or t1 <= t0:
            seg = _num(v0)
        else:
            p = f"(({var}-{_num(t0)})/{_num(t1 - t0)})"
            if e == "smooth":
                p = f"({p}*{p}*(3-2*{p}))"
            seg = f"({_num(v0)}+{_num(v1 - v0)}*{p})"
        expr = f"if(lt({var},{_num(t1)}),{seg},{expr})"
    return f"if(lt({var},{_num(keys[0][0])}),{_num(keys[0][1])},{expr})"


class _Ctx:
    def __init__(self, prefix: str, W: int, H: int, fps: float, src0: float, rate: float,
                 media: Callable[[str, float], str] | None):
        self.p, self.W, self.H, self.fps = prefix, W, H, fps
        self.short = min(W, H)
        self.src0, self.rate, self.media = src0, max(rate, 1e-6), media
        self.chains: list[str] = []
        self.n = 0

    def tmp(self) -> str:
        self.n += 1
        return f"{self.p}t{self.n}"


class _P:
    """Parametrii unui nod la compilare: valoare statică, valoarea la t=0, expresie în timp sau sendcmd."""

    def __init__(self, cx: _Ctx, kind: str, params: dict, anim: dict, label: str):
        self.cx, self.kind, self.params, self.label = cx, kind, params, label
        self.spec = CATALOG[kind]["params"]
        # cheile în timpul lanțului (secunde de la începutul clipului pe timeline)
        self.keys = {k: [((r["t"] - cx.src0) / cx.rate, r["v"], r.get("ease", "smooth")) for r in rows]
                     for k, rows in (anim or {}).items() if rows}

    def __call__(self, k: str):
        """Valoarea la începutul lanțului (statică sau prima valoare a animației)."""
        if k in self.keys:
            return interp(self.keys[k], 0.0)
        return self.params.get(k, self.spec[k]["def"])

    def animated(self, *ks: str) -> bool:
        return any(k in self.keys and len(self.keys[k]) > 1 for k in ks)

    def expr(self, k: str, fn: Callable[[str], str] = lambda x: x, num: Callable[[float], float] = lambda v: v,
             var: str = "t") -> str:
        """Expresie de timp pentru filtrele care evaluează pe fiecare cadru. `fn` transformă expresia,
        `num` face aceeași transformare pe o valoare fixă (fără să evaluăm text)."""
        if self.animated(k):
            return f"'{fn(curve_expr(self.keys[k], var))}'"
        return _num(float(num(self(k))))

    def cmd(self, inst: str, opts: dict[str, tuple[str, Callable[[float], float]]]) -> str:
        """Prefix `sendcmd` care schimbă opțiunile filtrului `inst` cadru cu cadru, cât timp parametrii se mișcă.
        opts: opțiune ffmpeg -> (parametru, funcție valoare -> argument). Gol dacă nimic nu e animat."""
        live = {o: (k, f) for o, (k, f) in opts.items() if self.animated(k)}
        if not live:
            return ""
        t0 = max(0.0, min(self.keys[k][0][0] for k, _ in live.values()))
        t1 = max(self.keys[k][-1][0] for k, _ in live.values())
        if t1 <= 0:
            return ""
        step = max(1 / self.cx.fps, (t1 - t0) / 1500)  # cel mult ~1500 de comenzi pe nod
        rows, last = [], {}
        t = t0
        while t <= t1 + 1e-9:
            parts = []
            for o, (k, f) in live.items():
                val = _num(f(interp(self.keys[k], t)))
                if last.get(o) != val:
                    parts.append(f"{inst} {o} {val}")
                    last[o] = val
            if parts:
                rows.append(f"{t:.4f} " + ",".join(parts))
            t += step
        return f"sendcmd=c='{';'.join(rows)}',"


def _lgg(p: dict, ch: str) -> str:
    """lift / gamma / gain pe un canal (0..1): out = (in·(1+gain) + lift·(1-in)) ^ (1/(1+gamma))."""
    lift = p.get(f"lift_{ch}", 0) + p.get("lift_y", 0)
    gamma = p.get(f"gamma_{ch}", 0) + p.get("gamma_y", 0)
    gain = p.get(f"gain_{ch}", 0) + p.get("gain_y", 0)
    g = max(0.2, 1 + gamma * 2)
    return (f"'clip(pow(clip((val/maxval)*{_num(1 + gain * 2)}+{_num(lift)}*(1-val/maxval),0,1),"
            f"{_num(1 / g)}),0,1)*maxval'")


def _node(cx: _Ctx, kind: str, params: dict, anim: dict, ins: dict[str, str], out: str, src: str | None) -> None:
    """Adaugă lanțurile unui nod: din etichetele `ins` (port -> etichetă) în eticheta `out`."""
    W, H, short = cx.W, cx.H, cx.short
    i = ins.get("in")
    get = _P(cx, kind, params, anim, out)
    inst = out  # numele instanțelor de filtru țintite de sendcmd (unic în graf)
    simple = None
    if kind == "color":
        parts = []
        if get("exposure") or get.animated("exposure"):
            g = lambda v: 2 ** v  # noqa: E731
            parts.append(get.cmd(f"colorchannelmixer@{inst}e", {o: ("exposure", g) for o in ("rr", "gg", "bb")})
                         + f"colorchannelmixer@{inst}e=rr={_num(g(get('exposure')))}:gg={_num(g(get('exposure')))}"
                         f":bb={_num(g(get('exposure')))}")
        frame = ":eval=frame" if get.animated("contrast", "saturation", "gamma") else ""
        parts.append(f"eq=contrast={get.expr('contrast')}:saturation={get.expr('saturation')}"
                     f":gamma={get.expr('gamma')}{frame}")
        if get("temperature") != 6500 or get.animated("temperature"):
            parts.append(get.cmd(f"colortemperature@{inst}k", {"temperature": ("temperature", lambda v: v)})
                         + f"colortemperature@{inst}k=temperature={_num(get('temperature'))}")
        if get("tint") or get.animated("tint"):
            parts.append(get.cmd(f"colorbalance@{inst}g", {"gm": ("tint", lambda v: -v * 0.4)})
                         + f"colorbalance@{inst}g=gm={_num(-get('tint') * 0.4)}")
        simple = ",".join(parts)
    elif kind == "wheels":
        simple = f"lutrgb=r={_lgg(params, 'r')}:g={_lgg(params, 'g')}:b={_lgg(params, 'b')}"
    elif kind == "curves":
        pts = " ".join(f"{k / 4:g}/{_num(get(f'p{k}'))}" for k in range(5))
        simple = f"curves={get('channel')}='{pts}'"
    elif kind == "hue":
        simple = (f"hue=h={get.expr('hue')}:s={get.expr('saturation')}"
                  f":b={get.expr('brightness', lambda x: f'({x})*10', lambda v: v * 10)}")
    elif kind == "blur":
        sig = lambda v: max(0.01, short * v / 100)  # noqa: E731
        simple = get.cmd(f"gblur@{inst}b", {"sigma": ("size", sig)}) + f"gblur@{inst}b=sigma={_num(sig(get('size')))}"
    elif kind == "sharpen":
        simple = f"unsharp=5:5:{_num(get('amount'))}"
    elif kind == "glow":
        a, b, g = cx.tmp(), cx.tmp(), cx.tmp()
        t = get("threshold")
        sig = lambda v: max(0.01, short * v / 100)  # noqa: E731
        lut = f"'if(gt(val,{_num(t)}*maxval),val,0)'"
        cx.chains.append(f"[{i}]format=gbrp,split[{a}][{b}]")
        cx.chains.append(f"[{b}]lutrgb=r={lut}:g={lut}:b={lut},"
                         + get.cmd(f"gblur@{inst}b", {"sigma": ("size", sig)})
                         + f"gblur@{inst}b=sigma={_num(sig(get('size')))}[{g}]")
        cx.chains.append(f"[{a}][{g}]" + get.cmd(f"blend@{inst}m", {"all_opacity": ("intensity", lambda v: v)})
                         + f"blend@{inst}m=all_mode=screen:all_opacity={_num(get('intensity'))}[{out}]")
        return
    elif kind == "vignette":
        frame = ":eval=frame" if get.animated("amount") else ""
        simple = f"vignette=angle={get.expr('amount', lambda x: f'max(0.01,{x})*PI/2.2', lambda v: max(0.01, v) * math.pi / 2.2)}{frame}"
    elif kind == "grain":
        simple = f"noise=alls={round(get('amount'))}:allf=t"
    elif kind == "chromatic":
        px = lambda v: max(0, round(short * v / 100))  # noqa: E731
        simple = (get.cmd(f"rgbashift@{inst}c", {"rh": ("amount", lambda v: -px(v)), "bh": ("amount", px)})
                  + f"rgbashift@{inst}c=rh={-px(get('amount'))}:bh={px(get('amount'))}")
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
        parts = []
        if get.animated("zoom", "x", "y"):
            # pe fiecare cadru: scalare (zoom ≥ 1) + fereastra W×H mutată; crop își fixează iw la primul cadru,
            # deci poziția o calculăm din aceeași formulă a zoom-ului
            z = get.expr("zoom", lambda x: f"max(1,{x})", lambda v: max(1.0, v)).strip("'")
            x = get.expr("x").strip("'")
            y = get.expr("y").strip("'")
            parts.append(f"scale=w='ceil({W}*{z}/2)*2':h='ceil({H}*{z}/2)*2':eval=frame")
            parts.append(f"crop={W}:{H}:x='floor({W}*({z}-1)/2*(1-({x})))':y='floor({H}*({z}-1)/2*(1-({y})))'")
        else:
            z, x, y = get("zoom"), get("x"), get("y")
            sw, sh = max(2, round(W * z / 2) * 2), max(2, round(H * z / 2) * 2)
            parts.append(f"scale={sw}:{sh}")
            if z >= 1:  # fereastra W×H mutată în imaginea mărită
                parts.append(f"crop={W}:{H}:{_num((sw - W) / 2 * (1 - x))}:{_num((sh - H) / 2 * (1 - y))}")
            else:  # imaginea micșorată, pe negru, deplasată
                parts.append(f"pad={W}:{H}:{_num((W - sw) / 2 * (1 + x))}:{_num((H - sh) / 2 * (1 + y))}:black")
        if get("rotate") or get.animated("rotate"):
            parts.append(f"rotate=a={get.expr('rotate', lambda x: f'({x})*PI/180', math.radians)}:fillcolor=black")
        simple = ",".join(parts)
    elif kind == "window":  # elipsă moale, calculată la 1/4 din rezoluție (masca e oricum moale)
        qw, qh = max(8, W // 4), max(8, H // 4)
        def e(k: str, fn=lambda x: x, num=lambda v: v) -> str:
            return get.expr(k, fn, num, var="T").strip("'")

        rx = e("w", lambda x: f"max(0.01,({x})/2)", lambda v: max(0.01, v / 2))
        ry = e("h", lambda x: f"max(0.01,({x})/2)", lambda v: max(0.01, v / 2))
        soft = e("soft", lambda x: f"max(0.001,{x})", lambda v: max(0.001, v))
        d = f"hypot((X/W-({e('cx')}))/({rx}),(Y/H-({e('cy')}))/({ry}))"
        v = f"clip((1-{d})/({soft})+0.5,0,1)"  # 1 înăuntru, 0 afară, trecere de lățime `soft` pe margine
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
        simple = ("format=yuva420p,"
                  + get.cmd(f"chromakey@{inst}k", {"similarity": ("similarity", lambda v: v), "blend": ("blend", lambda v: v)})
                  + f"chromakey@{inst}k=color={_rgb(get('color'))}:similarity={_num(get('similarity'))}"
                  f":blend={_num(get('blend'))}")
    elif kind == "solid":
        cx.chains.append(f"[{src}]drawbox=x=0:y=0:w=iw:h=ih:color={_rgb(get('color'))}:t=fill[{out}]")
        return
    elif kind == "media":
        aid = params.get("asset")
        if not aid:
            raise ValueError(f"nodul „{CATALOG[kind]['label']}”: alege fișierul")
        if cx.media is None:  # unde nu se pot adăuga intrări (ex. -vf simplu): cadru negru
            cx.chains.append(f"[{src}]drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill[{out}]")
            return
        cx.chains.append(f"[{src}]nullsink")
        lab = cx.media(aid, float(get("offset")))
        fit = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}" if get("fit") == "umple" else
               f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black")
        cx.chains.append(f"[{lab}]setpts=PTS-STARTPTS,{fit},setsar=1,fps={_num(cx.fps)},format=yuv420p[{out}]")
        return
    elif kind == "merge":
        bg, fg, m = ins.get("bg"), ins.get("fg"), ins.get("mask")
        if not bg or not fg:  # un singur strat legat: trece mai departe neschimbat
            cx.chains.append(f"[{bg or fg}]null[{out}]")
            return
        mode, op = get("mode"), get("opacity")
        ident = lambda v: v  # noqa: E731
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
            cx.chains.append(f"[{m}]format=gray,format=gbrp,"
                             + get.cmd(f"colorchannelmixer@{inst}o", {o: ("opacity", ident) for o in ("rr", "gg", "bb")})
                             + f"colorchannelmixer@{inst}o=rr={_num(op)}:gg={_num(op)}:bb={_num(op)}[{mk}]")
            if b2:  # bg-ul nefolosit de blend: îl închidem curat
                cx.chains.append(f"[{b2}]nullsink")
            cx.chains.append(f"[{b1}][{mixed}][{mk}]maskedmerge[{out}]")
        elif mode == "normal":
            f2 = cx.tmp()
            cx.chains.append(f"[{fg}]format=yuva420p,"
                             + get.cmd(f"colorchannelmixer@{inst}o", {"aa": ("opacity", ident)})
                             + f"colorchannelmixer@{inst}o=aa={_num(op)}[{f2}]")
            cx.chains.append(f"[{bg}][{f2}]overlay=format=auto:shortest=1,format=yuv420p[{out}]")
        else:
            b2, f2 = cx.tmp(), cx.tmp()
            cx.chains.append(f"[{bg}]format=gbrp[{b2}]")
            cx.chains.append(f"[{fg}]format=gbrp[{f2}]")
            cx.chains.append(f"[{b2}][{f2}]" + get.cmd(f"blend@{inst}o", {"all_opacity": ("opacity", ident)})
                             + f"blend@{inst}o=all_mode={mode}:all_opacity={_num(op)}[{out}]")
        return
    cx.chains.append(f"[{i}]{simple}[{out}]")


def compile_graph(graph, prefix: str, W: int, H: int, fps: float = 30.0, view: str | None = None,
                  src0: float = 0.0, rate: float = 1.0, media: Callable[[str, float], str] | None = None) -> str:
    """Fragmentul de filter_complex pentru graf: începe cu „,” (continuă lanțul clipului) și se termină cu un
    lanț deschis. `view`: id-ul nodului a cărui ieșire se vrea (preview pe nod), altfel nodul „out”.
    `src0`, `rate`: momentul din sursă la începutul lanțului și viteza clipului (pentru keyframe-uri).
    `media(asset, offset) -> etichetă`: adaugă o intrare pentru nodurile „media” (None: cadru negru).
    Graf gol sau doar in → out: șir gol."""
    if graph is None:
        return ""
    types = {n.id: n.type for n in graph.nodes}
    nodes = {n.id: n for n in graph.nodes}
    feeds: dict[str, dict[str, str]] = {}
    for e in graph.edges:
        feeds.setdefault(e.dst, {})[e.port] = e.src
    target = view or next(i for i, t in types.items() if t == "out")
    if target not in types:
        raise ValueError(f"nod inexistent: {target}")
    root = next(i for i, t in types.items() if t == "in")

    # nodurile care contează: cele din care se ajunge la țintă; sursele (window, solid, media) cer o copie din „in”
    order: list[str] = []
    seen: set[str] = set()

    def visit(i: str) -> None:
        if i in seen:
            return
        seen.add(i)
        for port in CATALOG[types[i]]["inputs"]:
            if port in feeds.get(i, {}):
                visit(feeds[i][port])
        if types[i] in SOURCES:
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
        if types[i] in SOURCES:
            uses[root] += 1
    cx = _Ctx(prefix, W, H, fps, src0, rate, media)
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
    final = None
    for i in order:
        kind = types[i]
        if kind == "in":
            continue
        ins = {port: take(feeds[i][port]) for port in CATALOG[kind]["inputs"] if port in feeds.get(i, {})}
        src = take(root) if kind in SOURCES else None
        if kind == "out":
            final = ins.get("in")
            break
        if kind != "merge" and CATALOG[kind]["inputs"] and "in" not in ins:
            raise ValueError(f"nodul {i} ({CATALOG[kind]['label']}) nu are intrarea legată")
        if kind == "merge" and not ins:
            raise ValueError(f"nodul {i} (merge) nu are nicio intrare legată")
        lab = f"{prefix}{i}"
        n = nodes[i]
        _node(cx, kind, n.params, getattr(n, "anim", {}) or {}, ins, lab, src)
        produce(i, lab)
    if final is None:
        final = take(target)
    # copiile rămase nefolosite (ex. „in” ramificat spre noduri care nu ajung la țintă) se închid
    for rest in labels.values():
        for lab in rest:
            cx.chains.append(f"[{lab}]nullsink")
    body = ";".join(cx.chains)
    return f",null[{head}];{body}{';' if body else ''}[{final}]format=yuv420p"
