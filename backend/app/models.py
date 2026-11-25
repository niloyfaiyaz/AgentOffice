"""SQLAlchemy data model.

Status columns are plain strings whose allowed values and transitions are defined and
enforced in ``app.state_machine``. Every state change goes through that module.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> uuid.UUID:
    return uuid.uuid4()


JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)


def fk(target: str, nullable: bool = False, ondelete: str = "CASCADE") -> Mapped[Any]:
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True)


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
class Project(TimestampMixin, Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deliverables: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    constraints: Mapped[str] = mapped_column(Text, nullable=False, default="")
    success_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    template_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Normalized name for uniqueness (see app.naming); maintained automatically on flush.
    name_key: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # user | acceptance_test | scripted_test - non-user projects are hidden from the normal list.
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    # Structured brief with per-item provenance (see app.discovery).
    brief: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)

    __table_args__ = (
        Index("uq_projects_active_name", "name_key", unique=True,
              postgresql_where=text("archived = false AND origin = 'user'")),
    )

    agents: Mapped[list["ProjectAgent"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    runs: Mapped[list["ProjectRun"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    requirements: Mapped[list["ProjectRequirement"]] = relationship(cascade="all, delete-orphan")
    files: Mapped[list["ReferenceFile"]] = relationship(cascade="all, delete-orphan")
    budget: Mapped[Optional["BudgetPolicy"]] = relationship(cascade="all, delete-orphan", uselist=False)


class ProjectRequirement(TimestampMixin, Base):
    """One requirement item. The brief is split into individual items so a change request can
    supersede exactly the rule it replaces; superseded items are kept (history) and linked to
    the item that replaced them."""

    __tablename__ = "project_requirements"
    __table_args__ = (UniqueConstraint("project_id", "ref", name="uq_requirement_ref"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    # objective (context) | requirement | deliverable | constraint | success_criterion |
    # clarification | change | feedback
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")  # active | superseded
    ref: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # stable per-project id, e.g. R-007
    superseded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_requirements.id", ondelete="SET NULL"), nullable=True, index=True)
    superseded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    run_id: Mapped[Optional[uuid.UUID]] = fk("project_runs.id", nullable=True, ondelete="SET NULL")


class ReferenceFile(TimestampMixin, Base):
    __tablename__ = "reference_files"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extraction_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ok")
    extraction_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ProjectTemplate(TimestampMixin, Base):
    __tablename__ = "project_templates"
    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommended_roles: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    deliverables: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    example_objective: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Models, agents and permissions
# ---------------------------------------------------------------------------
class ModelConfiguration(TimestampMixin, Base):
    __tablename__ = "model_configurations"
    __table_args__ = (UniqueConstraint("provider", "model_id", name="uq_model_provider_id"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # USD per million tokens; NULL means "not configured" and the cost cannot be estimated.
    input_price_per_mtok: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    output_price_per_mtok: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    cache_read_price_per_mtok: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    cache_write_price_per_mtok: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    pricing_source: Mapped[str] = mapped_column(Text, nullable=False, default="not configured")
    context_window: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_output_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    supports_tools: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    discovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AgentDefinition(TimestampMixin, Base):
    """Reusable agent profile (the "employee profile" in the Team library)."""

    __tablename__ = "agent_definitions"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    effort: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=16000)
    max_calls_per_task: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TeamPreset(TimestampMixin, Base):
    """A saved consulting team (list of agent definitions)."""

    __tablename__ = "team_presets"
    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    agent_definition_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)


class ProjectAgent(TimestampMixin, Base):
    """An agent hired onto a specific project (a copy of a definition, editable per project)."""

    __tablename__ = "project_agents"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    agent_definition_id: Mapped[Optional[uuid.UUID]] = fk("agent_definitions.id", nullable=True, ondelete="SET NULL")
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(120), nullable=False)
    role_key: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    avatar: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    effort: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=16000)
    max_calls_per_task: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    spend_limit_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    is_orchestrator: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    desk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Visual/operational status, updated only together with an AgentEvent.
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    current_task_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    removed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    project: Mapped[Project] = relationship(back_populates="agents")
    permissions: Mapped[list["ToolPermission"]] = relationship(
        cascade="all, delete-orphan", foreign_keys="ToolPermission.project_agent_id"
    )


class ToolPermission(TimestampMixin, Base):
    __tablename__ = "tool_permissions"
    __table_args__ = (
        CheckConstraint(
            "(agent_definition_id IS NULL) <> (project_agent_id IS NULL)", name="ck_tool_permission_owner"
        ),
        UniqueConstraint("agent_definition_id", "project_agent_id", "tool_key", name="uq_tool_permission"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    agent_definition_id: Mapped[Optional[uuid.UUID]] = fk("agent_definitions.id", nullable=True)
    project_agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True)
    tool_key: Mapped[str] = mapped_column(String(64), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


# ---------------------------------------------------------------------------
# Runs, tasks and execution
# ---------------------------------------------------------------------------
class ProjectRun(TimestampMixin, Base):
    __tablename__ = "project_runs"
    __table_args__ = (UniqueConstraint("project_id", "run_number", name="uq_run_number"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="initial")  # initial | revision
    revision_feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planning")
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="planning")
    blocked_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_action: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)  # pause | cancel
    sow: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    approved_tools: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    planned_task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    review_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    planning_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_owner: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    project: Mapped[Project] = relationship(back_populates="runs")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (UniqueConstraint("run_id", "idempotency_key", name="uq_task_idempotency"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID] = fk("project_runs.id")
    parent_task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    assigned_agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    plan_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="work")  # work|subtask|qa|rework|consolidation
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    input_refs: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    expected_output_type: Mapped[str] = mapped_column(String(32), nullable=False, default="markdown")
    acceptance_criteria: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    allowed_tools: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    budget_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    max_model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    output_artifact_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    context_notes: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    finding_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "depends_on_task_id", name="uq_task_dependency"),
        CheckConstraint("task_id <> depends_on_task_id", name="ck_no_self_dependency"),
    )
    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = fk("tasks.id")
    depends_on_task_id: Mapped[uuid.UUID] = fk("tasks.id")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TaskExecution(TimestampMixin, Base):
    __tablename__ = "task_executions"
    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = fk("tasks.id")
    agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    # Provider-neutral conversation (see app.providers.base) - persisted so a task can be
    # suspended (approval, pause, delegation) and resumed without losing in-flight tool calls.
    conversation: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    pending: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nudges: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_version_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AgentHandoff(TimestampMixin, Base):
    __tablename__ = "agent_handoffs"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID] = fk("project_runs.id")
    from_agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    to_agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    source_task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    created_task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="delegation")  # delegation|dependency|review|rework
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open | returned


class AgentEvent(Base):
    """Append-only activity log. Every visual state in the office is derived from these rows."""

    __tablename__ = "agent_events"
    __table_args__ = (Index("ix_agent_events_project_seq", "project_id", "seq"),)
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=new_id, unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[Optional[uuid.UUID]] = fk("project_runs.id", nullable=True)
    agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    type: Mapped[str] = mapped_column(String(48), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    agent_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[Optional[uuid.UUID]] = fk("project_runs.id", nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    sender: Mapped[str] = mapped_column(String(16), nullable=False)  # user | agent | system
    channel: Mapped[str] = mapped_column(String(32), nullable=False, default="client")  # client | agent_output
    intent: Mapped[str] = mapped_column(String(32), nullable=False, default="general")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ApprovalRequest(TimestampMixin, Base):
    __tablename__ = "approval_requests"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[Optional[uuid.UUID]] = fk("project_runs.id", nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    # sow | clarification | tool_authorization | budget | scope_change | task_failure |
    # requirement_change | deliverable_acceptance
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    artifact_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class UserDecision(Base):
    __tablename__ = "user_decisions"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    approval_request_id: Mapped[Optional[uuid.UUID]] = fk("approval_requests.id", nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)  # approve|reject|revise|answer
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


# ---------------------------------------------------------------------------
# Deliverables and QA
# ---------------------------------------------------------------------------
class Artifact(TimestampMixin, Base):
    __tablename__ = "artifacts"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_artifact_name"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[Optional[uuid.UUID]] = fk("project_runs.id", nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    owner_agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(16), nullable=False)  # markdown|json|csv|text|code
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="deliverable")  # deliverable|plan|summary|working
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acceptance_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # "[lineage] ..." when computed from requirement/input lineage; "[note] ..." when set by a client action.
    stale_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The client explicitly confirmed this version as current despite lineage uncertainty.
    confirmed_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ArtifactVersion(Base):
    __tablename__ = "artifact_versions"
    __table_args__ = (UniqueConstraint("artifact_id", "version", name="uq_artifact_version"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    artifact_id: Mapped[uuid.UUID] = fk("artifacts.id")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_refs: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    created_by_agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    # Lineage snapshot taken at write time (immutable): the requirement items the producing task
    # implemented, and the exact artifact versions it was derived from.
    requirement_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    input_version_ids: Mapped[list[Any]] = mapped_column(JSONType, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TaskRequirement(Base):
    """Which requirement items a task implements. Links are deactivated, never deleted, so the
    historical association survives requirement changes."""

    __tablename__ = "task_requirements"
    __table_args__ = (UniqueConstraint("task_id", "requirement_id", name="uq_task_requirement"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    task_id: Mapped[uuid.UUID] = fk("tasks.id")
    requirement_id: Mapped[uuid.UUID] = fk("project_requirements.id")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="plan")  # plan|inherited|change|qa
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ReviewFinding(TimestampMixin, Base):
    __tablename__ = "review_findings"
    __table_args__ = (UniqueConstraint("run_id", "finding_key", name="uq_finding_key"),)
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[uuid.UUID] = fk("project_runs.id")
    qa_task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    artifact_id: Mapped[Optional[uuid.UUID]] = fk("artifacts.id", nullable=True, ondelete="SET NULL")
    finding_key: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)  # critical|major|minor|info
    requirement_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="open")  # open|rework_requested|resolved|unresolved
    resolved_by_task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")


# ---------------------------------------------------------------------------
# Usage, budgets and credentials
# ---------------------------------------------------------------------------
class UsageRecord(Base):
    __tablename__ = "usage_records"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = fk("projects.id")
    run_id: Mapped[Optional[uuid.UUID]] = fk("project_runs.id", nullable=True)
    task_id: Mapped[Optional[uuid.UUID]] = fk("tasks.id", nullable=True, ondelete="SET NULL")
    agent_id: Mapped[Optional[uuid.UUID]] = fk("project_agents.id", nullable=True, ondelete="SET NULL")
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False, default="task")  # task|planning|chat|recommendation
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    other_usage: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    price_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False, default=dict)
    estimated_cost_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    is_test_provider: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class BudgetPolicy(TimestampMixin, Base):
    __tablename__ = "budget_policies"
    id: Mapped[uuid.UUID] = uuid_pk()
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    budget_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    warning_threshold_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    # Spending beyond this cumulative amount requires an explicit client approval (once).
    approval_threshold_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 4), nullable=True)
    approval_threshold_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    max_model_calls_per_run: Mapped[int] = mapped_column(Integer, nullable=False, default=120)
    max_concurrency: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_delegation_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_review_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    task_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    warning_emitted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ProviderCredentialReference(TimestampMixin, Base):
    """Metadata about a stored API key. The secret itself is never stored in this database."""

    __tablename__ = "provider_credential_refs"
    id: Mapped[uuid.UUID] = uuid_pk()
    provider: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False)  # keyring | encrypted_file
    key_hint: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unvalidated")
    last_validated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")


@event.listens_for(Project, "before_insert")
@event.listens_for(Project, "before_update")
def _normalize_project_name(mapper, connection, target: Project) -> None:
    from .naming import display_name, name_key

    target.name = display_name(target.name)
    target.name_key = name_key(target.name)
