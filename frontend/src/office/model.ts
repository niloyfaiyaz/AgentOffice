// Office model: a pure event -> state machine plus a frame step.
//
// Design pattern adapted (idea only, no code) from W17ant/Claude-Office src/officeReducer.ts:
// transitions are pure functions with no Phaser/React/DOM/timer access, so the whole
// lifecycle is unit-testable. The renderer (OfficeScene) only draws what this model says.
//
// Honesty rule: a character's status, location and animation come ONLY from the backend's
// recorded agent status (snapshot or event). Walking is interpolation between two recorded
// states and never implies work that did not happen.

import type { Agent, AgentEvent, AgentStatus, Avatar } from "../api";

export const TILE = 16;
export const COLS = 40;
export const ROWS = 24;
export const CORRIDOR_Y = 12;

export type Zone = "desk" | "meeting" | "review" | "reception";
export type Anim = "sit" | "type" | "talk" | "read" | "stand" | "walk";

export interface Point { x: number; y: number }

export interface Visual {
  zone: Zone;
  anim: Anim;
  icon: string | null; // small status glyph shown over the head
  label: string;
}

/** The single mapping from a recorded agent status to what the office shows. */
export function visualFor(status: AgentStatus): Visual {
  switch (status) {
    case "assigned": return { zone: "desk", anim: "sit", icon: "!", label: "Assigned a task" };
    case "working": return { zone: "desk", anim: "type", icon: null, label: "Working" };
    case "communicating": return { zone: "meeting", anim: "talk", icon: "…", label: "Handing off work" };
    case "reviewing": return { zone: "review", anim: "read", icon: "?", label: "Reviewing" };
    case "waiting_for_client": return { zone: "reception", anim: "stand", icon: "✋", label: "Waiting for you" };
    case "blocked": return { zone: "desk", anim: "sit", icon: "■", label: "Blocked" };
    case "completed": return { zone: "desk", anim: "sit", icon: "✓", label: "Completed" };
    case "failed": return { zone: "desk", anim: "sit", icon: "✗", label: "Failed" };
    case "walking": return { zone: "desk", anim: "walk", icon: null, label: "Walking" };
    default: return { zone: "desk", anim: "sit", icon: null, label: "Idle" };
  }
}

// Fixed office layout (tile coordinates). Desks occupy the upper floor in two rows.
export const DESKS: Point[] = [
  { x: 4, y: 5 }, { x: 10, y: 5 }, { x: 16, y: 5 }, { x: 22, y: 5 },
  { x: 4, y: 9 }, { x: 10, y: 9 }, { x: 16, y: 9 }, { x: 22, y: 9 },
  { x: 28, y: 5 }, { x: 28, y: 9 }, { x: 34, y: 5 }, { x: 34, y: 9 },
];
export const MEETING_TABLE: Point = { x: 18, y: 17 };
export const MEETING_SEATS: Point[] = [
  { x: 16, y: 16 }, { x: 20, y: 16 }, { x: 16, y: 19 }, { x: 20, y: 19 }, { x: 18, y: 15 }, { x: 18, y: 20 },
];
export const REVIEW_SEATS: Point[] = [{ x: 31, y: 17 }, { x: 34, y: 17 }, { x: 31, y: 20 }, { x: 34, y: 20 }];
export const RECEPTION_SPOTS: Point[] = [{ x: 6, y: 18 }, { x: 8, y: 18 }, { x: 6, y: 20 }, { x: 8, y: 20 }];
export const RECEPTION_DESK: Point = { x: 4, y: 16 };
export const STATUS_BOARD: Point = { x: 18, y: 1 };

export interface Character {
  id: string;
  name: string;
  role: string;
  avatar: Avatar;
  deskIndex: number;
  status: AgentStatus;
  pos: Point; // pixel position
  path: Point[]; // remaining pixel waypoints
  facing: "left" | "right";
  lastSeq: number;
}

export interface HandoffEffect { id: string; from: string; to: string; startedAt: number; label: string }

export interface OfficeState {
  characters: Record<string, Character>;
  effects: HandoffEffect[];
  now: number;
  lastSeq: number;
}

export type OfficeAction =
  | { type: "snapshot"; agents: Agent[]; seq: number }
  | { type: "event"; event: AgentEvent };

export const initialState = (): OfficeState => ({ characters: {}, effects: [], now: 0, lastSeq: 0 });

const px = (p: Point): Point => ({ x: p.x * TILE + TILE / 2, y: p.y * TILE + TILE / 2 });

/** Seat for a character given everyone's statuses (deterministic: ordered by desk index). */
export function targetFor(state: OfficeState, id: string): Point {
  const c = state.characters[id];
  const zone = visualFor(c.status).zone;
  if (zone === "desk") return px({ x: DESKS[c.deskIndex % DESKS.length].x, y: DESKS[c.deskIndex % DESKS.length].y + 1 });
  const peers = Object.values(state.characters)
    .filter((o) => visualFor(o.status).zone === zone)
    .sort((a, b) => a.deskIndex - b.deskIndex || a.id.localeCompare(b.id));
  const idx = Math.max(0, peers.findIndex((o) => o.id === id));
  const seats = zone === "meeting" ? MEETING_SEATS : zone === "review" ? REVIEW_SEATS : RECEPTION_SPOTS;
  return px(seats[idx % seats.length]);
}

/** Corridor-based route: leave the current row, travel along the corridor, enter the target row. */
export function route(from: Point, to: Point): Point[] {
  if (from.x === to.x && from.y === to.y) return [];
  const cy = CORRIDOR_Y * TILE + TILE / 2;
  const pts: Point[] = [];
  if (from.y !== cy) pts.push({ x: from.x, y: cy });
  if (from.x !== to.x) pts.push({ x: to.x, y: cy });
  pts.push(to);
  return pts.filter((p, i, a) => i === 0 || p.x !== a[i - 1].x || p.y !== a[i - 1].y);
}

function retarget(state: OfficeState, teleport: boolean): OfficeState {
  const chars: Record<string, Character> = {};
  for (const c of Object.values(state.characters)) {
    const target = targetFor(state, c.id);
    const end = c.path.length ? c.path[c.path.length - 1] : c.pos;
    if (teleport) chars[c.id] = { ...c, pos: target, path: [] };
    else if (end.x !== target.x || end.y !== target.y) chars[c.id] = { ...c, path: route(c.pos, target) };
    else chars[c.id] = c;
  }
  return { ...state, characters: chars };
}

export function reduce(state: OfficeState, action: OfficeAction, opts: { reducedMotion?: boolean } = {}): OfficeState {
  if (action.type === "snapshot") {
    // Authoritative reconciliation (initial load / reconnect): place everyone directly.
    const chars: Record<string, Character> = {};
    for (const a of action.agents) {
      const prev = state.characters[a.id];
      chars[a.id] = {
        id: a.id, name: a.display_name, role: a.role, avatar: a.avatar ?? {}, deskIndex: a.desk_index,
        status: a.status, pos: prev?.pos ?? { x: 0, y: 0 }, path: [], facing: prev?.facing ?? "right",
        lastSeq: action.seq,
      };
    }
    const next = { ...state, characters: chars, lastSeq: Math.max(state.lastSeq, action.seq) };
    // Newly seen characters are placed at their seat; known ones walk unless reduced motion.
    const placed = retarget(next, true);
    if (opts.reducedMotion) return placed;
    const out: Record<string, Character> = {};
    for (const c of Object.values(next.characters)) {
      out[c.id] = state.characters[c.id] ? { ...c, path: route(c.pos, targetFor(next, c.id)) } : placed.characters[c.id];
    }
    return { ...next, characters: out };
  }

  const ev = action.event;
  if (ev.seq <= state.lastSeq) return state; // already applied (replay after reconnect)
  let next: OfficeState = { ...state, lastSeq: ev.seq };
  if (ev.agent_id && ev.agent_status && next.characters[ev.agent_id]) {
    const c = next.characters[ev.agent_id];
    next = { ...next, characters: { ...next.characters, [c.id]: { ...c, status: ev.agent_status, lastSeq: ev.seq } } };
    next = retarget(next, !!opts.reducedMotion);
  }
  if (ev.type === "handoff" && ev.agent_id && ev.data?.to_agent_id && !opts.reducedMotion) {
    next = {
      ...next,
      effects: [...next.effects, { id: ev.id, from: ev.agent_id, to: String(ev.data.to_agent_id), startedAt: next.now, label: ev.message }],
    };
  }
  return next;
}

export const WALK_SPEED = 110; // pixels per second
export const EFFECT_MS = 1600;

/** Advance animation by dt milliseconds. Pure. */
export function step(state: OfficeState, dtMs: number): OfficeState {
  const now = state.now + dtMs;
  const chars: Record<string, Character> = {};
  let moved = false;
  for (const c of Object.values(state.characters)) {
    if (!c.path.length) {
      chars[c.id] = c;
      continue;
    }
    moved = true;
    let budget = (WALK_SPEED * dtMs) / 1000;
    let pos = c.pos;
    const path = [...c.path];
    let facing = c.facing;
    while (budget > 0 && path.length) {
      const t = path[0];
      const dx = t.x - pos.x;
      const dy = t.y - pos.y;
      const d = Math.hypot(dx, dy);
      if (dx !== 0) facing = dx < 0 ? "left" : "right";
      if (d <= budget) {
        pos = t;
        path.shift();
        budget -= d;
      } else {
        pos = { x: pos.x + (dx / d) * budget, y: pos.y + (dy / d) * budget };
        budget = 0;
      }
    }
    chars[c.id] = { ...c, pos, path, facing };
  }
  const effects = state.effects.filter((e) => now - e.startedAt < EFFECT_MS);
  if (!moved && effects.length === state.effects.length) return { ...state, now };
  return { ...state, characters: chars, effects, now };
}

/** What the renderer should show for a character right now. */
export function displayed(c: Character): Visual {
  const v = visualFor(c.status);
  return c.path.length ? { ...v, anim: "walk", label: `${v.label} (walking)` } : v;
}
