"""Cenzură (bip / liniște), fețe și zone ascunse, dublaj cu voce AI — randate real."""
import numpy as np
import pytest
from test_editing_pro import dominant_hz, frame, rms

from vedit import mcp_server as mcp
from vedit.beats import load_mono
from vedit.project import Project
from vedit.transcribe import Transcript, Word


def sharp(img, x0, y0, x1, y1):
    """Energia detaliilor (gradient) într-o zonă: scade mult când e blurată."""
    g = img[y0:y1, x0:x1].mean(axis=2)
    return float(np.abs(np.diff(g, axis=0)).mean() + np.abs(np.diff(g, axis=1)).mean())


def talk_words(p):
    # tonul din talking_video e pe [0,2), [3.5,5.5), [6.5,8)
    words = [(0.1, 0.5, "salut"), (0.7, 1.1, "fuck,"), (1.3, 1.8, "lume"), (3.6, 4.2, "ce"), (4.4, 5.2, "pula")]
    p.set_transcript("a0", Transcript(words=[Word(i=i, start=a, end=b, text=t) for i, (a, b, t) in enumerate(words)]))


def test_censor_bleep_and_mute(vhome, talking_video):
    p = Project("cz")
    p.add_asset(talking_video, "a0")
    talk_words(p)
    p.add_clip("a0", 0, 8)
    p.captions("a0", "bold_center")
    before = p.tl.duration
    out = p.censor_words(lang="en")
    assert "cenzurat 1" in out and "w1" in out
    assert p.tl.duration == pytest.approx(before, abs=0.01)
    assert "f***," in " ".join(c.text for c in p.tl.captions)
    assert [x.kind for x in p.tl.sfx] == ["bleep"] and p.tl.sfx[0].dur == pytest.approx(0.46, abs=0.02)
    r = p.render(preview=True)
    y, sr = load_mono(r["path"], sr=16000), 16000
    assert dominant_hz(y, sr, 0.8, 1.05) == pytest.approx(1000, abs=30)      # bipul peste cuvânt
    assert dominant_hz(y, sr, 0.15, 0.45) == pytest.approx(220, abs=15)      # restul vorbirii neatins

    # mute, pe id, prin MCP: liniște în locul cuvântului, fără bip
    mcp.censor_words("cz", words="w4", mode="mute")
    assert len(p.tl.sfx) == 1 and "p***" in " ".join(c.text for c in Project("cz").tl.captions)
    y = load_mono(Project("cz").render(preview=True)["path"], sr=sr)
    assert rms(y, sr, 4.5, 5.1) < 0.02 * rms(y, sr, 3.7, 4.1)
    assert "nimic de cenzurat" in Project("cz").censor_words(words="inexistent")


def test_blur_region_and_clear(vhome, talking_video):
    p = Project("br")
    p.add_asset(talking_video, "a0")
    p.add_clip("a0", 0, 8)
    base = frame(p.render(preview=True)["path"], 1.0, width=640)
    out = mcp.blur_region("br", 0.0, 4.0, 0.5, 0.5, 0.4, 0.4)
    assert "zonă ascunsă" in out and "blur=1 zone" in Project("br").tl.view()
    img = frame(Project("br").render(preview=True)["path"], 1.0, width=640)
    assert sharp(img, 360, 200, 540, 330) < 0.4 * sharp(base, 360, 200, 540, 330)   # zona e blurată
    assert sharp(img, 20, 20, 280, 160) == pytest.approx(sharp(base, 20, 20, 280, 160), rel=0.15)  # restul nu
    assert "x, y" in mcp.blur_region("br", 0, 1, 1.2, 0, 0.1, 0.1)                 # eroare clară
    Project("br").blur_clear()
    assert all(c.privacy is None for c in Project("br").tl.clips)


def test_blur_faces_follows_face(vhome, moving_face_video):
    pytest.importorskip("cv2")
    p = Project("bf")
    p.add_asset(moving_face_video, "a0")
    p.add_clip("a0", 0, 6)
    base = [frame(p.render(preview=True)["path"], t, width=640) for t in (1.0, 4.5)]
    out = p.blur_faces(style="pixel")
    assert "fețe ascunse" in out and "ATENȚIE" not in out
    got = [frame(p.render(preview=True)["path"], t, width=640) for t in (1.0, 4.5)]
    # fața e la x≈120-380 înainte de 3 s, apoi la x≈900-1160 (pe 1280): în 640 px, jumătate
    for (b, g), (x0, x1) in zip(zip(base, got), ((100, 140), (490, 530))):
        assert sharp(g, x0, 145, x1, 190) < 0.5 * sharp(b, x0, 145, x1, 190)
    assert sharp(got[0], 70, 210, 180, 238) == pytest.approx(sharp(base[0], 70, 210, 180, 238), rel=0.2)  # tricoul nu
    assert "pixel=fețe" in p.tl.view()
    p.blur_faces(off=True)
    assert all(c.privacy is None for c in p.tl.clips)
    # API-ul nu poate muta masca în afara proiectului
    tl = p.tl.model_copy(deep=True)
    tl.face_masks = {"a0": "/etc/passwd"}
    with p.edit():
        p.s.timeline = tl
    with pytest.raises(PermissionError):
        p.render(preview=True)


def test_dub_replaces_voice(vhome, talking_video):
    pytest.importorskip("piper")
    p = Project("dub")
    p.add_asset(talking_video, "a0")
    talk_words(p)
    p.add_clip("a0", 0, 8)
    p.captions("a0", "bold_center")
    try:
        out = p.dub("0.0-2.0|Hello world, how are you?\n3.5-5.5|This is a rather long sentence that must be "
                    "spoken a little faster.\n6.5-8.0|Bye.", lang="en")
    except RuntimeError as e:
        if "descărca" in str(e):
            pytest.skip("fără rețea pentru vocea Piper")
        raise
    assert "dublaj en: 3 replici" in out and "grăbite ca să încapă: 3.5s" in out
    nar = p.tl.narration.asset
    assert nar.startswith("dub_en") and all(c.volume_db == -100 for c in p.tl.clips)
    caps = " ".join(c.text for c in p.tl.captions)
    assert "Hello" in caps and "salut" not in caps
    words = p.transcript(nar).words
    assert words[0].start >= 0 and 3.5 <= [w for w in words if w.text == "This"][0].start < 3.9
    assert [w for w in words if w.text.startswith("faster")][0].end <= 6.55      # a încăput până la replica 3
    long = p.dub("0-1|" + "This sentence is far too long for one second. " * 3 + "\n1.5-3|Ok.", lang="en")
    assert "PREA LUNGI" in long and "0.0s" in long
    y, sr = load_mono(p.render(preview=True)["path"], sr=16000), 16000
    assert rms(y, sr, 0.3, 1.5) > 0.01                                            # se aude dublajul
    assert abs(dominant_hz(y, sr, 0.3, 1.5) - 220) > 20                           # nu tonul original
    assert "rând invalid" in mcp.dub("dub", "fără timpi")
    assert "suprapun" in mcp.dub("dub", "0-3|a\n2-4|b")
