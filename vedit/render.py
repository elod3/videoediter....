"""Compilează Timeline -> o singură comandă ffmpeg (filter_complex). Determinist, fără LLM."""
from __future__ import annotations

import os
import tempfile

from .captions import FONTS_DIR, to_ass
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


def build_command(tl: Timeline, assets: dict[str, MediaInfo], out_path: str, *,
                  preview: bool = False, workdir: str | None = None) -> tuple[list[str], str]:
    if not tl.clips:
        raise ValueError("timeline-ul e gol")
    workdir = workdir or tempfile.mkdtemp(prefix="vedit_")
    W, H = tl.width, tl.height
    if preview:  # 540p rapid
        f = 540 / min(W, H)
        W, H = _even(W * f), _even(H * f)

    args: list[str] = ["-y"]
    filters: list[str] = []
    n_in = 0
    concat_pads = ""
    for k, c in enumerate(tl.clips):
        m = assets[c.asset]
        d = c.duration
        args += ["-ss", f"{c.src_in:.3f}", "-t", f"{d:.3f}", "-i", os.path.abspath(m.path)]
        vi = n_in
        n_in += 1
        if tl.fill == "crop":
            cw, ch, x, y = crop_box(m.width, m.height, tl.width, tl.height, c)
            fit = f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}"
        else:
            fit = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
        filters.append(f"[{vi}:v]{fit},setsar=1,fps={tl.fps:g},format=yuv420p,setpts=PTS-STARTPTS[v{k}]")
        if m.has_audio:
            ai = f"{vi}:a"
        else:
            args += ["-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
            ai = f"{n_in}:a"
            n_in += 1
        fade = min(0.01, d / 4)
        filters.append(
            f"[{ai}]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS,"
            f"volume={c.volume_db:g}dB,afade=t=in:d={fade:.3f},afade=t=out:st={max(d - fade, 0):.3f}:d={fade:.3f}[a{k}]"
        )
        concat_pads += f"[v{k}][a{k}]"
    filters.append(f"{concat_pads}concat=n={len(tl.clips)}:v=1:a=1[vc][ac]")

    vlabel = "vc"
    if tl.captions or tl.texts:
        with open(os.path.join(workdir, "captions.ass"), "w", encoding="utf-8") as fh:
            fh.write(to_ass(tl))
        fonts = str(FONTS_DIR).replace("\\", "/").replace("'", r"\'")
        filters.append(f"[vc]ass=filename=captions.ass:fontsdir='{fonts}'[vs]")
        vlabel = "vs"

    alabel = "ac"
    if tl.music:
        mm = assets[tl.music.asset]
        args += ["-stream_loop", "-1", "-i", os.path.abspath(mm.path)]
        mi = n_in
        n_in += 1
        filters.append(
            f"[{mi}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{tl.duration:.3f},volume={tl.music.volume_db:g}dB,"
            f"afade=t=out:st={max(tl.duration - 1.5, 0):.3f}:d=1.5[mus]"
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
