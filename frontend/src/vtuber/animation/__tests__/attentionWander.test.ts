import { describe, expect, it } from "vitest";
import { AttentionDirector, WANDER_AFTER_S, type AttentionInput } from "../attention";

function input(over: Partial<AttentionInput> = {}): AttentionInput {
  return {
    speaking: false,
    replyPending: false,
    listening: false,
    emotion: "neutral",
    intensity: 0.5,
    sleepPhase: "awake",
    reachable: true,
    viewerAngle: 0.2,
    ...over,
  };
}

function lcg(seed = 7) {
  return () => (seed = (seed * 16807) % 2147483647) / 2147483647;
}

function share(director: AttentionDirector, seconds: number, inp: AttentionInput, state: string) {
  let n = 0;
  let total = 0;
  for (let t = 0; t < seconds; t += 1 / 30) {
    if (director.update(1 / 30, inp).state === state) n++;
    total++;
  }
  return n / total;
}

describe("attention left alone", () => {
  it("does not wander while someone is there", () => {
    const d = new AttentionDirector(lcg());
    expect(share(d, WANDER_AFTER_S - 1, input(), "wander")).toBe(0);
    expect(share(new AttentionDirector(lcg()), 120, input({ listening: true }), "wander")).toBe(0);
    expect(share(new AttentionDirector(lcg()), 120, input({ speaking: true }), "wander")).toBe(0);
  });

  it("after a while alone, looks around the room most of the time, with glances back", () => {
    const d = new AttentionDirector(lcg(3));
    share(d, WANDER_AFTER_S, input(), "wander");
    const wander = share(d, 120, input(), "wander");
    expect(wander).toBeGreaterThan(0.35);
    expect(wander).toBeLessThan(0.85);
  });

  it("a wandering look is at the room, not beside the viewer", () => {
    const d = new AttentionDirector(lcg(5));
    for (let t = 0; t < 200; t += 1 / 30) {
      const out = d.update(1 / 30, input());
      if (out.state === "wander") {
        expect(out.contact).toBe(0);
        expect(Math.hypot(out.offset.pitch, out.offset.yaw)).toBeGreaterThan(0.2);
        return;
      }
    }
    throw new Error("never wandered");
  });

  it("the person typing brings her eyes back at once", () => {
    const d = new AttentionDirector(lcg(11));
    let t = 0;
    for (; t < 300; t += 1 / 30) if (d.update(1 / 30, input()).state === "wander") break;
    expect(t).toBeLessThan(300);
    const back = d.update(1 / 30, input({ listening: true }));
    expect(back.state).toBe("contact");
    expect(back.contact).toBe(1);
    expect(back.shift).toBeGreaterThan(0.1); // a real gaze jump — may carry a blink
  });
});
