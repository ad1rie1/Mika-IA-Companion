import * as THREE from "three";
import { beforeEach, describe, expect, it } from "vitest";
import type { ClipManifestEntry } from "../../../types";
import { ClipLibrary, type LoadedClip } from "../ClipLibrary";
import {
  AnimationStateMachine,
  SLEEP_YAWN_CLIP,
  SPEECH_SETTLE_S,
  WAKE_STRETCH_CLIP,
} from "../AnimationStateMachine";
import { affectTimeScale } from "../affect";
import { makeRig } from "./rigFixtures";

/**
 * The state machine against a REAL THREE.AnimationMixer and synthetic
 * clips on the fixture rig — the transitions below are the ones a user
 * sees: the beat after the voice stops, the yawn before sleep, the
 * stretch on waking, the tempo of a mood.
 */

function clip(name: string, duration: number): THREE.AnimationClip {
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.1, 0, 0));
  return new THREE.AnimationClip(name, duration, [
    new THREE.QuaternionKeyframeTrack("Normalized_head.quaternion", [0, duration], [
      0, 0, 0, 1, q.x, q.y, q.z, q.w,
    ]),
  ]);
}

function harness(opts: { yawn?: boolean; stretch?: boolean; random?: () => number } = {}) {
  const rig = makeRig("0");
  const library = new ClipLibrary();
  library.prepare(rig.vrm);
  const clips = (library as unknown as { clips: Map<string, LoadedClip> }).clips;
  const add = (name: string, meta: ClipManifestEntry, duration = 3) => {
    clips.set(name, { name, clip: clip(name, duration), meta, report: null });
  };
  add("idle_breathing", { url: "x", category: "idle", weight: 3, hold: [8, 16] });
  add("idle_happy", { url: "x", category: "idle", weight: 2, hold: [7, 14], valence: 0.7 });
  add("talk_main", { url: "x", category: "talk", weight: 2, hold: [4, 9] });
  add("talk_heated", { url: "x", category: "talk", weight: 1, hold: [4, 8], arousal: 0.8 });
  if (opts.yawn) add(SLEEP_YAWN_CLIP, { url: "x", category: "gesture", fadeIn: 0.2, fadeOut: 0.4 }, 2);
  if (opts.stretch) add(WAKE_STRETCH_CLIP, { url: "x", category: "gesture", fadeIn: 0.3, fadeOut: 0.5 }, 2);

  const mixer = new THREE.AnimationMixer(rig.vrm.humanoid!.normalizedHumanBonesRoot);
  const machine = new AnimationStateMachine(mixer, library, { random: opts.random ?? (() => 0.5) });
  const tick = (seconds: number, dt = 1 / 60) => {
    for (let t = 0; t < seconds - 1e-9; t += dt) {
      rig.vrm.humanoid!.resetNormalizedPose();
      machine.update(dt);
      mixer.update(dt);
    }
  };
  return { rig, library, mixer, machine, tick };
}

describe("speech settle", () => {
  let h: ReturnType<typeof harness>;
  beforeEach(() => {
    h = harness();
    h.machine.start();
  });

  it("holds the talking stance a beat after the voice stops, then relaxes", () => {
    h.machine.setSpeaking(true);
    expect(h.machine.state).toBe("talking");
    h.machine.setSpeaking(false);
    expect(h.machine.state).toBe("talking");
    expect(h.machine.isSettling).toBe(true);
    h.tick(SPEECH_SETTLE_S * 0.6);
    expect(h.machine.state).toBe("talking");
    h.tick(SPEECH_SETTLE_S * 0.6);
    expect(h.machine.state).toBe("idle");
    expect(h.machine.isSettling).toBe(false);
  });

  it("a second reply starting inside the beat never leaves talking, nor re-picks", () => {
    h.machine.setSpeaking(true);
    const clipName = h.machine.currentClipName;
    h.machine.setSpeaking(false);
    h.tick(0.3);
    h.machine.setSpeaking(true);
    expect(h.machine.state).toBe("talking");
    expect(h.machine.isSettling).toBe(false);
    expect(h.machine.currentClipName).toBe(clipName);
    h.tick(2);
    expect(h.machine.state).toBe("talking");
  });

  it("a gesture requested during the beat clears it and lands on idle", () => {
    h.machine.setSpeaking(true);
    h.machine.setSpeaking(false);
    const loaded = h.library.get("talk_heated")!;
    // Any loaded clip can be a gesture for the machine.
    expect(h.machine.requestGesture(loaded)).toBe(true);
    expect(h.machine.isSettling).toBe(false);
    h.tick(4);
    expect(h.machine.state).toBe("idle");
  });
});

describe("sleep edges", () => {
  it("yawns before dozing off when the yawn clip is on disk", () => {
    const h = harness({ yawn: true });
    h.machine.start();
    h.machine.setSleepPhase("light_sleep");
    expect(h.machine.state).toBe("gesture");
    expect(h.machine.currentClipName).toBe(SLEEP_YAWN_CLIP);
    h.tick(2.5);
    expect(h.machine.state).toBe("sleeping");
  });

  it("without a yawn clip she dozes off directly", () => {
    const h = harness();
    h.machine.start();
    h.machine.setSleepPhase("light_sleep");
    expect(h.machine.state).toBe("sleeping");
  });

  it("never yawns mid-sentence", () => {
    const h = harness({ yawn: true });
    h.machine.start();
    h.machine.setSpeaking(true);
    h.machine.setSleepPhase("light_sleep");
    expect(h.machine.state).toBe("sleeping");
  });

  it("a phase change while already asleep swaps the clip, no yawn", () => {
    const h = harness({ yawn: true });
    h.machine.start();
    h.machine.setSleepPhase("light_sleep");
    h.tick(2.5);
    expect(h.machine.state).toBe("sleeping");
    h.machine.setSleepPhase("deep_sleep");
    expect(h.machine.state).toBe("sleeping");
  });

  it("woken during the yawn, the yawn finishes into idle instead of sleep", () => {
    const h = harness({ yawn: true, stretch: true });
    h.machine.start();
    h.machine.setSleepPhase("light_sleep");
    expect(h.machine.currentClipName).toBe(SLEEP_YAWN_CLIP);
    h.tick(0.5);
    h.machine.setSleepPhase("awake");
    expect(h.machine.currentClipName).toBe(SLEEP_YAWN_CLIP);
    h.tick(2.5);
    expect(h.machine.state).toBe("idle");
  });

  it("wakes with a stretch when one is on disk, then idles", () => {
    const h = harness({ stretch: true });
    h.machine.start();
    h.machine.setSleepPhase("deep_sleep");
    expect(h.machine.state).toBe("sleeping");
    h.machine.setSleepPhase("awake");
    expect(h.machine.state).toBe("gesture");
    expect(h.machine.currentClipName).toBe(WAKE_STRETCH_CLIP);
    h.tick(2.5);
    expect(h.machine.state).toBe("idle");
  });

  it("woken by a question that is already being answered: straight to talking, no stretch", () => {
    const h = harness({ stretch: true });
    h.machine.start();
    h.machine.setSleepPhase("deep_sleep");
    h.machine.setSpeaking(true);
    h.machine.setSleepPhase("awake");
    expect(h.machine.state).toBe("talking");
  });

  it("without a stretch clip the wake fade lands on idle as before", () => {
    const h = harness();
    h.machine.start();
    h.machine.setSleepPhase("rem");
    h.machine.setSleepPhase("awake");
    expect(h.machine.state).toBe("idle");
  });
});

describe("affect-aware pools", () => {
  it("weighs the heated talk clip up for anger and down for melancholy", () => {
    const h = harness();
    const heated = h.library.get("talk_heated")!;
    const plain = h.library.get("talk_main")!;
    h.machine.setAffect("angry", 0.9);
    expect(h.machine.poolWeight(heated)).toBeGreaterThan(heated.meta.weight!);
    expect(h.machine.poolWeight(plain)).toBe(plain.meta.weight!);
    h.machine.setAffect("melancholic", 0.9);
    expect(h.machine.poolWeight(heated)).toBeLessThan(heated.meta.weight! * 0.6);
  });

  it("a cheerful idle is rarely drawn when she is sad", () => {
    const h = harness();
    const happy = h.library.get("idle_happy")!;
    h.machine.setAffect("sad", 0.9);
    expect(h.machine.poolWeight(happy)).toBeLessThan(happy.meta.weight! * 0.5);
    h.machine.setAffect("neutral", 0.5);
    expect(h.machine.poolWeight(happy)).toBe(happy.meta.weight!);
  });

  it("the base clip's tempo eases toward the emotion's arousal and is applied to the action", () => {
    const h = harness();
    h.machine.start();
    h.machine.setAffect("excited", 1);
    h.tick(3);
    const expected = affectTimeScale("excited", 1);
    expect(h.machine.affectTempo).toBeCloseTo(expected, 2);
    const action = (h.machine as unknown as { currentAction: THREE.AnimationAction }).currentAction;
    expect(action.getEffectiveTimeScale()).toBeCloseTo(expected, 2);
    h.machine.setAffect("melancholic", 1);
    h.tick(3);
    expect(h.machine.affectTempo).toBeLessThan(1);
  });

  it("setAffect never triggers a transition by itself", () => {
    const h = harness();
    h.machine.start();
    const clipName = h.machine.currentClipName;
    h.machine.setAffect("angry", 1);
    h.tick(0.5);
    expect(h.machine.currentClipName).toBe(clipName);
    expect(h.machine.state).toBe("idle");
  });
});
