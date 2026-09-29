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


# ---------------- brand kit ----------------
@tool
def brand_logo(project: str, path: str, position: str = "tr", scale: float = 0.12, opacity: float = 0.85) -> str:
    """Logo-ul clientului ca watermark pe tot montajul (nu pe intro/outro). PNG cu transparență ideal (sau JPG/WebP),
    urcat în proiect. position: tl, tr, bl, br; scale = lățimea logo-ului din lățimea video-ului (0.08-0.15 discret);
    opacity 0..1. Stă peste B-roll, sub subtitrări. Pune-l în colțul opus textului de pe ecran."""
    path = guard.check_path(path, home() / project)
    return Project(project).brand_logo(path, position, scale, opacity)


@tool
def brand_captions(project: str, primary: str = "", highlight: str = "", outline: str = "", font_path: str = "",
                   font_family: str = "") -> str:
    """Culorile și fontul brandului pentru subtitrări și titluri. Culori hex #RRGGBB: primary = textul,
    highlight = cuvântul curent la karaoke, outline = conturul. font_path: .ttf/.otf urcat în proiect (numele
    familiei se citește din fișier; dă font_family doar dacă cere). '' = neschimbat, 'none' = revine la stil.
    Verifică lizibilitatea: text deschis cu contur închis (sau invers)."""
    if font_path:
        font_path = guard.check_path(font_path, home() / project)
    return Project(project).brand_captions(primary, highlight, outline, font_path, font_family)


@tool
def brand_intro_outro(project: str, intro: str = "", outro: str = "") -> str:
    """Intro / outro de brand (id-uri de asset video), lipite automat la randare înainte / după montaj.
    Nu intră în timeline: tăieturile, subtitrările și B-roll-ul rămân aliniate, logo-ul și muzica stau doar
    pe montaj. '' = fără (apelul setează ambele valori)."""
    return Project(project).brand_intro_outro(intro, outro)


@tool
def brand_clear(project: str, part: str = "all") -> str:
    """Scoate brandul: part = all, logo, captions (culori + font) sau intro_outro. Reversibil cu undo."""
    return Project(project).brand_clear(part)


# ---------------- viteză, efecte, stabilizare ----------------
@tool
def speed_set(project: str, clip_ids: str, speed: float = 1.0) -> str:
    """Viteza clipurilor (0.25-4; 1 = normal). <1 slow motion (merge bine pe B-roll / acțiune, NU pe vorbire),
    1.1-1.3 accelerează discret vorbirea lentă. Sunetul își păstrează tonul. Refă subtitrările după."""
    return Project(project).speed_set(clip_ids, speed)


@tool
def speed_ramp(project: str, clip_id: str, speed_from: float = 1.0, speed_to: float = 2.5, steps: int = 5) -> str:
    """Speed ramp: clipul accelerează/încetinește treptat (ex. 1 -> 3 înainte de o tăietură, 3 -> 0.5 pe un
    moment de impact). Împarte clipul în `steps` bucăți cu viteze interpolate. Pentru acțiune / B-roll / tranziții."""
    return Project(project).speed_ramp(clip_id, speed_from, speed_to, steps)


@tool
def freeze_frame(project: str, clip_id: str, seconds: float = 1.0) -> str:
    """Îngheață ultimul cadru al clipului `seconds` secunde (fără sunet). Clasic: freeze + title_card / callout
    („ăsta sunt eu”), sau înainte de o dezvăluire. 0 = scoate freeze-ul."""
    return Project(project).freeze_frame(clip_id, seconds)


@tool
def clip_fx(project: str, clip_ids: str, effects: str = "", mode: str = "add") -> str:
    """Efecte vizuale pe clipuri. effects (virgulă): bw (alb-negru), vintage, vignette, blur, sharpen, glitch
    (rafale RGB), shake (tremur de cameră, pe impact), flash (flash alb la intrare), grain, mirror, invert.
    mode: add / set / clear. Cu măsură: 1-2 efecte, pe momente care le justifică (hook, impact, flashback)."""
    return Project(project).clip_fx(clip_ids, effects, mode)


@tool
def stabilize(project: str, asset: str, smoothing: int = 15, off: bool = False) -> str:
    """Stabilizează un clip filmat din mână (vidstab, două treceri; durează cam cât clipul). smoothing 5-60.
    Randarea folosește apoi varianta stabilizată. off=True revine la original."""
    return Project(project).stabilize(asset, smoothing, off)


@tool
def broll_key(project: str, broll_id: str, color: str = "#00FF00") -> str:
    """Green screen pe un B-roll: culoarea `color` (#00FF00 verde, #0000FF albastru) devine transparentă și se vede
    montajul de dedesubt. 'none' scoate efectul. Verifică marginile cu frames_look."""
    return Project(project).broll_key(broll_id, color)


# ---------------- motion graphics ----------------
@tool
def graphic_add(project: str, kind: str, start: float, end: float, text: str = "", subtext: str = "",
                position: str = "", x: float = 0.5, y: float = 0.5, size: float = 0.12, value_from: float = 0,
                value_to: float = 0, decimals: int = 0, prefix: str = "", suffix: str = "", items: str = "",
                color: str = "") -> str:
    """Grafic animat pe montaj (timp de montaj, secunde). kind:
    lower_third (nume=text + rol=subtext, stânga-jos; la prima apariție a unui vorbitor),
    title_card (titlu mare centrat cu pop; capitole, hook, final), callout (casetă cu text care arată spre x,y),
    counter (număr care crește value_from -> value_to, cu prefix/suffix: „$”, „%”; cifre din discurs),
    progress_bar (bară de progres pe toată durata; bună la tutoriale / liste), cta (îndemn: abonează-te, link),
    list (items separate cu |, apar pe rând), kinetic (cuvintele din text apar unul câte unul; hook),
    circle (cerc care evidențiază punctul x,y; size = raza).
    position: top, center, bottom, lower_left, lower_right, upper_left, upper_right. color: #RRGGBB (implicit brandul).
    Graficele stau sub subtitrări: nu le pune în zona subtitrărilor. Verifică cu frames_look pe render."""
    return Project(project).graphic_add(kind, start, end, text=text, subtext=subtext, position=position or None,
                                        x=x, y=y, size=size, value_from=value_from, value_to=value_to,
                                        decimals=decimals, prefix=prefix, suffix=suffix, items=items,
                                        color=color or None)


@tool
def graphic_remove(project: str, graphic_ids: str) -> str:
    """Scoate grafice după id (ex. 'g0,g2')."""
    return Project(project).graphic_remove(graphic_ids)


# ---------------- efecte sonore ----------------
@tool
def sfx_add(project: str, kind: str, at: float, volume_db: float = -8.0) -> str:
    """Efect sonor la timpul `at` (montaj). kind: whoosh (tranziții, mișcări), pop (text/grafic apare),
    click (UI, listă), impact (titlu, dezvăluire), riser (tensiune înainte de drop / tăietură), ding (reușită,
    număr final), swipe (punch-in, schimbare rapidă), bass_drop (moment mare) — sau id-ul unui asset audio urcat.
    Puține și intenționate; -8..-14 dB sub voce."""
    return Project(project).sfx_add(kind, at, volume_db)


@tool
def sfx_auto(project: str, transitions: bool = True, graphics: bool = True, punch_ins: bool = True,
             volume_db: float = -10.0) -> str:
    """Pune automat efecte sonore unde le-ar pune un editor: whoosh pe tranziții, impact/swipe/pop/ding pe grafice,
    swipe pe punch-in. Rulează-l DUPĂ tranziții și grafice; îl poți rula din nou (înlocuiește doar ce a pus el)."""
    return Project(project).sfx_auto(transitions, graphics, punch_ins, volume_db)


@tool
def sfx_remove(project: str, sfx_ids: str = "all") -> str:
    """Scoate efecte sonore după id (ex. 'x0,xa3') sau toate ('all')."""
    return Project(project).sfx_remove(sfx_ids)


# ---------------- capitole ----------------
@tool
def chapters_set(project: str, chapters: str, title_cards: bool = False) -> str:
    """Capitole pentru YouTube: 'secunde=Titlu|secunde=Titlu' (timp de montaj, din transcript: unde se schimbă
    subiectul). Primul la 0, minim 3, fiecare ≥ 10 s. Întoarce textul gata de pus în descriere (cu decalajul
    intro-ului). title_cards=True pune și un titlu animat la începutul fiecărui capitol. '' le șterge."""
    return Project(project).chapters_set(chapters, title_cards)


# ---------------- cuvinte-cheie ----------------
@tool
def captions_emphasis(project: str, words: str = "auto", asset: str = "", color: str = "", scale: float = 1.25,
                      mode: str = "add") -> str:
    """Evidențiază cuvinte-cheie în subtitrări: altă culoare, mai mari, cu „pop” când sunt rostite (stil Hormozi).
    words: id-uri din transcript ('w12,w30') + asset, sau 'auto' (cifre și cuvinte importante, ~1 la 2 subtitrări).
    Rulează după captions_add; rămân și dacă refaci subtitrările. mode: add / set / clear. color #RRGGBB (implicit brand).
    Alege 1 cuvânt pe frază, cel care poartă sensul (cifră, rezultat, emoție), nu cuvinte de legătură."""
    return Project(project).captions_emphasis(words, asset, color, scale, mode)


@tool
def zoom_on_words(project: str, words: str, asset: str = "", zoom: float = 1.2, hold: float = 1.2) -> str:
    """Punch-in (tăietură în zoom) exact pe cuvintele date ('w12,w40'), ținut `hold` secunde. Accent pe ideile
    cheie; 2-4 pe minut, nu la fiecare frază. Merge bine împreună cu captions_emphasis pe același cuvânt."""
    return Project(project).zoom_on_words(words, asset, zoom, hold)


# ---------------- multicam ----------------
@tool
def multicam_sync(project: str, angles: str, reference: str = "") -> str:
    """Sincronizează mai multe camere care au filmat același moment, după sunet (ms precizie). angles: 'a0,a1,a2';
    referința (implicit primul) dă sunetul și timpul montajului: taie pauzele / cuvintele pe ea, apoi schimbă
    camerele. Refuză dacă sunetul nu se potrivește."""
    return Project(project).multicam_sync(angles, reference)


@tool
def multicam_auto(project: str, mode: str = "speaker", mapping: str = "", wide: str = "", min_shot: float = 1.5,
                  every: float = 4.0, wide_every: float = 0.0) -> str:
    """Schimbă automat camera pe montaj. mode='speaker': fiecare vorbitor pe camera lui, mapping='S0=a1,S1=a2'
    (vorbitorii din diarize; vezi cine e pe ce cameră cu frames_look), wide='a0' la suprapuneri / reacții,
    wide_every=20 inserează un cadru larg periodic. mode='rotate': alternează camerele la ~`every` secunde, pe
    finaluri de cuvânt (monolog filmat din mai multe unghiuri). min_shot = cadrul minim (1.2-2.5 s)."""
    return Project(project).multicam_auto(mode, mapping, wide, min_shot, every, wide_every)


@tool
def multicam_angle(project: str, start: float, end: float, angle: str) -> str:
    """Manual: pe [start, end) din montaj se vede camera `angle` (sunetul rămâne cel al referinței)."""
    return Project(project).multicam_angle(start, end, angle)


@tool
def split_screen(project: str, start: float, end: float, angles: str = "", mode: str = "stack") -> str:
    """Două camere în același cadru pe [start, end): stack = sus/jos (podcast în 9:16, reacție + gameplay),
    side = stânga/dreapta (16:9). Fiecare panou se centrează pe fața din camera lui. angles='' scoate split-ul."""
    return Project(project).split_screen(start, end, angles, mode)


# ---------------- livrare ----------------
@tool
def captions_export(project: str, fmt: str = "srt") -> str:
    """Scrie subtitrările ca fișier separat (fmt: srt sau vtt) în renders/, sincronizat cu video-ul randat
    (include decalajul intro-ului). Pentru upload pe YouTube/LinkedIn sau când clientul le vrea editabile."""
    return Project(project).captions_export(fmt)


@tool
def export_preset(project: str, platform: str, fmt: str = "") -> str:
    """Livrare pe platformă: setează formatul, fps și loudness (-14 LUFS), randează final ca `<platform>.mp4`
    și rulează QA. platform: tiktok, reels, shorts (9:16), youtube, x (16:9), instagram_feed (4:5), linkedin (1:1).
    fmt suprascrie formatul (ex. '9:16' pe LinkedIn). Citește `warnings` (durată peste limită, reframe) și `qa`."""
    guard.spend("render")
    return Project(project).export_preset(platform, fmt)


@tool
def thumbnail_export(project: str, at: float = -1, title: str = "") -> str:
    """Thumbnail PNG la rezoluția output-ului (renders/thumbnail.png). at = timp de timeline; -1 = alege automat
    cel mai clar cadru, preferând cadre cu fețe. title: text mare (2-5 cuvinte) cu fontul și culorile brandului.
    Verifică rezultatul cu vision înainte de livrare."""
    return Project(project).thumbnail_export(at, title)


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
