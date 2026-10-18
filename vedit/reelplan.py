"""Planul unui reel din transcript: cuvintele-lovitură și scenele (skill reels-pro, §0), ca agentul să pornească de
la un schelet bun și doar să decidă. Determinist, fără LLM: scor pe cuvânt (cifre, cuvinte cu sens, pauza de după,
hook-ul), lovituri la cel puțin ~2 s una de alta, blocul potrivit pentru fiecare."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

STOP = set("""
și sau dar că ca cu de din la în pe pentru prin fără spre după până ce care cine cum când unde nu da mai foarte
un o unui unei niște al ale ai a lui lor le îi îl mă te se ne vă eu tu el ea noi voi ei ele ăsta asta ăla aia acest
această acel acea este e sunt era fost fi am ai are avem aveți au vom va vor să ar aș îmi îți își ți mi
the a an and or but if then so of to in on at for with from by as is are was were be been it its this that these
those you your we our they their he she his her i me my do does did not no yes just very really can will would
tine mine sine noi voi ei apoi acum aici atunci doar chiar deja încă mult puțin tot toate toți fiecare nimic ceva
cineva altceva complet foarte prea atât cât cum așa then now here there only even already still much all every
""".split())
NUM = re.compile(r"\d")
TIME_UNITS = {"zile", "zi", "days", "day", "săptămâni", "weeks", "luni", "months", "ani", "years", "ore", "hours"}


@dataclass
class Hit:
    t: float            # timp de montaj (începutul cuvântului)
    end: float
    word: str
    before: list[str]   # 2-4 cuvinte dinainte (rândul mic)
    after: list[str]
    phrase: list[tuple[str, float]]  # fraza scurtă în jurul lui (cuvânt, timp de montaj)
    score: float


def _clean(w: str) -> str:
    return re.sub(r"[^\w%]", "", w.lower())


def words_on_timeline(tl, transcripts: dict) -> list[tuple[str, float, float, str]]:
    """(text, start, end, id) pentru cuvintele care se aud în montaj, în timp de montaj."""
    out = []
    for c, s in zip(tl.clips, tl.starts()):
        tr = transcripts.get(c.asset)
        if tr is None:
            continue
        for w in tr.words:
            if c.src_in <= w.start < c.src_out - 0.05:
                a = c.tl_at(s, w.start)
                b = c.tl_at(s, min(w.end, c.src_out))
                out.append((w.text.strip(), round(a, 3), round(b, 3), f"{c.asset}:w{w.i}"))
    return sorted(out, key=lambda x: x[1])


def pick(words: list[tuple[str, float, float, str]], duration: float, max_hits: int = 6,
         min_gap: float = 2.0) -> list[Hit]:
    scored = []
    for i, (txt, a, b, _id) in enumerate(words):
        cw = _clean(txt)
        if not cw or cw in STOP:
            continue
        sc = 0.0
        if NUM.search(cw):
            sc += 5.0                                      # cifrele sunt dovezi: aproape mereu lovitură
        sc += min(len(cw), 12) / 3                         # cuvintele lungi poartă sensul
        nxt = words[i + 1][1] if i + 1 < len(words) else duration
        if nxt - b > 0.25:
            sc += 0.8                                      # pauza de după: vorbitorul apasă pe cuvânt
        if txt.rstrip()[-1:] in ".!?":
            sc += 0.3
        if a < 2.5:
            sc += 1.5                                      # hook-ul
        if cw.isupper() or txt[:1].isupper() and i and words[i - 1][0][-1:] not in ".!?":
            sc += 0.4                                      # nume propriu în mijlocul frazei
        scored.append((sc, i))
    score = {i: sc for sc, i in scored}
    chosen: list[int] = []
    for sc, i in sorted(scored, reverse=True):
        a = words[i][1]
        if all(abs(a - words[j][1]) >= min_gap for j in chosen):
            chosen.append(i)
        if len(chosen) >= max_hits:
            break
    hits = []
    for i in sorted(chosen):
        txt, a, b, _ = words[i]
        before = []
        for w in reversed(words[max(0, i - 4):i]):  # rândul mic: doar din aceeași frază
            if a - w[1] > 2.0 or w[0].rstrip()[-1:] in ".!?":
                break
            before.insert(0, w[0])
        after = [w[0] for w in words[i + 1:i + 3] if w[1] - b < 1.0]
        lo = max(0, i - 3)
        phrase = [(w[0], w[1]) for w in words[lo:i + 3] if abs(w[1] - a) < 1.8]
        hits.append(Hit(a, b, txt, before, after, phrase, round(score[i], 2)))
    return hits


def scene(h: Hit, k: int, next_t: float) -> dict:
    """Blocul propus pentru o lovitură (motion_add)."""
    w = re.sub(r"[^\w%ăâîșțĂÂÎȘȚ-]", "", h.word)
    end = round(min(h.t + 1.4, next_t - 0.2), 2)
    start = round(max(h.t - 0.15, 0.0), 2)
    end = round(max(end, start + 1.2), 2)
    nxt = _clean(h.after[0]) if h.after else ""
    if NUM.search(w) and nxt in TIME_UNITS:
        n = int(re.sub(r"\D", "", w) or 1)
        return {"block": "day_counter", "start": start, "end": round(max(end, start + 1.5), 2),
                "params": {"from": 1, "to": min(n, 99), "label": h.after[0]}, "behind": False}
    end = round(end, 2)
    if k % 3 == 1 and 3 <= len(h.phrase) <= 6:
        t0 = h.phrase[0][1]
        return {"block": "orbit_words", "start": round(t0 - 0.05, 2), "end": round(max(end, t0 + 1.6), 2),
                "params": {"text": " ".join(p[0] for p in h.phrase), "times": [round(p[1] - t0 + 0.05, 2) for p in h.phrase],
                           "emphasis": [_clean(h.word)], "layout": "arc"}, "behind": True}
    top = " ".join(h.before[-4:])[:40]
    return {"block": "stack_title", "start": start, "end": end,
            "params": {k2: v for k2, v in {"top": top, "word": w.upper() if len(w) <= 6 else w.capitalize(),
                                           "reveal": "pixel" if k == 0 else "blur"}.items() if v},
            "behind": True}


def plan(tl, transcripts: dict, max_hits: int = 6) -> str:
    words = words_on_timeline(tl, transcripts)
    if not words:
        return "nu am transcript pentru clipurile din montaj: rulează transcript_get pe asset-uri"
    reel = tl.height > tl.width
    hits = pick(words, tl.duration, max_hits=max_hits, min_gap=2.0 if reel else 6.0)
    starts = tl.starts()
    lines = [f"plan de reel: {len(hits)} lovituri în {tl.duration:.1f} s (o scenă la ~{tl.duration / max(len(hits), 1):.1f} s)"]
    for k, h in enumerate(hits):
        nxt = hits[k + 1].t if k + 1 < len(hits) else tl.duration
        # nu trece blocul din spate peste o tăietură
        cut = next((s for s in starts[1:] if h.t < s < nxt), None)
        sc = scene(h, k, min(nxt, cut) if cut else nxt)
        dur = sc["end"] - sc["start"]
        lines.append(f"{h.t:6.2f}s  „{h.word}”  → {sc['block']} ({dur:.1f} s){'  [în spate]' if sc['behind'] else ''}")
        lines.append("        motion_add(" + json.dumps({k2: v for k2, v in sc.items()}, ensure_ascii=False) + ")")
    lines.append("Verifică fiecare cu motion_preview; schimbă ce nu e ideea frazei. Apoi sfx_auto și reel_check.")
    return "\n".join(lines)
