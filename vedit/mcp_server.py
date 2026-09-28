"""Server MCP: expune toolkit-ul oricărui agent (Hermes Agent, Claude, etc.).

Rulează:  vedit-mcp   (stdio)
Reguli de design pentru tool-uri eficiente:
  * puține tool-uri, fiecare cu un scop clar și nume verb_obiect
  * output compact (text, nu JSON uriaș) — timeline-ul e rezumat în ~1 linie/clip
  * starea stă pe server (proiect pe disc), agentul trimite doar operații mici
  * erorile sunt mesaje clare pe care agentul le poate corecta singur
"""
from __future__ import annotations

import json
from functools import wraps

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP

from .project import Project

mcp = FastMCP("vedit")


def tool(fn):
    """Înregistrează tool-ul și transformă excepțiile în text util pentru agent."""
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            out = fn(*a, **kw)
        except Exception as e:  # agentul primește eroarea ca text și se poate corecta
            return f"EROARE: {type(e).__name__}: {e}"
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    return mcp.tool()(wrapper)


# ---------------- proiect & asset-uri ----------------
@tool
def asset_add(project: str, path: str, asset_id: str = "") -> str:
    """Adaugă un fișier video/audio/muzică în proiect (creează proiectul dacă nu există). Returnează id-ul asset-ului."""
    return Project(project).add_asset(path, asset_id or None)


@tool
def asset_list(project: str) -> str:
    """Lista asset-urilor din proiect cu durată, rezoluție, fps, audio."""
    return Project(project).list_assets()


# ---------------- analiză (ochi & urechi) ----------------
@tool
def media_analyze(project: str, asset: str, noise_db: float = -35, min_silence: float = 0.4) -> str:
    """Analiză rapidă fără AI: liniști, loudness (LUFS), tăieturi de scenă, cadre negre. Rezultat în cache."""
    return Project(project).analyze(asset, noise_db, min_silence)


@tool
def transcript_get(project: str, asset: str, start: float = 0, end: float = -1,
                   model: str = "small", language: str = "") -> str:
    """Transcriere cu id pe cuvânt. Format: `w12-w20 [3.40-6.10] text`. Folosește id-urile w la tăiere.
    Prima rulare transcrie (lent), apoi e din cache. Cere intervale (start/end) pe video lungi."""
    tr = Project(project).transcript(asset, model, language or None)
    return tr.compact(start, None if end < 0 else end) or "(fără vorbire)"


@tool
def frames_look(project: str, asset: str, start: float = 0, end: float = -1, cols: int = 4, rows: int = 3) -> str:
    """Generează UN contact sheet (grilă de cadre) pentru a vedea conținutul. Returnează calea imaginii
    și timestamp-ul fiecărei celule. Deschide imaginea cu vision doar când decizia depinde de imagine.
    asset poate fi și 'render:preview' / 'render:final' pentru a verifica rezultatul."""
    return Project(project).look(asset, start, None if end < 0 else end, cols, rows)


# ---------------- editare ----------------
@tool
def timeline_view(project: str) -> str:
    """Starea curentă a timeline-ului: format, durată, clipuri (id @timp_timeline asset[in-out])."""
    return Project(project).tl.view()


@tool
def timeline_format(project: str, fmt: str = "9:16", fps: float = 0, fill: str = "") -> str:
    """Setează formatul de output: 9:16, 16:9, 1:1, 4:5. fill='crop' (umple) sau 'pad' (bare negre)."""
    return Project(project).set_format(fmt, fps or None, fill or None)


@tool
def cut_silences(project: str, asset: str, noise_db: float = -35, min_silence: float = 0.5, padding: float = 0.1) -> str:
    """Jump-cut automat: construiește timeline-ul din asset fără pauzele mai lungi de min_silence secunde."""
    return Project(project).auto_cut_silence(asset, noise_db, min_silence, padding)


@tool
def cut_words(project: str, asset: str, spans: str) -> str:
    """Șterge cuvinte/fraze din video după id-urile din transcript, ex: 'w10-w25,w88'. (bâlbe, repetări, 'ăăă')"""
    return Project(project).remove_words(asset, spans)


@tool
def keep_words(project: str, asset: str, spans: str) -> str:
    """Înlocuiește timeline-ul cu DOAR aceste fragmente, în ordinea dată. Pentru highlights / clipuri scurte
    dintr-un video lung. Șterge și captions/textele existente. Ex: 'w300-w360,w120-w140' (hook-ul poate fi pus primul)."""
    return Project(project).keep_words(asset, spans)


@tool
def clip_add(project: str, asset: str, src_in: float, src_out: float, index: int = -1) -> str:
    """Adaugă un clip din asset [src_in, src_out) la final sau la poziția index (b-roll, intro, outro)."""
    return Project(project).add_clip(asset, src_in, src_out, None if index < 0 else index)


@tool
def clip_remove(project: str, clip_id: str) -> str:
    """Șterge un clip din timeline după id."""
    return Project(project).remove_clip(clip_id)


@tool
def clip_move(project: str, clip_id: str, index: int) -> str:
    """Mută un clip pe o altă poziție (0 = primul). Util pentru a pune hook-ul la început."""
    return Project(project).move_clip(clip_id, index)


@tool
def clip_trim(project: str, clip_id: str, src_in: float = -1, src_out: float = -1) -> str:
    """Ajustează intrarea/ieșirea unui clip (timp sursă). -1 = neschimbat."""
    return Project(project).trim_clip(clip_id, None if src_in < 0 else src_in, None if src_out < 0 else src_out)


@tool
def range_remove(project: str, t0: float, t1: float) -> str:
    """Ripple delete pe timeline între t0 și t1 (timp de timeline, nu de sursă)."""
    return Project(project).remove_range(t0, t1)


@tool
def reframe(project: str, clip_ids: str = "all", cx: float = 0.5, cy: float = 0.5, zoom: float = 1.0) -> str:
    """Încadrare pentru crop (ex 16:9 -> 9:16): centrul (cx,cy) în 0..1 al sursei, zoom>=1 pentru punch-in.
    clip_ids: 'all' sau 'c0,c3'."""
    return Project(project).reframe(clip_ids, cx, cy, zoom)


@tool
def auto_reframe(project: str, clip_ids: str = "all", split: bool = True, punch_in: float = 0.0,
                 speaker: bool = True) -> str:
    """Încadrare AUTOMATĂ pe fețe (detecție locală, fără vision LLM). Rulează după timeline_format(9:16/1:1/4:5)
    și după tăieturi. split=True împarte clipurile când subiectul se mută sau se schimbă scena.
    speaker=True: când mai multe persoane nu încap în cadru (podcast), urmărește cine vorbește (gură + audio).
    punch_in=0.15 alternează zoom 1.0/1.15 între clipuri. Segmentele WIDE/NO_FACE din raport trebuie verificate."""
    return Project(project).auto_reframe(clip_ids, split, punch_in, speaker=speaker)


@tool
def speakers_detect(project: str, asset: str, start: float = 0, end: float = -1) -> str:
    """Cine vorbește când (vorbitor activ după mișcarea gurii + audio), în timp sursă.
    Format: `[t0-t1] S<id> cx=<poziție>`. Combină cu transcript_get ca să știi cine spune ce."""
    d = Project(project).speakers(asset, start, None if end < 0 else end)
    tracks = ", ".join(f"S{t['id']} cx={t['cx']:.2f}" for t in d["tracks"]) or "-"
    segs = "\n".join(f"[{s['t0']:.2f}-{s['t1']:.2f}] S{s['track']} cx={s['cx']:.2f}" for s in d["segments"])
    return f"fețe urmărite: {tracks}\n{segs}"


@tool
def clip_volume(project: str, clip_ids: str, volume_db: float) -> str:
    """Volum per clip în dB (ex +4 pentru un clip înregistrat mai încet). clip_ids: 'all' sau 'c0,c3'."""
    return Project(project).clip_volume(clip_ids, volume_db)


@tool
def captions_add(project: str, asset: str, style: str = "bold_center") -> str:
    """Generează subtitrări din transcript, sincronizate cu tăieturile. Stiluri: bold_center, karaoke, classic_bottom.
    Rulează DUPĂ ce tăieturile sunt finale."""
    return Project(project).captions(asset, style)


@tool
def text_add(project: str, start: float, end: float, text: str, position: str = "top") -> str:
    """Text/titlu peste video (timp de timeline). position: top, center, bottom."""
    return Project(project).add_text(start, end, text, position)


@tool
def music_set(project: str, asset: str = "", volume_db: float = -18, duck: bool = True) -> str:
    """Muzică de fundal (loop automat, fade-out la final, ducking sub voce). asset gol = fără muzică."""
    return Project(project).set_music(asset or None, volume_db, duck)


@tool
def undo(project: str) -> str:
    """Anulează ultima modificare de timeline."""
    return Project(project).undo()


# ---------------- output ----------------
@tool
def render(project: str, preview: bool = True, name: str = "") -> str:
    """Randează. preview=True: 540p rapid pentru verificare. preview=False: calitate finală (doar la sfârșit).
    name: numele fișierului (ex 'short1') când produci mai multe output-uri din același proiect."""
    return Project(project).render(preview, name or None)


@tool
def qa_check(project: str, path: str = "") -> str:
    """Verifică obiectiv un render: durată, rezoluție, loudness, cadre negre, liniști lungi. ok=true înainte de livrare."""
    return Project(project).qa(path or None)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
