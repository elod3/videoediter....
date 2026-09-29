import json
import os
import stat
import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from vedit.api.app import create_app  # noqa: E402
from vedit.api.runners import ClaudeCodeRunner, ScriptedRunner  # noqa: E402


@pytest.fixture
def client(vhome):
    with TestClient(create_app(ScriptedRunner())) as c:
        yield c


def wait_job(c, jid, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error", "cancelled"):
            return j
        time.sleep(0.2)
    raise AssertionError("jobul nu s-a terminat")


def upload(c, name, path):
    with open(path, "rb") as f:
        return c.post(f"/api/projects/{name}/assets", files={"file": (os.path.basename(path), f, "video/mp4")})


def test_projects_crud(client):
    assert client.get("/api/health").json()["runner"] == "scripted"
    assert client.post("/api/projects", json={"name": "demo"}).status_code == 200
    assert client.post("/api/projects", json={"name": "demo"}).status_code == 409
    assert client.post("/api/projects", json={"name": "../x"}).status_code == 400
    assert [p["name"] for p in client.get("/api/projects").json()] == ["demo"]
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/nope").status_code == 404
    assert client.delete("/api/projects/demo").json()["ok"]
    assert client.get("/api/projects").json() == []


def test_upload_agent_job_render_and_media(client, talking_video):
    client.post("/api/projects", json={"name": "p"})
    bad = client.post("/api/projects/p/assets", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 400
    r = upload(client, "p", talking_video)
    assert r.status_code == 200, r.text
    proj = r.json()["project"]
    assert proj["assets"][0]["id"] == "a0" and proj["assets"][0]["duration"] == 8.0
    assert client.get(proj["assets"][0]["thumb"]).headers["content-type"] == "image/jpeg"

    job = client.post("/api/projects/p/jobs", json={"prompt": "Fă-l pentru TikTok, taie pauzele"}).json()
    done = wait_job(client, job["id"])
    assert done["status"] == "done", done
    tools = [e["data"]["name"] for e in done["events"] if e["type"] == "tool"]
    assert tools[:3] == ["cut_silences", "timeline_format", "auto_reframe"] and "render" in tools
    assert "9:16" in done["result"]

    # SSE: fluxul complet se termină cu "done"
    sse = client.get(f"/api/jobs/{job['id']}/events").text
    assert "event: done" in sse and sse.count("event: tool\n") == len(tools)

    proj = client.get("/api/projects/p").json()
    assert proj["timeline"]["width"] == 1080 and len(proj["timeline"]["clips"]) >= 3
    prev = next(r for r in proj["renders"] if r["name"] == "preview")
    part = client.get(prev["url"], headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100  # video player cu seek

    # editare manuală: scoate un clip, apoi undo
    tl = proj["timeline"]
    n = len(tl["clips"])
    cid = tl["clips"][0]["id"]
    after = client.delete(f"/api/projects/p/timeline/clips/{cid}").json()["timeline"]
    assert len(after["clips"]) == n - 1 and after["can_undo"]
    assert len(client.post("/api/projects/p/undo").json()["timeline"]["clips"]) == n
    tl["clips"][0]["asset"] = "zz"
    assert client.put("/api/projects/p/timeline", json=tl).status_code == 422
    tl["clips"][0]["asset"] = "a0"
    tl["fps"] = 25
    assert client.put("/api/projects/p/timeline", json=tl).json()["timeline"]["fps"] == 25

    rj = client.post("/api/projects/p/render", json={"final": True}).json()
    assert wait_job(client, rj["id"])["status"] == "done"
    assert any(r["name"] == "final" for r in client.get("/api/projects/p").json()["renders"])


def test_job_validation(client):
    client.post("/api/projects", json={"name": "e"})
    assert client.post("/api/projects/e/jobs", json={"prompt": "ceva"}).status_code == 400  # fără video
    assert client.post("/api/projects/e/render", json={}).status_code == 400  # timeline gol


def test_auth_token(vhome, monkeypatch):
    monkeypatch.setenv("VEDIT_API_TOKEN", "secret")
    with TestClient(create_app(ScriptedRunner())) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/projects").status_code == 401
        assert c.get("/api/projects", headers={"Authorization": "Bearer secret"}).status_code == 200
        assert c.get("/api/projects?token=secret").status_code == 200  # <video src> / EventSource


FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}) + "\n")
def out(o): print(json.dumps(o), flush=True)
out({"type": "system", "subtype": "init", "session_id": "sess-1", "model": "fake",
     "mcp_servers": [{"name": "vedit", "status": "connected"}]})
out({"type": "assistant", "session_id": "sess-1", "message": {"content": [
    {"type": "text", "text": "Încep cu analiza."},
    {"type": "tool_use", "id": "t1", "name": "mcp__vedit__media_analyze", "input": {"project": "cc", "asset": "a0"}}]}})
out({"type": "user", "session_id": "sess-1", "message": {"content": [
    {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "{\"result\": \"liniste 2.5s\"}"}]}]}})
out({"type": "result", "subtype": "success", "is_error": False, "result": "Am tăiat 2.5s de pauze.",
     "session_id": "sess-1", "num_turns": 2, "total_cost_usd": 0.0})
'''


def test_claude_code_runner_with_fake_cli(vhome, tmp_path, monkeypatch, talking_video):
    fake = tmp_path / "claude"
    fake.write_text(FAKE_CLAUDE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("VEDIT_CLAUDE_BIN", str(fake))
    monkeypatch.setenv("FAKE_LOG", str(log))
    with TestClient(create_app(ClaudeCodeRunner())) as c:
        c.post("/api/projects", json={"name": "cc"})
        upload(c, "cc", talking_video)
        j1 = wait_job(c, c.post("/api/projects/cc/jobs", json={"prompt": "taie pauzele"}).json()["id"])
        assert j1["status"] == "done", j1
        assert j1["result"] == "Am tăiat 2.5s de pauze." and j1["runner"] == "claude-code"
        types = [(e["type"], e["data"].get("name") or e["data"].get("text", "")[:10]) for e in j1["events"]]
        assert ("tool", "media_analyze") in types and ("text", "Încep cu a") in types
        res = next(e["data"]["text"] for e in j1["events"] if e["type"] == "tool_result")
        assert res == "liniste 2.5s"  # despachetat din {"result": ...}
        j2 = wait_job(c, c.post("/api/projects/cc/jobs", json={"prompt": "mai scurt"}).json()["id"])
        assert j2["status"] == "done"
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    a1, a2 = calls[0]["argv"], calls[1]["argv"]
    assert a1[0] == "-p" and "a0: talk.mp4" in a1[1] and "taie pauzele" in a1[1]
    assert a1[a1.index("--allowedTools") + 1] == "mcp__vedit" and "Bash" not in " ".join(a1)
    assert "--strict-mcp-config" in a1 and "--resume" not in a1
    assert a2[a2.index("--resume") + 1] == "sess-1"  # continuă conversația pe același proiect
    cfg = json.loads(open(a1[a1.index("--mcp-config") + 1]).read())
    assert cfg["mcpServers"]["vedit"]["args"] == ["-m", "vedit.mcp_server"]
    assert os.path.isdir(os.path.join(calls[0]["cwd"], ".claude", "skills", "video-editor-core"))


def test_reference_role_drives_scripted_edit(client, talking_video, tmp_path):
    from vedit.ff import run

    ref = tmp_path / "ref_vertical.mp4"  # referință verticală, caldă
    run(["-y", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=25:duration=4", "-f", "lavfi", "-i", "sine=d=4",
         "-vf", "colorbalance=rs=.3:bs=-.3", "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(ref)])
    client.post("/api/projects", json={"name": "r"})
    upload(client, "r", talking_video)
    upload(client, "r", str(ref))
    proj = client.post("/api/projects/r/assets/a1/role", json={"role": "reference"}).json()
    assert [a["role"] for a in proj["assets"]] == ["source", "reference"]
    assert client.post("/api/projects/r/assets/a1/role", json={"role": "boss"}).status_code == 400
    done = wait_job(client, client.post("/api/projects/r/jobs", json={"prompt": "în stilul referinței"}).json()["id"])
    assert done["status"] == "done", done
    tools = [e["data"]["name"] for e in done["events"] if e["type"] == "tool"]
    assert tools[0] == "reference_analyze" and "color_match" in tools and "style_compare" in tools
    tl = client.get("/api/projects/r").json()["timeline"]
    assert {c["asset"] for c in tl["clips"]} == {"a0"}          # referința nu intră în montaj
    assert (tl["width"], tl["height"]) == (1080, 1920)          # formatul vine din referință
    assert set(tl["grades"]) == {"a0"}
