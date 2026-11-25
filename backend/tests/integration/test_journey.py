"""Project journey API (MOCKED-PROVIDER where a model is involved: the scripted test provider is
deterministic and not AI). Covers unique names, conversational discovery with provenance-preserving
brief merges, confirmation into versioned requirements, the recommended team, the inbox, chat intent
handling, and the synthetic-data cleanup classifier."""
import uuid

import pytest

from app.db import SessionLocal
from app.models import Message, Project, ProjectAgent, ProjectRequirement
from tests.helpers import drive, make_project, pending


# -- names ------------------------------------------------------------------------------------
def test_project_names_are_unique_after_normalization(client):
    assert client.post("/api/projects", json={"name": "TravelPoll", "objective": "Plan trips"}).status_code == 200
    for dup in ("travelpoll", "  TravelPoll  ", "Travel" "Poll", "ＴｒａｖｅｌＰｏｌｌ", "TRAVELPOLL"):
        r = client.post("/api/projects", json={"name": dup, "objective": "x"})
        assert r.status_code == 409, dup
        assert "already have a project" in r.json()["detail"]
    other = client.post("/api/projects", json={"name": "Budget app", "objective": "x"}).json()
    assert client.patch(f"/api/projects/{other['id']}", json={"name": " travelPOLL"}).status_code == 409
    # archived projects free their name; restoring into a conflict asks for a rename
    first = next(p for p in client.get("/api/projects").json() if p["name"] == "TravelPoll")
    assert client.post(f"/api/projects/{first['id']}/archive").status_code == 200
    again = client.post("/api/projects", json={"name": "travelpoll", "objective": "x"})
    assert again.status_code == 200 and again.json()["name"] == "travelpoll"
    r = client.post(f"/api/projects/{first['id']}/unarchive")
    assert r.status_code == 409 and "Rename" in r.json()["detail"]


def test_database_enforces_unique_names():
    from sqlalchemy.exc import IntegrityError

    with SessionLocal() as db:
        db.add(Project(name="Same Name"))
        db.commit()
        db.add(Project(name=" same   name "))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(Project(name="same name", origin="acceptance_test"))  # synthetic data is outside the user's namespace
        db.commit()


def test_synthetic_projects_are_hidden_from_the_normal_list(client):
    client.post("/api/projects", json={"name": "Real one", "objective": "x"})
    client.post("/api/projects", json={"name": "Real one", "objective": "x", "origin": "acceptance_test"})
    names = [p["name"] for p in client.get("/api/projects").json()]
    assert names == ["Real one"]
    assert len(client.get("/api/projects", params={"include_test": True}).json()) == 2
    assert all(p["origin"] == "user" for p in client.get("/api/dashboard").json()["projects"])


# -- discovery ---------------------------------------------------------------------------------
IDEA = "Build a simple travel planning web app where friends can suggest activities, vote, and generate a shared itinerary."


def test_discovery_conversation_brief_and_confirmation(client):
    """MOCKED-PROVIDER: the scripted provider plays the PM (labelled not AI in its messages)."""
    v = client.post("/api/discovery", json={"text": IDEA}).json()
    pid = v["project"]["id"]
    assert v["pm"]["role_key"] == "project_manager" and v["pm"]["provider"] == "scripted-test"
    assert v["brief"]["status"] == "discovering" and v["messages"][0]["sender"] == "user"

    v = client.post(f"/api/projects/{pid}/discovery/turn", json={}).json()
    b = v["brief"]
    assert len(b["questions"]) == 2 and b["status"] == "discovering"
    assert b["objective"]["basis"] == "client_stated" and b["audience"]["basis"] == "ai_proposed"
    assert all(i["basis"] == "ai_proposed" for i in b["assumptions"])
    assert "not AI" in v["messages"][-1]["content"]

    # The client edits one requirement and deletes an AI assumption.
    reqs = b["requirements"]
    edited = {"requirements": [{**reqs[0], "text": "Friends can suggest and vote on activities"}] + reqs[1:],
              "assumptions": []}
    b = client.put(f"/api/projects/{pid}/brief", json=edited).json()["brief"]
    assert b["requirements"][0]["basis"] == "client_edited"
    assert "Web first; mobile later" in b["removed"]

    # Answer the questions: the PM marks the brief ready but keeps the client's edit and the removal.
    b = client.post(f"/api/projects/{pid}/discovery/turn", json={"content": "Just my friends; a prototype"}).json()["brief"]
    assert b["status"] == "ready" and b["questions"] == []
    assert b["requirements"][0] == {**b["requirements"][0], "text": "Friends can suggest and vote on activities",
                                     "basis": "client_edited"}
    assert b["assumptions"] == []  # not resurrected
    assert any("Client answer" in i["text"] for i in b["requirements"])

    # Confirm: the brief becomes versioned requirement items with stable refs.
    v = client.post(f"/api/projects/{pid}/brief/confirm").json()
    assert v["brief"]["status"] == "confirmed" and v["project"]["name"] == b["name"]["text"]
    state = client.get(f"/api/projects/{pid}/state").json()
    kinds = {r["kind"] for r in state["requirements"]}
    assert {"objective", "requirement", "deliverable", "constraint", "success_criterion"} <= kinds
    assert all(r["ref"] and r["ref"].startswith("R-") for r in state["requirements"])
    # Editing a confirmed brief retires the old item (history kept) instead of deleting it.
    b = v["brief"]
    client.put(f"/api/projects/{pid}/brief", json={"requirements": [{"text": "Votes are anonymous"}] + b["requirements"][1:]})
    with SessionLocal() as db:
        old = db.query(ProjectRequirement).filter(ProjectRequirement.text == "Friends can suggest and vote on activities").one()
        assert old.status == "superseded"
    assert client.post(f"/api/projects/{pid}/discovery/turn", json={"content": "more"}).status_code == 409


def test_discovery_without_a_provider_is_labelled_not_ai(client, monkeypatch):
    from app import discovery

    monkeypatch.setattr(discovery, "usable_providers", lambda db: [])
    pid = client.post("/api/discovery", json={"text": "Research: the history of public libraries. It must cite sources."}).json()["project"]["id"]
    v = client.post(f"/api/projects/{pid}/discovery/turn", json={}).json()
    assert v["brief"]["status"] == "manual" and v["brief"]["method"] == "heuristic"
    assert v["provider_ready"] is False
    assert "No AI provider is connected" in v["messages"][-1]["content"] and v["messages"][-1]["sender"] == "system"
    assert any("must cite sources" in i["text"] for i in v["brief"]["requirements"])


def test_recommended_team_is_minimal_and_hireable(client):
    pid = client.post("/api/discovery", json={"text": IDEA}).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/discovery/turn", json={})
    rec = client.get(f"/api/projects/{pid}/team/recommended").json()
    keys = [r["role_key"] for r in rec["roles"]]
    assert keys == ["project_manager", "software_architect", "developer", "qa_reviewer"]
    assert "scripted" in rec["basis"]
    pm = rec["roles"][0]
    assert pm["hired"] and pm["model"]["model_id"] == "scripted-v1" and pm["tools"]
    assert all(r["reason"] and r["responsibility"] for r in rec["roles"])
    rec = client.post(f"/api/projects/{pid}/team/hire", json={"role_keys": keys}).json()
    assert all(r["hired"] for r in rec["roles"])
    client.post(f"/api/projects/{pid}/team/hire", json={"role_keys": keys})  # idempotent
    with SessionLocal() as db:
        assert db.query(ProjectAgent).filter(ProjectAgent.project_id == uuid.UUID(pid)).count() == 4
    assert client.post(f"/api/projects/{pid}/team/hire", json={"role_keys": ["wizard"]}).status_code == 422


# -- inbox and messages ------------------------------------------------------------------------
async def test_inbox_lists_actionable_items_once(client):
    pid = client.post("/api/discovery", json={"text": IDEA}).json()["project"]["id"]
    client.post(f"/api/projects/{pid}/discovery/turn", json={})
    proj = make_project(client, name="Planned project", roles=("project_manager", "business_analyst"))
    run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
    await drive(run["id"])
    hidden = client.post("/api/projects", json={"name": "Hidden", "objective": "x", "origin": "acceptance_test"}).json()
    box = client.get("/api/inbox").json()
    cats = {(a["project_name"], a["category"]) for a in box["actions"]}
    assert ("Planned project", "Plan approval") in cats
    assert any(a["category"] == "Answer questions" for a in box["actions"])
    assert all(a["project_id"] != hidden["id"] for a in box["actions"])
    sow = pending(client, proj["id"], "sow")[0]
    assert sum(1 for a in box["actions"] if a["id"] == sow["id"]) == 1


async def test_chat_answers_open_question_and_never_applies_changes(client):
    """MOCKED-PROVIDER. A typed reply in the agent's thread answers its open question; a message that
    reads like a requirement change only produces a suggestion for the structured flow."""
    from tests.integration.test_orchestration import start_and_approve

    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    [q] = pending(client, proj["id"], "clarification")
    bea = next(a for a in client.get(f"/api/projects/{proj['id']}/agents").json() if a["display_name"] == "Bea")
    threads = {t["id"]: t for t in client.get(f"/api/projects/{proj['id']}/threads").json()}
    assert threads[f"agent:{bea['id']}"]["pending"] == 1

    r = client.post(f"/api/projects/{proj['id']}/messages", json={"content": "SMB first", "agent_id": bea["id"]}).json()
    assert r["intent"] == "answer" and r["data"]["answered_approval_id"] == q["id"]
    assert pending(client, proj["id"], "clarification") == []
    msgs = client.get(f"/api/projects/{proj['id']}/messages", params={"channel": "direct", "agent_id": bea["id"]}).json()
    assert [m["sender"] for m in msgs] == ["user", "system"]  # the acknowledgement is AgentOffice's, not the agent's

    with SessionLocal() as db:
        before = db.query(ProjectRequirement).filter(ProjectRequirement.project_id == uuid.UUID(proj["id"])).count()
    r = client.post(f"/api/projects/{proj['id']}/messages",
                    json={"content": "Actually, it should target enterprise customers instead"}).json()
    assert r["intent"] == "requirement_change" and r["data"]["suggestion"]["intent"] == "requirement_change"
    with SessionLocal() as db:
        after = db.query(ProjectRequirement).filter(ProjectRequirement.project_id == uuid.UUID(proj["id"])).count()
        assert after == before  # nothing changed until the client confirms through the change flow
        assert db.query(Message).filter(Message.channel == "client").count() == 2
    r = client.post(f"/api/projects/{proj['id']}/messages", json={"content": "approve"}).json()
    assert r["data"]["suggestion"]["intent"] == "approval"


def test_plan_estimate_is_unavailable_without_history(client):
    proj = make_project(client)
    assert client.get(f"/api/projects/{proj['id']}/estimate").json()["available"] is False


# -- synthetic data cleanup ------------------------------------------------------------------------
def test_cleanup_classifies_on_evidence_and_deletes_only_flagged(client, capsys):
    from app import cleanup

    scripted = make_project(client, name="Scripted thing")
    evidence = client.post("/api/projects", json={"name": "CSV Import Assistant", "objective": "x"}).json()
    mine = client.post("/api/projects", json={"name": "CSV Import Assistant copy", "objective": "x"}).json()
    with SessionLocal() as db:
        rows = {r["id"]: r for r in cleanup.classify(db, {evidence["id"]: "docs/acceptance/evidence.json"})}
    assert rows[scripted["id"]]["classified"] == "scripted_test"
    assert rows[evidence["id"]]["classified"] == "acceptance_test"
    assert rows[mine["id"]]["classified"] == "user"  # a similar name is not evidence

    real_evidence = cleanup.evidence_ids
    cleanup.evidence_ids = lambda: {evidence["id"]: "docs/acceptance/evidence.json"}
    try:
        assert cleanup.main([]) == 0  # dry run changes nothing
        assert len(client.get("/api/projects").json()) == 3
        assert cleanup.main(["--delete"]) == 2  # refuses without --yes
        cleanup.main(["--mark"])
        assert [p["id"] for p in client.get("/api/projects").json()] == [mine["id"]]
        cleanup.main(["--delete", "--yes"])
    finally:
        cleanup.evidence_ids = real_evidence
    with SessionLocal() as db:
        assert {str(p.id) for p in db.query(Project)} == {mine["id"]}


def test_migration_renames_existing_duplicates():
    """0004 makes existing duplicate active names unique by suffixing later ones; nothing is deleted."""
    from alembic import command
    from sqlalchemy import text

    from app.db import engine
    from tests.conftest import _alembic_cfg

    command.downgrade(_alembic_cfg(), "0003")
    with engine.begin() as c:
        for i, n in enumerate(["Dup", "dup ", "DUP", "Solo"]):
            c.execute(text("INSERT INTO projects (id, name, objective, description, deliverables, constraints, "
                           "success_criteria, status, archived, created_at, updated_at) VALUES (:id, :n, '', '', '[]', '', '', "
                           "'draft', false, now() + make_interval(secs => :i), now())"), {"id": str(uuid.uuid4()), "n": n, "i": i})
    command.upgrade(_alembic_cfg(), "head")
    with engine.begin() as c:
        names = [r[0] for r in c.execute(text("SELECT name FROM projects ORDER BY created_at"))]
        renamed = c.execute(text("SELECT count(*) FROM agent_events WHERE type = 'project_renamed'")).scalar()
    assert names == ["Dup", "dup (2)", "DUP (3)", "Solo"] and renamed == 2
