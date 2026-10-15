"""Blocurile de motion (HTML + GSAP în Chromium): validare, stiluri, culori din filmare, cadre cu alfa, randare."""
import shutil

import numpy as np
import pytest

from vedit import motion as mo
from vedit.project import Project
from vedit.style import grab_frame

needs_chrome = pytest.mark.skipif(not any(shutil.which(b) for b in ("chromium", "google-chrome-stable", "google-chrome")),
                                  reason="fără Chromium")


def test_validate_rejects_bad_params():
    with pytest.raises(ValueError, match="necunoscut"):
        mo.validate("nu-exista", {}, 3, {})
    with pytest.raises(ValueError, match="lipsește text"):
        mo.validate("headline", {}, 3, {})
    with pytest.raises(ValueError, match="parametru necunoscut"):
        mo.validate("headline", {"text": "x", "html": "<b>"}, 3, {})
    with pytest.raises(ValueError, match="prea lung"):
        mo.validate("lower_third", {"name": "x" * 60}, 3, {})
    with pytest.raises(ValueError, match="aceeași lungime"):
        mo.validate("bars", {"labels": ["a", "b"], "values": [1]}, 4, {})
    with pytest.raises(ValueError, match="imaginea"):
        mo.validate("image_card", {}, 3, {})
    with pytest.raises(ValueError, match="una din"):
        mo.validate("headline", {"text": "x", "position": "stanga"}, 3, {})
    assert any("scurt" in w for w in mo.validate("list", {"items": ["a"]}, 1.2, {}))


def test_every_block_has_a_template_and_styles_resolve():
    for b in mo.BLOCK_HELP:
        assert (mo.BLOCKS / f"{b}.html").exists(), b
    for name in mo.styles_list():
        st = mo.resolve_style(name, {"accent": "#123456", "dark": "#010203", "dark2": "#020304"})
        assert st["colors"]["accent"] != "auto"
    st = mo.resolve_style("local", {"accent": "#123456", "dark": "#010203", "dark2": "#020304"}, brand_accent="#FF0000")
    assert st["colors"]["accent"] == "#FF0000" and st["colors"]["bg"] == "#010203"   # brandul bate filmarea


def test_palette_takes_the_dominant_hue():
    blue = np.zeros((40, 40, 3), np.uint8)
    blue[..., 2] = 200
    blue[:10, :10] = (120, 120, 120)                                   # puțin gri: ignorat
    pal = mo.palette_from_frames([blue])
    r, g, b = (int(pal["accent"][i:i + 2], 16) for i in (1, 3, 5))
    assert b > r and b > g                                             # accentul e albastru
    dr, dg, db = (int(pal["dark"][i:i + 2], 16) for i in (1, 3, 5))
    assert max(dr, dg, db) < 40                                        # fundalul: aceeași nuanță, foarte închisă


@needs_chrome
def test_frames_have_alpha_and_text_animates(tmp_path):
    style = mo.resolve_style("iman", {"accent": "#E8B04B"})
    d = mo.render_frames("headline", {"text": "Patruzeci de clienți", "highlight": ["patruzeci"], "shade": False}, style,
                         320, 568, 10, 2.0, tmp_path / "h")
    import cv2

    frames = sorted(d.glob("*.png"))
    assert len(frames) == 20 and (d / ".done").exists()
    first = cv2.imread(str(frames[0]), cv2.IMREAD_UNCHANGED)
    mid = cv2.imread(str(frames[10]), cv2.IMREAD_UNCHANGED)
    assert first.shape[2] == 4                                         # PNG cu transparență
    assert mid[..., 3].mean() > first[..., 3].mean() + 3               # textul a apărut (din blur)
    assert (mid[..., 3] == 0).mean() > 0.3                             # restul cadrului rămâne transparent
    again = mo.render_frames("headline", {"text": "x"}, style, 320, 568, 10, 2.0, tmp_path / "h")
    assert again == d and len(list(d.glob("*.png"))) == 20             # cache: nu se re-randează


@needs_chrome
def test_param_text_is_never_html(tmp_path):
    style = mo.resolve_style("iman")
    png = mo.still("headline", {"text": "<img src=x onerror=alert(1)> salut"}, style, 320, 568, 2.0, 1.5)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"                              # se randează ca text, nu ca element


@needs_chrome
def test_motion_block_in_render(vhome, talking_video):
    p = Project("mo")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 4)
    p.motion_style_set("iman", "#E8B04B")
    out = p.motion_add("stat", 1.0, 3.5, {"value": 40, "label": "clienți"})
    assert "m0" in out and len(p.tl.motion) == 1
    prev = p.motion_preview("m0")
    assert prev.endswith(".png")
    base = Project("mo_base")
    base.add_asset(talking_video)
    base.add_clip("a0", 0, 4)
    with_mo = grab_frame(p.render(preview=True)["path"], 2.5, 960, 540, width=320).astype(int)
    without = grab_frame(base.render(preview=True)["path"], 2.5, 960, 540, width=320).astype(int)
    assert np.abs(with_mo - without).mean() > 4                        # blocul se vede în cadru
    early_a = grab_frame(p.render(preview=True)["path"], 0.4, 960, 540, width=320).astype(int)
    early_b = grab_frame(base.render(preview=True)["path"], 0.4, 960, 540, width=320).astype(int)
    assert np.abs(early_a - early_b).mean() < 2                        # și doar în intervalul lui
    # tăietura de dinainte mută blocul (ripple), ca la grafice
    p.remove_range(0.0, 0.5)
    assert abs(p.tl.motion[0].start - 0.5) < 0.05
