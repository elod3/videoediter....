"""Proiect = asset-uri + cache de analize + timeline + istoric (undo).

Toate operațiile de nivel înalt pe care le apelează agentul trăiesc aici;
serverul MCP și CLI-ul sunt doar învelișuri subțiri peste această clasă.
Starea stă pe disc => agentul nu trebuie să țină timeline-ul în context.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel

from . import analyze, reframe as rf
from .captions import STYLES, build_captions
from .edit_ops import EditOps
from .probe import MediaInfo, probe
from .render import render
from .timeline import FORMATS, Crop, Music, TextOverlay, Timeline
from .transcribe import Transcript, transcribe

MAX_HISTORY = 50


def zip_longest_all(groups):
    """Intercalează listele: a0 b0 c0 a1 b1 ... (sursele alternează în montaj)."""
    from itertools import zip_longest

    return zip_longest(*groups)


def home() -> Path:
    return Path(os.environ.get("VEDIT_HOME", "./vedit_projects")).resolve()


def _new_id_simple(prefix: str, used: set[str]) -> str:
    n = 0
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


class ProjectState(BaseModel):
    name: str
    assets: dict[str, MediaInfo] = {}
    timeline: Timeline = Timeline()
    history: list[Timeline] = []
    future: list[Timeline] = []  # pașii anulați, pentru redo; o editare nouă îi șterge
    roles: dict[str, str] = {}  # asset -> "reference" (clip de referință: stil, culoare; nu intră în montaj)
    meta: dict[str, dict] = {}  # asset -> proveniență (stock / generat): sursă, autor, prompt, provider


class Project(EditOps):
    def __init__(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("numele proiectului: doar litere, cifre, _ și -")
        self.dir = home() / name
        self.file = self.dir / "project.json"
        if self.file.exists():
            self.s = ProjectState.model_validate_json(self.file.read_text())
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.s = ProjectState(name=name)
            self.save()
        (self.dir / "cache").mkdir(exist_ok=True)
        (self.dir / "renders").mkdir(exist_ok=True)

    # ---------- infrastructură ----------
    @property
    def tl(self) -> Timeline:
        return self.s.timeline

    def save(self) -> None:
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(self.s.model_dump_json())
        tmp.replace(self.file)

    @contextmanager
    def edit(self):
        """Orice modificare de timeline trece pe aici => undo gratuit + salvare atomică."""
        snapshot = self.tl.model_copy(deep=True)
        try:
            yield self.tl
            self._ripple(snapshot, self.tl)
        except Exception:
            self.s.timeline = snapshot  # operație eșuată => starea rămâne neatinsă
            raise
        self.s.history = (self.s.history + [snapshot])[-MAX_HISTORY:]
        self.s.future = []
        self.save()

    def _ripple(self, old: Timeline, new: Timeline) -> None:
        """Suprapunerile urmează tăieturile (timeline.ripple). Subtitrările făcute din transcript se refac exact,
        cuvânt cu cuvânt, cu același stil (evidențierile rămân)."""
        from .timeline import _layout, ripple

        if _layout(old) == _layout(new):
            return
        rebuild = None
        if old.captions and new.captions == old.captions:
            assets = {w.split(":")[0] for c in old.captions for w in (c.word_ids or [])}
            if len(assets) == 1 and all(c.word_ids for c in old.captions):
                rebuild = assets.pop()
        ripple(old, new)
        if rebuild and (self.dir / "cache" / f"{rebuild}.transcript.json").exists():
            build_captions(new, rebuild, self.transcript(rebuild), style=new.caption_style)

    def undo(self) -> str:
        if not self.s.history:
            return "nimic de anulat"
        self.s.future = (self.s.future + [self.tl])[-MAX_HISTORY:]
        self.s.timeline = self.s.history.pop()
        self.save()
        return self.tl.view()

    def redo(self) -> str:
        if not self.s.future:
            return "nimic de refăcut"
        self.s.history = (self.s.history + [self.tl])[-MAX_HISTORY:]
        self.s.timeline = self.s.future.pop()
        self.save()
        return self.tl.view()

    def _asset(self, aid: str) -> MediaInfo:
        if aid not in self.s.assets:
            raise KeyError(f"asset inexistent: {aid}. Disponibile: {', '.join(self.s.assets) or '-'}")
        return self.s.assets[aid]

    def _cache(self, aid: str, kind: str, fn):
        f = self.dir / "cache" / f"{aid}.{kind}.json"
        if f.exists():
            return json.loads(f.read_text())
        val = fn()
        f.write_text(json.dumps(val))
        return val

    # ---------- asset-uri ----------
    IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
    STILL_SECONDS = 60.0

    def _still_video(self, path: str) -> str:
        """Poză -> clip video fix (60 s, 30 fps). Tot restul toolkit-ului (încadrare, fețe, zoom animat, grading,
        B-roll) lucrează apoi cu ea ca un clip obișnuit; din clip se folosește doar cât trebuie."""
        from .ff import run

        src = Path(path)
        out = self.dir / "uploads" / f"{src.stem}.still.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            tmp = out.with_name(f".{out.name}")
            # latura mare maxim 3840, dimensiuni pare (libx264 / yuv420p)
            vf = ("scale='min(3840,iw)':'min(3840,ih)':force_original_aspect_ratio=decrease,"
                  "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p")
            run(["-y", "-loop", "1", "-framerate", "30", "-t", f"{self.STILL_SECONDS:g}", "-i", os.path.abspath(src),
                 "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage", "-crf", "16",
                 "-r", "30", str(tmp)], timeout=300)
            tmp.replace(out)
        return str(out)

    def add_asset(self, path: str, asset_id: str | None = None) -> str:
        image = Path(path).suffix.lower() in self.IMAGE_EXT
        src = self._still_video(path) if image else path
        info = probe(os.path.abspath(src))
        aid = asset_id or self._next_asset_id()
        self.s.assets[aid] = info
        if image:
            self.s.meta[aid] = {"source": "image", "file": Path(path).name}
        self.save()
        note = " — POZĂ (clip fix de 60 s: folosește doar cât îți trebuie; zoom_animate pentru mișcare)" if image else ""
        return f"{aid}: {Path(path).name} ({info.summary()}){note}"

    def _next_asset_id(self) -> str:
        """a0, a1, ...: după cel mai mare număr folosit (un asset șters nu-și lasă id-ul unui fișier nou)."""
        nums = [int(k[1:]) for k in self.s.assets if re.fullmatch(r"a\d+", k)]
        n = max(nums, default=-1) + 1
        while f"a{n}" in self.s.assets:
            n += 1
        return f"a{n}"

    @staticmethod
    def _uses(tl: Timeline, aid: str) -> bool:
        """True dacă timeline-ul pomenește asset-ul (clip, B-roll, muzică, sfx, chei de grading, cuvinte a0:w12...)."""
        def walk(v) -> bool:
            if isinstance(v, str):
                return v == aid or v.startswith(aid + ":")
            if isinstance(v, dict):
                return aid in v or any(walk(x) for x in v.values())
            if isinstance(v, (list, tuple)):
                return any(walk(x) for x in v)
            return False
        return walk(tl.model_dump())

    def remove_asset(self, aid: str) -> str:
        """Scoate un fișier din proiect. Refuză dacă montajul curent îl folosește; pașii de undo care îl
        folosesc se pierd (altfel un undo ar aduce înapoi un clip fără fișier)."""
        m = self._asset(aid)
        image = (self.s.meta.get(aid) or {}).get("source") == "image" and (self.s.meta[aid].get("file") or "")
        if self._uses(self.tl, aid):
            raise ValueError(f"{aid} e folosit în montaj; scoate-l întâi de pe timeline")
        keep = len(self.s.history)
        for i in range(len(self.s.history) - 1, -1, -1):
            if self._uses(self.s.history[i], aid):
                keep = len(self.s.history) - 1 - i
                break
        self.s.history = self.s.history[len(self.s.history) - keep:] if keep else []
        if any(self._uses(t, aid) for t in self.s.future):
            self.s.future = []
        del self.s.assets[aid]
        self.s.roles.pop(aid, None)
        self.s.meta.pop(aid, None)
        self.save()
        cache = self.dir / "cache"
        for f in [*cache.glob(f"{aid}.*"), *cache.glob(f"{aid}_*")]:
            f.unlink(missing_ok=True)
        uploads = (self.dir / "uploads").resolve()
        for f in (Path(m.path), uploads / image if image else None):
            if f and f.resolve().parent == uploads:  # fișierele din afara proiectului nu se ating
                f.resolve().unlink(missing_ok=True)
        return f"{aid} scos din proiect"

    def list_assets(self) -> str:
        tag = {"reference": " [REFERINȚĂ: doar pentru stil, nu o pune în timeline]",
               "broll": " [B-ROLL: pentru pista V2 (broll_add), nu pentru V1]",
               "brand": " [BRAND: intro/outro, se lipește singur la randare]"}
        return "\n".join(f"{k}: {Path(v.path).name} ({v.summary()}){tag.get(self.s.roles.get(k, ''), '')}"
                         for k, v in self.s.assets.items()) or "-"

    def set_role(self, aid: str, role: str) -> str:
        self._asset(aid)
        if role not in ("reference", "broll", "source", ""):
            raise ValueError("rol: reference, broll sau source")
        if role in ("reference", "broll"):
            self.s.roles[aid] = role
        else:
            self.s.roles.pop(aid, None)
        self.save()
        return self.list_assets()

    def references(self) -> list[str]:
        return [k for k, r in self.s.roles.items() if r == "reference" and k in self.s.assets]

    def brolls(self) -> list[str]:
        return [k for k, r in self.s.roles.items() if r == "broll" and k in self.s.assets]

    # ---------- muzică: beat-uri ----------
    def beats(self, aid: str):
        from .beats import Beats, detect

        m = self._asset(aid)
        if not m.has_audio:
            raise ValueError(f"{aid} nu are audio")
        return Beats(**self._cache(aid, "beats", lambda: detect(m.path).model_dump()))

    def _timeline_beats(self) -> list[float]:
        """Beat-urile muzicii din timeline, în timp de timeline."""
        if not self.tl.music:
            return []
        off = self.tl.music.src_in
        return [b - off for b in self.beats(self.tl.music.asset).beats if b - off >= 0]

    # ---------- B-roll (pista V2) ----------
    def broll_add(self, aid: str, at: float, duration: float, src_in: float = 0.0, mode: str = "full",
                  pip_pos: str = "tr", snap: bool = False, frame: str = "", scale: float = 0.38) -> str:
        from .timeline import BRoll

        if frame not in ("", "rounded", "phone", "laptop"):
            raise ValueError("frame: rounded, phone, laptop sau gol")
        if not 0.15 <= scale <= 1.0:
            raise ValueError("scale între 0.15 și 1.0")
        if frame and mode == "full":
            mode = "pip"  # o ramă e mereu o fereastră peste montaj

        m = self._asset(aid)
        if not m.has_video:
            raise ValueError(f"{aid} nu are video")
        if self.s.roles.get(aid) == "reference":
            raise ValueError(f"{aid} e referință, nu B-roll")
        if at >= self.tl.duration:
            raise ValueError(f"at={at} e după finalul montajului ({self.tl.duration:.2f}s)")
        if snap:  # începutul și finalul pe beat-urile muzicii
            beats = self._timeline_beats()
            if not beats:
                raise ValueError("snap cere muzică în timeline (music_set)")
            s = min(beats, key=lambda b: abs(b - at))
            e = min(beats, key=lambda b: abs(b - (at + duration)))
            at, duration = s, max(e - s, 0.3)
        duration = min(duration, m.duration - src_in, self.tl.duration - at)
        if duration <= 0.1:
            raise ValueError("B-roll prea scurt (verifică src_in și durata sursei)")
        with self.edit() as tl:
            used = {b.id for b in tl.broll}
            n = len(tl.broll)
            while f"b{n}" in used:
                n += 1
            tl.broll.append(BRoll(id=f"b{n}", asset=aid, src_in=round(src_in, 3), start=round(at, 3),
                                  duration=round(duration, 3), mode=mode, pip_pos=pip_pos, frame=frame,
                                  pip_scale=round(scale, 3)))
        return self.tl.view()

    def _aspect(self) -> str:
        w, h = self.tl.width, self.tl.height
        return "9:16" if h > w * 1.2 else "16:9" if w > h * 1.2 else "1:1"

    def broll_stock(self, query: str, count: int = 2, min_duration: float = 3.0) -> str:
        """Footage real, gratuit, de pe Pexels. Descarcă cele mai potrivite clipuri și le marchează [B-ROLL]."""
        from .sources import download, pexels_search

        orient = {"9:16": "portrait", "16:9": "landscape", "1:1": "square"}[self._aspect()]
        found = pexels_search(query, orient, per_page=max(count * 3, 6), min_duration=min_duration)
        if not found:
            return f"nimic pe Pexels pentru „{query}” ({orient}); încearcă alt cuvânt, în engleză"
        added = []
        for item in found[:count]:
            dest = self.dir / "broll" / f"pexels_{item['id']}.mp4"
            if not dest.exists():
                download(item["url"], dest)
            aid = next((k for k, v in self.s.assets.items() if Path(v.path) == dest.resolve()), None)
            if aid is None:
                aid = self.add_asset(str(dest)).split(":")[0]
            self.s.roles[aid] = "broll"
            self.s.meta[aid] = {"source": "pexels", "query": query, "page": item["page"], "author": item["author"]}
            added.append(f"{aid}: {item['duration']}s {item['width']}x{item['height']} de {item['author'] or '?'}")
        self.save()
        return f"B-roll stock pentru „{query}” (Pexels, licență gratuită):\n" + "\n".join(added)

    def broll_generate(self, prompt: str, duration: float = 5.0) -> str:
        """Generează un clip B-roll cu un model video prin API. COSTĂ BANI: doar dacă a fost cerut explicit."""
        from .sources import download, generate

        limit = int(os.environ.get("VEDIT_GEN_LIMIT", "3"))
        done = sum(1 for m in self.s.meta.values() if m.get("source") == "generated")
        if done >= limit:
            raise ValueError(f"limita de generări pe proiect atinsă ({limit}); crește VEDIT_GEN_LIMIT dacă e intenționat")
        url, prov = generate(prompt, duration, self._aspect())
        dest = self.dir / "broll" / f"gen_{done + 1}.mp4"
        download(url, dest)
        aid = self.add_asset(str(dest)).split(":")[0]
        self.s.roles[aid] = "broll"
        self.s.meta[aid] = {"source": "generated", "provider": prov, "prompt": prompt}
        self.save()
        m = self._asset(aid)
        return f"{aid}: generat cu {prov} ({m.summary()}). Generări folosite: {done + 1}/{limit}."

    def broll_remove(self, bid: str = "all") -> str:
        with self.edit() as tl:
            if bid == "all":
                tl.broll = []
            else:
                if not any(b.id == bid for b in tl.broll):
                    raise KeyError(f"B-roll inexistent: {bid}")
                tl.broll = [b for b in tl.broll if b.id != bid]
        return self.tl.view()

    def beat_montage(self, music: str, sources: str = "all", beats_per_shot: int = 2, max_duration: float = 0.0,
                     start_beat: int = 0, keep_audio: bool = False) -> str:
        """Montaj pe beat: fiecare shot durează exact N beat-uri, tăieturile cad pe lovituri."""
        from .timeline import Music

        bt = self.beats(music)
        beats = bt.beats[start_beat:]
        if len(beats) < beats_per_shot + 1:
            raise ValueError("prea puține beat-uri în piesă")
        srcs = ([k for k, v in self.s.assets.items() if v.has_video and self.s.roles.get(k) not in ("reference", "brand")]
                if sources == "all" else re.split(r"[,\s]+", sources.strip()))
        for s in srcs:
            if not self._asset(s).has_video:
                raise ValueError(f"{s} nu are video")
        # shot-urile surselor: tăieturile de scenă împart fiecare sursă; intercalăm sursele
        per_src = []
        for s in srcs:
            m = self._asset(s)
            cuts = self._cache(s, "scenes_0.3", lambda m=m: analyze.scenes(m.path, 0.3))
            edges = [0.0, *[c for c in cuts if 0.3 < c < m.duration - 0.3], m.duration]
            per_src.append([(s, a + 0.08, b) for a, b in zip(edges, edges[1:]) if b - a > 0.4])
        shots = [x for group in zip_longest_all(per_src) for x in group if x]
        if not shots:
            raise ValueError("sursele nu au footage utilizabil")
        slots = [(beats[i], beats[i + beats_per_shot]) for i in range(0, len(beats) - beats_per_shot, beats_per_shot)]
        t0 = beats[0]
        if max_duration > 0:
            slots = [sl for sl in slots if sl[1] - t0 <= max_duration + 1e-3] or slots[:1]
        used = [0.0] * len(shots)   # cât s-a consumat din fiecare shot (nu repetăm aceleași cadre)
        cursor = [0]

        def pick(need: float) -> tuple[str, float]:
            for _ in range(len(shots)):
                j = cursor[0] % len(shots)
                cursor[0] += 1
                s, st, en = shots[j]
                if en - (st + used[j]) >= need:
                    off = used[j]
                elif en - st >= need:        # shot consumat: îl reluăm de la început
                    off = 0.0
                else:
                    continue                 # shot prea scurt pentru slot
                used[j] = off + need
                return s, st + off
            j = max(range(len(shots)), key=lambda i: shots[i][2] - shots[i][1])  # niciunul nu ajunge
            return shots[j][0], shots[j][1]

        with self.edit() as tl:
            tl.clips, tl.captions, tl.broll = [], [], []
            for a, b in slots:
                s, st = pick(b - a)
                c = tl.add_clip(s, st, min(st + (b - a), self._asset(s).duration))
                if not keep_audio:
                    c.volume_db = -99
            tl.music = Music(asset=music, volume_db=0.0, duck=keep_audio, src_in=round(t0, 3))
        return (f"montaj pe beat: {bt.bpm:.1f} BPM, {len(slots)} shot-uri x {beats_per_shot} beat-uri, "
                f"{self.tl.duration:.2f}s, muzica pornește de la {t0:.2f}s\n{self.tl.view()}")

    # ---------- analiză ----------
    def analyze(self, aid: str, noise_db: float = -35, min_silence: float = 0.4, scene_threshold: float = 0.3) -> dict:
        m = self._asset(aid)
        out: dict = {"asset": aid, "duration": m.duration}
        if m.has_audio:
            sil = self._cache(aid, f"silence_{noise_db}_{min_silence}",
                              lambda: analyze.silences(m.path, noise_db, min_silence))
            out["silence_total"] = round(sum(b - a for a, b in sil), 2)
            out["silences"] = [[round(a, 2), round(b, 2)] for a, b in sil]
            out["loudness"] = self._cache(aid, "loudness", lambda: analyze.loudness(m.path))
        if m.has_video:
            out["scene_cuts"] = self._cache(aid, f"scenes_{scene_threshold}",
                                            lambda: analyze.scenes(m.path, scene_threshold))
            out["black"] = self._cache(aid, "black", lambda: analyze.black_frames(m.path))
        return out

    def transcript(self, aid: str, model: str = "small", language: str | None = None) -> Transcript:
        m = self._asset(aid)
        data = self._cache(aid, "transcript", lambda: transcribe(m.path, model, language).model_dump())
        tr = Transcript.model_validate(data)
        diar = self._diar(aid)
        if diar:
            tr.label_speakers(diar)
        return tr

    def set_transcript(self, aid: str, tr: Transcript) -> None:
        """Pentru transcrieri externe (API cloud) sau teste."""
        self._asset(aid)
        (self.dir / "cache" / f"{aid}.transcript.json").write_text(tr.model_dump_json())

    # ---------- diarizare (cine vorbește când, din audio) ----------
    def _diar(self, aid: str):
        from .diarize import Diarization

        f = self.dir / "cache" / f"{aid}.diarization.json"
        return Diarization.model_validate_json(f.read_text()) if f.exists() else None

    def diarization(self, aid: str, num_speakers: int = 0, min_speakers: int = 0, max_speakers: int = 0):
        from .diarize import diarize

        m = self._asset(aid)
        if not m.has_audio:
            raise ValueError(f"{aid} nu are audio")
        d = self._diar(aid)
        if d is None:
            d = diarize(m.path, num_speakers or None, min_speakers or None, max_speakers or None)
            self.set_diarization(aid, d)
        return d

    def set_diarization(self, aid: str, d) -> None:
        """Pentru diarizare externă (API cloud) sau teste. Invalidează legătura vorbitor→față."""
        self._asset(aid)
        (self.dir / "cache" / f"{aid}.diarization.json").write_text(d.model_dump_json())
        (self.dir / "cache" / f"{aid}.speaker_faces.json").unlink(missing_ok=True)

    def speaker_faces(self, aid: str) -> dict[str, dict]:
        """Leagă fiecare vorbitor audio (A, B..) de o față: votează pe replicile lui cea mai activă gură."""
        from statistics import median

        from .speaker import activity

        m = self._asset(aid)
        d = self._diar(aid)
        if d is None or not m.has_video:
            return {}

        def compute() -> dict:
            out = {}
            for sp in d.speakers():
                turns = sorted((t for t in d.turns if t.speaker == sp and t.end - t.start >= 1.2),
                               key=lambda t: t.start - t.end)[:8]
                votes: list[tuple[float, float]] = []
                for t in turns:
                    a = activity(m.path, m.width, m.height, t.start, min(t.end, t.start + 4.0))
                    means = sorted(((sum(v) / max(len(v), 1), tr) for tr in a["tracks"]
                                    for v in [a["act"][tr["id"]]]), key=lambda x: -x[0])
                    if not means or means[0][0] < 1e-3:
                        continue
                    if len(means) > 1 and means[0][0] < 1.3 * means[1][0]:
                        continue
                    votes.append((means[0][1]["cx"], means[0][1]["cy"]))
                if not votes:
                    continue
                mx = median(v[0] for v in votes)
                agree = [v for v in votes if abs(v[0] - mx) < 0.08]
                if len(agree) * 2 >= len(votes):
                    out[sp] = {"cx": round(median(v[0] for v in agree), 3), "cy": round(median(v[1] for v in agree), 3),
                               "votes": f"{len(agree)}/{len(votes)}"}
            return out

        return self._cache(aid, "speaker_faces", compute)

    def cut_speaker(self, aid: str, speaker: str, keep: bool = False) -> str:
        """Scoate tot ce spune un vorbitor (keep=False) sau păstrează DOAR vorbitorul (keep=True)."""
        from .diarize import speaker_spans

        d = self._diar(aid)
        if d is None:
            raise ValueError("rulează întâi diarize pe acest asset")
        speakers = set(d.speakers())
        if speaker not in speakers:
            raise KeyError(f"vorbitor necunoscut {speaker}; există: {', '.join(sorted(speakers))}")
        targets = sorted(speakers - {speaker}) if keep else [speaker]
        tr_file = self.dir / "cache" / f"{aid}.transcript.json"
        words = self.transcript(aid).words if tr_file.exists() else None
        spans = []
        for sp in targets:
            if words:  # aliniat la cuvinte => nu tai în mijlocul unui cuvânt
                spans += speaker_spans(words, sp)
            else:
                spans += [(t.start, t.end) for t in d.turns if t.speaker == sp]
        before = self.tl.duration
        with self.edit() as tl:
            if not tl.clips:
                tl.add_clip(aid, 0, self._asset(aid).duration)
            for a, b in spans:
                tl.remove_source_span(aid, a, b)
            tl.captions = []
        what = f"păstrat doar {speaker}" if keep else f"scos {speaker}"
        return f"{what}: {before:.2f}s -> {self.tl.duration:.2f}s ({len(spans)} intervale)\n{self.tl.view()}"

    def look(self, aid: str, start: float = 0, end: float | None = None, cols: int = 4, rows: int = 3) -> dict:
        """aid poate fi un asset sau 'render:<nume>' (ex. render:preview) pentru a verifica rezultatul."""
        if aid.startswith("render:"):
            f = self.dir / "renders" / f"{aid[7:]}.mp4"
            if not f.exists():
                raise FileNotFoundError(f"nu există render-ul {aid[7:]}; rulează render întâi")
            m = probe(str(f))
            aid = aid.replace(":", "_")
        else:
            m = self._asset(aid)
        out = self.dir / "cache" / f"{aid}_sheet_{start:g}_{end or 'end'}_{cols}x{rows}.png"
        times = analyze.contact_sheet(m.path, str(out), m.duration, cols, rows, start, end)
        return {"image": str(out), "cells_left_to_right_top_to_bottom": times}

    # ---------- stil & culoare ----------
    def _color_stats(self, aid: str) -> dict:
        from .style import color_stats

        m = self._asset(aid)
        if not m.has_video:
            raise ValueError(f"{aid} nu are video")
        return self._cache(aid, "color", lambda: color_stats(m.path, m.duration, m.width, m.height).model_dump())

    def style_profile(self, aid: str) -> dict:
        """Profilul măsurat al unui clip (de obicei referința): ritm, culoare, audio, format."""
        from .style import rhythm_from_cuts

        m = self._asset(aid)
        out: dict = {"asset": aid, "duration": m.duration,
                     "format": f"{m.width}x{m.height}" if m.has_video else "audio"}
        if m.has_video:
            ar = m.width / max(m.height, 1)
            out["aspect"] = "9:16" if ar < 0.7 else "4:5" if ar < 0.9 else "1:1" if ar < 1.2 else "16:9"
            cuts = self._cache(aid, "scenes_0.2", lambda: analyze.scenes(m.path, 0.2))
            out["rhythm"] = rhythm_from_cuts(cuts, m.duration).model_dump()
            out["color"] = self._color_stats(aid)
        if m.has_audio:
            out["lufs"] = self._cache(aid, "loudness", lambda: analyze.loudness(m.path))["lufs"]
            sil = self._cache(aid, "silence_-35_0.4", lambda: analyze.silences(m.path, -35, 0.4))
            out["silence_ratio"] = round(sum(b - a for a, b in sil) / max(m.duration, 1e-3), 3)
            if (self.dir / "cache" / f"{aid}.transcript.json").exists():
                words = self.transcript(aid).words
                out["words_per_sec"] = round(len(words) / max(m.duration, 1e-3), 2)
        return out

    def style_summary(self, aid: str) -> str:
        from .style import ColorStats, Rhythm

        d = self.style_profile(aid)
        lines = [f"{aid}: {d['format']} ({d.get('aspect', '-')}), {d['duration']:.1f} s"]
        if "rhythm" in d:
            lines.append("ritm: " + Rhythm(**d["rhythm"]).summary() + " (estimat din schimbările de imagine)")
        if "color" in d:
            lines.append("culoare: " + ColorStats(**d["color"]).summary())
        if "lufs" in d:
            audio = f"audio: {d['lufs']:.1f} LUFS · pauze {d['silence_ratio']:.0%} din durată"
            if "words_per_sec" in d:
                audio += f" · {d['words_per_sec']:.1f} cuvinte/s"
            lines.append(audio)
        lines.append("subtitrări, text pe ecran, B-roll: nu se măsoară automat; uită-te cu frames_look pe referință")
        return "\n".join(lines)

    def color_auto(self, aid: str = "all", strength: float = 0.7, warmth: float = 0.0) -> str:
        """Corecție automată și potrivire între clipuri: expunerea și contrastul spre mediana clipurilor (într-o zonă
        sănătoasă), dominanta de culoare scoasă (balans de alb), saturația egalizată. Toate ajung la aceeași țintă,
        deci clipurile filmate cu telefoane diferite arată ca dintr-o singură cameră. warmth: -1 rece .. +1 cald."""
        import statistics as stt

        from .style import ColorStats

        srcs = [a for a in self._video_sources(aid) if self.s.roles.get(a) != "broll" or aid != "all"]
        if not srcs:
            raise ValueError("nicio sursă video")
        stats = {a: ColorStats(**self._color_stats(a)) for a in srcs}
        med = lambda xs: stt.median(xs)  # noqa: E731
        L = min(max(med([s.mean[0] for s in stats.values()]), 46.0), 60.0)
        Ls = max(med([s.std[0] for s in stats.values()]), 17.0)
        cs = [max(med([s.std[i] for s in stats.values()]), 6.0) for i in (1, 2)]
        target = ColorStats(mean=[L, 0.0, 3.0 + 6.0 * warmth], std=[Ls, *cs], l_p5=8.0, l_p95=92.0,
                            chroma=med([s.chroma for s in stats.values()]))
        done = []
        for a in srcs:
            prev = self.tl.grades.get(a)
            self._bake_grade(a, None, strength, prev.adjust if prev else {}, prev.preset if prev else None,
                             target=target)
            done.append(f"{a}: {stats[a].summary()}")
        return (f"corecție automată ({strength:.0%}) spre: luminozitate {L:.0f}, contrast {Ls:.0f}, neutru"
                f"{' cald' if warmth > 0 else ' rece' if warmth < 0 else ''}\nînainte:\n" + "\n".join(done))

    def _bake_grade(self, aid: str, reference: str | None, strength: float, adjust: dict, preset: str | None,
                    target=None) -> str:
        import hashlib
        import json as _json

        from .style import PRESETS, Adjust, ColorStats, write_lut

        adj = Adjust(**{**(PRESETS[preset].model_dump() if preset else {}), **adjust})
        if reference == "auto":  # reaplicare (ex. color_grade după color_auto): aceeași țintă, salvată în grading
            prev = self.tl.grades.get(aid)
            target = ColorStats(**prev.target) if prev and prev.target else None
            reference = None
        src = ColorStats(**self._color_stats(aid)) if (reference or target is not None) else None
        ref = ColorStats(**self._color_stats(reference)) if reference else target
        key = _json.dumps([aid, reference, round(strength, 3), adj.model_dump(), src and src.mean,
                           target.model_dump() if target is not None else None], sort_keys=True)
        lut = self.dir / "luts" / f"{aid}_{hashlib.sha1(key.encode()).hexdigest()[:10]}.cube"
        if not lut.exists():
            write_lut(lut, src, ref, strength, adj)
        from .timeline import Grade

        with self.edit() as tl:
            tl.grades[aid] = Grade(lut=str(lut), reference=reference or ("auto" if target is not None else None),
                                   strength=strength, adjust=adjust, preset=preset,
                                   target=target.model_dump() if target is not None else {})
        return str(lut)

    def _video_sources(self, aid: str) -> list[str]:
        if aid != "all":
            self._asset(aid)
            return [aid]
        return [k for k, v in self.s.assets.items() if v.has_video and self.s.roles.get(k) not in ("reference", "brand")]

    def color_match(self, aid: str = "all", reference: str | None = None, strength: float = 0.8) -> str:
        reference = reference or next(iter(self.references()), None)
        if not reference:
            raise ValueError("nu există referință: marchează un clip cu asset_role(role='reference') sau dă reference=")
        out = []
        for a in self._video_sources(aid):
            if a == reference:
                continue
            prev = self.tl.grades.get(a)
            self._bake_grade(a, reference, strength, prev.adjust if prev else {}, prev.preset if prev else None)
            out.append(a)
        from .style import ColorStats

        ref = ColorStats(**self._color_stats(reference))
        return (f"grading potrivit cu {reference} pe {', '.join(out) or '-'} (putere {strength:.0%}).\n"
                f"ținta: {ref.summary()}")

    def color_grade(self, aid: str = "all", preset: str | None = None, **adjust) -> str:
        from .style import PRESETS

        if preset and preset not in PRESETS:
            raise ValueError(f"preset necunoscut; disponibile: {', '.join(PRESETS)}")
        adjust = {k: v for k, v in adjust.items() if v is not None}
        done = []
        for a in self._video_sources(aid):
            prev = self.tl.grades.get(a)
            self._bake_grade(a, prev.reference if prev else None, prev.strength if prev else 0.8,
                             {**(prev.adjust if prev else {}), **adjust}, preset or (prev.preset if prev else None))
            done.append(a)
        return f"grading actualizat pe {', '.join(done)}: preset={preset or '-'} {adjust or ''}".strip()

    def color_reset(self, aid: str = "all") -> str:
        with self.edit() as tl:
            for a in (list(tl.grades) if aid == "all" else [aid]):
                tl.grades.pop(a, None)
        return "grading scos"

    def style_compare(self, reference: str | None = None, render: str = "preview") -> dict:
        """Compară montajul (timeline + render) cu referința, pe cifre, și spune ce tool mută acul."""
        from .style import color_stats, compare, rhythm_from_cuts

        reference = reference or next(iter(self.references()), None)
        if not reference:
            raise ValueError("nu există referință")
        ref = self.style_profile(reference)
        f = self.dir / "renders" / f"{render}.mp4"
        if not f.exists():
            raise FileNotFoundError(f"randează întâi ({render})")
        info = probe(str(f))
        # tăieturile vizuale le știm exact din timeline: orice graniță de clip care sare în sursă sau schimbă cadrul
        cuts, t = [], 0.0
        for a, b in zip(self.tl.clips, self.tl.clips[1:]):
            t += a.duration
            if a.asset != b.asset or abs(a.src_out - b.src_in) > 0.05 or a.crop != b.crop:
                cuts.append(t)
        ours = {"rhythm": rhythm_from_cuts(cuts, self.tl.duration).model_dump(),
                "color": color_stats(str(f), info.duration, info.width, info.height).model_dump(),
                "lufs": analyze.loudness(str(f))["lufs"] if info.has_audio else None}
        return {"ours": {"rhythm": ours["rhythm"], "lufs": ours["lufs"], "color_mean": ours["color"]["mean"]},
                "reference": {"rhythm": ref.get("rhythm"), "lufs": ref.get("lufs"),
                              "color_mean": ref.get("color", {}).get("mean")},
                "tips": compare(ours, ref)}

    # ---------- editare ----------
    def set_format(self, fmt: str = "9:16", fps: float | None = None, fill: str | None = None) -> str:
        if fmt not in FORMATS:
            raise ValueError(f"format necunoscut; disponibile: {', '.join(FORMATS)}")
        if fill and fill not in ("crop", "pad", "blur"):
            raise ValueError("fill: crop, pad sau blur")
        with self.edit() as tl:
            tl.width, tl.height = FORMATS[fmt]
            if fps:
                tl.fps = fps
            if fill:
                tl.fill = fill
        return self.tl.view()

    def auto_cut_silence(self, aid: str, noise_db: float = -35, min_silence: float = 0.5,
                         padding: float = 0.1) -> str:
        m = self._asset(aid)
        sil = self._cache(aid, f"silence_{noise_db}_{min_silence}", lambda: analyze.silences(m.path, noise_db, min_silence))
        keep = analyze.speech_ranges(m.duration, [tuple(x) for x in sil], padding)
        with self.edit() as tl:
            if not tl.clips and m.has_video and tl.fps == Timeline().fps and m.fps:
                tl.fps = round(m.fps, 3)
            tl.set_clips_from_ranges(aid, keep)
            tl.captions = []  # tăieturile s-au schimbat => captions se regenerează
        n = len(keep)
        return f"{m.duration:.2f}s -> {self.tl.duration:.2f}s în {n} {'clip' if n == 1 else 'clipuri'}"

    @staticmethod
    def _spans(spec: str) -> list[tuple[int, int]]:
        out = []
        for part in re.split(r"[,\s]+", spec.strip()):
            if not part:
                continue
            mm = re.fullmatch(r"w?(\d+)(?:-w?(\d+))?", part)
            if not mm:
                raise ValueError(f"span invalid: {part} (format: w10-w25,w40)")
            a = int(mm[1])
            out.append((a, int(mm[2] or a)))
        return out

    def remove_words(self, aid: str, spans: str) -> str:
        tr = self.transcript(aid)
        with self.edit() as tl:
            if not tl.clips:
                tl.add_clip(aid, 0, self._asset(aid).duration)
            for a, b in self._spans(spans):
                s, e = tr.span(a, b)
                nxt = next((w.start for w in tr.words if w.i == b + 1), e)
                tl.remove_source_span(aid, s, min(nxt, e + 0.15))
        return self.tl.view()

    def keep_words(self, aid: str, spans: str, pad: float = 0.12) -> str:
        """Construiește timeline-ul DOAR din aceste fragmente, în ordinea dată (clipuri scurte / highlights)."""
        tr = self.transcript(aid)
        dur = self._asset(aid).duration
        with self.edit() as tl:
            tl.clips, tl.captions, tl.texts = [], [], []  # timeline nou => captions/texte vechi nu mai sunt valide
            for a, b in self._spans(spans):
                s, e = tr.span(a, b)
                tl.add_clip(aid, max(0, s - pad), min(dur, e + pad))
        return self.tl.view()

    def add_clip(self, aid: str, src_in: float, src_out: float, index: int | None = None) -> str:
        self._asset(aid)
        with self.edit() as tl:
            tl.add_clip(aid, src_in, min(src_out, self._asset(aid).duration), index)
        return self.tl.view()

    def remove_clip(self, cid: str) -> str:
        with self.edit() as tl:
            tl.clip(cid)
            tl.remove_clip(cid)
        return self.tl.view()

    def move_clip(self, cid: str, index: int) -> str:
        with self.edit() as tl:
            tl.move_clip(cid, index)
        return self.tl.view()

    def trim_clip(self, cid: str, src_in: float | None = None, src_out: float | None = None) -> str:
        with self.edit() as tl:
            c = tl.clip(cid)
            c.src_in = c.src_in if src_in is None else src_in
            c.src_out = c.src_out if src_out is None else src_out
            if c.src_out <= c.src_in:
                raise ValueError("interval invalid")
        return self.tl.view()

    def remove_range(self, t0: float, t1: float) -> str:
        with self.edit() as tl:
            tl.remove_range(t0, t1)
        return self.tl.view()

    def reframe(self, clip_ids: str = "all", cx: float = 0.5, cy: float = 0.5, zoom: float = 1.0) -> str:
        with self.edit() as tl:
            ids = {c.id for c in tl.clips} if clip_ids == "all" else set(re.split(r"[,\s]+", clip_ids.strip()))
            for c in tl.clips:
                if c.id in ids:
                    c.crop = Crop(cx=min(max(cx, 0), 1), cy=min(max(cy, 0), 1), zoom=max(zoom, 1))
        return self.tl.view()

    def _clip_ids(self, clip_ids: str) -> set[str]:
        if clip_ids == "all":
            return {c.id for c in self.tl.clips}
        ids = set(re.split(r"[,\s]+", clip_ids.strip())) - {""}
        missing = ids - {c.id for c in self.tl.clips}
        if missing:
            raise KeyError(f"clipuri inexistente: {', '.join(sorted(missing))}")
        return ids

    def face_track(self, aid: str, fps: float = 2.0, backend: str = "auto") -> dict:
        from .faces import detect_track

        m = self._asset(aid)
        if not m.has_video:
            raise ValueError(f"{aid} nu are video")
        return self._cache(aid, f"faces_{fps:g}", lambda: detect_track(m.path, m.width, m.height, fps, backend))

    def speakers(self, aid: str, start: float = 0.0, end: float | None = None, min_hold: float = 1.0) -> dict:
        """Cine vorbește când (după mișcarea gurii + audio). Segmente în timp sursă."""
        from .speaker import speakers

        m = self._asset(aid)
        if not (m.has_video and m.has_audio):
            raise ValueError(f"{aid} are nevoie de video și audio")
        end = m.duration if end is None else min(end, m.duration)
        return self._cache(aid, f"speakers_{start:.2f}_{end:.2f}_{min_hold:g}",
                           lambda: speakers(m.path, m.width, m.height, start, end, min_hold=min_hold))

    def _speaker_split(self, aid: str, s: rf.Segment, chf: float) -> list[rf.Segment]:
        """Un segment WIDE devine sub-segmente încadrate pe vorbitorul activ.
        Cu diarizare: granițe exacte din audio + fața fiecărui vorbitor. Fără: doar semnal vizual."""
        from .diarize import framing_plan

        d = self._diar(aid)
        if d is not None:
            faces = self.speaker_faces(aid)
            plan = framing_plan(d.turns, s.t0, s.t1, faces)
            if plan:
                return [rf.Segment(t0=a, t1=b, cx=faces[sp]["cx"], cy=round(faces[sp]["cy"] + chf * rf.HEADROOM, 3),
                                   faces=s.faces, flag=f"speaker:{sp}") for a, b, sp in plan]
        try:
            sp = self.speakers(aid, s.t0, s.t1)
        except Exception:  # fără landmarks/audio => rămâne WIDE
            return [s]
        if len(sp["tracks"]) < 2 or not sp["segments"]:
            return [s]
        return [rf.Segment(t0=g["t0"], t1=g["t1"], cx=g["cx"], cy=round(g["cy"] + chf * rf.HEADROOM, 3),
                           faces=s.faces, flag=f"speaker:S{g['track']}")
                for g in sp["segments"] if g["t1"] - g["t0"] > 0.04]

    def auto_reframe(self, clip_ids: str = "all", split: bool = True, punch_in: float = 0.0,
                     fps: float = 2.0, backend: str = "auto", speaker: bool = True) -> str:
        """Încadrează automat pe fețe fiecare clip; împarte clipurile unde subiectul se mută / se schimbă scena.
        speaker=True: la segmentele WIDE (mai multe persoane care nu încap) urmărește vorbitorul activ."""
        from .faces import Face, locate_change

        ids = self._clip_ids(clip_ids)
        tracks: dict[str, dict] = {}
        scene_cache: dict[str, list[float]] = {}
        backend_used = set()
        report: list[str] = []
        with self.edit() as tl:
            new: list = []
            used = {c.id for c in tl.clips}
            flagged = 0
            for c in tl.clips:
                va = c.angle or c.asset  # multicam: se încadrează unghiul care se vede
                m = self._asset(va)
                if c.id not in ids or not m.has_video or c.split:
                    new.append(c)
                    continue
                shift = tl.angle_time(c, va, 0.0)  # timp_unghi = timp_sursă + shift
                if va not in tracks:
                    tracks[va] = self.face_track(va, fps, backend)
                    backend_used.add(tracks[va]["backend"])
                    scene_cache[va] = self._cache(va, "scenes_0.3", lambda: analyze.scenes(m.path, 0.3))
                samples = [(t, [Face(**f) for f in fs]) for t, fs in tracks[va]["samples"]]
                cwf, chf = rf.crop_fraction(m.width, m.height, tl.width, tl.height, c.crop.zoom)
                def refine(ta, tb, old, new, m=m, cwf=cwf, chf=chf):
                    return locate_change(m.path, m.width, m.height, ta, tb, old, new, cwf, chf, backend=backend)

                segs = rf.plan(samples, c.src_in + shift, c.src_out + shift, cwf, chf, split=split,
                               scene_cuts=scene_cache[va], refine=refine)
                if speaker and m.has_audio:
                    segs = [x for s in segs for x in (self._speaker_split(va, s, chf) if s.flag == "wide" else [s])]
                if c.speed != 1 or c.freeze:  # nu tăiem clipuri cu viteză / freeze: doar încadrare
                    segs = [max(segs, key=lambda s: s.t1 - s.t0)]
                    segs[0].t0, segs[0].t1 = c.src_in + shift, c.src_out + shift
                for k, s in enumerate(segs):
                    part = c.model_copy(deep=True)
                    if k:
                        n = k
                        while f"{c.id}r{n}" in used:
                            n += 1
                        part.id = f"{c.id}r{n}"
                        used.add(part.id)
                    part.src_in, part.src_out = round(s.t0 - shift, 3), round(s.t1 - shift, 3)
                    if k < len(segs) - 1:
                        part.freeze = 0.0
                    if k:
                        part.transition = None
                    if s.flag != "no_face":
                        part.crop = Crop(cx=min(max(s.cx, 0), 1), cy=min(max(s.cy, 0), 1), zoom=c.crop.zoom)
                    new.append(part)
                    note = {"wide": " WIDE (fețele nu încap împreună; încadrat pe cea mai mare)",
                            "no_face": " NO_FACE (încadrare neschimbată)"}.get(s.flag, "")
                    if s.flag.startswith("speaker:"):
                        note = f" vorbitor {s.flag[8:]}"
                    flagged += s.flag in ("wide", "no_face")
                    report.append(f"{part.id} [{s.t0:.2f}-{s.t1:.2f}] cx={part.crop.cx:.2f} cy={part.crop.cy:.2f} "
                                  f"fețe={s.faces}{note}")
            n_before = len(tl.clips)
            tl.clips = [c for c in new if c.duration > 0.04]
            if punch_in > 0:
                out_ids = [c for c in tl.clips if c.id in ids or any(c.id.startswith(i + "r") for i in ids)]
                for k, c in enumerate(out_ids):
                    c.crop.zoom = round(1 + punch_in, 3) if k % 2 else 1.0
        head = (f"auto_reframe ({'/'.join(sorted(backend_used)) or '-'}): {n_before} clipuri -> {len(self.tl.clips)}. "
                f"{flagged} segmente marcate — verifică-le cu frames_look.")
        if flagged * 2 > max(len(report), 1):
            head += " Majoritatea marcate: ia în calcul timeline_format(fill='pad')."
        if punch_in > 0:
            zoomed = [c.id for c in self.tl.clips if c.crop.zoom > 1]
            head += f" Punch-in x{1 + punch_in:g} aplicat pe {len(zoomed)} clipuri ({', '.join(zoomed) or '-'}), cu sau fără fețe."
        return "\n".join([head, *report])

    def transition_set(self, clip_ids: str = "all", type: str = "fade", duration: float = 0.4) -> str:
        """Tranziție la intrarea în clipurile date (dinspre clipul anterior). type='none' o scoate."""
        from .timeline import TRANSITIONS, Transition

        if type != "none" and type not in TRANSITIONS:
            raise ValueError(f"tranziție necunoscută; disponibile: {', '.join(TRANSITIONS)}")
        ids = self._clip_ids(clip_ids)
        skipped = []
        with self.edit() as tl:
            for i, c in enumerate(tl.clips):
                if c.id not in ids:
                    continue
                if type == "none":
                    c.transition = None
                    continue
                if i == 0:
                    continue  # primul clip nu are de unde să intre
                limit = min(c.duration, tl.clips[i - 1].duration) / 2
                d = min(duration, limit)
                if d < 0.08:
                    skipped.append(c.id)
                    continue
                c.transition = Transition(type=type, duration=round(d, 3))
        note = f" (sărite, clipuri prea scurte: {', '.join(skipped)})" if skipped else ""
        return f"tranziții actualizate{note}\n{self.tl.view()}"

    def track_point(self, at: float, x: float, y: float, duration: float = 3.0) -> dict:
        """Urmărește punctul (x, y) din cadrul final, de la momentul `at` (montaj), cel mult `duration` s, în clipul
        în care e. Întoarce id-ul urmăririi (pentru motion_add track=...)."""
        from .render import crop_box
        from .track import track

        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError("x, y între 0 și 1 (din cadrul final, ca în frames_look)")
        tl = self.tl
        c, va, st = self._picture_at(at)
        start = next(s for cc, s in zip(tl.clips, tl.starts()) if cc.id == c.id)
        dur = max(0.3, min(duration, start + c.duration - at - 0.04))
        m = self._asset(va)
        if tl.fill == "crop":  # cadrul final -> sursă (fereastra de crop a clipului)
            cw, ch, ox, oy = crop_box(m.width, m.height, tl.width, tl.height, c)
        else:
            cw, ch, ox, oy = m.width, m.height, 0, 0
        sx, sy = (ox + x * cw) / m.width, (oy + y * ch) / m.height
        speed = getattr(c, "speed", 1.0) or 1.0
        path = track(m.path, m.width, m.height, st, sx, sy, dur * speed)
        out = [[round(t / speed, 4), round((px * m.width - ox) / cw, 5), round((py * m.height - oy) / ch, 5)]
               for t, px, py in path]
        with self.edit() as tl:
            tid = _new_id_simple("t", set(tl.tracks))
            tl.tracks[tid] = {"at": round(at, 3), "path": out}
        lost = out[-1][0] < dur - 0.2
        return {"track": tid, "from": round(at, 3), "seconds": out[-1][0], "points": len(out),
                "moved": [round(out[-1][1] - out[0][1], 3), round(out[-1][2] - out[0][2], 3)],
                "lost_at": round(at + out[-1][0], 2) if lost else None}

    def captions_look(self, engine: str = "motion", look: str = "line", y: float = -1) -> str:
        if engine not in ("motion", "ass"):
            raise ValueError("engine: motion sau ass")
        if look not in ("line", "chunk", "marker"):
            raise ValueError("look: line, chunk sau marker")
        if y != -1 and not 0.1 <= y <= 0.9:
            raise ValueError("y între 0.1 și 0.9 (sau -1 pentru implicit)")
        with self.edit() as tl:
            tl.caption_engine, tl.caption_look = engine, look
            tl.caption_y = None if y == -1 else y
        note = "" if self.tl.captions else " (încă nu există subtitrări: rulează captions_add)"
        return f"subtitrări: {engine}/{look}{note}"

    def keyframes_set(self, clip_id: str, keys: list[dict], motion_blur: bool = False) -> str:
        """Keyframe-uri de cameră pe un clip (timp din clip). Lista goală le scoate."""
        from .timeline import Key

        with self.edit() as tl:
            c = next((x for x in tl.clips if x.id == clip_id), None)
            if c is None:
                raise KeyError(f"clip inexistent: {clip_id}")
            ks = [Key(**k) for k in keys]
            for k in ks:
                if not 0 <= k.t <= c.duration + 1e-3:
                    raise ValueError(f"keyframe la {k.t}s: clipul are {c.duration:.2f}s (timpul e din clip, de la 0)")
                if not 1.0 <= k.zoom <= 3.0:
                    raise ValueError("zoom între 1.0 (cadrul întreg) și 3.0")
                if not (0 <= k.cx <= 1 and 0 <= k.cy <= 1):
                    raise ValueError("cx, cy între 0 și 1 (punctul din cadru care ajunge în centru)")
                if abs(k.rotate) > 25:
                    raise ValueError("rotate: maxim ±25 de grade (mai mult arată colțuri negre)")
                if k.rotate and k.zoom < 1 + abs(k.rotate) / 60:
                    raise ValueError(f"cu rotate={k.rotate} pune zoom >= {1 + abs(k.rotate) / 60:.2f}, altfel se văd colțuri negre")
            if len(ks) == 1:
                raise ValueError("cel puțin 2 keyframe-uri (de unde pornește și unde ajunge)")
            c.keys = sorted(ks, key=lambda k: k.t)
            c.motion_blur = bool(motion_blur) and bool(ks)
            if ks:
                c.anim = None
        return self.tl.view()

    def zoom_animate(self, clip_ids: str, zoom_to: float = 1.15, zoom_from: float = 1.0, ease: str = "inout") -> str:
        from .timeline import ZoomAnim

        if not (1.0 <= zoom_from <= 2.0 and 1.0 <= zoom_to <= 2.0):
            raise ValueError("zoom între 1.0 și 2.0 (peste 1.35 se vede pixelarea pe surse 1080p)")
        ids = self._clip_ids(clip_ids)
        with self.edit() as tl:
            for c in tl.clips:
                if c.id in ids:
                    c.anim = None if zoom_from == zoom_to else ZoomAnim(zoom_from=zoom_from, zoom_to=zoom_to, ease=ease)
        return self.tl.view()

    def _audio_check(self, aid: str):
        from .audiofx import AudioCheck, check

        m = self._asset(aid)
        if not m.has_audio:
            raise ValueError(f"{aid} nu are audio")
        sil = self._cache(aid, "silence_-35_0.4", lambda: analyze.silences(m.path, -35, 0.4))
        return AudioCheck(**self._cache(aid, "audio_check", lambda: check(m.path, [tuple(x) for x in sil]).model_dump()))

    def audio_check(self, aid: str) -> str:
        return self._audio_check(aid).summary()

    def audio_clean(self, aid: str = "all", preset: str = "medium") -> str:
        from .audiofx import PRESETS

        if preset != "none" and preset not in PRESETS:
            raise ValueError(f"preset necunoscut; disponibile: {', '.join(PRESETS)}, none")
        targets = [k for k, v in self.s.assets.items() if v.has_audio and v.has_video
                   and self.s.roles.get(k) not in ("reference", "broll", "brand")] if aid == "all" else [aid]
        measured = {a: self._audio_check(a).noise_db for a in targets} if preset != "none" else {}
        with self.edit() as tl:
            for a in targets:
                self._asset(a)
                if preset == "none":
                    tl.audio_fx.pop(a, None)
                else:
                    tl.audio_fx[a] = {"preset": preset, "noise_db": measured[a]}
        extra = ", ".join(f"{a}: zgomot {n:.0f} dB" for a, n in measured.items())
        return f"curățare audio {preset} pe {', '.join(targets) or '-'}" + (f" (calibrat pe {extra})" if extra else "")

    def clip_volume(self, clip_ids: str, volume_db: float) -> str:
        with self.edit() as tl:
            ids = {c.id for c in tl.clips} if clip_ids == "all" else set(re.split(r"[,\s]+", clip_ids.strip()))
            for c in tl.clips:
                if c.id in ids:
                    c.volume_db = volume_db
        return self.tl.view()

    def captions(self, aid: str, style: str = "bold_center", speaker_colors: bool = False) -> str:
        tr = self.transcript(aid)
        if speaker_colors and not any(w.spk for w in tr.words):
            raise ValueError("speaker_colors are nevoie de diarizare: rulează întâi diarize")
        with self.edit() as tl:
            n = build_captions(tl, aid, tr, style, speaker_colors)
        return f"{n} captions, stil {style}. Stiluri: {', '.join(STYLES)}"

    def add_text(self, start: float, end: float, text: str, position: str = "top") -> str:
        with self.edit() as tl:
            tl.texts.append(TextOverlay(start=start, end=end, text=text, position=position))
        return f"{len(self.tl.texts)} text overlays"

    def music_use(self, track_id: str, volume_db: float = -18, duck: bool = True, src_in: float = 0.0) -> str:
        """Piesa din catalog / biblioteca ta devine muzica proiectului; creditul (dacă licența îl cere) rămâne în
        meta și intră singur în descrierea postării."""
        import shutil as _sh

        from . import guard
        from .musiclib import fetch, get

        track = get(track_id)
        guard.spend("stock")
        src = fetch(track)
        dest = self.dir / "music" / Path(track["file"]).name
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            _sh.copy(src, dest)
        aid = next((k for k, v in self.s.assets.items() if Path(v.path) == dest.resolve()), None)
        if aid is None:
            aid = self.add_asset(str(dest)).split(":")[0]
        self.s.roles[aid] = "music"
        self.s.meta[aid] = {"source": track["source"], "track": track["id"], "title": track["title"],
                            "license": track["license"], "credit": track.get("credit", "")}
        self.save()
        self.set_music(aid, volume_db, duck, src_in)
        note = f"\nCredit (intră automat în descrierea postării): {track['credit']}" if track.get("credit") else ""
        return f"{aid}: „{track['title']}” ({track['bpm']} BPM, {track['seconds'] // 60}:{track['seconds'] % 60:02d}){note}"

    def music_fit(self) -> str:
        """Backtiming: piesa pornește astfel încât finalul ei REAL să cadă pe finalul montajului; începutul e pus pe
        cel mai apropiat beat (tăietura nu se aude). Piesa mai scurtă decât clipul rămâne de la început, în buclă."""
        tl = self.tl
        if not tl.music:
            raise ValueError("nu e muzică pe proiect (music_use / music_set)")
        m = self._asset(tl.music.asset)
        need = tl.duration
        if m.duration < need + 1.0:
            return f"piesa are {m.duration:.0f}s, clipul {need:.0f}s: rămâne de la început (în buclă)"
        # finalul real: ultimul moment în care piesa încă sună (sub -45 dB e liniștea de după final)
        import numpy as np

        from .beats import SR, load_mono

        s0 = max(0.0, m.duration - 15.0)
        y = load_mono(m.path, start=s0)
        hop = int(SR * 0.05)
        env = np.array([np.abs(y[i:i + hop]).max() for i in range(0, max(len(y) - hop, 1), hop)])
        thr = max(env.max() * 10 ** (-45 / 20), 1e-5) if len(env) else 1.0
        real_end = s0 + (len(env) - int(np.argmax(env[::-1] > thr))) * 0.05 if len(env) else m.duration
        src_in = max(0.0, real_end - need)
        beats = self.beats(tl.music.asset).beats
        if beats:  # începutul pe un beat; dacă mută finalul, mutăm și finalul cu el (diferență sub o bătaie)
            b = min(beats, key=lambda x: abs(x - src_in))
            if abs(b - src_in) < 0.6:
                src_in = b
        with self.edit() as tl:
            tl.music.src_in = round(src_in, 3)
            tl.music.ends_naturally = True
        return (f"muzica pornește la {src_in:.1f}s din piesă și se termină cu finalul ei, pe finalul clipului "
                f"({need:.1f}s); fade scurt de 0,25 s")

    def credits(self) -> list[str]:
        """Creditele cerute de licențele materialelor folosite în montaj (muzică CC BY etc.)."""
        used = {c.asset for c in self.tl.clips} | {b.asset for b in self.tl.broll}
        if self.tl.music:
            used.add(self.tl.music.asset)
        return sorted({m["credit"] for a, m in self.s.meta.items() if a in used and m.get("credit")})

    def set_music(self, aid: str | None, volume_db: float = -18, duck: bool = True, src_in: float = 0.0) -> str:
        with self.edit() as tl:
            tl.music = Music(asset=aid, volume_db=volume_db, duck=duck, src_in=src_in) if aid else None
            if aid:
                self._asset(aid)
        return self.tl.view()

    # ---------- brand kit ----------
    def _import_brand_file(self, path: str, sub: str, stem: str, ext: str) -> Path:
        """Copiază fișierul în <proiect>/brand/<sub>; numele are hash-ul conținutului, deci undo-ul
        nu ajunge niciodată la un fișier suprascris între timp."""
        from .brand import file_hash

        src = Path(path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"fișier inexistent: {Path(path).name}")
        d = self.dir / "brand" / sub
        d.mkdir(parents=True, exist_ok=True)
        dst = d / f"{stem}_{file_hash(src)}{ext}"
        if not dst.exists():
            shutil.copy2(src, dst)
        return dst.resolve()

    def brand_logo(self, path: str, position: str = "tr", scale: float = 0.12, opacity: float = 0.85,
                   margin: float = 0.04) -> str:
        from .brand import LOGO_EXT, check_ext
        from .ff import FFError, run
        from .timeline import Logo

        ext = check_ext(path, LOGO_EXT, "logo")
        if position not in ("tl", "tr", "bl", "br"):
            raise ValueError("position: tl, tr, bl sau br")
        if not (0.02 <= scale <= 0.5 and 0.05 <= opacity <= 1 and 0 <= margin <= 0.2):
            raise ValueError("scale 0.02-0.5 (din lățime), opacity 0.05-1, margin 0-0.2")
        dst = self._import_brand_file(path, "", "logo", ext)
        try:
            run(["-v", "error", "-i", str(dst), "-frames:v", "1", "-f", "null", "-"])
        except FFError as e:
            raise ValueError("logo-ul nu e o imagine validă (PNG/JPG/WebP)") from e
        with self.edit() as tl:
            tl.brand.logo = Logo(path=str(dst), position=position, scale=scale, opacity=opacity, margin=margin)
        return self.tl.brand_view()

    def brand_captions(self, primary: str = "", highlight: str = "", outline: str = "", font_path: str = "",
                       font_family: str = "") -> str:
        """Culori (#RRGGBB) și font pentru subtitrări și titluri. '' = neschimbat, 'none' = revine la stil."""
        from .brand import FONT_EXT, check_ext, font_family as read_family
        from .captions import norm_hex

        colors = {k: v.strip() for k, v in (("primary", primary), ("highlight", highlight), ("outline", outline)) if v}
        colors = {k: None if v.lower() == "none" else norm_hex(v) for k, v in colors.items()}
        font_file = family = None
        if font_path:
            ext = check_ext(font_path, FONT_EXT, "font")
            dst = self._import_brand_file(font_path, "fonts", Path(font_path).stem[:40], ext)
            family = font_family or read_family(dst)
            if not family:
                raise ValueError("nu pot citi numele fontului (lipsește fontTools): dă și font_family")
            font_file = str(dst)
        with self.edit() as tl:
            for k, v in colors.items():
                setattr(tl.brand, k, v)
            if font_file:
                tl.brand.font_file, tl.caption_font = font_file, family
            elif font_family.lower() == "none":
                tl.brand.font_file, tl.caption_font = None, None
            elif font_family:
                tl.caption_font = font_family  # un font inclus (vedit/fonts), fără fișier nou
        return self.tl.brand_view()

    def brand_intro_outro(self, intro: str = "", outro: str = "") -> str:
        """Clipuri lipite la randare înainte / după montaj. '' = fără."""
        vals = {}
        for key, aid in (("intro", intro), ("outro", outro)):
            if not aid:
                vals[key] = (None, 0.0)
                continue
            m = self._asset(aid)
            if not m.has_video:
                raise ValueError(f"{aid} nu are video")
            if self.s.roles.get(aid) == "reference":
                raise ValueError(f"{aid} e referință, nu intro/outro")
            vals[key] = (aid, round(m.duration, 3))
        old = {self.tl.brand.intro, self.tl.brand.outro}
        with self.edit() as tl:
            (tl.brand.intro, tl.brand.intro_dur), (tl.brand.outro, tl.brand.outro_dur) = vals["intro"], vals["outro"]
        for aid in old - {intro, outro}:
            if self.s.roles.get(aid) == "brand":
                self.s.roles.pop(aid)
        for aid in (intro, outro):
            if aid:
                self.s.roles[aid] = "brand"
        self.save()
        return f"{self.tl.brand_view()}\ndurata livrată: {self.tl.output_duration:.2f}s (montaj {self.tl.duration:.2f}s)"

    def brand_clear(self, part: str = "all") -> str:
        from .timeline import Brand

        if part not in ("all", "logo", "captions", "intro_outro"):
            raise ValueError("part: all, logo, captions sau intro_outro")
        with self.edit() as tl:
            b = tl.brand
            if part in ("all", "captions") and b.font_file:
                tl.caption_font = None
            if part == "all":
                tl.brand = Brand()
            elif part == "logo":
                b.logo = None
            elif part == "captions":
                b.primary = b.highlight = b.outline = b.font_file = None
            else:
                b.intro, b.intro_dur, b.outro, b.outro_dur = None, 0.0, None, 0.0
        self.s.roles = {k: v for k, v in self.s.roles.items()
                        if v != "brand" or k in (self.tl.brand.intro, self.tl.brand.outro)}
        self.save()
        return self.tl.brand_view()

    def _check_brand_files(self) -> None:
        """Orice cale de fișier din timeline trebuie să fie în proiect: timeline-ul poate veni și din API (alt client
        ar putea trimite /alt-proiect/video.mp4), nu doar din tool-uri."""
        tl = self.tl
        brand = (self.dir / "brand").resolve()
        cache = (self.dir / "cache").resolve()
        b = tl.brand
        for f in (b.logo.path if b.logo else None, b.font_file):
            if f and brand not in Path(f).resolve().parents:
                raise PermissionError("fișierele de brand trebuie să fie în <proiect>/brand (folosește brand_logo / brand_captions)")
        luts = (self.dir / "luts").resolve()
        for f, root in [(g.lut, luts) for g in tl.grades.values()] + [(f, cache) for f in tl.stabilized.values()] \
                + [(f, cache) for f in [*tl.mattes.values(), *tl.face_masks.values()]]:
            if f and root not in Path(f).resolve().parents:
                raise PermissionError("LUT-urile (<proiect>/luts) și clipurile stabilizate (<proiect>/cache) se fac "
                                      "doar cu color_match / color_grade / stabilize")
        problems = self.missing_refs(tl)
        if problems:
            raise ValueError("timeline-ul folosește asset-uri inexistente: " + ", ".join(problems))

    def missing_refs(self, tl: Timeline) -> list[str]:
        """Id-urile de asset folosite în timeline care nu există în proiect."""
        from .timeline import SFX_KINDS

        used = {c.asset for c in tl.clips} | {c.angle for c in tl.clips if c.angle} \
            | {a for c in tl.clips if c.split for a in c.split.angles} | {x.asset for x in tl.broll} \
            | {x.kind for x in tl.sfx if x.kind not in SFX_KINDS} | set(tl.stabilized) | set(tl.grades) \
            | set(tl.mattes) | set(tl.face_masks) | {c.bg.value for c in tl.clips if c.bg and c.bg.mode == "asset"}
        if tl.music:
            used.add(tl.music.asset)
        return sorted(used - set(self.s.assets))

    # ---------- livrare ----------
    def captions_export(self, fmt: str = "srt") -> dict:
        from .captions import to_subs

        fmt = fmt.lower().lstrip(".")
        if not self.tl.captions:
            raise ValueError("nu există subtitrări: rulează întâi captions_add")
        text = to_subs(self.tl, fmt, offset=self.tl.brand.intro_dur if self.tl.brand.intro else 0.0)
        out = self.dir / "renders" / f"captions.{fmt}"
        out.write_text(text, encoding="utf-8")
        n = text.count(" --> ")
        return {"path": str(out.resolve()), "format": fmt, "cues": n}

    def hook_variants(self, moments: str, texts: str = "", preview: bool = True) -> dict:
        """Același clip cu începuturi diferite (teaser din alt moment), randate separat ca hook1, hook2... pentru
        testare (Trial Reels / A-B). Montajul principal rămâne neatins: fiecare variantă se face și se anulează."""
        ranges = []
        for part in [x.strip() for x in moments.split(",") if x.strip()]:
            a, _, b = part.partition("-")
            ranges.append((float(a), float(b)))
        if not 2 <= len(ranges) <= 4:
            raise ValueError("2-4 momente, ex. '12.4-15.6,40-43.2'")
        labels = [t.strip() for t in texts.split("|")] if texts else []
        out = []
        for i, (a, b) in enumerate(ranges, 1):
            self.hook_teaser(a, b, labels[i - 1] if i - 1 < len(labels) else "", True)
            try:
                r = self.render(preview=preview, name=f"hook{i}")
            finally:
                self.undo()
            out.append({"name": f"hook{i}", "from": a, "to": b, "path": r["path"], "duration": r["duration"]})
        return {"variants": out, "note": "postează-le ca Trial Reels / teste; păstrează varianta cu retenția mai bună"}

    def export_all(self, platforms: str = "reels,shorts,tiktok") -> dict:
        """Același montaj, livrat pe mai multe platforme dintr-un singur apel (format, durată, loudness, QA)."""
        res = {}
        start_fmt = (self.tl.width, self.tl.height)
        for plat in [x.strip() for x in platforms.split(",") if x.strip()]:
            r = self.export_preset(plat)
            res[plat] = {"path": r["path"], "format": r["format"], "warnings": r.get("warnings", []),
                         "qa_ok": (r.get("qa") or {}).get("ok")}
        return {"exports": res, "format_initial": f"{start_fmt[0]}x{start_fmt[1]}"}

    def export_preset(self, platform: str, fmt: str = "") -> dict:
        """Format + fps + loudness pentru platformă, avertismente de durată, render final `<platform>` + QA."""
        from .brand import LUFS, PLATFORMS

        if platform not in PLATFORMS:
            raise ValueError(f"platformă necunoscută; disponibile: {', '.join(PLATFORMS)}")
        spec = PLATFORMS[platform]
        fmt = fmt or spec["fmt"]
        if fmt not in FORMATS:
            raise ValueError(f"format necunoscut; disponibile: {', '.join(FORMATS)}")
        if not self.tl.clips:
            raise ValueError("timeline-ul e gol")
        before = (self.tl.width, self.tl.height)
        with self.edit() as tl:
            tl.width, tl.height = FORMATS[fmt]
            # 30 fps; o sursă deja între 23.976 și 30 rămâne așa (conversia 25->30 dublează cadre, se vede sacadat)
            if not 23.9 <= tl.fps <= 30.001:
                tl.fps = 30.0
            tl.loudness_lufs = LUFS
        warnings = []
        if before != FORMATS[fmt] and self.tl.fill == "crop":
            warnings.append(f"formatul s-a schimbat în {fmt}: încadrarea e pe centru; rulează auto_reframe dacă "
                            f"subiectul iese din cadru, apoi exportă din nou")
        dur = self.tl.output_duration
        if dur > spec["max"]:
            warnings.append(f"durata {dur:.0f}s depășește ~{spec['max']}s ({spec['note']}); verifică limita curentă "
                            f"a platformei sau scurtează")
        out = self.render(preview=False, name=platform)
        qa = self.qa(out["path"])
        return {"platform": platform, "format": f"{fmt} {self.tl.width}x{self.tl.height}", "fps": self.tl.fps,
                "lufs": LUFS, "path": out["path"], "duration": out["duration"], "warnings": warnings, "qa": qa}

    def _at(self, t: float):
        """Clipul și timpul sursă pentru timpul de timeline t."""
        for c, s in zip(self.tl.clips, self.tl.starts()):
            if s <= t < s + c.duration:
                return c, min(c.src_at(t - s), max(c.src_out - 0.04, c.src_in))
        c = self.tl.clips[-1]
        return c, max(c.src_out - 0.05, c.src_in)

    def _picture_at(self, t: float):
        """(clip, asset-ul care se vede, timpul în el) la timpul de timeline t; la split, primul unghi."""
        c, st = self._at(t)
        va = c.split.angles[0] if c.split else (c.angle or c.asset)
        return c, va, self.tl.angle_time(c, va, st)

    def clip_frame(self, cid: str, t: float = 0.0, graph: dict | None = None, view: str | None = None,
                   max_side: int = 640) -> bytes:
        """Un cadru JPEG din clip, cu încadrarea, efectele și nodurile lui, la `t` secunde de la începutul clipului.
        `graph` (opțional): un graf de noduri încă nesalvat (editorul de noduri / pagina de culoare);
        `view`: id-ul nodului a cărui ieșire o vrei (ca în Fusion, cu „1” pe un nod)."""
        import subprocess

        from .ff import FFError, ffmpeg_bin
        from .nodes import compile_graph
        from .render import ASSETS, _even, _frame, _fx, _lut, media_path
        from .timeline import NodeGraph

        ASSETS.set(self.s.assets)
        tl = self.tl
        c = next((x for x in tl.clips if x.id == cid), None)
        if c is None:
            raise KeyError(f"clip inexistent: {cid}")
        g = NodeGraph.model_validate(graph) if graph is not None else c.nodes
        aid = c.split.angles[0] if c.split else (c.angle or c.asset)
        if c.split:
            c = c.model_copy(update={"split": None, "angle": aid, "crop": c.split.crops[0]})
        m = self._asset(aid)
        k = min(1.0, max_side / max(tl.width, tl.height))
        W, H = _even(tl.width * k), _even(tl.height * k)
        st = tl.angle_time(c, aid, c.src_at(min(max(t, 0.0), c.body - 0.02)))
        plain = c.model_copy(update={"nodes": None, "anim": None})
        chain = _lut(tl, aid) + _frame(tl, plain, m, W, H) + _fx(plain, W, H) + compile_graph(g, "p", W, H, view=view)
        cmd = [ffmpeg_bin(), "-hide_banner", "-nostdin", "-ss", f"{max(st, 0):.3f}", "-i", media_path(tl, aid, m),
               "-filter_complex", f"[0:v]{chain}[o]", "-map", "[o]", "-frames:v", "1",
               "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "3", "-"]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
        except subprocess.TimeoutExpired as e:
            raise FFError("cadrul nu s-a randat în 60 s") from e
        if proc.returncode != 0 or not proc.stdout:
            tail = "\n".join(proc.stderr.decode(errors="replace").strip().splitlines()[-8:])
            raise FFError(f"cadrul nu s-a putut randa:\n{tail}")
        return proc.stdout

    def thumbnail_export(self, at: float = -1, title: str = "", candidates: int = 12, style: str = "frame",
                         out_name: str = "thumbnail.png", title_y: float | None = None,
                         title_scale: float | None = None, title_front: bool = False) -> dict:
        """PNG la rezoluția output-ului. at<0: cel mai clar cadru din `candidates`, preferând cadre cu fețe.
        style='sticker': persoana decupată cu contur alb peste fundal încețoșat (stilul thumbnail-urilor YouTube).
        out_name: calea în renders/ (ex. thumbs/1_cover_frame.png)."""
        if style not in ("frame", "sticker"):
            raise ValueError("style: frame sau sticker")
        if not re.fullmatch(r"(?:[A-Za-z0-9_-]{1,64}/)?[A-Za-z0-9_-]{1,64}\.png", out_name):
            raise ValueError("out_name: nume.png sau folder/nume.png")
        import tempfile

        import numpy as np

        from .brand import pick_best, sharpness
        from .captions import fonts_dir, title_ass
        from .ff import run
        from .render import ASSETS, crop_box, fit_filter
        from .style import grab_frame

        ASSETS.set(self.s.assets)  # sursele HDR se convertesc și în thumbnail
        tl = self.tl
        if not tl.clips:
            raise ValueError("timeline-ul e gol")
        dur = tl.duration
        report: dict = {}
        if at < 0:
            try:
                from .faces import get_detector

                det = get_detector()
            except Exception:  # fără OpenCV / model => doar claritate
                det = None
            cands = []
            for i in range(candidates):
                t = round(dur * (0.05 + 0.9 * (i + 0.5) / candidates), 3)
                c, va, st = self._picture_at(t)
                m = self._asset(va)
                fr = grab_frame(m.path, st, m.width, m.height, width=480)
                if fr is None:
                    continue
                if tl.fill == "crop":  # măsurăm doar ce ajunge în cadru
                    k = 480 / m.width
                    cw, ch, x, y = crop_box(m.width, m.height, tl.width, tl.height, c)
                    fr = fr[int(y * k):int((y + ch) * k), int(x * k):int((x + cw) * k)]
                faces = len(det(np.ascontiguousarray(fr[..., ::-1]))) if det is not None and fr.size else 0
                cands.append({"t": t, "sharpness": round(sharpness(fr), 1), "faces": faces})
            if not cands:
                raise ValueError("nu am putut citi cadre din surse")
            best = pick_best(cands)
            at = best["t"]
            report = {"sharpness": best["sharpness"], "faces": best["faces"], "candidates": len(cands),
                      "face_detector": det.backend if det is not None else None}
        at = min(max(at, 0.0), max(dur - 0.04, 0.0))
        c, va, st = self._picture_at(at)
        m = self._asset(va)
        if c.split:  # thumbnail-ul arată un singur unghi, încadrat normal
            c = c.model_copy(update={"split": None, "angle": va, "crop": c.split.crops[0]})
        out = self.dir / "renders" / out_name
        out.parent.mkdir(parents=True, exist_ok=True)
        wd = tempfile.mkdtemp(prefix="vedit_thumb_")
        vf = f"setpts=PTS-STARTPTS,{fit_filter(tl, c, m, tl.width, tl.height)},setsar=1"
        title_vf = ""
        if title.strip():
            kw = {k: v for k, v in (("y", title_y), ("scale", title_scale)) if v is not None}
            Path(wd, "title.ass").write_text(title_ass(tl, title, tl.width, tl.height, **kw), encoding="utf-8")
            title_vf = f",ass=filename=title.ass:fontsdir={fonts_dir(tl, wd)}"
        try:
            if style == "sticker":  # cadrul -> decupare + contur (numpy/OpenCV) -> titlul peste
                import cv2

                from .segment import sticker_background, sticker_thumbnail

                raw = Path(wd, "frame.png")
                run(["-y", "-ss", f"{st:.3f}", "-i", os.path.abspath(m.path), "-frames:v", "1", "-vf", vf,
                     "-update", "1", str(raw)], cwd=wd)
                frame = cv2.imread(str(raw))
                cv2.imwrite(str(Path(wd, "bg.png")), sticker_background(frame))
                behind = title.strip() and not title_front
                if title.strip():  # titlul uriaș pe fundal, apoi persoana peste el: textul trece prin spatele ei
                    Path(wd, "title.ass").write_text(title_ass(tl, title, tl.width, tl.height,
                                                               scale=title_scale or 0.26, y=title_y or 0.3),
                                                     encoding="utf-8")
                if behind:
                    run(["-y", "-i", "bg.png", "-vf", f"ass=filename=title.ass:fontsdir={fonts_dir(tl, wd)}",
                         "-frames:v", "1", "-update", "1", "bgt.png"], cwd=wd)
                bg = cv2.imread(str(Path(wd, "bgt.png" if behind else "bg.png")))
                if title.strip() and title_front:  # persoana umple cadrul: titlul vine peste ea, să se citească
                    cv2.imwrite(str(Path(wd, "st.png")), sticker_thumbnail(frame, bg))
                    run(["-y", "-i", "st.png", "-vf", f"ass=filename=title.ass:fontsdir={fonts_dir(tl, wd)}",
                         "-frames:v", "1", "-update", "1", str(out)], cwd=wd)
                else:
                    cv2.imwrite(str(out), sticker_thumbnail(frame, bg))
            else:
                run(["-y", "-ss", f"{st:.3f}", "-i", os.path.abspath(m.path), "-frames:v", "1", "-vf", vf + title_vf,
                     "-update", "1", str(out)], cwd=wd)
        finally:
            shutil.rmtree(wd, ignore_errors=True)
        return {"image": str(out.resolve()), "at": round(at, 3), "size": f"{tl.width}x{tl.height}",
                "title": bool(title.strip()), "style": style, **report}

    THUMB_FORMATS = {"youtube": (1280, 720), "cover": (1080, 1920), "feed": (1080, 1350)}

    def thumbnail_variants(self, title: str = "", count: int = 4, formats: str = "", styles: str = "frame,sticker",
                           times: str = "") -> dict:
        """Variante de copertă din momente diferite, pe formatele platformelor, plus o planșă (sheet.png) cu toate
        la mărimea la care le vede omul în feed. Cadrul se încadrează pe fața cea mai mare din el."""
        import shutil as _sh

        import numpy as np

        from .brand import sharpness
        from .style import grab_frame

        tl = self.tl
        if not tl.clips:
            raise ValueError("timeline-ul e gol")
        count = max(1, min(int(count), 8))
        style_list = [x.strip() for x in styles.split(",") if x.strip()] or ["frame"]
        for st_ in style_list:
            if st_ not in ("frame", "sticker"):
                raise ValueError("styles: frame și/sau sticker")
        if formats.strip():
            fmt_list = [x.strip() for x in formats.split(",") if x.strip()]
        else:
            fmt_list = ["cover"] if tl.height > tl.width else ["youtube"] if tl.width > tl.height * 1.2 else ["feed"]
        for f in fmt_list:
            if f not in self.THUMB_FORMATS:
                raise ValueError(f"formats: {', '.join(self.THUMB_FORMATS)}")
        dur = tl.duration
        try:
            from .faces import get_detector

            det = get_detector()
        except Exception:
            det = None
        if times.strip():
            ts = [min(max(float(x), 0.0), max(dur - 0.05, 0.0)) for x in times.split(",") if x.strip()]
            picked = []
            for t in ts:
                c, va, st = self._picture_at(t)
                m = self._asset(va)
                fr = grab_frame(m.path, st, m.width, m.height, width=480)
                faces = det(np.ascontiguousarray(fr[..., ::-1])) if det is not None and fr is not None else []
                big = max(faces, key=lambda f: f.w * f.h, default=None)
                picked.append({"t": round(t, 3), "face": big})
        else:
            cands = []
            n = max(16, count * 6)
            for i in range(n):
                t = round(dur * (0.04 + 0.92 * (i + 0.5) / n), 3)
                c, va, st = self._picture_at(t)
                m = self._asset(va)
                fr = grab_frame(m.path, st, m.width, m.height, width=480)
                if fr is None:
                    continue
                faces = det(np.ascontiguousarray(fr[..., ::-1])) if det is not None else []
                big = max(faces, key=lambda f: f.w * f.h, default=None)
                cands.append({"t": t, "sharp": sharpness(fr), "face": big,
                              "area": (big.w * big.h) if big else 0.0})
            if not cands:
                raise ValueError("nu am putut citi cadre din surse")
            top = max(c["sharp"] for c in cands) or 1.0
            for c in cands:  # claritatea contează, o față mare și clară contează mai mult
                c["score"] = 0.45 * (c["sharp"] / top) + (0.55 * min(1.0, c["area"] * 9) if c["face"] else 0.0)
            gap = dur / (count + 1) * 0.6
            picked = []
            for c in sorted(cands, key=lambda c: -c["score"]):
                if all(abs(c["t"] - p["t"]) >= gap for p in picked):
                    picked.append(c)
                if len(picked) == count:
                    break
            picked.sort(key=lambda c: c["t"])
        out_dir = self.dir / "renders" / "thumbs"
        if out_dir.exists():
            _sh.rmtree(out_dir)
        out_dir.mkdir(parents=True)
        images = []
        original = self.s.timeline
        try:
            for i, cand in enumerate(picked, 1):
                for fmt in fmt_list:
                    W, H = self.THUMB_FORMATS[fmt]
                    tl2 = original.model_copy(deep=True, update={"width": W, "height": H, "fill": "crop"})
                    face = cand.get("face")
                    if face is not None:  # încadrare pe față: ochii puțin peste mijloc
                        for clip, start in zip(tl2.clips, tl2.starts()):
                            if start <= cand["t"] < start + clip.duration:
                                clip.crop.cx = min(max(face.x + face.w / 2, 0.0), 1.0)
                                clip.crop.cy = min(max(face.y + face.h * 0.9, 0.0), 1.0)
                                break
                    self.s.timeline = tl2
                    for st_ in style_list:
                        name = f"thumbs/{i}_{fmt}_{st_}.png"
                        ty, ts, front = None, None, False
                        if title.strip():  # întâi fără titlu, ca să vedem unde e fața în cadrul final
                            base = self.thumbnail_export(cand["t"], "", style=st_, out_name=name)
                            ty, ts, front = self._title_place(base["image"], fmt, st_, det, title)
                        r = self.thumbnail_export(cand["t"], title, style=st_, out_name=name, title_y=ty,
                                                  title_scale=ts, title_front=front)
                        images.append({"file": f"renders/{name}", "at": r["at"], "format": fmt, "style": st_,
                                       "face": face is not None, "title_y": ty, "title_front": front})
        finally:
            self.s.timeline = original
        sheet = self._thumb_sheet(images, out_dir / "sheet.png")
        return {"images": images, "sheet": f"renders/thumbs/{sheet.name}", "formats": fmt_list,
                "note": "planșa arată fiecare variantă la mărimea din feed-ul de pe telefon"}

    # Zona în care titlul se vede: copertele verticale au jos și în dreapta butoanele aplicației (like, caption),
    # iar grila profilului Instagram taie copertă la 3:4 din mijloc => titlul stă între 18% și 66% din înălțime.
    TITLE_BANDS = {"youtube": (0.16, 0.84), "cover": (0.2, 0.64), "feed": (0.15, 0.82)}
    TITLE_SCALE = {"youtube": 0.2, "cover": 0.13, "feed": 0.14}

    def _title_place(self, image: str, fmt: str, style: str, det, title: str = "") -> tuple[float, float, bool]:
        """(y, scale, în_față) pentru titlu: în banda sigură a formatului, în partea opusă feței. La sticker,
        rândul cel mai puțin acoperit de persoană; dacă tot e acoperit peste un sfert, titlul vine în fața ei."""
        import cv2

        lo, hi = self.TITLE_BANDS[fmt]
        scale = self.TITLE_SCALE[fmt] * (1.15 if style == "sticker" else 1.0)
        img = cv2.imread(image)
        if style == "sticker" and img is not None:  # titlul trece prin spatele persoanei: alegem rândul cel mai liber
            try:
                from .segment import matte_image

                alpha = matte_image(img)
                H, W = alpha.shape
                n = max(1, len(title.strip()))
                size = min(min(W, H) * scale, 0.92 * W / n / 0.62)  # ca în captions.title_ass
                tw = min(W * 0.92, n * size * 0.62)
                half = max(2, int(size * 0.55))
                xs = slice(int((W - tw) / 2), int((W + tw) / 2))  # doar unde stau literele
                best = None
                y = lo
                while y <= hi + 1e-6:
                    yc = int(y * H)
                    cover = float(alpha[max(0, yc - half):min(H, yc + half), xs].mean())
                    if best is None or cover < best[0] - 0.01:
                        best = (cover, y)
                    y += 0.03
                return best[1], scale, best[0] > 0.15
            except Exception:  # fără modelul de decupare: regula cu fața, mai jos
                pass
        faces = det(img) if det is not None and img is not None else []
        if not faces:
            return lo + (hi - lo) * 0.15, scale, False
        f = max(faces, key=lambda f: f.w * f.h)
        top, bottom = f.y, f.y + f.h
        # spațiul liber deasupra și dedesubtul feței, în bandă
        above = max(0.0, min(top, hi) - lo)
        below = max(0.0, hi - max(bottom, lo))
        if above >= below:
            return max(lo, (lo + min(top, hi)) / 2), scale, False
        return min(hi, (max(bottom, lo) + hi) / 2 + 0.04), scale, False

    def _thumb_sheet(self, images: list[dict], out: Path) -> Path:
        """Planșa: fiecare variantă la mărimea de feed (YouTube ~360 px lățime, copertă ~200 px, feed ~300 px)."""
        import cv2
        import numpy as np

        feed_w = {"youtube": 360, "cover": 200, "feed": 300}
        tiles = []
        for im in images:
            img = cv2.imread(str(self.dir / im["file"]))
            w = feed_w[im["format"]]
            h = int(img.shape[0] * w / img.shape[1])
            small = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
            label = f"{Path(im['file']).stem}  {im['at']:.1f}s"
            tile = np.full((h + 28, w, 3), 24, np.uint8)
            tile[:h] = small
            cv2.putText(tile, label, (6, h + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (230, 230, 230), 1, cv2.LINE_AA)
            tiles.append(tile)
        row_h = max(t.shape[0] for t in tiles)
        per_row = 4
        rows = []
        for i in range(0, len(tiles), per_row):
            chunk = tiles[i:i + per_row]
            padded = [np.vstack([t, np.full((row_h - t.shape[0], t.shape[1], 3), 24, np.uint8)]) for t in chunk]
            row = np.hstack([np.hstack([t, np.full((row_h, 12, 3), 24, np.uint8)]) for t in padded])
            rows.append(row)
        width = max(r.shape[1] for r in rows)
        rows = [np.hstack([r, np.full((r.shape[0], width - r.shape[1], 3), 24, np.uint8)]) for r in rows]
        sheet = np.vstack([np.vstack([r, np.full((12, width, 3), 24, np.uint8)]) for r in rows])
        cv2.imwrite(str(out), sheet)
        return out

    # ---------- output ----------
    def render(self, preview: bool = True, name: str | None = None) -> dict:
        name = name or ("preview" if preview else "final")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("nume render: doar litere, cifre, _ și -")
        self._check_brand_files()
        out = self.dir / "renders" / f"{name}.mp4"
        # randăm într-un fișier temporar și îl mutăm la final: nimeni nu vede un mp4 pe jumătate scris
        tmp = out.with_name(f".{name}.part.mp4")
        try:
            render(self.tl, self.s.assets, str(tmp), preview=preview)
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
        return {"path": str(out.resolve()), "duration": self.tl.output_duration, "preview": preview}

    def _visual_qa(self, path: str, info, max_points: int = 10) -> list[str]:
        """Verificare vizuală obiectivă (fără vision LLM): unde sursa are o față, render-ul trebuie s-o aibă întreagă
        și neacoperită de subtitrări. Rulează doar când există crop (formatul diferă de al surselor)."""
        try:
            import numpy as np

            from .captions import STYLES
            from .faces import Face, get_detector
            from .style import grab_frame
        except ImportError:
            return []
        tl = self.tl
        ar = tl.width / tl.height
        cropped = [(c, s) for c, s in zip(tl.clips, tl.starts())
                   if tl.fill == "crop" and not c.split and self._asset(c.angle or c.asset).has_video
                   and abs(self._asset(c.angle or c.asset).width / max(self._asset(c.angle or c.asset).height, 1)
                           - ar) > 0.05]
        if not cropped:
            return []
        try:
            det = get_detector("yunet")
        except Exception:
            return []
        step = max(1, len(cropped) // max_points)
        issues: list[str] = []
        style = STYLES.get(tl.caption_style, STYLES["bold_center"])
        cap_bottom = 1 - style["margin_v"]
        cap_top = cap_bottom - 2.4 * style["size"]  # ~2 rânduri de text
        for c, start in cropped[::step][:max_points]:
            t = start + c.body / 2
            if any(b.mode == "full" and b.start <= t < b.end for b in tl.broll):
                continue  # acolo se vede B-roll-ul, nu vorbitorul
            va = c.angle or c.asset
            m = self._asset(va)
            track = self.face_track(va)
            src_t = tl.angle_time(c, va, c.src_at(c.body / 2))
            near = min(track["samples"], key=lambda s: abs(s[0] - src_t), default=None)
            src_faces = [Face(**f) for f in (near[1] if near else []) if f["w"] > 0.04]
            if not src_faces:
                continue
            rgb = grab_frame(path, t, info.width, info.height, width=480)
            if rgb is None:
                continue
            faces = [f for f in det(np.ascontiguousarray(rgb[:, :, ::-1])) if f.w > 0.05]
            tc = f"{int(t // 60):02d}:{t % 60:05.2f}"
            active = any(cp.start <= t < cp.end for cp in tl.captions)
            if not faces:
                # unde AR trebui să fie fața: o proiectăm din sursă prin crop-ul clipului
                from .render import crop_box
                sf = max(src_faces, key=lambda f: f.area)
                cw, ch, x0, y0 = crop_box(m.width, m.height, tl.width, tl.height, c)
                py0, py1 = (sf.y * m.height - y0) / ch, ((sf.y + sf.h) * m.height - y0) / ch
                px0, px1 = (sf.x * m.width - x0) / cw, ((sf.x + sf.w) * m.width - x0) / cw
                inside = px1 > 0.05 and px0 < 0.95 and py1 > 0.05 and py0 < 0.95
                if inside and active and min(py1, cap_bottom) - max(py0, cap_top) > 0.3 * (py1 - py0):
                    issues.append(f"vizual: la {tc} ({c.id}) subtitrarea acoperă fața: reframe(cy mai mic) pe {c.id} "
                                  f"sau stil classic_bottom")
                else:
                    issues.append(f"vizual: la {tc} ({c.id}) sursa are o față, dar în cadru nu se vede: "
                                  f"auto_reframe sau reframe(cx=...) pe {c.id}")
                continue
            big = max(faces, key=lambda f: f.area)
            # o față care umple aproape tot cadrul (selfie foarte apropiat) atinge marginea oricum: nu e o greșeală
            # de încadrare, deci nu o raportăm (agentul ar încerca la nesfârșit să „repare” ceva imposibil)
            if big.w < 0.7 and (big.x < 0.015 or big.x + big.w > 0.985):
                issues.append(f"vizual: la {tc} ({c.id}) fața e tăiată la marginea cadrului: ajustează cx pe {c.id}")
            if active and tl.caption_style in ("bold_center", "karaoke"):
                overlap = min(big.y + big.h, cap_bottom) - max(big.y, cap_top)
                if overlap > 0.3 * big.h:
                    issues.append(f"vizual: la {tc} ({c.id}) subtitrarea acoperă fața: reframe(cy mai mic) pe {c.id} "
                                  f"sau stil classic_bottom")
        return issues

    def qa(self, path: str | None = None) -> dict:
        """Verificări obiective pe fișierul randat. Agentul NU declară 'gata' până nu trece."""
        path = path or str(self.dir / "renders" / "final.mp4")
        info = probe(path)
        issues: list[str] = []
        expected = self.tl.output_duration  # include intro/outro din brand
        if abs(info.duration - expected) > 0.5:
            issues.append(f"durata {info.duration:.2f}s != timeline {expected:.2f}s")
        if (info.width, info.height) != (self.tl.width, self.tl.height) and "preview" not in path:
            issues.append(f"rezoluție {info.width}x{info.height} != {self.tl.width}x{self.tl.height}")
        loud = analyze.loudness(path) if info.has_audio else None
        if loud and abs(loud["lufs"] - self.tl.loudness_lufs) > 2:
            issues.append(f"loudness {loud['lufs']:.1f} LUFS (țintă {self.tl.loudness_lufs})")
        if loud and loud["true_peak_db"] > -0.5:
            issues.append(f"true peak {loud['true_peak_db']:.1f} dB (risc de clipping)")
        black = analyze.black_frames(path, 0.3)
        if black:
            issues.append(f"cadre negre: {black[:5]}")
        long_sil = [s for s in analyze.silences(path, -40, 1.5)] if info.has_audio else []
        if long_sil:
            issues.append(f"liniști >1.5s: {long_sil[:5]}")
        if self.tl.output_duration < 1:
            issues.append("video mai scurt de 1s")
        issues += self._visual_qa(path, info)
        return {"ok": not issues, "issues": issues, "duration": info.duration,
                "resolution": f"{info.width}x{info.height}", "loudness": loud}
