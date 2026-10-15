"""De unde vine B-roll-ul când clientul nu are footage.

Ordinea recomandată (și impusă de skill):
  1. footage-ul clientului
  2. stock real, gratuit: Pexels (PEXELS_API_KEY)
  3. generare AI, cu plată, DOAR dacă e cerută explicit: fal.ai (FAL_KEY) sau Replicate (REPLICATE_API_TOKEN)

Protocoalele HTTP sunt cele din documentația oficială (fal queue: submit → status → result;
Replicate: POST /v1/models/{owner}/{name}/predictions, apoi urls.get). ID-urile modelelor se schimbă des,
deci modelul se alege prin VEDIT_FAL_MODEL / VEDIT_REPLICATE_MODEL, iar parametrii specifici modelului
prin VEDIT_GEN_EXTRA (JSON). Doar biblioteca standard (urllib), deci proxy-ul din mediu e respectat.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MAX_DOWNLOAD = 400 * 1024 * 1024


class SourceError(RuntimeError):
    pass


def _req(method: str, url: str, headers: dict | None = None, body: dict | None = None, timeout: float = 60) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    h = {"Accept": "application/json", "User-Agent": "vedit/0.1", **(headers or {})}
    if data is not None:
        h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h, method=method), timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise SourceError(f"{method} {url.split('?')[0]} → HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise SourceError(f"{method} {url.split('?')[0]} → {e.reason}") from e


def download(url: str, dest: Path, headers: dict | None = None) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    req = urllib.request.Request(url, headers={"User-Agent": "vedit/0.1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=300) as r, open(tmp, "wb") as out:
            total = 0
            while chunk := r.read(1 << 20):
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise SourceError("fișier prea mare (> 400 MB)")
                out.write(chunk)
    except urllib.error.URLError as e:
        tmp.unlink(missing_ok=True)
        raise SourceError(f"descărcare eșuată: {e}") from e
    tmp.replace(dest)
    return dest


# ---------------------------------------------------------------- stock: Pexels
def pexels_search(query: str, orientation: str | None = None, per_page: int = 10, min_duration: float = 3) -> list[dict]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise SourceError("lipsește PEXELS_API_KEY (gratuit pe pexels.com/api)")
    base = os.environ.get("VEDIT_PEXELS_BASE", "https://api.pexels.com")
    q = {"query": query, "per_page": per_page, "size": "medium"}
    if orientation:
        q["orientation"] = orientation
    data = _req("GET", f"{base}/v1/videos/search?{urllib.parse.urlencode(q)}", {"Authorization": key})
    out = []
    for v in data.get("videos", []):
        if v.get("duration", 0) < min_duration:
            continue
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("link")]
        if not files:
            continue
        # cea mai mică rezoluție de cel puțin 1080 pe latura scurtă, altfel cea mai mare disponibilă
        files.sort(key=lambda f: min(f.get("width") or 0, f.get("height") or 0))
        best = next((f for f in files if min(f.get("width") or 0, f.get("height") or 0) >= 1080), files[-1])
        out.append({"id": v["id"], "url": best["link"], "width": best.get("width"), "height": best.get("height"),
                    "duration": v.get("duration"), "page": v.get("url"), "author": (v.get("user") or {}).get("name", "")})
    return out


# ---------------------------------------------------------------- generare: fal / Replicate
def _find_video_url(obj) -> str | None:
    """Rezultatul diferă de la model la model; căutăm primul URL de video."""
    if isinstance(obj, str):
        return obj if obj.startswith("http") and any(x in obj.split("?")[0].lower() for x in (".mp4", ".mov", ".webm")) else None
    if isinstance(obj, dict):
        for k in ("video", "videos", "output", "url"):
            if k in obj:
                u = _find_video_url(obj[k])
                if u:
                    return u
        for v in obj.values():
            u = _find_video_url(v)
            if u:
                return u
    if isinstance(obj, list):
        for v in obj:
            u = _find_video_url(v)
            if u:
                return u
    return None


def _extra() -> dict:
    raw = os.environ.get("VEDIT_GEN_EXTRA", "")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise SourceError(f"VEDIT_GEN_EXTRA nu e JSON valid: {e}") from e


def provider() -> str | None:
    want = os.environ.get("VEDIT_GEN_PROVIDER")
    if want:
        return want
    if os.environ.get("FAL_KEY"):
        return "fal"
    if os.environ.get("REPLICATE_API_TOKEN"):
        return "replicate"
    return None


def generate_fal(prompt: str, duration: float, aspect: str, poll: float = 3.0, timeout: float = 900) -> str:
    key, model = os.environ.get("FAL_KEY"), os.environ.get("VEDIT_FAL_MODEL")
    if not key:
        raise SourceError("lipsește FAL_KEY")
    if not model:
        raise SourceError("setează VEDIT_FAL_MODEL (ID-ul modelului text-to-video de pe fal.ai, ex. din pagina modelului)")
    base = os.environ.get("VEDIT_FAL_BASE", "https://queue.fal.run")
    h = {"Authorization": f"Key {key}"}
    body = {"prompt": prompt, "duration": int(round(duration)), "aspect_ratio": aspect, **_extra()}
    sub = _req("POST", f"{base}/{model}", h, body)
    status_url = sub.get("status_url") or f"{base}/{model}/requests/{sub['request_id']}/status"
    result_url = sub.get("response_url") or f"{base}/{model}/requests/{sub['request_id']}"
    t0 = time.time()
    while True:
        st = _req("GET", status_url, h)
        if st.get("status") == "COMPLETED":
            break
        if st.get("status") not in ("IN_QUEUE", "IN_PROGRESS"):
            raise SourceError(f"fal: status neașteptat {st.get('status')}: {str(st)[:200]}")
        if time.time() - t0 > timeout:
            raise SourceError("fal: timeout la generare")
        time.sleep(poll)
    res = _req("GET", result_url, h)
    url = _find_video_url(res)
    if not url:
        raise SourceError(f"fal: nu găsesc video în rezultat: {str(res)[:200]}")
    return url


def generate_replicate(prompt: str, duration: float, aspect: str, poll: float = 3.0, timeout: float = 900) -> str:
    tok, model = os.environ.get("REPLICATE_API_TOKEN"), os.environ.get("VEDIT_REPLICATE_MODEL")
    if not tok:
        raise SourceError("lipsește REPLICATE_API_TOKEN")
    if not model or "/" not in model:
        raise SourceError("setează VEDIT_REPLICATE_MODEL=owner/nume (un model text-to-video de pe replicate.com)")
    base = os.environ.get("VEDIT_REPLICATE_BASE", "https://api.replicate.com")
    h = {"Authorization": f"Bearer {tok}", "Prefer": "wait=60"}
    body = {"input": {"prompt": prompt, "duration": int(round(duration)), "aspect_ratio": aspect, **_extra()}}
    pred = _req("POST", f"{base}/v1/models/{model}/predictions", h, body, timeout=90)
    t0 = time.time()
    while pred.get("status") not in ("succeeded", "failed", "canceled"):
        if time.time() - t0 > timeout:
            raise SourceError("replicate: timeout la generare")
        time.sleep(poll)
        pred = _req("GET", pred["urls"]["get"], {"Authorization": f"Bearer {tok}"})
    if pred["status"] != "succeeded":
        raise SourceError(f"replicate: {pred['status']}: {str(pred.get('error'))[:200]}")
    url = _find_video_url(pred.get("output"))
    if not url:
        raise SourceError(f"replicate: nu găsesc video în output: {str(pred.get('output'))[:200]}")
    return url


def generate(prompt: str, duration: float, aspect: str) -> tuple[str, str]:
    """Returnează (url_video, provider)."""
    p = provider()
    if p == "fal":
        return generate_fal(prompt, duration, aspect), "fal"
    if p == "replicate":
        return generate_replicate(prompt, duration, aspect), "replicate"
    raise SourceError("niciun provider de generare configurat (FAL_KEY sau REPLICATE_API_TOKEN)")
