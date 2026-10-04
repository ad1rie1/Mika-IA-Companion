// Single source of truth for sleep phases, matching backend
// memory/sleep.py::SleepPhase. Never re-declare SleepPhase elsewhere.
export const SLEEP_PHASES = [
  "awake",
  "light_sleep",
  "rem",
  "deep_sleep",
] as const;

export type SleepPhase = (typeof SLEEP_PHASES)[number];

const PHASE_SET: ReadonlySet<string> = new Set(SLEEP_PHASES);

export function isSleepPhase(value: unknown): value is SleepPhase {
  return typeof value === "string" && PHASE_SET.has(value);
}

/**
 * Résout une phase de sommeil venue du réseau (payload `inner_state`).
 *
 * Le compilateur croit `InnerState["sleep_phase"]` toujours valide, mais
 * c'est du JSON venu du backend, jamais vérifié à l'exécution — exactement
 * le défaut qu'`isEmotionName` corrige pour l'émotion. Une valeur inconnue
 * atteignait `SLEEP_PHASE_META[resolved]`, `undefined`, puis `.icon` : une
 * exception au milieu du handler `speech` qui coupait aussi le TTS et le
 * lip-sync du même tour. Vit ici, sans DOM, parce que le panneau et le
 * `SpeechPresenter` gardent tous deux leur entrée avec.
 */
export function resolveSleepPhase(value: unknown): SleepPhase {
  return isSleepPhase(value) ? value : "awake";
}
