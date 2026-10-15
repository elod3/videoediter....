"""`vedit-accounts`: conturile clienților, din terminal. Doar omul rulează comenzile astea.

    vedit-accounts init                          # seif nou + parola de recuperare
    vedit-accounts app google|meta|tiktok        # cheile aplicațiilor agenției (o singură dată)
    vedit-accounts client add service-rares --name "Service Rareș"
    vedit-accounts connect service-rares youtube|meta|tiktok
    vedit-accounts link proiect-rares service-rares
    vedit-accounts list
    vedit-accounts posts proiect-rares           # pachetele de postare ale proiectului
    vedit-accounts publish proiect-rares 1015-ab12cd
    vedit-accounts backup  /  restore            # copia criptată pe server (sero)
    vedit-accounts journal                       # ce s-a publicat, unde, când
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .vault import Vault, VaultError, check_id

CONFIG = Path(os.environ.get("VEDIT_ACCOUNTS_CONFIG") or Path.home() / ".config/vedit/accounts.json").expanduser()


def _cfg() -> dict:
    return json.loads(CONFIG.read_text()) if CONFIG.exists() else {}


def _save_cfg(cfg: dict) -> None:
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, indent=1))


def _ask_secret(label: str, value: str | None) -> str:
    return value if value else getpass.getpass(f"{label}: ").strip()


def _new_passphrase() -> str:
    print("Parola de recuperare deschide backup-ul dacă formatezi laptopul. Scrie-o undeva sigur (nu pe laptop).")
    p1 = getpass.getpass("Parola de recuperare (minimum 12 caractere): ")
    p2 = getpass.getpass("Încă o dată: ")
    if p1 != p2:
        raise VaultError("parolele nu se potrivesc")
    return p1


def cmd_init(v: Vault, a) -> None:
    v.init(_new_passphrase())
    print(f"Seif creat în {v.root}. Cheia locală: {v.keyfile}")


def cmd_unlock(v: Vault, a) -> None:
    v.unlock_with_passphrase(getpass.getpass("Parola de recuperare: "))
    print("Seif deblocat pe laptopul ăsta.")


def cmd_passwd(v: Vault, a) -> None:
    v.change_passphrase(_new_passphrase())
    print("Parola de recuperare schimbată. Fă un backup nou: vedit-accounts backup")


def cmd_app(v: Vault, a) -> None:
    if a.platform == "google":
        vals = {"client_id": a.id or input("Google OAuth client ID (tip Desktop app): ").strip(),
                "client_secret": _ask_secret("Google client secret", a.secret)}
    elif a.platform == "meta":
        vals = {"app_id": a.id or input("Meta App ID: ").strip(), "app_secret": _ask_secret("Meta App secret", a.secret)}
    else:
        vals = {"client_key": a.id or input("TikTok client key: ").strip(),
                "client_secret": _ask_secret("TikTok client secret", a.secret)}
    v.set_app(a.platform, vals)
    print(f"Aplicația {a.platform} salvată (criptat).")


def cmd_client(v: Vault, a) -> None:
    if a.action == "add":
        v.add_client(a.client, a.name or "")
        print(f"Client nou: {a.client}")
    elif a.action == "remove":
        if input(f"Șterg clientul {a.client} și toate conturile lui din seif? scrie numele ca să confirmi: ") != a.client:
            print("Anulat.")
            return
        v.remove_client(a.client)
        print("Șters.")


def cmd_list(v: Vault, a) -> None:
    idx = v.index()
    if not idx["clients"]:
        print("Niciun client încă: vedit-accounts client add <id> --name \"...\"")
    for cid, c in idx["clients"].items():
        print(f"\n{cid}  ({c['name']})")
        for k, acc in c["accounts"].items():
            print(f"   {acc['platform']:<9} {acc['display']:<30} {k}")
        projects = [p for p, owner in idx["projects"].items() if owner == cid]
        if projects:
            print("   proiecte: " + ", ".join(projects))


def cmd_connect(v: Vault, a) -> None:
    check_id(a.client, "clientul")
    if a.client not in v.clients():
        raise VaultError(f"nu există clientul {a.client}: vedit-accounts client add {a.client}")
    browser = not a.no_browser
    if a.platform == "youtube":
        from . import youtube
        cid, name, sec = youtube.connect(v.app("google"), browser)
        v.put_account(a.client, "youtube", cid, name, sec)
        print(f"YouTube conectat: {name}")
    elif a.platform == "tiktok":
        from . import tiktok
        oid, name, sec = tiktok.connect(v.app("tiktok"), browser)
        v.put_account(a.client, "tiktok", oid, name, sec)
        print(f"TikTok conectat: {name}")
    else:
        from . import meta

        def choose(pages):
            print("\nPaginile găsite:")
            for i, p in enumerate(pages):
                ig = p.get("instagram_business_account")
                print(f"  {i + 1}. {p['name']}" + (f"  +  Instagram @{ig.get('username')}" if ig else "  (fără Instagram legat)"))
            raw = input(f"Ce pagini sunt ale clientului {a.client}? (ex. 1 sau 1,3): ").strip()
            return [int(x) - 1 for x in raw.replace(" ", "").split(",") if x.isdigit() and 0 < int(x) <= len(pages)]

        for platform, aid, name, sec in meta.connect(v.app("meta"), browser, choose):
            v.put_account(a.client, platform, aid, name, sec)
            print(f"{platform} conectat: {name}")


def cmd_disconnect(v: Vault, a) -> None:
    v.remove_account(a.client, a.account)
    print(f"Scos {a.account} de la {a.client}.")


def cmd_link(v: Vault, a) -> None:
    v.link_project(a.project, a.client)
    print(f"Proiectul {a.project} e al clientului {a.client}: se poate posta doar pe conturile lui.")


def cmd_unlink(v: Vault, a) -> None:
    v.unlink_project(a.project)
    print(f"Proiectul {a.project} nu mai e legat de niciun client.")


def _project_dir(name: str) -> Path:
    from ..project import home
    return home() / name


def cmd_posts(v: Vault, a) -> None:
    from .package import Store
    from .service import preview
    pk = Store(_project_dir(a.project)).all()
    if not pk:
        print("Niciun pachet de postare în proiectul ăsta.")
    for p in pk:
        print("\n" + preview(v, p))


def cmd_publish(v: Vault, a) -> None:
    from .package import Store
    from .service import preview, publish
    d = _project_dir(a.project)
    pkg = Store(d).get(a.package)
    print(preview(v, pkg))
    if not a.yes and input("\nPublic acum? scrie DA: ").strip() != "DA":
        print("Anulat.")
        return
    os.environ["VEDIT_ALLOW_PUBLISH"] = "1"  # omul a confirmat în terminal
    res = publish(v, a.project, d, a.package, log=lambda m: print("  " + m))
    print("\nPublicat: " + (res.get("url") or json.dumps(res, ensure_ascii=False)))
    if res.get("warning"):
        print("Atenție: " + res["warning"])


def _remote(a) -> tuple[str, str]:
    cfg = _cfg()
    remote = a.remote or os.environ.get("VEDIT_VAULT_REMOTE") or cfg.get("remote")
    key = a.ssh_key or os.environ.get("VEDIT_VAULT_SSH_KEY") or cfg.get("ssh_key", "")
    if not remote:
        raise VaultError("unde fac backup? ex.: vedit-accounts backup --remote root@server:/root/vedit-vault "
                         "--ssh-key ~/.ssh/cheie --save")
    if a.save:
        cfg.update({"remote": remote, "ssh_key": key})
        _save_cfg(cfg)
    return remote, os.path.expanduser(key)


def _rsync(src: str, dst: str, key: str) -> None:
    if not shutil.which("rsync"):
        raise VaultError("lipsește rsync")
    ssh = "ssh -o BatchMode=yes" + (f" -i {key}" if key else "")
    subprocess.run(["rsync", "-a", "--chmod=D700,F600", "-e", ssh, src, dst], check=True)


def cmd_backup(v: Vault, a) -> None:
    if not v.initialized:
        raise VaultError("nu există seif")
    remote, key = _remote(a)
    host, _, path = remote.partition(":")
    subprocess.run(["ssh", "-o", "BatchMode=yes", *(["-i", key] if key else []), host,
                    f"mkdir -p {path} && chmod 700 {path}"], check=True)
    _rsync(str(v.root) + "/", remote.rstrip("/") + "/", key)
    cfg = _cfg()
    cfg["last_backup"] = int(time.time())
    _save_cfg(cfg)
    print(f"Backup făcut în {remote} (doar fișiere criptate; cheia rămâne pe laptop și în parola ta).")


def cmd_restore(v: Vault, a) -> None:
    remote, key = _remote(a)
    if v.initialized and input("Există deja un seif aici. Îl suprascriu cu backup-ul? scrie DA: ").strip() != "DA":
        print("Anulat.")
        return
    v.root.mkdir(parents=True, exist_ok=True)
    _rsync(remote.rstrip("/") + "/", str(v.root) + "/", key)
    v.unlock_with_passphrase(getpass.getpass("Parola de recuperare: "))
    print("Seif restaurat și deblocat. Verifică: vedit-accounts list")


def cmd_journal(v: Vault, a) -> None:
    f = v.root / "journal.jsonl"
    if not f.exists():
        print("Nimic publicat încă.")
        return
    for line in f.read_text().splitlines()[-a.n:]:
        j = json.loads(line)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(j["at"]))
        res = j["result"].get("url") or j["result"].get("error", "")
        print(f"{when}  {'OK ' if j['ok'] else 'ERR'}  {j['client']:<18} {j['platform']:<9} {j['project']:<20} {res}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vedit-accounts", description="Conturile clienților pentru publicare.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("unlock")
    sub.add_parser("passwd")
    p = sub.add_parser("app")
    p.add_argument("platform", choices=["google", "meta", "tiktok"])
    p.add_argument("--id")
    p.add_argument("--secret")
    p = sub.add_parser("client")
    p.add_argument("action", choices=["add", "remove"])
    p.add_argument("client")
    p.add_argument("--name")
    sub.add_parser("list")
    p = sub.add_parser("connect")
    p.add_argument("client")
    p.add_argument("platform", choices=["youtube", "meta", "tiktok"])
    p.add_argument("--no-browser", action="store_true")
    p = sub.add_parser("disconnect")
    p.add_argument("client")
    p.add_argument("account", help="cheia din `list`, ex. youtube:UCxxxx")
    p = sub.add_parser("link")
    p.add_argument("project")
    p.add_argument("client")
    p = sub.add_parser("unlink")
    p.add_argument("project")
    p = sub.add_parser("posts")
    p.add_argument("project")
    p = sub.add_parser("publish")
    p.add_argument("project")
    p.add_argument("package")
    p.add_argument("--yes", action="store_true", help="fără întrebarea de confirmare")
    for name in ("backup", "restore"):
        p = sub.add_parser(name)
        p.add_argument("--remote")
        p.add_argument("--ssh-key")
        p.add_argument("--save", action="store_true", help="ține minte serverul pentru data viitoare")
    p = sub.add_parser("journal")
    p.add_argument("-n", type=int, default=30)
    a = ap.parse_args(argv)
    try:
        globals()[f"cmd_{a.cmd}"](Vault(), a)
    except (VaultError, ValueError, RuntimeError, PermissionError) as e:
        print(f"Eroare: {e}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print(f"Eroare la comanda {e.cmd[0]}: cod {e.returncode}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
