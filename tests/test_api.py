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
if "--help" in sys.argv:
    print("  --restricted   Restricted mode ...\n  --setting-sources <sources>\n  --plugin-dir <path>")
    sys.exit(0)
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
    assert a1[a1.index("--allowedTools") + 1] == "mcp__vedit"
    allowed = a1[a1.index("--allowedTools") + 1: a1.index("--disallowedTools")]
    assert "Bash" not in allowed and "Bash" in a1[a1.index("--disallowedTools"):]
    assert "--restricted" in a1 and a1[a1.index("--permission-mode") + 1] == "dontAsk"
    plugin = a1[a1.index("--plugin-dir") + 1]             # skill-urile ajung la agent și în modul restricționat
    assert os.path.isfile(os.path.join(plugin, ".claude-plugin", "plugin.json"))
    assert os.path.isfile(os.path.join(plugin, "skills", "video-editor-core", "SKILL.md"))
    pdir = os.path.realpath(os.path.join(os.environ["VEDIT_HOME"], "cc"))
    assert a1[a1.index("--add-dir") + 1] == pdir and f"Read(/{pdir}/**)" in allowed  # citire doar din proiect
    assert "--strict-mcp-config" in a1 and "--resume" not in a1
    assert a2[a2.index("--resume") + 1] == "sess-1"  # continuă conversația pe același proiect
    cfg = json.loads(open(a1[a1.index("--mcp-config") + 1]).read())
    assert cfg["mcpServers"]["vedit"]["args"] == ["-m", "vedit.mcp_server"]
    env = cfg["mcpServers"]["vedit"]["env"]
    assert env["VEDIT_PROJECT_LOCK"] == "cc" and env["VEDIT_ALLOW_GENERATION"] == "0"
    assert "DATE din lista de fișiere" in a1[1] and "NU e permisă" in a1[1]
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


def test_scripted_beat_montage_and_broll(client, talking_video, tmp_path):
    from drums import drum_track

    from vedit.ff import run

    wav = tmp_path / "beat.wav"
    drum_track(str(wav), 120, dur=10)
    music = tmp_path / "beat.m4a"
    run(["-y", "-i", str(wav), "-c:a", "aac", str(music)])
    client.post("/api/projects", json={"name": "m"})
    upload(client, "m", talking_video)
    upload(client, "m", str(music))
    done = wait_job(client, client.post("/api/projects/m/jobs", json={"prompt": "montaj pe beat"}).json()["id"])
    assert done["status"] == "done", done
    proj = client.get("/api/projects/m").json()
    tl = proj["timeline"]
    assert tl["music"]["asset"] == "a1" and len(tl["beats"]) > 8
    assert abs(tl["beats"][1] - tl["beats"][0] - 0.5) < 0.02          # 120 BPM în timp de timeline
    starts = tl["starts"][1:]
    assert all(min(abs(b - s) for b in tl["beats"]) < 0.01 for s in starts)  # fiecare tăietură e pe beat

    # B-roll: rolul se setează din API, pipeline-ul îl pune pe V2
    client.post("/api/projects", json={"name": "b"})
    upload(client, "b", talking_video)
    upload(client, "b", talking_video)
    assert client.post("/api/projects/b/assets/a1/role", json={"role": "broll"}).json()["assets"][1]["role"] == "broll"
    done = wait_job(client, client.post("/api/projects/b/jobs", json={"prompt": "taie pauzele și pune b-roll"}).json()["id"])
    assert done["status"] == "done", done
    tl = client.get("/api/projects/b").json()["timeline"]
    assert tl["broll"] and {c["asset"] for c in tl["clips"]} == {"a0"}


def test_manual_polish_via_timeline_put(client, talking_video):
    client.post("/api/projects", json={"name": "pol"})
    upload(client, "pol", talking_video)
    wait_job(client, client.post("/api/projects/pol/jobs", json={"prompt": "taie pauzele"}).json()["id"])
    tl = client.get("/api/projects/pol").json()["timeline"]
    n = len(tl["clips"])
    assert n >= 2
    tl["clips"][1]["transition"] = {"type": "fadeblack", "duration": 0.3}
    tl["clips"][0]["anim"] = {"zoom_from": 1.0, "zoom_to": 1.1, "ease": "inout"}
    tl["captions"] = [{"start": 0.2, "end": 1.0, "text": "Vedit, corectat de mână", "word_durs": None}]
    out = client.put("/api/projects/pol/timeline", json=tl)
    assert out.status_code == 200, out.text
    new = out.json()["timeline"]
    assert new["clips"][1]["transition"]["type"] == "fadeblack" and new["captions"][0]["text"].startswith("Vedit")
    assert abs(new["duration"] - (sum(c["src_out"] - c["src_in"] for c in new["clips"]) - 0.3)) < 1e-3
    tl["clips"][1]["transition"] = {"type": "explozie", "duration": 0.3}
    assert client.put("/api/projects/pol/timeline", json=tl).status_code == 422
    job = client.post("/api/projects/pol/render", json={"final": False}).json()
    assert wait_job(client, job["id"])["status"] == "done"
