"""HTTP minimal (doar biblioteca standard) și login OAuth prin browser, cu callback pe localhost.

Toate adresele platformelor trec prin `base_url(...)`, ca testele să poată porni un server local care
imită API-ul (VEDIT_PUBLISH_FAKE=http://127.0.0.1:port). În producție variabila nu există.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

REAL = {
    "google_auth": "https://accounts.google.com",
    "google_token": "https://oauth2.googleapis.com",
    "youtube": "https://www.googleapis.com",
    "facebook_dialog": "https://www.facebook.com",
    "graph": "https://graph.facebook.com",
    "rupload": "https://rupload.facebook.com",
    "tiktok_auth": "https://www.tiktok.com",
    "tiktok": "https://open.tiktokapis.com",
}
META_VERSION = os.environ.get("VEDIT_META_API_VERSION", "v25.0")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """YouTube răspunde 308 la fiecare bucată urcată: nu e redirect, e „continuă”. Îl lăsăm să ajungă la noi."""

    def redirect_request(self, *a, **kw):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


class ApiError(Exception):
    def __init__(self, status: int, body: str, url: str = ""):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status} de la {urllib.parse.urlsplit(url).netloc}: {body[:400]}")


def base_url(name: str) -> str:
    fake = os.environ.get("VEDIT_PUBLISH_FAKE")
    return fake.rstrip("/") + "/" + name if fake else REAL[name]


def request(method: str, url: str, *, params: dict | None = None, data: bytes | None = None,
            form: dict | None = None, json_body: dict | None = None, headers: dict | None = None,
            timeout: float = 120) -> tuple[int, dict, dict]:
    """(status, json, headers). Ridică ApiError pe status >= 400."""
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        h.setdefault("Content-Type", "application/json; charset=UTF-8")
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        with _opener.open(req, timeout=timeout) as r:
            raw = r.read()
            status, rh = r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace"), url) from None
    try:
        body = json.loads(raw) if raw else {}
    except ValueError:
        body = {"_raw": raw.decode("utf-8", "replace")[:2000]}
    return status, body, rh


# ---------------- PKCE ----------------
def pkce_pair(encoding: str = "base64url") -> tuple[str, str]:
    """(verifier, challenge). Google: base64url; TikTok desktop: hex (așa scrie în documentația lor)."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    verifier = "".join(secrets.choice(alphabet) for _ in range(64))
    digest = hashlib.sha256(verifier.encode()).digest()
    if encoding == "hex":
        return verifier, digest.hex()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


# ---------------- callback pe localhost ----------------
class _Catcher(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        type(self).result = {k: v[0] for k, v in q.items()}
        ok = "code" in q
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        msg = "Cont conectat. Poți închide fereastra." if ok else "Conectarea n-a mers. Uită-te în terminal."
        self.wfile.write(f"<!doctype html><meta charset=utf-8><p style='font:18px sans-serif'>{msg}".encode())

    def log_message(self, *a):
        pass


def browser_login(auth_url_for, port: int = 8765, path: str = "/callback/", open_browser: bool = True,
                  timeout: float = 300) -> tuple[dict, str]:
    """Pornește un server pe 127.0.0.1:port, deschide browserul și așteaptă codul.

    `auth_url_for(redirect_uri, state)` construiește adresa de login. Întoarce (parametrii primiți, redirect_uri)."""
    state = secrets.token_urlsafe(16)
    srv = http.server.HTTPServer(("127.0.0.1", port), _Catcher)
    redirect = f"http://localhost:{port}{path}"
    url = auth_url_for(redirect, state)
    _Catcher.result = {}
    t = threading.Thread(target=srv.handle_request, daemon=True)
    srv.timeout = timeout
    t.start()
    print("\nDeschid browserul pentru conectare. Dacă nu se deschide, intră aici:\n" + url + "\n")
    if open_browser:
        webbrowser.open(url)
    t.join(timeout + 5)
    srv.server_close()
    got = _Catcher.result
    if not got:
        raise RuntimeError("n-a venit niciun răspuns de la platformă (timp expirat)")
    if got.get("state") != state:
        raise RuntimeError("răspunsul de la platformă nu se potrivește (state diferit): încearcă din nou")
    if "error" in got and "code" not in got:
        raise RuntimeError(f"platforma a refuzat: {got.get('error_description') or got.get('error')}")
    return got, redirect
