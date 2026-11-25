// What each agent is doing, in plain language, derived ONLY from recorded state: the agent's
// event-sourced status and the task table (assignments, dependencies, sub-tasks). Nothing is
// invented to make the office look busy.
import type { Agent, ProjectState, Task } from "../api";

export type SituationKind =
  | "working" | "waiting_teammate" | "waiting_client" | "reviewing" | "handing_off" | "blocked" | "completed"
  | "failed" | "assigned" | "idle";

export interface Situation {
  kind: SituationKind;
  label: string; // full sentence for lists and screen readers
  short: string; // a few words for the office canvas
  icon: string; // a text symbol, so state never depends on colour alone
  task: Task | null;
  waitingFor: string[]; // teammate names
}

const OPEN = ["pending", "ready", "running", "paused", "waiting_approval", "waiting_subtask"];

export function focusTask(a: Agent, s: ProjectState): Task | null {
  const cur = a.current_task_id ? s.tasks.find((t) => t.id === a.current_task_id) : undefined;
  if (cur && OPEN.includes(cur.status)) return cur;
  const mine = s.tasks.filter((t) => t.assigned_agent_id === a.id && OPEN.includes(t.status));
  return mine.find((t) => t.status === "running") ?? mine[0] ?? cur ?? null;
}

export function situation(a: Agent, s: ProjectState): Situation {
  const t = focusTask(a, s);
  const name = (id: string | null) => s.agents.find((x) => x.id === id)?.display_name ?? "a teammate";
  const base = { task: t, waitingFor: [] as string[] };
  if (a.status === "waiting_for_client" || t?.status === "waiting_approval")
    return { ...base, kind: "waiting_client", icon: "✋", short: "needs you", label: `Waiting for you${t ? ` on “${t.title}”` : ""}` };
  if (a.status === "failed") return { ...base, kind: "failed", icon: "✗", short: "failed", label: `Failed${t ? `: “${t.title}”` : ""}` };
  if (a.status === "blocked") return { ...base, kind: "blocked", icon: "■", short: "blocked", label: `Blocked${t ? ` on “${t.title}”` : ""}` };
  if (t?.status === "waiting_subtask") {
    const subs = s.tasks.filter((x) => x.parent_task_id === t.id && !["completed", "skipped", "cancelled"].includes(x.status));
    const who = [...new Set(subs.map((x) => name(x.assigned_agent_id)))];
    return { ...base, waitingFor: who, kind: "waiting_teammate", icon: "⏳", short: `waiting: ${who.join(", ") || "teammate"}`,
      label: `Waiting for ${who.join(" and ") || "a teammate"} (delegated work on “${t.title}”)` };
  }
  if (t && ["pending", "ready"].includes(t.status)) {
    const open = t.depends_on.map((d) => s.tasks.find((x) => x.id === d)).filter((d): d is Task => !!d && !["completed", "skipped"].includes(d.status));
    if (open.length) {
      const who = [...new Set(open.map((d) => name(d.assigned_agent_id)))];
      return { ...base, waitingFor: who, kind: "waiting_teammate", icon: "⏳", short: `waiting: ${who.join(", ")}`,
        label: `Waiting for ${who.join(" and ")} to finish “${open[0].title}” before starting “${t.title}”` };
    }
  }
  switch (a.status) {
    case "working": return { ...base, kind: "working", icon: "⌨", short: "working", label: `Working on “${t?.title ?? "a task"}”` };
    case "reviewing": return { ...base, kind: "reviewing", icon: "?", short: "reviewing", label: `Reviewing${t ? ` “${t.title}”` : ""}` };
    case "communicating": return { ...base, kind: "handing_off", icon: "…", short: "handing off", label: "Handing off work to a teammate" };
    case "assigned": return { ...base, kind: "assigned", icon: "!", short: "assigned", label: `Assigned “${t?.title ?? "a task"}”` };
    case "completed": return { ...base, kind: "completed", icon: "✓", short: "done", label: "Completed their work" };
    default:
      return t ? { ...base, kind: "assigned", icon: "·", short: "up next", label: `Up next: “${t.title}”` }
        : { ...base, kind: "idle", icon: "·", short: "", label: "Idle — no open task" };
  }
}
