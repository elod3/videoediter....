"""Worker de joburi în proces (thread-uri). Un singur job activ per proiect, ca să nu se calce pe timeline.

Pentru scalare: aceeași logică într-un proces separat care citește coada (Redis/arq) — API-ul nu se schimbă.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from collections import defaultdict
from pathlib import Path
from typing import Callable

from ..project import Project, home
from .db import DB
from .runners import Runner


class Worker:
    def __init__(self, db: DB, runner: Runner, threads: int = 2):
        self.db = db
        self.runner = runner
        self.q: queue.Queue[str] = queue.Queue()
        self.cancels: dict[str, threading.Event] = {}
        self.locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        # apelat când un job reușit a produs renders/final.mp4 nou (taxarea în credite); întoarce un mesaj sau None
        self.on_final: Callable[[dict, Path], str | None] | None = None
        for _ in range(threads):
            threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, project: str, kind: str, prompt: str = "", allow_generation: bool = False,
               user_id: int | None = None) -> dict:
        job = self.db.create_job(project, kind, prompt, self.runner.name if kind == "agent" else "", allow_generation,
                                 user_id)
        self.cancels[job["id"]] = threading.Event()
        self.db.emit(job["id"], "status", {"message": "în coadă"})
        self.q.put(job["id"])
        return job

    def cancel(self, jid: str) -> bool:
        ev = self.cancels.get(jid)
        if ev is None:
            return False
        ev.set()
        return True

    def _loop(self) -> None:
        while True:
            jid = self.q.get()
            job = self.db.job(jid)
            if job is None:
                continue
            with self.locks[job["project"]]:
                self._run(job)

    def _run(self, job: dict) -> None:
        jid, project = job["id"], job["project"]
        cancel = self.cancels.setdefault(jid, threading.Event())
        if cancel.is_set():
            self.db.update_job(jid, status="cancelled", finished=time.time())
            self.db.emit(jid, "done", {"status": "cancelled"})
            return
        self.db.update_job(jid, status="running", started=time.time())
        self.db.emit(jid, "status", {"message": "rulează"})
        emit = lambda type_, data: self.db.emit(jid, type_, data)  # noqa: E731
        final = home() / project / "renders" / "final.mp4"
        mtime = lambda: final.stat().st_mtime_ns if final.exists() else None  # noqa: E731
        before = mtime()
        try:
            if job["kind"] == "agent":
                session = self.db.session(project, self.runner.name)
                result, sid = self.runner.run(project, job["prompt"], emit, cancel, session,
                                              allow_generation=bool(job.get("allow_gen")))
                if sid:
                    self.db.set_session(project, self.runner.name, sid)
                emit("text", {"text": result, "final": True})
            elif job["kind"] == "render":
                preview = job["prompt"] != "final"
                out = Project(project).render(preview=preview)
                result = f"{'preview' if preview else 'final'} randat: {out['duration']:.1f}s"
            else:
                raise ValueError(f"tip de job necunoscut: {job['kind']}")
            if self.on_final and final.exists() and (job["prompt"] == "final" if job["kind"] == "render"
                                                     else mtime() != before):
                try:
                    if msg := self.on_final(job, final):
                        emit("status", {"message": msg})
                except Exception as e:  # taxarea nu strică un export reușit
                    emit("status", {"message": f"nu am putut calcula creditele: {e}"})
            self.db.update_job(jid, status="done", result=result, finished=time.time())
            emit("done", {"status": "done", "result": result})
        except Exception as e:
            status = "cancelled" if cancel.is_set() else "error"
            self.db.update_job(jid, status=status, error=str(e), finished=time.time())
            emit("error", {"message": str(e), "trace": traceback.format_exc(limit=3)})
            emit("done", {"status": status})
        finally:
            self.cancels.pop(jid, None)
