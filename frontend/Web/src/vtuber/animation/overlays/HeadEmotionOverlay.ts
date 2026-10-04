import type { EmotionName } from "../../../types";
import type { OverlayContext, ProceduralOverlay } from "./Overlay";

// Per-emotion head pose offsets (radians), composed ON TOP of whatever
// the clip does with the head. Positive pitch = look down, negative =
// look up. Positive roll = tilt right. Positive yaw = turn right.
// (Extracted from the old EmotionController, which wrote these as
// absolute Euler values — impossible next to a clip mixer.)
interface HeadPose {
  pitch: number;
  roll: number;
  yaw: number;
}

const EMOTION_HEAD_POSE: Partial<Record<EmotionName, HeadPose>> = {
  // Curiosity + thinking → classic head-tilt to one side
  curious:     { pitch: -0.04, roll:  0.10, yaw: 0 },
  thinking:    { pitch: -0.02, roll:  0.08, yaw: 0.03 },
  confused:    { pitch:  0.0,  roll: -0.10, yaw: 0 },
  // Embarrassment → head turns down-away
  embarrassed: { pitch:  0.08, roll: -0.05, yaw: -0.05 },
  // Proud → chin up slightly
  proud:       { pitch: -0.06, roll:  0.0,  yaw: 0 },
  determined:  { pitch: -0.03, roll:  0.0,  yaw: 0 },
  // Sad family → head down
  sad:         { pitch:  0.08, roll:  0.0,  yaw: 0 },
  lonely:      { pitch:  0.06, roll:  0.0,  yaw: 0 },
  melancholic: { pitch:  0.06, roll:  0.03, yaw: 0 },
  // Surprised → head back a touch
  surprised:   { pitch: -0.05, roll:  0.0,  yaw: 0 },
  scared:      { pitch: -0.03, roll:  0.04, yaw: 0 },
  // Dreamy / love → soft tilt
  dreamy:      { pitch: -0.02, roll:  0.05, yaw: 0 },
  love:        { pitch:  0.0,  roll:  0.04, yaw: 0 },
  // Mischievous → slight lean + side glance complement
  mischievous: { pitch: -0.02, roll:  0.06, yaw: 0.05 },
  // Everything else stays at rest
};

const EASE_SPEED = 2.0; // slower than expressions — reads natural

/** Additive emotional head pose. Suppressed (eased back to zero, never
 * frozen) while asleep so it can't stack with the sleep doze tilt. */
export class HeadEmotionOverlay implements ProceduralOverlay {
  private pitch = 0;
  private roll = 0;
  private yaw = 0;

  update(dt: number, ctx: OverlayContext): void {
    let tp = 0;
    let tr = 0;
    let ty = 0;
    if (ctx.sleepPhase === "awake") {
      const pose = EMOTION_HEAD_POSE[ctx.emotion];
      if (pose) {
        const scale = 0.3 + ctx.intensity * 0.7;
        tp = pose.pitch * scale;
        tr = pose.roll * scale;
        ty = pose.yaw * scale;
      }
    }
    const ease = Math.min(1, dt * EASE_SPEED);
    this.pitch += (tp - this.pitch) * ease;
    this.roll += (tr - this.roll) * ease;
    this.yaw += (ty - this.yaw) * ease;

    ctx.addRotation("head", this.pitch, this.yaw, this.roll);
  }
}
