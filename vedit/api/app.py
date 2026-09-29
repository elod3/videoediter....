"""API HTTP pentru editorul web.

Rulează:  vedit-server          (implicit http://127.0.0.1:8000, servește și frontend-ul din web/dist)
Env:
  VEDIT_HOME        unde stau proiectele (implicit ./vedit_projects)
  VEDIT_RUNNER      auto | claude-code | scripted
  VEDIT_API_TOKEN   dacă e setat, fiecare cerere trebuie să aibă `Authorization: Bearer <token>` (sau ?token=)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import analyze
from ..project import Project, home
from ..timeline import Timeline
from .db import DB
from .jobs import Worker
from .routes_export import export_router
from .runners import Runner, default_runner

NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MEDIA_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


class NewProject(BaseModel):
    name: str


class NewJob(BaseModel):
    prompt: str
    allow_generation: bool = False  # bifa explicită din UI: generarea AI costă bani


class RoleReq(BaseModel):
    role: str


class RenderReq(BaseModel):
    final: bool = False


def _project(name: str, create: bool = False) -> Project:
    if not NAME.match(name):
        raise HTTPException(400, "nume de proiect invalid (litere, cifre, _ și -)")
    if not create and not (home() / name / "project.json").exists():
        raise HTTPException(404, f"proiectul {name} nu există")
    return Project(name)


def _beats(p: Project) -> list[float]:
    """Beat-urile muzicii din timeline (timp de timeline), doar dacă sunt deja calculate (nu blocăm UI-ul)."""
    tl = p.tl
    if not tl.music or not (p.dir / "cache" / f"{tl.music.asset}.beats.json").exists():
        return []
    return [round(b, 3) for b in p._timeline_beats() if b <= tl.duration]


def _project_json(p: Project, runner: str) -> dict:
    tl = p.tl
    renders = []
    files = [f for f in (p.dir / "renders").glob("*.mp4") if not f.name.startswith(".")]
    for f in sorted(files, key=lambda f: f.stat().st_mtime, reverse=True):
        st = f.stat()
        renders.append({"name": f.stem, "url": f"/api/projects/{p.s.name}/renders/{f.name}?v={int(st.st_mtime)}",
                        "size": st.st_size, "mtime": st.st_mtime})
    return {
        "name": p.s.name,
        "runner": runner,
        "updated": p.file.stat().st_mtime,
        "assets": [{"id": k, "name": Path(v.path).name, **v.model_dump(exclude={"path"}),
                    "role": p.s.roles.get(k, "source"), "meta": p.s.meta.get(k),
                    "thumb": f"/api/projects/{p.s.name}/assets/{k}/thumb.jpg" if v.has_video else None}
                   for k, v in p.s.assets.items()],
        "timeline": {**tl.model_dump(), "duration": tl.duration, "starts": tl.starts(), "beats": _beats(p),
                     "can_undo": bool(p.s.history)},
        "renders": renders,
    }


def create_app(runner: Runner | None = None) -> FastAPI:
    app = FastAPI(title="vedit", version="0.1.0")
    db = DB(home() / "vedit.db")
    worker = Worker(db, runner or default_runner())
    app.state.db, app.state.worker = db, worker
    token = os.environ.get("VEDIT_API_TOKEN")

    @app.middleware("http")
    async def auth(request: Request, call_next):
        if token and request.url.path.startswith("/api/") and request.url.path != "/api/health":
            got = request.headers.get("authorization", "").removeprefix("Bearer ").strip() \
                or request.query_params.get("token", "")
            if got != token:
                return JSONResponse({"detail": "neautorizat"}, status_code=401)
        return await call_next(request)

    app.include_router(export_router(_project))  # subtitrări .srt/.vtt, thumbnail (routes_export.py)

    # ---------------- general ----------------
    @app.get("/api/health")
    def health():
        return {"ok": True, "runner": worker.runner.name, "auth": bool(token)}

    # ---------------- proiecte ----------------
    @app.get("/api/projects")
    def list_projects():
        out = []
        root = home()
        if root.exists():
            for f in root.glob("*/project.json"):
                p = Project(f.parent.name)
                thumb = next((f"/api/projects/{p.s.name}/assets/{k}/thumb.jpg"
                              for k, v in p.s.assets.items() if v.has_video), None)
                out.append({"name": p.s.name, "assets": len(p.s.assets), "duration": p.tl.duration,
                            "updated": f.stat().st_mtime, "thumb": thumb})
        return sorted(out, key=lambda x: -x["updated"])

    @app.post("/api/projects")
    def create_project(body: NewProject):
        if (home() / body.name / "project.json").exists():
            raise HTTPException(409, "există deja un proiect cu acest nume")
        p = _project(body.name, create=True)
        return _project_json(p, worker.runner.name)

    @app.get("/api/projects/{name}")
    def get_project(name: str):
        return _project_json(_project(name), worker.runner.name)

    @app.delete("/api/projects/{name}")
    def delete_project(name: str):
        p = _project(name)
        shutil.rmtree(p.dir)
        db.clear_session(name)
        return {"ok": True}

    # ---------------- asset-uri ----------------
    @app.post("/api/projects/{name}/assets")
    def upload(name: str, file: UploadFile = File(...)):
        p = _project(name)
        fname = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or "upload").name)[-80:] or "upload"
        if Path(fname).suffix.lower() not in MEDIA_EXT:
            raise HTTPException(400, f"tip de fișier neacceptat; acceptate: {' '.join(sorted(MEDIA_EXT))}")
        limit = int(os.environ.get("VEDIT_MAX_UPLOAD_MB", "4096")) * 1024 * 1024
        dest_dir = p.dir / "uploads"
        dest_dir.mkdir(exist_ok=True)
        dest = dest_dir / fname
        n = 1
        while dest.exists():
            dest = dest_dir / f"{Path(fname).stem}_{n}{Path(fname).suffix}"
            n += 1
        size = 0
        with open(dest, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    out.close()
                    dest.unlink()
                    raise HTTPException(413, "fișier prea mare")
                out.write(chunk)
        try:
            msg = p.add_asset(str(dest))
        except Exception as e:
            dest.unlink(missing_ok=True)
            raise HTTPException(400, f"nu pot citi fișierul media: {e}")
        return {"message": msg, "project": _project_json(Project(name), worker.runner.name)}

    @app.post("/api/projects/{name}/assets/{aid}/role")
    def set_role(name: str, aid: str, body: RoleReq):
        p = _project(name)
        try:
            p.set_role(aid, body.role)
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))
        return _project_json(p, worker.runner.name)

    @app.get("/api/projects/{name}/assets/{aid}/thumb.jpg")
    def thumb(name: str, aid: str):
        p = _project(name)
        if aid not in p.s.assets or not p.s.assets[aid].has_video:
            raise HTTPException(404)
        m = p.s.assets[aid]
        out = p.dir / "cache" / f"{aid}_thumb.jpg"
        if not out.exists():
            analyze.frame_at(m.path, min(m.duration * 0.1, 3.0), str(out), 480)
        return FileResponse(out, media_type="image/jpeg")

    @app.get("/api/projects/{name}/assets/{aid}/file")
    def asset_file(name: str, aid: str):
        p = _project(name)
        if aid not in p.s.assets:
            raise HTTPException(404)
        return FileResponse(p.s.assets[aid].path)

    @app.get("/api/projects/{name}/renders/{fname}")
    def render_file(name: str, fname: str):
        p = _project(name)
        f = (p.dir / "renders" / fname).resolve()
        if f.parent != (p.dir / "renders").resolve() or not f.exists():
            raise HTTPException(404)
        return FileResponse(f, media_type="video/mp4")

    # ---------------- timeline (editare manuală) ----------------
    @app.put("/api/projects/{name}/timeline")
    def put_timeline(name: str, body: dict):
        p = _project(name)
        try:
            new = Timeline.model_validate({k: v for k, v in body.items() if k not in ("duration", "starts", "can_undo")})
        except Exception as e:
            raise HTTPException(422, str(e))
        missing = {c.asset for c in new.clips} - set(p.s.assets)
        if new.music and new.music.asset not in p.s.assets:
            missing.add(new.music.asset)
        if missing:
            raise HTTPException(422, f"asset-uri inexistente: {', '.join(sorted(missing))}")
        with p.edit():
            p.s.timeline = new
        return _project_json(p, worker.runner.name)

    @app.delete("/api/projects/{name}/timeline/clips/{cid}")
    def delete_clip(name: str, cid: str):
        p = _project(name)
        try:
            p.remove_clip(cid)
        except KeyError as e:
            raise HTTPException(404, str(e))
        return _project_json(p, worker.runner.name)

    @app.post("/api/projects/{name}/undo")
    def undo(name: str):
        p = _project(name)
        p.undo()
        return _project_json(p, worker.runner.name)

    # ---------------- joburi (agent / render) ----------------
    @app.post("/api/projects/{name}/jobs")
    def new_job(name: str, body: NewJob):
        p = _project(name)
        if not body.prompt.strip():
            raise HTTPException(400, "cererea e goală")
        if not p.s.assets:
            raise HTTPException(400, "încarcă întâi un video")
        return worker.submit(name, "agent", body.prompt.strip(), allow_generation=body.allow_generation)

    @app.post("/api/projects/{name}/render")
    def new_render(name: str, body: RenderReq):
        p = _project(name)
        if not p.tl.clips:
            raise HTTPException(400, "timeline-ul e gol")
        return worker.submit(name, "render", "final" if body.final else "preview")

    @app.post("/api/projects/{name}/reset-agent")
    def reset_agent(name: str):
        _project(name)
        db.clear_session(name)
        return {"ok": True}

    @app.get("/api/projects/{name}/jobs")
    def list_jobs(name: str):
        _project(name)
        return db.jobs(name)

    @app.get("/api/jobs/{jid}")
    def get_job(jid: str):
        job = db.job(jid)
        if not job:
            raise HTTPException(404)
        return {**job, "events": db.events(jid)}

    @app.post("/api/jobs/{jid}/cancel")
    def cancel_job(jid: str):
        if not db.job(jid):
            raise HTTPException(404)
        return {"ok": worker.cancel(jid)}

    @app.get("/api/jobs/{jid}/events")
    def job_events(jid: str, after: int = 0):
        """Server-Sent Events: progresul agentului în timp real."""
        if not db.job(jid):
            raise HTTPException(404)

        def stream():
            last, idle = after, 0.0
            while True:
                evs = db.events(jid, last)
                for e in evs:
                    last = e["seq"]
                    yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                    if e["type"] == "done":
                        return
                if not evs:
                    idle += 0.3
                    if idle >= 15:  # keep-alive pentru proxy-uri
                        idle = 0
                        yield ": ping\n\n"
                    time.sleep(0.3)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ---------------- frontend ----------------
    dist = Path(os.environ.get("VEDIT_WEB_DIST", Path(__file__).resolve().parents[2] / "web" / "dist"))
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")

    return app


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host=os.environ.get("VEDIT_HOST", "127.0.0.1"),
                port=int(os.environ.get("VEDIT_PORT", "8000")))


if __name__ == "__main__":
    main()
