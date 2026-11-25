"""HTTP API. The browser talks only to this local API; provider calls originate in the backend."""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import catalog, events, exports, requirements, services
from ..config import settings
from ..db import SessionLocal, get_db
from ..models import (
    AgentDefinition, AgentEvent, AgentHandoff, ApprovalRequest, Artifact, ArtifactVersion, Message, ModelConfiguration,
    Project, ProjectAgent, ProjectRequirement, ProjectRun, ProjectTemplate, ProviderCredentialReference, ReferenceFile,
    ReviewFinding, Task, TaskExecution, TeamPreset, ToolPermission, UsageRecord, utcnow,
)
from ..orchestration import decisions
from ..orchestration.llm import Blocked, call_model
from ..providers import registry as providers
from ..providers.base import ProviderError
from ..security import credentials
from ..state_machine import RUN_TERMINAL
from ..tools import files as filetools
from ..tools import sandbox
from . import serialize as ser

router = APIRouter()


def _uuid(v: str) -> uuid.UUID:
    try:
        return uuid.UUID(v)
    except ValueError as e:
        raise HTTPException(404, "Not found") from e


def _get(db: Session, model, id_: str):
    obj = db.get(model, _uuid(id_))
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


def _money(v: Any) -> Optional[Decimal]:
    if v is None or v == "":
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation as e:
        raise HTTPException(422, f"Invalid amount {v}") from e
    if d < 0:
        raise HTTPException(422, "Amounts must be positive")
    return d


def _bad(e: Exception):
    raise HTTPException(400, str(e))


# ---------------------------------------------------------------------------
# Bootstrap / dashboard
# ---------------------------------------------------------------------------
@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"ok": True}


@router.get("/bootstrap")
async def bootstrap(db: Session = Depends(get_db)):
    sb = await sandbox.status()
    return {
        "providers": _provider_status(db),
        "credential_backend": credentials.store_backend_name(),
        "test_provider_enabled": settings.enable_test_provider,
        "sandbox": sb,
        "tool_permissions": catalog.TOOL_PERMISSIONS,
        "templates": [_template(t) for t in db.scalars(select(ProjectTemplate).order_by(ProjectTemplate.created_at))],
        "models": [ser.model(m) for m in db.scalars(select(ModelConfiguration).where(ModelConfiguration.enabled.is_(True))
                                                   .order_by(ModelConfiguration.provider, ModelConfiguration.model_id))],
        "privacy_notice": ("Project data is stored locally on this machine (PostgreSQL in Docker, files under data/). "
                           "When agents run, their prompts and the selected project context are sent to the AI providers "
                           "whose API keys you configure, and are subject to those providers' terms. "
                           "AgentOffice sends no telemetry."),
    }


def _template(t: ProjectTemplate) -> dict:
    return {"id": str(t.id), "key": t.key, "name": t.name, "description": t.description,
            "recommended_roles": t.recommended_roles, "deliverables": t.deliverables,
            "example_objective": t.example_objective}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    projects = list(db.scalars(select(Project).where(Project.archived.is_(False), Project.origin == "user")
                               .order_by(Project.updated_at.desc())))
    pend = dict(db.execute(select(ApprovalRequest.project_id, func.count()).where(ApprovalRequest.status == "pending")
                           .group_by(ApprovalRequest.project_id)).all())
    recent = list(db.scalars(select(AgentEvent).where(AgentEvent.project_id.in_([p.id for p in projects]))
                             .order_by(AgentEvent.seq.desc()).limit(25)))
    names = {p.id: p.name for p in db.scalars(select(Project))}
    return {
        "projects": [{**ser.project(p), "pending_approvals": pend.get(p.id, 0),
                      "estimated_spend_usd": float(services.project_spend(db, p.id)),
                      "agents": len(services.team(db, p.id))} for p in projects],
        "recent_activity": [{**events.event_to_dict(e), "project_name": names.get(e.project_id, "")} for e in recent],
        "team_presets": [_preset(p) for p in db.scalars(select(TeamPreset).order_by(TeamPreset.created_at.desc()))],
        "providers": _provider_status(db),
    }


# ---------------------------------------------------------------------------
# Providers & credentials (BYOK)
# ---------------------------------------------------------------------------
def _provider_status(db: Session) -> list[dict]:
    out = []
    for name in ("anthropic", "openai"):
        ref = db.scalar(select(ProviderCredentialReference).where(ProviderCredentialReference.provider == name))
        out.append({"provider": name, "configured": ref is not None, "key_hint": ref.key_hint if ref else "",
                    "status": ref.status if ref else "missing", "storage_backend": ref.storage_backend if ref else None,
                    "last_validated_at": ref.last_validated_at.isoformat() if ref and ref.last_validated_at else None,
                    "last_error": ref.last_error if ref else ""})
    if settings.enable_test_provider:
        out.append({"provider": providers.TEST_PROVIDER, "configured": True, "key_hint": "", "status": "valid",
                    "storage_backend": None, "last_validated_at": None, "last_error": "",
                    "note": "Deterministic scripted provider for automated tests. Not an AI model."})
    return out


class CredentialIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=400)


@router.get("/providers")
def list_providers(db: Session = Depends(get_db)):
    return _provider_status(db)


@router.put("/providers/{provider}/credential")
async def put_credential(provider: str, body: CredentialIn, db: Session = Depends(get_db)):
    if provider not in credentials.PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    try:
        backend = credentials.save_secret(provider, body.api_key)
    except credentials.CredentialError as e:
        raise HTTPException(400, str(e)) from e
    providers.invalidate()
    ref = db.scalar(select(ProviderCredentialReference).where(ProviderCredentialReference.provider == provider))
    if ref is None:
        ref = ProviderCredentialReference(provider=provider, storage_backend=backend)
        db.add(ref)
    ref.storage_backend = backend
    ref.key_hint = credentials.key_hint(body.api_key.strip())
    ref.status = "unvalidated"
    ref.last_error = ""
    db.commit()
    return await test_provider(provider, db)


@router.post("/providers/{provider}/test")
async def test_provider(provider: str, db: Session = Depends(get_db)):
    ref = db.scalar(select(ProviderCredentialReference).where(ProviderCredentialReference.provider == provider))
    if ref is None:
        raise HTTPException(400, "No API key is configured for this provider")
    try:
        p = providers.get_provider(provider)
        models = await p.validate()
    except ProviderError as e:
        ref.status = "invalid" if e.kind in ("auth", "permission") else "error"
        ref.last_error = e.user_message()
        ref.last_validated_at = utcnow()
        db.commit()
        return {"ok": False, "status": ref.status, "error": ref.last_error, "models": []}
    ref.status = "valid"
    ref.last_error = ""
    ref.last_validated_at = utcnow()
    found = []
    for m in models:
        mc = services.model_config(db, provider, m.model_id)
        if mc is None:
            mc = ModelConfiguration(provider=provider, model_id=m.model_id, display_name=m.display_name, discovered=True,
                                    pricing_source="not configured - enter prices on the Costs page")
            db.add(mc)
        mc.discovered = True
        mc.context_window = m.context_window or mc.context_window
        mc.max_output_tokens = m.max_output_tokens or mc.max_output_tokens
        if m.capabilities:
            mc.capabilities = m.capabilities
        found.append(m.model_id)
    db.commit()
    return {"ok": True, "status": "valid", "models": found,
            "note": "The key works and these models are visible to it. This does not guarantee every model or tool "
                    "is enabled for your account."}


@router.delete("/providers/{provider}/credential")
def delete_credential(provider: str, db: Session = Depends(get_db)):
    if provider not in credentials.PROVIDERS:
        raise HTTPException(404, "Unknown provider")
    try:
        credentials.delete_secret(provider)
    except credentials.CredentialError as e:
        raise HTTPException(400, str(e)) from e
    providers.invalidate()
    ref = db.scalar(select(ProviderCredentialReference).where(ProviderCredentialReference.provider == provider))
    if ref:
        db.delete(ref)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
@router.get("/models")
def list_models(db: Session = Depends(get_db)):
    q = select(ModelConfiguration).order_by(ModelConfiguration.provider, ModelConfiguration.model_id)
    out = [ser.model(m) for m in db.scalars(q)]
    if settings.enable_test_provider:
        out.append({"id": "scripted", "provider": providers.TEST_PROVIDER, "model_id": "scripted-v1",
                    "display_name": "Scripted test model (not AI)", "input_price_per_mtok": None,
                    "output_price_per_mtok": None, "pricing_source": "test provider - no cost", "enabled": True,
                    "cost_tier": "test", "context_window": None, "max_output_tokens": 16000, "discovered": False,
                    "notes": "", "supports_tools": True, "cache_read_price_per_mtok": None, "cache_write_price_per_mtok": None})
    return out


class ModelIn(BaseModel):
    provider: Optional[str] = None
    model_id: Optional[str] = None
    display_name: Optional[str] = None
    input_price_per_mtok: Optional[float] = None
    output_price_per_mtok: Optional[float] = None
    cache_read_price_per_mtok: Optional[float] = None
    cache_write_price_per_mtok: Optional[float] = None
    max_output_tokens: Optional[int] = None
    enabled: Optional[bool] = None
    notes: Optional[str] = None


@router.post("/models")
def create_model(body: ModelIn, db: Session = Depends(get_db)):
    if body.provider not in credentials.PROVIDERS or not body.model_id:
        raise HTTPException(422, "provider (anthropic|openai) and model_id are required")
    if services.model_config(db, body.provider, body.model_id):
        raise HTTPException(409, "Model already exists")
    mc = ModelConfiguration(provider=body.provider, model_id=body.model_id.strip(),
                            display_name=body.display_name or body.model_id, pricing_source="user-configured")
    db.add(mc)
    _apply_model(mc, body)
    db.commit()
    return ser.model(mc)


def _apply_model(mc: ModelConfiguration, body: ModelIn):
    data = body.model_dump(exclude_unset=True)
    priced = False
    for k in ("input_price_per_mtok", "output_price_per_mtok", "cache_read_price_per_mtok", "cache_write_price_per_mtok"):
        if k in data:
            setattr(mc, k, _money(data[k]))
            priced = True
    if priced:
        mc.pricing_source = "user-configured"
    for k in ("display_name", "max_output_tokens", "enabled", "notes"):
        if k in data and data[k] is not None:
            setattr(mc, k, data[k])


@router.patch("/models/{mid}")
def update_model(mid: str, body: ModelIn, db: Session = Depends(get_db)):
    mc = _get(db, ModelConfiguration, mid)
    _apply_model(mc, body)
    db.commit()
    return ser.model(mc)


# ---------------------------------------------------------------------------
# Agent library and saved teams
# ---------------------------------------------------------------------------
@router.get("/templates")
def templates(db: Session = Depends(get_db)):
    return [_template(t) for t in db.scalars(select(ProjectTemplate).order_by(ProjectTemplate.created_at))]


@router.get("/agent-definitions")
def list_definitions(db: Session = Depends(get_db)):
    q = select(AgentDefinition).where(AgentDefinition.archived.is_(False)).order_by(AgentDefinition.is_builtin.desc(),
                                                                                  AgentDefinition.created_at)
    return [ser.definition(db, d) for d in db.scalars(q)]


class AgentIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    role: Optional[str] = Field(default=None, max_length=120)
    role_key: Optional[str] = Field(default=None, max_length=64)
    description: Optional[str] = None
    instructions: Optional[str] = Field(default=None, max_length=20000)
    avatar: Optional[dict] = None
    provider: Optional[str] = None
    model_id: Optional[str] = None
    effort: Optional[str] = None
    max_output_tokens: Optional[int] = Field(default=None, ge=256, le=128000)
    max_calls_per_task: Optional[int] = Field(default=None, ge=1, le=100)
    tools: Optional[list[str]] = None
    spend_limit_usd: Optional[float] = None
    is_orchestrator: Optional[bool] = None
    agent_definition_id: Optional[str] = None


EFFORTS = {"low", "medium", "high", "xhigh", "max"}


def _validate_agent_fields(db: Session, data: dict):
    if "effort" in data and data["effort"] not in EFFORTS:
        raise HTTPException(422, f"effort must be one of {sorted(EFFORTS)}")
    if data.get("provider") is not None and data["provider"] not in providers.available_providers():
        raise HTTPException(422, "Unknown provider")
    if data.get("tools") is not None:
        bad = set(data["tools"]) - set(catalog.TOOL_PERMISSIONS)
        if bad:
            raise HTTPException(422, f"Unknown tools: {sorted(bad)}")


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:60] or "custom"


@router.post("/agent-definitions")
def create_definition(body: AgentIn, db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    _validate_agent_fields(db, data)
    if not body.name or not body.role:
        raise HTTPException(422, "name and role are required")
    d = AgentDefinition(name=body.name, role=body.role, role_key=body.role_key or _slugify(body.role),
                        description=body.description or "", instructions=body.instructions or "",
                        avatar=body.avatar or {"skin": "#f1c27d", "hair": "#333333", "shirt": "#6c757d",
                                               "pants": "#343a40", "accent": "#ffc107"},
                        provider=body.provider or catalog.DEFAULT_MODEL[0], model_id=body.model_id or catalog.DEFAULT_MODEL[1],
                        effort=body.effort or "medium", max_output_tokens=body.max_output_tokens or 16000,
                        max_calls_per_task=body.max_calls_per_task or 12)
    db.add(d)
    db.flush()
    for k in body.tools or catalog.BASE:
        db.add(ToolPermission(agent_definition_id=d.id, tool_key=k))
    db.commit()
    return ser.definition(db, d)


@router.patch("/agent-definitions/{did}")
def update_definition(did: str, body: AgentIn, db: Session = Depends(get_db)):
    d = _get(db, AgentDefinition, did)
    data = body.model_dump(exclude_unset=True)
    _validate_agent_fields(db, data)
    for k in ("name", "role", "description", "instructions", "avatar", "provider", "model_id", "effort",
              "max_output_tokens", "max_calls_per_task"):
        if k in data and data[k] is not None:
            setattr(d, k, data[k])
    if body.tools is not None:
        for p in list(db.scalars(select(ToolPermission).where(ToolPermission.agent_definition_id == d.id))):
            db.delete(p)
        db.flush()
        for k in body.tools:
            db.add(ToolPermission(agent_definition_id=d.id, tool_key=k))
    db.commit()
    return ser.definition(db, d)


@router.delete("/agent-definitions/{did}")
def archive_definition(did: str, db: Session = Depends(get_db)):
    d = _get(db, AgentDefinition, did)
    d.archived = True
    db.commit()
    return {"ok": True}


def _preset(p: TeamPreset) -> dict:
    return {"id": str(p.id), "name": p.name, "description": p.description, "agent_definition_ids": p.agent_definition_ids,
            "created_at": p.created_at.isoformat()}


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    agent_definition_ids: list[str] = []


@router.get("/team-presets")
def list_presets(db: Session = Depends(get_db)):
    return [_preset(p) for p in db.scalars(select(TeamPreset).order_by(TeamPreset.created_at.desc()))]


@router.post("/team-presets")
def create_preset(body: PresetIn, db: Session = Depends(get_db)):
    for i in body.agent_definition_ids:
        _get(db, AgentDefinition, i)
    p = TeamPreset(name=body.name, description=body.description, agent_definition_ids=body.agent_definition_ids)
    db.add(p)
    db.commit()
    return _preset(p)


@router.delete("/team-presets/{pid}")
def delete_preset(pid: str, db: Session = Depends(get_db)):
    db.delete(_get(db, TeamPreset, pid))
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
class ProjectIn(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    objective: Optional[str] = Field(default=None, max_length=20000)
    description: Optional[str] = Field(default=None, max_length=20000)
    deliverables: Optional[list[str]] = None
    constraints: Optional[str] = Field(default=None, max_length=20000)
    success_criteria: Optional[str] = Field(default=None, max_length=20000)
    deadline: Optional[date] = None
    template_key: Optional[str] = None
    budget_usd: Optional[float] = None
    origin: Optional[str] = None


def _project_summary(db: Session, p: Project, pend: dict) -> dict:
    run = services.latest_run(db, p.id)
    return {**ser.project(p), "estimated_spend_usd": float(services.project_spend(db, p.id)),
            "pending_approvals": pend.get(p.id, 0), "agents": len(services.team(db, p.id)),
            "run_status": run.status if run else None,
            "needs_input": pend.get(p.id, 0) + (1 if (p.brief or {}).get("questions") and p.status == "draft" else 0)}


@router.get("/projects")
def list_projects(archived: bool = False, include_test: bool = False, q: str = "", db: Session = Depends(get_db)):
    """Projects for the switcher and My Projects. Synthetic test projects are hidden unless asked for."""
    stmt = select(Project).where(Project.archived.is_(archived)).order_by(Project.updated_at.desc())
    if not include_test:
        stmt = stmt.where(Project.origin == "user")
    if q.strip():
        stmt = stmt.where(Project.name.ilike(f"%{q.strip()}%"))
    pend = dict(db.execute(select(ApprovalRequest.project_id, func.count()).where(ApprovalRequest.status == "pending")
                           .group_by(ApprovalRequest.project_id)).all())
    return [_project_summary(db, p, pend) for p in db.scalars(stmt)]


@router.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    if not (body.name or "").strip():
        raise HTTPException(422, "Project name is required")
    if not (body.objective or "").strip():
        raise HTTPException(422, "Describe the objective")
    origin = body.origin or "user"
    if origin not in ("user", "acceptance_test", "scripted_test"):
        raise HTTPException(422, "Unknown origin")
    if origin == "user":
        try:
            services.ensure_name_available(db, body.name)
        except services.NameTaken as e:
            raise HTTPException(409, str(e)) from e
    p = Project(origin=origin, name=body.name.strip(), objective=body.objective.strip(), description=body.description or "",
                deliverables=[d.strip() for d in (body.deliverables or []) if d.strip()],
                constraints=body.constraints or "", success_criteria=body.success_criteria or "",
                deadline=body.deadline, template_key=body.template_key, status="draft")
    db.add(p)
    db.flush()
    b = services.get_budget(db, p.id)
    b.budget_usd = _money(body.budget_usd)
    services.sync_core_requirements(db, p)
    events.emit(db, p.id, "project_created", f"Project “{p.name}” created")
    db.commit()
    return ser.project(p)


@router.get("/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_db)):
    return ser.project(_get(db, Project, pid))


@router.patch("/projects/{pid}")
def update_project(pid: str, body: ProjectIn, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    data = body.model_dump(exclude_unset=True)
    for k in ("name", "objective", "description", "constraints", "success_criteria", "deadline", "template_key"):
        if k in data:
            setattr(p, k, data[k] if data[k] is not None else ("" if k not in ("deadline", "template_key") else None))
    if "deliverables" in data and data["deliverables"] is not None:
        p.deliverables = [d.strip() for d in data["deliverables"] if d.strip()]
    if "budget_usd" in data:
        services.get_budget(db, p.id).budget_usd = _money(data["budget_usd"])
    if not p.name.strip():
        raise HTTPException(422, "Project name is required")
    if "name" in data and p.origin == "user" and not p.archived:
        try:
            services.ensure_name_available(db, p.name, exclude_id=p.id)
        except services.NameTaken as e:
            raise HTTPException(409, str(e)) from e
        if (p.brief or {}).get("name") is not None:
            from .. import discovery

            p.brief = {**p.brief, "name": discovery.item(p.name, "client_edited")}
    services.sync_core_requirements(db, p)
    run = services.latest_run(db, p.id)
    if run is not None and run.status not in RUN_TERMINAL:
        events.emit(db, p.id, "project_updated",
                    "Project details changed during a run; new tasks will see the updated requirements", run_id=run.id)
    db.commit()
    return ser.project(p)


@router.post("/projects/{pid}/archive")
def archive_project(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    run = services.latest_run(db, p.id)
    if run is not None and run.status not in RUN_TERMINAL:
        raise HTTPException(409, "Cancel the active run before archiving")
    p.archived = True
    db.commit()
    return ser.project(p)


@router.post("/projects/{pid}/unarchive")
def unarchive_project(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    if p.origin == "user":
        try:
            services.ensure_name_available(db, p.name, exclude_id=p.id)
        except services.NameTaken as e:
            raise HTTPException(409, f"{e} Rename this project before restoring it.") from e
    p.archived = False
    db.commit()
    return ser.project(p)


@router.delete("/projects/{pid}")
def delete_project(pid: str, db: Session = Depends(get_db)):
    """Permanently deletes the project, its history, uploads and exports."""
    import shutil

    p = _get(db, Project, pid)
    run = services.latest_run(db, p.id)
    if run is not None and run.status not in RUN_TERMINAL and run.lease_owner:
        raise HTTPException(409, "Cancel the active run before deleting")
    services.purge_project(db, p)
    db.commit()
    for d in (settings.uploads_dir / pid, settings.exports_dir / pid):
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@router.get("/projects/{pid}/intake-check")
def intake_check(pid: str, db: Session = Depends(get_db)):
    """Deterministic check for missing intake information (no model call)."""
    p = _get(db, Project, pid)
    hints = []
    if len(p.objective.split()) < 8:
        hints.append({"field": "objective", "question": "Can you describe the desired outcome in a bit more detail?"})
    if not p.deliverables:
        hints.append({"field": "deliverables", "question": "Which deliverables do you expect (e.g. PRD, backlog, code)?"})
    if not p.success_criteria.strip():
        hints.append({"field": "success_criteria", "question": "How will you judge the work as successful?"})
    if not p.constraints.strip():
        hints.append({"field": "constraints", "question": "Are there constraints (technology, policy, audience, length)?"})
    if services.get_budget(db, p.id).budget_usd is None:
        hints.append({"field": "budget_usd", "question": "Do you want a spending budget for this project?"})
    return {"hints": hints, "note": "These are optional; the Project Manager will state assumptions for anything missing."}


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
@router.get("/projects/{pid}/files")
def list_files(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    return [ser.file(f) for f in db.scalars(select(ReferenceFile).where(ReferenceFile.project_id == p.id)
                                            .order_by(ReferenceFile.created_at))]


@router.post("/projects/{pid}/files")
async def upload_file(pid: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    data = await file.read(settings.max_upload_bytes + 1)
    name = filetools.safe_name(file.filename or "upload")
    try:
        mime = filetools.validate(name, data)
    except filetools.FileRejected as e:
        raise HTTPException(422, str(e)) from e
    ex = await asyncio.to_thread(filetools.extract, name, data)
    path, digest = filetools.store(p.id, name, data)
    f = ReferenceFile(project_id=p.id, filename=name, mime_type=mime, size_bytes=len(data), sha256=digest,
                      storage_path=path, extracted_text=ex.text, extraction_status=ex.status, extraction_note=ex.note)
    db.add(f)
    events.emit(db, p.id, "file_uploaded", f"Reference file “{name}” uploaded ({ex.status})", data={"file": name})
    db.commit()
    return ser.file(f)


@router.delete("/projects/{pid}/files/{fid}")
def delete_file(pid: str, fid: str, db: Session = Depends(get_db)):
    from pathlib import Path

    f = _get(db, ReferenceFile, fid)
    if str(f.project_id) != pid:
        raise HTTPException(404, "Not found")
    Path(f.storage_path).unlink(missing_ok=True)
    db.delete(f)
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Team on a project
# ---------------------------------------------------------------------------
KEYWORDS = [
    ("software_architect", r"\b(code|app|application|software|api|backend|frontend|prototype|architecture|cli|tool|system)\b"),
    ("developer", r"\b(code|implement|build|prototype|script|cli|app|tests?)\b"),
    ("research_analyst", r"\b(research|competit\w*|market|literature|benchmark|evidence|landscape)\b"),
    ("business_analyst", r"\b(requirement\w*|prd|user stor\w*|backlog|feature\w*|product|process|stakeholder\w*)\b"),
    ("data_analyst", r"\b(data|csv|metrics?|dataset|analytics|statistic\w*)\b"),
    ("technical_writer", r"\b(document\w*|manual|guide|report|write-?up|handbook)\b"),
]


@router.get("/projects/{pid}/recommendation")
def recommend_team(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    tpl = db.scalar(select(ProjectTemplate).where(ProjectTemplate.key == p.template_key)) if p.template_key else None
    reasons: dict[str, str] = {"project_manager": "Plans, delegates and consolidates (required)."}
    if tpl is not None and tpl.key != "custom":
        for r in tpl.recommended_roles:
            reasons.setdefault(r, f"Recommended by the {tpl.name} template.")
        basis = f"template: {tpl.name}"
    else:
        text = f"{p.objective} {p.description} {' '.join(p.deliverables)}".lower()
        for role, pat in KEYWORDS:
            m = re.search(pat, text)
            if m:
                reasons.setdefault(role, f"Your objective mentions “{m.group(0)}”.")
        if len(reasons) >= 3:
            reasons.setdefault("qa_reviewer", "Reviews deliverables against acceptance criteria.")
        basis = "keyword heuristic (not an AI judgement) — adjust freely, or ask your Project Manager to propose a team"
    defs = {d.role_key: d for d in db.scalars(select(AgentDefinition).where(AgentDefinition.is_builtin.is_(True)))}
    return {"basis": basis, "roles": [{"role_key": k, "reason": v, "definition": ser.definition(db, defs[k])}
                                      for k, v in reasons.items() if k in defs]}


@router.post("/projects/{pid}/recommendation/ai")
async def recommend_team_ai(pid: str, db: Session = Depends(get_db)):
    """Ask the hired Project Manager to propose the rest of the team (Custom projects)."""
    from ..providers.base import ToolSpec

    p = _get(db, Project, pid)
    pm = services.orchestrator(db, p.id)
    if pm is None:
        raise HTTPException(400, "Hire a Project Manager first")
    defs = list(db.scalars(select(AgentDefinition).where(AgentDefinition.archived.is_(False))))
    roster = "\n".join(f"- {d.role_key}: {d.role} — {d.description}" for d in defs)
    tool = ToolSpec("recommend_team", "Recommend which roles to hire.", {
        "type": "object", "additionalProperties": False, "required": ["roles"],
        "properties": {"roles": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                                            "required": ["role_key", "reason"],
                                                            "properties": {"role_key": {"type": "string"},
                                                                           "reason": {"type": "string"}}}}}})
    msg = (f"Project objective: {p.objective}\nDeliverables: {', '.join(p.deliverables) or '(unspecified)'}\n\n"
           f"Available roles:\n{roster}\n\nRecommend the smallest team (besides yourself) that can deliver this well. "
           "Call recommend_team.")
    try:
        res = await call_model(db, project=p, run=None, agent=pm, task=None, purpose="recommendation",
                               system=f"You are {pm.display_name}, a project manager staffing a project.",
                               messages=[{"role": "user", "content": [{"type": "text", "text": msg}]}], tools=[tool])
    except ProviderError as e:
        raise HTTPException(502, e.user_message()) from e
    if isinstance(res, Blocked):
        raise HTTPException(402, res.block.detail)
    call = next((c for c in res.tool_calls if c.name == "recommend_team"), None)
    keys = {d.role_key: d for d in defs}
    roles = [{"role_key": r["role_key"], "reason": r.get("reason", ""), "definition": ser.definition(db, keys[r["role_key"]])}
             for r in (call.input.get("roles", []) if call else []) if r.get("role_key") in keys]
    return {"basis": f"proposed by {pm.display_name} ({pm.model_id})", "roles": roles}


def _hire(db: Session, p: Project, d: Optional[AgentDefinition], body: AgentIn) -> ProjectAgent:
    data = body.model_dump(exclude_unset=True)
    _validate_agent_fields(db, data)
    top = db.scalar(select(func.max(ProjectAgent.desk_index)).where(ProjectAgent.project_id == p.id))
    idx = 0 if top is None else top + 1
    a = ProjectAgent(project_id=p.id, agent_definition_id=d.id if d else None,
                     display_name=body.name or (d.name if d else "New hire"), role=body.role or (d.role if d else "Specialist"),
                     role_key=body.role_key or (d.role_key if d else _slugify(body.role or "specialist")),
                     description=body.description if body.description is not None else (d.description if d else ""),
                     instructions=body.instructions if body.instructions is not None else (d.instructions if d else ""),
                     avatar=body.avatar or (d.avatar if d else {}), provider=body.provider or (d.provider if d else catalog.DEFAULT_MODEL[0]),
                     model_id=body.model_id or (d.model_id if d else catalog.DEFAULT_MODEL[1]),
                     effort=body.effort or (d.effort if d else "medium"),
                     max_output_tokens=body.max_output_tokens or (d.max_output_tokens if d else 16000),
                     max_calls_per_task=body.max_calls_per_task or (d.max_calls_per_task if d else 12),
                     spend_limit_usd=_money(body.spend_limit_usd), desk_index=idx)
    if a.role_key == "project_manager" and services.orchestrator(db, p.id) is None:
        a.is_orchestrator = True
    if body.is_orchestrator:
        for other in services.team(db, p.id):
            other.is_orchestrator = False
        a.is_orchestrator = True
    db.add(a)
    db.flush()
    if body.tools is not None:
        tools = body.tools
    elif d is not None:
        tools = [t.tool_key for t in db.scalars(select(ToolPermission).where(ToolPermission.agent_definition_id == d.id))]
    else:
        tools = catalog.BASE
    services.set_agent_permissions(db, a, tools)
    events.emit(db, p.id, "agent_hired", f"{a.display_name} joined the team as {a.role}", agent_id=a.id, agent_status="idle")
    return a


@router.get("/projects/{pid}/agents")
def list_agents(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    return [ser.agent(db, a) for a in services.team(db, p.id)]


@router.post("/projects/{pid}/agents")
def hire_agent(pid: str, body: AgentIn, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    d = _get(db, AgentDefinition, body.agent_definition_id) if body.agent_definition_id else None
    if d is None and not (body.name and body.role):
        raise HTTPException(422, "Choose an agent from the library or give a name and role")
    if len(services.team(db, p.id)) >= 12:
        raise HTTPException(422, "A team can have at most 12 agents")
    a = _hire(db, p, d, body)
    db.commit()
    return ser.agent(db, a)


class PresetApply(BaseModel):
    preset_id: str


@router.post("/projects/{pid}/agents/apply-preset")
def apply_preset(pid: str, body: PresetApply, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    preset = _get(db, TeamPreset, body.preset_id)
    have = {a.agent_definition_id for a in services.team(db, p.id)}
    for did in preset.agent_definition_ids:
        d = db.get(AgentDefinition, uuid.UUID(did))
        if d and d.id not in have:
            _hire(db, p, d, AgentIn())
    db.commit()
    return [ser.agent(db, a) for a in services.team(db, p.id)]


class SaveTeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


@router.post("/projects/{pid}/team/save-preset")
def save_team(pid: str, body: SaveTeamIn, db: Session = Depends(get_db)):
    """Save this project's team as reusable agent definitions + a team preset."""
    p = _get(db, Project, pid)
    ids = []
    for a in services.team(db, p.id):
        d = AgentDefinition(name=a.display_name, role=a.role, role_key=a.role_key, description=a.description,
                            instructions=a.instructions, avatar=a.avatar, provider=a.provider, model_id=a.model_id,
                            effort=a.effort, max_output_tokens=a.max_output_tokens, max_calls_per_task=a.max_calls_per_task)
        db.add(d)
        db.flush()
        for k in services.agent_permissions(db, a):
            db.add(ToolPermission(agent_definition_id=d.id, tool_key=k))
        ids.append(str(d.id))
    preset = TeamPreset(name=body.name, description=body.description, agent_definition_ids=ids)
    db.add(preset)
    db.commit()
    return _preset(preset)


@router.patch("/projects/{pid}/agents/{aid}")
def update_agent(pid: str, aid: str, body: AgentIn, db: Session = Depends(get_db)):
    a = _get(db, ProjectAgent, aid)
    if str(a.project_id) != pid:
        raise HTTPException(404, "Not found")
    data = body.model_dump(exclude_unset=True)
    _validate_agent_fields(db, data)
    old_model = (a.provider, a.model_id)
    for k, attr in (("name", "display_name"), ("role", "role"), ("description", "description"),
                    ("instructions", "instructions"), ("avatar", "avatar"), ("provider", "provider"),
                    ("model_id", "model_id"), ("effort", "effort"), ("max_output_tokens", "max_output_tokens"),
                    ("max_calls_per_task", "max_calls_per_task")):
        if k in data and data[k] is not None:
            setattr(a, attr, data[k])
    if "spend_limit_usd" in data:
        a.spend_limit_usd = _money(data["spend_limit_usd"])
    if body.tools is not None:
        services.set_agent_permissions(db, a, body.tools)
    if body.is_orchestrator:
        for other in services.team(db, a.project_id):
            other.is_orchestrator = other.id == a.id
    if (a.provider, a.model_id) != old_model:
        events.emit(db, a.project_id, "model_changed",
                    f"{a.display_name} now uses {a.provider}/{a.model_id}; in-progress work switches at its next safe checkpoint",
                    agent_id=a.id, data={"from": list(old_model), "to": [a.provider, a.model_id]})
    db.commit()
    return ser.agent(db, a)


@router.delete("/projects/{pid}/agents/{aid}")
def remove_agent(pid: str, aid: str, db: Session = Depends(get_db)):
    a = _get(db, ProjectAgent, aid)
    if str(a.project_id) != pid:
        raise HTTPException(404, "Not found")
    active = db.scalar(select(func.count()).select_from(Task).where(
        Task.assigned_agent_id == a.id, Task.status.notin_(["completed", "failed", "cancelled", "skipped"])))
    if active:
        raise HTTPException(409, f"{a.display_name} has unfinished tasks; cancel the run or wait")
    a.removed = True
    a.is_orchestrator = False
    events.emit(db, a.project_id, "agent_removed", f"{a.display_name} left the team", agent_id=a.id, agent_status="idle")
    db.commit()
    return {"ok": True}


@router.get("/projects/{pid}/agents/{aid}/detail")
def agent_detail(pid: str, aid: str, db: Session = Depends(get_db)):
    a = _get(db, ProjectAgent, aid)
    if str(a.project_id) != pid:
        raise HTTPException(404, "Not found")
    evs = list(db.scalars(select(AgentEvent).where(AgentEvent.agent_id == a.id).order_by(AgentEvent.seq.desc()).limit(40)))
    tasks = list(db.scalars(select(Task).where(Task.assigned_agent_id == a.id).order_by(Task.created_at.desc()).limit(20)))
    arts = list(db.scalars(select(Artifact).where(Artifact.owner_agent_id == a.id)))
    hos = list(db.scalars(select(AgentHandoff).where((AgentHandoff.from_agent_id == a.id) | (AgentHandoff.to_agent_id == a.id))
                          .order_by(AgentHandoff.created_at.desc()).limit(20)))
    usage = db.execute(select(func.coalesce(func.sum(UsageRecord.input_tokens), 0), func.coalesce(func.sum(UsageRecord.output_tokens), 0),
                              func.count()).where(UsageRecord.agent_id == a.id)).one()
    blockers = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.agent_id == a.id, ApprovalRequest.status == "pending")))
    current = db.get(Task, a.current_task_id) if a.current_task_id else None
    focus = current or _open_task(db, a)
    waiting_on, deps = [], []
    if focus is not None:
        names = {x.id: x.display_name for x in services.team(db, a.project_id)}
        for d in services.dependencies(db, focus.id):
            deps.append({"id": str(d.id), "title": d.title, "status": d.status, "agent": names.get(d.assigned_agent_id)})
            if d.status not in ("completed", "skipped"):
                waiting_on.append({"kind": "teammate", "task": d.title, "agent": names.get(d.assigned_agent_id),
                                   "status": d.status})
        if focus.status == "waiting_subtask":
            for sub in db.scalars(select(Task).where(Task.parent_task_id == focus.id,
                                                     Task.status.notin_(["completed", "skipped", "cancelled"]))):
                waiting_on.append({"kind": "teammate", "task": sub.title, "agent": names.get(sub.assigned_agent_id),
                                   "status": sub.status})
    if blockers:
        waiting_on += [{"kind": "client", "task": b.title, "agent": None, "status": "pending"} for b in blockers]
    latest = None
    if arts:
        art = max(arts, key=lambda x: x.updated_at)
        lv = services.latest_version(db, art.id)
        latest = {"artifact_id": str(art.id), "name": art.name, "version": art.current_version,
                  "summary": (lv.summary if lv else "") or art.summary, "updated_at": art.updated_at.isoformat()}
    return {"agent": ser.agent(db, a), "current_task": ser.task(db, current) if current else None,
            "focus_task": ser.task(db, focus) if focus else None, "waiting_on": waiting_on, "dependencies": deps,
            "latest_output": latest,
            "recent_events": [events.event_to_dict(e) for e in evs], "tasks": [ser.task(db, t) for t in tasks],
            "artifacts": [ser.artifact(db, x) for x in arts], "handoffs": [ser.handoff(h) for h in hos],
            "usage": {"input_tokens": int(usage[0]), "output_tokens": int(usage[1]), "calls": int(usage[2]),
                      "estimated_spend_usd": float(services.agent_spend(db, a.id))},
            "blockers": [ser.approval(b) for b in blockers]}


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------
class BudgetIn(BaseModel):
    budget_usd: Optional[float] = None
    warning_threshold_pct: Optional[int] = Field(default=None, ge=1, le=100)
    approval_threshold_usd: Optional[float] = None
    max_model_calls_per_run: Optional[int] = Field(default=None, ge=1, le=5000)
    max_concurrency: Optional[int] = Field(default=None, ge=1, le=8)
    max_delegation_depth: Optional[int] = Field(default=None, ge=0, le=4)
    max_review_iterations: Optional[int] = Field(default=None, ge=0, le=5)
    task_timeout_seconds: Optional[int] = Field(default=None, ge=30, le=7200)


def _budget(b) -> dict:
    return {"budget_usd": ser.money(b.budget_usd), "warning_threshold_pct": b.warning_threshold_pct,
            "approval_threshold_usd": ser.money(b.approval_threshold_usd),
            "approval_threshold_acknowledged": b.approval_threshold_acknowledged,
            "max_model_calls_per_run": b.max_model_calls_per_run, "max_concurrency": b.max_concurrency,
            "max_delegation_depth": b.max_delegation_depth, "max_review_iterations": b.max_review_iterations,
            "task_timeout_seconds": b.task_timeout_seconds}


@router.get("/projects/{pid}/budget")
def get_budget(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    b = services.get_budget(db, p.id)
    db.commit()
    return _budget(b)


@router.put("/projects/{pid}/budget")
def put_budget(pid: str, body: BudgetIn, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    b = services.get_budget(db, p.id)
    data = body.model_dump(exclude_unset=True)
    for k in ("budget_usd", "approval_threshold_usd"):
        if k in data:
            setattr(b, k, _money(data[k]))
    for k in ("warning_threshold_pct", "max_model_calls_per_run", "max_concurrency", "max_delegation_depth",
              "max_review_iterations", "task_timeout_seconds"):
        if data.get(k) is not None:
            setattr(b, k, data[k])
    if "budget_usd" in data:
        b.warning_emitted = False
    events.emit(db, p.id, "budget_updated", "Budget controls updated", data=_budget(b))
    db.commit()
    return _budget(b)


# ---------------------------------------------------------------------------
# State snapshot, runs, controls
# ---------------------------------------------------------------------------
@router.get("/projects/{pid}/state")
def project_state(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    runs = list(db.scalars(select(ProjectRun).where(ProjectRun.project_id == p.id).order_by(ProjectRun.run_number.desc())))
    current = runs[0] if runs else None
    tasks = services.run_tasks(db, current.id) if current else []
    pending = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.project_id == p.id,
                                                            ApprovalRequest.status == "pending")
                              .order_by(ApprovalRequest.created_at)))
    last = db.scalar(select(func.max(AgentEvent.seq)).where(AgentEvent.project_id == p.id)) or 0
    reqs = services.active_requirements(db, p.id)
    b = services.get_budget(db, p.id)
    from .workspace import INFO_EVENTS

    notable = db.scalar(select(AgentEvent).where(AgentEvent.project_id == p.id, AgentEvent.type.in_(
        INFO_EVENTS | {"task_completed", "artifact_written", "approval_requested", "plan_proposed", "run_started",
                       "brief_updated", "rework_requested"})).order_by(AgentEvent.seq.desc()))
    db.commit()
    return {
        "project": ser.project(p), "budget": _budget(b),
        "agents": [ser.agent(db, a) for a in services.team(db, p.id)],
        "runs": [ser.run(r) for r in runs], "current_run": ser.run(current) if current else None,
        "tasks": [ser.task(db, t) for t in tasks], "pending_approvals": [ser.approval(a) for a in pending],
        "requirements": [requirements.to_dict(db, r) for r in reqs]
                        + [requirements.to_dict(db, r) for r in requirements.superseded(db, p.id)],
        "estimated_spend_usd": float(services.project_spend(db, p.id)), "last_event_seq": last,
        "last_update": events.event_to_dict(notable) if notable else None,
        "brief": (p.brief or None),
    }


class RunIn(BaseModel):
    kind: str = "initial"
    feedback: str = ""


@router.post("/projects/{pid}/runs")
def start_run(pid: str, body: RunIn, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    if p.archived:
        raise HTTPException(409, "Unarchive the project first")
    for a in services.team(db, p.id):
        if a.provider not in providers.available_providers():
            raise HTTPException(400, f"{a.display_name}'s provider is unavailable")
        if a.provider != providers.TEST_PROVIDER and credentials.load_secret(a.provider) is None:
            raise HTTPException(400, f"{a.display_name} uses {a.provider}, but no API key is configured. Add one in Settings.")
    try:
        run = decisions.start_run(db, p, kind="revision" if body.kind == "revision" else "initial", feedback=body.feedback)
    except decisions.DecisionError as e:
        raise HTTPException(400, str(e)) from e
    db.commit()
    return ser.run(run)


@router.post("/runs/{rid}/{action}")
def control_run(rid: str, action: str, db: Session = Depends(get_db)):
    if action not in ("pause", "resume", "cancel"):
        raise HTTPException(404, "Unknown action")
    run = _get(db, ProjectRun, rid)
    try:
        decisions.request_control(db, run, action)
    except decisions.DecisionError as e:
        raise HTTPException(400, str(e)) from e
    db.commit()
    return ser.run(run)


@router.get("/runs/{rid}/tasks")
def run_tasks(rid: str, db: Session = Depends(get_db)):
    run = _get(db, ProjectRun, rid)
    return [ser.task(db, t) for t in services.run_tasks(db, run.id)]


@router.get("/tasks/{tid}/executions")
def task_executions(tid: str, db: Session = Depends(get_db)):
    """Advanced view: the persisted agent conversation (secrets redacted)."""
    t = _get(db, Task, tid)
    exs = list(db.scalars(select(TaskExecution).where(TaskExecution.task_id == t.id).order_by(TaskExecution.attempt)))
    def clean(conv):
        out = []
        for m in conv:
            out.append({"role": m["role"], "content": events._redact_obj(m["content"])})
        return out
    return [{"id": str(e.id), "attempt": e.attempt, "provider": e.provider, "model_id": e.model_id, "status": e.status,
             "model_calls": e.model_calls, "error": e.error, "started_at": e.started_at.isoformat(),
             "ended_at": e.ended_at.isoformat() if e.ended_at else None, "conversation": clean(e.conversation)}
            for e in exs]


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------
@router.get("/projects/{pid}/approvals")
def list_approvals(pid: str, status: Optional[str] = None, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    q = select(ApprovalRequest).where(ApprovalRequest.project_id == p.id)
    if status:
        q = q.where(ApprovalRequest.status == status)
    return [ser.approval(a) for a in db.scalars(q.order_by(ApprovalRequest.created_at.desc()))]


class DecisionIn(BaseModel):
    decision: str
    comment: str = ""
    answer: Optional[str] = None
    plan: Optional[dict] = None
    approved_tools: Optional[list[str]] = None
    answers: Optional[dict[str, str]] = None
    option: Optional[str] = None
    for_whole_run: Optional[bool] = None
    budget_usd: Optional[float] = None
    max_model_calls_per_run: Optional[int] = None
    agent_limit_usd: Optional[float] = None
    acknowledge_threshold: Optional[bool] = None
    task_ids: Optional[list[str]] = None
    qa_review: Optional[bool] = None
    supersede_ids: Optional[list[str]] = None


@router.post("/approvals/{aid}/decide")
def decide(aid: str, body: DecisionIn, db: Session = Depends(get_db)):
    ap = db.scalar(select(ApprovalRequest).where(ApprovalRequest.id == _uuid(aid)).with_for_update())
    if ap is None:
        raise HTTPException(404, "Not found")
    try:
        decisions.decide(db, ap, body.decision, body.model_dump(exclude_unset=True))
    except (decisions.DecisionError, services.DomainError) as e:
        db.rollback()
        raise HTTPException(400, str(e)) from e
    db.commit()
    return ser.approval(ap)


@router.post("/tasks/{tid}/{action}")
def task_action(tid: str, action: str, db: Session = Depends(get_db)):
    """Targeted recovery for a failed task outside the approval card."""
    t = _get(db, Task, tid)
    if t.status != "failed":
        raise HTTPException(409, "Only failed tasks can be retried or skipped")
    ap = db.scalar(select(ApprovalRequest).where(ApprovalRequest.task_id == t.id, ApprovalRequest.kind == "task_failure",
                                                 ApprovalRequest.status == "pending"))
    if action not in ("retry", "skip"):
        raise HTTPException(404, "Unknown action")
    run = db.get(ProjectRun, t.run_id)
    if ap is not None:
        decisions.decide(db, ap, "approve", {"option": action})
    else:
        if action == "retry":
            t.max_retries = t.retry_count + 1
            from ..state_machine import transition_task

            transition_task(t, "ready")
        else:
            from ..state_machine import transition_task

            transition_task(t, "skipped")
        decisions.wake(db, run)
    db.commit()
    return ser.task(db, t)


# ---------------------------------------------------------------------------
# Client <-> Project Manager messages
# ---------------------------------------------------------------------------
INTENTS = {"auto", "question", "requirement_change", "task_feedback", "scope_change", "cancel"}
CONSEQUENTIAL = {"requirement_change", "scope_change", "cancel", "approval"}
_HEUR = [
    ("cancel", re.compile(r"\b(cancel|stop) (the )?(run|project|work)\b", re.I)),
    ("requirement_change", re.compile(r"\b(instead|no longer|change (the|a|this) requirement|must now|should now|"
                                      r"actually,? (it|we|they) (should|must|need))\b", re.I)),
    ("scope_change", re.compile(r"\b(also (add|build|include)|add (a|another) (new )?deliverable|expand the scope|out of scope)\b", re.I)),
    ("approval", re.compile(r"^\s*(approve[ds]?|looks good,? go ahead|go ahead|reject(ed)?|i approve)\b", re.I)),
]


def classify_message(text: str) -> str:
    """Deterministic first pass (no model): a hint only. Consequential intents are never applied
    from a chat message; the client confirms them through the structured mechanisms."""
    for intent, rx in _HEUR:
        if rx.search(text):
            return intent
    return "question"


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    intent: str = "auto"
    task_id: Optional[str] = None
    agent_id: Optional[str] = None  # a direct message to one agent (default: the project thread with the PM)


def _msg(m: Message) -> dict:
    return {"id": str(m.id), "sender": m.sender, "agent_id": str(m.agent_id) if m.agent_id else None,
            "channel": m.channel, "intent": m.intent, "content": m.content, "task_id": str(m.task_id) if m.task_id else None,
            "data": m.data, "created_at": m.created_at.isoformat()}


@router.get("/projects/{pid}/messages")
def list_messages(pid: str, channel: str = "client", agent_id: Optional[str] = None, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    q = select(Message).where(Message.project_id == p.id, Message.channel == channel)
    if agent_id:
        q = q.where(Message.agent_id == _uuid(agent_id))
    return [_msg(m) for m in db.scalars(q.order_by(Message.created_at).limit(500))]


@router.get("/projects/{pid}/threads")
def list_threads(pid: str, db: Session = Depends(get_db)):
    """The project's conversations: the team thread (the PM is the default contact), one direct
    thread per agent, and the discovery conversation. Each lists open questions from that agent."""
    p = _get(db, Project, pid)
    pend = list(db.scalars(select(ApprovalRequest).where(ApprovalRequest.project_id == p.id,
                                                         ApprovalRequest.status == "pending")))
    last = {}
    for m in db.scalars(select(Message).where(Message.project_id == p.id).order_by(Message.created_at)):
        key = "team" if m.channel == "client" else f"agent:{m.agent_id}" if m.channel == "direct" else m.channel
        last[key] = m
    out = [{"id": "team", "kind": "team", "title": "Project team", "agent_id": None,
            "pending": sum(1 for a in pend if a.kind != "clarification" or a.agent_id is None
                           or (services.orchestrator(db, p.id) and a.agent_id == services.orchestrator(db, p.id).id)),
            "last": _msg(last["team"]) if "team" in last else None}]
    for a in services.team(db, p.id):
        if a.is_orchestrator:
            continue
        k = f"agent:{a.id}"
        out.append({"id": k, "kind": "agent", "title": a.display_name, "agent_id": str(a.id), "role": a.role,
                    "pending": sum(1 for x in pend if x.agent_id == a.id), "last": _msg(last[k]) if k in last else None})
    if "discovery" in last:
        out.append({"id": "discovery", "kind": "discovery", "title": "Project discovery", "agent_id": None,
                    "pending": 0, "last": _msg(last["discovery"])})
    return out


@router.post("/projects/{pid}/messages")
async def post_message(pid: str, body: MessageIn, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    if body.intent not in INTENTS:
        raise HTTPException(422, f"intent must be one of {sorted(INTENTS)}")
    run = services.latest_run(db, p.id)
    active = run is not None and run.status not in RUN_TERMINAL
    pm = services.orchestrator(db, p.id)
    target = _get(db, ProjectAgent, body.agent_id) if body.agent_id else None
    if target is not None and target.project_id != p.id:
        raise HTTPException(404, "Not found")
    direct = target is not None and not target.is_orchestrator
    speaker = target if direct else pm
    channel = "direct" if direct else "client"
    um = Message(project_id=p.id, run_id=run.id if run else None, sender="user", channel=channel, intent=body.intent,
                 content=body.content, task_id=_uuid(body.task_id) if body.task_id else None,
                 agent_id=target.id if direct else None)
    db.add(um)
    reply: Optional[str] = None
    reply_data: dict = {}
    try:
        if body.intent == "auto":
            # 1) An open question from this agent: the message is the answer (it updates that record).
            q = select(ApprovalRequest).where(ApprovalRequest.project_id == p.id, ApprovalRequest.status == "pending",
                                              ApprovalRequest.kind == "clarification")
            q = q.where(ApprovalRequest.agent_id == speaker.id) if speaker is not None else q
            open_q = list(db.scalars(q.order_by(ApprovalRequest.created_at)))
            if len(open_q) == 1 and classify_message(body.content) == "question":
                ap = open_q[0]
                decisions.decide(db, ap, "answer", {"decision": "answer", "answer": body.content})
                um.intent = "answer"
                um.data = {"approval_id": str(ap.id)}
                reply = f"Answer recorded for “{ap.title}”. The task continues with it."
                reply_data = {"answered_approval_id": str(ap.id), "system": True}
            else:
                reply, detected, reply_data = await _agent_answer(db, p, speaker, body.content, direct=direct)
                um.intent = "question" if detected not in CONSEQUENTIAL else detected
                # 2) A direct instruction to a specialist with work in progress is recorded on that task.
                if direct and detected in ("question", "task_instruction") and speaker is not None:
                    t = _open_task(db, speaker)
                    if t is not None and detected == "task_instruction":
                        t.context_notes = [*t.context_notes, f"From the client (message): {body.content}"]
                        um.task_id = t.id
                        reply_data["recorded_on_task"] = {"id": str(t.id), "title": t.title}
        elif body.intent == "cancel":
            if not active:
                raise HTTPException(400, "There is no active run to cancel")
            decisions.request_control(db, run, "cancel")
            reply = "Understood — I've stopped the team. Completed deliverables are kept."
        elif body.intent == "requirement_change":
            change = ProjectRequirement(project_id=p.id, kind="change", text=body.content, source="client_message",
                                        run_id=run.id if run else None)
            db.add(change)
            db.flush()
            # 1) Which existing requirement items does the change replace? (PM proposal; client confirms)
            proposal = await requirements.propose_supersession(db, p, change)
            # 2) Evidence-based impact from task-requirement links and artifact lineage, per candidate,
            #    so the card's defaults follow the client's supersession choice.
            from .. import traceability

            cand_ids = [c["id"] for c in proposal["candidates"]]
            proposed_ids = [c["id"] for c in proposal["candidates"] if c["proposed"]]
            impacted, impact_by_candidate = [], {}
            if active:
                every = traceability.impact(db, run.id, cand_ids)
                chosen = {e["id"]: e for e in traceability.impact(db, run.id, proposed_ids)["tasks"]}
                for c in cand_ids:
                    impact_by_candidate[c] = [e["id"] for e in traceability.impact(db, run.id, [c])["tasks"]
                                              if e["action"] in ("rework", "rework_after")]
                # Listed: work affected under the PROPOSED supersession, then work affected only if the client
                # also replaces another candidate (so the card can follow their choice).
                impacted = [e for e in chosen.values() if e["impact"] != "unaffected"]
                cand_ref = {c["id"]: c["ref"] for c in proposal["candidates"]}
                for e in every["tasks"]:
                    if e["id"] not in chosen or chosen[e["id"]]["impact"] == "unaffected":
                        if e["impact"] in ("direct", "downstream"):
                            via = [cand_ref.get(c) for c, ids in impact_by_candidate.items() if e["id"] in ids]
                            impacted.append({**e, "impact": "if_selected", "action": "if_selected",
                                             "reason": f"only if you also replace {', '.join(r for r in via if r)}"})
                listed = {e["id"] for e in impacted}
                preserved = [e["title"] for e in chosen.values() if e["impact"] == "unaffected" and e["id"] not in listed]
                if not proposed_ids:
                    # Nothing is replaced: the change ADDS a rule. Lineage cannot say which finished work should
                    # incorporate it, so every completed/in-flight work task is surfaced as uncertain - never omitted.
                    impacted = [{**e, "impact": "uncertain", "action": "confirm",
                                 "reason": "the change adds a requirement that replaces nothing; select tasks that should incorporate it"}
                                for e in every["tasks"] if e["status"] == "completed" or e["status"] in traceability.IN_FLIGHT]
                    preserved = []
            else:
                preserved = []
            at_risk = traceability.artifacts_at_risk(db, p.id, proposed_ids)
            stale_docs = []
            if run is not None and run.status in RUN_TERMINAL:
                stale_docs = [a for a in services.project_artifacts(db, p.id, include_working=False) if a.category != "plan"]
                for a in stale_docs:
                    a.stale, a.stale_reason = True, f"[note] predates requirement change {change.ref}; request a revision"
            proposed_refs = [c["ref"] for c in proposal["candidates"] if c["proposed"]]
            # G1: an estimated rework cost per listed task (from recorded usage; no model call), so the
            # card can total whatever the client selects and compare it with the remaining budget.
            for e in impacted:
                t = db.get(Task, uuid.UUID(e["id"]))
                if t is not None:
                    e["estimate"] = services.rework_estimate(db, t)
            remaining = services.budget_remaining(db, p.id)
            if proposal["candidates"] or impacted:
                services.create_approval(
                    db, project_id=p.id, run_id=run.id if run else None, kind="requirement_change",
                    title=f"Confirm the impact of requirement change {change.ref}",
                    explanation=f"{change.ref}: {body.content}\n\nConfirm which existing requirements it replaces (they are "
                                "kept in history but no longer followed) and which tasks to rework. Tasks not yet started "
                                "follow the change automatically; in-progress tasks are reworked after they finish.",
                    payload={"change": body.content, "change_requirement_id": str(change.id), "change_ref": change.ref,
                             "candidates": proposal["candidates"], "proposal_method": proposal["method"],
                             "proposal_rationale": proposal["rationale"], "tasks": impacted,
                             "impact_by_candidate": impact_by_candidate, "preserved_tasks": preserved,
                             "artifacts_at_risk": at_risk,
                             "budget_remaining_usd": str(remaining.quantize(Decimal("0.0001"))) if remaining is not None else None})
            parts = [f"Recorded the change as {change.ref}."]
            if proposed_refs:
                who = "I" if proposal["method"] == "project_manager" else "A keyword check"
                parts.append(f"{who} propose{'s' if who != 'I' else ''} that it replaces {', '.join(proposed_refs)} — please confirm.")
            elif proposal["candidates"]:
                parts.append("I found no existing requirement it clearly replaces — please check the list.")
            n_rework = sum(1 for e in impacted if e["action"] in ("rework", "rework_after"))
            n_unc = sum(1 for e in impacted if e["impact"] == "uncertain")
            additive = active and not proposed_ids
            if n_rework:
                parts.append(f"Based on task-requirement links and artifact lineage, {n_rework} task(s) need rework"
                             f"{f' and {len(at_risk)} deliverable(s) would become stale' if at_risk else ''}; "
                             f"{len(preserved)} completed or planned task(s) are unaffected and will be kept.")
            if n_unc and additive:
                parts.append(f"It doesn't replace an existing requirement, so lineage can't show which finished work must "
                             f"incorporate it: I've listed {n_unc} completed or in-progress task(s) — choose any to rework.")
            elif n_unc:
                parts.append(f"{n_unc} task(s) have no requirement links, so I can't tell if they're affected — please confirm.")
            if stale_docs:
                parts.append(f"The run has already finished, so the {len(stale_docs)} delivered document(s) predate the change "
                             "and are marked stale; request a revision to update them.")
            elif not n_rework and not n_unc:
                parts.append("No completed or in-progress work depends on the replaced requirements; upcoming work will follow the change.")
            reply = " ".join(parts)
        elif body.intent == "task_feedback":
            if not body.task_id:
                raise HTTPException(422, "Choose the task the feedback is for")
            t = _get(db, Task, body.task_id)
            if t.status == "completed" and active:
                decisions.create_rework(db, run, t, f"Client feedback: {body.content}")
                decisions.wake(db, run)
                reply = f"I've asked the team to rework “{t.title}” with your feedback."
            elif t.status in ("pending", "ready", "paused", "waiting_approval", "waiting_subtask", "running"):
                t.context_notes = [*t.context_notes, body.content]
                reply = f"Noted — “{t.title}” will take your feedback into account" + (
                    " the next time it starts." if t.status == "running" else ".")
            else:
                db.add(ProjectRequirement(project_id=p.id, kind="feedback", text=f"On “{t.title}”: {body.content}",
                                          source="client_message"))
                reply = "Noted. The run has finished; request a revision on the deliverables to apply this feedback."
        elif body.intent == "scope_change":
            db.add(ProjectRequirement(project_id=p.id, kind="change", text=f"Scope change: {body.content}",
                                      source="client_message", run_id=run.id if run else None))
            services.create_approval(
                db, project_id=p.id, run_id=run.id if run else None, kind="scope_change", title="Confirm scope change",
                explanation=f"{body.content}\n\nThis exceeds the approved statement of work. Approving stops the current run "
                            "(completed work is kept) so a revised plan can be proposed for your approval.",
                payload={"change": body.content})
            reply = "That changes the approved scope, so it needs your confirmation before I re-plan."
        else:
            reply = await _pm_answer(db, p, pm, body.content)
    except decisions.DecisionError as e:
        raise HTTPException(400, str(e)) from e
    if reply:
        system_note = reply_data.get("system", False)
        db.add(Message(project_id=p.id, run_id=run.id if run else None,
                       sender="system" if (system_note or not speaker) else "agent",
                       agent_id=speaker.id if speaker else None, channel=channel, intent=um.intent, content=reply,
                       data=reply_data))
    db.commit()
    return {"reply": reply, "intent": um.intent, "data": reply_data}


def _open_task(db: Session, agent: ProjectAgent) -> Optional[Task]:
    if agent.current_task_id:
        t = db.get(Task, agent.current_task_id)
        if t is not None and t.status not in ("completed", "failed", "cancelled", "skipped"):
            return t
    return db.scalar(select(Task).where(Task.assigned_agent_id == agent.id,
                                        Task.status.in_(["pending", "ready", "running", "paused", "waiting_approval",
                                                         "waiting_subtask"])).order_by(Task.sort_order))


REPLY_TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "description": "Your answer to the client, brief and accurate."},
        "detected_intent": {"type": "string", "enum": ["question", "discussion", "clarification", "task_instruction",
                                                       "requirement_change", "scope_change", "approval", "cancel"],
                            "description": "What the client's message is, operationally."},
        "rationale": {"type": "string"},
    },
    "required": ["reply", "detected_intent"],
}


async def _agent_answer(db: Session, p: Project, agent: Optional[ProjectAgent], text: str,
                        direct: bool) -> tuple[str, str, dict]:
    """The agent answers from recorded project status and classifies the message. A consequential
    intent is returned as a SUGGESTION for the client to confirm; nothing is applied from chat."""
    from ..providers.base import ToolSpec

    heuristic = classify_message(text)
    if agent is None:
        return "Hire a Project Manager to ask questions about the project.", heuristic, {}
    run = services.latest_run(db, p.id)
    tasks = services.run_tasks(db, run.id) if run else []
    status = "\n".join(f"- [{t.status}] {t.title}" + (" (yours)" if t.assigned_agent_id == agent.id else "")
                       for t in tasks) or "(no tasks yet)"
    arts = "\n".join(f"- {a.name} v{a.current_version}" for a in services.project_artifacts(db, p.id)) or "(none)"
    ctx = (f"Project: {p.name}\nRequirements:\n{requirements.context_block(db, p.id)}\n"
           f"Run status: {run.status if run else 'not started'}\nTasks:\n{status}\nDeliverables:\n{arts}\n\n"
           f"Client message: {text}")
    role = "the client's project manager" if not direct else f"the team's {agent.role}"
    tool = ToolSpec("reply_to_client", "Reply to the client and classify their message.", REPLY_TOOL_SCHEMA)
    detected, data = heuristic, {}
    try:
        res = await call_model(db, project=p, run=None, agent=agent, task=None, purpose="chat",
                               system=f"You are {agent.display_name}, {role}. Answer briefly and accurately from the "
                                      "project status given. Do not invent progress. Never claim to have changed "
                                      "requirements, scope or approvals: the client confirms those separately. "
                                      "Call reply_to_client once.",
                               messages=[{"role": "user", "content": [{"type": "text", "text": ctx}]}], tools=[tool])
    except ProviderError as e:
        return f"(I couldn't answer: {e.user_message()})", heuristic, _suggest(heuristic)
    if isinstance(res, Blocked):
        return f"(Not answered: {res.block.detail})", heuristic, _suggest(heuristic)
    call = next((c for c in res.tool_calls if c.name == "reply_to_client"), None)
    answer = (call.input.get("reply") if call else None) or res.text or "(no answer)"
    if call and call.input.get("detected_intent"):
        detected = call.input["detected_intent"]
        data["classified_by"] = "test provider (not AI)" if agent.provider == "scripted-test" else "model"
    if detected not in CONSEQUENTIAL and heuristic in CONSEQUENTIAL:
        detected = heuristic  # be conservative: surface the structured route if either signal says so
    data.update(_suggest(detected))
    return answer, detected, data


def _suggest(intent: str) -> dict:
    labels = {"requirement_change": "This looks like a requirement change. Record it as a change request so its impact "
                                    "is analysed and confirmed?",
              "scope_change": "This looks like a scope change. Send it for your confirmation before re-planning?",
              "cancel": "Do you want to cancel the current run?",
              "approval": "Approvals are given on the decision cards, not by chat. Open the pending decisions?"}
    return {"suggestion": {"intent": intent, "text": labels[intent]}} if intent in labels else {}


async def _pm_answer(db: Session, p: Project, pm: Optional[ProjectAgent], question: str) -> str:
    if pm is None:
        return "Hire a Project Manager to ask questions about the project."
    run = services.latest_run(db, p.id)
    tasks = services.run_tasks(db, run.id) if run else []
    status = "\n".join(f"- [{t.status}] {t.title}" for t in tasks) or "(no tasks yet)"
    arts = "\n".join(f"- {a.name} v{a.current_version}" for a in services.project_artifacts(db, p.id)) or "(none)"
    ctx = (f"Project: {p.name}\nRequirements:\n{requirements.context_block(db, p.id)}\nRun status: {run.status if run else 'not started'}\n"
           f"Tasks:\n{status}\nDeliverables:\n{arts}\n\nClient question: {question}")
    try:
        res = await call_model(db, project=p, run=None, agent=pm, task=None, purpose="chat",
                               system=f"You are {pm.display_name}, the client's project manager. Answer briefly and "
                                      "accurately from the project status given. Do not invent progress.",
                               messages=[{"role": "user", "content": [{"type": "text", "text": ctx}]}], tools=[])
    except ProviderError as e:
        return f"(I couldn't answer: {e.user_message()})"
    if isinstance(res, Blocked):
        return f"(Not answered: {res.block.detail})"
    return res.text or "(no answer)"


# ---------------------------------------------------------------------------
# Deliverables
# ---------------------------------------------------------------------------
@router.get("/projects/{pid}/artifacts")
def list_artifacts(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    return [ser.artifact(db, a) for a in services.project_artifacts(db, p.id)]


@router.get("/artifacts/{aid}")
def get_artifact(aid: str, version: Optional[int] = None, db: Session = Depends(get_db)):
    a = _get(db, Artifact, aid)
    out = ser.artifact(db, a, content=True)
    vs = list(db.scalars(select(ArtifactVersion).where(ArtifactVersion.artifact_id == a.id).order_by(ArtifactVersion.version)))
    from .. import traceability

    def _inputs(v):
        res = []
        for iid in v.input_version_ids or []:
            try:
                iv = db.get(ArtifactVersion, uuid.UUID(str(iid)))
            except ValueError:
                iv = None
            if iv is not None and iv.artifact_id != v.artifact_id:
                ia = db.get(Artifact, iv.artifact_id)
                res.append(f"{ia.name if ia else '?'} v{iv.version}")
        return res

    out["versions"] = [{"version": v.version, "summary": v.summary, "created_at": v.created_at.isoformat(),
                        "requirement_refs": traceability.refs(db, v.requirement_ids or []), "inputs": _inputs(v),
                        "created_by_agent_id": str(v.created_by_agent_id) if v.created_by_agent_id else None,
                        "created_by_task_id": str(v.created_by_task_id) if v.created_by_task_id else None,
                        "sha256": v.sha256} for v in vs]
    if version is not None:
        v = next((x for x in vs if x.version == version), None)
        if v is None:
            raise HTTPException(404, "Version not found")
        out["content"], out["viewing_version"], out["source_refs"] = v.content, v.version, v.source_refs
    else:
        out["viewing_version"] = a.current_version
    out["findings"] = [ser.finding(f) for f in db.scalars(select(ReviewFinding).where(ReviewFinding.artifact_id == a.id))]
    return out


class AcceptIn(BaseModel):
    status: str  # accepted | revision_requested | pending
    comment: str = ""


@router.post("/artifacts/{aid}/acceptance")
def set_acceptance(aid: str, body: AcceptIn, db: Session = Depends(get_db)):
    a = _get(db, Artifact, aid)
    if body.status not in ("accepted", "revision_requested", "pending"):
        raise HTTPException(422, "Invalid status")
    a.acceptance_status = body.status
    events.emit(db, a.project_id, "artifact_acceptance", f"“{a.name}” marked {body.status.replace('_', ' ')}",
                data={"artifact_id": str(a.id), "comment": body.comment})
    if body.status == "revision_requested" and body.comment:
        db.add(ProjectRequirement(project_id=a.project_id, kind="feedback", text=f"On “{a.name}”: {body.comment}",
                                  source="deliverable_review"))
    db.commit()
    return ser.artifact(db, a)


@router.get("/artifacts/{aid}/export")
def export_artifact(aid: str, format: str = "md", db: Session = Depends(get_db)):
    a = _get(db, Artifact, aid)
    try:
        path = exports.export_artifact(db, a, format)
    except exports.ExportError as e:
        raise HTTPException(400, str(e)) from e
    return FileResponse(path, filename=path.name)


@router.get("/projects/{pid}/export")
def export_project(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    try:
        path = exports.export_project(db, p)
    except exports.ExportError as e:
        raise HTTPException(400, str(e)) from e
    events.emit(db, p.id, "exported", f"Deliverables exported ({path.name})")
    db.commit()
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.get("/projects/{pid}/findings")
def list_findings(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    return [ser.finding(f) for f in db.scalars(select(ReviewFinding).where(ReviewFinding.project_id == p.id)
                                               .order_by(ReviewFinding.created_at))]


# ---------------------------------------------------------------------------
# Activity
# ---------------------------------------------------------------------------
@router.get("/projects/{pid}/events")
def list_events(pid: str, after: int = 0, limit: int = Query(200, le=1000), db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    q = select(AgentEvent).where(AgentEvent.project_id == p.id, AgentEvent.seq > after).order_by(AgentEvent.seq).limit(limit)
    return [events.event_to_dict(e) for e in db.scalars(q)]


@router.get("/projects/{pid}/handoffs")
def list_handoffs(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    return [ser.handoff(h) for h in db.scalars(select(AgentHandoff).where(AgentHandoff.project_id == p.id)
                                               .order_by(AgentHandoff.created_at))]


@router.get("/projects/{pid}/stream")
async def stream(pid: str, request: Request, after: int = 0):
    """Server-sent events: new AgentEvents in order. Clients reconnect with ?after=<last seq>."""
    project_id = _uuid(pid)
    last_id = request.headers.get("last-event-id")
    cursor = int(last_id) if last_id and last_id.isdigit() else after

    async def gen():
        nonlocal cursor
        yield "retry: 2000\n\n"
        idle = 0
        while not await request.is_disconnected():
            def fetch():
                with SessionLocal() as db:
                    return [events.event_to_dict(e) for e in db.scalars(
                        select(AgentEvent).where(AgentEvent.project_id == project_id, AgentEvent.seq > cursor)
                        .order_by(AgentEvent.seq).limit(200))]
            batch = await asyncio.to_thread(fetch)
            for e in batch:
                cursor = e["seq"]
                yield f"id: {e['seq']}\nevent: agent_event\ndata: {json.dumps(e)}\n\n"
            if batch:
                idle = 0
            else:
                idle += 1
                if idle % 30 == 0:
                    yield ": keepalive\n\n"
                await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Costs
# ---------------------------------------------------------------------------
@router.get("/projects/{pid}/costs")
def project_costs(pid: str, db: Session = Depends(get_db)):
    p = _get(db, Project, pid)
    recs = list(db.scalars(select(UsageRecord).where(UsageRecord.project_id == p.id).order_by(UsageRecord.created_at)))
    agents = {a.id: a for a in db.scalars(select(ProjectAgent).where(ProjectAgent.project_id == p.id))}
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.project_id == p.id))}

    def agg(key):
        out: dict[str, dict] = {}
        for r in recs:
            k = key(r)
            d = out.setdefault(k, {"key": k, "calls": 0, "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0,
                                   "estimated_cost_usd": 0.0, "unpriced_calls": 0, "test_calls": 0})
            d["calls"] += 1
            d["input_tokens"] += r.input_tokens
            d["output_tokens"] += r.output_tokens
            d["cache_read_tokens"] += r.cache_read_tokens
            if r.is_test_provider:
                d["test_calls"] += 1
            elif r.estimated_cost_usd is None:
                d["unpriced_calls"] += 1
            else:
                d["estimated_cost_usd"] += float(r.estimated_cost_usd)
        return sorted(out.values(), key=lambda d: -d["estimated_cost_usd"])

    by_agent = agg(lambda r: agents[r.agent_id].display_name if r.agent_id in agents else "(removed)")
    by_task = agg(lambda r: tasks[r.task_id].title if r.task_id in tasks else f"({r.purpose})")
    by_model = agg(lambda r: f"{r.provider}/{r.model_id}")
    b = services.get_budget(db, p.id)
    db.commit()
    return {
        "estimated_total_usd": float(services.project_spend(db, p.id)), "budget": _budget(b),
        "by_agent": by_agent, "by_task": by_task, "by_model": by_model,
        "records": [{"id": str(r.id), "created_at": r.created_at.isoformat(), "provider": r.provider, "model_id": r.model_id,
                     "agent": agents[r.agent_id].display_name if r.agent_id in agents else None,
                     "task": tasks[r.task_id].title if r.task_id in tasks else None, "purpose": r.purpose,
                     "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                     "cache_read_tokens": r.cache_read_tokens, "cache_write_tokens": r.cache_write_tokens,
                     "other_usage": r.other_usage, "estimated_cost_usd": ser.money(r.estimated_cost_usd),
                     "is_test_provider": r.is_test_provider, "price_snapshot": r.price_snapshot} for r in recs[-500:]],
        "disclaimer": ("Costs are estimates computed from configured per-token prices. Providers bill actual usage, which "
                       "may differ and may be reported later. Budgets are AgentOffice controls, not provider billing caps."),
    }
