"""Momente virale, hook teaser, zoom pe înregistrări de ecran, audiogram — randate real."""
import numpy as np
import pytest
from test_editing_pro import frame

from vedit import mcp_server as mcp
from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.sfx import write_wav
from vedit.transcribe import Transcript, Word


def test_highlights_find_picks_hook_and_energy(vhome, tmp_path):
    sr, dur = 16000, 60.0
    rng = np.random.default_rng(1)
    y = (rng.standard_normal(int(sr * dur)) * 0.03).astype(np.float32)
    y[int(30 * sr):int(42 * sr)] *= 6                       # momentul cu energie
    write_wav(tmp_path / "pod.wav", np.stack([y, y], 1), sr)
    p = Project("hl")
    p.add_asset(str(tmp_path / "pod.wav"), "a0")
    words, t, i = [], 0.2, 0
    for s in range(12):
        text = ("De ce nimeni nu vă spune secretul ăsta despre bani ?".split() if s == 6 else
                "și apoi am mers mai departe cu discuția noastră de azi .".split())
        for w in text:
            if w in ".?":
                words[-1] = Word(i=words[-1].i, start=words[-1].start, end=words[-1].end, text=words[-1].text + w)
                continue
            words.append(Word(i=i, start=round(t, 2), end=round(t + 0.35, 2), text=w))
            t, i = t + 0.5, i + 1
    p.set_transcript("a0", Transcript(words=words))
    top = p.highlights("a0", n=3, min_len=8, max_len=15)
    assert top and top[0]["hook"].startswith("De ce") and "hook în prima frază" in top[0]["why"]
    assert all(a["end"] <= b["start"] or a["start"] >= b["end"] for a in top for b in top if a is not b)
    out = mcp.highlights_find("hl", "a0", n=2, min_len=8, max_len=15)
    assert "#1 scor" in out and "DATE din" in out and "w" in out
    assert "n între" in mcp.highlights_find("hl", "a0", n=0)


def test_hook_teaser_moves_overlays(vhome, talking_video):
    from vedit.transcribe import Transcript, Word

    p = Project("tz")
    p.add_asset(talking_video, "a0")
    p.set_transcript("a0", Transcript(words=[Word(i=0, start=0.2, end=1.5, text="început"),
                                             Word(i=1, start=6.6, end=7.8, text="finalul")]))
    p.add_clip("a0", 0, 8)
    p.captions("a0", "bold_center")
    p.add_text(1.0, 2.0, "TITLU")
    before = p.tl.duration
    out = p.hook_teaser(6.5, 8.0, text="Stai să vezi")
    tl = p.tl
    shift = tl.starts()[1]
    assert "teaser" in out and tl.clips[0].src_in == pytest.approx(6.5) and tl.clips[1].transition.type == "fadewhite"
    assert tl.duration == pytest.approx(before + 1.5 - 0.25, abs=0.02) and shift == pytest.approx(1.25, abs=0.02)
    assert tl.texts[0].text == "Stai să vezi" and tl.texts[0].end == pytest.approx(shift)
    assert tl.texts[1].text == "TITLU" and tl.texts[1].start == pytest.approx(1.0 + shift, abs=0.01)
    assert [c.text for c in tl.captions].count("finalul") == 2                 # în teaser și la locul lui
    assert [x.kind for x in tl.sfx] == ["whoosh"]
    r = p.render(preview=True)
    assert probe(r["path"]).duration == pytest.approx(tl.duration, abs=0.1)
    assert "între 1 și 6" in mcp.hook_teaser("tz", 0, 10)


@pytest.fixture(scope="module")
def screen_rec(tmp_path_factory):
    """„Înregistrare de ecran”: pagină albă cu text gri; între 2 și 6 s cursorul (pătrat negru) se mișcă
    în colțul stânga-sus; la 8 s se schimbă toată pagina (scroll)."""
    d = tmp_path_factory.mktemp("scr")
    out = d / "screen.mp4"
    run(["-y", "-f", "lavfi", "-i", "color=c=white:s=1280x720:r=25:d=10",
         "-f", "lavfi", "-i", "color=c=black:s=24x24:r=25:d=10",
         "-filter_complex", "[0:v]drawgrid=w=160:h=90:t=1:c=gray@0.4[bg];"
                            "[bg][1:v]overlay=x='200+40*(t-2)':y=150:enable='between(t,2,6)',"
                            "drawbox=x=0:y=0:w=1280:h=720:c=0x3050a0:t=fill:enable='gte(t,8)'[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out)])
    return str(out)


def test_screen_zoom_follows_activity(vhome, screen_rec):
    p = Project("sz")
    p.add_asset(screen_rec, "a0")
    p.add_clip("a0", 0, 10)
    out = mcp.screen_zoom("sz", max_zoom=2.0)
    assert "zoom automat: 1 zone" in out, out
    tl = Project("sz").tl
    zoomed = [c for c in tl.clips if c.anim and c.anim.zoom_to > 1.2 and c.anim.zoom_from == c.anim.zoom_to]
    assert zoomed and 0.1 < zoomed[0].anim.cx_to < 0.35 and 0.1 < zoomed[0].anim.cy_to < 0.4
    assert zoomed[0].src_in < 2.6 and zoomed[0].src_out > 5.5
    assert tl.duration == pytest.approx(10, abs=0.01) and len({c.id for c in tl.clips}) == len(tl.clips)
    r = Project("sz").render(preview=True)
    img = frame(r["path"], 4.0, width=640)
    dark = (img.mean(axis=2) < 60).sum()
    assert dark > 4 * (12 * 12 * 0.8)                   # cursorul e mult mai mare decât fără zoom (~12x12 px)
    assert img[..., 2].mean() > 180                      # încă pe pagina albă, nu pe cea albastră
    late = frame(r["path"], 9.0, width=640)
    assert late[..., 2].mean() > late[..., 0].mean() + 40    # după scroll: cadrul întreg (albastru)


def test_audiogram_render(vhome, music_file, tmp_path):
    p = Project("ag")
    p.add_asset(music_file, "m")
    out = mcp.audiogram("ag", "m", color="#203040", style="wave", fmt="1:1")
    assert "audiogram 1:1" in out and "VIZ undă wave" in Project("ag").tl.view()
    r = Project("ag").render(preview=True)
    info = probe(r["path"])
    assert (info.width, info.height) == (540, 540) and info.duration == pytest.approx(3.0, abs=0.15)
    img = frame(r["path"], 1.5, width=540)
    top, band = img[40:200], img[330:470]
    assert abs(top[..., 0].mean() - 0x20) < 12 and abs(top[..., 2].mean() - 0x40) < 12   # fundalul
    assert (band.mean(axis=2) > 200).sum() > 500                                          # unda albă
    assert "style" in mcp.audiogram("ag", "m", style="spirala")


def test_scripted_runner_audiogram(vhome, music_file):
    import threading

    from vedit.api.runners import ScriptedRunner

    p = Project("sa")
    p.add_asset(music_file, "a0")
    p.set_transcript("a0", Transcript(words=[Word(i=0, start=0.2, end=1.0, text="salut"),
                                             Word(i=1, start=1.2, end=2.4, text="lume")]))
    events = []
    msg, _ = ScriptedRunner().run("sa", "fă un audiogram pentru TikTok", lambda t, d: events.append((t, d)),
                                  threading.Event())
    tools = [d["name"] for t, d in events if t == "tool"]
    assert tools[:3] == ["audiogram", "captions_add", "render"] and "audiogram 9:16" in msg, (tools, msg)
    q = Project("sa")
    assert q.tl.visualizer and q.tl.width == 1080 and q.tl.height == 1920 and q.tl.captions


def test_audiogram_fragment_reuses_transcript(vhome, tmp_path):
    sr = 48000
    t = np.arange(sr * 10) / sr
    y = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    write_wav(tmp_path / "ep.wav", np.stack([y, y], 1), sr)
    p = Project("agf")
    p.add_asset(str(tmp_path / "ep.wav"), "ep")
    p.set_transcript("ep", Transcript(words=[Word(i=0, start=1.0, end=1.5, text="înainte"),
                                             Word(i=1, start=4.2, end=4.8, text="momentul"),
                                             Word(i=2, start=6.0, end=6.5, text="bun")]))
    out = p.audiogram("ep", start=4.0, end=7.0, fmt="9:16", position="top")
    aid = p.tl.narration.asset
    assert aid == "epf0" and "sunetul epf0" in out and p.s.assets[aid].duration == pytest.approx(3.0, abs=0.05)
    assert [(w.text, w.start) for w in p.transcript(aid).words] == [("momentul", 0.2), ("bun", 2.0)]
    assert p.tl.visualizer.position == "top" and p.tl.duration == pytest.approx(3.0, abs=0.05)
    p.audiogram("ep", start=4.0, end=7.0)                                        # același fragment: refolosit
    assert sum(1 for k in p.s.assets if k.startswith("epf")) == 1
    assert "fragment invalid" in mcp.audiogram("agf", "ep", start=5, end=6)
