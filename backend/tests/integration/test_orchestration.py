"""MOCKED-PROVIDER tests for orchestration controls: delegation, dependencies, parallelism,
pause/resume, cancellation, budgets, tool security, provider errors and restart recovery."""
import uuid
from decimal import Decimal

import pytest

from app import worker
from app.db import SessionLocal
from app.models import ProjectRun, Task, TaskExecution, UsageRecord
from app.providers import registry
from app.providers.base import ProviderError
from tests.fakes import FakeProvider, call, plan_call, simple_worker
from tests.helpers import drive, make_project, pending, run_status

T = lambda key, assignee, deps=(), title=None: {  # noqa: E731
    "key": key, "title": title or f"Task {key}", "objective": f"Do the work for {key} properly.", "assignee": assignee,
    "depends_on": list(deps), "acceptance_criteria": ["done"]}


@pytest.fixture
def fake():
    holder = {}

    def install(policy, **kw):
        p = FakeProvider(policy, **kw)
        registry.set_override("scripted-test", p)
        holder["p"] = p
        return p

    yield install
    registry.set_override("scripted-test", None)


def planner_then(tasks, worker_policy=simple_worker, tools=()):
    def policy(ctx):
        if "submit_work_plan" in ctx["tools"]:
            return [plan_call(tasks, tools)]
        return worker_policy(ctx)
    return policy


async def start_and_approve(client, pid, body=None):
    run = client.post(f"/api/projects/{pid}/runs", json={}).json()
    await drive(run["id"])
    [sow] = pending(client, pid, "sow")
    r = client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve", **(body or {})})
    assert r.status_code == 200, r.text
    return run


def tasks_of(client, pid):
    return client.get(f"/api/projects/{pid}/state").json()["tasks"]


async def test_dependencies_and_parallelism(client, fake):
    p = fake(planner_then([T("A", "Bea"), T("B", "Archie"), T("C", "Bea", ["A", "B"])]), delay=0.2)
    proj = make_project(client, roles=("project_manager", "business_analyst", "software_architect"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    with SessionLocal() as db:
        ts = {t.plan_key: t for t in db.query(Task).filter(Task.run_id == uuid.UUID(run["id"]))}
        assert ts["C"].started_at >= max(ts["A"].completed_at, ts["B"].completed_at)  # dependency enforced
    assert p.max_active >= 2  # A and B ran concurrently


async def test_concurrency_limit_respected(client, fake):
    p = fake(planner_then([T(k, "Bea") for k in "ABCD"]), delay=0.15)
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    client.put(f"/api/projects/{proj['id']}/budget", json={"max_concurrency": 1})
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    assert p.max_active == 1


async def test_delegation_handoff_and_depth(client, fake):
    def w(ctx):
        if ctx["title"] == "Task A" and "delegate_subtask" not in ctx["done"]:
            return [call("delegate_subtask", to_agent="Archie", title="Architecture input",
                         objective="Describe the system components.")]
        if ctx["title"] == "Task A" and "write_artifact" not in ctx["done"]:
            got = [r["content"] for r in ctx["results"] if "completed the subtask" in r["content"]]
            assert got, "delegated result must be returned as the tool result"
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst", "software_architect"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    hos = client.get(f"/api/projects/{proj['id']}/handoffs").json()
    deleg = [h for h in hos if h["kind"] == "delegation"]
    assert len(deleg) == 1 and deleg[0]["status"] == "returned"
    sub = next(t for t in tasks_of(client, proj["id"]) if t["kind"] == "subtask")
    assert sub["depth"] == 1 and sub["status"] == "completed"
    types = [e["type"] for e in client.get(f"/api/projects/{proj['id']}/events").json()]
    assert "handoff" in types and "handoff_returned" in types


async def test_delegation_depth_limit(client, fake):
    seen = []

    def w(ctx):
        if "delegate_subtask" in ctx["tools"] and "delegate_subtask" not in ctx["done"] and ctx["title"] == "Task A":
            return [call("delegate_subtask", to_agent="Archie", title="x", objective="Some delegated work here.")]
        if ctx["results"]:
            seen.extend(r["content"] for r in ctx["results"])
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst", "software_architect"))
    client.put(f"/api/projects/{proj['id']}/budget", json={"max_delegation_depth": 0})
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert any("Delegation depth limit" in s for s in seen)
    assert not [t for t in tasks_of(client, proj["id"]) if t["kind"] == "subtask"]


async def test_unauthorized_tool_fails_safely(client, fake):
    seen = []

    def w(ctx):
        if ctx["title"] == "Task A" and not ctx["done"]:
            return [call("run_code", entrypoint="main.py")]  # Bea has no code_execution permission
        seen.extend(r["content"] for r in ctx["results"])
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert any("not authorized" in s for s in seen)
    assert "tool_denied" in [e["type"] for e in client.get(f"/api/projects/{proj['id']}/events").json()]


async def test_consequential_tool_requires_approval(client, fake):
    outputs = []

    def w(ctx):
        if ctx["title"] == "Task A":
            if "write_artifact" not in ctx["done"]:
                return [call("write_artifact", name="main.py", artifact_type="code", content="print('hi')", summary="s")]
            if "run_code" not in ctx["done"]:
                return [call("run_code", entrypoint="main.py")]
            outputs.extend(r["content"] for r in ctx["results"])
        return simple_worker(ctx)

    fake(planner_then([T("A", "Dev")], w))
    proj = make_project(client, roles=("project_manager", "developer"))
    run = await start_and_approve(client, proj["id"], {"approved_tools": []})  # client did not pre-authorize
    await drive(run["id"])
    assert run_status(run["id"]) == "blocked"
    [auth] = pending(client, proj["id"], "tool_authorization")
    client.post(f"/api/approvals/{auth['id']}/decide", json={"decision": "reject", "comment": "not now"})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    assert any("did not authorize" in o for o in outputs)


@pytest.mark.sandbox
async def test_sandboxed_execution_is_isolated(client, fake):
    """Runs real code in the Docker sandbox: no network, read-only root, workspace only."""
    from app.tools import sandbox

    if not (await sandbox.status(refresh=True))["available"]:
        pytest.skip("Docker sandbox unavailable")
    code = (
        "import socket, os\n"
        "try:\n    socket.create_connection(('1.1.1.1', 53), timeout=2); print('NET:open')\n"
        "except OSError: print('NET:blocked')\n"
        "try:\n    open('/etc/x','w'); print('ROOT:writable')\n"
        "except OSError: print('ROOT:readonly')\n"
        "print('UID:', os.getuid()); print('HOST_SECRETS:', [k for k in os.environ if k.startswith(('ANTHROPIC', 'OPENAI', 'AGENTOFFICE', 'AWS'))])\n"
    )
    test = "from main import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    outputs = []

    def w(ctx):
        if ctx["title"] == "Task A":
            d = ctx["done"]
            if d.count("write_artifact") == 0:
                return [call("write_artifact", name="probe.py", artifact_type="code", content=code, summary="probe")]
            if d.count("write_artifact") == 1:
                return [call("write_artifact", name="main.py", artifact_type="code", content="def add(a, b):\n    return a + b\n", summary="s")]
            if d.count("write_artifact") == 2:
                return [call("write_artifact", name="tests/test_main.py", artifact_type="code", content=test, summary="t")]
            if "run_code" not in d:
                return [call("run_code", entrypoint="probe.py")]
            if "run_tests" not in d:
                return [call("run_tests")]
            outputs.extend(r["content"] for r in ctx["results"])
        return simple_worker(ctx)

    fake(planner_then([T("A", "Dev")], w, tools=["code_execution", "test_execution"]))
    proj = make_project(client, roles=("project_manager", "developer"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed", tasks_of(client, proj["id"])
    probe = next(o for o in outputs if "NET:" in o)
    assert "NET:blocked" in probe and "ROOT:readonly" in probe and "UID: 10001" in probe and "HOST_SECRETS: []" in probe
    assert any("1 passed" in o for o in outputs)


async def test_pause_and_resume(client, fake):
    state = {"paused": False}

    def w(ctx):
        if ctx["title"] == "Task A" and not state["paused"]:
            with SessionLocal() as db:  # client presses pause while the agent is working
                from app.orchestration import decisions
                run = db.query(ProjectRun).one()
                decisions.request_control(db, run, "pause")
                db.commit()
            state["paused"] = True
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea"), T("B", "Bea", ["A"])], w))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "paused"
    ts = {t["title"]: t["status"] for t in tasks_of(client, proj["id"])}
    assert ts["Task A"] == "paused" and ts["Task B"] == "pending"
    with SessionLocal() as db:  # conversation persisted for resume
        ex = db.query(TaskExecution).one()
        assert ex.status == "suspended" and len(ex.conversation) >= 2
    r = client.post(f"/api/runs/{run['id']}/resume")
    assert r.status_code == 200 and r.json()["status"] == "running"
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    with SessionLocal() as db:
        a = db.query(Task).filter(Task.title == "Task A").one()
        assert db.query(TaskExecution).filter(TaskExecution.task_id == a.id).count() == 1  # resumed, not restarted


async def test_cancel(client, fake):
    fake(planner_then([T("A", "Bea"), T("B", "Bea", ["A"])]))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    r = client.post(f"/api/runs/{run['id']}/cancel")
    assert r.status_code == 200
    await drive(run["id"])
    assert run_status(run["id"]) == "cancelled"
    assert {t["status"] for t in tasks_of(client, proj["id"])} == {"cancelled"}
    assert client.post(f"/api/runs/{run['id']}/resume").status_code == 400


async def test_budget_blocks_then_resumes(client, fake):
    fake(planner_then([T("A", "Bea")]), test_provider=False)  # behaves as a priced provider
    proj = make_project(client, roles=("project_manager", "business_analyst"), provider="anthropic",
                        model="claude-haiku-5-5")
    with SessionLocal() as db:  # route the anthropic agents to the fake provider
        pass
    registry.set_override("anthropic", registry._overrides["scripted-test"])
    client.put(f"/api/projects/{proj['id']}/budget", json={"budget_usd": 0.0001})
    from app.security import credentials
    credentials.save_secret("anthropic", "sk-ant-test-0000000000")
    try:
        run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
        await drive(run["id"])
        assert run_status(run["id"]) == "blocked"
        [b] = pending(client, proj["id"], "budget")
        assert b["payload"]["reason"] == "project_budget"
        assert b["agent_id"] is not None
        with SessionLocal() as db:
            assert db.query(UsageRecord).count() == 0  # no call was made over budget
        client.post(f"/api/approvals/{b['id']}/decide", json={"decision": "approve", "budget_usd": 5})
        await drive(run["id"])
        assert run_status(run["id"]) == "awaiting_approval"
        with SessionLocal() as db:
            rec = db.query(UsageRecord).one()
            assert rec.estimated_cost_usd == Decimal("0.000200")  # 1000 in * $0.10/M + 200 out * $0.50/M
    finally:
        registry.set_override("anthropic", None)


async def test_max_model_calls(client, fake):
    fake(planner_then([T("A", "Bea"), T("B", "Bea")]))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    client.put(f"/api/projects/{proj['id']}/budget", json={"max_model_calls_per_run": 2})
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    [b] = pending(client, proj["id"], "budget")
    assert b["payload"]["reason"] == "max_calls"
    client.post(f"/api/approvals/{b['id']}/decide", json={"decision": "approve", "max_model_calls_per_run": 100})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"


async def test_provider_error_targeted_retry_then_failure_decision(client, fake):
    attempts = {"n": 0}

    def w(ctx):
        if ctx["title"] == "Task B":
            attempts["n"] += 1
            return ProviderError("auth", "invalid x-api-key")  # non-retryable
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea"), T("B", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "blocked"
    ts = {t["title"]: t for t in tasks_of(client, proj["id"])}
    assert ts["Task A"]["status"] == "completed"  # failure did not restart or cancel other work
    assert ts["Task B"]["status"] == "failed" and "rejected the API key" in ts["Task B"]["error"]
    assert attempts["n"] == 1  # auth errors are not retried blindly
    [f] = pending(client, proj["id"], "task_failure")
    client.post(f"/api/approvals/{f['id']}/decide", json={"decision": "approve", "option": "skip"})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"


async def test_transient_errors_are_retried(client, fake, monkeypatch):
    import app.orchestration.llm as llm

    async def nosleep(_):
        return None

    monkeypatch.setattr(llm.asyncio, "sleep", nosleep)
    n = {"c": 0}

    def w(ctx):
        n["c"] += 1
        if n["c"] <= 2:
            return ProviderError("overloaded", "busy", retryable=True)
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    evs = [e for e in client.get(f"/api/projects/{proj['id']}/events").json() if e["type"] == "provider_error"]
    assert len(evs) == 2


async def test_restart_recovery(client, fake):
    """Simulate a crashed worker: a task left 'running' with an expired lease is resumed
    from its persisted conversation by the next worker."""
    fake(planner_then([T("A", "Bea")]))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    from datetime import timedelta
    from app.models import utcnow
    from app.state_machine import transition_task
    with SessionLocal() as db:
        t = db.query(Task).one()
        transition_task(t, "ready")
        transition_task(t, "running")
        db.add(TaskExecution(task_id=t.id, agent_id=t.assigned_agent_id, provider="scripted-test", model_id="scripted-v1",
                             status="running", conversation=[{"role": "user", "content": [{"type": "text", "text": "# Your task: Task A\n"}]}]))
        r = db.get(ProjectRun, uuid.UUID(run["id"]))
        r.lease_owner = "dead-worker"
        r.lease_expires_at = utcnow() - timedelta(seconds=5)
        db.commit()
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    with SessionLocal() as db:
        a = db.query(Task).filter(Task.title == "Task A").one()
        exs = db.query(TaskExecution).filter(TaskExecution.task_id == a.id).all()
        assert len(exs) == 1 and exs[0].status == "succeeded"  # same execution resumed, not restarted
    assert "run_recovered" in [e["type"] for e in client.get(f"/api/projects/{proj['id']}/events").json()]


async def test_requirement_change_and_feedback(client, fake):
    fake(planner_then([T("A", "Bea"), T("B", "Bea", ["A"])]))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    # run task A only
    with SessionLocal() as db:
        b = db.query(Task).filter(Task.title == "Task B").one()
        b_id = b.id
    await drive(run["id"])
    st = client.get(f"/api/projects/{proj['id']}/state").json()
    assert st["current_run"]["status"] == "completed"
    # feedback after completion -> recorded, suggests revision
    a = next(t for t in st["tasks"] if t["title"] == "Task A")
    r = client.post(f"/api/projects/{proj['id']}/messages", json={"content": "Make it shorter", "intent": "task_feedback",
                                                                 "task_id": a["id"]}).json()
    assert "revision" in r["reply"]
    # deliverable revision starts a new run
    [acc] = pending(client, proj["id"], "deliverable_acceptance")
    r = client.post(f"/api/approvals/{acc['id']}/decide", json={"decision": "revise", "comment": "Shorter please"})
    assert r.status_code == 200
    runs = client.get(f"/api/projects/{proj['id']}/state").json()["runs"]
    assert runs[0]["run_number"] == 2 and runs[0]["kind"] == "revision"


async def test_requirement_change_during_run_targets_completed_tasks(client, fake):
    gate = {"stop": True}

    def w(ctx):
        if ctx["title"] == "Task B" and gate["stop"]:
            return [call("ask_client", question="Proceed with B?")]
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea"), T("B", "Bea", ["A"])], w))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "blocked"
    r = client.post(f"/api/projects/{proj['id']}/messages",
                    json={"content": "Target enterprise customers instead", "intent": "requirement_change"}).json()
    assert "rework" in r["reply"]
    [chg] = pending(client, proj["id"], "requirement_change")
    a_id = next(t["id"] for t in chg["payload"]["tasks"] if t["title"] == "Task A")
    client.post(f"/api/approvals/{chg['id']}/decide", json={"decision": "approve", "task_ids": [a_id]})
    gate["stop"] = False
    [q] = pending(client, proj["id"], "clarification")
    client.post(f"/api/approvals/{q['id']}/decide", json={"decision": "answer", "answer": "yes"})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    rework = [t for t in tasks_of(client, proj["id"]) if t["kind"] == "rework"]
    assert len(rework) == 1 and rework[0]["title"] == "Rework: Task A" and rework[0]["status"] == "completed"
    reqs = client.get(f"/api/projects/{proj['id']}/state").json()["requirements"]
    assert any(r["kind"] == "change" for r in reqs)


async def test_qa_review_cycles_are_bounded(client, fake):
    def w(ctx):
        if "submit_review" in ctx["tools"] and "submit_review" not in ctx["done"]:
            return [call("submit_review", verdict="revise", summary="never happy", findings=[
                {"severity": "major", "artifact": "Task A", "requirement": "ok", "evidence": "x", "recommendation": "y"}])]
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst", "qa_reviewer"))
    client.put(f"/api/projects/{proj['id']}/budget", json={"max_review_iterations": 1})
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    ts = tasks_of(client, proj["id"])
    assert [t["kind"] for t in ts].count("qa") == 2 and [t["kind"] for t in ts].count("rework") == 1
    fs = client.get(f"/api/projects/{proj['id']}/findings").json()
    assert any(f["status"] == "unresolved" for f in fs)
    [acc] = pending(client, proj["id"], "deliverable_acceptance")
    assert acc["payload"]["unresolved_findings"]


async def test_run_requires_credentials_for_real_providers(client):
    proj = make_project(client, roles=("project_manager",), provider="anthropic", model="claude-opus-5-5")
    r = client.post(f"/api/projects/{proj['id']}/runs", json={})
    assert r.status_code == 400 and "no API key" in r.text


async def test_worker_main_loop_runs_to_rest(client, fake):
    fake(planner_then([T("A", "Bea")]))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
    await worker.main(stop_after_idle=1.5)
    assert run_status(run["id"]) == "awaiting_approval"


async def test_single_agent_without_qa_skips_extra_agents(client, fake):
    """Selective orchestration: a one-task plan with qa_review=false uses one agent and no
    consolidation model call, even though a QA Reviewer is on the team."""
    def policy(ctx):
        if "submit_work_plan" in ctx["tools"]:
            c = plan_call([T("A", "Pat")])
            c.input["qa_review"] = False
            return [c]
        return simple_worker(ctx)

    p = fake(policy)
    proj = make_project(client, roles=("project_manager", "business_analyst", "qa_reviewer"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    ts = tasks_of(client, proj["id"])
    assert [t["kind"] for t in ts] == ["work"]
    assert len(p.calls) == 3  # plan + write + complete; no QA, no consolidation call
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    summary = client.get(f"/api/artifacts/{arts['Final Delivery Summary (run 1)']['id']}").json()
    assert "No independent QA review" in summary["content"]
    [acc] = pending(client, proj["id"], "deliverable_acceptance")
    assert acc["payload"]["qa_performed"] is False


async def test_client_can_turn_qa_on_at_approval(client, fake):
    def policy(ctx):
        if "submit_work_plan" in ctx["tools"]:
            c = plan_call([T("A", "Bea")])
            c.input["qa_review"] = False
            return [c]
        return simple_worker(ctx)

    fake(policy)
    proj = make_project(client, roles=("project_manager", "business_analyst", "qa_reviewer"))
    run = await start_and_approve(client, proj["id"], {"qa_review": True})
    await drive(run["id"])
    assert "qa" in [t["kind"] for t in tasks_of(client, proj["id"])]


async def test_artifact_ownership_guard_and_agent_memory(client, fake):
    seen = []

    def w(ctx):
        if ctx["title"] == "Task B" and "write_artifact" not in ctx["done"]:
            seen.append(ctx["brief"])
            return [call("write_artifact", name="Task A", artifact_type="markdown", content="hijack", summary="x")]
        if ctx["title"] == "Task B":
            seen.extend(r["content"] for r in ctx["results"])
            if not any(d == "write_artifact" for d in ctx["done"][1:]):
                return [call("write_artifact", name="Task B", artifact_type="markdown", content="mine", summary="y")]
        if ctx["title"] == "Task C" and not ctx["done"]:
            seen.append(ctx["brief"])
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea"), T("B", "Archie", ["A"]), T("C", "Bea", ["B"])], w))
    proj = make_project(client, roles=("project_manager", "business_analyst", "software_architect"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    assert any("belongs to Bea" in s for s in seen)
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    assert arts["Task A"]["current_version"] == 1
    brief_b = next(s for s in seen if "# Your task: Task B" in s)
    assert "Teammates' tasks" in brief_b and "Bea: Task A" in brief_b
    brief_c = next(s for s in seen if "# Your task: Task C" in s)
    assert "Your earlier work on this project" in brief_c and "finished Task A" in brief_c


async def test_model_change_applies_at_safe_checkpoint(client, fake):
    """Changing an agent's model mid-task takes effect when the suspended task resumes,
    continuing the same persisted conversation (no orphaned tool calls)."""
    state = {"paused": False}

    def w(ctx):
        if ctx["title"] == "Task A" and not state["paused"]:
            with SessionLocal() as db:
                from app.orchestration import decisions
                decisions.request_control(db, db.query(ProjectRun).one(), "pause")
                db.commit()
            state["paused"] = True
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "paused"
    bea = next(a for a in client.get(f"/api/projects/{proj['id']}/agents").json() if a["display_name"] == "Bea")
    client.patch(f"/api/projects/{proj['id']}/agents/{bea['id']}", json={"model_id": "scripted-v2"})
    client.post(f"/api/runs/{run['id']}/resume")
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    with SessionLocal() as db:
        a = db.query(Task).filter(Task.title == "Task A").one()
        [ex] = db.query(TaskExecution).filter(TaskExecution.task_id == a.id).all()
        assert ex.model_id == "scripted-v2" and ex.status == "succeeded"
        calls = [b for m in ex.conversation if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_call"]
        results = {b["tool_call_id"] for m in ex.conversation if m["role"] == "user" for b in m["content"] if b["type"] == "tool_result"}
        assert all(c["id"] in results for c in calls)  # every tool call paired with a result
    types = [e["type"] for e in client.get(f"/api/projects/{proj['id']}/events").json()]
    assert "model_changed" in types and "model_switched" in types


# --- Regression tests from the 2026-11-20 acceptance run (docs/AGENTOFFICE_E2E_ACCEPTANCE_REPORT.md) ---

async def test_D1_qa_report_is_written_by_the_qa_review_not_other_roles(client, fake):
    """D1: the BA wrote 'qa-review-report.md' before QA ran. Non-QA roles may no longer write QA
    reports or the final consolidated deliverable; the QA review produces a traceable report."""
    seen = []

    def w(ctx):
        if ctx["title"] == "Task A" and "write_artifact" not in ctx["done"]:
            return [call("write_artifact", name="csv_qa-review-report.md", artifact_type="markdown", content="fake QA", summary="x"),
                    call("write_artifact", name="final-consolidated-deliverable.md", artifact_type="markdown", content="x", summary="x")]
        if ctx["title"] == "Task A" and ctx["done"].count("write_artifact") == 2:
            seen.extend(r["content"] for r in ctx["results"])
            return [call("write_artifact", name="Task A", artifact_type="markdown", content="# PRD", summary="own work")]
        if "submit_review" in ctx["tools"] and "submit_review" not in ctx["done"]:
            return [call("submit_review", verdict="pass", summary="Looks complete.", findings=[
                {"severity": "minor", "artifact": "Task A", "requirement": "R1", "evidence": "typo", "recommendation": "fix"}])]
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst", "qa_reviewer"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    assert any("QA reports are produced by the QA Reviewer" in s for s in seen)
    assert any("final consolidated deliverable is produced by the Project Manager" in s for s in seen)
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    assert "csv_qa-review-report.md" not in arts and "final-consolidated-deliverable.md" not in arts
    rep = arts["QA Review Report (run 1)"]
    quinn = next(a for a in client.get(f"/api/projects/{proj['id']}/agents").json() if a["display_name"] == "Quinn")
    assert rep["owner_agent_id"] == quinn["id"]
    body = client.get(f"/api/artifacts/{rep['id']}").json()["content"]
    assert "F-001" in body and "Verdict: **pass**" in body and "minor" in body


async def test_D2_no_delegating_work_a_teammate_has_planned_after_you(client, fake):
    """D2: the BA delegated the technical assessment that the Technical Reviewer already had planned."""
    seen = []

    def w(ctx):
        if ctx["title"] == "Task A" and "delegate_subtask" not in ctx["done"]:
            return [call("delegate_subtask", to_agent="Archie", title="Tech assessment", objective="Assess feasibility of the import.")]
        if ctx["title"] == "Task A":
            seen.extend(r["content"] for r in ctx["results"])
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea"), T("B", "Archie", ["A"])], w))
    proj = make_project(client, roles=("project_manager", "business_analyst", "software_architect"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    assert any("already has the planned task" in s for s in seen)
    assert not [t for t in tasks_of(client, proj["id"]) if t["kind"] == "subtask"]


async def test_D3_requirement_change_covers_in_flight_tasks(client, fake):
    """D3: a task already running when the change arrived was not offered for rework, so it could
    deliver output based on the old requirement. In-flight tasks are now listed; their rework
    runs after they finish and sees the change."""
    gate = {"hold": True}
    briefs = []

    def w(ctx):
        if ctx["title"] == "Task A" and gate["hold"] and "ask_client" not in ctx["done"]:
            return [call("ask_client", question="Which columns are required?")]
        if ctx["title"].startswith("Rework: Task A") and not ctx["done"]:
            briefs.append(ctx["brief"])
        return simple_worker(ctx)

    fake(planner_then([T("A", "Bea")], w))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])  # Task A is now in flight (waiting for the client)
    r = client.post(f"/api/projects/{proj['id']}/messages",
                    json={"content": "Email OR phone is enough; reject only if both are missing.", "intent": "requirement_change"}).json()
    assert "in-progress" in r["reply"]
    [chg] = pending(client, proj["id"], "requirement_change")
    entry = next(t for t in chg["payload"]["tasks"] if t["title"] == "Task A")
    assert entry["status"] == "waiting_approval"
    client.post(f"/api/approvals/{chg['id']}/decide", json={"decision": "approve", "task_ids": [entry["id"]]})
    rework = next(t for t in tasks_of(client, proj["id"]) if t["kind"] == "rework")
    assert rework["status"] == "pending" and entry["id"] in rework["depends_on"]  # waits for the in-flight task
    gate["hold"] = False
    [q] = pending(client, proj["id"], "clarification")
    client.post(f"/api/approvals/{q['id']}/decide", json={"decision": "answer", "answer": "name and email"})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    with SessionLocal() as db:
        a = db.query(Task).filter(Task.title == "Task A").one()
        rw = db.query(Task).filter(Task.kind == "rework").one()
        assert rw.started_at >= a.completed_at  # rework ran after the in-flight task finished
    assert briefs and "Email OR phone is enough" in briefs[0]


async def test_D5_requirement_change_after_completion_marks_deliverables_stale(client, fake):
    """D5: after a run finished, a change only said 'upcoming work will follow it'."""
    fake(planner_then([T("A", "Bea")]))
    proj = make_project(client, roles=("project_manager", "business_analyst"))
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    r = client.post(f"/api/projects/{proj['id']}/messages", json={"content": "Phone is enough.", "intent": "requirement_change"}).json()
    assert "marked stale" in r["reply"] and "revision" in r["reply"]
    arts = [a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json() if a["category"] != "plan"]
    assert arts and all(a["stale"] for a in arts)
