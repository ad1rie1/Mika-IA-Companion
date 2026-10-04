import { describe, expect, it } from "vitest";
import type { VRM } from "@pixiv/three-vrm";
import { EMOTION_NAMES } from "../../types";
import {
  EmotionController,
  MIN_OFFSET_SPEED,
  offsetSpeedFor,
  onsetSpeedFor,
} from "../EmotionController";

function stubVrm() {
  const values = new Map<string, number>();
  const vrm = {
    expressionManager: {
      getExpression: () => null, // standard presets only
      setValue: (name: string, v: number) => values.set(name, v),
    },
  } as unknown as VRM;
  return { vrm, values };
}

describe("expression onset / offset asymmetry", () => {
  it("a startle lands faster than sadness; every offset is slower than its onset", () => {
    expect(onsetSpeedFor("surprised")).toBeGreaterThan(onsetSpeedFor("happy"));
    expect(onsetSpeedFor("happy")).toBeGreaterThan(onsetSpeedFor("sad"));
    for (const name of EMOTION_NAMES) {
      expect(offsetSpeedFor(name), name).toBeLessThan(onsetSpeedFor(name));
      expect(offsetSpeedFor(name), name).toBeGreaterThanOrEqual(MIN_OFFSET_SPEED);
    }
  });

  it("on the face: surprise is mostly there after 100 ms, sadness is not", () => {
    const fast = stubVrm();
    const ec1 = new EmotionController();
    ec1.setVRM(fast.vrm);
    ec1.setEmotion("surprised", 1);
    ec1.update(0.1);
    expect(fast.values.get("surprised")!).toBeGreaterThan(0.75);

    const slow = stubVrm();
    const ec2 = new EmotionController();
    ec2.setVRM(slow.vrm);
    ec2.setEmotion("sad", 1);
    ec2.update(0.1);
    expect(slow.values.get("sad")!).toBeLessThan(0.25);
  });

  it("an expression fades out more slowly than it came in", () => {
    const { vrm, values } = stubVrm();
    const ec = new EmotionController();
    ec.setVRM(vrm);
    ec.setEmotion("happy", 1);
    ec.update(0.1);
    const risen = values.get("happy")!;
    // Let it fully land, then release toward neutral.
    for (let i = 0; i < 60; i++) ec.update(0.05);
    ec.setEmotion("neutral", 1);
    ec.update(0.1);
    const remaining = values.get("happy")!;
    // Rose by `risen` in 100 ms; fell by less than that in the same 100 ms.
    expect(1 - remaining).toBeLessThan(risen * 0.75);
  });
});
