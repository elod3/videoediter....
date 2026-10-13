"""Lanț de efecte parametrizate pe un clip (vedit.edit_ops.fx_chain), cu LISTĂ ALBĂ.

Niciodată filtre ffmpeg arbitrare venite ca text: fiecare pas e un nume dintr-o listă albă, iar fiecare
parametru are tip și interval verificate. Altfel un agent (sau un timeline venit din API) ar putea strecura
filtre care citesc fișiere (movie=) ori strică randarea. Efectele se aplică în ordinea din listă, după
efectele fixe ale clipului (`Clip.fx`).
"""
from __future__ import annotations

from .timeline import FxStep


def _even(x: float) -> int:
    return max(2, int(round(x / 2)) * 2)


# fiecare: parametru -> (tip, min, max, implicit); {} = fără parametri
SCHEMA: dict[str, dict[str, tuple]] = {
    "brightness": {"value": ("num", -1.0, 1.0, 0.0)},
    "contrast": {"value": ("num", 0.0, 3.0, 1.0)},
    "saturation": {"value": ("num", 0.0, 3.0, 1.0)},
    "gamma": {"value": ("num", 0.1, 10.0, 1.0)},
    "hue": {"value": ("num", -180.0, 180.0, 0.0)},
    "blur": {"sigma": ("num", 0.0, 50.0, 4.0)},
    "sharpen": {"amount": ("num", 0.0, 5.0, 1.0)},
    "vignette": {"angle": ("num", 0.0, 3.1416, 0.6981)},
    "grain": {"strength": ("num", 0.0, 64.0, 9.0)},
    "zoom": {"value": ("num", 1.0, 4.0, 1.5), "cx": ("num", 0.0, 1.0, 0.5), "cy": ("num", 0.0, 1.0, 0.5)},
    "mirror": {},
    "flip_vertical": {},
    "sepia": {},
}


def _clean(name: str, params: dict) -> dict:
    """Validează și normalizează parametrii unui pas. ValueError cu mesaj clar în română."""
    if name not in SCHEMA:
        raise ValueError(f"efect necunoscut {name!r}; disponibile: {', '.join(sorted(SCHEMA))}")
    spec = SCHEMA[name]
    extra = set(params) - set(spec)
    if extra:
        raise ValueError(f"{name}: parametri necunoscuți {', '.join(sorted(extra))}; acceptați: "
                         f"{', '.join(spec) or '—'}")
    out = {}
    for key, (kind, lo, hi, dflt) in spec.items():
        raw = params.get(key, dflt)
        try:
            val = int(round(float(raw))) if kind == "int" else float(raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name}.{key}: valoare numerică invalidă {raw!r}") from None
        if not lo <= val <= hi:
            raise ValueError(f"{name}.{key}: {val} e în afara intervalului [{lo}, {hi}]")
        out[key] = val
    return out


def compile_step(step: FxStep, W: int, H: int) -> str:
    """Un pas -> fragment de filtru ffmpeg (validat). ValueError dacă numele/parametrii nu-s în listă."""
    name = step.name.strip().lower()
    p = _clean(name, step.params or {})
    if name == "brightness":
        return f"eq=brightness={p['value']:.3f}"
    if name == "contrast":
        return f"eq=contrast={p['value']:.3f}"
    if name == "saturation":
        return f"eq=saturation={p['value']:.3f}"
    if name == "gamma":
        return f"eq=gamma={p['value']:.3f}"
    if name == "hue":
        return f"hue=h={p['value']:.1f}"
    if name == "blur":
        return f"gblur=sigma={p['sigma']:.2f}"
    if name == "sharpen":
        return f"unsharp=5:5:{p['amount']:.2f}"
    if name == "vignette":
        return f"vignette={p['angle']:.4f}"
    if name == "grain":
        return f"noise=alls={int(round(p['strength']))}:allf=t"
    if name == "zoom":
        z = max(p["value"], 1.0)
        cw, ch = _even(W / z), _even(H / z)
        x = int(max(0, min(p["cx"] * W - cw / 2, W - cw)))
        y = int(max(0, min(p["cy"] * H - ch / 2, H - ch)))
        return f"crop={cw}:{ch}:{x}:{y},scale={W}:{H}"
    if name == "mirror":
        return "hflip"
    if name == "flip_vertical":
        return "vflip"
    if name == "sepia":
        return "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131"
    raise ValueError(f"efect necunoscut {name!r}")  # pragma: no cover (acoperit de _clean)


def compile_chain(c, W: int, H: int) -> list[str]:
    """Toate efectele din lanțul unui clip -> fragmente de filtru (validare inclusă)."""
    return [compile_step(s, W, H) for s in getattr(c, "fx_chain", []) or []]


def validate_steps(steps: list[FxStep]) -> None:
    """Verifică un lanț fără să randăm (aceleași reguli ca la compilare)."""
    for s in steps:
        compile_step(s, 1920, 1080)


def describe() -> str:
    """Text pentru agent: efectele disponibile și parametrii lor."""
    rows = []
    for name in sorted(SCHEMA):
        spec = SCHEMA[name]
        pars = ", ".join(f"{k}={v[3]}" if v[0] == "num" else f"{k}({v[1]}-{v[2]})" for k, v in spec.items()) or "—"
        rows.append(f"{name}: {pars}")
    return "\n".join(rows)
