import numpy as np
import pytest

from drums import drum_track
from vedit.analyze import scenes
from vedit.beats import detect
from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("bb")
    wav = d / "drums.wav"
    truth = drum_track(str(wav), 120, dur=12)
    music = str(d / "music.m4a")
    run(["-y", "-i", str(wav), "-c:a", "aac", music])
    srcs = []
    for i, src in enumerate(["testsrc2", "mandelbrot", "smptebars"]):
        p = str(d / f"src{i}.mp4")
        run(["-y", "-f", "lavfi", "-t", "6", "-i", f"{src}=size=640x360:rate=25", "-f", "lavfi", "-i", "sine=f=500:d=6",
             "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", p])
        srcs.append(p)
    return {"music": music, "truth": truth, "srcs": srcs}


@pytest.mark.parametrize("bpm", [70, 90, 120, 140, 172])
def test_beats_exact_on_drums(tmp_path, bpm):
    truth = drum_track(str(tmp_path / "d.wav"), bpm)
    b = detect(str(tmp_path / "d.wav"))
    assert abs(b.bpm - bpm) < 1.0, b.bpm                       # fără erori de octavă
    err = [np.min(np.abs(truth - x)) for x in b.beats]
    assert len(b.beats) >= len(truth) - 1 and np.max(err) < 0.03  # fiecare beat pe o lovitură reală


def test_beat_montage_cuts_land_on_beats(vhome, media):
    p = Project("montaj")
    for s in media["srcs"]:
        p.add_asset(s)
    p.add_asset(media["music"], "music")
    msg = p.beat_montage("music", beats_per_shot=2, max_duration=8)
    assert "120" in msg.split(" BPM")[0][-6:], msg
    assert len({c.asset for c in p.tl.clips}) == 3                 # sursele alternează
    assert all(c.volume_db <= -90 for c in p.tl.clips)              # sunetul surselor e oprit
    beats = np.array(p.beats("music").beats) - p.tl.music.src_in
    out = p.render(preview=True)["path"]
    cuts = np.array(scenes(out, 0.3))
    assert len(cuts) >= len(p.tl.clips) - 2
    # fiecare tăietură din video-ul randat cade pe un beat (±1 cadru la 25 fps + toleranță)
    assert max(np.min(np.abs(beats - c)) for c in cuts) < 0.06, (cuts, beats[:10])


def test_broll_overlay_window_and_pip(vhome, media):
    p = Project("broll")
    p.add_asset(media["srcs"][0])
    p.add_asset(media["srcs"][2], "b")
    p.set_role("b", "broll")
    assert "[B-ROLL" in p.list_assets()
    p.add_clip("a0", 0, 6)
    base = p.render(preview=True, name="base")["path"]
    p.broll_add("b", at=2.0, duration=2.0)
    assert "V2 b0 @2.00-4.00 b[0.00-2.00]" in p.tl.view()
    with_b = p.render(preview=True, name="withb")["path"]
    info = probe(with_b)
    assert abs(info.duration - 6) < 0.1

    def diff(t):
        a = grab_frame(base, t, info.width, info.height).astype(int)
        b = grab_frame(with_b, t, info.width, info.height).astype(int)
        return np.abs(a - b).mean()

    assert diff(1.0) < 3 and diff(5.0) < 3        # în afara ferestrei: neschimbat
    assert diff(3.0) > 20                          # în fereastră: B-roll pe tot ecranul
    p.broll_remove("all")
    p.broll_add("b", at=1.0, duration=3.0, mode="pip", pip_pos="br")
    pip = p.render(preview=True, name="pip")["path"]
    fr = grab_frame(pip, 2.0, info.width, info.height, width=160).astype(int)
    ref = grab_frame(base, 2.0, info.width, info.height, width=160).astype(int)
    h, w = fr.shape[:2]
    assert np.abs(fr[: h // 3, : w // 3] - ref[: h // 3, : w // 3]).mean() < 3       # colțul stânga-sus intact
    assert np.abs(fr[-h // 4:, -w // 4:] - ref[-h // 4:, -w // 4:]).mean() > 15     # PiP în dreapta-jos
    with pytest.raises(ValueError):
        p.broll_add("b", at=99, duration=1)


def test_broll_snaps_to_music_beats(vhome, media):
    p = Project("snap")
    p.add_asset(media["srcs"][0])
    p.add_asset(media["srcs"][1], "b")
    p.add_asset(media["music"], "music")
    p.add_clip("a0", 0, 6)
    p.set_music("music", -18, duck=True)
    p.broll_add("b", at=1.13, duration=1.4, snap=True)
    b = p.tl.broll[0]
    beats = p._timeline_beats()
    assert min(abs(x - b.start) for x in beats) < 1e-6 and min(abs(x - b.end) for x in beats) < 1e-3
