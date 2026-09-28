"""Transcriere cu timestamp pe cuvânt + format compact pentru LLM.

Fiecare cuvânt primește un id stabil (w0, w1, ...). Agentul editează textul
("șterge w120-w134") în loc să ghicească timestamp-uri — asta e cheia preciziei.
"""
from __future__ import annotations

from pydantic import BaseModel


class Word(BaseModel):
    i: int
    start: float
    end: float
    text: str


class Transcript(BaseModel):
    language: str = ""
    words: list[Word] = []

    def sentences(self, max_gap: float = 0.7, max_words: int = 18) -> list[list[Word]]:
        """Grupează cuvintele în fraze (după punctuație / pauze)."""
        out: list[list[Word]] = []
        cur: list[Word] = []
        for w in self.words:
            if cur and (w.start - cur[-1].end > max_gap or len(cur) >= max_words):
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
        """Format economic în tokeni:  `w12-w20 [3.40-6.10] text frază`."""
        lines = []
        for s in self.sentences():
            if s[-1].end < start or (end is not None and s[0].start > end):
                continue
            text = " ".join(w.text.strip() for w in s)
            lines.append(f"w{s[0].i}-w{s[-1].i} [{s[0].start:.2f}-{s[-1].end:.2f}] {text}")
        return "\n".join(lines)

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
    segments, info = model.transcribe(path, language=language, word_timestamps=True, vad_filter=True)
    words: list[Word] = []
    for seg in segments:
        for w in seg.words or []:
            words.append(Word(i=len(words), start=round(w.start, 3), end=round(w.end, 3), text=w.word.strip()))
    return Transcript(language=info.language, words=words)
