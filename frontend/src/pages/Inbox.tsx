import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, type AgentEvent, type InboxItem } from "../api";
import { Badge, Button, Card, Empty, fmtTime } from "../ui";

export interface InboxData { actions: InboxItem[]; notices: (AgentEvent & { project_name: string })[] }

export function useInbox() {
  return useQuery({ queryKey: ["inbox"], queryFn: () => api.get<InboxData>("/inbox"), refetchInterval: 15_000 });
}

/** Where an inbox item is handled. Every item points at its one underlying record. */
export function itemHref(i: InboxItem): string {
  const p = `/p/${i.project_id}`;
  switch (i.kind) {
    case "brief": return `/new/${i.project_id}`;
    case "clarification": return `${p}/messages/${i.agent_id ? `agent:${i.agent_id}` : "team"}`;
    case "sow": case "run_failed": case "requirement_change": case "scope_change": case "stale_artifacts": return `${p}/plan`;
    case "deliverable_acceptance": return p;
    default: return p;
  }
}

const SEEN_KEY = "ao.inboxSeenSeq";
function seenSeq(): number {
  try { return Number(localStorage.getItem(SEEN_KEY) ?? 0); } catch { return 0; }
}

/** Global inbox: things that need you (questions, approvals, budget, failures, acceptance) apart
 * from informational updates. Routine agent activity stays in each project's timeline. */
export function InboxPage() {
  const q = useInbox();
  const [seen, setSeen] = useState(seenSeq());
  const markRead = () => {
    const top = Math.max(0, ...(q.data?.notices ?? []).map((n) => n.seq));
    try { localStorage.setItem(SEEN_KEY, String(top)); } catch { /* per-browser convenience only */ }
    setSeen(top);
  };
  const actions = q.data?.actions ?? [];
  const byProject = actions.reduce<Record<string, InboxItem[]>>((m, a) => ({ ...m, [a.project_name]: [...(m[a.project_name] ?? []), a] }), {});
  return (
    <div className="mx-auto max-w-4xl space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Inbox</h1>
        <p className="text-sm text-muted">Decisions and questions across all your projects. Each item opens the place where you handle it.</p>
      </div>
      <Card title={`Needs your action (${actions.length})`}>
        {!q.data ? <p className="text-sm text-muted">Loading…</p> : actions.length === 0 ? <Empty>You're all caught up. Nothing needs you right now.</Empty> : (
          <div className="space-y-4">
            {Object.entries(byProject).map(([name, items]) => (
              <section key={name} aria-label={name}>
                <h2 className="mb-1 text-sm font-semibold">{name}</h2>
                <ul className="divide-y divide-line rounded-md border border-line">
                  {items.map((i) => (
                    <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 p-2.5 text-sm">
                      <div className="min-w-0">
                        <Badge tone={i.category === "Failure" ? "bad" : "warn"}>{i.category}</Badge>{" "}
                        <span className="font-medium">{i.title}</span>
                        <span className="block text-xs text-muted">{i.agent_name ? `${i.agent_name} · ` : ""}{fmtTime(i.created_at)}</span>
                      </div>
                      <Link to={itemHref(i)} className="rounded-md border border-line px-3 py-1 text-xs hover:bg-panel2">Open</Link>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </Card>
      <Card title="Updates" actions={<Button variant="ghost" onClick={markRead}>Mark all as read</Button>}>
        {!q.data?.notices.length ? <p className="text-sm text-muted">No updates yet.</p> : (
          <ol className="space-y-1 text-sm" aria-label="Informational updates">
            {q.data.notices.map((n) => (
              <li key={n.seq} className="flex flex-wrap gap-x-3">
                <span aria-label={n.seq > seen ? "unread" : "read"} className={n.seq > seen ? "text-accent" : "text-transparent"}>●</span>
                <time className="w-40 shrink-0 text-xs text-muted">{fmtTime(n.created_at)}</time>
                <Link to={`/p/${n.project_id}`} className="text-muted hover:underline">{n.project_name}</Link>
                <span className="min-w-0">{n.message}</span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
