"""Task-to-requirement traceability, artifact lineage and deterministic freshness.

* ``TaskRequirement`` links record which requirement items a task implements (multi-valued,
  historical: links are deactivated, never deleted).
* Every artifact version snapshots its lineage at write time: the requirement items its
  producing task implemented and the exact artifact versions that task consumed.
* Freshness is computed from that lineage only - no model is involved:
    - a version implementing a superseded requirement is STALE;
    - a version derived from a stale input version is STALE;
    - a work version with no requirement links, produced before a supersession, is UNCERTAIN
      (treated as stale until the client confirms it or it is reworked);
    - the client may confirm a specific version as current.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Artifact, ArtifactVersion, ProjectRequirement, Task, TaskDependency, TaskExecution, TaskRequirement, utcnow,
)

WORK_KINDS = ("work", "subtask", "rework")
IN_FLIGHT = ("running", "waiting_approval", "waiting_subtask", "paused")
NOT_STARTED = ("pending", "ready")
LINEAGE = "[lineage] "


# -- links ---------------------------------------------------------------------------
def link(db: Session, task: Task, requirement_ids: Iterable[Any], source: str = "plan") -> None:
    for rid in {uuid.UUID(str(r)) for r in requirement_ids}:
        row = db.scalar(select(TaskRequirement).where(TaskRequirement.task_id == task.id,
                                                      TaskRequirement.requirement_id == rid))
        if row is None:
            db.add(TaskRequirement(task_id=task.id, requirement_id=rid, source=source))
        elif not row.active:
            row.active, row.deactivated_at, row.source = True, None, source
    db.flush()


def links(db: Session, task_id: uuid.UUID, active_only: bool = True) -> list[TaskRequirement]:
    q = select(TaskRequirement).where(TaskRequirement.task_id == task_id)
    if active_only:
        q = q.where(TaskRequirement.active.is_(True))
    return list(db.scalars(q))


def requirement_ids(db: Session, task_id: uuid.UUID) -> list[str]:
    return sorted(str(r.requirement_id) for r in links(db, task_id))


def refs(db: Session, ids: Iterable[Any]) -> list[str]:
    ids = [uuid.UUID(str(i)) for i in ids]
    if not ids:
        return []
    return sorted(r for r in db.scalars(select(ProjectRequirement.ref).where(ProjectRequirement.id.in_(ids))) if r)


def inherit(db: Session, new_task: Task, from_task: Task, source: str = "inherited") -> None:
    link(db, new_task, [l.requirement_id for l in links(db, from_task.id)], source)


def relink_superseded(db: Session, task: Task, superseded: set[uuid.UUID], replacement: ProjectRequirement) -> bool:
    """Swap links to superseded items for the replacing item (history kept)."""
    changed = False
    for l in links(db, task.id):
        if l.requirement_id in superseded:
            l.active, l.deactivated_at = False, utcnow()
            changed = True
    if changed:
        link(db, task, [replacement.id], "change")
    return changed


def current_requirement_ids(db: Session, ids: Iterable[Any]) -> list[uuid.UUID]:
    """Map requirement ids to their current versions (follow supersession chains)."""
    out = set()
    for i in ids:
        r = db.get(ProjectRequirement, uuid.UUID(str(i)))
        hops = 0
        while r is not None and r.status == "superseded" and r.superseded_by_id and hops < 20:
            r, hops = db.get(ProjectRequirement, r.superseded_by_id), hops + 1
        if r is not None and r.status == "active":
            out.add(r.id)
    return sorted(out)


def links_for_rework(db: Session, original: Task, superseded: set[uuid.UUID],
                     replacement: Optional[ProjectRequirement]) -> list[uuid.UUID]:
    ids = {l.requirement_id for l in links(db, original.id)}
    if superseded & ids or (replacement is not None and not ids):
        ids = (ids - superseded) | ({replacement.id} if replacement is not None else set())
    return sorted(ids)


# -- lineage capture -----------------------------------------------------------------
def latest_version(db: Session, artifact_id: uuid.UUID) -> Optional[ArtifactVersion]:
    return db.scalar(select(ArtifactVersion).where(ArtifactVersion.artifact_id == artifact_id)
                     .order_by(ArtifactVersion.version.desc()).limit(1))


def context_inputs(db: Session, task: Task) -> list[str]:
    """Artifact versions a task's context is built from (dependencies, explicit inputs, and for
    QA/consolidation every delivered document)."""
    art_ids: set[uuid.UUID] = set()
    for dep_id in db.scalars(select(TaskDependency.depends_on_task_id).where(TaskDependency.task_id == task.id)):
        dep = db.get(Task, dep_id)
        if dep is not None:
            art_ids |= {uuid.UUID(a) for a in dep.output_artifact_ids}
    for r in task.input_refs or []:
        try:
            art_ids.add(uuid.UUID(str(r)))
        except ValueError:
            pass
    if task.kind in ("qa", "consolidation"):
        art_ids |= set(db.scalars(select(Artifact.id).where(Artifact.project_id == task.project_id,
                                                            Artifact.category == "deliverable")))
    out = []
    for aid in art_ids:
        v = latest_version(db, aid)
        if v is not None:
            out.append(str(v.id))
    return sorted(out)


def record_input(execution: TaskExecution, version_ids: Iterable[Any]) -> None:
    cur = list(execution.input_version_ids or [])
    for v in version_ids:
        if str(v) not in cur:
            cur.append(str(v))
    execution.input_version_ids = cur


def snapshot(db: Session, version: ArtifactVersion, task: Optional[Task], execution: Optional[TaskExecution],
             extra_inputs: Iterable[Any] = ()) -> None:
    """Freeze the lineage of a newly written version."""
    version.requirement_ids = requirement_ids(db, task.id) if task is not None else []
    inputs = list(execution.input_version_ids or []) if execution is not None else []
    for v in extra_inputs:
        if str(v) not in inputs:
            inputs.append(str(v))
    version.input_version_ids = inputs


# -- freshness ------------------------------------------------------------------------
def _last_supersession(db: Session, project_id: uuid.UUID):
    return db.scalar(select(func.max(ProjectRequirement.superseded_at)).where(
        ProjectRequirement.project_id == project_id, ProjectRequirement.superseded_by_id.is_not(None)))


class Freshness:
    """Memoized, deterministic freshness evaluation for one project."""

    def __init__(self, db: Session, project_id: uuid.UUID, simulate_superseded: Iterable[Any] = ()):
        self.db = db
        self.project_id = project_id
        self.sim = {uuid.UUID(str(i)) for i in simulate_superseded}  # "what if these were replaced?"
        self.req = {r.id: r for r in db.scalars(select(ProjectRequirement).where(ProjectRequirement.project_id == project_id))}
        self.last_change = _last_supersession(db, project_id)
        self.memo: dict[uuid.UUID, list[str]] = {}

    def version_reasons(self, v: ArtifactVersion, seen: Optional[set] = None) -> list[str]:
        if v.id in self.memo:
            return self.memo[v.id]
        seen = (seen or set()) | {v.id}
        art = self.db.get(Artifact, v.artifact_id)
        if art is not None and art.confirmed_version == v.version:
            self.memo[v.id] = []
            return []
        reasons: list[str] = []
        for rid in v.requirement_ids or []:
            r = self.req.get(uuid.UUID(str(rid)))
            if r is not None and r.id in self.sim and r.status == "active":
                reasons.append(f"implements {r.ref}, which this change would replace")
            elif r is not None and r.status == "superseded" and r.superseded_by_id:
                by = self.req.get(r.superseded_by_id)
                reasons.append(f"implements superseded {r.ref} (replaced by {by.ref if by else '?'})")
        task = self.db.get(Task, v.created_by_task_id) if v.created_by_task_id else None
        if (not v.requirement_ids and task is not None and task.kind in WORK_KINDS and self.last_change is not None
                and v.created_at < self.last_change):
            reasons.append("no requirement links recorded and produced before the latest requirement change "
                           "(confirm it is current, or rework it)")
        # Documents a task was asked to revise ("Deliverables to work on") are revision sources, not derivation.
        revising = {str(a) for a in (task.input_refs or [])} if task is not None else set()
        for iid in v.input_version_ids or []:
            try:
                iv = self.db.get(ArtifactVersion, uuid.UUID(str(iid)))
            except ValueError:
                continue
            if iv is None or iv.id in seen or iv.artifact_id == v.artifact_id:
                continue  # revising your own earlier version is not derivation
            if str(iv.artifact_id) in revising:
                continue  # the task read the stale version it was asked to bring up to date
            if self.version_reasons(iv, seen):
                ia = self.db.get(Artifact, iv.artifact_id)
                reasons.append(f"derived from stale input “{ia.name if ia else '?'}” v{iv.version}")
        self.memo[v.id] = reasons
        return reasons

    def artifact_reasons(self, art: Artifact) -> list[str]:
        v = latest_version(self.db, art.id)
        return self.version_reasons(v) if v is not None else []


def refresh(db: Session, project_id: uuid.UUID) -> list[Artifact]:
    """Recompute stale flags from lineage. Client notes ('[note] ...') are left untouched."""
    f = Freshness(db, project_id)
    stale = []
    for art in db.scalars(select(Artifact).where(Artifact.project_id == project_id, Artifact.category != "plan")):
        reasons = f.artifact_reasons(art)
        if reasons:
            art.stale, art.stale_reason = True, LINEAGE + "; ".join(reasons)
            stale.append(art)
        elif art.stale_reason.startswith(LINEAGE):
            art.stale, art.stale_reason = False, ""
    db.flush()
    return stale


def delivery_blockers(db: Session, project_id: uuid.UUID, run_id: Optional[uuid.UUID] = None,
                      stage: str = "final") -> list[dict[str, Any]]:
    """Deliverables that must not be delivered as current (deterministic gate).

    stage="pre": before QA/consolidation - consolidation outputs are excluded because this run's
    consolidation regenerates them. stage="final": everything, except an earlier run's consolidated
    deliverable once this run has produced its own (it is then historical, kept for audit)."""
    refresh(db, project_id)
    this_run_consolidated = run_id is not None and db.scalar(select(func.count()).select_from(Task).where(
        Task.run_id == run_id, Task.kind == "consolidation", Task.status == "completed")) > 0
    out = []
    for art in db.scalars(select(Artifact).where(Artifact.project_id == project_id, Artifact.category == "deliverable",
                                                 Artifact.stale.is_(True))):
        v = latest_version(db, art.id)
        task = db.get(Task, v.created_by_task_id) if v and v.created_by_task_id else None
        if task is not None and task.kind == "consolidation":
            if stage == "pre" or (this_run_consolidated and task.run_id != run_id):
                continue
        out.append({"artifact_id": str(art.id), "name": art.name, "version": art.current_version,
                    "reason": art.stale_reason.replace(LINEAGE, "") or "marked stale",
                    "producing_task_id": str(task.id) if task else None, "producing_task": task.title if task else None})
    return out


# -- impact analysis ----------------------------------------------------------------------
def _dependents(db: Session, run_id: uuid.UUID) -> dict[uuid.UUID, set[uuid.UUID]]:
    children: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for d in db.scalars(select(TaskDependency).join(Task, Task.id == TaskDependency.task_id).where(Task.run_id == run_id)):
        children[d.depends_on_task_id].add(d.task_id)
    return children


def _consumers(db: Session, run_id: uuid.UUID) -> dict[uuid.UUID, set[uuid.UUID]]:
    """producing task -> tasks whose executions consumed one of its artifact versions."""
    producer: dict[str, uuid.UUID] = {}
    for v in db.scalars(select(ArtifactVersion).join(Task, Task.id == ArtifactVersion.created_by_task_id)
                        .where(Task.run_id == run_id)):
        producer[str(v.id)] = v.created_by_task_id
    out: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for ex in db.scalars(select(TaskExecution).join(Task, Task.id == TaskExecution.task_id).where(Task.run_id == run_id)):
        for iv in ex.input_version_ids or []:
            p = producer.get(str(iv))
            if p is not None and p != ex.task_id:
                out[p].add(ex.task_id)
    return out


def impact(db: Session, run_id: uuid.UUID, superseded_ids: Iterable[Any]) -> dict[str, Any]:
    """Evidence-based impact of superseding ``superseded_ids`` on one run's tasks."""
    sup = {uuid.UUID(str(i)) for i in superseded_ids}
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.run_id == run_id))}
    direct: dict[uuid.UUID, list[uuid.UUID]] = {}
    for t in tasks.values():
        hit = [l.requirement_id for l in links(db, t.id) if l.requirement_id in sup]
        if hit and t.kind in WORK_KINDS:
            direct[t.id] = hit
    children, consumers = _dependents(db, run_id), _consumers(db, run_id)
    downstream: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)  # task -> affected upstream tasks
    frontier = list(direct)
    while frontier:
        up = frontier.pop()
        for nxt in children.get(up, set()) | consumers.get(up, set()):
            t = tasks.get(nxt)
            if t is None or t.kind not in WORK_KINDS:
                continue
            if up not in downstream[nxt]:
                downstream[nxt].add(up)
                frontier.append(nxt)
    req_ref = {r.id: r.ref for r in db.scalars(select(ProjectRequirement).where(ProjectRequirement.id.in_(sup)))} if sup else {}
    entries = []
    for tid, t in tasks.items():
        if t.kind not in WORK_KINDS or t.status in ("cancelled", "skipped", "failed"):
            continue
        linked = links(db, tid, active_only=False)
        if tid in direct:
            why = f"implements {', '.join(req_ref.get(r, '?') for r in direct[tid])}"
            kind = "direct"
        elif downstream.get(tid):
            why = "uses output of " + ", ".join(f"“{tasks[u].title}”" for u in downstream[tid] if u in tasks)
            kind = "downstream"
        elif not linked:
            why = "no requirement links recorded; impact cannot be determined"
            kind = "uncertain"
        else:
            why = "implements " + ", ".join(refs(db, [l.requirement_id for l in links(db, tid)])) + " only"
            kind = "unaffected"
        if t.status == "completed":
            action = {"direct": "rework", "downstream": "rework", "uncertain": "confirm", "unaffected": "preserve"}[kind]
        elif t.status in IN_FLIGHT:
            action = {"direct": "rework_after", "downstream": "rework_after", "uncertain": "confirm",
                      "unaffected": "preserve"}[kind]
        else:  # not started: picks up the new baseline; waits for any upstream rework so it never reads stale input
            action = {"direct": "relink", "downstream": "wait", "uncertain": "none", "unaffected": "none"}[kind]
            if kind == "direct" and downstream.get(tid):
                action = "relink_wait"
        outputs = [db.get(Artifact, uuid.UUID(a)) for a in t.output_artifact_ids]
        entries.append({"id": str(tid), "title": t.title, "status": t.status, "impact": kind, "action": action,
                        "reason": why, "upstream": [str(u) for u in downstream.get(tid, set())],
                        "direct_requirements": [str(r) for r in direct.get(tid, [])],
                        "artifacts": [{"id": str(a.id), "name": a.name, "version": a.current_version} for a in outputs if a]})
    return {"tasks": entries,
            "counts": {k: sum(1 for e in entries if e["impact"] == k) for k in ("direct", "downstream", "uncertain", "unaffected")}}


def artifacts_at_risk(db: Session, project_id: uuid.UUID, candidate_ids: Iterable[Any]) -> list[dict[str, Any]]:
    """Deliverables that would become stale if ``candidate_ids`` were superseded (deterministic)."""
    f = Freshness(db, project_id, simulate_superseded=candidate_ids)
    out = []
    for art in db.scalars(select(Artifact).where(Artifact.project_id == project_id, Artifact.category == "deliverable")):
        reasons = f.artifact_reasons(art)
        if reasons:
            out.append({"id": str(art.id), "name": art.name, "version": art.current_version, "reason": "; ".join(reasons)})
    return out
