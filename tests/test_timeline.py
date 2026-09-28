import pytest

from vedit.analyze import speech_ranges
from vedit.render import crop_box
from vedit.timeline import Clip, Crop, Timeline
from vedit.transcribe import Transcript, Word


def tl3():
    tl = Timeline()
    tl.add_clip("a", 0, 2)
    tl.add_clip("a", 5, 8)
    tl.add_clip("b", 1, 2)
    return tl


def test_duration_and_view():
    tl = tl3()
    assert tl.duration == 6
    assert "c1 @2.00-5.00 a[5.00-8.00]" in tl.view()


def test_remove_range_ripples():
    tl = tl3()
    tl.remove_range(1, 3)  # jumătate din c0, prima secundă din c1
    assert tl.duration == 4
    assert [(c.src_in, c.src_out) for c in tl.clips] == [(0, 1), (6, 8), (1, 2)]


def test_remove_source_span_everywhere():
    tl = tl3()
    tl.remove_source_span("a", 6, 7)
    assert [(c.asset, c.src_in, c.src_out) for c in tl.clips] == [("a", 0, 2), ("a", 5, 6), ("a", 7, 8), ("b", 1, 2)]
    assert len({c.id for c in tl.clips}) == 4


def test_source_to_timeline():
    assert tl3().source_to_timeline("a", 6) == [3.0]


def test_speech_ranges_inverts_and_pads():
    keep = speech_ranges(10, [(2, 4), (4.1, 6), (9.9, 10)], padding=0.1)
    assert keep == [(0.0, 2.1), (3.9, 4.2), (5.9, 10.0)]


def test_crop_box_vertical_from_landscape():
    c = Clip(id="x", asset="a", src_in=0, src_out=1)
    w, h, x, y = crop_box(1920, 1080, 1080, 1920, c)
    assert (w, h) == (608, 1080) and x == (1920 - 608) // 2 and y == 0
    c.crop = Crop(cx=0.0, zoom=2)
    w, h, x, y = crop_box(1920, 1080, 1080, 1920, c)
    assert (w, h, x) == (304, 540, 0) and y == 270


def test_transcript_compact_and_span():
    tr = Transcript(words=[Word(i=0, start=0, end=0.4, text="Salut."), Word(i=1, start=1.0, end=1.3, text="Ce"),
                           Word(i=2, start=1.3, end=1.6, text="faci?")])
    assert tr.compact() == "w0-w0 [0.00-0.40] Salut.\nw1-w2 [1.00-1.60] Ce faci?"
    assert tr.span(1, 2) == (1.0, 1.6)
    with pytest.raises(ValueError):
        tr.span(9, 9)
