"""Project-journey API: conversational discovery, the structured brief, the recommended team,
plan cost estimates and the cross-project inbox. Everything here reuses the existing records
(projects, requirement items, agents, approvals, events); nothing duplicates orchestration."""
from __future__ import annotations

import statistics
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import catalog, discovery, events, services
from ..db import get_db
from ..models import (
    AgentDefinition, AgentEvent, ApprovalRequest, Message, Project, ProjectAgent, ProjectRun, Task, ToolPermission,
    UsageRecord,
)
from ..pricing import is_priced
from . import serialize as ser

router = APIRouter()
ORIGINS = {"user", "acceptance_test", "scripted_test"}


def _project(db: Session, pid: str) -> Project:
    try:
        p = db.get(Project, uuid.UUID(pid))
    except ValueError:
        p = None
    if p is None:
        raise HTTPException(404, "Project not found")
    return p


def _messages(db: Session, p: Project, channel: str) -> list[dict]:
    rows = db.scalars(select(Message).where(Message.project_id == p.id, Message.channel == channel)
                      .order_by(Message.created_at).limit(500))
    return [{"id": str(m.id), "sender": m.sender, "agent_id": str(m.agent_id) if m.agent_id else None,
             "content": m.content, "data": m.data, "created_at": m.created_at.isoformat()} for m in rows]


def _discovery_view(db: Session, p: Project) -> dict:
    pm = services.orchestrator(db, p.id)
    return {"project": ser.project(p), "brief": discovery.brief_of(p), "messages": _messages(db, p, "discovery"),
            "pm": ser.agent(db, pm) if pm else None,
            "provider_ready": bool(pm and discovery.provider_ready(db, pm)),
            "usable_providers": discovery.usable_providers(db)}


# -- discovery -----------------------------------------------------------------------------
class DiscoveryStart(BaseModel):
    text: str = Field(min_length=3, max_length=20000)
    template_key: Optional[str] = None
    origin: str = "user"


@router.post("/discovery")
def start_discovery(body: DiscoveryStart, db: Session = Depends(get_db)):
    """Step 1: a free-text idea becomes a draft project with a project manager. The first PM turn
    is requested separately (after any attachments are uploaded)."""
    if body.origin not in ORIGINS:
        raise HTTPException(422, "Unknown origin")
    words = body.text.strip().split()
    provisional = " ".join(words[:6]) + ("…" if len(words) > 6 else "")
    p = Project(name=services.unique_name(db, provisional) if body.origin == "user" else provisional,
                objective=body.text.strip(), template_key=body.template_key, status="draft", origin=body.origin,
                brief=discovery.empty_brief())
    db.add(p)
    db.flush()
    services.get_budget(db, p.id)
    discovery.ensure_pm(db, p)
    db.add(Message(project_id=p.id, sender="user", channel="discovery", intent="discovery", content=body.text.strip()))
    events.emit(db, p.id, "project_created", f"Project “{p.name}” started from your description")
    db.commit()
    return _discovery_view(db, p)


@router.get("/projects/{pid}/discovery")
def get_discovery(pid: str, db: Session = Depends(get_db)):
    return _discovery_view(db, _project(db, pid))


class TurnIn(BaseModel):
    content: Optional[str] = Field(default=None, max_length=20000)


@router.post("/projects/{pid}/discovery/turn")
async def discovery_turn(pid: str, body: TurnIn, db: Session = Depends(get_db)):
    """Step 2: the client's reply (optional on the first turn) and one PM turn."""
    p = _project(db, pid)
    if discovery.brief_of(p).get("status") == "confirmed":
        raise HTTPException(409, "The brief is already confirmed; edit it directly or message the project manager")
    if body.content and body.content.strip():
        db.add(Message(project_id=p.id, sender="user", channel="discovery", intent="discovery", content=body.content.strip()))
        db.flush()
    await discovery.run_turn(db, p)
    db.commit()
    return _discovery_view(db, p)


@router.put("/projects/{pid}/brief")
def edit_brief(pid: str, body: dict[str, Any], db: Session = Depends(get_db)):
    """Step 3: the client edits any section. Edited items become ``client_edited``."""
    p = _project(db, pid)
    b = discovery.apply_client_edit(discovery.brief_of(p), body)
    discovery._history(b, "client", "You edited the brief")
    p.brief = b
    if b.get("status") == "confirmed":
        try:
            discovery.confirm(db, p)  # keep the requirement baseline in step (versioned, never resurrected)
        except services.NameTaken as e:
            raise HTTPException(409, str(e)) from e
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    db.commit()
    return _discovery_view(db, p)


@router.post("/projects/{pid}/brief/confirm")
def confirm_brief(pid: str, db: Session = Depends(get_db)):
    p = _project(db, pid)
    try:
        discovery.confirm(db, p)
    except services.NameTaken as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return _discovery_view(db, p)


# -- team ----------------------------------------------------------------------------------
def typical_task_cost(db: Session, provider: str, model_id: str) -> Optional[dict]:
    """Median recorded cost of a completed work task on this model (no estimate below 3 samples)."""
    rows = db.execute(
        select(UsageRecord.task_id, func.sum(UsageRecord.estimated_cost_usd))
        .join(Task, Task.id == UsageRecord.task_id)
        .where(UsageRecord.provider == provider, UsageRecord.model_id == model_id,
               UsageRecord.is_test_provider.is_(False), UsageRecord.estimated_cost_usd.is_not(None),
               Task.kind.in_(["work", "subtask", "rework", "qa", "consolidation"]), Task.status == "completed")
        .group_by(UsageRecord.task_id)).all()
    vals = [float(v) for _, v in rows if v is not None]
    if len(vals) < 3:
        return None
    return {"usd": round(statistics.median(vals), 4), "samples": len(vals)}


def _model_info(db: Session, provider: str, model_id: str) -> dict:
    mc = services.model_config(db, provider, model_id)
    return {"provider": provider, "model_id": model_id, "display_name": mc.display_name if mc else model_id,
            "cost_tier": catalog.cost_tier(mc.input_price_per_mtok, mc.output_price_per_mtok) if mc else "unpriced",
            "priced": is_priced(mc),
            "input_price_per_mtok": float(mc.input_price_per_mtok) if mc and mc.input_price_per_mtok is not None else None,
            "output_price_per_mtok": float(mc.output_price_per_mtok) if mc and mc.output_price_per_mtok is not None else None,
            "typical_task": typical_task_cost(db, provider, model_id),
            "ready": provider in discovery.usable_providers(db)}


def recommended_team(db: Session, p: Project) -> dict:
    """Step 4: the smallest team for the brief. Source order: the PM's recommendation from the brief
    (AI), the template, then a labelled keyword heuristic."""
    from .routes import recommend_team as legacy

    b = discovery.brief_of(p)
    hired = {a.role_key: a for a in services.team(db, p.id)}
    defs = {d.role_key: d for d in db.scalars(select(AgentDefinition).where(AgentDefinition.is_builtin.is_(True)))}
    roles: list[dict] = [{"role_key": "project_manager", "responsibility": "Plans the work, coordinates the team, "
                          "consolidates the delivery and is your main contact.", "reason": "Every project needs one."}]
    if b.get("recommended_team"):
        basis = ("your project manager's recommendation from the brief" if b.get("method") == "ai"
                 else "scripted test recommendation (not AI)" if b.get("method") == "scripted-test" else "the brief")
        roles += [r for r in b["recommended_team"] if r["role_key"] != "project_manager"]
    else:
        lg = legacy(str(p.id), db)
        basis = lg["basis"]
        roles += [{"role_key": r["role_key"], "responsibility": r["definition"]["description"], "reason": r["reason"]}
                  for r in lg["roles"] if r["role_key"] != "project_manager"]
    out = []
    for r in roles:
        d = defs.get(r["role_key"])
        if d is None:
            continue
        a = hired.get(r["role_key"])
        provider, model = (a.provider, a.model_id) if a else discovery.default_model(db, r["role_key"])
        out.append({"role_key": r["role_key"], "name": a.display_name if a else d.name, "role": d.role,
                    "avatar": a.avatar if a else d.avatar, "responsibility": r["responsibility"], "reason": r["reason"],
                    "tools": ser.agent(db, a)["tools"] if a else [t.tool_key for t in db.scalars(
                        select(ToolPermission).where(ToolPermission.agent_definition_id == d.id))],
                    "model": _model_info(db, provider, model), "hired": a is not None,
                    "agent_id": str(a.id) if a else None})
    return {"basis": basis, "roles": out}


@router.get("/projects/{pid}/team/recommended")
def get_recommended_team(pid: str, db: Session = Depends(get_db)):
    return recommended_team(db, _project(db, pid))


class HireIn(BaseModel):
    role_keys: list[str]


@router.post("/projects/{pid}/team/hire")
def hire_recommended(pid: str, body: HireIn, db: Session = Depends(get_db)):
    """Accept the recommendation: hire each listed role not already on the team, with default models."""
    p = _project(db, pid)
    have = {a.role_key for a in services.team(db, p.id)}
    valid = {r["role_key"] for r in catalog.DEFAULT_ROLES}
    for rk in dict.fromkeys(body.role_keys):
        if rk not in valid:
            raise HTTPException(422, f"Unknown role {rk}")
        if rk not in have:
            if len(services.team(db, p.id)) >= 12:
                raise HTTPException(422, "A team can have at most 12 agents")
            discovery.hire_role(db, p, rk)
            have.add(rk)
    db.commit()
    return recommended_team(db, p)


# -- plan estimate ---------------------------------------------------------------------------
@router.get("/projects/{pid}/estimate")
def plan_estimate(pid: str, db: Session = Depends(get_db)):
    """An ESTIMATE of the pending plan's cost from this install's own history: the median recorded
    cost of a completed task on each assigned model. Reported as unavailable rather than guessed when
    a model has fewer than 3 completed tasks on record."""
    p = _project(db, pid)
    ap = db.scalar(select(ApprovalRequest).where(ApprovalRequest.project_id == p.id, ApprovalRequest.kind == "sow",
                                                 ApprovalRequest.status == "pending").order_by(ApprovalRequest.created_at.desc()))
    team = services.team(db, p.id)
    if ap is None:
        return {"available": False, "reason": "no plan to estimate yet", "lines": []}
    plan = ap.payload.get("plan") or {}

    def agent_for(name: str) -> Optional[ProjectAgent]:
        n = (name or "").lower()
        return next((a for a in team if n in (a.display_name.lower(), a.role.lower(), a.role_key.lower())), None)

    lines, missing = [], set()
    steps = [(t.get("title", ""), agent_for(t.get("assignee", ""))) for t in plan.get("tasks", [])]
    qa = next((a for a in team if a.role_key == "qa_reviewer"), None)
    if plan.get("qa_review", True) and qa:
        steps.append(("QA review", qa))
    pm = services.orchestrator(db, p.id)
    if pm and len(steps) > 1:
        steps.append(("Consolidate final delivery", pm))
    total = 0.0
    for title, a in steps:
        tc = typical_task_cost(db, a.provider, a.model_id) if a else None
        lines.append({"title": title, "agent": a.display_name if a else None,
                      "model": a.model_id if a else None, "usd": tc["usd"] if tc else None,
                      "samples": tc["samples"] if tc else 0})
        if tc:
            total += tc["usd"]
        elif a:
            missing.add(a.model_id)
    return {"available": bool(lines) and not missing, "partial": bool(missing) and total > 0,
            "total_usd": round(total, 4), "missing_models": sorted(missing), "lines": lines,
            "basis": "median recorded cost of a completed task on each model in this installation (estimate)"}


# -- inbox -----------------------------------------------------------------------------------
CATEGORY = {
    "clarification": "Question", "sow": "Plan approval", "tool_authorization": "Permission request",
    "budget": "Budget decision", "task_failure": "Failure", "requirement_change": "Change impact",
    "stale_artifacts": "Delivery blocked", "scope_change": "Scope change",
    "deliverable_acceptance": "Deliverable awaiting acceptance",
}
INFO_EVENTS = {"run_completed", "run_failed", "run_cancelled", "brief_confirmed", "requirement_superseded",
               "budget_warning", "review_limit", "project_renamed", "plan_approved", "deliverables_accepted",
               "delivery_blocked", "review_submitted"}


@router.get("/inbox")
def inbox(include_test: bool = False, db: Session = Depends(get_db)):
    """Actionable items across projects (each is the ONE underlying decision record), separated from
    informational notices. Routine agent events are not included."""
    q = select(Project).where(Project.archived.is_(False))
    if not include_test:
        q = q.where(Project.origin == "user")
    projects = {p.id: p for p in db.scalars(q)}
    if not projects:
        return {"actions": [], "notices": []}
    names = {a.id: a.display_name for a in db.scalars(select(ProjectAgent).where(ProjectAgent.project_id.in_(projects)))}
    actions = []
    for ap in db.scalars(select(ApprovalRequest).where(ApprovalRequest.project_id.in_(projects),
                                                       ApprovalRequest.status == "pending").order_by(ApprovalRequest.created_at)):
        actions.append({"id": str(ap.id), "type": "approval", "kind": ap.kind, "category": CATEGORY.get(ap.kind, ap.kind),
                        "title": ap.title, "project_id": str(ap.project_id), "project_name": projects[ap.project_id].name,
                        "agent_id": str(ap.agent_id) if ap.agent_id else None, "agent_name": names.get(ap.agent_id),
                        "task_id": str(ap.task_id) if ap.task_id else None, "created_at": ap.created_at.isoformat()})
    for p in projects.values():
        b = discovery.brief_of(p)
        if p.status == "draft" and b.get("status") in ("discovering", "ready", "manual") and p.brief:
            actions.append({"id": f"brief-{p.id}", "type": "brief", "kind": "brief",
                            "category": "Answer questions" if b.get("questions") else "Review the brief",
                            "title": (f"{len(b['questions'])} question(s) from your project manager" if b.get("questions")
                                      else "Review and confirm the project brief"),
                            "project_id": str(p.id), "project_name": p.name, "agent_id": None, "agent_name": None,
                            "task_id": None, "created_at": p.updated_at.isoformat()})
    for run in db.scalars(select(ProjectRun).where(ProjectRun.project_id.in_(projects), ProjectRun.status == "failed")):
        latest = services.latest_run(db, run.project_id)
        if latest and latest.id == run.id:
            actions.append({"id": f"run-{run.id}", "type": "run_failed", "kind": "run_failed", "category": "Failure",
                            "title": f"Run {run.run_number} failed: {run.error[:160]}", "project_id": str(run.project_id),
                            "project_name": projects[run.project_id].name, "agent_id": None, "agent_name": None,
                            "task_id": None, "created_at": (run.finished_at or run.created_at).isoformat()})
    notices = [{**events.event_to_dict(e), "project_name": projects[e.project_id].name}
               for e in db.scalars(select(AgentEvent).where(AgentEvent.project_id.in_(projects),
                                                            AgentEvent.type.in_(INFO_EVENTS))
                                   .order_by(AgentEvent.seq.desc()).limit(30))]
    return {"actions": actions, "notices": notices}
