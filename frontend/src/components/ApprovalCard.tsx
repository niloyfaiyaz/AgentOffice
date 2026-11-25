import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, money, type Agent, type Approval } from "../api";
import { useBootstrap } from "../hooks";
import { Badge, Button, ErrorText, Field, inputCls } from "../ui";

const KIND_LABEL: Record<string, string> = {
  sow: "Statement of work", clarification: "Question from the team", tool_authorization: "Tool authorization",
  budget: "Budget decision", task_failure: "Task failed", requirement_change: "Requirement change",
  scope_change: "Scope change", deliverable_acceptance: "Final acceptance", stale_artifacts: "Delivery blocked",
};

function useDecide(a: Approval) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api.post(`/approvals/${a.id}/decide`, body),
    onSuccess: () => { for (const k of ["state", "approvals", "dashboard", "artifacts"]) qc.invalidateQueries({ queryKey: [k] }); },
  });
}

/** The statement-of-work review. In project setup it is the "Approve & Start Project" step: ``gate``
 * (a reason) keeps approval disabled until credentials, team and brief are in order. */
export function SowEditor({ a, agents, gate, approveLabel = "Approve and start", onApproved }: {
  a: Approval; agents: Agent[]; gate?: string | null; approveLabel?: string; onApproved?: () => void;
}) {
  const boot = useBootstrap();
  const decide = useDecide(a);
  const plan0 = a.payload.plan ?? {};
  const [tasks, setTasks] = useState<any[]>(plan0.tasks ?? []);
  const [tools, setTools] = useState<string[]>(plan0.tool_requirements ?? []);
  const [qa, setQa] = useState<boolean>(plan0.qa_review ?? true);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [comment, setComment] = useState("");
  const hasQa = agents.some((x) => x.role_key === "qa_reviewer");
  const consequential = Object.entries(boot.data?.tool_permissions ?? {}).filter(([, v]) => v.consequential);
  const removed = (plan0.tasks ?? []).filter((t: any) => !tasks.some((x) => x.key === t.key));
  const plan = { ...plan0, tasks: tasks.map((t) => ({ ...t, depends_on: (t.depends_on ?? []).filter((d: string) => tasks.some((x) => x.key === d)) })) };
  const li = (xs: string[] | undefined) => (xs?.length ? <ul className="list-disc pl-5">{xs.map((x, i) => <li key={i}>{x}</li>)}</ul> : <span className="text-muted">—</span>);
  return (
    <div className="space-y-4 text-sm">
      <p>{plan0.summary}</p>
      <div className="grid gap-3 md:grid-cols-2">
        <div><h4 className="font-medium">Scope</h4><p className="text-muted">{plan0.scope}</p></div>
        <div><h4 className="font-medium">Deliverables</h4>{li(plan0.deliverables)}</div>
        <div><h4 className="font-medium">Acceptance criteria</h4>{li(plan0.acceptance_criteria)}</div>
        <div><h4 className="font-medium">Assumptions</h4>{li(plan0.assumptions)}</div>
        <div><h4 className="font-medium">Risks</h4>{li(plan0.risks)}</div>
        <div><h4 className="font-medium">Out of scope</h4>{li(plan0.out_of_scope)}</div>
      </div>
      <div>
        <h4 className="mb-1 font-medium">Work plan — edit assignments or remove tasks</h4>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="text-xs text-muted"><tr><th className="py-1">Task</th><th>Assigned to</th><th>Depends on / implements</th><th>Output</th><th></th></tr></thead>
            <tbody>
              {tasks.map((t, i) => (
                <tr key={t.key} className="border-t border-line align-top">
                  <td className="py-1.5 pr-2">
                    <input aria-label={`Title of ${t.key}`} className={inputCls} value={t.title} onChange={(e) => setTasks(tasks.map((x, j) => j === i ? { ...x, title: e.target.value } : x))} />
                    <p className="mt-1 text-xs text-muted">{t.objective}</p>
                  </td>
                  <td className="pr-2">
                    <select aria-label={`Assignee of ${t.key}`} className={inputCls} value={agents.find((x) => [x.display_name, x.role, x.role_key].map((s) => s.toLowerCase()).includes(String(t.assignee).toLowerCase()))?.display_name ?? t.assignee}
                      onChange={(e) => setTasks(tasks.map((x, j) => j === i ? { ...x, assignee: e.target.value } : x))}>
                      {agents.map((x) => <option key={x.id} value={x.display_name}>{x.display_name} ({x.role})</option>)}
                    </select>
                  </td>
                  <td className="pr-2 text-xs">{(t.depends_on ?? []).join(", ") || "—"}<div className="text-muted">{(t.requirement_refs ?? []).join(", ")}</div></td>
                  <td className="pr-2 text-xs">{t.expected_output_type}</td>
                  <td><Button variant="ghost" aria-label={`Remove ${t.title}`} disabled={tasks.length === 1} onClick={() => setTasks(tasks.filter((_, j) => j !== i))}>Remove</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {removed.length > 0 && <p className="mt-1 text-xs text-warn">Removed: {removed.map((t: any) => t.title).join(", ")}. Dependencies on removed tasks are dropped.</p>}
      </div>
      <fieldset className="space-y-1">
        <legend className="font-medium">Authorizations for this run</legend>
        {consequential.map(([k, v]) => (
          <label key={k} className="flex items-center gap-2">
            <input type="checkbox" checked={tools.includes(k)} onChange={(e) => setTools(e.target.checked ? [...tools, k] : tools.filter((x) => x !== k))} />
            {v.label}{(plan0.tool_requirements ?? []).includes(k) && <Badge tone="info">requested</Badge>}
          </label>
        ))}
        <p className="text-xs text-muted">Unchecked tools still require your approval each time an agent wants them.</p>
        <label className="flex items-center gap-2 pt-1">
          <input type="checkbox" checked={qa && hasQa} disabled={!hasQa} onChange={(e) => setQa(e.target.checked)} />
          Independent QA review {hasQa ? "" : "(hire a QA Reviewer to enable)"}
        </label>
      </fieldset>
      {plan0.clarification_questions?.length > 0 && (
        <div className="space-y-2">
          <h4 className="font-medium">Questions from the project manager</h4>
          {plan0.clarification_questions.map((q: string) => (
            <Field key={q} label={q}><input className={inputCls} value={answers[q] ?? ""} onChange={(e) => setAnswers({ ...answers, [q]: e.target.value })} /></Field>
          ))}
        </div>
      )}
      {plan0.budget_notes && <p className="text-xs text-muted">Budget notes: {plan0.budget_notes}</p>}
      <Field label="Feedback (required to request a revision)"><textarea className={`${inputCls} h-16`} value={comment} onChange={(e) => setComment(e.target.value)} /></Field>
      <ErrorText error={decide.error} />
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="danger" disabled={decide.isPending} onClick={() => decide.mutate({ decision: "reject", comment })}>Reject</Button>
        <Button disabled={decide.isPending || (!comment && !Object.values(answers).some(Boolean))} onClick={() => decide.mutate({ decision: "revise", comment, answers })}>Request revision</Button>
        <Button variant="primary" disabled={decide.isPending || !!gate} title={gate ?? undefined}
          onClick={() => decide.mutate({ decision: "approve", plan, approved_tools: tools, qa_review: qa && hasQa, answers, comment },
            { onSuccess: () => onApproved?.() })}>{approveLabel}</Button>
      </div>
      {gate && <p className="text-right text-xs text-warn" role="status">{gate}</p>}
    </div>
  );
}

type Estimate = { usd: string | null; calls: number; partial: boolean; basis: string };

export function estimateLabel(e: Estimate): string {
  if (e.usd === null) return e.basis === "unpriced" ? "est. cost unknown (model unpriced)" : "est. cost unknown (no usage yet)";
  return `est. ${e.partial ? "≥ " : "~"}${money(Number(e.usd))}`;
}

// G1: estimated rework cost for the tasks the client has selected, from each task's recorded usage
// re-priced at its agent's current model. Shown as an estimate, never as a quote.
export function ReworkEstimate({ tasks, selected, remaining }: { tasks: any[]; selected: string[]; remaining?: string | null }) {
  const chosen = tasks.filter((t) => selected.includes(t.id));
  const priced = chosen.filter((t) => t.estimate?.usd != null);
  const total = priced.reduce((s, t) => s + Number(t.estimate.usd), 0);
  const unknown = chosen.length - priced.length;
  const lowerBound = unknown > 0 || priced.some((t) => t.estimate.partial);
  const left = remaining == null ? null : Number(remaining);
  return (
    <div className="rounded border border-line bg-panel p-2 text-xs" aria-label="Estimated rework cost">
      <div>
        <span className="font-medium">Estimated rework cost:</span>{" "}
        {chosen.length === 0 ? "nothing selected" : <>{lowerBound ? "at least " : "about "}{money(total)} for {chosen.length} task{chosen.length === 1 ? "" : "s"}</>}
        {left !== null && chosen.length > 0 && (
          <span className={total > left ? " font-medium text-bad" : " text-muted"}>
            {" "}· {money(Math.max(left, 0))} left in the project budget{total > left ? " (the rework may need more budget)" : ""}
          </span>
        )}
      </div>
      <p className="mt-1 text-muted">
        Based on what each task used the first time, priced at its agent's current model.
        {unknown > 0 && ` ${unknown} selected task${unknown === 1 ? " has" : "s have"} no usable cost data and ${unknown === 1 ? "isn't" : "aren't"} counted.`}
        {" "}Rework often costs less because it revises existing work, but it can take more calls. Budgets are still enforced before every call.
      </p>
    </div>
  );
}

export function ApprovalCard({ a, agents, compact }: { a: Approval; agents: Agent[]; compact?: boolean }) {
  const decide = useDecide(a);
  const [text, setText] = useState("");
  const [sup, setSup] = useState<string[]>(() => (a.payload.candidates ?? []).filter((c: any) => c.proposed).map((c: any) => c.id));
  const proposedTasks = (chosen: string[]) => {
    const byCand: Record<string, string[]> = a.payload.impact_by_candidate ?? {};
    const fromCands = new Set(chosen.flatMap((c) => byCand[c] ?? []));
    return (a.payload.tasks ?? []).filter((t: any) => ["rework", "rework_after"].includes(t.action) || fromCands.has(t.id))
      .filter((t: any) => t.action !== "confirm" && (t.action !== "if_selected" || fromCands.has(t.id))).map((t: any) => t.id);
  };
  const [sel, setSel] = useState<string[]>(() => proposedTasks((a.payload.candidates ?? []).filter((c: any) => c.proposed).map((c: any) => c.id)));
  const [touched, setTouched] = useState(false);
  const toggleSup = (id: string, on: boolean) => {
    const next = on ? [...sup, id] : sup.filter((x) => x !== id);
    setSup(next);
    if (!touched) setSel(proposedTasks(next));
  };
  const [budget, setBudget] = useState({ budget_usd: "", max_model_calls_per_run: "", agent_limit_usd: "" });
  const who = agents.find((x) => x.id === a.agent_id);
  const d = (body: Record<string, unknown>) => decide.mutate(body);
  return (
    <article className="rounded-lg border border-warn/40 bg-warn/5 p-4" aria-label={`${KIND_LABEL[a.kind] ?? a.kind}: ${a.title}`}>
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone="warn">{KIND_LABEL[a.kind] ?? a.kind}</Badge>
        {who && <span className="text-xs text-muted">from {who.display_name}</span>}
        <h3 className="w-full text-sm font-semibold">{a.title}</h3>
      </header>
      {a.explanation && <p className="mb-3 whitespace-pre-wrap text-sm text-muted">{a.explanation}</p>}
      {a.kind === "sow" && (compact
        ? <Link className="text-sm text-accent underline" to={`/p/${a.project_id}/plan`}>Review the plan</Link>
        : <SowEditor a={a} agents={agents} />)}
      {a.kind === "clarification" && (
        <div className="space-y-2">
          {!!a.payload.options?.length && (
            <div className="flex flex-wrap gap-2">{a.payload.options.map((o: string) => <Button key={o} onClick={() => d({ decision: "answer", answer: o })}>{o}</Button>)}</div>
          )}
          <div className="flex gap-2">
            <input aria-label="Your answer" className={inputCls} placeholder="Type an answer…" value={text} onChange={(e) => setText(e.target.value)} />
            <Button variant="primary" disabled={!text} onClick={() => d({ decision: "answer", answer: text })}>Answer</Button>
          </div>
          <Button variant="ghost" onClick={() => d({ decision: "reject", comment: "Proceed with stated assumptions" })}>Let them proceed with assumptions</Button>
        </div>
      )}
      {a.kind === "tool_authorization" && (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => d({ decision: "approve" })}>Allow once</Button>
          <Button onClick={() => d({ decision: "approve", for_whole_run: true })}>Allow for this run</Button>
          <Button variant="danger" onClick={() => d({ decision: "reject", comment: text })}>Deny</Button>
        </div>
      )}
      {a.kind === "budget" && (
        <div className="space-y-2 text-sm">
          <p className="text-xs text-muted">Spent so far (estimate): {money(Number(a.payload.spent ?? 0))} · current budget {a.payload.current?.budget_usd ? money(Number(a.payload.current.budget_usd)) : "none"}</p>
          <div className="grid gap-2 sm:grid-cols-3">
            {a.payload.reason === "project_budget" && <Field label="New project budget (USD)"><input className={inputCls} inputMode="decimal" value={budget.budget_usd} onChange={(e) => setBudget({ ...budget, budget_usd: e.target.value })} /></Field>}
            {a.payload.reason === "max_calls" && <Field label="New max model calls"><input className={inputCls} type="number" value={budget.max_model_calls_per_run} onChange={(e) => setBudget({ ...budget, max_model_calls_per_run: e.target.value })} /></Field>}
            {a.payload.reason === "agent_limit" && <Field label="New agent limit (USD)"><input className={inputCls} inputMode="decimal" value={budget.agent_limit_usd} onChange={(e) => setBudget({ ...budget, agent_limit_usd: e.target.value })} /></Field>}
          </div>
          {a.payload.reason === "unpriced" && <p>Enter prices for this model on the <Link to={`/p/${a.project_id}/team`} className="text-accent underline">Costs page</Link>, then approve.</p>}
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => d({ decision: "approve",
              ...(budget.budget_usd && { budget_usd: Number(budget.budget_usd) }),
              ...(budget.max_model_calls_per_run && { max_model_calls_per_run: Number(budget.max_model_calls_per_run) }),
              ...(budget.agent_limit_usd && { agent_limit_usd: Number(budget.agent_limit_usd) }) })}>Approve and continue</Button>
            <Button variant="danger" onClick={() => d({ decision: "reject" })}>Stop spending</Button>
          </div>
        </div>
      )}
      {a.kind === "task_failure" && (
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => d({ decision: "approve", option: "retry" })}>Retry task</Button>
          <Button onClick={() => d({ decision: "approve", option: "skip" })}>Skip task</Button>
          <Button variant="danger" onClick={() => d({ decision: "reject", option: "cancel" })}>Cancel run</Button>
        </div>
      )}
      {a.kind === "requirement_change" && (
        <div className="space-y-3 text-sm">
          {!!a.payload.candidates?.length && (
            <fieldset className="space-y-1">
              <legend className="font-medium">Which current requirements does {a.payload.change_ref ?? "this change"} replace?</legend>
              <p className="text-xs text-muted">
                {a.payload.proposal_method === "project_manager" ? "Pre-selected by the project manager" : "Pre-selected by keyword match"}
                {a.payload.proposal_rationale ? `: ${a.payload.proposal_rationale}` : ""}. Replaced items stay in history but agents stop following them.
              </p>
              {a.payload.candidates.map((c: { id: string; ref: string; text: string }) => (
                <label key={c.id} className="flex items-start gap-2">
                  <input type="checkbox" className="mt-1" checked={sup.includes(c.id)}
                    onChange={(e) => toggleSup(c.id, e.target.checked)} />
                  <span><span className="font-mono text-xs text-muted">{c.ref}</span> {c.text}</span>
                </label>
              ))}
            </fieldset>
          )}
          {!!a.payload.tasks?.length && (
            <fieldset className="space-y-1">
              <legend className="font-medium">Which tasks should be reworked?</legend>
              <p className="text-xs text-muted">Proposed from task–requirement links and artifact lineage. Unaffected work is kept.</p>
              {(a.payload.tasks ?? []).map((t: any) => (
                <label key={t.id} className="flex items-start gap-2">
                  <input type="checkbox" className="mt-1" checked={sel.includes(t.id)}
                    onChange={(e) => { setTouched(true); setSel(e.target.checked ? [...sel, t.id] : sel.filter((x) => x !== t.id)); }} />
                  <span>Rework “{t.title}” {t.reason && <span className="text-xs text-muted">— {t.reason}</span>}{" "}
                    {(t.action === "rework_after" || (!t.action && t.status && t.status !== "completed")) &&
                      <Badge tone="info">in progress — reworked after it finishes</Badge>}
                    {t.impact === "uncertain" && <Badge tone="warn">needs your confirmation</Badge>}
                    {t.action === "if_selected" && <Badge>only if that requirement is replaced</Badge>}
                    {t.estimate && <span className="text-xs text-muted"> · {estimateLabel(t.estimate)}</span>}
                  </span>
                </label>
              ))}
            </fieldset>
          )}
          {!!a.payload.tasks?.length && <ReworkEstimate tasks={a.payload.tasks} selected={sel} remaining={a.payload.budget_remaining_usd} />}
          {!!a.payload.artifacts_at_risk?.length && (
            <div className="text-xs"><span className="font-medium">Deliverables that become stale:</span>{" "}
              {a.payload.artifacts_at_risk.map((x: any) => `${x.name} v${x.version}`).join(", ")}</div>
          )}
          {!!a.payload.preserved_tasks?.length && (
            <div className="text-xs text-muted"><span className="font-medium">Unaffected (kept):</span> {a.payload.preserved_tasks.join(", ")}</div>
          )}
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => d({ decision: "approve", task_ids: sel, supersede_ids: sup })}>Apply</Button>
            <Button onClick={() => d({ decision: "reject" })}>Keep everything as is</Button>
          </div>
        </div>
      )}
      {a.kind === "stale_artifacts" && (
        <div className="space-y-2 text-sm">
          <ul className="space-y-1">
            {(a.payload.artifacts ?? []).map((x: any) => (
              <li key={x.artifact_id}><span className="font-medium">{x.name}</span> v{x.version} <span className="text-xs text-muted">— {x.reason}</span></li>
            ))}
          </ul>
          <p className="text-xs text-muted">Stale versions are kept for audit. Rework creates targeted tasks for the agents who produced them.</p>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => d({ decision: "approve", option: "rework" })}>Rework them</Button>
            <Button onClick={() => d({ decision: "approve", option: "confirm" })}>I've checked — they're current</Button>
            <Button variant="danger" onClick={() => d({ decision: "reject", option: "cancel" })}>Cancel run</Button>
          </div>
        </div>
      )}
      {a.kind === "scope_change" && (
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => d({ decision: "approve" })}>Stop and re-plan</Button>
          <Button onClick={() => d({ decision: "reject" })}>Keep current scope</Button>
        </div>
      )}
      {a.kind === "deliverable_acceptance" && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-2 text-xs">
            <Badge tone="ok">Agent work completed</Badge>
            <Badge tone={a.payload.qa_performed ? "info" : "muted"}>{a.payload.qa_performed ? "QA review performed" : "No QA review"}</Badge>
            {!!a.payload.unresolved_findings?.length && <Badge tone="warn">{a.payload.unresolved_findings.length} unresolved finding(s)</Badge>}
            {!!a.payload.qa_notes?.length && <Badge title="Informational reviewer observations, not defects">{a.payload.qa_notes.length} QA note(s)</Badge>}
            <Badge>Awaiting your acceptance</Badge>
          </div>
          <Link className="text-sm text-accent underline" to={`/p/${a.project_id}/deliverables`}>Review deliverables</Link>
          <textarea aria-label="Revision request" className={`${inputCls} h-16`} placeholder="What should be revised? (required for a revision)" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => d({ decision: "approve" })}>Accept deliverables</Button>
            <Button disabled={!text} onClick={() => d({ decision: "revise", comment: text })}>Request revision</Button>
          </div>
        </div>
      )}
      <ErrorText error={decide.error} />
    </article>
  );
}
