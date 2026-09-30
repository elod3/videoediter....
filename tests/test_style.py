import numpy as np
import pytest

from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.style import Adjust, ColorStats, color_stats, lab_to_rgb, rgb_to_lab, rhythm_from_cuts, write_lut


def make(path, vf, dur=4, src="testsrc2"):
    run(["-y", "-f", "lavfi", "-i", f"{src}=size=640x360:rate=25:duration={dur}", "-f", "lavfi", "-i",
         f"sine=f=300:d={dur}", "-vf", vf, "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)])
    return str(path)


@pytest.fixture(scope="module")
def clips(tmp_path_factory):
    d = tmp_path_factory.mktemp("style")
    dull = make(d / "dull.mp4", "eq=saturation=0.55:brightness=-0.06:contrast=0.85")
    warm = make(d / "warm.mp4", "colorbalance=rs=.25:gs=.05:bs=-.3:rm=.15:bm=-.2,eq=contrast=1.25:saturation=1.2")
    # referință cu tăieturi dure la 1, 2, 2.5 și 3 s (shot-uri cu conținut diferit)
    segs = [("testsrc2", 1), ("mandelbrot", 1), ("color=c=orange", .5), ("smptebars", .5), ("rgbtestsrc", 2)]
    args, pads = ["-y"], ""
    for i, (src, dur) in enumerate(segs):
        opt = "s=640x360:r=25" if src.startswith("color") else "size=640x360:rate=25"
        args += ["-f", "lavfi", "-t", str(dur), "-i", f"{src}{':' if '=' in src else '='}{opt}"]
        pads += f"[{i}:v]setsar=1,format=yuv420p[v{i}];"
    cuts = str(d / "cuts.mp4")
    run([*args, "-filter_complex", pads + "".join(f"[v{i}]" for i in range(len(segs))) + f"concat=n={len(segs)}:v=1[v]",
         "-map", "[v]", "-c:v", "libx264", "-preset", "ultrafast", cuts])
    return {"dull": dull, "warm": warm, "cuts": cuts}


def dist(a: ColorStats, b: ColorStats) -> float:
    return float(np.linalg.norm(np.array(a.mean) - np.array(b.mean)) + np.linalg.norm(np.array(a.std) - np.array(b.std)))


def test_lab_roundtrip():
    rgb = np.random.default_rng(0).random((500, 3))
    assert np.abs(lab_to_rgb(rgb_to_lab(rgb)) - rgb).max() < 1e-6
    assert np.allclose(rgb_to_lab(np.array([[1.0, 1.0, 1.0]]))[0], [100, 0, 0], atol=0.05)


def test_identity_lut_and_presets(tmp_path):
    lut = write_lut(tmp_path / "id.cube", size=9)
    rows = [list(map(float, row.split())) for row in lut.read_text().splitlines()[4:] if row]
    grid = np.linspace(0, 1, 9)
    assert len(rows) == 729 and np.allclose(rows[1], [grid[1], 0, 0], atol=1e-4)  # R variază primul
    assert np.allclose(np.array(rows), np.array([[r, g, b] for b in grid for g in grid for r in grid]), atol=1e-4)
    bw = write_lut(tmp_path / "bw.cube", adj=Adjust(saturation=0), size=5)
    vals = np.array([list(map(float, row.split())) for row in bw.read_text().splitlines()[4:] if row])
    assert np.abs(vals - vals.mean(1, keepdims=True)).max() < 0.02  # gri


def test_color_match_moves_render_toward_reference(vhome, clips):
    p = Project("grade")
    p.add_asset(clips["dull"])
    p.add_asset(clips["warm"])
    p.set_role("a1", "reference")
    assert "REFERINȚĂ" in p.list_assets()
    p.add_clip("a0", 0, 4)
    before = p.render(preview=True, name="before")["path"]
    msg = p.color_match()
    assert "a0" in msg and "a1" not in msg.split("pe ")[1].split(" (")[0]
    after = p.render(preview=True, name="after")["path"]
    info = probe(after)
    ref = ColorStats(**p._color_stats("a1"))
    s_before = color_stats(before, 4, info.width, info.height)
    s_after = color_stats(after, 4, info.width, info.height)
    assert dist(s_after, ref) < 0.5 * dist(s_before, ref), (dist(s_before, ref), dist(s_after, ref))
    # reglaj manual peste potrivire + undo + reset
    p.color_grade("a0", preset="rece")
    assert p.tl.grades["a0"].preset == "rece" and p.tl.grades["a0"].reference == "a1"
    p.undo()
    assert p.tl.grades["a0"].preset is None
    p.color_reset()
    assert p.tl.grades == {}


def test_reference_profile_and_compare(vhome, clips):
    p = Project("ref")
    p.add_asset(clips["dull"])
    p.add_asset(clips["warm"])
    p.set_role("a1", "reference")
    s = p.style_summary("a1")
    assert "tăieturi/min" in s and "LUFS" in s and "saturație" in s
    p.add_clip("a0", 0, 4)
    p.render(preview=True)
    cmp = p.style_compare()
    assert any("color_match" in t for t in cmp["tips"]), cmp
    p.color_match(strength=1.0)
    p.render(preview=True)
    assert not any("culoarea diferă" in t for t in p.style_compare()["tips"])


def test_reference_rhythm_detected_from_video(vhome, clips):
    p = Project("rh")
    p.add_asset(clips["cuts"])
    r = p.style_profile("a0")["rhythm"]
    assert r["cuts"] == 4 and r["hook_cuts_3s"] == 3, r  # tăieturi reale la 1, 2, 2.5, 3 s


def test_rhythm_from_cuts():
    r = rhythm_from_cuts([1, 2, 2.5, 3], 5)
    assert r.cuts == 4 and r.cuts_per_min == 48 and r.hook_cuts_3s == 3 and r.shot_median == 1.0
