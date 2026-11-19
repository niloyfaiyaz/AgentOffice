"""MOCKED-PROVIDER integration tests: the real orchestration engine, database, worker,
approvals, QA loop and exports, driven by the deterministic scripted provider (not an AI)."""
import io
import zipfile

from tests.helpers import drive, make_project, pending, run_status


async def test_complete_journey(client):
    p = make_project(client)
    pid = p["id"]
    run = client.post(f"/api/projects/{pid}/runs", json={}).json()
    assert run["status"] == "planning"

    await drive(run["id"])
    assert run_status(run["id"]) == "awaiting_approval"
    [sow] = pending(client, pid, "sow")
    assert sow["payload"]["plan"]["tasks"], "plan has tasks"
    r = client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve"})
    assert r.status_code == 200, r.text
    state = client.get(f"/api/projects/{pid}/state").json()
    assert state["current_run"]["status"] == "running"
    assert {t["status"] for t in state["tasks"]} == {"pending"}

    # Execution: the discovery task asks the client a clarification question.
    await drive(run["id"])
    assert run_status(run["id"]) == "blocked"
    [q] = pending(client, pid, "clarification")
    assert "segment" in q["title"]
    st = client.get(f"/api/projects/{pid}/state").json()
    waiting_agent = next(a for a in st["agents"] if a["id"] == q["agent_id"])
    assert waiting_agent["status"] == "waiting_for_client"
    client.post(f"/api/approvals/{q['id']}/decide", json={"decision": "answer", "answer": "SMB"})
    assert run_status(run["id"]) == "running"

    # The rest runs: dependent tasks, QA (requests rework), rework, re-review, consolidation.
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    st = client.get(f"/api/projects/{pid}/state").json()
    kinds = [t["kind"] for t in st["tasks"]]
    assert kinds.count("qa") == 2 and "rework" in kinds and "consolidation" in kinds
    assert all(t["status"] == "completed" for t in st["tasks"])
    findings = client.get(f"/api/projects/{pid}/findings").json()
    assert len(findings) == 1 and findings[0]["status"] == "resolved"

    # The clarification answer reached the agent's deliverable.
    arts = client.get(f"/api/projects/{pid}/artifacts").json()
    names = {a["name"] for a in arts}
    assert "Final Delivery Summary" in names
    discovery = next(a for a in arts if a["name"].startswith("requirements for"))
    v1 = client.get(f"/api/artifacts/{discovery['id']}", params={"version": 1}).json()
    assert "SMB" in v1["content"]
    assert [v["version"] for v in v1["versions"]] == [1, 2]  # QA-requested rework added v2
    # Rework created a new version of the QA-flagged artifact.
    assert any(a["current_version"] >= 2 for a in arts)

    # Handoffs and events recorded; usage recorded and flagged as test usage.
    events = client.get(f"/api/projects/{pid}/events").json()
    types = {e["type"] for e in events}
    assert {"task_started", "task_completed", "review_submitted", "rework_requested", "approval_requested"} <= types
    costs = client.get(f"/api/projects/{pid}/costs").json()
    assert costs["records"] and all(r["is_test_provider"] for r in costs["records"])
    assert costs["estimated_total_usd"] == 0

    # Acceptance + export.
    [acc] = pending(client, pid, "deliverable_acceptance")
    client.post(f"/api/approvals/{acc['id']}/decide", json={"decision": "approve"})
    res = client.get(f"/api/projects/{pid}/export")
    assert res.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(res.content))
    assert "manifest.json" in z.namelist() and "qa/findings.json" in z.namelist()
    docx = client.get(f"/api/artifacts/{discovery['id']}/export", params={"format": "docx"})
    assert docx.status_code == 200 and docx.content[:2] == b"PK"


async def test_plan_revision_and_rejection(client):
    p = make_project(client)
    run = client.post(f"/api/projects/{p['id']}/runs", json={}).json()
    await drive(run["id"])
    [sow] = pending(client, p["id"], "sow")
    r = client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "revise", "comment": "Add a risk register"})
    assert r.status_code == 200
    assert run_status(run["id"]) == "planning"
    await drive(run["id"])
    [sow2] = pending(client, p["id"], "sow")
    assert sow2["id"] != sow["id"]
    client.post(f"/api/approvals/{sow2['id']}/decide", json={"decision": "reject"})
    assert run_status(run["id"]) == "cancelled"
    assert client.get(f"/api/projects/{p['id']}").json()["status"] == "cancelled"


async def test_edited_plan_is_validated(client):
    p = make_project(client)
    run = client.post(f"/api/projects/{p['id']}/runs", json={}).json()
    await drive(run["id"])
    [sow] = pending(client, p["id"], "sow")
    plan = sow["payload"]["plan"]
    plan["tasks"][0]["assignee"] = "Nobody"
    r = client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve", "plan": plan})
    assert r.status_code == 400 and "not on the team" in r.text
    plan["tasks"][0]["assignee"] = "Pat"
    plan["tasks"] = plan["tasks"][:1]
    r = client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve", "plan": plan})
    assert r.status_code == 200
    st = client.get(f"/api/projects/{p['id']}/state").json()
    assert len(st["tasks"]) == 1 and st["tasks"][0]["assigned_agent_id"] == next(
        a["id"] for a in st["agents"] if a["display_name"] == "Pat")
