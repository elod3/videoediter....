"""Biblioteca de efecte sonore reale (CC0), în locul celor sintetizate.

    vedit-sfx fetch           # descarcă sursele din sfx_sources.json, verifică sha256, pregătește fișierele
    vedit-sfx import <folder> # adaugă un pachet al tău (Sonniss, cumpărat, înregistrat), clasat după numele fișierelor
    vedit-sfx list            # ce e în bibliotecă

Fiecare sunet e pregătit o dată (48 kHz stereo, liniștea tăiată, vârful la -3 dBFS) și tăiat după rolul lui,
ca să cadă la fel ca efectul sintetizat pe care îl înlocuiește: whoosh-ul are vârful în același loc, riser-ul se
termină exact pe moment, impactul pornește imediat. La randare se alege o variantă după momentul din clip,
deterministă: același montaj sună la fel, dar două whoosh-uri la rând nu sunt identice.
Fără bibliotecă (sau fără un tip în ea), vedit folosește sunetele sintetizate din sfx.py.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

SOURCES = Path(__file__).with_name("sfx_sources.json")
AUDIO_EXT = (".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aif", ".aiff")

# cum se taie fiecare tip: (secunde înainte de vârf, secunde după vârf) sau ("onset", lungime maximă)
SHAPE = {
    "whoosh": ("peak", 0.38, 0.32), "swipe": ("peak", 0.14, 0.13), "riser": ("peak", 1.5, 0.1),
    "buildup": ("peak", 6.0, 0.2), "reverse": ("peak", 2.0, 0.05),
    "impact": ("onset", 1.6), "bass_drop": ("onset", 2.2), "pop": ("onset", 0.35), "click": ("onset", 0.25),
    "ding": ("onset", 1.2), "camera": ("onset", 0.9), "glitch": ("onset", 0.6), "error": ("onset", 0.8),
}
# cuvinte din numele fișierelor, pentru `import` (pachete străine)
KEYWORDS = [
    ("riser", ["riser", "rise", "uplifter"]), ("buildup", ["buildup", "build-up", "build_up", "tension"]),
    ("reverse", ["reverse", "rev_", "suck"]), ("bass_drop", ["sub drop", "subdrop", "bass drop", "boom", "thump"]),
    ("impact", ["impact", "hit", "punch", "slam", "bang"]), ("swipe", ["swipe", "swish", "flick"]),
    ("whoosh", ["whoosh", "swoosh", "woosh", "pass", "transition"]), ("pop", ["pop", "bubble", "pluck"]),
    ("click", ["click", "tap", "button", "ui", "select", "tick", "toggle"]), ("ding", ["ding", "chime", "bell", "success", "notification"]),
    ("camera", ["shutter", "camera", "flash"]), ("glitch", ["glitch", "stutter", "digital"]), ("error", ["error", "wrong", "fail"]),
]


def lib_dir() -> Path:
    env = os.environ.get("VEDIT_SFX_DIR")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
    return base / "vedit" / "sfx"


def index(root: Path | None = None) -> dict[str, list[dict]]:
    f = (root or lib_dir()) / "index.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _save_index(root: Path, idx: dict) -> None:
    tmp = root / "index.json.tmp"
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=1))
    tmp.replace(root / "index.json")


def pick(kind: str, at: float) -> Path | None:
    """Varianta pentru un efect la momentul `at`; None dacă biblioteca n-are tipul ăsta."""
    root = lib_dir()
    items = index(root).get(kind) or []
    items = [x for x in items if (root / x["file"]).exists()]
    if not items:
        return None
    i = int(hashlib.sha1(f"{kind}:{round(at, 2)}".encode()).hexdigest(), 16) % len(items)
    return root / items[i]["file"]


def kinds_available() -> dict[str, int]:
    return {k: len(v) for k, v in index().items() if v}


# ---------------- pregătirea unui fișier ----------------
def _ffmpeg() -> str:
    from .ff import ffmpeg_bin
    return ffmpeg_bin()


def _decode(path: Path):
    import numpy as np

    raw = subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-i", str(path), "-f", "f32le", "-ac", "2",
                          "-ar", "48000", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def prepare(src: Path, kind: str, dst: Path) -> float:
    """Taie și normalizează un sunet după rolul lui. Întoarce durata finală."""
    import numpy as np

    from .sfx import SR, write_wav

    x = _decode(src)
    if len(x) < 64:
        raise ValueError("sunet gol")
    env = np.abs(x).max(1)
    thr = max(env.max() * 10 ** (-45 / 20), 1e-5)
    on = int(np.argmax(env > thr))
    off = len(env) - int(np.argmax(env[::-1] > thr))
    x, env = x[on:off], env[on:off]
    shape = SHAPE[kind]
    if shape[0] == "peak":  # vârful energiei (fereastră de 20 ms) cade la `pre` secunde de la început
        win = int(SR * 0.02)
        rms = np.sqrt(np.convolve((x ** 2).mean(1), np.ones(win) / win, mode="same"))
        p = int(rms.argmax())
        pre, post = int(shape[1] * SR), int(shape[2] * SR)
        a, b = max(0, p - pre), min(len(x), p + post)
        x = x[a:b]
        if p - a < pre:  # sunetul începe mai târziu decât vrem: liniște înainte, ca vârful să stea pe loc
            x = np.vstack([np.zeros((pre - (p - a), 2), np.float32), x])
    else:
        x = x[: int(shape[1] * SR)]
    fade_in, fade_out = int(SR * 0.004), int(SR * min(0.06, len(x) / SR / 4))
    if fade_in:
        x[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
    if fade_out:
        x[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    peak = float(np.abs(x).max()) or 1.0
    x = x / peak * 10 ** (-3 / 20)
    dst.parent.mkdir(parents=True, exist_ok=True)
    write_wav(dst, x)
    return round(len(x) / SR, 3)


def _add(root: Path, idx: dict, src: Path, kind: str, name: str, source: str, license_: str) -> bool:
    safe = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")[:60] or "sfx"
    rel = f"{kind}/{source}-{safe}.wav"
    try:
        dur = prepare(src, kind, root / rel)
    except (ValueError, subprocess.CalledProcessError) as e:
        print(f"  sar peste {name}: {e}", file=sys.stderr)
        return False
    items = [x for x in idx.setdefault(kind, []) if x["file"] != rel]
    items.append({"file": rel, "dur": dur, "source": source, "license": license_, "name": name})
    idx[kind] = sorted(items, key=lambda x: x["file"])
    return True


def _get(url: str, timeout: float = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "vedit-sfx/1 (+https://github.com/elod3)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch(root: Path | None = None, only: str | None = None, log=print) -> dict[str, int]:
    """Descarcă sursele fixate (cu sha256) și le pune în bibliotecă."""
    root = root or lib_dir()
    root.mkdir(parents=True, exist_ok=True)
    idx = index(root)
    spec = json.loads(SOURCES.read_text())
    with tempfile.TemporaryDirectory(prefix="vedit_sfx_") as tmp:
        tmp = Path(tmp)
        for s in spec["sources"]:
            if only and s["name"] != only:
                continue
            log(f"{s['name']} ({s['license']})")
            n = 0
            if "files" in s:
                for f in s["files"]:
                    data = _get(f["url"])
                    if hashlib.sha256(data).hexdigest() != f["sha256"]:
                        log(f"  {f['name']}: fișierul de pe server s-a schimbat (sha256 diferit), îl sar")
                        continue
                    p = tmp / (f["name"] + Path(f["url"]).suffix)
                    p.write_bytes(data)
                    n += _add(root, idx, p, f["kind"], f["name"], s["name"], s["license"])
            if "zip" in s:
                data = _get(s["zip"]["url"], 300)
                if hashlib.sha256(data).hexdigest() != s["zip"]["sha256"]:
                    log("  arhiva s-a schimbat (sha256 diferit), o sar")
                    continue
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for info in z.infolist():
                        nm = Path(info.filename).name
                        if not nm.lower().endswith(AUDIO_EXT) or ".." in info.filename:
                            continue
                        stem = Path(nm).stem.lower()
                        kind = next((k for k, words in s["rules"].items() if any(stem.startswith(w) for w in words)), None)
                        if not kind:
                            continue
                        p = tmp / nm
                        p.write_bytes(z.read(info))
                        n += _add(root, idx, p, kind, Path(nm).stem, s["name"], s["license"])
            log(f"  {n} sunete")
    _save_index(root, idx)
    return {k: len(v) for k, v in idx.items()}


def classify(name: str) -> str | None:
    low = name.lower().replace("_", " ")
    for kind, words in KEYWORDS:
        if any(w in low for w in words):
            return kind
    return None


def import_dir(folder: Path, license_: str, root: Path | None = None, log=print) -> dict[str, int]:
    root = root or lib_dir()
    root.mkdir(parents=True, exist_ok=True)
    idx = index(root)
    added, skipped = 0, []
    src_name = re.sub(r"[^a-z0-9]+", "-", folder.name.lower()).strip("-")[:24] or "import"
    for p in sorted(Path(folder).rglob("*")):
        if not p.is_file() or p.suffix.lower() not in AUDIO_EXT:
            continue
        kind = classify(str(p.relative_to(folder)))
        if not kind:
            skipped.append(p.name)
            continue
        added += _add(root, idx, p, kind, p.stem, src_name, license_)
    _save_index(root, idx)
    log(f"{added} sunete adăugate" + (f"; {len(skipped)} fără tip recunoscut (ex. {', '.join(skipped[:3])})" if skipped else ""))
    return {k: len(v) for k, v in idx.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vedit-sfx", description="Biblioteca de efecte sonore reale.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--only")
    i = sub.add_parser("import")
    i.add_argument("folder")
    i.add_argument("--license", required=True, help="ex. „CC0”, „Sonniss GDC royalty-free”, „cumpărat de la X”")
    sub.add_parser("list")
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        res = fetch(only=a.only)
    elif a.cmd == "import":
        res = import_dir(Path(a.folder).expanduser(), a.license)
    else:
        res = {k: len(v) for k, v in index().items()}
    print(f"\nBiblioteca ({lib_dir()}):")
    for k, n in sorted(res.items()):
        print(f"  {k:<10} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
