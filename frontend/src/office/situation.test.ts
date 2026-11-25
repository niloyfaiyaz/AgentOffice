import { describe, expect, it } from "vitest";
import type { Agent, Approval, ProjectState, Task } from "../api";
import { nextAction, phaseOf } from "../pages/Workspace";
import { situation } from "./situation";

const agent = (id: string, name: string, status: Agent["status"], current: string | null = null) =>
  ({ id, display_name: name, status, current_task_id: current, is_orchestrator: id === "pm" } as Agent);
const task = (id: string, owner: string, status: string, deps: string[] = [], extra: Partial<Task> = {}) =>
  ({ id, title: `Task ${id}`, assigned_agent_id: owner, status, depends_on: deps, parent_task_id: null, kind: "work", ...extra } as Task);
const state = (agents: Agent[], tasks: Task[], extra: Partial<ProjectState> = {}) =>
  ({ project: { id: "p1" }, agents, tasks, pending_approvals: [], current_run: { status: "running" }, brief: null, ...extra } as unknown as ProjectState);

describe("agent situation (derived only from recorded state)", () => {
  it("shows an agent waiting for a teammate's unfinished dependency", () => {
    const s = state([agent("a", "Archie", "waiting_for_client", "t1"), agent("d", "Dev", "idle")],
      [task("t1", "a", "waiting_approval"), task("t2", "d", "pending", ["t1"])]);
    const dev = situation(s.agents[1], s);
    expect(dev.kind).toBe("waiting_teammate");
    expect(dev.waitingFor).toEqual(["Archie"]);
    expect(dev.label).toContain("Waiting for Archie");
    expect(situation(s.agents[0], s)).toMatchObject({ kind: "waiting_client", short: "needs you", icon: "✋" });
  });

  it("shows delegated work as waiting for the sub-task owner", () => {
    const s = state([agent("b", "Bea", "working", "t1"), agent("r", "Rhea", "working", "t2")],
      [task("t1", "b", "waiting_subtask"), task("t2", "r", "running", [], { parent_task_id: "t1" })]);
    expect(situation(s.agents[0], s)).toMatchObject({ kind: "waiting_teammate", waitingFor: ["Rhea"] });
    expect(situation(s.agents[1], s)).toMatchObject({ kind: "working" });
  });

  it("never invents activity for an agent with no open task", () => {
    const s = state([agent("q", "Quinn", "idle")], []);
    expect(situation(s.agents[0], s)).toMatchObject({ kind: "idle", short: "" });
  });
});

describe("workspace guidance", () => {
  it("points the client at the question that blocks the team", () => {
    const ap = { id: "x", kind: "clarification", agent_id: "a", title: "Which segment?" } as Approval;
    const s = state([agent("pm", "Pat", "idle"), agent("a", "Archie", "waiting_for_client")], [], { pending_approvals: [ap] });
    expect(nextAction(s)).toEqual({ text: "Answer Archie's question: “Which segment?”", to: "/p/p1/messages/agent:a" });
  });

  it("reports the delivery phase without gating anything", () => {
    expect(phaseOf(state([], [], { current_run: null, brief: { status: "discovering" } as any }))).toBe(0);
    expect(phaseOf(state([], [], { current_run: { status: "awaiting_approval" } as any }))).toBe(2);
    expect(phaseOf(state([], [task("t", "a", "running")]))).toBe(3);
    expect(phaseOf(state([], [task("q", "a", "running", [], { kind: "qa" })]))).toBe(4);
  });
});
