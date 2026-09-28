"""Subtitrări: transcript -> Caption-uri pe timeline -> fișier .ass (randat de libass)."""
from __future__ import annotations

from .timeline import Caption, Timeline
from .transcribe import Transcript

# Stiluri predefinite. Agentul alege un nume, nu scrie ASS de mână.
STYLES = {
    # short-form (TikTok/Reels): mare, bold, 1-3 cuvinte, sub față (~70% din înălțime), nu peste gură
    "bold_center": dict(size=0.045, bold=1, outline=0.006, shadow=0, align=2, margin_v=0.30,
                        upper=True, max_words=3, primary="&H00FFFFFF", secondary="&H00FFFFFF"),
    # karaoke: cuvântul curent devine galben
    "karaoke": dict(size=0.042, bold=1, outline=0.006, shadow=0, align=2, margin_v=0.28,
                    upper=True, max_words=4, primary="&H0000E5FF", secondary="&H00FFFFFF"),
    # subtitrare clasică jos (YouTube long-form, podcast)
    "classic_bottom": dict(size=0.04, bold=0, outline=0.003, shadow=0.002, align=2, margin_v=0.06,
                           upper=False, max_words=10, primary="&H00FFFFFF", secondary="&H00FFFFFF"),
}


# culori per vorbitor (ASS: &HBBGGRR&): alb, galben, cyan, verde deschis, roz
SPEAKER_COLORS = ["&HFFFFFF&", "&H00E5FF&", "&HFFE000&", "&H7CFF7C&", "&HC080FF&"]


def build_captions(tl: Timeline, asset: str, tr: Transcript, style: str | None = None,
                   speaker_colors: bool | None = None) -> int:
    """Mapează cuvintele din sursă pe timeline (respectând tăieturile) și le grupează."""
    style = style or tl.caption_style
    if style not in STYLES:
        raise ValueError(f"stil necunoscut {style}; disponibile: {', '.join(STYLES)}")
    tl.caption_style = style
    if speaker_colors is not None:
        tl.caption_speaker_colors = speaker_colors
    max_words = STYLES[style]["max_words"]
    caps: list[Caption] = []
    for clip, start in zip(tl.clips, tl.starts()):
        if clip.asset != asset:
            continue
        ws = [w for w in tr.words if w.start >= clip.src_in - 0.05 and w.end <= clip.src_out + 0.05]
        runs: list[list] = []  # o captură nu amestecă doi vorbitori
        for w in ws:
            if runs and runs[-1][-1].spk == w.spk:
                runs[-1].append(w)
            else:
                runs.append([w])
        for run in runs:
            for i in range(0, len(run), max_words):
                chunk = run[i:i + max_words]
                a = max(start, start + chunk[0].start - clip.src_in)
                b = min(start + clip.duration, start + chunk[-1].end - clip.src_in)
                if b - a < 0.05:
                    continue
                caps.append(Caption(start=round(a, 3), end=round(b, 3),
                                    text=" ".join(w.text for w in chunk),
                                    word_durs=[round(w.end - w.start, 3) for w in chunk],
                                    speaker=chunk[0].spk))
    # fără goluri mici între captions (evită flicker)
    for x, y in zip(caps, caps[1:]):
        if 0 < y.start - x.end < 0.3:
            x.end = y.start
    tl.captions = caps
    return len(caps)


def _ts(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def to_ass(tl: Timeline, font: str = "Arial") -> str:
    W, H = tl.width, tl.height
    s = STYLES.get(tl.caption_style, STYLES["bold_center"])
    unit = min(W, H)
    size = int(s["size"] * H)
    title_size = int(size * 1.1)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},{s['primary']},{s['secondary']},&H00000000,&H80000000,"
        f"{-1 if s['bold'] else 0},0,0,0,100,100,0,0,1,{max(1, int(s['outline'] * unit))},"
        f"{int(s['shadow'] * unit)},{s['align']},{int(W * 0.06)},{int(W * 0.06)},{int(s['margin_v'] * H)},1",
        f"Style: Title,{font},{title_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(1, int(0.006 * unit))},0,8,{int(W * 0.06)},{int(W * 0.06)},{int(0.08 * H)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for c in tl.captions:
        text = c.text.upper() if s["upper"] else c.text
        if tl.caption_style == "karaoke" and c.word_durs:
            words = text.split(" ")
            if len(words) == len(c.word_durs):
                text = " ".join(f"{{\\k{int(d * 100)}}}{_esc(w)}" for w, d in zip(words, c.word_durs))
            else:
                text = _esc(text)
        else:
            text = _esc(text)
        if tl.caption_speaker_colors and c.speaker:
            spk = sorted({x.speaker for x in tl.captions if x.speaker})
            col = SPEAKER_COLORS[spk.index(c.speaker) % len(SPEAKER_COLORS)]
            # karaoke: culoarea vorbitorului e cea „ne-cântată”; restul stilurilor: culoarea textului
            text = ("{\\2c" if tl.caption_style == "karaoke" else "{\\1c") + col + "}" + text
        lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},Cap,,0,0,0,,{text}")
    pos = {"top": 8, "center": 5, "bottom": 2}
    for t in tl.texts:
        lines.append(f"Dialogue: 1,{_ts(t.start)},{_ts(t.end)},Title,,0,0,0,,{{\\an{pos[t.position]}}}{_esc(t.text)}")
    return "\n".join(lines) + "\n"
