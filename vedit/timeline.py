"""Timeline declarativ (EDL). Agentul modifică DOAR această structură; randarea e deterministă.

De ce: un LLM e bun la decizii ("ce păstrez, în ce ordine"), prost la sintaxă ffmpeg.
Separăm decizia (timeline JSON) de execuție (render.py) => zero comenzi ffmpeg halucinate.
"""
from __future__ import annotations

import itertools
from typing import Literal

from pydantic import BaseModel, Field

FORMATS = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}


class Crop(BaseModel):
    """Încadrare când aspectul sursei diferă de output. Coordonate normalizate 0..1."""
    cx: float = 0.5
    cy: float = 0.5
    zoom: float = 1.0  # >1 = punch-in


class Clip(BaseModel):
    id: str
    asset: str
    src_in: float
    src_out: float
    crop: Crop = Field(default_factory=Crop)
    volume_db: float = 0.0

    @property
    def duration(self) -> float:
        return self.src_out - self.src_in


class Caption(BaseModel):
    start: float
    end: float
    text: str
    # durate per cuvânt (secunde), pentru stilul karaoke
    word_durs: list[float] | None = None
    speaker: str | None = None


class TextOverlay(BaseModel):
    start: float
    end: float
    text: str
    position: Literal["top", "center", "bottom"] = "top"


class Music(BaseModel):
    asset: str
    volume_db: float = -18.0
    duck: bool = True  # coboară muzica automat când se vorbește


class Timeline(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    fill: Literal["crop", "pad"] = "crop"
    clips: list[Clip] = []
    captions: list[Caption] = []
    caption_style: str = "bold_center"
    caption_speaker_colors: bool = False  # culoare diferită per vorbitor (podcast / interviu)
    texts: list[TextOverlay] = []
    music: Music | None = None
    loudness_lufs: float = -14.0  # -14 pt TikTok/YT/IG

    # ---------- interogări ----------
    @property
    def duration(self) -> float:
        return round(sum(c.duration for c in self.clips), 3)

    def starts(self) -> list[float]:
        return list(itertools.accumulate([0.0] + [c.duration for c in self.clips[:-1]]))

    def clip(self, cid: str) -> Clip:
        for c in self.clips:
            if c.id == cid:
                return c
        raise KeyError(f"clip inexistent: {cid}")

    def source_to_timeline(self, asset: str, t: float) -> list[float]:
        return [s + (t - c.src_in) for c, s in zip(self.clips, self.starts())
                if c.asset == asset and c.src_in <= t < c.src_out]

    def view(self) -> str:
        """Rezumat compact pentru LLM (≈1 linie/clip)."""
        head = (f"{self.width}x{self.height}@{self.fps:g} fill={self.fill} dur={self.duration:.2f}s "
                f"clips={len(self.clips)} captions={len(self.captions)} style={self.caption_style}"
                f" texts={len(self.texts)} music={self.music.asset if self.music else '-'}")
        rows = []
        for c, s in zip(self.clips, self.starts()):
            extra = ""
            if c.crop != Crop():
                extra += f" crop=({c.crop.cx:.2f},{c.crop.cy:.2f},x{c.crop.zoom:g})"
            if c.volume_db:
                extra += f" vol={c.volume_db:+g}dB"
            rows.append(f"{c.id} @{s:.2f}-{s + c.duration:.2f} {c.asset}[{c.src_in:.2f}-{c.src_out:.2f}]{extra}")
        return "\n".join([head, *rows])

    # ---------- modificări ----------
    def _new_id(self) -> str:
        used = {c.id for c in self.clips}
        n = len(self.clips)
        while f"c{n}" in used:
            n += 1
        return f"c{n}"

    def add_clip(self, asset: str, src_in: float, src_out: float, index: int | None = None) -> Clip:
        if src_out <= src_in:
            raise ValueError("src_out trebuie să fie > src_in")
        c = Clip(id=self._new_id(), asset=asset, src_in=round(src_in, 3), src_out=round(src_out, 3))
        self.clips.insert(len(self.clips) if index is None else index, c)
        return c

    def set_clips_from_ranges(self, asset: str, ranges: list[tuple[float, float]]) -> None:
        self.clips = []
        for a, b in ranges:
            self.add_clip(asset, a, b)

    def remove_clip(self, cid: str) -> None:
        self.clips = [c for c in self.clips if c.id != cid]

    def move_clip(self, cid: str, index: int) -> None:
        c = self.clip(cid)
        self.clips.remove(c)
        self.clips.insert(index, c)

    def split_at(self, t: float) -> None:
        """Taie clipul care conține timpul t (timp de timeline)."""
        for i, (c, s) in enumerate(zip(self.clips, self.starts())):
            if s < t < s + c.duration:
                cut = round(c.src_in + (t - s), 3)
                right = c.model_copy(deep=True)
                right.id = self._new_id()
                right.src_in = cut
                c.src_out = cut
                self.clips.insert(i + 1, right)
                return

    def remove_range(self, t0: float, t1: float) -> None:
        """Ripple delete pe timeline: [t0, t1) dispare, restul se lipește."""
        self.split_at(t0)
        self.split_at(t1)
        self.clips = [c for c, s in zip(self.clips, self.starts())
                      if not (s >= t0 - 1e-6 and s + c.duration <= t1 + 1e-6)]

    def remove_source_span(self, asset: str, a: float, b: float) -> int:
        """Scoate intervalul [a,b) din SURSĂ oriunde apare (ex: cuvinte șterse din transcript)."""
        out: list[Clip] = []
        removed = 0
        for c in self.clips:
            if c.asset != asset or b <= c.src_in or a >= c.src_out:
                out.append(c)
                continue
            removed += 1
            if a > c.src_in:
                left = c.model_copy(deep=True)
                left.src_out = round(a, 3)
                out.append(left)
            if b < c.src_out:
                right = c.model_copy(deep=True)
                right.src_in = round(b, 3)
                right.id = c.id + "b" if a > c.src_in else c.id
                out.append(right)
        self.clips = [c for c in out if c.duration > 0.04]
        return removed
