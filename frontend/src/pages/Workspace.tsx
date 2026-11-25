import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useParams } from "react-router-dom";
import { api, money, type Artifact, type Finding, type ProjectState } from "../api";
import { ApprovalCard } from "../components/ApprovalCard";
import { ProjectSwitcher } from "../components/ProjectSwitcher";
import { TeamEditor } from "../components/TeamEditor";
import { rememberProject, useProjectStream } from "../hooks";
import { situation } from "../office/situation";
import { ActivityPage } from "./Activity";
import { CostsPage } from "./Costs";
import { DeliverablesPage } from "./Deliverables";
import { MessagesPage } from "./Messages";
import { OfficeView } from "./Office";
import { BudgetForm, PlanBoard, RequirementsCard, RunControls } from "./ProjectDetail";
import { Badge, Button, Card, Empty, ErrorText, StatusBadge, fmtTime, inputCls } from "../ui";

const PHASES: Record<string, string[]> = {
  software: ["Discover", "Requirements", "Plan", "Build & test", "Review & deliver"],
  research: ["Discover", "Define questions", "Plan", "Research & write", "Review & deliver"],
  default: ["Discover", "Define", "Plan", "Execute", "Review & deliver"],
};

/** Where the project is in ordinary delivery terms. Informational only: it never gates anything. */
export function phaseOf(s: ProjectState): number {
  const b = s.brief;
  if (b && b.status && b.status !== "confirmed" && !s.current_run) return b.status === "discovering" ? 0 : 1;
  const run = s.current_run;
  if (!run || ["planning", "awaiting_approval"].includes(run.status)) return 2;
  if (run.status === "completed") return 4;
  const late = s.tasks.some((t) => ["qa", "consolidation"].includes(t.kind) && t.status !== "pending");
  return late ? 4 : 3;
}

function PhaseStrip({ s }: { s: ProjectState }) {
  const labels = PHASES[s.brief?.project_type ?? ""] ?? PHASES.default;
  const cur = phaseOf(s);
  const done = s.current_run?.status === "completed";
  return (
    <ol aria-label="Delivery phase" className="flex flex-wrap gap-1 text-xs">
      {labels.map((l, i) => (
        <li key={l} aria-current={i === cur ? "step" : undefined}
          className={`rounded-full px-2.5 py-0.5 ${i === cur ? "bg-accent text-accentInk" : i < cur || done ? "bg-panel2 text-ink" : "text-muted"}`}>
          {i < cur || (done && i === cur) ? "✓ " : ""}{l}
        </li>
      ))}
    </ol>
  );
}

const TABS = [
  { to: "", label: "Office & overview" }, { to: "messages", label: "Messages" }, { to: "plan", label: "Work plan" },
  { to: "deliverables", label: "Deliverables" }, { to: "team", label: "Team & costs" },
];

/** The project workspace. Everything inside is keyed by the project id, so switching projects
 * remounts every view: no office character, message or cost can leak between projects. */
export function Workspace() {
  const { pid } = useParams();
  if (!pid) return <Navigate to="/" replace />;
  rememberProject(pid);
  return <WorkspaceInner key={pid} pid={pid} />;
}

function WorkspaceInner({ pid }: { pid: string }) {
  const { state, connected } = useProjectStream(pid);
  const loc = useLocation();
  const s = state.data;
  if (state.error) return <ErrorText error={state.error} />;
  if (!s) return <p className="text-sm text-muted">Loading…</p>;
  const run = s.current_run;
  if (!run || (run.run_number === 1 && ["planning", "awaiting_approval"].includes(run.status))) return <Navigate to={`/new/${pid}`} replace />;
  const tab = loc.pathname.split("/")[3] ?? "";
  const pendingQuestions = s.pending_approvals.length;
  const openQuestions = s.pending_approvals.filter((a) => a.kind === "clarification").length;
  return (
    <div className="space-y-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <ProjectSwitcher current={s.project} tab={tab} />
          {run.status === "blocked" && pendingQuestions > 0 ? <Badge tone="warn">Waiting for you</Badge> : <StatusBadge status={run.status} />}
          {pendingQuestions > 0 && <Badge tone="warn">{pendingQuestions} decision{pendingQuestions > 1 ? "s" : ""} for you</Badge>}
          <span className="text-xs text-muted">est. spend {money(s.estimated_spend_usd)}</span>
          <span className={`text-xs ${connected ? "text-ok" : "text-muted"}`}>{connected ? "● live" : "○ reconnecting"}</span>
        </div>
        <PhaseStrip s={s} />
        <nav aria-label="Project sections" className="flex flex-wrap gap-1 border-b border-line">
          {TABS.map((t) => (
            <NavLink key={t.to} to={`/p/${pid}${t.to ? `/${t.to}` : ""}`} end={t.to === ""}
              className={({ isActive }) => `-mb-px border-b-2 px-3 py-2 text-sm ${isActive ? "border-accent text-ink" : "border-transparent text-muted hover:text-ink"}`}>
              {t.label}{t.to === "messages" && openQuestions > 0 && <span aria-label={`${openQuestions} open questions`} className="ml-1 rounded-full bg-warn/20 px-1.5 text-xs text-warn">{openQuestions}</span>}
            </NavLink>
          ))}
        </nav>
      </header>
      <Routes>
        <Route index element={<Overview s={s} />} />
        <Route path="messages" element={<MessagesPage pid={pid} s={s} thread="team" />} />
        <Route path="messages/:thread" element={<ThreadRoute pid={pid} s={s} />} />
        <Route path="plan" element={<WorkPlan s={s} />} />
        <Route path="deliverables" element={<DeliverablesPage pid={pid} />} />
        <Route path="team" element={<TeamAndCosts s={s} />} />
        <Route path="activity" element={<ActivityPage pid={pid} />} />
        <Route path="*" element={<Navigate to={`/p/${pid}`} replace />} />
      </Routes>
    </div>
  );
}

function ThreadRoute({ pid, s }: { pid: string; s: ProjectState }) {
  const { thread } = useParams();
  return <MessagesPage pid={pid} s={s} thread={thread ?? "team"} />;
}

// -- Office & overview -----------------------------------------------------------------------
export function nextAction(s: ProjectState): { text: string; to?: string } {
  const pid = s.project.id;
  const pend = s.pending_approvals;
  const q = pend.find((a) => a.kind === "clarification");
  if (q) {
    const pm = s.agents.find((a) => a.is_orchestrator);
    const who = s.agents.find((a) => a.id === q.agent_id);
    return { text: `Answer ${who?.display_name ?? "the team"}'s question: “${q.title}”`, to: `/p/${pid}/messages/${!who || who.id === pm?.id ? "team" : `agent:${who.id}`}` };
  }
  const acc = pend.find((a) => a.kind === "deliverable_acceptance");
  if (acc) return { text: "Review the delivery below, then accept it or request a revision." };
  if (pend.length) return { text: `Make the decision${pend.length > 1 ? "s" : ""} below (${pend.map((a) => a.title).join("; ")}).` };
  const run = s.current_run;
  if (run?.status === "paused") return { text: "The project is paused. Resume it on the Work plan tab when ready.", to: `/p/${pid}/plan` };
  if (run?.status === "failed") return { text: `The run failed (${run.error}). Retry or start a new run from the Work plan tab.`, to: `/p/${pid}/plan` };
  if (run?.status === "completed") return { text: "Download the export, or request a revision if anything should change.", to: `/p/${pid}/deliverables` };
  if (run?.status === "cancelled") return { text: "This run was cancelled. Start a new run from the Work plan tab if needed.", to: `/p/${pid}/plan` };
  return { text: "Nothing needs you right now. The team is working; you'll find questions here and in your Inbox." };
}

function ago(iso: string): string {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : new Date(iso).toLocaleDateString();
}

function Overview({ s }: { s: ProjectState }) {
  const busy = s.agents.map((a) => ({ a, st: situation(a, s) })).filter((x) => !["idle", "completed"].includes(x.st.kind));
  const next = nextAction(s);
  const done = s.current_run?.status === "completed";
  const decisions = s.pending_approvals.filter((a) => !(done && a.kind === "deliverable_acceptance"));
  return (
    <div className="space-y-4">
      <Card title="Where things stand">
        <div className="grid gap-3 text-sm md:grid-cols-3">
          <div>
            <h3 className="text-xs uppercase tracking-wide text-muted">Last update</h3>
            <p>{s.last_update ? <>{s.last_update.message} <span className="text-xs text-muted">({ago(s.last_update.created_at)})</span></> : "Nothing yet."}</p>
          </div>
          <div>
            <h3 className="text-xs uppercase tracking-wide text-muted">The team</h3>
            {busy.length ? <ul className="space-y-0.5">{busy.slice(0, 5).map(({ a, st }) => <li key={a.id}><span aria-hidden>{st.icon} </span><span className="font-medium">{a.display_name}</span>: {st.label}</li>)}</ul>
              : <p>{done ? "Everyone has finished." : "No one is working right now."}</p>}
          </div>
          <div>
            <h3 className="text-xs uppercase tracking-wide text-muted">Next step</h3>
            <p className="font-medium">{next.to ? <Link className="text-accent underline" to={next.to}>{next.text}</Link> : next.text}</p>
          </div>
        </div>
      </Card>
      {decisions.length > 0 && (
        <Card title={`Needs your decision (${decisions.length})`}>
          <div className="space-y-3">{decisions.map((a) => <ApprovalCard key={a.id} a={a} agents={s.agents} compact />)}</div>
        </Card>
      )}
      {done && <Handover s={s} />}
      <OfficeView pid={s.project.id} />
    </div>
  );
}

function Handover({ s }: { s: ProjectState }) {
  const pid = s.project.id;
  const arts = useQuery({ queryKey: ["artifacts", pid], queryFn: () => api.get<Artifact[]>(`/projects/${pid}/artifacts`) });
  const findings = useQuery({ queryKey: ["findings", pid], queryFn: () => api.get<Finding[]>(`/projects/${pid}/findings`) });
  const acc = s.pending_approvals.find((a) => a.kind === "deliverable_acceptance");
  const reqs = s.requirements.filter((r) => r.status === "active" && ["requirement", "constraint", "success_criterion", "change", "clarification"].includes(r.kind));
  const covered = new Set(s.tasks.filter((t) => t.status === "completed").flatMap((t) => t.requirement_refs ?? []));
  const open = (findings.data ?? []).filter((f) => !["resolved"].includes(f.status) && f.severity !== "info");
  const assumptions = s.requirements.filter((r) => r.status === "active" && r.kind === "assumption");
  const deliverables = (arts.data ?? []).filter((a) => a.category === "deliverable" || a.category === "summary");
  return (
    <Card title="Delivery summary" className="border-ok/50">
      <div className="grid gap-4 text-sm lg:grid-cols-2">
        <div className="space-y-3">
          <div><h3 className="font-medium">Objective</h3><p className="text-muted">{s.brief?.objective?.text ?? s.project.objective}</p></div>
          <div><h3 className="font-medium">Deliverables ({deliverables.length})</h3>
            {deliverables.length ? <ul className="list-disc pl-5">{deliverables.map((a) => (
              <li key={a.id}><Link className="text-accent underline" to={`/p/${pid}/deliverables?artifact=${a.id}`}>{a.name}</Link> v{a.current_version}
                {a.stale && <Badge tone="warn">stale</Badge>}</li>))}</ul> : <p className="text-muted">None recorded.</p>}
          </div>
          <div><h3 className="font-medium">Requirements coverage</h3>
            <p>{reqs.filter((r) => r.ref && covered.has(r.ref)).length} of {reqs.length} requirement items are linked to completed work.</p>
            {reqs.some((r) => r.ref && !covered.has(r.ref)) && <p className="text-xs text-muted">Not linked: {reqs.filter((r) => r.ref && !covered.has(r.ref)).map((r) => r.ref).join(", ")}
              (links show which work cites a requirement; they are not proof it is met).</p>}
          </div>
        </div>
        <div className="space-y-3">
          <div><h3 className="font-medium">QA results</h3>
            <p>{s.tasks.some((t) => t.kind === "qa" && t.status === "completed") ? `${(findings.data ?? []).length} finding(s) recorded, ${open.length} unresolved.` : "No independent QA review ran."}
              <span className="block text-xs text-muted">A QA pass is a review opinion, not proof of correctness.</span></p>
            {open.length > 0 && <ul className="list-disc pl-5 text-xs">{open.map((f) => <li key={f.id}>{f.finding_key} [{f.severity}] {f.evidence}</li>)}</ul>}
          </div>
          <div><h3 className="font-medium">Assumptions</h3>
            {assumptions.length ? <ul className="list-disc pl-5 text-xs">{assumptions.map((r) => <li key={r.id}>{r.text}</li>)}</ul> : <p className="text-muted">None recorded.</p>}
          </div>
          <div><h3 className="font-medium">Total estimated usage cost</h3><p>{money(s.estimated_spend_usd)} <span className="text-xs text-muted">(estimate; your provider bills actual usage)</span></p></div>
          <div><h3 className="font-medium">Recommended next actions</h3>
            <p className="text-muted">{open.length ? "Review the unresolved findings before accepting, or request a revision." : "Read each deliverable, then accept or request a revision. Export a ZIP for sharing."}</p>
          </div>
        </div>
      </div>
      <div className="mt-4 space-y-3 border-t border-line pt-3">
        <a href={`/api/projects/${pid}/export`} download className="inline-block rounded-md bg-accent px-3 py-1.5 text-sm font-semibold text-accentInk">Export all deliverables (.zip)</a>
        {acc ? <ApprovalCard a={acc} agents={s.agents} /> : <p className="text-sm text-muted">The delivery decision has been recorded.</p>}
      </div>
    </Card>
  );
}

// -- Work plan --------------------------------------------------------------------------------
function WorkPlan({ s }: { s: ProjectState }) {
  const qc = useQueryClient();
  const pid = s.project.id;
  const [text, setText] = useState("");
  const [reply, setReply] = useState("");
  const send = useMutation({
    mutationFn: (intent: string) => api.post<{ reply: string }>(`/projects/${pid}/messages`, { content: text, intent }),
    onSuccess: (r) => { setText(""); setReply(r.reply); for (const k of ["state", "messages", "threads", "inbox"]) qc.invalidateQueries({ queryKey: [k] }); },
  });
  const sow = s.pending_approvals.find((a) => a.kind === "sow");
  const changes = s.pending_approvals.filter((a) => ["requirement_change", "scope_change", "stale_artifacts"].includes(a.kind));
  return (
    <div className="space-y-4">
      <RunControls s={s} />
      {sow && <Card title="Revised plan for your approval"><ApprovalCard a={sow} agents={s.agents} /></Card>}
      {changes.map((a) => <ApprovalCard key={a.id} a={a} agents={s.agents} />)}
      {s.tasks.length ? <PlanBoard s={s} /> : <Empty>Tasks appear here once a plan is approved.</Empty>}
      <div className="grid gap-4 lg:grid-cols-2">
        <RequirementsCard s={s} />
        <Card title="Change a requirement or the scope">
          <p className="mb-2 text-sm text-muted">Describe the change. AgentOffice works out which requirements it replaces and which work is affected,
            keeps unaffected work, estimates the rework cost and asks you to confirm before anything changes.</p>
          <textarea aria-label="Describe the change" className={`${inputCls} h-24`} value={text} onChange={(e) => setText(e.target.value)} />
          <ErrorText error={send.error} />
          <div className="mt-2 flex flex-wrap justify-end gap-2">
            <Button disabled={!text.trim() || send.isPending} onClick={() => send.mutate("scope_change")}>It changes the scope</Button>
            <Button variant="primary" disabled={!text.trim() || send.isPending} onClick={() => send.mutate("requirement_change")}>Submit requirement change</Button>
          </div>
          {reply && <p role="status" className="mt-2 rounded-md bg-panel2 p-2 text-sm">{reply}</p>}
        </Card>
      </div>
    </div>
  );
}

// -- Team & costs ------------------------------------------------------------------------------
function TeamAndCosts({ s }: { s: ProjectState }) {
  const pid = s.project.id;
  const active = !!s.current_run && !["completed", "failed", "cancelled"].includes(s.current_run.status);
  return (
    <div className="space-y-4">
      <TeamEditor pid={pid} agents={s.agents} locked={active} />
      <CostsPage pid={pid} />
      <details className="rounded-lg border border-line bg-panel p-3">
        <summary className="cursor-pointer text-sm font-medium">Budget and execution limits (advanced)</summary>
        <div className="mt-3"><BudgetForm pid={pid} budget={s.budget} /></div>
      </details>
      <p className="text-sm text-muted">More: <Link className="text-accent underline" to={`/p/${pid}/activity`}>full activity log</Link> ·{" "}
        <Link className="text-accent underline" to="/settings/agents">agent library</Link> · project created {fmtTime(s.project.created_at)}</p>
    </div>
  );
}
