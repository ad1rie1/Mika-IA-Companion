import * as THREE from "three";
import { describe, expect, it } from "vitest";
import { stepPhysiology } from "../FacePhysiology";
import { secondaryOf } from "../EmotionController";
import type { EmotionName } from "../../types";
import { baseClipName, mirrorClip } from "../animation/clipMirror";

function hold(emotion: EmotionName, intensity: number, seconds: number, state = fresh()) {
  for (let t = 0; t < seconds; t += 1 / 30) stepPhysiology(state, emotion, intensity, 1 / 30);
  return state;
}
const fresh = () => ({ blush: 0, watery: 0, tear: 0, pupil: 0, load: 0 });

describe("face physiology", () => {
  it("tears well up: never on the first second, only after strong sadness lasts", () => {
    expect(hold("sad", 0.95, 1).tear).toBe(0);
    const s = hold("sad", 0.95, 10);
    expect(s.watery).toBeGreaterThan(0.9);
    expect(s.tear).toBeGreaterThan(0.4);
  });

  it("a mild sadness, however long, never cries", () => {
    const s = hold("sad", 0.5, 60);
    expect(s.tear).toBe(0);
    expect(s.watery).toBeLessThan(0.5);
  });

  it("laughing to tears only happens at the top of the scale", () => {
    expect(hold("amused", 0.7, 20).watery).toBe(0);
    expect(hold("amused", 1, 8).watery).toBeGreaterThan(0.3);
  });

  it("tears dry slowly after the sadness passes", () => {
    const s = hold("sad", 0.95, 10);
    const before = s.watery;
    hold("neutral", 0.5, 3, s);
    expect(s.watery).toBeGreaterThan(before * 0.5);
    hold("neutral", 0.5, 40, s);
    expect(s.watery).toBeLessThan(0.05);
  });

  it("a blush comes in over a second or two and leaves much more slowly", () => {
    const s = hold("embarrassed", 0.9, 0.3);
    expect(s.blush).toBeLessThan(0.3);
    hold("embarrassed", 0.9, 5, s);
    const peak = s.blush;
    expect(peak).toBeGreaterThan(0.7);
    hold("happy", 0.6, 2, s);
    expect(s.blush).toBeGreaterThan(peak * 0.7);
  });

  it("pupils widen with love and fear, narrow with anger", () => {
    expect(hold("love", 0.9, 3).pupil).toBeGreaterThan(0.3);
    expect(hold("scared", 0.9, 3).pupil).toBeGreaterThan(0.3);
    expect(hold("angry", 0.9, 3).pupil).toBeLessThan(-0.2);
  });
});

describe("secondary emotion on the face", () => {
  it("shows a secondary feeling only when it weighs enough", () => {
    expect(secondaryOf("happy", [{ emotion: "happy", weight: 0.6 }, { emotion: "sad", weight: 0.4 }]))
      .toEqual({ emotion: "sad", ratio: expect.closeTo(0.667, 2) });
    expect(secondaryOf("happy", [{ emotion: "happy", weight: 0.9 }, { emotion: "sad", weight: 0.1 }])).toBeNull();
    expect(secondaryOf("happy", [{ emotion: "happy", weight: 1 }])).toBeNull();
    expect(secondaryOf("happy", [{ emotion: "happy", weight: 0.6 }, { emotion: "bogus", weight: 0.5 }])).toBeNull();
  });
});

describe("clip mirroring", () => {
  const nodes = new Map([
    ["L_arm", "R_arm"],
    ["R_arm", "L_arm"],
    ["hips", "hips"],
  ]);
  const q = new THREE.Quaternion().setFromEuler(new THREE.Euler(0.2, 0.3, 0.4));
  const clip = new THREE.AnimationClip("idle", 1, [
    new THREE.QuaternionKeyframeTrack("L_arm.quaternion", [0], [q.x, q.y, q.z, q.w]),
    new THREE.QuaternionKeyframeTrack("hips.quaternion", [0], [q.x, q.y, q.z, q.w]),
    new THREE.VectorKeyframeTrack("hips.position", [0], [0.1, 0.9, 0.05]),
  ]);

  it("moves each track to the opposite bone and reflects across the lateral plane", () => {
    const m = mirrorClip(clip, nodes);
    expect(m.name).toBe("idle~m");
    expect(baseClipName(m.name)).toBe("idle");
    const arm = m.tracks.find((t) => t.name === "R_arm.quaternion")!;
    expect(Array.from(arm.values)).toEqual(
      [q.x, -q.y, -q.z, q.w].map((v) => expect.closeTo(v, 6))
    );
    const pos = m.tracks.find((t) => t.name === "hips.position")!;
    expect(Array.from(pos.values)).toEqual([expect.closeTo(-0.1, 6), expect.closeTo(0.9, 6), expect.closeTo(0.05, 6)]);
  });

  it("mirroring twice gives the original back", () => {
    const twice = mirrorClip(mirrorClip(clip, nodes), nodes, "idle");
    for (const t of clip.tracks) {
      const back = twice.tracks.find((x) => x.name === t.name)!;
      expect(Array.from(back.values)).toEqual(Array.from(t.values).map((v) => expect.closeTo(v, 6)));
    }
  });

  it("a reflected rotation mirrors its effect on a vector", () => {
    const m = mirrorClip(clip, nodes);
    const mq = new THREE.Quaternion().fromArray(Array.from(m.tracks.find((t) => t.name === "hips.quaternion")!.values));
    const v = new THREE.Vector3(0.3, 0.5, 0.7);
    const a = v.clone().applyQuaternion(q);
    const b = new THREE.Vector3(-v.x, v.y, v.z).applyQuaternion(mq);
    expect(b.x).toBeCloseTo(-a.x, 6);
    expect(b.y).toBeCloseTo(a.y, 6);
    expect(b.z).toBeCloseTo(a.z, 6);
  });
});
