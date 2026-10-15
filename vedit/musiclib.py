"""Muzica de fundal: catalogul Kevin MacLeod (incompetech.com, CC BY 4.0) + biblioteca ta (vedit-music import).

Catalogul e în repo (music_catalog.json, 1.443 de piese cu stare, gen, BPM, durată): căutarea nu cere internet.
Piesa aleasă se descarcă o singură dată, în VEDIT_MUSIC_DIR. CC BY cere credit: îl ține proiectul (meta) și
intră automat în descrierea postării (vedit/publish).

Biblioteca proprie (Artlist, Epidemic, piese cumpărate): `vedit-music import <folder> --license "..."`.
Starea se ia din numele folderului / fișierului (ex. „upbeat/…”, „calm - piano.mp3”), BPM-ul se măsoară.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CATALOG = Path(__file__).with_name("music_catalog.json")
CREDIT = ("„{title}” Kevin MacLeod (incompetech.com). Licensed under Creative Commons: "
          "By Attribution 4.0 License, http://creativecommons.org/licenses/by/4.0/")

# cuvintele cu care cere agentul (ro / en) -> stările din catalog
MOODS = {
    "energic": ["Driving", "Bouncy", "Action", "Intense"], "upbeat": ["Bouncy", "Bright", "Grooving", "Uplifting"],
    "vesel": ["Bright", "Bouncy", "Humorous"], "inspirational": ["Uplifting", "Bright", "Epic"],
    "motivational": ["Uplifting", "Driving", "Epic"], "calm": ["Calming", "Relaxed"], "relaxat": ["Relaxed", "Calming"],
    "corporate": ["Bright", "Uplifting", "Relaxed"], "premium": ["Relaxed", "Grooving", "Calming"],
    "groove": ["Grooving", "Bouncy"], "lofi": ["Relaxed", "Grooving", "Calming"], "epic": ["Epic", "Intense", "Action"],
    "dramatic": ["Intense", "Somber", "Epic"], "misterios": ["Mysterious", "Mystical", "Suspenseful"],
    "tensiune": ["Suspenseful", "Unnerving", "Intense"], "trist": ["Somber", "Calming"], "amuzant": ["Humorous", "Bouncy"],
    "sport": ["Driving", "Action", "Intense", "Aggressive"], "documentar": ["Mysterious", "Somber", "Calming", "Relaxed"],
    "dark": ["Dark", "Mysterious", "Eerie"],
}


# genurile care se potrivesc unei stări (urcă în listă); restul nu dispare, doar coboară
MOOD_GENRES = {
    "premium": ["Electronica", "Contemporary", "Modern", "Urban", "Pop"], "corporate": ["Contemporary", "Pop", "Electronica"],
    "lofi": ["Urban", "Electronica", "Jazz"], "upbeat": ["Pop", "Electronica", "Funk", "Contemporary"],
    "energic": ["Electronica", "Rock", "Funk"], "sport": ["Rock", "Electronica"], "inspirational": ["Contemporary", "Soundtrack"],
    "motivational": ["Contemporary", "Electronica", "Soundtrack"], "documentar": ["Soundtrack", "Contemporary", "World"],
    "epic": ["Soundtrack"], "dramatic": ["Soundtrack"], "groove": ["Funk", "Urban", "Electronica", "Jazz"],
    "calm": ["Contemporary", "Classical", "Electronica"],
}
AVOID = {"premium": ["Classical", "Silent Film Score"], "corporate": ["Classical"], "lofi": ["Classical", "Rock"],
         "upbeat": ["Classical"], "energic": ["Classical"], "sport": ["Classical", "Jazz"]}


def lib_dir() -> Path:
    env = os.environ.get("VEDIT_MUSIC_DIR")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "vedit" / "music"


def catalog() -> list[dict]:
    d = json.loads(CATALOG.read_text(encoding="utf-8"))
    out = [{"id": "km:" + p["f"].rsplit(".", 1)[0], "title": p["t"], "file": p["f"], "seconds": p["s"], "bpm": p["b"],
            "genre": p["g"], "feel": p["feel"], "instruments": p["i"], "about": p["d"], "source": "incompetech",
            "license": "CC BY 4.0", "credit": CREDIT.format(title=p["t"])} for p in d["pieces"]]
    out += own()
    return out


def own() -> list[dict]:
    f = lib_dir() / "own" / "index.json"
    return json.loads(f.read_text()) if f.exists() else []


def search(mood: str = "", query: str = "", bpm_min: int = 0, bpm_max: int = 0, min_seconds: float = 0,
           genre: str = "", n: int = 8, exclude: tuple[str, ...] = ("Horror", "Holiday", "Polka", "Silent Film Score")) -> list[dict]:
    want: list[str] = []
    for w in re.split(r"[\s,/]+", mood.lower()):
        if not w:
            continue
        want += MOODS.get(w, [w.capitalize()])
    words = [w for w in re.split(r"\W+", query.lower()) if len(w) > 2]
    res = []
    for p in catalog():
        if p["genre"] in exclude and genre.lower() != p["genre"].lower():
            continue
        if genre and genre.lower() not in p["genre"].lower():
            continue
        if bpm_min and p["bpm"] and p["bpm"] < bpm_min or bpm_max and p["bpm"] and p["bpm"] > bpm_max:
            continue
        if min_seconds and p["seconds"] < min_seconds:
            continue
        score = sum(2.0 for f in p["feel"] if f in want)
        moods = [w for w in re.split(r"[\s,/]+", mood.lower()) if w]
        if any(p["genre"] in MOOD_GENRES.get(w, []) for w in moods):
            score += 2.5
        if any(p["genre"] in AVOID.get(w, []) for w in moods) or "waltz" in p["title"].lower():
            score -= 4
        text = f"{p['title']} {p['about']} {p['instruments']}".lower()
        score += sum(1.0 for w in words if w in text)
        if want and not any(f in want for f in p["feel"]):
            continue
        if words and not any(w in text for w in words) and not want:
            continue
        if p["source"] != "incompetech":
            score += 1.5  # piesele tale (licențiate de tine) au prioritate
        res.append((score, p))
    res.sort(key=lambda x: (-x[0], abs((x[1]["seconds"] or 200) - 150)))
    return [p for _, p in res[:n]]


def get(track_id: str) -> dict:
    for p in catalog():
        if p["id"] == track_id:
            return p
    raise ValueError(f"piesă necunoscută: {track_id} (caută cu music_find)")


def fetch(track: dict) -> Path:
    """Fișierul local al piesei (descărcat o dată). Piesele proprii sunt deja pe disc."""
    if track["source"] != "incompetech":
        return Path(track["path"])
    dest = lib_dir() / "incompetech" / track["file"]
    if dest.exists() and dest.stat().st_size > 50_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = json.loads(CATALOG.read_text(encoding="utf-8"))["url"] + urllib.parse.quote(track["file"])
    req = urllib.request.Request(url, headers={"User-Agent": "vedit-music/1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if not (data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")):
        raise ValueError("serverul n-a dat un MP3 (încearcă altă piesă)")
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(dest)
    return dest


def import_dir(folder: Path, license_: str, credit: str = "", log=print) -> int:
    """Piesele tale: starea din numele folderului/fișierului, BPM-ul măsurat (vedit.beats)."""
    from .beats import detect
    from .probe import probe

    root = lib_dir() / "own"
    root.mkdir(parents=True, exist_ok=True)
    idx = {p["id"]: p for p in own()}
    n = 0
    known = {f.lower(): f for fs in MOODS.values() for f in fs} | {k: k for k in MOODS}
    for f in sorted(Path(folder).rglob("*")):
        if f.suffix.lower() not in (".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"):
            continue
        rel = str(f.relative_to(folder)).lower()
        feel = sorted({known[w] if w in known else w.capitalize() for w in re.split(r"[^a-zăâîșț]+", rel) if w in known})
        feel = [x for k in feel for x in (MOODS.get(k.lower(), [k]))] or ["Relaxed"]
        try:
            info = probe(str(f))
            bpm = int(round(detect(str(f), duration=90).bpm))
        except Exception as e:  # fișier stricat: îl sărim
            log(f"  sar peste {f.name}: {e}")
            continue
        tid = "own:" + re.sub(r"[^a-z0-9]+", "-", rel)[:80]
        idx[tid] = {"id": tid, "title": f.stem, "file": f.name, "path": str(f.resolve()), "seconds": int(info.duration),
                    "bpm": bpm, "genre": "", "feel": sorted(set(feel)), "instruments": "", "about": "",
                    "source": "own", "license": license_, "credit": credit}
        n += 1
    (root / "index.json").write_text(json.dumps(list(idx.values()), ensure_ascii=False, indent=1))
    log(f"{n} piese adăugate în biblioteca ta")
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vedit-music", description="Muzica de fundal.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("find")
    s.add_argument("mood", nargs="?", default="")
    s.add_argument("--query", default="")
    s.add_argument("--bpm", default="", help="ex. 90-120")
    i = sub.add_parser("import")
    i.add_argument("folder")
    i.add_argument("--license", required=True)
    i.add_argument("--credit", default="", help="textul de credit, dacă licența îl cere")
    a = ap.parse_args(argv)
    if a.cmd == "import":
        import_dir(Path(a.folder).expanduser(), a.license, a.credit)
        return 0
    lo, hi = (int(x) for x in a.bpm.split("-")) if a.bpm else (0, 0)
    for p in search(a.mood, a.query, lo, hi):
        print(f"{p['id']:<40} {p['bpm']:>4} bpm {p['seconds'] // 60}:{p['seconds'] % 60:02d}  {', '.join(p['feel'])}  "
              f"| {p['about'][:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
