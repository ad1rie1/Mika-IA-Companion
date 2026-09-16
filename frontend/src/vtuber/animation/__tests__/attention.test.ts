import { describe, expect, it } from "vitest";
import {
  AVERSION_INTERVAL,
  AVERSION_P_IDLE,
  AVERSION_P_LISTENING,
  AVERSION_PROFILE,
  AttentionDirector,
  INNER_CONTACT,
  ONSET_AVERSION_P,
  SACCADE_INTERVAL,
  THINKING_CHECKIN_DURATION,
  THINKING_CHECKIN_INTERVAL,
  THINKING_CONTACT,
  THINKING_MAX_S,
  type AttentionInput,
} from "../attention";
import { EMOTION_NAMES } from "../../../types";

const base = (over: Partial<AttentionInput> = {}): AttentionInput => ({
  speaking: false,
  replyPending: false,
  listening: false,
  persona: "speaking",
  emotion: "neutral",
  intensity: 0.5,
  sleepPhase: "awake",
  reachable: true,
  viewerAngle: 0.3,
  ...over,
});

/** Constant random source: every sample lands at `value` of its range. */
const constant = (value: number) => () => value;

function advance(d: AttentionDirector, input: AttentionInput, seconds: number, dt = 0.05) {
  let last = d.update(0, input);
  for (let t = 0; t < seconds - 1e-9; t += dt) last = d.update(dt, input);
  return last;
}

describe("AttentionDirector — modes", () => {
  it("asleep: no contact, no offset, no saccade", () => {
    const d = new AttentionDirector(constant(0));
    const g = d.update(0.1, base({ sleepPhase: "deep_sleep" }));
    expect(g.state).toBe("asleep");
    expect(g.contact).toBe(0);
    expect(g.offset).toEqual({ pitch: 0, yaw: 0 });
    expect(g.saccade).toEqual({ pitch: 0, yaw: 0 });
  });

  it("contact by default when awake and someone is in front", () => {
    const d = new AttentionDirector(constant(0.99));
    const g = d.update(0.1, base());
    expect(g.state).toBe("contact");
    expect(g.contact).toBe(1);
    expect(g.offset).toEqual({ pitch: 0, yaw: 0 });
  });

  it("an inner murmur is not addressed to you: low contact, eyes down-side", () => {
    const d = new AttentionDirector(constant(0.99));
    const g = d.update(0.1, base({ persona: "inner", speaking: true }));
    expect(g.state).toBe("inner");
    expect(g.contact).toBe(INNER_CONTACT);
    expect(g.offset.pitch).toBeGreaterThan(0); // down
    expect(Math.abs(g.offset.yaw)).toBeGreaterThan(0);
  });

  it("an inner persona that is NOT speaking is just her: contact", () => {
    const d = new AttentionDirector(constant(0.99));
    const g = d.update(0.1, base({ persona: "inner", speaking: false }));
    expect(g.state).toBe("contact");
  });

  it("a pending reply pulls the gaze up and to the side, with check-ins", () => {
    const d = new AttentionDirector(constant(0));
    const g = d.update(0.1, base({ replyPending: true }));
    expect(g.state).toBe("thinking");
    expect(g.contact).toBe(THINKING_CONTACT);
    expect(g.offset.pitch).toBeLessThan(0); // up
    expect(Math.abs(g.offset.yaw)).toBeGreaterThan(0.1);

    // random=0 → check-in after THINKING_CHECKIN_INTERVAL[0], lasting
    // THINKING_CHECKIN_DURATION[0]: a glance back at you.
    const atCheckin = advance(d, base({ replyPending: true }), THINKING_CHECKIN_INTERVAL[0] + 0.05);
    expect(atCheckin.contact).toBe(1);
    expect(atCheckin.offset).toEqual({ pitch: 0, yaw: 0 });
    const after = advance(d, base({ replyPending: true }), THINKING_CHECKIN_DURATION[0] + 0.1);
    expect(after.contact).toBe(THINKING_CONTACT);
  });

  it("the thinking side is picked once per pending reply and held", () => {
    const d = new AttentionDirector(constant(0.7)); // → side +1
    const a = d.update(0.05, base({ replyPending: true }));
    const b = d.update(0.05, base({ replyPending: true }));
    expect(a.offset.yaw).toBe(b.offset.yaw);
    expect(a.offset.yaw).toBeGreaterThan(0);
  });

  it("speaking outranks a pending message: one finishes one's sentence first", () => {
    const d = new AttentionDirector(constant(0.99));
    const g = d.update(0.1, base({ replyPending: true, speaking: true }));
    expect(g.state).not.toBe("thinking");
    expect(g.contact).toBe(1);
  });

  it("a reply that never comes stops being thought about after THINKING_MAX_S", () => {
    const d = new AttentionDirector(constant(0.99));
    const during = advance(d, base({ replyPending: true }), 5, 0.5);
    expect(during.state).toBe("thinking");
    const late = advance(d, base({ replyPending: true }), THINKING_MAX_S + 1, 0.5);
    expect(late.state).toBe("contact");
  });

  it("the reply landing returns the gaze at once (a jump, reported as shift)", () => {
    const d = new AttentionDirector(constant(0.99));
    d.update(0.1, base({ replyPending: true }));
    const g = d.update(0.05, base({ replyPending: false }));
    expect(g.state).toBe("contact");
    expect(g.contact).toBe(1);
    expect(g.shift).toBeGreaterThan(0.1);
  });

  it("out of reach: contact 0 and state away — but a thought keeps its offset", () => {
    const d = new AttentionDirector(constant(0.99));
    const away = d.update(0.1, base({ reachable: false }));
    expect(away.state).toBe("away");
    expect(away.contact).toBe(0);
    const thinking = d.update(0.1, base({ reachable: false, replyPending: true }));
    expect(thinking.state).toBe("thinking");
    expect(thinking.contact).toBe(0);
    expect(thinking.offset.pitch).toBeLessThan(0);
  });
});

describe("AttentionDirector — aversions", () => {
  it("the start of an utterance carries a planning look-away, then contact returns", () => {
    // random 0.1 < ONSET_AVERSION_P → the aversion fires; its duration is
    // ONSET range at 10 %.
    expect(0.1).toBeLessThan(ONSET_AVERSION_P);
    const d = new AttentionDirector(constant(0.1));
    d.update(0.05, base({ speaking: false }));
    const onset = d.update(0.05, base({ speaking: true }));
    expect(onset.state).toBe("avert");
    expect(onset.offset.pitch).toBeLessThan(0); // up: planning, not shame
    expect(onset.shift).toBeGreaterThan(0.1);
    const later = advance(d, base({ speaking: true }), 1.2);
    expect(later.state).toBe("contact");
    expect(later.offset).toEqual({ pitch: 0, yaw: 0 });
  });

  it("no planning aversion when the roll fails", () => {
    const d = new AttentionDirector(constant(0.9));
    d.update(0.05, base({ speaking: false }));
    const onset = d.update(0.05, base({ speaking: true }));
    expect(onset.state).toBe("contact");
  });

  it("embarrassed averts DOWN at the first cadence; love, with the same dice, holds the gaze", () => {
    const roll = 0.2;
    expect(roll).toBeLessThan(AVERSION_P_IDLE * AVERSION_PROFILE.embarrassed!.p);
    expect(roll).toBeGreaterThan(AVERSION_P_IDLE * AVERSION_PROFILE.love!.p);

    const shy = new AttentionDirector(constant(roll));
    const shyAt = advance(shy, base({ emotion: "embarrassed" }), AVERSION_INTERVAL[0] + roll * 4.5 + 0.1);
    expect(shyAt.state).toBe("avert");
    expect(shyAt.offset.pitch).toBeGreaterThan(0);

    const loving = new AttentionDirector(constant(roll));
    const lovingAt = advance(loving, base({ emotion: "love" }), AVERSION_INTERVAL[0] + roll * 4.5 + 0.1);
    expect(lovingAt.state).toBe("contact");
  });

  it("listening (the viewer is typing) makes aversions rarer", () => {
    const roll = 0.3;
    expect(roll).toBeLessThan(AVERSION_P_IDLE);
    expect(roll).toBeGreaterThan(AVERSION_P_LISTENING);
    const idle = new AttentionDirector(constant(roll));
    const idleAt = advance(idle, base(), AVERSION_INTERVAL[0] + roll * 4.5 + 0.1);
    expect(idleAt.state).toBe("avert");
    const listening = new AttentionDirector(constant(roll));
    const listeningAt = advance(listening, base({ listening: true }), AVERSION_INTERVAL[0] + roll * 4.5 + 0.1);
    expect(listeningAt.state).toBe("contact");
  });

  it("every aversion profile names a known emotion and a legal direction", () => {
    const valid = new Set<string>(EMOTION_NAMES);
    for (const [emotion, profile] of Object.entries(AVERSION_PROFILE)) {
      expect(valid.has(emotion), emotion).toBe(true);
      expect(profile.p).toBeGreaterThan(0);
      if (profile.dir) {
        expect(Math.abs(profile.dir.pitch)).toBeLessThanOrEqual(0.25);
        expect(Math.abs(profile.dir.yaw)).toBeLessThanOrEqual(0.25);
      }
    }
  });
});

describe("AttentionDirector — saccades", () => {
  it("fire at the sampled cadence, as a jump, and are reported in shift", () => {
    const d = new AttentionDirector(constant(0));
    const first = advance(d, base(), SACCADE_INTERVAL[0] - 0.1);
    expect(first.saccade).toEqual({ pitch: 0, yaw: 0 });
    let jumped = false;
    let g = first;
    for (let i = 0; i < 6; i++) {
      g = d.update(0.05, base());
      if (g.shift > 0) jumped = true;
    }
    expect(jumped).toBe(true);
    expect(Math.hypot(g.saccade.pitch, g.saccade.yaw)).toBeGreaterThan(0.01);
  });

  it("a saccade is a step: two consecutive frames without one hold the same value", () => {
    const d = new AttentionDirector(constant(0.5));
    d.update(0.05, base());
    const a = d.update(0.05, base());
    const p = a.saccade.pitch;
    const y = a.saccade.yaw;
    const b = d.update(0.05, base());
    expect(b.saccade.pitch).toBe(p);
    expect(b.saccade.yaw).toBe(y);
  });
});
