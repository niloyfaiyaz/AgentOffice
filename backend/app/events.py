"""Activity events. Every agent status change in the office is written here first.

The office view never invents state: it renders ``ProjectAgent.status`` and the event
stream, both of which are only updated by :func:`emit`.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session

from .models import AgentEvent, ProjectAgent
from .state_machine import AGENT_VISUAL_STATES

_SECRET_PATTERNS = [
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)(api[_-]?key|authorization|x-api-key)(\"?\s*[:=]\s*\"?)([^\s\"']{8,})"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 3:
            out = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
        else:
            out = pat.sub("[REDACTED]", out)
    return out


def _redact_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return redact(obj)
    if isinstance(obj, dict):
        return {k: _redact_obj(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_obj(v) for v in obj]
    return obj


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def emit(
    db: Session,
    project_id: uuid.UUID,
    type: str,
    message: str = "",
    *,
    run_id: Optional[uuid.UUID] = None,
    agent_id: Optional[uuid.UUID] = None,
    task_id: Optional[uuid.UUID] = None,
    data: Optional[dict[str, Any]] = None,
    agent_status: Optional[str] = None,
) -> AgentEvent:
    if agent_status is not None and agent_status not in AGENT_VISUAL_STATES:
        raise ValueError(f"Unknown agent status {agent_status}")
    ev = AgentEvent(
        project_id=project_id,
        run_id=run_id,
        agent_id=agent_id,
        task_id=task_id,
        type=type,
        message=redact(message)[:4000],
        data=_redact_obj(_jsonable(data or {})),
        agent_status=agent_status,
    )
    db.add(ev)
    if agent_id is not None and agent_status is not None:
        agent = db.get(ProjectAgent, agent_id)
        if agent is not None:
            agent.status = agent_status
            if agent_status in {"working", "reviewing", "assigned", "waiting_for_client", "communicating"}:
                agent.current_task_id = task_id or agent.current_task_id
            elif agent_status in {"idle"}:
                agent.current_task_id = None
    db.flush()
    return ev


def event_to_dict(ev: AgentEvent) -> dict[str, Any]:
    return {
        "seq": ev.seq,
        "id": str(ev.id),
        "project_id": str(ev.project_id),
        "run_id": str(ev.run_id) if ev.run_id else None,
        "agent_id": str(ev.agent_id) if ev.agent_id else None,
        "task_id": str(ev.task_id) if ev.task_id else None,
        "type": ev.type,
        "message": ev.message,
        "data": ev.data,
        "agent_status": ev.agent_status,
        "created_at": ev.created_at.isoformat(),
    }
