import sys
import types
from dataclasses import dataclass

import pytest

from vedit.diarize import Diarization, Turn, annotation_tracks, framing_plan, normalize, speaker_spans
from vedit.timeline import Timeline
from vedit.transcribe import Transcript, Word


def turns(*spec):
    return [Turn(start=a, end=b, speaker=s) for a, b, s in spec]


def test_normalize_relabels_merges_and_drops():
    d = normalize([(5, 6, "SPEAKER_00"), (0, 2, "SPEAKER_01"), (2.3, 4, "SPEAKER_01"), (4.2, 4.3, "SPEAKER_00")])
    assert [(t.start, t.end, t.speaker) for t in d.turns] == [(0, 4, "A"), (5, 6, "B")]
    assert d.speakers() == {"A": 4, "B": 1}
    assert d.speaker_at(4.1) == "A" and d.speaker_at(5.5) == "B" and d.speaker_at(20) is None


def test_annotation_tracks_pyannote_3_and_4():
    core = pytest.importorskip("pyannote.core")
    ann = core.Annotation()
    ann[core.Segment(0, 1.5)] = "SPEAKER_01"
    ann[core.Segment(1.6, 3)] = "SPEAKER_00"
    assert annotation_tracks(ann) == [(0, 1.5, "SPEAKER_01"), (1.6, 3, "SPEAKER_00")]  # 3.x

    @dataclass
    class DiarizeOutput:  # forma din pyannote 4.x
        speaker_diarization: object
        exclusive_speaker_diarization: object

    empty = core.Annotation()
    assert annotation_tracks(DiarizeOutput(empty, ann))[0][2] == "SPEAKER_01"
    assert annotation_tracks(DiarizeOutput(ann, empty)) == []  # exclusive are prioritate chiar goală


def test_diarize_calls_pipeline_with_waveform(monkeypatch, talking_video):
    core = pytest.importorskip("pyannote.core")
    from vedit import diarize as dz

    class FakeTensor:
        def __init__(self, a):
            self.a = a

        def unsqueeze(self, _):
            return self

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(from_numpy=FakeTensor))
    seen = {}

    def pipe(file, **kw):
        seen.update(file=file, kw=kw)
        ann = core.Annotation()
        ann[core.Segment(0, 2)] = "SPEAKER_07"
        ann[core.Segment(3.5, 5.5)] = "SPEAKER_03"
        return ann

    monkeypatch.setattr(dz, "pyannote_pipeline", lambda model: pipe)
    d = dz.diarize(talking_video, num_speakers=2)
    assert seen["kw"] == {"num_speakers": 2} and seen["file"]["sample_rate"] == 16000
    assert abs(len(seen["file"]["waveform"].a) / 16000 - 8) < 0.1
    assert [t.speaker for t in d.turns] == ["A", "B"] and d.backend.startswith("pyannote")


def test_speaker_spans_word_aligned():
    ws = [Word(i=0, start=0, end=0.5, text="a", spk="A"), Word(i=1, start=0.6, end=1, text="b", spk="A"),
          Word(i=2, start=1.4, end=2, text="c", spk="B"), Word(i=3, start=2.6, end=3, text="d", spk="A"),
          Word(i=4, start=3.1, end=3.5, text="e", spk="B")]
    assert speaker_spans(ws, "B") == [(1.25, 2.6), (3.0, 3.65)]
    assert speaker_spans(ws, "A") == [(0, 1.4), (2.45, 3.1)]


def test_framing_plan_hysteresis_and_offscreen():
    faces = {"A": {}, "B": {}}
    tt = turns((0, 3, "A"), (3.2, 3.6, "B"), (3.7, 6, "A"), (6.2, 9, "B"), (9, 10, "C"))
    # „da” scurt de la B ignorat; golurile rămân pe vorbitorul anterior; C (fără față) nu mută camera
    assert framing_plan(tt, 0, 10, faces) == [(0, 6.2, "A"), (6.2, 10, "B")]
    assert framing_plan(tt, 7, 8, faces) == [(7, 8, "B")]
    assert framing_plan(turns((0, 1, "C")), 0, 1, faces) == []


def test_transcript_speaker_labels():
    tr = Transcript(words=[Word(i=0, start=0, end=0.4, text="Salut"), Word(i=1, start=0.5, end=0.9, text="tuturor"),
                           Word(i=2, start=1.0, end=1.4, text="Salut"), Word(i=3, start=1.5, end=1.9, text="Andrei.")])
    tr.label_speakers(Diarization(turns=turns((0, 0.95, "A"), (0.95, 2, "B"))))
    assert tr.compact() == "w0-w1 [0.00-0.90] A: Salut tuturor\nw2-w3 [1.00-1.90] B: Salut Andrei."


def test_caption_speaker_colors():
    from vedit.captions import build_captions, to_ass

    tl = Timeline()
    tl.add_clip("a", 0, 2)
    tr = Transcript(words=[Word(i=0, start=0, end=0.4, text="unu", spk="A"), Word(i=1, start=0.5, end=0.9, text="doi", spk="B")])
    assert build_captions(tl, "a", tr, "bold_center", speaker_colors=True) == 2  # nu amestecă vorbitorii
    ass = to_ass(tl)
    assert "{\\1c&HFFFFFF&}UNU" in ass and "{\\1c&H00E5FF&}DOI" in ass


# ---------- integrare pe podcastul sintetic ----------
POD_TURNS = [(0, 3, "SPEAKER_1"), (3, 5.0, "SPEAKER_2"), (5.0, 5.4, "SPEAKER_1"), (5.4, 6.5, "SPEAKER_2"),
             (6.5, 9, "SPEAKER_1")]  # A: stânga, B: dreapta; „da” scurt al lui A la 5.0


def pod_words():
    ws, i = [], 0
    for a, b, _ in POD_TURNS:
        t = a + 0.05
        while t + 0.3 <= b:
            ws.append(Word(i=i, start=round(t, 2), end=round(t + 0.3, 2), text=f"x{i}"))
            i, t = i + 1, t + 0.4
    return Transcript(words=ws)


def test_diarization_driven_reframe_and_cut(vhome, podcast_video):
    from vedit import mcp_server as m
    from vedit.project import Project

    p = Project("dz")
    p.add_asset(podcast_video)
    p.set_diarization("a0", normalize(POD_TURNS))
    faces = p.speaker_faces("a0")
    assert faces["A"]["cx"] < 0.3 and faces["B"]["cx"] > 0.7, faces
    out = m.diarize("dz", "a0")
    assert "A→cx=0.19" in out and "B→cx=0.80" in out, out

    p.add_clip("a0", 0, 9)
    p.set_format("9:16")
    rep = p.auto_reframe()
    got = [(c.src_in, c.src_out, round(c.crop.cx, 1)) for c in p.tl.clips]
    assert got == [(0, 3, 0.2), (3, 6.5, 0.8), (6.5, 9, 0.2)], rep  # granițe exacte din audio
    assert "vorbitor A" in rep and "vorbitor B" in rep

    p.set_transcript("a0", pod_words())
    assert p.transcript("a0").compact().splitlines()[0].split("] ")[1].startswith("A: ")
    p.undo()
    p.undo()  # timeline gol
    msg = p.cut_speaker("a0", "B")
    assert 5.0 < p.tl.duration < 6.3, msg  # A vorbește ~5.9s
    msg = m.cut_speaker("dz", "a0", "Z")
    assert msg.startswith("EROARE") and "A, B" in msg
    assert "captions" in p.captions("a0", "karaoke", speaker_colors=True)
