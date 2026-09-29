"""Motion graphics: ASS randat real cu libass (ffmpeg), verificat pe pixeli."""
import tempfile
from pathlib import Path

import numpy as np
import pytest

from vedit.captions import fonts_dir
from vedit.ff import run
from vedit.graphics import GRAPHICS, KINDS_HELP, graphics_ass, validate
from vedit.timeline import Brand, Graphic, Timeline

W, H = 640, 360
BG = 0x20


def tl_with(*graphics, **kw) -> Timeline:
    return Timeline(width=W, height=H, graphics=list(graphics), **kw)


def frames(tl: Timeline, times: list[float], dur: float = 4.0) -> list[np.ndarray]:
    """Randează documentul ASS peste un fundal gri închis și întoarce cadrele RGB (H, W, 3) la momentele date."""
    out = []
    with tempfile.TemporaryDirectory() as wd:
        Path(wd, "g.ass").write_text(graphics_ass(tl, W, H), encoding="utf-8")
        fd = fonts_dir(tl, wd)
        for i, t in enumerate(times):
            run(["-y", "-f", "lavfi", "-i", f"color=c=0x202020:s={W}x{H}:d={dur}:r=25",
                 "-vf", f"ass=filename=g.ass:fontsdir={fd}", "-ss", f"{t:.3f}", "-frames:v", "1",
                 "-f", "rawvideo", "-pix_fmt", "rgb24", f"f{i}.raw"], cwd=wd)
            out.append(np.fromfile(Path(wd, f"f{i}.raw"), np.uint8).reshape(H, W, 3).astype(int))
    return out


def accent(fr):  # #C8FF3D (lime), accentul implicit
    return (fr[..., 0] > 150) & (fr[..., 1] > 200) & (fr[..., 2] < 130)


def blank(fr):
    return np.abs(fr - BG).max() < 6


def test_empty_graphics_gives_empty_doc():
    assert graphics_ass(Timeline(), 1920, 1080) == ""
    assert set(KINDS_HELP) == set(GRAPHICS)


def test_every_kind_renders_and_scales():
    gs = [Graphic(id=f"g{i}", kind=k, start=0, end=2, text="Salut lume", items=["unu", "doi"],
                  value_from=0, value_to=10) for i, k in enumerate(GRAPHICS)]
    for g in gs:
        validate(g)
    doc = graphics_ass(tl_with(*gs), 960, 540)
    assert "PlayResX: 960" in doc and "PlayResY: 540" in doc and "ScaledBorderAndShadow: yes" in doc
    assert doc.count("Dialogue:") > len(GRAPHICS)
    fr = frames(tl_with(*gs), [1.0], dur=2)[0]
    assert not blank(fr)


def test_lower_third_timing_and_region():
    g = Graphic(id="g1", kind="lower_third", start=0.5, end=2.5, text="Ana Popescu", subtext="Fondator")
    before, mid, after = frames(tl_with(g), [0.2, 1.5, 3.0])
    assert blank(before) and blank(after)
    m = accent(mid)
    assert m[H // 2:, : W // 2].sum() > 200, m.sum()          # bara accent: stânga-jos
    assert m[: H // 2].sum() == 0 and m[:, W // 2:].sum() == 0
    assert (mid[H // 2:, : W // 2] > 200).all(axis=2).sum() > 50  # numele, alb


def test_lower_third_honors_position():
    g = Graphic(id="g1", kind="lower_third", start=0, end=2, text="Ana", position="upper_right")
    m = accent(frames(tl_with(g), [1.0])[0])
    assert m[: H // 2, W // 2:].sum() > 100 and m[H // 2:].sum() == 0


def test_progress_bar_grows():
    g = Graphic(id="p", kind="progress_bar", start=0, end=3)
    f1, f2 = frames(tl_with(g), [0.75, 2.25])
    a1, a2 = accent(f1[:8]).sum(), accent(f2[:8]).sum()
    assert a1 > 0 and 2.4 < a2 / a1 < 3.6, (a1, a2)
    assert accent(f1[8:]).sum() == 0
    cols = np.where(accent(f2[:8]).any(axis=0))[0]
    assert cols.min() == 0 and abs(cols.max() - 0.75 * W) < 0.05 * W
    bottom = frames(tl_with(g.model_copy(update={"position": "bottom"})), [1.5])[0]
    assert accent(bottom[-8:]).sum() > 0 and accent(bottom[:-8]).sum() == 0


def test_counter_animates_then_holds():
    g = Graphic(id="c", kind="counter", start=0, end=3, value_from=0, value_to=12500, suffix="+")
    f1, f2, h1, h2 = frames(tl_with(g), [0.4, 1.2, 2.2, 2.6])
    assert accent(f1).sum() > 100 and accent(h1).sum() > 100
    assert np.abs(f1 - f2).max() > 50                      # numărul se schimbă
    assert np.abs(h1 - h2).max() == 0                      # valoarea finală stă pe loc
    doc = graphics_ass(tl_with(g), W, H)
    assert "12.500+" in doc and doc.count("Dialogue:") > 25


def test_circle_ring_around_point():
    g = Graphic(id="o", kind="circle", start=0, end=3, x=0.5, y=0.5, size=0.2)
    before, fr = frames(tl_with(g.model_copy(update={"start": 0.5})), [0.2, 1.0])
    assert blank(before)
    m = accent(fr)
    ys, xs = np.nonzero(m)
    R = 0.2 * H
    dist = np.hypot(xs - W / 2, ys - H / 2)
    assert len(dist) > 200
    assert dist.min() > 0.75 * R and dist.max() < 1.2 * R, (dist.min(), dist.max(), R)
    assert abs(xs.mean() - W / 2) < 3 and abs(ys.mean() - H / 2) < 3
    assert blank(fr[int(H / 2 - R / 2):int(H / 2 + R / 2), int(W / 2 - R / 2):int(W / 2 + R / 2)])


def test_callout_points_at_target_and_stays_inside():
    g = Graphic(id="k", kind="callout", start=0, end=2, text="Butonul nou e aici", x=0.95, y=0.1)
    fr = frames(tl_with(g), [1.0], dur=2)[0]
    m = accent(fr)
    px, py = int(0.95 * W), int(0.1 * H)
    assert m[py - 4:py + 5, px - 4:px + 5].sum() > 20           # punctul accent pe țintă
    ys, xs = np.nonzero(fr.max(axis=2) < 12)                     # panoul închis al casetei
    assert len(xs) > 1000
    assert xs.min() > 5 and xs.max() < W - 5 and ys.min() > 5 and ys.max() < H - 5  # rămâne în cadru
    assert xs.max() < px                                          # la stânga punctului (nu încape la dreapta)


def test_kinetic_and_list_accumulate():
    k = Graphic(id="k", kind="kinetic", start=0, end=3, text="Asta schimbă totul azi")
    lst = Graphic(id="l", kind="list", start=0, end=3, items=["Unu", "Doi", "Trei"])
    for g in (k, lst):
        a, b, c = [(f > 200).all(axis=2).sum() for f in frames(tl_with(g), [0.3, 1.0, 2.2])]
        assert a < b < c, (g.kind, a, b, c)


def test_title_card_and_cta_visible_then_gone():
    t = Graphic(id="t", kind="title_card", start=0, end=1.5, text="Titlu", subtext="sub")
    c = Graphic(id="c", kind="cta", start=1.5, end=3)
    tl = tl_with(t, c)
    f1, f2, f3 = frames(tl, [0.8, 2.3, 3.5])
    assert (f1 > 200).all(axis=2).sum() > 300 and accent(f1).sum() > 50   # titlu + bara accent
    assert accent(f2)[H // 2:].sum() > 1000                              # pastila accent, jos
    assert blank(f3)
    assert "Urmărește pentru mai mult" in graphics_ass(tl, W, H)


def test_colors_from_graphic_then_brand():
    g = Graphic(id="p", kind="progress_bar", start=0, end=2)
    assert "\\1c&H0000FF&" in graphics_ass(tl_with(g, brand=Brand(highlight="#FF0000")), W, H)
    g2 = g.model_copy(update={"color": "#00FF00"})
    assert "\\1c&H00FF00&" in graphics_ass(tl_with(g2, brand=Brand(highlight="#FF0000")), W, H)
    doc = graphics_ass(tl_with(g, brand=Brand(primary="#112233"), caption_font="Brand Sans"), W, H)
    assert "Style: H,Brand Sans," in doc and "&H00332211" in doc


def test_untrusted_text_cannot_inject_tags():
    evil = "{\\p1}m 0 0 l 640 0 640 360 0 360{\\p0}\\N\nx"
    g = Graphic(id="t", kind="title_card", start=0, end=2, text=evil[:60])
    doc = graphics_ass(tl_with(g), W, H)
    line = next(x for x in doc.splitlines() if x.startswith("Dialogue") and "\\fscx70" in x)
    body = line.split("}", 1)[1]
    assert "{" not in body and "\\" not in body.replace("\\N", "")
    fr = frames(tl_with(g), [1.0], dur=2)[0]
    assert (np.abs(fr - BG).max(axis=2) < 6).mean() > 0.6               # nu s-a desenat un dreptunghi pe tot cadrul


@pytest.mark.parametrize("bad, msg", [
    (dict(kind="counter", value_from=5, value_to=5), "value_from"),
    (dict(kind="list", items=[]), "1-6"),
    (dict(kind="list", items=list("abcdefg")), "1-6"),
    (dict(kind="list", items=["x" * 41]), "40"),
    (dict(kind="title_card", text="x" * 61), "prea lung"),
    (dict(kind="title_card", text=""), "are nevoie de text"),
    (dict(end=0.3), "0.5"),
    (dict(start=2, end=1), "end > start"),
    (dict(x=1.5), "între 0 și 1"),
    (dict(kind="circle", size=0.6), "size"),
    (dict(color="rosu"), "culoare invalidă"),
])
def test_validate_rejects(bad, msg):
    base = dict(id="g", kind="cta", start=0, end=2, text="Hei")
    with pytest.raises(ValueError, match=msg):
        validate(Graphic(**{**base, **bad}))


def test_validate_accepts_good():
    validate(Graphic(id="g", kind="counter", start=1, end=3, value_from=0, value_to=99.5, decimals=1,
                     prefix="$", color="#ffd400"))
    validate(Graphic(id="g", kind="list", start=0, end=4, text="Pași", items=["Unu", "Doi"]))
