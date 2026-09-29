"""Operații de montaj avansate: viteză, freeze, efecte, motion graphics, efecte sonore, multicam, stabilizare.

Mixin pentru Project (aceleași reguli: orice mutație prin `self.edit()`, erori clare pe care agentul le poate corecta).
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .timeline import EFFECTS, GRAPHICS, SFX_KINDS, Chapter, Clip, Crop, Graphic, Sfx, Split, Timeline


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
        return "Durata s-a schimbat: subtitrările, graficele, B-roll-ul și efectele sonore s-au mutat odată cu " \
            "vorbirea; verifică-le în preview.\n" if self.tl.captions or self.tl.graphics else ""

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

    def _matte(self, aid: str, until: float) -> str:
        """Masca persoanei pentru asset, calculată până la secunda `until` (refolosită dacă acoperă deja)."""
        from .probe import probe
        from .segment import matte_video

        m = self._asset(aid)
        out = self.dir / "cache" / f"{aid}.matte.mp4"
        still = (self.s.meta.get(aid) or {}).get("source") == "image"
        if out.exists() and (still or probe(str(out)).duration >= min(until, m.duration) - 0.15):
            return str(out.resolve())
        need = m.duration if still else min(m.duration, until + 5.0)  # puțină rezervă pentru ajustări
        matte_video(os.path.abspath(m.path), str(out), m.width, m.height, until=None if still else need,
                    still=m.duration if still else 0.0)
        return str(out.resolve())

    def background(self, clip_ids: str, mode: str = "blur", value: str = "") -> str:
        """Fundalul din spatele persoanei, fără green screen: blur (portret), color (#RRGGBB), asset (poză / clip
        de fundal), none (original). Prima dată calculează masca persoanei (durează ~1-3x lungimea clipului)."""
        from .captions import norm_hex
        from .timeline import Background

        if mode not in ("blur", "color", "asset", "none"):
            raise ValueError("mode: blur, color, asset sau none")
        if mode == "color":
            value = norm_hex(value or "#101010")
        if mode == "asset":
            bm = self._asset(value)
            if not bm.has_video:
                raise ValueError(f"{value} nu are imagine (fundalul e o poză sau un clip)")
        ids = self._clip_ids(clip_ids)
        clips = [c for c in self.tl.clips if c.id in ids]
        if any(c.split for c in clips):
            raise ValueError("fundalul nu merge pe clipuri split-screen")
        mattes = {}
        if mode != "none":
            need: dict[str, float] = {}
            for c in self.tl.clips:  # masca trebuie să acopere toate clipurile cu fundal (vechi și noi)
                if c.id in ids or c.bg:
                    va = c.angle or c.asset
                    need[va] = max(need.get(va, 0.0), self.tl.angle_time(c, va, c.src_out))
            for aid, until in need.items():
                if not self._asset(aid).has_video:
                    raise ValueError(f"{aid} nu are imagine")
                mattes[aid] = self._matte(aid, until)
        with self.edit() as tl:
            tl.mattes.update(mattes)
            for c in tl.clips:
                if c.id in ids:
                    c.bg = None if mode == "none" else Background(mode=mode, value=value)
        return f"fundal {mode} pe {len(ids)} clipuri; verifică marginile (păr, mâini) cu frames_look\n{self.tl.view()}"

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
        if fields.get("behind") and kind not in ("title_card", "kinetic", "counter", "list"):
            raise ValueError("behind (text în spatele persoanei) merge la title_card, kinetic, counter și list")
        if isinstance(fields.get("items"), str):
            fields["items"] = [x.strip() for x in fields["items"].split("|") if x.strip()]
        with self.edit() as tl:
            g = Graphic(id=_new_id("g", {x.id for x in tl.graphics}), kind=kind, start=round(max(start, 0), 3),
                        end=round(min(end, dur), 3), **fields)
            validate(g)
            tl.graphics.append(g)
            if g.behind:  # masca persoanei pentru clipurile de sub grafic
                for c, s in zip(tl.clips, tl.starts()):
                    va = c.angle or c.asset
                    if not c.split and s < g.end and s + c.duration > g.start and self._asset(va).has_video:
                        tl.mattes[va] = self._matte(va, tl.angle_time(c, va, c.src_out))
        note = " (în spatele persoanei)" if g.behind else ""
        return f"{g.id} adăugat{note}\n{self.tl.view()}"

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

    # ------------------------------------------------------------------ corecturi de text
    def transcript_fix(self, asset: str, fixes: str) -> str:
        """Corectează cuvinte transcrise greșit (nume, branduri): 'w12=Mihai|w40=vedit'. Subtitrările făcute din
        acest transcript se refac automat, cu același stil."""
        from .captions import build_captions

        tr = self.transcript(asset)
        by_id = {w.i: w for w in tr.words}
        changed = []
        for part in [x for x in fixes.split("|") if x.strip()]:
            if "=" not in part:
                raise ValueError(f"corectură invalidă {part!r}: format 'w12=Text'")
            wid, text = part.split("=", 1)
            m = re.fullmatch(r"\s*w?(\d+)\s*", wid)
            text = " ".join(text.split())
            if not m or int(m[1]) not in by_id:
                raise ValueError(f"cuvânt inexistent: {wid.strip()}")
            if not text or len(text) > 40:
                raise ValueError("textul corectat: 1-40 caractere")
            w = by_id[int(m[1])]
            changed.append(f"w{w.i}: {w.text} -> {text}")
            w.text = text
        self.set_transcript(asset, tr)
        rebuilt = any((c.word_ids or [""])[0].startswith(f"{asset}:") for c in self.tl.captions)
        if rebuilt:
            with self.edit() as tl:
                build_captions(tl, asset, self.transcript(asset), style=tl.caption_style)
        return "corectat: " + "; ".join(changed) + (" (subtitrările refăcute)" if rebuilt else "")

    def captions_list(self) -> str:
        return "\n".join(f"{k} [{c.start:.2f}-{c.end:.2f}] {c.text}" for k, c in enumerate(self.tl.captions)) \
            or "(fără subtitrări)"

    def captions_text(self, items: str) -> str:
        """Rescrie textul unor subtitrări după index: '0=Hello everyone|1=Today we talk'. Pentru traduceri și
        reformulări; acele subtitrări pierd sincronizarea pe cuvânt (karaoke / evidențiere)."""
        edits = {}
        for part in [x for x in items.split("|") if x.strip()]:
            if "=" not in part:
                raise ValueError(f"format 'index=text', nu {part!r}")
            k, text = part.split("=", 1)
            text = " ".join(text.split())
            if not k.strip().isdigit() or not text or len(text) > 120:
                raise ValueError(f"subtitrare invalidă: {part[:40]!r} (index + text de 1-120 caractere)")
            edits[int(k)] = text
        with self.edit() as tl:
            bad = [k for k in edits if k >= len(tl.captions)]
            if bad:
                raise ValueError(f"indexuri inexistente: {bad} (sunt {len(tl.captions)} subtitrări)")
            for k, text in edits.items():
                c = tl.captions[k]
                c.text, c.word_ids, c.word_durs = text, None, None
        return f"{len(edits)} subtitrări rescrise"

    # ------------------------------------------------------------------ voice-over și faceless
    def voiceover(self, script: str, lang: str = "ro", speed: float = 1.0, start: float = 0.0) -> str:
        """Textul devine voce (Piper, local) pe pista A3, cu transcript exact (subtitrări perfect sincronizate).
        Pentru clipuri fără persoană pe ecran: apoi visuals_fill cu pozele / clipurile, captions_add pe voice-over."""
        import hashlib

        from .timeline import Narration
        from .transcribe import Transcript, Word
        from .tts import synth

        script = " ".join(script.split())
        if not 3 <= len(script) <= 5000:
            raise ValueError("scriptul: între 3 și 5000 de caractere")
        key = hashlib.sha1(f"{lang}|{speed}|{script}".encode()).hexdigest()[:10]
        out = self.dir / "uploads" / f"voiceover_{key}.wav"
        out.parent.mkdir(parents=True, exist_ok=True)
        words = synth(script, lang, str(out), speed) if not out.exists() else None
        aid = next((k for k, m in self.s.meta.items() if m.get("source") == "voiceover" and m.get("key") == key), None)
        if aid is None:
            n = 0
            while f"vo{n}" in self.s.assets:
                n += 1
            aid = f"vo{n}"
            self.add_asset(str(out), aid)
            if words is None:  # fișierul exista, dar asset-ul nu: timpii se refac din sinteză
                out.unlink()
                words = synth(script, lang, str(out), speed)
            self.set_transcript(aid, Transcript(words=[Word(i=i, start=a, end=b, text=t)
                                                       for i, (a, b, t) in enumerate(words)]))
            self.s.meta[aid] = {"source": "voiceover", "key": key, "lang": lang, "text": script[:300]}
            self.save()
        with self.edit() as tl:
            tl.narration = Narration(asset=aid, start=round(max(start, 0.0), 3))
        dur = self._asset(aid).duration
        return (f"{aid}: voice-over {dur:.1f}s ({lang}) pe A3 de la {start:.2f}s. Imaginea (V1) trebuie să țină "
                f"până la {start + dur:.1f}s: visuals_fill. Subtitrări: captions_add(asset='{aid}').")

    def narration_set(self, asset: str, start: float = 0.0, volume_db: float = 0.0) -> str:
        """O înregistrare urcată (vocea clientului, un podcast audio) devine narațiunea de pe A3. asset='' o scoate."""
        from .timeline import Narration

        if not asset:
            with self.edit() as tl:
                tl.narration = None
            return "narațiunea scoasă"
        if not self._asset(asset).has_audio:
            raise ValueError(f"{asset} nu are sunet")
        with self.edit() as tl:
            tl.narration = Narration(asset=asset, start=round(max(start, 0.0), 3), volume_db=volume_db)
        return (f"{asset} e narațiunea (A3) de la {start:.2f}s, {self._asset(asset).duration:.1f}s. Subtitrări: "
                f"captions_add(asset='{asset}') (transcrierea se face la primul apel).")

    def visuals_fill(self, assets: str, per: float = 3.0, until: float = 0.0, kenburns: bool = True,
                     at_words: str = "") -> str:
        """Umple pista V1 cu imaginile date (poze / clipuri), câte `per` secunde fiecare, pe rând, până la `until`
        (implicit: finalul voice-over-ului). Sunetul lor e oprit (vorbește narațiunea); pozele primesc Ken Burns."""
        from .timeline import ZoomAnim

        ids = _ids(assets)
        if not ids:
            raise ValueError("dă cel puțin un asset cu imagine, ex. assets='a1,a2,a3'")
        for aid in ids:
            if not self._asset(aid).has_video:
                raise ValueError(f"{aid} nu are imagine")
        if not 1.0 <= per <= 15:
            raise ValueError("per între 1 și 15 secunde")
        tl = self.tl
        if until <= 0:
            if not tl.narration:
                raise ValueError("dă until (secunde) sau pune întâi un voice-over")
            until = tl.narration.start + self._asset(tl.narration.asset).duration + 0.3
        # at_words: fiecare asset începe pe cuvântul lui din voice-over (imaginea urmează ce se spune)
        plan: list[tuple[float, str]] = []
        if at_words:
            if not tl.narration:
                raise ValueError("at_words cere un voice-over (voiceover / narration_set)")
            marks = [w for w in _ids(at_words)]
            if len(marks) != len(ids):
                raise ValueError(f"at_words are {len(marks)} cuvinte, assets are {len(ids)}: câte unul pentru fiecare")
            times = {w.i: w.start for w in self.transcript(tl.narration.asset).words}
            for aid, mark in zip(ids, marks):
                m = re.fullmatch(r"w?(\d+)", mark)
                if not m or int(m[1]) not in times:
                    raise ValueError(f"cuvânt inexistent în voice-over: {mark}")
                plan.append((0.0 if not plan else tl.narration.start + times[int(m[1])], aid))
            if any(b[0] <= a[0] for a, b in zip(plan, plan[1:])):
                raise ValueError("at_words trebuie să fie în ordinea din voice-over")
        pos = {aid: 0.0 for aid in ids}
        with self.edit() as tl:
            tl.clips = []
            t, k = 0.0, 0
            while t < until - 0.05:
                if plan:  # asset-ul curent după timp; în interiorul unui segment lung, cadre de ~per secunde
                    aid = [a for s, a in plan if s <= t + 1e-3][-1]
                    nxt = next((s for s, _ in plan if s > t + 1e-3), until)
                    seg_end = min(nxt, until)
                    left = seg_end - t
                    d = left if left < per * 1.5 else per
                    m = self._asset(aid)
                    if pos[aid] + d > m.duration:
                        pos[aid] = 0.0
                    d = min(d, m.duration)
                    c = tl.add_clip(aid, pos[aid], pos[aid] + d)
                    c.volume_db = -100.0
                    if kenburns and (self.s.meta.get(aid) or {}).get("source") == "image":
                        c.anim = ZoomAnim(zoom_from=1.0, zoom_to=1.12) if k % 2 == 0 else \
                            ZoomAnim(zoom_from=1.12, zoom_to=1.0)
                    pos[aid] += d
                    t += d
                    k += 1
                    continue
                aid = ids[k % len(ids)]
                m = self._asset(aid)
                d = min(per, until - t)
                if pos[aid] + d > m.duration:  # clipul s-a terminat: o luăm de la capăt
                    pos[aid] = 0.0
                d = min(d, m.duration)
                c = tl.add_clip(aid, pos[aid], pos[aid] + d)
                c.volume_db = -100.0
                if kenburns and (self.s.meta.get(aid) or {}).get("source") == "image":
                    c.anim = ZoomAnim(zoom_from=1.0, zoom_to=1.12) if k % 2 == 0 else ZoomAnim(zoom_from=1.12, zoom_to=1.0)
                pos[aid] += d
                t += d
                k += 1
        return f"V1: {len(self.tl.clips)} cadre din {', '.join(ids)}, {self.tl.duration:.1f}s\n{self.tl.view()}"

    # ------------------------------------------------------------------ brand kit pe cont
    def _kits_dir(self) -> Path:
        """Kit-urile aparțin proprietarului proiectului (u12-nume -> u12): un client nu vede kit-urile altuia."""
        from .project import home

        m = re.match(r"^(u\d+)-", self.s.name)
        return home() / ".brand" / (m[1] if m else "default")

    def brand_kit_list(self) -> list[dict]:
        root = self._kits_dir()
        out = []
        for f in sorted(root.glob("*/kit.json")) if root.exists() else []:
            data = json.loads(f.read_text())
            out.append({"name": f.parent.name, "summary": data.get("summary", "")})
        return out

    def brand_kit_save(self, name: str = "implicit") -> str:
        """Salvează brandul proiectului (logo, culori, font, intro/outro) ca kit refolosibil în alte proiecte.
        Kit-ul „implicit” se aplică singur pe proiectele noi."""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            raise ValueError("numele kit-ului: litere, cifre, _ și - (maxim 40)")
        tl, b = self.tl, self.tl.brand
        if not b.is_set():
            raise ValueError("proiectul nu are brand de salvat (brand_logo / brand_captions / brand_intro_outro)")
        d = self._kits_dir() / name
        tmp = d.with_name(f".{name}.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)

        def keep(path: str | None) -> str | None:
            if not path:
                return None
            shutil.copy2(path, tmp / Path(path).name)
            return Path(path).name

        data = {"primary": b.primary, "highlight": b.highlight, "outline": b.outline,
                "font_file": keep(b.font_file), "caption_font": tl.caption_font if b.font_file else None,
                "logo": ({**b.logo.model_dump(exclude={"path"}), "file": keep(b.logo.path)} if b.logo else None),
                "intro": keep(self._asset(b.intro).path) if b.intro else None,
                "outro": keep(self._asset(b.outro).path) if b.outro else None,
                "summary": tl.brand_view().removeprefix("brand: ")}
        (tmp / "kit.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))
        shutil.rmtree(d, ignore_errors=True)
        tmp.replace(d)
        return f"kit „{name}” salvat: {data['summary']}"

    def brand_kit_apply(self, name: str = "implicit") -> str:
        """Aplică un kit salvat: copiază fișierele în proiect și setează brandul (înlocuiește brandul curent)."""
        from .timeline import Brand, Logo

        d = self._kits_dir() / name
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name) or not (d / "kit.json").exists():
            have = ", ".join(k["name"] for k in self.brand_kit_list()) or "niciunul"
            raise ValueError(f"kit inexistent: {name} (salvate: {have})")
        data = json.loads((d / "kit.json").read_text())
        brand = Brand(primary=data.get("primary"), highlight=data.get("highlight"), outline=data.get("outline"))
        if data.get("logo"):
            lg = data["logo"]
            dst = self._import_brand_file(str(d / lg["file"]), "", "logo", Path(lg["file"]).suffix.lower())
            brand.logo = Logo(path=str(dst), **{k: v for k, v in lg.items() if k != "file"})
        font = None
        if data.get("font_file"):
            f = d / data["font_file"]
            brand.font_file = str(self._import_brand_file(str(f), "fonts", f.stem[:40], f.suffix.lower()))
            font = data.get("caption_font")
        for key in ("intro", "outro"):
            if data.get(key):
                aid = f"{key}_{name}"[:30]
                if aid not in self.s.assets:
                    dst = self._import_brand_file(str(d / data[key]), "clips", key, Path(data[key]).suffix.lower())
                    self.add_asset(str(dst), aid)
                self.s.roles[aid] = "brand"
                setattr(brand, key, aid)
                setattr(brand, f"{key}_dur", round(self._asset(aid).duration, 3))
        self.save()
        with self.edit() as tl:
            tl.brand = brand
            if font:
                tl.caption_font = font
        return f"kit „{name}” aplicat\n{self.tl.brand_view()}"

    # ------------------------------------------------------------------ capitole
    def chapters_set(self, chapters: str, title_cards: bool = False) -> str:
        """Capitole: 'secunde=Titlu|secunde=Titlu' (timp de montaj). Reguli YouTube: primul la 0, minim 3,
        fiecare de cel puțin 10 s. title_cards=True pune și un title_card de 2 s la începutul fiecăruia (fără primul)."""
        items = []
        for part in [x for x in chapters.split("|") if x.strip()]:
            if "=" not in part:
                raise ValueError(f"capitol invalid {part!r}: format 'secunde=Titlu'")
            t, title = part.split("=", 1)
            title = " ".join(title.split())[:60]
            if not title:
                raise ValueError("capitol fără titlu")
            items.append(Chapter(start=round(float(t), 2), title=title))
        items.sort(key=lambda c: c.start)
        dur = self.tl.duration
        if items:
            if len(items) < 3:
                raise ValueError("YouTube cere minim 3 capitole")
            if items[0].start != 0:
                raise ValueError("primul capitol trebuie să înceapă la 0")
            bounds = [c.start for c in items] + [dur]
            short = [c.title for c, a, b in zip(items, bounds, bounds[1:]) if b - a < 10]
            if short:
                raise ValueError(f"capitole sub 10 s (YouTube le ignoră): {', '.join(short)}")
        with self.edit() as tl:
            tl.chapters = items
            tl.graphics = [g for g in tl.graphics if not g.id.startswith("gch")]
            if title_cards:
                for k, c in enumerate(items[1:], 1):
                    tl.graphics.append(Graphic(id=f"gch{k}", kind="title_card", start=c.start,
                                               end=min(c.start + 2.0, dur), text=c.title))
        return self.chapters_text() or "capitole șterse"

    def chapters_text(self) -> str:
        """Textul pentru descrierea YouTube (include decalajul intro-ului)."""
        off = self.tl.brand.intro_dur if self.tl.brand.intro else 0.0

        def stamp(t: float) -> str:
            t = int(t + 1e-6)
            return f"{t // 3600}:{t // 60 % 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60}:{t % 60:02d}"

        # primul rămâne 0:00 (YouTube îl cere), intro-ul intră în el; restul se decalează cu intro-ul
        return "\n".join(f"{stamp(0 if k == 0 else c.start + off)} {c.title}" for k, c in enumerate(self.tl.chapters))

    # ------------------------------------------------------------------ cuvinte-cheie
    _STOP = set("""acest această aceste acestea pentru despre dintre fiindcă deoarece atunci foarte trebuie
        putem puteți poate lucru lucruri oameni because really actually something everything anything
        there their would could should about which through""".split())

    def _pick_keywords(self, tl: Timeline, share: float = 0.5) -> list[str]:
        """Cuvinte-cheie automat: cel mai bun cuvânt din fiecare subtitrare (cifre, apoi cuvinte lungi, fără
        cuvinte de legătură), păstrând doar `share` din subtitrări, pe cele cu scorul cel mai mare."""
        cands: list[tuple[float, int, str]] = []
        for k, c in enumerate(tl.captions):
            best, score = None, 0.0
            for j, (w, wid) in enumerate(zip(c.text.split(" "), c.word_ids or [])):
                bare = re.sub(r"[^\w%$€]", "", w.lower())
                if not bare or bare in self._STOP:
                    continue
                sc = 3.0 if re.search(r"\d", bare) else (1 + len(bare) / 10 if len(bare) >= 7 else 0)
                # nume proprii (majusculă în mijlocul frazei): rar poartă ideea, deci doar dacă nu e altceva
                if j and w[:1].isupper() and not w.isupper() and not re.search(r"\d", bare):
                    sc *= 0.3
                if sc > score:
                    best, score = wid, sc
            if best:
                cands.append((score, k, best))
        keep = max(1, round(len(tl.captions) * share)) if cands else 0
        chosen = sorted(sorted(cands, reverse=True)[:keep], key=lambda x: x[1])
        return [wid for _, _, wid in chosen]

    def captions_emphasis(self, words: str = "auto", asset: str = "", color: str = "", scale: float = 1.25,
                          mode: str = "add") -> str:
        """Evidențiază cuvinte-cheie în subtitrări (altă culoare, mai mari, pop când sunt rostite).
        words: id-uri din transcript ('w12,w30-w31') cu `asset`, sau 'auto' (cifre și cuvinte importante)."""
        from .captions import norm_hex

        tl = self.tl
        if not tl.captions:
            raise ValueError("nu există subtitrări: rulează întâi captions_add")
        if mode not in ("add", "set", "clear"):
            raise ValueError("mode: add, set sau clear")
        if not 1.0 <= scale <= 1.8:
            raise ValueError("scale între 1.0 și 1.8")
        if mode == "clear":
            keys: list[str] = []
        elif words.strip() == "auto":
            keys = self._pick_keywords(tl)
        else:
            aid = asset or tl.clips[0].asset
            keys = [f"{aid}:w{i}" for a, b in self._spans(words) for i in range(a, b + 1)]
            known = {w for c in tl.captions for w in (c.word_ids or [])}
            absent = [k for k in keys if k not in known]
            if absent:
                raise ValueError(f"cuvinte care nu apar în subtitrări (tăiate sau alt asset): {', '.join(absent[:8])}")
        with self.edit() as tl:
            tl.emphasis = keys if mode in ("set", "clear") else list(dict.fromkeys(tl.emphasis + keys))
            if color:
                tl.emphasis_color = None if color.lower() == "none" else norm_hex(color)
            tl.emphasis_scale = scale
        lookup = {w: t for c in tl.captions for w, t in zip(c.word_ids or [], c.text.split(" "))}
        shown = ", ".join(f"{k.split(':')[1]}={lookup.get(k, '?')}" for k in self.tl.emphasis[:20])
        return f"{len(self.tl.emphasis)} cuvinte evidențiate: {shown or '-'}"

    def zoom_on_words(self, words: str, asset: str = "", zoom: float = 1.2, hold: float = 1.2) -> str:
        """Punch-in (tăietură în zoom) pe cuvintele date, ținut `hold` secunde: accentul unui editor pe ideea-cheie."""
        if not 1.05 <= zoom <= 1.6:
            raise ValueError("zoom între 1.05 și 1.6")
        if not 0.4 <= hold <= 4:
            raise ValueError("hold între 0.4 și 4 secunde")
        tl = self.tl
        if not tl.clips:
            raise ValueError("timeline-ul e gol")
        aid = asset or tl.clips[0].asset
        tr = self.transcript(aid)
        at = {w.i: w.start for w in tr.words}
        times = []
        for a, _ in self._spans(words):
            if a not in at:
                raise ValueError(f"w{a} nu există în transcriptul lui {aid}")
            found = tl.source_to_timeline(aid, at[a])
            if not found:
                raise ValueError(f"w{a} a fost tăiat din montaj")
            times.append(found[0])
        with self.edit() as tl:
            for t in sorted(times):
                end = min(t + hold, tl.duration)
                for c in _in_range(tl, max(t - 0.03, 0), end):
                    c.crop.zoom = round(min(c.crop.zoom * zoom, 2.0), 3)
        return f"punch-in x{zoom:g} la {', '.join(f'{t:.2f}s' for t in sorted(times))}\n{self.tl.view()}"

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

    def _covered(self, tl: Timeline, angle: str) -> list[tuple[float, float]]:
        """Intervalele de montaj în care camera `angle` are imagine (a pornit mai târziu / s-a oprit mai devreme)."""
        dur = self._asset(angle).duration
        out = []
        for c, s in zip(tl.clips, tl.starts()):
            if c.asset not in tl.sync or angle not in tl.sync:
                continue
            shift = tl.angle_time(c, angle, 0.0)
            lo, hi = max(c.src_in, -shift + 0.02), min(c.src_out, dur - shift - 0.02)
            if hi > lo:
                out.append((c.tl_at(s, lo), c.tl_at(s, hi)))
        return out

    def _fit_coverage(self, tl: Timeline, ranges, fallback: str | None):
        """Taie din fiecare cadru partea pe care camera lui nu o acoperă; acolo pune `fallback` (wide) sau
        camera de referință (None). Bucățile sub 0.3 s rămân pe cadrul vecin."""
        out: list[tuple[float, float, str | None]] = []
        cover = {}
        for a, b, angle in ranges:
            if angle not in cover:
                cover[angle] = self._covered(tl, angle)
            t = a
            for lo, hi in sorted(cover[angle]):
                lo, hi = max(lo, a), min(hi, b)
                if hi - lo < 0.3:
                    continue
                if lo - t > 1e-3:
                    out.append((t, lo, fallback))
                out.append((lo, hi, angle))
                t = hi
            if b - t > 1e-3:
                out.append((t, b, fallback))
        merged: list[tuple[float, float, str | None]] = []
        for a, b, x in out:
            if merged and (merged[-1][2] == x or b - a < 0.3):
                merged[-1] = (merged[-1][0], b, merged[-1][2])
            else:
                merged.append((a, b, x))
        return merged

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
        ranges = self._fit_coverage(tl, ranges, wide or None)
        with self.edit() as tl:
            for a, b, angle in ranges:
                for c in _in_range(tl, a, b):
                    if c.asset not in tl.sync or (angle and angle != c.asset and angle not in tl.sync):
                        continue
                    if angle:
                        self._check_angle(tl, c, angle)
                    c.angle = None if not angle or angle == c.asset else angle
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
