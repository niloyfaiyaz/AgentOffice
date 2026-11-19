import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { ProjectSwitcher } from "../App";
import { api, type AgentEvent } from "../api";
import { useProjectStream } from "../hooks";
import { Badge, Card, Empty, inputCls } from "../ui";

const GROUPS: Record<string, string[]> = {
  "All": [],
  "Tasks": ["task_assigned", "task_started", "task_resumed", "task_completed", "task_failed", "task_retry", "task_waiting", "task_paused", "task_cancelled", "task_skipped"],
  "Handoffs": ["handoff", "handoff_returned", "rework_requested", "review_requested"],
  "Decisions": ["approval_requested", "decision_recorded", "plan_proposed", "plan_approved"],
  "Tools": ["tool_call", "tool_action", "tool_denied", "artifact_written"],
  "Models & cost": ["model_call", "provider_error", "budget_warning", "budget_blocked", "model_changed", "model_switched"],
};

export function ActivityPage({ pid }: { pid: string }) {
  const { state, live } = useProjectStream(pid);
  const hist = useQuery({ queryKey: ["events", pid], queryFn: () => api.get<AgentEvent[]>(`/projects/${pid}/events?limit=1000`) });
  const handoffs = useQuery({ queryKey: ["handoffs", pid], queryFn: () => api.get<any[]>(`/projects/${pid}/handoffs`) });
  const [group, setGroup] = useState("All");
  const [agent, setAgent] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const agents = state.data?.agents ?? [];
  const name = (id: string | null) => agents.find((a) => a.id === id)?.display_name ?? "";
  const all = useMemo(() => {
    const m = new Map<number, AgentEvent>();
    for (const e of [...(hist.data ?? []), ...live]) m.set(e.seq, e);
    return [...m.values()].sort((a, b) => b.seq - a.seq);
  }, [hist.data, live]);
  const shown = all.filter((e) => (!GROUPS[group].length || GROUPS[group].includes(e.type)) && (!agent || e.agent_id === agent));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-semibold">Activity</h1><ProjectSwitcher pid={pid} base="/activity" /></div>
      <p className="text-sm text-muted">The complete, non-animated record of what the team did. Every office animation is derived from these events.</p>
      <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
        <Card title={`Events (${shown.length})`} actions={
          <>
            <select aria-label="Filter by type" className={`${inputCls} w-auto`} value={group} onChange={(e) => setGroup(e.target.value)}>{Object.keys(GROUPS).map((g) => <option key={g}>{g}</option>)}</select>
            <select aria-label="Filter by agent" className={`${inputCls} w-auto`} value={agent} onChange={(e) => setAgent(e.target.value)}>
              <option value="">All agents</option>{agents.map((a) => <option key={a.id} value={a.id}>{a.display_name}</option>)}</select>
          </>}>
          {!shown.length ? <Empty>No events.</Empty> : (
            <ol className="divide-y divide-line text-sm">
              {shown.map((e) => (
                <li key={e.seq} className="py-1.5">
                  <button className="flex w-full flex-wrap items-baseline gap-2 text-left" onClick={() => setExpanded(expanded === e.seq ? null : e.seq)} aria-expanded={expanded === e.seq}>
                    <time className="shrink-0 text-xs text-muted sm:w-36">{new Date(e.created_at).toLocaleString()}</time>
                    <Badge>{e.type}</Badge>{e.agent_id && <span className="text-xs font-medium">{name(e.agent_id)}</span>}
                    <span className="min-w-0 flex-1 break-words">{e.message}</span>
                  </button>
                  {expanded === e.seq && <pre className="mt-1 overflow-x-auto rounded bg-panel2 p-2 text-xs">{JSON.stringify(e.data, null, 2)}</pre>}
                </li>
              ))}
            </ol>
          )}
        </Card>
        <Card title="Handoffs">
          {!handoffs.data?.length ? <p className="text-sm text-muted">No handoffs yet.</p> : (
            <ul className="space-y-2 text-sm">{handoffs.data.map((h) => (
              <li key={h.id} className="rounded-md border border-line p-2"><div className="text-xs"><Badge>{h.kind}</Badge> {name(h.from_agent_id)} → {name(h.to_agent_id)} <span className="text-muted">({h.status})</span></div>
                <div className="mt-1">{h.summary}</div></li>
            ))}</ul>
          )}
        </Card>
      </div>
    </div>
  );
}
