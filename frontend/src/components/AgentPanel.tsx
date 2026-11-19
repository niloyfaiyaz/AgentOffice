import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, money, type Agent, type AgentEvent, type Approval, type Artifact, type Task } from "../api";
import { visualFor } from "../office/model";
import { AvatarIcon, Badge, Button, StatusBadge, fmtTime } from "../ui";

interface Detail {
  agent: Agent; current_task: Task | null; recent_events: AgentEvent[]; tasks: Task[]; artifacts: Artifact[];
  handoffs: { id: string; from_agent_id: string | null; to_agent_id: string | null; kind: string; summary: string; status: string; created_at: string }[];
  usage: { input_tokens: number; output_tokens: number; calls: number; estimated_spend_usd: number }; blockers: Approval[];
}
interface Exec { id: string; attempt: number; provider: string; model_id: string; status: string; model_calls: number; error: string; conversation: any[] }

export function AgentPanel({ pid, agentId, agents, onClose }: { pid: string; agentId: string; agents: Agent[]; onClose: () => void }) {
  const [advanced, setAdvanced] = useState(false);
  const q = useQuery({ queryKey: ["agentDetail", pid, agentId], queryFn: () => api.get<Detail>(`/projects/${pid}/agents/${agentId}/detail`) });
  const d = q.data;
  const taskId = d?.current_task?.id ?? d?.tasks[0]?.id;
  const ex = useQuery({ queryKey: ["executions", taskId], enabled: advanced && !!taskId, queryFn: () => api.get<Exec[]>(`/tasks/${taskId}/executions`) });
  const name = (id: string | null) => agents.find((a) => a.id === id)?.display_name ?? "?";
  if (!d) return <aside className="rounded-lg border border-line bg-panel p-4 text-sm text-muted">Loading…</aside>;
  const a = d.agent;
  const tools = d.recent_events.filter((e) => ["tool_call", "tool_action", "tool_denied"].includes(e.type));
  return (
    <aside aria-label={`${a.display_name} details`} className="space-y-3 rounded-lg border border-line bg-panel p-4 text-sm">
      <header className="flex items-start gap-3">
        <AvatarIcon avatar={a.avatar} size={4} />
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold">{a.display_name}</h2>
          <p className="text-muted">{a.role}</p>
          <p className="text-xs text-muted">{a.provider}/{a.model_id}</p>
          <div className="mt-1 flex items-center gap-2"><StatusBadge status={a.status} /><span className="text-xs text-muted">{visualFor(a.status).label}</span></div>
        </div>
        <Button variant="ghost" aria-label="Close details" onClick={onClose}>✕</Button>
      </header>
      <dl className="grid grid-cols-2 gap-2 rounded-md bg-panel2 p-2 text-xs">
        <div><dt className="text-muted">Model calls</dt><dd>{d.usage.calls}</dd></div>
        <div><dt className="text-muted">Est. spend</dt><dd>{money(d.usage.estimated_spend_usd)}{a.spend_limit_usd !== null && ` / ${money(a.spend_limit_usd)}`}</dd></div>
        <div><dt className="text-muted">Input tokens</dt><dd>{d.usage.input_tokens.toLocaleString()}</dd></div>
        <div><dt className="text-muted">Output tokens</dt><dd>{d.usage.output_tokens.toLocaleString()}</dd></div>
      </dl>
      <section>
        <h3 className="font-medium">Current task</h3>
        {d.current_task ? <p>{d.current_task.title} <StatusBadge status={d.current_task.status} /></p> : <p className="text-muted">None</p>}
      </section>
      {d.blockers.length > 0 && (
        <section><h3 className="font-medium text-warn">Waiting on you</h3><ul className="list-disc pl-4">{d.blockers.map((b) => <li key={b.id}>{b.title}</li>)}</ul></section>
      )}
      <section>
        <h3 className="font-medium">Deliverables</h3>
        {d.artifacts.length ? <ul className="list-disc pl-4">{d.artifacts.map((x) => <li key={x.id}>{x.name} <span className="text-muted">v{x.current_version}</span></li>)}</ul> : <p className="text-muted">None yet</p>}
      </section>
      <section>
        <h3 className="font-medium">Handoffs</h3>
        {d.handoffs.length ? <ul className="space-y-1">{d.handoffs.map((h) => (
          <li key={h.id} className="text-xs"><Badge>{h.kind}</Badge> {name(h.from_agent_id)} → {name(h.to_agent_id)}: {h.summary} <span className="text-muted">({h.status})</span></li>
        ))}</ul> : <p className="text-muted">None</p>}
      </section>
      <section>
        <h3 className="font-medium">Tool actions</h3>
        {tools.length ? <ul className="space-y-0.5 text-xs">{tools.slice(0, 10).map((e) => <li key={e.seq}>{e.message}</li>)}</ul> : <p className="text-muted">None</p>}
      </section>
      <section>
        <h3 className="font-medium">Recent activity</h3>
        <ol className="max-h-56 space-y-0.5 overflow-y-auto text-xs">{d.recent_events.map((e) => (
          <li key={e.seq}><time className="text-muted">{new Date(e.created_at).toLocaleTimeString()}</time> {e.message}</li>
        ))}</ol>
      </section>
      <Button variant="ghost" onClick={() => setAdvanced(!advanced)} aria-expanded={advanced}>{advanced ? "Hide" : "Show"} advanced view</Button>
      {advanced && (
        <section className="space-y-2">
          <p className="text-xs text-muted">Configuration: {a.provider}/{a.model_id} · effort {a.effort} · max {a.max_calls_per_task} calls/task · tools: {a.tools.join(", ")}</p>
          {ex.data?.map((x) => (
            <details key={x.id} className="rounded-md border border-line p-2 text-xs">
              <summary>Attempt {x.attempt} · {x.provider}/{x.model_id} · {x.status} · {x.model_calls} calls {x.error && `· ${x.error}`}</summary>
              <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap">{JSON.stringify(x.conversation, null, 1)}</pre>
            </details>
          ))}
          <details className="rounded-md border border-line p-2 text-xs"><summary>Structured events (JSON)</summary>
            <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap">{JSON.stringify(d.recent_events, null, 1)}</pre></details>
          <p className="text-xs text-muted">Last updated {fmtTime(new Date().toISOString())}</p>
        </section>
      )}
    </aside>
  );
}
