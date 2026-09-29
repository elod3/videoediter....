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


TRANSITIONS = ("fade", "dissolve", "fadeblack", "fadewhite", "wipeleft", "wiperight", "slideleft", "slideright",
               "slideup", "slidedown", "smoothleft", "smoothright", "circleopen", "circleclose", "radial",
               "zoomin", "hblur", "pixelize")


class Transition(BaseModel):
    """Tranziție la INTRAREA în clip (dinspre clipul anterior). Clipurile se suprapun `duration` secunde."""
    type: Literal[TRANSITIONS] = "fade"  # type: ignore[valid-type]
    duration: float = 0.4


class ZoomAnim(BaseModel):
    """Zoom animat pe durata clipului (Ken Burns / push-in), relativ la încadrarea clipului."""
    zoom_from: float = 1.0
    zoom_to: float = 1.15
    ease: Literal["inout", "in", "out", "linear"] = "inout"


class Clip(BaseModel):
    id: str
    asset: str
    src_in: float
    src_out: float
    crop: Crop = Field(default_factory=Crop)
    volume_db: float = 0.0
    transition: Transition | None = None
    anim: ZoomAnim | None = None

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
    src_in: float = 0.0  # de unde pornește piesa (ex. de pe primul beat / drop)


class BRoll(BaseModel):
    """Pista V2: footage peste montajul principal. Sunetul rămâne cel de pe V1 (vocea continuă)."""
    id: str
    asset: str
    src_in: float
    start: float        # timp de timeline
    duration: float
    mode: Literal["full", "pip"] = "full"
    pip_pos: Literal["tl", "tr", "bl", "br"] = "tr"
    pip_scale: float = 0.38
    crop: Crop = Field(default_factory=Crop)

    @property
    def end(self) -> float:
        return self.start + self.duration


class Grade(BaseModel):
    """Color grading pentru o sursă: potrivire cu o referință și/sau reglaje, copte într-un LUT .cube."""
    lut: str                      # cale absolută către .cube
    reference: str | None = None  # asset-ul de referință folosit la potrivire
    strength: float = 0.8
    adjust: dict = {}             # reglaje manuale (vezi vedit.style.Adjust)
    preset: str | None = None


class Logo(BaseModel):
    """Watermark: deasupra B-roll-ului, SUB subtitrări și titluri (textul rămâne mereu lizibil)."""
    path: str                     # cale absolută, în <proiect>/brand/
    position: Literal["tl", "tr", "bl", "br"] = "tr"
    scale: float = 0.12           # lățimea logo-ului / lățimea output-ului
    opacity: float = 0.85
    margin: float = 0.04          # distanța de la margine, fracție din latura mică


class Brand(BaseModel):
    """Brand kit per proiect. Stă în timeline => orice schimbare are undo și intră în render."""
    logo: Logo | None = None
    primary: str | None = None    # #RRGGBB: textul subtitrărilor (la karaoke: cuvintele încă nespuse)
    highlight: str | None = None  # #RRGGBB: cuvântul curent la karaoke
    outline: str | None = None    # #RRGGBB: conturul textului
    font_file: str | None = None  # fontul brandului, copiat în <proiect>/brand/fonts/ (familia e în caption_font)
    intro: str | None = None      # asset lipit ÎNAINTE de montaj, la randare
    intro_dur: float = 0.0
    outro: str | None = None      # asset lipit DUPĂ montaj, la randare
    outro_dur: float = 0.0

    def is_set(self) -> bool:
        return self != Brand()


class Timeline(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: float = 30.0
    fill: Literal["crop", "pad"] = "crop"
    clips: list[Clip] = []
    captions: list[Caption] = []
    caption_style: str = "bold_center"
    caption_font: str | None = None  # fontul brandului; implicit cel al stilului (vedit/fonts)
    caption_speaker_colors: bool = False  # culoare diferită per vorbitor (podcast / interviu)
    texts: list[TextOverlay] = []
    music: Music | None = None
    loudness_lufs: float = -14.0  # -14 pt TikTok/YT/IG
    grades: dict[str, Grade] = {}  # asset -> grading
    broll: list[BRoll] = []        # pista V2
    audio_fx: dict[str, dict] = {}  # asset -> {"preset", "noise_db"} curățare audio (vezi vedit.audiofx)
    brand: Brand = Field(default_factory=Brand)

    # ---------- interogări ----------
    @property
    def duration(self) -> float:
        """Durata montajului (fără intro/outro): timpul în care trăiesc captions, texte, B-roll."""
        overlap = sum(c.transition.duration for c in self.clips[1:] if c.transition)
        return round(sum(c.duration for c in self.clips) - overlap, 3)

    @property
    def output_duration(self) -> float:
        """Durata fișierului randat: intro + montaj + outro."""
        b = self.brand
        return round(self.duration + (b.intro_dur if b.intro else 0) + (b.outro_dur if b.outro else 0), 3)

    def starts(self) -> list[float]:
        """Începutul fiecărui clip pe timeline; tranzițiile suprapun clipul peste finalul celui anterior."""
        out, t = [], 0.0
        for i, c in enumerate(self.clips):
            if i and c.transition:
                t -= c.transition.duration
            out.append(round(t, 6))
            t += c.duration
        return out

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
                f" texts={len(self.texts)} music={self.music.asset if self.music else '-'}"
                f" grading={','.join(self.grades) or '-'} broll={len(self.broll)}")
        rows = []
        for c, s in zip(self.clips, self.starts()):
            extra = ""
            if c.crop != Crop():
                extra += f" crop=({c.crop.cx:.2f},{c.crop.cy:.2f},x{c.crop.zoom:g})"
            if c.transition:
                extra += f" ←{c.transition.type} {c.transition.duration:g}s"
            if c.anim:
                extra += f" zoom {c.anim.zoom_from:g}→{c.anim.zoom_to:g} {c.anim.ease}"
            if c.volume_db <= -90:
                extra += " mut"
            elif c.volume_db:
                extra += f" vol={c.volume_db:+g}dB"
            rows.append(f"{c.id} @{s:.2f}-{s + c.duration:.2f} {c.asset}[{c.src_in:.2f}-{c.src_out:.2f}]{extra}")
        for b in sorted(self.broll, key=lambda b: b.start):
            pip = f" pip-{b.pip_pos}" if b.mode == "pip" else ""
            rows.append(f"V2 {b.id} @{b.start:.2f}-{b.end:.2f} {b.asset}[{b.src_in:.2f}-{b.src_in + b.duration:.2f}]{pip}")
        if self.music and self.music.src_in:
            rows.append(f"A2 muzică {self.music.asset} din {self.music.src_in:.2f}s")
        if self.brand.is_set():
            rows.append(self.brand_view())
        return "\n".join([head, *rows])

    def brand_view(self) -> str:
        b = self.brand
        parts = []
        if b.logo:
            parts.append(f"logo {b.logo.position} {b.logo.scale:.0%} opac {b.logo.opacity:.0%}")
        cols = [f"{k}={v}" for k, v in (("text", b.primary), ("highlight", b.highlight), ("contur", b.outline)) if v]
        if cols:
            parts.append("culori " + " ".join(cols))
        if b.font_file:
            parts.append(f"font {self.caption_font}")
        if b.intro:
            parts.append(f"intro {b.intro} ({b.intro_dur:.2f}s)")
        if b.outro:
            parts.append(f"outro {b.outro} ({b.outro_dur:.2f}s)")
        return "brand: " + (" · ".join(parts) or "-")

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
                right.transition = None  # tăietura nouă e dură
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
                if a > c.src_in:
                    right.transition = None
                out.append(right)
        self.clips = [c for c in out if c.duration > 0.04]
        return removed
