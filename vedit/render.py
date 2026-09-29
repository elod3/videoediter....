"""Compilează Timeline -> o singură comandă ffmpeg (filter_complex). Determinist, fără LLM.

Ordinea straturilor, de jos în sus: V1 (clipuri + grading + intro/outro) -> V2 (B-roll) -> logo -> subtitrări și titluri.
"""
from __future__ import annotations

import os
import tempfile

from .captions import fonts_dir, to_ass
from .ff import run
from .probe import MediaInfo
from .timeline import Clip, Timeline


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


def crop_box(src_w: int, src_h: int, out_w: int, out_h: int, clip: Clip) -> tuple[int, int, int, int]:
    """Cea mai mare fereastră cu aspectul output-ului, centrată pe (cx,cy), împărțită la zoom."""
    ar = out_w / out_h
    if src_w / src_h > ar:
        ch, cw = src_h, src_h * ar
    else:
        cw, ch = src_w, src_w / ar
    z = max(clip.crop.zoom, 1.0)
    cw, ch = _even(min(cw / z, src_w)), _even(min(ch / z, src_h))
    x = min(max(clip.crop.cx * src_w - cw / 2, 0), src_w - cw)
    y = min(max(clip.crop.cy * src_h - ch / 2, 0), src_h - ch)
    return cw, ch, int(x), int(y)


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
    p = f"min(t/{max(c.duration, 0.04):.4f},1)"
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


def fit_filter(tl: Timeline, c: Clip, m: MediaInfo, W: int, H: int) -> str:
    """Grading + încadrare (crop/pad) + zoom animat pentru un clip, la dimensiunea W x H."""
    if tl.fill == "crop":
        cw, ch, x, y = crop_box(m.width, m.height, tl.width, tl.height, c)
        fit = f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}"
    else:
        fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
    return _lut(tl, c.asset) + fit + _zoom_anim(c, W, H)


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
    if b.outro:
        m = assets[b.outro]
        out.clips.append(Clip(id="_outro", asset=b.outro, src_in=0, src_out=round(b.outro_dur or m.duration, 3)))
    return out, off


def build_command(tl: Timeline, assets: dict[str, MediaInfo], out_path: str, *,
                  preview: bool = False, workdir: str | None = None) -> tuple[list[str], str]:
    if not tl.clips:
        raise ValueError("timeline-ul e gol")
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
    for k, c in enumerate(tl.clips):
        m = assets[c.asset]
        d = c.duration
        args += ["-ss", f"{c.src_in:.3f}", "-t", f"{d:.3f}", "-i", os.path.abspath(m.path)]
        vi = n_in
        n_in += 1
        fit = fit_filter(tl, c, m, W, H)
        filters.append(f"[{vi}:v]setpts=PTS-STARTPTS,{fit},setsar=1,fps={tl.fps:g},format=yuv420p,settb=AVTB[v{k}]")
        if m.has_audio:
            ai = f"{vi}:a"
        else:
            args += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            ai = f"{n_in}:a"
            n_in += 1
        fade = min(0.01, d / 4)
        filters.append(
            f"[{ai}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
            f"{_audio_fx(tl, c.asset)}volume={'0' if c.volume_db <= -90 else f'{c.volume_db:g}dB'},afade=t=in:d={fade:.3f},afade=t=out:st={max(d - fade, 0):.3f}:d={fade:.3f}[a{k}]"
        )
    filters += _join(tl)

    vlabel = "vc"
    # ---- pista V2 (B-roll): overlay la timpul lui, sub subtitrări; sunetul rămâne cel de pe V1
    for k, b in enumerate(sorted(tl.broll, key=lambda b: b.start)):
        if b.start >= off + main_dur - 0.04:
            continue
        m = assets[b.asset]
        dur = min(b.duration, off + main_dur - b.start)
        args += ["-ss", f"{b.src_in:.3f}", "-t", f"{dur:.3f}", "-i", os.path.abspath(m.path)]
        bi = n_in
        n_in += 1
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
        filters.append(f"[{bi}:v]{_lut(tl, b.asset)}{fit},setsar=1,fps={tl.fps:g},format=yuv420p,"
                       f"setpts=PTS-STARTPTS+{b.start:.3f}/TB[b{k}]")
        filters.append(f"[{vlabel}][b{k}]overlay=x={x}:y={y}:eof_action=pass:"
                       f"enable='between(t,{b.start:.3f},{b.start + dur - 0.001:.3f})'[o{k}]")
        vlabel = f"o{k}"

    # ---- logo (brand): peste V1 + V2, sub subtitrări/titluri; doar pe montaj, nu peste intro/outro
    logo = tl.brand.logo
    if logo:
        if not os.path.exists(logo.path):
            raise FileNotFoundError("logo-ul brandului lipsește de pe disc; reîncarcă-l cu brand_logo")
        args += ["-i", os.path.abspath(logo.path)]
        li = n_in
        n_in += 1
        margin = _even(min(W, H) * logo.margin)
        x = margin if logo.position in ("tl", "bl") else f"W-w-{margin}"
        y = margin if logo.position in ("tl", "tr") else f"H-h-{margin}"
        filters.append(f"[{li}:v]scale={_even(W * logo.scale)}:-2,format=rgba,"
                       f"colorchannelmixer=aa={min(max(logo.opacity, 0), 1):.3f}[logo]")
        filters.append(f"[{vlabel}][logo]overlay=x={x}:y={y}:format=auto:"
                       f"enable='between(t,{off:.3f},{off + main_dur:.3f})'[vl]")
        vlabel = "vl"

    if tl.captions or tl.texts:
        with open(os.path.join(workdir, "captions.ass"), "w", encoding="utf-8") as fh:
            fh.write(to_ass(tl))
        filters.append(f"[{vlabel}]ass=filename=captions.ass:fontsdir={fonts_dir(tl, workdir)}[vs]")
        vlabel = "vs"

    alabel = "ac"
    if tl.music:  # muzica acoperă doar montajul; intro/outro au sunetul lor
        mm = assets[tl.music.asset]
        args += ["-stream_loop", "-1", "-ss", f"{tl.music.src_in:.3f}", "-i", os.path.abspath(mm.path)]
        mi = n_in
        n_in += 1
        delay = f",adelay={int(off * 1000)}:all=1" if off else ""
        filters.append(
            f"[{mi}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{main_dur:.3f},volume={tl.music.volume_db:g}dB,"
            f"afade=t=out:st={max(main_dur - 1.5, 0):.3f}:d=1.5{delay}[mus]"
        )
        if tl.music.duck:
            filters.append("[ac]asplit=2[voice][sc]")
            filters.append("[mus][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck]")
            filters.append("[voice][duck]amix=inputs=2:duration=first:normalize=0[am]")
        else:
            filters.append("[ac][mus]amix=inputs=2:duration=first:normalize=0[am]")
        alabel = "am"
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
    run(args, cwd=workdir)
    return os.path.abspath(out_path)
