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
_reserved: dict[uuid.UUID, Decimal] = {}  # run_id -> worst-case cost of in-flight calls
_reserved_agent: dict[uuid.UUID, Decimal] = {}  # agent_id -> worst-case cost of its in-flight calls
# A call is only made if at least this much output fits in the remaining budget (or the agent's
# whole allowance, if that is smaller); below it the client is asked for a budget decision.
MIN_OUTPUT_TOKENS = 2000


@dataclass
class BudgetBlock:
    reason: str  # max_calls | unpriced | project_budget | agent_limit | task_budget | approval_threshold
    detail: str


def reserve(run_id: Optional[uuid.UUID], amount: Optional[Decimal], agent_id: Optional[uuid.UUID] = None) -> None:
    if amount:
        with _lock:
            if run_id is not None:
                _reserved[run_id] = _reserved.get(run_id, Decimal(0)) + amount
            if agent_id is not None:
                _reserved_agent[agent_id] = _reserved_agent.get(agent_id, Decimal(0)) + amount


def release(run_id: Optional[uuid.UUID], amount: Optional[Decimal], agent_id: Optional[uuid.UUID] = None) -> None:
    if amount:
        with _lock:
            if run_id is not None:
                _reserved[run_id] = max(_reserved.get(run_id, Decimal(0)) - amount, Decimal(0))
            if agent_id is not None:
                _reserved_agent[agent_id] = max(_reserved_agent.get(agent_id, Decimal(0)) - amount, Decimal(0))


def reserved(run_id: uuid.UUID) -> Decimal:
    with _lock:
        return _reserved.get(run_id, Decimal(0))


def reserved_for_agent(agent_id: uuid.UUID) -> Decimal:
    with _lock:
        return _reserved_agent.get(agent_id, Decimal(0))


@dataclass
class Allowance:
    """The output allowance a call may use and its worst-case cost (what gets reserved)."""
    max_tokens: int
    estimate: Optional[Decimal]
    reduced_from: Optional[int] = None
    limit: str = ""


def plan_call(db: Session, *, project: Project, run: Optional[ProjectRun], agent: ProjectAgent, task: Optional[Task],
              mc: Optional[ModelConfiguration], prompt_chars: int, max_tokens: int, web_searches: int,
              is_test: bool):
    """Decide whether a call may run and with which output allowance.

    Hard limits (project budget, agent limit, task allocation) are guaranteed: the call's worst
    case - input bound plus the output allowance actually sent to the provider - plus everything
    already spent or reserved never exceeds any limit. When the full allowance does not fit, the
    allowance is reduced to what fits instead of blocking; the call is blocked only when fewer than
    MIN_OUTPUT_TOKENS would fit. Returns an ``Allowance`` or a ``BudgetBlock``."""
    policy = services.get_budget(db, project.id)
    if run is not None:
        db.refresh(run)
        if run.model_calls >= policy.max_model_calls_per_run:
            return BudgetBlock("max_calls", f"The run reached its limit of {policy.max_model_calls_per_run} model calls.")
    worst = pricing.estimate_call_cost(mc, prompt_chars, max_tokens, web_searches)
    limits_set = any(x is not None for x in (policy.budget_usd, agent.spend_limit_usd, task.budget_usd if task else None,
                                             policy.approval_threshold_usd))
    if worst is None:
        if limits_set and not is_test:
            return BudgetBlock("unpriced", f"Pricing for {agent.provider}/{agent.model_id} is not configured, so "
                                           "spending limits cannot be enforced. Enter prices on the Costs page.")
        return Allowance(max_tokens, None)
    spent = services.project_spend(db, project.id)
    inflight = reserved(run.id) if run is not None else Decimal(0)
    # Headroom under every hard limit; the tightest one binds.
    headrooms: list[tuple[str, Decimal, str]] = []
    if policy.budget_usd is not None:
        headrooms.append(("project_budget", policy.budget_usd - spent - inflight,
                          f"the project budget of ${policy.budget_usd:.2f} (spent ${spent:.4f}, reserved for calls "
                          f"in progress ${inflight:.4f})"))
    if agent.spend_limit_usd is not None:
        a_spent = services.agent_spend(db, agent.id)
        a_res = reserved_for_agent(agent.id)
        headrooms.append(("agent_limit", agent.spend_limit_usd - a_spent - a_res,
                          f"{agent.display_name}'s ${agent.spend_limit_usd:.2f} limit (spent ${a_spent:.4f}, "
                          f"reserved ${a_res:.4f})"))
    if task is not None and task.budget_usd is not None:
        t_spent = services.task_spend(db, task.id)
        headrooms.append(("task_budget", task.budget_usd - t_spent,
                          f"the ${task.budget_usd:.2f} allocation of “{task.title}” (spent ${t_spent:.4f})"))
    allowance = Allowance(max_tokens, worst)
    if headrooms:
        kind, room, desc = min(headrooms, key=lambda h: h[1])
        if worst > room:
            fit = min(pricing.affordable_output_tokens(mc, room, prompt_chars, web_searches), max_tokens)
            floor = min(MIN_OUTPUT_TOKENS, max_tokens)
            if fit < floor:
                return BudgetBlock(kind, f"Not enough budget left for another call under {desc}: at least "
                                         f"{floor} output tokens must fit (worst case ${pricing.estimate_call_cost(mc, prompt_chars, floor, web_searches):.4f}), "
                                         f"but only ${max(room, Decimal(0)):.4f} remains. Spend is estimated from configured prices.")
            est = pricing.estimate_call_cost(mc, prompt_chars, fit, web_searches)
            while est > room and fit > floor:  # rounding guard: the worst case must fit exactly
                fit -= 1
                est = pricing.estimate_call_cost(mc, prompt_chars, fit, web_searches)
            if est > room:
                return BudgetBlock(kind, f"Not enough budget left for another call under {desc}.")
            allowance = Allowance(fit, est, reduced_from=max_tokens, limit=desc)
    est = allowance.estimate
    if (run is not None and policy.approval_threshold_usd is not None and not policy.approval_threshold_acknowledged
            and spent + inflight + est > policy.approval_threshold_usd):
        return BudgetBlock("approval_threshold", f"Spending is about to pass your approval threshold of "
                                                 f"${policy.approval_threshold_usd:.2f}.")
    if (run is not None and policy.budget_usd and not policy.warning_emitted
            and spent >= policy.budget_usd * Decimal(policy.warning_threshold_pct) / 100):
        policy.warning_emitted = True
        events.emit(db, project.id, "budget_warning",
                    f"Estimated spend ${spent:.4f} has reached {policy.warning_threshold_pct}% of the ${policy.budget_usd:.2f} budget",
                    run_id=run.id, data={"spent": str(spent), "budget": str(policy.budget_usd)})
    return allowance


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
