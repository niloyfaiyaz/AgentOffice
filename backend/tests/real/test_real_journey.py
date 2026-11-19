"""REAL-PROVIDER end-to-end journey (spec §16 mandatory test).

Runs only when a real API key is available: from the OS keychain entry AgentOffice stores
(Settings -> Anthropic or OpenAI), or AGENTOFFICE_REAL_<PROVIDER>_KEY. Anthropic is preferred
when both exist; force one with AGENTOFFICE_REAL_PROVIDER, and a model with AGENTOFFICE_REAL_MODEL. Otherwise it is SKIPPED, and
never reported as passed. Makes real, billed API calls; spending is capped by the project
budget (AGENTOFFICE_REAL_BUDGET_USD, default $3). Results are written to
data/real-journey-result.json.

    cd backend && ../.venv/bin/python -m pytest tests/real -m real_provider -s
"""
import json
import os
import time
import uuid
from pathlib import Path

import pytest

from app.db import SessionLocal
from app.models import UsageRecord
from app.providers import registry
from app.security import credentials
from tests.helpers import drive, pending, run_status

DEFAULT_MODEL = {"anthropic": "claude-opus-5-5", "openai": "gpt-5.4"}
BUDGET = float(os.environ.get("AGENTOFFICE_REAL_BUDGET_USD", "3"))
RESULT = Path(__file__).resolve().parents[3] / "data" / "real-journey-result.json"


def _real_key(provider: str) -> str | None:
    env = os.environ.get(f"AGENTOFFICE_REAL_{provider.upper()}_KEY")
    if env:
        return env
    try:
        return credentials.KeyringStore().get(provider) if credentials.KeyringStore.available() else None
    except Exception:
        return None


def _pick_provider() -> tuple[str | None, str | None]:
    wanted = os.environ.get("AGENTOFFICE_REAL_PROVIDER")
    for p in ([wanted] if wanted else ["anthropic", "openai"]):
        key = _real_key(p)
        if key:
            return p, key
    return None, None


@pytest.mark.real_provider
async def test_real_saas_onboarding_journey(client):
    provider, key = _pick_provider()
    if not key:
        pytest.skip("No real provider API key configured - real-provider journey NOT executed")
    MODEL = os.environ.get("AGENTOFFICE_REAL_MODEL", DEFAULT_MODEL[provider])
    credentials.get_store().set(provider, key)
    registry.invalidate()
    steps: list[dict] = []

    def log(step, ok, detail=""):
        steps.append({"step": step, "ok": ok, "detail": detail, "t": time.time()})

    # 1. Create a SaaS onboarding improvement project
    p = client.post("/api/projects", json={
        "name": "SaaS onboarding improvement (real test)", "template_key": "product_requirements",
        "objective": "Improve self-serve onboarding for a B2B SaaS analytics product: produce a prioritized backlog "
                     "with acceptance criteria and the key technical considerations.",
        "deliverables": ["Prioritized backlog with acceptance criteria", "Technical considerations"],
        "constraints": "Keep each deliverable under 900 words.", "success_criteria": "Actionable by an engineering team.",
        "budget_usd": BUDGET}).json()
    pid = p["id"]
    log("create project", True, pid)
    # 2. Hire PM, BA, Technical Architect, QA Reviewer; 3. assign models
    defs = {d["role_key"]: d for d in client.get("/api/agent-definitions").json()}
    for r in ("project_manager", "business_analyst", "software_architect", "qa_reviewer"):
        res = client.post(f"/api/projects/{pid}/agents", json={"agent_definition_id": defs[r]["id"], "provider": provider,
                                                               "model_id": MODEL, "effort": "low", "max_output_tokens": 8000})
        assert res.status_code == 200, res.text
    log("hire team + assign models", True, MODEL)
    from app.models import ProviderCredentialReference
    from app.db import SessionLocal as _S
    with _S() as db:  # register the credential reference as the Settings page would
        db.add(ProviderCredentialReference(provider=provider, storage_backend="memory", key_hint=credentials.key_hint(key)))
        db.commit()
    test = client.post(f"/api/providers/{provider}/test")
    assert test.status_code == 200 and test.json()["ok"], test.text
    log("provider connection", True, f"{len(test.json()['models'])} models visible")

    # 4. Approve the statement of work
    run = client.post(f"/api/projects/{pid}/runs", json={}).json()
    await drive(run["id"])
    sows = pending(client, pid, "sow")
    assert sows, f"no SOW; run status {run_status(run['id'])}"
    plan = sows[0]["payload"]["plan"]
    log("statement of work proposed", True, f"{len(plan['tasks'])} tasks, qa_review={plan.get('qa_review')}")
    answers = {q: "Prioritize small and mid-sized teams; web app only." for q in plan.get("clarification_questions", [])}
    r = client.post(f"/api/approvals/{sows[0]['id']}/decide", json={"decision": "approve", "answers": answers, "qa_review": True})
    assert r.status_code == 200, r.text
    log("SOW approved", True)

    # 5-9. Execute; answer clarifications; QA review; consolidation
    clarifications = 0
    for _ in range(25):
        await drive(run["id"])
        st = run_status(run["id"])
        if st in ("completed", "failed", "cancelled"):
            break
        for ap in pending(client, pid):
            if ap["kind"] == "clarification":
                clarifications += 1
                client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "answer",
                            "answer": "Focus on small and mid-sized teams; assume a web app; keep it pragmatic."})
            elif ap["kind"] in ("tool_authorization", "budget"):
                client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "reject"})
            elif ap["kind"] == "task_failure":
                client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "approve", "option": "skip"})
    final = run_status(run["id"])
    state = client.get(f"/api/projects/{pid}/state").json()
    log("run finished", final == "completed", f"status={final}; clarifications answered={clarifications}")
    findings = client.get(f"/api/projects/{pid}/findings").json()
    log("QA review", any(t["kind"] == "qa" and t["status"] == "completed" for t in state["tasks"]), f"{len(findings)} findings")
    # 10. Export
    exp = client.get(f"/api/projects/{pid}/export")
    log("export", exp.status_code == 200 and exp.content[:2] == b"PK", f"{len(exp.content)} bytes")
    # 11. Usage records
    with SessionLocal() as db:
        recs = db.query(UsageRecord).filter(UsageRecord.project_id == uuid.UUID(pid)).all()
        real = [x for x in recs if not x.is_test_provider]
        total = sum(float(x.estimated_cost_usd or 0) for x in real)
    log("usage recorded", bool(real), f"{len(real)} real calls, est ${total:.4f}, "
                                      f"{sum(x.input_tokens for x in real)} in / {sum(x.output_tokens for x in real)} out tokens")
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps({"provider": provider, "model": MODEL, "project_id": pid, "steps": steps,
                                  "tasks": [{"title": t["title"], "kind": t["kind"], "status": t["status"]} for t in state["tasks"]]},
                                 indent=2))
    assert final == "completed", steps
    assert real and total > 0
