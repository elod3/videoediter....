"""Gazda de tool-uri a unui job: proces separat, cu lacătul pe proiect în PROPRIUL mediu.

De ce proces separat: garda (vedit/guard.py) citește VEDIT_PROJECT_LOCK, consimțământul și bugetele din
variabile de mediu și contoare globale. În procesul API ele ar fi comune tuturor joburilor; aici fiecare job
are procesul lui, cu proiectul lui, bugetele lui și doar cheile permise.

Protocol (JSON pe linii, stdin → stdout):
  {"id": 1, "op": "list"}                               → {"id": 1, "result": [{"name", "description", "parameters"}]}
  {"id": 2, "name": "cut_silences", "args": {...}}      → {"id": 2, "result": "text"}
Rulează:  VEDIT_PROJECT_LOCK=<proiect> python -m vedit.api.toolhost
"""
from __future__ import annotations

import asyncio
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

HIDDEN = {"project"}  # îl completează runner-ul; modelul nu-l vede


def _schema(tool) -> dict:
    s = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
    return s if isinstance(s, dict) else dict(s)


def _clean(schema: dict) -> dict:
    """Schema pentru model: fără `project` și fără câmpurile `title` (tokeni inutili)."""
    props = {k: {kk: vv for kk, vv in v.items() if kk != "title"}
             for k, v in (schema.get("properties") or {}).items() if k not in HIDDEN}
    out = {"type": "object", "properties": props}
    req = [r for r in schema.get("required", []) if r not in HIDDEN]
    if req:
        out["required"] = req
    return out


def specs() -> list[dict]:
    from .. import mcp_server as m

    return [{"name": t.name, "description": (t.description or "").strip(), "parameters": _clean(_schema(t))}
            for t in asyncio.run(m.mcp.list_tools())]


def _coerce(args: dict, schema: dict) -> dict:
    """Modelele ieftine trimit uneori "5" sau "true" ca text; convertim după tipul din schemă."""
    props = schema.get("properties") or {}
    out = dict(args)
    for k, v in args.items():
        t = (props.get(k) or {}).get("type")
        if not isinstance(v, str):
            continue
        try:
            if t == "number":
                out[k] = float(v)
            elif t == "integer":
                out[k] = int(float(v))
            elif t == "boolean" and v.lower() in ("true", "false", "1", "0"):
                out[k] = v.lower() in ("true", "1")
        except ValueError:
            pass
    return out


def main() -> None:
    proto = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)  # orice print (al nostru sau al unui subproces) merge în log, nu în protocol
    sys.stdout = sys.stderr
    from .. import guard
    from .. import mcp_server as m

    if not guard.project_lock():
        print("toolhost: refuz să pornesc fără VEDIT_PROJECT_LOCK", file=sys.stderr)
        sys.exit(2)
    tools = {t.name: _schema(t) for t in asyncio.run(m.mcp.list_tools())}

    def answer(rid, result) -> None:
        proto.write(json.dumps({"id": rid, "result": result}, ensure_ascii=False) + "\n")

    for line in sys.stdin:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        rid = req.get("id")
        if req.get("op") == "list":
            answer(rid, specs())
            continue
        name, args = req.get("name"), req.get("args") or {}
        if name not in tools:  # doar tool-urile înregistrate, niciodată alte funcții din modul
            answer(rid, f"EROARE: tool necunoscut „{name}”")
            continue
        if not isinstance(args, dict):
            answer(rid, "EROARE: argumentele trebuie să fie un obiect JSON")
            continue
        answer(rid, getattr(m, name)(**_coerce(args, tools[name])))


class HostError(RuntimeError):
    pass


class ToolHost:
    """Clientul din procesul API: pornește gazda unui job și îi trimite apeluri, oprit de cancel/timeout."""

    SECRETS = ("FAL_KEY", "REPLICATE_API_TOKEN", "VEDIT_LLM_API_KEY", "VEDIT_LLM_HEADERS", "VEDIT_API_TOKEN",
               "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY")

    def __init__(self, project: str, allow_generation: bool = False, log: Path | None = None):
        from .runners import agent_env

        env = {k: v for k, v in os.environ.items() if k not in self.SECRETS}
        env.update(agent_env(project, allow_generation))
        root = str(Path(__file__).resolve().parents[2])  # pachetul vedit din care rulează API-ul
        env["PYTHONPATH"] = os.pathsep.join(x for x in (root, env.get("PYTHONPATH")) if x)
        self._log = open(log, "ab") if log else subprocess.DEVNULL
        self.proc = subprocess.Popen([sys.executable, "-m", "vedit.api.toolhost"], env=env, cwd=root,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                                     text=True, encoding="utf-8", start_new_session=True)
        self._q: queue.Queue = queue.Queue()
        self._n = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            try:
                self._q.put(json.loads(line))
            except json.JSONDecodeError:
                continue
        self._q.put(None)  # procesul s-a închis

    def request(self, msg: dict, cancel: threading.Event | None = None, deadline: float | None = None):
        self._n += 1
        rid = self._n
        try:
            self.proc.stdin.write(json.dumps({"id": rid, **msg}, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            raise HostError("gazda de tool-uri s-a oprit neașteptat") from None
        while True:
            if cancel is not None and cancel.is_set():
                self.close()
                raise HostError("anulat")
            if deadline is not None and time.monotonic() > deadline:
                self.close()
                raise HostError("timeout")
            try:
                resp = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            if resp is None:
                raise HostError(f"gazda de tool-uri s-a oprit (cod {self.proc.poll()})")
            if resp.get("id") == rid:
                return resp.get("result")

    def list(self) -> list[dict]:
        return self.request({"op": "list"}, deadline=time.monotonic() + 120)

    def call(self, name: str, args: dict, cancel=None, deadline=None) -> str:
        out = self.request({"name": name, "args": args}, cancel, deadline)
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)

    def _signal(self, sig) -> None:
        try:  # tot grupul: și ffmpeg-ul pornit de un render lung
            os.killpg(self.proc.pid, sig)
        except (ProcessLookupError, PermissionError, AttributeError):
            self.proc.send_signal(sig)

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            self._signal(signal.SIGTERM)
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self._signal(signal.SIGKILL)
                self.proc.wait()
        if self._log is not subprocess.DEVNULL and not self._log.closed:
            self._log.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


if __name__ == "__main__":
    main()
