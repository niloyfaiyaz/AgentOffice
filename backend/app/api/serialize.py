from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy.orm import Session

from .. import services
from ..catalog import cost_tier
from ..models import (
    AgentDefinition, AgentHandoff, ApprovalRequest, Artifact, ModelConfiguration, Project, ProjectAgent, ProjectRun,
    ReferenceFile, ReviewFinding, Task, ToolPermission,
)


def s(v: Any) -> Optional[str]:
    return None if v is None else str(v)


def money(v: Optional[Decimal]) -> Optional[float]:
    return None if v is None else float(v)


def project(p: Project) -> dict:
    return {"id": s(p.id), "name": p.name, "objective": p.objective, "description": p.description,
            "deliverables": p.deliverables, "constraints": p.constraints, "success_criteria": p.success_criteria,
            "deadline": p.deadline.isoformat() if p.deadline else None, "status": p.status, "archived": p.archived,
            "template_key": p.template_key, "created_at": p.created_at.isoformat(), "updated_at": p.updated_at.isoformat()}


def model(m: ModelConfiguration) -> dict:
    return {"id": s(m.id), "provider": m.provider, "model_id": m.model_id, "display_name": m.display_name,
            "input_price_per_mtok": money(m.input_price_per_mtok), "output_price_per_mtok": money(m.output_price_per_mtok),
            "cache_read_price_per_mtok": money(m.cache_read_price_per_mtok),
            "cache_write_price_per_mtok": money(m.cache_write_price_per_mtok),
            "pricing_source": m.pricing_source, "context_window": m.context_window,
            "max_output_tokens": m.max_output_tokens, "supports_tools": m.supports_tools, "discovered": m.discovered,
            "enabled": m.enabled, "notes": m.notes,
            "cost_tier": cost_tier(m.input_price_per_mtok, m.output_price_per_mtok)}


def definition(db: Session, d: AgentDefinition) -> dict:
    perms = sorted(p.tool_key for p in db.query(ToolPermission).filter(ToolPermission.agent_definition_id == d.id,
                                                                        ToolPermission.allowed.is_(True)))
    mc = services.model_config(db, d.provider, d.model_id)
    return {"id": s(d.id), "name": d.name, "role": d.role, "role_key": d.role_key, "description": d.description,
            "instructions": d.instructions, "avatar": d.avatar, "provider": d.provider, "model_id": d.model_id,
            "effort": d.effort, "max_output_tokens": d.max_output_tokens, "max_calls_per_task": d.max_calls_per_task,
            "is_builtin": d.is_builtin, "archived": d.archived, "tools": perms,
            "cost_tier": cost_tier(mc.input_price_per_mtok, mc.output_price_per_mtok) if mc else "unpriced"}


def agent(db: Session, a: ProjectAgent, spend: bool = True) -> dict:
    mc = services.model_config(db, a.provider, a.model_id)
    out = {"id": s(a.id), "project_id": s(a.project_id), "agent_definition_id": s(a.agent_definition_id),
           "display_name": a.display_name, "role": a.role, "role_key": a.role_key, "description": a.description,
           "instructions": a.instructions, "avatar": a.avatar, "provider": a.provider, "model_id": a.model_id,
           "effort": a.effort, "max_output_tokens": a.max_output_tokens, "max_calls_per_task": a.max_calls_per_task,
           "spend_limit_usd": money(a.spend_limit_usd), "is_orchestrator": a.is_orchestrator, "desk_index": a.desk_index,
           "status": a.status, "current_task_id": s(a.current_task_id), "tools": sorted(services.agent_permissions(db, a)),
           "cost_tier": "test" if a.provider == "scripted-test" else
           (cost_tier(mc.input_price_per_mtok, mc.output_price_per_mtok) if mc else "unpriced")}
    if spend:
        out["estimated_spend_usd"] = float(services.agent_spend(db, a.id))
    return out


def run(r: ProjectRun) -> dict:
    return {"id": s(r.id), "project_id": s(r.project_id), "run_number": r.run_number, "kind": r.kind,
            "revision_feedback": r.revision_feedback, "status": r.status, "phase": r.phase,
            "blocked_reason": r.blocked_reason, "requested_action": r.requested_action, "sow": r.sow,
            "approved_tools": r.approved_tools, "planned_task_count": r.planned_task_count, "model_calls": r.model_calls,
            "review_iterations": r.review_iterations, "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None, "error": r.error,
            "worker_active": r.lease_owner is not None, "created_at": r.created_at.isoformat()}


def task(db: Session, t: Task) -> dict:
    deps = [s(d.id) for d in services.dependencies(db, t.id)]
    return {"id": s(t.id), "run_id": s(t.run_id), "parent_task_id": s(t.parent_task_id),
            "assigned_agent_id": s(t.assigned_agent_id), "plan_key": t.plan_key, "kind": t.kind, "title": t.title,
            "objective": t.objective, "input_refs": t.input_refs, "expected_output_type": t.expected_output_type,
            "acceptance_criteria": t.acceptance_criteria, "allowed_tools": t.allowed_tools,
            "budget_usd": money(t.budget_usd), "max_model_calls": t.max_model_calls, "status": t.status,
            "depth": t.depth, "retry_count": t.retry_count, "max_retries": t.max_retries,
            "output_artifact_ids": t.output_artifact_ids, "result_summary": t.result_summary, "error": t.error,
            "depends_on": deps, "context_notes": t.context_notes, "sort_order": t.sort_order,
            "requirement_refs": _task_refs(db, t.id, True), "former_requirement_refs": _task_refs(db, t.id, False),
            "estimated_spend_usd": float(services.task_spend(db, t.id)),
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None}


def _task_refs(db: Session, task_id, active: bool) -> list[str]:
    from .. import traceability

    rows = [l for l in traceability.links(db, task_id, active_only=False) if l.active == active]
    return traceability.refs(db, [l.requirement_id for l in rows])


def approval(a: ApprovalRequest) -> dict:
    return {"id": s(a.id), "project_id": s(a.project_id), "run_id": s(a.run_id), "task_id": s(a.task_id),
            "agent_id": s(a.agent_id), "kind": a.kind, "title": a.title, "explanation": a.explanation,
            "payload": a.payload, "artifact_ids": a.artifact_ids, "status": a.status,
            "created_at": a.created_at.isoformat(), "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None}


def artifact(db: Session, a: Artifact, content: bool = False) -> dict:
    v = services.latest_version(db, a.id)
    out = {"id": s(a.id), "project_id": s(a.project_id), "run_id": s(a.run_id), "task_id": s(a.task_id),
           "owner_agent_id": s(a.owner_agent_id), "name": a.name, "artifact_type": a.artifact_type, "category": a.category,
           "current_version": a.current_version, "acceptance_status": a.acceptance_status, "stale": a.stale,
           "stale_reason": a.stale_reason.replace("[lineage] ", "").replace("[note] ", ""),
           "confirmed_version": a.confirmed_version,
           "summary": v.summary if v else "", "size": len(v.content) if v else 0,
           "updated_at": a.updated_at.isoformat()}
    if content and v:
        out["content"] = v.content
        out["source_refs"] = v.source_refs
    return out


def finding(f: ReviewFinding) -> dict:
    return {"id": s(f.id), "run_id": s(f.run_id), "qa_task_id": s(f.qa_task_id), "artifact_id": s(f.artifact_id),
            "finding_key": f.finding_key, "severity": f.severity, "requirement_ref": f.requirement_ref,
            "evidence": f.evidence, "recommendation": f.recommendation, "status": f.status,
            "created_at": f.created_at.isoformat()}


def handoff(h: AgentHandoff) -> dict:
    return {"id": s(h.id), "run_id": s(h.run_id), "from_agent_id": s(h.from_agent_id), "to_agent_id": s(h.to_agent_id),
            "source_task_id": s(h.source_task_id), "created_task_id": s(h.created_task_id), "kind": h.kind,
            "summary": h.summary, "status": h.status, "created_at": h.created_at.isoformat()}


def file(f: ReferenceFile) -> dict:
    return {"id": s(f.id), "filename": f.filename, "mime_type": f.mime_type, "size_bytes": f.size_bytes,
            "chars": len(f.extracted_text), "extraction_status": f.extraction_status, "extraction_note": f.extraction_note,
            "preview": f.extracted_text[:600], "created_at": f.created_at.isoformat()}
