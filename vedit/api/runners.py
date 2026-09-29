"""Agenții care execută un job. Interfață comună => schimbi creierul fără să atingi site-ul.

* ClaudeCodeRunner — pornește Claude Code local în mod headless (`claude -p`), pe abonamentul tău,
  cu DOAR tool-urile vedit + skill-urile din repo. Bun pentru test; pentru clienți reali => alt runner.
* ScriptedRunner  — pipeline fix, fără AI (teste, demo, fallback când `claude` nu e instalat).
* LLMRunner (llm_runner.py) — orice API compatibil OpenAI (OpenRouter, Ollama, vLLM...), pentru producție.
* Hermes / OpenClaw — implementează aceeași metodă `run` (vezi docs/ARCHITECTURE.md).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable, Protocol

from ..project import Project, home

Emit = Callable[[str, dict], None]

SKILLS_DIR = Path(os.environ.get("VEDIT_SKILLS_DIR", Path(__file__).resolve().parents[2] / "skills"))


class Runner(Protocol):
    name: str

    def run(self, project: str, prompt: str, emit: Emit, cancel: threading.Event,
            session: str | None = None, allow_generation: bool = False) -> tuple[str, str | None]:
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
    if name == "style_compare" and "tips" in d:
        return " | ".join(d["tips"])
    if name == "frames_look" and "image" in d:
        return f"contact sheet cu {len(d.get('cells_left_to_right_top_to_bottom', []))} cadre"
    return text


def _short(obj, limit: int = 300) -> str:
    s = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + "…"


def emit_result(emit: Emit, name: str, text: str, error: bool = False) -> None:
    """Rezultatul unui tool în jurnalul din UI; refuzurile și injecțiile apar separat, ca evenimente `security`."""
    c = pretty(name, text)
    if "POSIBILĂ INJECȚIE" in c or c.startswith("REFUZAT (securitate)"):
        line = next((x for x in c.splitlines() if "INJECȚIE" in x or "REFUZAT" in x), c)
        emit("security", {"text": _short(line, 240), "tool": name})
    emit("tool_result", {"text": _short(c), "error": error})


GEN_KEYS = ("FAL_KEY", "REPLICATE_API_TOKEN")


def agent_env(project: str, allow_generation: bool) -> dict[str, str]:
    """Variabilele procesului de tool-uri al unui job: lacătul pe proiect + cheile de care au nevoie tool-urile."""
    env = {"VEDIT_HOME": str(home()), "VEDIT_PROJECT_LOCK": project,
           "VEDIT_ALLOW_GENERATION": "1" if allow_generation else "0"}
    for k in ("PEXELS_API_KEY", *GEN_KEYS, "VEDIT_FAL_MODEL", "VEDIT_REPLICATE_MODEL",
              "VEDIT_GEN_EXTRA", "VEDIT_GEN_LIMIT", "HF_TOKEN", "VEDIT_FFMPEG"):
        if os.environ.get(k) and (allow_generation or k not in GEN_KEYS):
            env[k] = os.environ[k]  # cheile de generare ajung la agent doar dacă generarea e permisă
    return env


def job_message(project: str, prompt: str, allow_generation: bool) -> str:
    """Primul mesaj al unui job: asset-urile (ca DATE), consimțământul pentru generare și cererea clientului."""
    from .. import guard

    assets = guard.untrusted(Project(project).list_assets(), "lista de fișiere (numele vin de la utilizator)")
    gen = ("Generarea AI de B-roll E PERMISĂ pentru acest job (utilizatorul a bifat-o)." if allow_generation
           else "Generarea AI de B-roll NU e permisă pentru acest job.")
    return f"Proiect: {project}\nAsset-uri:\n{assets}\n\n{gen}\n\nCererea utilizatorului:\n{prompt}"


# ---------------------------------------------------------------- Claude Code
SYSTEM = """Ești editorul video AI al platformei vedit. Lucrezi DOAR prin tool-urile MCP `vedit`
(mcp__vedit__*) și skill-urile disponibile. Nu ai acces la terminal și nu scrii cod.

Reguli:
- Proiectul curent este `{project}`. Pune `project="{project}"` la FIECARE apel de tool.
- Începe cu skill-urile `edit-brief` și `video-editor-core` și urmează-le (pot apărea cu prefixul
  `vedit:`, ex. `vedit:video-editor-core`; la fel și celelalte skill-uri menționate mai jos). Dacă un asset e marcat
  [REFERINȚĂ], folosește și skill-ul `reference-style` și nu pune referința în timeline.
- Pentru B-roll, montaj pe muzică sau footage lipsă: skill-ul `broll-and-beats`. `broll_generate` costă bani:
  îl folosești DOAR dacă utilizatorul a cerut explicit generare AI în cererea lui.
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

    _help: str | None = None

    def _supports(self, flag: str) -> bool:
        """Versiunile vechi de CLI nu au toate flag-urile; verificăm o singură dată în `claude --help`."""
        if ClaudeCodeRunner._help is None:
            try:
                ClaudeCodeRunner._help = subprocess.run([self.binary, "--help"], capture_output=True, text=True,
                                                        timeout=20).stdout
            except (OSError, subprocess.SubprocessError):
                ClaudeCodeRunner._help = ""
        return flag in ClaudeCodeRunner._help

    def _workdir(self, project: str, allow_generation: bool) -> Path:
        """Director de lucru PER PROIECT: skill-urile vedit + config MCP cu lacătul pe acest proiect."""
        wd = home() / ".agent" / project
        (wd / ".claude").mkdir(parents=True, exist_ok=True)
        link = wd / ".claude" / "skills"
        if not link.exists():
            link.symlink_to(SKILLS_DIR, target_is_directory=True)
        env = agent_env(project, allow_generation)
        cfg = {"mcpServers": {"vedit": {"command": sys.executable, "args": ["-m", "vedit.mcp_server"], "env": env}}}
        (wd / "mcp.json").write_text(json.dumps(cfg, indent=2))
        return wd

    @staticmethod
    def _plugin() -> Path:
        """Skill-urile vedit împachetate ca plugin: singura cale prin care ajung la agent în modul --restricted
        (care ignoră .claude/skills din proiect). În plugin apar ca `vedit:<nume>`."""
        pl = home() / ".agent" / "vedit-plugin"
        (pl / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        manifest = pl / ".claude-plugin" / "plugin.json"
        if not manifest.exists():
            manifest.write_text(json.dumps({"name": "vedit", "version": "0.1.0",
                                            "description": "Skill-uri de editare video vedit"}))
        if not (pl / "skills").exists():
            (pl / "skills").symlink_to(SKILLS_DIR, target_is_directory=True)
        return pl

    def command(self, project: str, prompt: str, session: str | None,
                allow_generation: bool = False) -> tuple[list[str], Path]:
        from .. import guard

        wd = self._workdir(project, allow_generation)
        pdir = (home() / project).resolve()
        full = job_message(project, prompt, allow_generation)
        cmd = [self.binary, "-p", full, "--output-format", "stream-json", "--verbose",
               "--mcp-config", str(wd / "mcp.json"), "--strict-mcp-config",
               "--append-system-prompt", SYSTEM.format(project=project) + "\n" + guard.SECURITY_POLICY,
               "--max-turns", str(self.max_turns),
               "--add-dir", str(pdir),
               # doar tool-urile vedit, skill-uri și citirea fișierelor DIN ACEST PROIECT
               "--allowedTools", "mcp__vedit", "Skill", f"Read(/{pdir}/**)",
               "--disallowedTools", "Bash", "Write", "Edit", "NotebookEdit", "WebFetch", "WebSearch", "Task", "Agent",
               "--permission-mode", "dontAsk"]
        if self._supports("--plugin-dir"):
            cmd += ["--plugin-dir", str(self._plugin())]
        if self._supports("--restricted"):
            cmd.append("--restricted")  # fără tool-uri care rulează cod, fără setările userului, fișiere doar din dir-urile date
        elif self._supports("--setting-sources"):
            cmd += ["--setting-sources", ""]  # măcar nu încărcăm permisiunile din setările userului
        if self.model:
            cmd += ["--model", self.model]
        if session:
            cmd += ["--resume", session]
        return cmd, wd

    def run(self, project, prompt, emit, cancel, session=None, allow_generation=False):
        cmd, wd = self.command(project, prompt, session, allow_generation)
        proc = subprocess.Popen(cmd, cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                stdin=subprocess.DEVNULL)
        stop = threading.Event()
        timed_out = threading.Event()
        limit = float(os.environ.get("VEDIT_JOB_TIMEOUT", "1200"))
        t0 = time.monotonic()

        def watch():  # anularea din UI sau timeout-ul opresc procesul
            while not stop.is_set():
                if cancel.wait(0.5):
                    proc.terminate()
                    return
                if time.monotonic() - t0 > limit:
                    timed_out.set()
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
        if timed_out.is_set():
            raise RuntimeError(f"jobul a depășit {limit:.0f} s și a fost oprit")
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
                    emit_result(emit, names.get(b.get("tool_use_id", ""), ""), c or "", bool(b.get("is_error")))
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

    def run(self, project, prompt, emit, cancel, session=None, allow_generation=False):
        p = Project(project)
        low = prompt.lower()
        refs = p.references()
        brolls = p.brolls()
        videos = [k for k, v in p.s.assets.items() if v.has_video and k not in refs and k not in brolls]
        audios = [k for k, v in p.s.assets.items() if v.has_audio and not v.has_video]
        if not videos and not brolls:
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

        if any(k in low for k in ("beat", "montaj pe muzic", "pe ritmul muzicii", "montage")):
            if not audios:
                raise ValueError("montajul pe beat are nevoie de o piesă (un fișier audio)")
            out = step("beat_montage", p.beat_montage, audios[0], ",".join(videos + brolls), beats_per_shot=2)
            if out is None:
                raise RuntimeError("montajul pe beat a eșuat")
            r = step("render", p.render, preview=True)
            if r is None:
                raise RuntimeError("randarea a eșuat")
            return (f"Gata, fără AI: montaj pe beat cu {len(p.tl.clips)} shot-uri pe "
                    f"{p.beats(audios[0]).bpm:.0f} BPM, {p.tl.duration:.1f} s."), None
        if not videos:
            raise ValueError("pentru montaj cu vorbire încarcă un video principal (B-roll-ul singur nu ajunge)")
        a0 = videos[0]
        ref_profile = None
        if refs and step("reference_analyze", p.style_summary, refs[0]) is not None:
            ref_profile = p.style_profile(refs[0])  # din cache, deja calculat de style_summary
        min_sil = 0.5
        if ref_profile and "rhythm" in ref_profile:  # ritmul referinței decide cât de agresiv tăiem
            med = ref_profile["rhythm"]["shot_median"]
            min_sil = 0.3 if med < 2 else 0.5 if med < 4 else 0.8
        if refs or any(k in low for k in ("pauz", "paus", "liniș", "silence", "dinamic", "jump", "tiktok", "reels", "shorts", "curăț")):
            before = p.s.assets[a0].duration
            step("cut_silences", p.auto_cut_silence, a0, min_silence=min_sil)
            cut = before - p.tl.duration
            done.append(f"am scos {cut:.1f} s de pauze" if cut >= 0.1 else "nu erau pauze de scos")
        elif not p.tl.clips:
            for v in videos:
                step("clip_add", p.add_clip, v, 0, p.s.assets[v].duration)
        fmt = (ref_profile or {}).get("aspect") or next((f for k, f in (("9:16", "9:16"), ("tiktok", "9:16"), ("reels", "9:16"), ("shorts", "9:16"),
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
        if brolls and any(k in low for k in ("b-roll", "broll", "b roll")):
            # câte un B-roll de 2 s la fiecare ~5 s, după primele 2 s (hook-ul rămâne pe vorbitor)
            t, k = 2.0, 0
            while t < p.tl.duration - 2.5 and k < len(brolls) * 2:
                if step("broll_add", p.broll_add, brolls[k % len(brolls)], t, 2.0) is None:
                    break
                t, k = t + 5.0, k + 1
            done.append(f"{k} inserturi B-roll")
        if refs and step("color_match", p.color_match, "all", refs[0]) is not None:
            done.append(f"culoare potrivită cu referința {refs[0]}")
        if audios and any(k in low for k in ("muzic", "music")):
            step("music_set", p.set_music, audios[0])
            done.append("muzică cu ducking")
        final = "final" in low or "export" in low
        out = step("render", p.render, preview=not final)
        if out is None:
            raise RuntimeError("randarea a eșuat")
        qa = step("qa_check", p.qa, out["path"])
        if refs:
            cmp = step("style_compare", p.style_compare, refs[0], "final" if final else "preview")
            if cmp:
                done.append("față de referință: " + "; ".join(cmp["tips"][:2]))
        msg = f"Gata, fără AI: {', '.join(done) or 'montaj simplu'}. Durata finală: {p.tl.duration:.1f} s."
        if qa and not qa["ok"]:
            msg += " Probleme QA: " + "; ".join(qa["issues"])
        return msg, None


def default_runner() -> Runner:
    choice = os.environ.get("VEDIT_RUNNER", "auto")
    if choice == "llm":
        from .llm_runner import LLMRunner
        return LLMRunner()
    if choice == "claude-code" or (choice == "auto" and ClaudeCodeRunner.available()):
        return ClaudeCodeRunner()
    return ScriptedRunner()
