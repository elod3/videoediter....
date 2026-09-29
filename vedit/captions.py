"""Subtitrări: transcript -> Caption-uri pe timeline -> fișier .ass (randat de libass)."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from .timeline import Caption, Timeline
from .transcribe import Transcript

# Stiluri predefinite. Agentul alege un nume, nu scrie ASS de mână.
STYLES = {
    # short-form (TikTok/Reels): mare, bold, 1-3 cuvinte, sub față (~70% din înălțime), nu peste gură
    "bold_center": dict(font="Archivo Black", size=0.045, bold=0, outline=0.006, shadow=0, align=2, margin_v=0.30,
                        upper=True, max_words=3, primary="&H00FFFFFF", secondary="&H00FFFFFF"),
    # karaoke: cuvântul curent devine galben
    "karaoke": dict(font="Archivo Black", size=0.042, bold=0, outline=0.006, shadow=0, align=2, margin_v=0.28,
                    upper=True, max_words=4, primary="&H0000E5FF", secondary="&H00FFFFFF"),
    # subtitrare clasică jos (YouTube long-form, podcast)
    "classic_bottom": dict(font="Archivo", size=0.04, bold=0, outline=0.003, shadow=0.002, align=2, margin_v=0.06,
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
    placements = list(zip(tl.clips, tl.starts()))
    if tl.narration and tl.narration.asset == asset:  # voice-over: un singur „clip” continuu, de la start
        from .timeline import Clip

        end = max((w.end for w in tr.words), default=0.0) + 0.05
        placements = [(Clip(id="_nar", asset=asset, src_in=0.0, src_out=end), tl.narration.start)]
    for clip, start in placements:
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
                a = max(start, clip.tl_at(start, chunk[0].start))
                b = min(start + clip.body, clip.tl_at(start, chunk[-1].end))
                if b - a < 0.05:
                    continue
                caps.append(Caption(start=round(a, 3), end=round(b, 3),
                                    text=" ".join(w.text for w in chunk),
                                    word_durs=[round((w.end - w.start) / clip.speed, 3) for w in chunk],
                                    word_ids=[f"{asset}:w{w.i}" for w in chunk],
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


FONTS_DIR = Path(__file__).parent / "fonts"
HEX = re.compile(r"^#?([0-9A-Fa-f]{6})$")


def norm_hex(value: str) -> str:
    """'#ff00aa' / 'FF00AA' -> '#FF00AA'; altceva => ValueError clar."""
    m = HEX.match((value or "").strip())
    if not m:
        raise ValueError(f"culoare invalidă {value!r}: folosește hex #RRGGBB (ex. #FFD400)")
    return "#" + m[1].upper()


def ass_color(value: str, inline: bool = False) -> str:
    """#RRGGBB -> ASS (ordinea e inversă: BGR). inline=True: &HBBGGRR& pentru tag-uri, altfel &H00BBGGRR pt stil."""
    h = norm_hex(value)[1:]
    bgr = h[4:6] + h[2:4] + h[0:2]
    return f"&H{bgr}&" if inline else f"&H00{bgr}"


def fonts_dir(tl: Timeline, workdir: str) -> str:
    """Folder de fonturi per randare: fonturile incluse + fontul brandului (symlink, sau copie dacă nu se poate).
    libass primește un singur `fontsdir`, de aceea le adunăm într-unul. Returnează calea relativă la workdir."""
    d = Path(workdir) / "fonts"
    d.mkdir(parents=True, exist_ok=True)
    files = [f for f in FONTS_DIR.iterdir() if f.suffix.lower() in (".ttf", ".otf")]
    if tl.brand.font_file:
        if not os.path.exists(tl.brand.font_file):
            raise FileNotFoundError("fontul brandului lipsește de pe disc; reîncarcă-l cu brand_captions")
        files.append(Path(tl.brand.font_file))
    for f in files:
        dst = d / f.name
        if dst.exists() or dst.is_symlink():
            continue
        try:
            os.symlink(f.resolve(), dst)
        except OSError:
            shutil.copy2(f, dst)
    return "fonts"


def _style_colors(tl: Timeline, s: dict) -> tuple[str, str, str]:
    """(Primary, Secondary, Outline) pentru stilul Cap, cu culorile brandului peste cele ale stilului.
    La karaoke libass colorează cuvântul curent cu Primary și restul cu Secondary."""
    b = tl.brand
    primary, secondary = s["primary"], s["secondary"]
    if tl.caption_style == "karaoke":
        primary = ass_color(b.highlight) if b.highlight else primary
        secondary = ass_color(b.primary) if b.primary else secondary
    elif b.primary:
        primary = secondary = ass_color(b.primary)
    outline = ass_color(b.outline) if b.outline else "&H00000000"
    return primary, secondary, outline


def _emph(word: str, col: str, scale: float, at_ms: int | None, restore: str) -> str:
    """Cuvânt-cheie: altă culoare, mai mare; la at_ms (momentul rostirii) face un „pop”. `restore` = tag-urile
    care readuc stilul rândului după el (culoarea vorbitorului rămâne)."""
    big = int(scale * 100)
    if at_ms is None:
        return f"{{\\1c{col}\\fscx{big}\\fscy{big}}}{word}{{{restore}}}"
    pop = int(big * 1.12)
    return (f"{{\\1c{col}\\t({at_ms},{at_ms + 90},\\fscx{pop}\\fscy{pop})"
            f"\\t({at_ms + 90},{at_ms + 200},\\fscx{big}\\fscy{big})}}{word}{{{restore}}}")


def _inline(style_color: str) -> str:
    """&H00BBGGRR (stil) -> &HBBGGRR& (tag)."""
    return f"&H{style_color[-6:]}&"


def to_ass(tl: Timeline, font: str | None = None) -> str:
    W, H = tl.width, tl.height
    s = STYLES.get(tl.caption_style, STYLES["bold_center"])
    font = font or tl.caption_font or s["font"]
    unit = min(W, H)
    size = int(s["size"] * H)
    title_size = int(size * 1.1)
    primary, secondary, outline = _style_colors(tl, s)
    title_col = ass_color(tl.brand.primary) if tl.brand.primary else "&H00FFFFFF"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{font},{size},{primary},{secondary},{outline},&H80000000,"
        f"{-1 if s['bold'] else 0},0,0,0,100,100,0,0,1,{max(1, int(s['outline'] * unit))},"
        f"{int(s['shadow'] * unit)},{s['align']},{int(W * 0.06)},{int(W * 0.06)},{int(s['margin_v'] * H)},1",
        f"Style: Title,{font},{title_size},{title_col},{title_col},{outline},&H80000000,-1,0,0,0,100,100,0,0,1,"
        f"{max(1, int(0.006 * unit))},0,8,{int(W * 0.06)},{int(W * 0.06)},{int(0.08 * H)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    emph = set(tl.emphasis)
    ecol = ass_color(tl.emphasis_color or tl.brand.highlight or "#FFD400", inline=True)
    esc = max(1.0, min(tl.emphasis_scale, 1.8))
    for c in tl.captions:
        text = c.text.upper() if s["upper"] else c.text
        words = text.split(" ")
        aligned = bool(c.word_durs) and len(words) == len(c.word_durs)
        marks = [bool(c.word_ids and i < len(c.word_ids) and c.word_ids[i] in emph) for i in range(len(words))]
        base = _inline(primary)
        if tl.caption_speaker_colors and c.speaker and tl.caption_style != "karaoke":
            spk = sorted({x.speaker for x in tl.captions if x.speaker})
            base = SPEAKER_COLORS[spk.index(c.speaker) % len(SPEAKER_COLORS)]
        restore = f"\\1c{base}\\fscx100\\fscy100"
        if tl.caption_style == "karaoke" and aligned:
            text = " ".join(f"{{\\k{int(d * 100)}}}{_emph(_esc(w), ecol, esc, None, restore) if m else _esc(w)}"
                            for w, d, m in zip(words, c.word_durs, marks))
        elif any(marks):
            at = [sum(c.word_durs[:i]) if aligned else 0.0 for i in range(len(words))]
            text = " ".join(_emph(_esc(w), ecol, esc, int(t * 1000), restore) if m else _esc(w)
                            for w, m, t in zip(words, marks, at))
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


# ---------------------------------------------------------------- fișiere de subtitrare (SRT / VTT)
def _clean(text: str) -> str:
    """Text simplu, pe un rând: fără caractere de control, tag-uri sau override-uri ASS."""
    text = "".join(ch if ch.isprintable() else " " for ch in text or "")
    text = re.sub(r"<[^>]*>|\{[^}]*\}", "", text).replace("-->", "->")
    return re.sub(r"\s+", " ", text).strip()


def _stamp(t: float, sep: str) -> str:
    ms = int(round(max(t, 0) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{sep}{ms % 1000:03d}"


def to_subs(tl: Timeline, fmt: str = "srt", offset: float = 0.0) -> str:
    """Subtitrările timeline-ului ca SRT sau WebVTT. offset = durata intro-ului (timpul din fișierul randat)."""
    if fmt not in ("srt", "vtt"):
        raise ValueError("format: srt sau vtt")
    cues = []
    for c in sorted(tl.captions, key=lambda c: c.start):
        text = _clean(c.text)
        if not text or c.end - c.start < 0.02:
            continue
        if fmt == "vtt":
            text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cues.append((c.start + offset, c.end + offset, text))
    if fmt == "srt":
        return "".join(f"{i}\n{_stamp(a, ',')} --> {_stamp(b, ',')}\n{t}\n\n" for i, (a, b, t) in enumerate(cues, 1))
    return "WEBVTT\n\n" + "".join(f"{_stamp(a, '.')} --> {_stamp(b, '.')}\n{t}\n\n" for a, b, t in cues)


def title_ass(tl: Timeline, text: str, W: int, H: int) -> str:
    """Un singur titlu mare, puțin deasupra mijlocului (thumbnail). Font și culori din brand."""
    b = tl.brand
    font = (tl.caption_font if b.font_file else None) or "Archivo Black"
    col = ass_color(b.primary) if b.primary else "&H00FFFFFF"
    out = ass_color(b.outline) if b.outline else "&H00000000"
    size = int(min(W, H) * 0.11)
    return "\n".join([
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: T,{font},{size},{col},{col},{out},&H80000000,0,0,0,0,100,100,0,0,1,{max(2, int(size * 0.09))},"
        f"{max(1, int(size * 0.05))},5,{int(W * 0.07)},{int(W * 0.07)},0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
        f"Dialogue: 0,0:00:00.00,0:01:00.00,T,,0,0,0,,{{\\pos({W // 2},{int(H * 0.42)})}}{_esc(_clean(text).upper())}",
    ]) + "\n"
