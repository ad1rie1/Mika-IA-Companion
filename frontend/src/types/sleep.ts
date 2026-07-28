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
