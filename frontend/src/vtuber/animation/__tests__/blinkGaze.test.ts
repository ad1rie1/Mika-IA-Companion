import { afterEach, describe, expect, it, vi } from "vitest";
import type { VRM } from "@pixiv/three-vrm";
import {
  BlinkController,
  GAZE_BLINK_MIN_SHIFT,
  GAZE_BLINK_REFRACTORY_S,
} from "../BlinkController";
import { OverlayContext } from "../overlays/Overlay";

function ctxWithBlink() {
  const values = new Map<string, number>();
  const vrm = {
    meta: { metaVersion: "0" },
    expressionManager: {
      setValue: (name: string, v: number) => values.set(name, v),
      getExpression: () => null,
    },
    humanoid: { getNormalizedBoneNode: () => null },
  } as unknown as VRM;
  return { ctx: new OverlayContext(vrm), values };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("gaze-evoked blinks", () => {
  it("a large gaze shift can trigger a blink outside the regular cadence", () => {
    // Regular cadence far away (nextBlinkAt ≥ 3 s); the roll passes.
    vi.spyOn(Math, "random").mockReturnValue(0.1);
    const { ctx, values } = ctxWithBlink();
    const blink = new BlinkController();
    // Past the refractory window, eyes open.
    for (let i = 0; i < 60; i++) {
      ctx.gazeShift = 0;
      blink.update(1 / 60, ctx);
    }
    expect(values.get("blink") ?? 0).toBe(0);
    ctx.gazeShift = GAZE_BLINK_MIN_SHIFT + 0.05;
    blink.update(1 / 60, ctx);
    ctx.gazeShift = 0;
    blink.update(0.05, ctx);
    expect(values.get("blink")!).toBeGreaterThan(0.3);
  });

  it("a small fixational jump never does", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.1);
    const { ctx, values } = ctxWithBlink();
    const blink = new BlinkController();
    for (let i = 0; i < 60; i++) {
      ctx.gazeShift = 0;
      blink.update(1 / 60, ctx);
    }
    ctx.gazeShift = GAZE_BLINK_MIN_SHIFT * 0.5;
    blink.update(1 / 60, ctx);
    ctx.gazeShift = 0;
    blink.update(0.05, ctx);
    expect(values.get("blink") ?? 0).toBe(0);
  });

  it("nor a shift right after a blink (refractory)", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.1);
    const { ctx, values } = ctxWithBlink();
    const blink = new BlinkController();
    for (let i = 0; i < 60; i++) {
      ctx.gazeShift = 0;
      blink.update(1 / 60, ctx);
    }
    ctx.gazeShift = 0.3;
    blink.update(1 / 60, ctx);
    // Let that blink finish (~165 ms), then shift again inside the window.
    ctx.gazeShift = 0;
    for (let i = 0; i < 15; i++) blink.update(1 / 60, ctx);
    expect(values.get("blink")!).toBe(0);
    ctx.gazeShift = 0.3;
    blink.update(1 / 60, ctx);
    ctx.gazeShift = 0;
    blink.update(0.05, ctx);
    expect(values.get("blink")!).toBe(0);
    expect(GAZE_BLINK_REFRACTORY_S).toBeGreaterThan(0.25);
  });
});
