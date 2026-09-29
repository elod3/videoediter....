"""Agenții care execută un job. Interfață comună => schimbi creierul fără să atingi site-ul.

* ClaudeCodeRunner — pornește Claude Code local în mod headless (`claude -p`), pe abonamentul tău,
  cu DOAR tool-urile vedit + skill-urile din repo. Bun pentru test; pentru clienți reali => alt runner.
* ScriptedRunner  — pipeline fix, fără AI (teste, demo, fallback când `claude` nu e instalat).
* Hermes / OpenClaw / API — implementează aceeași metodă `run` (vezi docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable, Protocol

from ..project import Project, home

Emit = Callable[[str, dict], None]

SKILLS_DIR = Path(os.environ.get("VEDIT_SKILLS_DIR", Path(__file__).resolve().parents[2] / "skills"))


class Runner(Protocol):
    name: str

    def run(self, project: str, prompt: str, emit: Emit, cancel: threading.Event,
            session: str | None = None) -> tuple[str, str | None]:
        """Execută cererea. Returnează (mesaj final pentru utilizator, id sesiune pentru continuare)."""


def pretty(name: str, text: str) -> str:
    """Rezultatele JSON ale tool-urilor, pe o linie citibilă pentru jurnalul din UI (fără căi interne)."""
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text
    if not isinstance(d, dict):
        return text
    if name == "render" and "duration" in d:
        return f"{'preview' if d.get('preview') else 'final'} · {d['duration']:.1f} s"
    if name == "qa_check" and "ok" in d:
        loud = d.get("loudness") or {}
        lufs = f" · {loud['lufs']:.1f} LUFS" if "lufs" in loud else ""
        return f"ok · {d.get('resolution', '')}{lufs}" if d["ok"] else "probleme: " + "; ".join(d.get("issues", []))
    if name == "media_analyze" and "duration" in d:
        parts = [f"{d['duration']:.1f} s"]
        if "silence_total" in d:
            parts.append(f"pauze {d['silence_total']:.1f} s")
        if "lufs" in (d.get("loudness") or {}):
            parts.append(f"{d['loudness']['lufs']:.1f} LUFS")
        if d.get("scene_cuts"):
            parts.append(f"{len(d['scene_cuts'])} tăieturi de scenă")
        return " · ".join(parts)
    if name == "frames_look" and "image" in d:
        return f"contact sheet cu {len(d.get('cells_left_to_right_top_to_bottom', []))} cadre"
    return text


def _short(obj, limit: int = 300) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "…"


# ---------------------------------------------------------------- Claude Code
SYSTEM = """Ești editorul video AI al platformei vedit. Lucrezi DOAR prin tool-urile MCP `vedit`
(mcp__vedit__*) și skill-urile disponibile. Nu ai acces la terminal și nu scrii cod.

Reguli:
- Proiectul curent este `{project}`. Pune `project="{project}"` la FIECARE apel de tool.
- Începe cu skill-urile `edit-brief` și `video-editor-core` și urmează-le.
- Pentru imagini returnate de `frames_look`, deschide calea cu Read doar când decizia depinde de imagine.
- Termină cu `render(preview=true)` și `qa_check` pe preview. Randează final (`preview=false`) doar dacă
  utilizatorul cere explicit versiunea finală / export.
- Răspunsul final: în română, 3-6 rânduri: ce ai făcut, durata, ce ar mai putea fi îmbunătățit.
"""


class ClaudeCodeRunner:
    name = "claude-code"

    def __init__(self, binary: str | None = None, model: str | None = None, max_turns: int = 60):
        self.binary = binary or os.environ.get("VEDIT_CLAUDE_BIN", "claude")
        self.model = model or os.environ.get("VEDIT_CLAUDE_MODEL")
        self.max_turns = max_turns

    @staticmethod
    def available() -> bool:
        return shutil.which(os.environ.get("VEDIT_CLAUDE_BIN", "claude")) is not None

    def _workdir(self) -> Path:
        """Director de lucru pentru agent: skill-urile vedit în .claude/skills + config MCP."""
        wd = home() / ".agent"
        (wd / ".claude").mkdir(parents=True, exist_ok=True)
        link = wd / ".claude" / "skills"
        if not link.exists():
            link.symlink_to(SKILLS_DIR, target_is_directory=True)
        cfg = {"mcpServers": {"vedit": {"command": sys.executable, "args": ["-m", "vedit.mcp_server"],
                                        "env": {"VEDIT_HOME": str(home())}}}}
        (wd / "mcp.json").write_text(json.dumps(cfg, indent=2))
        return wd

    def command(self, project: str, prompt: str, session: str | None) -> tuple[list[str], Path]:
        wd = self._workdir()
        assets = Project(project).list_assets()
        full = f"Proiect: {project}\nAsset-uri:\n{assets}\n\nCererea utilizatorului:\n{prompt}"
        cmd = [self.binary, "-p", full, "--output-format", "stream-json", "--verbose",
               "--mcp-config", str(wd / "mcp.json"), "--strict-mcp-config",
               "--append-system-prompt", SYSTEM.format(project=project),
               "--max-turns", str(self.max_turns),
               # doar tool-urile vedit, skill-uri și citirea imaginilor din proiecte — fără Bash/Write/Edit
               "--allowedTools", "mcp__vedit", "Skill", f"Read(/{home()}/**)"]
        if self.model:
            cmd += ["--model", self.model]
        if session:
            cmd += ["--resume", session]
        return cmd, wd

    def run(self, project, prompt, emit, cancel, session=None):
        cmd, wd = self.command(project, prompt, session)
        proc = subprocess.Popen(cmd, cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                stdin=subprocess.DEVNULL)
        stop = threading.Event()

        def watch():  # anularea din UI oprește procesul
            while not stop.is_set():
                if cancel.wait(0.5):
                    proc.terminate()
                    return

        threading.Thread(target=watch, daemon=True).start()
        final, sid = "", session
        names: dict[str, str] = {}  # tool_use_id -> nume, ca să formatăm rezultatul potrivit
        try:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # ID-ul sesiunii de reluat: doar din init/result (alte evenimente pot purta alt id)
                if ev.get("type") == "result" or (ev.get("type") == "system" and ev.get("subtype") == "init"):
                    sid = ev.get("session_id") or sid
                final = self._handle(ev, emit, names) or final
            proc.wait()
        finally:
            stop.set()
            if proc.poll() is None:
                proc.terminate()
        if cancel.is_set():
            raise RuntimeError("anulat")
        if proc.returncode != 0 and not final:
            err = proc.stderr.read().strip().splitlines()[-5:]
            raise RuntimeError("Claude Code a eșuat: " + " | ".join(err) if err else f"cod {proc.returncode}")
        return final, sid

    @staticmethod
    def _handle(ev: dict, emit: Emit, names: dict[str, str] | None = None) -> str | None:
        names = {} if names is None else names
        t = ev.get("type")
        if t == "system" and ev.get("subtype") == "init":
            servers = {s.get("name"): s.get("status") for s in ev.get("mcp_servers", [])}
            if servers.get("vedit") not in (None, "connected"):
                emit("error", {"message": f"serverul MCP vedit: {servers.get('vedit')}"})
            emit("status", {"message": "agentul a pornit", "model": ev.get("model", "")})
        elif t == "assistant":
            for b in ev.get("message", {}).get("content", []):
                if b.get("type") == "text" and b.get("text", "").strip():
                    emit("text", {"text": b["text"]})
                elif b.get("type") == "tool_use":
                    name = re.sub(r"^mcp__vedit__", "", b.get("name", ""))
                    names[b.get("id", "")] = name
                    args = {k: v for k, v in (b.get("input") or {}).items() if k != "project"}
                    emit("tool", {"name": name, "input": _short(args, 200)})
        elif t == "user":
            for b in ev.get("message", {}).get("content", []):
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    c = b.get("content")
                    if isinstance(c, list):
                        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                    try:  # MCP 2.x învelește textul în {"result": "..."} — pentru UI arătăm doar textul
                        inner = json.loads(c or "")
                        if isinstance(inner, dict) and set(inner) == {"result"}:
                            c = str(inner["result"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                    c = pretty(names.get(b.get("tool_use_id", ""), ""), c or "")
                    emit("tool_result", {"text": _short(c), "error": bool(b.get("is_error"))})
        elif t == "result":
            if ev.get("is_error") or ev.get("subtype") != "success":
                raise RuntimeError(f"agentul s-a oprit: {ev.get('subtype')} {_short(ev.get('result', ''))}")
            emit("status", {"message": "agentul a terminat", "turns": ev.get("num_turns"),
                            "cost_usd": ev.get("total_cost_usd")})
            return ev.get("result", "")
        return None


# ---------------------------------------------------------------- fără AI
class ScriptedRunner:
    """Pipeline determinist ghidat de cuvinte-cheie. Fără LLM: util pentru teste și demo."""
    name = "scripted"

    def run(self, project, prompt, emit, cancel, session=None):
        p = Project(project)
        low = prompt.lower()
        videos = [k for k, v in p.s.assets.items() if v.has_video]
        audios = [k for k, v in p.s.assets.items() if v.has_audio and not v.has_video]
        if not videos:
            raise ValueError("încarcă întâi un video")
        done: list[str] = []

        def step(name: str, fn, *a, **kw):
            if cancel.is_set():
                raise RuntimeError("anulat")
            emit("tool", {"name": name, "input": _short({k: v for k, v in kw.items()}, 200)})
            try:
                out = fn(*a, **kw)
            except Exception as e:
                emit("tool_result", {"text": f"EROARE: {e}", "error": True})
                return None
            text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
            emit("tool_result", {"text": _short(pretty(name, text)), "error": False})
            return out

        a0 = videos[0]
        if any(k in low for k in ("paus", "liniș", "silence", "dinamic", "jump", "tiktok", "reels", "shorts", "curăț")):
            before = p.s.assets[a0].duration
            step("cut_silences", p.auto_cut_silence, a0)
            cut = before - p.tl.duration
            done.append(f"am scos {cut:.1f} s de pauze" if cut >= 0.1 else "nu erau pauze de scos")
        elif not p.tl.clips:
            for v in videos:
                step("clip_add", p.add_clip, v, 0, p.s.assets[v].duration)
        fmt = next((f for k, f in (("9:16", "9:16"), ("tiktok", "9:16"), ("reels", "9:16"), ("shorts", "9:16"),
                                   ("vertical", "9:16"), ("1:1", "1:1"), ("pătrat", "1:1"), ("4:5", "4:5"),
                                   ("16:9", "16:9"), ("youtube", "16:9")) if k in low), None)
        if fmt:
            step("timeline_format", p.set_format, fmt)
            done.append(f"format {fmt}")
            if fmt != "16:9":
                if step("auto_reframe", p.auto_reframe, punch_in=0.15 if "tiktok" in low else 0.0) is not None:
                    done.append("încadrare automată pe fețe")
        if any(k in low for k in ("subtitr", "caption", "tiktok", "reels", "shorts")):
            style = "karaoke" if "karaoke" in low else "bold_center" if fmt in ("9:16", "1:1", "4:5") else "classic_bottom"
            if step("captions_add", p.captions, a0, style=style) is not None:
                done.append(f"subtitrări {style}")
        if audios and any(k in low for k in ("muzic", "music")):
            step("music_set", p.set_music, audios[0])
            done.append("muzică cu ducking")
        final = "final" in low or "export" in low
        out = step("render", p.render, preview=not final)
        if out is None:
            raise RuntimeError("randarea a eșuat")
        qa = step("qa_check", p.qa, out["path"])
        msg = f"Gata, fără AI: {', '.join(done) or 'montaj simplu'}. Durata finală: {p.tl.duration:.1f} s."
        if qa and not qa["ok"]:
            msg += " Probleme QA: " + "; ".join(qa["issues"])
        return msg, None


def default_runner() -> Runner:
    choice = os.environ.get("VEDIT_RUNNER", "auto")
    if choice == "claude-code" or (choice == "auto" and ClaudeCodeRunner.available()):
        return ClaudeCodeRunner()
    return ScriptedRunner()
