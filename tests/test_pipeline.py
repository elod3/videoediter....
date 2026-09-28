import json
import os

from vedit import mcp_server as m
from vedit.project import Project
from vedit.probe import probe
from vedit.transcribe import Transcript, Word


def fake_transcript():
    ws = [(0.1, 0.9, "Salut"), (1.0, 1.9, "tuturor."), (3.6, 4.4, "Azi"), (4.5, 5.4, "editam."),
          (6.6, 7.2, "Hai"), (7.3, 7.9, "sa-ncepem!")]
    return Transcript(language="ro", words=[Word(i=i, start=a, end=b, text=t) for i, (a, b, t) in enumerate(ws)])


def test_full_short_form_pipeline(vhome, talking_video, music_file):
    p = Project("demo")
    assert p.add_asset(talking_video).startswith("a0:")
    p.add_asset(music_file, "music")
    info = p.analyze("a0")
    assert 2.3 < info["silence_total"] < 2.8

    msg = p.auto_cut_silence("a0", min_silence=0.5, padding=0.1)
    assert len(p.tl.clips) == 3 and 5.5 < p.tl.duration < 6.5, msg

    p.set_format("9:16")
    p.reframe("all", cx=0.5, zoom=1.2)
    p.set_transcript("a0", fake_transcript())
    p.remove_words("a0", "w4")  # scoate "Hai"
    assert p.tl.duration < 6.0
    assert "captions" in p.captions("a0", "karaoke")
    p.add_text(0, 1.5, "TITLU TEST")
    p.set_music("music", -20, duck=True)

    out = p.render(preview=True)
    got = probe(out["path"])
    assert (got.width, got.height) == (540, 960)
    assert abs(got.duration - p.tl.duration) < 0.3

    final = p.render(preview=False)
    qa = p.qa(final["path"])
    assert qa["resolution"] == "1080x1920"
    assert not any("durata" in i or "rezoluție" in i for i in qa["issues"]), qa


def test_undo_and_errors_via_mcp_tools(vhome, talking_video):
    assert m.asset_add("p2", talking_video).startswith("a0")
    m.cut_silences("p2", "a0")
    n = len(Project("p2").tl.clips)
    m.clip_remove("p2", "c0")
    assert len(Project("p2").tl.clips) == n - 1
    m.undo("p2")
    assert len(Project("p2").tl.clips) == n
    assert m.clip_remove("p2", "nope").startswith("EROARE")
    assert len(Project("p2").tl.clips) == n  # operația eșuată nu a stricat starea
    sheet = json.loads(m.frames_look("p2", "a0", cols=3, rows=2))
    assert os.path.getsize(sheet["image"]) > 1000 and len(sheet["cells_left_to_right_top_to_bottom"]) == 6


def test_keep_words_builds_highlight(vhome, talking_video):
    p = Project("p3")
    p.add_asset(talking_video)
    p.set_transcript("a0", fake_transcript())
    view = p.keep_words("a0", "w4-w5,w0-w1")  # hook-ul primul
    assert view.splitlines()[1].startswith("c0 @0.00") and p.tl.clips[0].src_in > 6


def test_named_render_look_and_clip_volume(vhome, talking_video):
    p = Project("p4")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 2)
    assert "vol=+4dB" in p.clip_volume("all", 4)
    out = p.render(preview=True, name="short1")
    assert out["path"].endswith("short1.mp4")
    sheet = p.look("render:short1", cols=2, rows=1)
    assert os.path.exists(sheet["image"])
