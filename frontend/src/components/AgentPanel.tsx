import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, money, type Agent, type AgentEvent, type Approval, type Artifact, type ProjectState, type Task } from "../api";
import { situation } from "../office/situation";
import { AvatarIcon, Badge, Button, StatusBadge, fmtTime } from "../ui";

interface Detail {
  agent: Agent; current_task: Task | null; focus_task: Task | null; recent_events: AgentEvent[]; tasks: Task[]; artifacts: Artifact[];
  waiting_on: { kind: "teammate" | "client"; task: string; agent: string | null; status: string }[];
  dependencies: { id: string; title: string; status: string; agent: string | null }[];
  latest_output: { artifact_id: string; name: string; version: number; summary: string; updated_at: string } | null;
  handoffs: { id: string; from_agent_id: string | null; to_agent_id: string | null; kind: string; summary: string; status: string; created_at: string }[];
  usage: { input_tokens: number; output_tokens: number; calls: number; estimated_spend_usd: number }; blockers: Approval[];
}
interface Exec { id: string; attempt: number; provider: string; model_id: string; status: string; model_calls: number; error: string; conversation: any[] }

/** Agent inspection: identity, what it is doing now, what it waits on, latest output, deliverables,
 * cost - all from recorded state. The private model reasoning is never shown; the advanced view
 * contains only the recorded conversation (prompts, tool calls and results) for inspection. */
export function AgentPanel({ pid, agentId, s, onClose }: { pid: string; agentId: string; s: ProjectState; onClose: () => void }) {
  const [advanced, setAdvanced] = useState(false);
  const q = useQuery({ queryKey: ["agentDetail", pid, agentId], queryFn: () => api.get<Detail>(`/projects/${pid}/agents/${agentId}/detail`) });
  const d = q.data;
  const taskId = d?.focus_task?.id ?? d?.tasks[0]?.id;
  const ex = useQuery({ queryKey: ["executions", taskId], enabled: advanced && !!taskId, queryFn: () => api.get<Exec[]>(`/tasks/${taskId}/executions`) });
  const agents = s.agents;
  const name = (id: string | null) => agents.find((a) => a.id === id)?.display_name ?? "?";
  const a = d?.agent ?? agents.find((x) => x.id === agentId);
  if (!a) return null;
  const sit = situation(a, s);
  const tools = d?.recent_events.filter((e) => ["tool_call", "tool_action", "tool_denied", "artifact_written", "handoff", "task_completed"].includes(e.type)) ?? [];
  return (
    <div aria-label={`${a.display_name} details`} className="space-y-4 text-sm">
      <header className="flex items-start gap-3">
        <AvatarIcon avatar={a.avatar} size={4} />
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">{a.display_name}</h2>
          <p className="text-muted">{a.role}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2"><StatusBadge status={a.status} /></div>
        </div>
        <Button variant="ghost" aria-label="Close details" onClick={onClose}>✕</Button>
      </header>

      <section aria-label="Now" className="rounded-md border border-line bg-panel2 p-3">
        <h3 className="text-xs uppercase tracking-wide text-muted">Now</h3>
        <p className="mt-0.5 font-medium"><span aria-hidden>{sit.icon} </span>{sit.label}</p>
        {d?.focus_task && <p className="mt-1 text-xs text-muted">{d.focus_task.objective}</p>}
        {!!d?.waiting_on.length && (
          <ul className="mt-2 space-y-0.5 text-xs">
            {d.waiting_on.map((w, i) => (
              <li key={i}>{w.kind === "client" ? <span className="text-warn">Waiting for you: {w.task}</span>
                : <>Waiting for <span className="font-medium">{w.agent ?? "a teammate"}</span>: “{w.task}” ({w.status.replace("_", " ")})</>}</li>
            ))}
          </ul>
        )}
        <div className="mt-2 flex flex-wrap gap-2">
          <Link to={`/p/${pid}/messages/${a.is_orchestrator ? "team" : `agent:${a.id}`}`} className="rounded-md bg-accent px-3 py-1.5 text-xs font-semibold text-accentInk">
            {a.is_orchestrator ? "Message the team" : `Message ${a.display_name}`}
          </Link>
          {!!d?.blockers.length && <Link to={`/p/${pid}/messages/${a.is_orchestrator ? "team" : `agent:${a.id}`}`} className="rounded-md border border-warn px-3 py-1.5 text-xs">Answer {d.blockers.length} question(s)</Link>}
        </div>
      </section>

      {!!d?.dependencies.length && (
        <section><h3 className="font-medium">Depends on</h3>
          <ul className="space-y-0.5 text-xs">{d.dependencies.map((x) => <li key={x.id}>{x.title} — {x.agent ?? "?"} <StatusBadge status={x.status} /></li>)}</ul>
        </section>
      )}

      <section>
        <h3 className="font-medium">Latest output</h3>
        {d?.latest_output ? (
          <p><Link className="text-accent underline" to={`/p/${pid}/deliverables?artifact=${d.latest_output.artifact_id}`}>{d.latest_output.name} v{d.latest_output.version}</Link>
            {d.latest_output.summary && <span className="block text-xs text-muted">{d.latest_output.summary}</span>}</p>
        ) : <p className="text-muted">Nothing delivered yet.</p>}
        {d && d.artifacts.length > 1 && <p className="mt-1 text-xs text-muted">Also: {d.artifacts.filter((x) => x.id !== d.latest_output?.artifact_id).map((x) => `${x.name} v${x.current_version}`).join(", ")}</p>}
      </section>

      <section>
        <h3 className="font-medium">Recent actions</h3>
        {tools.length ? <ol className="space-y-0.5 text-xs">{tools.slice(0, 8).map((e) => (
          <li key={e.seq}><time className="text-muted">{new Date(e.created_at).toLocaleTimeString()}</time> {e.message}</li>))}</ol>
          : <p className="text-muted">No recorded actions yet.</p>}
      </section>

      {!!d?.handoffs.length && (
        <section>
          <h3 className="font-medium">Hand-offs</h3>
          <ul className="space-y-1">{d.handoffs.slice(0, 6).map((h) => (
            <li key={h.id} className="text-xs"><Badge>{h.kind}</Badge> {name(h.from_agent_id)} → {name(h.to_agent_id)}: {h.summary} <span className="text-muted">({h.status})</span></li>
          ))}</ul>
        </section>
      )}

      <dl className="grid grid-cols-2 gap-2 rounded-md bg-panel2 p-2 text-xs">
        <div><dt className="text-muted">Model</dt><dd>{a.provider}/{a.model_id}</dd></div>
        <div><dt className="text-muted">Est. spend</dt><dd>{money(d?.usage.estimated_spend_usd)}{a.spend_limit_usd !== null && ` / ${money(a.spend_limit_usd)} limit`}</dd></div>
        <div><dt className="text-muted">Model calls</dt><dd>{d?.usage.calls ?? "—"}</dd></div>
        <div><dt className="text-muted">Tokens in / out</dt><dd>{d ? `${d.usage.input_tokens.toLocaleString()} / ${d.usage.output_tokens.toLocaleString()}` : "—"}</dd></div>
      </dl>

      <Button variant="ghost" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>{advanced ? "Hide" : "Show"} technical details</Button>
      {advanced && d && (
        <section className="space-y-2">
          <p className="text-xs text-muted">Configuration: effort {a.effort} · max {a.max_calls_per_task} calls/task · tools: {a.tools.join(", ")}.
            Shown: the recorded conversation (prompts, tool calls, results). Private model reasoning is not recorded or shown.</p>
          {ex.data?.map((x) => (
            <details key={x.id} className="rounded-md border border-line p-2 text-xs">
              <summary>Attempt {x.attempt} · {x.provider}/{x.model_id} · {x.status} · {x.model_calls} calls {x.error && `· ${x.error}`}</summary>
              <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap">{JSON.stringify(x.conversation, null, 1)}</pre>
            </details>
          ))}
          <details className="rounded-md border border-line p-2 text-xs"><summary>Recorded events (JSON)</summary>
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap">{JSON.stringify(d.recent_events, null, 1)}</pre></details>
          <p className="text-xs text-muted">Updated {fmtTime(new Date().toISOString())}</p>
        </section>
      )}
    </div>
  );
}
