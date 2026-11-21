"""Application-enforced spending controls, evaluated before every model call.

These are AgentOffice limits, not provider billing caps: estimates are computed from
configured prices, and providers bill actual usage independently.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events, pricing, services
from ..models import ApprovalRequest, ModelConfiguration, Project, ProjectAgent, ProjectRun, Task

_lock = threading.Lock()
_reserved: dict[uuid.UUID, Decimal] = {}  # run_id -> estimated cost of in-flight calls


@dataclass
class BudgetBlock:
    reason: str  # max_calls | unpriced | project_budget | agent_limit | task_budget | approval_threshold
    detail: str


def reserve(run_id: uuid.UUID, amount: Optional[Decimal]) -> None:
    if amount:
        with _lock:
            _reserved[run_id] = _reserved.get(run_id, Decimal(0)) + amount


def release(run_id: uuid.UUID, amount: Optional[Decimal]) -> None:
    if amount:
        with _lock:
            _reserved[run_id] = max(_reserved.get(run_id, Decimal(0)) - amount, Decimal(0))


def reserved(run_id: uuid.UUID) -> Decimal:
    with _lock:
        return _reserved.get(run_id, Decimal(0))


def check(db: Session, *, project: Project, run: ProjectRun, agent: ProjectAgent, task: Optional[Task],
          mc: Optional[ModelConfiguration], estimate: Optional[Decimal], is_test: bool) -> Optional[BudgetBlock]:
    policy = services.get_budget(db, project.id)
    db.refresh(run)
    if run.model_calls >= policy.max_model_calls_per_run:
        return BudgetBlock("max_calls", f"The run reached its limit of {policy.max_model_calls_per_run} model calls.")
    limits_set = any(x is not None for x in (policy.budget_usd, agent.spend_limit_usd, task.budget_usd if task else None,
                                             policy.approval_threshold_usd))
    if estimate is None:
        if limits_set and not is_test:
            return BudgetBlock("unpriced", f"Pricing for {agent.provider}/{agent.model_id} is not configured, so "
                                           "spending limits cannot be enforced. Enter prices on the Costs page.")
        return None
    spent = services.project_spend(db, project.id)
    inflight = reserved(run.id)
    if policy.budget_usd is not None and spent + inflight + estimate > policy.budget_usd:
        return BudgetBlock("project_budget",
                           f"Spent so far (estimated): ${spent:.4f}. Reserved for calls already in progress: ${inflight:.4f}. "
                           f"The next call could cost up to ${estimate:.4f} (worst case: its full output allowance), which "
                           f"would exceed the project budget of ${policy.budget_usd:.2f}. Reservations are released when "
                           f"calls finish; actual spend is usually well below the worst case.")
    if agent.spend_limit_usd is not None:
        a_spent = services.agent_spend(db, agent.id)
        if a_spent + estimate > agent.spend_limit_usd:
            return BudgetBlock("agent_limit", f"{agent.display_name} has spent ${a_spent:.4f}; the next call (up to "
                                              f"${estimate:.4f}) would exceed their ${agent.spend_limit_usd:.2f} limit.")
    if task is not None and task.budget_usd is not None:
        t_spent = services.task_spend(db, task.id)
        if t_spent + estimate > task.budget_usd:
            return BudgetBlock("task_budget", f"Task “{task.title}” would exceed its ${task.budget_usd:.2f} allocation.")
    if (policy.approval_threshold_usd is not None and not policy.approval_threshold_acknowledged
            and spent + inflight + estimate > policy.approval_threshold_usd):
        return BudgetBlock("approval_threshold", f"Spending is about to pass your approval threshold of "
                                                 f"${policy.approval_threshold_usd:.2f}.")
    if (policy.budget_usd and not policy.warning_emitted
            and spent >= policy.budget_usd * Decimal(policy.warning_threshold_pct) / 100):
        policy.warning_emitted = True
        events.emit(db, project.id, "budget_warning",
                    f"Estimated spend ${spent:.4f} has reached {policy.warning_threshold_pct}% of the ${policy.budget_usd:.2f} budget",
                    run_id=run.id, data={"spent": str(spent), "budget": str(policy.budget_usd)})
    return None


def check_outside_run(db: Session, *, project: Project, agent: ProjectAgent, estimate: Optional[Decimal],
                      is_test: bool) -> Optional[BudgetBlock]:
    """Limits for calls not tied to a run (PM chat, team recommendations)."""
    policy = services.get_budget(db, project.id)
    if estimate is None:
        if (policy.budget_usd is not None or agent.spend_limit_usd is not None) and not is_test:
            return BudgetBlock("unpriced", "Pricing for this model is not configured, so the budget cannot be enforced.")
        return None
    spent = services.project_spend(db, project.id)
    if policy.budget_usd is not None and spent + estimate > policy.budget_usd:
        return BudgetBlock("project_budget", f"This would exceed the project budget of ${policy.budget_usd:.2f}.")
    if agent.spend_limit_usd is not None and services.agent_spend(db, agent.id) + estimate > agent.spend_limit_usd:
        return BudgetBlock("agent_limit", f"This would exceed {agent.display_name}'s spending limit.")
    return None


def request_budget_decision(db: Session, *, project: Project, run: ProjectRun, agent: ProjectAgent,
                            task: Optional[Task], block: BudgetBlock) -> ApprovalRequest:
    """Create (or join) a pending budget approval for this run."""
    existing = db.scalar(select(ApprovalRequest).where(ApprovalRequest.run_id == run.id, ApprovalRequest.kind == "budget",
                                                       ApprovalRequest.status == "pending"))
    if existing is not None:
        ids = set(existing.payload.get("task_ids", []))
        if task is not None:
            ids.add(str(task.id))
        existing.payload = {**existing.payload, "task_ids": sorted(ids)}
        events.emit(db, project.id, "budget_blocked", block.detail, run_id=run.id, agent_id=agent.id,
                    task_id=task.id if task else None, agent_status="waiting_for_client")
        return existing
    policy = services.get_budget(db, project.id)
    return services.create_approval(
        db, project_id=project.id, run_id=run.id, kind="budget", title="Budget decision needed",
        explanation=block.detail, task_id=task.id if task else None, agent_id=agent.id,
        payload={"reason": block.reason, "task_ids": [str(task.id)] if task else [],
                 "current": {"budget_usd": str(policy.budget_usd) if policy.budget_usd is not None else None,
                             "max_model_calls_per_run": policy.max_model_calls_per_run,
                             "agent_limit_usd": str(agent.spend_limit_usd) if agent.spend_limit_usd is not None else None,
                             "approval_threshold_usd": str(policy.approval_threshold_usd) if policy.approval_threshold_usd is not None else None},
                 "agent_id": str(agent.id), "spent": str(services.project_spend(db, project.id))})
