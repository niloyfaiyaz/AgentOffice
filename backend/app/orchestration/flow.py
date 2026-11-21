"""Run-level orchestration steps used as LangGraph nodes."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections import defaultdict
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events, services
from ..db import SessionLocal
from ..models import (
    ApprovalRequest, Artifact, Project, ProjectAgent, ProjectRun, ReviewFinding, Task, TaskDependency, TaskExecution,
    utcnow,
)
from ..state_machine import TASK_DONE, TASK_TERMINAL, sync_project_status, transition_run, transition_task
from .runner import run_task

log = logging.getLogger("agentoffice.flow")
ACTIVE_WAIT = {"waiting_approval", "waiting_subtask"}


def _key(run_id, *parts) -> str:
    return hashlib.sha256("|".join([str(run_id), *map(str, parts)]).encode()).hexdigest()[:40]


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------
def promote_ready(db: Session, run: ProjectRun) -> None:
    tasks = services.run_tasks(db, run.id)
    status = {t.id: t.status for t in tasks}
    deps: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for d in db.scalars(select(TaskDependency).join(Task, Task.id == TaskDependency.task_id).where(Task.run_id == run.id)):
        deps[d.task_id].append(d.depends_on_task_id)
    for t in tasks:
        if t.status == "pending" and all(status.get(d) in TASK_DONE for d in deps[t.id]):
            transition_task(t, "ready")
        elif t.status == "waiting_subtask":
            subs = [d for d in deps[t.id] if db.get(Task, d).parent_task_id == t.id]
            if subs and all(status.get(s) in TASK_TERMINAL for s in subs):
                transition_task(t, "ready")
        elif t.status == "paused" and run.requested_action is None:
            transition_task(t, "ready")
    db.flush()


def blocked_by_failure(db: Session, run: ProjectRun) -> list[Task]:
    return [t for t in services.run_tasks(db, run.id) if t.status == "failed"]


# ---------------------------------------------------------------------------
# Execute: a concurrency-limited pool that refills as tasks finish
# ---------------------------------------------------------------------------
async def execute(run_id: uuid.UUID) -> str:
    """Run ready tasks until none can progress. Returns 'progress_done' | 'control' | 'waiting'."""
    running: dict[asyncio.Task, uuid.UUID] = {}
    while True:
        with SessionLocal() as db:
            run = db.get(ProjectRun, run_id)
            policy = services.get_budget(db, run.project_id)
            control = run.requested_action is not None
            if not control:
                promote_ready(db, run)
            db.commit()
            ready = [] if control else [t.id for t in services.run_tasks(db, run.id) if t.status == "ready"]
            timeout = policy.task_timeout_seconds
            limit = max(1, policy.max_concurrency)
        in_flight = set(running.values())
        for tid in ready:
            if len(running) >= limit:
                break
            if tid in in_flight:
                continue
            coro = asyncio.wait_for(run_task(tid), timeout=timeout)
            running[asyncio.ensure_future(coro)] = tid
        if not running:
            break
        done, _ = await asyncio.wait(running.keys(), return_when=asyncio.FIRST_COMPLETED)
        for fut in done:
            tid = running.pop(fut)
            exc = fut.exception()
            if exc is not None:
                _handle_crash(tid, exc, timeout)
    with SessionLocal() as db:
        run = db.get(ProjectRun, run_id)
        if run.requested_action is not None:
            return "control"
        tasks = services.run_tasks(db, run.id)
        if all(t.status in TASK_DONE or t.status == "cancelled" for t in tasks):
            return "progress_done"
        return "waiting"


def _handle_crash(task_id: uuid.UUID, exc: BaseException, timeout: int) -> None:
    from .runner import _fail

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task.status in TASK_TERMINAL or task.status in ACTIVE_WAIT or task.status == "paused":
            return
        run = db.get(ProjectRun, task.run_id)
        project = db.get(Project, task.project_id)
        agent = db.get(ProjectAgent, task.assigned_agent_id) if task.assigned_agent_id else None
        ex = db.scalar(select(TaskExecution).where(TaskExecution.task_id == task.id)
                       .order_by(TaskExecution.attempt.desc()).limit(1))
        if isinstance(exc, asyncio.TimeoutError):
            msg = f"Task exceeded its {timeout}s time limit."
        else:
            log.exception("task crashed", exc_info=exc)
            msg = f"Internal error: {type(exc).__name__}: {str(exc)[:300]}"
        _fail(db, project, run, task, agent, ex, msg, retry=True)


def settle_waiting(run_id: uuid.UUID) -> str:
    """After execute returns 'waiting': mark the run blocked with a clear reason. Returns 'blocked'."""
    with SessionLocal() as db:
        run = db.get(ProjectRun, run_id)
        project = db.get(Project, run.project_id)
        failed = blocked_by_failure(db, run)
        for t in failed:
            exists = db.scalar(select(ApprovalRequest).where(ApprovalRequest.task_id == t.id,
                                                             ApprovalRequest.kind == "task_failure",
                                                             ApprovalRequest.status == "pending"))
            if exists is None:
                services.create_approval(
                    db, project_id=project.id, run_id=run.id, kind="task_failure",
                    title=f"“{t.title}” failed", explanation=f"{t.error}\n\nRetry the task, skip it (dependent work "
                    "continues without it), or cancel the run.", payload={"options": ["retry", "skip", "cancel"]},
                    task_id=t.id, agent_id=t.assigned_agent_id)
        pending = services.pending_approvals(db, run.id)
        waiting = [t for t in services.run_tasks(db, run.id) if t.status in ACTIVE_WAIT]
        if pending:
            run.blocked_reason = "Waiting for client: " + "; ".join(a.title for a in pending)[:900]
        elif waiting:
            run.blocked_reason = "Waiting for delegated work."
        else:
            run.blocked_reason = "No task can make progress."
        transition_run(run, "blocked")
        sync_project_status(project, run)
        events.emit(db, project.id, "run_blocked", run.blocked_reason, run_id=run.id)
        db.commit()
        return "blocked"


# ---------------------------------------------------------------------------
# Review gate: QA -> targeted rework (bounded) -> consolidation
# ---------------------------------------------------------------------------
def _qa_agent(db: Session, project_id) -> Optional[ProjectAgent]:
    for a in services.team(db, project_id):
        if a.role_key == "qa_reviewer":
            return a
    return None


def review_gate(run_id: uuid.UUID) -> str:
    """Returns 'more_work' (new tasks created) or 'finalize'."""
    with SessionLocal() as db:
        run = db.get(ProjectRun, run_id)
        project = db.get(Project, run.project_id)
        policy = services.get_budget(db, project.id)
        tasks = services.run_tasks(db, run.id)
        work = [t for t in tasks if t.kind in ("work", "subtask", "rework") and t.status == "completed"]
        qa_tasks = [t for t in tasks if t.kind == "qa"]
        consolidation = next((t for t in tasks if t.kind == "consolidation"), None)
        qa = _qa_agent(db, project.id)
        pm = services.orchestrator(db, project.id)
        order = max((t.sort_order for t in tasks), default=0) + 1

        if _stale_gate(db, run, project, stage="pre"):
            db.commit()
            return "blocked"

        if consolidation is not None:
            return "finalize"

        wants_qa = bool((run.sow or {}).get("qa_review", True))
        if qa is not None and wants_qa and not qa_tasks:
            t = _new_task(db, run, qa, "qa", "QA review of deliverables",
                          "Review every deliverable against the approved acceptance criteria and requirements.",
                          ["Every acceptance criterion is checked", "Findings cite evidence and a recommended correction"],
                          deps=work, order=order, key=_key(run.id, "qa", 1))
            events.emit(db, project.id, "review_requested", f"{qa.display_name} was asked to review the deliverables",
                        run_id=run.id, agent_id=qa.id, task_id=t.id, agent_status="assigned")
            db.commit()
            return "more_work"

        if qa is not None and qa_tasks:
            blocking = list(db.scalars(select(ReviewFinding).where(
                ReviewFinding.run_id == run.id, ReviewFinding.status.in_(["open", "rework_requested"]),
                ReviewFinding.severity.in_(["critical", "major"]))))
            if blocking and run.review_iterations < policy.max_review_iterations:
                run.review_iterations += 1
                groups: dict[uuid.UUID, list[ReviewFinding]] = defaultdict(list)
                for f in blocking:
                    owner = None
                    if f.artifact_id:
                        art = db.get(Artifact, f.artifact_id)
                        owner = art.owner_agent_id if art else None
                    groups[owner or (pm.id if pm else qa.id)].append(f)
                rework = []
                for agent_id, fs in groups.items():
                    agent = db.get(ProjectAgent, agent_id)
                    if agent is None or agent.removed:
                        agent = pm or qa
                    arts = sorted({str(f.artifact_id) for f in fs if f.artifact_id})
                    t = _new_task(db, run, agent, "rework", f"Rework: address QA findings ({', '.join(f.finding_key for f in fs)})",
                                  "Revise the affected deliverables to resolve the QA findings listed below.",
                                  [f"{f.finding_key} is resolved" for f in fs], deps=[], order=order,
                                  key=_key(run.id, "rework", run.review_iterations, agent.id))
                    t.finding_ids = [str(f.id) for f in fs]
                    t.input_refs = arts
                    from .. import traceability

                    req_ids = set()
                    for aid in arts:
                        lv = services.latest_version(db, uuid.UUID(aid))
                        req_ids |= {str(r) for r in (lv.requirement_ids if lv else [])}
                    traceability.link(db, t, traceability.current_requirement_ids(db, req_ids), "qa")
                    for f in fs:
                        f.status = "rework_requested"
                    rework.append(t)
                    qa_task = qa_tasks[-1]
                    from ..models import AgentHandoff

                    db.add(AgentHandoff(project_id=project.id, run_id=run.id, from_agent_id=qa.id, to_agent_id=agent.id,
                                        source_task_id=qa_task.id, created_task_id=t.id, kind="rework",
                                        summary=f"Rework requested for {', '.join(f.finding_key for f in fs)}"))
                    events.emit(db, project.id, "rework_requested",
                                f"{qa.display_name} sent {len(fs)} finding(s) back to {agent.display_name}",
                                run_id=run.id, agent_id=agent.id, task_id=t.id, agent_status="assigned",
                                data={"findings": [f.finding_key for f in fs], "from_agent_id": str(qa.id)})
                db.flush()
                t2 = _new_task(db, run, qa, "qa", f"QA re-review (round {run.review_iterations + 1})",
                               "Re-check the reworked deliverables. Resolve findings that are fixed (resolved_finding_keys) "
                               "and report anything still wrong.",
                               ["Each earlier finding is resolved or re-reported"], deps=rework, order=order + 1,
                               key=_key(run.id, "qa", run.review_iterations + 1))
                events.emit(db, project.id, "review_requested", f"{qa.display_name} will re-review after rework",
                            run_id=run.id, agent_id=qa.id, task_id=t2.id)
                db.commit()
                return "more_work"
            for f in blocking:
                f.status = "unresolved"
            if blocking:
                events.emit(db, project.id, "review_limit",
                            f"Review cycle limit reached; {len(blocking)} finding(s) remain unresolved and are reported to the client",
                            run_id=run.id)

        delivered = [t for t in services.run_tasks(db, run.id) if t.status == "completed"
                     and t.kind in ("work", "subtask", "rework")]
        if not qa_tasks and len(delivered) <= 1:
            # Nothing to consolidate: skip a model call and write the summary from records.
            _deterministic_summary(db, project, run, delivered)
            db.commit()
            return "finalize"

        if pm is not None:
            all_done = [t for t in services.run_tasks(db, run.id) if t.status == "completed"]
            t = _new_task(db, run, pm, "consolidation", "Consolidate final delivery",
                          "Write the final delivery summary: what was delivered, each teammate's contribution, assumptions, "
                          "open questions, QA findings still open, and which claims are verified (by tests/tools) versus unverified.",
                          ["Summarizes every deliverable", "Lists unresolved findings and open questions",
                           "Separates verified from unverified claims"], deps=all_done, order=order + 2,
                          key=_key(run.id, "consolidation"))
            t.allowed_tools = ["artifact_read", "artifact_write", "file_read"]
            events.emit(db, project.id, "task_assigned", f"{pm.display_name} is consolidating the final delivery",
                        run_id=run.id, agent_id=pm.id, task_id=t.id, agent_status="assigned")
            db.commit()
            return "more_work"
        db.commit()
        return "finalize"


def _deterministic_summary(db: Session, project: Project, run: ProjectRun, delivered: list[Task]) -> None:
    lines = [f"# Final Delivery Summary — run {run.run_number}", "",
             "_Compiled automatically from the task records (no model call); a single task needed no consolidation._", ""]
    for t in delivered:
        who = db.get(ProjectAgent, t.assigned_agent_id) if t.assigned_agent_id else None
        lines += [f"## {t.title} — {who.display_name if who else 'teammate'}", t.result_summary or "(no summary)", ""]
        for aid in t.output_artifact_ids:
            a = db.get(Artifact, uuid.UUID(aid))
            if a:
                lines.append(f"- Deliverable: “{a.name}” v{a.current_version}")
        lines.append("")
    lines += ["## Quality assurance", "No independent QA review was performed for this run.", "",
              "## Verification", "Nothing in this delivery has been independently verified unless a deliverable states "
              "that tests were run in the sandbox.", ""]
    inputs = [str(v.id) for t in delivered for aid in t.output_artifact_ids
              if (v := services.latest_version(db, uuid.UUID(aid))) is not None]
    services.write_artifact(db, project_id=project.id, run_id=run.id, task_id=None, agent_id=None,
                            name=f"Final Delivery Summary (run {run.run_number})", content="\n".join(lines),
                            artifact_type="markdown", summary="Automatic delivery summary.", category="summary",
                            extra_inputs=inputs)


def _new_task(db: Session, run: ProjectRun, agent: ProjectAgent, kind: str, title: str, objective: str,
              criteria: list[str], deps: list[Task], order: int, key: str) -> Task:
    existing = db.scalar(select(Task).where(Task.run_id == run.id, Task.idempotency_key == key))
    if existing is not None:
        return existing
    t = Task(project_id=run.project_id, run_id=run.id, assigned_agent_id=agent.id, kind=kind, title=title,
             objective=objective, acceptance_criteria=criteria, allowed_tools=sorted(services.agent_permissions(db, agent)),
             idempotency_key=key, max_model_calls=agent.max_calls_per_task, sort_order=order, status="pending")
    db.add(t)
    db.flush()
    for d in deps:
        db.add(TaskDependency(task_id=t.id, depends_on_task_id=d.id))
    db.flush()
    return t


# ---------------------------------------------------------------------------
# Finalize / halt
# ---------------------------------------------------------------------------
def _stale_gate(db: Session, run: ProjectRun, project: Project, stage: str = "final") -> bool:
    """Deterministic delivery gate: block while any deliverable is stale (from lineage).
    Returns True when the run must wait for the client."""
    from .. import traceability

    blockers = traceability.delivery_blockers(db, project.id, run.id, stage)
    if not blockers:
        return False
    if not db.scalar(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id, ApprovalRequest.kind == "stale_artifacts",
                                                   ApprovalRequest.status == "pending")):
        services.create_approval(
            db, project_id=project.id, run_id=run.id, kind="stale_artifacts",
            title=f"Delivery blocked: {len(blockers)} deliverable(s) are not current",
            explanation=("These deliverables were derived from requirements that have since been replaced (or their lineage "
                         "cannot be verified), so they cannot be delivered as current:\n"
                         + "\n".join(f"- {b['name']} v{b['version']}: {b['reason']}" for b in blockers)
                         + "\n\nRework them (targeted tasks for the producing agents) or, if you have checked them, "
                           "confirm they are current."),
            payload={"artifacts": blockers, "options": ["rework", "confirm", "cancel"]},
            artifact_ids=[uuid.UUID(b["artifact_id"]) for b in blockers])
    events.emit(db, project.id, "delivery_blocked", f"Delivery blocked: {len(blockers)} stale deliverable(s)", run_id=run.id,
                data={"artifacts": [b["name"] for b in blockers]})
    return True


def finalize(run_id: uuid.UUID) -> bool:
    """Returns False if the delivery gate blocked completion."""
    with SessionLocal() as db:
        run = db.get(ProjectRun, run_id)
        project = db.get(Project, run.project_id)
        if _stale_gate(db, run, project):
            db.commit()
            return False
        tasks = services.run_tasks(db, run.id)
        findings = list(db.scalars(select(ReviewFinding).where(ReviewFinding.run_id == run.id)))
        # "info" findings are reviewer observations, not defects; they are reported separately.
        unresolved = [f for f in findings if f.status in ("open", "unresolved", "rework_requested") and f.severity != "info"]
        notes = [f for f in findings if f.severity == "info"]
        qa_done = any(t.kind == "qa" and t.status == "completed" for t in tasks)
        summary = next((t for t in tasks if t.kind == "consolidation"), None)
        arts = [a for a in services.project_artifacts(db, project.id, include_working=False) if a.category != "plan"]
        transition_run(run, "completed")
        run.phase = "done"
        run.finished_at = utcnow()
        sync_project_status(project, run)
        services.create_approval(
            db, project_id=project.id, run_id=run.id, kind="deliverable_acceptance", title="Review and accept the deliverables",
            explanation=("Agent work is complete. "
                         + ("A QA review was performed. " if qa_done else "No QA review was performed (no QA Reviewer on the team). ")
                         + (f"{len(unresolved)} QA finding(s) remain unresolved. " if unresolved else "")
                         + "QA approval is a review opinion, not proof of correctness. Accept the work, or request a revision."),
            payload={"agent_work_completed": True, "qa_performed": qa_done,
                     "unresolved_findings": [f.finding_key for f in unresolved],
                     "qa_notes": [f.finding_key for f in notes],
                     "summary_task_id": str(summary.id) if summary else None},
            artifact_ids=[a.id for a in arts])
        events.emit(db, project.id, "run_completed",
                    f"Run {run.run_number} finished: {len([t for t in tasks if t.status == 'completed'])} tasks completed, "
                    f"{len(unresolved)} unresolved finding(s). Awaiting client acceptance.", run_id=run.id)
        db.commit()
        return True


def halt(run_id: uuid.UUID) -> None:
    """Apply a pending pause or cancel request once no task is mid-call."""
    with SessionLocal() as db:
        run = db.get(ProjectRun, run_id)
        project = db.get(Project, run.project_id)
        action = run.requested_action
        if action == "cancel":
            for t in services.run_tasks(db, run.id):
                if t.status not in TASK_TERMINAL:
                    if t.status == "failed":
                        continue
                    transition_task(t, "cancelled")
            for ap in services.pending_approvals(db, run.id):
                ap.status = "cancelled"
                ap.resolved_at = utcnow()
            transition_run(run, "cancelled")
            run.finished_at = utcnow()
            run.requested_action = None
            for a in services.team(db, project.id):
                events.emit(db, project.id, "agent_released", f"{a.display_name} stopped work (run cancelled)",
                            run_id=run.id, agent_id=a.id, agent_status="idle")
            events.emit(db, project.id, "run_cancelled", f"Run {run.run_number} was cancelled by the client", run_id=run.id)
        elif action == "pause":
            if run.status != "paused":
                transition_run(run, "paused")
            run.requested_action = None
            events.emit(db, project.id, "run_paused", f"Run {run.run_number} is paused; in-flight work stopped at a safe point",
                        run_id=run.id)
        sync_project_status(project, run)
        db.commit()


def recover_interrupted(db: Session, run: ProjectRun) -> int:
    """Called when a worker takes over a run whose previous lease expired."""
    n = 0
    for t in services.run_tasks(db, run.id):
        if t.status == "running":
            ex = db.scalar(select(TaskExecution).where(TaskExecution.task_id == t.id)
                           .order_by(TaskExecution.attempt.desc()).limit(1))
            if ex is not None and ex.status == "running":
                ex.status = "suspended"  # resume the persisted conversation
            transition_task(t, "ready")
            n += 1
    if n:
        events.emit(db, run.project_id, "run_recovered", f"Recovered {n} interrupted task(s) after a restart", run_id=run.id)
    return n
