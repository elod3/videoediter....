"""Operații de montaj avansate: viteză, freeze, efecte, motion graphics, efecte sonore, multicam, stabilizare.

Mixin pentru Project (aceleași reguli: orice mutație prin `self.edit()`, erori clare pe care agentul le poate corecta).
"""
from __future__ import annotations

import os
import re

from .timeline import EFFECTS, GRAPHICS, SFX_KINDS, Clip, Crop, Graphic, Sfx, Split, Timeline


def _ids(spec: str) -> list[str]:
    return [x for x in re.split(r"[,\s]+", spec.strip()) if x]


def _new_id(prefix: str, used: set[str]) -> str:
    n = 0
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _in_range(tl: Timeline, t0: float, t1: float) -> list[Clip]:
    """Taie la t0 și t1, apoi întoarce clipurile aflate complet în [t0, t1) (timp de montaj)."""
    if t1 <= t0:
        raise ValueError("end trebuie să fie > start")
    tl.split_at(t0)
    tl.split_at(t1)
    return [c for c, s in zip(tl.clips, tl.starts()) if s >= t0 - 1e-3 and s + c.duration <= t1 + 1e-3]


class EditOps:
    # ------------------------------------------------------------------ viteză și freeze
    def speed_set(self, clip_ids: str, speed: float) -> str:
        """Viteză constantă (0.25-4). Sunetul își păstrează tonul; subtitrările trebuie refăcute după."""
        if not 0.25 <= speed <= 4:
            raise ValueError("speed între 0.25 (slow motion) și 4")
        ids = self._clip_ids(clip_ids)
        with self.edit() as tl:
            for c in tl.clips:
                if c.id in ids:
                    c.speed = round(speed, 4)
        return f"{self._captions_note()}{self.tl.view()}"

    def speed_ramp(self, clip_id: str, speed_from: float = 1.0, speed_to: float = 2.5, steps: int = 5) -> str:
        """Speed ramp: împarte clipul în `steps` bucăți cu viteze care cresc/scad treptat (tăieturi invizibile)."""
        if not (0.25 <= speed_from <= 4 and 0.25 <= speed_to <= 4):
            raise ValueError("vitezele între 0.25 și 4")
        if not 2 <= steps <= 12:
            raise ValueError("steps între 2 și 12")
        with self.edit() as tl:
            c = tl.clip(clip_id)
            i = tl.clips.index(c)
            span = (c.src_out - c.src_in) / steps
            if span < 0.08:
                raise ValueError("clipul e prea scurt pentru atâtea trepte")
            used = {x.id for x in tl.clips}
            parts = []
            for k in range(steps):
                p = c.model_copy(deep=True)
                if k:
                    p.id = _new_id(f"{c.id}s", used)
                    used.add(p.id)
                    p.transition = None
                p.src_in = round(c.src_in + k * span, 3)
                p.src_out = round(c.src_out if k == steps - 1 else c.src_in + (k + 1) * span, 3)
                # ease-in-out între viteze: tranziția de ritm se simte naturală
                x = (k + 0.5) / steps
                e = x * x * (3 - 2 * x)
                p.speed = round(speed_from + (speed_to - speed_from) * e, 3)
                p.freeze = c.freeze if k == steps - 1 else 0.0
                p.anim = None
                parts.append(p)
            tl.clips[i:i + 1] = parts
        return f"{self._captions_note()}{self.tl.view()}"

    def freeze_frame(self, clip_id: str, seconds: float = 1.0) -> str:
        """Îngheață ultimul cadru al clipului `seconds` secunde (0 = scoate). Bun cu un title_card sau callout peste."""
        if not 0 <= seconds <= 6:
            raise ValueError("freeze între 0 și 6 secunde")
        with self.edit() as tl:
            tl.clip(clip_id).freeze = round(seconds, 3)
        return f"{self._captions_note()}{self.tl.view()}"

    def _captions_note(self) -> str:
        return "ATENȚIE: durata s-a schimbat; refă subtitrările (captions_add) și verifică graficele.\n" \
            if self.tl.captions or self.tl.graphics else ""

    # ------------------------------------------------------------------ efecte vizuale
    def clip_fx(self, clip_ids: str, effects: str = "", mode: str = "add") -> str:
        """Efecte vizuale pe clipuri: add / set / clear. Lista: EFFECTS."""
        fx = _ids(effects)
        bad = [f for f in fx if f not in EFFECTS]
        if bad:
            raise ValueError(f"efecte necunoscute: {', '.join(bad)}; disponibile: {', '.join(EFFECTS)}")
        if mode not in ("add", "set", "clear"):
            raise ValueError("mode: add, set sau clear")
        ids = self._clip_ids(clip_ids)
        with self.edit() as tl:
            for c in tl.clips:
                if c.id not in ids:
                    continue
                if mode == "clear":
                    c.fx = [f for f in c.fx if f not in fx] if fx else []
                elif mode == "set":
                    c.fx = fx
                else:
                    c.fx = c.fx + [f for f in fx if f not in c.fx]
        return self.tl.view()

    def stabilize(self, aid: str, smoothing: int = 15, off: bool = False) -> str:
        """Stabilizare vidstab în două treceri; fișierul stabilizat se folosește la randare în locul sursei."""
        from .ff import run

        m = self._asset(aid)
        if not m.has_video:
            raise ValueError(f"{aid} nu are video")
        if off:
            with self.edit() as tl:
                tl.stabilized.pop(aid, None)
            return f"{aid}: stabilizarea scoasă"
        if not 5 <= smoothing <= 60:
            raise ValueError("smoothing între 5 (ușor) și 60 (foarte lin)")
        cache = self.dir / "cache"
        out = cache / f"{aid}.stab{smoothing}.mp4"
        if not out.exists():
            trf = f"{aid}.trf"
            src = os.path.abspath(m.path)
            run(["-y", "-i", src, "-vf", f"vidstabdetect=shakiness=6:accuracy=12:result={trf}", "-f", "null", "-"],
                cwd=str(cache))
            tmp = cache / f".{out.name}"
            run(["-y", "-i", src, "-vf", f"vidstabtransform=input={trf}:smoothing={smoothing}:zoom=0:optzoom=1,"
                 "unsharp=5:5:0.6", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
                 "-c:a", "copy", str(tmp)], cwd=str(cache))
            tmp.replace(out)
        with self.edit() as tl:
            tl.stabilized[aid] = str(out.resolve())
        return f"{aid}: stabilizat (smoothing {smoothing}); marginile se decupează ușor (optzoom)"

    def broll_key(self, bid: str, color: str = "#00FF00") -> str:
        """Green screen pe un B-roll: fundalul de culoarea `color` devine transparent. color='none' scoate."""
        from .captions import norm_hex

        key = None if color.lower() == "none" else norm_hex(color)
        with self.edit() as tl:
            b = next((x for x in tl.broll if x.id == bid), None)
            if b is None:
                raise KeyError(f"B-roll inexistent: {bid}")
            b.chroma = key
        return self.tl.view()

    # ------------------------------------------------------------------ motion graphics
    def graphic_add(self, kind: str, start: float, end: float, **fields) -> str:
        from .graphics import validate

        if kind not in GRAPHICS:
            raise ValueError(f"grafic necunoscut; disponibile: {', '.join(GRAPHICS)}")
        dur = self.tl.duration
        if start >= dur:
            raise ValueError(f"start={start} e după finalul montajului ({dur:.2f}s)")
        fields = {k: v for k, v in fields.items() if v not in (None, "")}
        if isinstance(fields.get("items"), str):
            fields["items"] = [x.strip() for x in fields["items"].split("|") if x.strip()]
        with self.edit() as tl:
            g = Graphic(id=_new_id("g", {x.id for x in tl.graphics}), kind=kind, start=round(max(start, 0), 3),
                        end=round(min(end, dur), 3), **fields)
            validate(g)
            tl.graphics.append(g)
        return f"{g.id} adăugat\n{self.tl.view()}"

    def graphic_remove(self, ids: str) -> str:
        want = set(_ids(ids))
        with self.edit() as tl:
            missing = want - {g.id for g in tl.graphics}
            if missing:
                raise KeyError(f"grafice inexistente: {', '.join(sorted(missing))}")
            tl.graphics = [g for g in tl.graphics if g.id not in want]
        return self.tl.view()

    # ------------------------------------------------------------------ efecte sonore
    def sfx_add(self, kind: str, at: float, volume_db: float = -8.0) -> str:
        if kind not in SFX_KINDS:
            m = self.s.assets.get(kind)
            if m is None or not m.has_audio:
                raise ValueError(f"sfx necunoscut; presetări: {', '.join(SFX_KINDS)} sau id-ul unui asset audio")
        if not -40 <= volume_db <= 6:
            raise ValueError("volume_db între -40 și 6")
        if not 0 <= at < self.tl.duration:
            raise ValueError(f"at în afara montajului (0-{self.tl.duration:.2f}s)")
        with self.edit() as tl:
            s = Sfx(id=_new_id("x", {x.id for x in tl.sfx}), kind=kind, at=round(at, 3), volume_db=volume_db)
            tl.sfx.append(s)
        return f"{s.id} adăugat\n{self.tl.view()}"

    def sfx_remove(self, ids: str) -> str:
        want = set(_ids(ids))
        with self.edit() as tl:
            if want == {"all"}:
                tl.sfx = []
            else:
                missing = want - {x.id for x in tl.sfx}
                if missing:
                    raise KeyError(f"sfx inexistente: {', '.join(sorted(missing))}")
                tl.sfx = [x for x in tl.sfx if x.id not in want]
        return self.tl.view()

    def sfx_auto(self, transitions: bool = True, graphics: bool = True, punch_ins: bool = True,
                 volume_db: float = -10.0) -> str:
        """Efecte sonore acolo unde un editor le-ar pune: whoosh pe tranziții, pop/impact pe grafice, swipe pe
        punch-in. Refacerea înlocuiește doar efectele puse automat (id `xa…`), nu pe cele puse de mână."""
        from .sfx import duration as sfx_dur

        tl = self.tl
        plan: list[tuple[str, float, float]] = []
        starts = tl.starts()
        if transitions:
            for c, s in zip(tl.clips[1:], starts[1:]):
                if c.transition:  # vârful whoosh-ului pe mijlocul tranziției
                    plan.append(("whoosh", s + c.transition.duration / 2 - sfx_dur("whoosh") / 2, 0))
        if punch_ins:
            for a, b, s in zip(tl.clips, tl.clips[1:], starts[1:]):
                if not b.transition and a.asset == b.asset and abs(a.crop.zoom - b.crop.zoom) > 0.08:
                    plan.append(("swipe", s - 0.05, -4))
        if graphics:
            sound = {"title_card": "impact", "lower_third": "swipe", "callout": "pop", "cta": "pop", "list": "pop",
                     "kinetic": "pop", "circle": "pop", "counter": "ding"}
            for g in tl.graphics:
                kind = sound.get(g.kind)
                if not kind:
                    continue
                at = g.start + 0.7 * g.duration if g.kind == "counter" else g.start
                plan.append((kind, at, -3 if kind == "impact" else 0))
                if g.kind == "list":  # câte un pop pe fiecare rând care apare
                    step = 0.6 * g.duration / max(len(g.items), 1)
                    plan += [("pop", g.start + step * k, -2) for k in range(1, len(g.items))]
        plan = sorted((k, round(max(at, 0), 3), extra) for k, at, extra in plan if at < tl.duration - 0.05)
        with self.edit() as tl:
            tl.sfx = [x for x in tl.sfx if not x.id.startswith("xa")]
            used = {x.id for x in tl.sfx}
            for kind, at, extra in plan:
                sid = _new_id("xa", used)
                used.add(sid)
                tl.sfx.append(Sfx(id=sid, kind=kind, at=at, volume_db=volume_db + extra))
        counts = {}
        for kind, _, _ in plan:
            counts[kind] = counts.get(kind, 0) + 1
        summary = ", ".join(f"{n}× {k}" for k, n in counts.items()) or "nimic (nu există tranziții, punch-in sau grafice)"
        return f"sfx automat: {summary}\n{self.tl.view()}"

    # ------------------------------------------------------------------ multicam
    def multicam_sync(self, angles: str, reference: str = "") -> str:
        """Sincronizează camerele după sunet. `angles`: asset-urile (ex. 'a0,a1,a2'); referința = primul."""
        from .multicam import find_offset

        ids = _ids(angles)
        ref = reference or ids[0]
        if ref not in ids:
            ids.insert(0, ref)
        if len(ids) < 2:
            raise ValueError("dă cel puțin două camere, ex. angles='a0,a1'")
        for aid in ids:
            m = self._asset(aid)
            if not (m.has_video and m.has_audio):
                raise ValueError(f"{aid} trebuie să aibă video și sunet (sincronizarea se face după sunet)")
        base = self.tl.sync.get(ref, 0.0)
        res, weak = {ref: base}, []
        lines = [f"{ref}: referință"]
        for aid in ids:
            if aid == ref:
                continue
            off, conf = find_offset(self._asset(ref).path, self._asset(aid).path)
            res[aid] = round(base + off, 4)
            lines.append(f"{aid}: {off:+.3f}s față de {ref} (încredere {conf:.2f})")
            if conf < 0.2:
                weak.append(aid)
        if weak:
            raise ValueError("sincronizare nesigură pentru " + ", ".join(weak) + ": sunetul nu seamănă destul "
                             "(camere fără microfon? alt moment?).\n" + "\n".join(lines))
        with self.edit() as tl:
            tl.sync.update(res)
        return "sincronizat:\n" + "\n".join(lines)

    def _check_angle(self, tl: Timeline, c: Clip, angle: str) -> None:
        if angle == c.asset:
            return
        m = self._asset(angle)
        if not m.has_video:
            raise ValueError(f"{angle} nu are video")
        a = tl.angle_time(c, angle, c.src_in)
        b = tl.angle_time(c, angle, c.src_out)
        if a < -0.05 or b > m.duration + 0.05:
            raise ValueError(f"{angle} nu acoperă momentul {c.id} ({a:.2f}-{b:.2f}s din {m.duration:.2f}s)")

    def multicam_angle(self, start: float, end: float, angle: str) -> str:
        """Pe intervalul [start, end) din montaj se vede camera `angle` (sunetul rămâne cel principal)."""
        with self.edit() as tl:
            for c in _in_range(tl, start, end):
                self._check_angle(tl, c, angle)
                c.angle = None if angle == c.asset else angle
                c.split = None
        return self.tl.view()

    def _speaker_segments(self, tl: Timeline) -> list[tuple[float, float, str]]:
        segs: list[list] = []
        for c, s in zip(tl.clips, tl.starts()):
            f = self.dir / "cache" / f"{c.asset}.transcript.json"
            if not f.exists():
                continue
            words = [w for w in self.transcript(c.asset).words
                     if w.spk and w.end > c.src_in and w.start < c.src_out]
            for w in words:
                a = max(c.tl_at(s, max(w.start, c.src_in)), s)
                b = min(c.tl_at(s, min(w.end, c.src_out)), s + c.body)
                if segs and segs[-1][2] == w.spk and a - segs[-1][1] < 0.8:
                    segs[-1][1] = b
                else:
                    segs.append([a, b, w.spk])
        return [(a, b, spk) for a, b, spk in segs if b > a]

    def multicam_auto(self, mode: str = "speaker", mapping: str = "", wide: str = "", min_shot: float = 1.5,
                      every: float = 4.0, wide_every: float = 0.0) -> str:
        """Montaj multicam automat. mode='speaker': fiecare vorbitor pe camera lui (mapping 'S0=a1,S1=a2'),
        wide la suprapuneri. mode='rotate': schimbă camerele (din mapping sau toate cele sincronizate) la ~`every`
        secunde, pe finaluri de cuvânt."""
        from .multicam import plan_switches, rotate_switches

        tl = self.tl
        if not tl.clips:
            raise ValueError("timeline-ul e gol")
        if len(tl.sync) < 2:
            raise ValueError("rulează întâi multicam_sync cu toate camerele")
        pairs = dict(p.split("=", 1) for p in _ids(mapping)) if mapping else {}
        for a in [*pairs.values(), *([wide] if wide else [])]:
            if a not in tl.sync:
                raise ValueError(f"{a} nu e sincronizat (multicam_sync)")
        dur = tl.duration
        if mode == "speaker":
            segs = self._speaker_segments(tl)
            if not segs:
                raise ValueError("nu știu cine vorbește: rulează diarize (și transcrierea) pe sursa principală")
            speakers = sorted({s for _, _, s in segs})
            missing = [s for s in speakers if s not in pairs]
            if missing:
                raise ValueError(f"lipsește camera pentru {', '.join(missing)}: mapping ca 'S0=a1,S1=a2'. "
                                 f"Folosește speakers/frames_look ca să vezi cine e pe ce cameră.")
            ranges = plan_switches(segs, pairs, dur, wide or None, min_shot, wide_every)
        elif mode == "rotate":
            angles = list(dict.fromkeys(pairs.values())) or list(tl.sync)
            bounds = []
            for c, s in zip(tl.clips, tl.starts()):
                f = self.dir / "cache" / f"{c.asset}.transcript.json"
                if f.exists():
                    bounds += [c.tl_at(s, w.end) for w in self.transcript(c.asset).words
                               if c.src_in < w.end <= c.src_out]
            ranges = rotate_switches(dur, angles, every, bounds or None)
        else:
            raise ValueError("mode: speaker sau rotate")
        with self.edit() as tl:
            for a, b, angle in ranges:
                for c in _in_range(tl, a, b):
                    if c.asset not in tl.sync:
                        continue
                    self._check_angle(tl, c, angle)
                    c.angle = None if angle == c.asset else angle
                    c.split = None
        shots = " ".join(f"{a:.1f}-{b:.1f}:{x}" for a, b, x in ranges)
        return f"multicam {mode}: {len(ranges)} cadre\n{shots}\nVerifică încadrarea (auto_reframe pe unghiuri).\n" \
               f"{self.tl.view()}"

    def split_screen(self, start: float, end: float, angles: str = "", mode: str = "stack") -> str:
        """Două camere în același cadru (stack = sus/jos pentru 9:16, side = stânga/dreapta). angles='' scoate."""
        ids = _ids(angles)
        if ids and len(ids) != 2:
            raise ValueError("split_screen cere exact două camere, ex. angles='a1,a2'")
        if mode not in ("stack", "side"):
            raise ValueError("mode: stack sau side")
        with self.edit() as tl:
            clips = _in_range(tl, start, end)
            if not ids:
                for c in clips:
                    c.split = None
            else:
                crops = [self._face_crop(aid) for aid in ids]
                for c in clips:
                    for aid in ids:
                        self._check_angle(tl, c, aid)
                    c.split = Split(angles=ids, mode=mode, crops=[x.model_copy() for x in crops])
                    c.angle = None
        return self.tl.view()

    def _face_crop(self, aid: str) -> Crop:
        """Centrul mediu al celei mai mari fețe din asset (pentru panourile de split-screen)."""
        try:
            track = self.face_track(aid)
        except Exception:  # fără detector => centru
            return Crop()
        pts = []
        for _, faces in track["samples"]:
            if faces:
                f = max(faces, key=lambda f: f["w"] * f["h"])
                pts.append((f["x"] + f["w"] / 2, f["y"] + f["h"] / 2))
        if not pts:
            return Crop()
        pts.sort()
        cx = pts[len(pts) // 2][0]
        cy = sorted(p[1] for p in pts)[len(pts) // 2]
        return Crop(cx=round(cx, 3), cy=round(min(max(cy + 0.08, 0), 1), 3))  # puțin loc deasupra capului


__all__ = ["EditOps"]
