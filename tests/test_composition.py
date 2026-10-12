"""Faza 2 — calitatea compoziției. Fiecare test randează video real (ffmpeg) și verifică pe pixeli / timeline.

Acoperă cele 4 defecte: (1) QA prinde subtitrarea peste gura feței, (2) graficul se plasează singur în
zona liberă (nu peste față), (3) hook-ul suspendă subtitrarea (un singur strat de text), (4) cardul are
contrast garantat pe fundal luminos și închis.
"""
import numpy as np
import pytest

from vedit import compose, hooklib
from vedit.ff import run
from vedit.graphics import graphic_box
from vedit.probe import probe
from vedit.project import Project
from vedit.style import grab_frame
from vedit.transcribe import Transcript, Word


def _words(n: int, step: float = 0.5, start: float = 0.2):
    return [Word(i=i, start=start + i * step, end=start + step * 0.8 + i * step, text=f"cuvant{i}") for i in range(n)]


def _face_png(d) -> str:
    pytest.importorskip("cv2")
    from synth import face_image

    import cv2

    face = face_image(d)
    if face is None:
        pytest.skip("fără rețea pentru imaginea de test")
    cv2.imwrite(str(d / "face.png"), face)
    return str(d / "face.png")


def _video(d, name: str, face_y: int, face_h: int, dur: float = 4.0, src: str = "gray") -> str:
    """1280x720 cu o față decupată din imaginea de test, lipită la (centru, face_y) cu înălțimea face_h."""
    fp = _face_png(d)
    out = d / name
    run(["-y", "-f", "lavfi", "-i", f"color=c={src}:s=1280x720:r=25:d={dur}",
         "-loop", "1", "-t", f"{dur}", "-i", fp, "-f", "lavfi", "-i", f"sine=f=200:d={dur}",
         "-filter_complex", f"[1:v]scale=-1:{face_h}[f];[0:v][f]overlay=x=(W-w)/2:y={face_y}:shortest=1[v]",
         "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out)])
    return str(out)


# ---------------------------------------------------------------- fixture-uri (module scope, randate o dată)
@pytest.fixture(scope="module")
def big_face_low(tmp_path_factory):
    """Față mare, decupată larg: după crop-ul 9:16 umple aproape tot cadrul (ca selfie-ul din demo/vlog)."""
    return _video(tmp_path_factory.mktemp("cmp_big"), "big.mp4", face_y=-240, face_h=1200, dur=4.0)


@pytest.fixture(scope="module")
def face_high(tmp_path_factory):
    """Față mică, jos-centrată -> loc liber sus pentru grafic."""
    return _video(tmp_path_factory.mktemp("cmp_up"), "up.mp4", face_y=235, face_h=250, dur=6.0)


@pytest.fixture(scope="module")
def bright_dark(tmp_path_factory):
    d = tmp_path_factory.mktemp("cmp_cards")
    out = {}
    for name, col in (("bright", "0xE6E6E6"), ("dark", "0x0E0E0E")):
        p = d / f"{name}.mp4"
        run(["-y", "-f", "lavfi", "-i", f"color=c={col}:s=1080x1920:r=25:d=4", "-f", "lavfi", "-i", "sine=f=300:d=4",
             "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)])
        out[name] = str(p)
    return out


# ---------------------------------------------------------------- 1. QA: subtitrarea peste gura feței
def test_qa_flags_caption_over_mouth(vhome, big_face_low):
    p = Project("cmp_qa")
    p.add_asset(big_face_low)
    p.add_clip("a0", 0, 4)
    p.set_format("9:16")
    p.set_transcript("a0", Transcript(words=_words(7)))
    p.captions("a0", "bold_center")                       # centrat: cade peste gură pe un selfie
    qa = p.qa(p.render(preview=True)["path"])
    assert any("acoperă fața" in i for i in qa["issues"]), qa["issues"]
    p.captions("a0", "classic_bottom")                    # jos de tot: nu mai acoperă gura
    qa = p.qa(p.render(preview=True)["path"])
    assert not any("acoperă fața" in i for i in qa["issues"]), qa["issues"]


# ---------------------------------------------------------------- 2. plasare automată a graficului
def test_graphic_avoids_face(vhome, face_high):
    p = Project("cmp_gfx")
    p.add_asset(face_high)
    p.add_clip("a0", 0, 6)
    p.set_format("9:16")
    p.set_transcript("a0", Transcript(words=_words(10, step=0.5)))
    p.captions("a0", "bold_center")
    msg = p.graphic_add("quote_card", 1.5, 5.5, text="Casele bune se văd în detaliu", subtext="Arh Demo")
    assert "NEadăugat" not in msg, msg
    g = p.tl.graphics[0]
    assert g.position in ("top", "bottom"), g.position
    boxes = p.output_face_boxes(1.5, 5.5)
    assert boxes, "testul are nevoie de o față detectată"
    f0, f1 = min(b[1] for b in boxes), max(b[3] for b in boxes)
    gb = graphic_box(g, p.tl.width, p.tl.height)
    band = compose.zone_band(g.position, gb[3] - gb[1] if gb else None)
    assert not (f0 < band[1] and band[0] < f1), (f0, f1, band)             # fără suprapunere cu fața
    out = p.render(preview=True)["path"]
    assert probe(out).duration > 1
    fr = grab_frame(out, 3.0, 540, 960, width=270)                       # graficul se vede (nu e cadru gol)
    assert fr is not None and fr.std() > 8


def test_graphic_refused_when_no_free_zone(vhome, big_face_low):
    p = Project("cmp_gfx2")
    p.add_asset(big_face_low)
    p.add_clip("a0", 0, 4)
    p.set_format("9:16")
    n0 = len(p.tl.graphics)
    msg = p.graphic_add("quote_card", 0.5, 3.5, text="Citește asta", subtext="autor")
    assert "NEadăugat" in msg, msg                                        # avertizare clară, nu plasare orbească
    assert len(p.tl.graphics) == n0


# ---------------------------------------------------------------- 3. hook vs subtitrare
def _hook_project(name, src):
    p = Project(name)
    p.add_asset(src, "a0")
    p.add_clip("a0", 0, 6)
    p.set_format("9:16")
    p.set_transcript("a0", Transcript(words=_words(11, step=0.5)))
    p.captions("a0", "bold_center")
    return p


def _bright_ratio(fr, y0, y1):
    band = fr[int(y0 * fr.shape[0]):int(y1 * fr.shape[0])].astype(int)
    return float((band.max(axis=2) > 200).mean())


def test_hook_suspends_captions_single_text_layer(vhome, face_high):
    pa = _hook_project("cmp_hook_a", face_high)
    assert any(c.start < 1.8 and c.end > 0.0 for c in pa.tl.captions)     # coliziune înainte de hook
    msg = hooklib.apply_hook(pa, "punch_text", text="Asta schimbă totul")
    assert "EROARE" not in msg
    assert not any(c.start < 1.8 and c.end > 0.0 for c in pa.tl.captions)  # suspendate pe durata hook-ului
    oa = pa.render(preview=True)["path"]
    fr_a = grab_frame(oa, 1.0, 540, 960, width=270)
    assert fr_a is not None

    # control: cu flag-ul de oprire, subtitrarea rămâne -> în bandă apar pixeli de text în plus
    pb = _hook_project("cmp_hook_b", face_high)
    hooklib.apply_hook(pb, "punch_text", text="Asta schimbă totul", subtitrari=False)
    assert any(c.start < 1.8 and c.end > 0.0 for c in pb.tl.captions)
    ob = pb.render(preview=True)["path"]
    fr_b = grab_frame(ob, 1.0, 540, 960, width=270)
    ratio_a, ratio_b = _bright_ratio(fr_a, 0.60, 0.70), _bright_ratio(fr_b, 0.60, 0.70)
    assert ratio_b > ratio_a + 0.02, (ratio_a, ratio_b)                   # un singur strat de text în A


# ---------------------------------------------------------------- 4. contrast de card
def test_card_contrast_adapts_to_background(vhome, bright_dark):
    alphas = {}
    for name, path in bright_dark.items():
        p = Project(f"cmp_card_{name}")
        p.set_format("9:16")
        p.add_asset(path)
        p.add_clip("a0", 0, 4)
        p.graphic_add("quote_card", 0.5, 3.5, text="Mai puțin e mai mult", subtext="Mies van der Rohe")
        g = p.tl.graphics[0]
        assert g.panel_alpha and g.panel_alpha.startswith("&H"), g.panel_alpha
        alphas[name] = int(g.panel_alpha[2:4], 16)
        out = p.render(preview=True)["path"]
        assert probe(out).duration > 1
        raw = grab_frame(path, 2.0, 1080, 1920, width=270)
        fr = grab_frame(out, 2.0, 540, 960, width=270)
        assert raw is not None and fr is not None
        center = slice(int(0.38 * fr.shape[0]), int(0.62 * fr.shape[0]))
        alphas[name] = (alphas[name], float(raw[center].mean() - fr[center].mean()))
    # fundal luminos -> panou mai opac (alpha ASS mai mic) și zona se întunecă vizibil
    assert alphas["bright"][0] < alphas["dark"][0], alphas
    assert alphas["bright"][1] > 20, alphas        # pe luminos panoul chiar întunecă
    assert alphas["dark"][1] < alphas["bright"][1], alphas
