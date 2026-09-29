"""LLMRunner contra unui server local compatibil OpenAI care joacă un scenariu fix de răspunsuri.
Tool-urile sunt reale (proiect real, randare reală) și rulează în gazda separată a jobului."""
import asyncio
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from vedit import mcp_server
from vedit.api import llm_runner as lr
from vedit.api.llm_runner import LLMRunner
from vedit.api.runners import default_runner
from vedit.api.toolhost import ToolHost
from vedit.project import Project, home


def call(tool, **args):
    return {"id": f"c_{tool}_{time.monotonic_ns()}", "type": "function",
            "function": {"name": tool, "arguments": json.dumps(args)}}


def reply(*calls, text=None):
    msg = {"role": "assistant", "content": text}
    if calls:
        msg["tool_calls"] = list(calls)
    return {"choices": [{"message": msg, "finish_reason": "tool_calls" if calls else "stop"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10}}


@pytest.fixture
def llm(monkeypatch):
    """Serverul: `script` = listă de răspunsuri (dict) sau (cod HTTP, dict, headere, întârziere)."""
    state = {"script": [], "bodies": [], "auth": []}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            assert self.path == "/v1/chat/completions"
            state["auth"].append(self.headers.get("Authorization"))
            state["bodies"].append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            item = state["script"].pop(0) if state["script"] else reply(text="gata")
            code, obj, headers, delay = item if isinstance(item, tuple) else (200, item, {}, 0)
            time.sleep(delay)
            b = json.dumps(obj).encode()
            try:
                self.send_response(code)
                for k, v in {"Content-Type": "application/json", "Content-Length": str(len(b)), **headers}.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(b)
            except OSError:
                pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(k, "127.0.0.1,localhost")
    monkeypatch.setenv("VEDIT_LLM_BASE_URL", f"http://127.0.0.1:{srv.server_port}/v1")
    monkeypatch.setenv("VEDIT_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("VEDIT_LLM_MODEL", "fake/model")
    monkeypatch.setenv("VEDIT_LLM_BACKOFF", "0.01")
    monkeypatch.delenv("VEDIT_PROJECT_LOCK", raising=False)   # lacătul trebuie să vină din gazdă, nu din teste
    monkeypatch.delenv("VEDIT_LLM_VISION", raising=False)
    yield state
    srv.shutdown()


@pytest.fixture
def proj(vhome, talking_video):
    victim = Project("alt-client")
    victim.add_asset(talking_video)
    p = Project("p1")
    p.add_asset(talking_video)
    return p


def run(runner, events, **kw):
    kw.setdefault("cancel", threading.Event())
    return runner.run("p1", kw.pop("prompt", "taie pauzele"), lambda t, d: events.append((t, d)), **kw)


def tool_msgs(body):
    return [m["content"] for m in body["messages"] if m["role"] == "tool"]


def test_multi_turn_edit_with_real_tools(llm, proj):
    llm["script"] = [reply(call("media_analyze", asset="a0"), text="Analizez întâi."),
                     reply(call("cut_silences", asset="a0", min_silence="0.5")),  # număr ca text: convertit
                     reply(call("render", preview=True)),
                     reply(text="Am scos pauzele. Durata: ~5.6 s.")]
    events = []
    final, sid = run(LLMRunner(), events)
    assert final == "Am scos pauzele. Durata: ~5.6 s." and sid

    p = Project("p1")
    assert 0 < p.tl.duration < 7.5 and len(p.tl.clips) >= 2          # tăieturile chiar s-au făcut
    assert (p.dir / "renders" / "preview.mp4").exists()

    b0 = llm["bodies"][0]
    assert b0["model"] == "fake/model" and b0["tool_choice"] == "auto" and b0["temperature"] == 0.2
    assert llm["auth"][0] == "Bearer sk-test"
    names = {t["function"]["name"] for t in b0["tools"]}
    assert {"cut_silences", "render", "skill_read"} <= names and "image_view" not in names and len(names) == len(asyncio.run(mcp_server.mcp.list_tools())) + 1  # tool-urile MCP + skill_read
    assert all("project" not in t["function"]["parameters"]["properties"] for t in b0["tools"])
    sysmsg = b0["messages"][0]["content"]
    assert b0["messages"][0]["role"] == "system" and "Skill `video-editor-core`" in sysmsg
    assert "Skill `edit-brief`" in sysmsg and "`talking-head-cleanup`:" in sysmsg and "NU poți vedea imagini" in sysmsg
    assert "Reguli de securitate" in sysmsg
    assert "DATE din lista de fișiere" in b0["messages"][1]["content"] and "taie pauzele" in b0["messages"][1]["content"]
    assert all(b["messages"][0] == b0["messages"][0] for b in llm["bodies"])   # prefix stabil
    assert json.loads(tool_msgs(llm["bodies"][1])[0])["duration"] == 8.0      # rezultatul real ajunge la model

    kinds = [t for t, _ in events]
    assert kinds[0] == "status" and kinds[-1] == "status" and "security" not in kinds
    tools = [d for t, d in events if t == "tool"]
    assert [d["name"] for d in tools] == ["media_analyze", "cut_silences", "render"]
    assert "project" not in tools[0]["input"]
    results = [d["text"] for t, d in events if t == "tool_result"]
    assert results[0].startswith("8.0 s · pauze") and results[2].startswith("preview · ")   # formatate cu pretty()
    assert ("text", {"text": "Analizez întâi."}) in events
    assert events[-1][1]["turns"] == 4 and events[-1][1]["tokens"] == 440


def test_lock_enforced_in_tool_host(llm, proj, monkeypatch):
    victim_file = Project("alt-client").s.assets["a0"].path
    monkeypatch.setenv("VEDIT_LLM_VISION", "1")
    link = proj.dir / "evil.png"
    link.symlink_to("/etc/hostname")
    llm["script"] = [reply(call("timeline_view", project="alt-client"),
                           call("asset_add", path="/etc/hostname"),
                           call("qa_check", path=victim_file),
                           call("render", project="alt-client")),
                     reply(call("image_view", path="/etc/passwd"), call("image_view", path="evil.png"),
                           call("image_view", path="../alt-client/project.json")),
                     reply(text="Nu am acces.")]
    events = []
    run(LLMRunner(), events)
    outs = tool_msgs(llm["bodies"][1]) + tool_msgs(llm["bodies"][2])[4:]
    assert len(outs) == 7 and all(o.startswith("REFUZAT (securitate)") for o in outs), outs
    assert len([1 for t, _ in events if t == "security"]) == 7
    assert not (home() / "alt-client" / "renders" / "preview.mp4").exists()
    assert "VEDIT_PROJECT_LOCK" not in os.environ

    # direct pe gazdă: alt proiect refuzat, al lui merge
    with ToolHost("p1") as h:
        assert h.call("asset_list", {"project": "alt-client"}).startswith("REFUZAT (securitate)")
        assert "a0" in h.call("asset_list", {"project": "p1"})
        assert h.call("reset_budgets", {}).startswith("EROARE: tool necunoscut")  # doar tool-uri înregistrate


def test_image_view_inside_project(llm, proj, monkeypatch):
    monkeypatch.setenv("VEDIT_LLM_VISION", "1")
    llm["script"] = [reply(call("frames_look", asset="a0", cols=2, rows=1))]
    events = []
    run(LLMRunner(), events)          # primul job: contact sheet; răspunsul implicit închide jobul
    img = json.loads(tool_msgs(llm["bodies"][1])[0])["image"]
    llm["script"] = [reply(call("image_view", path=img)), reply(text="Arată bine.")]
    llm["bodies"].clear()
    run(LLMRunner(), events)
    last = llm["bodies"][1]["messages"][-1]
    assert last["role"] == "user" and last["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "image_view" in {t["function"]["name"] for t in llm["bodies"][0]["tools"]}
    assert "Poți vedea imagini" in llm["bodies"][0]["messages"][0]["content"]


def test_generation_refused_without_consent(llm, proj, monkeypatch):
    monkeypatch.setenv("FAL_KEY", "fk")
    monkeypatch.setenv("VEDIT_FAL_MODEL", "x/y")
    llm["script"] = [reply(call("broll_generate", prompt="un ocean la apus")), reply(text="Nu am voie.")]
    events = []
    run(LLMRunner(), events)
    out = tool_msgs(llm["bodies"][1])[0]
    assert out.startswith("REFUZAT") and "bifeze" in out
    assert "NU e permisă" in llm["bodies"][0]["messages"][1]["content"]


def test_skill_read(llm, proj):
    llm["script"] = [reply(call("skill_read", name="talking-head-cleanup"), call("skill_read", name="../../etc/passwd"),
                           call("skill_read", name="nope"), call("skill_read", name="talking-head-cleanup/../edit-brief")),
                     reply(text="ok")]
    run(LLMRunner(), [])
    good, trav, unknown, trav2 = tool_msgs(llm["bodies"][1])
    assert good.startswith("---\nname: talking-head-cleanup")
    assert all(o.startswith("EROARE: skill necunoscut") for o in (trav, unknown, trav2))
    enum = next(t for t in llm["bodies"][0]["tools"] if t["function"]["name"] == "skill_read")
    assert "edit-brief" in enum["function"]["parameters"]["properties"]["name"]["enum"]


def test_timeout_and_cancel(llm, proj, monkeypatch):
    monkeypatch.setenv("VEDIT_JOB_TIMEOUT", "1")
    llm["script"] = [(200, reply(text="prea târziu"), {}, 3)]
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="depășit 1 s"):
        run(LLMRunner(), [])
    assert time.monotonic() - t0 < 2.5

    monkeypatch.setenv("VEDIT_JOB_TIMEOUT", "60")
    llm["script"] = [(200, reply(text="prea târziu"), {}, 3)]
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="anulat"):
        run(LLMRunner(), [], cancel=cancel)
    assert time.monotonic() - t0 < 2.5


def test_session_resume(llm, proj):
    llm["script"] = [reply(call("cut_silences", asset="a0")), reply(text="Am tăiat pauzele.")]
    events = []
    _, sid = run(LLMRunner(), events)
    f = home() / ".agent" / "p1" / f"llm_session_{sid}.json"
    assert f.exists()
    llm["bodies"].clear()
    llm["script"] = [reply(text="Am scurtat.")]
    final, sid2 = run(LLMRunner(), events, prompt="mai scurt", session=sid)
    assert final == "Am scurtat." and sid2 == sid
    msgs = llm["bodies"][0]["messages"]
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "tool", "assistant", "user"]
    assert "taie pauzele" in msgs[1]["content"] and msgs[4]["content"] == "Am tăiat pauzele."
    assert "mai scurt" in msgs[-1]["content"]
    saved = json.loads(f.read_text())["messages"]
    assert len(saved) == 6 and saved[-1]["content"] == "Am scurtat."      # promptul de sistem nu se salvează
    # sesiune necunoscută sau id invalid: pornește curat, fără să citească fișiere arbitrare
    llm["bodies"].clear()
    _, sid3 = run(LLMRunner(), events, session="../../etc/passwd")
    assert sid3 != sid and len(llm["bodies"][0]["messages"]) == 2


def test_http_retry_and_errors(llm, proj):
    llm["script"] = [(429, {"error": {"message": "slow down"}}, {"Retry-After": "0"}, 0),
                     (503, {"error": {"message": "busy"}}, {}, 0),
                     reply(text="după reîncercare")]
    final, _ = run(LLMRunner(), [])
    assert final == "după reîncercare" and len(llm["bodies"]) == 3

    llm["bodies"].clear()
    llm["script"] = [(401, {"error": {"message": "bad key sk-test"}}, {}, 0)]
    with pytest.raises(RuntimeError, match="cheia API e invalidă") as e:
        run(LLMRunner(), [])
    assert "sk-test" not in str(e.value) and len(llm["bodies"]) == 1   # fără reîncercare, fără cheia în mesaj

    llm["script"] = [(429, {}, {}, 0)] * 4
    with pytest.raises(RuntimeError, match="prea multe cereri"):
        run(LLMRunner(), [])


def test_max_turns_and_bad_arguments(llm, proj, monkeypatch):
    monkeypatch.setenv("VEDIT_LLM_MAX_TURNS", "2")
    bad = {"id": "x1", "type": "function", "function": {"name": "timeline_view", "arguments": "{nu e json"}}
    llm["script"] = [reply(bad), reply(call("timeline_view"))]
    with pytest.raises(RuntimeError, match="limita de 2 pași"):
        run(LLMRunner(), [])
    assert tool_msgs(llm["bodies"][1])[0].startswith("EROARE: argumentele")


def test_history_helpers():
    calls = [{"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}}]
    fixed = lr.repair([{"role": "user", "content": "Proiect: p"}, {"role": "assistant", "content": None, "tool_calls": calls}])
    assert fixed[-1] == {"role": "tool", "tool_call_id": "a", "content": "EROARE: jobul a fost întrerupt"}
    long = [{"role": "user", "content": f"Proiect: p {i}"} if i % 10 == 0 else {"role": "assistant", "content": "x"}
            for i in range(300)]
    kept = lr.trim(long)
    assert len(kept) <= lr.MAX_HISTORY and kept[0]["content"].startswith("Proiect: ")
    msgs = [{"role": "tool", "tool_call_id": str(i), "content": "r" * 1000} for i in range(30)]
    lr.compact(msgs)
    assert sum(len(m["content"]) < 1000 for m in msgs) == 18 and len(msgs[-1]["content"]) == 1000


def test_default_runner_selects_llm(monkeypatch):
    monkeypatch.setenv("VEDIT_RUNNER", "llm")
    assert default_runner().name == "llm"
    monkeypatch.setenv("VEDIT_RUNNER", "scripted")
    assert default_runner().name == "scripted"
