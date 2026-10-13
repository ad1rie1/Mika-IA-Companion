import type { Intent, Step } from "./protocol.g";

/** Où en est une action à un instant donné : quel pas, et quelle part de ce pas. */
export interface IntentPoint {
  /** Index du pas en cours ; `steps.length` quand tout est joué. */
  step: number;
  /** Part du pas en cours, de 0 à 1. */
  fraction: number;
  /** Secondes restantes dans le pas en cours. */
  remainingS: number;
}

/**
 * Le calendrier nominal d'une action : chaque pas a sa durée
 * (`duration_us`), le premier commence à `started`. Un écran qui s'ouvre en
 * route place l'acteur sur son trajet par ce calendrier. (Le jumeau de
 * `Mika.World.Model.IntentTimeline`.)
 */
export function intentAt(intent: Intent, kernelNowUs: number): IntentPoint {
  let t = Math.max(0, kernelNowUs - intent.started);
  const steps = intent.steps;
  for (let i = 0; i < steps.length; i++) {
    const d = steps[i].duration_us;
    if (t < d) return { step: i, fraction: d <= 0 ? 1 : t / d, remainingS: (d - t) / 1e6 };
    t -= d;
  }
  return { step: steps.length, fraction: 1, remainingS: 0 };
}

export function intentDone(intent: Intent, point: IntentPoint): boolean {
  return point.step >= intent.steps.length;
}

/** L'instant (noyau) où commence le pas `index`. */
export function stepStart(intent: Intent, index: number): number {
  let t = intent.started;
  for (let i = 0; i < index && i < intent.steps.length; i++) t += intent.steps[i].duration_us;
  return t;
}

/** Le dernier lieu visé par les pas de marche. */
export function destination(intent: Intent): { room: string | null; place: string | null } {
  let room: string | null = null;
  let place: string | null = null;
  for (const s of intent.steps) {
    if (s.kind === "walk") {
      room = s.to_room ?? null;
      place = s.to_place ?? null;
    }
  }
  return { room, place };
}

export function walks(intent: Intent): Step[] {
  return intent.steps.filter((s) => s.kind === "walk");
}
