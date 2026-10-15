"""Al doilea lot „de agenție”: culoare automată, retuș, curățarea imaginii, fundal alb-negru / întunecat, rame
pentru B-roll, logo reveal, muzica pe final, profilul clientului."""
import shutil

import numpy as np
import pytest

from vedit import render as rd
from vedit.ff import run
from vedit.project import Project
from vedit.style import grab_frame

needs_chrome = pytest.mark.skipif(not any(shutil.which(b) for b in ("chromium", "google-chrome-stable", "google-chrome")),
                                  reason="fără Chromium")


def _cmd(p, vhome):
    return " ".join(rd.build_command(p.tl, p.s.assets, str(vhome / "x.mp4"), preview=True)[0])


@pytest.fixture(scope="module")
def two_looks(tmp_path_factory):
    """Aceeași scenă, „filmată” cu două telefoane: una întunecată și rece, una spălată și caldă."""
    d = tmp_path_factory.mktemp("looks")
    src = ["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=3"]
    dark, wash = d / "dark.mp4", d / "wash.mp4"
    run(["-y", *src, "-vf", "eq=brightness=-0.18:contrast=0.8,colorbalance=bs=0.25:rs=-0.15", "-c:v", "libx264",
         "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dark)])
    run(["-y", *src, "-vf", "eq=brightness=0.15:contrast=0.6:saturation=0.7,colorbalance=rs=0.2:bs=-0.2", "-c:v",
         "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(wash)])
    return str(dark), str(wash)


def test_color_auto_brings_clips_together(vhome, two_looks):
    p = Project("ca")
    a = p.add_asset(two_looks[0]).split(":")[0]
    b = p.add_asset(two_looks[1]).split(":")[0]
    p.add_clip(a, 0, 3)
    p.add_clip(b, 0, 3)
    before = p.render(preview=True, name="b")["path"]
    out = p.color_auto("all", 0.8)
    assert "corecție automată" in out and p.tl.grades[a].reference == "auto" and p.tl.grades[a].target
    after = p.render(preview=True, name="a")["path"]

    def mean(path, t):
        return grab_frame(path, t, 960, 540, width=160).astype(float).mean(axis=(0, 1))

    gap_before = np.abs(mean(before, 1.5) - mean(before, 4.5)).mean()
    gap_after = np.abs(mean(after, 1.5) - mean(after, 4.5)).mean()
    assert gap_after < gap_before * 0.6                                   # clipurile seamănă mai mult între ele
    p.color_grade(a, saturation=1.1)                                      # se poate reaplica peste (ținta salvată)
    assert p.tl.grades[a].reference == "auto"


def test_enhance_and_background_modes_build_filters(vhome, talking_video):
    p = Project("enh")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 3)
    c = p.tl.clips[0].id
    p.enhance(c, "medium", 0.3)
    cmd = _cmd(p, vhome)
    assert "hqdn3d=4:3:6:4.5" in cmd and "cas=strength=" in cmd
    with pytest.raises(ValueError):
        p.enhance(c, "ultra")
    p.enhance(c, "none", 0)
    assert "hqdn3d" not in _cmd(p, vhome)
    with p.edit() as tl:  # fundalul alb-negru / întunecat folosește masca persoanei (aici una falsă, gri plin)
        mask = p.dir / "cache" / "a0.matte.mp4"
        run(["-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:d=3", "-c:v", "libx264", "-preset", "ultrafast",
             str(mask)])
        tl.mattes["a0"] = str(mask)
        from vedit.timeline import Background
        tl.clips[0].bg = Background(mode="bw")
    assert "hue=s=0" in _cmd(p, vhome)
    p.render(preview=True)


def test_retouch_needs_faces_and_smooths(vhome, podcast_video):
    p = Project("ret")
    p.add_asset(podcast_video)
    p.add_clip("a0", 0, 3)
    c = p.tl.clips[0].id
    with pytest.raises(ValueError):
        p.retouch(c, 1.5)
    out = p.retouch(c, 0.6)
    assert "retuș" in out and p.tl.clips[0].retouch == 0.6 and "a0" in p.tl.skin_masks
    assert "bilateral" in _cmd(p, vhome)
    path = p.render(preview=True)["path"]
    assert grab_frame(path, 1.0, 960, 540, width=160) is not None


@needs_chrome
def test_framed_broll_phone_laptop_rounded(vhome, talking_video, two_looks):
    for frame, fmt in (("phone", "16:9"), ("laptop", "16:9"), ("rounded", "9:16")):
        p = Project(f"fr_{frame}")
        p.add_asset(talking_video)
        b = p.add_asset(two_looks[1]).split(":")[0]
        p.add_clip("a0", 0, 3)
        p.set_format(fmt)
        p.broll_add(b, 0.5, 2.0, 0, "full", "center", False, frame)
        assert p.tl.broll[0].mode == "pip" and p.tl.broll[0].frame == frame
        path = p.render(preview=True)["path"]
        early = grab_frame(path, 0.2, 960 if fmt == "16:9" else 540, 540 if fmt == "16:9" else 960, width=200)
        mid = grab_frame(path, 1.6, 960 if fmt == "16:9" else 540, 540 if fmt == "16:9" else 960, width=200)
        assert np.abs(mid.astype(float) - early.astype(float)).mean() > 3   # rama cu video-ul a apărut
    with pytest.raises(ValueError):
        Project("fr_phone").broll_add(b, 0.5, 1.0, 0, "pip", "tr", False, "tablet")


@needs_chrome
def test_logo_reveal_block(vhome, tmp_path):
    import cv2

    from vedit import motion as mo

    logo = tmp_path / "logo.png"
    img = np.zeros((200, 600, 4), np.uint8)
    cv2.putText(img, "LOGO", (40, 150), cv2.FONT_HERSHEY_DUPLEX, 4, (255, 255, 255, 255), 8)
    cv2.imwrite(str(logo), img)
    with pytest.raises(ValueError, match="imaginea"):
        mo.validate("logo_reveal", {}, 3, {})
    st = mo.resolve_style("local", {"accent": "#E8B04B", "dark": "#101214", "dark2": "#1A1C20"})
    a = cv2.imdecode(np.frombuffer(mo.still("logo_reveal", {"tagline": "din 2009"}, st, 320, 568, 3, 0.05,
                                            {"logo": str(logo)}), np.uint8), cv2.IMREAD_COLOR)
    b = cv2.imdecode(np.frombuffer(mo.still("logo_reveal", {"tagline": "din 2009"}, st, 320, 568, 3, 2.0,
                                            {"logo": str(logo)}), np.uint8), cv2.IMREAD_COLOR)
    assert b.max() > 200 and a.max() < b.max()                          # logo-ul alb apare din mască


def test_music_fit_ends_with_the_track(vhome, talking_video, tmp_path):
    song = tmp_path / "song.wav"
    run(["-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=20", "-af", "volume=0.5", str(song)])
    p = Project("mf")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 6)
    with pytest.raises(ValueError):
        p.music_fit()
    m = p.add_asset(str(song)).split(":")[0]
    p.set_music(m, -12)
    out = p.music_fit()
    assert p.tl.music.ends_naturally and abs(p.tl.music.src_in - (20 - p.tl.duration)) < 0.7, out
    assert ":d=0.25" in _cmd(p, vhome)                                    # fără fade-ul lung de la final


def test_client_profile_roundtrip(vhome, talking_video):
    p = Project("u1-cp")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 3)
    p.motion_style_set("local", "#C81E1E")
    p.captions_look("motion", "chunk")
    saved = p.client_profile("save", "service-rares", tone="direct, cald, fără termeni tehnici",
                             cta="Programează-te: 0740 000 000", hashtags="#targumures #service", music_mood="upbeat")
    assert saved["look"]["motion_style"] == "local" and saved["intent"]["cta"].startswith("Programează")
    q = Project("u1-cp2")
    q.add_asset(talking_video)
    q.add_clip("a0", 0, 3)
    got = q.client_profile("apply", "service-rares")
    assert q.tl.motion_style == "local" and q.tl.caption_look == "chunk" and q.tl.motion_palette["accent"] == "#C81E1E"
    assert got["intent"]["music_mood"] == "upbeat"
    assert "service-rares" in q.client_profile("list")
    other = Project("u2-x")                                               # alt cont nu vede profilul
    with pytest.raises(ValueError):
        other.client_profile("apply", "service-rares")


def test_studio_voice_reduces_noise_in_pauses(vhome, tmp_path):
    from vedit.audiofx import RNN_MODEL, AudioFx, chain

    assert RNN_MODEL.exists()
    src = tmp_path / "noisy.wav"
    # „vorbire” 0-1 s și 2-3 s, liniște între, peste zgomot de fond
    run(["-y", "-f", "lavfi", "-i", "sine=frequency=210:duration=3", "-f", "lavfi", "-i",
         "anoisesrc=d=3:c=pink:a=0.06", "-filter_complex",
         "[0]volume='if(between(t,1,2),0,1)':eval=frame[s];[s][1]amix=inputs=2:normalize=0", str(src)])
    out = tmp_path / "clean.wav"
    run(["-y", "-i", str(src), "-af", chain(AudioFx(preset="studio", noise_db=-30)), str(out)])
    import wave

    def rms(path, a, b):
        with wave.open(str(path)) as w:
            sr = w.getframerate()
            x = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
        return np.sqrt((x[int(a * sr):int(b * sr)] ** 2).mean()) + 1e-9

    assert rms(out, 1.2, 1.8) < rms(src, 1.2, 1.8) * 0.5                 # zgomotul din pauză scade mult


def test_hook_variants_leave_main_edit_untouched(vhome, talking_video):
    p = Project("hv")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 8)
    before = p.tl.model_dump()
    with pytest.raises(ValueError):
        p.hook_variants("1-3")
    res = p.hook_variants("3.6-5.4,6.6-8", "Stai|Uite")
    assert [v["name"] for v in res["variants"]] == ["hook1", "hook2"]
    assert all(v["duration"] > p.tl.duration for v in res["variants"])   # teaser-ul lungește varianta
    assert p.tl.model_dump() == before                                   # montajul principal rămâne la fel


def test_export_all_platforms(vhome, talking_video):
    p = Project("ea")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 4)
    res = p.export_all("reels,youtube")
    assert set(res["exports"]) == {"reels", "youtube"}
    from vedit.probe import probe

    r = probe(res["exports"]["reels"]["path"])
    y = probe(res["exports"]["youtube"]["path"])
    assert (r.width, r.height) == (1080, 1920) and y.width > y.height


def test_real_content_regressions(vhome, talking_video):
    """Bugurile găsite pe interviul real: cut_silences refăcea tot clipul, „am” era luat drept „ăăă”,
    corecturile cu virgulă erau respinse."""
    from vedit.transcribe import Transcript, Word

    p = Project("reg")
    p.add_asset(talking_video)
    words = [Word(i=0, start=0.1, end=0.5, text="Am"), Word(i=1, start=0.6, end=1.0, text="construit"),
             Word(i=2, start=1.1, end=1.4, text="ăm"), Word(i=3, start=1.5, end=1.9, text="case")]
    p._cache("a0", "transcript", lambda: Transcript(language="ro", words=words).model_dump())
    p.add_clip("a0", 0.0, 2.0)                                     # montajul: doar primele 2 s din 8
    out = p.auto_cut_silence("a0", -35, 0.4, 0.1)
    assert "montajul existent" in out and p.tl.duration <= 2.0      # nu reapare clipul întreg
    res = p.clean_speech("a0", lang="ro")
    assert "ăm" in res and "Am," not in res and "(Am" not in res    # „am” e verb, „ăm” e ezitare
    p.transcript_fix("a0", "w1=construită,w3=casa,")
    tr = p.transcript("a0")
    assert [w.text for w in tr.words if w.i in (1, 3)] == ["construită", "casa"]


def test_qa_without_path_checks_latest_render(vhome, talking_video):
    import os
    import shutil

    from vedit.project import Project

    p = Project("qa_latest")
    p.add_asset(str(talking_video))
    with pytest.raises(FileNotFoundError, match="niciun render"):
        p.qa()
    r = p.dir / "renders"
    r.mkdir(exist_ok=True)
    shutil.copy(talking_video, r / "reels.mp4")
    os.utime(r / "reels.mp4", (1, 1))
    shutil.copy(talking_video, r / "preview.mp4")   # previzualizarea nu contează
    assert p.qa()["duration"] > 0
