/**
 * Ce que montrent la pastille du haut, sa colonne du chat et son visage, tiré de ce qu'on sait d'elle. Pur.
 *
 * La ligne d'état suit l'application Android (`StatusLine.kt`), dans la forme de la maquette : un problème
 * de lien d'abord (on ne dit pas « éveillée » de quelqu'un qu'on ne joint pas), puis son sommeil, puis ce
 * qu'elle fait et où (« travaille à son bureau »), puis son humeur quand elle est assez marquée.
 */
import type { EmotionCategory } from "@web/types";
import {
  activityLabel,
  emotionCategory,
  emotionLabel,
  emotionLower,
  placeLabel,
  sleepLabel,
} from "./labels";
import { isAsleep, type MikaState, type Mood } from "./state";

/** L'état de la connexion, tel que la ligne d'état le dit. */
export type LinkState = "connecting" | "connected" | "offline" | "unauthorized";

/** En dessous, l'émotion n'est pas assez marquée pour être dite, ni pour changer son portrait. */
export const MOOD_MIN_INTENSITY = 0.25;

export interface StatusLine {
  /** « éveillée · travaille à son bureau · curieuse » : sa colonne et l'infobulle. */
  full: string;
  /** La pastille : sans « éveillée », qui va de soi. */
  short: string;
  /** `eveillee` | `ecrit` | `dort` : la pastille et sa pastille verte. */
  state: "eveillee" | "ecrit" | "dort";
}

const LINK_PROBLEMS: Partial<Record<LinkState, string>> = {
  connecting: "connexion…",
  offline: "hors ligne",
  unauthorized: "session expirée",
};

export function moodWord(mood: Mood | null): string | null {
  if (!mood || mood.emotion === "neutral" || mood.intensity < MOOD_MIN_INTENSITY) return null;
  return emotionLower(mood.emotion);
}

/** Ce qu'elle fait et où : « travaille à son bureau », « à la fenêtre », ou rien. */
export function doingWords(state: MikaState, nowMs: number): string | null {
  const a = state.activity;
  const live = a && (a.until === null || a.until > nowMs) ? a : null;
  const parts = [live ? activityLabel(live.name, live.label) : null, placeLabel(state.place)].filter(
    (p): p is string => !!p,
  );
  return parts.length ? parts.join(" ") : null;
}

export function statusLine(
  state: MikaState,
  opts: { link: LinkState; typing: boolean; nowMs: number },
): StatusLine {
  const problem = LINK_PROBLEMS[opts.link];
  if (problem) return { full: problem, short: problem, state: "eveillee" };
  if (isAsleep(state)) {
    const words = sleepLabel(state.sleepPhase);
    return { full: words, short: words, state: "dort" };
  }
  const doing = opts.typing ? "en train d'écrire…" : doingWords(state, opts.nowMs);
  const mood = moodWord(state.mood);
  const rest = [doing, mood].filter((p): p is string => !!p);
  return {
    full: ["éveillée", ...rest].join(" · "),
    short: rest.length ? rest.join(" · ") : "éveillée",
    state: opts.typing ? "ecrit" : "eveillee",
  };
}

// ── Les facettes de son humeur ──────────────────────────────────────

export interface Facet {
  emotion: string;
  label: string;
  /** 0…1. */
  value: number;
}

/**
 * Les facettes de son humeur (« Curieuse 62 % »), de la plus forte à la plus faible : le mélange que le
 * serveur envoie (`emotion_blend`, des émotions 0–1 jugées par le modèle), ou l'émotion seule quand il n'y a
 * pas de mélange. Une émotion redite ne compte qu'une fois, à sa plus forte valeur.
 */
export function facetsOf(mood: Mood | null, max = 4): Facet[] {
  if (!mood) return [];
  const best = new Map<string, number>();
  for (const part of mood.blend) {
    if (part.weight <= 0) continue;
    best.set(part.emotion, Math.max(best.get(part.emotion) ?? 0, part.weight));
  }
  if (!best.size && mood.intensity > 0) best.set(mood.emotion, mood.intensity);
  return [...best.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, max)
    .map(([emotion, value]) => ({ emotion, label: emotionLabel(emotion), value }));
}

export function percent(value: number): string {
  return `${Math.round(Math.min(1, Math.max(0, value)) * 100)} %`;
}

// ── Son visage : quel portrait, quelle aura ─────────────────────────

export type AuraName = "chaude" | "froide" | "crepuscule" | "nuit" | "neutre";

/** L'aura de son coin, comme sur Android (`AvatarBackdrop.kt`) : [clair, sombre]. */
export const AURAS: Record<AuraName, readonly [string, string]> = {
  chaude: ["#ffd3cc", "#5e2f45"],
  froide: ["#c9d7f4", "#1f3459"],
  crepuscule: ["#ddd1f8", "#392e68"],
  nuit: ["#c2c8e6", "#0d1330"],
  neutre: ["#e1e0ff", "#3b3ba6"],
};

const CATEGORY_AURA: Record<EmotionCategory, AuraName> = {
  positive: "chaude",
  negative: "froide",
  complex: "crepuscule",
  neutral: "neutre",
};

/** L'énergie sous laquelle elle a l'air fatiguée, et l'émotion qui se voit malgré tout. */
export const TIRED_ENERGY = 0.3;
export const TIRED_OVERRIDE = 0.5;

export interface Face {
  /** La clé de son portrait (`frontend/Android/app/src/main/assets/avatar/<clé>.webp`). */
  portrait: string;
  aura: AuraName;
  asleep: boolean;
}

/**
 * Quel visage montrer (`AvatarDirector.kt`, sans les retrouvailles) : endormie, « sleep » ; elle écrit,
 * « thinking » ; son humeur si elle est assez marquée (sauf fatiguée, à moins qu'elle soit forte) ;
 * « tired » quand l'énergie est basse ; « neutral » au repos. Un portrait absent retombe sur « neutral ».
 */
export function faceOf(state: MikaState, typing: boolean, available: ReadonlySet<string> | null): Face {
  const pick = (key: string) => (!available || available.has(key) ? key : "neutral");
  if (isAsleep(state)) return { portrait: pick("sleep"), aura: "nuit", asleep: true };
  if (typing) return { portrait: pick("thinking"), aura: "crepuscule", asleep: false };
  const mood = state.mood;
  const tired = state.energy !== null && state.energy < TIRED_ENERGY;
  const category = mood ? emotionCategory(mood.emotion) : null;
  const strong = !!mood && category !== null && mood.intensity >= MOOD_MIN_INTENSITY;
  if (strong && !(tired && mood.intensity < TIRED_OVERRIDE)) {
    return { portrait: pick(mood.emotion), aura: CATEGORY_AURA[category], asleep: false };
  }
  if (tired) return { portrait: pick("tired"), aura: "neutre", asleep: false };
  return { portrait: "neutral", aura: "neutre", asleep: false };
}
