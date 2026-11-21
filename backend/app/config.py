"""Runtime configuration. All values come from environment variables with safe local defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    """Load AGENTOFFICE_* settings from the git-ignored .env written by ./agentoffice
    (environment variables always win)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key.startswith("AGENTOFFICE_") and key not in os.environ:
            os.environ[key] = value


_load_dotenv(REPO_ROOT / ".env")


def db_url(dbname: str = "agentoffice") -> str:
    """Connection URL for the local Docker PostgreSQL, using the per-install password."""
    pw = os.environ.get("AGENTOFFICE_DB_PASSWORD", "agentoffice-local")
    return f"postgresql+psycopg://agentoffice:{pw}@127.0.0.1:55432/{dbname}"


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get("AGENTOFFICE_DATABASE_URL", db_url()))
    data_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("AGENTOFFICE_DATA_DIR", str(REPO_ROOT / "data")))
    )
    host: str = field(default_factory=lambda: os.environ.get("AGENTOFFICE_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("AGENTOFFICE_PORT", "8765")))
    # Frontend dev server origin allowed by CORS (only used during development).
    dev_origin: str = field(default_factory=lambda: os.environ.get("AGENTOFFICE_DEV_ORIGIN", "http://127.0.0.1:5173"))
    frontend_dist: Path = field(default_factory=lambda: REPO_ROOT / "frontend" / "dist")
    max_upload_bytes: int = 10 * 1024 * 1024
    worker_poll_seconds: float = 1.0
    lease_seconds: int = 60
    max_parallel_runs: int = 3
    sandbox_image: str = field(default_factory=lambda: os.environ.get("AGENTOFFICE_SANDBOX_IMAGE", "agentoffice-sandbox:1"))
    # The scripted provider is a deterministic, non-AI provider used ONLY for automated
    # end-to-end tests. It is never available unless this flag is set explicitly.
    enable_test_provider: bool = field(default_factory=lambda: _env_bool("AGENTOFFICE_ENABLE_TEST_PROVIDER", False))
    credential_backend: str = field(default_factory=lambda: os.environ.get("AGENTOFFICE_CREDENTIAL_BACKEND", "auto"))
    credential_passphrase: str | None = field(default_factory=lambda: os.environ.get("AGENTOFFICE_CREDENTIAL_PASSPHRASE"))

    @property
    def api_token_file(self) -> Path:
        return self.data_dir / "api-token"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def exports_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def sandbox_dir(self) -> Path:
        return self.data_dir / "sandbox"


settings = Settings()
