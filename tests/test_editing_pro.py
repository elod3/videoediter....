"""Viteză, freeze, efecte, efecte sonore, multicam, split-screen, green screen, stabilizare — randate real."""
import numpy as np
import pytest

from vedit import mcp_server as mcp
from vedit.beats import load_mono
from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame
from vedit.transcribe import Transcript, Word


def frame(path, t, width=320):
    info = probe(path)
    return grab_frame(path, t, info.width, info.height, width=width).astype(int)


def rms(y, sr, a, b):
    seg = y[int(a * sr):int(b * sr)]
    return float(np.sqrt(np.mean(seg ** 2))) if seg.size else 0.0


def dominant_hz(y, sr, a, b):
    seg = y[int(a * sr):int(b * sr)]
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
    return float(np.fft.rfftfreq(len(seg), 1 / sr)[spec.argmax()])


@pytest.fixture(scope="module")
def cams(tmp_path_factory):
    """Două „camere” ale aceluiași moment: sunet comun (rafale de zgomot), culori diferite.
    Camera B a pornit cu 1.5 s mai târziu (momentul t din A e la t-1.5 în B)."""
    from vedit.sfx import write_wav

    d = tmp_path_factory.mktemp("cams")
    rng = np.random.default_rng(7)
    sr, dur = 48000, 12.0
    env = np.zeros(int(sr * dur), np.float32)
    t = 0.2
    while t < dur - 0.5:
        n = rng.uniform(0.15, 0.6)
        env[int(t * sr):int((t + n) * sr)] = rng.uniform(0.3, 0.9)
        t += n + rng.uniform(0.1, 0.5)
    sig = (rng.standard_normal(env.size).astype(np.float32) * env * 0.3)
    write_wav(d / "a.wav", np.stack([sig, sig], 1))
    b = sig[int(1.5 * sr):] * 0.5 + rng.standard_normal(sig.size - int(1.5 * sr)).astype(np.float32) * 0.005
    write_wav(d / "b.wav", np.stack([b, b], 1))
    out = {}
    for name, color, wav, secs in (("A", "red", "a.wav", dur), ("B", "blue", "b.wav", dur - 1.5)):
        p = d / f"cam{name}.mp4"
        run(["-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=25:d={secs}", "-i", str(d / wav),
             "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)])
        out[name] = str(p)
    return out


def test_speed_and_freeze_render(vhome, talking_video):
    p = Project("spd")
    p.add_asset(talking_video, "a0")
    p.add_clip("a0", 0, 2)          # ton 220 Hz
    p.add_clip("a0", 3.5, 5.5)
    p.speed_set("c0", 2.0)
    p.freeze_frame("c1", 1.0)
    assert p.tl.duration == pytest.approx(1 + 2 + 1, abs=0.01)
    out = p.render(preview=True)["path"]
    assert probe(out).duration == pytest.approx(4.0, abs=0.1)
    y = load_mono(out, sr=16000)
    assert dominant_hz(y, 16000, 0.2, 0.9) == pytest.approx(220, abs=15)   # atempo: tonul rămâne
    assert rms(y, 16000, 3.2, 3.9) < 0.1 * rms(y, 16000, 1.5, 2.8)          # freeze-ul e fără sunet
    a, b = frame(out, 3.2), frame(out, 3.8)
    assert np.abs(a - b).mean() < 2                                         # cadru înghețat
    assert np.abs(frame(out, 1.2) - frame(out, 2.4)).mean() > 5            # înainte se mișcă


def test_speed_ramp_and_split_keep_duration(vhome, talking_video):
    p = Project("ramp")
    p.add_asset(talking_video, "a0")
    p.add_clip("a0", 0, 4)
    p.speed_ramp("c0", 1.0, 3.0, steps=4)
    speeds = [c.speed for c in p.tl.clips]
    assert len(speeds) == 4 and speeds == sorted(speeds) and speeds[0] < 1.3 and speeds[-1] > 2.6
    expected = sum(1.0 / s for s in speeds)
    assert p.tl.duration == pytest.approx(expected, abs=0.01)
    out = p.render(preview=True)["path"]
    assert probe(out).duration == pytest.approx(expected, abs=0.12)
    before = p.tl.duration
    p.tl.split_at(0.3)  # tăietura pe un clip accelerat păstrează durata
    assert p.tl.duration == pytest.approx(before, abs=0.01)


def test_clip_fx_bw_mirror_and_validation(vhome, talking_video):
    p = Project("fx")
    p.add_asset(talking_video, "a0")
    p.add_clip("a0", 0, 2)
    ref = frame(p.render(preview=True, name="ref")["path"], 1.0)
    p.clip_fx("c0", "bw,mirror")
    out = p.render(preview=True)["path"]
    fr = frame(out, 1.0)
    assert np.abs(fr[..., 0] - fr[..., 2]).mean() < 4          # fără culoare
    lum = (ref @ np.array([0.299, 0.587, 0.114])).astype(float)
    got = fr.mean(axis=2)
    flipped = np.corrcoef(got.ravel(), lum[:, ::-1].ravel())[0, 1]
    straight = np.corrcoef(got.ravel(), lum.ravel())[0, 1]
    assert flipped > 0.8 and flipped > straight + 0.2                          # oglindit
    with pytest.raises(ValueError):
        p.clip_fx("c0", "sepia-magic")
    p.clip_fx("c0", "glitch,shake,flash,grain,vintage,vignette,blur,sharpen,invert", mode="set")
    assert probe(p.render(preview=True)["path"]).duration == pytest.approx(2, abs=0.1)


def test_sfx_manual_and_auto(vhome, talking_video):
    p = Project("sfx")
    p.add_asset(talking_video, "a0")
    p.add_clip("a0", 2.0, 3.5)       # liniște în sursă
    p.add_clip("a0", 5.5, 6.5)
    assert "x0" in p.sfx_add("impact", 0.5, volume_db=0)
    with pytest.raises(ValueError):
        p.sfx_add("laser", 0.5)
    y = load_mono(p.render(preview=True)["path"], sr=16000)
    assert rms(y, 16000, 0.5, 0.9) > 10 * rms(y, 16000, 0.05, 0.4)
    p.transition_set("c1", "fade", 0.4)
    p.graphic_add("title_card", 0.2, 1.2, text="Titlu")
    msg = p.sfx_auto()
    assert "whoosh" in msg and "impact" in msg
    n = len(p.tl.sfx)
    p.sfx_auto()                      # idempotent: nu dublează
    assert len(p.tl.sfx) == n and any(x.id == "x0" for x in p.tl.sfx)
    assert probe(p.render(preview=True)["path"]).duration == pytest.approx(p.tl.duration, abs=0.1)


def test_multicam_sync_angle_split_and_auto(vhome, cams):
    p = Project("mc")
    p.add_asset(cams["A"], "a0")
    p.add_asset(cams["B"], "a1")
    msg = p.multicam_sync("a0,a1")
    assert p.tl.sync["a1"] == pytest.approx(-1.5, abs=0.02), msg
    p.add_clip("a0", 2.0, 8.0)
    p.multicam_angle(1.0, 3.0, "a1")
    angles = [(c.angle, round(s, 2)) for c, s in zip(p.tl.clips, p.tl.starts())]
    assert angles == [(None, 0.0), ("a1", 1.0), (None, 3.0)]
    out = p.render(preview=True)["path"]
    red, blue = frame(out, 0.5), frame(out, 2.0)
    assert red[..., 0].mean() > 150 and red[..., 2].mean() < 80
    assert blue[..., 2].mean() > 150 and blue[..., 0].mean() < 80
    # sunetul rămâne al referinței: identic cu randarea fără multicam
    y = load_mono(out, sr=16000)
    q = Project("mc_ref")
    q.add_asset(cams["A"], "a0")
    q.add_clip("a0", 2.0, 8.0)
    y0 = load_mono(q.render(preview=True)["path"], sr=16000)
    n = min(len(y), len(y0))
    assert np.corrcoef(y[:n], y0[:n])[0, 1] > 0.95
    # unghi care nu acoperă momentul => eroare clară
    with pytest.raises(KeyError):
        p.multicam_angle(5.9, 6.0, "zz")
    # split-screen: sus A (roșu), jos B (albastru)
    p.split_screen(3.0, 5.0, "a0,a1", mode="stack")
    fr = frame(p.render(preview=True)["path"], 4.0)
    h = fr.shape[0]
    assert fr[: h // 3, :, 0].mean() > 150 and fr[2 * h // 3:, :, 2].mean() > 150
    # rotate: alternează camerele
    words = [Word(i=i, start=2.0 + i * 0.5, end=2.0 + i * 0.5 + 0.4, text=f"w{i}") for i in range(12)]
    p.set_transcript("a0", Transcript(words=words))
    p.multicam_auto(mode="rotate", mapping="x=a0,y=a1", every=2.0)
    assert {c.angle for c in p.tl.clips} == {None, "a1"}


def test_multicam_speaker_mode_and_mcp(vhome, cams, monkeypatch):
    p = Project("mcs")
    p.add_asset(cams["A"], "a0")
    p.add_asset(cams["B"], "a1")
    p.multicam_sync("a0,a1")
    p.add_clip("a0", 2.0, 10.0)
    words = [Word(i=i, start=2.0 + i * 0.4, end=2.3 + i * 0.4, text="x", spk="S0" if i < 10 else "S1")
             for i in range(20)]
    p.set_transcript("a0", Transcript(words=words))
    assert "lipsește camera" in mcp.multicam_auto("mcs", mode="speaker", mapping="S0=a0")
    out = mcp.multicam_auto("mcs", mode="speaker", mapping="S0=a0,S1=a1", min_shot=1.0)
    assert "cadre" in out, out
    tl = Project("mcs").tl
    shots = [(c.angle or c.asset, s) for c, s in zip(tl.clips, tl.starts())]
    assert shots[0][0] == "a0" and shots[-1][0] == "a1"
    switch = next(s for a, s in shots if a == "a1")
    assert 3.4 < switch < 4.4            # S1 începe la 4.0 s pe montaj
    assert mcp.multicam_sync("mcs", "a0,a1").startswith("sincronizat")


def test_broll_chroma_key(vhome, talking_video, tmp_path):
    green = tmp_path / "green.mp4"
    # B-roll verde cu un pătrat alb în mijloc: verdele dispare, pătratul rămâne
    run(["-y", "-f", "lavfi", "-i", "color=c=0x00FF00:s=640x360:r=25:d=2", "-vf",
         "drawbox=x=270:y=130:w=100:h=100:color=white:t=fill", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", str(green)])
    p = Project("key")
    p.add_asset(talking_video, "a0")
    p.add_asset(str(green), "a1")
    p.add_clip("a0", 0, 2)
    p.broll_add("a1", at=0.0, duration=2.0)
    bid = p.tl.broll[0].id
    p.broll_key(bid, "#00FF00")
    fr = frame(p.render(preview=True)["path"], 1.0)
    h, w = fr.shape[:2]
    corner = fr[: h // 5, : w // 5]
    assert not ((corner[..., 1] > 200) & (corner[..., 0] < 60)).mean() > 0.5   # nu mai e verde plin
    center = fr[int(h * 0.42):int(h * 0.58), int(w * 0.45):int(w * 0.55)]
    assert (center > 200).all(axis=2).mean() > 0.8                              # pătratul alb rămâne


def test_stabilize_smoke(vhome, tmp_path):
    shaky = tmp_path / "shaky.mp4"
    run(["-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=2", "-vf",
         "crop=600:330:x='20+15*sin(t*17)':y='15+12*sin(t*13)',scale=640:360",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(shaky)])
    p = Project("stab")
    p.add_asset(str(shaky), "a0")
    p.add_clip("a0", 0, 2)
    assert "stabilizat" in p.stabilize("a0", smoothing=10)
    assert "a0" in p.tl.stabilized
    assert probe(p.render(preview=True)["path"]).duration == pytest.approx(2, abs=0.15)
    p.stabilize("a0", off=True)
    assert not p.tl.stabilized


def test_graphics_through_render_and_intro_shift(vhome, tmp_path):
    gray = tmp_path / "gray.mp4"
    red = tmp_path / "red.mp4"
    for path, color, d in ((gray, "0x303030", 3), (red, "red", 1)):
        run(["-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=25:d={d}", "-f", "lavfi", "-i",
             f"sine=f=330:d={d}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
             "-c:a", "aac", str(path)])
    p = Project("gfx")
    p.add_asset(str(gray), "a0")
    p.add_asset(str(red), "a1")
    p.add_clip("a0", 0, 3)
    p.graphic_add("progress_bar", 0, 3, color="#00FF00")
    with pytest.raises(ValueError):
        p.graphic_add("counter", 0, 1, value_from=5, value_to=5)
    with pytest.raises(ValueError):
        p.graphic_add("hologram", 0, 1)
    p.brand_intro_outro(intro="a1")
    out = p.render(preview=True)["path"]

    def green_cols(t):
        fr = frame(out, t)
        top = fr[: max(3, fr.shape[0] // 40)]
        return int(((top[..., 1] > 180) & (top[..., 0] < 100)).any(axis=0).sum())

    assert green_cols(0.5) == 0                     # pe intro nu apare
    early, late = green_cols(1.6), green_cols(3.6)  # montajul începe la 1.0 s (după intro)
    assert 0 < early < late
