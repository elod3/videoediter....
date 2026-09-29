"""Plăți Stripe pentru pachete de credite (doar urllib, fără SDK).

Env:
  VEDIT_PACKS            JSON: [{"id": "starter", "credits": 30, "price_id": "price_…", "label": "30 de minute"}]
  STRIPE_SECRET_KEY      cheia secretă (sk_…)
  STRIPE_WEBHOOK_SECRET  secretul endpoint-ului de webhook (whsec_…)
  VEDIT_PUBLIC_URL       adresa site-ului, pentru întoarcerea din Checkout (implicit http://127.0.0.1:8000)
  VEDIT_STRIPE_BASE      alt API decât https://api.stripe.com (teste)

Flux: /checkout creează o sesiune Checkout cu user_id + credite în metadata; Stripe trimite
`checkout.session.completed` la /webhook (semnat), iar creditele se adaugă o singură dată per eveniment.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .auth import current_user

TOLERANCE = 300  # secunde, ca în librăriile Stripe (protecție la replay)
PAID_EVENTS = ("checkout.session.completed", "checkout.session.async_payment_succeeded")

router = APIRouter()


def packs() -> list[dict]:
    try:
        raw = json.loads(os.environ.get("VEDIT_PACKS", "[]") or "[]")
    except json.JSONDecodeError:
        return []
    return [p for p in raw if isinstance(p, dict) and p.get("id") and p.get("price_id") and int(p.get("credits", 0)) > 0]


def verify_signature(payload: bytes, header: str, secret: str, now: float | None = None) -> None:
    """Verificarea manuală din documentația Stripe: t=…,v1=… ; v1 = HMAC-SHA256(secret, f"{t}.{corp}")."""
    t, sigs = None, []
    for item in (header or "").split(","):
        k, _, v = item.strip().partition("=")
        if k == "t":
            t = v
        elif k == "v1":
            sigs.append(v)
    try:
        ts = int(t or "")
    except ValueError:
        raise ValueError("semnătură Stripe lipsă sau malformată")
    if not sigs:
        raise ValueError("semnătură Stripe lipsă sau malformată")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise ValueError("semnătură Stripe invalidă")
    if abs((now or time.time()) - ts) > TOLERANCE:
        raise ValueError("semnătură Stripe expirată")


def _stripe_post(path: str, fields: list[tuple[str, str]]) -> dict:
    key = os.environ.get("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(503, "plățile nu sunt configurate pe acest server")
    base = os.environ.get("VEDIT_STRIPE_BASE", "https://api.stripe.com").rstrip("/")
    req = urllib.request.Request(f"{base}{path}", data=urllib.parse.urlencode(fields).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read())["error"]["message"]
        except Exception:
            msg = f"HTTP {e.code}"
        raise HTTPException(502, f"Stripe a refuzat plata: {msg}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise HTTPException(502, f"Stripe nu răspunde: {e}")


class CheckoutReq(BaseModel):
    pack: str


@router.get("/api/billing/packs")
def list_packs():
    return [{"id": p["id"], "credits": int(p["credits"]), "label": p.get("label") or f"{p['credits']} minute"}
            for p in packs()]


@router.post("/api/billing/checkout")
def checkout(body: CheckoutReq, request: Request):
    user = current_user(request)
    pack = next((p for p in packs() if p["id"] == body.pack), None)
    if pack is None:
        raise HTTPException(404, "pachet inexistent")
    public = os.environ.get("VEDIT_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
    s = _stripe_post("/v1/checkout/sessions", [
        ("mode", "payment"),
        ("line_items[0][price]", pack["price_id"]),
        ("line_items[0][quantity]", "1"),
        ("success_url", f"{public}/?plata=ok&session_id={{CHECKOUT_SESSION_ID}}"),
        ("cancel_url", f"{public}/?plata=anulata"),
        ("client_reference_id", str(user["id"])),
        ("customer_email", user["email"]),
        ("metadata[user_id]", str(user["id"])),
        ("metadata[credits]", str(int(pack["credits"]))),
        ("metadata[pack]", pack["id"]),
    ])
    if not s.get("url"):
        raise HTTPException(502, "Stripe nu a întors adresa de plată")
    return {"url": s["url"], "id": s.get("id")}


@router.post("/api/billing/webhook")
async def webhook(request: Request):
    """Neautentificat, dar acceptat doar cu semnătura Stripe validă."""
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "webhook-ul Stripe nu e configurat")
    payload = await request.body()
    try:
        verify_signature(payload, request.headers.get("stripe-signature", ""), secret)
        event = json.loads(payload)
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, str(e))
    obj = (event.get("data") or {}).get("object") or {}
    if event.get("type") not in PAID_EVENTS or obj.get("payment_status") != "paid":
        return {"ok": True, "ignored": True}
    meta = obj.get("metadata") or {}
    try:
        uid, credits = int(meta["user_id"]), int(meta["credits"])
    except (KeyError, TypeError, ValueError):
        return {"ok": True, "ignored": True}
    db = request.app.state.db
    if credits <= 0 or not event.get("id") or not db.user(uid):
        return {"ok": True, "ignored": True}
    done = db.credit_event(str(event["id"]), uid, credits, f"cumpărare pachet {meta.get('pack', '?')}", obj.get("id", ""))
    return {"ok": True, "credited": done}
