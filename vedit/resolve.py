"""Dus-întors cu DaVinci Resolve (și orice editor care citește FCPXML: Final Cut, Premiere prin plugin).

`to_fcpxml` scrie timeline-ul ca FCPXML 1.9: V1 pe linia principală, B-roll-ul ca clipuri conectate
pe pista de deasupra, muzica și voice-over-ul pe piste audio dedesubt. Fișierele media sunt referite prin
calea lor absolută de pe disc, deci Resolve le găsește fără relink când rulează pe aceeași mașină.

`apply_fcpxml` citește înapoi un FCPXML exportat din Resolve (File > Export > Timeline) și reface V1
(și B-roll-ul) din el. Proprietățile pe care Resolve nu le știe (încadrare, efecte, fundal, blur pe fețe)
se păstrează de pe clipul vechi din aceeași sursă care se suprapune cel mai mult cu cel nou.
Subtitrările și graficele urmează tăieturile prin ripple-ul obișnuit din `Project.edit()`.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

from .timeline import BRoll, Clip, Timeline, Transition

FCPXML_VERSION = "1.9"
SEQ_PREFIX = "vedit · "  # numele timeline-ului în Resolve; scriptul din Resolve citește proiectul din el
MAX_XML = 8 * 1024 * 1024


# ---------------- timpi ----------------
def _fps(tl: Timeline) -> tuple[int, int]:
    """Durata unui cadru ca fracție (numărător, numitor), ca în FCPXML: 1/25s, 1001/30000s."""
    f = tl.fps or 25
    if abs(f - round(f)) < 0.01:
        return 1, int(round(f))
    return 1001, int(round(f * 1001))


def _t(seconds: float, frame: tuple[int, int]) -> str:
    """Secunde → timp FCPXML rotunjit la cadru („150/25s”)."""
    n, d = frame
    frames = round(Fraction(seconds).limit_denominator(100000) * d / n)
    if frames == 0:
        return "0s"
    v = Fraction(frames * n, d)
    return f"{v.numerator}s" if v.denominator == 1 else f"{v.numerator}/{v.denominator}s"


def _parse_t(s: str | None) -> float:
    if not s:
        return 0.0
    s = s.strip().rstrip("s")
    if "/" in s:
        a, b = s.split("/", 1)
        return float(Fraction(int(a), int(b)))
    return float(s)


def _uri(path: str) -> str:
    return "file://" + quote(os.path.abspath(path))


# ---------------- export ----------------
def to_fcpxml(tl: Timeline, assets: dict, project: str) -> str:
    """`assets`: id → MediaInfo (calea fișierului, durata, ce piste are)."""
    frame = _fps(tl)
    fd = f"{frame[0]}/{frame[1]}s"
    root = ET.Element("fcpxml", version=FCPXML_VERSION)
    res = ET.SubElement(root, "resources")
    seq_fmt = {"id": "r0", "frameDuration": fd, "width": str(tl.width), "height": str(tl.height)}
    if (tl.width, tl.height) == (1920, 1080):  # numele standard doar unde există; 9:16 / 1:1 merg pe dimensiuni
        seq_fmt["name"] = f"FFVideoFormat1080p{round(tl.fps or 25)}"
    ET.SubElement(res, "format", **seq_fmt)

    used = [c.asset for c in tl.clips] + [b.asset for b in tl.broll]
    used += [tl.music.asset] if tl.music else []
    used += [tl.narration.asset] if tl.narration else []
    ref: dict[str, str] = {}
    for i, aid in enumerate(dict.fromkeys(used)):
        m = assets[aid]
        rid = f"r{i + 1}"
        ref[aid] = rid
        attrs = {"id": rid, "name": Path(m.path).name, "uid": f"vedit-{project}-{aid}", "start": "0s",
                 "duration": _t(m.duration, frame), "hasVideo": "1" if m.has_video else "0",
                 "hasAudio": "1" if m.has_audio else "0"}
        if m.has_video:
            fid = f"f{i + 1}"
            ET.SubElement(res, "format", id=fid, width=str(m.width or tl.width), height=str(m.height or tl.height),
                          frameDuration=_fps_of(m.fps, frame))
            attrs["format"] = fid
        if m.has_audio:
            attrs.update(audioSources="1", audioChannels="2", audioRate="48000")
        a = ET.SubElement(res, "asset", **attrs)
        ET.SubElement(a, "media-rep", kind="original-media", src=_uri(m.path))

    lib = ET.SubElement(root, "library")
    ev = ET.SubElement(lib, "event", name="vedit")
    pr = ET.SubElement(ev, "project", name=f"{SEQ_PREFIX}{project}")
    seq = ET.SubElement(pr, "sequence", format="r0", duration=_t(tl.duration, frame), tcStart="0s",
                        tcFormat="NDF", audioLayout="stereo", audioRate="48k")
    spine = ET.SubElement(seq, "spine")

    starts = tl.starts()
    ends = [starts[i + 1] if i + 1 < len(starts) else tl.duration for i in range(len(starts))]
    parents: list[tuple[float, float, ET.Element, float]] = []  # (start, end, element, start-ul local)
    for i, c in enumerate(tl.clips):
        if i and c.transition:
            # tranziția stă centrată pe tăietură; materialul pentru ea vine din handle-urile clipurilor
            d = c.transition.duration
            tr = ET.SubElement(spine, "transition", name="Cross Dissolve", offset=_t(starts[i] - d / 2, frame),
                               duration=_t(d, frame))
            ET.SubElement(tr, "filter-video", ref=_effect(res, "Cross Dissolve"), name="Cross Dissolve")
        dur = ends[i] - starts[i]
        if dur <= 0:
            continue
        el = ET.SubElement(spine, "asset-clip", ref=ref[c.asset], name=f"{c.id} · {Path(assets[c.asset].path).name}",
                           offset=_t(starts[i], frame), start=_t(c.src_in, frame), duration=_t(dur, frame),
                           tcFormat="NDF")
        if abs(c.speed - 1) > 1e-6 or c.freeze:
            tm = ET.SubElement(el, "timeMap")
            body = c.body
            ET.SubElement(tm, "timept", time=_t(c.src_in, frame), value=_t(c.src_in, frame), interp="linear")
            ET.SubElement(tm, "timept", time=_t(c.src_in + body, frame), value=_t(c.src_out, frame), interp="linear")
            if c.freeze:
                ET.SubElement(tm, "timept", time=_t(c.src_in + body + c.freeze, frame), value=_t(c.src_out, frame),
                              interp="linear")
        if c.volume_db:
            ET.SubElement(el, "adjust-volume", amount=f"{c.volume_db:g}dB")
        parents.append((starts[i], ends[i], el, c.src_in))

    def attach(at: float) -> tuple[ET.Element, float]:
        """Clipul de pe V1 de care se agață un element conectat la momentul `at` (timp de timeline)."""
        for s, e, el, local in parents:
            if s <= at < e:
                return el, local + (at - s)
        s, _, el, local = parents[-1]
        return el, local + (at - s)

    if parents:
        for b in tl.broll:
            el, off = attach(b.start)
            ET.SubElement(el, "asset-clip", ref=ref[b.asset], lane="1", name=f"{b.id} · {Path(assets[b.asset].path).name}",
                          offset=_t(off, frame), start=_t(b.src_in, frame), duration=_t(b.duration, frame),
                          tcFormat="NDF")
        audio = [(tl.music, -1, "muzică"), (tl.narration, -2, "voice-over")]
        for item, lane, label in audio:
            if not item:
                continue
            start = getattr(item, "start", 0.0)
            src_in = getattr(item, "src_in", 0.0)
            length = min(assets[item.asset].duration - src_in, tl.duration - start)
            if length <= 0:
                continue
            el, off = attach(start)
            a = ET.SubElement(el, "asset-clip", ref=ref[item.asset], lane=str(lane), name=f"{label} · {Path(assets[item.asset].path).name}",
                              offset=_t(off, frame), start=_t(src_in, frame), duration=_t(length, frame),
                              audioRole="music" if lane == -1 else "dialogue")
            if item.volume_db:
                ET.SubElement(a, "adjust-volume", amount=f"{item.volume_db:g}dB")

    if parents:  # capitolele devin markere în Resolve
        for ch in tl.chapters:
            el, off = attach(ch.start)
            ET.SubElement(el, "marker", start=_t(off, frame), duration=fd, value=ch.title)

    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding="unicode") + "\n"


def _fps_of(fps: float, fallback: tuple[int, int]) -> str:
    if not fps:
        return f"{fallback[0]}/{fallback[1]}s"
    if abs(fps - round(fps)) < 0.01:
        return f"1/{int(round(fps))}s"
    return f"1001/{int(round(fps * 1001))}s"


def _effect(res: ET.Element, name: str) -> str:
    for e in res.findall("effect"):
        if e.get("name") == name:
            return e.get("id", "")
    eid = f"e{len(res.findall('effect')) + 1}"
    ET.SubElement(res, "effect", id=eid, name=name, uid="FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265")
    return eid


# ---------------- import ----------------
class ImportError_(ValueError):
    """Mesaj clar pentru utilizator (UI-ul îl afișează ca atare)."""


def _media_index(assets: dict) -> tuple[dict[str, str], dict[str, str]]:
    by_path, by_name = {}, {}
    for aid, m in assets.items():
        by_path.setdefault(os.path.realpath(m.path), aid)
        by_name.setdefault(Path(m.path).name.lower(), aid)
    return by_path, by_name


def _src_path(asset_el: ET.Element) -> str:
    rep = asset_el.find("media-rep")
    src = rep.get("src") if rep is not None else asset_el.get("src", "")
    if not src:
        return ""
    u = urlparse(src)
    return unquote(u.path) if u.scheme in ("file", "") else ""


def _retime(el: ET.Element) -> tuple[float, float]:
    """(viteza, freeze) din <timeMap>: primul segment dă viteza; un ultim segment cu aceeași valoare = freeze."""
    tm = el.find("timeMap")
    if tm is None:
        return 1.0, 0.0
    pts = [(_parse_t(p.get("time")), _parse_t(p.get("value"))) for p in tm.findall("timept")]
    if len(pts) < 2 or pts[1][0] == pts[0][0]:
        return 1.0, 0.0
    speed = max(0.25, min(4.0, (pts[1][1] - pts[0][1]) / (pts[1][0] - pts[0][0])))
    freeze = pts[-1][0] - pts[-2][0] if len(pts) >= 3 and abs(pts[-1][1] - pts[-2][1]) < 1e-6 else 0.0
    return speed, freeze


def parse_fcpxml(xml: str | bytes, assets: dict) -> dict:
    """FCPXML → {"clips": [...], "broll": [...], "gaps": n, "unknown": [nume]} (timpi în secunde).

    Acceptă ce scrie Resolve (1.8-1.11): asset-clip sau clip/video pe linia principală, gap-uri,
    tranziții și clipuri conectate (lane > 0 = B-roll; lane < 0 = audio, ignorat)."""
    if len(xml) > MAX_XML:
        raise ImportError_("fișierul FCPXML e prea mare")
    if isinstance(xml, str):
        xml = xml.encode()
    if b"<!ENTITY" in xml:  # fără entități externe / „billion laughs”
        raise ImportError_("FCPXML cu entități nu e acceptat")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ImportError_(f"nu e un FCPXML valid ({e})") from None
    if root.tag != "fcpxml":
        raise ImportError_("nu e un fișier FCPXML (exportă din Resolve cu File > Export > Timeline > FCPXML)")

    by_path, by_name = _media_index(assets)
    res_assets = {a.get("id"): a for a in root.iter("asset")}
    unknown: list[str] = []

    def asset_of(el: ET.Element) -> str | None:
        r = el.get("ref")
        if el.tag == "clip":  # Resolve: <clip><video ref=…/></clip>
            inner = el.find("video") if el.find("video") is not None else el.find("asset-clip")
            r = inner.get("ref") if inner is not None else None
        a = res_assets.get(r)
        if a is None:
            return None
        path = _src_path(a)
        aid = by_path.get(os.path.realpath(path)) if path else None
        if not aid:
            name = Path(path).name if path else a.get("name", "")
            aid = by_name.get(name.lower())
            m = re.match(r"(a\d+)\b", el.get("name", ""))
            if not aid and m and m.group(1) in assets:
                aid = m.group(1)
            if not aid:
                unknown.append(name or a.get("name", "?"))
        return aid

    spine = next(root.iter("spine"), None)
    if spine is None:
        raise ImportError_("FCPXML fără timeline (lipsește <spine>)")

    clips, broll, gaps, pending_tr = [], [], 0, None
    t = 0.0
    for el in spine:
        dur = _parse_t(el.get("duration"))
        if el.tag == "transition":
            # în vedit clipul următor se suprapune peste coada celui anterior: coada revine în clipul anterior
            pending_tr = dur
            if clips:
                prev = clips[-1]
                prev["src_out"] = round(min(assets[prev["asset"]].duration, prev["src_out"] + dur * prev["speed"]), 3)
            continue
        if el.tag == "gap":
            gaps += 1 if dur > 0.05 else 0
            local0 = _parse_t(el.get("start"))
            _connected(el, _parse_t(el.get("offset")), local0, asset_of, broll)
            t += dur
            continue
        if el.tag not in ("asset-clip", "clip", "video"):
            continue
        aid = asset_of(el)
        offset = _parse_t(el.get("offset"))
        start = _parse_t(el.get("start"))
        speed, freeze = _retime(el)
        if aid:
            m = assets[aid]
            src_in = max(0.0, start)
            src_out = min(m.duration, src_in + max(dur - freeze, 0) * speed)
            if src_out - src_in > 0.04:
                clips.append({"asset": aid, "src_in": round(src_in, 3), "src_out": round(src_out, 3),
                              "speed": round(speed, 4), "freeze": round(freeze, 3), "transition": pending_tr})
        pending_tr = None
        _connected(el, offset, start, asset_of, broll)
        t += dur
    return {"clips": clips, "broll": broll, "gaps": gaps, "unknown": sorted(set(unknown))}


def _connected(parent: ET.Element, parent_offset: float, parent_start: float, asset_of, out: list) -> None:
    for ch in parent:
        if ch.tag not in ("asset-clip", "clip", "video") or int(ch.get("lane", "0") or 0) <= 0:
            continue
        aid = asset_of(ch)
        if not aid:
            continue
        at = parent_offset + (_parse_t(ch.get("offset")) - parent_start)
        out.append({"asset": aid, "src_in": round(_parse_t(ch.get("start")), 3), "start": round(max(0.0, at), 3),
                    "duration": round(_parse_t(ch.get("duration")), 3)})


def apply_fcpxml(tl: Timeline, parsed: dict, assets: dict) -> str:
    """Rescrie V1 (și B-roll-ul) din `parsed`, păstrând proprietățile clipurilor vechi. Mutația se face
    pe `tl` (apelantul e în `with p.edit()`). Întoarce un rezumat în română."""
    if not parsed["clips"]:
        raise ImportError_("niciun clip din FCPXML nu corespunde fișierelor din proiect"
                           + (f" (necunoscute: {', '.join(parsed['unknown'][:5])})" if parsed["unknown"] else ""))
    old = list(tl.clips)
    taken: set[str] = set()
    new: list[Clip] = []
    for spec in parsed["clips"]:
        best, score = None, 0.0
        for c in old:
            if c.asset != spec["asset"]:
                continue
            ov = min(c.src_out, spec["src_out"]) - max(c.src_in, spec["src_in"])
            if ov > score:
                best, score = c, ov
        if best is not None:
            c = best.model_copy(deep=True)
            if best.id in taken:
                c.id = ""
            taken.add(best.id)
        else:
            c = Clip(id="", asset=spec["asset"], src_in=0, src_out=1)
        c.src_in, c.src_out, c.speed, c.freeze = spec["src_in"], spec["src_out"], spec["speed"], spec["freeze"]
        if spec["transition"]:
            kind = c.transition.type if c.transition else "dissolve"
            c.transition = Transition(type=kind, duration=round(min(spec["transition"], 2.0), 3))
        else:
            c.transition = None
        new.append(c)
    if new:
        new[0].transition = None
    tl.clips = []
    for c in new:  # id-uri noi doar unde trebuie, fără coliziuni
        if not c.id or any(x.id == c.id for x in tl.clips):
            c.id = tl._new_id()
        tl.clips.append(c)

    if parsed["broll"] or tl.broll:
        olds = {(b.asset, round(b.src_in, 1)): b for b in tl.broll}
        out = []
        for i, b in enumerate(parsed["broll"]):
            prev = olds.get((b["asset"], round(b["src_in"], 1)))
            nb = prev.model_copy(deep=True) if prev else BRoll(id=f"b{i + 1}", **b)
            nb.src_in, nb.start, nb.duration = b["src_in"], b["start"], b["duration"]
            out.append(nb)
        ids = set()
        for i, b in enumerate(out):
            if b.id in ids:
                b.id = f"b{len(out) + i + 1}"
            ids.add(b.id)
        tl.broll = out

    note = f"{len(new)} clipuri pe V1, {len(tl.broll)} B-roll"
    if parsed["gaps"]:
        note += f"; {parsed['gaps']} goluri scoase (V1 e magnetic, ca în CapCut)"
    if parsed["unknown"]:
        note += f"; ignorate (nu sunt în proiect): {', '.join(parsed['unknown'][:5])}"
    return note
