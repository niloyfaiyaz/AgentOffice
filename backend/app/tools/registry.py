"""Agent tools. Every tool call is checked against (a) the agent's permissions, (b) the
task's allowed tools and (c) the run's approved scope, server-side, regardless of what the
model asks for. Model output can never grant itself a permission."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import statistics
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional, Union

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import events, services
from ..catalog import TOOL_PERMISSIONS
from ..models import (
    AgentHandoff, Artifact, ArtifactVersion, BudgetPolicy, Project, ProjectAgent, ProjectRun, ReferenceFile,
    ReviewFinding, Task, TaskDependency, TaskExecution,
)
from ..providers.base import ToolSpec
from . import sandbox
from .files import untrusted_block


@dataclass
class ToolContext:
    db: Session
    project: Project
    run: ProjectRun
    task: Task
    agent: ProjectAgent
    execution: TaskExecution
    policy: BudgetPolicy
    authorized_call_id: Optional[str] = None  # a consequential call the client just approved
    written_this_execution: list[str] = field(default_factory=list)


@dataclass
class ToolOutput:
    content: str
    is_error: bool = False
    finish: bool = False  # complete_task succeeded


@dataclass
class Suspend:
    reason: str  # approval | subtask
    ref_id: uuid.UUID
    note: str = ""


Handler = Callable[[ToolContext, dict[str, Any], str], Awaitable[Union[ToolOutput, Suspend]]]


@dataclass
class ToolDef:
    name: str
    permission: Optional[str]  # None = always available for its task kinds
    description: str
    schema: dict[str, Any]
    handler: Handler
    kinds: tuple[str, ...] = ("work", "subtask", "rework", "consolidation", "qa")


def _obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def _clip(text: str, n: int = 12000) -> str:
    return text if len(text) <= n else text[:n] + f"\n…[truncated {len(text) - n} chars]"


# ---------------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------------
async def h_list_files(ctx: ToolContext, args, call_id) -> ToolOutput:
    files = list(ctx.db.scalars(select(ReferenceFile).where(ReferenceFile.project_id == ctx.project.id)))
    if not files:
        return ToolOutput("No reference files were provided for this project.")
    rows = [f"- id={f.id} name={f.filename} type={f.mime_type} chars={len(f.extracted_text)} status={f.extraction_status}"
            for f in files]
    return ToolOutput("\n".join(rows))


async def h_read_file(ctx: ToolContext, args, call_id) -> ToolOutput:
    try:
        fid = uuid.UUID(str(args.get("file_id", "")))
    except ValueError:
        return ToolOutput("file_id must be one of the ids from list_reference_files", is_error=True)
    f = ctx.db.get(ReferenceFile, fid)
    if f is None or f.project_id != ctx.project.id:
        return ToolOutput("No such file in this project", is_error=True)
    offset = max(int(args.get("offset", 0) or 0), 0)
    limit = min(max(int(args.get("max_chars", 20000) or 20000), 1000), 40000)
    chunk = f.extracted_text[offset:offset + limit]
    more = len(f.extracted_text) > offset + limit
    note = f"\n[showing chars {offset}-{offset + len(chunk)} of {len(f.extracted_text)}{'; call again with a larger offset for more' if more else ''}]"
    return ToolOutput(untrusted_block(f.filename, chunk) + note)


async def h_list_artifacts(ctx: ToolContext, args, call_id) -> ToolOutput:
    arts = services.project_artifacts(ctx.db, ctx.project.id)
    if not arts:
        return ToolOutput("No deliverables exist yet.")
    rows = []
    for a in arts:
        owner = ctx.db.get(ProjectAgent, a.owner_agent_id) if a.owner_agent_id else None
        v = services.latest_version(ctx.db, a.id)
        rows.append(f"- name=\"{a.name}\" type={a.artifact_type} v{a.current_version} owner={owner.display_name if owner else '-'}"
                    f" summary={(v.summary if v else '')[:160]!r}")
    return ToolOutput("\n".join(rows))


def _find_artifact(ctx: ToolContext, ref: str) -> Optional[Artifact]:
    ref = (ref or "").strip()
    try:
        a = ctx.db.get(Artifact, uuid.UUID(ref))
        if a and a.project_id == ctx.project.id:
            return a
    except ValueError:
        pass
    return ctx.db.scalar(select(Artifact).where(Artifact.project_id == ctx.project.id, Artifact.name == ref))


async def h_read_artifact(ctx: ToolContext, args, call_id) -> ToolOutput:
    a = _find_artifact(ctx, str(args.get("name", "")))
    if a is None:
        return ToolOutput("No deliverable with that name. Use list_artifacts.", is_error=True)
    ver = args.get("version")
    q = select(ArtifactVersion).where(ArtifactVersion.artifact_id == a.id)
    v = ctx.db.scalar(q.where(ArtifactVersion.version == int(ver))) if ver else services.latest_version(ctx.db, a.id)
    if v is None:
        return ToolOutput("Version not found", is_error=True)
    from .. import traceability

    traceability.record_input(ctx.execution, [v.id])  # lineage: this task consumed this exact version
    stale = f" — STALE: {a.stale_reason.replace(traceability.LINEAGE, '')}" if a.stale and a.stale_reason else ""
    return ToolOutput(f"[{a.name} v{v.version}, type={a.artifact_type}{stale}]\n{_clip(v.content, 60000)}")


async def h_write_artifact(ctx: ToolContext, args, call_id) -> ToolOutput:
    name_arg = str(args.get("name", ""))
    if _is_qa_report_name(name_arg) and ctx.agent.role_key != "qa_reviewer":
        return ToolOutput("QA reports are produced by the QA Reviewer's review, not by other roles. Leave QA "
                          "reporting to the QA Reviewer and save only your own deliverable.", is_error=True)
    if _FINAL.search(name_arg.replace("_", " ")) and ctx.task.kind != "consolidation":
        return ToolOutput("The final consolidated deliverable is produced by the Project Manager's consolidation "
                          "step at the end of the run. Save only your own deliverable.", is_error=True)
    # Conflict prevention: a teammate's deliverable may only be revised by a task that
    # targets it (rework / consolidation / an explicit input), never overwritten in passing.
    existing = _find_artifact(ctx, str(args.get("name", "")))
    if (existing is not None and existing.owner_agent_id not in (None, ctx.agent.id)
            and ctx.task.kind not in ("rework", "consolidation")
            and str(existing.id) not in [str(r) for r in ctx.task.input_refs]):
        owner = ctx.db.get(ProjectAgent, existing.owner_agent_id)
        return ToolOutput(f"“{existing.name}” belongs to {owner.display_name if owner else 'a teammate'}. Save your work "
                          "under a different name, or delegate changes to its owner.", is_error=True)
    try:
        art, ver, created = services.write_artifact(
            ctx.db, project_id=ctx.project.id, run_id=ctx.run.id, task_id=ctx.task.id, agent_id=ctx.agent.id,
            name=str(args.get("name", "")), content=str(args.get("content", "")),
            artifact_type=str(args.get("artifact_type", "markdown")), summary=str(args.get("summary", "")),
            source_refs=[str(s) for s in (args.get("source_refs") or [])][:50], execution=ctx.execution,
        )
    except services.DomainError as e:
        return ToolOutput(str(e), is_error=True)
    if str(art.id) not in ctx.task.output_artifact_ids:
        ctx.task.output_artifact_ids = [*ctx.task.output_artifact_ids, str(art.id)]
    ctx.written_this_execution.append(str(art.id))
    events.emit(ctx.db, ctx.project.id, "artifact_written",
                f"{ctx.agent.display_name} {'created' if created else 'updated'} “{art.name}” (v{ver.version})",
                run_id=ctx.run.id, agent_id=ctx.agent.id, task_id=ctx.task.id,
                data={"artifact_id": str(art.id), "version": ver.version, "name": art.name})
    return ToolOutput(f"Saved “{art.name}” as version {ver.version}.")


def _load_table(ctx: ToolContext, source: str) -> tuple[list[dict[str, Any]], str]:
    text = None
    label = source
    try:
        f = ctx.db.get(ReferenceFile, uuid.UUID(source))
        if f and f.project_id == ctx.project.id:
            text, label = f.extracted_text, f.filename
    except ValueError:
        pass
    if text is None:
        a = _find_artifact(ctx, source)
        if a is not None:
            v = services.latest_version(ctx.db, a.id)
            text, label = (v.content if v else ""), a.name
    if text is None:
        raise ValueError("source must be a reference file id or a deliverable name")
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [data])
        rows = [r for r in data if isinstance(r, dict)]
    else:
        rows = list(csv.DictReader(io.StringIO(text)))
    return rows, label


def _num(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


async def h_analyze_table(ctx: ToolContext, args, call_id) -> ToolOutput:
    try:
        rows, label = _load_table(ctx, str(args.get("source", "")))
    except Exception as e:
        return ToolOutput(f"Could not load table: {e}", is_error=True)
    op = args.get("operation", "describe")
    if not rows:
        return ToolOutput(f"{label}: no rows")
    cols = list(rows[0].keys())
    if op == "describe":
        out = [f"{label}: {len(rows)} rows, columns: {cols}"]
        for c in cols[:40]:
            vals = [r.get(c) for r in rows]
            nums = [n for n in (_num(v) for v in vals) if n is not None]
            nonnull = sum(1 for v in vals if v not in (None, ""))
            if nums and len(nums) >= 0.8 * max(nonnull, 1):
                out.append(f"- {c}: numeric n={len(nums)} min={min(nums):g} max={max(nums):g} "
                           f"mean={statistics.fmean(nums):.4g} sum={sum(nums):.6g}")
            else:
                counts: dict[str, int] = {}
                for v in vals:
                    counts[str(v)] = counts.get(str(v), 0) + 1
                top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
                out.append(f"- {c}: text non-empty={nonnull} distinct={len(counts)} top={top}")
        return ToolOutput("\n".join(out))
    if op == "group_by":
        g, val, agg = args.get("group_by"), args.get("column"), args.get("aggregate", "count")
        if g not in cols or (agg != "count" and val not in cols):
            return ToolOutput(f"Unknown column. Columns: {cols}", is_error=True)
        groups: dict[str, list[float]] = {}
        for r in rows:
            k = str(r.get(g))
            groups.setdefault(k, [])
            if agg != "count":
                n = _num(r.get(val))
                if n is not None:
                    groups[k].append(n)
            else:
                groups[k].append(1)
        fn = {"count": len, "sum": sum, "mean": lambda x: statistics.fmean(x) if x else 0,
              "min": lambda x: min(x) if x else 0, "max": lambda x: max(x) if x else 0}.get(agg)
        if fn is None:
            return ToolOutput("aggregate must be count|sum|mean|min|max", is_error=True)
        res = sorted(((k, fn(v)) for k, v in groups.items()), key=lambda kv: -kv[1])[:100]
        return ToolOutput(f"{label}: {agg}({val or '*'}) by {g}\n" + "\n".join(f"{k}: {v:g}" for k, v in res))
    if op == "filter":
        c, cmp, target = args.get("column"), args.get("comparator", "eq"), args.get("value")
        if c not in cols:
            return ToolOutput(f"Unknown column. Columns: {cols}", is_error=True)

        def keep(r):
            v = r.get(c)
            if cmp in ("gt", "lt", "gte", "lte"):
                a, b = _num(v), _num(target)
                if a is None or b is None:
                    return False
                return {"gt": a > b, "lt": a < b, "gte": a >= b, "lte": a <= b}[cmp]
            if cmp == "contains":
                return str(target).lower() in str(v).lower()
            return str(v) == str(target)

        hits = [r for r in rows if keep(r)]
        return ToolOutput(f"{label}: {len(hits)} matching rows (showing up to 50)\n" + json.dumps(hits[:50], default=str)[:20000])
    return ToolOutput("operation must be describe|group_by|filter", is_error=True)


async def h_ask_client(ctx: ToolContext, args, call_id) -> Union[ToolOutput, Suspend]:
    q = str(args.get("question", "")).strip()
    if not q:
        return ToolOutput("question is required", is_error=True)
    # Do not re-ask what the client already answered.
    from ..models import ApprovalRequest

    prior = ctx.db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.project_id == ctx.project.id, ApprovalRequest.kind == "clarification",
        ApprovalRequest.title == q[:300], ApprovalRequest.status == "answered"))
    if prior is not None:
        return ToolOutput(f"The client already answered this question: {prior.payload.get('answer', '')}")
    asked = ctx.db.scalar(select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.task_id == ctx.task.id, ApprovalRequest.kind == "clarification"))
    if (asked or 0) >= 2:
        return ToolOutput("You have already asked the client the maximum number of questions for this task. "
                          "Proceed with clearly stated assumptions.", is_error=True)
    ap = services.create_approval(
        ctx.db, project_id=ctx.project.id, run_id=ctx.run.id, kind="clarification", title=q,
        explanation=str(args.get("context", ""))[:2000],
        payload={"options": [str(o) for o in (args.get("options") or [])][:6], "tool_call_id": call_id},
        task_id=ctx.task.id, agent_id=ctx.agent.id)
    return Suspend("approval", ap.id, "Waiting for the client's answer")


async def h_delegate(ctx: ToolContext, args, call_id) -> Union[ToolOutput, Suspend]:
    db = ctx.db
    if ctx.task.depth + 1 > ctx.policy.max_delegation_depth:
        return ToolOutput(f"Delegation depth limit ({ctx.policy.max_delegation_depth}) reached. Do the work yourself.",
                          is_error=True)
    target_name = str(args.get("to_agent", "")).strip().lower()
    target = None
    for a in services.team(db, ctx.project.id):
        if target_name in {a.display_name.lower(), a.role.lower(), a.role_key.lower()}:
            target = a
            break
    if target is None:
        names = ", ".join(f"{a.display_name} ({a.role})" for a in services.team(db, ctx.project.id))
        return ToolOutput(f"No teammate called '{target_name}'. Team: {names}", is_error=True)
    if target.id == ctx.agent.id:
        return ToolOutput("You cannot delegate to yourself.", is_error=True)
    planned = db.scalar(select(Task).join(TaskDependency, TaskDependency.task_id == Task.id).where(
        TaskDependency.depends_on_task_id == ctx.task.id, Task.assigned_agent_id == target.id,
        Task.status.in_(["pending", "ready"])))
    if planned is not None:
        return ToolOutput(f"{target.display_name} already has the planned task “{planned.title}”, which starts after yours "
                          "and receives your output. Do not delegate overlapping work; finish your own task.", is_error=True)
    objective = str(args.get("objective", "")).strip()
    if not objective:
        return ToolOutput("objective is required", is_error=True)
    total = db.scalar(select(func.count()).select_from(Task).where(Task.run_id == ctx.run.id)) or 0
    limit = int(ctx.run.planned_task_count * 1.5) + 4
    if total >= limit:
        return ToolOutput("Creating more tasks would exceed the approved scope. Complete your task with what you have, "
                          "or ask the client if more work is needed.", is_error=True)
    key = "sub:" + hashlib.sha256(f"{ctx.task.id}|{target.id}|{objective.lower()}".encode()).hexdigest()[:40]
    existing = db.scalar(select(Task).where(Task.run_id == ctx.run.id, Task.idempotency_key == key))
    if existing is not None:
        if existing.status == "completed":
            return ToolOutput(f"This was already delegated and completed: {existing.result_summary}")
        return Suspend("subtask", existing.id, "Waiting for delegated work")
    target_perms = services.agent_permissions(db, target)
    sub = Task(
        project_id=ctx.project.id, run_id=ctx.run.id, parent_task_id=ctx.task.id, assigned_agent_id=target.id,
        kind="subtask", title=str(args.get("title", objective[:80]))[:300], objective=objective,
        expected_output_type=str(args.get("expected_output_type", "markdown")),
        acceptance_criteria=[str(c) for c in (args.get("acceptance_criteria") or [])][:10],
        allowed_tools=sorted(target_perms - {"delegation"} if ctx.task.depth + 1 >= ctx.policy.max_delegation_depth
                             else target_perms),
        depth=ctx.task.depth + 1, idempotency_key=key, status="ready",
        max_model_calls=target.max_calls_per_task, sort_order=ctx.task.sort_order,
        input_refs=ctx.task.output_artifact_ids,
    )
    db.add(sub)
    db.flush()
    from .. import traceability

    traceability.inherit(db, sub, ctx.task)
    db.add(TaskDependency(task_id=ctx.task.id, depends_on_task_id=sub.id))
    ho = AgentHandoff(project_id=ctx.project.id, run_id=ctx.run.id, from_agent_id=ctx.agent.id, to_agent_id=target.id,
                      source_task_id=ctx.task.id, created_task_id=sub.id, kind="delegation",
                      summary=objective[:2000], payload={"tool_call_id": call_id})
    db.add(ho)
    db.flush()
    events.emit(db, ctx.project.id, "handoff", f"{ctx.agent.display_name} delegated “{sub.title}” to {target.display_name}",
                run_id=ctx.run.id, agent_id=ctx.agent.id, task_id=ctx.task.id, agent_status="communicating",
                data={"handoff_id": str(ho.id), "to_agent_id": str(target.id), "subtask_id": str(sub.id)})
    events.emit(db, ctx.project.id, "task_assigned", f"{target.display_name} was assigned “{sub.title}”",
                run_id=ctx.run.id, agent_id=target.id, task_id=sub.id, agent_status="assigned",
                data={"from_agent_id": str(ctx.agent.id), "handoff_id": str(ho.id)})
    return Suspend("subtask", sub.id, "Waiting for delegated work")


def _code_files(ctx: ToolContext) -> dict[str, str]:
    files = {}
    for a in services.project_artifacts(ctx.db, ctx.project.id):
        if a.artifact_type == "code":
            v = services.latest_version(ctx.db, a.id)
            if v:
                files[a.name] = v.content
    return files


async def _authorize(ctx: ToolContext, perm: str, call_id: str, title: str, detail: str) -> Optional[Suspend]:
    if perm in (ctx.run.approved_tools or []) or ctx.authorized_call_id == call_id:
        return None
    ap = services.create_approval(
        ctx.db, project_id=ctx.project.id, run_id=ctx.run.id, kind="tool_authorization", title=title,
        explanation=detail, payload={"tool": perm, "tool_call_id": call_id}, task_id=ctx.task.id, agent_id=ctx.agent.id)
    return Suspend("approval", ap.id, "Waiting for tool authorization")


async def _sandbox_call(ctx: ToolContext, command: list[str], label: str, call_id: str) -> ToolOutput:
    files = _code_files(ctx)
    if not files:
        return ToolOutput("There are no code deliverables to run. Write code artifacts first.", is_error=True)
    try:
        res = await sandbox.execute(files, command, timeout_s=min(ctx.policy.task_timeout_seconds, 120))
    except sandbox.SandboxUnavailable as e:
        return ToolOutput(f"Sandboxed execution is unavailable: {e}", is_error=True)
    except ValueError as e:
        return ToolOutput(str(e), is_error=True)
    status = "timed out" if res.timed_out else f"exit code {res.exit_code}"
    events.emit(ctx.db, ctx.project.id, "tool_action", f"{ctx.agent.display_name} ran {label} in the sandbox ({status})",
                run_id=ctx.run.id, agent_id=ctx.agent.id, task_id=ctx.task.id,
                data={"tool": label, "command": command, "exit_code": res.exit_code, "timed_out": res.timed_out,
                      "duration_s": res.duration_s, "stdout_tail": res.stdout[-3000:], "stderr_tail": res.stderr[-3000:]})
    return ToolOutput(f"[{label}: {status}, {res.duration_s}s]\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}",
                      is_error=res.exit_code != 0 or res.timed_out)


async def h_run_code(ctx: ToolContext, args, call_id) -> Union[ToolOutput, Suspend]:
    entry = str(args.get("entrypoint", "")).strip()
    try:
        sandbox.safe_rel_path(entry)
    except ValueError as e:
        return ToolOutput(str(e), is_error=True)
    cmd = ["python", entry, *[str(a) for a in (args.get("args") or [])][:20]]
    s = await _authorize(ctx, "code_execution", call_id, f"Allow {ctx.agent.display_name} to run code: {' '.join(cmd)}",
                         "Runs the project's code deliverables in an isolated container with no network access.")
    if s:
        return s
    return await _sandbox_call(ctx, cmd, "run_code", call_id)


async def h_run_tests(ctx: ToolContext, args, call_id) -> Union[ToolOutput, Suspend]:
    target = str(args.get("path", "") or "").strip()
    cmd = ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if target:
        try:
            sandbox.safe_rel_path(target)
        except ValueError as e:
            return ToolOutput(str(e), is_error=True)
        cmd.append(target)
    s = await _authorize(ctx, "test_execution", call_id, f"Allow {ctx.agent.display_name} to run automated tests",
                         "Runs pytest against the project's code deliverables in an isolated container with no network.")
    if s:
        return s
    return await _sandbox_call(ctx, cmd, "run_tests", call_id)


SEVERITIES = {"critical", "major", "minor", "info"}


def _write_qa_report(ctx: ToolContext, verdict: str, summary: str) -> None:
    """Deterministic QA report generated from the QA agent's structured review (system-authored
    from recorded findings, so the report can never claim more than the review recorded)."""
    db = ctx.db
    findings = list(db.scalars(select(ReviewFinding).where(ReviewFinding.run_id == ctx.run.id)
                               .order_by(ReviewFinding.finding_key)))
    reviewed = [a for a in services.project_artifacts(db, ctx.project.id, include_working=False)
                if a.category == "deliverable" and not _is_qa_report_name(a.name)]
    lines = [f"# QA Review Report — run {ctx.run.run_number}", "",
             f"Reviewer: {ctx.agent.display_name} ({ctx.agent.role}) · model {ctx.agent.provider}/{ctx.agent.model_id}",
             f"Review task: {ctx.task.title}", f"Verdict: **{verdict}**", "", "## Summary", summary or "(none)", "",
             "## Deliverables reviewed"]
    lines += [f"- {a.name} v{a.current_version}" for a in reviewed] or ["- (none)"]
    lines += ["", "## Findings", "| ID | Severity | Status | Deliverable | Requirement | Evidence | Recommendation |",
              "|---|---|---|---|---|---|---|"]
    names = {a.id: a.name for a in services.project_artifacts(db, ctx.project.id)}
    clean = lambda t: (t or "").replace("|", "/").replace("\n", " ")[:400]  # noqa: E731
    for f in findings:
        lines.append(f"| {f.finding_key} | {f.severity} | {f.status} | {clean(names.get(f.artifact_id, '—'))} | "
                     f"{clean(f.requirement_ref)} | {clean(f.evidence)} | {clean(f.recommendation)} |")
    if not findings:
        lines.append("| — | — | — | — | — | No findings recorded | — |")
    lines += ["", "_This report is generated from the findings the QA Reviewer recorded. A QA pass is a review "
              "opinion, not proof of correctness._"]
    reviewed_versions = [str(v.id) for v in (services.latest_version(db, a.id) for a in reviewed) if v is not None]
    services.write_artifact(db, project_id=ctx.project.id, run_id=ctx.run.id, task_id=ctx.task.id, agent_id=ctx.agent.id,
                            name=f"QA Review Report (run {ctx.run.run_number})", content="\n".join(lines),
                            artifact_type="markdown", summary=f"QA verdict {verdict}; {len(findings)} finding(s).",
                            execution=ctx.execution, extra_inputs=reviewed_versions)


_QA_REPORT = re.compile(r"\bqa\b.*\b(report|review)\b|quality assurance.*report|review report", re.I)
_FINAL = re.compile(r"final[ _-]*(consolidated|delivery|deliverable)|consolidated[ _-]*deliverable", re.I)


def _is_qa_report_name(name: str) -> bool:
    return bool(_QA_REPORT.search(name.replace("_", " ").replace("-", " ")))


async def h_submit_review(ctx: ToolContext, args, call_id) -> ToolOutput:
    db = ctx.db
    verdict = str(args.get("verdict", "")).lower()
    if verdict not in {"pass", "revise"}:
        return ToolOutput("verdict must be 'pass' or 'revise'", is_error=True)
    created = []
    n = db.scalar(select(func.count()).select_from(ReviewFinding).where(ReviewFinding.run_id == ctx.run.id)) or 0
    for f in (args.get("findings") or [])[:30]:
        sev = str(f.get("severity", "minor")).lower()
        if sev not in SEVERITIES:
            sev = "minor"
        art = _find_artifact(ctx, str(f.get("artifact", "")))
        n += 1
        rf = ReviewFinding(project_id=ctx.project.id, run_id=ctx.run.id, qa_task_id=ctx.task.id,
                           artifact_id=art.id if art else None, finding_key=f"F-{n:03d}", severity=sev,
                           requirement_ref=str(f.get("requirement", ""))[:2000], evidence=str(f.get("evidence", ""))[:4000],
                           recommendation=str(f.get("recommendation", ""))[:4000], status="open")
        db.add(rf)
        created.append(rf)
    resolved = []
    for key in (args.get("resolved_finding_keys") or [])[:60]:
        rf = db.scalar(select(ReviewFinding).where(ReviewFinding.run_id == ctx.run.id,
                                                   ReviewFinding.finding_key == str(key)))
        if rf and rf.status != "resolved":
            rf.status = "resolved"
            resolved.append(rf.finding_key)
    db.flush()
    ctx.task.finding_ids = [*ctx.task.finding_ids, *[str(r.id) for r in created]]
    summary = str(args.get("summary", ""))[:4000]
    ctx.task.result_summary = f"Verdict: {verdict}. {summary}"
    events.emit(db, ctx.project.id, "review_submitted",
                f"{ctx.agent.display_name} reviewed the deliverables: {verdict} ({len(created)} new findings, "
                f"{len(resolved)} resolved)", run_id=ctx.run.id, agent_id=ctx.agent.id, task_id=ctx.task.id,
                agent_status="reviewing",
                data={"verdict": verdict, "new_findings": [r.finding_key for r in created], "resolved": resolved})
    _write_qa_report(ctx, verdict, summary)
    return ToolOutput(f"Review recorded: {len(created)} findings ({', '.join(r.finding_key for r in created) or 'none'}); "
                      f"resolved: {', '.join(resolved) or 'none'}. Now call complete_task.")


async def h_complete(ctx: ToolContext, args, call_id) -> ToolOutput:
    summary = str(args.get("summary", "")).strip()
    if not summary:
        return ToolOutput("summary is required", is_error=True)
    perms = effective_permissions(ctx)
    if ctx.task.kind == "qa" and not ctx.task.result_summary.startswith("Verdict:"):
        return ToolOutput("Submit your review with submit_review before completing.", is_error=True)
    if (ctx.task.kind != "qa" and "artifact_write" in perms and not ctx.task.output_artifact_ids):
        return ToolOutput("Save your deliverable with write_artifact before completing the task.", is_error=True)
    if ctx.task.kind == "qa":
        ctx.task.result_summary = f"{ctx.task.result_summary}\n{summary}"[:4000]
    else:
        ctx.task.result_summary = summary[:4000]
    return ToolOutput("Task marked complete.", finish=True)


# ---------------------------------------------------------------------------------
# Definitions
# ---------------------------------------------------------------------------------
TOOLS: list[ToolDef] = [
    ToolDef("list_reference_files", "file_read", "List the client's uploaded reference files.", _obj({}, []), h_list_files),
    ToolDef("read_reference_file", "file_read", "Read the extracted text of a reference file (untrusted client data).",
            _obj({"file_id": {"type": "string"}, "offset": {"type": "integer"}, "max_chars": {"type": "integer"}},
                 ["file_id"]), h_read_file),
    ToolDef("list_artifacts", "artifact_read", "List the team's deliverables.", _obj({}, []), h_list_artifacts),
    ToolDef("read_artifact", "artifact_read", "Read a deliverable by name (latest version unless version is given).",
            _obj({"name": {"type": "string"}, "version": {"type": "integer"}}, ["name"]), h_read_artifact),
    ToolDef("write_artifact", "artifact_write",
            "Create or update a deliverable. Writing to an existing name creates a new version. For code use "
            "artifact_type=code and a relative file path as the name (e.g. src/main.py).",
            _obj({"name": {"type": "string"},
                  "artifact_type": {"type": "string", "enum": ["markdown", "json", "csv", "text", "code"]},
                  "content": {"type": "string"}, "summary": {"type": "string", "description": "One or two sentences."},
                  "source_refs": {"type": "array", "items": {"type": "string"},
                                  "description": "Files, deliverables or URLs this content is based on."}},
                 ["name", "artifact_type", "content", "summary"]), h_write_artifact,
            kinds=("work", "subtask", "rework", "consolidation")),
    ToolDef("analyze_table", "data_analysis",
            "Compute statistics over a CSV/JSON reference file or deliverable: describe, group_by or filter.",
            _obj({"source": {"type": "string", "description": "Reference file id or deliverable name"},
                  "operation": {"type": "string", "enum": ["describe", "group_by", "filter"]},
                  "column": {"type": "string"}, "group_by": {"type": "string"},
                  "aggregate": {"type": "string", "enum": ["count", "sum", "mean", "min", "max"]},
                  "comparator": {"type": "string", "enum": ["eq", "gt", "lt", "gte", "lte", "contains"]},
                  "value": {"type": "string"}}, ["source", "operation"]), h_analyze_table),
    ToolDef("ask_client", "client_questions",
            "Ask the client a clarification question when a decision genuinely blocks your work. Your task pauses "
            "until they answer. Do not ask about anything already stated in the requirements.",
            _obj({"question": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
                  "context": {"type": "string", "description": "Why you need this answer."}}, ["question"]),
            h_ask_client),
    ToolDef("delegate_subtask", "delegation",
            "Delegate a well-defined piece of work to a teammate whose specialty fits. Your task waits for the result.",
            _obj({"to_agent": {"type": "string", "description": "Teammate name or role"}, "title": {"type": "string"},
                  "objective": {"type": "string"},
                  "expected_output_type": {"type": "string", "enum": ["markdown", "json", "csv", "text", "code"]},
                  "acceptance_criteria": {"type": "array", "items": {"type": "string"}}},
                 ["to_agent", "title", "objective"]), h_delegate, kinds=("work", "subtask", "rework")),
    ToolDef("run_code", "code_execution", "Run a Python entrypoint from the code deliverables in an isolated sandbox (no network).",
            _obj({"entrypoint": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}},
                 ["entrypoint"]), h_run_code),
    ToolDef("run_tests", "test_execution", "Run pytest over the code deliverables in an isolated sandbox (no network).",
            _obj({"path": {"type": "string", "description": "Optional test path"}}, []), h_run_tests),
    ToolDef("submit_review", None,
            "Record your QA review. List findings with severity (critical/major/minor/info), the affected deliverable "
            "name, the requirement it relates to, evidence, and a recommended correction. Use resolved_finding_keys to "
            "close earlier findings that are now fixed.",
            _obj({"verdict": {"type": "string", "enum": ["pass", "revise"]},
                  "summary": {"type": "string"},
                  "findings": {"type": "array", "items": _obj({
                      "severity": {"type": "string", "enum": ["critical", "major", "minor", "info"]},
                      "artifact": {"type": "string"}, "requirement": {"type": "string"},
                      "evidence": {"type": "string"}, "recommendation": {"type": "string"}},
                      ["severity", "artifact", "requirement", "evidence", "recommendation"])},
                  "resolved_finding_keys": {"type": "array", "items": {"type": "string"}}},
                 ["verdict", "summary", "findings"]), h_submit_review, kinds=("qa",)),
    ToolDef("complete_task", None, "Finish your task with a concise handoff summary for the team.",
            _obj({"summary": {"type": "string"}}, ["summary"]), h_complete),
]
TOOLS_BY_NAME = {t.name: t for t in TOOLS}


def effective_permissions(ctx: ToolContext) -> set[str]:
    perms = services.agent_permissions(ctx.db, ctx.agent)
    if ctx.task.allowed_tools:
        perms &= set(ctx.task.allowed_tools) | {"client_questions"} & perms
    return perms


def tools_for(ctx: ToolContext, provider) -> tuple[list[ToolSpec], dict[str, ToolDef]]:
    perms = effective_permissions(ctx)
    specs: list[ToolSpec] = []
    allowed: dict[str, ToolDef] = {}
    for t in TOOLS:
        if ctx.task.kind not in t.kinds:
            continue
        if t.permission is not None and t.permission not in perms:
            continue
        specs.append(ToolSpec(t.name, t.description, t.schema))
        allowed[t.name] = t
    if ("web_research" in perms and "web_research" in (ctx.run.approved_tools or [])
            and provider.supports_native_tool(ctx.agent.model_id or "", "web_research")):
        specs.append(ToolSpec("web_search", "Web search (provider-hosted)", {}, native={"kind": "web_search", "max_uses": 5}))
    return specs, allowed


async def dispatch(ctx: ToolContext, name: str, args: dict[str, Any], call_id: str, allowed: dict[str, ToolDef]):
    t = allowed.get(name)
    if t is None:
        # Unauthorized or unknown tools fail safely and are logged.
        events.emit(ctx.db, ctx.project.id, "tool_denied",
                    f"{ctx.agent.display_name} tried to use '{name}', which is not authorized for this task",
                    run_id=ctx.run.id, agent_id=ctx.agent.id, task_id=ctx.task.id, data={"tool": name})
        return ToolOutput(f"Tool '{name}' is not authorized for you on this task.", is_error=True)
    if "__invalid_json__" in args:
        return ToolOutput("Tool arguments were not valid JSON. Please retry.", is_error=True)
    if t.name not in {"complete_task", "write_artifact", "submit_review"}:
        events.emit(ctx.db, ctx.project.id, "tool_call", f"{ctx.agent.display_name} used {t.name}",
                    run_id=ctx.run.id, agent_id=ctx.agent.id, task_id=ctx.task.id,
                    data={"tool": t.name, "args": {k: (str(v)[:300]) for k, v in args.items()}})
    try:
        return await t.handler(ctx, args, call_id)
    except Exception as e:  # tool bugs must not crash the run
        return ToolOutput(f"Tool error: {type(e).__name__}: {str(e)[:500]}", is_error=True)


def permission_labels() -> dict[str, dict]:
    return TOOL_PERMISSIONS
