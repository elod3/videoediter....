"""Pachetul de postare: ce urcăm, unde și cu ce text. Agentul îl pregătește, omul cere publicarea.

Un pachet stă în `<proiect>/publish/<id>.json`. Nu conține secrete: doar clientul și contul (ca id-uri),
textele, coperta și opțiunile. La publicare, clientul și contul se verifică din nou față de seif.
"""
from __future__ import annotations

import json
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Platform = Literal["youtube", "instagram", "facebook", "tiktok"]
Privacy = Literal["public", "unlisted", "private", "friends", "followers"]

HASHTAG_RE = re.compile(r"(?<!\w)#[\wÀ-ɏ]+")


class PostPackage(BaseModel):
    id: str
    project: str
    client: str
    account: str                      # cheia din seif, ex. "youtube:UCxxxx"
    platform: Platform
    video: str                        # cale relativă la proiect (de obicei renders/...mp4)
    cover: str = ""                   # imagine relativă la proiect (YouTube: thumbnail), opțional
    cover_at_ms: int = -1             # Instagram / TikTok: cadrul folosit drept copertă
    title: str = ""                   # YouTube: titlul; TikTok: textul postării
    caption: str = ""                 # Instagram / Facebook: descrierea; YouTube: descrierea
    hashtags: list[str] = []
    privacy: Privacy = "public"
    schedule_at: str = ""             # ISO 8601 cu fus orar; doar YouTube și Facebook
    options: dict = {}                # opțiuni pe platformă (vezi OPTIONS)
    credits: list[str] = []           # creditele cerute de licențe (muzică CC BY), adăugate la final
    status: Literal["draft", "publishing", "published", "failed"] = "draft"
    result: dict = {}
    created: int = Field(default_factory=lambda: int(time.time()))

    def full_text(self) -> str:
        """Textul final: descrierea + hashtag-urile care nu sunt deja în ea."""
        base = (self.caption if self.platform != "tiktok" else self.title).strip()
        have = {h.lower() for h in HASHTAG_RE.findall(base)}
        extra = [h for h in self.hashtags if h.lower() not in have]
        text = (base + ("\n\n" + " ".join(extra) if extra else "")).strip()
        if self.credits:
            text += "\n\n" + "\n".join(("Muzică: " + c) if not c.lower().startswith(("muzică", "music")) else c
                                         for c in self.credits)
        return text


OPTIONS = {
    "youtube": {"made_for_kids": bool, "category_id": str, "tags": list, "contains_synthetic_media": bool},
    "instagram": {"share_to_feed": bool, "trial": bool},
    "facebook": {},
    "tiktok": {"disable_comment": bool, "disable_duet": bool, "disable_stitch": bool,
               "is_aigc": bool, "brand_content": bool, "brand_organic": bool},
}

# Limitele publicate de platforme (oct. 2026). Cele marcate „hard” le respinge API-ul; restul sunt avertismente.
LIMITS = {
    "youtube": {"title": 100, "text": 5000, "privacy": {"public", "unlisted", "private"}},
    "instagram": {"text": 2200, "hashtags": 5, "privacy": {"public"}},
    "facebook": {"text": 63206, "privacy": {"public"}},
    "tiktok": {"title": 2200, "privacy": {"public", "friends", "followers", "private"}},
}


def norm_hashtags(tags: list[str] | str) -> list[str]:
    if isinstance(tags, str):
        tags = re.split(r"[\s,]+", tags)
    out: list[str] = []
    for t in tags:
        t = t.strip()
        if not t:
            continue
        t = "#" + t.lstrip("#")
        if not re.fullmatch(r"#[\wÀ-ɏ]+", t):
            raise ValueError(f"hashtag invalid: {t} (fără spații sau semne)")
        if t.lower() not in {x.lower() for x in out}:
            out.append(t)
    return out


def validate(pkg: PostPackage, duration: float | None = None) -> list[str]:
    """Erorile blochează (ValueError); avertismentele se întorc ca listă."""
    lim = LIMITS[pkg.platform]
    warn: list[str] = []
    if pkg.privacy not in lim["privacy"]:
        raise ValueError(f"{pkg.platform}: vizibilitatea poate fi {', '.join(sorted(lim['privacy']))}")
    if pkg.platform == "youtube":
        if not pkg.title.strip():
            raise ValueError("YouTube cere titlu")
        if len(pkg.title) > lim["title"]:
            raise ValueError(f"titlul YouTube are {len(pkg.title)} caractere (max {lim['title']})")
        if "<" in pkg.title + pkg.caption or ">" in pkg.title + pkg.caption:
            raise ValueError("YouTube nu acceptă < sau > în titlu și descriere")
        if len(pkg.full_text().encode()) > lim["text"]:
            raise ValueError(f"descrierea YouTube trece de {lim['text']} de octeți")
        if "made_for_kids" not in pkg.options:
            raise ValueError("YouTube: spune explicit made_for_kids (true dacă e făcut pentru copii, altfel false)")
    if pkg.platform == "tiktok" and len(pkg.full_text().encode("utf-16-le")) // 2 > lim["title"]:
        raise ValueError(f"textul TikTok trece de {lim['title']} de caractere")
    if pkg.platform in ("instagram", "facebook") and len(pkg.full_text()) > lim["text"]:
        raise ValueError(f"descrierea are {len(pkg.full_text())} caractere (max {lim['text']})")
    if "hashtags" in lim:
        n = len(HASHTAG_RE.findall(pkg.full_text()))
        if n > lim["hashtags"]:
            raise ValueError(f"Instagram acceptă cel mult {lim['hashtags']} hashtag-uri pe postare (sunt {n})")
    if pkg.schedule_at:
        if pkg.platform not in ("youtube", "facebook"):
            raise ValueError(f"{pkg.platform} nu are programare prin API: publică la ora aleasă")
        when = parse_time(pkg.schedule_at)
        delta = (when - datetime.now(timezone.utc)).total_seconds()
        if delta < 15 * 60:
            raise ValueError("programarea trebuie să fie la cel puțin 15 minute de acum")
        if pkg.platform == "facebook" and delta > 75 * 86400:
            raise ValueError("Facebook programează cel mult 75 de zile înainte")
        if pkg.platform == "youtube" and pkg.privacy != "private":
            warn.append("YouTube: un video programat stă privat până la ora aleasă (îl setez eu așa)")
    known = OPTIONS[pkg.platform]
    for k, v in pkg.options.items():
        if k not in known:
            raise ValueError(f"opțiune necunoscută pentru {pkg.platform}: {k} (merg: {', '.join(known) or 'niciuna'})")
        if not isinstance(v, known[k]):
            raise ValueError(f"opțiunea {k} trebuie să fie {known[k].__name__}")
    if duration is not None:
        if pkg.platform == "facebook" and not 3 <= duration <= 90:
            warn.append(f"Facebook Reels: 3–90 s (clipul are {duration:.0f} s); mai lung va apărea ca video obișnuit")
        if pkg.platform == "instagram" and not 3 <= duration <= 900:
            raise ValueError(f"Instagram Reels prin API: 3 s – 15 min (clipul are {duration:.0f} s)")
        if pkg.platform == "tiktok" and duration > 600:
            warn.append("TikTok: peste 10 min poate fi refuzat de contul creatorului")
    if pkg.platform == "tiktok" and pkg.options.get("brand_content") and pkg.privacy == "private":
        raise ValueError("TikTok: conținutul de brand (parteneriat plătit) nu poate fi privat")
    if pkg.platform == "youtube" and pkg.cover and not pkg.cover.lower().endswith((".png", ".jpg", ".jpeg")):
        raise ValueError("coperta YouTube: PNG sau JPG")
    return warn


def parse_time(s: str) -> datetime:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as e:
        raise ValueError("ora: format ISO, ex. 2026-10-20T18:30:00+03:00") from e
    if dt.tzinfo is None:
        raise ValueError("ora trebuie să aibă fus orar, ex. +03:00")
    return dt.astimezone(timezone.utc)


class Store:
    """Pachetele unui proiect, ca fișiere JSON în <proiect>/publish/."""

    def __init__(self, project_dir: Path):
        self.dir = Path(project_dir) / "publish"

    def new_id(self) -> str:
        return time.strftime("%m%d") + "-" + secrets.token_hex(3)

    def save(self, pkg: PostPackage) -> None:
        self.dir.mkdir(exist_ok=True)
        tmp = self.dir / f"{pkg.id}.tmp"
        tmp.write_text(pkg.model_dump_json(indent=1))
        tmp.replace(self.dir / f"{pkg.id}.json")

    def get(self, pkg_id: str) -> PostPackage:
        if not re.fullmatch(r"[0-9]{4}-[0-9a-f]{6}", pkg_id or ""):
            raise ValueError("id de pachet invalid")
        f = self.dir / f"{pkg_id}.json"
        if not f.exists():
            raise ValueError(f"nu există pachetul {pkg_id}")
        return PostPackage.model_validate_json(f.read_text())

    def all(self) -> list[PostPackage]:
        if not self.dir.exists():
            return []
        return sorted((PostPackage.model_validate(json.loads(f.read_text())) for f in self.dir.glob("*.json")),
                      key=lambda p: p.created)
