import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { planSpeechBeats } from "../speechBeats";
import { OverlayContext } from "../overlays/Overlay";
import { SpeechBodyOverlay } from "../overlays/SpeechBodyOverlay";
import { BreathingOverlay, breathWave } from "../overlays/BreathingOverlay";
import { LifeOverlay, lifeNoise } from "../overlays/LifeOverlay";
import { makeRig, worldForward } from "./rigFixtures";

const last = <T>(xs: T[]): T => xs[xs.length - 1];
const kinds = (text: string) => planSpeechBeats(text).map((b) => [text.slice(b.at).split(/[\s,]/)[0], b.kind]);

describe("planSpeechBeats", () => {
  it("closes a question on its last word, a statement with a nod", () => {
    expect(last(kinds("Tu vas bien ?"))).toEqual(["bien", "question"]);
    expect(last(kinds("Je suis rentrée tard."))).toEqual(["tard.", "final"]);
    expect(last(kinds("C'est génial !"))).toEqual(["génial", "emphasis"]);
    expect(last(kinds("Je ne sais pas…"))).toEqual(["pas…", "trail"]);
  });

  it("puts a pause on the comma itself and stresses the word closing the group", () => {
    const text = "Franchement mardi, demain soir ça me va.";
    const beats = planSpeechBeats(text);
    const pause = beats.find((b) => b.kind === "pause")!;
    expect(text[pause.at]).toBe(",");
    expect(beats.some((b) => b.kind === "stress" && text.startsWith("mardi", b.at))).toBe(true);
  });

  it("insists on capitals, *starred* words and intensifiers", () => {
    const text = "Non mais c'est TROP bien, et vraiment *magique* quoi.";
    const emphasized = planSpeechBeats(text)
      .filter((b) => b.kind === "emphasis")
      .map((b) => text.slice(b.at).match(/[\p{L}]+/u)![0]);
    expect(emphasized).toEqual(expect.arrayContaining(["TROP", "vraiment", "magique"]));
  });

  it("never beats inside a prosody token, and keeps indices in the full text", () => {
    const text = "[SIGH] Bon. [PAUSE:400] On y va ?";
    const beats = planSpeechBeats(text);
    for (const b of beats) {
      expect(text.slice(b.at)).not.toMatch(/^[A-Z_]+[:\]]/);
      expect(text[b.at]).toMatch(/[\p{L},]/u);
    }
    expect(text.startsWith("va", last(beats).at)).toBe(true);
  });

  it("a long clause still moves: no stretch of 30+ characters goes unpunctuated", () => {
    const text =
      "Je me disais que les longues soirées passées à regarder les étoiles depuis le balcon étaient précieuses.";
    const at = planSpeechBeats(text).map((b) => b.at);
    for (let i = 1; i < at.length; i++) expect(at[i] - at[i - 1]).toBeLessThanOrEqual(36);
    expect(at.length).toBeGreaterThanOrEqual(4);
  });

  it("is sorted with one beat per position", () => {
    const beats = planSpeechBeats("Coucou ! Tu sais, j'ai repensé à tout ça. Et toi ?");
    for (let i = 1; i < beats.length; i++) expect(beats[i].at).toBeGreaterThan(beats[i - 1].at);
  });
});

function stage(meta: "0" | "1") {
  const rig = makeRig(meta);
  const ctx = new OverlayContext(rig.vrm);
  ctx.speaking = true;
  ctx.emotion = "neutral";
  const overlay = new SpeechBodyOverlay(() => 0.3);
  const run = (seconds: number, cursor = ctx.speechCursor) => {
    ctx.speechCursor = cursor;
    let maxPitch = -Infinity;
    for (let t = 0; t < seconds; t += 1 / 60) {
      rig.vrm.humanoid!.resetNormalizedPose();
      overlay.update(1 / 60, ctx);
      const e = new THREE.Euler().setFromQuaternion(rig.nodes.get("head")!.quaternion);
      maxPitch = Math.max(maxPitch, rig.sign * e.x);
    }
    return maxPitch;
  };
  return { rig, ctx, overlay, run };
}

describe("SpeechBodyOverlay", () => {
  it("nods when the voice reaches a stressed word, not before", () => {
    const { overlay, run } = stage("1");
    const text = "Je pense que tu as raison.";
    overlay.begin(planSpeechBeats(text));
    expect(run(0.4, 2)).toBeLessThan(0.005); // before "raison"
    expect(run(0.4, text.indexOf("raison"))).toBeGreaterThan(0.02);
  });

  it("the nod tips the face DOWN on both rig conventions", () => {
    for (const meta of ["0", "1"] as const) {
      const { rig, overlay, ctx } = stage(meta);
      const text = "Vraiment.";
      overlay.begin(planSpeechBeats(text));
      ctx.speechCursor = 0;
      let lowest = 0;
      for (let i = 0; i < 20; i++) {
        rig.vrm.humanoid!.resetNormalizedPose();
        overlay.update(1 / 60, ctx);
        lowest = Math.min(lowest, worldForward(rig.nodes.get("head")!, rig.sign).y);
      }
      expect(lowest).toBeLessThan(-0.02);
    }
  });

  it("a question lifts the chin, tilts the head and holds the brows up", () => {
    const { overlay, ctx, rig, run } = stage("1");
    const text = "Tu viens ce soir ?";
    overlay.begin(planSpeechBeats(text));
    run(0.6, text.indexOf("soir"));
    const e = new THREE.Euler().setFromQuaternion(rig.nodes.get("head")!.quaternion);
    expect(Math.abs(e.z)).toBeGreaterThan(0.02);
    expect(e.x).toBeLessThan(0);
    expect(ctx.speechQuestion).toBeGreaterThan(0.5);
  });

  it("skips beats the cursor jumped far past (a resync) instead of firing a burst", () => {
    const { overlay, run } = stage("1");
    const text = "Alors voilà, hier soir je suis allée voir le concert dont je te parlais.";
    overlay.begin(planSpeechBeats(text));
    // Every beat lies more than STALE_CHARS behind the re-seated cursor.
    expect(run(0.5, text.length + 15)).toBeLessThan(0.01);
  });

  it("is silent when she is not speaking, and a murmur barely moves", () => {
    const quiet = stage("1");
    quiet.ctx.speaking = false;
    quiet.overlay.begin(planSpeechBeats("Vraiment."));
    expect(quiet.run(0.4, 0)).toBeLessThan(0.005);

    const loud = stage("1");
    loud.overlay.begin(planSpeechBeats("Vraiment."));
    const inner = stage("1");
    inner.ctx.persona = "inner";
    inner.overlay.begin(planSpeechBeats("Vraiment."));
    expect(inner.run(0.4, 0)).toBeLessThan(loud.run(0.4, 0) * 0.5);
  });

  it("asks for a breath at the start of an utterance and at clause pauses", () => {
    const { overlay, ctx } = stage("1");
    const text = "Bon, on y va.";
    overlay.begin(planSpeechBeats(text));
    ctx.speechCursor = 0;
    overlay.update(1 / 60, ctx);
    expect(ctx.breathRequest).toBe("catch");
    ctx.breathRequest = null;
    ctx.speechCursor = text.indexOf(",");
    overlay.update(1 / 60, ctx);
    expect(ctx.breathRequest).toBe("catch");
  });
});

describe("breathing", () => {
  it("inhales faster than it exhales, then pauses empty", () => {
    expect(breathWave(0.36)).toBeCloseTo(1, 5);
    // Half-way up the inhale vs half-way down the exhale, in cycle time.
    const inhaleSpan = 0.36;
    const exhaleSpan = 0.86 - 0.36;
    expect(exhaleSpan).toBeGreaterThan(inhaleSpan);
    expect(breathWave(0.9)).toBe(0);
    expect(breathWave(0.99)).toBe(0);
  });

  function breathe(setup: (ctx: OverlayContext) => void, seconds: number, random = Math.random) {
    const rig = makeRig("1");
    const ctx = new OverlayContext(rig.vrm);
    setup(ctx);
    const overlay = new BreathingOverlay(random);
    const trace: number[] = [];
    for (let t = 0; t < seconds; t += 1 / 60) {
      overlay.update(1 / 60, ctx);
      trace.push(ctx.breath);
    }
    return { trace, ctx, overlay };
  }

  it("no two breaths alike: cycle lengths vary", () => {
    const { trace } = breathe(() => {}, 40);
    const peaks: number[] = [];
    for (let i = 1; i < trace.length - 1; i++) {
      if (trace[i] > 0.6 && trace[i] >= trace[i - 1] && trace[i] > trace[i + 1]) peaks.push(i);
    }
    const gaps = peaks.slice(1).map((p, i) => p - peaks[i]);
    expect(gaps.length).toBeGreaterThanOrEqual(4);
    expect(new Set(gaps.map((g) => Math.round(g / 6))).size).toBeGreaterThan(1);
  });

  it("speaking: a catch-breath fills quickly, then the words empty it slowly", () => {
    const { trace, ctx, overlay } = breathe((c) => (c.speaking = true), 2);
    const low = last(trace);
    ctx.breathRequest = "catch";
    for (let i = 0; i < 18; i++) overlay.update(1 / 60, ctx);
    expect(ctx.breath).toBeGreaterThan(low + 0.25);
    const full = ctx.breath;
    for (let i = 0; i < 60; i++) overlay.update(1 / 60, ctx);
    expect(ctx.breath).toBeLessThan(full);
    expect(ctx.breath).toBeGreaterThan(full - 0.35);
  });

  it("a sigh goes past a normal breath, then below empty, then settles", () => {
    const { ctx, overlay } = breathe(() => {}, 0.1);
    ctx.breathRequest = "sigh";
    let max = 0;
    let min = 0;
    for (let t = 0; t < 4.2; t += 1 / 60) {
      overlay.update(1 / 60, ctx);
      max = Math.max(max, ctx.breath);
      min = Math.min(min, ctx.breath);
    }
    expect(max).toBeGreaterThan(1.5);
    expect(min).toBeLessThan(-0.1);
  });
});

describe("LifeOverlay", () => {
  it("noise stays bounded", () => {
    for (let t = 0; t < 200; t += 0.37) expect(Math.abs(lifeNoise(t, 3))).toBeLessThanOrEqual(1);
  });

  function sway(setup: (ctx: OverlayContext) => void, seconds: number) {
    const rig = makeRig("1");
    const ctx = new OverlayContext(rig.vrm);
    setup(ctx);
    let seed = 1;
    const overlay = new LifeOverlay(() => ((seed = (seed * 16807) % 2147483647) / 2147483647));
    const rolls: number[] = [];
    for (let t = 0; t < seconds; t += 1 / 30) {
      rig.vrm.humanoid!.resetNormalizedPose();
      overlay.update(1 / 30, ctx);
      rolls.push(new THREE.Euler().setFromQuaternion(rig.nodes.get("spine")!.quaternion).z);
    }
    return rolls;
  }

  it("shifts its weight within half a minute, and stays subtle", () => {
    const rolls = sway(() => {}, 30);
    const max = Math.max(...rolls.map(Math.abs));
    expect(max).toBeGreaterThan(0.012);
    expect(max).toBeLessThan(0.08);
  });

  it("is nearly still in sleep", () => {
    const awake = sway(() => {}, 20);
    const asleep = sway((c) => (c.sleepPhase = "deep_sleep"), 20);
    const amp = (xs: number[]) => Math.max(...xs.slice(200).map(Math.abs));
    expect(amp(asleep)).toBeLessThan(amp(awake) * 0.5);
  });
});
