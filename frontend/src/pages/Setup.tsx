import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import {
  api, BRIEF_LISTS, money, type Basis, type Brief, type BriefItem, type BriefList, type DiscoveryView, type ProjectState,
  type RecommendedRole,
} from "../api";
import { SowEditor } from "../components/ApprovalCard";
import { Composer } from "../components/Composer";
import { TeamEditor } from "../components/TeamEditor";
import { useBootstrap, useProjectState } from "../hooks";
import { AvatarIcon, Badge, Button, Card, ErrorText, Field, inputCls } from "../ui";

const LIST_LABEL: Record<BriefList, string> = {
  requirements: "Requirements", deliverables: "Deliverables", scope_in: "In scope", scope_out: "Out of scope",
  constraints: "Constraints", assumptions: "Assumptions (please review)", success_criteria: "Success criteria",
  open_questions: "Open questions",
};
const BASIS: Record<Basis, { label: string; tone: "info" | "warn" | "ok" }> = {
  client_stated: { label: "From you", tone: "info" },
  client_edited: { label: "Edited by you", tone: "ok" },
  ai_proposed: { label: "AI proposal", tone: "warn" },
};
const STEPS = ["Describe & clarify", "Project brief", "Team", "Review & approve"] as const;

type Stage = 0 | 1 | 2 | 3;

function stageOf(d: DiscoveryView | undefined, s: ProjectState | undefined): Stage | "workspace" {
  if (!d || !s) return 0;
  const run = s.current_run;
  if (run && !["planning", "awaiting_approval"].includes(run.status)) return "workspace";
  if (run) return 3;
  if (d.brief.status === "confirmed") return 2;
  return d.brief.status === "discovering" && d.brief.questions.length ? 0 : 1;
}

export function SetupPage({ pid }: { pid: string }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const disc = useQuery({ queryKey: ["discovery", pid], queryFn: () => api.get<DiscoveryView>(`/projects/${pid}/discovery`) });
  const state = useProjectState(pid);
  const run = state.data?.current_run;
  // While the PM drafts the plan, poll (the SSE stream is used inside the workspace).
  useEffect(() => {
    if (run?.status !== "planning") return;
    const t = setInterval(() => qc.invalidateQueries({ queryKey: ["state", pid] }), 1500);
    return () => clearInterval(t);
  }, [run?.status, pid, qc]);
  const auto = stageOf(disc.data, state.data);
  const [view, setView] = useState<Stage | null>(null);
  if (disc.error) return <ErrorText error={disc.error} />;
  if (!disc.data || !state.data) return <p className="text-sm text-muted">Loading…</p>;
  if (auto === "workspace") return <Navigate to={`/p/${pid}`} replace />;
  const reached = auto as Stage;
  const stage = view !== null && view <= reached ? view : reached;
  const refresh = () => { qc.invalidateQueries({ queryKey: ["discovery", pid] }); qc.invalidateQueries({ queryKey: ["state", pid] }); };
  return (
    <div className="mx-auto max-w-6xl space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wide text-muted">New project</p>
          <h1 className="truncate text-2xl font-semibold">{disc.data.brief.name?.text ?? disc.data.project.name}</h1>
        </div>
        <ol aria-label="Setup steps" className="flex flex-wrap gap-1 text-sm">
          {STEPS.map((label, i) => (
            <li key={label}>
              <button disabled={i > reached} onClick={() => setView(i as Stage)} aria-current={stage === i ? "step" : undefined}
                className={`rounded-full px-3 py-1 ${stage === i ? "bg-accent text-accentInk" : i <= reached ? "bg-panel2 hover:brightness-110" : "text-muted"}`}>
                {i < reached ? "✓ " : `${i + 1}. `}{label}
              </button>
            </li>
          ))}
        </ol>
      </div>
      {stage <= 1 && <DiscoverStep d={disc.data} onChange={refresh} onConfirmed={() => { setView(2); refresh(); }} />}
      {stage === 2 && <TeamStep pid={pid} s={state.data} onPlanned={() => { setView(3); refresh(); }} />}
      {stage === 3 && <ReviewStep pid={pid} d={disc.data} s={state.data} onStarted={() => nav(`/p/${pid}`)} onBack={(st) => setView(st)} />}
    </div>
  );
}

// -- Steps 1-2: conversation + live brief ---------------------------------------------------------
function DiscoverStep({ d, onChange, onConfirmed }: { d: DiscoveryView; onChange: () => void; onConfirmed: () => void }) {
  const pid = d.project.id;
  const [draft, setDraft] = useState<Brief>(d.brief);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (!dirty) setDraft(d.brief); }, [d.brief, dirty]);
  const save = useMutation({
    mutationFn: () => api.put<DiscoveryView>(`/projects/${pid}/brief`, draft),
    onSuccess: () => { setDirty(false); onChange(); },
  });
  const turn = useMutation({
    mutationFn: async (content: string) => {
      if (dirty) { await api.put(`/projects/${pid}/brief`, draft); setDirty(false); }
      return api.post<DiscoveryView>(`/projects/${pid}/discovery/turn`, { content });
    },
    onSuccess: onChange,
  });
  const confirm = useMutation({
    mutationFn: async () => {
      if (dirty) await api.put(`/projects/${pid}/brief`, draft);
      return api.post(`/projects/${pid}/brief/confirm`);
    },
    onSuccess: () => { setDirty(false); onConfirmed(); },
  });
  const edit = (b: Brief) => { setDraft(b); setDirty(true); };
  const pmName = d.pm?.display_name ?? "Your project manager";
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <Card title={`Conversation with ${pmName}`} className="min-w-0">
        <Conversation d={d} busy={turn.isPending} onSend={(t) => turn.mutate(t)} />
        <ErrorText error={turn.error} />
      </Card>
      <div className="min-w-0 space-y-3">
        <BriefEditor brief={draft} onEdit={edit} />
        <ErrorText error={save.error || confirm.error} />
        <div className="flex flex-wrap items-center justify-end gap-2">
          {dirty && <span className="text-xs text-muted">Unsaved edits</span>}
          {dirty && <Button onClick={() => save.mutate()} disabled={save.isPending}>Save edits</Button>}
          <Button variant="primary" disabled={confirm.isPending || !draft.objective?.text}
            onClick={() => confirm.mutate()}>Confirm brief & choose team</Button>
        </div>
        {draft.status === "discovering" && draft.questions.length > 0 && (
          <p className="text-right text-xs text-muted">You can confirm now: unanswered questions become open questions and assumptions.</p>
        )}
      </div>
    </div>
  );
}

function Conversation({ d, busy, onSend }: { d: DiscoveryView; busy: boolean; onSend: (t: string) => void }) {
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [d.messages.length, busy]);
  const pm = d.pm;
  const qs = d.brief.questions;
  return (
    <div className="flex flex-col gap-3">
      <ol className="max-h-[52vh] space-y-2 overflow-y-auto pr-1 text-sm" aria-label="Discovery conversation" aria-live="polite">
        {d.messages.map((m) => (
          <li key={m.id} className={`rounded-lg p-2.5 ${m.sender === "user" ? "ml-8 bg-accent/10" : m.sender === "system" ? "border border-warn/40 bg-warn/10" : "mr-6 bg-panel2"}`}>
            <div className="mb-0.5 flex items-center gap-2 text-xs text-muted">
              {m.sender === "agent" && pm && <AvatarIcon avatar={pm.avatar} size={1} />}
              {m.sender === "user" ? "You" : m.sender === "system" ? "AgentOffice" : pm?.display_name ?? "PM"}
              {m.data?.test_provider && <Badge tone="warn">test provider — not AI</Badge>}
            </div>
            <div className="whitespace-pre-wrap">{m.content}</div>
          </li>
        ))}
        {busy && <li className="mr-6 rounded-lg bg-panel2 p-2.5 text-sm text-muted">{pm?.display_name ?? "The PM"} is thinking…</li>}
        <li ref={end} aria-hidden />
      </ol>
      {qs.length > 0 && !busy && (
        <div className="space-y-2" aria-label="Questions from your project manager">
          {qs.map((q) => (
            <div key={q.id} className="rounded-lg border border-line p-2.5 text-sm">
              <p className="font-medium">{q.question}</p>
              {q.why && <p className="text-xs text-muted">Why it matters: {q.why}</p>}
              <div className="mt-2 flex flex-wrap gap-1.5">
                {q.options.map((o) => <Button key={o} onClick={() => onSend(`${q.question} — ${o}`)}>{o}</Button>)}
                {!q.options.some((o) => /don.?t know/i.test(o)) && <Button variant="ghost" onClick={() => onSend(`${q.question} — I don't know; please make a reasonable assumption.`)}>I don't know</Button>}
              </div>
            </div>
          ))}
        </div>
      )}
      {d.provider_ready ? (
        <Composer onSend={onSend} busy={busy} label="Reply to your project manager"
          placeholder={qs.length ? "Answer in your own words…" : "Add anything else, or confirm the brief →"} />
      ) : (
        <p className="text-xs text-muted">Connect an AI provider in <Link className="text-accent underline" to="/settings">Settings</Link> to continue the conversation. You can still edit and confirm the brief yourself.</p>
      )}
    </div>
  );
}

function ItemRow({ it, onChange, onRemove, label }: { it: BriefItem; onChange: (t: string) => void; onRemove: () => void; label: string }) {
  const b = BASIS[it.basis] ?? BASIS.ai_proposed;
  return (
    <li className="flex items-start gap-2">
      <input aria-label={label} className={`${inputCls} flex-1`} value={it.text} onChange={(e) => onChange(e.target.value)} />
      <Badge tone={b.tone} title={b.label}>{b.label}</Badge>
      <Button variant="ghost" aria-label={`Remove: ${it.text}`} onClick={onRemove}>✕</Button>
    </li>
  );
}

export function BriefEditor({ brief, onEdit }: { brief: Brief; onEdit: (b: Brief) => void }) {
  const [adding, setAdding] = useState<Record<string, string>>({});
  const scalar = (k: "name" | "objective" | "audience", label: string, area = false) => {
    const it = brief[k];
    const set = (t: string) => onEdit({ ...brief, [k]: { id: it?.id ?? `new-${k}`, text: t, basis: "client_edited" } });
    const b = it ? BASIS[it.basis] : null;
    return (
      <Field label={label}>
        <div className="flex items-start gap-2">
          {area ? <textarea aria-label={label} className={`${inputCls} h-20 flex-1`} value={it?.text ?? ""} onChange={(e) => set(e.target.value)} />
            : <input aria-label={label} className={`${inputCls} flex-1`} value={it?.text ?? ""} onChange={(e) => set(e.target.value)} />}
          {b && <Badge tone={b.tone}>{b.label}</Badge>}
        </div>
      </Field>
    );
  };
  const list = (k: BriefList) => {
    const items = brief[k];
    const upd = (xs: BriefItem[]) => onEdit({ ...brief, [k]: xs });
    if (k === "open_questions" && !items.length) return null;
    return (
      <section key={k} aria-label={LIST_LABEL[k]}>
        <h4 className="mb-1 text-sm font-medium">{LIST_LABEL[k]} <span className="text-muted">({items.length})</span></h4>
        <ul className="space-y-1.5">
          {items.map((it, i) => (
            <ItemRow key={it.id} it={it} label={`${LIST_LABEL[k]} ${i + 1}`}
              onChange={(t) => upd(items.map((x, j) => (j === i ? { ...x, text: t, basis: "client_edited" } : x)))}
              onRemove={() => upd(items.filter((_, j) => j !== i))} />
          ))}
        </ul>
        <form className="mt-1.5 flex gap-2" onSubmit={(e) => {
          e.preventDefault();
          const t = (adding[k] ?? "").trim();
          if (!t) return;
          upd([...items, { id: `new-${Date.now()}`, text: t, basis: "client_edited" }]);
          setAdding({ ...adding, [k]: "" });
        }}>
          <input aria-label={`Add to ${LIST_LABEL[k]}`} placeholder="Add…" className={`${inputCls} flex-1`} value={adding[k] ?? ""}
            onChange={(e) => setAdding({ ...adding, [k]: e.target.value })} />
          <Button type="submit" variant="ghost">Add</Button>
        </form>
      </section>
    );
  };
  return (
    <Card title="Project brief" actions={<span className="text-xs text-muted">{brief.method === "ai" ? "Drafted by your PM (AI) — edit anything"
      : brief.method === "heuristic" ? "Prefilled from your text (not AI)" : brief.method === "scripted-test" ? "Scripted test draft (not AI)" : ""}</span>}>
      <div className="space-y-3">
        <p className="flex flex-wrap gap-2 text-xs text-muted">Labels:
          {Object.values(BASIS).map((b) => <Badge key={b.label} tone={b.tone}>{b.label}</Badge>)}
          — AI proposals are only adopted when you confirm the brief.</p>
        {scalar("name", "Project name")}
        {scalar("objective", "Objective / problem statement", true)}
        {scalar("audience", "Intended audience")}
        {BRIEF_LISTS.map((k) => list(k))}
        {brief.history.length > 0 && (
          <details className="text-xs text-muted"><summary className="cursor-pointer">Brief history ({brief.history.length})</summary>
            <ul className="mt-1 space-y-0.5">{brief.history.map((h, i) => <li key={i}>{new Date(h.at).toLocaleString()} — {h.summary}</li>)}</ul>
          </details>
        )}
      </div>
    </Card>
  );
}

// -- Step 3: recommended team --------------------------------------------------------------------
function ModelLine({ m }: { m: RecommendedRole["model"] }) {
  return (
    <span className="text-xs text-muted">
      {m.display_name} · {m.cost_tier}
      {m.priced && m.input_price_per_mtok !== null && ` · ${money(m.input_price_per_mtok, 2)}/${money(m.output_price_per_mtok, 2)} per M tokens`}
      {m.typical_task ? ` · typical task ≈ ${money(m.typical_task.usd)} (from ${m.typical_task.samples} past tasks)` : " · no cost history yet"}
      {!m.ready && <span className="text-warn"> · provider not connected</span>}
    </span>
  );
}

function TeamStep({ pid, s, onPlanned }: { pid: string; s: ProjectState; onPlanned: () => void }) {
  const qc = useQueryClient();
  const boot = useBootstrap();
  const rec = useQuery({ queryKey: ["recommended", pid], queryFn: () => api.get<{ basis: string; roles: RecommendedRole[] }>(`/projects/${pid}/team/recommended`) });
  const [skip, setSkip] = useState<string[]>([]);
  const hired = s.agents.length > 1 || (rec.data?.roles.every((r) => r.hired) ?? false);
  const [accepted, setAccepted] = useState(hired);
  const accept = useMutation({
    mutationFn: () => api.post(`/projects/${pid}/team/hire`, { role_keys: rec.data!.roles.map((r) => r.role_key).filter((k) => !skip.includes(k)) }),
    onSuccess: () => { setAccepted(true); for (const k of ["state", "recommended"]) qc.invalidateQueries({ queryKey: [k] }); },
  });
  const plan = useMutation({ mutationFn: () => api.post(`/projects/${pid}/runs`, {}), onSuccess: onPlanned });
  const perm = boot.data?.tool_permissions ?? {};
  return (
    <div className="space-y-4">
      {!accepted && (
        <Card title="Recommended team" actions={<span className="text-xs text-muted">Basis: {rec.data?.basis ?? "…"}</span>}>
          <p className="mb-3 text-sm text-muted">The smallest team that covers your brief. Untick anyone you don't need; you can add,
            remove and customize agents next.</p>
          <ul className="grid gap-3 md:grid-cols-2">
            {rec.data?.roles.map((r) => {
              const on = !skip.includes(r.role_key);
              const pm = r.role_key === "project_manager";
              return (
                <li key={r.role_key} className={`rounded-lg border p-3 text-sm ${on ? "border-accent/60" : "border-line opacity-60"}`}>
                  <label className="flex items-start gap-3">
                    <input type="checkbox" className="mt-1" checked={on} disabled={pm}
                      onChange={(e) => setSkip(e.target.checked ? skip.filter((x) => x !== r.role_key) : [...skip, r.role_key])}
                      aria-label={`Include ${r.name}, ${r.role}`} />
                    <AvatarIcon avatar={r.avatar} size={3} />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{r.name} — {r.role}</span>
                      <span className="block">{r.responsibility}</span>
                      <span className="block text-xs text-muted">Why: {r.reason}</span>
                      <ModelLine m={r.model} />
                      <span className="mt-1 block text-xs text-muted">Can: {r.tools.map((t) => perm[t]?.label ?? t).join(", ") || "—"}</span>
                    </span>
                  </label>
                </li>
              );
            })}
          </ul>
          <ErrorText error={accept.error} />
          <div className="mt-3 flex justify-end"><Button variant="primary" disabled={!rec.data || accept.isPending} onClick={() => accept.mutate()}>Accept team</Button></div>
        </Card>
      )}
      {accepted && (
        <>
          <TeamEditor pid={pid} agents={s.agents} hideSuggestions />
          <ErrorText error={plan.error} />
          <div className="flex flex-wrap items-center justify-end gap-2">
            <span className="text-xs text-muted">Change any agent's model, instructions, tools or spending limit above (Edit), or continue with the defaults.</span>
            <Button variant="primary" disabled={plan.isPending || !s.agents.some((a) => a.is_orchestrator)} onClick={() => plan.mutate()}>
              Ask {s.agents.find((a) => a.is_orchestrator)?.display_name ?? "the PM"} for the work plan
            </Button>
          </div>
        </>
      )}
    </div>
  );
}

// -- Step 4: one integrated review with the existing SOW approval ---------------------------------
interface Estimate { available: boolean; partial?: boolean; total_usd?: number; missing_models?: string[]; reason?: string;
  lines: { title: string; agent: string | null; model: string | null; usd: number | null; samples: number }[]; basis?: string }

function ReviewStep({ pid, d, s, onStarted, onBack }: { pid: string; d: DiscoveryView; s: ProjectState; onStarted: () => void; onBack: (st: Stage) => void }) {
  const qc = useQueryClient();
  const boot = useBootstrap();
  const run = s.current_run!;
  const sow = s.pending_approvals.find((a) => a.kind === "sow");
  const est = useQuery({ queryKey: ["estimate", pid, sow?.id], enabled: !!sow, queryFn: () => api.get<Estimate>(`/projects/${pid}/estimate`) });
  const [budget, setBudget] = useState<string>(s.budget.budget_usd === null ? "" : String(s.budget.budget_usd));
  const saveBudget = useMutation({
    mutationFn: () => api.put(`/projects/${pid}/budget`, { budget_usd: budget === "" ? null : Number(budget) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["state", pid] }),
  });
  const ready = new Set((boot.data?.providers ?? []).filter((p) => p.status === "valid").map((p) => p.provider));
  const missing = [...new Set(s.agents.filter((a) => !a.provider || !ready.has(a.provider)).map((a) => a.provider ?? "none"))];
  const gate = useMemo(() => {
    if (missing.length) return `Connect ${missing.join(", ")} in Settings (or change those agents' models) before starting.`;
    if (!s.agents.some((a) => a.is_orchestrator)) return "Hire a Project Manager first.";
    if (budget !== String(s.budget.budget_usd ?? "")) return "Save the budget change first.";
    return null;
  }, [missing, s, budget]);
  const reqs = s.requirements.filter((r) => r.status === "active");
  const assumptions = d.brief.assumptions;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Requirements" actions={<Button variant="ghost" onClick={() => onBack(1)}>Edit brief</Button>}>
          <ul className="max-h-60 space-y-1 overflow-y-auto text-sm">{reqs.map((r) => <li key={r.id}><span className="font-mono text-xs text-muted">{r.ref}</span> {r.text}</li>)}</ul>
          {assumptions.length > 0 && <p className="mt-2 text-xs text-muted">Includes {assumptions.length} assumption(s) you accepted.</p>}
        </Card>
        <Card title="Team & models" actions={<Button variant="ghost" onClick={() => onBack(2)}>Edit team</Button>}>
          <ul className="space-y-1.5 text-sm">{s.agents.map((a) => (
            <li key={a.id} className="flex items-center gap-2"><AvatarIcon avatar={a.avatar} size={1} />
              <span className="min-w-0"><span className="font-medium">{a.display_name}</span> <span className="text-muted">{a.role}</span>
                <span className="block text-xs text-muted">{a.provider}/{a.model_id}{a.provider && !ready.has(a.provider) && <span className="text-warn"> — not connected</span>}</span></span>
            </li>))}</ul>
        </Card>
        <Card title="Budget & estimate">
          <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); saveBudget.mutate(); }}>
            <Field label="Project budget (USD)" hint="Checked before every model call. Blank = no budget.">
              <input inputMode="decimal" className={inputCls} value={budget} onChange={(e) => setBudget(e.target.value)} />
            </Field>
            <Button disabled={saveBudget.isPending}>Save</Button>
          </form>
          <p className="mt-2 text-xs text-muted">Spent so far (setup): {money(s.estimated_spend_usd)}</p>
          <div className="mt-2 text-sm">
            {!sow ? <p className="text-muted">The estimate appears with the plan.</p> : est.data?.available ? (
              <p>Estimated cost: <span className="font-medium">≈ {money(est.data.total_usd)}</span>
                <span className="block text-xs text-muted">{est.data.basis}</span></p>
            ) : (
              <p className="text-muted">No reliable estimate yet{est.data?.missing_models?.length ? `: no cost history for ${est.data.missing_models.join(", ")}` : ""}.
                The budget above is still enforced.</p>
            )}
          </div>
        </Card>
      </div>
      <Card title="Work plan, deliverables, dependencies, assumptions and permissions">
        {run.status === "planning" && <p role="status" className="text-sm text-muted">{s.agents.find((a) => a.is_orchestrator)?.display_name ?? "The PM"} is drafting the work plan…</p>}
        {run.status === "awaiting_approval" && sow && (
          <SowEditor a={sow} agents={s.agents} gate={gate} approveLabel="Approve & Start Project" onApproved={onStarted} />
        )}
        {run.status === "awaiting_approval" && !sow && <p className="text-sm text-muted">Loading the plan…</p>}
      </Card>
    </div>
  );
}
