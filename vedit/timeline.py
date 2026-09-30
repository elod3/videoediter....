"""Timeline declarativ (EDL). Agentul modifică DOAR această structură; randarea e deterministă.

De ce: un LLM e bun la decizii ("ce păstrez, în ce ordine"), prost la sintaxă ffmpeg.
Separăm decizia (timeline JSON) de execuție (render.py) => zero comenzi ffmpeg halucinate.
"""
from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator


def _hex(value: str) -> str:
    import re

    if not re.fullmatch(r"#?[0-9A-Fa-f]{6}", value):
        raise ValueError(f"culoare invalidă {value[:40]!r}: folosește hex #RRGGBB (ex. #FFD400)")
    return value


# culorile ajung în filtrele ffmpeg: doar format strict (un timeline venit din API nu poate strecura
# filtre precum movie=, care ar citi fișierele altor proiecte)
Hex = Annotated[str, AfterValidator(_hex)]

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
    # punctul spre care se face zoom (normalizat în cadrul clipului): implicit centrul; diferite = pan + zoom
    cx_from: float = 0.5
    cy_from: float = 0.5
    cx_to: float = 0.5
    cy_to: float = 0.5


# efecte vizuale per clip (compilate în render.py, în ordinea din listă)
EFFECTS = ("bw", "vintage", "vignette", "blur", "sharpen", "glitch", "shake", "flash", "grain", "mirror", "invert")


class Split(BaseModel):
    """Split-screen: două unghiuri (camere) în același cadru. stack = sus/jos (9:16), side = stânga/dreapta."""
    angles: list[str]                      # exact 2 asset-uri video, sincronizate prin Timeline.sync
    mode: Literal["stack", "side"] = "stack"
    crops: list[Crop] = Field(default_factory=lambda: [Crop(), Crop()])


class Background(BaseModel):
    """Fundalul din spatele persoanei (decupată cu segment.py): blur (portret), culoare sau alt asset."""
    mode: Literal["blur", "color", "asset"] = "blur"
    value: str = ""                        # color: #RRGGBB; asset: id-ul pozei / clipului de fundal

    @model_validator(mode="after")
    def _strict_value(self):
        import re

        if self.mode == "color" and not re.fullmatch(r"#?[0-9A-Fa-f]{6}", self.value):
            raise ValueError("fundal color: culoare invalidă, folosește #RRGGBB")
        if self.mode == "asset" and not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", self.value):
            raise ValueError("fundal asset: id de asset invalid")
        return self


class Box(BaseModel):
    """Dreptunghi normalizat 0..1 față de cadrul sursă."""
    x: float
    y: float
    w: float
    h: float


class Privacy(BaseModel):
    """Zone ascunse pe un clip: dreptunghiuri fixe (număr de mașină, ecran, logo) și/sau fețele (urmărite)."""
    boxes: list[Box] = []
    faces: bool = False                    # masca fețelor: Timeline.face_masks[asset] (privacy.py)
    style: Literal["blur", "pixel"] = "blur"


class Clip(BaseModel):
    """Un segment din sursă pe pista V1.

    `asset` e sursa de SUNET și de timp (transcript, tăieturi). Cu multicam, imaginea poate veni din alt unghi
    (`angle`) sau din două (`split`); timpul unghiului se calculează prin Timeline.sync."""
    id: str
    asset: str
    src_in: float
    src_out: float
    crop: Crop = Field(default_factory=Crop)
    volume_db: float = 0.0
    transition: Transition | None = None
    anim: ZoomAnim | None = None
    speed: float = 1.0                     # 0.25-4; sunetul își păstrează tonul (atempo)
    freeze: float = 0.0                    # secunde de freeze frame pe ultimul cadru, după clip (fără sunet)
    angle: str | None = None               # multicam: imaginea din alt asset (același moment)
    split: Split | None = None             # multicam: două unghiuri în același cadru
    fx: list[Literal[EFFECTS]] = []        # type: ignore[valid-type]
    bg: Background | None = None           # fundal înlocuit în spatele persoanei (fără green screen)
    privacy: Privacy | None = None         # blur / pixelare pe zone sau pe fețe

    @property
    def body(self) -> float:
        """Durata părții în mișcare (fără freeze), pe timeline."""
        return (self.src_out - self.src_in) / self.speed

    @property
    def duration(self) -> float:
        return self.body + self.freeze

    def src_at(self, dt: float) -> float:
        """Timpul sursă pentru `dt` secunde de la începutul clipului pe timeline."""
        return min(self.src_in + max(dt, 0) * self.speed, self.src_out)

    def tl_at(self, start: float, t_src: float) -> float:
        """Timpul de timeline pentru momentul `t_src` din sursă (clipul începe la `start`)."""
        return start + (t_src - self.src_in) / self.speed

    @property
    def video_assets(self) -> list[str]:
        if self.split:
            return list(self.split.angles)
        return [self.angle or self.asset]


GRAPHICS = ("lower_third", "title_card", "callout", "counter", "progress_bar", "cta", "list", "kinetic", "circle")


class Graphic(BaseModel):
    """Motion graphics: șabloane animate (libass), deasupra imaginii, sub subtitrări. Timp de montaj."""
    id: str
    kind: Literal[GRAPHICS]                # type: ignore[valid-type]
    start: float
    end: float
    text: str = ""                         # titlu / nume / text principal
    subtext: str = ""                      # rol, subtitlu, text secundar
    position: Literal["top", "center", "bottom", "lower_left", "lower_right", "upper_left", "upper_right"] = "center"
    x: float = 0.5                         # callout / circle: punctul vizat, normalizat 0..1
    y: float = 0.5
    size: float = 0.12                     # circle: raza, fracție din latura mică
    value_from: float = 0.0                # counter
    value_to: float = 0.0
    decimals: int = 0
    prefix: str = ""                       # counter: „$”, „+”
    suffix: str = ""                       # counter: „%”, „ lei”
    items: list[str] = []                  # list: rândurile, apar pe rând
    color: Hex | None = None               # #RRGGBB accent; implicit highlight-ul brandului sau lime
    behind: bool = False                   # textul trece prin spatele persoanei (cere masca, vezi segment.py)

    @property
    def duration(self) -> float:
        return self.end - self.start


SFX_KINDS = ("whoosh", "pop", "click", "impact", "riser", "ding", "swipe", "bass_drop", "bleep")


class Chapter(BaseModel):
    start: float                           # timp de montaj
    title: str


class Sfx(BaseModel):
    """Efect sonor la un moment de pe timeline: preset sintetizat (SFX_KINDS) sau un asset audio urcat."""
    id: str
    kind: str                              # un nume din SFX_KINDS sau id de asset (a3)
    at: float
    volume_db: float = -8.0
    dur: float | None = None               # tăiat la atâtea secunde (ex. bleep-ul cât cuvântul cenzurat)


class Caption(BaseModel):
    start: float
    end: float
    text: str
    # durate per cuvânt (secunde), pentru stilul karaoke
    word_durs: list[float] | None = None
    speaker: str | None = None
    word_ids: list[str] | None = None  # „a0:w12” pentru fiecare cuvânt (evidențiere, sincronizare cu transcriptul)


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


class Visualizer(BaseModel):
    """Unda sunetului animată peste imagine (audiogram): bare de frecvență, undă sau linie."""
    style: Literal["bars", "wave", "line"] = "wave"
    color: Hex = "#FFFFFF"
    position: Literal["top", "center", "bottom"] = "bottom"
    height: float = 0.22                   # fracție din înălțimea cadrului


class Narration(BaseModel):
    """Voice-over pe pista A3 (vedit/tts.py sau o înregistrare urcată): pornește la `start` pe montaj, peste
    imaginea de pe V1. Muzica se coboară sub ea (ducking), ca sub orice voce."""
    asset: str
    start: float = 0.0
    volume_db: float = 0.0


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
    chroma: Hex | None = None  # #RRGGBB: fundalul de scos (green screen); se vede montajul de dedesubt

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
    primary: Hex | None = None    # #RRGGBB: textul subtitrărilor (la karaoke: cuvintele încă nespuse)
    highlight: Hex | None = None  # #RRGGBB: cuvântul curent la karaoke
    outline: Hex | None = None    # #RRGGBB: conturul textului
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
    fill: Literal["crop", "pad", "blur"] = "crop"  # blur = clipul întreg peste o copie mărită și încețoșată
    clips: list[Clip] = []
    captions: list[Caption] = []
    caption_style: str = "bold_center"
    caption_font: str | None = None  # fontul brandului; implicit cel al stilului (vedit/fonts)
    caption_speaker_colors: bool = False  # culoare diferită per vorbitor (podcast / interviu)
    emphasis: list[str] = []       # cuvinte-cheie evidențiate în subtitrări („a0:w12”); rămân după captions_add
    emphasis_color: Hex | None = None  # #RRGGBB; implicit highlight-ul brandului sau galben
    emphasis_scale: float = 1.25
    texts: list[TextOverlay] = []
    music: Music | None = None
    narration: Narration | None = None
    visualizer: Visualizer | None = None
    loudness_lufs: float = -14.0  # -14 pt TikTok/YT/IG
    grades: dict[str, Grade] = {}  # asset -> grading
    broll: list[BRoll] = []        # pista V2
    audio_fx: dict[str, dict] = {}  # asset -> {"preset", "noise_db"} curățare audio (vezi vedit.audiofx)
    brand: Brand = Field(default_factory=Brand)
    graphics: list[Graphic] = []   # motion graphics (vedit/graphics.py)
    sfx: list[Sfx] = []            # efecte sonore
    sync: dict[str, float] = {}    # multicam: timp_asset = timp_referință + sync[asset] (vezi multicam.py)
    stabilized: dict[str, str] = {}  # asset -> fișier stabilizat (vidstab), folosit la randare în locul sursei
    mattes: dict[str, str] = {}      # asset -> masca persoanei (video gri, segment.py), pentru Clip.bg
    face_masks: dict[str, str] = {}  # asset -> masca fețelor de ascuns (video gri, privacy.py), Clip.privacy
    chapters: list[Chapter] = []   # capitole YouTube (descriere) și, opțional, title_card la fiecare

    def angle_time(self, clip: Clip, angle: str, t_src: float) -> float:
        """Momentul `t_src` din clip.asset, exprimat în timpul lui `angle` (multicam)."""
        if angle == clip.asset:
            return t_src
        if angle not in self.sync or clip.asset not in self.sync:
            raise ValueError(f"{angle} nu e sincronizat cu {clip.asset}: rulează multicam_sync")
        return t_src - self.sync[clip.asset] + self.sync[angle]

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
        return [c.tl_at(s, t) for c, s in zip(self.clips, self.starts())
                if c.asset == asset and c.src_in <= t < c.src_out]

    def view(self) -> str:
        """Rezumat compact pentru LLM (≈1 linie/clip)."""
        head = (f"{self.width}x{self.height}@{self.fps:g} fill={self.fill} dur={self.duration:.2f}s "
                f"clips={len(self.clips)} captions={len(self.captions)} style={self.caption_style}"
                f" texts={len(self.texts)} music={self.music.asset if self.music else '-'}"
                f" grading={','.join(self.grades) or '-'} broll={len(self.broll)} gfx={len(self.graphics)}"
                f" sfx={len(self.sfx)}")
        rows = []
        for c, s in zip(self.clips, self.starts()):
            extra = ""
            if c.crop != Crop():
                extra += f" crop=({c.crop.cx:.2f},{c.crop.cy:.2f},x{c.crop.zoom:g})"
            if c.transition:
                extra += f" ←{c.transition.type} {c.transition.duration:g}s"
            if c.anim:
                extra += f" zoom {c.anim.zoom_from:g}→{c.anim.zoom_to:g} {c.anim.ease}"
            if c.speed != 1:
                extra += f" {c.speed:g}x"
            if c.freeze:
                extra += f" freeze {c.freeze:g}s"
            if c.angle:
                extra += f" cam={c.angle}"
            if c.split:
                extra += f" split-{c.split.mode}={'+'.join(c.split.angles)}"
            if c.fx:
                extra += f" fx={','.join(c.fx)}"
            if c.bg:
                extra += f" fundal={c.bg.mode}{':' + c.bg.value if c.bg.value else ''}"
            if c.privacy:
                what = (["fețe"] if c.privacy.faces else []) + ([f"{len(c.privacy.boxes)} zone"] if c.privacy.boxes else [])
                extra += f" {c.privacy.style}={'+'.join(what)}"
            if c.volume_db <= -90:
                extra += " mut"
            elif c.volume_db:
                extra += f" vol={c.volume_db:+g}dB"
            rows.append(f"{c.id} @{s:.2f}-{s + c.duration:.2f} {c.asset}[{c.src_in:.2f}-{c.src_out:.2f}]{extra}")
        for b in sorted(self.broll, key=lambda b: b.start):
            pip = f" pip-{b.pip_pos}" if b.mode == "pip" else ""
            key = f" chroma={b.chroma}" if b.chroma else ""
            rows.append(f"V2 {b.id} @{b.start:.2f}-{b.end:.2f} {b.asset}[{b.src_in:.2f}-{b.src_in + b.duration:.2f}]{pip}{key}")
        for g in sorted(self.graphics, key=lambda g: g.start):
            label = g.text or ", ".join(g.items) or (f"{g.prefix}{g.value_from:g}→{g.value_to:g}{g.suffix}"
                                                     if g.kind == "counter" else "")
            rows.append(f"GFX {g.id} @{g.start:.2f}-{g.end:.2f} {g.kind} {label[:40]!r}")
        if self.sfx:
            rows.append("SFX " + " ".join(f"{x.id}:{x.kind}@{x.at:.2f}" for x in sorted(self.sfx, key=lambda x: x.at)))
        if self.sync:
            rows.append("sync " + " ".join(f"{a}{o:+.3f}s" for a, o in self.sync.items()))
        if self.stabilized:
            rows.append("stabilizat: " + ", ".join(self.stabilized))
        if self.narration:
            rows.append(f"A3 voice-over {self.narration.asset} de la {self.narration.start:.2f}s")
        if self.visualizer:
            rows.append(f"VIZ undă {self.visualizer.style} {self.visualizer.color} ({self.visualizer.position})")
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
            # nu lăsa bucăți mai scurte de 2 cadre (nu se văd, iar sub un cadru blochează randarea)
            if s + 2 / self.fps < t < s + c.body - 2 / self.fps:
                cut = round(c.src_at(t - s), 3)
                right = c.model_copy(deep=True)
                right.id = self._new_id()
                right.src_in = cut
                right.transition = None  # tăietura nouă e dură
                c.src_out = cut
                c.freeze = 0.0           # freeze-ul rămâne la finalul clipului original (partea dreaptă)
                if c.anim:               # zoom-ul animat pornește din nou pe fiecare bucată
                    right.anim = c.anim.model_copy()
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


# ---------------------------------------------------------------- ripple: suprapunerile urmează tăieturile
def _layout(tl: Timeline) -> list[tuple]:
    return [(c.asset, c.src_in, c.src_out, c.speed, c.freeze) for c in tl.clips]


def _source_at(tl: Timeline, t: float) -> tuple[str, float] | None:
    for c, s in zip(tl.clips, tl.starts()):
        if s <= t < s + c.duration:
            return c.asset, c.src_at(t - s)
    return None


def _map(old: Timeline, new: Timeline, t: float) -> float | None:
    src = _source_at(old, t)
    if src is None:
        return None
    found = new.source_to_timeline(*src)
    return min(found, key=lambda x: abs(x - t)) if found else None


def _scan(old: Timeline, new: Timeline, a: float, b: float, forward: bool) -> tuple[float, float] | None:
    """Primul moment din [a, b) (de la început sau de la sfârșit) care încă există în montajul nou.
    Întoarce (timpul vechi, timpul nou)."""
    step = 0.04
    n = max(1, int((b - a) / step))
    for k in range(n + 1):
        t = a + k * step if forward else b - 0.001 - k * step
        if not a - 1e-9 <= t < b + 1e-9:
            continue
        m = _map(old, new, t)
        if m is not None:
            return t, m
    return None


def ripple(old: Timeline, new: Timeline) -> None:
    """După o modificare a clipurilor, mută subtitrările, textele, graficele, B-roll-ul, efectele sonore și capitolele
    odată cu sursa lor: ce era peste un cuvânt rămâne peste același cuvânt; ce a fost tăiat complet dispare.
    Listele pe care operația le-a schimbat ea însăși nu se ating (au fost deja calculate pe montajul nou)."""
    if _layout(old) == _layout(new) or not old.clips or not new.clips:
        return

    def span(a: float, b: float, min_len: float = 0.1):
        x, y = _scan(old, new, a, b, True), _scan(old, new, a, b, False)
        if not x or not y or y[1] + 0.001 - x[1] < min_len:
            return None
        return x, (y[0], y[1] + 0.001)

    if new.captions == old.captions:
        out = []
        for c in old.captions:
            r = span(c.start, c.end, 0.05)
            if r:
                out.append(c.model_copy(update={"start": round(r[0][1], 3), "end": round(r[1][1], 3)}))
        new.captions = out
    if new.texts == old.texts:
        new.texts = [x.model_copy(update={"start": round(r[0][1], 3), "end": round(r[1][1], 3)})
                     for x in old.texts if (r := span(x.start, x.end))]
    if new.graphics == old.graphics:
        new.graphics = [g.model_copy(update={"start": round(r[0][1], 3), "end": round(r[1][1], 3)})
                        for g in old.graphics if (r := span(g.start, g.end, 0.5))]
    if new.broll == old.broll:
        out = []
        for b in old.broll:
            r = span(b.start, b.end, 0.3)
            if r:  # sursa B-roll-ului avansează cu cât s-a tăiat din începutul lui
                out.append(b.model_copy(update={"start": round(r[0][1], 3), "duration": round(r[1][1] - r[0][1], 3),
                                                "src_in": round(b.src_in + r[0][0] - b.start, 3)}))
        new.broll = out
    if new.sfx == old.sfx:
        new.sfx = [x.model_copy(update={"at": round(m, 3)}) for x in old.sfx
                   if (m := _map(old, new, x.at)) is not None]
    if new.chapters == old.chapters and old.chapters:
        out = [old.chapters[0]]
        for c in old.chapters[1:]:
            m = _map(old, new, c.start)
            if m is not None and m - out[-1].start >= 1:
                out.append(c.model_copy(update={"start": round(m, 2)}))
        new.chapters = out
