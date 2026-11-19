"""Domain helpers shared by the API and the orchestration engine."""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import events
from .models import (
    ApprovalRequest, Artifact, ArtifactVersion, BudgetPolicy, ModelConfiguration, Project, ProjectAgent,
    ProjectRequirement, ProjectRun, Task, TaskDependency, ToolPermission, UsageRecord, utcnow,
)

ARTIFACT_TYPES = {"markdown", "json", "csv", "text", "code"}
MAX_ARTIFACT_CHARS = 300_000


class DomainError(ValueError):
    pass


# -- artifacts ---------------------------------------------------------------------
def write_artifact(
    db: Session, *, project_id: uuid.UUID, run_id: Optional[uuid.UUID], task_id: Optional[uuid.UUID],
    agent_id: Optional[uuid.UUID], name: str, content: str, artifact_type: str, summary: str = "",
    source_refs: Optional[list[Any]] = None, category: str = "deliverable",
) -> tuple[Artifact, ArtifactVersion, bool]:
    name = name.strip()[:300]
    if not name:
        raise DomainError("Artifact name is required")
    if artifact_type not in ARTIFACT_TYPES:
        raise DomainError(f"artifact_type must be one of {sorted(ARTIFACT_TYPES)}")
    if len(content) > MAX_ARTIFACT_CHARS:
        raise DomainError(f"Artifact content exceeds {MAX_ARTIFACT_CHARS} characters")
    if artifact_type == "json":
        import json

        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            raise DomainError(f"Content is not valid JSON: {e}") from e
    if artifact_type == "code":
        from .tools.sandbox import safe_rel_path

        try:
            safe_rel_path(name)
        except ValueError as e:
            raise DomainError(f"Code artifacts must be named with a relative file path ({e})") from e
    digest = hashlib.sha256(content.encode()).hexdigest()
    art = db.scalar(select(Artifact).where(Artifact.project_id == project_id, Artifact.name == name))
    created = False
    if art is None:
        art = Artifact(project_id=project_id, run_id=run_id, task_id=task_id, owner_agent_id=agent_id, name=name,
                       artifact_type=artifact_type, category=category, current_version=0)
        db.add(art)
        db.flush()
        created = True
    else:
        latest = latest_version(db, art.id)
        if latest is not None and latest.sha256 == digest:
            return art, latest, False
        art.artifact_type = artifact_type
        art.run_id = run_id or art.run_id
    art.current_version += 1
    art.stale = False
    art.acceptance_status = "pending"
    v = ArtifactVersion(artifact_id=art.id, version=art.current_version, content=content, summary=summary[:2000],
                        source_refs=source_refs or [], sha256=digest, created_by_task_id=task_id,
                        created_by_agent_id=agent_id)
    db.add(v)
    db.flush()
    return art, v, created


def latest_version(db: Session, artifact_id: uuid.UUID) -> Optional[ArtifactVersion]:
    return db.scalar(select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id)
                     .order_by(ArtifactVersion.version.desc()).limit(1))


def project_artifacts(db: Session, project_id: uuid.UUID, include_working: bool = True) -> list[Artifact]:
    q = select(Artifact).where(Artifact.project_id == project_id)
    if not include_working:
        q = q.where(Artifact.category != "working")
    return list(db.scalars(q.order_by(Artifact.created_at)))


# -- approvals ---------------------------------------------------------------------
def create_approval(
    db: Session, *, project_id: uuid.UUID, run_id: Optional[uuid.UUID], kind: str, title: str, explanation: str,
    payload: Optional[dict[str, Any]] = None, task_id: Optional[uuid.UUID] = None,
    agent_id: Optional[uuid.UUID] = None, artifact_ids: Optional[Iterable[uuid.UUID]] = None,
) -> ApprovalRequest:
    ap = ApprovalRequest(project_id=project_id, run_id=run_id, kind=kind, title=title[:300], explanation=explanation,
                         payload=events._jsonable(payload or {}), task_id=task_id, agent_id=agent_id,
                         artifact_ids=[str(a) for a in (artifact_ids or [])])
    db.add(ap)
    db.flush()
    events.emit(db, project_id, "approval_requested", f"Client decision needed: {title}", run_id=run_id,
                agent_id=agent_id, task_id=task_id, data={"approval_id": str(ap.id), "kind": kind},
                agent_status="waiting_for_client" if agent_id else None)
    return ap


def pending_approvals(db: Session, run_id: uuid.UUID) -> list[ApprovalRequest]:
    return list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.run_id == run_id,
                                                         ApprovalRequest.status == "pending")))


# -- requirements ------------------------------------------------------------------
def active_requirements(db: Session, project_id: uuid.UUID) -> list[ProjectRequirement]:
    return list(db.scalars(select(ProjectRequirement).where(ProjectRequirement.project_id == project_id,
                                                            ProjectRequirement.status == "active")
                           .order_by(ProjectRequirement.created_at)))


def sync_core_requirements(db: Session, project: Project) -> None:
    """Mirror the project form fields into ProjectRequirement rows (source=user)."""
    wanted: list[tuple[str, str]] = []
    if project.objective.strip():
        wanted.append(("objective", project.objective.strip()))
    for d in project.deliverables or []:
        if str(d).strip():
            wanted.append(("deliverable", str(d).strip()))
    if project.constraints.strip():
        wanted.append(("constraint", project.constraints.strip()))
    if project.success_criteria.strip():
        wanted.append(("success_criterion", project.success_criteria.strip()))
    existing = list(db.scalars(select(ProjectRequirement).where(
        ProjectRequirement.project_id == project.id, ProjectRequirement.source == "user",
        ProjectRequirement.status == "active", ProjectRequirement.kind.in_(
            ["objective", "deliverable", "constraint", "success_criterion"]))))
    keep = set(wanted)
    have = {(r.kind, r.text) for r in existing}
    for r in existing:
        if (r.kind, r.text) not in keep:
            r.status = "superseded"
    for kind, text in wanted:
        if (kind, text) not in have:
            db.add(ProjectRequirement(project_id=project.id, kind=kind, text=text, source="user"))
    db.flush()


# -- budgets & usage ---------------------------------------------------------------
def get_budget(db: Session, project_id: uuid.UUID) -> BudgetPolicy:
    b = db.scalar(select(BudgetPolicy).where(BudgetPolicy.project_id == project_id))
    if b is None:
        b = BudgetPolicy(project_id=project_id)
        db.add(b)
        db.flush()
    return b


def project_spend(db: Session, project_id: uuid.UUID) -> Decimal:
    v = db.scalar(select(func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0))
                  .where(UsageRecord.project_id == project_id))
    return Decimal(v or 0)


def agent_spend(db: Session, agent_id: uuid.UUID) -> Decimal:
    v = db.scalar(select(func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0))
                  .where(UsageRecord.agent_id == agent_id))
    return Decimal(v or 0)


def task_spend(db: Session, task_id: uuid.UUID) -> Decimal:
    v = db.scalar(select(func.coalesce(func.sum(UsageRecord.estimated_cost_usd), 0))
                  .where(UsageRecord.task_id == task_id))
    return Decimal(v or 0)


def model_config(db: Session, provider: Optional[str], model_id: Optional[str]) -> Optional[ModelConfiguration]:
    if not provider or not model_id:
        return None
    return db.scalar(select(ModelConfiguration).where(ModelConfiguration.provider == provider,
                                                      ModelConfiguration.model_id == model_id))


# -- agents & tasks ----------------------------------------------------------------
def agent_permissions(db: Session, agent: ProjectAgent) -> set[str]:
    return {p.tool_key for p in db.scalars(select(ToolPermission).where(
        ToolPermission.project_agent_id == agent.id, ToolPermission.allowed.is_(True)))}


def set_agent_permissions(db: Session, agent: ProjectAgent, keys: Iterable[str]) -> None:
    from .catalog import TOOL_PERMISSIONS

    keys = set(keys)
    unknown = keys - set(TOOL_PERMISSIONS)
    if unknown:
        raise DomainError(f"Unknown tool permissions: {sorted(unknown)}")
    for p in list(db.scalars(select(ToolPermission).where(ToolPermission.project_agent_id == agent.id))):
        db.delete(p)
    db.flush()
    for k in sorted(keys):
        db.add(ToolPermission(project_agent_id=agent.id, tool_key=k, allowed=True))
    db.flush()


def team(db: Session, project_id: uuid.UUID) -> list[ProjectAgent]:
    return list(db.scalars(select(ProjectAgent).where(ProjectAgent.project_id == project_id,
                                                      ProjectAgent.removed.is_(False))
                           .order_by(ProjectAgent.desk_index)))


def orchestrator(db: Session, project_id: uuid.UUID) -> Optional[ProjectAgent]:
    agents = team(db, project_id)
    for a in agents:
        if a.is_orchestrator:
            return a
    return None


def dependencies(db: Session, task_id: uuid.UUID) -> list[Task]:
    ids = list(db.scalars(select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == task_id)))
    return [db.get(Task, i) for i in ids] if ids else []


def run_tasks(db: Session, run_id: uuid.UUID) -> list[Task]:
    return list(db.scalars(select(Task).where(Task.run_id == run_id).order_by(Task.sort_order, Task.created_at)))


def latest_run(db: Session, project_id: uuid.UUID) -> Optional[ProjectRun]:
    return db.scalar(select(ProjectRun).where(ProjectRun.project_id == project_id)
                     .order_by(ProjectRun.run_number.desc()).limit(1))


def now():
    return utcnow()
