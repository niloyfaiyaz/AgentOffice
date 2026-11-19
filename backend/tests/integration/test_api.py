"""API tests against the real database (no model calls)."""
import io

from sqlalchemy import inspect

from tests.helpers import make_project


def test_project_crud_archive_delete(client):
    r = client.post("/api/projects", json={"name": "", "objective": "x"})
    assert r.status_code == 422
    p = client.post("/api/projects", json={"name": "Alpha", "objective": "Build a thing", "budget_usd": 3}).json()
    assert p["status"] == "draft"
    p2 = client.patch(f"/api/projects/{p['id']}", json={"name": "Beta", "deliverables": ["A", " "]}).json()
    assert p2["name"] == "Beta" and p2["deliverables"] == ["A"]
    assert client.get(f"/api/projects/{p['id']}/budget").json()["budget_usd"] == 3.0
    hints = client.get(f"/api/projects/{p['id']}/intake-check").json()["hints"]
    assert {h["field"] for h in hints} >= {"objective", "success_criteria"}
    client.post(f"/api/projects/{p['id']}/archive")
    assert client.get("/api/projects").json() == []
    assert len(client.get("/api/projects", params={"archived": True}).json()) == 1
    client.post(f"/api/projects/{p['id']}/unarchive")
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_team_editing_and_permissions(client):
    p = make_project(client, roles=("project_manager", "developer"))
    agents = client.get(f"/api/projects/{p['id']}/agents").json()
    pm = next(a for a in agents if a["role_key"] == "project_manager")
    assert pm["is_orchestrator"]
    dev = next(a for a in agents if a["role_key"] == "developer")
    assert "code_execution" in dev["tools"]
    r = client.patch(f"/api/projects/{p['id']}/agents/{dev['id']}",
                     json={"name": "Devon", "tools": ["artifact_write"], "spend_limit_usd": 1.5, "effort": "high"})
    assert r.status_code == 200 and r.json()["tools"] == ["artifact_write"] and r.json()["display_name"] == "Devon"
    assert client.patch(f"/api/projects/{p['id']}/agents/{dev['id']}", json={"tools": ["root_shell"]}).status_code == 422
    assert client.patch(f"/api/projects/{p['id']}/agents/{dev['id']}", json={"effort": "ultra"}).status_code == 422
    custom = client.post(f"/api/projects/{p['id']}/agents", json={"name": "Lee", "role": "Legal Reviewer"}).json()
    assert custom["role_key"] == "legal_reviewer"
    assert client.delete(f"/api/projects/{p['id']}/agents/{custom['id']}").status_code == 200
    preset = client.post(f"/api/projects/{p['id']}/team/save-preset", json={"name": "My team"}).json()
    assert len(preset["agent_definition_ids"]) == 2
    p2 = client.post("/api/projects", json={"name": "Two", "objective": "x"}).json()
    team = client.post(f"/api/projects/{p2['id']}/agents/apply-preset", json={"preset_id": preset["id"]}).json()
    assert {a["display_name"] for a in team} == {"Pat", "Devon"}


def test_recommendation_heuristic(client):
    p = client.post("/api/projects", json={"name": "C", "objective": "Research competitors and build a prototype app",
                                           "template_key": "custom"}).json()
    rec = client.get(f"/api/projects/{p['id']}/recommendation").json()
    keys = {r["role_key"] for r in rec["roles"]}
    assert {"project_manager", "research_analyst", "developer"} <= keys
    assert "heuristic" in rec["basis"]


def test_file_upload(client):
    p = client.post("/api/projects", json={"name": "F", "objective": "x"}).json()
    r = client.post(f"/api/projects/{p['id']}/files", files={"file": ("notes.md", io.BytesIO(b"# Notes\nhello"), "text/markdown")})
    assert r.status_code == 200 and r.json()["chars"] > 0
    r = client.post(f"/api/projects/{p['id']}/files", files={"file": ("evil.sh.exe", io.BytesIO(b"MZ"), "x")})
    assert r.status_code == 422
    assert len(client.get(f"/api/projects/{p['id']}/files").json()) == 1


def test_credentials_never_returned(client, monkeypatch):
    from app.providers import registry
    from tests.fakes import FakeProvider

    fp = FakeProvider(lambda c: "")
    monkeypatch.setattr(registry, "get_provider", lambda name: fp)
    r = client.put("/api/providers/anthropic/credential", json={"api_key": "sk-ant-api03-SECRETSECRET1234"})
    assert r.status_code == 200 and r.json()["ok"]
    assert "SECRETSECRET" not in r.text
    st = client.get("/api/providers").json()
    a = next(x for x in st if x["provider"] == "anthropic")
    assert a["configured"] and a["key_hint"] == "…1234" and a["status"] == "valid"
    boot = client.get("/api/bootstrap").text
    assert "SECRETSECRET" not in boot
    client.delete("/api/providers/anthropic/credential")
    assert not next(x for x in client.get("/api/providers").json() if x["provider"] == "anthropic")["configured"]


def test_security_middleware():
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        assert c.post("/api/projects", json={"name": "x", "objective": "y"}).status_code == 403  # no client header
        assert c.get("/api/health", headers={"host": "attacker.example"}).status_code == 403  # DNS rebinding
        assert c.get("/api/health").status_code == 200


def test_model_pricing_edit(client):
    ms = client.get("/api/models").json()
    gpt = next(m for m in ms if m["model_id"] == "gpt-5")
    assert gpt["input_price_per_mtok"] is None and gpt["cost_tier"] == "unpriced"
    r = client.patch(f"/api/models/{gpt['id']}", json={"input_price_per_mtok": 1.25, "output_price_per_mtok": 10})
    assert r.json()["pricing_source"] == "user-configured" and r.json()["cost_tier"] == "$$"
    assert client.patch(f"/api/models/{gpt['id']}", json={"input_price_per_mtok": -1}).status_code == 422


def test_migration_matches_models():
    """The migrated schema contains every table and column defined by the models."""
    from app.db import engine
    from app.models import Base

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    for t in Base.metadata.sorted_tables:
        assert t.name in tables
        cols = {c["name"] for c in insp.get_columns(t.name)}
        assert {c.name for c in t.columns} <= cols, t.name


def test_migration_roundtrip():
    from alembic import command
    from tests.conftest import _alembic_cfg

    command.downgrade(_alembic_cfg(), "base")
    command.upgrade(_alembic_cfg(), "head")
