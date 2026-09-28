"""Worker de joburi în proces (thread-uri). Un singur job activ per proiect, ca să nu se calce pe timeline.

Pentru scalare: aceeași logică într-un proces separat care citește coada (Redis/arq) — API-ul nu se schimbă.
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from collections import defaultdict

from ..project import Project
from .db import DB
from .runners import Runner


class Worker:
    def __init__(self, db: DB, runner: Runner, threads: int = 2):
        self.db = db
        self.runner = runner
        self.q: queue.Queue[str] = queue.Queue()
        self.cancels: dict[str, threading.Event] = {}
        self.locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
        for _ in range(threads):
            threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, project: str, kind: str, prompt: str = "") -> dict:
        job = self.db.create_job(project, kind, prompt, self.runner.name if kind == "agent" else "")
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
        try:
            if job["kind"] == "agent":
                session = self.db.session(project, self.runner.name)
                result, sid = self.runner.run(project, job["prompt"], emit, cancel, session)
                if sid:
                    self.db.set_session(project, self.runner.name, sid)
                emit("text", {"text": result, "final": True})
            elif job["kind"] == "render":
                preview = job["prompt"] != "final"
                out = Project(project).render(preview=preview)
                result = f"{'preview' if preview else 'final'} randat: {out['duration']:.1f}s"
            else:
                raise ValueError(f"tip de job necunoscut: {job['kind']}")
            self.db.update_job(jid, status="done", result=result, finished=time.time())
            emit("done", {"status": "done", "result": result})
        except Exception as e:
            status = "cancelled" if cancel.is_set() else "error"
            self.db.update_job(jid, status=status, error=str(e), finished=time.time())
            emit("error", {"message": str(e), "trace": traceback.format_exc(limit=3)})
            emit("done", {"status": status})
        finally:
            self.cancels.pop(jid, None)
