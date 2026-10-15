"""Meta (Facebook Login for Business): pagini de Facebook + conturile Instagram Business legate de ele.

O singură conectare dă tokenul de pagină. Cu el se publică:
  * Reels pe pagina de Facebook  (/{page}/video_reels: start -> upload pe rupload -> finish)
  * Reels pe Instagram           (/{ig}/media cu upload_type=resumable -> rupload -> status -> media_publish)
Upload-ul „resumable” din fișier local merge doar pe varianta cu Facebook Login (nu cu Instagram Login),
de-asta folosim graph.facebook.com și tokenul de pagină.
"""
from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

from .net import META_VERSION, base_url, browser_login, request

SCOPES = ",".join([
    "pages_show_list", "pages_read_engagement", "pages_manage_posts", "business_management",
    "instagram_basic", "instagram_content_publish",
])


def _g(path: str) -> str:
    return f"{base_url('graph')}/{META_VERSION}/{path.lstrip('/')}"


def connect(app: dict, open_browser: bool = True, choose=None) -> list[tuple[str, str, str, dict]]:
    """Login Facebook -> lista de conturi de salvat: (platformă, id, nume afișat, secrete).

    `choose(pages)` primește paginile găsite și întoarce indicii aleși (CLI-ul întreabă omul)."""
    def url(redirect, state):
        return f"{base_url('facebook_dialog')}/{META_VERSION}/dialog/oauth?" + urllib.parse.urlencode({
            "client_id": app["app_id"], "redirect_uri": redirect, "state": state,
            "scope": SCOPES, "response_type": "code"})

    got, redirect = browser_login(url, open_browser=open_browser)
    _, short, _ = request("GET", _g("oauth/access_token"), params={
        "client_id": app["app_id"], "client_secret": app["app_secret"], "redirect_uri": redirect, "code": got["code"]})
    _, long_, _ = request("GET", _g("oauth/access_token"), params={
        "grant_type": "fb_exchange_token", "client_id": app["app_id"], "client_secret": app["app_secret"],
        "fb_exchange_token": short["access_token"]})
    _, pages, _ = request("GET", _g("me/accounts"), params={
        "fields": "id,name,access_token,instagram_business_account{id,username}",
        "access_token": long_["access_token"]})
    pages = pages.get("data") or []
    if not pages:
        raise RuntimeError("contul de Facebook nu administrează nicio pagină (sau n-ai bifat pagina la conectare)")
    picked = choose(pages) if choose else range(len(pages))
    out = []
    for i in picked:
        p = pages[i]
        out.append(("facebook", p["id"], p["name"], {"page_token": p["access_token"]}))
        ig = p.get("instagram_business_account")
        if ig:
            out.append(("instagram", ig["id"], "@" + ig.get("username", ig["id"]),
                        {"page_token": p["access_token"], "page_id": p["id"]}))
    return out


def _rupload(url: str, token: str, video: Path) -> None:
    size = video.stat().st_size
    _, body, _ = request("POST", url, data=video.read_bytes(), timeout=1800, headers={
        "Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size),
        "Content-Type": "application/octet-stream"})
    if body and body.get("success") is False:
        raise RuntimeError(f"upload refuzat de Meta: {body}")


def publish_instagram(sec: dict, ig_id: str, pkg, video: Path, log, poll: float = 15, max_wait: float = 900) -> dict:
    token = sec["page_token"]
    params = {"media_type": "REELS", "upload_type": "resumable", "caption": pkg.full_text(),
              "share_to_feed": "true" if pkg.options.get("share_to_feed", True) else "false",
              "access_token": token}
    if pkg.cover_at_ms >= 0:
        params["thumb_offset"] = str(pkg.cover_at_ms)
    if pkg.options.get("trial"):
        params["trial_params"] = '{"graduation_strategy":"MANUAL"}'
    _, c, _ = request("POST", _g(f"{ig_id}/media"), form=params)
    cid = c["id"]
    up = c.get("uri") or f"{base_url('rupload')}/ig-api-upload/{META_VERSION}/{cid}"
    log("Instagram: urc clipul")
    _rupload(up, token, video)
    t0 = time.time()
    while True:
        _, st, _ = request("GET", _g(cid), params={"fields": "status_code,status", "access_token": token})
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram n-a procesat clipul: {st.get('status') or code}")
        if time.time() - t0 > max_wait:
            raise RuntimeError("Instagram procesează prea mult; încearcă publicarea din nou peste câteva minute")
        log("Instagram: procesează clipul...")
        time.sleep(poll)
    _, pub, _ = request("POST", _g(f"{ig_id}/media_publish"), form={"creation_id": cid, "access_token": token})
    mid = pub["id"]
    link = ""
    try:
        _, info, _ = request("GET", _g(mid), params={"fields": "permalink", "access_token": token})
        link = info.get("permalink", "")
    except Exception:
        pass
    return {"id": mid, "url": link}


def publish_facebook(sec: dict, page_id: str, pkg, video: Path, log) -> dict:
    token = sec["page_token"]
    _, s, _ = request("POST", _g(f"{page_id}/video_reels"), form={"upload_phase": "start", "access_token": token})
    vid = s["video_id"]
    log("Facebook: urc clipul")
    _rupload(s.get("upload_url") or f"{base_url('rupload')}/video-upload/{META_VERSION}/{vid}", token, video)
    fin = {"upload_phase": "finish", "video_id": vid, "description": pkg.full_text(), "access_token": token}
    if pkg.schedule_at:
        from .package import parse_time

        fin["video_state"] = "SCHEDULED"
        fin["scheduled_publish_time"] = str(int(parse_time(pkg.schedule_at).timestamp()))
    else:
        fin["video_state"] = "PUBLISHED"
    _, done, _ = request("POST", _g(f"{page_id}/video_reels"), form=fin)
    if not done.get("success", True):
        raise RuntimeError(f"Facebook n-a publicat: {done}")
    return {"id": vid, "url": f"https://www.facebook.com/reel/{vid}"}
