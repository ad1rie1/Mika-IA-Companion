import { describe, expect, it } from "vitest";
import {
  VRMExpression,
  VRMExpressionManager,
  VRMExpressionMorphTargetBind,
  type VRM,
} from "@pixiv/three-vrm";
import { rawName } from "../../vtuber/faceRig";
import {
  DEFAULT_MS_PER_CHAR,
  LipSyncController,
  VRC_VISEME_MORPHS,
  msPerCharForRate,
} from "../LipSyncController";

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
    // 130 ms in: past the closure of the « b », inside the nasal « on » —
    // one frame for the digraph, anchored on its first letter (the old
    // letter-by-letter estimate had reached the « n » as a separate shape).
    lip.update(0.13);
    expect(lip.currentCharOffset).toBe(1);
    expect(lip.currentViseme).toBe("oh");

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

// ── Rendering on a face ─────────────────────────────────────────────

const PRESETS = ["aa", "ih", "ou", "ee", "oh"];

/**
 * A VRM reduced to what the lip-sync touches: one mesh carrying `morphs`,
 * and a REAL expression manager (registration, setValue/getValue, binds)
 * holding the five mouth presets.
 */
function faceVrm(morphs: readonly string[]) {
  const mesh = {
    isMesh: true,
    morphTargetDictionary: Object.fromEntries(morphs.map((m, i) => [m, i])),
    morphTargetInfluences: morphs.map(() => 0),
  };
  const manager = new VRMExpressionManager();
  for (const preset of PRESETS) manager.registerExpression(new VRMExpression(preset));
  const vrm = {
    scene: { traverse: (visit: (o: unknown) => void) => visit(mesh) },
    expressionManager: manager,
  } as unknown as VRM;
  /** An expression of another controller (emotion), bound to one morph. */
  const addExpression = (name: string, morph: string, weight = 1) => {
    const expression = new VRMExpression(name);
    expression.addBind(
      new VRMExpressionMorphTargetBind({
        primitives: [mesh as never],
        index: mesh.morphTargetDictionary[morph],
        weight,
      })
    );
    manager.registerExpression(expression);
  };
  return { vrm, manager, addExpression };
}

const v = (manager: VRMExpressionManager, morph: string) => manager.getValue(rawName(morph)) ?? 0;
const STEP = 1 / 120;

/** Plays `text` and returns, per step, the viseme values and the cursor. */
function play(lip: LipSyncController, manager: VRMExpressionManager, text: string, msPerChar = 60) {
  lip.startFromPlan([{ type: "speech", text, start: 0 }], msPerChar);
  const samples: Array<{ offset: number; viseme: string; values: Record<string, number> }> = [];
  for (let k = 0; k < 400 && lip.isSpeaking(); k++) {
    lip.update(STEP);
    const values: Record<string, number> = {};
    for (const morph of VRC_VISEME_MORPHS) values[morph] = v(manager, morph);
    for (const preset of PRESETS) values[preset] = manager.getValue(preset) ?? 0;
    samples.push({ offset: lip.currentCharOffset, viseme: lip.currentViseme, values });
  }
  return samples;
}

const visemeSum = (values: Record<string, number>) =>
  VRC_VISEME_MORPHS.reduce((sum, morph) => sum + values[morph], 0);
const peak = (samples: ReturnType<typeof play>, key: string) =>
  Math.max(...samples.map((s) => s.values[key]));

describe("LipSyncController — articulating on the VRChat visemes", () => {
  it("registers and drives the vrc.v_* morphs when the model carries them, leaving the presets alone", () => {
    const { vrm, manager } = faceVrm(VRC_VISEME_MORPHS);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    expect(lip.outputMode).toBe("visemes");
    expect(manager.getExpression(rawName("vrc.v_pp"))).not.toBeNull();

    const samples = play(lip, manager, "papa");
    expect(peak(samples, "vrc.v_aa")).toBeGreaterThan(0.6);
    expect(peak(samples, "vrc.v_pp")).toBeGreaterThan(0.7);
    for (const preset of PRESETS) expect(peak(samples, preset)).toBe(0);
  });

  it("a bilabial actually closes the mouth between two vowels", () => {
    const { vrm, manager } = faceVrm(VRC_VISEME_MORPHS);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    const samples = play(lip, manager, "papa");
    // After the first « a » has opened the mouth, the second « p » must read:
    // lips shut, the open shape out of the way.
    const opened = samples.findIndex((s) => s.values["vrc.v_aa"] > 0.5);
    expect(opened).toBeGreaterThan(-1);
    const closed = samples
      .slice(opened)
      .some((s) => s.values["vrc.v_pp"] > 0.6 && s.values["vrc.v_aa"] < 0.35);
    expect(closed).toBe(true);
  });

  it("and the vowel after it opens clearly — the closure hands over, it does not linger", () => {
    // The defect this pins: the « p » faded at the rest-release rate, so the
    // lips stayed half shut through the whole « a » that followed.
    const { vrm, manager } = faceVrm(VRC_VISEME_MORPHS);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    const firstA = play(lip, manager, "papa").filter((s) => s.offset === 1);
    expect(firstA.some((s) => s.values["vrc.v_aa"] > 0.72 && s.values["vrc.v_pp"] < 0.2)).toBe(true);
  });

  it("anticipates: the lips start closing for the « p » before the « a » ends", () => {
    const { vrm, manager } = faceVrm(VRC_VISEME_MORPHS);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    const samples = play(lip, manager, "papa");
    const firstA = samples.filter((s) => s.offset === 1);
    expect(firstA.length).toBeGreaterThan(3);
    const lowest = Math.min(...firstA.map((s) => s.values["vrc.v_pp"]));
    expect(firstA[firstA.length - 1].values["vrc.v_pp"]).toBeGreaterThan(lowest + 0.1);
  });

  it("never sums the visemes past one mouth", () => {
    const { vrm, manager } = faceVrm(VRC_VISEME_MORPHS);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    const samples = play(lip, manager, "oiseau, champagne, beaucoup !");
    for (const s of samples) expect(visemeSum(s.values)).toBeLessThanOrEqual(1 + 1e-6);
  });

  it("leaves room for an emotion that already opens the mouth", () => {
    const morphs = [...VRC_VISEME_MORPHS, "MouthOpen4", "MouthSmile2"];
    const free = faceVrm(morphs);
    const lipFree = new LipSyncController();
    lipFree.setVRM(free.vrm);
    const freePeak = Math.max(...play(lipFree, free.manager, "papa").map((s) => visemeSum(s.values)));

    const shocked = faceVrm(morphs);
    const lip = new LipSyncController();
    lip.setVRM(shocked.vrm);
    // Registered AFTER setVRM, like another controller's raw shapes would be.
    shocked.addExpression("Shocked", "MouthOpen4");
    shocked.manager.setValue("Shocked", 1);
    const samples = play(lip, shocked.manager, "papa");
    const shockedPeak = Math.max(...samples.map((s) => visemeSum(s.values)));
    expect(freePeak).toBeGreaterThan(0.8);
    // A fully open mouth leaves the speech its floor, no more.
    expect(shockedPeak).toBeLessThanOrEqual(0.45 + 1e-6);
    expect(shockedPeak).toBeGreaterThan(0.3);

    // A smile is not an opening: it costs the speech much less.
    const smiling = faceVrm(morphs);
    const lipSmile = new LipSyncController();
    lipSmile.setVRM(smiling.vrm);
    smiling.addExpression("Smile", "MouthSmile2");
    smiling.manager.setValue("Smile", 1);
    const smilePeak = Math.max(...play(lipSmile, smiling.manager, "papa").map((s) => visemeSum(s.values)));
    expect(smilePeak).toBeGreaterThan(0.8);
  });

  it("a lower articulation makes smaller openings but keeps the closures", () => {
    const full = faceVrm(VRC_VISEME_MORPHS);
    const lipFull = new LipSyncController();
    lipFull.setVRM(full.vrm);
    const fullSamples = play(lipFull, full.manager, "papa");

    const tired = faceVrm(VRC_VISEME_MORPHS);
    const lipTired = new LipSyncController();
    lipTired.setVRM(tired.vrm);
    lipTired.setArticulation(0.6);
    const tiredSamples = play(lipTired, tired.manager, "papa");

    expect(peak(tiredSamples, "vrc.v_aa")).toBeLessThan(peak(fullSamples, "vrc.v_aa") * 0.7);
    expect(peak(tiredSamples, "vrc.v_pp")).toBeGreaterThan(peak(fullSamples, "vrc.v_pp") * 0.85);
    // Garbage in → normal articulation (2 decimals: the replay starts from
    // the tail of the previous release, not from rest).
    lipTired.setArticulation(Number.NaN);
    expect(peak(play(lipTired, tired.manager, "papa"), "vrc.v_aa")).toBeCloseTo(peak(fullSamples, "vrc.v_aa"), 2);
  });

  it("falls back on the five VRM presets when the model has no visemes", () => {
    const { vrm, manager } = faceVrm(["Blink", "MouthSmile2"]);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    expect(lip.outputMode).toBe("presets");
    expect(manager.getExpression(rawName("vrc.v_aa"))).toBeNull();

    const samples = play(lip, manager, "bonjour Mika");
    expect(peak(samples, "oh")).toBeGreaterThan(0.3); // « on »
    expect(peak(samples, "ou")).toBeGreaterThan(0.3); // « ou »
    expect(peak(samples, "ih")).toBeGreaterThan(0.3); // « i »
    expect(peak(samples, "aa")).toBeGreaterThan(0.3); // « a »
    // Then the mouth comes back to rest.
    lip.stop();
    for (let k = 0; k < 120; k++) lip.update(STEP);
    for (const preset of PRESETS) expect(manager.getValue(preset)).toBeLessThan(0.01);
  });

  it("an incomplete viseme set is completed by the presets, viseme by viseme", () => {
    const { vrm, manager } = faceVrm(["vrc.v_aa", "vrc.v_oh"]);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    expect(lip.outputMode).toBe("mixed");
    const samples = play(lip, manager, "papa oui");
    expect(peak(samples, "vrc.v_aa")).toBeGreaterThan(0.6);
    expect(peak(samples, "aa")).toBeLessThan(0.35); // « a » goes to the viseme, only consonants spill here
    expect(peak(samples, "ou")).toBeGreaterThan(0.3); // « ou » has no viseme on this model
  });

  it("the estimate lasts as long as the voice's character budget", () => {
    const { vrm, manager } = faceVrm(VRC_VISEME_MORPHS);
    const lip = new LipSyncController();
    lip.setVRM(vrm);
    lip.startFromPlan([{ type: "speech", text: "bonjour tout le monde", start: 0 }], 60);
    lip.update(21 * 0.06 - 0.01);
    expect(lip.isSpeaking()).toBe(true);
    lip.update(0.02);
    expect(lip.isSpeaking()).toBe(false);
    expect(manager.getValue(rawName("vrc.v_oh"))).toBeGreaterThanOrEqual(0);
  });
});
