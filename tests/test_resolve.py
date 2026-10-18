"""Dus-întors cu DaVinci Resolve prin FCPXML: exportul păstrează montajul, importul îl reface fără să piardă
proprietățile pe care Resolve nu le știe (efecte, încadrare), iar subtitrările urmează tăieturile."""
import os

import pytest

from vedit.project import Project
from vedit.resolve import ImportError_, apply_fcpxml, parse_fcpxml, to_fcpxml
from vedit.timeline import BRoll, Caption, Transition


@pytest.fixture
def proj(vhome, talking_video):
    p = Project("rt")
    p.add_asset(talking_video)
    with p.edit() as tl:
        tl.add_clip("a0", 0, 2)
        c = tl.add_clip("a0", 3.5, 5.5)
        c.speed, c.fx = 2.0, ["bw"]
        c.crop.cx = 0.3
        last = tl.add_clip("a0", 6.5, 8)
        last.transition = Transition(type="fade", duration=0.4)
        last.freeze = 0.5
        tl.broll = [BRoll(id="b1", asset="a0", src_in=1, start=1.5, duration=1)]
    return p


def _layout(tl):
    return [(c.asset, round(c.src_in, 2), round(c.src_out, 2), round(c.speed, 2), round(c.freeze, 2)) for c in tl.clips]


def test_round_trip_keeps_cut_and_properties(proj):
    before = _layout(proj.tl)
    xml = to_fcpxml(proj.tl, proj.s.assets, "rt")
    assert 'name="vedit · rt"' in xml and "file://" in xml and "<timeMap>" in xml
    parsed = parse_fcpxml(xml, proj.s.assets)
    assert parsed["unknown"] == [] and parsed["gaps"] == 0
    with proj.edit() as tl:
        apply_fcpxml(tl, parsed, proj.s.assets)
    assert _layout(proj.tl) == before
    c1 = proj.tl.clips[1]
    assert c1.fx == ["bw"] and c1.crop.cx == 0.3  # Resolve nu le știe; rămân de pe clipul vechi
    assert proj.tl.clips[2].transition.type == "fade"
    assert [(b.start, b.duration, b.src_in) for b in proj.tl.broll] == [(1.5, 1.0, 1.0)]


def test_trim_in_resolve_ripples_captions(proj):
    with proj.edit() as tl:
        tl.captions = [Caption(start=3.0, end=3.4, text="ultimul")]
    old_start = proj.tl.captions[0].start
    xml = to_fcpxml(proj.tl, proj.s.assets, "rt")
    # ca și cum ai șterge primul clip în Resolve (ripple delete): restul vin mai devreme cu 2 s
    first = xml.index("<asset-clip", xml.index("<spine>"))
    end = xml.index("</asset-clip>", first) + len("</asset-clip>")
    parsed = parse_fcpxml(xml[:first] + xml[end:], proj.s.assets)
    with proj.edit() as tl:
        apply_fcpxml(tl, parsed, proj.s.assets)
    assert len(proj.tl.clips) == 2
    assert proj.tl.captions and abs(proj.tl.captions[0].start - (old_start - 2)) < 0.1


def test_rejects_garbage_and_foreign_media(proj):
    with pytest.raises(ImportError_):
        parse_fcpxml("nu e xml", proj.s.assets)
    with pytest.raises(ImportError_):
        parse_fcpxml('<!DOCTYPE x [<!ENTITY a "b">]><fcpxml/>', proj.s.assets)
    xml = to_fcpxml(proj.tl, proj.s.assets, "rt").replace(os.path.basename(proj.s.assets["a0"].path), "altceva.mov")
    xml = xml.replace(os.path.dirname(proj.s.assets["a0"].path), "/alt/folder")
    parsed = parse_fcpxml(xml, proj.s.assets)
    assert parsed["unknown"] == ["altceva.mov"]
    with pytest.raises(ImportError_):
        apply_fcpxml(proj.tl.model_copy(deep=True), parsed, proj.s.assets)


def test_api_round_trip(vhome, talking_video):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from vedit.api.app import create_app
    from vedit.api.runners import ScriptedRunner

    with TestClient(create_app(ScriptedRunner())) as c:
        c.post("/api/projects", json={"name": "r"})
        with open(talking_video, "rb") as f:
            c.post("/api/projects/r/assets", files={"file": ("talk.mp4", f, "video/mp4")})
        assert c.get("/api/projects/r/resolve.fcpxml").status_code == 409  # timeline gol
        p = Project("r")
        with p.edit() as tl:
            tl.add_clip("a0", 0, 4)
            tl.add_clip("a0", 5, 8)
        xml = c.get("/api/projects/r/resolve.fcpxml")
        assert xml.status_code == 200 and "fcpxml" in xml.headers["content-disposition"]
        trimmed = xml.text.replace('start="5s" duration="3s"', 'start="6s" duration="2s"')
        r = c.post("/api/projects/r/resolve/import", content=trimmed, headers={"content-type": "application/xml"})
        assert r.status_code == 200, r.text
        assert r.json()["project"]["timeline"]["duration"] == 6.0
        r = c.post("/api/projects/r/resolve/import", files={"file": ("x.fcpxml", b"<html/>", "text/xml")})
        assert r.status_code == 422
        assert c.post("/api/projects/r/undo").json()["timeline"]["duration"] == 7.0
