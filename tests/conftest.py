import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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
