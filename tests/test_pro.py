"""Ce face montajul să sune și să arate „de editor”: biblioteca de sunete, muzica, tranzițiile, keyframe-urile,
subtitrările prin motorul de motion, urmărirea obiectelor și encoderul hardware."""
import json
import math
import shutil
import wave

import numpy as np
import pytest

from vedit import render as rd
from vedit import sfxlib
from vedit.ff import run
from vedit.project import Project
from vedit.style import grab_frame
from vedit.timeline import Caption

needs_chrome = pytest.mark.skipif(not any(shutil.which(b) for b in ("chromium", "google-chrome-stable", "google-chrome")),
                                  reason="fără Chromium")


def _wav(path, x, sr=48000):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes(np.repeat(pcm[:, None], 2, 1).tobytes())


def _read(path):
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).astype(float) / 32767


# ---------------- efecte sonore reale ----------------
def test_prepare_aligns_peak_and_onset(tmp_path):
    sr = 48000
    t = np.arange(int(sr * 3.0)) / sr
    swell = np.exp(-((t - 2.1) ** 2) / 0.02) * np.sin(2 * np.pi * 300 * t) * 0.6   # vârf la 2,1 s, liniște înainte
    _wav(tmp_path / "w.wav", swell)
    out = tmp_path / "whoosh.wav"
    sfxlib.prepare(tmp_path / "w.wav", "whoosh", out)
    y = _read(out)
    win = 960
    rms = np.sqrt(np.convolve((y ** 2).mean(1), np.ones(win) / win, "same"))
    assert abs(rms.argmax() / sr - 0.38) < 0.03                          # vârful cade unde cade și la cel sintetizat
    assert abs(np.abs(y).max() - 10 ** (-3 / 20)) < 0.02                 # normalizat la -3 dBFS
    hit = np.zeros(sr * 2)
    hit[int(sr * 0.7):int(sr * 0.75)] = 0.5                               # impact după 0,7 s de liniște
    _wav(tmp_path / "i.wav", hit)
    sfxlib.prepare(tmp_path / "i.wav", "impact", tmp_path / "impact.wav")
    z = _read(tmp_path / "impact.wav")
    assert np.argmax(np.abs(z).max(1) > 0.05) < sr * 0.01                # pornește imediat (liniștea tăiată)


def test_library_pick_import_and_fallback(tmp_path, monkeypatch, vhome):
    monkeypatch.setenv("VEDIT_SFX_DIR", str(tmp_path / "lib"))
    from vedit.sfx import sfx_path

    assert sfx_path("whoosh").parent.name == ".sfx"                       # fără bibliotecă: cel sintetizat
    assert sfx_path("buildup").name == "riser.wav"                        # tip nou fără bibliotecă: înlocuitor
    pack = tmp_path / "pack"
    pack.mkdir()
    sr = 48000
    t = np.arange(sr) / sr
    for name in ("Big Whoosh 01.wav", "whoosh_02.wav", "UI click.wav", "random.wav"):
        _wav(pack / name, np.sin(2 * np.pi * 440 * t) * np.exp(-((t - 0.5) ** 2) / 0.01) * 0.5)
    res = sfxlib.import_dir(pack, "test", log=lambda *_: None)
    assert res["whoosh"] == 2 and res["click"] == 1 and "random" not in json.dumps(sfxlib.index())
    a, b = sfxlib.pick("whoosh", 1.0), sfxlib.pick("whoosh", 1.0)
    assert a == b and a.exists()                                          # determinist
    picks = {sfxlib.pick("whoosh", x / 10) for x in range(30)}
    assert len(picks) == 2                                                # variante diferite pe momente diferite
    assert sfx_path("whoosh", 1.0) == a                                   # randarea folosește biblioteca
    monkeypatch.setenv("VEDIT_SFX_SYNTH", "1")
    assert sfx_path("whoosh").parent.name == ".sfx"


def test_sources_manifest_is_pinned():
    spec = json.loads(sfxlib.SOURCES.read_text())
    for s in spec["sources"]:
        assert "CC0" in s["license"]
        for f in s.get("files", []):
            assert len(f["sha256"]) == 64 and f["kind"] in sfxlib.SHAPE
        if "zip" in s:
            assert len(s["zip"]["sha256"]) == 64 and "/archive/" in s["zip"]["url"]


# ---------------- muzică ----------------
def test_music_search_and_credit_reaches_the_post(vhome, talking_video, music_file, monkeypatch, tmp_path):
    from vedit import musiclib
    from vedit.publish.package import PostPackage

    res = musiclib.search("energic", bpm_min=110, bpm_max=140, min_seconds=60)
    assert res and all(110 <= p["bpm"] <= 140 for p in res if p["bpm"]) and all(p["seconds"] >= 60 for p in res)
    assert all(any(f in ("Driving", "Bouncy", "Action", "Intense") for f in p["feel"]) for p in res)
    premium = musiclib.search("premium", n=10)
    assert not any("waltz" in p["title"].lower() for p in premium[:5])
    tr = res[0]
    monkeypatch.setattr(musiclib, "fetch", lambda track: __import__("pathlib").Path(music_file))
    p = Project("mus")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 4)
    out = p.music_use(tr["id"], volume_db=-20)
    assert "Kevin MacLeod" in out and p.tl.music is not None
    credits = p.credits()
    assert credits and tr["title"] in credits[0] and "CC BY" not in credits[0] or "Attribution 4.0" in credits[0]
    pkg = PostPackage(id="1015-abcdef", project="mus", client="c", account="instagram:x", platform="instagram",
                      video="renders/a.mp4", caption="Plăcuțe noi", credits=credits)
    assert pkg.full_text().endswith(credits[0]) and "Muzică:" in pkg.full_text()


# ---------------- tranziții „de editor” ----------------
def test_pro_transitions_render(vhome, talking_video):
    p = Project("trx")
    p.add_asset(talking_video)
    for a, b in ((0, 2.5), (2.5, 5), (5, 8)):
        p.add_clip("a0", a, b)
    ids = [c.id for c in p.tl.clips]
    p.transition_set(ids[1], "whipleft", 0.3)
    p.transition_set(ids[2], "glitch", 0.2)
    path = p.render(preview=True)["path"]
    from vedit.probe import probe

    assert abs(probe(path).duration - p.tl.duration) < 0.15
    filt = " ".join(rd.build_command(p.tl, p.s.assets, str(vhome / "x.mp4"), preview=True)[0])
    assert "dblur" in filt and "rgbashift" in filt and "slideleft" in filt


# ---------------- keyframe-uri ----------------
def test_keyframes_move_the_camera(vhome, talking_video):
    p = Project("kf")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 4)
    c = p.tl.clips[0].id
    with pytest.raises(ValueError, match="2 keyframe"):
        p.keyframes_set(c, [{"t": 0, "zoom": 1.2}])
    with pytest.raises(ValueError, match="colțuri"):
        p.keyframes_set(c, [{"t": 0}, {"t": 2, "rotate": 10}])
    p.keyframes_set(c, [{"t": 0, "zoom": 1.0}, {"t": 1.0, "zoom": 2.0, "cx": 0.25, "cy": 0.25, "ease": "expo"},
                        {"t": 3.9, "zoom": 2.0, "cx": 0.25, "cy": 0.25}], motion_blur=True)
    path = p.render(preview=True)["path"]
    a = grab_frame(path, 0.05, 960, 540, width=320).astype(float)
    b = grab_frame(path, 2.0, 960, 540, width=320).astype(float)
    src = grab_frame(talking_video, 2.0, 640, 360, width=320).astype(float)
    assert np.abs(a - b).mean() > 10                                     # cadrul s-a mișcat
    assert np.abs(b - src).mean() > np.abs(a - grab_frame(talking_video, 0.05, 640, 360, width=320)).mean() + 5


# ---------------- subtitrări prin motorul de motion ----------------
@needs_chrome
def test_motion_captions_replace_ass_captions(vhome, talking_video):
    p = Project("mcap")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 4)
    p.set_format("9:16")
    with p.edit() as tl:
        tl.captions = [Caption(start=0.3, end=2.5, text="Patruzeci de clienți noi", word_durs=[0.5, 0.4, 0.6, 0.5],
                               word_ids=["a0:w0", "a0:w1", "a0:w2", "a0:w3"])]
        tl.emphasis = ["a0:w0"]
    for look in ("line", "chunk", "marker"):
        p.captions_look("motion", look)
        cmd = " ".join(rd.build_command(p.tl, p.s.assets, str(vhome / "x.mp4"), preview=True)[0])
        assert "captions.ass" not in cmd and "%05d.png" in cmd
    path = p.render(preview=True)["path"]
    with_text = grab_frame(path, 2.0, 540, 960, width=180).astype(float)
    before = grab_frame(path, 0.1, 540, 960, width=180).astype(float)
    band = slice(int(320 * 0.55), int(320 * 0.8))
    assert np.abs(with_text[band] - before[band]).mean() > 3              # textul apare în banda subtitrărilor
    p.captions_look("ass")
    assert "captions.ass" in " ".join(rd.build_command(p.tl, p.s.assets, str(vhome / "y.mp4"), preview=True)[0])


# ---------------- urmărirea unui obiect ----------------
def test_track_point_follows_a_moving_patch(vhome, tmp_path):
    pytest.importorskip("cv2")
    patch = tmp_path / "p.png"
    run(["-y", "-f", "lavfi", "-i", "testsrc2=size=160x160:d=1", "-frames:v", "1", str(patch)])
    mov = tmp_path / "m.mp4"
    run(["-y", "-f", "lavfi", "-i", "color=c=0x404850:s=1280x720:r=25:d=4", "-i", str(patch), "-filter_complex",
         "[0][1]overlay=x='100+t*200':y='300-t*40'", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(mov)])
    p = Project("trk")
    p.add_asset(str(mov))
    p.add_clip("a0", 0, 4)
    r = p.track_point(0.5, (100 + 100 + 80) / 1280, (300 - 20 + 80) / 720, 3.0)
    path = p.tl.tracks[r["track"]]["path"]
    errs = [math.hypot((x - (100 + (0.5 + t) * 200 + 80) / 1280) * 1280, (y - (300 - (0.5 + t) * 40 + 80) / 720) * 720)
            for t, x, y in path]
    assert len(path) > 30 and sum(errs) / len(errs) < 6
    with pytest.raises(ValueError, match="detalii"):
        p.track_point(3.5, 0.95, 0.1, 1.0)                                # zonă plată: refuzat
    p.motion_add("pin", 0.6, 3.0, {"label": "aici", "x": 0.2, "y": 0.5}, track=r["track"])
    assert p.tl.motion[0].track and abs(p.tl.motion[0].track[0][0] + 0.1) < 0.05


# ---------------- encoder hardware ----------------
def test_hw_encoder_falls_back_to_x264(monkeypatch):
    monkeypatch.setenv("VEDIT_ENCODER", "nvenc")
    monkeypatch.setitem(rd._hw_ok, "nvenc", False)
    assert rd.encoder_args() == rd.X264
    monkeypatch.setitem(rd._hw_ok, "nvenc", True)
    assert rd.encoder_args()[1] == "h264_nvenc"
    monkeypatch.setenv("VEDIT_ENCODER", "libx264")
    assert rd.encoder_args() == rd.X264
