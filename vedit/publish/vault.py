"""Seiful de conturi: tokenurile fiecărui client, criptate, izolate pe client.

Cum stă pe disc (VEDIT_VAULT_DIR, implicit ~/.config/vedit/vault; NU în VEDIT_HOME, unde lucrează agentul):

    vault/
      index.json            # fără secrete: clienți, conturi (nume afișat), proiect -> client
      apps.enc              # cheile aplicațiilor (Google, Meta, TikTok), ale agenției
      clients/<id>.enc      # tokenurile unui singur client
      key.wrapped           # cheia seifului, criptată cu parola de recuperare (pentru backup)
    ~/.config/vedit/vault.key   # cheia seifului în clar, 0600, doar pe laptop

Criptare: AES-256-GCM cu cheia seifului (32 de octeți aleatori). Cheia e „împachetată” cu o cheie derivată
din parola de recuperare (scrypt), deci backup-ul (tot folderul vault/) poate sta pe un server străin:
fără parolă nu se poate citi nimic. Pe laptop nu se cere parola la fiecare postare: se folosește vault.key.

Izolarea: tokenurile unui client stau într-un fișier al lui; `client_for_project` e singura legătură
proiect -> client și se schimbă doar din CLI (`vedit-accounts link`), niciodată dintr-un tool de agent.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import time
from pathlib import Path

ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,47}")
PLATFORMS = ("youtube", "instagram", "facebook", "tiktok")


class VaultError(Exception):
    pass


def vault_dir() -> Path:
    return Path(os.environ.get("VEDIT_VAULT_DIR") or Path.home() / ".config/vedit/vault").expanduser()


def key_file() -> Path:
    return Path(os.environ.get("VEDIT_VAULT_KEY_FILE") or Path.home() / ".config/vedit/vault.key").expanduser()


def _aes():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as e:  # pragma: no cover - dependență opțională
        raise VaultError("lipsește pachetul cryptography: pip install -e '.[publish]'") from e
    return AESGCM


def _seal(key: bytes, data: bytes, aad: bytes) -> bytes:
    nonce = secrets.token_bytes(12)
    return b"VV1" + nonce + _aes()(key).encrypt(nonce, data, aad)


def _open(key: bytes, blob: bytes, aad: bytes) -> bytes:
    if not blob.startswith(b"VV1"):
        raise VaultError("fișier de seif necunoscut")
    try:
        return _aes()(key).decrypt(blob[3:15], blob[15:], aad)
    except Exception as e:
        raise VaultError("nu pot decripta: cheie greșită sau fișier stricat") from e


def _kdf(passphrase: str, salt: bytes) -> bytes:
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())


def _write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    tmp.replace(path)


def check_id(value: str, what: str = "id") -> str:
    if not ID_RE.fullmatch(value or ""):
        raise VaultError(f"{what}: doar litere mici, cifre, _ și - (ex. service-rares)")
    return value


class Vault:
    def __init__(self, root: Path | None = None, keyfile: Path | None = None):
        self.root = Path(root) if root else vault_dir()
        self.keyfile = Path(keyfile) if keyfile else key_file()

    # ---------- cheie ----------
    @property
    def initialized(self) -> bool:
        return (self.root / "key.wrapped").exists()

    def init(self, passphrase: str) -> None:
        """Seif nou: cheie aleatoare, salvată local și împachetată cu parola de recuperare."""
        if self.initialized:
            raise VaultError("seiful există deja")
        if len(passphrase) < 12:
            raise VaultError("parola de recuperare: minimum 12 caractere (o frază e cel mai bine)")
        key = secrets.token_bytes(32)
        self._wrap(key, passphrase)
        _write(self.keyfile, base64.b64encode(key))
        self._save_index({"clients": {}, "projects": {}})

    def _wrap(self, key: bytes, passphrase: str) -> None:
        salt = secrets.token_bytes(16)
        blob = _seal(_kdf(passphrase, salt), key, b"key")
        _write(self.root / "key.wrapped", json.dumps({
            "v": 1, "kdf": "scrypt-n15-r8-p1", "salt": base64.b64encode(salt).decode(),
            "key": base64.b64encode(blob).decode()}).encode())

    def unlock_with_passphrase(self, passphrase: str) -> None:
        """După restaurare (laptop formatat): scoate cheia din key.wrapped și o pune la loc în vault.key."""
        w = json.loads((self.root / "key.wrapped").read_text())
        try:
            key = _open(_kdf(passphrase, base64.b64decode(w["salt"])), base64.b64decode(w["key"]), b"key")
        except VaultError as e:
            raise VaultError("parola de recuperare nu e bună") from e
        _write(self.keyfile, base64.b64encode(key))

    def change_passphrase(self, new: str) -> None:
        if len(new) < 12:
            raise VaultError("parola de recuperare: minimum 12 caractere")
        self._wrap(self._key(), new)

    def _key(self) -> bytes:
        if not self.keyfile.exists():
            if self.initialized:
                raise VaultError("seiful e blocat pe laptopul ăsta: rulează `vedit-accounts unlock` cu parola de recuperare")
            raise VaultError("nu există seif: rulează `vedit-accounts init`")
        key = base64.b64decode(self.keyfile.read_text().strip())
        if len(key) != 32:
            raise VaultError("vault.key e stricat")
        return key

    # ---------- index (fără secrete) ----------
    def index(self) -> dict:
        f = self.root / "index.json"
        if not f.exists():
            return {"clients": {}, "projects": {}}
        return json.loads(f.read_text())

    def _save_index(self, idx: dict) -> None:
        _write(self.root / "index.json", json.dumps(idx, ensure_ascii=False, indent=1).encode())

    # ---------- clienți ----------
    def add_client(self, client_id: str, name: str = "") -> None:
        check_id(client_id, "clientul")
        idx = self.index()
        if client_id in idx["clients"]:
            raise VaultError(f"clientul {client_id} există deja")
        idx["clients"][client_id] = {"name": name or client_id, "accounts": {}, "created": int(time.time())}
        self._save_index(idx)
        self._save_secrets(client_id, {})

    def remove_client(self, client_id: str) -> None:
        idx = self.index()
        idx["clients"].pop(check_id(client_id, "clientul"), None)
        idx["projects"] = {p: c for p, c in idx["projects"].items() if c != client_id}
        self._save_index(idx)
        (self.root / "clients" / f"{client_id}.enc").unlink(missing_ok=True)

    def clients(self) -> dict:
        return self.index()["clients"]

    # ---------- proiect -> client (doar din CLI) ----------
    def link_project(self, project: str, client_id: str) -> None:
        idx = self.index()
        if client_id not in idx["clients"]:
            raise VaultError(f"nu există clientul {client_id}")
        old = idx["projects"].get(project)
        if old and old != client_id:
            raise VaultError(f"proiectul {project} e deja al clientului {old}; rulează întâi `vedit-accounts unlink {project}`")
        idx["projects"][project] = client_id
        self._save_index(idx)

    def unlink_project(self, project: str) -> None:
        idx = self.index()
        idx["projects"].pop(project, None)
        self._save_index(idx)

    def client_for_project(self, project: str) -> str | None:
        return self.index()["projects"].get(project)

    # ---------- conturi ----------
    def _client_file(self, client_id: str) -> Path:
        return self.root / "clients" / f"{check_id(client_id, 'clientul')}.enc"

    def _load_secrets(self, client_id: str) -> dict:
        f = self._client_file(client_id)
        if not f.exists():
            return {}
        return json.loads(_open(self._key(), f.read_bytes(), f"client:{client_id}".encode()))

    def _save_secrets(self, client_id: str, data: dict) -> None:
        blob = _seal(self._key(), json.dumps(data).encode(), f"client:{client_id}".encode())
        _write(self._client_file(client_id), blob)

    def put_account(self, client_id: str, platform: str, account_id: str, display: str, secrets_: dict) -> None:
        if platform not in PLATFORMS:
            raise VaultError(f"platforma: {', '.join(PLATFORMS)}")
        idx = self.index()
        if client_id not in idx["clients"]:
            raise VaultError(f"nu există clientul {client_id}")
        # același cont (același id de pe platformă) nu are voie să fie la doi clienți
        for other, c in idx["clients"].items():
            if other != client_id and f"{platform}:{account_id}" in c["accounts"]:
                raise VaultError(f"contul ăsta de {platform} e deja conectat la clientul {other}")
        sec = self._load_secrets(client_id)
        sec[f"{platform}:{account_id}"] = secrets_
        self._save_secrets(client_id, sec)
        idx["clients"][client_id]["accounts"][f"{platform}:{account_id}"] = {
            "platform": platform, "id": account_id, "display": display, "connected": int(time.time())}
        self._save_index(idx)

    def remove_account(self, client_id: str, key: str) -> None:
        sec = self._load_secrets(client_id)
        sec.pop(key, None)
        self._save_secrets(client_id, sec)
        idx = self.index()
        idx["clients"].get(client_id, {}).get("accounts", {}).pop(key, None)
        self._save_index(idx)

    def accounts(self, client_id: str, platform: str | None = None) -> dict:
        acc = self.index()["clients"].get(client_id, {}).get("accounts", {})
        return {k: v for k, v in acc.items() if platform is None or v["platform"] == platform}

    def secrets_for(self, client_id: str, key: str) -> dict:
        if key not in self.accounts(client_id):
            raise VaultError(f"contul {key} nu e al clientului {client_id}")
        sec = self._load_secrets(client_id)
        if key not in sec:
            raise VaultError(f"lipsește tokenul pentru {key}: reconectează contul")
        return sec[key]

    def update_secrets(self, client_id: str, key: str, patch: dict) -> None:
        """Tokenuri reîmprospătate (refresh) scrise înapoi în fișierul clientului."""
        sec = self._load_secrets(client_id)
        if key not in sec:
            raise VaultError(f"contul {key} nu e al clientului {client_id}")
        sec[key].update(patch)
        self._save_secrets(client_id, sec)

    # ---------- aplicațiile agenției ----------
    def apps(self) -> dict:
        f = self.root / "apps.enc"
        return json.loads(_open(self._key(), f.read_bytes(), b"apps")) if f.exists() else {}

    def set_app(self, platform: str, values: dict) -> None:
        if platform not in ("google", "meta", "tiktok"):
            raise VaultError("aplicația: google, meta sau tiktok")
        apps = self.apps()
        apps[platform] = {k: v for k, v in values.items() if v}
        _write(self.root / "apps.enc", _seal(self._key(), json.dumps(apps).encode(), b"apps"))

    def app(self, platform: str) -> dict:
        a = self.apps().get(platform)
        if not a:
            raise VaultError(f"nu e configurată aplicația {platform}: `vedit-accounts app {platform} ...`")
        return a
