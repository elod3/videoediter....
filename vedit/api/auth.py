"""Conturi, sesiuni și credite (activ doar cu VEDIT_AUTH=on).

Env:
  VEDIT_AUTH           on | off (implicit off: un singur utilizator, ca înainte)
  VEDIT_FREE_CREDITS   credite la înregistrare (implicit 3)
  VEDIT_SESSION_DAYS   cât ține o sesiune (implicit 30 de zile)
  VEDIT_MAX_AGENT_JOBS_PER_DAY  cereri către agent per cont în 24 h (implicit 60; 0 = fără limită)
  VEDIT_MAX_PROJECTS   proiecte per cont (implicit 50; 0 = fără limită)

Token-ul de sesiune vine în JSON și într-un cookie HttpOnly; e acceptat ca `Authorization: Bearer`,
cookie sau `?token=` (pentru <video> și EventSource). În baza de date stă doar sha256 al lui.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..probe import probe

COOKIE = "vedit_session"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SCRYPT = (2 ** 14, 8, 1)  # n, r, p (~16 MB RAM per hash)
NO_CREDITS = "Nu mai ai credite. Cumpără un pachet de minute ca să continui."

router = APIRouter()


def enabled() -> bool:
    return os.environ.get("VEDIT_AUTH", "off").strip().lower() == "on"


# ---------- parole și token-uri ----------
def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = SCRYPT
    h = hashlib.scrypt(pw.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${h.hex()}"


def check_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=len(h) // 2)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), h)


_DUMMY = hash_password(secrets.token_hex(8))  # login pe email inexistent costă la fel (fără enumerare prin timp)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def request_token(request: Request) -> str:
    """Bearer, apoi cookie, apoi ?token= (media / SSE nu pot trimite header-e)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer ") and auth[7:].strip():
        return auth[7:].strip()
    return request.cookies.get(COOKIE) or request.query_params.get("token", "")


def session_user(db, request: Request) -> dict | None:
    tok = request_token(request)
    return db.login_user(token_hash(tok)) if tok else None


def current_user(request: Request) -> dict:
    """Utilizatorul pus de middleware în request.state (401 dacă lipsește)."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "neautorizat")
    return user


def public_user(u: dict) -> dict:
    return {"id": u["id"], "email": u["email"], "credits": u["credits"], "created": u["created"]}


# ---------- limită la încercările eșuate de login ----------
class _Limiter:
    def __init__(self, n: int = 10, window: float = 600):
        self.n, self.window = n, window
        self.fails: defaultdict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def _recent(self, key: str) -> deque:
        q = self.fails[key]
        while q and q[0] < time.time() - self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        with self.lock:
            return len(self._recent(key)) >= self.n

    def fail(self, key: str) -> None:
        with self.lock:
            self._recent(key).append(time.time())

    def reset(self, key: str) -> None:
        with self.lock:
            self.fails.pop(key, None)


limiter = _Limiter()


# ---------- credite ----------
def minutes(duration: float) -> int:
    """1 credit = 1 minut început: 5 s -> 1, 60 s -> 1, 61 s -> 2."""
    return max(1, math.ceil(round(duration, 3) / 60))


def charge_final(db, job: dict, path: Path) -> str | None:
    """Taxează exportul final al unui job (apelat de worker). Niciodată sub 0 credite."""
    uid = job.get("user_id")
    if not uid:
        return None
    dur = probe(str(path)).duration
    n = minutes(dur)
    what = "export final" if path.stem == "final" else f"export {path.stem}"
    applied = db.add_credits(uid, -n, f"{what} {dur:.1f} s ({n} min)", job["id"])
    return f"{what}: {-applied} {'credit consumat' if -applied == 1 else 'credite consumate'}"


def require_credits(user: dict, db) -> None:
    u = db.user(user["id"])
    if not u or u["credits"] <= 0:
        raise HTTPException(402, NO_CREDITS)


def limit_agent_jobs(user: dict, db) -> None:
    """Joburile de agent nu costă credite, dar costă operatorul (LLM, CPU): plafon pe 24 h per cont."""
    cap = int(os.environ.get("VEDIT_MAX_AGENT_JOBS_PER_DAY", "60"))
    if cap > 0 and db.user_jobs_since(user["id"], "agent", time.time() - 86400) >= cap:
        raise HTTPException(429, f"ai atins limita de {cap} cereri către agent în 24 de ore; "
                                 f"poți continua cu editarea manuală și exportul")


def limit_projects(user: dict, db) -> None:
    cap = int(os.environ.get("VEDIT_MAX_PROJECTS", "50"))
    if cap > 0 and len(db.user_projects(user["id"])) >= cap:
        raise HTTPException(409, f"ai {cap} proiecte, maximul pe cont; șterge unul vechi ca să creezi altul")


# ---------- rute ----------
class Credentials(BaseModel):
    email: str
    password: str


def _login_response(request: Request, response: Response, user: dict) -> dict:
    tok = secrets.token_urlsafe(32)
    days = float(os.environ.get("VEDIT_SESSION_DAYS", "30"))
    request.app.state.db.create_login(token_hash(tok), user["id"], time.time() + days * 86400)
    secure = os.environ.get("VEDIT_PUBLIC_URL", "").startswith("https://")
    response.set_cookie(COOKIE, tok, max_age=int(days * 86400), httponly=True, samesite="lax", secure=secure, path="/")
    return {"token": tok, "user": public_user(user)}


@router.post("/api/auth/register")
def register(body: Credentials, request: Request, response: Response):
    email = body.email.strip().lower()
    if len(email) > 254 or not EMAIL.match(email):
        raise HTTPException(400, "adresă de email invalidă")
    if not 8 <= len(body.password) <= 256:
        raise HTTPException(400, "parola trebuie să aibă cel puțin 8 caractere")
    free = max(0, int(os.environ.get("VEDIT_FREE_CREDITS", "3")))
    user = request.app.state.db.create_user(email, hash_password(body.password), free)
    if user is None:
        raise HTTPException(409, "există deja un cont cu acest email")
    return _login_response(request, response, user)


@router.post("/api/auth/login")
def login(body: Credentials, request: Request, response: Response):
    email = body.email.strip().lower()
    key = f"{request.client.host if request.client else '?'}|{email}"
    if limiter.blocked(key):
        raise HTTPException(429, "prea multe încercări greșite; încearcă din nou peste câteva minute")
    user = request.app.state.db.user_by_email(email)
    if not check_password(body.password[:256], user["pw"] if user else _DUMMY) or not user:
        limiter.fail(key)
        raise HTTPException(401, "email sau parolă greșită")
    limiter.reset(key)
    return _login_response(request, response, user)


class ForgotReq(BaseModel):
    email: str


class ResetReq(BaseModel):
    token: str
    password: str


@router.post("/api/auth/forgot")
def forgot(body: ForgotReq, request: Request):
    """Trimite linkul de resetare. Răspunsul e același dacă emailul există sau nu (fără enumerare de conturi)."""
    from . import mail

    if not mail.enabled():
        raise HTTPException(503, "resetarea prin email nu e configurată pe acest server; scrie-ne și te ajutăm")
    email = body.email.strip().lower()
    key = f"forgot|{request.client.host if request.client else '?'}"
    if limiter.blocked(key):
        raise HTTPException(429, "prea multe cereri; încearcă din nou peste câteva minute")
    limiter.fail(key)  # fiecare cerere consumă din plafon (max 10 / 10 min per IP)
    user = request.app.state.db.user_by_email(email)
    if user:
        tok = secrets.token_urlsafe(32)
        request.app.state.db.create_reset(token_hash(tok), user["id"], time.time() + 3600)
        public = os.environ.get("VEDIT_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
        try:
            mail.send(email, "Resetarea parolei vedit",
                      f"Ai cerut o parolă nouă pentru contul vedit.\n\nDeschide linkul (valabil o oră):\n"
                      f"{public}/#/reset/{tok}\n\nDacă nu ai cerut tu, ignoră acest email; parola rămâne aceeași.")
        except Exception as e:  # noqa: BLE001 (nu dezvăluim dacă contul există: eroarea merge doar în log)
            import logging

            logging.getLogger("vedit").warning("email de resetare netrimis: %s", e)
    return {"ok": True, "message": "Dacă există un cont cu acest email, ți-am trimis un link de resetare."}


@router.post("/api/auth/reset")
def reset(body: ResetReq, request: Request, response: Response):
    if not 8 <= len(body.password) <= 256:
        raise HTTPException(400, "parola trebuie să aibă cel puțin 8 caractere")
    user = request.app.state.db.use_reset(token_hash(body.token.strip()), hash_password(body.password))
    if not user:
        raise HTTPException(400, "linkul de resetare e invalid sau a expirat; cere unul nou")
    return _login_response(request, response, user)


@router.post("/api/auth/logout")
def logout(request: Request, response: Response):
    if tok := request_token(request):
        request.app.state.db.delete_login(token_hash(tok))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/api/me")
def me(request: Request):
    u = request.app.state.db.user(current_user(request)["id"])
    return public_user(u)


@router.get("/api/me/ledger")
def my_ledger(request: Request, limit: int = 50):
    return request.app.state.db.ledger(current_user(request)["id"], max(1, min(limit, 200)))
