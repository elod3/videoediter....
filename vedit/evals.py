"""Evaluare pe clipuri reale: rulezi agentul pe un set de cazuri și măsori obiectiv rezultatul.

Folosire:
    vedit-eval evals/                    # rulează toate cazurile cu runner-ul implicit
    vedit-eval evals/ --runner scripted  # sau claude-code / llm
    vedit-eval evals/ --only vlog1       # un singur caz

Un caz = un folder cu `case.json` și fișierele lui:
    {
      "prompt": "Pentru TikTok: fără pauze, 9:16, subtitrări",
      "assets": ["vlog.mp4", "muzica.mp3"],          // în ordine: a0, a1, ...
      "roles": {"a1": "reference"},                  // opțional
      "transcripts": {"a0": "transcript.json"},     // opțional: Transcript JSON (dacă n-ai whisper)
      "allow_generation": false,
      "expect": {
        "format": "9:16", "duration_min": 10, "duration_max": 60,
        "captions": true, "qa_ok": true, "max_midword_cuts": 0,
        "must_call": ["cut_silences"], "must_not_call": ["broll_generate"],
        "max_seconds": 300
      }
    }
Raportul (Markdown + JSON) arată fiecare verificare trecută sau picată, plus timpul și numărul de pași.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path

from pydantic import BaseModel

from .project import Project, home
from .transcribe import Transcript


class Check(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class CaseResult(BaseModel):
    case: str
    status: str
    seconds: float
    tool_calls: int
    tools: list[str]
    security_events: int
    checks: list[Check]
    final_text: str = ""
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "done" and all(c.ok for c in self.checks)


def midword_cuts(p: Project, aid: str) -> int:
    """Tăieturi care cad în interiorul unui cuvânt (se aude ca o silabă mâncată)."""
    f = p.dir / "cache" / f"{aid}.transcript.json"
    if not f.exists():
        return -1
    words = Transcript.model_validate_json(f.read_text()).words
    bad = 0
    for c in p.tl.clips:
        if c.asset != aid:
            continue
        for edge in (c.src_in, c.src_out):
            if any(w.start + 0.04 < edge < w.end - 0.04 for w in words):
                bad += 1
    return bad


def evaluate(case_dir: Path, runner, workroot: Path) -> CaseResult:
    spec = json.loads((case_dir / "case.json").read_text())
    name = case_dir.name
    exp = spec.get("expect", {})
    pname = "eval-" + "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name)[:50]
    pdir = workroot / pname
    if pdir.exists():
        shutil.rmtree(pdir)
    p = Project(pname)
    up = p.dir / "uploads"
    up.mkdir(exist_ok=True)
    for i, a in enumerate(spec["assets"]):
        dst = up / Path(a).name
        shutil.copy(case_dir / a, dst)
        p.add_asset(str(dst), f"a{i}")
    for aid, role in spec.get("roles", {}).items():
        p.set_role(aid, role)
    for aid, tfile in spec.get("transcripts", {}).items():
        p.set_transcript(aid, Transcript.model_validate_json((case_dir / tfile).read_text()))

    events: list[tuple[str, dict]] = []
    cancel = threading.Event()
    limit = float(exp.get("max_seconds", 900))
    timer = threading.Timer(limit, cancel.set)
    timer.start()
    t0 = time.monotonic()
    status, final, error = "done", "", ""
    try:
        final, _ = runner.run(pname, spec["prompt"], lambda t, d: events.append((t, d)), cancel,
                              None, allow_generation=bool(spec.get("allow_generation")))
    except Exception as e:  # un caz picat nu oprește evaluarea
        status, error = ("timeout" if cancel.is_set() else "error"), str(e)
    finally:
        timer.cancel()
    secs = round(time.monotonic() - t0, 1)
    p = Project(pname)  # reîncarcă starea scrisă de agent
    tools = [d.get("name", "") for t, d in events if t == "tool"]
    checks: list[Check] = []
    tl = p.tl

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append(Check(name=name, ok=bool(ok), detail=detail))

    if "format" in exp:
        from .timeline import FORMATS
        want = FORMATS[exp["format"]]
        add(f"format {exp['format']}", (tl.width, tl.height) == want, f"{tl.width}x{tl.height}")
    if "duration_min" in exp or "duration_max" in exp:
        lo, hi = exp.get("duration_min", 0), exp.get("duration_max", 1e9)
        add(f"durată {lo}-{hi}s", lo <= tl.duration <= hi, f"{tl.duration:.1f}s")
    if "captions" in exp:
        add("subtitrări" if exp["captions"] else "fără subtitrări", bool(tl.captions) == exp["captions"],
            f"{len(tl.captions)} blocuri")
    renders = sorted((p.dir / "renders").glob("*.mp4"))
    if exp.get("qa_ok", True):
        if renders:
            qa = p.qa(str(max(renders, key=lambda f: f.stat().st_mtime)))
            add("QA ok", qa["ok"], "; ".join(qa["issues"]) or "fără probleme")
        else:
            add("QA ok", False, "niciun render")
    if "max_midword_cuts" in exp:
        n = midword_cuts(p, "a0")
        add(f"tăieturi în cuvânt ≤ {exp['max_midword_cuts']}", n <= exp["max_midword_cuts"] if n >= 0 else True,
            "fără transcript" if n < 0 else str(n))
    for t in exp.get("must_call", []):
        add(f"a folosit {t}", t in tools)
    for t in exp.get("must_not_call", []):
        add(f"NU a folosit {t}", t not in tools)
    return CaseResult(case=name, status=status, seconds=secs, tool_calls=len(tools), tools=tools,
                      security_events=sum(1 for t, _ in events if t == "security"), checks=checks,
                      final_text=final[:600], error=error[:400])


def report(results: list[CaseResult]) -> str:
    ok = sum(r.passed for r in results)
    lines = [f"# Evaluare vedit: {ok}/{len(results)} cazuri trecute", "",
             "| caz | status | verificări | timp | pași | securitate |", "|---|---|---|---|---|---|"]
    for r in results:
        passed = sum(c.ok for c in r.checks)
        lines.append(f"| {r.case} | {'✅' if r.passed else '❌'} {r.status} | {passed}/{len(r.checks)} | "
                     f"{r.seconds:.0f}s | {r.tool_calls} | {r.security_events} |")
    for r in results:
        lines += ["", f"## {r.case}", ""]
        lines += [f"- {'✅' if c.ok else '❌'} {c.name}" + (f": {c.detail}" if c.detail else "") for c in r.checks]
        if r.error:
            lines.append(f"- eroare: {r.error}")
        if r.tools:
            lines.append(f"- pași: {' → '.join(r.tools)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from .api.runners import ClaudeCodeRunner, ScriptedRunner, default_runner

    ap = argparse.ArgumentParser(prog="vedit-eval", description="Evaluează agentul pe un set de cazuri.")
    ap.add_argument("cases", help="folder cu subfoldere de cazuri (fiecare cu case.json)")
    ap.add_argument("--runner", default=os.environ.get("VEDIT_RUNNER", "auto"))
    ap.add_argument("--only", default="")
    ap.add_argument("--out", default="eval-report")
    args = ap.parse_args(argv)
    runner = {"scripted": ScriptedRunner, "claude-code": ClaudeCodeRunner}.get(args.runner)
    if args.runner == "llm":
        from .api.llm_runner import LLMRunner  # disponibil când e instalat runner-ul de producție
        runner = LLMRunner
    runner = runner() if runner else default_runner()
    cases = sorted(d for d in Path(args.cases).iterdir() if (d / "case.json").exists()
                   and (not args.only or d.name == args.only))
    if not cases:
        print("niciun caz găsit (fiecare caz = folder cu case.json)", file=sys.stderr)
        return 2
    results = []
    for c in cases:
        print(f"→ {c.name} ...", flush=True)
        r = evaluate(c, runner, home())
        print(f"  {'✅' if r.passed else '❌'} {sum(x.ok for x in r.checks)}/{len(r.checks)} în {r.seconds:.0f}s")
        results.append(r)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    (out / "report.md").write_text(report(results))
    (out / "results.json").write_text(json.dumps([r.model_dump() for r in results], ensure_ascii=False, indent=2))
    print(f"\nraport: {out / 'report.md'}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
