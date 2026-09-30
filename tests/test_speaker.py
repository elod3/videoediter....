
from vedit.speaker import assign

FPS = 8.0


def times(n):
    return [i / FPS for i in range(n)]


def test_assign_switches_with_hysteresis():
    n = 48  # 6s
    a0 = [0.02 if i < 24 else 0.0 for i in range(n)]
    a1 = [0.0 if i < 24 else 0.02 for i in range(n)]
    segs = assign(times(n), {0: a0, 1: a1}, [True] * n, 0, 6, FPS)
    assert [k for *_, k in segs] == [0, 1]
    assert 2.8 < segs[0][1] < 3.4


def test_short_interjection_ignored():
    n = 48
    a0 = [0.02] * n
    a1 = [0.0] * n
    for i in range(20, 24):  # 0.5s "da, da" de la celălalt
        a0[i], a1[i] = 0.0, 0.03
    segs = assign(times(n), {0: a0, 1: a1}, [True] * n, 0, 6, FPS, min_hold=1.0)
    assert segs == [(0, 6, 0)]


def test_mouth_motion_without_speech_ignored():
    n = 48
    a0 = [0.02 if i < 24 else 0.0 for i in range(n)]
    a1 = [0.0 if i < 24 else 0.05 for i in range(n)]  # mestecă / zâmbește, dar nu se aude nimic
    speech = [i < 24 for i in range(n)]
    assert [k for *_, k in assign(times(n), {0: a0, 1: a1}, speech, 0, 6, FPS)] == [0]


def test_single_track():
    assert assign(times(4), {3: [0.0] * 4}, [True] * 4, 0, 0.5, FPS) == [(0, 0.5, 3)]


# ---------- integrare (fixture podcast_video în conftest) ----------
def test_speakers_detect_and_reframe(vhome, podcast_video):
    from vedit import mcp_server as m
    from vedit.project import Project

    p = Project("pod")
    p.add_asset(podcast_video)
    d = p.speakers("a0")
    got = [(round(s["t0"], 1), s["track"]) for s in d["segments"]]
    assert [k for _, k in got] == [0, 1, 0], got
    assert abs(d["segments"][1]["t0"] - 3.0) < 0.45 and abs(d["segments"][2]["t0"] - 6.5) < 0.45
    assert d["tracks"][0]["cx"] < 0.5 < d["tracks"][1]["cx"]
    assert "S1 cx=0.8" in m.speakers_detect("pod", "a0")

    p.add_clip("a0", 0, 9)
    p.set_format("9:16")
    rep = p.auto_reframe()
    assert "vorbitor S0" in rep and "vorbitor S1" in rep and "WIDE" not in rep, rep
    cx = [round(c.crop.cx, 1) for c in p.tl.clips]
    assert cx == [0.2, 0.8, 0.2], rep
    assert abs(p.tl.duration - 9) < 0.05
    # fără speaker => rămâne WIDE, încadrat pe o singură față
    p.undo()
    assert "WIDE" in p.auto_reframe(speaker=False)
