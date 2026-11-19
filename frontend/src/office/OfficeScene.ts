// Phaser renderer for the office. It draws exactly what the pure model (model.ts) says;
// it never decides an agent's state.
import Phaser from "phaser";
import type { OfficeState } from "./model";
import {
  COLS, CORRIDOR_Y, DESKS, MEETING_TABLE, RECEPTION_DESK, REVIEW_SEATS, ROWS, STATUS_BOARD, TILE, displayed,
} from "./model";
import { CHAR_H, CHAR_W, FRAMES, frameIndex, sheet, type Frame } from "./sprites";

export interface OfficeBridge {
  getState(): OfficeState;
  advance(dtMs: number): void;
  board(): string[];
  onSelect(id: string): void;
  selectedId(): string | null;
  busyDesks(): Set<number>; // desks whose agent is actively typing (monitor glow)
}

const C = {
  floorA: 0x3a4152, floorB: 0x353c4c, wall: 0x262b38, wallTop: 0x1d212b, window: 0x6fa8dc, wood: 0x8b5a2b,
  woodDark: 0x6b4420, monitor: 0x111522, glow: 0x7fe0ff, chair: 0x4b5563, plant: 0x3c9d5d, pot: 0x9a5b3a,
  rug: 0x51466b, table: 0x9c6b3f, board: 0xf4f1e6, boardFrame: 0x5b4a3a, counter: 0xb08968, couch: 0x6c4f8f,
};

interface CharObjs { sprite: Phaser.GameObjects.Image; name: Phaser.GameObjects.Text; icon: Phaser.GameObjects.Text; ring: Phaser.GameObjects.Graphics; key: string }

export class OfficeScene extends Phaser.Scene {
  private bridge!: OfficeBridge;
  private chars = new Map<string, CharObjs>();
  private monitors: Phaser.GameObjects.Rectangle[] = [];
  private boardText!: Phaser.GameObjects.Text;
  private fx!: Phaser.GameObjects.Graphics;
  private tick = 0;

  constructor() {
    super("office");
  }

  init(data: { bridge: OfficeBridge }) {
    this.bridge = data.bridge;
  }

  create() {
    // Render at 2x internal resolution so names and the board stay crisp when scaled to fit.
    this.cameras.main.setZoom(2).centerOn((COLS * TILE) / 2, (ROWS * TILE) / 2);
    this.drawStatic();
    this.fx = this.add.graphics().setDepth(5000);
    this.boardText = this.add
      .text(STATUS_BOARD.x * TILE - 106, STATUS_BOARD.y * TILE - 6, "", {
        fontFamily: "ui-monospace, Menlo, monospace", fontSize: "7px", color: "#2a2a2a", lineSpacing: 0,
        resolution: 4,
      })
      .setDepth(20);
  }

  private drawStatic() {
    const g = this.add.graphics();
    for (let y = 0; y < ROWS; y++)
      for (let x = 0; x < COLS; x++) {
        g.fillStyle((x + y) % 2 ? C.floorA : C.floorB, 1).fillRect(x * TILE, y * TILE, TILE, TILE);
      }
    // back wall with windows
    g.fillStyle(C.wallTop, 1).fillRect(0, 0, COLS * TILE, TILE);
    g.fillStyle(C.wall, 1).fillRect(0, TILE, COLS * TILE, TILE * 2);
    for (let x = 2; x < COLS - 2; x += 6) {
      if (Math.abs(x + 1.5 - STATUS_BOARD.x) < 9) continue;
      g.fillStyle(C.window, 1).fillRect(x * TILE, TILE + 4, TILE * 3, TILE + 6);
      g.fillStyle(0xffffff, 0.25).fillRect(x * TILE + 3, TILE + 6, 6, TILE + 2);
    }
    // corridor rug
    g.fillStyle(C.rug, 0.55).fillRect(TILE, CORRIDOR_Y * TILE + 3, (COLS - 2) * TILE, TILE - 6);
    // status board
    g.fillStyle(C.boardFrame, 1).fillRect(STATUS_BOARD.x * TILE - 112, STATUS_BOARD.y * TILE - 10, 240, 52);
    g.fillStyle(C.board, 1).fillRect(STATUS_BOARD.x * TILE - 109, STATUS_BOARD.y * TILE - 7, 234, 46);
    // desks
    DESKS.forEach((d, i) => {
      const x = d.x * TILE - TILE, y = d.y * TILE;
      g.fillStyle(C.chair, 1).fillRect(d.x * TILE - 5, (d.y + 1) * TILE + 6, 10, 9);
      g.fillStyle(C.wood, 1).fillRect(x, y, TILE * 3, TILE);
      g.fillStyle(C.woodDark, 1).fillRect(x, y + TILE - 3, TILE * 3, 3);
      g.fillStyle(C.monitor, 1).fillRect(d.x * TILE - 7, y - 9, 14, 10);
      this.monitors[i] = this.add.rectangle(d.x * TILE, y - 4, 12, 8, C.glow, 0.15).setDepth(y + 1);
    });
    // plants
    [[1, 4], [38, 4], [1, 21], [38, 21], [26, 14]].forEach(([px, py]) => {
      g.fillStyle(C.pot, 1).fillRect(px * TILE + 3, py * TILE + 8, 10, 8);
      g.fillStyle(C.plant, 1).fillCircle(px * TILE + 8, py * TILE + 5, 7);
    });
    // meeting table
    g.fillStyle(C.table, 1).fillRoundedRect((MEETING_TABLE.x - 2) * TILE, (MEETING_TABLE.y - 1) * TILE + 4, TILE * 5, TILE * 2 + 4, 6);
    // review area: couch + small board
    g.fillStyle(C.couch, 1).fillRect((REVIEW_SEATS[0].x - 1) * TILE, (REVIEW_SEATS[0].y + 1) * TILE - 2, TILE * 6, 8);
    g.fillStyle(C.boardFrame, 1).fillRect(36 * TILE, 15 * TILE, TILE * 2, TILE * 3);
    g.fillStyle(C.board, 1).fillRect(36 * TILE + 2, 15 * TILE + 2, TILE * 2 - 4, TILE * 3 - 4);
    // reception counter
    g.fillStyle(C.counter, 1).fillRect((RECEPTION_DESK.x - 2) * TILE, RECEPTION_DESK.y * TILE, TILE * 6, TILE);
    g.fillStyle(C.woodDark, 1).fillRect((RECEPTION_DESK.x - 2) * TILE, RECEPTION_DESK.y * TILE + TILE - 3, TILE * 6, 3);
    const label = (x: number, y: number, t: string) =>
      this.add.text(x, y, t, { fontFamily: "ui-monospace, Menlo, monospace", fontSize: "7px", color: "#c9d1e3", resolution: 4 }).setAlpha(0.8);
    label((RECEPTION_DESK.x - 2) * TILE, (RECEPTION_DESK.y - 1) * TILE + 6, "CLIENT DESK");
    label((MEETING_TABLE.x - 2) * TILE, (MEETING_TABLE.y - 3) * TILE + 6, "MEETING TABLE");
    label((REVIEW_SEATS[0].x - 1) * TILE, (REVIEW_SEATS[0].y - 2) * TILE + 6, "QA REVIEW");
    g.setDepth(0);
  }

  private ensure(id: string): CharObjs {
    const st = this.bridge.getState().characters[id];
    const key = `char-${id}-${JSON.stringify(st.avatar)}`;
    let obj = this.chars.get(id);
    if (obj && obj.key === key) return obj;
    obj?.sprite.destroy();
    obj?.name.destroy();
    obj?.icon.destroy();
    obj?.ring.destroy();
    if (!this.textures.exists(key)) {
      const tex = this.textures.addCanvas(key, sheet(st.avatar))!;
      for (let i = 0; i < FRAMES.length * 2; i++) tex.add(i, 0, i * CHAR_W, 0, CHAR_W, CHAR_H);
    }
    const sprite = this.add.image(0, 0, key, 0).setOrigin(0.5, 1).setInteractive({ useHandCursor: true });
    sprite.on("pointerdown", () => this.bridge.onSelect(id));
    const name = this.add
      .text(0, 0, st.name, { fontFamily: "ui-monospace, Menlo, monospace", fontSize: "8px", color: "#ffffff",
        backgroundColor: "#00000088", padding: { x: 2, y: 1 }, resolution: 4 })
      .setOrigin(0.5, 1);
    const icon = this.add
      .text(0, 0, "", { fontFamily: "ui-monospace, Menlo, monospace", fontSize: "9px", color: "#111",
        backgroundColor: "#ffffff", padding: { x: 2, y: 0 }, resolution: 4 })
      .setOrigin(0.5, 1);
    const ring = this.add.graphics();
    obj = { sprite, name, icon, ring, key };
    this.chars.set(id, obj);
    return obj;
  }

  update(_t: number, delta: number) {
    this.bridge.advance(Math.min(delta, 100));
    this.tick += delta;
    const state = this.bridge.getState();
    const seen = new Set<string>();
    const selected = this.bridge.selectedId();
    for (const c of Object.values(state.characters)) {
      seen.add(c.id);
      const o = this.ensure(c.id);
      const v = displayed(c);
      const phase = Math.floor(this.tick / 180) % 2;
      let frame: Frame = "stand";
      if (v.anim === "walk") frame = phase ? "walkA" : "walkB";
      else if (v.anim === "type") frame = phase && this.tick % 900 < 600 ? "type" : "stand";
      else if (v.anim === "talk") frame = this.tick % 1400 < 700 ? "wave" : "stand";
      else if (v.anim === "stand" && c.status === "waiting_for_client") frame = this.tick % 2000 < 1000 ? "wave" : "stand";
      const x = Math.round(c.pos.x), y = Math.round(c.pos.y);
      o.sprite.setFrame(frameIndex(frame, c.facing === "left")).setPosition(x, y + 4).setDepth(y + 10);
      o.name.setPosition(x, y - CHAR_H + 2).setDepth(4000);
      o.icon.setText(v.icon ?? "").setVisible(!!v.icon).setPosition(x, y - CHAR_H - 9).setDepth(4001);
      o.icon.setBackgroundColor(c.status === "failed" || c.status === "blocked" ? "#ff8a80" :
        c.status === "completed" ? "#b9f6ca" : c.status === "waiting_for_client" ? "#ffe082" : "#ffffff");
      o.ring.clear();
      if (selected === c.id) o.ring.lineStyle(1, 0xffd166, 1).strokeEllipse(x, y + 4, 18, 6).setDepth(y + 9);
    }
    for (const [id, o] of this.chars) {
      if (!seen.has(id)) {
        o.sprite.destroy(); o.name.destroy(); o.icon.destroy(); o.ring.destroy();
        this.chars.delete(id);
      }
    }
    const busy = this.bridge.busyDesks();
    this.monitors.forEach((m, i) => m.setFillStyle(0x7fe0ff, busy.has(i) ? 0.55 + 0.25 * Math.sin(this.tick / 150) : 0.12));
    // handoff effects: a document travels from sender to receiver
    this.fx.clear();
    for (const e of state.effects) {
      const a = state.characters[e.from], b = state.characters[e.to];
      if (!a || !b) continue;
      const t = Math.min(1, (state.now - e.startedAt) / 1600);
      const px = a.pos.x + (b.pos.x - a.pos.x) * t, py = a.pos.y - 12 + (b.pos.y - a.pos.y) * t - Math.sin(t * Math.PI) * 18;
      this.fx.fillStyle(0xffffff, 1).fillRect(px - 3, py - 4, 7, 9);
      this.fx.lineStyle(1, 0x555555, 1).strokeRect(px - 3, py - 4, 7, 9);
    }
    this.boardText.setText(this.bridge.board().slice(0, 5).join("\n"));
  }
}

export function createOfficeGame(parent: HTMLElement, bridge: OfficeBridge): Phaser.Game {
  return new Phaser.Game({
    type: Phaser.CANVAS,
    parent,
    width: COLS * TILE * 2,
    height: ROWS * TILE * 2,
    pixelArt: true,
    backgroundColor: "#1d2433",
    scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_HORIZONTALLY },
    scene: [],
    banner: false,
    audio: { noAudio: true },
    callbacks: {
      postBoot: (game) => game.scene.add("office", OfficeScene, true, { bridge }),
    },
  });
}
