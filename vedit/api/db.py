"""Stocare minimă în SQLite: joburi + evenimente (progres live pentru browser).

Proiectele (asset-uri, timeline) stau deja pe disc prin vedit.project; aici ținem doar
ce e specific web-ului. SQLite e suficient pentru un singur server; la scalare => Postgres.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  kind TEXT NOT NULL,            -- agent | render
  prompt TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,          -- queued | running | done | error | cancelled
  runner TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  allow_gen INTEGER NOT NULL DEFAULT 0,  -- utilizatorul a bifat generarea AI pentru acest job
  created REAL NOT NULL,
  started REAL,
  finished REAL
);
CREATE INDEX IF NOT EXISTS jobs_project ON jobs(project, created);
CREATE TABLE IF NOT EXISTS events (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  job TEXT NOT NULL,
  ts REAL NOT NULL,
  type TEXT NOT NULL,            -- status | text | tool | tool_result | error | done
  data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_job ON events(job, seq);
CREATE TABLE IF NOT EXISTS sessions (
  project TEXT PRIMARY KEY,      -- sesiunea agentului per proiect (pentru "mai scurt", "altă muzică")
  runner TEXT NOT NULL,
  session_id TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(jobs)")}
            if "allow_gen" not in cols:  # migrare pentru baze create înainte de coloană
                self._conn.execute("ALTER TABLE jobs ADD COLUMN allow_gen INTEGER NOT NULL DEFAULT 0")
            # joburile rămase "running" după un restart nu mai rulează
            self._conn.execute("UPDATE jobs SET status='error', error='server repornit' WHERE status IN ('running','queued')")

    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ---------- joburi ----------
    def create_job(self, project: str, kind: str, prompt: str = "", runner: str = "", allow_gen: bool = False) -> dict:
        jid = uuid.uuid4().hex[:12]
        self._q("INSERT INTO jobs(id, project, kind, prompt, status, runner, allow_gen, created) VALUES (?,?,?,?,?,?,?,?)",
                (jid, project, kind, prompt, "queued", runner, int(allow_gen), time.time()))
        return self.job(jid)

    def job(self, jid: str) -> dict | None:
        rows = self._q("SELECT * FROM jobs WHERE id=?", (jid,))
        return rows[0] if rows else None

    def jobs(self, project: str, limit: int = 50) -> list[dict]:
        return self._q("SELECT * FROM jobs WHERE project=? ORDER BY created DESC LIMIT ?", (project, limit))

    def update_job(self, jid: str, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        self._q(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), jid))

    # ---------- evenimente ----------
    def emit(self, jid: str, type_: str, data: dict | str) -> None:
        self._q("INSERT INTO events(job, ts, type, data) VALUES (?,?,?,?)",
                (jid, time.time(), type_, json.dumps(data, ensure_ascii=False)))

    def events(self, jid: str, after: int = 0) -> list[dict]:
        rows = self._q("SELECT seq, ts, type, data FROM events WHERE job=? AND seq>? ORDER BY seq", (jid, after))
        for r in rows:
            r["data"] = json.loads(r["data"])
        return rows

    # ---------- sesiuni agent ----------
    def session(self, project: str, runner: str) -> str | None:
        rows = self._q("SELECT session_id FROM sessions WHERE project=? AND runner=?", (project, runner))
        return rows[0]["session_id"] if rows else None

    def set_session(self, project: str, runner: str, session_id: str) -> None:
        self._q("INSERT OR REPLACE INTO sessions(project, runner, session_id) VALUES (?,?,?)",
                (project, runner, session_id))

    def clear_session(self, project: str) -> None:
        self._q("DELETE FROM sessions WHERE project=?", (project,))
