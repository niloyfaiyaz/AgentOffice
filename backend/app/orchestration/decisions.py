"""Applying client decisions and interventions to orchestration state."""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import events, services
from ..catalog import TOOL_PERMISSIONS
from ..models import (
    ApprovalRequest, Artifact, Project, ProjectAgent, ProjectRequirement, ProjectRun, Task, TaskDependency,
    UserDecision, utcnow,
)
from ..state_machine import RUN_TERMINAL, sync_project_status, transition_run, transition_task
from . import planner

CONSEQUENTIAL = {k for k, v in TOOL_PERMISSIONS.items() if v["consequential"]}


class DecisionError(ValueError):
    pass


def _dec(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation as e:
        raise DecisionError(f"Invalid amount: {v}") from e
    if d < 0:
        raise DecisionError("Amounts must be positive")
    return d


def wake(db: Session, run: ProjectRun) -> None:
    """Make a blocked run runnable again so the worker resumes it."""
    if run.status == "blocked":
        transition_run(run, "planning" if run.phase == "planning" else "running")
        run.blocked_reason = ""
        sync_project_status(db.get(Project, run.project_id), run)


def _ready(db: Session, task_id: Optional[uuid.UUID]) -> None:
    if task_id is None:
        return
    t = db.get(Task, task_id)
    if t is not None and t.status == "waiting_approval":
        transition_task(t, "ready")


def start_run(db: Session, project: Project, kind: str = "initial", feedback: str = "") -> ProjectRun:
    latest = services.latest_run(db, project.id)
    if latest is not None and latest.status not in RUN_TERMINAL:
        raise DecisionError("A run is already in progress for this project")
    pm = services.orchestrator(db, project.id)
    if pm is None:
        raise DecisionError("Hire a Project Manager (orchestrator) before starting")
    for a in services.team(db, project.id):
        if not a.provider or not a.model_id:
            raise DecisionError(f"{a.display_name} has no model assigned")
    services.sync_core_requirements(db, project)
    n = (db.scalar(select(func.max(ProjectRun.run_number)).where(ProjectRun.project_id == project.id)) or 0) + 1
    run = ProjectRun(project_id=project.id, run_number=n, kind=kind, revision_feedback=feedback, status="planning",
                     phase="planning", started_at=utcnow())
    db.add(run)
    db.flush()
    budget = services.get_budget(db, project.id)
    budget.approval_threshold_acknowledged = False
    if feedback:
        db.add(ProjectRequirement(project_id=project.id, kind="feedback", text=feedback, source="revision", run_id=run.id))
    for a in services.team(db, project.id):
        if a.status != "idle":
            events.emit(db, project.id, "agent_reset", f"{a.display_name} is available", run_id=run.id, agent_id=a.id,
                        agent_status="idle")
    sync_project_status(project, run)
    events.emit(db, project.id, "run_started", f"Run {n} started ({kind}); the Project Manager is planning",
                run_id=run.id, data={"kind": kind})
    db.flush()
    return run


def decide(db: Session, ap: ApprovalRequest, decision: str, body: dict[str, Any]) -> ApprovalRequest:
    if ap.status != "pending":
        raise DecisionError("This request has already been resolved")
    valid = {"approve", "reject", "revise", "answer"}
    if decision not in valid:
        raise DecisionError(f"decision must be one of {sorted(valid)}")
    project = db.get(Project, ap.project_id)
    run = db.get(ProjectRun, ap.run_id) if ap.run_id else None
    comment = str(body.get("comment") or "")[:4000]
    db.add(UserDecision(project_id=project.id, approval_request_id=ap.id, decision=decision, comment=comment,
                        payload=events._jsonable({k: v for k, v in body.items() if k != "comment"})))
    handler = {
        "sow": _sow, "clarification": _clarification, "tool_authorization": _tool_auth, "budget": _budget,
        "task_failure": _task_failure, "requirement_change": _requirement_change, "scope_change": _scope_change,
        "deliverable_acceptance": _acceptance, "stale_artifacts": _stale_artifacts,
    }.get(ap.kind)
    if handler is None:
        raise DecisionError(f"Unknown approval kind {ap.kind}")
    handler(db, project, run, ap, decision, body, comment)
    ap.resolved_at = utcnow()
    events.emit(db, project.id, "decision_recorded", f"Client decision on “{ap.title}”: {decision}",
                run_id=run.id if run else None, task_id=ap.task_id,
                data={"approval_id": str(ap.id), "kind": ap.kind, "decision": decision, "comment": comment[:500]})
    db.flush()
    return ap


# -- handlers ------------------------------------------------------------------------
def _sow(db, project, run, ap, decision, body, comment):
    if run is None or run.status != "awaiting_approval":
        raise DecisionError("The run is not awaiting plan approval")
    answers = body.get("answers") or {}
    for q, a in (answers.items() if isinstance(answers, dict) else []):
        if str(a).strip():
            db.add(ProjectRequirement(project_id=project.id, kind="clarification", text=f"{q} — {a}",
                                      source="clarification", run_id=run.id))
    if decision == "approve":
        raw = dict(body.get("plan") or run.sow)
        if body.get("qa_review") is not None:
            raw["qa_review"] = bool(body["qa_review"])
        plan, errors = planner.validate_plan(db, project, raw)
        if plan is None:
            raise DecisionError("The edited plan is invalid: " + "; ".join(errors))
        requested = body.get("approved_tools")
        tools = set(plan.tool_requirements) if requested is None else set(requested)
        tools &= CONSEQUENTIAL
        run.sow = plan.model_dump()
        planner.apply_approved_plan(db, project, run, plan, sorted(tools))
        ap.status = "approved"
        ap.payload = {**ap.payload, "approved_plan": run.sow, "approved_tools": sorted(tools)}
        transition_run(run, "running")
        run.phase = "executing"
        sync_project_status(project, run)
        pm = services.orchestrator(db, project.id)
        if pm:
            events.emit(db, project.id, "plan_approved", "The client approved the statement of work; work begins",
                        run_id=run.id, agent_id=pm.id, agent_status="idle")
    elif decision == "revise":
        if not comment.strip() and not answers:
            raise DecisionError("Describe what should change in the plan")
        if comment.strip():
            db.add(ProjectRequirement(project_id=project.id, kind="feedback", text=f"Plan feedback: {comment}",
                                      source="plan_review", run_id=run.id))
        ap.status = "revised"
        transition_run(run, "planning")
        run.phase = "planning"
        sync_project_status(project, run)
    elif decision == "reject":
        ap.status = "rejected"
        transition_run(run, "cancelled")
        run.finished_at = utcnow()
        sync_project_status(project, run)
    else:
        raise DecisionError("Use approve, revise or reject for a statement of work")


def _clarification(db, project, run, ap, decision, body, comment):
    if decision in ("answer", "approve"):
        answer = str(body.get("answer") or comment).strip()
        if not answer:
            raise DecisionError("Provide an answer")
        ap.status = "answered"
        ap.payload = {**ap.payload, "answer": answer}
        db.add(ProjectRequirement(project_id=project.id, kind="clarification", text=f"{ap.title} — {answer}",
                                  source="clarification", run_id=run.id if run else None))
    else:
        ap.status = "rejected"
        ap.payload = {**ap.payload, "comment": comment}
    _ready(db, ap.task_id)
    if run:
        wake(db, run)


def _tool_auth(db, project, run, ap, decision, body, comment):
    if decision == "approve":
        ap.status = "approved"
        if body.get("for_whole_run") and run is not None:
            run.approved_tools = sorted(set(run.approved_tools or []) | {ap.payload.get("tool")})
    else:
        ap.status = "rejected"
        ap.payload = {**ap.payload, "comment": comment}
    _ready(db, ap.task_id)
    if run:
        wake(db, run)


def _budget(db, project, run, ap, decision, body, comment):
    policy = services.get_budget(db, project.id)
    task_ids = [uuid.UUID(t) for t in ap.payload.get("task_ids", [])]
    if decision == "approve":
        if "budget_usd" in body:
            policy.budget_usd = _dec(body.get("budget_usd"))
            policy.warning_emitted = False
        if body.get("max_model_calls_per_run"):
            policy.max_model_calls_per_run = int(body["max_model_calls_per_run"])
        if "agent_limit_usd" in body and ap.payload.get("agent_id"):
            agent = db.get(ProjectAgent, uuid.UUID(ap.payload["agent_id"]))
            if agent:
                agent.spend_limit_usd = _dec(body.get("agent_limit_usd"))
        if ap.payload.get("reason") == "approval_threshold" or body.get("acknowledge_threshold"):
            policy.approval_threshold_acknowledged = True
        ap.status = "approved"
        for tid in task_ids:
            _ready(db, tid)
    else:
        ap.status = "rejected"
        for tid in task_ids:
            t = db.get(Task, tid)
            if t and t.status == "waiting_approval":
                transition_task(t, "failed")
                t.error = "The client declined additional spending."
        if run and run.phase == "planning":
            transition_run(run, "cancelled")
            run.finished_at = utcnow()
            sync_project_status(project, run)
            return
    if run:
        wake(db, run)


def _task_failure(db, project, run, ap, decision, body, comment):
    t = db.get(Task, ap.task_id)
    option = str(body.get("option") or ("retry" if decision == "approve" else "cancel"))
    if option == "retry":
        t.max_retries = t.retry_count + 1
        t.retry_count = t.retry_count  # keep history
        transition_task(t, "ready")
        ap.status = "approved"
    elif option == "skip":
        transition_task(t, "skipped")
        ap.status = "approved"
        events.emit(db, project.id, "task_skipped", f"The client skipped “{t.title}”", run_id=run.id, task_id=t.id,
                    agent_id=t.assigned_agent_id, agent_status="idle" if t.assigned_agent_id else None)
    elif option == "cancel":
        ap.status = "rejected"
        request_control(db, run, "cancel")
        return
    else:
        raise DecisionError("option must be retry, skip or cancel")
    wake(db, run)


def _requirement_change(db, project, run, ap, decision, body, comment):
    from .. import requirements

    change_ref = ap.payload.get("change_ref")
    if change_ref:
        # The blanket "predates this change" notes were provisional; once the client decides the change,
        # precise lineage (recomputed below) is authoritative.
        for a in db.scalars(select(Artifact).where(Artifact.project_id == project.id,
                                                   Artifact.stale_reason == f"[note] predates requirement change {change_ref}; request a revision")):
            a.stale, a.stale_reason = False, ""
    if decision != "approve":
        ap.status = "rejected"
        from .. import traceability

        traceability.refresh(db, project.id)
        return
    ap.status = "approved"
    change_id = ap.payload.get("change_requirement_id")
    change = db.get(ProjectRequirement, uuid.UUID(change_id)) if change_id else None
    sup = body.get("supersede_ids")
    if sup is None:  # default: the proposal shown on the card
        sup = [c["id"] for c in ap.payload.get("candidates", []) if c.get("proposed")]
    if change is not None and sup:
        done = requirements.supersede(db, project.id, list(sup), change, run_id=run.id if run else None)
        ap.payload = {**ap.payload, "superseded_refs": [r.ref for r in done]}
    from .. import traceability

    superseded_ids = {uuid.UUID(c) for c in ap.payload.get("superseded_ids", [])}
    if change is not None and sup:
        superseded_ids |= {r.id for r in db.scalars(select(ProjectRequirement).where(
            ProjectRequirement.superseded_by_id == change.id))}
    ap.payload = {**ap.payload, "superseded_ids": sorted(str(i) for i in superseded_ids)}
    if run is None or run.status in RUN_TERMINAL:
        traceability.refresh(db, project.id)  # delivered documents derived from retired rules become stale
        return
    imp = traceability.impact(db, run.id, superseded_ids) if superseded_ids else {"tasks": []}
    selected = {str(t) for t in (body.get("task_ids") or [])}
    note = f"Update for the requirement change {change.ref + ': ' if change else ''}{ap.payload.get('change', '')}"
    applied = {"reworked": [], "relinked": [], "waiting": [], "preserved": [], "not_reworked": []}
    reworks: dict[str, Task] = {}
    for e in imp["tasks"]:
        t = db.get(Task, uuid.UUID(e["id"]))
        if e["action"] in ("relink", "relink_wait") and change is not None:
            traceability.relink_superseded(db, t, superseded_ids, change)  # not started: uses the new baseline
            applied["relinked"].append(t.title)
        elif e["action"] == "preserve":
            applied["preserved"].append(t.title)
    for tid in selected:
        t = db.get(Task, uuid.UUID(tid))
        if t is None or t.run_id != run.id or t.status in ("cancelled", "skipped", "failed"):
            continue
        # In-flight tasks finish first (they started with the old requirement), then get reworked.
        reworks[tid] = create_rework(db, run, t, note, after_original=t.status != "completed",
                                     change=change, superseded=superseded_ids)
        applied["reworked"].append(t.title)
    for e in imp["tasks"]:
        if e["action"] in ("rework", "rework_after") and e["id"] not in selected:
            applied["not_reworked"].append(e["title"])  # its outputs stay stale; the delivery gate will ask again
        # Ordering: a not-started task, or a rework, never runs before the rework of its upstream work,
        # so it cannot consume a stale input.
        waiter = None
        if e["action"] in ("wait", "relink_wait"):
            waiter = db.get(Task, uuid.UUID(e["id"]))
        elif e["id"] in reworks:
            waiter = reworks[e["id"]]
        if waiter is not None:
            for up in e["upstream"]:
                rw = reworks.get(up)
                if rw is not None and rw.id != waiter.id:
                    db.add(TaskDependency(task_id=waiter.id, depends_on_task_id=rw.id))
                    if waiter.status == "ready":
                        transition_task(waiter, "pending")
                    applied["waiting"].append(waiter.title)
    db.flush()
    traceability.refresh(db, project.id)
    ap.payload = {**ap.payload, "applied": applied}
    wake(db, run)


def _stale_artifacts(db, project, run, ap, decision, body, comment):
    """Remediate a blocked delivery: targeted rework, explicit client confirmation, or cancel."""
    from .. import traceability

    option = str(body.get("option") or ("rework" if decision == "approve" else "cancel"))
    if option == "cancel" or decision == "reject":
        ap.status = "rejected"
        request_control(db, run, "cancel")
        return
    chosen = {str(a) for a in (body.get("artifact_ids") or [b["artifact_id"] for b in ap.payload.get("artifacts", [])])}
    if option == "confirm":
        for b in ap.payload.get("artifacts", []):
            if b["artifact_id"] in chosen:
                a = db.get(Artifact, uuid.UUID(b["artifact_id"]))
                if a is not None:
                    a.confirmed_version = a.current_version
                    events.emit(db, project.id, "artifact_confirmed_current",
                                f"Client confirmed “{a.name}” v{a.current_version} as current", run_id=run.id)
    elif option == "rework":
        sup = {r.id for r in db.scalars(select(ProjectRequirement).where(ProjectRequirement.project_id == project.id,
                                                                         ProjectRequirement.superseded_by_id.is_not(None)))}
        for b in ap.payload.get("artifacts", []):
            if b["artifact_id"] in chosen and b.get("producing_task_id"):
                t = db.get(Task, uuid.UUID(b["producing_task_id"]))
                if t is not None and t.assigned_agent_id:
                    create_rework(db, run, t, f"Bring “{b['name']}” up to date with the current requirements ({b['reason']}).",
                                  superseded=sup)
    else:
        raise DecisionError("option must be rework, confirm or cancel")
    ap.status = "approved"
    traceability.refresh(db, project.id)
    wake(db, run)


def _scope_change(db, project, run, ap, decision, body, comment):
    if decision != "approve":
        ap.status = "rejected"
        return
    ap.status = "approved"
    if run is not None and run.status not in RUN_TERMINAL:
        request_control(db, run, "cancel")
    ap.payload = {**ap.payload, "replan_requested": True}


def _acceptance(db, project, run, ap, decision, body, comment):
    arts = [db.get(Artifact, uuid.UUID(a)) for a in ap.artifact_ids]
    if decision == "approve":
        ap.status = "approved"
        for a in arts:
            if a:
                a.acceptance_status = "accepted"
        events.emit(db, project.id, "deliverables_accepted", "The client accepted the deliverables", run_id=run.id)
    elif decision in ("revise", "reject"):
        if not comment.strip():
            raise DecisionError("Describe the revision you need")
        ap.status = "revised"
        for a in arts:
            if a:
                a.acceptance_status = "revision_requested"
        start_run(db, project, kind="revision", feedback=comment)
    else:
        raise DecisionError("Use approve or revise")


# -- interventions ---------------------------------------------------------------------
def request_control(db: Session, run: ProjectRun, action: str) -> None:
    if run.status in RUN_TERMINAL:
        raise DecisionError("The run has already finished")
    project = db.get(Project, run.project_id)
    if action == "pause":
        if run.status in ("paused", "pausing"):
            return
        if run.status in ("running", "planning"):
            run.requested_action = "pause"
            transition_run(run, "pausing")
        elif run.status == "blocked":
            transition_run(run, "paused")  # nothing is in flight while blocked
        else:
            raise DecisionError("Nothing to pause while the plan awaits your approval")
        events.emit(db, project.id, "pause_requested", "The client asked the team to pause", run_id=run.id)
    elif action == "cancel":
        run.requested_action = "cancel"
        events.emit(db, project.id, "cancel_requested", "The client cancelled the run", run_id=run.id)
    elif action == "resume":
        if run.status not in ("paused", "pausing"):
            raise DecisionError("The run is not paused")
        run.requested_action = None
        target = "planning" if run.phase == "planning" else "running"
        transition_run(run, target)
        for t in services.run_tasks(db, run.id):
            if t.status == "paused":
                transition_task(t, "ready")
        events.emit(db, project.id, "run_resumed", "The client resumed the run", run_id=run.id)
    else:
        raise DecisionError("Unknown action")
    sync_project_status(project, run)


def create_rework(db: Session, run: ProjectRun, original: Task, note: str, after_original: bool = False,
                  change: Optional[ProjectRequirement] = None, superseded: Optional[set] = None) -> Task:
    key = "fb:" + hashlib.sha256(f"{original.id}|{note}".encode()).hexdigest()[:40]
    existing = db.scalar(select(Task).where(Task.run_id == run.id, Task.idempotency_key == key))
    if existing:
        return existing
    agent = db.get(ProjectAgent, original.assigned_agent_id)
    t = Task(project_id=run.project_id, run_id=run.id, assigned_agent_id=agent.id, kind="rework",
             title=f"Rework: {original.title}", objective=f"Revise your earlier deliverable. {note}",
             acceptance_criteria=["The client's feedback is fully addressed"], input_refs=original.output_artifact_ids,
             allowed_tools=sorted(services.agent_permissions(db, agent)), idempotency_key=key,
             status="pending" if after_original else "ready",
             context_notes=[note], max_model_calls=agent.max_calls_per_task, sort_order=original.sort_order)
    db.add(t)
    if after_original:
        db.flush()
        db.add(TaskDependency(task_id=t.id, depends_on_task_id=original.id))
    db.flush()
    # Traceability: the rework implements the original's requirements, mapped to their current versions.
    from .. import traceability

    orig_ids = [l.requirement_id for l in traceability.links(db, original.id, active_only=False)
                if l.active or (superseded and l.requirement_id in superseded)]
    req_ids = set(traceability.current_requirement_ids(db, orig_ids))
    if change is not None and (not orig_ids or (superseded and set(orig_ids) & superseded)):
        req_ids.add(change.id)
    traceability.link(db, t, req_ids, "inherited")
    for aid in original.output_artifact_ids:
        a = db.get(Artifact, uuid.UUID(aid))
        if a and not a.stale:
            a.stale, a.stale_reason = True, f"[note] rework requested: {note[:300]}"
    db.flush()
    events.emit(db, run.project_id, "task_assigned", f"{agent.display_name} was asked to rework “{original.title}”",
                run_id=run.id, agent_id=agent.id, task_id=t.id, agent_status="assigned", data={"feedback": note[:500]})
    return t
