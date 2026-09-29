"""Stocare minimă în SQLite: joburi + evenimente (progres live pentru browser), plus conturi,
proprietatea proiectelor, credite și plăți (folosite doar cu VEDIT_AUTH=on).

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
  kind TEXT NOT NULL,            -- agent | render | export
  prompt TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,          -- queued | running | done | error | cancelled
  runner TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  allow_gen INTEGER NOT NULL DEFAULT 0,  -- utilizatorul a bifat generarea AI pentru acest job
  user_id INTEGER,               -- cine a pornit jobul (doar cu conturi)
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
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,    -- mereu lowercase
  pw TEXT NOT NULL,              -- scrypt$n$r$p$sare$hash
  created REAL NOT NULL,
  credits INTEGER NOT NULL DEFAULT 0  -- 1 credit = 1 minut început de video final exportat
);
CREATE TABLE IF NOT EXISTS user_sessions (
  token TEXT PRIMARY KEY,        -- sha256(token); tokenul în clar nu se salvează
  user_id INTEGER NOT NULL,
  expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
  storage TEXT PRIMARY KEY,      -- numele de pe disc (u{user}-{nume})
  owner INTEGER NOT NULL,
  display TEXT NOT NULL,         -- numele văzut de utilizator (în URL-uri)
  created REAL NOT NULL,
  UNIQUE(owner, display)
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  delta INTEGER NOT NULL,
  reason TEXT NOT NULL,
  job TEXT NOT NULL DEFAULT '',  -- job / sesiune Stripe
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ledger_user ON ledger(user_id, id);
CREATE TABLE IF NOT EXISTS stripe_events (
  id TEXT PRIMARY KEY,           -- idempotență: un eveniment Stripe se aplică o singură dată
  ts REAL NOT NULL
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
            if "user_id" not in cols:
                self._conn.execute("ALTER TABLE jobs ADD COLUMN user_id INTEGER")
            # joburile rămase "running" după un restart nu mai rulează
            self._conn.execute("UPDATE jobs SET status='error', error='server repornit' WHERE status IN ('running','queued')")

    def _q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    # ---------- joburi ----------
    def create_job(self, project: str, kind: str, prompt: str = "", runner: str = "", allow_gen: bool = False,
                   user_id: int | None = None) -> dict:
        jid = uuid.uuid4().hex[:12]
        self._q("INSERT INTO jobs(id, project, kind, prompt, status, runner, allow_gen, user_id, created) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (jid, project, kind, prompt, "queued", runner, int(allow_gen), user_id, time.time()))
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

    # ---------- conturi ----------
    def create_user(self, email: str, pw: str, credits: int) -> dict | None:
        """None dacă emailul există deja. Creditele gratuite intră și în registru."""
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                cur = c.execute("INSERT OR IGNORE INTO users(email, pw, created, credits) VALUES (?,?,?,?)",
                                (email, pw, time.time(), credits))
                if cur.rowcount == 0:
                    c.execute("ROLLBACK")
                    return None
                uid = cur.lastrowid
                if credits:
                    c.execute("INSERT INTO ledger(user_id, delta, reason, job, ts) VALUES (?,?,?,?,?)",
                              (uid, credits, "credite gratuite la înregistrare", "", time.time()))
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        return self.user(uid)

    def user(self, uid: int) -> dict | None:
        rows = self._q("SELECT * FROM users WHERE id=?", (uid,))
        return rows[0] if rows else None

    def user_by_email(self, email: str) -> dict | None:
        rows = self._q("SELECT * FROM users WHERE email=?", (email,))
        return rows[0] if rows else None

    def create_login(self, token_hash: str, uid: int, expires: float) -> None:
        self._q("INSERT INTO user_sessions(token, user_id, expires) VALUES (?,?,?)", (token_hash, uid, expires))

    def login_user(self, token_hash: str) -> dict | None:
        """Utilizatorul unei sesiuni valide (sesiunile expirate se șterg din mers)."""
        now = time.time()
        rows = self._q("SELECT u.* FROM user_sessions s JOIN users u ON u.id = s.user_id "
                       "WHERE s.token=? AND s.expires>?", (token_hash, now))
        if not rows:
            self._q("DELETE FROM user_sessions WHERE expires<=?", (now,))
        return rows[0] if rows else None

    def delete_login(self, token_hash: str) -> None:
        self._q("DELETE FROM user_sessions WHERE token=?", (token_hash,))

    # ---------- proprietatea proiectelor ----------
    def add_project(self, storage: str, owner: int, display: str) -> None:
        self._q("INSERT INTO projects(storage, owner, display, created) VALUES (?,?,?,?)",
                (storage, owner, display, time.time()))

    def project_of(self, owner: int, display: str) -> dict | None:
        rows = self._q("SELECT * FROM projects WHERE owner=? AND display=?", (owner, display))
        return rows[0] if rows else None

    def project_by_storage(self, storage: str) -> dict | None:
        rows = self._q("SELECT * FROM projects WHERE storage=?", (storage,))
        return rows[0] if rows else None

    def user_projects(self, owner: int) -> list[dict]:
        return self._q("SELECT * FROM projects WHERE owner=?", (owner,))

    def delete_project(self, storage: str) -> None:
        self._q("DELETE FROM projects WHERE storage=?", (storage,))

    # ---------- credite ----------
    def _apply_credits(self, uid: int, delta: int, reason: str, job: str) -> int:
        """Aplică delta fără să coboare sub 0; întoarce delta efectiv (apelat în tranzacție)."""
        row = self._conn.execute("SELECT credits FROM users WHERE id=?", (uid,)).fetchone()
        if row is None:
            return 0
        applied = max(delta, -row["credits"])
        self._conn.execute("UPDATE users SET credits = credits + ? WHERE id=?", (applied, uid))
        self._conn.execute("INSERT INTO ledger(user_id, delta, reason, job, ts) VALUES (?,?,?,?,?)",
                           (uid, applied, reason, job, time.time()))
        return applied

    def add_credits(self, uid: int, delta: int, reason: str, job: str = "") -> int:
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                applied = self._apply_credits(uid, delta, reason, job)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        return applied

    def credit_event(self, event_id: str, uid: int, credits: int, reason: str, ref: str = "") -> bool:
        """Creditează o plată Stripe o singură dată per eveniment. False = deja procesat."""
        with self._lock:
            c = self._conn
            c.execute("BEGIN IMMEDIATE")
            try:
                if c.execute("INSERT OR IGNORE INTO stripe_events(id, ts) VALUES (?,?)",
                             (event_id, time.time())).rowcount == 0:
                    c.execute("ROLLBACK")
                    return False
                self._apply_credits(uid, credits, reason, ref)
                c.execute("COMMIT")
            except Exception:
                c.execute("ROLLBACK")
                raise
        return True

    def ledger(self, uid: int, limit: int = 50) -> list[dict]:
        return self._q("SELECT id, delta, reason, job, ts FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT ?",
                       (uid, limit))
