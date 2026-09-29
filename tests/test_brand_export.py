import re
import struct
import tempfile
import zlib

import numpy as np
import pytest

from vedit import guard, mcp_server as m
from vedit.captions import ass_color, to_ass, to_subs
from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.render import build_command, with_bookends
from vedit.style import grab_frame
from vedit.timeline import Caption


def write_png(path, w, h, pixel):
    """PNG RGBA minimal (fără dependențe). pixel(x, y) -> (r, g, b, a)."""
    raw = b"".join(b"\x00" + b"".join(bytes(pixel(x, y)) for x in range(w)) for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return str(path)


def color_clip(path, color, dur):
    run(["-y", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=25:d={dur}", "-f", "lavfi", "-i",
         f"sine=f=330:d={dur}", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(path)])
    return str(path)


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("brand")
    blurred = d / "blur.mp4"  # clar DOAR în [6, 7.5]
    run(["-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=9",
         "-vf", "boxblur=8:enable='not(between(t,6,7.5))'", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", str(blurred)])
    return {
        "main": color_clip(d / "gray.mp4", "0x404040", 3),
        "intro": color_clip(d / "red.mp4", "red", 1.5),
        "outro": color_clip(d / "blue.mp4", "blue", 1),
        "blur": str(blurred),
        # jumătatea stângă transparentă, dreapta verde opac
        "logo": write_png(d / "logo.png", 100, 50, lambda x, y: (0, 255, 0, 0 if x < 50 else 255)),
        "dir": d,
    }


def frame(path, t, width=480):
    info = probe(path)
    return grab_frame(path, t, info.width, info.height, width=width).astype(int)


def white(fr):
    return int(((fr > 200).all(axis=2)).sum())


def test_logo_corner_alpha_and_opacity(vhome, media):
    p = Project("logo")
    p.add_asset(media["main"])
    p.add_clip("a0", 0, 3)
    view = p.brand_logo(media["logo"], position="tr", scale=0.2, opacity=1.0)
    assert "logo tr 20%" in view and p.tl.brand.logo.path.startswith(str(p.dir / "brand"))
    out = p.render(preview=True)["path"]
    fr = frame(out, 1.0)          # 480x270; logo 96x48 la 11 px de colțul dreapta-sus
    left, right = fr[16:50, 378:412].mean((0, 1)), fr[16:50, 428:462].mean((0, 1))
    assert np.abs(left - 64).max() < 12, left                       # partea transparentă: fundal gri
    assert right[1] > 200 and right[0] < 60, right                   # partea opacă: verde
    assert np.abs(fr[200:260, 10:100] - 64).max() < 12              # colțul stânga-jos neatins
    p.brand_logo(media["logo"], position="bl", scale=0.2, opacity=0.5)
    fr = frame(p.render(preview=True)["path"], 1.0)
    half = fr[-50:-16, 68:102].mean((0, 1))                         # acum stânga-jos, 50% opac
    assert 130 < half[1] < 190 and half[0] < 70, half
    assert np.abs(fr[16:50, 428:462] - 64).max() < 12
    p.undo()
    assert p.tl.brand.logo.position == "tr"
    p.brand_clear("logo")
    assert p.tl.brand.logo is None
    with pytest.raises(ValueError):
        p.brand_logo(media["main"])                                 # nu e imagine


def test_caption_brand_colors_and_custom_font(vhome, media, tmp_path):
    TTFont = pytest.importorskip("fontTools.ttLib").TTFont
    from vedit.captions import FONTS_DIR

    font = TTFont(str(FONTS_DIR / "Archivo-Regular.ttf"))
    for rec in font["name"].names:  # un font „nou” al clientului
        if rec.nameID in (1, 4, 6, 16):
            rec.string = {1: "VeditBrandTest", 4: "VeditBrandTest Regular", 6: "VeditBrandTest-Regular",
                          16: "VeditBrandTest"}[rec.nameID]
    font.save(str(tmp_path / "client.ttf"))

    p = Project("capbrand")
    p.add_asset(media["main"])
    p.add_clip("a0", 0, 3)
    with p.edit() as tl:
        tl.captions = [Caption(start=0.2, end=1.5, text="Salut lume", word_durs=[0.6, 0.7])]
    default_ass = to_ass(p.tl)
    assert "Style: Cap,Archivo Black,48,&H00FFFFFF,&H00FFFFFF,&H00000000" in default_ass  # fără brand: neschimbat

    view = p.brand_captions(primary="#12ab34", highlight="#FFD400", outline="#000080",
                            font_path=str(tmp_path / "client.ttf"))
    assert "font VeditBrandTest" in view and p.tl.caption_font == "VeditBrandTest"
    assert ass_color("#12AB34") == "&H0034AB12" and ass_color("#12AB34", inline=True) == "&H34AB12&"
    ass = to_ass(p.tl)
    assert "Style: Cap,VeditBrandTest,48,&H0034AB12,&H0034AB12,&H00800000" in ass
    with p.edit() as tl:
        tl.caption_style = "karaoke"
    assert ",&H0000D4FF,&H0034AB12,&H00800000," in to_ass(p.tl)   # karaoke: highlight = cuvântul curent

    wd = tempfile.mkdtemp()
    args, _ = build_command(p.tl, p.s.assets, str(tmp_path / "o.mp4"), preview=True, workdir=wd)
    log = run(["-loglevel", "verbose", *args], cwd=wd).stderr
    sel = [ln for ln in log.splitlines() if "fontselect" in ln]
    assert sel and all("VeditBrandTest" in ln.split("->")[1] for ln in sel), sel  # libass a ales fontul clientului
    with pytest.raises(ValueError):
        p.brand_captions(primary="galben")
    p.brand_clear("captions")
    assert p.tl.caption_font is None and to_ass(p.tl).count("&H0034AB12") == 0


def test_intro_outro_durations_and_caption_timing(vhome, media):
    p = Project("bookends")
    for k in ("main", "intro", "outro"):
        p.add_asset(media[k], k)
    p.add_clip("main", 0, 3)
    with p.edit() as tl:
        tl.captions = [Caption(start=0.5, end=1.5, text="SALUT")]
    p.brand_logo(media["logo"], scale=0.2, opacity=1.0)
    p.set_music("outro", -18, duck=True)  # muzica stă doar pe montaj (adelay cu durata intro-ului)
    msg = p.brand_intro_outro(intro="intro", outro="outro")
    assert "intro intro (1.50s)" in msg and p.tl.output_duration == 5.5 and p.tl.duration == 3.0
    assert "[BRAND" in p.list_assets()

    tl2, off = with_bookends(p.tl, p.s.assets)
    assert off == 1.5 and [c.id for c in tl2.clips] == ["_intro", "c0", "_outro"] and tl2.duration == 5.5
    assert "Dialogue: 0,0:00:02.00,0:00:03.00,Cap" in to_ass(tl2)

    out = p.render(preview=True)
    assert out["duration"] == 5.5 and abs(probe(out["path"]).duration - 5.5) < 0.15
    at = lambda t: frame(out["path"], t)  # noqa: E731
    intro, cap, plain, outro = at(1.0), at(2.5), at(3.8), at(5.2)
    assert intro[..., 0].mean() > 200 and white(intro) == 0          # intro roșu: fără subtitrare, fără logo
    assert intro[16:50, 428:462, 1].mean() < 60
    assert white(cap) > 30 and white(plain) == 0                     # subtitrarea apare decalată cu intro-ul
    assert cap[16:50, 428:462, 1].mean() > 200                       # logo pe montaj
    assert outro[..., 2].mean() > 200 and outro[16:50, 428:462, 1].mean() < 60
    srt = p.captions_export("srt")
    assert "00:00:02,000 --> 00:00:03,000" in open(srt["path"], encoding="utf-8").read()
    final = p.render(preview=False)
    qa = p.qa(final["path"])
    assert not any("durata" in i for i in qa["issues"]), qa
    p.brand_clear("intro_outro")
    assert p.tl.output_duration == 3.0 and "[BRAND" not in p.list_assets()


def parse_srt(text):
    blocks = [b for b in text.strip().split("\n\n")]
    out = []
    for i, b in enumerate(blocks, 1):
        idx, times, *body = b.split("\n")
        assert int(idx) == i and len(body) == 1
        mm = re.fullmatch(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})", times)
        assert mm, times
        g = [int(x) for x in mm.groups()]
        out.append((g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000, g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000, body[0]))
    return out


def test_srt_vtt_roundtrip_and_api(vhome, media):
    p = Project("subs")
    p.add_asset(media["main"])
    p.add_clip("a0", 0, 3)
    with pytest.raises(ValueError):
        p.captions_export("srt")
    caps = [Caption(start=0.5, end=1.234, text="Ăsta e <b>testul</b> {\\an8}șți"),
            Caption(start=61.5, end=3661.001, text="a --> b\nrând & <x"),
            Caption(start=4000, end=4000.01, text="prea scurt")]
    with p.edit() as tl:
        tl.captions = caps
    srt = open(p.captions_export("srt")["path"], encoding="utf-8").read()
    got = parse_srt(srt)
    assert [x[2] for x in got] == ["Ăsta e testul șți", "a -> b rând & <x"]
    assert [x[:2] for x in got] == [pytest.approx((0.5, 1.234)), pytest.approx((61.5, 3661.001))]
    vtt = open(p.captions_export(".VTT")["path"], encoding="utf-8").read()
    assert vtt.startswith("WEBVTT\n\n")
    cues = re.findall(r"(\d\d:\d\d:\d\d\.\d{3}) --> (\d\d:\d\d:\d\d\.\d{3})\n(.+)\n", vtt)
    assert cues == [("00:00:00.500", "00:00:01.234", "Ăsta e testul șți"),
                    ("00:01:01.500", "01:01:01.001", "a -&gt; b rând &amp; &lt;x")]
    assert to_subs(p.tl, "srt", offset=2).startswith("1\n00:00:02,500")

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vedit.api.app import create_app
    from vedit.api.runners import ScriptedRunner

    with TestClient(create_app(ScriptedRunner())) as c:
        r = c.get("/api/projects/subs/captions.vtt")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/vtt") and r.text == vtt
        assert c.get("/api/projects/subs/captions.srt").text == srt
        assert c.get("/api/projects/subs/captions.exe").status_code == 404
        assert c.get("/api/projects/nope/captions.srt").status_code == 404
        assert c.get("/api/projects/subs/thumbnail.png").status_code == 404


def test_export_preset_sets_format_and_renders(vhome, media, monkeypatch):
    from vedit import brand

    p = Project("preset")
    p.add_asset(media["main"])
    p.add_clip("a0", 0, 2)
    res = p.export_preset("tiktok")
    assert res["format"] == "9:16 1080x1920" and (p.tl.width, p.tl.height) == (1080, 1920)
    assert res["path"].endswith("renders/tiktok.mp4") and res["lufs"] == -14.0 and res["fps"] == 30
    info = probe(res["path"])
    assert (info.width, info.height) == (1080, 1920) and "qa" in res
    assert any("auto_reframe" in w for w in res["warnings"])        # formatul s-a schimbat din 16:9
    monkeypatch.setitem(brand.PLATFORMS, "x", {**brand.PLATFORMS["x"], "max": 1})
    res = p.export_preset("x")
    assert res["format"].startswith("16:9") and res["path"].endswith("x.mp4")
    assert any("verifică limita curentă" in w for w in res["warnings"]), res["warnings"]
    with pytest.raises(ValueError):
        p.export_preset("myspace")


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


def test_thumbnail_picks_sharp_frame_and_title(vhome, media):
    p = Project("thumb")
    p.add_asset(media["blur"])
    p.add_clip("a0", 0, 9)
    res = p.thumbnail_export()
    assert 6.0 <= res["at"] <= 7.5, res                             # singurul segment clar
    assert png_size(res["image"]) == (1920, 1080)
    plain = grab_frame(res["image"], 0, 1920, 1080, width=480).astype(int)
    res2 = p.thumbnail_export(at=res["at"], title="Cel mai bun titlu")
    assert res2["title"] and png_size(res2["image"]) == (1920, 1080)
    titled = grab_frame(res2["image"], 0, 1920, 1080, width=480).astype(int)
    assert np.abs(titled[90:140] - plain[90:140]).mean() > 10       # titlul e desenat pe mijloc
    assert np.abs(titled[240:] - plain[240:]).mean() < 3             # restul cadrului neatins
    p.set_format("9:16")
    assert png_size(p.thumbnail_export(at=1)["image"]) == (1080, 1920)


def test_brand_paths_refused_under_project_lock(vhome, media, monkeypatch, tmp_path):
    guard.reset_budgets()
    from vedit.project import home

    Project("lk")
    outside = write_png(tmp_path / "evil.png", 10, 10, lambda x, y: (255, 0, 0, 255))
    monkeypatch.setenv("VEDIT_PROJECT_LOCK", "lk")
    root = home() / "lk"
    link = root / "link.png"
    link.symlink_to(outside)
    for path in (outside, str(root / ".." / ".." / "evil.png"), str(link), "/etc/passwd"):
        assert m.brand_logo("lk", path).startswith("REFUZAT"), path
    assert m.brand_captions("lk", font_path="/etc/passwd").startswith("REFUZAT")
    assert m.brand_captions("lk", font_path=str(root / "../../x.ttf")).startswith("REFUZAT")
    assert m.brand_logo("altul", outside).startswith("REFUZAT")
    assert Project("lk").tl.brand.logo is None
    inside = write_png(root / "logo.png", 10, 10, lambda x, y: (255, 0, 0, 255))
    assert "logo tr" in m.brand_logo("lk", inside)
    # timeline modificat pe altă cale (ex. PUT din API) cu logo din afara proiectului => render refuzat
    p = Project("lk")
    p.add_asset(media["main"])
    p.add_clip("a0", 0, 1)
    with p.edit() as tl:
        tl.brand.logo.path = outside
    with pytest.raises(PermissionError):
        p.render()


def test_brand_and_export_routes(vhome, media, monkeypatch):
    """Brand kit și exportul pe platformă din API (ce folosește editorul web)."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from test_api import upload, wait_job

    from vedit.api.app import create_app
    from vedit.api.runners import ScriptedRunner

    with TestClient(create_app(ScriptedRunner())) as c:
        assert {x["id"] for x in c.get("/api/platforms").json()} >= {"tiktok", "youtube", "reels"}
        c.post("/api/projects", json={"name": "b"})
        upload(c, "b", media["main"])
        Project("b").add_clip("a0", 0, 2)
        assert c.get("/api/projects/b/brand/logo").status_code == 404
        with open(media["logo"], "rb") as f:
            r = c.post("/api/projects/b/brand/logo", files={"file": ("logo.png", f, "image/png")},
                       data={"position": "bl", "scale": "0.2"})
        assert r.status_code == 200, r.text
        assert r.json()["logo"]["position"] == "bl" and "path" not in r.json()["logo"]
        assert c.get("/api/projects/b/brand/logo").headers["content-type"] == "image/png"
        assert c.put("/api/projects/b/brand/logo", json={"position": "tr"}).json()["logo"]["position"] == "tr"
        bad = c.post("/api/projects/b/brand/logo", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
        assert bad.status_code == 400
        r = c.put("/api/projects/b/brand/captions", json={"primary": "#ffcc00", "highlight": "00ff88"})
        assert r.status_code == 200 and r.json()["primary"].lower() == "#ffcc00"
        assert c.put("/api/projects/b/brand/captions", json={"primary": "galben"}).status_code == 400
        assert c.post("/api/projects/b/brand/clear", json={"part": "logo"}).json()["logo"] is None

        assert c.post("/api/projects/b/export", json={"platform": "myspace"}).status_code == 400
        j = wait_job(c, c.post("/api/projects/b/export", json={"platform": "reels"}).json()["id"])
        assert j["status"] == "done", j
        assert j["kind"] == "export" and j["result"].startswith("reels: 9:16")
        assert (Project("b").dir / "renders" / "reels.mp4").exists()
        t = c.post("/api/projects/b/thumbnail", json={"title": "Test"})
        assert t.status_code == 200 and c.get(t.json()["url"]).headers["content-type"] == "image/png"
