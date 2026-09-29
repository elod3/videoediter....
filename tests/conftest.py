import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import urllib.request

import pytest

from vedit.ff import run


@pytest.fixture(scope="session")
def talking_video(tmp_path_factory):
    """8s 16:9 cu 'vorbire' (ton) pe [0,2), [3.5,5.5), [6.5,8) și liniște în rest."""
    p = tmp_path_factory.mktemp("media") / "talk.mp4"
    expr = "0.5*sin(2*PI*220*t)*(lt(t,2)+between(t,3.5,5.5)+gte(t,6.5))"
    run(["-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=8",
         "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d=8",
         "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(p)])
    return str(p)


@pytest.fixture(scope="session")
def music_file(tmp_path_factory):
    p = tmp_path_factory.mktemp("media") / "music.m4a"
    run(["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:a", "aac", str(p)])
    return str(p)


@pytest.fixture
def vhome(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_HOME", str(tmp_path / "projects"))
    return tmp_path


@pytest.fixture(scope="session")
def podcast_video(tmp_path_factory):
    pytest.importorskip("cv2")
    from synth import face_image, two_speakers

    d = tmp_path_factory.mktemp("pod")
    face = face_image(d)
    if face is None:
        pytest.skip("fără rețea pentru imaginea de test")
    out = d / "pod.mp4"
    # S0 (stânga) 0-3s, S1 (dreapta) 3-6.5s, S0 din nou 6.5-9s
    two_speakers(str(out), face, [(0, 3, 0), (3, 6.5, 1), (6.5, 9, 0)], dur=9)
    return str(out)


# ---------- integrare: față reală care se mută între două "shot-uri" ----------
FACE_URL = "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/messi5.jpg"


@pytest.fixture(scope="session")
def moving_face_video(tmp_path_factory):
    pytest.importorskip("cv2")
    from vedit.ff import run

    d = tmp_path_factory.mktemp("face")
    img = d / "src.jpg"
    try:
        urllib.request.urlretrieve(FACE_URL, img)
    except OSError:
        pytest.skip("fără rețea pentru imaginea de test")
    face_png = d / "face.png"
    run(["-y", "-i", str(img), "-vf", "crop=110:100:190:60,scale=260:-2", str(face_png)])
    out = d / "moving.mp4"
    run(["-y", "-f", "lavfi", "-i", "color=c=gray:s=1280x720:r=25:d=6", "-loop", "1", "-t", "6", "-i", str(face_png),
         "-f", "lavfi", "-i", "sine=f=200:d=6",
         "-filter_complex", "[0:v][1:v]overlay=x='if(lt(t,3),120,900)':y=240:shortest=1[v]",
         "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-t", "6", str(out)])
    return str(out)
