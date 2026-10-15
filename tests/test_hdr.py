"""Filmările HDR de pe telefon (HLG, ca iPhone-ul) se convertesc în SDR la randare: altfel ies spălate și gri."""
import numpy as np
import pytest

from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame


@pytest.fixture(scope="module")
def hlg_and_sdr(tmp_path_factory):
    d = tmp_path_factory.mktemp("hdr")
    sdr, hlg = d / "sdr.mp4", d / "hlg.mp4"
    src = ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=2"]
    run(["-y", *src, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(sdr)])
    # aceeași imagine, codată HLG / BT.2020 pe 10 biți, cu etichetele pe care le pune un iPhone
    try:
        run(["-y", *src, "-vf", "zscale=tin=bt709:t=arib-std-b67:pin=bt709:p=bt2020:min=bt709:m=bt2020nc:npl=203,"
             "format=yuv420p10le", "-c:v", "libx264", "-preset", "ultrafast", "-color_trc", "arib-std-b67",
             "-color_primaries", "bt2020", "-colorspace", "bt2020nc", str(hlg)])
    except Exception:
        pytest.skip("ffmpeg fără zscale / libx264 pe 10 biți")
    return str(sdr), str(hlg)


def test_probe_flags_hlg(hlg_and_sdr):
    sdr, hlg = hlg_and_sdr
    assert probe(hlg).hdr and probe(hlg).transfer == "arib-std-b67"
    assert not probe(sdr).hdr
    assert "HDR" in probe(hlg).summary()


def test_hdr_render_matches_sdr_colors(vhome, hlg_and_sdr):
    sdr, hlg = hlg_and_sdr
    out = {}
    for name, path in (("sdr", sdr), ("hlg", hlg)):
        p = Project(f"hdr_{name}")
        p.add_asset(path)
        p.add_clip("a0", 0, 2)
        r = p.render(preview=True)
        out[name] = grab_frame(r["path"], 1.0, 960, 540, width=320).astype(float)
    raw = grab_frame(hlg, 1.0, 640, 360, width=320).astype(float)       # HLG citit fără conversie
    sat = lambda f: (f.max(axis=2) - f.min(axis=2)).mean()               # noqa: E731
    # fără conversie, HLG are contrastul și saturația căzute; după, e aproape de SDR
    assert sat(raw) < sat(out["sdr"]) * 0.85
    assert abs(sat(out["hlg"]) - sat(out["sdr"])) < sat(out["sdr"]) * 0.15   # pattern-ul de test e saturat la maxim
    assert np.abs(out["hlg"].mean(axis=(0, 1)) - out["sdr"].mean(axis=(0, 1))).max() < 25
