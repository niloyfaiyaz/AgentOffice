"""The single gateway for model calls: budget check -> reservation -> provider call with
bounded retries -> usage record + activity event."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Optional, Union

from sqlalchemy import update
from sqlalchemy.orm import Session

from .. import events, pricing, services
from ..models import Project, ProjectAgent, ProjectRun, Task, UsageRecord, new_id
from ..providers.base import CompletionResult, ProviderError, ToolSpec
from ..providers.registry import get_provider
from . import budget

MAX_ATTEMPTS = 3


@dataclass
class Blocked:
    block: budget.BudgetBlock


async def call_model(
    db: Session, *, project: Project, run: Optional[ProjectRun], agent: ProjectAgent, task: Optional[Task],
    purpose: str, system: str, messages: list[dict[str, Any]], tools: list[ToolSpec], provider=None,
) -> Union[CompletionResult, Blocked]:
    if not agent.provider or not agent.model_id:
        raise ProviderError("not_configured", f"{agent.display_name} has no AI model assigned.")
    provider = provider or get_provider(agent.provider)
    mc = services.model_config(db, agent.provider, agent.model_id)
    # Everything sent counts toward the input bound: system prompt, messages AND tool schemas.
    prompt_chars = (len(system) + sum(len(str(m.get("content"))) for m in messages)
                    + sum(len(t.name) + len(t.description) + len(json.dumps(t.input_schema)) for t in tools))
    web_searches = sum(int((t.native or {}).get("max_uses", 0)) for t in tools if t.native)
    max_tokens = agent.max_output_tokens
    if mc and mc.max_output_tokens:
        max_tokens = min(max_tokens, mc.max_output_tokens)
    plan = budget.plan_call(db, project=project, run=run, agent=agent, task=task, mc=mc, prompt_chars=prompt_chars,
                            max_tokens=max_tokens, web_searches=web_searches, is_test=provider.is_test_provider)
    if isinstance(plan, budget.BudgetBlock):
        return Blocked(plan)
    max_tokens, estimate = plan.max_tokens, plan.estimate
    if plan.reduced_from is not None:
        events.emit(db, project.id, "budget_capped",
                    f"{agent.display_name}'s output allowance for this call was reduced from {plan.reduced_from} to "
                    f"{max_tokens} tokens to stay within {plan.limit}",
                    run_id=run.id if run else None, agent_id=agent.id, task_id=task.id if task else None,
                    data={"from": plan.reduced_from, "to": max_tokens, "worst_case_usd": str(estimate)})
    if run is not None:
        # Count the call against the run before making it (atomic increment).
        db.execute(update(ProjectRun).where(ProjectRun.id == run.id).values(model_calls=ProjectRun.model_calls + 1))
    budget.reserve(run.id if run else None, estimate, agent.id)
    db.commit()
    try:
        last: Optional[ProviderError] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                result = await provider.complete(model=agent.model_id, system=system, messages=messages, tools=tools,
                                                 max_tokens=max_tokens, effort=agent.effort)
                break
            except ProviderError as e:
                last = e
                events.emit(db, project.id, "provider_error", f"{agent.display_name}: {e.user_message()}",
                            run_id=run.id if run else None, agent_id=agent.id, task_id=task.id if task else None,
                            data={"kind": e.kind, "status": e.status, "attempt": attempt, "retryable": e.retryable})
                db.commit()
                if not e.retryable or attempt == MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(2 ** attempt)
        else:  # pragma: no cover
            raise last or ProviderError("server", "unknown")
    finally:
        budget.release(run.id if run else None, estimate, agent.id)
    cost = pricing.cost_of(mc, result.usage)
    if cost is not None and estimate is not None and cost > estimate and not provider.is_test_provider:
        # Transparency: the worst-case bound was wrong (e.g. the input heuristic under-counted).
        events.emit(db, project.id, "budget_estimate_exceeded",
                    f"A call cost ${cost:.4f}, above its worst-case estimate of ${estimate:.4f}",
                    run_id=run.id if run else None, agent_id=agent.id, task_id=task.id if task else None)
    rec = UsageRecord(
        id=new_id(), project_id=project.id, run_id=run.id if run else None, task_id=task.id if task else None, agent_id=agent.id,
        provider=agent.provider, model_id=agent.model_id, purpose=purpose,
        input_tokens=result.usage.input_tokens, output_tokens=result.usage.output_tokens,
        cache_read_tokens=result.usage.cache_read_tokens, cache_write_tokens=result.usage.cache_write_tokens,
        other_usage={**result.usage.other, "served_model": result.served_model},
        price_snapshot=pricing.price_snapshot(mc), estimated_cost_usd=cost if not provider.is_test_provider else None,
        is_test_provider=provider.is_test_provider,
    )
    db.add(rec)
    cost_txt = "test provider, no cost" if provider.is_test_provider else (f"≈${cost:.4f}" if cost is not None else "cost unknown (unpriced)")
    events.emit(db, project.id, "model_call",
                f"{agent.display_name} called {agent.model_id}: {result.usage.input_tokens} in / {result.usage.output_tokens} out ({cost_txt})",
                run_id=run.id if run else None, agent_id=agent.id, task_id=task.id if task else None,
                data={"usage_id": str(rec.id), "input_tokens": result.usage.input_tokens,
                      "output_tokens": result.usage.output_tokens, "cost": str(cost) if cost is not None else None,
                      "purpose": purpose, "stop_reason": result.stop_reason})
    db.commit()
    return result
