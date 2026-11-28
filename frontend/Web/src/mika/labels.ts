/**
 * Les mots de son état, en français. Les noms restent anglais sur le fil ; on ne les traduit qu'ici, comme
 * l'application Android (`data/mind/MindLabels.kt`) ; les 29 émotions sont celles de `types/emotions.ts`.
 */
import { EMOTION_META, isEmotionName, type EmotionCategory } from "../types";

/** `curious` → « Curieuse » ; « Réfléchit… » avec sa vraie ellipse. Un nom hors des 29 est rendu tel quel. */
export function emotionLabel(name: string): string {
  const key = String(name || "").trim().toLowerCase();
  const label = isEmotionName(key) ? EMOTION_META[key].label : String(name || "");
  return label.replace(/\.\.\.$/, "…");
}

/** La forme de la ligne d'état : « curieuse », « excitée », « s'ennuie », « pleine d'espoir ». */
export function emotionLower(name: string): string {
  const key = String(name || "").trim().toLowerCase();
  if (!isEmotionName(key)) return String(name || "");
  return EMOTION_META[key].label.replace(/\.\.\.$/, "").replace(/ !$/, "").trim().toLowerCase();
}

export function emotionCategory(name: string): EmotionCategory | null {
  const key = String(name || "").trim().toLowerCase();
  return isEmotionName(key) ? EMOTION_META[key].category : null;
}

/** Ses besoins, avec les mots de la console. */
const DRIVES: Record<string, string> = { social: "Compagnie", expression: "S'exprimer", curiosity: "Apprendre" };

export function driveLabel(kind: string): string {
  return DRIVES[kind] ?? kind;
}

/** Les sortes de rêve (`contracts/self_.py::DREAM_KINDS`). */
const DREAMS: Record<string, string> = {
  associative: "Un rêve associatif",
  nightmare: "Un cauchemar léger",
  pleasant: "Un rêve doux",
  mundane: "Un rêve banal",
  melancholic: "Un rêve mélancolique",
};

export function dreamLabel(kind: string): string {
  return DREAMS[kind] ?? "Un rêve";
}

/** Le statut d'un de ses projets, tel que le serveur l'envoie (`app/domains/projects/port.py` : `active`, `paused`). */
const PROJECT_STATUSES: ReadonlyMap<string, string> = new Map([
  ["active", "en cours"],
  ["paused", "en pause"],
]);

/** « en cours », « en pause » ; un statut que ce client ne connaît pas ne se montre pas (jamais la clé anglaise). */
export function projectStatusLabel(status: string | null | undefined): string | null {
  return PROJECT_STATUSES.get(String(status ?? "").trim().toLowerCase()) ?? null;
}

/** Le moment de la journée. */
const MOMENTS: Record<string, string> = {
  morning: "le matin",
  afternoon: "l'après-midi",
  evening: "le soir",
  night: "la nuit",
};

export function momentLabel(phase: string | null | undefined): string | null {
  return (phase && MOMENTS[phase]) || null;
}

/** Le sommeil, en mots. */
export function sleepLabel(phase: string): string {
  switch (phase) {
    case "light_sleep":
      return "dort";
    case "rem":
      return "dort · rêve";
    case "deep_sleep":
      return "dort profondément";
    default:
      return "éveillée";
  }
}
