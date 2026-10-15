"""Diarizare audio („cine vorbește când”) cu pyannote + logica ce o leagă de editare.

Etichetele audio sunt litere în ordinea primei apariții: A, B, C...
(diferite de fețele vizuale S0, S1 = de la stânga la dreapta; legătura A→S1 o face `vote_faces`).

Backend-uri:
  * pyannote (local, GPU recomandat): pip install 'vedit[diarize]', HF_TOKEN + acceptă termenii modelului
    https://hf.co/pyannote/speaker-diarization-community-1
  * extern (orice API cu diarizare: pyannoteAI, AssemblyAI, Deepgram...): Project.set_diarization(...)
"""
from __future__ import annotations

import os
import string
import subprocess

from pydantic import BaseModel

from .ff import ffmpeg_bin

DEFAULT_MODEL = "pyannote/speaker-diarization-community-1"


class Turn(BaseModel):
    start: float
    end: float
    speaker: str


class Diarization(BaseModel):
    backend: str = ""
    turns: list[Turn] = []

    def speakers(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for t in self.turns:
            out[t.speaker] = out.get(t.speaker, 0.0) + t.end - t.start
        return out

    def speaker_at(self, t: float, tolerance: float = 0.3) -> str | None:
        best, dist = None, tolerance
        for tr in self.turns:
            if tr.start <= t < tr.end:
                return tr.speaker
            d = min(abs(t - tr.start), abs(t - tr.end))
            if d < dist:
                best, dist = tr.speaker, d
        return best

    def summary(self, start: float = 0.0, end: float | None = None, max_turns: int = 60) -> str:
        total = sum(self.speakers().values()) or 1
        head = ", ".join(f"{s}: {d:.0f}s ({d / total:.0%})" for s, d in sorted(self.speakers().items()))
        turns = [t for t in self.turns if t.end > start and (end is None or t.start < end)]
        lines = [f"[{t.start:.2f}-{t.end:.2f}] {t.speaker}" for t in turns[:max_turns]]
        if len(turns) > max_turns:
            lines.append(f"... încă {len(turns) - max_turns} replici (cere un interval start/end)")
        return "\n".join([f"vorbitori: {head}", *lines])


def normalize(raw: list[tuple[float, float, str]], merge_gap: float = 0.5, min_dur: float = 0.2) -> Diarization:
    """Sortează, redenumește în A, B, C (ordinea apariției), unește replicile aceluiași vorbitor apropiate."""
    names: dict[str, str] = {}
    turns: list[Turn] = []
    for s, e, lab in sorted(raw):
        if e - s < min_dur:
            continue
        if lab not in names:
            i = len(names)
            names[lab] = string.ascii_uppercase[i] if i < 26 else f"X{i}"
        sp = names[lab]
        if turns and turns[-1].speaker == sp and s - turns[-1].end <= merge_gap:
            turns[-1].end = max(turns[-1].end, round(e, 3))
        else:
            turns.append(Turn(start=round(s, 3), end=round(e, 3), speaker=sp))
    return Diarization(turns=turns)


def _load_audio(path: str, sr: int = 16000):
    import numpy as np

    raw = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", path, "-vn",
                          "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy(), sr


def annotation_tracks(result) -> list[tuple[float, float, str]]:
    """Acceptă ieșirea pyannote 4.x (DiarizeOutput) sau 3.x (Annotation)."""
    ann = result
    for attr in ("exclusive_speaker_diarization", "speaker_diarization"):
        if getattr(result, attr, None) is not None:
            ann = getattr(result, attr)
            break
    return [(float(seg.start), float(seg.end), str(lab)) for seg, _, lab in ann.itertracks(yield_label=True)]


_PIPELINES: dict = {}


def pyannote_pipeline(model: str = DEFAULT_MODEL):
    if model in _PIPELINES:
        return _PIPELINES[model]
    try:
        import torch
        from pyannote.audio import Pipeline
    except ImportError as e:
        raise RuntimeError("Instalează diarizarea: pip install 'vedit[diarize]'") from e
    token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")
    try:
        pipe = Pipeline.from_pretrained(model, token=token)
    except TypeError:  # pyannote 3.x
        pipe = Pipeline.from_pretrained(model, use_auth_token=token)
    if pipe is None:
        raise RuntimeError(f"nu pot încărca {model}: setează HF_TOKEN și acceptă termenii pe https://hf.co/{model}")
    if torch.cuda.is_available():
        pipe.to(torch.device("cuda"))
    _PIPELINES[model] = pipe
    return pipe


def diarize(path: str, num_speakers: int | None = None, min_speakers: int | None = None,
            max_speakers: int | None = None, model: str = DEFAULT_MODEL) -> Diarization:
    import torch

    pipe = pyannote_pipeline(model)
    audio, sr = _load_audio(path)  # decodăm noi cu ffmpeg => orice format video merge
    kw = {k: v for k, v in dict(num_speakers=num_speakers, min_speakers=min_speakers,
                                max_speakers=max_speakers).items() if v}
    result = pipe({"waveform": torch.from_numpy(audio).unsqueeze(0), "sample_rate": sr}, **kw)
    d = normalize(annotation_tracks(result))
    d.backend = f"pyannote:{model.split('/')[-1]}"
    return d


# ---------------- logică de editare (pură, testabilă) ----------------

def speaker_spans(words, speaker: str, pad: float = 0.15) -> list[tuple[float, float]]:
    """Intervale sursă acoperite de un vorbitor, aliniate la cuvinte (nu taie în mijlocul cuvântului).
    `words` trebuie să aibă .spk setat. Intervalul merge până la începutul primului cuvânt al altcuiva."""
    spans: list[tuple[float, float]] = []
    i = 0
    while i < len(words):
        if words[i].spk != speaker:
            i += 1
            continue
        j = i
        while j + 1 < len(words) and words[j + 1].spk == speaker:
            j += 1
        s = words[i].start if i == 0 else max(words[i - 1].end, words[i].start - pad)
        e = words[j + 1].start if j + 1 < len(words) else words[j].end + pad
        spans.append((round(s, 3), round(e, 3)))
        i = j + 1
    return spans


def framing_plan(turns: list[Turn], t0: float, t1: float, faces: dict[str, dict],
                 min_hold: float = 1.0) -> list[tuple[float, float, str]]:
    """Segmente de încadrare [(t0, t1, vorbitor)] pentru intervalul [t0, t1).

    Replicile sub min_hold (ex. „da”, „exact”) nu mută camera; golurile rămân pe vorbitorul anterior;
    vorbitorii fără față cunoscută (off-screen) nu mută camera.
    """
    seq: list[list] = []
    for t in turns:
        s, e = max(t.start, t0), min(t.end, t1)
        if e - s <= 0 or t.speaker not in faces:
            continue
        seq.append([s, e, t.speaker])
    if not seq:
        return []
    # acoperă tot intervalul: golurile aparțin vorbitorului anterior
    seq[0][0] = t0
    for a, b in zip(seq, seq[1:]):
        a[1] = b[0]
    seq[-1][1] = t1
    changed = True
    while changed and len(seq) > 1:
        changed = False
        for k, (s, e, sp) in enumerate(seq):
            if e - s < min_hold:
                if k > 0:
                    seq[k - 1][1] = e
                else:
                    seq[1][0] = s
                seq.pop(k)
                changed = True
                break
        merged = [seq[0]]
        for s, e, sp in seq[1:]:
            if sp == merged[-1][2]:
                merged[-1][1] = e
            else:
                merged.append([s, e, sp])
        seq = merged
    return [(round(s, 3), round(e, 3), sp) for s, e, sp in seq]
