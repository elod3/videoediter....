import wave

import numpy as np
import pytest

from vedit.audiofx import check
from vedit.beats import load_mono
from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame


@pytest.fixture(scope="module")
def colors(tmp_path_factory):
    d = tmp_path_factory.mktemp("fx")
    out = []
    for i, col in enumerate(["red", "blue", "green"]):
        p = d / f"{col}.mp4"
        run(["-y", "-f", "lavfi", "-i", f"color=c={col}:s=640x360:r=25:d=2", "-f", "lavfi", "-i", f"sine=f={300 + 100 * i}:d=2",
             "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)])
        out.append(str(p))
    bars = d / "bars.mp4"
    run(["-y", "-f", "lavfi", "-t", "3", "-i", "smptebars=size=640x360:rate=25", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(bars)])
    return {"clips": out, "bars": str(bars), "dir": d}


def test_transitions_overlap_and_blend(vhome, colors):
    p = Project("tr")
    for c in colors["clips"]:
        p.add_asset(c)
    for i in range(3):
        p.add_clip(f"a{i}", 0, 2)
    p.transition_set("c1", "fade", 0.5)
    p.transition_set("c2", "slideleft", 0.5)
    p.transition_set("c0", "fade", 0.5)          # primul clip: ignorat
    assert p.tl.clips[0].transition is None
    assert p.tl.duration == 5.0 and p.tl.starts() == [0, 1.5, 3.0]
    out = p.render(preview=True)["path"]
    info = probe(out)
    assert abs(info.duration - 5.0) < 0.1
    mid = grab_frame(out, 1.75, info.width, info.height).reshape(-1, 3).mean(0)  # jumătatea fade roșu→albastru
    assert mid[0] > 60 and mid[2] > 60, mid
    assert grab_frame(out, 1.0, info.width, info.height).reshape(-1, 3).mean(0)[2] < 30   # încă roșu pur
    with pytest.raises(ValueError):
        p.transition_set("c1", "explozie")
    p.tl.split_at(2.5)  # tăietura nouă nu moștenește tranziția
    assert [c.transition is not None for c in p.tl.clips] == [False, True, False, True]
    p.transition_set("all", "none")
    assert p.tl.duration == 6.0


def test_zoom_animation_measured(vhome, colors):
    import cv2

    p = Project("zoom")
    p.add_asset(colors["bars"])
    p.add_clip("a0", 0, 3)
    p.zoom_animate("c0", zoom_to=1.5, zoom_from=1.0, ease="linear")
    out = p.render(preview=True)["path"]
    info = probe(out)
    w = 320
    f0 = grab_frame(out, 0.0, info.width, info.height, width=w).astype(float)
    f1 = grab_frame(out, 2.96, info.width, info.height, width=w).astype(float)
    h = f0.shape[0]
    cw, ch = int(w / 1.5), int(h / 1.5)
    crop = f0[(h - ch) // 2:(h - ch) // 2 + ch, (w - cw) // 2:(w - cw) // 2 + cw]
    expected = cv2.resize(crop, (w, h), interpolation=cv2.INTER_LINEAR)
    assert np.abs(f1 - expected).mean() < 0.5 * np.abs(f1 - f0).mean()  # finalul = centrul mărit de 1.5x
    with pytest.raises(ValueError):
        p.zoom_animate("c0", zoom_to=3)


def noisy_voice(path, sr=48000, dur=9.0, noise_db=-32):
    rng = np.random.default_rng(3)
    t = np.arange(int(sr * dur)) / sr
    voice = sum(np.sin(2 * np.pi * f * t) / (k + 1) for k, f in enumerate([150, 300, 450, 600, 900]))
    voice *= 0.5 * (1 + np.sin(2 * np.pi * 4 * t)) / 2  # silabe ~4 Hz
    gate = ((t % 3) < 2).astype(float)                   # 2 s vorbire, 1 s pauză
    y = 0.25 * voice * gate + 10 ** (noise_db / 20) * rng.standard_normal(len(t))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())


def snr(path):
    y = load_mono(path, sr=16000)
    t = np.arange(len(y)) / 16000
    pause = ((t % 3) > 2.15) & ((t % 3) < 2.85)
    speech = ((t % 3) > 0.2) & ((t % 3) < 1.8)
    return 20 * np.log10(np.sqrt((y[speech] ** 2).mean()) / np.sqrt((y[pause] ** 2).mean()))


def test_audio_clean_improves_snr(vhome, tmp_path):
    wav = tmp_path / "v.wav"
    noisy_voice(wav)
    vid = tmp_path / "talk.mp4"
    run(["-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=9", "-i", str(wav), "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(vid)])
    p = Project("audio")
    p.add_asset(str(vid))
    rep = p.audio_check("a0")
    assert "SNR" in rep and ("medium" in rep or "strong" in rep or "light" in rep), rep
    p.add_clip("a0", 0, 9)
    before = snr(p.render(preview=True, name="before")["path"])
    p.audio_clean("a0", "medium")
    after = snr(p.render(preview=True, name="after")["path"])
    assert after - before > 8, (before, after)
    p.audio_clean("all", "none")
    assert p.tl.audio_fx == {}
    with pytest.raises(ValueError):
        p.audio_clean("a0", "magic")


def test_audio_check_detects_clipping(tmp_path):
    sr = 16000
    y = np.clip(1.6 * np.sin(2 * np.pi * 200 * np.arange(sr * 2) / sr), -1, 1)
    with wave.open(str(tmp_path / "c.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((y * 32767).astype(np.int16).tobytes())
    assert "clipping" in check(str(tmp_path / "c.wav"), []).recommendation
