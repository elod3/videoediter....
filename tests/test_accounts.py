"""Conturi, izolare între clienți, credite și plăți Stripe (VEDIT_AUTH=on)."""
import hashlib
import hmac
import json
import os
import stat
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from test_api import FAKE_CLAUDE, upload, wait_job  # noqa: E402

from vedit.api import auth as accounts  # noqa: E402
from vedit.api.app import create_app  # noqa: E402
from vedit.api.runners import ClaudeCodeRunner, ScriptedRunner  # noqa: E402

WHSEC = "whsec_test"
PACKS = [{"id": "starter", "credits": 30, "price_id": "price_123", "label": "30 de minute"},
         {"id": "broken", "credits": 5, "price_id": "price_bad"}]


@pytest.fixture
def app(vhome, monkeypatch):
    monkeypatch.setenv("VEDIT_AUTH", "on")
    monkeypatch.delenv("VEDIT_FREE_CREDITS", raising=False)
    monkeypatch.delenv("VEDIT_API_TOKEN", raising=False)
    monkeypatch.setenv("VEDIT_PACKS", json.dumps(PACKS))
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", WHSEC)
    accounts.limiter.fails.clear()
    return create_app(ScriptedRunner())


def client(app):
    return TestClient(app)


def register(c, email="ana@example.com", password="parola-buna"):
    r = c.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_register_login_logout_and_token_transports(app):
    with client(app) as c:
        assert c.get("/api/health").json()["accounts"] is True
        assert c.get("/api/projects").status_code == 401
        assert c.get("/api/me").status_code == 401

        assert c.post("/api/auth/register", json={"email": "nu-e-email", "password": "parola-buna"}).status_code == 400
        assert c.post("/api/auth/register", json={"email": "a@b.ro", "password": "scurta"}).status_code == 400
        r = c.post("/api/auth/register", json={"email": "  Ana@Example.com ", "password": "parola-buna"})
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["email"] == "ana@example.com" and body["user"]["credits"] == 3
        sc = r.headers["set-cookie"]
        assert "vedit_session=" in sc and "HttpOnly" in sc and "samesite=lax" in sc.lower()
        assert c.post("/api/auth/register", json={"email": "ANA@example.com", "password": "altaparola"}).status_code == 409

        tok = body["token"]
        assert c.get("/api/me").json()["email"] == "ana@example.com"            # cookie
        c.cookies.clear()
        assert c.get("/api/me").status_code == 401
        assert c.get("/api/me", headers=bearer(tok)).json()["credits"] == 3     # Bearer
        assert c.get(f"/api/me?token={tok}").status_code == 200                 # ?token= (video / SSE)
        assert c.get("/api/me", headers=bearer("gresit")).status_code == 401
        led = c.get("/api/me/ledger", headers=bearer(tok)).json()
        assert [(e["delta"], e["reason"]) for e in led] == [(3, "credite gratuite la înregistrare")]

        assert c.post("/api/auth/login", json={"email": "ana@example.com", "password": "gresita1"}).status_code == 401
        assert c.post("/api/auth/login", json={"email": "nimeni@example.com", "password": "gresita1"}).status_code == 401
        r = c.post("/api/auth/login", json={"email": "ANA@example.com", "password": "parola-buna"})
        assert r.status_code == 200 and r.json()["token"] != tok
        assert c.get("/api/me").status_code == 200                              # cookie nou
        tok2 = r.json()["token"]
        assert c.post("/api/auth/logout").json()["ok"]
        assert c.get("/api/me", headers=bearer(tok2)).status_code == 401       # sesiunea e ștearsă din DB
        c.cookies.clear()
        assert c.get("/api/me", headers=bearer(tok)).status_code == 200        # cealaltă sesiune rămâne


def test_login_rate_limit(app):
    with client(app) as c:
        register(c)
        for _ in range(10):
            assert c.post("/api/auth/login", json={"email": "ana@example.com", "password": "gresita!"}).status_code == 401
        r = c.post("/api/auth/login", json={"email": "ana@example.com", "password": "parola-buna"})
        assert r.status_code == 429  # blocat chiar și cu parola corectă
        other = c.post("/api/auth/login", json={"email": "alt@example.com", "password": "gresita!"})
        assert other.status_code == 401  # limita e per IP + email


def test_password_hash_is_salted_scrypt():
    a, b = accounts.hash_password("parola-buna"), accounts.hash_password("parola-buna")
    assert a != b and a.startswith("scrypt$")
    assert accounts.check_password("parola-buna", a) and not accounts.check_password("parola-rea", a)


def test_tenant_isolation(app, talking_video):
    with client(app) as a, client(app) as b:
        ua = register(a, "a@example.com")
        register(b, "b@example.com")
        assert a.post("/api/projects", json={"name": "alpha"}).json()["name"] == "alpha"
        assert (accounts_home() / f"u{ua['user']['id']}-alpha" / "project.json").exists()
        proj = upload(a, "alpha", talking_video).json()["project"]
        assert proj["name"] == "alpha" and proj["assets"][0]["thumb"].startswith("/api/projects/alpha/")
        job = a.post("/api/projects/alpha/jobs", json={"prompt": "taie pauzele"}).json()
        assert job["project"] == "alpha"
        assert app.state.db.job(job["id"])["project"] == f"u{ua['user']['id']}-alpha"  # pe disc: namespaced
        assert wait_job(a, job["id"])["status"] == "done"
        proj = a.get("/api/projects/alpha").json()
        media = [proj["assets"][0]["thumb"], "/api/projects/alpha/assets/a0/file", proj["renders"][0]["url"]]
        assert all(a.get(u).status_code == 200 for u in media)

        # B nu vede nimic din A: 404 (nu 403), inclusiv joburi, SSE și media
        assert b.get("/api/projects").json() == []
        assert b.get("/api/projects/alpha").status_code == 404
        assert all(b.get(u).status_code == 404 for u in media)
        assert b.get(f"/api/jobs/{job['id']}").status_code == 404
        assert b.get(f"/api/jobs/{job['id']}/events").status_code == 404
        assert b.post(f"/api/jobs/{job['id']}/cancel").status_code == 404
        assert b.get("/api/projects/alpha/jobs").status_code == 404
        assert b.post("/api/projects/alpha/render", json={}).status_code == 404
        assert b.delete("/api/projects/alpha").status_code == 404
        # același nume public la B = alt proiect, gol
        assert b.post("/api/projects", json={"name": "alpha"}).json()["assets"] == []
        assert [p["name"] for p in b.get("/api/projects").json()] == ["alpha"]
        assert len(a.get("/api/projects/alpha").json()["assets"]) == 1
        assert a.post("/api/projects", json={"name": "alpha"}).status_code == 409
        assert a.post("/api/projects", json={"name": "x" * 62}).status_code == 400  # u1- + 62 > 64
        assert a.post("/api/projects", json={"name": "x" * 61}).status_code == 200
        assert [j["project"] for j in a.get("/api/projects/alpha/jobs").json()] == ["alpha"]
        sse = a.get(f"/api/jobs/{job['id']}/events").text
        assert "event: done" in sse
        assert a.delete("/api/projects/alpha").json()["ok"]
        assert len(b.get("/api/projects").json()) == 1


def accounts_home():
    from vedit.project import home

    return home()


def test_credits_charge_on_final_and_402(app, talking_video, monkeypatch):
    monkeypatch.setenv("VEDIT_FREE_CREDITS", "2")
    with client(app) as c:
        register(c)
        c.post("/api/projects", json={"name": "p"})
        upload(c, "p", talking_video)
        # agent fără export final: gratuit
        j = wait_job(c, c.post("/api/projects/p/jobs", json={"prompt": "taie pauzele"}).json()["id"])
        assert j["status"] == "done" and c.get("/api/me").json()["credits"] == 2
        # render final (~5 s) => 1 minut început => 1 credit
        rj = c.post("/api/projects/p/render", json={"final": True}).json()
        done = wait_job(c, rj["id"])
        assert done["status"] == "done"
        assert any("1 credit consumat" in e["data"].get("message", "") for e in done["events"])
        assert c.get("/api/me").json()["credits"] == 1
        # agent care exportă final (mtime nou pe renders/final.mp4) => încă 1 credit
        aj = wait_job(c, c.post("/api/projects/p/jobs", json={"prompt": "export final"}).json()["id"])
        assert aj["status"] == "done", aj
        assert c.get("/api/me").json()["credits"] == 0
        led = c.get("/api/me/ledger").json()
        assert [(e["delta"], e["job"]) for e in led[:2]] == [(-1, aj["id"]), (-1, rj["id"])]
        assert led[0]["reason"].startswith("export final")
        # fără credite: agent și final refuzate cu 402, preview-ul rămâne gratuit
        r = c.post("/api/projects/p/jobs", json={"prompt": "mai scurt"})
        assert r.status_code == 402 and "credite" in r.json()["detail"]
        assert c.post("/api/projects/p/render", json={"final": True}).status_code == 402
        pj = c.post("/api/projects/p/render", json={"final": False})
        assert pj.status_code == 200 and wait_job(c, pj.json()["id"])["status"] == "done"
        assert c.get("/api/me").json()["credits"] == 0


def test_credits_never_below_zero(app):
    db = app.state.db
    u = db.create_user("x@example.com", accounts.hash_password("parola-buna"), 1)
    assert db.add_credits(u["id"], -5, "export final", "j1") == -1
    assert db.user(u["id"])["credits"] == 0
    assert db.add_credits(u["id"], -1, "export final", "j2") == 0
    assert db.user(u["id"])["credits"] == 0
    assert accounts.minutes(5) == 1 and accounts.minutes(60) == 1 and accounts.minutes(61) == 2


def test_agent_lock_uses_storage_name(app, vhome, tmp_path, monkeypatch, talking_video):
    fake = tmp_path / "claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("VEDIT_CLAUDE_BIN", str(fake))
    monkeypatch.setenv("FAKE_LOG", str(log))
    with TestClient(create_app(ClaudeCodeRunner())) as c:
        uid = register(c)["user"]["id"]
        c.post("/api/projects", json={"name": "cc"})
        upload(c, "cc", talking_video)
        j = wait_job(c, c.post("/api/projects/cc/jobs", json={"prompt": "taie pauzele"}).json()["id"])
        assert j["status"] == "done", j
    a1 = json.loads(log.read_text().splitlines()[0])["argv"]
    env = json.loads(open(a1[a1.index("--mcp-config") + 1]).read())["mcpServers"]["vedit"]["env"]
    assert env["VEDIT_PROJECT_LOCK"] == f"u{uid}-cc"
    assert a1[a1.index("--add-dir") + 1] == os.path.realpath(os.path.join(os.environ["VEDIT_HOME"], f"u{uid}-cc"))


# ---------------- Stripe ----------------
@pytest.fixture
def fake_stripe(monkeypatch):
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            form = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
            seen.append({"path": self.path, "auth": self.headers.get("Authorization"),
                         "ctype": self.headers.get("Content-Type"), "form": {k: v[0] for k, v in form.items()}})
            if form["line_items[0][price]"][0] == "price_bad":
                code, obj = 400, {"error": {"message": "No such price: 'price_bad'"}}
            else:
                code, obj = 200, {"id": "cs_test_1", "object": "checkout.session",
                                  "url": "https://checkout.stripe.com/c/pay/cs_test_1"}
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(k, "127.0.0.1,localhost")
    monkeypatch.setenv("VEDIT_STRIPE_BASE", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("VEDIT_PUBLIC_URL", "https://vedit.example")
    yield seen
    srv.shutdown()


def test_packs_and_checkout(app, fake_stripe):
    with client(app) as c:
        packs = c.get("/api/billing/packs").json()  # public, fără price_id
        assert packs == [{"id": "starter", "credits": 30, "label": "30 de minute", "price": ""},
                         {"id": "broken", "credits": 5, "label": "5 minute", "price": ""}]
        assert c.post("/api/billing/checkout", json={"pack": "starter"}).status_code == 401
        r = c.post("/api/auth/register", json={"email": "ana@example.com", "password": "parola-buna"})
        assert "secure" in r.headers["set-cookie"].lower()  # VEDIT_PUBLIC_URL e https => cookie Secure
        uid, h = r.json()["user"]["id"], bearer(r.json()["token"])  # testserver e http: trimitem Bearer
        assert c.post("/api/billing/checkout", json={"pack": "nu-exista"}, headers=h).status_code == 404
        r = c.post("/api/billing/checkout", json={"pack": "starter"}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["url"] == "https://checkout.stripe.com/c/pay/cs_test_1"
        req = fake_stripe[-1]
        assert req["path"] == "/v1/checkout/sessions" and req["auth"] == "Bearer sk_test_123"
        assert req["ctype"] == "application/x-www-form-urlencoded"
        f = req["form"]
        assert f["mode"] == "payment" and f["line_items[0][price]"] == "price_123" and f["line_items[0][quantity]"] == "1"
        assert f["client_reference_id"] == str(uid) and f["metadata[user_id]"] == str(uid)
        assert f["metadata[credits]"] == "30" and f["metadata[pack]"] == "starter"
        assert f["success_url"].startswith("https://vedit.example/") and "{CHECKOUT_SESSION_ID}" in f["success_url"]
        assert f["cancel_url"].startswith("https://vedit.example/")
        bad = c.post("/api/billing/checkout", json={"pack": "broken"}, headers=h)
        assert bad.status_code == 502 and "No such price" in bad.json()["detail"]


def signed(payload: bytes, t: int | None = None, secret: str = WHSEC) -> dict:
    t = int(time.time()) if t is None else t
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return {"Stripe-Signature": f"t={t},v1={sig}", "Content-Type": "application/json"}


def event(uid, eid="evt_1", status="paid", type_="checkout.session.completed"):
    return json.dumps({"id": eid, "type": type_, "data": {"object": {
        "id": "cs_test_1", "object": "checkout.session", "payment_status": status, "client_reference_id": str(uid),
        "metadata": {"user_id": str(uid), "credits": "30", "pack": "starter"}}}}).encode()


def test_webhook_signature_and_idempotency(app):
    with client(app) as c:
        uid = register(c)["user"]["id"]
        c.cookies.clear()  # webhook-ul nu are cookie de sesiune
        body = event(uid)
        hook = "/api/billing/webhook"
        assert c.post(hook, content=body, headers={"Content-Type": "application/json"}).status_code == 400
        assert c.post(hook, content=body, headers=signed(body, secret="whsec_altul")).status_code == 400
        assert c.post(hook, content=body + b" ", headers=signed(body)).status_code == 400  # corp modificat
        old = c.post(hook, content=body, headers=signed(body, t=int(time.time()) - 301))
        assert old.status_code == 400 and "expirat" in old.json()["detail"]
        assert c.get("/api/me", headers=bearer("x")).status_code == 401
        db = app.state.db
        assert db.user(uid)["credits"] == 3

        ok = c.post(hook, content=body, headers=signed(body))
        assert ok.status_code == 200 and ok.json()["credited"] is True
        assert db.user(uid)["credits"] == 33
        again = c.post(hook, content=body, headers=signed(body))  # Stripe retrimite același eveniment
        assert again.status_code == 200 and again.json()["credited"] is False
        assert db.user(uid)["credits"] == 33
        led = db.ledger(uid)
        assert led[0]["delta"] == 30 and led[0]["job"] == "cs_test_1" and "starter" in led[0]["reason"]

        unpaid = event(uid, "evt_2", status="unpaid")
        assert c.post(hook, content=unpaid, headers=signed(unpaid)).json()["ignored"] is True
        other = event(uid, "evt_3", type_="payment_intent.created")
        assert c.post(hook, content=other, headers=signed(other)).json()["ignored"] is True
        late = event(uid, "evt_4", type_="checkout.session.async_payment_succeeded")
        assert c.post(hook, content=late, headers=signed(late)).json()["credited"] is True
        assert db.user(uid)["credits"] == 63
        # header cu mai multe semnături (rotația secretului): e destul una validă
        multi = event(uid, "evt_5")
        h = signed(multi)
        h["Stripe-Signature"] = h["Stripe-Signature"].replace("v1=", "v1=deadbeef,v1=") + ",v0=abc"
        assert c.post(hook, content=multi, headers=h).json()["credited"] is True


def test_auth_off_keeps_single_user_behaviour(vhome, monkeypatch):
    monkeypatch.delenv("VEDIT_AUTH", raising=False)
    with TestClient(create_app(ScriptedRunner())) as c:
        assert c.get("/api/health").json()["accounts"] is False
        assert c.post("/api/auth/register", json={"email": "a@b.ro", "password": "parola-buna"}).status_code == 404
        assert c.post("/api/projects", json={"name": "demo"}).json()["name"] == "demo"
        assert (vhome / "projects" / "demo" / "project.json").exists()


def test_exports_are_tenant_isolated(app, talking_video):
    """Rutele de export (subtitrări, thumbnail) respectă proprietarul, ca restul API-ului."""
    from vedit.project import Project
    from vedit.transcribe import Transcript, Word

    with client(app) as c:
        a = register(c, "a@example.com")["token"]
        b = register(c, "b@example.com")["token"]
        c.cookies.clear()
        assert c.post("/api/projects", json={"name": "film"}, headers=bearer(a)).status_code == 200
        with open(talking_video, "rb") as f:
            c.post("/api/projects/film/assets", files={"file": ("t.mp4", f, "video/mp4")}, headers=bearer(a))
        storage = next(p for p in os.listdir(os.environ["VEDIT_HOME"]) if p.endswith("-film"))
        p = Project(storage)
        p.add_clip("a0", 0, 4)
        p.set_transcript("a0", Transcript(words=[Word(i=0, start=0.2, end=0.8, text="secret")]))
        p.captions("a0", "classic_bottom")
        p.thumbnail_export(at=1.0)
        assert c.get("/api/projects/film/captions.srt", headers=bearer(a)).status_code == 200
        assert c.get("/api/projects/film/thumbnail.png", headers=bearer(a)).status_code == 200
        assert c.get("/api/projects/film/captions.srt", headers=bearer(b)).status_code == 404
        assert c.get("/api/projects/film/thumbnail.png", headers=bearer(b)).status_code == 404
        assert c.get("/api/projects/film/captions.vtt").status_code == 401


def test_any_full_resolution_render_is_charged(app, talking_video, monkeypatch):
    """Nu se ocolește plata cu alt nume de fișier: export_preset / render(name=...) la rezoluție finală se taxează,
    preview-urile (540p) nu."""
    from vedit.project import Project

    class Exporter:
        name = "exporter"

        def run(self, project, prompt, emit, cancel, session=None, allow_generation=False):
            p = Project(project)
            if prompt == "preview":
                p.render(preview=True, name="schita")
            else:
                p.render(preview=False, name="tiktok")
            return "gata", None

    monkeypatch.setenv("VEDIT_FREE_CREDITS", "5")
    with client(app) as c:
        register(c)
        c.post("/api/projects", json={"name": "p"})
        upload(c, "p", talking_video)
        app.state.worker.runner = Exporter()
        storage = next(p for p in os.listdir(os.environ["VEDIT_HOME"]) if p.endswith("-p"))
        Project(storage).add_clip("a0", 0, 4)
        j = wait_job(c, c.post("/api/projects/p/jobs", json={"prompt": "preview"}).json()["id"])
        assert j["status"] == "done" and c.get("/api/me").json()["credits"] == 5
        j = wait_job(c, c.post("/api/projects/p/jobs", json={"prompt": "export"}).json()["id"])
        assert j["status"] == "done", j
        assert c.get("/api/me").json()["credits"] == 4
        assert any("credit consumat" in e["data"].get("message", "") for e in j["events"])


def test_agent_job_and_project_caps(app, talking_video, monkeypatch):
    monkeypatch.setenv("VEDIT_FREE_CREDITS", "5")
    monkeypatch.setenv("VEDIT_MAX_AGENT_JOBS_PER_DAY", "1")
    monkeypatch.setenv("VEDIT_MAX_PROJECTS", "1")
    with client(app) as c:
        register(c)
        assert c.post("/api/projects", json={"name": "p"}).status_code == 200
        r = c.post("/api/projects", json={"name": "q"})
        assert r.status_code == 409 and "maximul" in r.json()["detail"]
        upload(c, "p", talking_video)
        wait_job(c, c.post("/api/projects/p/jobs", json={"prompt": "taie pauzele"}).json()["id"])
        r = c.post("/api/projects/p/jobs", json={"prompt": "încă o dată"})
        assert r.status_code == 429 and "limita" in r.json()["detail"]


def test_admin_cli(app, capsys):
    from vedit.api import admin

    with client(app) as c:
        register(c, "ana@example.com")
    assert admin.main(["credits", "ana@example.com", "7", "bonus"]) == 0
    assert "+7" in capsys.readouterr().out
    assert admin.main(["reset-password", "ana@example.com"]) == 0
    temp = capsys.readouterr().out.split(": ")[1].split()[0]
    with client(app) as c:
        assert c.get("/api/me").status_code == 401  # sesiunea veche închisă
        assert c.post("/api/auth/login", json={"email": "ana@example.com", "password": "parola-buna"}).status_code == 401
        r = c.post("/api/auth/login", json={"email": "ana@example.com", "password": temp})
        assert r.status_code == 200 and r.json()["user"]["credits"] == 10
    assert admin.main(["credits", "nimeni@example.com", "1"]) == 1
