import type { EmotionName } from "../../types";
import type { OverlayContext, ProceduralOverlay } from "./overlays/Overlay";

/**
 * Micro-expression layer — the face's equivalent of the body's idle
 * clips. Without it the face only blinks (~125ms every 3-5s) and holds
 * whatever emotion shape EmotionController set, which next to a
 * clip-animated body reads as a mask.
 *
 * It drives the model's ARKit perfect-sync shapes (BrowInnerUp,
 * MouthDimpleLeft, CheekSquintRight…), a set deliberately DISJOINT from
 * every other face writer:
 *   - EmotionController owns the emotion shapes (Smile1, Angry1, …)
 *   - LipSyncController owns aa / oh / ih / ee
 *   - BlinkController owns blink
 * so all four compose additively with no arbitration.
 *
 * Two contributions:
 *   1. continuous micro-drift — slow incommensurate noise per channel,
 *      with deliberately different rates left/right (a perfectly
 *      symmetric face is the strongest "it's a puppet" tell)
 *   2. per-emotion ARKit accents — brow/nose/cheek shading that makes an
 *      emotion read even before the main shape lands, and gives
 *      `neutral` (an EMPTY expression set on this model) something to do
 *
 * Amplitudes stay small on purpose: the custom emotion shapes already
 * bind some of the same morph targets, and VRM binds ACCUMULATE (`+=`),
 * so a big micro value would over-deform an already-expressive face.
 */

/** Cheap organic noise: three incommensurate sines. Never visibly repeats. */
function noise(t: number, seed: number): number {
  return (
    (Math.sin(t * 0.37 + seed * 1.7) +
      Math.sin(t * 0.91 + seed * 3.1) * 0.5 +
      Math.sin(t * 1.53 + seed * 5.3) * 0.25) /
    1.75
  );
}

export interface MicroChannel {
  name: string;
  /** Noise amplitude. */
  amp: number;
  /** Resting offset the noise modulates around (keeps it continuous
   * rather than clamping to 0 half the time). */
  bias: number;
  /** Noise time scale — L/R pairs differ so the face stays asymmetric. */
  rate: number;
  seed: number;
  /** Extra amplitude while speaking (people are more expressive). */
  talkBoost?: number;
}

export const MICRO_CHANNELS: MicroChannel[] = [
  { name: "BrowInnerUp", amp: 0.07, bias: 0.05, rate: 0.55, seed: 1, talkBoost: 1.5 },
  { name: "BrowOuterUpLeft", amp: 0.06, bias: 0.04, rate: 0.47, seed: 2, talkBoost: 1.4 },
  { name: "BrowOuterUpRight", amp: 0.06, bias: 0.04, rate: 0.53, seed: 3, talkBoost: 1.4 },
  { name: "EyeSquintLeft", amp: 0.05, bias: 0.03, rate: 0.61, seed: 4 },
  { name: "EyeSquintRight", amp: 0.05, bias: 0.03, rate: 0.67, seed: 5 },
  { name: "MouthDimpleLeft", amp: 0.06, bias: 0.05, rate: 0.42, seed: 6, talkBoost: 1.6 },
  { name: "MouthDimpleRight", amp: 0.06, bias: 0.05, rate: 0.38, seed: 7, talkBoost: 1.6 },
  { name: "MouthPressLeft", amp: 0.04, bias: 0.02, rate: 0.35, seed: 8 },
  { name: "MouthPressRight", amp: 0.04, bias: 0.02, rate: 0.31, seed: 9 },
  { name: "MouthShrugUpper", amp: 0.04, bias: 0.03, rate: 0.29, seed: 10 },
  { name: "CheekSquintLeft", amp: 0.035, bias: 0.02, rate: 0.44, seed: 11 },
  { name: "CheekSquintRight", amp: 0.035, bias: 0.02, rate: 0.48, seed: 12 },
];

/**
 * Per-emotion ARKit shading, scaled by intensity. Values are weights at
 * intensity 1.0 and are kept ≤ 0.45 so they read as shading on top of
 * the emotion shape, not as a second competing expression.
 */
export const EMOTION_ACCENT: Partial<Record<EmotionName, Record<string, number>>> = {
  // Positive — cheeks lift, outer brows rise, eyes squint into the smile
  happy: { MouthSmileLeft: 0.3, MouthSmileRight: 0.3, CheekSquintLeft: 0.25, CheekSquintRight: 0.25 },
  excited: { EyeWideLeft: 0.35, EyeWideRight: 0.35, BrowOuterUpLeft: 0.3, BrowOuterUpRight: 0.3, MouthSmileLeft: 0.25, MouthSmileRight: 0.25 },
  love: { CheekSquintLeft: 0.3, CheekSquintRight: 0.3, BrowInnerUp: 0.2, MouthSmileLeft: 0.2, MouthSmileRight: 0.2 },
  proud: { BrowOuterUpLeft: 0.2, BrowOuterUpRight: 0.2, MouthSmileLeft: 0.22, MouthSmileRight: 0.22 },
  grateful: { BrowInnerUp: 0.25, MouthSmileLeft: 0.25, MouthSmileRight: 0.25, CheekSquintLeft: 0.2, CheekSquintRight: 0.2 },
  playful: { MouthSmileLeft: 0.35, MouthSmileRight: 0.15, EyeSquintLeft: 0.2, BrowOuterUpRight: 0.25 },
  amused: { MouthSmileLeft: 0.3, MouthSmileRight: 0.3, CheekSquintLeft: 0.3, CheekSquintRight: 0.3, EyeSquintLeft: 0.25, EyeSquintRight: 0.25 },
  hopeful: { BrowInnerUp: 0.3, BrowOuterUpLeft: 0.2, BrowOuterUpRight: 0.2, MouthSmileLeft: 0.15, MouthSmileRight: 0.15 },
  relieved: { BrowInnerUp: 0.2, MouthShrugUpper: 0.2, EyeSquintLeft: 0.2, EyeSquintRight: 0.2 },

  // Negative — inner brow is the sadness muscle, brow-down is anger
  sad: { BrowInnerUp: 0.45, MouthFrownLeft: 0.3, MouthFrownRight: 0.3 },
  angry: { BrowDownLeft: 0.45, BrowDownRight: 0.45, NoseSneerLeft: 0.2, NoseSneerRight: 0.2, MouthPressLeft: 0.25, MouthPressRight: 0.25 },
  scared: { BrowInnerUp: 0.4, EyeWideLeft: 0.4, EyeWideRight: 0.4, MouthStretchLeft: 0.2, MouthStretchRight: 0.2 },
  disgusted: { NoseSneerLeft: 0.45, NoseSneerRight: 0.45, BrowDownLeft: 0.25, BrowDownRight: 0.25, MouthFrownLeft: 0.2, MouthFrownRight: 0.2 },
  frustrated: { BrowDownLeft: 0.35, BrowDownRight: 0.35, MouthPressLeft: 0.3, MouthPressRight: 0.3 },
  lonely: { BrowInnerUp: 0.35, MouthFrownLeft: 0.2, MouthFrownRight: 0.2, EyeSquintLeft: 0.15, EyeSquintRight: 0.15 },
  anxious: { BrowInnerUp: 0.4, MouthPressLeft: 0.3, MouthPressRight: 0.3, EyeWideLeft: 0.2, EyeWideRight: 0.2 },
  bored: { BrowDownLeft: 0.15, BrowDownRight: 0.15, EyeSquintLeft: 0.3, EyeSquintRight: 0.3, MouthShrugLower: 0.2 },
  jealous: { BrowDownLeft: 0.3, BrowDownRight: 0.2, MouthPressLeft: 0.3, EyeSquintRight: 0.2 },

  // Complex — asymmetry is what reads as "thinking" rather than "posing"
  surprised: { BrowInnerUp: 0.45, BrowOuterUpLeft: 0.4, BrowOuterUpRight: 0.4, EyeWideLeft: 0.45, EyeWideRight: 0.45 },
  thinking: { BrowDownLeft: 0.3, BrowInnerUp: 0.2, MouthPressLeft: 0.3, EyeSquintLeft: 0.2 },
  confused: { BrowInnerUp: 0.3, BrowDownRight: 0.3, BrowOuterUpLeft: 0.25, MouthShrugUpper: 0.2 },
  embarrassed: { BrowInnerUp: 0.3, EyeSquintLeft: 0.25, EyeSquintRight: 0.25, MouthShrugUpper: 0.25, CheekSquintLeft: 0.2, CheekSquintRight: 0.2 },
  nostalgic: { BrowInnerUp: 0.3, MouthSmileLeft: 0.15, MouthSmileRight: 0.15, EyeSquintLeft: 0.15, EyeSquintRight: 0.15 },
  dreamy: { BrowOuterUpLeft: 0.2, BrowOuterUpRight: 0.2, EyeSquintLeft: 0.25, EyeSquintRight: 0.25 },
  determined: { BrowDownLeft: 0.3, BrowDownRight: 0.3, MouthPressLeft: 0.25, MouthPressRight: 0.25 },
  mischievous: { MouthSmileLeft: 0.35, EyeSquintLeft: 0.3, BrowDownLeft: 0.2, BrowOuterUpRight: 0.25 },
  curious: { BrowInnerUp: 0.25, BrowOuterUpLeft: 0.3, EyeWideLeft: 0.2, EyeWideRight: 0.2 },
  melancholic: { BrowInnerUp: 0.4, MouthFrownLeft: 0.25, MouthFrownRight: 0.25, EyeSquintLeft: 0.15, EyeSquintRight: 0.15 },
};

/** How fast accents ease in/out when the emotion changes. */
const ACCENT_EASE = 2.5;
/** Micro amplitude retained while asleep — a sleeping face still breathes. */
const SLEEP_MICRO_SCALE = 0.18;

export class FaceIdleController implements ProceduralOverlay {
  private time = 0;
  /** Shapes this model actually exposes (resolved once). */
  private available: Set<string> | null = null;
  /** Eased accent weights, keyed by shape name. */
  private accent = new Map<string, number>();
  /** Names written last frame, so a dropped one gets zeroed exactly once. */
  private written = new Set<string>();

  private resolveAvailable(ctx: OverlayContext): Set<string> {
    const manager = ctx.vrm.expressionManager;
    const found = new Set<string>();
    if (!manager) return found;

    const candidates = new Set<string>(MICRO_CHANNELS.map((m) => m.name));
    for (const accents of Object.values(EMOTION_ACCENT)) {
      for (const name of Object.keys(accents)) candidates.add(name);
    }
    for (const name of candidates) {
      if (manager.getExpression(name) != null) found.add(name);
    }
    console.log(
      `FaceIdleController: ${found.size}/${candidates.size} micro-expression shapes available`
    );
    return found;
  }

  update(dt: number, ctx: OverlayContext): void {
    const manager = ctx.vrm.expressionManager;
    if (!manager) return;
    if (this.available === null) this.available = this.resolveAvailable(ctx);
    if (this.available.size === 0) return;

    this.time += dt;
    const asleep = ctx.sleepPhase !== "awake";

    // --- accents ease toward the current emotion's target ---
    const target = asleep ? undefined : EMOTION_ACCENT[ctx.emotion];
    const scale = 0.35 + ctx.intensity * 0.65;
    const ease = Math.min(1, dt * ACCENT_EASE);
    const names = new Set<string>([
      ...this.accent.keys(),
      ...(target ? Object.keys(target) : []),
    ]);
    for (const name of names) {
      const want = (target?.[name] ?? 0) * scale;
      const current = this.accent.get(name) ?? 0;
      const next = current + (want - current) * ease;
      if (want === 0 && next < 0.001) this.accent.delete(name);
      else this.accent.set(name, next);
    }

    // --- compose micro-drift + accent, one write per shape ---
    const values = new Map<string, number>();
    const microScale = asleep ? SLEEP_MICRO_SCALE : 1;

    for (const channel of MICRO_CHANNELS) {
      if (!this.available.has(channel.name)) continue;
      const boost =
        ctx.speaking && channel.talkBoost ? channel.talkBoost : 1;
      const v =
        (channel.bias +
          noise(this.time * channel.rate, channel.seed) * channel.amp * boost) *
        microScale;
      values.set(channel.name, v);
    }
    for (const [name, weight] of this.accent) {
      if (!this.available.has(name)) continue;
      values.set(name, (values.get(name) ?? 0) + weight);
    }

    for (const [name, value] of values) {
      manager.setValue(name, Math.max(0, Math.min(1, value)));
      this.written.add(name);
    }
    // A shape that stopped contributing must be released, or it would
    // stay stuck at its last weight forever.
    for (const name of this.written) {
      if (!values.has(name)) {
        manager.setValue(name, 0);
        this.written.delete(name);
      }
    }
  }
}
