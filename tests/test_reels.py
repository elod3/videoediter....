"""Unelte de reel: blocurile noi, blocuri în spatele persoanei (cu strat de prim-plan), fundal de studio și persoana
mutată, tranziții de agenție, montaj pe beat cu tipar și pulsuri pe beat."""
import numpy as np
import pytest

from drums import drum_track
from vedit import motion as mo
from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame


def _has_chrome() -> bool:
    try:
        return bool(mo.engine.chrome_bin())
    except mo.MotionError:
        return False


needs_chrome = pytest.mark.skipif(not _has_chrome(), reason="fără Chromium")


def frame(path, t, width=320):
    info = probe(path)
    return grab_frame(path, t, info.width, info.height, width=width).astype(int)


def test_new_blocks_validate():
    with pytest.raises(ValueError, match="un singur cuvânt"):
        mo.validate("stack_title", {"word": "nemaipomenitdelung"}, 2, {})
    with pytest.raises(ValueError, match="maxim 9"):
        mo.validate("orbit_words", {"text": "unu doi trei patru cinci șase șapte opt nouă zece"}, 3, {})
    with pytest.raises(ValueError, match="times"):
        mo.validate("orbit_words", {"text": "stop buying", "times": [0, 9]}, 2, {})
    with pytest.raises(ValueError, match="color"):
        mo.validate("pixel_wipe", {"color": "roșu"}, 0.5, {})
    with pytest.raises(ValueError, match="imagine necunoscută"):
        mo.validate("float_cards", {}, 2, {"card1": "a1", "card9": "a2"})
    with pytest.raises(ValueError, match="card1"):
        mo.validate("float_cards", {}, 2, {})
    assert mo.validate("pixel_wipe", {}, 0.4, {}) == []          # tranzițiile scurte sunt permise
    assert mo.validate("day_counter", {"to": 3, "label": "zile"}, 2, {}) == []
    assert "reel" in mo.styles_list()


def test_photo_keeps_original_for_image_blocks(vhome, tmp_path):
    import cv2

    img = tmp_path / "card.jpg"
    cv2.imwrite(str(img), np.full((200, 160, 3), 90, np.uint8))
    p = Project("poze")
    p.add_asset(str(img), "a0")
    assert p.s.assets["a0"].path.endswith(".still.mp4")
    assert mo.image_file(p.s.assets["a0"].path).endswith("card.jpg")   # originalul a rămas lângă clip


@needs_chrome
@pytest.mark.parametrize("block,params,images", [
    ("stack_title", {"top": "Fă scripturi", "word": "MAI BUNE", "accent": "cu formula asta", "reveal": "pixel"}, {}),
    ("orbit_words", {"text": "și algoritmul uită de tine", "emphasis": ["uită"]}, {}),
    ("day_counter", {"from": 1, "to": 3, "label": "zile", "title": "Vin vizualizări"}, {}),
    ("speed_lines", {"tone": "light"}, {}),
    ("pixel_wipe", {"mode": "burst"}, {}),
    ("bubble", {"text": "Sfatul ăsta îți schimbă viața"}, {}),
    ("float_cards", {"labels": ["Înainte", "După"]}, {"card1": "x", "card2": "x"}),
])
def test_new_blocks_draw(tmp_path, block, params, images):
    import cv2

    if images:
        im = tmp_path / "x.png"
        cv2.imwrite(str(im), np.dstack([np.full((240, 200), c, np.uint8) for c in (40, 120, 220)]))
        images = {k: str(im) for k in images}
    style = mo.resolve_style("reel", {"accent": "#E0262B"})
    params = {**params, "_scene": {"face": [0.42, 0.3, 0.16, 0.09], "luma": [0.2, 0.2, 0.2], "tone": "dark"}}
    png = mo.still(block, params, style, 270, 480, 2.0, 1.0 if block != "pixel_wipe" else 0.4, images)
    a = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    assert a.shape[2] == 4 and (a[..., 3] > 0).mean() > 0.005, block   # se desenează ceva


@needs_chrome
def test_block_behind_person_with_front_layer(vhome, seg_assets, monkeypatch):
    """stack_title cu behind: cuvântul uriaș dispare pe corpul persoanei, scrisul de mână (.fg) rămâne peste ea."""
    import cv2

    monkeypatch.setenv("VEDIT_SEG_MODEL", str(seg_assets / "modnet.onnx"))
    p = Project("reel_behind")
    p.add_asset(str(seg_assets / "messi.jpg"), "a0")
    p.add_clip("a0", 0, 2.0)
    with p.edit() as tl:
        tl.width, tl.height = 548, 342
    p.motion_style_set("reel", "#FF00FF")
    ref = cv2.resize(cv2.imread(str(seg_assets / "messi.jpg")), (548, 342))[..., ::-1].astype(int)
    params = {"word": "GOOOL", "tone": "accent", "position": "center", "size": 0.95, "reveal": "slide"}
    p.motion_add("stack_title", 0.1, 1.9, params)
    front = frame(p.render(preview=True)["path"], 1.2, width=548)
    p.undo()
    out = p.motion_add("stack_title", 0.1, 1.9, params, behind=True)
    assert "în spate" in out and "a0" in p.tl.mattes and p.tl.motion[0].scene.get("luma")
    back = frame(p.render(preview=True)["path"], 1.2, width=548)
    magenta = lambda f: (f[..., 0] > 200) & (f[..., 1] < 80) & (f[..., 2] > 200)   # noqa: E731
    torso = (slice(130, 200), slice(215, 265))
    assert magenta(front)[torso].mean() > magenta(back)[torso].mean() * 3 + 0.01      # pe corp, cuvântul e în spate
    assert magenta(back).sum() > 300                                                   # și se vede în rest
    assert np.abs(back[torso] - ref[torso]).mean() < np.abs(front[torso] - ref[torso]).mean()
    assert "m0" in p.tl.view() and "MOT" in p.tl.view()


def test_studio_background_and_moved_person(vhome, seg_assets, monkeypatch):
    monkeypatch.setenv("VEDIT_SEG_MODEL", str(seg_assets / "modnet.onnx"))
    p = Project("studio")
    p.add_asset(str(seg_assets / "messi.jpg"), "a0")
    p.add_clip("a0", 0, 1.5)
    with p.edit() as tl:
        tl.width, tl.height = 548, 342
    with pytest.raises(ValueError, match="fundal nou"):
        p.background("c0", "blur", scale=0.5)
    p.background("c0", "studio", "#5E6B3A")
    bg = p.tl.clips[0].bg
    assert bg.mode == "studio" and 0.5 < bg.foot <= 1.0
    full = frame(p.render(preview=True)["path"], 0.7, width=548)
    corner = full[5:40, 400:540]
    assert abs(corner[..., 1].mean() - corner[..., 0].mean()) > 8 and corner.std() < 25   # publicul a dispărut
    p.background("c0", "studio", "#5E6B3A", scale=0.5, x=0.75, y=0.95, move=0.3)
    assert "persoana=50%" in p.tl.view()
    small = frame(p.render(preview=True)["path"], 1.0, width=548)
    torso = (slice(130, 200), slice(215, 265))                   # tricoul, în locul vechi: acum e fundal
    assert small[torso].std() < full[torso].std() * 0.7
    right = small[200:330, 330:530]                               # persoana a ajuns jos-dreapta
    assert right.std() > corner.std() + 5
    p.background("c0", "silhouette")
    sil = frame(p.render(preview=True)["path"], 0.7, width=548)
    assert (sil[5:40, 400:540] > 230).all(axis=2).mean() > 0.9 and (sil[torso] < 40).all(axis=2).mean() > 0.6


def test_agency_transitions_render(vhome, talking_video):
    p = Project("tr")
    p.add_asset(talking_video, "a0")
    p.add_clip("a0", 0, 2)
    p.add_clip("a0", 3, 5)
    p.add_clip("a0", 5.5, 7.5)
    p.transition_set("c1", "invertwhip", 0.2)
    p.transition_set("c2", "chromawhip", 0.25)
    out = p.render(preview=True)["path"]
    assert abs(probe(out).duration - (6 - 0.45)) < 0.12
    # pe mijlocul primei tranziții e un cadru negativ: e inversul aceluiași whip fără negativ
    mid = 1.8 + 0.1
    p.transition_set("c1", "whipleft", 0.2)
    plain = frame(p.render(preview=True, name="plain")["path"], mid)
    neg = frame(out, mid)
    assert np.abs(neg - (255 - plain)).mean() < 20 < np.abs(neg - plain).mean()


@pytest.fixture(scope="module")
def beat_media(tmp_path_factory):
    d = tmp_path_factory.mktemp("bm")
    drum_track(str(d / "d.wav"), 120, dur=12)
    music = str(d / "music.m4a")
    run(["-y", "-i", str(d / "d.wav"), "-c:a", "aac", music])
    src = str(d / "src.mp4")
    run(["-y", "-f", "lavfi", "-t", "10", "-i", "testsrc2=size=640x360:rate=25", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", src])
    return {"music": music, "src": src}


def test_beat_montage_pattern_lead_and_pulses(vhome, beat_media):
    p = Project("pattern")
    p.add_asset(beat_media["src"], "a0")
    p.add_asset(beat_media["music"], "music")
    with pytest.raises(ValueError, match="pattern"):
        p.beat_montage("music", pattern="2,x")
    msg = p.beat_montage("music", pattern="2,1,1", lead=0.03, max_duration=8)
    assert "tipar 2,1,1" in msg
    beats = p.beats("music").beats
    durs = [c.duration for c in p.tl.clips]
    period = 60 / 120
    want = [2, 1, 1] * 10
    assert all(abs(d - w * period) < 0.04 for d, w in zip(durs, want)), durs
    assert abs(p.tl.music.src_in - (beats[0] - 0.03)) < 0.005              # beat-ul vine la 0.03 s după tăietură
    with pytest.raises(ValueError, match="kind"):
        p.beat_fx("zoomz")
    out = p.beat_fx("punch", 1.0, 4.0)
    assert "p0" in out and "BEAT" in p.tl.view()
    with pytest.raises(ValueError, match="deja"):
        p.beat_fx("punch", 2.0, 3.0)
    p.beat_fx("rgb", 4.0, -1, every=2)
    p.beat_fx("flash", 0.0, 1.0)
    path = p.render(preview=True)["path"]
    assert abs(probe(path).duration - p.tl.duration) < 0.1
    first = p.tl.beat_fx[2].offset                                          # flash: mai luminos chiar pe beat
    on, after = frame(path, first + 0.01).mean(), frame(path, first + 0.2).mean()
    assert on > after + 3, (on, after)
    p.beat_fx("flash", off=True)
    assert len(p.tl.beat_fx) == 0
