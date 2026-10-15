"""YouTube Data API v3: conectarea unui canal și urcarea unui video (resumable), cu thumbnail și programare.

Notă: proiectele Google neverificate (create după 28 iulie 2020) pot urca doar video PRIVATE, până trec
de auditul YouTube API. Codul urcă oricum; dacă YouTube îl blochează pe privat, raportul o spune.
"""
from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

from .net import ApiError, base_url, browser_login, pkce_pair, request

SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
CHUNK = 8 * 1024 * 1024  # multiplu de 256 KiB, cum cere protocolul resumable


def connect(app: dict, open_browser: bool = True) -> tuple[str, str, dict]:
    """Login Google în browser -> (id canal, nume afișat, secrete de salvat în seif)."""
    verifier, challenge = pkce_pair()

    def url(redirect, state):
        return base_url("google_auth") + "/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": app["client_id"], "redirect_uri": redirect, "response_type": "code",
            "scope": SCOPES, "access_type": "offline", "prompt": "consent select_account",
            "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})

    got, redirect = browser_login(url, open_browser=open_browser)
    _, tok, _ = request("POST", base_url("google_token") + "/token", form={
        "code": got["code"], "client_id": app["client_id"], "client_secret": app.get("client_secret", ""),
        "redirect_uri": redirect, "grant_type": "authorization_code", "code_verifier": verifier})
    if "refresh_token" not in tok:
        raise RuntimeError("Google n-a dat refresh_token: scoate accesul aplicației din contul Google și reconectează")
    sec = {"refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
           "expires": int(time.time()) + int(tok.get("expires_in", 3600)) - 60}
    _, ch, _ = request("GET", base_url("youtube") + "/youtube/v3/channels",
                       params={"part": "snippet", "mine": "true"},
                       headers={"Authorization": f"Bearer {sec['access_token']}"})
    items = ch.get("items") or []
    if not items:
        raise RuntimeError("contul Google n-are canal YouTube")
    return items[0]["id"], items[0]["snippet"]["title"], sec


def access_token(app: dict, sec: dict, save) -> str:
    if sec.get("access_token") and sec.get("expires", 0) > time.time():
        return sec["access_token"]
    _, tok, _ = request("POST", base_url("google_token") + "/token", form={
        "client_id": app["client_id"], "client_secret": app.get("client_secret", ""),
        "refresh_token": sec["refresh_token"], "grant_type": "refresh_token"})
    patch = {"access_token": tok["access_token"], "expires": int(time.time()) + int(tok.get("expires_in", 3600)) - 60}
    save(patch)
    return patch["access_token"]


def publish(app: dict, sec: dict, save, pkg, video: Path, cover: Path | None, log) -> dict:
    token = access_token(app, sec, save)
    auth = {"Authorization": f"Bearer {token}"}
    status = {"privacyStatus": pkg.privacy, "selfDeclaredMadeForKids": bool(pkg.options["made_for_kids"])}
    if pkg.schedule_at:
        from .package import parse_time

        status["privacyStatus"] = "private"
        status["publishAt"] = parse_time(pkg.schedule_at).strftime("%Y-%m-%dT%H:%M:%SZ")
    if "contains_synthetic_media" in pkg.options:
        status["containsSyntheticMedia"] = bool(pkg.options["contains_synthetic_media"])
    body = {"snippet": {"title": pkg.title, "description": pkg.full_text(),
                        "categoryId": pkg.options.get("category_id", "22"),
                        "tags": [t.lstrip("#") for t in pkg.options.get("tags", [])]},
            "status": status}
    size = video.stat().st_size
    _, _, h = request("POST", base_url("youtube") + "/upload/youtube/v3/videos",
                      params={"uploadType": "resumable", "part": "snippet,status"}, json_body=body,
                      headers={**auth, "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
    loc = h.get("Location") or h.get("location")
    if not loc:
        raise RuntimeError("YouTube n-a dat adresa de upload")
    sent, result = 0, {}
    with open(video, "rb") as f:
        while sent < size:
            chunk = f.read(CHUNK)
            end = sent + len(chunk) - 1
            try:
                st, result, h = request("PUT", loc, data=chunk, timeout=600, headers={
                    **auth, "Content-Type": "video/mp4", "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {sent}-{end}/{size}"})
            except ApiError as e:
                if e.status != 308:
                    raise
            sent = end + 1
            log(f"YouTube: {sent * 100 // size}% urcat")
    vid = result.get("id")
    if not vid:
        raise RuntimeError(f"YouTube n-a confirmat video-ul: {result}")
    out = {"id": vid, "url": f"https://youtu.be/{vid}", "privacy": result.get("status", {}).get("privacyStatus")}
    if cover is not None:
        try:
            mime = "image/png" if cover.suffix.lower() == ".png" else "image/jpeg"
            request("POST", base_url("youtube") + "/upload/youtube/v3/thumbnails/set", params={"videoId": vid},
                    data=cover.read_bytes(), headers={**auth, "Content-Type": mime})
            out["thumbnail"] = "pus"
        except ApiError as e:  # canalele neverificate prin telefon nu pot pune thumbnail
            out["thumbnail"] = f"nepus: {e.body[:200]}"
    if out.get("privacy") == "private" and pkg.privacy == "public" and not pkg.schedule_at:
        out["warning"] = ("YouTube l-a lăsat privat: aplicația Google n-a trecut încă de auditul YouTube API. "
                          "Îl poți face public din YouTube Studio.")
    return out

