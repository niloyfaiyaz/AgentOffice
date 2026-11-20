"""Versioned requirement items.

The client's brief is split into individual requirement items with stable references
(R-001, R-002, ...). A change request supersedes specific items: they are kept for history,
marked ``superseded`` and linked (``superseded_by_id``) to the item that replaced them.
Agents only ever receive active items, plus an explicit "no longer valid" list.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from . import events
from .models import Project, ProjectRequirement, utcnow

KIND_LABEL = {
    "objective": "Context", "requirement": "Requirement", "deliverable": "Deliverable", "constraint": "Constraint",
    "success_criterion": "Success criterion", "clarification": "Client clarification", "change": "Requirement change",
    "feedback": "Client feedback",
}
# Items a change request may supersede (deliverable lists and background context are not rules).
SUPERSEDABLE = {"requirement", "constraint", "success_criterion", "clarification", "change", "feedback"}

_LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)\s*$")
_RULE = re.compile(r"\b(must|shall|should|required|requires|needs? to|has to|have to|reject(?:ed)?|may not|"
                   r"cannot|can't|never|always|only if|at least)\b", re.I)


def split_brief(text: str) -> list[tuple[str, str]]:
    """Split free-text objective into (kind, text) items: numbered/bulleted lines and
    normative sentences become ``requirement`` items; the rest is kept as ``objective`` context."""
    items: list[tuple[str, str]] = []
    context: list[str] = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        m = _LIST_ITEM.match(line)
        if m:
            items.append(("requirement", m.group(1).strip()))
            continue
        for sent in re.split(r"(?<=[.!?])\s+", line.strip()):
            sent = sent.strip()
            if not sent:
                continue
            if _RULE.search(sent) and not sent.endswith(":"):
                items.append(("requirement", sent))
            else:
                context.append(sent)
    out = [("objective", " ".join(context))] if context else []
    seen = set()
    for k, t in items:
        if (k, t) not in seen:
            seen.add((k, t))
            out.append((k, t))
    return out


# -- stable references -------------------------------------------------------------
def _next_numbers(db: Session, project_id: uuid.UUID) -> int:
    refs = db.scalars(select(ProjectRequirement.ref).where(ProjectRequirement.project_id == project_id,
                                                           ProjectRequirement.ref.is_not(None)))
    nums = [int(r[2:]) for r in refs if r and r.startswith("R-") and r[2:].isdigit()]
    return max(nums, default=0)


@event.listens_for(Session, "before_flush")
def _assign_refs(session: Session, flush_context, instances) -> None:
    """Every new requirement item gets the next stable per-project reference."""
    pending = [o for o in session.new if isinstance(o, ProjectRequirement) and not o.ref]
    if not pending:
        return
    counters: dict[uuid.UUID, int] = {}
    with session.no_autoflush:
        for o in pending:
            if o.project_id not in counters:
                counters[o.project_id] = _next_numbers(session, o.project_id)
            counters[o.project_id] += 1
            o.ref = f"R-{counters[o.project_id]:03d}"


# -- queries -----------------------------------------------------------------------
def active(db: Session, project_id: uuid.UUID) -> list[ProjectRequirement]:
    return list(db.scalars(select(ProjectRequirement).where(ProjectRequirement.project_id == project_id,
                                                            ProjectRequirement.status == "active")
                           .order_by(ProjectRequirement.created_at, ProjectRequirement.ref)))


def superseded(db: Session, project_id: uuid.UUID) -> list[ProjectRequirement]:
    return list(db.scalars(select(ProjectRequirement).where(ProjectRequirement.project_id == project_id,
                                                            ProjectRequirement.status == "superseded",
                                                            ProjectRequirement.superseded_by_id.is_not(None))
                           .order_by(ProjectRequirement.ref)))


def to_dict(db: Session, r: ProjectRequirement) -> dict[str, Any]:
    by = db.get(ProjectRequirement, r.superseded_by_id) if r.superseded_by_id else None
    return {"id": str(r.id), "ref": r.ref, "kind": r.kind, "text": r.text, "source": r.source, "status": r.status,
            "superseded_by": by.ref if by else None, "superseded_at": r.superseded_at.isoformat() if r.superseded_at else None,
            "created_at": r.created_at.isoformat()}


# -- sync from the project form ----------------------------------------------------
def sync_core(db: Session, project: Project) -> None:
    """Mirror the brief into requirement items. Items the client retired through a change
    request are never resurrected, even though the original brief text still contains them."""
    wanted: list[tuple[str, str]] = list(split_brief(project.objective))
    for d in project.deliverables or []:
        if str(d).strip():
            wanted.append(("deliverable", str(d).strip()))
    if project.constraints.strip():
        wanted.append(("constraint", project.constraints.strip()))
    if project.success_criteria.strip():
        wanted.append(("success_criterion", project.success_criteria.strip()))
    kinds = ["objective", "requirement", "deliverable", "constraint", "success_criterion"]
    rows = list(db.scalars(select(ProjectRequirement).where(
        ProjectRequirement.project_id == project.id, ProjectRequirement.source == "user",
        ProjectRequirement.kind.in_(kinds))))
    keep = set(wanted)
    known = {(r.kind, r.text) for r in rows}  # active OR superseded: never re-add a retired rule
    for r in rows:
        if r.status == "active" and (r.kind, r.text) not in keep:
            r.status = "superseded"  # removed from the brief by an edit (no replacing item)
            r.superseded_at = utcnow()
    for kind, text in wanted:
        if (kind, text) not in known:
            db.add(ProjectRequirement(project_id=project.id, kind=kind, text=text, source="user"))
    db.flush()


# -- supersession ------------------------------------------------------------------
def supersede(db: Session, project_id: uuid.UUID, ids: list[str], by: ProjectRequirement,
              run_id: Optional[uuid.UUID] = None) -> list[ProjectRequirement]:
    done = []
    for i in ids:
        try:
            r = db.get(ProjectRequirement, uuid.UUID(str(i)))
        except ValueError:
            continue
        if r is None or r.project_id != project_id or r.status != "active" or r.id == by.id:
            continue
        r.status = "superseded"
        r.superseded_by_id = by.id
        r.superseded_at = utcnow()
        done.append(r)
    if done:
        events.emit(db, project_id, "requirement_superseded",
                    f"{by.ref} replaces {', '.join(r.ref for r in done)}", run_id=run_id,
                    data={"by": by.ref, "superseded": [r.ref for r in done]})
    db.flush()
    return done


_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "only", "must", "should", "update", "updated",
         "affected", "requirements", "requirement", "stories", "story", "acceptance", "criteria", "tests", "test",
         "now", "may", "will", "are", "not", "any", "each", "every", "when", "they", "their", "them", "row", "rows"}


def _terms(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z][a-z0-9-]{2,}", text.lower()) if w not in _STOP}


def heuristic_candidates(change: str, items: list[ProjectRequirement]) -> list[ProjectRequirement]:
    """Fallback impact proposal: rule items sharing at least two salient terms with the change."""
    ct = _terms(change)
    return [r for r in items if len(_terms(r.text) & ct) >= 2]


async def propose_supersession(db: Session, project: Project, change: ProjectRequirement) -> dict[str, Any]:
    """Ask the PM which active items the change replaces; fall back to the keyword heuristic.
    The result is only a proposal - the client confirms it on the approval card."""
    from .orchestration.llm import Blocked, call_model
    from .providers.base import ProviderError, ToolSpec
    from .services import orchestrator

    candidates = [r for r in active(db, project.id) if r.kind in SUPERSEDABLE and r.id != change.id]
    if not candidates:
        return {"candidates": [], "proposed": [], "method": "none", "rationale": ""}
    proposed: list[str] = []
    method, rationale = "heuristic", "Keyword overlap with the change (the project manager did not answer)."
    pm = orchestrator(db, project.id)
    if pm is not None:
        listing = "\n".join(f"- {r.ref} [{KIND_LABEL.get(r.kind, r.kind)}] {r.text}" for r in candidates)
        tool = ToolSpec("select_superseded", "Report which existing requirement items the change replaces.", {
            "type": "object", "additionalProperties": False, "required": ["superseded_refs", "rationale"],
            "properties": {"superseded_refs": {"type": "array", "items": {"type": "string"}},
                           "rationale": {"type": "string"}}})
        msg = (f"The client changed a requirement:\n\"{change.text}\"\n\nCurrent requirement items:\n{listing}\n\n"
               "Which items does this change contradict or replace, so they must no longer be followed? Include only "
               "items whose rule conflicts with the change (not items that merely relate to the same topic). "
               "Call select_superseded.")
        try:
            res = await call_model(db, project=project, run=None, agent=pm, task=None, purpose="impact_analysis",
                                   system=f"You are {pm.display_name}, the project manager, maintaining the requirements baseline.",
                                   messages=[{"role": "user", "content": [{"type": "text", "text": msg}]}], tools=[tool])
            if not isinstance(res, Blocked):
                call = next((c for c in res.tool_calls if c.name == "select_superseded"), None)
                if call is not None:
                    refs = {str(x).strip() for x in call.input.get("superseded_refs", [])}
                    proposed = [str(r.id) for r in candidates if r.ref in refs]
                    method, rationale = "project_manager", str(call.input.get("rationale", ""))[:1000]
        except ProviderError:
            pass
    if method == "heuristic":
        proposed = [str(r.id) for r in heuristic_candidates(change.text, candidates)]
    return {"candidates": [{"id": str(r.id), "ref": r.ref, "kind": r.kind, "text": r.text, "proposed": str(r.id) in proposed}
                           for r in candidates],
            "proposed": proposed, "method": method, "rationale": rationale}


def context_block(db: Session, project_id: uuid.UUID) -> str:
    """What agents see: active items (authoritative) and an explicit no-longer-valid list."""
    act = active(db, project_id)
    lines = [f"- {r.ref} [{KIND_LABEL.get(r.kind, r.kind)}] {r.text}" for r in act] or ["(none recorded)"]
    old = superseded(db, project_id)
    if old:
        refs = {r.id: r.ref for r in db.scalars(select(ProjectRequirement).where(ProjectRequirement.project_id == project_id))}
        lines += ["", "NO LONGER VALID - superseded by a client change (do not follow these; follow the replacing item):"]
        lines += [f"- {r.ref} (replaced by {refs.get(r.superseded_by_id, '?')}): {r.text}" for r in old]
    return "\n".join(lines)
