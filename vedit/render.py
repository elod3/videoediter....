"""Compilează Timeline -> o singură comandă ffmpeg (filter_complex). Determinist, fără LLM.

Ordinea straturilor, de jos în sus: V1 (clipuri + grading + intro/outro) -> V2 (B-roll) -> logo -> subtitrări și titluri.
"""
from __future__ import annotations

import os
import tempfile
from contextvars import ContextVar

from .captions import fonts_dir, to_ass
from .ff import run
from .probe import MediaInfo
from .timeline import Clip, Crop, Timeline


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def crop_box(src_w: int, src_h: int, out_w: int, out_h: int, clip) -> tuple[int, int, int, int]:
    """Cea mai mare fereastră cu aspectul output-ului, centrată pe (cx,cy), împărțită la zoom.
    `clip` e orice obiect cu `.crop` (Clip, BRoll) sau direct un Crop."""
    crop = clip if isinstance(clip, Crop) else clip.crop
    ar = out_w / out_h
    if src_w / src_h > ar:
        ch, cw = src_h, src_h * ar
    else:
        cw, ch = src_w, src_w / ar
    z = max(crop.zoom, 1.0)
    cw, ch = _even(min(cw / z, src_w)), _even(min(ch / z, src_h))
    x = min(max(crop.cx * src_w - cw / 2, 0), src_w - cw)
    y = min(max(crop.cy * src_h - ch / 2, 0), src_h - ch)
    return cw, ch, int(x), int(y)


def _atempo(speed: float) -> str:
    """atempo acceptă 0.5-2 per filtru: vitezele extreme se compun din mai multe."""
    parts, s = [], speed
    while s > 2.0:
        parts.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        parts.append("atempo=0.5")
        s /= 0.5
    parts.append(f"atempo={s:.6f}")
    return ",".join(parts) + ","


def _fx(c: Clip, W: int, H: int, fps: float = 30.0, media=None) -> str:
    """Efectele vizuale ale clipului, la dimensiunea output-ului (se aplică după încadrare)."""
    short = min(W, H)
    out = []
    for f in c.fx:
        if f == "bw":
            out.append("hue=s=0")
        elif f == "vintage":
            out.append("curves=preset=vintage,noise=alls=10:allf=t,vignette=PI/4.5")
        elif f == "vignette":
            out.append("vignette=PI/4.5")
        elif f == "blur":
            out.append(f"gblur=sigma={short * 0.012:.2f}")
        elif f == "sharpen":
            out.append("unsharp=5:5:0.9")
        elif f == "glitch":  # decalaj RGB + zgomot în rafale scurte
            px = max(2, round(short * 0.012))
            out.append(f"rgbashift=rh=-{px}:bh={px}:enable='lt(mod(t,0.6),0.12)',"
                       f"noise=alls=24:allf=t:enable='lt(mod(t,0.6),0.12)'")
        elif f == "shake":  # tremur de cameră: supradimensionare 6% + fereastră care oscilează
            sw, sh = _even(W * 1.06), _even(H * 1.06)
            dx, dy = (sw - W) / 2, (sh - H) / 2
            out.append(f"scale={sw}:{sh},crop={W}:{H}:x='{dx:.1f}+{dx * 0.8:.1f}*sin(t*23)':"
                       f"y='{dy:.1f}+{dy * 0.8:.1f}*sin(t*19+1)'")
        elif f == "flash":
            out.append("fade=t=in:st=0:d=0.25:color=white")
        elif f == "grain":
            out.append("noise=alls=9:allf=t")
        elif f == "mirror":
            out.append("hflip")
        elif f == "invert":
            out.append("negate")
    from .nodes import compile_graph

    return ("," + ",".join(out) if out else "") + compile_graph(c.nodes, f"n{c.id}_", W, H, fps=fps, src0=c.src_in,
                                                                rate=c.speed, media=media)


def media_path(tl: Timeline, aid: str, m: MediaInfo) -> str:
    """Sursa folosită la randare: varianta stabilizată, dacă există."""
    p = tl.stabilized.get(aid)
    return os.path.abspath(p if p and os.path.exists(p) else m.path)


EASE = {
    "inout": "(1-cos(PI*{p}))/2",
    "in": "({p})*({p})",
    "out": "(1-(1-{p})*(1-{p}))",
    "linear": "{p}",
    "expo": "(1-pow(2,-10*{p}))",
    "hold": "0",
}


def _keys_expr(keys, field: str) -> str:
    """Expresie ffmpeg pe bucăți: între keyframe-ul i și i+1 valoarea urmează curba lui i (t = timpul din clip)."""
    ks = sorted(keys, key=lambda k: k.t)
    expr = f"{getattr(ks[-1], field):g}"
    for a, b in reversed(list(zip(ks, ks[1:]))):
        va, vb = getattr(a, field), getattr(b, field)
        span = max(b.t - a.t, 1e-3)
        p = f"min(max((t-{a.t:.4f})/{span:.4f},0),1)"
        seg = f"({va:g}+({vb:g}-{va:g})*{EASE[a.ease].format(p=p)})" if va != vb else f"{va:g}"
        expr = f"if(lt(t,{b.t:.4f}),{seg},{expr})"
    return f"if(lt(t,{ks[0].t:.4f}),{getattr(ks[0], field):g},{expr})"


def _keys_anim(c: Clip, W: int, H: int) -> str:
    z, fx, fy = _keys_expr(c.keys, "zoom"), _keys_expr(c.keys, "cx"), _keys_expr(c.keys, "cy")
    out = f",scale=w='ceil({W}*({z})/2)*2':h='ceil({H}*({z})/2)*2':eval=frame"
    if any(k.rotate for k in c.keys):  # rotim imaginea mărită, înainte de crop: zoom-ul acoperă colțurile
        out += f",rotate=a='({_keys_expr(c.keys, 'rotate')})*PI/180':ow=iw:oh=ih:c=black"
    out += (f",crop={W}:{H}:x='floor(clip(({fx})*{W}*({z})-{W}/2,0,{W}*(({z})-1)))'"
            f":y='floor(clip(({fy})*{H}*({z})-{H}/2,0,{H}*(({z})-1)))'")
    if c.motion_blur:
        out += ",tmix=frames=3:weights='1 2 1'"
    return out


def _zoom_anim(c: Clip, W: int, H: int) -> str:
    """Zoom animat: scalare pe fiecare cadru (netedă, sub-pixel) + crop fix la dimensiunea output-ului."""
    if c.keys:
        return _keys_anim(c, W, H)
    if not c.anim:
        return ""
    a = c.anim
    p = f"min(t/{max(c.body, 0.04):.4f},1)"
    z = f"({a.zoom_from:g}+({a.zoom_to:g}-{a.zoom_from:g})*{EASE[a.ease].format(p=p)})"
    # crop își fixează iw/ih la primul cadru, deci centrul îl calculăm din aceeași formulă a zoom-ului
    if (a.cx_from, a.cy_from, a.cx_to, a.cy_to) == (0.5, 0.5, 0.5, 0.5):
        return (f",scale=w='ceil({W}*{z}/2)*2':h='ceil({H}*{z}/2)*2':eval=frame,"
                f"crop={W}:{H}:x='floor({W}*({z}-1)/2)':y='floor({H}*({z}-1)/2)'")
    # focus mobil: punctul (cx, cy) ajunge în centrul cadrului, fără să iasă crop-ul din imagine
    e = EASE[a.ease].format(p=p)
    fx = f"({a.cx_from:g}+({a.cx_to:g}-{a.cx_from:g})*{e})"
    fy = f"({a.cy_from:g}+({a.cy_to:g}-{a.cy_from:g})*{e})"
    return (f",scale=w='ceil({W}*{z}/2)*2':h='ceil({H}*{z}/2)*2':eval=frame,"
            f"crop={W}:{H}:x='floor(clip({fx}*{W}*{z}-{W}/2,0,{W}*({z}-1)))'"
            f":y='floor(clip({fy}*{H}*{z}-{H}/2,0,{H}*({z}-1)))'")


def _audio_fx(tl: Timeline, asset: str) -> str:
    from .audiofx import AudioFx, chain

    fx = tl.audio_fx.get(asset)
    return f"{chain(AudioFx(**fx))}," if fx else ""


# Tranzițiile „de editor”: xfade-ul de bază + un efect doar pe fereastra tranziției (motion blur, blur, glitch).
PRO_TRANSITIONS = {
    "whipleft": "slideleft", "whipright": "slideright", "whipup": "slideup", "whipdown": "slidedown",
    "zoomthrough": "zoomin", "glitch": "fade", "blurdissolve": "fade", "lightleak": "fade",  # dissolve din ffmpeg e punctat
    "invertwhip": "slideleft", "chromawhip": "slideleft",
}


def _window_fx(kind: str, a: float, b: float, W: int, fps: float = 30.0) -> str:
    """Filtrul pus peste [a, b] (secunde de montaj) pentru o tranziție „de editor”. W = lățimea randării."""
    en = f"enable='between(t,{a:.3f},{b:.3f})'"
    k = W / 1080
    if kind == "invertwhip":  # whip + 2 cadre în negativ chiar pe mijlocul tăieturii (look-ul reels-urilor de agenție)
        mid, fr = (a + b) / 2, 1 / fps
        return (f"dblur=angle=0:radius={max(4, int(52 * k))}:{en},tmix=frames=3:weights='1 2 1':{en},"
                f"lutyuv=y=negval:u=negval:v=negval:enable='between(t,{mid - fr:.3f},{mid + fr * 0.99:.3f})'")
    if kind == "chromawhip":  # whip cu canalele de culoare despărțite (RGB split) pe toată fereastra
        sh = max(3, int(22 * k))
        return (f"dblur=angle=0:radius={max(4, int(40 * k))}:{en},rgbashift=rh={-sh}:bh={sh}:{en},"
                f"tmix=frames=3:weights='1 2 1':{en}")
    if kind.startswith("whip"):
        ang = 0 if kind in ("whipleft", "whipright") else 90
        return (f"dblur=angle={ang}:radius={max(4, int(46 * k))}:{en},"
                f"tmix=frames=3:weights='1 2 1':{en}")
    if kind == "zoomthrough":
        return f"gblur=sigma={max(2, 9 * k):.1f}:{en}"
    if kind == "blurdissolve":
        return f"gblur=sigma={max(2, 7 * k):.1f}:{en}"
    if kind == "glitch":
        sh = max(2, int(14 * k))
        return f"rgbashift=rh={-sh}:bh={sh}:gv={sh // 2}:{en},noise=alls=28:allf=t:{en}"
    return ""


def _beat_filter(bf, W: int, H: int, fps: float) -> str:
    """Un puls pe fiecare beat din [start, end]: PU = 1 chiar pe beat, scade la 0 în câteva cadre."""
    en = f"between(t,{bf.start:.3f},{bf.end:.3f})"
    if bf.kind == "flash":
        pu = f"max(0,1-mod(t-{bf.offset:.4f}+{bf.period:.4f}*100,{bf.period:.4f})/0.09)"
        return f"eq=brightness='{0.16 * bf.strength:.3f}*{pu}*{en}':eval=frame"
    if bf.kind == "rgb":  # 3 cadre de RGB split chiar pe beat
        sh = max(2, int(W / 1080 * 9 * bf.strength))
        win = f"lt(mod(t-{bf.offset:.4f}+{bf.period:.4f}*100,{bf.period:.4f}),{3 / fps:.4f})"
        return f"rgbashift=rh={-sh}:bh={sh}:enable='{en}*{win}'"
    # punch: zoom-in de ~5% care se stinge în 0.15 s, cu mărimea cadrului fixă (perspective, nu scale)
    tt = f"(in/{fps:g})"
    pu = f"max(0,1-mod({tt}-{bf.offset:.4f}+{bf.period:.4f}*100,{bf.period:.4f})/0.15)*between({tt},{bf.start:.3f},{bf.end:.3f})"
    z = f"({0.05 * bf.strength:.3f}*{pu})"
    dx, dy = f"({W / 2:.1f}*{z})", f"({H / 2:.1f}*{z})"
    return (f"perspective=x0='-{dx}':y0='-{dy}':x1='{W}+{dx}':y1='-{dy}':x2='-{dx}':y2='{H}+{dy}':x3='{W}+{dx}':"
            f"y3='{H}+{dy}':sense=destination:eval=frame:interpolation=linear")


def _join(tl: Timeline, W: int = 1080) -> list[str]:
    """Lipește clipurile: fără tranziție => concat (în grupuri), cu tranziție => xfade + acrossfade.

    Offset-ul xfade e începutul clipului pe timeline (Timeline.starts ține deja cont de suprapuneri).
    Ieșirea finală e mereu [vc][ac]."""
    starts = tl.starts()
    groups: list[list[int]] = [[0]]
    for k in range(1, len(tl.clips)):
        if tl.clips[k].transition:
            groups.append([k])
        else:
            groups[-1].append(k)
    single = len(groups) == 1
    out: list[str] = []
    labels = []
    for g, ks in enumerate(groups):
        gv, ga = ("vc", "ac") if single else (f"gv{g}", f"ga{g}")
        if len(ks) > 1:
            out.append("".join(f"[v{k}][a{k}]" for k in ks) + f"concat=n={len(ks)}:v=1:a=1[{gv}][{ga}]")
        elif single:
            out += [f"[v{ks[0]}]null[vc]", f"[a{ks[0]}]anull[ac]"]
        else:
            gv, ga = f"v{ks[0]}", f"a{ks[0]}"
        labels.append((gv, ga))
    v, a = labels[0]
    for g in range(1, len(groups)):
        tr = tl.clips[groups[g][0]].transition
        gv, ga = labels[g]
        nv, na = ("vc", "ac") if g == len(groups) - 1 else (f"xv{g}", f"xa{g}")
        base = PRO_TRANSITIONS.get(tr.type, tr.type)
        out.append(f"[{v}][{gv}]xfade=transition={base}:duration={tr.duration:.3f}:"
                   f"offset={starts[groups[g][0]]:.3f}[{nv}]")
        out.append(f"[{a}][{ga}]acrossfade=d={tr.duration:.3f}:c1=tri:c2=tri[{na}]")
        v, a = nv, na
    fx = []
    for k in range(1, len(tl.clips)):
        tr = tl.clips[k].transition
        if tr and tr.type in PRO_TRANSITIONS:
            f = _window_fx(tr.type, starts[k], starts[k] + tr.duration, W, tl.fps)
            if f:
                fx.append(f)
    if fx:  # efectele de fereastră, la final, pe imaginea lipită
        out = [x[:-4] + "[vc_raw]" if x.endswith("[vc]") else x for x in out]  # ultimul xfade scria [vc]
        out.append(f"[vc_raw]{','.join(fx)}[vc]")
    return out


# Asset-urile randării curente: _lut le citește ca să știe ce surse sunt HDR (setat de render / thumbnail / cadru).
ASSETS: ContextVar[dict] = ContextVar("vedit_assets", default={})


def subject_xform(c: Clip, W: int, H: int, fps: float) -> tuple[str, str]:
    """Persoana micșorată / mutată peste fundal (Background.scale/x/y/move), într-un cadru de mărime FIXĂ (filtrele
    de după nu suportă cadre care își schimbă mărimea). Întoarce (filtrul, de aplicat pe imaginea cu alfa a
    persoanei; gol dacă nu se mută) și linia picioarelor ca expresie în t (pentru umbra de contact).
    Aceeași geometrie la imagine și la persoana pusă din nou peste blocurile din spatele ei."""
    b = c.bg
    moved = bool(b) and b.mode in ("color", "asset", "studio", "silhouette") and \
        (b.scale < 0.999 or abs(b.x - 0.5) > 1e-3 or abs(b.y - 1.0) > 1e-3)
    if not moved:
        return "", f"{H * (b.foot if b else 1.0):.1f}"

    def ease(var: str) -> str:  # 0 -> 1 în b.move secunde, ease out cubic; fără move, direct la țintă
        return f"(1-pow(1-min({var}/{b.move:.3f},1),3))" if b.move > 0 else "1"

    e = ease(f"(in/{fps:g})")       # perspective numără cadrele, nu are timp
    sc = f"(1+({b.scale:.4f}-1)*{e})"
    cx = f"({W / 2 + 2:.1f}+({b.x * W:.1f}-{W / 2:.1f})*{e})"   # +2: marginea transparentă din pad
    by = f"({H + 2:.1f}+({b.y * H:.1f}-{H:.1f})*{e})"
    x0, x1, y0 = f"({cx}-{W / 2:.1f}*{sc})", f"({cx}+{W / 2:.1f}*{sc})", f"({by}-{H:.1f}*{sc})"
    flt = (f"format=yuva420p,pad={W + 4}:{H + 4}:2:2:color=black@0,"
           f"perspective=x0='{x0}':y0='{y0}':x1='{x1}':y1='{y0}':x2='{x0}':y2='{by}':x3='{x1}':y3='{by}'"
           f":sense=destination:eval=frame:interpolation=linear,crop={W}:{H}:2:2")
    et = ease("t")  # picioarele: linia de jos a persoanei, mutată și scalată odată cu ea
    return flt, (f"(({H:.1f}+({b.y * H:.1f}-{H:.1f})*{et})-{H * (1 - b.foot):.1f}*(1+({b.scale:.4f}-1)*{et}))")


def studio_png(path: str, W: int, H: int, color: str) -> None:
    """Fundal de studio: lumină caldă din spatele persoanei (gradient radial deasupra centrului), podea puțin mai
    închisă, vignetă. Determinist, o poză pe clip (în workdir)."""
    import cv2
    import numpy as np

    c = np.array([int(color.lstrip("#")[i:i + 2], 16) for i in (4, 2, 0)], np.float32)  # BGR
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - W * 0.5) / (W * 0.62)) ** 2 + ((y - H * 0.42) / (H * 0.5)) ** 2)
    light = np.clip(1.16 - 0.5 * d ** 1.6, 0.55, 1.16)             # centru luminat, margini în umbră
    floor = 1 - 0.1 * np.clip((y - H * 0.72) / (H * 0.28), 0, 1)    # podeaua, puțin mai închisă spre cameră
    img = c[None, None, :] * (light * floor)[..., None]
    if c.mean() > 150:  # pe fundal deschis lumina „arde” spre alb, ca un fundal de studio
        img = img + (255 - img) * np.clip(light - 1, 0, 1)[..., None] * 1.5
    cv2.imwrite(path, np.clip(img, 0, 255).astype(np.uint8))


def motion_frames(tl: Timeline, assets: dict[str, MediaInfo], W: int, H: int):
    """(bloc, folder cu cadre) pentru fiecare bloc de motion; randate o dată și ținute în cache.

    Cache-ul stă în VEDIT_HOME/.motion (cheia = bloc + parametri + stil + rezoluție + fps + durată + poze)."""
    from pathlib import Path

    from .motion import image_file, render_frames, resolve_style
    from .motion.engine import cache_key

    root = Path(os.environ.get("VEDIT_HOME", "./vedit_projects")).resolve() / ".motion"
    brand_accent = tl.brand.highlight if getattr(tl.brand, "highlight", None) else None
    out = []
    for mv in tl.motion:
        style = resolve_style(mv.style or tl.motion_style, tl.motion_palette, brand_accent)
        imgs = {k: image_file(assets[a].path) for k, a in mv.images.items() if a in assets}
        dur = round(mv.end - mv.start, 3)
        base = dict(mv.params)
        if mv.track:
            base["_track"] = mv.track
        if mv.scene:
            base["_scene"] = mv.scene
        for layer in motion_layers(mv):
            params = {**base, "_layer": layer} if layer != "all" else base
            key = cache_key(mv.block, params, style, W, H, tl.fps, dur, imgs)
            d = render_frames(mv.block, params, style, W, H, tl.fps, dur, root / key, imgs)
            out.append((mv, str(d), layer))
    return out


def motion_layers(mv) -> tuple[str, ...]:
    """Straturile unui bloc: „all” (tot blocul, o dată) sau, la un bloc pus în spatele persoanei care are și
    elemente de prim-plan (ex. scrisul de mână din stack_title), „back” (sub persoană) + „front” (peste ea)."""
    from .motion import BLOCK_HELP

    if mv.behind and BLOCK_HELP.get(mv.block, {}).get("front"):
        return ("back", "front")
    return ("all",)


def caption_frames(tl: Timeline, W: int, H: int):
    """(subtitrare, folder cu cadre) pentru subtitrările randate prin vedit/motion (Timeline.caption_engine)."""
    from pathlib import Path

    from .motion import render_frames, resolve_style
    from .motion.engine import cache_key

    root = Path(os.environ.get("VEDIT_HOME", "./vedit_projects")).resolve() / ".motion"
    style = resolve_style(tl.motion_style, tl.motion_palette,
                          tl.brand.highlight or (tl.emphasis_color if tl.emphasis_color else None))
    emph = set(tl.emphasis)
    out = []
    for cap in tl.captions:
        words = cap.text.split()
        durs = cap.word_durs if cap.word_durs and len(cap.word_durs) == len(words) else None
        total = max(cap.end - cap.start, 0.2)
        if durs is None:  # fără timpi pe cuvinte: împărțim egal
            durs = [total / max(len(words), 1)] * len(words)
        starts, t = [], 0.0
        for d in durs:
            starts.append(round(t, 3))
            t += d
        ends = [round(s + d, 3) for s, d in zip(starts, durs)]
        ids = cap.word_ids or []
        em = [i for i, wid in enumerate(ids) if wid in emph]
        params = {"words": words, "starts": starts, "ends": ends, "emph": em, "mode": tl.caption_look,
                  "y": tl.caption_y}
        dur = round(total, 3)
        key = cache_key("captions", params, style, W, H, tl.fps, dur, {})
        out.append((cap, str(render_frames("captions", params, style, W, H, tl.fps, dur, root / key))))
    return out


def tonemap(m: MediaInfo | None) -> str:
    """HDR (HLG de pe iPhone, PQ) -> SDR BT.709, înainte de orice altceva. Fără asta clipul iese spălat și gri."""
    if m is None or not m.hdr:
        return ""
    prim = "bt2020" if m.primaries in ("", "bt2020") else m.primaries
    return (f"zscale=tin={m.transfer}:pin={prim}:min=bt2020nc:t=linear:npl=203,format=gbrpf32le,"
            "zscale=p=bt709,tonemap=tonemap=mobius:param=0.8:desat=0,"
            "zscale=t=bt709:m=bt709:r=tv,format=yuv420p,")


def _lut(tl: Timeline, asset: str) -> str:
    tm = tonemap(ASSETS.get().get(asset))
    grade = tl.grades.get(asset)
    if grade and os.path.exists(grade.lut):
        lut = grade.lut.replace("\\", "/").replace("'", r"\'")
        return f"{tm}lut3d=file='{lut}':interp=tetrahedral,"
    return tm


def _frame(tl: Timeline, c: Clip, m: MediaInfo, W: int, H: int) -> str:
    """Încadrarea (crop/pad) + zoom animat, fără culoare: aceeași pentru imagine și pentru masca persoanei."""
    if tl.fill == "crop":
        # fereastra pe aspectul timeline-ului: preview-ul și finalul au exact aceeași încadrare
        cw, ch, x, y = crop_box(m.width, m.height, tl.width, tl.height, c)
        fit = f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}"
    else:  # pad (și geometria lui „blur”: imaginea întreagă, centrată)
        fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
    return fit + _zoom_anim(c, W, H)


def fit_filter(tl: Timeline, c: Clip, m: MediaInfo, W: int, H: int, media=None) -> str:
    """Grading + încadrare (crop/pad) + zoom animat + efecte, pentru un clip cu o singură imagine.
    `m` e media unghiului afișat (c.angle sau c.asset)."""
    return _lut(tl, c.angle or c.asset) + _frame(tl, c, m, W, H) + _fx(c, W, H, tl.fps, media)


def with_bookends(tl: Timeline, assets: dict[str, MediaInfo]) -> tuple[Timeline, float]:
    """Intro/outro din brand, lipite la randare ca clipuri V1 înainte/după montaj.

    Nu le punem în timeline-ul editabil: tăieturile, captions, B-roll-ul și beat-urile rămân în timpul
    montajului. Aici tot ce e pe timeline se decalează cu durata intro-ului. Returnează (timeline, decalaj)."""
    b = tl.brand
    if not (b.intro or b.outro):
        return tl, 0.0
    out = tl.model_copy(deep=True)
    off = 0.0
    if b.intro:
        m = assets[b.intro]
        off = round(b.intro_dur or m.duration, 3)
        if out.clips:
            out.clips[0].transition = None
        out.clips.insert(0, Clip(id="_intro", asset=b.intro, src_in=0, src_out=off))
        for x in [*out.captions, *out.texts]:
            x.start, x.end = x.start + off, x.end + off
        for x in out.broll:
            x.start += off
        for g in out.graphics:
            g.start, g.end = g.start + off, g.end + off
        for g in out.motion:
            g.start, g.end = g.start + off, g.end + off
        for s in out.sfx:
            s.at += off
        for bf in out.beat_fx:
            bf.start, bf.end, bf.offset = bf.start + off, bf.end + off, bf.offset + off
    if b.outro:
        m = assets[b.outro]
        out.clips.append(Clip(id="_outro", asset=b.outro, src_in=0, src_out=round(b.outro_dur or m.duration, 3)))
    return out, off


def build_command(tl: Timeline, assets: dict[str, MediaInfo], out_path: str, *,
                  preview: bool = False, workdir: str | None = None) -> tuple[list[str], str]:
    ASSETS.set(assets)  # pentru _lut: ce surse sunt HDR
    if not tl.clips:
        raise ValueError("timeline-ul e gol")
    # un clip mai scurt decât un cadru nu produce niciun cadru, iar concat l-ar aștepta la nesfârșit
    frame = 1.0 / max(tl.fps, 1.0)
    if any(c.duration < frame for c in tl.clips):
        tl = tl.model_copy(deep=True)
        tl.clips = [c for c in tl.clips if c.duration >= frame]
        if not tl.clips:
            raise ValueError("timeline-ul are doar clipuri mai scurte decât un cadru")
    main_dur = tl.duration
    tl, off = with_bookends(tl, assets)
    workdir = workdir or tempfile.mkdtemp(prefix="vedit_")
    W, H = tl.width, tl.height
    if preview:  # 540p rapid
        f = 540 / min(W, H)
        W, H = _even(W * f), _even(H * f)

    args: list[str] = ["-y"]
    filters: list[str] = []
    n_in = 0

    def add_input(path: str, ss: float | None = None, t: float | None = None, pre: list[str] | None = None) -> int:
        nonlocal args, n_in
        args += (pre or []) + (["-ss", f"{ss:.3f}"] if ss is not None else []) + \
            (["-t", f"{t:.3f}"] if t is not None else []) + ["-i", path]
        n_in += 1
        return n_in - 1

    def hide(tag: str, c: Clip, aid: str, vm, vi: int, t_in: float, src_d: float) -> str:
        """Sursa clipului cu zonele / fețele ascunse (Clip.privacy), la rezoluția sursei. Întoarce eticheta."""
        pv = c.privacy
        has_pv = bool(pv and (pv.boxes or pv.faces))
        if not has_pv and not c.retouch and not c.denoise and not c.sharpen:
            return f"[{vi}:v]"
        sw, sh = vm.width, vm.height
        cur = f"hs{tag}"
        filters.append(f"[{vi}:v]setpts=PTS-STARTPTS,format=yuv420p[{cur}]")
        if c.denoise:  # întâi zgomotul (altfel netezirea și claritatea îl amplifică)
            dn = {"light": "hqdn3d=2:1.5:3:2.5", "medium": "hqdn3d=4:3:6:4.5",
                  "strong": "nlmeans=s=3.5:p=7:r=11"}[c.denoise]
            filters.append(f"[{cur}]{dn}[dn{tag}]")
            cur = f"dn{tag}"
        if c.retouch > 0:  # piele: netezire care păstrează marginile, doar pe fețe, dozată de masca înmulțită
            if aid not in tl.skin_masks or not os.path.exists(tl.skin_masks[aid]):
                raise ValueError(f"lipsește masca fețelor pentru {aid}: rulează retouch pe {c.id}")
            mi = add_input(os.path.abspath(tl.skin_masks[aid]), t_in, src_d)
            sig = max(2.0, min(sw, sh) * 0.008)
            filters.append(f"[{cur}]split[rk{tag}][rb{tag}]")
            sr = f"sigmaR={0.06 + 0.08 * c.retouch:.3f}"
            if sw * sh > 1280 * 720:  # la jumătate de rezoluție bilateral e mult mai ieftin, iar pe piele nu se vede diferența
                filters.append(f"[rb{tag}]scale={sw // 4 * 2}:{sh // 4 * 2}:flags=area,bilateral=sigmaS={sig / 2:.1f}:{sr},"
                               f"scale={sw}:{sh}:flags=bicubic[rbb{tag}]")
            else:
                filters.append(f"[rb{tag}]bilateral=sigmaS={sig:.1f}:{sr}[rbb{tag}]")
            filters.append(f"[{mi}:v]setpts=PTS-STARTPTS,scale={sw}:{sh},format=gray,"
                           f"lut=y='val*{min(max(c.retouch, 0), 1) * 0.85:.3f}'[rm{tag}]")
            filters.append(f"[rbb{tag}][rm{tag}]alphamerge[ra{tag}]")
            filters.append(f"[rk{tag}][ra{tag}]overlay=format=auto[rf{tag}]")
            cur = f"rf{tag}"
        if c.sharpen > 0:
            filters.append(f"[{cur}]cas=strength={min(max(c.sharpen, 0), 1) * 0.7:.3f}[sp{tag}]")
            cur = f"sp{tag}"
        if not has_pv:
            return f"[{cur}]"
        if pv.style == "pixel":
            def hid(w, h):
                return f"scale={max(2, w // 16)}:{max(2, h // 16)}:flags=area,scale={w}:{h}:flags=neighbor"
        else:
            def hid(w, h):
                return f"gblur=sigma={max(6.0, min(w, h) * 0.12 if w < sw else min(sw, sh) * 0.03):.1f}"
        if pv.faces:
            if aid not in tl.face_masks or not os.path.exists(tl.face_masks[aid]):
                raise ValueError(f"lipsește masca fețelor pentru {aid}: rulează blur_faces pe {c.id}")
            mi = add_input(os.path.abspath(tl.face_masks[aid]), t_in, src_d)
            filters.append(f"[{cur}]split[hk{tag}][hb{tag}]")
            filters.append(f"[hb{tag}]{hid(sw, sh)}[hbb{tag}]")
            filters.append(f"[{mi}:v]setpts=PTS-STARTPTS,scale={sw}:{sh},format=gray[hm{tag}]")
            filters.append(f"[hbb{tag}][hm{tag}]alphamerge[ha{tag}]")
            filters.append(f"[hk{tag}][ha{tag}]overlay=format=auto[hf{tag}]")
            cur = f"hf{tag}"
        for j, b in enumerate(pv.boxes):
            w, h = max(2, int(b.w * sw) // 2 * 2), max(2, int(b.h * sh) // 2 * 2)
            x, y = min(int(b.x * sw), sw - w), min(int(b.y * sh), sh - h)
            filters.append(f"[{cur}]split[hx{tag}_{j}][hy{tag}_{j}]")
            filters.append(f"[hy{tag}_{j}]crop={w}:{h}:{x}:{y},{hid(w, h)}[hz{tag}_{j}]")
            filters.append(f"[hx{tag}_{j}][hz{tag}_{j}]overlay={x}:{y}[hb{tag}_{j}]")
            cur = f"hb{tag}_{j}"
        return f"[{cur}]"

    for k, c in enumerate(tl.clips):
        m = assets[c.asset]
        d, src_d = c.duration, c.src_out - c.src_in

        def media(aid: str, offset: float, c=c) -> str:
            """Nodul „media”: alt fișier din proiect ca intrare (în buclă), cât durează clipul."""
            if aid not in assets or not assets[aid].has_video:
                raise ValueError(f"nodul media de pe {c.id}: {aid} nu e un fișier video din proiect")
            am = assets[aid]
            return f"{add_input(media_path(tl, aid, am), offset % max(am.duration, 0.04), c.body + 0.2, pre=['-stream_loop', '-1'])}:v"

        speed = f"setpts=(PTS-STARTPTS)/{c.speed:g}," if c.speed != 1 else "setpts=PTS-STARTPTS,"
        hold = f",tpad=stop_mode=clone:stop_duration={c.freeze:.3f}" if c.freeze > 0 else ""
        tail = f"setsar=1,fps={tl.fps:g}{hold},format=yuv420p,settb=AVTB[v{k}]"
        vi = None
        if c.split:  # două unghiuri în același cadru: sus/jos sau stânga/dreapta
            sp = c.split
            pw, ph = (W, _even(H / 2)) if sp.mode == "stack" else (_even(W / 2), H)
            lw, lh = (tl.width, tl.height / 2) if sp.mode == "stack" else (tl.width / 2, tl.height)
            panes = []
            for j, (aid, crop) in enumerate(zip(sp.angles, sp.crops)):
                am = assets[aid]
                idx = add_input(media_path(tl, aid, am), tl.angle_time(c, aid, c.src_in), src_d)
                cw, ch, x, y = crop_box(am.width, am.height, round(lw), round(lh), crop)
                filters.append(f"[{idx}:v]{speed}{_lut(tl, aid)}crop={cw}:{ch}:{x}:{y},scale={pw}:{ph},setsar=1[sp{k}_{j}]")
                panes.append(f"[sp{k}_{j}]")
            stack = "vstack" if sp.mode == "stack" else "hstack"
            filters.append(f"{''.join(panes)}{stack}=inputs=2,scale={W}:{H}{_fx(c, W, H, tl.fps, media)},{tail}")
        else:
            aid = c.angle or c.asset
            vm = assets[aid]
            t_in = tl.angle_time(c, aid, c.src_in)
            vi = add_input(media_path(tl, aid, vm), t_in, src_d)
            src = hide(str(k), c, aid, vm, vi, t_in, src_d)
            if c.bg:  # persoana decupată (masca din segment.py) peste fundalul ales
                if aid not in tl.mattes or not os.path.exists(tl.mattes[aid]):
                    raise ValueError(f"lipsește masca persoanei pentru {aid}: rulează background pe {c.id}")
                mi = add_input(os.path.abspath(tl.mattes[aid]), t_in, src_d)
                frame = _frame(tl, c, vm, W, H)
                filters.append(f"{src}{speed}{_lut(tl, aid)}{frame},setsar=1,fps={tl.fps:g},format=yuv420p[fg{k}]")
                filters.append(f"[{mi}:v]{speed}scale={vm.width}:{vm.height},{frame},fps={tl.fps:g},format=gray[mk{k}]")
                if c.bg.mode in ("blur", "bw", "dim"):
                    look = {"blur": f"gblur=sigma={min(W, H) * 0.03:.1f}",
                            "bw": "hue=s=0,eq=contrast=1.08",
                            "dim": f"eq=brightness=-0.16:saturation=0.55,gblur=sigma={min(W, H) * 0.008:.1f}"}
                    filters.append(f"[fg{k}]split[fgs{k}][bgs{k}]")
                    filters.append(f"[bgs{k}]{look[c.bg.mode]}[bg{k}]")
                    fg = f"fgs{k}"
                elif c.bg.mode in ("color", "silhouette"):
                    col = c.bg.value or ("#FFFFFF" if c.bg.mode == "silhouette" else "#101010")
                    ci = add_input(f"color=c=0x{col.lstrip('#')}:s={W}x{H}:r={tl.fps:g}", t=c.body,
                                   pre=["-f", "lavfi"])
                    filters.append(f"[{ci}:v]setsar=1,format=yuv420p[bg{k}]")
                    fg = f"fg{k}"
                    if c.bg.mode == "silhouette":  # persoana devine o formă neagră plină
                        filters.append(f"[fg{k}]lutrgb=r=0:g=0:b=0[fgk{k}]")
                        fg = f"fgk{k}"
                elif c.bg.mode == "studio":
                    png = os.path.join(workdir, f"studio_{k}.png")
                    studio_png(png, W, H, c.bg.value or "#E9E7E3")
                    si = add_input(png, pre=["-loop", "1", "-framerate", f"{tl.fps:g}"], t=c.body)
                    filters.append(f"[{si}:v]setsar=1,format=yuv420p[bg{k}]")
                    fg = f"fg{k}"
                else:
                    bm = assets[c.bg.value]
                    bi = add_input(media_path(tl, c.bg.value, bm), 0.0, c.body, pre=["-stream_loop", "-1"])
                    bw, bh, bx, by = crop_box(bm.width, bm.height, tl.width, tl.height, Crop())
                    filters.append(f"[{bi}:v]setpts=PTS-STARTPTS,{_lut(tl, c.bg.value)}crop={bw}:{bh}:{bx}:{by},"
                                   f"scale={W}:{H},setsar=1,fps={tl.fps:g},format=yuv420p[bg{k}]")
                    fg = f"fg{k}"
                filters.append(f"[{fg}][mk{k}]alphamerge[fa{k}]")
                b = c.bg
                xf, foot = subject_xform(c, W, H, tl.fps)
                if b.mode in ("studio", "color") or xf:
                    filters.append(f"[fa{k}]{xf or 'null'},split[fpz{k}][fs{k}]")
                    if b.mode in ("studio", "color"):
                        # umbra de contact: silueta turtită la 7% din înălțime, încețoșată, cu linia picioarelor
                        # (rândul foot din cadru = rândul foot*0.07 din bandă) chiar sub picioare
                        band = max(2, int(H * 0.07) // 2 * 2)
                        filters.append(f"[fs{k}]alphaextract,scale={W}:{band},gblur=sigma={min(W, H) * 0.02:.1f},"
                                       f"lut=y='val*0.55',split[sm{k}][sk{k}]")
                        filters.append(f"[sk{k}]lut=y=0,format=yuv420p[sb{k}]")
                        filters.append(f"[sb{k}][sm{k}]alphamerge[sh{k}]")
                        filters.append(f"[bg{k}][sh{k}]overlay=x=0:y='{foot}*(1-{band / H:.4f})+{H * 0.008:.1f}'"
                                       f":format=auto:shortest=1[bgs{k}]")
                        base = f"bgs{k}"
                    else:
                        filters.append(f"[fs{k}]nullsink")
                        base = f"bg{k}"
                    filters.append(f"[{base}][fpz{k}]overlay=format=auto:shortest=1{_fx(c, W, H, tl.fps, media)},{tail}")
                else:
                    filters.append(f"[bg{k}][fa{k}]overlay=format=auto:shortest=1{_fx(c, W, H, tl.fps, media)},{tail}")
            elif tl.fill == "blur":  # clipul întreg în mijloc, peste o copie a lui mărită și încețoșată
                filters.append(f"{src}{speed}{_lut(tl, aid)}split[bfa{k}][bfb{k}]")
                filters.append(f"[bfa{k}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                               f"gblur=sigma={min(W, H) * 0.04:.1f},eq=brightness=-0.06[bfg{k}]")
                filters.append(f"[bfb{k}]scale={W}:{H}:force_original_aspect_ratio=decrease[bff{k}]")
                filters.append(f"[bfg{k}][bff{k}]overlay=(W-w)/2:(H-h)/2{_zoom_anim(c, W, H)}{_fx(c, W, H, tl.fps, media)},{tail}")
            else:
                filters.append(f"{src}{speed}{fit_filter(tl, c, vm, W, H, media)},{tail}")
        # sunetul vine mereu din c.asset (sursa de timp); cu alt unghi, e o intrare separată
        if m.has_audio:
            ai = f"{vi}:a" if vi is not None and not c.angle else \
                f"{add_input(media_path(tl, c.asset, m), c.src_in, src_d)}:a"
            tempo = _atempo(c.speed) if c.speed != 1 else ""
            pad = f"apad=pad_dur={c.freeze:.3f}," if c.freeze > 0 else ""
        else:
            ai = f"{add_input('anullsrc=r=48000:cl=stereo', t=d, pre=['-f', 'lavfi'])}:a"
            tempo = pad = ""
        fade = min(0.01, d / 4)
        vol = "0" if c.volume_db <= -90 else f"{c.volume_db:g}dB"
        filters.append(
            f"[{ai}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
            f"{_audio_fx(tl, c.asset)}{tempo}{pad}atrim=0:{d:.3f},volume={vol},"
            f"afade=t=in:d={fade:.3f},afade=t=out:st={max(d - fade, 0):.3f}:d={fade:.3f}[a{k}]"
        )
    filters += _join(tl, W)

    vlabel = "vc"
    for j, bf in enumerate(tl.beat_fx):  # pulsuri pe beat, pe imaginea lipită (sub grafice și text)
        filters.append(f"[{vlabel}]{_beat_filter(bf, W, H, tl.fps)}[vbf{j}]")
        vlabel = f"vbf{j}"
    leaks = [(k, c.transition) for k, c in enumerate(tl.clips) if c.transition and c.transition.type == "lightleak"]
    if leaks:  # light leak: pete de lumină randate în Chromium (bloc intern), peste fereastra tranziției
        from pathlib import Path as _P

        from .motion import render_frames
        from .motion.engine import cache_key

        root = _P(os.environ.get("VEDIT_HOME", "./vedit_projects")).resolve() / ".motion"
        starts_ = tl.starts()
        for j, (k, tr) in enumerate(leaks):
            dur = round(max(0.6, tr.duration * 2.4), 3)
            t0 = max(0.0, starts_[k] + tr.duration / 2 - dur / 2)
            key = cache_key("light_leak", {}, {}, W, H, tl.fps, dur, {})
            d = render_frames("light_leak", {}, {}, W, H, tl.fps, dur, root / key)
            li = add_input(os.path.join(str(d), "%05d.png"), pre=["-framerate", f"{tl.fps:g}", "-start_number", "0"])
            filters.append(f"[{li}:v]format=rgba,setpts=PTS-STARTPTS+{t0:.3f}/TB[lk{j}]")
            filters.append(f"[{vlabel}][lk{j}]overlay=format=auto:eof_action=pass:"
                           f"enable='between(t,{t0:.3f},{t0 + dur - 0.001:.3f})'[vlk{j}]")
            vlabel = f"vlk{j}"
    # ---- pista V2 (B-roll): overlay la timpul lui, sub subtitrări; sunetul rămâne cel de pe V1
    for k, b in enumerate(sorted(tl.broll, key=lambda b: b.start)):
        if b.start >= off + main_dur - 0.04:
            continue
        m = assets[b.asset]
        dur = min(b.duration, off + main_dur - b.start)
        bi = add_input(media_path(tl, b.asset, m), b.src_in, dur)
        margin = _even(min(W, H) * 0.04)
        if b.frame:  # fereastră cu ramă (colțuri rotunde / telefon / laptop), umbră și alunecare la intrare
            from . import layouts

            g = layouts.geometry(b.frame, W, H, b.pip_scale, m.width / max(m.height, 1))
            fa = layouts.assets(b.frame, g)
            pos = b.pip_pos if b.mode == "pip" else "center"
            if b.frame in ("phone", "laptop") and pos in ("tl", "tr", "bl", "br") and b.pip_pos == "tr":
                pos = "center"
            X0 = {"center": (W - g["w"]) // 2, "left": margin * 2, "right": W - g["w"] - margin * 2,
                  "tl": margin, "bl": margin, "tr": W - g["w"] - margin, "br": W - g["w"] - margin}[pos]
            Y0 = {"tl": margin, "tr": margin, "bl": H - g["h"] - margin, "br": H - g["h"] - margin}.get(pos, (H - g["h"]) // 2)
            slide = f"pow(1-min(max((t-{b.start:.3f})/0.55,0),1),3)*{_even(H * 0.12)}"  # intră de jos, se așază lent
            en = f"enable='between(t,{b.start:.3f},{b.start + dur - 0.001:.3f})'"
            pad = fa["pad"]
            si = add_input(str(fa["shadow"]), t=dur, pre=["-loop", "1"])
            filters.append(f"[{si}:v]format=rgba,setpts=PTS-STARTPTS+{b.start:.3f}/TB[bsh{k}]")
            filters.append(f"[{vlabel}][bsh{k}]overlay=x={X0 - pad}:y='{Y0 - pad}+{slide}':eof_action=pass:{en}[bs{k}]")
            cw, ch, cx, cy = crop_box(m.width, m.height, g["sw"], g["sh"], b)
            mi = add_input(str(fa["mask"]), t=dur, pre=["-loop", "1"])
            filters.append(f"[{bi}:v]{_lut(tl, b.asset)}crop={cw}:{ch}:{cx}:{cy},scale={g['sw']}:{g['sh']},setsar=1,"
                           f"fps={tl.fps:g},format=yuva420p[bv{k}]")
            filters.append(f"[{mi}:v]format=gray,scale={g['sw']}:{g['sh']}[bm{k}]")
            filters.append(f"[bv{k}][bm{k}]alphamerge,setpts=PTS-STARTPTS+{b.start:.3f}/TB[b{k}]")
            filters.append(f"[bs{k}][b{k}]overlay=x={X0 + g['sx']}:y='{Y0 + g['sy']}+{slide}':eof_action=pass:{en}[bo{k}]")
            vlabel = f"bo{k}"
            if fa["frame"] is not None:
                fi = add_input(str(fa["frame"]), t=dur, pre=["-loop", "1"])
                filters.append(f"[{fi}:v]format=rgba,setpts=PTS-STARTPTS+{b.start:.3f}/TB[bf{k}]")
                filters.append(f"[{vlabel}][bf{k}]overlay=x={X0}:y='{Y0}+{slide}':eof_action=pass:{en}[o{k}]")
                vlabel = f"o{k}"
            continue
        if b.mode == "pip":
            pw = _even(W * b.pip_scale)
            fit = f"scale={pw}:-2"
            x = margin if b.pip_pos in ("tl", "bl") else f"W-w-{margin}"
            y = margin if b.pip_pos in ("tl", "tr") else f"H-h-{margin}"
        else:
            cw, ch, cx, cy = crop_box(m.width, m.height, tl.width, tl.height, b)
            fit = f"crop={cw}:{ch}:{cx}:{cy},scale={W}:{H}"
            x = y = 0
        # green screen: fundalul devine transparent, deci se vede montajul de pe V1
        key = f",format=yuva420p,colorkey=0x{b.chroma.lstrip('#')}:0.32:0.08" if b.chroma else ",format=yuv420p"
        filters.append(f"[{bi}:v]{_lut(tl, b.asset)}{fit},setsar=1,fps={tl.fps:g}{key},"
                       f"setpts=PTS-STARTPTS+{b.start:.3f}/TB[b{k}]")
        filters.append(f"[{vlabel}][b{k}]overlay=x={x}:y={y}:eof_action=pass:"
                       f"enable='between(t,{b.start:.3f},{b.start + dur - 0.001:.3f})'[o{k}]")
        vlabel = f"o{k}"

    # ---- logo (brand): peste V1 + V2, sub subtitrări/titluri; doar pe montaj, nu peste intro/outro
    logo = tl.brand.logo
    if logo:
        if not os.path.exists(logo.path):
            raise FileNotFoundError("logo-ul brandului lipsește de pe disc; reîncarcă-l cu brand_logo")
        li = add_input(os.path.abspath(logo.path))
        margin = _even(min(W, H) * logo.margin)
        x = margin if logo.position in ("tl", "bl") else f"W-w-{margin}"
        y = margin if logo.position in ("tl", "tr") else f"H-h-{margin}"
        filters.append(f"[{li}:v]scale={_even(W * logo.scale)}:-2,format=rgba,"
                       f"colorchannelmixer=aa={min(max(logo.opacity, 0), 1):.3f}[logo]")
        filters.append(f"[{vlabel}][logo]overlay=x={x}:y={y}:format=auto:"
                       f"enable='between(t,{off:.3f},{off + main_dur:.3f})'[vl]")
        vlabel = "vl"

    # Straturile din spatele persoanei (blocuri de motion și grafice cu behind) se pun direct peste imagine, apoi
    # persoana decupată (masca din segment.py) se pune DIN NOU peste ele: textul pare în spatele ei.
    mframes = list(motion_frames(tl, assets, W, H)) if tl.motion else []

    def motion_layer(items):
        nonlocal vlabel
        for k, (mv, frames, _layer) in items:  # cadre PNG cu alfa (randate o dată, în cache)
            mi = add_input(os.path.join(frames, "%05d.png"), pre=["-framerate", f"{tl.fps:g}", "-start_number", "0"])
            filters.append(f"[{mi}:v]format=rgba,setpts=PTS-STARTPTS+{mv.start:.3f}/TB[mo{k}]")
            filters.append(f"[{vlabel}][mo{k}]overlay=format=auto:eof_action=pass:"
                           f"enable='between(t,{mv.start:.3f},{mv.end - 0.001:.3f})'[vm{k}]")
            vlabel = f"vm{k}"

    def graphics_layer(name, gs):
        nonlocal vlabel
        from .graphics import graphics_ass

        with open(os.path.join(workdir, f"graphics_{name}.ass"), "w", encoding="utf-8") as fh:
            fh.write(graphics_ass(tl.model_copy(update={"graphics": gs}), W, H))
        filters.append(f"[{vlabel}]ass=filename=graphics_{name}.ass:fontsdir={fonts_dir(tl, workdir)}[vg_{name}]")
        vlabel = f"vg_{name}"

    behind_m = [(k, x) for k, x in enumerate(mframes) if x[0].behind and x[2] != "front"]
    behind_g = [g for g in tl.graphics if g.behind]
    motion_layer(behind_m)
    if behind_g:
        graphics_layer("behind", behind_g)
    spans = [(x[0].start, x[0].end) for _, x in behind_m] + [(g.start, g.end) for g in behind_g]
    if spans:  # persoana decupată din nou, peste ce e în spatele ei
        starts = tl.starts()
        for k, (c, s) in enumerate(zip(tl.clips, starts)):
            aid = c.angle or c.asset
            if c.split or aid not in tl.mattes or not any(a < s + c.duration and b > s for a, b in spans):
                continue
            vm = assets[aid]
            t_in = tl.angle_time(c, aid, c.src_in)
            src_d = c.src_out - c.src_in
            pi = add_input(media_path(tl, aid, vm), t_in, src_d)
            psrc = hide(f"p{k}", c, aid, vm, pi, t_in, src_d)
            mi = add_input(os.path.abspath(tl.mattes[aid]), t_in, src_d)
            speed = f"setpts=(PTS-STARTPTS)/{c.speed:g}," if c.speed != 1 else "setpts=PTS-STARTPTS,"
            frame = _frame(tl, c, vm, W, H)
            sil = ",lutrgb=r=0:g=0:b=0" if c.bg and c.bg.mode == "silhouette" else ""
            filters.append(f"{psrc}{speed}{_lut(tl, aid)}{frame},setsar=1,fps={tl.fps:g},format=yuv420p{sil}[pf{k}]")
            filters.append(f"[{mi}:v]{speed}scale={vm.width}:{vm.height},{frame},fps={tl.fps:g},format=gray[pm{k}]")
            xf, _ = subject_xform(c, W, H, tl.fps)  # aceeași mutare ca în imagine
            filters.append(f"[pf{k}][pm{k}]alphamerge{',' + xf if xf else ''},setpts=PTS+{s:.3f}/TB[pa{k}]")
            # doar cât se vede ceva în spate și NU în ferestrele de tranziție (acolo imaginea e amestecul a două
            # clipuri care se mișcă; persoana pusă fix peste el ar apărea dublată)
            lo = s + (c.transition.duration if c.transition else 0.0)
            nxt = tl.clips[k + 1] if k + 1 < len(tl.clips) else None
            hi = s + c.duration - (nxt.transition.duration if nxt is not None and nxt.transition else 0.0)
            on = "+".join(f"between(t,{max(a, lo):.3f},{min(b, hi) - 0.001:.3f})"
                          for a, b in spans if a < hi and b > lo)
            if not on:
                continue
            filters.append(f"[{vlabel}][pa{k}]overlay=format=auto:eof_action=pass:enable='{on}'[pv{k}]")
            vlabel = f"pv{k}"

    front_g = [g for g in tl.graphics if not g.behind]
    if front_g:  # motion graphics (libass): peste imagine și logo, sub subtitrări
        graphics_layer("front", front_g)
    motion_layer([(k, x) for k, x in enumerate(mframes) if not x[0].behind or x[2] == "front"])

    motion_caps = tl.caption_engine == "motion" and bool(tl.captions)
    if motion_caps:  # subtitrări prin motorul de motion: o frază = un set de cadre (cache pe frază)
        for k, (cap, frames) in enumerate(caption_frames(tl, W, H)):
            ci = add_input(os.path.join(frames, "%05d.png"), pre=["-framerate", f"{tl.fps:g}", "-start_number", "0"])
            filters.append(f"[{ci}:v]format=rgba,setpts=PTS-STARTPTS+{cap.start:.3f}/TB[cp{k}]")
            filters.append(f"[{vlabel}][cp{k}]overlay=format=auto:eof_action=pass:"
                           f"enable='between(t,{cap.start:.3f},{cap.end - 0.001:.3f})'[vcp{k}]")
            vlabel = f"vcp{k}"
    ass_tl = tl.model_copy(update={"captions": []}) if motion_caps else tl
    if ass_tl.captions or ass_tl.texts:
        with open(os.path.join(workdir, "captions.ass"), "w", encoding="utf-8") as fh:
            fh.write(to_ass(ass_tl))
        filters.append(f"[{vlabel}]ass=filename=captions.ass:fontsdir={fonts_dir(tl, workdir)}[vs]")
        vlabel = "vs"

    alabel = "ac"
    nar = tl.narration
    if nar and nar.start < main_dur:  # voice-over-ul intră în „voce”, deci muzica se coboară și sub el
        nm = assets[nar.asset]
        ni = add_input(os.path.abspath(nm.path))
        delay = int(round((nar.start + off) * 1000))
        filters.append(f"[{ni}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                       f"atrim=0:{max(main_dur - nar.start, 0.05):.3f},volume={nar.volume_db:g}dB,"
                       f"adelay={delay}:all=1[nar]")
        filters.append("[ac][nar]amix=inputs=2:duration=first:normalize=0[acn]")
        alabel = "acn"
    if tl.music:  # muzica acoperă doar montajul; intro/outro au sunetul lor
        mm = assets[tl.music.asset]
        mi = add_input(os.path.abspath(mm.path), tl.music.src_in, pre=["-stream_loop", "-1"])
        delay = f",adelay={int(off * 1000)}:all=1" if off else ""
        filters.append(
            f"[{mi}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{main_dur:.3f},volume={tl.music.volume_db:g}dB,"
            f"afade=t=out:st={max(main_dur - (0.25 if tl.music.ends_naturally else 1.5), 0):.3f}"
            f":d={0.25 if tl.music.ends_naturally else 1.5}{delay}[mus]"
        )
        if tl.music.duck:
            filters.append(f"[{alabel}]asplit=2[voice][sc]")
            filters.append("[mus][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck]")
            filters.append("[voice][duck]amix=inputs=2:duration=first:normalize=0[am]")
        else:
            filters.append(f"[{alabel}][mus]amix=inputs=2:duration=first:normalize=0[am]")
        alabel = "am"
    sfx = [s for s in sorted(tl.sfx, key=lambda s: s.at) if s.at < off + main_dur]
    if sfx:  # efecte sonore peste mixaj (după ducking: nu coboară muzica)
        from .sfx import sfx_path

        labels = []
        for k, s in enumerate(sfx):
            src = os.path.abspath(assets[s.kind].path) if s.kind in assets else str(sfx_path(s.kind, s.at))
            si = add_input(src)
            cut = f"atrim=0:{s.dur:.3f},afade=t=out:st={max(s.dur - 0.01, 0):.3f}:d=0.01," if s.dur else ""
            filters.append(f"[{si}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,{cut}"
                           f"volume={s.volume_db:g}dB,adelay={int(round(max(s.at, 0) * 1000))}:all=1[fx{k}]")
            labels.append(f"[fx{k}]")
        filters.append(f"[{alabel}]{''.join(labels)}amix=inputs={len(labels) + 1}:duration=first:normalize=0[asfx]")
        alabel = "asfx"
    silent = not tl.music and not sfx and not nar and all(
        c.volume_db <= -90 or not assets[c.asset].has_audio for c in tl.clips)
    if silent:  # loudnorm pe liniște totală dă NaN și encoderul AAC refuză fișierul
        filters.append(f"[{alabel}]anull[aout]")
    else:
        filters.append(f"[{alabel}]loudnorm=I={tl.loudness_lufs:g}:TP=-1.5:LRA=11,aresample=48000[aout]")

    if tl.visualizer:  # unda sunetului final, peste imagine (audiogram)
        vz = tl.visualizer
        vh = _even(H * vz.height)
        col = "0x" + vz.color.lstrip("#")
        filters[-1] = filters[-1].replace("[aout]", "[aout0]")
        filters.append("[aout0]asplit[aout][aviz]")
        # desenat la jumătate de rezoluție și mărit: linii mai groase, vizibile pe telefon
        hw, hh = _even(W / 2), _even(vh / 2)
        if vz.style == "bars":
            draw = (f"showfreqs=s={hw}x{hh}:mode=bar:ascale=sqrt:fscale=log:win_size=2048:colors={col},"
                    f"crop={hw}:{hh}:0:0,scale={W}:{vh}:flags=neighbor")
        else:
            draw = (f"showwaves=s={hw}x{hh}:mode={'cline' if vz.style == 'wave' else 'line'}:rate={tl.fps:g}"
                    f":scale=sqrt:draw=full:colors={col},scale={W}:{vh}")
        y = {"top": f"{_even(H * 0.06)}", "center": f"{(H - vh) // 2}", "bottom": f"{H - vh - _even(H * 0.08)}"}
        # doar desenul primește volum normalizat: unda se vede și la voce încetă; sunetul final rămâne neatins.
        # Fundalul undei e deja transparent; un colorkey aici face ffmpeg 6.1 să umple memoria (GB-uri).
        filters.append(f"[aviz]aformat=channel_layouts=mono,dynaudnorm=f=100:g=9,{draw},fps={tl.fps:g},format=rgba[viz]")
        filters.append(f"[{vlabel}][viz]overlay=0:{y[vz.position]}:shortest=1:format=auto[vzout]")
        vlabel = "vzout"

    enc = ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"] if preview else encoder_args()
    pix = ["-pix_fmt", "yuv420p"]
    if enc and enc[0] == "@vaapi":  # VAAPI: cadrele se urcă pe GPU la final, encoderul lucrează acolo
        args = ["-y", "-vaapi_device", os.environ.get("VEDIT_VAAPI_DEVICE", "/dev/dri/renderD128"), *args[1:]]
        filters.append(f"[{vlabel}]format=nv12,hwupload[venc]")
        vlabel, enc, pix = "venc", enc[1:], []
    args += ["-filter_complex", ";".join(filters), "-map", f"[{vlabel}]", "-map", "[aout]"]
    args += enc
    args += [*pix, "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             "-t", f"{tl.duration:.3f}", os.path.abspath(out_path)]
    return args, workdir


# Encodere hardware, cu calitate apropiată de libx264 crf 19. VEDIT_ENCODER: libx264 (implicit), auto (cel mai rapid
# care chiar merge pe mașina asta), videotoolbox (Mac), qsv / vaapi (Intel, AMD), nvenc (NVIDIA).
HW_ENCODERS = {
    "videotoolbox": ["-c:v", "h264_videotoolbox", "-q:v", "62", "-profile:v", "high", "-allow_sw", "1"],
    "nvenc": ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-profile:v", "high"],
    "qsv": ["-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "21", "-look_ahead", "1", "-profile:v", "high"],
    # „@vaapi” = marcaj pentru build_command: adaugă -vaapi_device și urcarea pe GPU (format=nv12,hwupload)
    "vaapi": ["@vaapi", "-c:v", "h264_vaapi", "-rc_mode", "CQP", "-qp", "21", "-profile:v", "high"],
}
X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high"]
_hw_ok: dict[str, bool] = {}


def _hw_works(name: str) -> bool:
    """Un encoder poate apărea în listă fără să meargă (fără driver / GPU): îl încercăm o dată, pe 10 cadre."""
    if name not in _hw_ok:
        import subprocess

        from .ff import ffmpeg_bin

        enc = HW_ENCODERS[name]
        if enc[0] == "@vaapi":
            dev = os.environ.get("VEDIT_VAAPI_DEVICE", "/dev/dri/renderD128")
            cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-vaapi_device", dev, "-f", "lavfi", "-i",
                   "testsrc2=s=320x240:d=0.4", "-vf", "format=nv12,hwupload", *enc[1:], "-f", "null", "-"]
        else:
            cmd = [ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                   "testsrc2=s=320x240:d=0.4", "-pix_fmt", "yuv420p", *enc, "-f", "null", "-"]
        try:
            _hw_ok[name] = subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _hw_ok[name] = False
    return _hw_ok[name]


def encoder_args() -> list[str]:
    choice = os.environ.get("VEDIT_ENCODER", "libx264").lower()
    if choice in HW_ENCODERS:
        if _hw_works(choice):
            return HW_ENCODERS[choice]
        return X264  # cerut, dar nu merge aici: calitatea rămâne, doar viteza scade
    if choice == "auto":
        import sys

        order = ["videotoolbox"] if sys.platform == "darwin" else ["nvenc", "qsv", "vaapi"]
        for name in order:
            if _hw_works(name):
                return HW_ENCODERS[name]
    return X264


def render(tl: Timeline, assets: dict[str, MediaInfo], out_path: str, preview: bool = False) -> str:
    args, workdir = build_command(tl, assets, out_path, preview=preview)
    # plafon generos: de ~40x durata (surse 4K, multe straturi), minim 5 min; VEDIT_RENDER_TIMEOUT îl suprascrie
    limit = float(os.environ.get("VEDIT_RENDER_TIMEOUT", 0)) or max(300.0, tl.output_duration * 40)
    run(args, cwd=workdir, timeout=limit)
    return os.path.abspath(out_path)


def still_video(out_path: str, duration: float, width: int, height: int, image: str | None = None,
                color: str = "#101820", fps: float = 30) -> str:
    """Un fundal fix cât `duration`: poza dată (umple cadrul, cu crop) sau o culoare. Pentru audiogram."""
    size = f"{_even(width)}x{_even(height)}"
    if not image:
        src = ["-f", "lavfi", "-i", f"color=c=0x{color.lstrip('#')}:s={size}:r={fps:g}"]
    elif image.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".bmp")):
        src = ["-loop", "1", "-framerate", f"{fps:g}", "-i", os.path.abspath(image)]
    else:  # poză deja convertită în clip fix sau un clip scurt: îl repetăm
        src = ["-stream_loop", "-1", "-i", os.path.abspath(image)]
    vf = f"scale={size.replace('x', ':')}:force_original_aspect_ratio=increase,crop={size.replace('x', ':')},setsar=1"
    run(["-y", *src, "-t", f"{duration:.3f}", "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast",
         "-tune", "stillimage", "-crf", "20", "-pix_fmt", "yuv420p", os.path.abspath(out_path)],
        timeout=max(120.0, duration * 2))
    return os.path.abspath(out_path)


def cut_audio(src: str, start: float, end: float, out_path: str) -> str:
    """Fragmentul [start, end) dintr-un fișier cu sunet, ca WAV 48 kHz (fără reencodare cu pierderi)."""
    run(["-y", "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", os.path.abspath(src), "-vn",
         "-ar", "48000", "-c:a", "pcm_s16le", os.path.abspath(out_path)], timeout=300)
    return os.path.abspath(out_path)
