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

from . import guard
from .project import Project, home

mcp = FastMCP("vedit")


def tool(fn):
    """Înregistrează tool-ul și transformă excepțiile în text util pentru agent.

    Fiecare apel trece prin gardă: bugetul de apeluri și lacătul pe proiect (vezi vedit/guard.py)."""
    @wraps(fn)
    def wrapper(*a, **kw):
        try:
            guard.spend("tool")
            proj = kw.get("project", a[0] if a else None)
            if proj is not None:
                guard.check_project(proj)
            out = fn(*a, **kw)
        except guard.GuardError as e:
            return f"REFUZAT (securitate): {e}"
        except Exception as e:  # agentul primește eroarea ca text și se poate corecta
            return f"EROARE: {type(e).__name__}: {e}"
        return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
    return mcp.tool()(wrapper)


# ---------------- proiect & asset-uri ----------------
@tool
def asset_add(project: str, path: str, asset_id: str = "") -> str:
    """Adaugă un fișier video/audio/muzică în proiect (creează proiectul dacă nu există). Returnează id-ul asset-ului."""
    path = guard.check_path(path, home() / project)
    return Project(project).add_asset(path, asset_id or None)


@tool
def asset_list(project: str) -> str:
    """Lista asset-urilor din proiect cu durată, rezoluție, fps, audio."""
    return guard.untrusted(Project(project).list_assets(), "lista de fișiere (numele vin de la utilizator)")


@tool
def asset_role(project: str, asset: str, role: str = "reference") -> str:
    """Rolul unui clip: 'reference' (referință de stil: nu intră în timeline, din ea se iau ritmul, culoarea,
    formatul), 'broll' (footage pentru pista V2) sau 'source' (material principal)."""
    return Project(project).set_role(asset, role)


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
    text = tr.compact(start, None if end < 0 else end) or "(fără vorbire)"
    return guard.untrusted(text, f"transcriptul lui {asset} (ce se spune în video)")


@tool
def diarize(project: str, asset: str, num_speakers: int = 0, start: float = 0, end: float = -1) -> str:
    """Diarizare audio (pyannote): cine vorbește când, vorbitori A, B, C... După asta transcript_get arată
    `A: text` pe fiecare frază, iar auto_reframe urmărește vorbitorul cu granițe exacte.
    num_speakers=0 = detectare automată; pune numărul dacă îl știi (mai precis). Rezultat în cache."""
    p = Project(project)
    d = p.diarization(asset, num_speakers)
    out = d.summary(start, None if end < 0 else end)
    faces = p.speaker_faces(asset) if p.s.assets[asset].has_video else {}
    if faces:
        out += "\nfețe: " + ", ".join(f"{k}→cx={v['cx']:.2f} ({v['votes']})" for k, v in sorted(faces.items()))
        missing = sorted(set(d.speakers()) - set(faces))
        if missing:
            out += f"\nfără față găsită (off-screen / neclar): {', '.join(missing)}"
    return out


@tool
def frames_look(project: str, asset: str, start: float = 0, end: float = -1, cols: int = 4, rows: int = 3) -> str:
    """Generează UN contact sheet (grilă de cadre) pentru a vedea conținutul. Returnează calea imaginii
    și timestamp-ul fiecărei celule. Deschide imaginea cu vision doar când decizia depinde de imagine.
    asset poate fi și 'render:preview' / 'render:final' pentru a verifica rezultatul."""
    return Project(project).look(asset, start, None if end < 0 else end, cols, rows)


# ---------------- stil de referință & culoare ----------------
@tool
def reference_analyze(project: str, asset: str = "") -> str:
    """Profilul MĂSURAT al clipului de referință: ritmul tăieturilor (tăieturi/min, lungimea shot-urilor,
    hook-ul din primele 3 s), culoarea (luminozitate, contrast, saturație, temperatură), audio, format.
    Gol = referința marcată. Subtitrările și textul din referință le vezi cu frames_look(asset=<referința>)."""
    p = Project(project)
    aid = asset or next(iter(p.references()), "")
    if not aid:
        return "EROARE: nu există referință. Marchează una cu asset_role."
    return p.style_summary(aid)


@tool
def color_match(project: str, asset: str = "all", reference: str = "", strength: float = 0.8) -> str:
    """Color grading care preia culoarea referinței (transfer statistic în LAB, copt într-un LUT 3D).
    asset='all' = toate sursele video (camere diferite ajung la același look). strength 0..1:
    0.6-0.8 natural, 1.0 identic statistic. Se aplică la render; e reversibil (color_reset / undo)."""
    return Project(project).color_match(asset, reference or None, strength)


@tool
def color_grade(project: str, asset: str = "all", preset: str = "", exposure: float = -999,
                contrast: float = -999, saturation: float = -999, temperature: float = -999,
                tint: float = -999, teal_orange: float = -999) -> str:
    """Grading manual, peste potrivirea cu referința (dacă există). Preseturi: cald, rece, contrast, desaturat,
    alb_negru, cinematic, luminos. Reglaje: exposure (-20..20), contrast (0.5..1.6), saturation (0..2),
    temperature (+cald/-rece, ~-15..15), tint (+magenta/-verde), teal_orange (0..1). -999 = neschimbat."""
    vals = dict(exposure=exposure, contrast=contrast, saturation=saturation, temperature=temperature,
                tint=tint, teal_orange=teal_orange)
    return Project(project).color_grade(asset, preset or None, **{k: (None if v == -999 else v) for k, v in vals.items()})


@tool
def color_reset(project: str, asset: str = "all") -> str:
    """Scoate grading-ul (toate sursele sau una)."""
    return Project(project).color_reset(asset)


@tool
def style_compare(project: str, reference: str = "", render: str = "preview") -> str:
    """Compară montajul randat cu referința, pe cifre (ritm, hook, culoare, volum) și spune ce tool să folosești
    ca să te apropii. Rulează-l după render(preview=true) și iterează până nu mai are sfaturi importante."""
    return Project(project).style_compare(reference or None, render)


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
def cut_speaker(project: str, asset: str, speaker: str, keep: bool = False) -> str:
    """Taie după vorbitor (cere diarize). keep=False: scoate tot ce spune `speaker` (ex. întrebările
    moderatorului). keep=True: păstrează DOAR `speaker` (ex. doar răspunsurile invitatului). Aliniat la cuvinte."""
    return Project(project).cut_speaker(asset, speaker, keep)


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
def transition_set(project: str, clip_ids: str = "all", type: str = "fade", duration: float = 0.4) -> str:
    """Tranziție la INTRAREA în clipuri (dinspre clipul anterior); clipurile se suprapun `duration` s, deci
    montajul se scurtează. Tipuri: fade, dissolve, fadeblack, fadewhite (flash), wipeleft/right,
    slideleft/right/up/down, smoothleft/right, circleopen/close, radial, zoomin, hblur (whip), pixelize.
    type='none' le scoate. Pe social media: tăieturi dure + tranziții rare, pe schimbări de idee."""
    return Project(project).transition_set(clip_ids, type, duration)


@tool
def zoom_animate(project: str, clip_ids: str, zoom_to: float = 1.15, zoom_from: float = 1.0, ease: str = "inout") -> str:
    """Zoom animat pe durata clipului (push-in lent sau Ken Burns). zoom_to 1.05-1.2 subtil, 1.2-1.35 accent;
    zoom_from > zoom_to = zoom out. ease: inout, in, out, linear. Egal = scoate animația."""
    return Project(project).zoom_animate(clip_ids, zoom_to, zoom_from, ease)


@tool
def audio_check(project: str, asset: str) -> str:
    """Diagnostic audio MĂSURAT: nivelul vorbirii, zgomotul din pauze, SNR, clipping, plus presetul recomandat."""
    return Project(project).audio_check(asset)


@tool
def audio_clean(project: str, asset: str = "all", preset: str = "medium") -> str:
    """Curăță vocea (reducere de zgomot calibrată pe zgomotul măsurat, poartă de zgomot, de-esser, compresor).
    Preset: light, medium, strong, voice (EQ de prezență pentru voce deja curată), none. Rulează întâi
    audio_check. După curățare ascultă/verifică: presetul strong poate suna metalic sau poate tăia finalul cuvintelor."""
    return Project(project).audio_clean(asset, preset)


@tool
def clip_volume(project: str, clip_ids: str, volume_db: float) -> str:
    """Volum per clip în dB (ex +4 pentru un clip înregistrat mai încet). clip_ids: 'all' sau 'c0,c3'."""
    return Project(project).clip_volume(clip_ids, volume_db)


@tool
def captions_add(project: str, asset: str, style: str = "bold_center", speaker_colors: bool = False) -> str:
    """Generează subtitrări din transcript, sincronizate cu tăieturile. Stiluri: bold_center, karaoke, classic_bottom.
    speaker_colors=True: culoare diferită per vorbitor (cere diarize înainte). Rulează DUPĂ ce tăieturile sunt finale."""
    return Project(project).captions(asset, style, speaker_colors)


@tool
def text_add(project: str, start: float, end: float, text: str, position: str = "top") -> str:
    """Text/titlu peste video (timp de timeline). position: top, center, bottom."""
    return Project(project).add_text(start, end, text, position)


@tool
def music_set(project: str, asset: str = "", volume_db: float = -18, duck: bool = True, src_in: float = 0) -> str:
    """Muzică de fundal (loop automat, fade-out la final, ducking sub voce). asset gol = fără muzică.
    src_in: de unde pornește piesa (ex. primul beat sau drop-ul, din beats_detect)."""
    return Project(project).set_music(asset or None, volume_db, duck, src_in)


# ---------------- muzică: beat & montaj ----------------
@tool
def beats_detect(project: str, asset: str) -> str:
    """Tempo (BPM) și beat-urile unei piese, în secunde (timp sursă). Beat-urile sunt precise; downbeat-urile
    (începutul măsurii) sunt doar estimate. Rezultat în cache."""
    return Project(project).beats(asset).summary()


@tool
def beat_montage(project: str, music: str, sources: str = "all", beats_per_shot: int = 2, max_duration: float = 0,
                 start_beat: int = 0, keep_audio: bool = False) -> str:
    """Montaj pe beat: ÎNLOCUIEȘTE timeline-ul cu shot-uri din surse, fiecare lung de exact `beats_per_shot`
    beat-uri, tăieturile pe lovituri, muzica pe fundal (fără ducking). Pentru montaje fără vorbire
    (travel, produs, eveniment, recap). sources: 'all' sau 'a0,a2'. keep_audio: păstrează sunetul surselor.
    Ritm: 1 = foarte alert, 2 = normal (~1 s la 120 BPM), 4 = calm."""
    return Project(project).beat_montage(music, sources, beats_per_shot, max_duration, start_beat, keep_audio)


# ---------------- B-roll (pista V2) ----------------
@tool
def broll_add(project: str, asset: str, at: float, duration: float, src_in: float = 0, mode: str = "full",
              pip_pos: str = "tr", snap: bool = False) -> str:
    """Pune B-roll pe pista V2, peste montaj, la `at` (timp de timeline) pentru `duration` secunde; vocea de pe V1
    continuă. mode='full' (tot ecranul) sau 'pip' (fereastră în colț: tl/tr/bl/br). snap=True aliniază
    începutul și finalul pe beat-urile muzicii. Adaugă B-roll DUPĂ ce tăieturile de pe V1 sunt finale."""
    return Project(project).broll_add(asset, at, duration, src_in, mode, pip_pos, snap)


@tool
def broll_remove(project: str, broll_id: str = "all") -> str:
    """Scoate un B-roll (ex. 'b0') sau pe toate ('all')."""
    return Project(project).broll_remove(broll_id)


@tool
def broll_stock(project: str, query: str, count: int = 2) -> str:
    """Caută și descarcă footage REAL, gratuit (Pexels), în orientarea montajului. Folosește-l când clientul nu
    are B-roll. Query scurt, concret, în engleză ('city night traffic', 'coffee pouring'). Clipurile primesc
    rolul [B-ROLL]; apoi le pui cu broll_add."""
    guard.spend("stock", count)
    return guard.untrusted(Project(project).broll_stock(query, count), "rezultatele Pexels")


@tool
def broll_generate(project: str, prompt: str, duration: float = 5) -> str:
    """Generează un clip B-roll cu un model video AI prin API (fal.ai sau Replicate). COSTĂ BANI.
    Folosește-l DOAR dacă utilizatorul a cerut explicit generare AI, sau nu există footage și stock-ul nu
    are nimic potrivit și utilizatorul a acceptat generarea. Prompt: subiect + acțiune + cadru + lumină,
    fără text/logo-uri. Are o limită de generări pe proiect (VEDIT_GEN_LIMIT)."""
    guard.require_generation_consent()
    return Project(project).broll_generate(prompt, duration)


@tool
def undo(project: str) -> str:
    """Anulează ultima modificare de timeline."""
    return Project(project).undo()


# ---------------- output ----------------
@tool
def render(project: str, preview: bool = True, name: str = "") -> str:
    """Randează. preview=True: 540p rapid pentru verificare. preview=False: calitate finală (doar la sfârșit).
    name: numele fișierului (ex 'short1') când produci mai multe output-uri din același proiect."""
    guard.spend("render")
    return Project(project).render(preview, name or None)


@tool
def qa_check(project: str, path: str = "") -> str:
    """Verifică obiectiv un render: durată, rezoluție, loudness, cadre negre, liniști lungi. ok=true înainte de livrare."""
    if path:
        path = guard.check_path(path, home() / project)
    return Project(project).qa(path or None)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
