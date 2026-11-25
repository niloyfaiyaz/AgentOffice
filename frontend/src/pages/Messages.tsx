import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Approval, type Msg, type ProjectState, type Thread } from "../api";
import { ApprovalCard } from "../components/ApprovalCard";
import { Composer } from "../components/Composer";
import { AvatarIcon, Badge, Button, Card, Empty, ErrorText, StatusBadge, fmtTime, inputCls } from "../ui";

const EXPLICIT = [
  { id: "auto", label: "Let the team work out what it is" },
  { id: "question", label: "Question" },
  { id: "requirement_change", label: "Requirement change" },
  { id: "scope_change", label: "Scope change" },
  { id: "task_feedback", label: "Feedback on a task" },
  { id: "cancel", label: "Cancel the run" },
];

/** Project-scoped workplace messaging. One record per message and per decision: decision cards
 * shown here are the same approval records listed in the Inbox and the Overview. */
export function MessagesPage({ pid, s, thread }: { pid: string; s: ProjectState; thread: string }) {
  const nav = useNavigate();
  const threads = useQuery({ queryKey: ["threads", pid], queryFn: () => api.get<Thread[]>(`/projects/${pid}/threads`) });
  const current = threads.data?.find((t) => t.id === thread) ?? threads.data?.[0];
  return (
    <div className="grid gap-4 md:grid-cols-[16rem_minmax(0,1fr)]">
      <nav aria-label="Conversations" className="space-y-1">
        {threads.data?.map((t) => {
          const a = s.agents.find((x) => x.id === t.agent_id);
          const pm = s.agents.find((x) => x.is_orchestrator);
          return (
            <button key={t.id} onClick={() => nav(`/p/${pid}/messages/${t.id}`)} aria-current={current?.id === t.id ? "page" : undefined}
              className={`flex w-full items-center gap-2 rounded-md border p-2 text-left text-sm ${current?.id === t.id ? "border-accent bg-accent/10" : "border-line hover:bg-panel2"}`}>
              {(a ?? (t.kind === "team" ? pm : undefined)) && <AvatarIcon avatar={(a ?? pm)!.avatar} size={1} />}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{t.kind === "team" ? `Project team${pm ? ` (${pm.display_name}, PM)` : ""}` : t.title}</span>
                <span className="block truncate text-xs text-muted">{t.role ?? (t.kind === "discovery" ? "How the brief was agreed" : "Default contact for project questions")}</span>
              </span>
              {t.pending > 0 && <Badge tone="warn" title="Needs your input">{t.pending}</Badge>}
            </button>
          );
        })}
      </nav>
      {current ? <ThreadView key={current.id} pid={pid} s={s} t={current} /> : <Empty>Loading conversations…</Empty>}
    </div>
  );
}

function ThreadView({ pid, s, t }: { pid: string; s: ProjectState; t: Thread }) {
  const qc = useQueryClient();
  const [intent, setIntent] = useState("auto");
  const [taskId, setTaskId] = useState("");
  const params = t.kind === "team" ? "channel=client" : t.kind === "agent" ? `channel=direct&agent_id=${t.agent_id}` : "channel=discovery";
  const msgs = useQuery({ queryKey: ["messages", pid, t.id], queryFn: () => api.get<Msg[]>(`/projects/${pid}/messages?${params}`) });
  const history = useQuery({ queryKey: ["approvals", pid, "all"], queryFn: () => api.get<Approval[]>(`/projects/${pid}/approvals`) });
  const pm = s.agents.find((a) => a.is_orchestrator);
  const agent = t.kind === "agent" ? s.agents.find((a) => a.id === t.agent_id) : pm;
  const mine = (ap: Approval) => (t.kind === "agent" ? ap.agent_id === t.agent_id
    : t.kind === "team" ? !(ap.kind === "clarification" && ap.agent_id && ap.agent_id !== pm?.id) : false);
  const open = s.pending_approvals.filter(mine);
  const decided = (history.data ?? []).filter((a) => a.status !== "pending" && mine(a));
  const send = useMutation({
    mutationFn: (b: { content: string; intent?: string }) => api.post<{ reply: string; intent: string; data: any }>(`/projects/${pid}/messages`, {
      content: b.content, intent: b.intent ?? intent, task_id: (b.intent ?? intent) === "task_feedback" ? taskId || null : null,
      agent_id: t.kind === "agent" ? t.agent_id : null,
    }),
    onSuccess: () => { setIntent("auto"); for (const k of ["messages", "threads", "state", "approvals", "inbox"]) qc.invalidateQueries({ queryKey: [k] }); },
  });
  const end = useRef<HTMLLIElement>(null);
  useEffect(() => { end.current?.scrollIntoView?.({ block: "nearest" }); }, [msgs.data?.length]);
  const list = msgs.data ?? [];
  const who = (m: Msg) => m.sender === "user" ? "You" : m.sender === "system" ? "AgentOffice" : s.agents.find((a) => a.id === m.agent_id)?.display_name ?? "Agent";
  const focus = t.kind === "agent" ? s.tasks.find((x) => x.assigned_agent_id === t.agent_id && !["completed", "failed", "cancelled", "skipped"].includes(x.status)) : undefined;
  return (
    <Card title={t.kind === "team" ? "Project team" : t.kind === "discovery" ? "Project discovery" : `${t.title} — ${t.role ?? ""}`}>
      {t.kind === "agent" && agent && (
        <p className="mb-2 text-xs text-muted">{focus ? <>Working on: “{focus.title}” <StatusBadge status={focus.status} /> — instructions you send here are recorded on that task.</> : "No open task right now."}</p>
      )}
      {t.kind === "team" && <p className="mb-2 text-xs text-muted">{pm?.display_name ?? "The project manager"} answers project questions here. Requirement changes, scope
        changes and approvals are suggested back to you for confirmation, never applied from a chat message.</p>}
      <ol className="max-h-[50vh] space-y-2 overflow-y-auto pr-1 text-sm" aria-label="Messages" aria-live="polite">
        {list.length === 0 && <li className="text-muted">No messages yet. {t.kind === "discovery" ? "" : `Ask ${agent?.display_name ?? "the team"} anything about the work.`}</li>}
        {list.map((m, i) => (
          <li key={m.id} className={`rounded-lg p-2.5 ${m.sender === "user" ? "ml-8 bg-accent/10" : m.sender === "system" ? "border border-warn/40 bg-warn/10" : "mr-6 bg-panel2"}`}>
            <div className="mb-0.5 flex flex-wrap items-center gap-2 text-xs text-muted">
              {who(m)} · {fmtTime(m.created_at)}
              {m.intent && !["auto", "question", "discovery", "general"].includes(m.intent) && <Badge tone="info">{m.intent.replace("_", " ")}</Badge>}
              {m.data?.classified_by && <span>classified by {m.data.classified_by}</span>}
            </div>
            <div className="whitespace-pre-wrap">{m.content}</div>
            {m.data?.recorded_on_task && <p className="mt-1 text-xs text-muted">Recorded on task “{m.data.recorded_on_task.title}”.</p>}
            {m.data?.suggestion && <Suggestion pid={pid} s={m.data.suggestion} original={[...list.slice(0, i)].reverse().find((x) => x.sender === "user")?.content ?? ""}
              onConfirm={(intent, content) => send.mutate({ content, intent })} busy={send.isPending} />}
          </li>
        ))}
        <li ref={end} aria-hidden />
      </ol>
      {open.length > 0 && (
        <section className="mt-3 space-y-2" aria-label="Decisions in this conversation">
          <h3 className="text-sm font-medium text-warn">Needs your decision ({open.length})</h3>
          {open.map((a) => <ApprovalCard key={a.id} a={a} agents={s.agents} compact />)}
          {open.some((a) => a.kind === "clarification") && <p className="text-xs text-muted">Tip: you can also just type your answer below.</p>}
        </section>
      )}
      {t.kind !== "discovery" && (
        <div className="mt-3 space-y-2">
          <Composer onSend={(c) => send.mutate({ content: c })} busy={send.isPending} label={`Message ${agent?.display_name ?? "the team"}`}
            placeholder={open.some((a) => a.kind === "clarification") ? "Type your answer…" : `Message ${agent?.display_name ?? "the team"}…`} />
          <details className="text-xs">
            <summary className="cursor-pointer text-muted">Message type: {EXPLICIT.find((x) => x.id === intent)?.label}</summary>
            <div className="mt-2 flex flex-wrap gap-2">
              <select aria-label="Message type" className={`${inputCls} w-auto`} value={intent} onChange={(e) => setIntent(e.target.value)}>
                {EXPLICIT.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
              </select>
              {intent === "task_feedback" && (
                <select aria-label="Task" className={`${inputCls} w-auto`} value={taskId} onChange={(e) => setTaskId(e.target.value)}>
                  <option value="">Choose task…</option>
                  {s.tasks.map((x) => <option key={x.id} value={x.id}>{x.title}</option>)}
                </select>
              )}
            </div>
          </details>
          <ErrorText error={send.error} />
        </div>
      )}
      {decided.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted">Decision history ({decided.length})</summary>
          <ul className="mt-1 space-y-1 text-xs">{decided.map((a) => (
            <li key={a.id}><StatusBadge status={a.status} /> {a.title} <span className="text-muted">{fmtTime(a.resolved_at)}</span></li>))}</ul>
        </details>
      )}
    </Card>
  );
}

function Suggestion({ pid, s, original, onConfirm, busy }: { pid: string; s: { intent: string; text: string }; original: string; busy: boolean;
  onConfirm: (intent: string, content: string) => void }) {
  const [done, setDone] = useState<"" | "sent" | "dismissed">("");
  if (done) return <p className="mt-1 text-xs text-muted">{done === "sent" ? "Sent through the structured flow — see the decision card." : "Kept as a message only."}</p>;
  return (
    <div className="mt-2 rounded-md border border-info/50 bg-info/10 p-2 text-xs" role="group" aria-label="Suggested action">
      <p>{s.text}</p>
      <div className="mt-1.5 flex flex-wrap gap-2">
        {s.intent === "approval" ? <Link to={`/p/${pid}`} className="text-accent underline">Open the pending decisions</Link> : (
          <Button disabled={busy || !original} onClick={() => { onConfirm(s.intent, original); setDone("sent"); }}>
            {s.intent === "requirement_change" ? "Record as a change request" : s.intent === "scope_change" ? "Send as a scope change" : "Cancel the run"}
          </Button>
        )}
        <Button variant="ghost" onClick={() => setDone("dismissed")}>No, it was just a message</Button>
      </div>
    </div>
  );
}
