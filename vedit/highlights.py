"""Cele mai bune momente dintr-un video lung (podcast, stream, interviu), pentru shorts.

Fără LLM: candidații sunt fraze întregi de `min_len`-`max_len` secunde, notate după semnale pe care le folosesc și
editorii: hook în prima frază (întrebare, cifră, „secret”, „greșeală”, „de ce”), energie în voce (mai tare decât
restul episodului), ritm de vorbire, fără pauze moarte, final de frază. Agentul citește doar primele câteva și
alege cu judecata lui, în loc să citească tot transcriptul unei ore.
"""
from __future__ import annotations

import re

import numpy as np

HOOKS = [
    # ro
    r"\bsecret", r"\bgreșe", r"\bgrese", r"\bde ce\b", r"\bcum (să|sa)\b", r"\bnimeni\b", r"\bniciodată\b",
    r"\badevăr", r"\bnu o să\b", r"\bcel mai\b", r"\bcea mai\b", r"\bproblema\b", r"\bbani\b", r"\bgratis\b",
    r"\bimportant\b", r"\bincredibil", r"\bșoc", r"\bfrică\b", r"\bpovest",
    # en
    r"\bsecret", r"\bmistake", r"\bwhy\b", r"\bhow to\b", r"\bnobody\b", r"\bnever\b", r"\btruth\b",
    r"\bthe best\b", r"\bthe worst\b", r"\bmoney\b", r"\bfree\b", r"\bcrazy\b", r"\binsane\b", r"\bstory\b",
    # hu
    r"\btitok", r"\bhiba", r"\bmiért\b", r"\bhogyan\b", r"\bsenki\b", r"\bsoha\b", r"\bigazság", r"\bpénz",
]
_HOOK = re.compile("|".join(HOOKS), re.I)
_END = re.compile(r"[.!?…]$")
_ABBR = {"mr.", "mrs.", "ms.", "dr.", "st.", "sf.", "dl.", "dna.", "prof.", "etc.", "vs.", "nr.", "ing."}
# un fragment care începe cu o conjuncție nu stă singur (îi lipsește ce era înainte)
_WEAK_START = {"and", "but", "so", "or", "și", "si", "dar", "că", "ca", "iar", "deci", "és", "de", "hogy"}


def _ends(text: str) -> bool:
    t = text.strip()
    return bool(_END.search(t)) and t.lower() not in _ABBR


def _sentences(words) -> list[tuple[int, int]]:
    """Indicii (început, sfârșit inclusiv) ai frazelor: punct la final sau pauză > 0.7 s."""
    out, start = [], 0
    for i, w in enumerate(words):
        nxt = words[i + 1] if i + 1 < len(words) else None
        if _ends(w.text) or nxt is None or nxt.start - w.end > 0.7:
            out.append((start, i))
            start = i + 1
    return out


def energy(y: np.ndarray, sr: int, hop: float = 0.25) -> np.ndarray:
    n = int(sr * hop)
    k = len(y) // n
    if k == 0:
        return np.zeros(1)
    return 10 * np.log10(np.mean(y[: k * n].reshape(k, n) ** 2, axis=1) + 1e-10)


def find(words, env: np.ndarray, hop: float = 0.25, n: int = 5, min_len: float = 20.0,
         max_len: float = 60.0) -> list[dict]:
    """Top `n` fragmente care nu se suprapun: [{start, end, w0, w1, score, why, hook}]."""
    if not words:
        return []
    sents = _sentences(words)
    speech = env[env > np.percentile(env, 30)] if env.size > 4 else env
    base, spread = (float(np.median(speech)), float(np.std(speech)) or 1.0) if speech.size else (0.0, 1.0)
    rates = [len(words[a:b + 1]) / max(words[b].end - words[a].start, 0.3) for a, b in sents]
    rate_med = float(np.median(rates)) if rates else 2.5
    cands = []
    for si, (a, _) in enumerate(sents):
        for sj in range(si, len(sents)):
            b = sents[sj][1]
            dur = words[b].end - words[a].start
            if dur > max_len:
                break
            if dur < min_len:
                continue
            ws = words[a:b + 1]
            gaps = sum(max(0.0, y.start - x.end - 0.5) for x, y in zip(ws, ws[1:]))
            seg = env[int(words[a].start / hop): int(words[b].end / hop) + 1]
            loud = (float(np.mean(seg)) - base) / spread if seg.size else 0.0
            peaks = float(np.mean(seg > base + spread)) if seg.size else 0.0
            rate = len(ws) / max(dur, 1.0)
            first = " ".join(w.text for w in words[a:sents[si][1] + 1])
            why, score = [], 0.0
            if first.rstrip().endswith("?"):
                score += 2.0
                why.append("începe cu o întrebare")
            if _HOOK.search(first):
                score += 2.0
                why.append("hook în prima frază")
            if re.search(r"\d", first):
                score += 1.0
                why.append("cifră în hook")
            score += 1.5 * float(np.clip(loud, -1, 2)) + 3.0 * peaks
            if loud > 0.5:
                why.append("energie peste medie")
            score += 1.0 * float(np.clip(rate / rate_med - 1, -0.5, 0.5)) * 2
            score -= 0.6 * gaps
            if gaps > 2:
                why.append(f"{gaps:.0f}s de pauze")
            score += 0.5 * len(_HOOK.findall(" ".join(w.text for w in ws))) ** 0.5
            if not _ends(ws[-1].text):
                score -= 0.5
            if re.sub(r"\W", "", ws[0].text.lower()) in _WEAK_START:
                score -= 1.0
            cands.append({"start": round(words[a].start, 2), "end": round(words[b].end, 2), "w0": ws[0].i,
                          "w1": ws[-1].i, "score": round(score, 2), "why": why, "hook": first[:160]})
    cands.sort(key=lambda c: -c["score"])
    picked: list[dict] = []
    for c in cands:
        if all(c["end"] <= p["start"] or c["start"] >= p["end"] for p in picked):
            picked.append(c)
        if len(picked) >= n:
            break
    return picked
