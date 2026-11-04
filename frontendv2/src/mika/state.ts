/**
 * Ce que le client sait d'elle, plié trame après trame : `inner_state_update` (son corps, ce qu'elle fait,
 * ce qui lui trotte dans la tête, ce qu'elle a promis), `emotion_update` et l'émotion des `speech`. Pur, sans
 * DOM ; du JSON jamais cru sur parole (`backendv2/docs/protocole-chat.md` § 4).
 *
 * La règle des sections, celle de l'application Android (`InnerStateReducer`) : les clés de base (sommeil,
 * énergie, lieu, occupation, rythme, besoins, estime) remplacent quand elles sont là et lisibles ; les
 * sections personnelles (pensées, promesses, journal, rêve, projets) restent telles quelles quand la trame
 * ne parle de personne (`person_scope: false`), sinon elles sont remplacées — une section absente s'efface.
 * Une section illisible garde toujours sa valeur d'avant.
 */
import { isEmotionName, resolveSleepPhase, type EmotionBlend, type SleepPhase } from "@web/types";

export interface Activity {
  name: string;
  label: string;
  /** Millisecondes ; `null` : jusqu'à ce qu'elle s'arrête. */
  until: number | null;
}

export interface Rumination {
  summary: string;
  intensity: number;
  emotion: string;
}

export interface Mood {
  emotion: string;
  intensity: number;
  blend: EmotionBlend;
}

export interface MikaState {
  sleepPhase: SleepPhase;
  energy: number | null;
  place: string | null;
  activity: Activity | null;
  /** `morning` | `afternoon` | `evening` | `night`, et l'heure locale. */
  circadian: { phase: string; hour: number } | null;
  /** La tension de chaque besoin, 0…1. */
  drives: Record<string, number>;
  estime: number | null;
  ruminations: Rumination[];
  commitments: string[];
  journal: { title: string; narrative: string } | null;
  dream: { content: string; kind: string; vividness: number; recalled: boolean } | null;
  projects: Array<{ title: string; status: string }>;
  mood: Mood | null;
}

export const EMPTY_MIKA: MikaState = {
  sleepPhase: "awake",
  energy: null,
  place: null,
  activity: null,
  circadian: null,
  drives: {},
  estime: null,
  ruminations: [],
  commitments: [],
  journal: null,
  dream: null,
  projects: [],
  mood: null,
};

const BAD = Symbol("illisible");
type Read<T> = T | typeof BAD;

function isObject(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === "object" && !Array.isArray(v);
}

function unit(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? Math.min(1, Math.max(0, v)) : null;
}

function str(v: unknown, max = 2000): string {
  return typeof v === "string" ? v.slice(0, max) : "";
}

function readActivity(v: unknown): Read<Activity | null> {
  if (v === null) return null;
  if (!isObject(v)) return BAD;
  const name = str(v.name, 64);
  const label = str(v.label, 120).trim();
  if (!name && !label) return BAD;
  const until = typeof v.until === "number" && Number.isFinite(v.until) && v.until > 0 ? v.until : null;
  return { name, label, until };
}

function readRuminations(v: unknown): Read<Rumination[]> {
  if (!Array.isArray(v)) return BAD;
  const out: Rumination[] = [];
  for (const item of v) {
    if (!isObject(item)) continue;
    const summary = str(item.summary, 400).trim();
    if (!summary) continue;
    out.push({ summary, intensity: unit(item.intensity) ?? 0, emotion: str(item.emotion, 32) });
  }
  return out.sort((a, b) => b.intensity - a.intensity);
}

function readStrings(v: unknown): Read<string[]> {
  if (!Array.isArray(v)) return BAD;
  return v.filter((s): s is string => typeof s === "string" && s.trim() !== "").map((s) => s.trim().slice(0, 400));
}

function readJournal(v: unknown): Read<MikaState["journal"]> {
  if (v === undefined || v === null) return null;
  if (!isObject(v)) return BAD;
  const narrative = str(v.narrative, 4000).trim();
  if (!narrative) return null;
  return { title: str(v.title, 120).trim(), narrative };
}

function readDream(v: unknown): Read<MikaState["dream"]> {
  if (v === undefined || v === null) return null;
  if (!isObject(v)) return BAD;
  const content = str(v.content, 2000).trim();
  if (!content) return null;
  return { content, kind: str(v.dream_type, 32), vividness: unit(v.vividness) ?? 0, recalled: v.recalled === true };
}

function readProjects(v: unknown): Read<MikaState["projects"]> {
  if (v === undefined) return [];
  if (!Array.isArray(v)) return BAD;
  return v
    .filter(isObject)
    .map((p) => ({ title: str(p.title, 200).trim(), status: str(p.status, 40) }))
    .filter((p) => p.title);
}

function readDrives(v: unknown): Read<Record<string, number>> {
  if (!isObject(v)) return BAD;
  const out: Record<string, number> = {};
  for (const [kind, drive] of Object.entries(v)) {
    const tension = isObject(drive) ? unit(drive.tension) : null;
    if (tension !== null) out[kind] = tension;
  }
  return out;
}

/** Une section : sa valeur lue, ou celle d'avant si elle est illisible. */
function keep<T>(read: Read<T>, previous: T): T {
  return read === BAD ? previous : read;
}

/** Une trame `inner_state_update` (son `inner_state`), pliée dans ce qu'on savait. */
export function withInnerState(prev: MikaState, raw: unknown): MikaState {
  if (!isObject(raw)) return prev;
  const next: MikaState = { ...prev };
  if (typeof raw.sleep_phase === "string") next.sleepPhase = resolveSleepPhase(raw.sleep_phase);
  const energy = unit(raw.energy);
  if (energy !== null) next.energy = energy;
  if (typeof raw.place === "string") next.place = raw.place;
  // l'occupation : un `null` explicite dit qu'elle ne fait plus rien ; une trame sans la clé n'y touche pas
  if ("activity" in raw) next.activity = keep(readActivity(raw.activity), prev.activity);
  if (isObject(raw.circadian) && typeof raw.circadian.phase === "string") {
    const hour = typeof raw.circadian.hour === "number" && Number.isFinite(raw.circadian.hour) ? raw.circadian.hour : NaN;
    next.circadian = { phase: raw.circadian.phase, hour };
  }
  if ("drives" in raw) next.drives = keep(readDrives(raw.drives), prev.drives);
  const estime = unit(raw.estime);
  if (estime !== null) next.estime = estime;
  if (raw.person_scope === false) return next;
  next.ruminations = keep(raw.ruminations === undefined ? [] : readRuminations(raw.ruminations), prev.ruminations);
  next.commitments = keep(
    raw.pending_commitments === undefined ? [] : readStrings(raw.pending_commitments),
    prev.commitments,
  );
  next.journal = keep(readJournal(raw.today_journal), prev.journal);
  next.dream = keep(readDream(raw.last_dream), prev.dream);
  next.projects = keep(readProjects(raw.projects), prev.projects);
  return next;
}

/** Ce qu'une trame dit de son visage (`emotion_update`, ou l'émotion d'une `speech`). */
export interface MoodFrame {
  emotion?: unknown;
  emotion_intensity?: unknown;
  emotion_blend?: unknown;
  source?: unknown;
}

/**
 * Son humeur du moment. Une émotion inconnue ne dit rien (l'humeur reste) ; un texte de repli
 * (`source: "error"`) non plus : ce n'est pas elle qui parle, c'est la machine.
 */
export function withMood(prev: MikaState, frame: MoodFrame): MikaState {
  if (frame.source === "error") return prev;
  const emotion = typeof frame.emotion === "string" ? frame.emotion.trim().toLowerCase() : "";
  if (!isEmotionName(emotion)) return prev;
  const blend: EmotionBlend = [];
  if (Array.isArray(frame.emotion_blend)) {
    for (const part of frame.emotion_blend) {
      if (!isObject(part) || !isEmotionName(part.emotion)) continue;
      const weight = unit(part.weight);
      if (weight !== null) blend.push({ emotion: part.emotion, weight });
    }
  }
  return { ...prev, mood: { emotion, intensity: unit(frame.emotion_intensity) ?? 0, blend } };
}

export function isAsleep(state: MikaState): boolean {
  return state.sleepPhase !== "awake";
}
