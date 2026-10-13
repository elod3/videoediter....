"""Biblioteca de hook-uri de deschidere: catalog + fiecare rețetă aplicată și randată real (mp4 pe disc)."""
import os

import pytest

from vedit import hooklib
from vedit.ff import run
from vedit.probe import probe
from vedit.project import Project

# parametri de test pentru fiecare hook (garantează că fiecare e exersat, nu doar listat)
HOOK_ARGS = {
    "teaser_replica": {"start": 0.0, "end": 2.0, "text": "Stai să vezi"},
    "cold_open": {},
    "intrebare": {"text": "Ce urmează?"},
    "before_after_instant": {"text": "RENDER", "subtext": "REALITATE"},
    "pattern_interrupt": {"at": 1.0},
    "punch_text": {"text": "Asta schimbă totul"},
    "countdown": {"de_la": 3, "la": 1},
    "detaliu_ansamblu": {"zoom": 1.4},
    "schema_reveal": {"text": "Structura", "subtext": "2024"},
    "citat_autor": {"text": "Mai puțin e mai mult", "subtext": "Mies"},
    "trei_lucruri": {"items": "Unu|Doi|Trei", "text": "Ce înveți"},
    "flash_best": {"text": "Uite", "freeze": 0.5},
    "spec_intro": {"text": "Proiect", "items": "Suprafață 120|An 2024"},
    "mask_open": {"text": "Titlu mare"},
    "chapter_start": {"text": "Introducere", "value_to": 2},
    "stat_pill": {"text": "4.200"},
}


def make_src(path, dur=6.0):
    run(["-y", "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={dur}",
         "-f", "lavfi", "-i", f"sine=f=300:d={dur}", "-shortest", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path)])
    return str(path)


def test_hooks_catalogue_is_complete():
    hs = hooklib.hooks()
    assert len(hs) >= 12
    ids = [h["id"] for h in hs]
    assert len(ids) == len(set(ids))                       # id-uri unice
    for h in hs:
        assert {"id", "nume", "descriere", "pentru", "durata_s", "parametri"} <= set(h)
        assert h["pentru"] in ("vorbire", "b-roll", "showreel")
        assert h["durata_s"] > 0
        for p in h["parametri"]:
            assert {"nume", "descriere", "obligatoriu"} <= set(p)
    assert set(HOOK_ARGS) == set(ids), "fiecare hook din catalog are parametri de test"


def test_unknown_hook_raises():
    with pytest.raises(ValueError):
        hooklib.apply_hook("inexistent", "nici-un-hook")
    with pytest.raises(ValueError):
        hooklib.apply_hook("inexistent", "citat_autor", text="x")   # lipsește subtext


@pytest.mark.parametrize("hook_id", list(HOOK_ARGS))
def test_every_hook_applies_and_renders(vhome, tmp_path_factory, hook_id):
    p = Project(f"hk_{hook_id}")
    p.set_format("16:9")
    p.add_asset(make_src(tmp_path_factory.mktemp("hook") / "s.mp4", 6.0), "a0")
    p.add_clip("a0", 0, 6)
    msg = hooklib.apply_hook(p, hook_id, **HOOK_ARGS[hook_id])
    assert "EROARE" not in msg
    out = p.render(preview=True)["path"]
    assert out.endswith(".mp4") and os.path.exists(out)
    assert probe(out).duration > 0.5


def test_hooks_via_mcp_tools(vhome, tmp_path):
    from vedit import mcp_server as mcp
    listed = mcp.hooks_list()
    assert "teaser_replica" in listed and "parametri" in listed
    assert "showreel" in mcp.hooks_list(pentru="showreel")
    p = Project("hk_mcp")
    p.set_format("16:9")
    p.add_asset(make_src(tmp_path / "s.mp4", 4.0), "a0")
    p.add_clip("a0", 0, 4)
    r = mcp.hook_apply("hk_mcp", "intrebare", text="De ce?")
    assert "EROARE" not in r
    assert any(g.kind == "title_card" for g in Project("hk_mcp").tl.graphics)  # proiectul de pe disc
