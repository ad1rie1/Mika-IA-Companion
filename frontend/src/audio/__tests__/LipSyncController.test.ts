import { describe, expect, it } from "vitest";
import type { VRM } from "@pixiv/three-vrm";
import { DEFAULT_MS_PER_CHAR, LipSyncController, msPerCharForRate } from "../LipSyncController";

function stubVrm(): VRM {
  return {
    expressionManager: { setValue: () => {}, getExpression: () => null },
  } as unknown as VRM;
}

describe("msPerCharForRate", () => {
  it("scales the estimate with the utterance rate, bounded like the rate itself", () => {
    expect(msPerCharForRate(1)).toBe(DEFAULT_MS_PER_CHAR);
    expect(msPerCharForRate(2)).toBe(DEFAULT_MS_PER_CHAR / 2);
    expect(msPerCharForRate(0.5)).toBe(DEFAULT_MS_PER_CHAR * 2);
    expect(msPerCharForRate(10)).toBe(DEFAULT_MS_PER_CHAR / 2);
    expect(msPerCharForRate(Number.NaN)).toBe(DEFAULT_MS_PER_CHAR);
    expect(msPerCharForRate(0)).toBe(DEFAULT_MS_PER_CHAR);
  });
});

describe("LipSyncController — frames keep their character index", () => {
  it("the estimate advances through the text, and a word boundary re-seats it", () => {
    const lip = new LipSyncController();
    lip.setVRM(stubVrm());
    lip.startFromPlan([{ type: "speech", text: "bonjour tout le monde", start: 0 }], 60);
    expect(lip.currentCharOffset).toBe(0);
    lip.update(0.13); // two 60 ms frames
    expect(lip.currentCharOffset).toBe(2);

    expect(lip.seekToChar(8)).toBe(true); // "tout"
    expect(lip.currentCharOffset).toBe(8);
    expect(lip.isSpeaking()).toBe(true);
  });

  it("seeking backward works too — a slow voice pulls the mouth back", () => {
    const lip = new LipSyncController();
    lip.setVRM(stubVrm());
    lip.startFromPlan([{ type: "speech", text: "bonjour tout le monde", start: 0 }], 60);
    lip.update(1.0);
    expect(lip.currentCharOffset).toBeGreaterThan(10);
    lip.seekToChar(3);
    expect(lip.currentCharOffset).toBe(3);
  });

  it("silences carry no index and are skipped over by a seek", () => {
    const lip = new LipSyncController();
    lip.setVRM(stubVrm());
    lip.startFromPlan(
      [
        { type: "speech", text: "ok", start: 0 },
        { type: "silence", ms: 600 },
        { type: "speech", text: "oui", start: 9 },
      ],
      60
    );
    expect(lip.seekToChar(9)).toBe(true);
    expect(lip.currentCharOffset).toBe(9);
  });

  it("collapsed whitespace keeps the ORIGINAL indices", () => {
    const lip = new LipSyncController();
    lip.setVRM(stubVrm());
    lip.startFromPlan([{ type: "speech", text: "a  b", start: 0 }], 60);
    lip.seekToChar(3);
    expect(lip.currentCharOffset).toBe(3);
    // The double space is one short frame, not two.
    lip.seekToChar(1);
    expect(lip.currentCharOffset).toBe(1);
    lip.update(0.035);
    expect(lip.currentCharOffset).toBe(3);
  });

  it("a boundary past the last voiced character lands on the last voiced frame", () => {
    const lip = new LipSyncController();
    lip.setVRM(stubVrm());
    lip.startFromPlan([{ type: "speech", text: "ok.", start: 4 }], 60);
    expect(lip.seekToChar(500)).toBe(true);
    expect(lip.currentCharOffset).toBe(6);
  });

  it("an estimate that finished early is revived by the next boundary", () => {
    // The defect: at rate 0.8 the mouth closed with a fifth of the audio
    // still to go, because the plan ran out before the voice did.
    const lip = new LipSyncController();
    lip.setVRM(stubVrm());
    lip.startFromPlan([{ type: "speech", text: "salut", start: 0 }], 60);
    lip.update(5);
    expect(lip.isSpeaking()).toBe(false);
    expect(lip.seekToChar(3)).toBe(true);
    expect(lip.isSpeaking()).toBe(true);
    expect(lip.currentCharOffset).toBe(3);
  });

  it("a plan without positions still plays (legacy path) and refuses seeks gracefully", () => {
    const lip = new LipSyncController();
    lip.setVRM(stubVrm());
    lip.startTextDriven("bonjour", 420);
    expect(lip.isSpeaking()).toBe(true);
    expect(lip.currentCharOffset).toBe(-1);
    expect(lip.seekToChar(2)).toBe(false);
    lip.stop();
    expect(lip.seekToChar(0)).toBe(false);
  });
});
