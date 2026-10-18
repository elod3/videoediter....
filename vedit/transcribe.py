"""Transcriere cu timestamp pe cuvânt + format compact pentru LLM.

Fiecare cuvânt primește un id stabil (w0, w1, ...). Agentul editează textul
("șterge w120-w134") în loc să ghicească timestamp-uri — asta e cheia preciziei.
"""
from __future__ import annotations

import os

from pydantic import BaseModel


class Word(BaseModel):
    i: int
    start: float
    end: float
    text: str
    spk: str | None = None  # vorbitor din diarizare (A, B, ...)


class Transcript(BaseModel):
    language: str = ""
    words: list[Word] = []

    def sentences(self, max_gap: float = 0.7, max_words: int = 18) -> list[list[Word]]:
        """Grupează cuvintele în fraze (după punctuație / pauze)."""
        out: list[list[Word]] = []
        cur: list[Word] = []
        for w in self.words:
            if cur and (w.start - cur[-1].end > max_gap or len(cur) >= max_words or w.spk != cur[-1].spk):
                out.append(cur)
                cur = []
            cur.append(w)
            if w.text.rstrip().endswith((".", "?", "!")):
                out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return out

    def compact(self, start: float = 0.0, end: float | None = None) -> str:
        """Format economic în tokeni:  `w12-w20 [3.40-6.10] A: text frază` (A = vorbitor, dacă există diarizare)."""
        lines = []
        for s in self.sentences():
            if s[-1].end < start or (end is not None and s[0].start > end):
                continue
            text = " ".join(w.text.strip() for w in s)
            who = f"{s[0].spk}: " if s[0].spk else ""
            lines.append(f"w{s[0].i}-w{s[-1].i} [{s[0].start:.2f}-{s[-1].end:.2f}] {who}{text}")
        return "\n".join(lines)

    def label_speakers(self, diar) -> None:
        """Atribuie fiecărui cuvânt vorbitorul din diarizare (după mijlocul cuvântului)."""
        for w in self.words:
            w.spk = diar.speaker_at((w.start + w.end) / 2)

    def span(self, first: int, last: int) -> tuple[float, float]:
        ws = [w for w in self.words if first <= w.i <= last]
        if not ws:
            raise ValueError(f"nu există cuvinte w{first}-w{last}")
        return ws[0].start, ws[-1].end


def transcribe(path: str, model_size: str = "small", language: str | None = None) -> Transcript:
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError("Instalează transcrierea: pip install 'vedit[whisper]'") from e
    model = WhisperModel(model_size, device="auto", compute_type="auto")
    # sunetul îl decodăm noi, cu ffmpeg (16 kHz mono): decodorul intern (PyAV) se strică între versiuni.
    # Pe bucăți de 5 minute: un interviu de o oră nu mai stă tot în memorie odată.
    import subprocess

    import numpy as np

    from .ff import ffmpeg_bin
    from .probe import probe

    total = probe(path).duration or 0.0
    chunk = float(os.environ.get("VEDIT_TRANSCRIBE_CHUNK", "300"))
    words: list[Word] = []
    lang = language
    t0 = 0.0
    while t0 < max(total, 0.1):
        raw = subprocess.run([ffmpeg_bin(), "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{t0:.3f}",
                              "-t", f"{chunk:.3f}", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                             capture_output=True, check=True).stdout
        audio = np.frombuffer(raw, np.float32)
        if len(audio) < 1600:
            break
        segments, info = model.transcribe(audio, language=lang, word_timestamps=True, vad_filter=True)
        lang = lang or info.language  # limba aflată pe prima bucată rămâne pentru restul
        for seg in segments:
            for w in seg.words or []:
                words.append(Word(i=len(words), start=round(t0 + w.start, 3), end=round(t0 + w.end, 3),
                                  text=w.word.strip()))
        t0 += chunk
        del audio, raw
    return Transcript(language=lang or "", words=words)
