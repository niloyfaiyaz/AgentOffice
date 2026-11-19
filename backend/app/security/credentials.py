"""BYOK credential storage.

Primary backend: the operating system credential store via ``keyring`` (macOS Keychain,
Windows Credential Manager, Secret Service on Linux).

Fallback backend (when no OS store is available, or AGENTOFFICE_CREDENTIAL_BACKEND=encrypted_file):
an encrypted file at ``<data_dir>/credentials.enc``. The key is derived with scrypt from a
user-supplied passphrase (AGENTOFFICE_CREDENTIAL_PASSPHRASE) and the file is encrypted with
Fernet (AES-128-CBC + HMAC-SHA256). Limitations: anyone who can read the file *and* knows
the passphrase can decrypt it; the passphrase must be supplied to every process that runs
agents. Secrets are never written to the database, logs, events or the browser.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ..config import settings

SERVICE = "agentoffice"
PROVIDERS = {"anthropic", "openai"}


class CredentialError(Exception):
    pass


def key_hint(secret: str) -> str:
    return f"…{secret[-4:]}" if len(secret) >= 8 else "…"


class KeyringStore:
    name = "keyring"

    def __init__(self) -> None:
        import keyring  # noqa: F401

        self._kr = keyring

    @staticmethod
    def available() -> bool:
        try:
            import keyring
            from keyring.backends import fail

            kr = keyring.get_keyring()
            if isinstance(kr, fail.Keyring):
                return False
            return kr.priority > 0
        except Exception:
            return False

    def set(self, provider: str, secret: str) -> None:
        self._kr.set_password(SERVICE, provider, secret)

    def get(self, provider: str) -> Optional[str]:
        return self._kr.get_password(SERVICE, provider)

    def delete(self, provider: str) -> None:
        try:
            self._kr.delete_password(SERVICE, provider)
        except Exception:
            pass


class EncryptedFileStore:
    name = "encrypted_file"

    def __init__(self, passphrase: Optional[str], path: Optional[Path] = None) -> None:
        if not passphrase:
            raise CredentialError(
                "No OS credential store is available. Set AGENTOFFICE_CREDENTIAL_PASSPHRASE to use the "
                "encrypted-file fallback."
            )
        self.path = path or (settings.data_dir / "credentials.enc")
        self._passphrase = passphrase.encode()

    def _fernet(self, salt: bytes) -> Fernet:
        kdf = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1)
        return Fernet(base64.urlsafe_b64encode(kdf.derive(self._passphrase)))

    def _load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text())
        salt = base64.b64decode(raw["salt"])
        try:
            data = self._fernet(salt).decrypt(raw["token"].encode())
        except InvalidToken as e:
            raise CredentialError("Credential file could not be decrypted (wrong passphrase?)") from e
        return json.loads(data)

    def _save(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        salt = os.urandom(16)
        token = self._fernet(salt).encrypt(json.dumps(values).encode()).decode()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"v": 1, "salt": base64.b64encode(salt).decode(), "token": token}))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def set(self, provider: str, secret: str) -> None:
        values = self._load()
        values[provider] = secret
        self._save(values)

    def get(self, provider: str) -> Optional[str]:
        return self._load().get(provider)

    def delete(self, provider: str) -> None:
        values = self._load()
        if provider in values:
            del values[provider]
            self._save(values)


_store = None


def get_store():
    global _store
    if _store is not None:
        return _store
    backend = settings.credential_backend
    if backend == "keyring" or (backend == "auto" and KeyringStore.available()):
        _store = KeyringStore()
    else:
        _store = EncryptedFileStore(settings.credential_passphrase)
    return _store


def set_store(store) -> None:
    """Testing hook."""
    global _store
    _store = store


def store_backend_name() -> str:
    try:
        return get_store().name
    except CredentialError:
        return "unavailable"


def save_secret(provider: str, secret: str) -> str:
    if provider not in PROVIDERS:
        raise CredentialError(f"Unknown provider {provider}")
    secret = secret.strip()
    if len(secret) < 8 or any(c.isspace() for c in secret):
        raise CredentialError("That does not look like a valid API key")
    store = get_store()
    store.set(provider, secret)
    return store.name


def load_secret(provider: str) -> Optional[str]:
    try:
        return get_store().get(provider)
    except CredentialError:
        return None


def delete_secret(provider: str) -> None:
    get_store().delete(provider)
