

from vedit.faces import Face
from vedit.reframe import crop_fraction, plan, target

CWF, CHF = crop_fraction(1920, 1080, 1080, 1920)  # 9:16 din 16:9 ≈ 0.316 din lățime


def face(cx, w=0.08, cy=0.4):
    return Face(x=cx - w / 2, y=cy - w, w=w, h=2 * w)


def samples(cxs, fps=2.0, t0=0.0):
    return [(t0 + i / fps, [face(c)] if c is not None else []) for i, c in enumerate(cxs)]


def test_crop_fraction():
    assert round(CWF, 3) == 0.316 and CHF == 1.0
    assert crop_fraction(1920, 1080, 1920, 1080, 2.0) == (0.5, 0.5)


def test_steady_face_one_segment():
    segs = plan(samples([0.3, 0.31, 0.29, 0.3, 0.3, 0.32]), 0, 3, CWF, CHF)
    assert len(segs) == 1 and abs(segs[0].cx - 0.3) < 0.02 and segs[0].flag == ""


def test_subject_moves_splits_at_scene_cut():
    s = samples([0.25] * 6 + [0.75] * 6)  # t=0..5.5
    segs = plan(s, 0, 6, CWF, CHF, scene_cuts=[2.8])
    assert [(x.t0, x.t1) for x in segs] == [(0, 2.8), (2.8, 6)]
    assert abs(segs[0].cx - 0.25) < 0.01 and abs(segs[1].cx - 0.75) < 0.01
    # fără scene cut: tăietura la mijloc între eșantioane
    assert plan(s, 0, 6, CWF, CHF)[1].t0 == 2.75
    # cu refine: momentul exact găsit de detector
    assert plan(s, 0, 6, CWF, CHF, refine=lambda a, b, o, n: 2.92)[1].t0 == 2.92
    # split=False => un singur segment
    assert len(plan(s, 0, 6, CWF, CHF, split=False)) == 1


def test_single_outlier_does_not_split():
    segs = plan(samples([0.3, 0.3, 0.8, 0.3, 0.3, 0.3]), 0, 3, CWF, CHF)
    assert len(segs) == 1 and abs(segs[0].cx - 0.3) < 0.01


def test_short_segment_merged():
    segs = plan(samples([0.3] * 6 + [0.8] * 2 + [0.3] * 6), 0, 7, CWF, CHF, min_seg=1.5)
    assert all(s.t1 - s.t0 >= 1.5 for s in segs)


def test_two_faces_fit_or_wide():
    close = target([face(0.45), face(0.55)], CWF, CHF)
    assert abs(close[0] - 0.5) < 0.01 and close[2] == 2 and close[3] is False
    far = target([face(0.2, w=0.1), face(0.8)], CWF, CHF)
    assert abs(far[0] - 0.2) < 0.01 and far[3] is True  # încadrat pe cea mai mare
    # fețele mici din fundal sunt ignorate
    bg = target([face(0.2, w=0.1), face(0.9, w=0.03)], CWF, CHF)
    assert bg[2] == 1 and bg[3] is False


def test_no_face_and_gaps():
    assert plan(samples([None, None]), 0, 1, CWF, CHF)[0].flag == "no_face"
    segs = plan(samples([None, 0.4, None, 0.4]), 0, 2, CWF, CHF)
    assert len(segs) == 1 and abs(segs[0].cx - 0.4) < 0.01


def test_auto_reframe_end_to_end(vhome, moving_face_video):
    from vedit.probe import probe
    from vedit.project import Project

    p = Project("rf")
    p.add_asset(moving_face_video)
    p.add_clip("a0", 0, 6)
    p.set_format("9:16")
    rep = p.auto_reframe(punch_in=0.15)
    assert "Punch-in x1.15 aplicat pe 1 clipuri (c0r1)" in rep
    clips = p.tl.clips
    assert len(clips) == 2, rep
    assert abs(clips[0].src_out - 3.0) < 0.1                      # tăietura exact la schimbarea de poziție
    assert abs(clips[0].crop.cx - (120 + 130) / 1280) < 0.05, rep  # față stânga
    assert abs(clips[1].crop.cx - (900 + 130) / 1280) < 0.05, rep  # față dreapta
    assert [c.crop.zoom for c in clips] == [1.0, 1.15]
    assert abs(p.tl.duration - 6) < 0.05
    out = p.render(preview=True)
    assert probe(out["path"]).height == 960
