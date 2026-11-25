import { useEffect, useRef, useState } from "react";
import type Phaser from "phaser";
import { type AgentEvent, type ProjectState } from "../api";
import { AgentPanel } from "../components/AgentPanel";
import { useProjectStream, useReducedMotion } from "../hooks";
import { initialState, reduce, step, type OfficeState } from "../office/model";
import { situation } from "../office/situation";
import { AvatarIcon, Button, Card, Empty, Sheet } from "../ui";

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

const TONE: Record<string, string> = {
  waiting_client: "border-warn text-warn", failed: "border-bad text-bad", blocked: "border-bad text-bad",
  waiting_teammate: "border-info text-info", completed: "border-ok text-ok",
};

/** The project's pixel-art office. Mounted per project (keyed by id), so no character, selection or
 * effect can leak from one project into another. Every animated fact is also listed below it. */
export function OfficeView({ pid }: { pid: string }) {
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
        tagFor: (id) => {
          const st = stateRef.current;
          const a = st?.agents.find((x) => x.id === id);
          return a && st ? situation(a, st).short : "";
        },
      });
    });
    return () => {
      cancelled = true;
      game.current?.destroy(true);
      game.current = null;
    };
  }, [showCanvas, pid]);

  const agents = s?.agents ?? [];
  const sel = agents.find((a) => a.id === selected);
  const timeline = live.slice().reverse();
  return (
    <div className="space-y-3">
      {showCanvas && (
        <div className="overflow-hidden rounded-lg border border-line bg-[#1d2433]">
          <div ref={host} role="img" aria-label="Pixel-art office showing each agent's recorded status. The same information is listed below; select an agent to inspect it."
            className="mx-auto w-full max-w-[1280px] [image-rendering:pixelated]" />
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <span className={connected ? "text-ok" : "text-muted"}>{connected ? "● live" : "○ connecting"} · select an agent in the office or the list to inspect it</span>
        <div className="flex gap-2">
          <Button onClick={() => setReduced(!reduced)} aria-pressed={reduced}>{reduced ? "Motion: reduced" : "Motion: on"}</Button>
          <Button onClick={() => setShowCanvas(!showCanvas)} aria-pressed={!showCanvas}>{showCanvas ? "Hide office view" : "Show office view"}</Button>
        </div>
      </div>
      <Card title="The team right now">
        {!s ? <p className="text-sm text-muted">Loading…</p> : agents.length === 0 ? <Empty>No agents hired for this project.</Empty> : (
          <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3" aria-label="Agents">
            {agents.map((a) => {
              const st = situation(a, s);
              return (
                <li key={a.id} className="min-w-0">
                  <button onClick={() => setSelected(a.id)} aria-pressed={selected === a.id} aria-label={`${a.display_name}, ${a.role}: ${st.label}`}
                    className={`flex w-full items-center gap-3 rounded-md border p-2 text-left text-sm hover:bg-panel2 ${selected === a.id ? "border-accent" : "border-line"}`}>
                    <AvatarIcon avatar={a.avatar} size={2} />
                    <span className="min-w-0 flex-1">
                      <span className="block font-medium">{a.display_name} <span className="text-xs font-normal text-muted">{a.role}</span></span>
                      <span className="block truncate text-xs">{st.label}</span>
                    </span>
                    <span className={`shrink-0 rounded border px-1.5 text-xs ${TONE[st.kind] ?? "border-line text-muted"}`}><span aria-hidden>{st.icon}</span> {st.short || st.kind}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </Card>
      <details className="rounded-lg border border-line bg-panel p-3 text-sm">
        <summary className="cursor-pointer font-medium">Live timeline ({live.length})</summary>
        <ol className="mt-2 max-h-72 space-y-1 overflow-y-auto text-xs" aria-live="polite" aria-label="Live activity">
          {timeline.length === 0 ? <li className="text-muted">Waiting for activity…</li> : timeline.map((e) => (
            <li key={e.seq} className="flex gap-2"><time className="shrink-0 text-muted">{new Date(e.created_at).toLocaleTimeString()}</time><span>{e.message}</span></li>
          ))}
        </ol>
      </details>
      <Sheet open={!!sel && !!s} title={sel ? `${sel.display_name} details` : "Agent"} onClose={() => setSelected(null)}>
        {sel && s && <AgentPanel pid={pid} agentId={sel.id} s={s} onClose={() => setSelected(null)} />}
      </Sheet>
    </div>
  );
}
