"""Pregătirea și publicarea unui pachet, cu verificările care țin clienții separați.

Reguli (impuse aici, nu lăsate pe seama agentului):
  1. Proiectul trebuie să fie legat de un client în seif (`vedit-accounts link`, doar din CLI).
  2. Contul ales trebuie să fie al ACELUI client și pe platforma pachetului.
  3. La publicare, legătura se verifică din nou: dacă proiectul a trecut între timp la alt client, refuz.
  4. Publicarea cere VEDIT_ALLOW_PUBLISH=1 și nu merge niciodată dintr-un job cu lacăt (site).
  5. Un pachet publicat nu se mai publică a doua oară (fără dubluri pe contul clientului).
  6. Fiecare publicare se scrie în jurnalul seifului (cine, ce, unde, linkul).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .. import guard
from .package import PostPackage, Store, norm_hashtags, validate
from .vault import Vault, VaultError

STALE_PUBLISHING = 30 * 60


def _client(vault: Vault, project: str) -> str:
    c = vault.client_for_project(project)
    if not c:
        raise VaultError(f"proiectul {project} nu e legat de niciun client. Omul rulează: "
                         f"vedit-accounts link {project} <client>")
    return c


def _pick_account(vault: Vault, client: str, platform: str, hint: str) -> str:
    accs = vault.accounts(client, platform)
    if not accs:
        raise VaultError(f"clientul {client} n-are niciun cont de {platform} conectat "
                         f"(omul rulează: vedit-accounts connect {client} {platform})")
    if hint:
        h = hint.lower().lstrip("@")
        hits = [k for k, a in accs.items() if h in (a["id"].lower(), a["display"].lower().lstrip("@"), k.lower())]
        if len(hits) != 1:
            raise VaultError(f"contul „{hint}” nu e printre conturile de {platform} ale clientului {client}: "
                             + ", ".join(a["display"] for a in accs.values()))
        return hits[0]
    if len(accs) > 1:
        raise VaultError(f"clientul {client} are mai multe conturi de {platform}; alege unul cu account=: "
                         + ", ".join(a["display"] for a in accs.values()))
    return next(iter(accs))


def _inside(project_dir: Path, rel: str, what: str) -> Path:
    if not rel:
        raise ValueError(f"lipsește {what}")
    p = (project_dir / rel).resolve()
    root = project_dir.resolve()
    if root not in p.parents:
        raise guard.GuardError(f"{what} trebuie să fie în proiect")
    if not p.is_file():
        raise ValueError(f"nu găsesc {what}: {rel} (randează întâi)")
    return p


def prepare(vault: Vault, project: str, project_dir: Path, *, platform: str, video: str, title: str = "",
            caption: str = "", hashtags: list[str] | str = (), privacy: str = "public", schedule_at: str = "",
            cover: str = "", cover_at: float = -1, account: str = "", options: dict | None = None,
            duration: float | None = None, credits: list[str] | None = None) -> tuple[PostPackage, list[str]]:
    client = _client(vault, project)
    key = _pick_account(vault, client, platform, account)
    _inside(project_dir, video, "clipul")
    if cover:
        _inside(project_dir, cover, "coperta")
    store = Store(project_dir)
    pkg = PostPackage(id=store.new_id(), project=project, client=client, account=key, platform=platform,
                      video=video, cover=cover, cover_at_ms=int(cover_at * 1000) if cover_at >= 0 else -1,
                      title=title.strip(), caption=caption.strip(), hashtags=norm_hashtags(list(hashtags) if not
                      isinstance(hashtags, str) else hashtags), privacy=privacy, schedule_at=schedule_at,
                      options=options or {}, credits=list(credits or []))
    warnings = validate(pkg, duration)
    store.save(pkg)
    return pkg, warnings


def preview(vault: Vault, pkg: PostPackage) -> str:
    acc = vault.accounts(pkg.client).get(pkg.account, {})
    name = vault.clients().get(pkg.client, {}).get("name", pkg.client)
    lines = [f"Pachet {pkg.id} · {pkg.platform} · {pkg.status}",
             f"Client: {name}  ·  cont: {acc.get('display', pkg.account)}",
             f"Clip: {pkg.video}" + (f"  ·  copertă: {pkg.cover}" if pkg.cover else "")
             + (f"  ·  copertă la {pkg.cover_at_ms / 1000:.1f}s" if pkg.cover_at_ms >= 0 else ""),
             f"Vizibilitate: {pkg.privacy}" + (f"  ·  programat: {pkg.schedule_at}" if pkg.schedule_at else "")]
    if pkg.title and pkg.platform == "youtube":
        lines.append(f"Titlu: {pkg.title}")
    lines += ["Text:", "  " + pkg.full_text().replace("\n", "\n  ")]
    if pkg.options:
        lines.append("Opțiuni: " + ", ".join(f"{k}={v}" for k, v in pkg.options.items()))
    if pkg.result:
        lines.append("Rezultat: " + json.dumps(pkg.result, ensure_ascii=False))
    return "\n".join(lines)


def publish(vault: Vault, project: str, project_dir: Path, pkg_id: str, log=print) -> dict:
    guard.require_publish_consent()
    store = Store(project_dir)
    pkg = store.get(pkg_id)
    if pkg.project != project:
        raise guard.GuardError("pachetul nu e al proiectului ăstuia")
    if pkg.status == "published":
        raise ValueError(f"pachetul {pkg.id} e deja publicat: {pkg.result.get('url') or pkg.result}")
    if pkg.status == "publishing" and time.time() - pkg.result.get("started", 0) < STALE_PUBLISHING:
        raise ValueError("pachetul se publică deja (pornit acum mai puțin de 30 de minute)")
    client_now = _client(vault, project)
    if client_now != pkg.client:
        raise guard.GuardError(f"pachetul e pentru clientul {pkg.client}, dar proiectul e acum al lui {client_now}: "
                               "pregătește-l din nou")
    acc = vault.accounts(pkg.client).get(pkg.account)
    if not acc or acc["platform"] != pkg.platform:
        raise guard.GuardError("contul din pachet nu mai e conectat la clientul ăsta")
    video = _inside(project_dir, pkg.video, "clipul")
    cover = _inside(project_dir, pkg.cover, "coperta") if pkg.cover else None
    validate(pkg)
    sec = vault.secrets_for(pkg.client, pkg.account)

    def save(patch):
        vault.update_secrets(pkg.client, pkg.account, patch)

    pkg.status, pkg.result = "publishing", {"started": int(time.time())}
    store.save(pkg)
    try:
        if pkg.platform == "youtube":
            from . import youtube
            res = youtube.publish(vault.app("google"), sec, save, pkg, video, cover, log)
        elif pkg.platform == "tiktok":
            from . import tiktok
            res = tiktok.publish(vault.app("tiktok"), sec, save, pkg, video, log)
        elif pkg.platform == "instagram":
            from . import meta
            res = meta.publish_instagram(sec, acc["id"], pkg, video, log)
        else:
            from . import meta
            res = meta.publish_facebook(sec, acc["id"], pkg, video, log)
    except Exception as e:
        pkg.status, pkg.result = "failed", {"error": str(e)[:1000], "at": int(time.time())}
        store.save(pkg)
        _journal(vault, pkg, ok=False)
        raise
    pkg.status, pkg.result = "published", {**res, "at": int(time.time())}
    store.save(pkg)
    _journal(vault, pkg, ok=True)
    return pkg.result


def _journal(vault: Vault, pkg: PostPackage, ok: bool) -> None:
    line = {"at": int(time.time()), "ok": ok, "project": pkg.project, "client": pkg.client, "account": pkg.account,
            "platform": pkg.platform, "package": pkg.id, "result": pkg.result}
    vault.root.mkdir(parents=True, exist_ok=True)
    with open(vault.root / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
