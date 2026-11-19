import { useEffect, useRef, useState } from "react";
import type Phaser from "phaser";
import { ProjectSwitcher } from "../App";
import { type AgentEvent, type ProjectState } from "../api";
import { AgentPanel } from "../components/AgentPanel";
import { ApprovalCard } from "../components/ApprovalCard";
import { useProjectStream, useReducedMotion } from "../hooks";
import { initialState, reduce, step, visualFor, type OfficeState } from "../office/model";
import { AvatarIcon, Button, Card, Empty, StatusBadge } from "../ui";

function boardLines(s: ProjectState | undefined): string[] {
  if (!s) return ["Loading…"];
  const run = s.current_run;
  const count = (st: string[]) => s.tasks.filter((t) => st.includes(t.status)).length;
  return [
    `${s.project.name.slice(0, 30)}`,
    run ? `Run ${run.run_number}: ${run.status.replace("_", " ")}` : "No run yet",
    `Tasks  done ${count(["completed", "skipped"])}/${s.tasks.length}  active ${count(["running"])}`,
    `Waiting on you: ${s.pending_approvals.length}`,
    `Est. spend $${s.estimated_spend_usd.toFixed(4)}`,
  ];
}

export function OfficePage({ pid }: { pid: string }) {
  const [reduced, setReduced] = useReducedMotion();
  const [showCanvas, setShowCanvas] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const model = useRef<OfficeState>(initialState());
  const reducedRef = useRef(reduced);
  reducedRef.current = reduced;
  const stateRef = useRef<ProjectState | undefined>(undefined);
  const selRef = useRef<string | null>(null);
  selRef.current = selected;
  const host = useRef<HTMLDivElement>(null);
  const game = useRef<Phaser.Game | null>(null);

  const onEvent = (e: AgentEvent) => {
    model.current = reduce(model.current, { type: "event", event: e }, { reducedMotion: reducedRef.current });
  };
  const { state, connected, live } = useProjectStream(pid, onEvent);
  const s = state.data;
  stateRef.current = s;

  // Reconcile with every authoritative snapshot (initial load, refetch after events, reconnect).
  useEffect(() => {
    if (s) model.current = reduce(model.current, { type: "snapshot", agents: s.agents, seq: s.last_event_seq }, { reducedMotion: reduced });
  }, [s, reduced]);

  useEffect(() => {
    if (!showCanvas || !host.current) return;
    let cancelled = false;
    import("../office/OfficeScene").then(({ createOfficeGame }) => {
      if (cancelled || !host.current) return;
      game.current = createOfficeGame(host.current, {
        getState: () => model.current,
        advance: (dt) => { model.current = step(model.current, dt); },
        board: () => boardLines(stateRef.current),
        onSelect: (id) => setSelected(id),
        selectedId: () => selRef.current,
        busyDesks: () => new Set(Object.values(model.current.characters)
          .filter((c) => c.status === "working" && !c.path.length).map((c) => c.deskIndex)),
      });
    });
    return () => {
      cancelled = true;
      game.current?.destroy(true);
      game.current = null;
    };
  }, [showCanvas, pid]);

  const agents = s?.agents ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">Virtual Office</h1>
          <ProjectSwitcher pid={pid} base="/office" />
          <span className={`text-xs ${connected ? "text-ok" : "text-muted"}`}>{connected ? "● live" : "○ connecting"}</span>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => setReduced(!reduced)} aria-pressed={reduced}>{reduced ? "Motion: reduced" : "Motion: on"}</Button>
          <Button onClick={() => setShowCanvas(!showCanvas)} aria-pressed={!showCanvas}>{showCanvas ? "Hide office view" : "Show office view"}</Button>
        </div>
      </div>

      <div className="grid gap-4 2xl:grid-cols-[1fr_400px]">
        <div className="min-w-0 space-y-4">
          {showCanvas && (
            <div className="overflow-hidden rounded-lg border border-line bg-[#1d2433]">
              <div ref={host} role="img" aria-label="Pixel-art office showing each agent's current recorded status. The same information is listed in the team panel."
                className="mx-auto w-full max-w-[1280px] [image-rendering:pixelated]" />
            </div>
          )}
          <Card title="Team (keyboard accessible)">
            {agents.length === 0 ? <Empty>No agents hired for this project.</Empty> : (
              <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {agents.map((a) => (
                  <li key={a.id} className="min-w-0">
                    <button onClick={() => setSelected(a.id)} aria-pressed={selected === a.id}
                      className={`flex w-full items-center gap-3 rounded-md border p-2 text-left text-sm ${selected === a.id ? "border-accent" : "border-line hover:bg-panel2"}`}>
                      <AvatarIcon avatar={a.avatar} size={2} />
                      <span className="min-w-0 flex-1"><span className="block font-medium">{a.display_name}</span>
                        <span className="block truncate text-xs text-muted">{visualFor(a.status).label}{a.current_task_id && s?.tasks.find((t) => t.id === a.current_task_id) ? ` — ${s.tasks.find((t) => t.id === a.current_task_id)!.title}` : ""}</span></span>
                      <StatusBadge status={a.status} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="grid gap-4 xl:grid-cols-2 2xl:grid-cols-1 2xl:content-start">
          {selected && agents.some((a) => a.id === selected) && (
            <AgentPanel pid={pid} agentId={selected} agents={agents} onClose={() => setSelected(null)} />
          )}
          {s && s.pending_approvals.length > 0 && (
            <Card title={`Needs your decision (${s.pending_approvals.length})`}>
              <div className="space-y-3">{s.pending_approvals.map((a) => <ApprovalCard key={a.id} a={a} agents={agents} compact />)}</div>
            </Card>
          )}
          <Card title="Live timeline">
            <ol className="max-h-[420px] space-y-1 overflow-y-auto text-xs" aria-live="polite" aria-label="Live activity">
              {live.length === 0 ? <li className="text-muted">Waiting for activity… (full history on the Activity page)</li> :
                [...live].reverse().map((e) => (
                  <li key={e.seq} className="flex gap-2"><time className="shrink-0 text-muted">{new Date(e.created_at).toLocaleTimeString()}</time><span>{e.message}</span></li>
                ))}
            </ol>
          </Card>
        </div>
      </div>
    </div>
  );
}
