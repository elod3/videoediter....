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


def test_caption_emphasis_and_zoom_on_words(vhome, talking_video):
    from vedit.captions import to_ass

    p = Project("emph")
    p.add_asset(talking_video, "a0")
    text = "am ajuns la 12500 de clienti in doar trei luni fără reclame plătite".split()
    words = [Word(i=i, start=3.5 + i * 0.15, end=3.5 + i * 0.15 + 0.12, text=w) for i, w in enumerate(text)]
    p.set_transcript("a0", Transcript(words=words))
    p.add_clip("a0", 3.4, 5.6)
    p.captions("a0", "bold_center")
    with pytest.raises(ValueError):
        p.captions_emphasis("w99")
    msg = p.captions_emphasis("auto")
    assert "a0:w3" in p.tl.emphasis, msg                  # cifra câștigă
    p.captions_emphasis("w8", color="#FF3366", mode="add")
    ass = to_ass(p.tl)
    assert "\\1c&H6633FF&" in ass and "\\fscx125" in ass and "\\t(" in ass
    p.captions("a0", "karaoke")                            # evidențierea rămâne după refacere
    assert "\\fscx125" in to_ass(p.tl)
    fr = frame(p.render(preview=True)["path"], 1.2)
    assert ((fr[..., 0] > 200) & (fr[..., 1] < 120) & (fr[..., 2] > 60)).sum() > 30   # roz pe ecran
    p.zoom_on_words("w3", zoom=1.3, hold=0.6)
    zoomed = [c for c in p.tl.clips if c.crop.zoom > 1.2]
    assert len(zoomed) == 1 and zoomed[0].duration == pytest.approx(0.6, abs=0.05)


def test_scripted_runner_multicam_and_dynamic(vhome, cams):
    import threading

    from vedit.api.runners import ScriptedRunner

    p = Project("sr")
    p.add_asset(cams["A"], "a0")
    p.add_asset(cams["B"], "a1")
    words = [Word(i=i, start=1.6 + i * 0.5, end=1.6 + i * 0.5 + 0.4, text=w)
             for i, w in enumerate("azi am vândut 300 de produse într-o singură zi incredibil".split())]
    p.set_transcript("a0", Transcript(words=words))
    events = []
    msg, _ = ScriptedRunner().run("sr", "multicam cu ambele camere, subtitrări, mai dinamic", lambda t, d: events.append((t, d)),
                                  threading.Event())
    tools = [d["name"] for t, d in events if t == "tool"]
    assert "multicam_sync" in tools and "multicam_auto" in tools and "captions_emphasis" in tools, tools
    q = Project("sr")
    assert {c.angle for c in q.tl.clips} >= {"a1"} and q.tl.emphasis and q.tl.sfx, msg


def test_multicam_auto_falls_back_where_camera_missing(vhome, cams):
    """Camera B a pornit cu 1.5 s mai târziu: la început se vede referința, fără eroare."""
    p = Project("cov")
    p.add_asset(cams["A"], "a0")
    p.add_asset(cams["B"], "a1")
    p.multicam_sync("a0,a1")
    p.add_clip("a0", 0.0, 6.0)
    words = [Word(i=i, start=0.2 + i * 0.4, end=0.5 + i * 0.4, text="x", spk="S1") for i in range(14)]
    p.set_transcript("a0", Transcript(words=words))
    p.multicam_auto(mode="speaker", mapping="S1=a1", min_shot=0.5)
    shots = [(c.angle, round(s, 2)) for c, s in zip(p.tl.clips, p.tl.starts())]
    assert shots[0] == (None, 0.0) and any(a == "a1" for a, _ in shots), shots
    first_b = next(s for a, s in shots if a == "a1")
    assert 1.4 < first_b < 1.8


def test_no_subframe_slivers_and_render_never_hangs(vhome, talking_video):
    """Regresie din testul cu agentul real: multicam_angle până la 28.17 din 28.18 lăsa un clip de 5 ms,
    iar ffmpeg aștepta la nesfârșit un cadru care nu vine."""
    p = Project("sliver")
    p.add_asset(talking_video, "a0")
    p.add_clip("a0", 0, 3)
    with p.edit() as tl:
        tl.split_at(2.995)                 # sub 2 cadre de final: nu taie
        assert len(tl.clips) == 1
        tl.clips.append(tl.clips[0].model_copy(update={"id": "tiny", "src_in": 5.0, "src_out": 5.004}))
    r = p.render(preview=True)            # clipul de 4 ms e ignorat, nu blochează
    assert r["duration"] == pytest.approx(3.0, abs=0.1)


def test_photo_becomes_still_clip_with_ken_burns(vhome, tmp_path, talking_video):
    from test_brand_export import write_png

    img = write_png(tmp_path / "produs.png", 300, 200, lambda x, y: (255, 140, 0, 255) if x < 150 else (20, 20, 200, 255))
    p = Project("foto")
    p.add_asset(talking_video, "a0")
    msg = p.add_asset(img, "a1")
    assert "POZĂ" in msg and p.s.assets["a1"].has_video and p.s.assets["a1"].duration >= 59
    assert p.s.meta["a1"]["source"] == "image"
    p.add_clip("a0", 0, 1.5)
    p.add_clip("a1", 0, 2.0)
    p.zoom_animate("c1", zoom_to=1.2)
    out = p.render(preview=True)["path"]
    assert probe(out).duration == pytest.approx(3.5, abs=0.1)
    fr = frame(out, 2.5)
    h, w = fr.shape[:2]
    assert fr[h // 2, w // 8, 0] > 200 and fr[h // 2, 7 * w // 8, 2] > 150     # poza, stânga portocaliu / dreapta albastru
    p.broll_add("a1", at=0.2, duration=1.0, mode="pip")                           # și ca B-roll (produs în colț)
    assert probe(p.render(preview=True)["path"]).duration == pytest.approx(3.5, abs=0.1)


def test_chapters_youtube_rules_and_export(vhome, talking_video):
    p = Project("chap")
    p.add_asset(talking_video, "a0")
    for _ in range(5):
        p.add_clip("a0", 0, 8)                       # 40 s
    with pytest.raises(ValueError):
        p.chapters_set("5=Intro|15=A|30=B")         # nu începe la 0
    with pytest.raises(ValueError):
        p.chapters_set("0=Intro|5=A|30=B")          # sub 10 s
    txt = p.chapters_set("0=Intro|12.5=Cum am început|30=Greșeli", title_cards=True)
    assert txt.splitlines() == ["0:00 Intro", "0:12 Cum am început", "0:30 Greșeli"]
    assert [g.start for g in p.tl.graphics if g.id.startswith("gch")] == [12.5, 30]
    p.chapters_set("0=Intro|12.5=Cum am început|30=Greșeli")   # fără title cards: le scoate
    assert not [g for g in p.tl.graphics if g.id.startswith("gch")]


def test_text_based_editing_api(vhome, talking_video):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vedit.api.app import create_app
    from vedit.api.runners import ScriptedRunner

    with TestClient(create_app(ScriptedRunner())) as c:
        c.post("/api/projects", json={"name": "txt"})
        with open(talking_video, "rb") as f:
            c.post("/api/projects/txt/assets", files={"file": ("t.mp4", f, "video/mp4")})
        assert c.get("/api/projects/txt/transcript/a0").status_code == 404
        words = [Word(i=i, start=0.1 + i * 0.3, end=0.35 + i * 0.3, text=f"w{i}") for i in range(20)]
        Project("txt").set_transcript("a0", Transcript(words=words))
        Project("txt").add_clip("a0", 0, 6.2)
        data = c.get("/api/projects/txt/transcript/a0").json()
        assert len(data["words"]) == 20 and all(w["kept"] for w in data["words"])
        r = c.post("/api/projects/txt/transcript/a0/cut", json={"spans": "w5-w9"})
        assert r.status_code == 200 and r.json()["duration"] < 6.2 - 1.2
        kept = [w["kept"] for w in c.get("/api/projects/txt/transcript/a0").json()["words"]]
        assert kept[4] and not any(kept[5:10]) and kept[10]
        assert c.post("/api/projects/txt/transcript/a0/cut", json={"spans": "zz"}).status_code == 400
        assert c.get("/api/projects/txt/chapters.txt").status_code == 404


def test_ripple_overlays_follow_cuts(vhome, talking_video, tmp_path):
    """Tăieturile făcute DUPĂ subtitrări / grafice / B-roll / sfx le mută odată cu vorbirea (ca un editor NLE)."""
    p = Project("rip")
    p.add_asset(talking_video, "a0")
    p.add_asset(talking_video, "a1")
    words = [Word(i=i, start=0.2 + i * 0.35, end=0.5 + i * 0.35, text=f"cuv{i}") for i in range(20)]
    p.set_transcript("a0", Transcript(words=words))
    p.add_clip("a0", 0, 7.4)
    p.captions("a0", "bold_center")
    p.captions_emphasis("w12")
    t12 = p.tl.source_to_timeline("a0", words[12].start)[0]
    p.graphic_add("title_card", t12, t12 + 1.0, text="Ideea")
    p.graphic_add("callout", 1.0, 1.9, text="dispare")        # peste w2-w4, care vor fi tăiate
    p.broll_add("a1", at=5.0, duration=1.5)
    p.sfx_add("pop", t12)
    p.remove_words("a0", "w2-w5")
    cut = words[6].start - words[2].start
    tl = p.tl
    new12 = tl.source_to_timeline("a0", words[12].start)[0]
    assert new12 == pytest.approx(t12 - cut, abs=0.06)
    g = {x.text: x for x in tl.graphics}
    assert "dispare" not in g and g["Ideea"].start == pytest.approx(new12, abs=0.06)
    assert tl.sfx[0].at == pytest.approx(new12, abs=0.06)
    assert tl.broll[0].start == pytest.approx(5.0 - cut, abs=0.06) and tl.broll[0].src_in == 0
    text = " ".join(c.text for c in tl.captions)
    assert all(f"cuv{i}" not in text.split() for i in range(2, 6)) and "cuv12" in text
    cap12 = next(c for c in tl.captions if "cuv12" in c.text)
    assert cap12.start <= new12 + 0.05                        # subtitrarea e tot pe cuvântul ei
    assert tl.emphasis == ["a0:w12"]
    p.undo()                                                  # undo readuce totul
    assert {x.text for x in p.tl.graphics} == {"Ideea", "dispare"}


@pytest.fixture(scope="session")
def seg_assets(tmp_path_factory):
    """Modelul de decupare (MODNet) și o poză cu o persoană; fără rețea, testul se sare."""
    import urllib.request

    pytest.importorskip("cv2")
    from vedit.segment import MODEL_URL

    d = tmp_path_factory.mktemp("seg")
    try:
        urllib.request.urlretrieve(MODEL_URL, d / "modnet.onnx")
        urllib.request.urlretrieve("https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/messi5.jpg",
                                   d / "messi.jpg")
    except OSError:
        pytest.skip("fără rețea pentru modelul de decupare")
    return d


def test_background_replacement_without_green_screen(vhome, seg_assets, monkeypatch):
    import cv2

    monkeypatch.setenv("VEDIT_SEG_MODEL", str(seg_assets / "modnet.onnx"))
    img = cv2.imread(str(seg_assets / "messi.jpg"))                 # 548x342, jucătorul în stânga-centru
    p = Project("bg")
    p.add_asset(str(seg_assets / "messi.jpg"), "a0")
    p.add_clip("a0", 0, 1.5)
    with p.edit() as tl:
        tl.width, tl.height = 548, 342
    p.background("c0", "color", "#00FF00")
    assert "a0" in p.tl.mattes and p.tl.clips[0].bg.mode == "color"
    fr = frame(p.render(preview=True)["path"], 0.7, width=548)
    green = (fr[..., 1] > 200) & (fr[..., 0] < 60) & (fr[..., 2] < 60)
    assert green[5:40, 400:540].mean() > 0.9                         # colțul dreapta-sus (public) e acum verde
    body = fr[130:200, 215:265]                                      # tricoul jucătorului rămâne
    assert not green[130:200, 215:265].any() and body.std() > 10
    ref = cv2.resize(img, (548, 342))[..., ::-1].astype(int)
    assert np.abs(fr[140:190, 220:260] - ref[140:190, 220:260]).mean() < 40
    p.background("c0", "blur")
    blurred = frame(p.render(preview=True)["path"], 0.7, width=548)
    assert np.abs(np.diff(blurred[5:60, 300:540].mean(axis=2), axis=1)).mean() < \
        np.abs(np.diff(ref[5:60, 300:540].mean(axis=2), axis=1)).mean() * 0.6   # publicul e încețoșat
    p.background("c0", "none")
    assert p.tl.clips[0].bg is None


def test_text_behind_person(vhome, seg_assets, monkeypatch):
    import cv2

    monkeypatch.setenv("VEDIT_SEG_MODEL", str(seg_assets / "modnet.onnx"))
    p = Project("behind")
    p.add_asset(str(seg_assets / "messi.jpg"), "a0")
    p.add_clip("a0", 0, 2.0)
    with p.edit() as tl:
        tl.width, tl.height = 548, 342
    ref = cv2.resize(cv2.imread(str(seg_assets / "messi.jpg")), (548, 342))[..., ::-1].astype(int)
    p.graphic_add("title_card", 0.1, 1.9, text="GOOOOOOL", color="#FF00FF")
    front = frame(p.render(preview=True)["path"], 1.2, width=548)
    p.undo()
    with pytest.raises(ValueError):
        p.graphic_add("lower_third", 0.1, 1.9, text="x", behind=True)
    p.graphic_add("title_card", 0.1, 1.9, text="GOOOOOOL", color="#FF00FF", behind=True)
    assert "a0" in p.tl.mattes
    back = frame(p.render(preview=True)["path"], 1.2, width=548)
    torso = (slice(130, 200), slice(215, 265))
    white_front = ((front[torso] > 235).all(axis=2)).mean()
    white_back = ((back[torso] > 235).all(axis=2)).mean()
    assert white_front > 0.05 and white_back < white_front / 4          # peste tricou, textul dispare
    assert np.abs(back[torso] - ref[torso]).mean() < np.abs(front[torso] - ref[torso]).mean()
    assert (back > 235).all(axis=2).sum() > 500                          # textul se vede în rest


def test_blur_fill_transcript_fix_and_translation(vhome, talking_video):
    p = Project("fixes")
    p.add_asset(talking_video, "a0")
    words = [Word(i=i, start=0.2 + i * 0.4, end=0.5 + i * 0.4, text=w)
             for i, w in enumerate("salut sunt mihal de la vedet și azi editez".split())]
    p.set_transcript("a0", Transcript(words=words))
    p.add_clip("a0", 0, 3.8)
    p.set_format("9:16", fill="blur")
    with pytest.raises(ValueError):
        p.set_format("9:16", fill="stretch")
    p.captions("a0", "bold_center")
    out = p.transcript_fix("a0", "w2=Mihai|w5=vedit")
    assert "mihal -> Mihai" in out and "refăcute" in out
    text = " ".join(c.text for c in p.tl.captions)
    assert "Mihai" in text and "vedit" in text and "mihal" not in text
    with pytest.raises(ValueError):
        p.transcript_fix("a0", "w99=x")
    p.captions_text("0=Hi, I'm Mihai")
    assert p.tl.captions[0].text == "Hi, I'm Mihai" and p.tl.captions[0].word_ids is None
    with pytest.raises(ValueError):
        p.captions_text("50=nope")
    fr = frame(p.render(preview=True)["path"], 1.0, width=270)
    h = fr.shape[0]
    assert fr[h // 2].std() > 20 and fr[5].std() > 3            # centrul = clipul, sus = fundal încețoșat (nu negru)
    assert fr[5].mean() > 15


def test_auto_keywords_prefer_meaning_over_proper_names(vhome, talking_video):
    p = Project("kw")
    p.add_asset(talking_video, "a0")
    text = "the pictures of Birkitt are wonderfully luminous and delicate".split()
    p.set_transcript("a0", Transcript(words=[Word(i=i, start=0.2 + i * 0.3, end=0.45 + i * 0.3, text=w)
                                             for i, w in enumerate(text)]))
    p.add_clip("a0", 0, 3.5)
    p.captions("a0", "karaoke")
    p.captions_emphasis("auto")
    chosen = {k.split(":")[1] for k in p.tl.emphasis}
    assert "w3" not in chosen and chosen & {"w5", "w6", "w8"}, chosen   # nu „Birkitt”


def test_voiceover_faceless_video(vhome, tmp_path):
    """Script -> voce (Piper) pe A3, poze pe V1 cu Ken Burns, subtitrări din textul exact, muzica sub voce."""
    pytest.importorskip("piper")
    from test_brand_export import write_png

    p = Project("faceless")
    try:
        msg = p.voiceover("Trei trucuri de montaj. Primul: taie pauzele. Al doilea: pune subtitrări mari.", "ro")
    except RuntimeError as e:
        if "descărca" in str(e):
            pytest.skip("fără rețea pentru vocea Piper")
        raise
    vo = p.tl.narration.asset
    assert vo.startswith("vo") and "A3" in msg
    dur = p.s.assets[vo].duration
    assert 3 < dur < 15
    imgs = []
    for k, col in enumerate([(200, 40, 40, 255), (40, 200, 40, 255), (40, 40, 200, 255)]):
        imgs.append(p.add_asset(write_png(tmp_path / f"f{k}.png", 320, 180, lambda x, y, c=col: c), f"i{k}").split(":")[0])
    p.visuals_fill("i0,i1,i2", per=2.0)
    assert p.tl.duration == pytest.approx(dur + 0.3, abs=0.05) and all(c.anim for c in p.tl.clips)
    p.captions(vo, "bold_center")
    assert "TRUCURI" in " ".join(c.text.upper() for c in p.tl.captions)
    assert p.tl.captions[0].start >= 0 and p.tl.captions[-1].end <= p.tl.duration + 0.01
    assert p.voiceover("Trei trucuri de montaj. Primul: taie pauzele. Al doilea: pune subtitrări mari.", "ro") \
        and len([a for a in p.s.assets if a.startswith("vo")]) == 1                     # aceeași voce, refolosită
    out = p.render(preview=True)["path"]
    y = load_mono(out, sr=16000)
    assert rms(y, 16000, 0.5, dur - 0.5) > 0.02                                        # vocea se aude
    qa = p.qa(out)
    assert qa["ok"], qa
    with pytest.raises(ValueError):
        p.voiceover("Salut", lang="klingon")


def test_visuals_follow_script_words(vhome, tmp_path):
    from test_brand_export import write_png

    from vedit.timeline import Narration

    p = Project("vw")
    tone = tmp_path / "vo.m4a"
    run(["-y", "-f", "lavfi", "-i", "sine=f=200:d=12", "-c:a", "aac", str(tone)])
    p.add_asset(str(tone), "vo")
    p.set_transcript("vo", Transcript(words=[Word(i=i, start=i * 0.5, end=i * 0.5 + 0.4, text="x") for i in range(24)]))
    with p.edit() as tl:
        tl.narration = Narration(asset="vo")
    for k in range(3):
        p.add_asset(write_png(tmp_path / f"p{k}.png", 160, 90, lambda x, y, k=k: (80 * k, 50, 50, 255)), f"i{k}")
    with pytest.raises(ValueError):
        p.visuals_fill("i0,i1,i2", at_words="w0,w10")
    p.visuals_fill("i0,i1,i2", per=2.0, at_words="w0,w6,w20")
    starts = {}
    for c, s in zip(p.tl.clips, p.tl.starts()):
        starts.setdefault(c.asset, s)
    assert starts == {"i0": 0.0, "i1": pytest.approx(3.0), "i2": pytest.approx(10.0)}
    assert max(c.duration for c in p.tl.clips) <= 3.0 + 1e-6               # segmentul lung, împărțit


def test_new_caption_styles_and_recipes(vhome, talking_video):
    from vedit.captions import to_ass

    p = Project("rec")
    p.add_asset(talking_video, "a0")
    text = "am crescut de la zero la 12000 de clienți în doar opt luni fără reclame".split()
    p.set_transcript("a0", Transcript(words=[Word(i=i, start=0.1 + i * 0.3, end=0.35 + i * 0.3, text=w)
                                             for i, w in enumerate(text)]))
    p.add_clip("a0", 0, 4.0)
    p.captions("a0", "word_pop")
    assert all(len(c.text.split()) == 1 for c in p.tl.captions) and "\\t(0,90" in to_ass(p.tl)
    p.captions("a0", "boxed")
    assert ",3," in next(line for line in to_ass(p.tl).splitlines() if line.startswith("Style: Cap"))
    msg = p.style_recipe("hormozi")
    assert "punch-in" in msg and p.tl.emphasis and p.tl.sfx and p.tl.caption_style == "bold_center"
    assert any(c.crop.zoom > 1.1 for c in p.tl.clips)
    p.style_recipe("tiktok")
    assert p.tl.caption_style == "boxed" and not any(x.id.startswith("xa") for x in p.tl.sfx)
    p.style_recipe("mrbeast")
    assert p.tl.caption_style == "word_pop" and "a0" in p.tl.grades
    with pytest.raises(ValueError):
        p.style_recipe("wes_anderson")
    assert probe(p.render(preview=True)["path"]).duration == pytest.approx(p.tl.duration, abs=0.1)


def test_sticker_thumbnail(vhome, seg_assets, monkeypatch):
    import cv2

    monkeypatch.setenv("VEDIT_SEG_MODEL", str(seg_assets / "modnet.onnx"))
    p = Project("thumb")
    p.add_asset(str(seg_assets / "messi.jpg"), "a0")
    p.add_clip("a0", 0, 2)
    with p.edit() as tl:
        tl.width, tl.height = 548, 342
    plain = cv2.imread(p.thumbnail_export(at=1.0)["image"]).astype(int)
    out = p.thumbnail_export(at=1.0, title="GOL", style="sticker")
    st = cv2.imread(out["image"]).astype(int)
    assert out["style"] == "sticker" and st.shape == plain.shape
    corner = (slice(5, 60), slice(420, 540))                   # publicul din spate: încețoșat și întunecat
    assert st[corner].mean() < plain[corner].mean() * 0.8
    torso = (slice(140, 190), slice(220, 260))                  # jucătorul rămâne neatins
    assert np.abs(st[torso] - plain[torso]).mean() < 25
    with pytest.raises(ValueError):
        p.thumbnail_export(style="neon")


def test_clean_speech_and_auto_pacing(vhome, talking_video):
    p = Project("clean")
    p.add_asset(talking_video, "a0")
    text = "ăăă deci eu eu cred că și asta și asta contează um foarte mult pentru noi toți".split()
    p.set_transcript("a0", Transcript(words=[Word(i=i, start=0.1 + i * 0.4, end=0.4 + i * 0.4, text=w)
                                             for i, w in enumerate(text)]))
    p.add_clip("a0", 0, 8.0)
    msg = p.clean_speech("a0")
    assert "curățat" in msg, msg
    kept = [w.text for w in p.transcript("a0").words
            if any(c.src_in <= (w.start + w.end) / 2 < c.src_out for c in p.tl.clips)]
    assert "ăăă" not in kept and "um" not in kept
    assert kept.count("eu") == 1 and " ".join(kept).count("și asta") == 1 and "deci" in kept
    assert "nimic" in p.clean_speech("a0")                                 # a doua oară: nimic de scos

    q = Project("pace")
    q.add_asset(talking_video, "a0")
    q.set_transcript("a0", Transcript(words=[Word(i=i, start=i * 0.5, end=i * 0.5 + 0.35, text="x")
                                             for i in range(16)]))
    q.add_clip("a0", 0, 8.0)
    before = q.tl.duration
    out = q.auto_pacing(max_static=2.5, zoom=1.2)
    assert "tăieturi" in out and len(q.tl.clips) >= 3
    assert q.tl.duration == pytest.approx(before, abs=0.01)                # doar tăieturi, nimic scos
    zooms = [c.crop.zoom for c in q.tl.clips]
    assert zooms[0] == 1.0 and zooms[1] == pytest.approx(1.2) and max(c.duration for c in q.tl.clips) < 3.8
    ends = {round(w.end, 3) for w in q.transcript("a0").words}
    assert all(round(c.src_out, 3) in ends for c in q.tl.clips[:-1])     # tăieturile cad pe final de cuvânt


@pytest.fixture(scope="module")
def podcast_cams(tmp_path_factory):
    """Podcast cu 2 vorbitori și 3 camere: wide (aude pe amândoi), ana și mihai (microfonul fiecăruia aude
    mai tare pe vorbitorul lui). Ana a pornit cu 1 s mai târziu, Mihai cu 0.5 s."""
    from vedit.sfx import write_wav

    d = tmp_path_factory.mktemp("pod")
    rng = np.random.default_rng(3)
    sr, dur = 48000, 14.0
    turns = [(0.3, 4.5, "ana"), (5.0, 9.6, "mihai"), (10.0, 13.6, "ana")]
    voice = {"ana": np.zeros(int(sr * dur), np.float32), "mihai": np.zeros(int(sr * dur), np.float32)}
    for a, b, who in turns:
        t = a
        while t < b:                                   # silabe: rafale scurte, cu goluri mici
            n = rng.uniform(0.12, 0.35)
            voice[who][int(t * sr):int(min(t + n, b) * sr)] = \
                rng.standard_normal(int(min(t + n, b) * sr) - int(t * sr)) * rng.uniform(0.2, 0.4)
            t += n + rng.uniform(0.05, 0.2)
    lead = {"wide": 0.0, "ana": 1.0, "mihai": 0.5}
    mix = {"wide": 0.6 * (voice["ana"] + voice["mihai"]), "ana": voice["ana"] + 0.2 * voice["mihai"],
           "mihai": voice["mihai"] + 0.2 * voice["ana"]}
    out = {}
    for (cam, y), color in zip(mix.items(), ("gray", "red", "blue")):
        y = y[int(lead[cam] * sr):] + rng.standard_normal(len(y) - int(lead[cam] * sr)).astype(np.float32) * 0.003
        write_wav(d / f"{cam}.wav", np.stack([y, y], 1))
        p = d / f"{cam}.mp4"
        run(["-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=25:d={dur - lead[cam]}",
             "-i", str(d / f"{cam}.wav"), "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
             "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)])
        out[cam] = str(p)
    return out


def test_multicam_mics_mode(vhome, podcast_cams):
    p = Project("mics")
    for cam, path in podcast_cams.items():
        p.add_asset(path, cam)
    p.multicam_sync("wide,ana,mihai")
    assert p.tl.sync["ana"] == pytest.approx(-1.0, abs=0.02)
    p.add_clip("wide", 0, p.s.assets["wide"].duration)
    assert "fără diarizare" not in mcp.multicam_auto("mics", mode="mics", wide="nope")  # eroare clară, nu crash
    out = p.multicam_auto("mics", wide="wide", min_shot=1.0)
    assert "multicam mics" in out

    def angle_at(t):
        s = 0.0
        for c in p.tl.clips:
            if s <= t < s + c.duration:
                return c.angle or c.asset
            s += c.duration
    assert [angle_at(t) for t in (2.0, 7.0, 12.0)] == ["ana", "mihai", "ana"]
    r = p.render(preview=True)
    assert frame(r["path"], 7.0)[..., 2].mean() > frame(r["path"], 7.0)[..., 0].mean() + 40  # albastru = mihai
