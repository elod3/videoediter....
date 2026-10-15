"""TikTok Content Posting API (Direct Post), cu login desktop (PKCE în hex, callback pe localhost).

Până la auditul TikTok, aplicația poate posta doar PRIVAT (SELF_ONLY) și pentru cel mult 5 conturi pe zi.
Opțiunile de vizibilitate vin din creator_info: le respectăm, cum cer regulile TikTok.
"""
from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

from .net import ApiError, base_url, browser_login, pkce_pair, request

SCOPES = "user.info.basic,video.publish,video.upload"
PRIVACY = {"public": "PUBLIC_TO_EVERYONE", "friends": "MUTUAL_FOLLOW_FRIENDS",
           "followers": "FOLLOWER_OF_CREATOR", "private": "SELF_ONLY"}
MIN_CHUNK, CHUNK = 5 * 1024 * 1024, 10 * 1024 * 1024


def _api(path: str) -> str:
    return f"{base_url('tiktok')}/v2/{path.strip('/')}/"


def connect(app: dict, open_browser: bool = True) -> tuple[str, str, dict]:
    verifier, challenge = pkce_pair("hex")

    def url(redirect, state):
        return base_url("tiktok_auth") + "/v2/auth/authorize/?" + urllib.parse.urlencode({
            "client_key": app["client_key"], "scope": SCOPES, "response_type": "code",
            "redirect_uri": redirect, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})

    got, redirect = browser_login(url, open_browser=open_browser)
    _, tok, _ = request("POST", _api("oauth/token"), form={
        "client_key": app["client_key"], "client_secret": app["client_secret"], "code": got["code"],
        "grant_type": "authorization_code", "redirect_uri": redirect, "code_verifier": verifier})
    if "access_token" not in tok:
        raise RuntimeError(f"TikTok n-a dat token: {tok}")
    sec = _token_secrets(tok)
    _, me, _ = request("GET", _api("user/info"), params={"fields": "open_id,display_name"},
                       headers={"Authorization": f"Bearer {sec['access_token']}"})
    user = (me.get("data") or {}).get("user") or {}
    return tok["open_id"], user.get("display_name") or tok["open_id"], sec


def _token_secrets(tok: dict) -> dict:
    now = int(time.time())
    return {"access_token": tok["access_token"], "refresh_token": tok["refresh_token"],
            "expires": now + int(tok.get("expires_in", 86400)) - 120,
            "refresh_expires": now + int(tok.get("refresh_expires_in", 31536000))}


def access_token(app: dict, sec: dict, save) -> str:
    if sec.get("expires", 0) > time.time():
        return sec["access_token"]
    if sec.get("refresh_expires", 0) < time.time():
        raise RuntimeError("conexiunea TikTok a expirat (un an): reconectează contul")
    _, tok, _ = request("POST", _api("oauth/token"), form={
        "client_key": app["client_key"], "client_secret": app["client_secret"],
        "grant_type": "refresh_token", "refresh_token": sec["refresh_token"]})
    patch = _token_secrets(tok)
    save(patch)
    return patch["access_token"]


def chunk_plan(size: int) -> tuple[int, int]:
    """(chunk_size, total_chunk_count) după regulile TikTok: sub 5 MB o singură bucată; altfel bucăți
    egale, iar restul intră în ultima (care poate avea până la 128 MB)."""
    if size < MIN_CHUNK:
        return size, 1
    chunk = min(CHUNK, size)
    return chunk, max(1, size // chunk)


def publish(app: dict, sec: dict, save, pkg, video: Path, log, poll: float = 5, max_wait: float = 900) -> dict:
    token = access_token(app, sec, save)
    auth = {"Authorization": f"Bearer {token}"}
    _, ci, _ = request("POST", _api("post/publish/creator_info/query"), json_body={}, headers=auth)
    info = ci.get("data") or {}
    allowed = info.get("privacy_level_options") or []
    want = PRIVACY[pkg.privacy]
    if allowed and want not in allowed:
        nice = {v: k for k, v in PRIVACY.items()}
        raise RuntimeError("TikTok permite pe contul ăsta doar: " + ", ".join(nice.get(a, a) for a in allowed)
                           + (" (aplicația n-a trecut încă de auditul TikTok: postările sunt private)"
                              if allowed == ["SELF_ONLY"] else ""))
    size = video.stat().st_size
    chunk, total = chunk_plan(size)
    post_info = {"title": pkg.full_text(), "privacy_level": want,
                 "disable_comment": bool(pkg.options.get("disable_comment", info.get("comment_disabled", False))),
                 "disable_duet": bool(pkg.options.get("disable_duet", info.get("duet_disabled", False))),
                 "disable_stitch": bool(pkg.options.get("disable_stitch", info.get("stitch_disabled", False))),
                 "is_aigc": bool(pkg.options.get("is_aigc", False)),
                 "brand_content_toggle": bool(pkg.options.get("brand_content", False)),
                 "brand_organic_toggle": bool(pkg.options.get("brand_organic", False))}
    if pkg.cover_at_ms >= 0:
        post_info["video_cover_timestamp_ms"] = pkg.cover_at_ms
    _, init, _ = request("POST", _api("post/publish/video/init"), headers=auth, json_body={
        "post_info": post_info,
        "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total}})
    data = init.get("data") or {}
    pid, up = data.get("publish_id"), data.get("upload_url")
    if not pid or not up:
        raise RuntimeError(f"TikTok n-a pornit upload-ul: {init.get('error')}")
    with open(video, "rb") as f:
        for i in range(total):
            start = i * chunk
            length = size - start if i == total - 1 else chunk
            f.seek(start)
            body = f.read(length)
            try:
                request("PUT", up, data=body, timeout=600, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(body)),
                    "Content-Range": f"bytes {start}-{start + len(body) - 1}/{size}"})
            except ApiError as e:
                if e.status not in (201, 206):
                    raise
            log(f"TikTok: bucata {i + 1}/{total} urcată")
    t0 = time.time()
    while True:
        _, st, _ = request("POST", _api("post/publish/status/fetch"), headers=auth, json_body={"publish_id": pid})
        d = st.get("data") or {}
        status = d.get("status")
        if status == "PUBLISH_COMPLETE":
            ids = d.get("publicaly_available_post_id") or []
            return {"id": pid, "post_id": ids[0] if ids else "", "privacy": pkg.privacy,
                    "url": f"https://www.tiktok.com/@/video/{ids[0]}" if ids else ""}
        if status == "FAILED":
            raise RuntimeError(f"TikTok a refuzat postarea: {d.get('fail_reason') or st.get('error')}")
        if time.time() - t0 > max_wait:
            return {"id": pid, "status": status or "necunoscut",
                    "warning": "TikTok încă procesează; postarea apare în aplicație când termină"}
        time.sleep(poll)
