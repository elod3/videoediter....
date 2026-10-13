"""Compoziție liberă: clip_animate (poziție/scară/rotație/opacitate), fx_chain (listă albă), text_overlay.

Toate randate real (mp4 pe disc), nu mock.
"""
import numpy as np
import pytest

from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame


def src(path, dur=4.0):
    run(["-y", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={dur}",
         "-f", "lavfi", "-i", f"sine=f=300:d={dur}", "-shortest", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)])
    return str(path)


def frame(path, t, width=240):
    info = probe(path)
    return grab_frame(path, t, info.width, info.height, width=width).astype(int)


def test_clip_animate_transforms_over_time(vhome, tmp_path):
    p = Project("anim")
    p.set_format("16:9")
    p.add_asset(src(tmp_path / "a.mp4", 3.0), "a0")
    p.add_clip("a0", 0, 3)
    p.clip_animate("c0", '[{"t":0,"scale":0.4,"x":0.25,"opacity":0.15},'
                         '{"t":2.5,"scale":1.0,"x":0.5,"opacity":1.0}]')
    assert len(p.tl.clips[0].animate) == 2
    out = p.render(preview=True)["path"]
    assert probe(out).duration > 2.5
    f0, f2 = frame(out, 0.15), frame(out, 2.4)
    assert f0.mean() < f2.mean()                          # se aprinde (opacitate + scară cresc)
    assert f0[:, -30:].mean() < 12                        # la început, colțul dreapta e negru (clip mic, în stânga)


def test_clip_animate_validation_and_clear(vhome, tmp_path):
    p = Project("animv")
    p.add_asset(src(tmp_path / "a.mp4"), "a0")
    p.add_clip("a0", 0, 3)
    for bad in ['[{"t":-0.5}]', '[{"t":0,"scale":9}]', '[{"t":0,"x":1.5}]', '[{"t":0,"opacity":2}]', 'garbage']:
        with pytest.raises(ValueError):
            p.clip_animate("c0", bad)
    p.clip_animate("c0", '[{"t":0},{"t":1,"scale":1.2}]')
    assert p.tl.clips[0].animate
    p.clip_animate("c0", "")                              # golește
    assert p.tl.clips[0].animate == []


def test_fx_chain_whitelist_and_render(vhome, tmp_path):
    p = Project("fx")
    p.set_format("16:9")
    p.add_asset(src(tmp_path / "a.mp4", 3.0), "a0")
    p.add_clip("a0", 0, 3)
    p.fx_chain("c0", "saturation:value=0|brightness:value=0")   # alb-negru
    assert [s.name for s in p.tl.clips[0].fx_chain] == ["saturation", "brightness"]
    out = frame(p.render(preview=True)["path"], 1.5)
    assert np.abs(out[..., 0] - out[..., 2]).mean() < 6    # R ≈ B: fără culoare
    for bad in ["magic:value=1", "blur:sigma=999", "brightness:value=5", "contrast:necunoscut=1"]:
        with pytest.raises(ValueError):
            p.fx_chain("c0", bad)
    p.fx_chain("c0", "mirror|grain:strength=10")           # formă compactă
    assert [s.name for s in p.tl.clips[0].fx_chain] == ["mirror", "grain"]
    assert probe(p.render(preview=True)["path"]).duration > 2.5


def test_text_overlay_free_position_and_color(vhome, tmp_path):
    p = Project("txt")
    p.set_format("16:9")
    p.add_asset(src(tmp_path / "a.mp4", 3.0), "a0")
    p.add_clip("a0", 0, 3)
    p.text_overlay(0.3, 2.6, "TITLU LIBER", x=0.5, y=0.2, size=0.09, color="#FFD400", anim="wipe")
    assert p.tl.texts[0].x == 0.5 and p.tl.texts[0].anim == "wipe"
    fr = frame(p.render(preview=True)["path"], 1.5, width=320)
    top = fr[: int(0.4 * fr.shape[0])]
    yellow = (top[..., 0] > 180) & (top[..., 1] > 150) & (top[..., 2] < 120)
    assert yellow.sum() > 30                              # textul galben e sus, unde l-am pus


def test_text_overlay_validation(vhome, tmp_path):
    p = Project("txtv")
    p.add_asset(src(tmp_path / "a.mp4"), "a0")
    p.add_clip("a0", 0, 3)
    with pytest.raises(ValueError):
        p.text_overlay(0, 2, "")
    with pytest.raises(ValueError):
        p.text_overlay(2, 1, "x")
    with pytest.raises(ValueError):
        p.text_overlay(0, 2, "x", anim="fly")
    with pytest.raises(ValueError):
        p.text_overlay(0, 2, "x", x=2)
    with pytest.raises(ValueError):
        p.text_overlay(0, 2, "x", size=0.9)
