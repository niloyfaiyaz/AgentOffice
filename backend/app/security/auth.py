"""Local API authentication.

A random per-install token (``data/api-token``, owner-readable only) protects the API from other
programs and other users on the same machine. Browsers present it as an HttpOnly, SameSite=Strict
cookie obtained once via ``/api/auth/session?token=...`` (the launcher opens that link); scripts
send ``Authorization: Bearer <token>``. AGENTOFFICE_API_TOKEN overrides the file (tests).
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

from ..config import settings

COOKIE = "agentoffice_session"
_cached: Optional[str] = None


def api_token() -> str:
    global _cached
    env = os.environ.get("AGENTOFFICE_API_TOKEN")
    if env:
        return env
    if _cached:
        return _cached
    path: Path = settings.api_token_file
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32))
    _cached = path.read_text().strip()
    return _cached


def valid(candidate: Optional[str]) -> bool:
    return bool(candidate) and secrets.compare_digest(candidate.encode(), api_token().encode())


def request_token(headers, cookies) -> Optional[str]:
    auth = headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return cookies.get(COOKIE)
