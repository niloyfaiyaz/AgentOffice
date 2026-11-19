import { describe, expect, it } from "vitest";
import type { Agent, AgentEvent } from "../api";
import {
  DESKS, MEETING_SEATS, RECEPTION_SPOTS, REVIEW_SEATS, TILE, displayed, initialState, reduce, route, step, visualFor,
} from "./model";

const agent = (id: string, desk: number, status: Agent["status"] = "idle"): Agent => ({
  id, project_id: "p", agent_definition_id: null, display_name: id, role: "r", role_key: "r", description: "",
  instructions: "", avatar: {}, provider: "x", model_id: "m", effort: "medium", max_output_tokens: 1, max_calls_per_task: 1,
  spend_limit_usd: null, is_orchestrator: false, desk_index: desk, status, current_task_id: null, tools: [], cost_tier: "$",
});
const ev = (seq: number, agent_id: string, agent_status: Agent["status"] | null, type = "x", data = {}): AgentEvent => ({
  seq, id: `e${seq}`, project_id: "p", run_id: "r", agent_id, task_id: null, type, message: type, data, agent_status,
  created_at: "",
});
const seat = (p: { x: number; y: number }) => ({ x: p.x * TILE + TILE / 2, y: p.y * TILE + TILE / 2 });
const settle = (s: ReturnType<typeof initialState>) => {
  for (let i = 0; i < 400; i++) s = step(s, 100);
  return s;
};

describe("event -> animation mapping", () => {
  it("maps every recorded status to a zone and animation", () => {
    expect(visualFor("working")).toMatchObject({ zone: "desk", anim: "type" });
    expect(visualFor("communicating").zone).toBe("meeting");
    expect(visualFor("reviewing").zone).toBe("review");
    expect(visualFor("waiting_for_client").zone).toBe("reception");
    expect(visualFor("failed").icon).toBe("✗");
    expect(visualFor("idle")).toMatchObject({ zone: "desk", anim: "sit", icon: null });
  });

  it("places agents at their own desks from a snapshot", () => {
    const s = reduce(initialState(), { type: "snapshot", agents: [agent("a", 0), agent("b", 3)], seq: 5 });
    expect(s.characters.a.pos).toEqual(seat({ x: DESKS[0].x, y: DESKS[0].y + 1 }));
    expect(s.characters.b.pos).toEqual(seat({ x: DESKS[3].x, y: DESKS[3].y + 1 }));
    expect(s.characters.a.path).toEqual([]);
  });

  it("walks to the review area only after a recorded reviewing event", () => {
    let s = reduce(initialState(), { type: "snapshot", agents: [agent("q", 1)], seq: 1 });
    s = reduce(s, { type: "event", event: ev(2, "q", "reviewing") });
    expect(s.characters.q.status).toBe("reviewing");
    expect(displayed(s.characters.q).anim).toBe("walk");
    s = settle(s);
    expect(s.characters.q.pos).toEqual(seat(REVIEW_SEATS[0]));
    expect(displayed(s.characters.q)).toMatchObject({ anim: "read", label: "Reviewing" });
  });

  it("ignores events without an agent status and never invents movement", () => {
    let s = reduce(initialState(), { type: "snapshot", agents: [agent("a", 0)], seq: 1 });
    const before = s.characters.a;
    s = reduce(s, { type: "event", event: ev(2, "a", null, "model_call") });
    expect(s.characters.a).toEqual(before);
    expect(settle(s).characters.a.pos).toEqual(before.pos);
  });

  it("deduplicates replayed events after reconnect", () => {
    let s = reduce(initialState(), { type: "snapshot", agents: [agent("a", 0)], seq: 10 });
    s = reduce(s, { type: "event", event: ev(9, "a", "failed") });
    expect(s.characters.a.status).toBe("idle");
  });

  it("assigns distinct meeting and reception seats", () => {
    let s = reduce(initialState(), { type: "snapshot", agents: [agent("a", 0), agent("b", 1), agent("c", 2)], seq: 1 });
    s = reduce(s, { type: "event", event: ev(2, "a", "communicating") });
    s = reduce(s, { type: "event", event: ev(3, "b", "communicating") });
    s = reduce(s, { type: "event", event: ev(4, "c", "waiting_for_client") });
    s = settle(s);
    expect(s.characters.a.pos).toEqual(seat(MEETING_SEATS[0]));
    expect(s.characters.b.pos).toEqual(seat(MEETING_SEATS[1]));
    expect(s.characters.c.pos).toEqual(seat(RECEPTION_SPOTS[0]));
  });

  it("shows a handoff effect only for a recorded handoff event", () => {
    let s = reduce(initialState(), { type: "snapshot", agents: [agent("a", 0), agent("b", 1)], seq: 1 });
    s = reduce(s, { type: "event", event: ev(2, "a", "communicating", "handoff", { to_agent_id: "b" }) });
    expect(s.effects).toHaveLength(1);
    expect(s.effects[0]).toMatchObject({ from: "a", to: "b" });
    s = step(s, 5000);
    expect(s.effects).toHaveLength(0);
  });

  it("teleports instead of walking with reduced motion", () => {
    let s = reduce(initialState(), { type: "snapshot", agents: [agent("q", 1)], seq: 1 }, { reducedMotion: true });
    s = reduce(s, { type: "event", event: ev(2, "q", "reviewing", "handoff", { to_agent_id: "q" }) }, { reducedMotion: true });
    expect(s.characters.q.path).toEqual([]);
    expect(s.characters.q.pos).toEqual(seat(REVIEW_SEATS[0]));
    expect(s.effects).toHaveLength(0);
  });

  it("routes through the corridor", () => {
    const r = route({ x: 10, y: 10 }, { x: 100, y: 300 });
    expect(r[0].x).toBe(10);
    expect(r[r.length - 1]).toEqual({ x: 100, y: 300 });
  });
});
