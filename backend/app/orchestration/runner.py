"""Executes one task with its assigned agent.

The conversation is persisted after every step so a task can be suspended (client
approval, delegation, pause, budget decision) and resumed later - by this or another worker
process - with every tool call still paired with its result.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import events, services
from ..db import SessionLocal
from ..models import (
    ApprovalRequest, Message, Project, ProjectAgent, ProjectRun, Task, TaskExecution, utcnow,
)
from ..providers.base import ProviderError, text_of
from ..providers.registry import get_provider
from ..state_machine import transition_task
from ..tools import registry as toolreg
from . import budget
from .context import system_prompt, task_message
from .llm import Blocked, call_model

MAX_NUDGES = 2
NON_RETRYABLE = {"auth", "permission", "not_found", "invalid_request", "refusal", "billing", "not_configured"}


def _working_status(task: Task) -> str:
    return "reviewing" if task.kind == "qa" else "working"


def _latest_execution(db: Session, task_id: uuid.UUID) -> Optional[TaskExecution]:
    return db.scalar(select(TaskExecution).where(TaskExecution.task_id == task_id)
                     .order_by(TaskExecution.attempt.desc(), TaskExecution.started_at.desc()).limit(1))


def _resolve_waiting(db: Session, ctx: toolreg.ToolContext, waiting: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Turn a resolved suspension into a tool_result block (or a re-dispatch request)."""
    reason = waiting.get("reason")
    call_id = waiting.get("call_id")
    if reason == "subtask":
        sub = db.get(Task, uuid.UUID(waiting["ref_id"]))
        if sub is None:
            return {"type": "tool_result", "tool_call_id": call_id, "content": "Delegated task was removed.", "is_error": True}
        names = []
        for aid in sub.output_artifact_ids:
            from ..models import Artifact

            a = db.get(Artifact, uuid.UUID(aid))
            if a:
                names.append(a.name)
        who = db.get(ProjectAgent, sub.assigned_agent_id) if sub.assigned_agent_id else None
        if sub.status == "completed":
            from ..models import AgentHandoff

            ho = db.scalar(select(AgentHandoff).where(AgentHandoff.created_task_id == sub.id))
            if ho:
                ho.status = "returned"
            events.emit(db, ctx.project.id, "handoff_returned",
                        f"{who.display_name if who else 'Teammate'} returned “{sub.title}” to {ctx.agent.display_name}",
                        run_id=ctx.run.id, agent_id=ctx.agent.id, task_id=ctx.task.id, agent_status="communicating",
                        data={"subtask_id": str(sub.id)})
            return {"type": "tool_result", "tool_call_id": call_id,
                    "content": f"{who.display_name if who else 'Teammate'} completed the subtask. Summary: {sub.result_summary}\n"
                               f"Deliverables: {', '.join(names) or '(none)'} (use read_artifact)"}
        return {"type": "tool_result", "tool_call_id": call_id, "is_error": True,
                "content": f"The delegated subtask ended with status {sub.status}: {sub.error or 'no details'}. Continue without it."}
    if reason == "approval":
        ap = db.get(ApprovalRequest, uuid.UUID(waiting["ref_id"]))
        if ap is None:
            return {"type": "tool_result", "tool_call_id": call_id, "content": "Request was withdrawn.", "is_error": True}
        if ap.kind == "clarification":
            if ap.status == "answered":
                return {"type": "tool_result", "tool_call_id": call_id, "content": f"Client answer: {ap.payload.get('answer', '')}"}
            return {"type": "tool_result", "tool_call_id": call_id, "is_error": True,
                    "content": "The client declined to answer. Proceed with clearly stated assumptions."}
        if ap.kind == "tool_authorization":
            if ap.status == "approved":
                return {"redispatch": True}
            return {"type": "tool_result", "tool_call_id": call_id, "is_error": True,
                    "content": f"The client did not authorize this action. {ap.payload.get('comment', '')}".strip()}
    return None


async def run_task(task_id: uuid.UUID) -> str:
    """Returns: completed | waiting | paused | cancelled | retry | failed"""
    db = SessionLocal()
    try:
        return await _run(db, task_id)
    finally:
        db.close()


async def _run(db: Session, task_id: uuid.UUID) -> str:
    task = db.get(Task, task_id)
    run = db.get(ProjectRun, task.run_id)
    project = db.get(Project, task.project_id)
    agent = db.get(ProjectAgent, task.assigned_agent_id) if task.assigned_agent_id else None
    policy = services.get_budget(db, project.id)
    if agent is None or agent.removed:
        return _fail(db, project, run, task, None, None, "No agent is assigned to this task.", retry=False)
    try:
        provider = get_provider(agent.provider or "")
    except ProviderError as e:
        return _fail(db, project, run, task, agent, None, e.user_message(), retry=False)

    execution = _latest_execution(db, task.id)
    resuming = execution is not None and execution.status == "suspended"
    if resuming:
        # Model changes take effect here, at a safe checkpoint between calls.
        if execution.model_id != agent.model_id or execution.provider != agent.provider:
            events.emit(db, project.id, "model_switched",
                        f"{agent.display_name} continues on {agent.model_id} (was {execution.model_id})",
                        run_id=run.id, agent_id=agent.id, task_id=task.id)
            execution.provider, execution.model_id = agent.provider, agent.model_id
        execution.status = "running"
    else:
        execution = TaskExecution(task_id=task.id, agent_id=agent.id, attempt=task.retry_count + 1,
                                  provider=agent.provider, model_id=agent.model_id, status="running",
                                  conversation=[{"role": "user", "content": [
                                      {"type": "text", "text": task_message(db, project, run, task, agent)}]}])
        from .. import traceability

        execution.input_version_ids = traceability.context_inputs(db, task)  # lineage of the context it saw
        db.add(execution)
    transition_task(task, "running")
    task.started_at = task.started_at or utcnow()
    events.emit(db, project.id, "task_resumed" if resuming else "task_started",
                f"{agent.display_name} {'resumed' if resuming else 'started'} “{task.title}”",
                run_id=run.id, agent_id=agent.id, task_id=task.id, agent_status=_working_status(task),
                data={"attempt": execution.attempt, "kind": task.kind})
    db.commit()

    ctx = toolreg.ToolContext(db=db, project=project, run=run, task=task, agent=agent, execution=execution, policy=policy)
    conv: list[dict[str, Any]] = list(execution.conversation)

    def save():
        execution.conversation = list(conv)
        db.commit()

    # --- Resume: settle whatever the task was waiting for ---------------------------------
    pending = dict(execution.pending or {})
    execution.pending = {}
    results: list[dict[str, Any]] = list(pending.get("results", []))
    waiting = pending.get("waiting")
    _, allowed = toolreg.tools_for(ctx, provider)
    if waiting:
        res = _resolve_waiting(db, ctx, waiting)
        if res and res.get("redispatch"):
            ctx.authorized_call_id = waiting["call_id"]
            out = await toolreg.dispatch(ctx, waiting["name"], waiting["input"], waiting["call_id"], allowed)
            if isinstance(out, toolreg.Suspend):
                return _suspend(db, project, run, task, agent, execution, conv, results, waiting, out)
            results.append({"type": "tool_result", "tool_call_id": waiting["call_id"], "content": out.content,
                            "is_error": out.is_error})
        elif res:
            results.append(res)
    elif conv and conv[-1]["role"] == "assistant":
        # Interrupted between a model reply and its tool results (e.g. a crash): re-run the
        # calls. Tools are idempotent (artifacts dedupe by content, delegation by key).
        unanswered = [b for b in conv[-1]["content"] if b["type"] == "tool_call"]
        if unanswered:
            outcome = await _process_calls(db, ctx, provider, conv, unanswered, results)
            if outcome is not None:
                return outcome
    if results:
        conv.append({"role": "user", "content": results})
        save()
        if any(r.get("finish") for r in results):
            pass
    # --- Main loop ---------------------------------------------------------------------------
    sys_prompt = system_prompt(db, project, agent)
    while True:
        db.refresh(run)
        if run.requested_action == "cancel":
            execution.status = "cancelled"
            execution.ended_at = utcnow()
            transition_task(task, "cancelled")
            save()
            events.emit(db, project.id, "task_cancelled", f"“{task.title}” was cancelled", run_id=run.id,
                        agent_id=agent.id, task_id=task.id, agent_status="idle")
            db.commit()
            return "cancelled"
        if run.requested_action == "pause":
            execution.status = "suspended"
            execution.pending = {}
            transition_task(task, "paused")
            save()
            events.emit(db, project.id, "task_paused", f"{agent.display_name} paused “{task.title}” at a safe point",
                        run_id=run.id, agent_id=agent.id, task_id=task.id, agent_status="idle")
            db.commit()
            return "paused"
        if execution.model_calls >= task.max_model_calls:
            return _fail(db, project, run, task, agent, execution,
                         f"The task used its maximum of {task.max_model_calls} model calls without finishing.", retry=False)
        specs, allowed = toolreg.tools_for(ctx, provider)
        try:
            result = await call_model(db, project=project, run=run, agent=agent, task=task, purpose="task",
                                      system=sys_prompt, messages=conv, tools=specs, provider=provider)
        except ProviderError as e:
            return _fail(db, project, run, task, agent, execution, e.user_message(), retry=e.kind not in NON_RETRYABLE)
        if isinstance(result, Blocked):
            ap = budget.request_budget_decision(db, project=project, run=run, agent=agent, task=task, block=result.block)
            execution.pending = {"waiting": {"reason": "budget", "ref_id": str(ap.id)}}
            execution.status = "suspended"
            transition_task(task, "waiting_approval")
            save()
            return "waiting"
        execution.model_calls += 1
        conv.append(result.assistant_message)
        if result.text.strip():
            db.add(Message(project_id=project.id, run_id=run.id, task_id=task.id, agent_id=agent.id, sender="agent",
                           channel="agent_output", content=result.text[:20000]))
        save()
        if result.stop_reason == "pause":
            continue
        if not result.tool_calls:
            if result.stop_reason == "max_tokens":
                conv.append({"role": "user", "content": [{"type": "text", "text":
                             "Your reply was cut off by the output limit. Continue; save long content with write_artifact "
                             "(you can split it into several deliverables)."}]})
                save()
                continue
            if execution.nudges < MAX_NUDGES:
                execution.nudges += 1
                conv.append({"role": "user", "content": [{"type": "text", "text":
                             "Please use your tools: save your deliverable with write_artifact (if you have that tool) "
                             "and then call complete_task with a short summary."}]})
                save()
                continue
            # The agent keeps answering in prose: keep its work instead of discarding it.
            perms = toolreg.effective_permissions(ctx)
            text = result.text.strip()
            if task.kind != "qa" and "artifact_write" in perms and text and not task.output_artifact_ids:
                await toolreg.h_write_artifact(ctx, {"name": f"{task.title}", "artifact_type": "markdown",
                                                     "content": text, "summary": "Saved from the agent's reply."}, "auto")
            if task.kind == "qa" and not task.result_summary.startswith("Verdict:"):
                return _fail(db, project, run, task, agent, execution, "The reviewer did not submit a structured review.",
                             retry=True)
            task.result_summary = task.result_summary or text[:2000]
            return _complete(db, project, run, task, agent, execution, conv)
        results = []
        outcome = await _process_calls(db, ctx, provider, conv, result.tool_calls, results)
        if outcome is not None:
            return outcome


async def _process_calls(db, ctx: toolreg.ToolContext, provider, conv, calls, results) -> Optional[str]:
    _, allowed = toolreg.tools_for(ctx, provider)
    suspend: Optional[toolreg.Suspend] = None
    waiting: Optional[dict[str, Any]] = None
    finished = False
    for c in calls:
        cid = c.id if hasattr(c, "id") else c["id"]
        name = c.name if hasattr(c, "name") else c["name"]
        args = c.input if hasattr(c, "input") else c["input"]
        if suspend is not None:
            results.append({"type": "tool_result", "tool_call_id": cid, "is_error": True,
                            "content": "Not executed: another action is waiting for a decision. Retry after it resolves."})
            continue
        out = await toolreg.dispatch(ctx, name, args, cid, allowed)
        if isinstance(out, toolreg.Suspend):
            suspend = out
            waiting = {"reason": out.reason, "ref_id": str(out.ref_id), "call_id": cid, "name": name, "input": args}
            continue
        results.append({"type": "tool_result", "tool_call_id": cid, "content": out.content, "is_error": out.is_error})
        finished = finished or out.finish
    if suspend is not None:
        return _suspend(db, ctx.project, ctx.run, ctx.task, ctx.agent, ctx.execution, conv, results, waiting, suspend)
    conv.append({"role": "user", "content": results})
    ctx.execution.conversation = list(conv)
    db.commit()
    if finished:
        return _complete(db, ctx.project, ctx.run, ctx.task, ctx.agent, ctx.execution, conv)
    return None


def _suspend(db, project, run, task, agent, execution, conv, results, waiting, s: toolreg.Suspend) -> str:
    execution.pending = {"results": results, "waiting": waiting}
    execution.status = "suspended"
    execution.conversation = list(conv)
    transition_task(task, "waiting_subtask" if s.reason == "subtask" else "waiting_approval")
    if s.reason == "approval":
        events.emit(db, project.id, "task_waiting", f"{agent.display_name} is waiting for the client: {s.note}",
                    run_id=run.id, agent_id=agent.id, task_id=task.id, agent_status="waiting_for_client")
    else:
        events.emit(db, project.id, "task_waiting", f"{agent.display_name} is waiting for delegated work",
                    run_id=run.id, agent_id=agent.id, task_id=task.id, agent_status="communicating")
    db.commit()
    return "waiting"


def _complete(db, project, run, task, agent, execution, conv) -> str:
    execution.status = "succeeded"
    execution.ended_at = utcnow()
    execution.conversation = list(conv)
    transition_task(task, "completed")
    task.completed_at = utcnow()
    task.error = ""
    events.emit(db, project.id, "task_completed", f"{agent.display_name} completed “{task.title}”",
                run_id=run.id, agent_id=agent.id, task_id=task.id, agent_status="completed",
                data={"summary": task.result_summary[:1000], "artifact_ids": task.output_artifact_ids})
    db.commit()
    return "completed"


def _fail(db, project, run, task, agent, execution, message: str, retry: bool) -> str:
    if execution is not None:
        execution.status = "failed"
        execution.error = message
        execution.ended_at = utcnow()
    task.error = message[:4000]
    agent_id = agent.id if agent else None
    if task.status not in ("running",):
        # e.g. failing before start: move through running for a valid transition
        try:
            transition_task(task, "running")
        except Exception:
            pass
    if retry and task.retry_count < task.max_retries:
        task.retry_count += 1
        transition_task(task, "ready")
        events.emit(db, project.id, "task_retry",
                    f"“{task.title}” failed ({message[:200]}); retrying (attempt {task.retry_count + 1})",
                    run_id=run.id, agent_id=agent_id, task_id=task.id, agent_status="blocked" if agent_id else None)
        db.commit()
        return "retry"
    transition_task(task, "failed")
    events.emit(db, project.id, "task_failed", f"“{task.title}” failed: {message[:500]}", run_id=run.id,
                agent_id=agent_id, task_id=task.id, agent_status="failed" if agent_id else None, data={"error": message})
    db.commit()
    return "failed"
