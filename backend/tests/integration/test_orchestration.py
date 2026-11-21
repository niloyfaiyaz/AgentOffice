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
    "depends_on": list(deps), "acceptance_criteria": ["done"], "requirement_refs": ["AUTO"]}


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


# --- D4: versioned requirement items with explicit supersession ---------------------------------
CSV_OBJECTIVE = ("Administrators upload CSV contact files.\n\n1. Allow administrators to upload a CSV file.\n"
                 "2. Identify duplicate contacts within the uploaded file.\n\n"
                 "Every contact must have a valid email address. Rows with missing or invalid email addresses must be rejected.")
CR = ("A customer contact may now be imported without an email address if a valid phone number is provided. "
      "Reject a row only if both contact methods are absent or invalid.")


def _reqs(client, pid):
    return {r["text"]: r for r in client.get(f"/api/projects/{pid}/state").json()["requirements"]}


def _csv_project(client):
    p = make_project(client, roles=("project_manager", "business_analyst"))
    client.patch(f"/api/projects/{p['id']}", json={"objective": CSV_OBJECTIVE})
    return p


async def test_D4_change_supersedes_specific_items_and_agents_stop_seeing_them(client, fake):
    briefs = []

    def policy(ctx):
        if "submit_work_plan" in ctx["tools"]:
            return [plan_call([T("A", "Bea"), T("B", "Bea", ["A"])])]
        if "select_superseded" in ctx["tools"]:  # the PM's impact proposal
            refs = [line.split()[1] for line in ctx["brief"].splitlines() if "email" in line and line.startswith("- R-")]
            return [call("select_superseded", superseded_refs=refs, rationale="Email is no longer mandatory.")]
        if ctx["title"] == "Task A" and "ask_client" not in ctx["done"]:
            return [call("ask_client", question="Proceed?")]
        if not ctx["done"]:
            briefs.append((ctx["title"], ctx["brief"]))
        return simple_worker(ctx)

    fake(policy)
    proj = _csv_project(client)
    reqs = _reqs(client, proj["id"])
    email_rule = reqs["Every contact must have a valid email address."]
    reject_rule = reqs["Rows with missing or invalid email addresses must be rejected."]
    dup_rule = reqs["Identify duplicate contacts within the uploaded file."]
    assert email_rule["ref"].startswith("R-") and email_rule["status"] == "active"
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])  # Task A waits for the client
    r = client.post(f"/api/projects/{proj['id']}/messages", json={"content": CR, "intent": "requirement_change"}).json()
    assert "I propose that it replaces" in r["reply"] and email_rule["ref"] in r["reply"]
    [ap] = pending(client, proj["id"], "requirement_change")
    assert ap["payload"]["proposal_method"] == "project_manager"
    proposed = {c["ref"] for c in ap["payload"]["candidates"] if c["proposed"]}
    assert proposed == {email_rule["ref"], reject_rule["ref"]}
    rework_ids = [t["id"] for t in ap["payload"]["tasks"] if t["action"] in ("rework", "rework_after")]
    client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "approve", "task_ids": rework_ids})
    reqs = _reqs(client, proj["id"])
    change_ref = ap["payload"]["change_ref"]
    assert reqs[email_rule["text"]]["status"] == "superseded" and reqs[email_rule["text"]]["superseded_by"] == change_ref
    assert reqs[reject_rule["text"]]["superseded_by"] == change_ref
    assert reqs[dup_rule["text"]]["status"] == "active"  # unrelated rule untouched
    [q] = pending(client, proj["id"], "clarification")
    client.post(f"/api/approvals/{q['id']}/decide", json={"decision": "answer", "answer": "yes"})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    brief_b = next(b for t, b in briefs if t == "Task B")
    active_part, _, retired_part = brief_b.partition("NO LONGER VALID")
    assert "must have a valid email address" not in active_part  # the stale rule is gone from active requirements
    assert "must have a valid email address" in retired_part and f"replaced by {change_ref}" in retired_part
    assert CR in active_part
    # Editing the brief (which still contains the original sentence) never resurrects the retired rule.
    client.patch(f"/api/projects/{proj['id']}", json={"name": "renamed"})
    assert _reqs(client, proj["id"])[email_rule["text"]]["status"] == "superseded"
    types = [e["type"] for e in client.get(f"/api/projects/{proj['id']}/events").json()]
    assert "requirement_superseded" in types


async def test_D4_client_overrides_the_proposal_and_heuristic_fallback(client, fake):
    fake(planner_then([T("A", "Bea")]))  # the PM never calls select_superseded -> keyword fallback
    proj = _csv_project(client)
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    client.post(f"/api/projects/{proj['id']}/messages", json={"content": CR, "intent": "requirement_change"})
    [ap] = pending(client, proj["id"], "requirement_change")  # run finished -> still asks to confirm supersession
    assert ap["payload"]["proposal_method"] == "heuristic"
    cands = {c["text"]: c for c in ap["payload"]["candidates"]}
    assert cands["Every contact must have a valid email address."]["proposed"]
    only = cands["Every contact must have a valid email address."]["id"]
    client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "approve", "supersede_ids": [only]})
    reqs = _reqs(client, proj["id"])
    assert reqs["Every contact must have a valid email address."]["status"] == "superseded"
    assert reqs["Rows with missing or invalid email addresses must be rejected."]["status"] == "active"  # client unchecked it


# --- Traceability, evidence-based impact and stale-artifact protection --------------------------
TRACE_OBJECTIVE = ("Administrators upload CSV contact files.\n\n1. Identify duplicate contacts within the uploaded file.\n"
                   "2. Provide an import summary.\n\nEvery imported customer contact must have a valid email address.")
CR_PHONE = "Contacts may be imported if they have either a valid email address or a valid phone number."


def _ref(brief, needle):
    import re as _re
    m = _re.search(r"^- (R-\d{3}) \[[^\]]+\] .*" + _re.escape(needle), brief.split("NO LONGER VALID")[0], _re.M)
    return m.group(1) if m else None


def _trace_plan(gate=None):
    """A = validation rules (email), C = duplicates (unrelated), B = summary built on A's output."""
    def policy(ctx):
        if "submit_work_plan" in ctx["tools"]:
            b = ctx["brief"]
            return [plan_call([
                {**T("A", "Bea"), "requirement_refs": [_ref(b, "valid email")]},
                {**T("C", "Archie"), "requirement_refs": [_ref(b, "duplicate contacts")]},
                {**T("B", "Bea", ["A"]), "requirement_refs": [_ref(b, "import summary")]},
            ])]
        if "select_superseded" in ctx["tools"]:
            return [call("select_superseded", superseded_refs=[_ref(ctx["brief"], "valid email")], rationale="email-only rule replaced")]
        if gate and gate(ctx):
            return gate(ctx)
        return simple_worker(ctx)
    return policy


def _trace_project(client):
    p = make_project(client, roles=("project_manager", "business_analyst", "software_architect"))
    client.patch(f"/api/projects/{p['id']}", json={"objective": TRACE_OBJECTIVE})
    return p


async def test_plan_tasks_must_cite_valid_requirements(client, fake):
    attempts = []

    def policy(ctx):
        if "submit_work_plan" in ctx["tools"]:
            attempts.append(ctx["results"])
            refs = ["R-999"] if len(attempts) == 1 else [_ref(ctx["brief"], "valid email")]
            return [plan_call([{**T("A", "Bea"), "requirement_refs": refs}])]
        return simple_worker(ctx)

    fake(policy)
    proj = _trace_project(client)
    run = await start_and_approve(client, proj["id"])
    assert any("unknown requirement reference 'R-999'" in r["content"] for r in attempts[1])  # validated, PM corrected
    [t] = tasks_of(client, proj["id"])
    assert len(t["requirement_refs"]) == 1 and t["requirement_refs"][0].startswith("R-")
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    [art] = [a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json() if a["name"] == "Task A"]
    detail = client.get(f"/api/artifacts/{art['id']}").json()
    assert detail["versions"][0]["requirement_refs"] == t["requirement_refs"]  # lineage snapshot on the version


async def test_impact_is_evidence_based_and_preserves_unrelated_work(client, fake):
    gate = {"hold": True}
    fake(_trace_plan(lambda ctx: [call("ask_client", question="Proceed with B?")]
                     if ctx["title"] == "Task B" and gate["hold"] and "ask_client" not in ctx["done"] else None))
    proj = _trace_project(client)
    client.put(f"/api/projects/{proj['id']}/budget", json={"max_concurrency": 1})
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])  # A and C completed, B in flight (waiting for the client)
    ts = {t["title"]: t for t in tasks_of(client, proj["id"])}
    assert ts["Task A"]["status"] == "completed" and ts["Task C"]["status"] == "completed"
    r = client.post(f"/api/projects/{proj['id']}/messages", json={"content": CR_PHONE, "intent": "requirement_change"}).json()
    assert "task-requirement links and artifact lineage" in r["reply"]
    [ap] = pending(client, proj["id"], "requirement_change")
    by_title = {t["title"]: t for t in ap["payload"]["tasks"]}
    assert by_title["Task A"]["impact"] == "direct" and by_title["Task A"]["action"] == "rework"
    assert by_title["Task B"]["impact"] == "downstream" and by_title["Task B"]["action"] == "rework_after"
    assert by_title["Task C"]["action"] == "if_selected"  # affected only if the client also replaced its rule
    assert "Task C" in ap["payload"]["preserved_tasks"] or by_title["Task C"]["impact"] == "if_selected"
    assert {a["name"] for a in ap["payload"]["artifacts_at_risk"]} == {"Task A"}
    rework = [t["id"] for t in ap["payload"]["tasks"] if t["action"] in ("rework", "rework_after")]
    client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "approve", "task_ids": rework})
    gate["hold"] = False
    [q] = pending(client, proj["id"], "clarification")
    client.post(f"/api/approvals/{q['id']}/decide", json={"decision": "answer", "answer": "yes"})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    ts = tasks_of(client, proj["id"])
    reworked = sorted(t["title"] for t in ts if t["kind"] == "rework")
    assert reworked == ["Rework: Task A", "Rework: Task B"]  # only the affected chain was redone
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    assert arts["Task C"]["current_version"] == 1 and not arts["Task C"]["stale"]  # preserved, still current
    assert arts["Task A"]["current_version"] == 2 and not arts["Task A"]["stale"]
    rw_b = next(t for t in ts if t["title"] == "Rework: Task B")
    rw_a = next(t for t in ts if t["title"] == "Rework: Task A")
    assert rw_a["id"] in rw_b["depends_on"]  # downstream rework waited for the upstream rework
    a_task = next(t for t in ts if t["title"] == "Task A")
    assert a_task["requirement_refs"] and rw_a["requirement_refs"] != a_task["requirement_refs"]  # rework uses new baseline


async def test_stale_deliverable_blocks_delivery_until_confirmed(client, fake):
    fake(_trace_plan())
    proj = _trace_project(client)
    run = await start_and_approve(client, proj["id"])
    gate = {"stop": True}
    with SessionLocal() as db:  # hold the run after A completes by pausing it
        pass
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    # Change after delivery, client approves supersession but requests no rework yet.
    client.post(f"/api/projects/{proj['id']}/messages", json={"content": CR_PHONE, "intent": "requirement_change"})
    [ap] = pending(client, proj["id"], "requirement_change")
    client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "approve"})
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    assert arts["Task A"]["stale"] and "implements superseded" in arts["Task A"]["stale_reason"]
    assert arts["Task B"]["stale"] and "derived from stale input" in arts["Task B"]["stale_reason"]
    # A revision run cannot deliver while required inputs are stale.
    [acc] = pending(client, proj["id"], "deliverable_acceptance")
    client.post(f"/api/approvals/{acc['id']}/decide", json={"decision": "revise", "comment": "Apply the phone rule"})
    run2 = client.get(f"/api/projects/{proj['id']}/state").json()["current_run"]
    await drive(run2["id"])
    [sow] = pending(client, proj["id"], "sow")
    plan = sow["payload"]["plan"]
    plan["tasks"] = [t for t in plan["tasks"] if t["key"] == "C"]  # client approves only unrelated work
    client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve", "plan": plan})
    await drive(run2["id"])
    assert run_status(run2["id"]) == "blocked"
    [blk] = pending(client, proj["id"], "stale_artifacts")
    names = {b["name"] for b in blk["payload"]["artifacts"]}
    assert {"Task A", "Task B"} <= names and "Task C" not in names
    assert not [t for t in tasks_of(client, proj["id"]) if t["kind"] == "consolidation" and t["run_id"] == run2["id"]]
    client.post(f"/api/approvals/{blk['id']}/decide", json={"decision": "approve", "option": "rework"})
    await drive(run2["id"])
    assert run_status(run2["id"]) == "completed"
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    stale = {n for n, a in arts.items() if a["category"] == "deliverable" and a["stale"]}
    assert stale == set()  # run 2's consolidation re-issued the summary under the current baseline
    cons = client.get(f"/api/artifacts/{arts['Consolidate final delivery']['id']}").json()
    assert len(cons["versions"]) == 2  # run 1's stale summary kept as v1 for audit
    assert not arts["Task A"]["stale"] and not arts["Task B"]["stale"] and not arts["Task C"]["stale"]
    detail = client.get(f"/api/artifacts/{arts['Task A']['id']}").json()
    assert [v["version"] for v in detail["versions"]] == [1, 2]  # stale version preserved for audit


async def test_untraced_work_is_flagged_uncertain_and_client_can_confirm(client, fake):
    fake(_trace_plan())
    proj = _trace_project(client)
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])
    from app.models import ArtifactVersion, TaskRequirement
    with SessionLocal() as db:  # simulate legacy work produced before traceability existed
        c = db.query(Task).filter(Task.title == "Task C").one()
        db.query(TaskRequirement).filter(TaskRequirement.task_id == c.id).delete()
        for v in db.query(ArtifactVersion).filter(ArtifactVersion.created_by_task_id == c.id):
            v.requirement_ids = []
        db.commit()
    client.post(f"/api/projects/{proj['id']}/messages", json={"content": CR_PHONE, "intent": "requirement_change"})
    [ap] = pending(client, proj["id"], "requirement_change")
    client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "approve"})
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    assert arts["Task C"]["stale"] and "no requirement links" in arts["Task C"]["stale_reason"]  # not silently omitted
    [acc] = pending(client, proj["id"], "deliverable_acceptance")
    client.post(f"/api/approvals/{acc['id']}/decide", json={"decision": "revise", "comment": "update"})
    run2 = client.get(f"/api/projects/{proj['id']}/state").json()["current_run"]
    await drive(run2["id"])
    [sow] = pending(client, proj["id"], "sow")
    plan = sow["payload"]["plan"]
    plan["tasks"] = [t for t in plan["tasks"] if t["key"] != "C"]  # the legacy, untraced document is not redone
    client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve", "plan": plan})
    await drive(run2["id"])
    [blk] = pending(client, proj["id"], "stale_artifacts")
    assert {b["name"] for b in blk["payload"]["artifacts"]} == {"Task C"}  # only the unverifiable one blocks
    c_id = next(b["artifact_id"] for b in blk["payload"]["artifacts"] if b["name"] == "Task C")
    client.post(f"/api/approvals/{blk['id']}/decide", json={"decision": "approve", "option": "confirm", "artifact_ids": [c_id]})
    arts = {a["name"]: a for a in client.get(f"/api/projects/{proj['id']}/artifacts").json()}
    assert not arts["Task C"]["stale"] and arts["Task C"]["confirmed_version"] == arts["Task C"]["current_version"]
    await drive(run2["id"])
    assert run_status(run2["id"]) == "completed"


async def test_relinked_task_keeps_link_history(client, fake):
    hold = {"on": True}
    fake(_trace_plan(lambda ctx: [call("ask_client", question="Go?")]
                     if ctx["title"] == "Task A" and hold["on"] and "ask_client" not in ctx["done"] else None))
    proj = _trace_project(client)
    run = await start_and_approve(client, proj["id"])
    await drive(run["id"])  # A in flight (waiting), C done, B not started (depends on A)
    b = next(t for t in tasks_of(client, proj["id"]) if t["title"] == "Task B")
    assert b["status"] in ("pending", "ready")
    client.post(f"/api/projects/{proj['id']}/messages", json={"content": CR_PHONE, "intent": "requirement_change"})
    [ap] = pending(client, proj["id"], "requirement_change")
    by_title = {t["title"]: t for t in ap["payload"]["tasks"]}
    assert by_title["Task A"]["action"] == "rework_after"
    assert by_title["Task B"]["action"] == "wait"  # not started, downstream of A: must not run on stale input
    rework = [t["id"] for t in ap["payload"]["tasks"] if t["action"] in ("rework", "rework_after")]
    client.post(f"/api/approvals/{ap['id']}/decide", json={"decision": "approve", "task_ids": rework})
    ts = tasks_of(client, proj["id"])
    b = next(t for t in ts if t["title"] == "Task B")
    rw_a = next(t for t in ts if t["title"] == "Rework: Task A")
    assert rw_a["id"] in b["depends_on"]
    a = next(t for t in ts if t["title"] == "Task A")
    assert a["requirement_refs"]  # the in-flight task keeps its historical link (its output becomes stale)
    hold["on"] = False
    [q] = pending(client, proj["id"], "clarification")
    client.post(f"/api/approvals/{q['id']}/decide", json={"decision": "answer", "answer": "go"})
    await drive(run["id"])
    assert run_status(run["id"]) == "completed"
    with SessionLocal() as db:
        bt = db.query(Task).filter(Task.title == "Task B").one()
        rw = db.query(Task).filter(Task.title == "Rework: Task A").one()
        assert bt.started_at >= rw.completed_at  # B consumed the reworked, current output


async def test_D6_budget_block_separates_actual_spend_from_reservations(client, fake):
    fake(planner_then([T("A", "Bea")]), test_provider=False)
    proj = make_project(client, roles=("project_manager", "business_analyst"), provider="anthropic", model="claude-haiku-5-5")
    registry.set_override("anthropic", registry._overrides["scripted-test"])
    client.put(f"/api/projects/{proj['id']}/budget", json={"budget_usd": 0.0001})
    from app.security import credentials
    credentials.save_secret("anthropic", "sk-ant-test-0000000000")
    try:
        run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
        await drive(run["id"])
        [b] = pending(client, proj["id"], "budget")
        assert "spent $0.0000" in b["explanation"] and "reserved for calls in progress $0.0000" in b["explanation"]
        assert "worst case" in b["explanation"] and "output tokens must fit" in b["explanation"]
    finally:
        registry.set_override("anthropic", None)



# --- Budget reservations: cap the output allowance instead of blocking; the cap stays a guarantee ---
class WorstCaseProvider(FakeProvider):
    """Bills every call at its worst case: input from the real request size, output = max_tokens."""

    async def complete(self, *, model, system, messages, tools, max_tokens, effort=None):
        r = await super().complete(model=model, system=system, messages=messages, tools=tools, max_tokens=max_tokens,
                                   effort=effort)
        import json as _json
        from app.pricing import estimate_tokens
        sent = len(system) + sum(len(str(m.get("content"))) for m in messages) + sum(
            len(t.name) + len(t.description) + len(_json.dumps(t.input_schema)) for t in tools)
        r.usage.input_tokens, r.usage.output_tokens = estimate_tokens(sent), max_tokens
        self.max_tokens_seen = getattr(self, "max_tokens_seen", []) + [max_tokens]
        return r


def _priced_project(client, fake_policy, budget, *, concurrency=1, roles=("project_manager", "business_analyst")):
    p = WorstCaseProvider(fake_policy, test_provider=False)
    registry.set_override("scripted-test", p)
    registry.set_override("anthropic", p)
    proj = make_project(client, roles=roles, provider="anthropic", model="claude-opus-5-5")  # $4 / $20 per Mtok
    from app.security import credentials
    credentials.save_secret("anthropic", "sk-ant-test-0000000000")
    client.put(f"/api/projects/{proj['id']}/budget", json={"budget_usd": budget, "max_concurrency": concurrency})
    return p, proj


async def test_budget_caps_output_allowance_instead_of_blocking(client):
    """With $0.70 left, the 16,000-token worst case ($0.32+) no longer fits twice: later calls run
    with a reduced allowance instead of stopping the run, and spend never passes the budget."""
    try:
        p, proj = _priced_project(client, planner_then([T("A", "Bea"), T("B", "Bea")]), 0.70)
        run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
        await drive(run["id"])
        [sow] = pending(client, proj["id"], "sow")
        client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve"})
        await drive(run["id"])
        spent = client.get(f"/api/projects/{proj['id']}/costs").json()["estimated_total_usd"]
        assert spent <= 0.70  # guarantee holds even though EVERY call was billed at its worst case
        assert any(m < 16000 for m in p.max_tokens_seen)  # some calls ran with a reduced allowance
        evs = [e for e in client.get(f"/api/projects/{proj['id']}/events").json() if e["type"] == "budget_capped"]
        assert evs and "reduced from 16000" in evs[0]["message"]
        assert not [e for e in client.get(f"/api/projects/{proj['id']}/events").json() if e["type"] == "budget_estimate_exceeded"]
    finally:
        registry.set_override("anthropic", None)
        registry.set_override("scripted-test", None)


async def test_budget_blocks_only_below_the_minimum_useful_allowance(client):
    try:
        p, proj = _priced_project(client, planner_then([T("A", "Bea"), T("B", "Bea"), T("C", "Bea")]), 0.40)
        run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
        await drive(run["id"])
        [sow] = pending(client, proj["id"], "sow")
        client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve"})
        await drive(run["id"])
        [b] = pending(client, proj["id"], "budget")
        assert "2000 output tokens must fit" in b["explanation"]
        assert min(p.max_tokens_seen) >= 2000  # no call ever ran with a uselessly small allowance
        spent = client.get(f"/api/projects/{proj['id']}/costs").json()["estimated_total_usd"]
        assert spent <= 0.40
    finally:
        registry.set_override("anthropic", None)
        registry.set_override("scripted-test", None)


async def test_parallel_calls_share_the_remaining_budget_safely(client):
    """Concurrent tasks reserve their worst case; together they can never exceed the budget."""
    try:
        policy = planner_then([T("A", "Bea"), T("B", "Archie"), T("C", "Bea"), T("D", "Archie")])
        p, proj = _priced_project(client, policy, 0.90, concurrency=4,
                                  roles=("project_manager", "business_analyst", "software_architect"))
        p.delay = 0.05
        run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
        await drive(run["id"])
        [sow] = pending(client, proj["id"], "sow")
        client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve"})
        await drive(run["id"])
        spent = client.get(f"/api/projects/{proj['id']}/costs").json()["estimated_total_usd"]
        assert spent <= 0.90 and p.max_active >= 2
    finally:
        registry.set_override("anthropic", None)
        registry.set_override("scripted-test", None)


async def test_agent_spend_limit_is_guaranteed_across_parallel_tasks(client):
    try:
        policy = planner_then([T("A", "Bea"), T("B", "Bea"), T("C", "Bea")])
        p, proj = _priced_project(client, policy, None, concurrency=3)
        bea = next(a for a in client.get(f"/api/projects/{proj['id']}/agents").json() if a["display_name"] == "Bea")
        client.patch(f"/api/projects/{proj['id']}/agents/{bea['id']}", json={"spend_limit_usd": 0.50})
        p.delay = 0.05
        run = client.post(f"/api/projects/{proj['id']}/runs", json={}).json()
        await drive(run["id"])
        [sow] = pending(client, proj["id"], "sow")
        client.post(f"/api/approvals/{sow['id']}/decide", json={"decision": "approve"})
        await drive(run["id"])
        by_agent = {a["key"]: a["estimated_cost_usd"] for a in client.get(f"/api/projects/{proj['id']}/costs").json()["by_agent"]}
        assert by_agent["Bea"] <= 0.50
    finally:
        registry.set_override("anthropic", None)
        registry.set_override("scripted-test", None)
