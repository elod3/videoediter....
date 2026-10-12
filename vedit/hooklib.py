"""Bibliotecă de hook-uri de deschidere: primele 1,5-3 s care prind privitorul.

Un hook NU e un efect nou, ci o REȚETĂ compusă din operații care există deja în editor (tăiere, text,
grafic, sfx, tranziție, zoom, viteză). Fiecare hook are un `id` stabil, un nume, o descriere, pentru ce
tip de material merge (`vorbire` / `b-roll` / `showreel`) și durata tipică.

Funcții publice:
  * `hooks()`  -> lista hook-urilor (id, nume, descriere, pentru, durata_s, parametri)
  * `apply_hook(project, hook_id, at=0.0, **opțiuni)` -> aplică rețeta pe montaj

Regula: hook-ul se pune la ÎNCEPUT (at≈0) și se verifică pe preview (`frames_look`), nu se lasă la ghici.
Un singur hook per clip; două hook-uri suprapuse se bat cap în cap.
"""
from __future__ import annotations

from .project import Project
from .timeline import Crop

# ---------------------------------------------------------------- definiții
HOOKS: list[dict] = [
    {"id": "teaser_replica", "nume": "Teaser cu cea mai tare replică", "pentru": "vorbire", "durata_s": 3.0,
     "descriere": "Cea mai tare frază (start-end dat) se pune și la început, apoi flash și clipul de la capăt. "
                  "Trucul clasic de reținere: promit ceva în primele secunde.",
     "parametri": [{"nume": "start", "descriere": "secunda de început a momentului tare", "obligatoriu": True},
                   {"nume": "end", "descriere": "secunda de sfârșit a momentului tare", "obligatoriu": True},
                   {"nume": "text", "descriere": "text opțional peste teaser", "obligatoriu": False}]},
    {"id": "cold_open", "nume": "Cold open (fără intro)", "pentru": "vorbire", "durata_s": 2.0,
     "descriere": "Scoate intro/outro și deschide tăietură dură direct pe conținut, cu un whoosh discret. "
                  "Zero lălăială, intri în subiect în prima secundă.",
     "parametri": []},
    {"id": "intrebare", "nume": "Întrebare pe ecran", "pentru": "vorbire", "durata_s": 2.5,
     "descriere": "Un title_card cu o întrebare peste primul cadru — privitorul vrea răspunsul.",
     "parametri": [{"nume": "text", "descriere": "întrebarea (max ~60 caractere)", "obligatoriu": True}]},
    {"id": "before_after_instant", "nume": "Before/after instant", "pentru": "showreel", "durata_s": 2.5,
     "descriere": "Mască care culisează între două jumătăți (render vs realitate / înainte vs după), direct din prima secundă.",
     "parametri": [{"nume": "text", "descriere": "eticheta din stânga (ex. RENDER)", "obligatoriu": False},
                   {"nume": "subtext", "descriere": "eticheta din dreapta (ex. REALITATE)", "obligatoriu": False}]},
    {"id": "pattern_interrupt", "nume": "Pattern interrupt (zoom brusc + impact)", "pentru": "b-roll", "durata_s": 1.0,
     "descriere": "Punch-in brusc plus flash pe cadrul de la `at`, cu impact sonor. Rupe ritmul ca să nu se "
                  "instaleze plictiseala.",
     "parametri": [{"nume": "at", "descriere": "secunda cadrului pe care intri", "obligatoriu": False}]},
    {"id": "punch_text", "nume": "Punch text peste primul cadru", "pentru": "vorbire", "durata_s": 2.0,
     "descriere": "Text cinetic (cuvintele apar pe rând) peste primul cadru, cu un pop la apariție.",
     "parametri": [{"nume": "text", "descriere": "fraza scurtă și tare", "obligatoriu": True}]},
    {"id": "countdown", "nume": "Numărătoare inversă", "pentru": "b-roll", "durata_s": 2.5,
     "descriere": "Counter de la 3 la 1 (sau alt interval) ca deschidere de listă / top.",
     "parametri": [{"nume": "de_la", "descriere": "valoarea de pornire (implicit 3)", "obligatoriu": False},
                   {"nume": "la", "descriere": "valoarea finală (implicit 1)", "obligatoriu": False},
                   {"nume": "text", "descriere": "etichetă sub cifră", "obligatoriu": False}]},
    {"id": "detaliu_ansamblu", "nume": "Detaliu → ansamblu", "pentru": "showreel", "durata_s": 3.0,
     "descriere": "Cadrul pornește aproape (detaliu) și se desface în plan larg (zoom out lent).",
     "parametri": [{"nume": "zoom", "descriere": "cât de aproape pornește (implicit 1.35)", "obligatoriu": False}]},
    {"id": "schema_reveal", "nume": "Schemă → rezultat", "pentru": "showreel", "durata_s": 3.0,
     "descriere": "Se desenează o schemă/grilă (line_grid), apoi intră titlul peste ea. Schema devine rezultat.",
     "parametri": [{"nume": "text", "descriere": "titlul", "obligatoriu": True},
                   {"nume": "subtext", "descriere": "subtitlu opțional", "obligatoriu": False}]},
    {"id": "citat_autor", "nume": "Citat de autor", "pentru": "showreel", "durata_s": 3.0,
     "descriere": "Un citat, cu semn mare de citat și autorul dedesubt. Intrare lină, editorială.",
     "parametri": [{"nume": "text", "descriere": "citatul", "obligatoriu": True},
                   {"nume": "subtext", "descriere": "autorul", "obligatoriu": True}]},
    {"id": "trei_lucruri", "nume": "„3 lucruri”", "pentru": "vorbire", "durata_s": 3.0,
     "descriere": "Listă cu 3 rânduri care apar pe rând — promisiune de valoare structurată.",
     "parametri": [{"nume": "items", "descriere": "cele 3 rânduri, separate cu |", "obligatoriu": True},
                   {"nume": "text", "descriere": "titlu opțional", "obligatoriu": False}]},
    {"id": "flash_best", "nume": "Flash pe cea mai bună imagine", "pentru": "b-roll", "durata_s": 2.0,
     "descriere": "Flash alb pe cel mai bun cadru, freeze scurt și un titlu peste — moment de „stop, uite”.",
     "parametri": [{"nume": "text", "descriere": "titlul peste freeze", "obligatoriu": False},
                   {"nume": "freeze", "descriere": "secunde de freeze (implicit 0.6)", "obligatoriu": False}]},
    {"id": "spec_intro", "nume": "Card tehnic de deschidere", "pentru": "showreel", "durata_s": 3.0,
     "descriere": "Card de date (titlu + rânduri etichetă/valoare), rândurile apar pe rând. Cifrele vând.",
     "parametri": [{"nume": "text", "descriere": "titlul cardului (numele proiectului)", "obligatoriu": True},
                   {"nume": "items", "descriere": "rândurile, separate cu |", "obligatoriu": True}]},
    {"id": "mask_open", "nume": "Titlu dezvăluit de mască", "pentru": "showreel", "durata_s": 2.5,
     "descriere": "Titlul e dezvăluit de o mască care culisează (nu pop, nu fade simplu). Calm și premium.",
     "parametri": [{"nume": "text", "descriere": "titlul", "obligatoriu": True},
                   {"nume": "subtext", "descriere": "subtitlu opțional", "obligatoriu": False}]},
    {"id": "chapter_start", "nume": "Deschidere de capitol", "pentru": "vorbire", "durata_s": 2.5,
     "descriere": "Număr mare de capitol cu linie subțire, care intră cu wipe, plus titlul capitolului.",
     "parametri": [{"nume": "text", "descriere": "titlul capitolului", "obligatoriu": True},
                   {"nume": "value_to", "descriere": "numărul capitolului (1-99, implicit 1)", "obligatoriu": False}]},
    {"id": "stat_pill", "nume": "Pastilă cu o cifră", "pentru": "showreel", "durata_s": 2.5,
     "descriere": "Pastilă mică de colț cu o cifră sau etichetă — fără zgomot vizual, doar informația.",
     "parametri": [{"nume": "text", "descriere": "valoarea sau eticheta (ex. „4.200”, „2024”)", "obligatoriu": True}]},
]

HOOKS_BY_ID = {h["id"]: h for h in HOOKS}


def hooks() -> list[dict]:
    """Lista hook-urilor disponibile (copie — nu se poate modifica registrul din greșeală)."""
    return [dict(h) for h in HOOKS]


# ---------------------------------------------------------------- ajutoare
def _clip_at(tl, t):
    """(clip, start) pentru timpul de montaj t; ultimul clip dacă t e la final, (None, 0) dacă nu există clipuri."""
    for c, s in zip(tl.clips, tl.starts()):
        if s <= t < s + c.duration:
            return c, s
    return (tl.clips[-1], tl.starts()[-1]) if tl.clips else (None, 0.0)


def _gfx(p, kind, at, dur, **fields):
    """Adaugă un grafic tăiat la durata montajului, cu mesaj clar dacă nu încape.

    Dacă `graphic_add` refuză (n-ar încăpea fără să acopere fața), hook-ul nu poate continua: ridicăm
    o eroare clară în loc să lăsăm hook-ul fără text.
    """
    tl = p.tl
    if tl.duration <= 0:
        raise ValueError("timeline gol: adaugă întâi clipuri, apoi aplică un hook")
    if at >= tl.duration:
        raise ValueError(f"at={at:.2f}s e după finalul montajului ({tl.duration:.2f}s)")
    end = min(at + dur, tl.duration)
    if end - at < 0.5:
        raise ValueError("prea puțin spațiu la finalul montajului pentru hook (minim 0.5 s)")
    before = len(p.tl.graphics)
    msg = p.graphic_add(kind, round(at, 3), round(end, 3), **fields)
    if len(p.tl.graphics) == before:
        raise ValueError(f"hook-ul nu s-a putut plasa: {msg}")
    return msg


def _sfx(p, kind, at, db=-8.0):
    """Efect sonor doar dacă timpul e valid în montaj."""
    if 0 <= at < p.tl.duration:
        p.sfx_add(kind, round(at, 3), volume_db=db)


def _items(v) -> list[str]:
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in str(v).replace(";", "|").split("|") if x.strip()]


def _need(o, key) -> str:
    v = str(o.get(key, "") or "").strip()
    if not v:
        raise ValueError(f"hook-ul are nevoie de „{key}”")
    return v


# ---------------------------------------------------------------- rețetele (fiecare = operații existente)
def _teaser_replica(p, at, o) -> list[str]:
    s, e = float(o.get("start", at)), float(o.get("end", at + 2.5))
    p.hook_teaser(s, e, str(o.get("text", "")))
    return [f"teaser {s:.1f}-{e:.1f}s pus la început, cu flash de tranziție"]


def _cold_open(p, at, o) -> list[str]:
    p.brand_intro_outro("")
    tl = p.tl
    if not tl.clips:
        raise ValueError("timeline gol: adaugă întâi clipuri")
    with p.edit() as t:
        t.clips[0].transition = None
        t.clips[0].freeze = 0.0
    _sfx(p, "whoosh", min(at, 0.05), -10)
    return ["intro/outro scoase, tăietură dură pe primul cadru, whoosh"]


def _intrebare(p, at, o) -> list[str]:
    _gfx(p, "title_card", at, 2.5, text=_need(o, "text"), position="center")
    _sfx(p, "pop", at)
    return ["title_card cu întrebarea", "pop"]


def _before_after_instant(p, at, o) -> list[str]:
    _gfx(p, "before_after", at, 2.5, text=str(o.get("text", "RENDER")), subtext=str(o.get("subtext", "REALITATE")))
    _sfx(p, "swipe", at, -6)
    return ["mască before/after care culisează", "swipe"]


def _pattern_interrupt(p, at, o) -> list[str]:
    tl = p.tl
    c, _ = _clip_at(tl, at)
    if c is None:
        raise ValueError("timeline gol: adaugă întâi clipuri")
    with p.edit() as t:
        cc = t.clip(c.id)
        cc.crop = Crop(cx=cc.crop.cx, cy=cc.crop.cy, zoom=max(cc.crop.zoom, 1.25))
        if "flash" not in cc.fx:
            cc.fx = [*cc.fx, "flash"]
    _sfx(p, "impact", at, -6)
    return ["punch-in brusc (x1.25) + flash", "impact"]


def _punch_text(p, at, o) -> list[str]:
    _gfx(p, "kinetic", at, 2.0, text=_need(o, "text"), position="center")
    _sfx(p, "pop", at)
    return ["text cinetic peste primul cadru", "pop"]


def _countdown(p, at, o) -> list[str]:
    a, b = float(o.get("de_la", 3)), float(o.get("la", 1))
    if a == b:
        raise ValueError("countdown: „de_la” și „la” trebuie să difere")
    _gfx(p, "counter", at, 2.5, value_from=a, value_to=b, decimals=0, text=str(o.get("text", "")))
    _sfx(p, "ding", min(at + 2.0, p.tl.duration - 0.05), -8)
    return [f"numărătoare inversă {a:g} → {b:g}", "ding la final"]


def _detaliu_ansamblu(p, at, o) -> list[str]:
    tl = p.tl
    c, _ = _clip_at(tl, at)
    if c is None:
        raise ValueError("timeline gol: adaugă întâi clipuri")
    z = float(o.get("zoom", 1.35))
    p.zoom_animate(c.id, zoom_to=1.0, zoom_from=z, ease="out")
    return [f"zoom out lent de la x{z:g} la cadru larg"]


def _schema_reveal(p, at, o) -> list[str]:
    _gfx(p, "line_grid", at, min(1.6, 3.0), text=_need(o, "text"))
    _gfx(p, "title_card", at + 1.4, 1.6, text=_need(o, "text"), subtext=str(o.get("subtext", "")),
         position="center")
    return ["schemă desenată progresiv → title_card"]


def _citat_autor(p, at, o) -> list[str]:
    _gfx(p, "quote_card", at, 3.0, text=_need(o, "text"), subtext=_need(o, "subtext"))
    _sfx(p, "ding", at, -10)
    return ["citat + autor"]


def _trei_lucruri(p, at, o) -> list[str]:
    items = _items(_need(o, "items"))[:3]
    if len(items) < 2:
        raise ValueError("trei_lucruri are nevoie de 2-3 rânduri separate cu |")
    _gfx(p, "list", at, 3.0, items=items, text=str(o.get("text", "")))
    _sfx(p, "pop", at)
    return [f"listă cu {len(items)} rânduri pe rând"]


def _flash_best(p, at, o) -> list[str]:
    tl = p.tl
    c, _ = _clip_at(tl, at)
    if c is None:
        raise ValueError("timeline gol: adaugă întâi clipuri")
    p.clip_fx(c.id, "flash")
    p.freeze_frame(c.id, float(o.get("freeze", 0.6)))
    _sfx(p, "impact", at, -6)
    if o.get("text"):
        _gfx(p, "title_card", at, 1.6, text=str(o["text"]), position="center")
    return ["flash pe imagine", "freeze scurt", "impact"]


def _spec_intro(p, at, o) -> list[str]:
    items = _items(_need(o, "items"))[:8]
    if not items:
        raise ValueError("spec_intro are nevoie de rânduri separate cu |")
    _gfx(p, "spec_card", at, 3.0, text=_need(o, "text"), items=items)
    _sfx(p, "swipe", at, -7)
    return [f"card tehnic cu {len(items)} rânduri"]


def _mask_open(p, at, o) -> list[str]:
    _gfx(p, "mask_reveal", at, 2.5, text=_need(o, "text"), subtext=str(o.get("subtext", "")))
    return ["titlu dezvăluit de mască"]


def _chapter_start(p, at, o) -> list[str]:
    n = int(round(float(o.get("value_to", 1))))
    _gfx(p, "chapter_num", at, 2.5, text=_need(o, "text"), value_to=n)
    return [f"număr de capitol {n:02d} + titlu"]


def _stat_pill(p, at, o) -> list[str]:
    _gfx(p, "stat_badge", at, 2.5, text=_need(o, "text"))
    return ["pastilă de colț cu cifra/eticheta"]


_BUILD = {
    "teaser_replica": _teaser_replica, "cold_open": _cold_open, "intrebare": _intrebare,
    "before_after_instant": _before_after_instant, "pattern_interrupt": _pattern_interrupt,
    "punch_text": _punch_text, "countdown": _countdown, "detaliu_ansamblu": _detaliu_ansamblu,
    "schema_reveal": _schema_reveal, "citat_autor": _citat_autor, "trei_lucruri": _trei_lucruri,
    "flash_best": _flash_best, "spec_intro": _spec_intro, "mask_open": _mask_open,
    "chapter_start": _chapter_start, "stat_pill": _stat_pill,
}


def apply_hook(project, hook_id: str, at: float = 0.0, subtitrari: bool = True, **opțiuni) -> str:
    """Aplică un hook de deschidere pe montaj (timp de montaj). `project` = nume sau un Project.

    Fiecare rețetă compune operații existente (tăieturi, grafice, sfx, tranziții, zoom, viteză). Întoarce
    un rezumat + view-ul timeline-ului. Verifică rezultatul pe preview cu frames_look.

    Implicit (`subtitrari=True`) subtitrarea e suspendată pe durata hook-ului, ca textul mare al hook-ului
    să nu se bată cu subtitrarea centrată (un singur strat de text vizibil). `subtitrari=False` o lasă pe loc.
    """
    p = project if isinstance(project, Project) else Project(str(project))
    hook = HOOKS_BY_ID.get(hook_id)
    if hook is None:
        raise ValueError(f"hook necunoscut {hook_id!r}; disponibile: {', '.join(h['id'] for h in HOOKS)}")
    at = float(at)
    parts: list[str] = []
    if subtitrari and p.tl.captions:
        n = p.captions_suspend(at, at + float(hook["durata_s"]))  # întâi scoatem subtitrarea din cale
        if n:
            parts.append(f"{n} subtitrări suspendate pe durata hook-ului")
    elif not subtitrari and any(c.end > at and c.start < at + float(hook["durata_s"]) for c in p.tl.captions):
        parts.append("ATENȚIE: subtitrările n-au fost suspendate (subtitrari=False), textul se poate suprapune")
    parts += _BUILD[hook_id](p, at, opțiuni)
    return f"hook „{hook['nume']}” la {at:.2f}s: " + "; ".join(parts) + f"\n{p.tl.view()}"
