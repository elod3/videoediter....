"""Rute de livrare: fișiere de subtitrare și thumbnail. Separat de app.py; se înregistrează cu
`app.include_router(export_router(get_project))`, unde `get_project(request, name)` verifică proprietarul
(cu conturi active) și dă 404 pentru proiectele altora."""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..project import Project

MEDIA = {"srt": "application/x-subrip; charset=utf-8", "vtt": "text/vtt; charset=utf-8"}


def export_router(get_project: Callable[[Request, str], Project]) -> APIRouter:
    r = APIRouter()

    @r.get("/api/projects/{name}/captions.{fmt}")
    def captions_file(request: Request, name: str, fmt: str):
        if fmt not in MEDIA:
            raise HTTPException(404, "format: srt sau vtt")
        p = get_project(request, name)
        try:
            out = p.captions_export(fmt)
        except ValueError as e:
            raise HTTPException(409, str(e))
        return FileResponse(out["path"], media_type=MEDIA[fmt], filename=f"{name}.{fmt}")

    @r.get("/api/projects/{name}/thumbnail.png")
    def thumbnail_file(request: Request, name: str):
        f = get_project(request, name).dir / "renders" / "thumbnail.png"
        if not f.exists():
            raise HTTPException(404, "nu există thumbnail; rulează thumbnail_export")
        return FileResponse(f, media_type="image/png")

    return r
