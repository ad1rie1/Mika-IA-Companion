import { describe, expect, it } from "vitest";
import {
  DESK_POSES,
  DeskChoreography,
  TYPE_ROLL,
  TYPE_YAW,
  type DeskInput,
  type DeskPlayer,
} from "../desk/DeskChoreography";

const FADE = 0.45;
const ONE_SHOTS = new Set(["pull_in", "push_out", "turn_left_45", "turn_right_45", "turn_left_90", "turn_right_90", "write_start", "write_end", "drink", "take", "stretch"]);

/** Clips of a known length, faded in over 0.45 s; the chair gestures' curves run linearly, the pen's Hold too. */
class FakePlayer implements DeskPlayer {
  now = 0;
  played: string[] = [];
  missing = new Set<string>();
  private current: string | null = null;
  private since = 0;

  has(pose: string): boolean {
    return pose in DESK_POSES && !this.missing.has(pose);
  }

  play(pose: string, restart: boolean): void {
    if (pose === this.current && !restart) return;
    this.current = pose;
    this.since = this.now;
    this.played.push(pose);
  }

  settled(pose: string): boolean {
    return pose === this.current && this.now - this.since >= FADE;
  }

  progress(pose: string): number | null {
    if (pose !== this.current) return null;
    const p = (this.now - this.since) / this.seconds(pose);
    return ONE_SHOTS.has(pose) ? Math.min(1, p) : p;
  }

  seconds(pose: string): number {
    return pose.startsWith("turn") || pose.startsWith("write_") ? 2 : pose === "pull_in" || pose === "push_out" ? 3 : 6;
  }

  curve(pose: string, name: string): number {
    const p = this.progress(pose);
    if (p === null) return 0;
    if (name === "Hold") {
      if (pose === "write") return 1;
      if (pose === "write_start") return p;
      if (pose === "write_end") return 1 - p;
      if (pose === "drink" || pose === "take") return p > 0.2 && p < 0.8 ? 0.5 : 0;
      return 0;
    }
    if ((name === "ChairYaw" || name === "ChairRoll") && ONE_SHOTS.has(pose)) return Math.min(1, p);
    return 0;
  }
}

function setup(seed = 0.5) {
  const player = new FakePlayer();
  const desk = new DeskChoreography(player, () => seed);
  const input: DeskInput = { activity: null, companion: null, leaving: false, keyboard: true, mug: true, pen: true, mouse: true };
  const run = (seconds: number, until?: () => boolean) => {
    for (let t = 0; t < seconds; t += 1 / 30) {
      player.now += 1 / 30;
      desk.update(player.now, input);
      if (until?.()) return true;
    }
    return false;
  };
  return { player, desk, input, run };
}

describe("son bureau, comme le joue Unity", () => {
  it("au travail, elle se tire au clavier par son geste : la chaise suit sa course", () => {
    const { desk, input, run, player } = setup();
    input.activity = "work";
    const yaws: number[] = [];
    const working = () => desk.pose === "type" || desk.pose === "mouse";
    expect(run(20, () => (yaws.push(desk.yaw), working()))).toBe(true);
    // d'abord posée (les mains sur les cuisses), puis le geste, puis le clavier — la souris d'abord, comme Unity
    expect(player.played.slice(0, 2)).toEqual(["lap", "pull_in"]);
    expect(["type", "mouse"]).toContain(player.played[2]);
    expect(desk.stop).toBe("type");
    expect(desk.yaw).toBeCloseTo(TYPE_YAW, 6);
    expect(desk.roll).toBeCloseTo(TYPE_ROLL, 6);
    // la chaise ne revient jamais en arrière pendant le geste
    for (let i = 1; i < yaws.length; i++) expect(yaws[i]).toBeGreaterThanOrEqual(yaws[i - 1]);
  });

  it("pour dessiner, elle pivote vers son carnet et prend son stylo", () => {
    const { desk, input, run } = setup();
    input.activity = "draw";
    expect(run(30, () => desk.pose === "write")).toBe(true);
    expect(desk.stop).toBe("write");
    expect(desk.yaw).toBeCloseTo(TYPE_YAW - 45, 6);
    expect(desk.penWriting).toBe(true);
    expect(desk.carry()).toEqual({ object: "pen", hand: "right", hold: 1 });
  });

  it("avant de se lever, le stylo reposé, la chaise ramenée à sa place par ses gestes", () => {
    const { desk, input, run, player } = setup();
    input.activity = "draw";
    run(30, () => desk.pose === "write");
    input.leaving = true;
    const before = player.played.length;
    expect(run(40, () => desk.readyToStand(player.now))).toBe(true);
    expect(player.played.slice(before)).toEqual(["write_end", "lap", "turn_right_45", "desk", "push_out", "lap"]);
    expect(desk.penWriting).toBe(false);
    expect([desk.yaw, desk.roll, desk.stop]).toEqual([0, 0, "home"]);
  });

  it("quelqu'un lui parle à sa droite : elle pivote vers lui, puis revient au travail", () => {
    const { desk, input, run, player } = setup();
    input.activity = "work";
    run(20, () => desk.pose === "type" || desk.pose === "mouse");
    input.companion = 90;
    expect(run(10, () => desk.where === "type+90")).toBe(true);
    expect(player.played).toContain("turn_right_90");
    expect(desk.yaw).toBeCloseTo(TYPE_YAW + 90, 6);
    // tournée vers lui : les mains sur les cuisses
    run(1);
    expect(desk.pose).toBe("lap");
    input.companion = null;
    expect(run(15, () => desk.where === "type" && (desk.pose === "type" || desk.pose === "mouse"))).toBe(true);
    expect(desk.yaw).toBeCloseTo(TYPE_YAW, 6);
  });

  it("une personne à peine de côté ne la fait pas pivoter : sa tête suffit", () => {
    const { desk, input, run, player } = setup();
    input.activity = "work";
    run(20, () => desk.pose === "type" || desk.pose === "mouse");
    input.companion = TYPE_YAW + 20;
    run(3);
    expect(player.played.some((p) => p.startsWith("turn"))).toBe(false);
    expect(desk.pose).toBe("desk");
  });

  it("au repos, elle boit parfois une gorgée : la tasse dans sa main gauche", () => {
    // tirage 0,5 : ni réfléchir (< 0,45), boire (< 0,62)
    const { desk, run } = setup(0.5);
    let held: ReturnType<DeskChoreography["carry"]> = null;
    expect(run(60, () => ((held = desk.carry()), held !== null && held.hold > 0))).toBe(true);
    expect(held).toMatchObject({ object: "mug", hand: "left", hold: 0.5 });
  });

  it("un geste qui manque : la chaise prend sa place d'un coup", () => {
    const { desk, input, run, player } = setup();
    player.missing.add("pull_in");
    input.activity = "work";
    expect(run(10, () => desk.stop === "type")).toBe(true);
    expect(desk.yaw).toBeCloseTo(TYPE_YAW, 6);
  });
});
