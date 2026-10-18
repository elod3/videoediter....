import pytest

from vedit.project import Project
from vedit.transcribe import Transcript, Word


@pytest.fixture(scope="module")
def face_low_center(tmp_path_factory):
    pytest.importorskip("cv2")
    from synth import face_image

    from vedit.ff import run
    d = tmp_path_factory.mktemp("vqa")
    face = face_image(d)
    if face is None:
        pytest.skip("fără rețea pentru imaginea de test")
    import cv2
    cv2.imwrite(str(d / "face.png"), face)
    out = d / "low.mp4"  # fața pe centru orizontal, jos în cadru (unde stau subtitrările)
    run(["-y", "-f", "lavfi", "-i", "color=c=gray:s=1280x720:r=25:d=4", "-loop", "1", "-t", "4", "-i", str(d / "face.png"),
         "-f", "lavfi", "-i", "sine=f=200:d=4", "-filter_complex", "[0:v][1:v]overlay=x=510:y=330:shortest=1[v]",
         "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-t", "4", str(out)])
    return str(out)


def test_face_lost_then_fixed_by_reframe(vhome, moving_face_video):
    p = Project("vqa")
    p.add_asset(moving_face_video)
    p.add_clip("a0", 0, 6)
    p.set_format("9:16")                              # crop pe centru: fața e în lateral, iese din cadru
    qa = p.qa(p.render(preview=True)["path"])
    assert any("nu se vede" in i for i in qa["issues"]), qa["issues"]
    p.auto_reframe()
    qa = p.qa(p.render(preview=True)["path"])
    assert not any(i.startswith("vizual") for i in qa["issues"]), qa["issues"]


def test_captions_over_face_flagged(vhome, face_low_center):
    p = Project("vqa2")
    p.add_asset(face_low_center)
    p.add_clip("a0", 0, 4)
    p.set_format("9:16")
    words = [Word(i=i, start=0.2 + i * 0.5, end=0.6 + i * 0.5, text=f"cuvant{i}") for i in range(7)]
    p.set_transcript("a0", Transcript(words=words))
    p.captions("a0", "bold_center")
    qa = p.qa(p.render(preview=True)["path"])
    assert any("acoperă fața" in i for i in qa["issues"]), qa["issues"]
    p.captions("a0", "classic_bottom")               # jos de tot: nu mai acoperă
    qa = p.qa(p.render(preview=True)["path"])
    assert not any("acoperă fața" in i for i in qa["issues"]), qa["issues"]
