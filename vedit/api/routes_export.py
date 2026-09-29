"""Rute de livrare și brand kit: subtitrări, thumbnail, preseturi de platformă, logo / culori / font.
Separat de app.py; se înregistrează cu `app.include_router(export_router(get_project))`, unde
`get_project(request, name)` verifică proprietarul (cu conturi active) și dă 404 pentru proiectele altora.

Exportul pe platformă randează la rezoluție finală, deci trece prin coada de joburi (și prin credite): e în app.py.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..brand import FONT_EXT, LOGO_EXT, PLATFORMS
from ..project import Project

MEDIA = {"srt": "application/x-subrip; charset=utf-8", "vtt": "text/vtt; charset=utf-8"}
IMAGE = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
BRAND_MAX = 20 * 1024 * 1024


class ColorsReq(BaseModel):
    primary: str = ""
    highlight: str = ""
    outline: str = ""
    font_family: str = ""


class ClearReq(BaseModel):
    part: str = "all"


class ThumbReq(BaseModel):
    at: float = -1
    title: str = ""


def _save_upload(file: UploadFile, allowed: tuple[str, ...], what: str, tmp: Path) -> Path:
    """Upload mic (logo / font) într-un fișier temporar; Project îl copiază în <proiect>/brand."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or what).name)[-60:] or what
    if Path(name).suffix.lower() not in allowed:
        raise HTTPException(400, f"{what}: doar {', '.join(allowed)}")
    dest, size = tmp / name, 0
    with open(dest, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > BRAND_MAX:
                raise HTTPException(413, f"{what} prea mare (maxim 20 MB)")
            out.write(chunk)
    return dest


def brand_json(p: Project) -> dict:
    b, tl = p.tl.brand, p.tl
    return {"logo": b.logo.model_dump(exclude={"path"}) if b.logo else None,
            "primary": b.primary, "highlight": b.highlight, "outline": b.outline,
            "font": tl.caption_font, "custom_font": bool(b.font_file),
            "intro": b.intro, "outro": b.outro, "summary": tl.brand_view()}


def export_router(get_project: Callable[[Request, str], Project]) -> APIRouter:
    r = APIRouter()

    def act(fn):
        try:
            return fn()
        except (ValueError, KeyError) as e:
            raise HTTPException(400, str(e).strip("'"))

    @r.get("/api/platforms")
    def platforms():
        return [{"id": k, "format": v["fmt"], "max": v["max"], "note": v["note"]} for k, v in PLATFORMS.items()]

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

    @r.post("/api/projects/{name}/thumbnail")
    def make_thumbnail(request: Request, name: str, body: ThumbReq):
        p = get_project(request, name)
        if not p.tl.clips:
            raise HTTPException(400, "timeline-ul e gol")
        out = act(lambda: p.thumbnail_export(at=body.at, title=body.title[:80]))
        return {"at": out.get("at"), "url": f"/api/projects/{name}/thumbnail.png"}

    @r.get("/api/projects/{name}/thumbnail.png")
    def thumbnail_file(request: Request, name: str):
        f = get_project(request, name).dir / "renders" / "thumbnail.png"
        if not f.exists():
            raise HTTPException(404, "nu există thumbnail; rulează thumbnail_export")
        return FileResponse(f, media_type="image/png", headers={"Cache-Control": "no-store"})

    # ---------- brand kit ----------
    @r.get("/api/projects/{name}/brand")
    def get_brand(request: Request, name: str):
        return brand_json(get_project(request, name))

    @r.post("/api/projects/{name}/brand/logo")
    def upload_logo(request: Request, name: str, file: UploadFile = File(...), position: str = Form("tr"),
                    scale: float = Form(0.12), opacity: float = Form(0.85)):
        p = get_project(request, name)
        with tempfile.TemporaryDirectory() as tmp:
            src = _save_upload(file, LOGO_EXT, "logo", Path(tmp))
            act(lambda: p.brand_logo(str(src), position=position, scale=scale, opacity=opacity))
        return brand_json(p)

    @r.put("/api/projects/{name}/brand/logo")
    def update_logo(request: Request, name: str, body: dict):
        """Doar poziție / mărime / opacitate pentru logo-ul existent (fără re-upload)."""
        p = get_project(request, name)
        logo = p.tl.brand.logo
        if not logo:
            raise HTTPException(404, "nu există logo")
        act(lambda: p.brand_logo(logo.path, position=str(body.get("position", logo.position)),
                                 scale=float(body.get("scale", logo.scale)),
                                 opacity=float(body.get("opacity", logo.opacity))))
        return brand_json(p)

    @r.get("/api/projects/{name}/brand/logo")
    def logo_file(request: Request, name: str):
        logo = get_project(request, name).tl.brand.logo
        if not logo or not Path(logo.path).exists():
            raise HTTPException(404)
        return FileResponse(logo.path, media_type=IMAGE.get(Path(logo.path).suffix.lower(), "image/png"))

    @r.post("/api/projects/{name}/brand/font")
    def upload_font(request: Request, name: str, file: UploadFile = File(...)):
        p = get_project(request, name)
        with tempfile.TemporaryDirectory() as tmp:
            src = _save_upload(file, FONT_EXT, "font", Path(tmp))
            act(lambda: p.brand_captions(font_path=str(src)))
        return brand_json(p)

    @r.put("/api/projects/{name}/brand/captions")
    def brand_colors(request: Request, name: str, body: ColorsReq):
        p = get_project(request, name)
        act(lambda: p.brand_captions(primary=body.primary, highlight=body.highlight, outline=body.outline,
                                     font_family=body.font_family))
        return brand_json(p)

    @r.post("/api/projects/{name}/brand/clear")
    def brand_clear(request: Request, name: str, body: ClearReq):
        p = get_project(request, name)
        act(lambda: p.brand_clear(body.part))
        return brand_json(p)

    return r
