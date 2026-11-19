"""Test configuration.

Tests run against a real PostgreSQL database (agentoffice_test) with migrations applied.
Tests that use the scripted provider exercise the real orchestration engine with a
deterministic, non-AI model; they are labelled MOCKED-PROVIDER in their docstrings.
"""
import os

TEST_DB = os.environ.get("AGENTOFFICE_TEST_DATABASE_URL",
                         "postgresql+psycopg://agentoffice:agentoffice-local@127.0.0.1:55432/agentoffice_test")
os.environ["AGENTOFFICE_DATABASE_URL"] = TEST_DB
os.environ["AGENTOFFICE_ENABLE_TEST_PROVIDER"] = "1"
os.environ.setdefault("AGENTOFFICE_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data", "test"))

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

HERE = os.path.dirname(__file__)


def _alembic_cfg() -> Config:
    cfg = Config(os.path.join(HERE, "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "..", "migrations"))
    cfg.set_main_option("sqlalchemy.url", TEST_DB)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def migrated():
    command.downgrade(_alembic_cfg(), "base")
    command.upgrade(_alembic_cfg(), "head")
    yield


class MemoryStore:
    name = "memory"

    def __init__(self):
        self.v = {}

    def set(self, p, s):
        self.v[p] = s

    def get(self, p):
        return self.v.get(p)

    def delete(self, p):
        self.v.pop(p, None)


@pytest.fixture(autouse=True)
def clean_db(migrated):
    from app.db import engine
    from app.models import Base
    from app.security import credentials

    credentials.set_store(MemoryStore())
    with engine.begin() as conn:
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, headers={"X-AgentOffice-Client": "1"}) as c:
        yield c
