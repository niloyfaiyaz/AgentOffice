import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, money, type Agent, type Budget, type ProjectState, type Task } from "../api";
import { ApprovalCard } from "../components/ApprovalCard";
import { FilesPanel } from "../components/FilesPanel";
import { TeamEditor } from "../components/TeamEditor";
import { useProjectStream } from "../hooks";
import { Badge, Button, Card, Dialog, Empty, ErrorText, Field, StatusBadge, Tabs, fmtTime, inputCls } from "../ui";

type Tab = "overview" | "plan" | "team" | "files" | "chat" | "budget";

export function ProjectDetailPage({ pid }: { pid: string }) {
  const { state, connected } = useProjectStream(pid);
  const [tab, setTab] = useState<Tab>("overview");
  const s = state.data;
  if (state.error) return <ErrorText error={state.error} />;
  if (!s) return <p className="text-sm text-muted">Loading…</p>;
  const pending = s.pending_approvals.length;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold">{s.project.name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-sm">
            <StatusBadge status={s.project.status} />
            {s.current_run && <span className="text-muted">Run {s.current_run.run_number} · phase {s.current_run.phase}</span>}
            <span className="text-muted">· est. spend {money(s.estimated_spend_usd)}</span>
            <span className={`text-xs ${connected ? "text-ok" : "text-muted"}`}>{connected ? "● live" : "○ reconnecting"}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to={`/office/${pid}`} className="rounded-md border border-line bg-panel2 px-3 py-1.5 text-sm hover:brightness-110">Open office</Link>
          <Link to={`/deliverables/${pid}`} className="rounded-md border border-line bg-panel2 px-3 py-1.5 text-sm hover:brightness-110">Deliverables</Link>
        </div>
      </div>
      <RunControls s={s} />
      <Tabs value={tab} onChange={setTab} items={[
        { id: "overview", label: <>Overview{pending > 0 && <Badge tone="warn">{pending}</Badge>}</> },
        { id: "plan", label: "Plan & tasks" }, { id: "team", label: "Team" }, { id: "files", label: "Files" },
        { id: "chat", label: "Talk to the PM" }, { id: "budget", label: "Budget & limits" },
      ]} />
      {tab === "overview" && <Overview s={s} />}
      {tab === "plan" && <PlanBoard s={s} />}
      {tab === "team" && <TeamEditor pid={pid} agents={s.agents} locked={!!s.current_run && !["completed", "failed", "cancelled"].includes(s.current_run.status)} />}
      {tab === "files" && <FilesPanel pid={pid} />}
      {tab === "chat" && <Chat s={s} />}
      {tab === "budget" && <BudgetForm pid={pid} budget={s.budget} />}
    </div>
  );
}

function RunControls({ s }: { s: ProjectState }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const pid = s.project.id;
  const run = s.current_run;
  const active = run && !["completed", "failed", "cancelled"].includes(run.status);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const done = () => { qc.invalidateQueries({ queryKey: ["state", pid] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); };
  const start = useMutation({ mutationFn: () => api.post(`/projects/${pid}/runs`, {}), onSuccess: done });
  const control = useMutation({ mutationFn: (a: string) => api.post(`/runs/${run!.id}/${a}`), onSuccess: done });
  const archive = useMutation({ mutationFn: () => api.post(`/projects/${pid}/${s.project.archived ? "unarchive" : "archive"}`), onSuccess: done });
  const del = useMutation({ mutationFn: () => api.del(`/projects/${pid}`), onSuccess: () => { qc.invalidateQueries({ queryKey: ["projects"] }); nav("/projects"); } });
  const hasPm = s.agents.some((a) => a.is_orchestrator);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-sm">
          {!run && (hasPm ? "Ready when you are: the project manager will draft a statement of work for your approval." : "Hire a Project Manager on the Team tab to begin.")}
          {run?.status === "planning" && "The project manager is drafting the statement of work…"}
          {run?.status === "awaiting_approval" && "The statement of work is waiting for your approval below."}
          {run?.status === "running" && "The team is working."}
          {run?.status === "pausing" && "Pausing: agents stop at their next safe point."}
          {run?.status === "paused" && "Paused. Nothing is running."}
          {run?.status === "blocked" && <span className="text-warn">{run.blocked_reason || "Blocked."}</span>}
          {run?.status === "completed" && "This run is complete. Review and accept the deliverables, or request a revision."}
          {run?.status === "failed" && <span className="text-bad">Run failed: {run.error}</span>}
          {run?.status === "cancelled" && "This run was cancelled."}
          {run && <span className="ml-2 text-xs text-muted">{run.model_calls} model calls{run.worker_active ? " · worker active" : ""}</span>}
        </div>
        <div className="flex flex-wrap gap-2">
          {!active && <Button variant="primary" disabled={!hasPm || start.isPending || s.project.archived} onClick={() => start.mutate()}>
            {run ? "Start a new run" : "Ask the PM for a plan"}</Button>}
          {active && ["running", "planning", "blocked"].includes(run!.status) && <Button onClick={() => control.mutate("pause")}>Pause</Button>}
          {active && ["paused", "pausing"].includes(run!.status) && <Button variant="primary" onClick={() => control.mutate("resume")}>Resume</Button>}
          {active && <Button variant="danger" onClick={() => control.mutate("cancel")}>Cancel run</Button>}
          {!active && <Button variant="ghost" onClick={() => archive.mutate()}>{s.project.archived ? "Unarchive" : "Archive"}</Button>}
          {!active && <Button variant="ghost" onClick={() => setConfirmDelete(true)}>Delete…</Button>}
        </div>
      </div>
      <ErrorText error={start.error || control.error || archive.error || del.error} />
      <Dialog open={confirmDelete} title="Delete this project permanently?" onClose={() => setConfirmDelete(false)}>
        <p className="text-sm">This permanently deletes “{s.project.name}”, its history, deliverables, uploaded files and exports from this
          machine. It cannot be undone. (Archive instead to hide it.)</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => setConfirmDelete(false)}>Keep project</Button>
          <Button variant="danger" onClick={() => del.mutate()}>Delete permanently</Button>
        </div>
      </Dialog>
    </Card>
  );
}

function Overview({ s }: { s: ProjectState }) {
  const qc = useQueryClient();
  const [editing, setEditing] = useState(false);
  const p = s.project;
  const [f, setF] = useState({ name: p.name, objective: p.objective, constraints: p.constraints, success_criteria: p.success_criteria, deliverables: p.deliverables.join("\n") });
  const save = useMutation({
    mutationFn: () => api.patch(`/projects/${p.id}`, { ...f, deliverables: f.deliverables.split("\n") }),
    onSuccess: () => { setEditing(false); qc.invalidateQueries({ queryKey: ["state", p.id] }); },
  });
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <Card title={`Decisions needed (${s.pending_approvals.length})`} className="lg:col-span-5">
        {s.pending_approvals.length === 0 ? <p className="text-sm text-muted">Nothing needs you right now.</p> : (
          <div className="space-y-3">{s.pending_approvals.map((a) => <ApprovalCard key={a.id} a={a} agents={s.agents} />)}</div>
        )}
      </Card>
      <div className="min-w-0 space-y-4 lg:col-span-3">
        <Card title="Run history">
          {s.runs.length === 0 ? <p className="text-sm text-muted">No runs yet.</p> : (
            <ul className="text-sm">{s.runs.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-2 py-1">
                <span>Run {r.run_number} ({r.kind})</span><StatusBadge status={r.status} />
                <span className="text-xs text-muted">{fmtTime(r.started_at)} → {fmtTime(r.finished_at)} · {r.model_calls} calls · {r.review_iterations} review cycles</span>
              </li>))}
            </ul>
          )}
        </Card>
      </div>
      <div className="min-w-0 space-y-4 lg:col-span-2">
        <Card title="Brief" actions={!editing && <Button onClick={() => setEditing(true)}>Edit</Button>}>
          {editing ? (
            <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
              <Field label="Name"><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
              <Field label="Objective"><textarea className={`${inputCls} h-20`} value={f.objective} onChange={(e) => setF({ ...f, objective: e.target.value })} /></Field>
              <Field label="Deliverables (one per line)"><textarea className={`${inputCls} h-20`} value={f.deliverables} onChange={(e) => setF({ ...f, deliverables: e.target.value })} /></Field>
              <Field label="Constraints"><textarea className={`${inputCls} h-14`} value={f.constraints} onChange={(e) => setF({ ...f, constraints: e.target.value })} /></Field>
              <Field label="Success criteria"><textarea className={`${inputCls} h-14`} value={f.success_criteria} onChange={(e) => setF({ ...f, success_criteria: e.target.value })} /></Field>
              <ErrorText error={save.error} />
              <div className="flex justify-end gap-2"><Button type="button" onClick={() => setEditing(false)}>Cancel</Button><Button variant="primary">Save</Button></div>
            </form>
          ) : (
            <dl className="space-y-2 text-sm">
              <div><dt className="font-medium">Objective</dt><dd className="text-muted">{p.objective}</dd></div>
              <div><dt className="font-medium">Deliverables</dt><dd className="text-muted">{p.deliverables.join(" · ") || "—"}</dd></div>
              <div><dt className="font-medium">Constraints</dt><dd className="text-muted">{p.constraints || "—"}</dd></div>
              <div><dt className="font-medium">Success criteria</dt><dd className="text-muted">{p.success_criteria || "—"}</dd></div>
            </dl>
          )}
        </Card>
        <Card title="Requirements on record">
          <ul className="space-y-1 text-sm">
            {s.requirements.map((r) => <li key={r.id}><Badge>{r.kind.replace("_", " ")}</Badge> <span className="text-muted">{r.text}</span></li>)}
          </ul>
        </Card>
      </div>
    </div>
  );
}

const COLUMNS: { key: string; label: string; statuses: string[] }[] = [
  { key: "todo", label: "To do", statuses: ["pending", "ready"] },
  { key: "doing", label: "In progress", statuses: ["running", "paused"] },
  { key: "waiting", label: "Waiting", statuses: ["waiting_approval", "waiting_subtask"] },
  { key: "done", label: "Done", statuses: ["completed", "skipped"] },
  { key: "stopped", label: "Failed / cancelled", statuses: ["failed", "cancelled"] },
];

function TaskCard({ t, agents, tasks }: { t: Task; agents: Agent[]; tasks: Task[] }) {
  const [open, setOpen] = useState(false);
  const who = agents.find((a) => a.id === t.assigned_agent_id);
  const deps = t.depends_on.map((d) => tasks.find((x) => x.id === d)?.title ?? "?");
  return (
    <li className="rounded-md border border-line bg-bg p-2.5 text-sm">
      <button className="w-full text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <div className="flex items-start justify-between gap-2"><span className="font-medium">{t.title}</span>{t.kind !== "work" && <Badge tone="info">{t.kind}</Badge>}</div>
        <div className="mt-1 text-xs text-muted">{who?.display_name ?? "unassigned"} · {money(t.estimated_spend_usd)}{t.retry_count > 0 && ` · retry ${t.retry_count}`}</div>
      </button>
      {open && (
        <div className="mt-2 space-y-1 border-t border-line pt-2 text-xs">
          <p>{t.objective}</p>
          {deps.length > 0 && <p><span className="font-medium">Depends on:</span> {deps.join(", ")}</p>}
          <p className="font-medium">Acceptance criteria</p>
          <ul className="list-disc pl-4">{t.acceptance_criteria.map((c, i) => <li key={i}>{c}</li>)}</ul>
          {t.result_summary && <p><span className="font-medium">Handoff:</span> {t.result_summary}</p>}
          {t.error && <p className="text-bad">{t.error}</p>}
        </div>
      )}
    </li>
  );
}

function PlanBoard({ s }: { s: ProjectState }) {
  if (!s.tasks.length) return <Empty>Tasks appear here once you approve a statement of work.</Empty>;
  return (
    <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-5">
      {COLUMNS.map((c) => {
        const ts = s.tasks.filter((t) => c.statuses.includes(t.status));
        return (
          <section key={c.key} aria-label={c.label} className="rounded-lg border border-line bg-panel p-2.5">
            <h3 className="mb-2 text-sm font-semibold">{c.label} <span className="text-muted">({ts.length})</span></h3>
            <ul className="space-y-2">{ts.map((t) => <TaskCard key={t.id} t={t} agents={s.agents} tasks={s.tasks} />)}</ul>
          </section>
        );
      })}
    </div>
  );
}

interface Msg { id: string; sender: string; intent: string; content: string; created_at: string; task_id: string | null }

function Chat({ s }: { s: ProjectState }) {
  const qc = useQueryClient();
  const pid = s.project.id;
  const msgs = useQuery({ queryKey: ["messages", pid], queryFn: () => api.get<Msg[]>(`/projects/${pid}/messages`) });
  const [text, setText] = useState("");
  const [intent, setIntent] = useState("question");
  const [taskId, setTaskId] = useState("");
  const send = useMutation({
    mutationFn: () => api.post(`/projects/${pid}/messages`, { content: text, intent, task_id: taskId || null }),
    onSuccess: () => { setText(""); qc.invalidateQueries({ queryKey: ["messages", pid] }); qc.invalidateQueries({ queryKey: ["state", pid] }); },
  });
  const pm = s.agents.find((a) => a.is_orchestrator);
  return (
    <Card title={`Conversation with ${pm?.display_name ?? "the project manager"}`}>
      <ol className="mb-3 max-h-96 space-y-2 overflow-y-auto text-sm" aria-live="polite">
        {msgs.data?.length ? msgs.data.map((m) => (
          <li key={m.id} className={`rounded-md p-2 ${m.sender === "user" ? "ml-8 bg-accent/10" : "mr-8 bg-panel2"}`}>
            <div className="text-xs text-muted">{m.sender === "user" ? "You" : pm?.display_name ?? "PM"} · {m.intent.replace("_", " ")} · {fmtTime(m.created_at)}</div>
            <div className="whitespace-pre-wrap">{m.content}</div>
          </li>
        )) : <li className="text-muted">Ask a question, change a requirement, give feedback on a task, or stop the run.</li>}
      </ol>
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); send.mutate(); }}>
        <div className="flex flex-wrap gap-2">
          <select aria-label="Message type" className={`${inputCls} w-auto`} value={intent} onChange={(e) => setIntent(e.target.value)}>
            <option value="question">General question</option>
            <option value="requirement_change">Requirement change</option>
            <option value="task_feedback">Feedback on a task</option>
            <option value="scope_change">Scope change</option>
            <option value="cancel">Cancel the run</option>
          </select>
          {intent === "task_feedback" && (
            <select aria-label="Task" className={`${inputCls} w-auto`} value={taskId} onChange={(e) => setTaskId(e.target.value)}>
              <option value="">Choose task…</option>
              {s.tasks.map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}
            </select>
          )}
        </div>
        <textarea aria-label="Message" className={`${inputCls} h-20`} value={text} onChange={(e) => setText(e.target.value)} required />
        <ErrorText error={send.error} />
        <div className="flex justify-end"><Button variant="primary" disabled={send.isPending || !text || (intent === "task_feedback" && !taskId)}>{send.isPending ? "Sending…" : "Send"}</Button></div>
      </form>
    </Card>
  );
}

function BudgetForm({ pid, budget }: { pid: string; budget: Budget }) {
  const qc = useQueryClient();
  const [f, setF] = useState({
    budget_usd: budget.budget_usd ?? "", approval_threshold_usd: budget.approval_threshold_usd ?? "",
    warning_threshold_pct: budget.warning_threshold_pct, max_model_calls_per_run: budget.max_model_calls_per_run,
    max_concurrency: budget.max_concurrency, max_delegation_depth: budget.max_delegation_depth,
    max_review_iterations: budget.max_review_iterations, task_timeout_seconds: budget.task_timeout_seconds,
  });
  const save = useMutation({
    mutationFn: () => api.put(`/projects/${pid}/budget`, {
      ...f, budget_usd: f.budget_usd === "" ? null : Number(f.budget_usd),
      approval_threshold_usd: f.approval_threshold_usd === "" ? null : Number(f.approval_threshold_usd),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["state", pid] }),
  });
  const num = (k: keyof typeof f, label: string, hint?: string) => (
    <Field label={label} hint={hint}><input className={inputCls} inputMode="decimal" value={String(f[k])} onChange={(e) => setF({ ...f, [k]: e.target.value === "" ? "" : Number(e.target.value) } as typeof f)} /></Field>
  );
  return (
    <Card title="Budget and execution limits">
      <p className="mb-3 text-sm text-muted">Limits are checked before every model call using estimated costs. They are AgentOffice controls, not provider
        billing caps: providers bill actual usage, which can differ and may be reported later.</p>
      <form className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {num("budget_usd", "Project budget (USD)", "Blank = no budget")}
        {num("approval_threshold_usd", "Ask me before spend passes (USD)")}
        {num("warning_threshold_pct", "Warn at % of budget")}
        {num("max_model_calls_per_run", "Max model calls per run")}
        {num("max_concurrency", "Agents working in parallel")}
        {num("max_delegation_depth", "Max delegation depth")}
        {num("max_review_iterations", "Max QA rework cycles")}
        {num("task_timeout_seconds", "Task time limit (seconds)")}
        <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
          <Button variant="primary" disabled={save.isPending}>Save limits</Button>
          {save.isSuccess && <span className="text-sm text-ok">Saved</span>}
          <ErrorText error={save.error} />
        </div>
      </form>
    </Card>
  );
}
