"""Publicarea: seiful, separarea clienților, consimțământul și fluxul complet pe un API fals local.

Serverul fals imită endpoint-urile reale (aceleași căi, aceleași coduri: 308 la YouTube, 206/201 la TikTok,
rupload la Meta), ca să verificăm că fiecare octet ajunge și că headerele sunt cele cerute de platforme.
"""
import json
import os
import shutil
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("cryptography")

from vedit import guard
from vedit.project import Project
from vedit.publish import service, tiktok
from vedit.publish.package import PostPackage, norm_hashtags, validate
from vedit.publish.vault import Vault, VaultError

PASS = "o fraza lunga de recuperare"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("VEDIT_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.setenv("VEDIT_VAULT_KEY_FILE", str(tmp_path / "vault.key"))
    monkeypatch.delenv("VEDIT_ALLOW_PUBLISH", raising=False)
    monkeypatch.delenv("VEDIT_PROJECT_LOCK", raising=False)
    v = Vault()
    v.init(PASS)
    return v


@pytest.fixture
def project(vhome, talking_video):
    p = Project("rares-reel")
    p.add_asset(talking_video)
    (p.dir / "renders").mkdir(exist_ok=True)
    shutil.copy(talking_video, p.dir / "renders" / "reels.mp4")
    Path(p.dir / "renders" / "thumb.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    return p


def setup_clients(v: Vault):
    v.add_client("service-rares", "Service Rareș")
    v.add_client("clinica-ana", "Clinica Ana")
    v.put_account("service-rares", "youtube", "UC_RARES", "Service Rareș", {"refresh_token": "refresh-RARES-0f9c2a7d",
                  "access_token": "a1", "expires": 9_999_999_999})
    v.put_account("service-rares", "instagram", "IG_RARES", "@service.rares", {"page_token": "pt-rares", "page_id": "PG_R"})
    v.put_account("service-rares", "facebook", "PG_R", "Service Rareș", {"page_token": "pt-rares"})
    v.put_account("service-rares", "tiktok", "TT_RARES", "rares.tt", {"access_token": "tt1", "refresh_token": "tr",
                  "expires": 9_999_999_999, "refresh_expires": 9_999_999_999})
    v.put_account("clinica-ana", "youtube", "UC_ANA", "Clinica Ana", {"refresh_token": "r2", "access_token": "a2",
                  "expires": 9_999_999_999})
    v.set_app("google", {"client_id": "gid", "client_secret": "google-secret-x"})
    v.set_app("tiktok", {"client_key": "tk", "client_secret": "ts"})
    v.set_app("meta", {"app_id": "mid", "app_secret": "ms"})


# ---------------- seiful ----------------
def test_vault_encrypts_and_restores_with_passphrase(vault, tmp_path):
    setup_clients(vault)
    raw = (vault.root / "clients" / "service-rares.enc").read_bytes()
    assert b"pt-rares" not in raw and b"refresh-RARES" not in raw     # tokenurile nu stau în clar
    assert b"google-secret-x" not in (vault.root / "apps.enc").read_bytes()
    assert stat.S_IMODE(os.stat(vault.keyfile).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(vault.root / "clients" / "service-rares.enc").st_mode) == 0o600
    # laptopul formatat: rămâne doar folderul vault/ (backup-ul), fără vault.key
    vault.keyfile.unlink()
    with pytest.raises(VaultError, match="blocat"):
        vault.secrets_for("service-rares", "youtube:UC_RARES")
    with pytest.raises(VaultError, match="parola"):
        vault.unlock_with_passphrase("parola gresita de tot")
    vault.unlock_with_passphrase(PASS)
    assert vault.secrets_for("service-rares", "youtube:UC_RARES")["refresh_token"] == "refresh-RARES-0f9c2a7d"
    assert vault.app("google")["client_secret"] == "google-secret-x"
    # fișierul unui client nu se poate pune în locul altuia (AAD legat de id)
    shutil.copy(vault.root / "clients" / "service-rares.enc", vault.root / "clients" / "clinica-ana.enc")
    with pytest.raises(VaultError):
        vault.secrets_for("clinica-ana", "youtube:UC_ANA")


def test_same_platform_account_cannot_belong_to_two_clients(vault):
    setup_clients(vault)
    with pytest.raises(VaultError, match="deja conectat la clientul service-rares"):
        vault.put_account("clinica-ana", "youtube", "UC_RARES", "Service Rareș", {})


# ---------------- separarea clienților ----------------
def test_project_posts_only_to_its_clients_accounts(vault, project):
    setup_clients(vault)
    with pytest.raises(VaultError, match="nu e legat de niciun client"):
        service.prepare(vault, project.s.name, project.dir, platform="youtube", video="renders/reels.mp4",
                        title="T", options={"made_for_kids": False})
    vault.link_project(project.s.name, "service-rares")
    pkg, _ = service.prepare(vault, project.s.name, project.dir, platform="youtube", video="renders/reels.mp4",
                             title="Plăcuțe noi", options={"made_for_kids": False})
    assert pkg.client == "service-rares" and pkg.account == "youtube:UC_RARES"
    # contul altui client nu se poate alege, nici după nume, nici după id
    for hint in ("Clinica Ana", "UC_ANA", "youtube:UC_ANA"):
        with pytest.raises(VaultError, match="nu e printre conturile"):
            service.prepare(vault, project.s.name, project.dir, platform="youtube", video="renders/reels.mp4",
                            title="T", account=hint, options={"made_for_kids": False})
    # proiectul nu trece la alt client fără unlink explicit
    with pytest.raises(VaultError, match="deja al clientului"):
        vault.link_project(project.s.name, "clinica-ana")


def test_publish_refuses_when_project_moved_to_another_client(vault, project, monkeypatch):
    setup_clients(vault)
    vault.link_project(project.s.name, "service-rares")
    pkg, _ = service.prepare(vault, project.s.name, project.dir, platform="youtube", video="renders/reels.mp4",
                             title="T", options={"made_for_kids": False})
    vault.unlink_project(project.s.name)
    vault.link_project(project.s.name, "clinica-ana")
    monkeypatch.setenv("VEDIT_ALLOW_PUBLISH", "1")
    with pytest.raises(guard.GuardError, match="clientul service-rares"):
        service.publish(vault, project.s.name, project.dir, pkg.id)


def test_video_must_be_inside_project(vault, project, tmp_path):
    setup_clients(vault)
    vault.link_project(project.s.name, "service-rares")
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"x")
    with pytest.raises(guard.GuardError):
        service.prepare(vault, project.s.name, project.dir, platform="tiktok", video=f"../../{outside.name}")


# ---------------- consimțământul ----------------
def test_publish_needs_human_consent_and_never_runs_in_site_jobs(vault, project, monkeypatch):
    setup_clients(vault)
    vault.link_project(project.s.name, "service-rares")
    pkg, _ = service.prepare(vault, project.s.name, project.dir, platform="tiktok", video="renders/reels.mp4",
                             title="test", privacy="private")
    with pytest.raises(guard.GuardError, match="VEDIT_ALLOW_PUBLISH"):
        service.publish(vault, project.s.name, project.dir, pkg.id)
    monkeypatch.setenv("VEDIT_ALLOW_PUBLISH", "1")
    monkeypatch.setenv("VEDIT_PROJECT_LOCK", project.s.name)      # job din site: refuzat chiar cu variabila
    with pytest.raises(guard.GuardError, match="site"):
        service.publish(vault, project.s.name, project.dir, pkg.id)


def test_site_jobs_do_not_even_see_the_publish_tool():
    from vedit.api import runners, toolhost

    assert "post_publish" in toolhost.HIDDEN_TOOLS
    assert "post_publish" not in {s["name"] for s in toolhost.specs()}
    assert "post_prepare" in {s["name"] for s in toolhost.specs()}
    src = Path(runners.__file__).read_text()
    assert '"mcp__vedit__post_publish"' in src
    env = runners.agent_env("p", allow_generation=False)
    assert "VEDIT_ALLOW_PUBLISH" not in env and env["VEDIT_PROJECT_LOCK"] == "p"


def test_mcp_publish_tool_refused_under_lock(vault, project, monkeypatch):
    from vedit import mcp_server

    setup_clients(vault)
    vault.link_project(project.s.name, "service-rares")
    guard.reset_budgets()
    monkeypatch.setenv("VEDIT_ALLOW_PUBLISH", "1")
    monkeypatch.setenv("VEDIT_PROJECT_LOCK", project.s.name)
    out = mcp_server.post_prepare(project.s.name, "tiktok", "renders/reels.mp4", title="x", privacy="private")
    pid = out.split()[1]
    assert mcp_server.post_publish(project.s.name, pid).startswith("REFUZAT")


# ---------------- validarea textelor ----------------
def mk(**kw):
    base = dict(id="1015-abcdef", project="p", client="c", account="youtube:x", platform="youtube",
                video="renders/a.mp4", title="Titlu", options={"made_for_kids": False})
    base.update(kw)
    return PostPackage(**base)


def test_platform_rules():
    assert norm_hashtags("frane, #service  #Frane auto") == ["#frane", "#service", "#auto"]
    with pytest.raises(ValueError, match="made_for_kids"):
        validate(mk(options={}))
    with pytest.raises(ValueError, match="100"):
        validate(mk(title="x" * 101))
    with pytest.raises(ValueError, match="cel mult 5"):
        validate(mk(platform="instagram", account="instagram:x", options={},
                    caption="ok", hashtags=[f"#t{i}" for i in range(6)]))
    with pytest.raises(ValueError, match="programare"):
        validate(mk(platform="instagram", account="instagram:x", options={}, schedule_at="2030-01-01T10:00:00+02:00"))
    with pytest.raises(ValueError, match="fus orar"):
        validate(mk(schedule_at="2030-01-01T10:00:00"))
    with pytest.raises(ValueError, match="opțiune necunoscută"):
        validate(mk(platform="tiktok", account="tiktok:x", options={"made_for_kids": False}))
    assert any("privat" in w for w in validate(mk(schedule_at="2030-01-01T10:00:00+02:00")))


def test_tiktok_chunk_plan_follows_their_rules():
    MB = 1024 * 1024
    assert tiktok.chunk_plan(3 * MB) == (3 * MB, 1)                   # sub 5 MB: o singură bucată
    c, n = tiktok.chunk_plan(57 * MB)
    assert c == 10 * MB and n == 5 and 57 * MB - c * (n - 1) <= 128 * MB  # restul intră în ultima
    c, n = tiktok.chunk_plan(7 * MB)
    assert (c, n) == (7 * MB, 1)


# ---------------- fluxul complet, pe API-ul fals ----------------
class Fake(BaseHTTPRequestHandler):
    calls: list = []
    bytes_in: dict = {}

    def _send(self, code, body=None, headers=None):
        data = json.dumps(body or {}).encode()
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def log_message(self, *a):
        pass

    def do_GET(self):  # noqa: N802
        u = urlsplit(self.path)
        Fake.calls.append(("GET", u.path, dict(self.headers)))
        if u.path.endswith("/c1"):
            return self._send(200, {"status_code": "FINISHED"})
        if u.path.endswith("/m1"):
            return self._send(200, {"permalink": "https://www.instagram.com/reel/abc/"})
        self._send(404, {"error": "nope"})

    def do_POST(self):  # noqa: N802
        u, body = urlsplit(self.path), self._body()
        ctype = self.headers.get("Content-Type", "")
        q = {**parse_qs(u.query), **(parse_qs(body.decode()) if ctype.startswith("application/x-www-form") else {})}
        Fake.calls.append(("POST", u.path, dict(self.headers), q, len(body)))
        host = f"http://127.0.0.1:{self.server.server_port}"
        p = u.path
        if p == "/youtube/upload/youtube/v3/videos":
            return self._send(200, {}, {"Location": f"{host}/youtube/session/1"})
        if p == "/youtube/upload/youtube/v3/thumbnails/set":
            assert ctype == "image/png"
            return self._send(200, {})
        if p.endswith("/IG_RARES/media"):
            return self._send(200, {"id": "c1"})
        if p.startswith("/rupload/"):
            Fake.bytes_in[p] = len(body)
            assert ctype == "application/octet-stream"
            assert self.headers["Authorization"] == "OAuth pt-rares" and self.headers["offset"] == "0"
            assert int(self.headers["file_size"]) == len(body)
            return self._send(200, {"success": True, "message": "Upload successful."})
        if p.endswith("/IG_RARES/media_publish"):
            return self._send(200, {"id": "m1"})
        if p.endswith("/PG_R/video_reels"):
            if q["upload_phase"] == ["start"]:
                return self._send(200, {"video_id": "v9", "upload_url": f"{host}/rupload/video-upload/v25.0/v9"})
            assert q["video_state"] == ["PUBLISHED"]
            return self._send(200, {"success": True})
        if p == "/tiktok/v2/post/publish/creator_info/query/":
            return self._send(200, {"data": {"privacy_level_options": ["SELF_ONLY"]}})
        if p == "/tiktok/v2/post/publish/video/init/":
            j = json.loads(body)
            Fake.tiktok_init = j
            return self._send(200, {"data": {"publish_id": "p1", "upload_url": f"{host}/tiktok-up/p1"},
                                    "error": {"code": "ok"}})
        if p == "/tiktok/v2/post/publish/status/fetch/":
            return self._send(200, {"data": {"status": "PUBLISH_COMPLETE", "publicaly_available_post_id": [777]}})
        self._send(404, {"error": p})

    def do_PUT(self):  # noqa: N802
        u, body = urlsplit(self.path), self._body()
        rng = self.headers["Content-Range"]
        Fake.calls.append(("PUT", u.path, rng, len(body)))
        first, last_total = rng.split(" ")[1].split("-")
        last, total = map(int, last_total.split("/"))
        Fake.bytes_in[u.path] = Fake.bytes_in.get(u.path, 0) + len(body)
        if u.path == "/youtube/session/1":
            if last + 1 < total:
                return self._send(308, {}, {"Range": f"bytes=0-{last}"})
            return self._send(200, {"id": "vid123", "status": {"privacyStatus": "private"}})
        if u.path == "/tiktok-up/p1":
            return self._send(201 if last + 1 == total else 206, {})
        self._send(404)


@pytest.fixture
def fake_api(monkeypatch):
    Fake.calls, Fake.bytes_in = [], {}
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("VEDIT_PUBLISH_FAKE", f"http://127.0.0.1:{srv.server_port}")
    yield Fake
    srv.shutdown()


def test_end_to_end_all_platforms(vault, project, fake_api, monkeypatch):
    from vedit.publish import youtube

    monkeypatch.setattr(youtube, "CHUNK", 256 * 1024)               # mai multe bucăți, ca să vedem 308-urile
    setup_clients(vault)
    vault.link_project(project.s.name, "service-rares")
    size = (project.dir / "renders" / "reels.mp4").stat().st_size
    name, d = project.s.name, project.dir
    monkeypatch.setenv("VEDIT_ALLOW_PUBLISH", "1")

    yt, _ = service.prepare(vault, name, d, platform="youtube", video="renders/reels.mp4", title="Plăcuțe noi",
                            caption="Ce schimbăm la o revizie.", hashtags="#service", cover="renders/thumb.png",
                            options={"made_for_kids": False})
    res = service.publish(vault, name, d, yt.id, log=lambda m: None)
    assert res["id"] == "vid123" and res["thumbnail"] == "pus"
    assert "auditul" in res["warning"]                               # YouTube l-a ținut privat
    assert fake_api.bytes_in["/youtube/session/1"] == size
    assert sum(1 for c in fake_api.calls if c[0] == "PUT") > 1
    with pytest.raises(ValueError, match="deja publicat"):            # fără dubluri
        service.publish(vault, name, d, yt.id)

    ig, _ = service.prepare(vault, name, d, platform="instagram", video="renders/reels.mp4",
                            caption="Plăcuțe noi în 20 de minute", hashtags="#frane #service", cover_at=1.5)
    res = service.publish(vault, name, d, ig.id, log=lambda m: None)
    assert res["url"].startswith("https://www.instagram.com/reel/")
    create = next(c for c in fake_api.calls if c[0] == "POST" and c[1].endswith("/IG_RARES/media"))
    assert create[3]["media_type"] == ["REELS"] and create[3]["upload_type"] == ["resumable"]
    assert create[3]["thumb_offset"] == ["1500"] and "#frane" in create[3]["caption"][0]
    assert fake_api.bytes_in["/rupload/ig-api-upload/v25.0/c1"] == size

    fb, _ = service.prepare(vault, name, d, platform="facebook", video="renders/reels.mp4", caption="Pe pagină")
    res = service.publish(vault, name, d, fb.id, log=lambda m: None)
    assert res["url"] == "https://www.facebook.com/reel/v9"
    assert fake_api.bytes_in["/rupload/video-upload/v25.0/v9"] == size

    tt, _ = service.prepare(vault, name, d, platform="tiktok", video="renders/reels.mp4", title="Plăcuțe #frane",
                            privacy="public")
    with pytest.raises(RuntimeError, match="auditul TikTok"):         # neauditat: doar privat
        service.publish(vault, name, d, tt.id, log=lambda m: None)
    tt2, _ = service.prepare(vault, name, d, platform="tiktok", video="renders/reels.mp4", title="Plăcuțe #frane",
                             privacy="private", options={"is_aigc": False, "brand_organic": True})
    res = service.publish(vault, name, d, tt2.id, log=lambda m: None)
    assert res["post_id"] == 777
    init = fake_api.tiktok_init
    assert init["post_info"]["privacy_level"] == "SELF_ONLY" and init["post_info"]["brand_organic_toggle"] is True
    assert init["source_info"]["video_size"] == size and fake_api.bytes_in["/tiktok-up/p1"] == size

    journal = [json.loads(x) for x in (vault.root / "journal.jsonl").read_text().splitlines()]
    assert [j["platform"] for j in journal if j["ok"]] == ["youtube", "instagram", "facebook", "tiktok"]
    assert all(j["client"] == "service-rares" for j in journal)
    assert all("pt-rares" not in json.dumps(j) for j in journal)      # fără tokenuri în jurnal


# ---------------- thumbnail studio ----------------
def test_thumbnail_variants_formats_and_sheet(vhome, talking_video):
    pytest.importorskip("cv2")
    import cv2

    p = Project("thumbs")
    p.add_asset(talking_video)
    p.add_clip("a0", 0, 8)
    res = p.thumbnail_variants(title="Plăcuțe noi", count=3, formats="youtube,cover", styles="frame")
    assert len(res["images"]) == 6
    for im in res["images"]:
        img = cv2.imread(str(p.dir / im["file"]))
        assert (img.shape[1], img.shape[0]) == {"youtube": (1280, 720), "cover": (1080, 1920)}[im["format"]]
    ats = sorted({im["at"] for im in res["images"]})
    assert len(ats) == 3 and min(b - a for a, b in zip(ats, ats[1:])) > 0.8   # momente diferite
    sheet = cv2.imread(str(p.dir / res["sheet"]))
    assert sheet is not None and sheet.shape[1] < 2000                # mărimi de feed, nu rezoluția întreagă
    assert (p.tl.width, p.tl.height) == (1920, 1080)                  # timeline-ul proiectului neatins
