import asyncio
import uuid

from app import worker
from app.db import SessionLocal
from app.models import ProjectRun


async def drive(run_id, rounds: int = 20):
    """Let the worker drive a run until it rests (waiting for the client or finished)."""
    for _ in range(rounds):
        rid = worker.claim_one()
        if rid is None:
            return
        await worker.drive(rid, None)


def run_status(run_id) -> str:
    with SessionLocal() as db:
        return db.get(ProjectRun, uuid.UUID(str(run_id))).status


def make_project(client, name="Onboarding PRD", roles=("project_manager", "business_analyst", "software_architect", "qa_reviewer"),
                 provider="scripted-test", model="scripted-v1", **extra):
    p = client.post("/api/projects", json={"name": name, "objective": "Write a PRD for an AI onboarding assistant for SaaS.",
                                           "deliverables": ["PRD", "Backlog"], "template_key": "product_requirements", **extra}).json()
    defs = {d["role_key"]: d for d in client.get("/api/agent-definitions").json()}
    for r in roles:
        res = client.post(f"/api/projects/{p['id']}/agents",
                          json={"agent_definition_id": defs[r]["id"], "provider": provider, "model_id": model})
        assert res.status_code == 200, res.text
    return p


def pending(client, pid, kind=None):
    aps = client.get(f"/api/projects/{pid}/approvals", params={"status": "pending"}).json()
    return [a for a in aps if kind is None or a["kind"] == kind]
