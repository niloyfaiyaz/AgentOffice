// Original procedural pixel art for AgentOffice (no external assets).
// Characters are 12x20 pixel maps recolored per agent from their avatar palette.

import type { Avatar } from "../api";

export const CHAR_W = 12;
export const CHAR_H = 20;

// Legend: H hair, S skin, E eye, C shirt, A accent, P pants, B shoes, . transparent
const HEAD = [
  "...HHHHHH...",
  "..HHHHHHHH..",
  "..HSSSSSSH..",
  "..SSESSESS..",
  "..SSSSSSSS..",
  "...SSSSSS...",
  "....SSSS....",
];
const TORSO_SIDES = [
  "..CCCCCCCC..",
  ".CCCCAACCCC.",
  ".CCCCCCCCCC.",
  ".SCCCCCCCCS.",
  ".S.CCCCCC.S.",
  "...CCCCCC...",
];
const TORSO_TYPING = [
  "..CCCCCCCC..",
  ".CCCCAACCCC.",
  ".CCCCCCCCCC.",
  "..CCCCCCCC..",
  ".SSCCCCCCSS.",
  "...CCCCCC...",
];
const TORSO_WAVE = [
  "S.CCCCCCCC..",
  "SCCCCAACCCC.",
  ".CCCCCCCCCC.",
  "..CCCCCCCCS.",
  "...CCCCCC.S.",
  "...CCCCCC...",
];
const LEGS_STAND = ["...PPPPPP...", "...PP..PP...", "...PP..PP...", "...PP..PP...", "...BB..BB...", "............", "............"];
const LEGS_WALK_A = ["...PPPPPP...", "..PP...PP...", "..PP....PP..", ".PP.....PP..", ".BB......BB.", "............", "............"];
const LEGS_WALK_B = ["...PPPPPP...", "...PP.PP....", "....PPP.....", "....PPP.....", "....BBB.....", "............", "............"];

export type Frame = "stand" | "walkA" | "walkB" | "type" | "wave";

export function frameRows(frame: Frame): string[] {
  const torso = frame === "type" ? TORSO_TYPING : frame === "wave" ? TORSO_WAVE : TORSO_SIDES;
  const legs = frame === "walkA" ? LEGS_WALK_A : frame === "walkB" ? LEGS_WALK_B : LEGS_STAND;
  return [...HEAD, ...torso, ...legs].slice(0, CHAR_H);
}

const DEFAULTS: Required<Avatar> = { skin: "#f1c27d", hair: "#3b2a1a", shirt: "#2f6fdf", pants: "#2b2d42", accent: "#ffd166" };

export function palette(a: Avatar): Record<string, string> {
  const p = { ...DEFAULTS, ...Object.fromEntries(Object.entries(a || {}).filter(([, v]) => !!v)) } as Required<Avatar>;
  return { H: p.hair, S: p.skin, E: "#1b1b1b", C: p.shirt, A: p.accent, P: p.pants, B: "#1f1f1f" };
}

/** Draw a frame into a 2D canvas context at (ox, oy) with integer scale. */
export function drawFrame(ctx: CanvasRenderingContext2D, frame: Frame, av: Avatar, ox = 0, oy = 0, scale = 1, flip = false) {
  const pal = palette(av);
  const rows = frameRows(frame);
  for (let y = 0; y < rows.length; y++) {
    for (let x = 0; x < CHAR_W; x++) {
      const ch = rows[y][flip ? CHAR_W - 1 - x : x];
      if (ch === "." || !pal[ch]) continue;
      ctx.fillStyle = pal[ch];
      ctx.fillRect(ox + x * scale, oy + y * scale, scale, scale);
    }
  }
}

export const FRAMES: Frame[] = ["stand", "walkA", "walkB", "type", "wave"];

/** A horizontal sprite sheet (all frames, both facings) as a canvas. */
export function sheet(av: Avatar): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = CHAR_W * FRAMES.length * 2;
  c.height = CHAR_H;
  const ctx = c.getContext("2d")!;
  FRAMES.forEach((f, i) => {
    drawFrame(ctx, f, av, i * CHAR_W, 0, 1, false);
    drawFrame(ctx, f, av, (FRAMES.length + i) * CHAR_W, 0, 1, true);
  });
  return c;
}

export const frameIndex = (f: Frame, flip: boolean) => FRAMES.indexOf(f) + (flip ? FRAMES.length : 0);
