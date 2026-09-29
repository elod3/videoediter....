"""Proiect = asset-uri + cache de analize + timeline + istoric (undo).

Toate operațiile de nivel înalt pe care le apelează agentul trăiesc aici;
serverul MCP și CLI-ul sunt doar învelișuri subțiri peste această clasă.
Starea stă pe disc => agentul nu trebuie să țină timeline-ul în context.
"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

from pydantic import BaseModel

from . import analyze, reframe as rf
from .captions import STYLES, build_captions
from .probe import MediaInfo, probe
from .render import render
from .timeline import FORMATS, Crop, Music, TextOverlay, Timeline
from .transcribe import Transcript, transcribe

MAX_HISTORY = 50


def home() -> Path:
    return Path(os.environ.get("VEDIT_HOME", "./vedit_projects")).resolve()


class ProjectState(BaseModel):
    name: str
    assets: dict[str, MediaInfo] = {}
    timeline: Timeline = Timeline()
    history: list[Timeline] = []


class Project:
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
        except Exception:
            self.s.timeline = snapshot  # operație eșuată => starea rămâne neatinsă
            raise
        self.s.history = (self.s.history + [snapshot])[-MAX_HISTORY:]
        self.save()

    def undo(self) -> str:
        if not self.s.history:
            return "nimic de anulat"
        self.s.timeline = self.s.history.pop()
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
    def add_asset(self, path: str, asset_id: str | None = None) -> str:
        info = probe(os.path.abspath(path))
        aid = asset_id or f"a{len(self.s.assets)}"
        self.s.assets[aid] = info
        self.save()
        return f"{aid}: {Path(path).name} ({info.summary()})"

    def list_assets(self) -> str:
        return "\n".join(f"{k}: {Path(v.path).name} ({v.summary()})" for k, v in self.s.assets.items()) or "-"

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

    # ---------- editare ----------
    def set_format(self, fmt: str = "9:16", fps: float | None = None, fill: str | None = None) -> str:
        if fmt not in FORMATS:
            raise ValueError(f"format necunoscut; disponibile: {', '.join(FORMATS)}")
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
                m = self._asset(c.asset)
                if c.id not in ids or not m.has_video:
                    new.append(c)
                    continue
                if c.asset not in tracks:
                    tracks[c.asset] = self.face_track(c.asset, fps, backend)
                    backend_used.add(tracks[c.asset]["backend"])
                    scene_cache[c.asset] = self._cache(c.asset, "scenes_0.3", lambda: analyze.scenes(m.path, 0.3))
                samples = [(t, [Face(**f) for f in fs]) for t, fs in tracks[c.asset]["samples"]]
                cwf, chf = rf.crop_fraction(m.width, m.height, tl.width, tl.height, c.crop.zoom)
                def refine(ta, tb, old, new, m=m, cwf=cwf, chf=chf):
                    return locate_change(m.path, m.width, m.height, ta, tb, old, new, cwf, chf, backend=backend)

                segs = rf.plan(samples, c.src_in, c.src_out, cwf, chf, split=split,
                               scene_cuts=scene_cache[c.asset], refine=refine)
                if speaker and m.has_audio:
                    segs = [x for s in segs for x in (self._speaker_split(c.asset, s, chf) if s.flag == "wide" else [s])]
                for k, s in enumerate(segs):
                    part = c.model_copy(deep=True)
                    if k:
                        n = k
                        while f"{c.id}r{n}" in used:
                            n += 1
                        part.id = f"{c.id}r{n}"
                        used.add(part.id)
                    part.src_in, part.src_out = round(s.t0, 3), round(s.t1, 3)
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
        return "\n".join([head, *report])

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

    def set_music(self, aid: str | None, volume_db: float = -18, duck: bool = True) -> str:
        with self.edit() as tl:
            tl.music = Music(asset=aid, volume_db=volume_db, duck=duck) if aid else None
            if aid:
                self._asset(aid)
        return self.tl.view()

    # ---------- output ----------
    def render(self, preview: bool = True, name: str | None = None) -> dict:
        name = name or ("preview" if preview else "final")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
            raise ValueError("nume render: doar litere, cifre, _ și -")
        out = self.dir / "renders" / f"{name}.mp4"
        # randăm într-un fișier temporar și îl mutăm la final: nimeni nu vede un mp4 pe jumătate scris
        tmp = out.with_name(f".{name}.part.mp4")
        try:
            render(self.tl, self.s.assets, str(tmp), preview=preview)
            tmp.replace(out)
        finally:
            tmp.unlink(missing_ok=True)
        return {"path": str(out.resolve()), "duration": self.tl.duration, "preview": preview}

    def qa(self, path: str | None = None) -> dict:
        """Verificări obiective pe fișierul randat. Agentul NU declară 'gata' până nu trece."""
        path = path or str(self.dir / "renders" / "final.mp4")
        info = probe(path)
        issues: list[str] = []
        if abs(info.duration - self.tl.duration) > 0.5:
            issues.append(f"durata {info.duration:.2f}s != timeline {self.tl.duration:.2f}s")
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
        if self.tl.duration < 1:
            issues.append("video mai scurt de 1s")
        return {"ok": not issues, "issues": issues, "duration": info.duration,
                "resolution": f"{info.width}x{info.height}", "loudness": loud}
