"""Compilează Timeline -> o singură comandă ffmpeg (filter_complex). Determinist, fără LLM.

Ordinea straturilor, de jos în sus: V1 (clipuri + grading + intro/outro) -> V2 (B-roll) -> logo -> subtitrări și titluri.
"""
from __future__ import annotations

import os
import tempfile

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


def _fx(c: Clip, W: int, H: int) -> str:
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
    return "," + ",".join(out) if out else ""


def media_path(tl: Timeline, aid: str, m: MediaInfo) -> str:
    """Sursa folosită la randare: varianta stabilizată, dacă există."""
    p = tl.stabilized.get(aid)
    return os.path.abspath(p if p and os.path.exists(p) else m.path)


EASE = {
    "inout": "(1-cos(PI*{p}))/2",
    "in": "({p})*({p})",
    "out": "1-(1-{p})*(1-{p})",
    "linear": "{p}",
}


def _zoom_anim(c: Clip, W: int, H: int) -> str:
    """Zoom animat: scalare pe fiecare cadru (netedă, sub-pixel) + crop fix la dimensiunea output-ului."""
    if not c.anim:
        return ""
    a = c.anim
    p = f"min(t/{max(c.body, 0.04):.4f},1)"
    z = f"({a.zoom_from:g}+({a.zoom_to:g}-{a.zoom_from:g})*{EASE[a.ease].format(p=p)})"
    # crop își fixează iw/ih la primul cadru, deci centrul îl calculăm din aceeași formulă a zoom-ului
    return (f",scale=w='ceil({W}*{z}/2)*2':h='ceil({H}*{z}/2)*2':eval=frame,"
            f"crop={W}:{H}:x='floor({W}*({z}-1)/2)':y='floor({H}*({z}-1)/2)'")


def _audio_fx(tl: Timeline, asset: str) -> str:
    from .audiofx import AudioFx, chain

    fx = tl.audio_fx.get(asset)
    return f"{chain(AudioFx(**fx))}," if fx else ""


def _join(tl: Timeline) -> list[str]:
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
        out.append(f"[{v}][{gv}]xfade=transition={tr.type}:duration={tr.duration:.3f}:"
                   f"offset={starts[groups[g][0]]:.3f}[{nv}]")
        out.append(f"[{a}][{ga}]acrossfade=d={tr.duration:.3f}:c1=tri:c2=tri[{na}]")
        v, a = nv, na
    return out


def _lut(tl: Timeline, asset: str) -> str:
    grade = tl.grades.get(asset)
    if grade and os.path.exists(grade.lut):
        lut = grade.lut.replace("\\", "/").replace("'", r"\'")
        return f"lut3d=file='{lut}':interp=tetrahedral,"
    return ""


def _frame(tl: Timeline, c: Clip, m: MediaInfo, W: int, H: int) -> str:
    """Încadrarea (crop/pad) + zoom animat, fără culoare: aceeași pentru imagine și pentru masca persoanei."""
    if tl.fill == "crop":
        # fereastra pe aspectul timeline-ului: preview-ul și finalul au exact aceeași încadrare
        cw, ch, x, y = crop_box(m.width, m.height, tl.width, tl.height, c)
        fit = f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}"
    else:  # pad (și geometria lui „blur”: imaginea întreagă, centrată)
        fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
    return fit + _zoom_anim(c, W, H)


def fit_filter(tl: Timeline, c: Clip, m: MediaInfo, W: int, H: int) -> str:
    """Grading + încadrare (crop/pad) + zoom animat + efecte, pentru un clip cu o singură imagine.
    `m` e media unghiului afișat (c.angle sau c.asset)."""
    return _lut(tl, c.angle or c.asset) + _frame(tl, c, m, W, H) + _fx(c, W, H)


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
        for s in out.sfx:
            s.at += off
    if b.outro:
        m = assets[b.outro]
        out.clips.append(Clip(id="_outro", asset=b.outro, src_in=0, src_out=round(b.outro_dur or m.duration, 3)))
    return out, off


def build_command(tl: Timeline, assets: dict[str, MediaInfo], out_path: str, *,
                  preview: bool = False, workdir: str | None = None) -> tuple[list[str], str]:
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

    for k, c in enumerate(tl.clips):
        m = assets[c.asset]
        d, src_d = c.duration, c.src_out - c.src_in
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
            filters.append(f"{''.join(panes)}{stack}=inputs=2,scale={W}:{H}{_fx(c, W, H)},{tail}")
        else:
            aid = c.angle or c.asset
            vm = assets[aid]
            t_in = tl.angle_time(c, aid, c.src_in)
            vi = add_input(media_path(tl, aid, vm), t_in, src_d)
            if c.bg:  # persoana decupată (masca din segment.py) peste fundalul ales
                if aid not in tl.mattes or not os.path.exists(tl.mattes[aid]):
                    raise ValueError(f"lipsește masca persoanei pentru {aid}: rulează background pe {c.id}")
                mi = add_input(os.path.abspath(tl.mattes[aid]), t_in, src_d)
                frame = _frame(tl, c, vm, W, H)
                filters.append(f"[{vi}:v]{speed}{_lut(tl, aid)}{frame},setsar=1,fps={tl.fps:g},format=yuv420p[fg{k}]")
                filters.append(f"[{mi}:v]{speed}scale={vm.width}:{vm.height},{frame},fps={tl.fps:g},format=gray[mk{k}]")
                if c.bg.mode == "blur":
                    filters.append(f"[fg{k}]split[fgs{k}][bgs{k}]")
                    filters.append(f"[bgs{k}]gblur=sigma={min(W, H) * 0.03:.1f}[bg{k}]")
                    fg = f"fgs{k}"
                elif c.bg.mode == "color":
                    ci = add_input(f"color=c=0x{c.bg.value.lstrip('#')}:s={W}x{H}:r={tl.fps:g}", t=c.body,
                                   pre=["-f", "lavfi"])
                    filters.append(f"[{ci}:v]setsar=1,format=yuv420p[bg{k}]")
                    fg = f"fg{k}"
                else:
                    bm = assets[c.bg.value]
                    bi = add_input(media_path(tl, c.bg.value, bm), 0.0, c.body, pre=["-stream_loop", "-1"])
                    bw, bh, bx, by = crop_box(bm.width, bm.height, tl.width, tl.height, Crop())
                    filters.append(f"[{bi}:v]setpts=PTS-STARTPTS,{_lut(tl, c.bg.value)}crop={bw}:{bh}:{bx}:{by},"
                                   f"scale={W}:{H},setsar=1,fps={tl.fps:g},format=yuv420p[bg{k}]")
                    fg = f"fg{k}"
                filters.append(f"[{fg}][mk{k}]alphamerge[fa{k}]")
                filters.append(f"[bg{k}][fa{k}]overlay=format=auto:shortest=1{_fx(c, W, H)},{tail}")
            elif tl.fill == "blur":  # clipul întreg în mijloc, peste o copie a lui mărită și încețoșată
                filters.append(f"[{vi}:v]{speed}{_lut(tl, aid)}split[bfa{k}][bfb{k}]")
                filters.append(f"[bfa{k}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                               f"gblur=sigma={min(W, H) * 0.04:.1f},eq=brightness=-0.06[bfg{k}]")
                filters.append(f"[bfb{k}]scale={W}:{H}:force_original_aspect_ratio=decrease[bff{k}]")
                filters.append(f"[bfg{k}][bff{k}]overlay=(W-w)/2:(H-h)/2{_zoom_anim(c, W, H)}{_fx(c, W, H)},{tail}")
            else:
                filters.append(f"[{vi}:v]{speed}{fit_filter(tl, c, vm, W, H)},{tail}")
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
    filters += _join(tl)

    vlabel = "vc"
    # ---- pista V2 (B-roll): overlay la timpul lui, sub subtitrări; sunetul rămâne cel de pe V1
    for k, b in enumerate(sorted(tl.broll, key=lambda b: b.start)):
        if b.start >= off + main_dur - 0.04:
            continue
        m = assets[b.asset]
        dur = min(b.duration, off + main_dur - b.start)
        bi = add_input(media_path(tl, b.asset, m), b.src_in, dur)
        margin = _even(min(W, H) * 0.04)
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

    if tl.graphics:  # motion graphics: peste imagine și logo, sub subtitrări
        from .graphics import graphics_ass

        layers = [("behind", [g for g in tl.graphics if g.behind]), ("front", [g for g in tl.graphics if not g.behind])]
        for name, gs in layers:
            if not gs:
                continue
            with open(os.path.join(workdir, f"graphics_{name}.ass"), "w", encoding="utf-8") as fh:
                fh.write(graphics_ass(tl.model_copy(update={"graphics": gs}), W, H))
            filters.append(f"[{vlabel}]ass=filename=graphics_{name}.ass:fontsdir={fonts_dir(tl, workdir)}[vg_{name}]")
            vlabel = f"vg_{name}"
            if name == "behind":  # persoana decupată din nou, peste text: textul pare în spatele ei
                starts = tl.starts()
                for k, (c, s) in enumerate(zip(tl.clips, starts)):
                    aid = c.angle or c.asset
                    if c.split or aid not in tl.mattes or not any(g.start < s + c.duration and g.end > s for g in gs):
                        continue
                    vm = assets[aid]
                    t_in = tl.angle_time(c, aid, c.src_in)
                    src_d = c.src_out - c.src_in
                    pi = add_input(media_path(tl, aid, vm), t_in, src_d)
                    mi = add_input(os.path.abspath(tl.mattes[aid]), t_in, src_d)
                    speed = f"setpts=(PTS-STARTPTS)/{c.speed:g}," if c.speed != 1 else "setpts=PTS-STARTPTS,"
                    frame = _frame(tl, c, vm, W, H)
                    filters.append(f"[{pi}:v]{speed}{_lut(tl, aid)}{frame},setsar=1,fps={tl.fps:g},format=yuv420p[pf{k}]")
                    filters.append(f"[{mi}:v]{speed}scale={vm.width}:{vm.height},{frame},fps={tl.fps:g},format=gray[pm{k}]")
                    filters.append(f"[pf{k}][pm{k}]alphamerge,setpts=PTS+{s:.3f}/TB[pa{k}]")
                    filters.append(f"[{vlabel}][pa{k}]overlay=format=auto:eof_action=pass:"
                                   f"enable='between(t,{s:.3f},{s + c.body - 0.001:.3f})'[pv{k}]")
                    vlabel = f"pv{k}"

    if tl.captions or tl.texts:
        with open(os.path.join(workdir, "captions.ass"), "w", encoding="utf-8") as fh:
            fh.write(to_ass(tl))
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
            f"afade=t=out:st={max(main_dur - 1.5, 0):.3f}:d=1.5{delay}[mus]"
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
            src = os.path.abspath(assets[s.kind].path) if s.kind in assets else str(sfx_path(s.kind))
            si = add_input(src)
            filters.append(f"[{si}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
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

    args += ["-filter_complex", ";".join(filters), "-map", f"[{vlabel}]", "-map", "[aout]"]
    if preview:
        args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "30"]
    else:
        args += ["-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high"]
    args += ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
             "-t", f"{tl.duration:.3f}", os.path.abspath(out_path)]
    return args, workdir


def render(tl: Timeline, assets: dict[str, MediaInfo], out_path: str, preview: bool = False) -> str:
    args, workdir = build_command(tl, assets, out_path, preview=preview)
    # plafon generos: de ~40x durata (surse 4K, multe straturi), minim 5 min; VEDIT_RENDER_TIMEOUT îl suprascrie
    limit = float(os.environ.get("VEDIT_RENDER_TIMEOUT", 0)) or max(300.0, tl.output_duration * 40)
    run(args, cwd=workdir, timeout=limit)
    return os.path.abspath(out_path)
