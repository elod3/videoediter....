"""Verificatorul de „slop” al unui montaj: regulile din skill-ul reels-pro, măsurate pe timeline (și, cu un render,
pe imagine). Fiecare problemă are gravitate (P0 = nu predai, P1 = refaci zona, P2 = cosmetic), timpul și reparația.
Fără LLM: reguli deterministe, ca agentul să se corecteze singur înainte să predea."""
from __future__ import annotations

from dataclasses import dataclass

from .timeline import Timeline

# blocurile „mari”: un singur element mare pe ecran (skill motion-design, §3)
BIG = {"stack_title", "kinetic", "headline", "chapter", "stat", "quote", "day_counter", "map", "bars", "line_chart",
       "compare", "list", "steps", "logo_reveal", "scene_card"}


@dataclass
class Issue:
    level: str          # P0 / P1 / P2
    at: float           # secunda de montaj (-1 = tot clipul)
    what: str
    fix: str

    def line(self) -> str:
        t = f"{self.at:6.2f}s" if self.at >= 0 else "  tot  "
        return f"{self.level} {t}  {self.what} → {self.fix}"


def _reel(tl: Timeline) -> bool:
    return tl.height > tl.width and tl.duration <= 95


def check(tl: Timeline) -> list[Issue]:
    """Regulile care se văd din structura montajului (fără să randăm)."""
    from .motion import hits

    out: list[Issue] = []
    dur = tl.duration
    reel = _reel(tl)
    starts = tl.starts()
    cuts = starts[1:]

    # 1. doar subtitrări: zero grafică pe un reel
    if reel and tl.captions and not tl.motion and not tl.graphics and not tl.broll and dur > 8:
        out.append(Issue("P0", -1, "reel doar cu subtitrări, fără nicio scenă grafică",
                         "3-6 cuvinte-lovitură din transcript ca stack_title / orbit_words (skill reels-pro)"))

    # 2. porțiuni statice: nicio schimbare (tăietură, bloc, grafic, B-roll, mișcare de cameră, puls)
    events = [0.0, dur, *cuts]
    events += [m.start for m in tl.motion] + [g.start for g in tl.graphics] + [t.start for t in tl.texts]
    events += [b.start for b in tl.broll] + [b.start + b.duration for b in tl.broll]
    moving: list[tuple[float, float]] = []
    for c, s in zip(tl.clips, starts):
        if c.keys or c.anim or (c.bg and c.bg.move > 0):
            moving.append((s, s + c.duration))
    moving += [(b.start, b.end) for b in tl.beat_fx]
    ev = sorted(set(round(x, 3) for x in events))
    limit = 6.0 if reel else 15.0
    for a, b in zip(ev, ev[1:]):
        gap = b - a
        covered = sum(max(0.0, min(b, y) - max(a, x)) for x, y in moving)
        if gap - covered > limit:
            lvl = "P0" if gap - covered > limit * 1.7 else "P1"
            out.append(Issue(lvl, a, f"{gap:.1f} s fără nicio schimbare pe ecran",
                             "o tăietură / punch-in (zoom_on_words, auto_pacing) sau un bloc pe cuvântul de acolo"))

    # 3. hook gol pe reel
    if reel and dur > 6:
        early = [m for m in tl.motion if m.start < 2.5] + [g for g in tl.graphics if g.start < 2.5]
        if not early and not any(t.start < 2.5 for t in tl.texts):
            out.append(Issue("P1", 0.0, "nimic grafic în primele 2.5 s (hook-ul)",
                             "cuvântul-lovitură al ideii ca stack_title cu behind=true, sau orbit_words"))

    # 4. două elemente mari în același timp
    big = sorted([m for m in tl.motion if m.block in BIG], key=lambda m: m.start)
    for x, y in zip(big, big[1:]):
        if y.start < x.end - 0.15:
            out.append(Issue("P1", y.start, f"două elemente mari deodată ({x.id} {x.block} + {y.id} {y.block})",
                             f"un singur element mare pe ecran: scurtează {x.id} (end={y.start:.2f}) sau mută {y.id}"))

    # 5. un bloc în spatele persoanei care trece peste o tăietură
    for m in tl.motion:
        if m.behind:
            cross = [s for s in cuts if m.start + 0.05 < s < m.end - 0.05]
            if cross:
                out.append(Issue("P1", cross[0], f"{m.id} ({m.block}, în spate) trece peste tăietură",
                                 f"oprește-l la tăietură (end={cross[0]:.2f}) sau pune altul pe clipul următor"))

    # 6. repetiții: aceeași tranziție > 2 ori, același bloc de 3 ori la rând
    kinds: dict[str, int] = {}
    for c in tl.clips:
        if c.transition:
            kinds[c.transition.type] = kinds.get(c.transition.type, 0) + 1
    for k, n in kinds.items():
        if n > 2:
            out.append(Issue("P2", -1, f"tranziția {k} de {n} ori", "maxim 2 la fel; restul tăieturi dure"))
    seq = [m.block for m in sorted(tl.motion, key=lambda m: m.start)]
    for i in range(len(seq) - 2):
        if seq[i] == seq[i + 1] == seq[i + 2]:
            out.append(Issue("P2", sorted(tl.motion, key=lambda m: m.start)[i].start,
                             f"{seq[i]} de 3 ori la rând", "alternează: cuvânt uriaș / arc / card / balon"))
            break

    # 7. animații fără sunet: lovitura blocului fără niciun sfx aproape
    sfx_at = [x.at for x in tl.sfx]
    mute = []
    for m in tl.motion:
        hs = hits(m.block, m.params, m.start, m.end - m.start)
        if hs and not any(abs(a - h[1]) < 0.3 for a in sfx_at for h in hs):
            mute.append(m.id)
    if mute:
        out.append(Issue("P2" if len(mute) < 3 else "P1", -1, f"blocuri fără sunet: {', '.join(mute)}",
                         "sfx_auto(graphics=true) pune sunetul pe lovitura fiecărui bloc"))

    # 8. densitate prea mare: peste un element nou la 1.2 s, pe toată durata
    if tl.motion and dur > 10 and len(tl.motion) + len(tl.graphics) > dur / 1.2:
        out.append(Issue("P1", -1, f"{len(tl.motion) + len(tl.graphics)} elemente în {dur:.0f} s: zgomot",
                         "lasă 0.6-1 s de liniște după fiecare lovitură; scoate ce nu e cuvânt-lovitură"))

    # 9. fraze lungi pe ecran
    for m in tl.motion:
        if m.block == "orbit_words" and len(str(m.params.get("text", "")).split()) > 6:
            out.append(Issue("P2", m.start, f"{m.id}: frază de peste 6 cuvinte pe cerc", "taie fraza la ideea ei"))
    order = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(out, key=lambda x: (order[x.level], x.at))


def faces_covered(tl: Timeline, path: str) -> list[Issue]:
    """Pe render: unde blocul știa că e o față (Motion.scene), fața trebuie să se vadă în cadrul final."""
    try:
        from .faces import get_detector
        from .probe import probe
        from .style import grab_frame
    except ImportError:
        return []
    info = probe(path)
    det = get_detector()
    out = []
    for m in tl.motion:
        if m.behind or not m.scene.get("face") or m.block in ("pixel_wipe", "speed_lines"):
            continue
        t = m.start + min(0.9, (m.end - m.start) * 0.6)
        fr = grab_frame(path, t, info.width, info.height, width=480)
        if fr is None:
            continue
        if not det(fr[..., ::-1].copy()):
            out.append(Issue("P0", t, f"fața nu se mai vede sub {m.id} ({m.block})",
                             "mută blocul (position / layout) sau pune-l în spatele persoanei (behind=true)"))
    return out


def report(issues: list[Issue]) -> str:
    if not issues:
        return "verificare reel: nicio problemă găsită de reguli (uită-te totuși la 2-3 cadre cu timeline_frame)"
    n = {k: sum(1 for i in issues if i.level == k) for k in ("P0", "P1", "P2")}
    head = f"verificare reel: P0={n['P0']} P1={n['P1']} P2={n['P2']}" + \
        (": NU preda cu P0" if n["P0"] else "")
    return head + "\n" + "\n".join(i.line() for i in issues)
