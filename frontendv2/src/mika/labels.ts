/**
 * Les mots de son état, en français. Les noms restent anglais sur le fil ; on ne les traduit qu'ici, comme
 * l'application Android (`data/mind/MindLabels.kt`) et le client web (`types/emotions.ts`, dont les 29
 * émotions sont reprises telles quelles).
 */
import { EMOTION_META, isEmotionName, type EmotionCategory } from "@web/types";

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

/** Où elle est dans sa chambre (`contracts/place.py`). */
const PLACES: Record<string, string> = {
  center: "au milieu de sa chambre",
  window: "à la fenêtre",
  desk: "à son bureau",
  bed: "sur son lit",
  bookshelf: "près de sa bibliothèque",
  door: "près de la porte",
};

export function placeLabel(place: string | null | undefined): string | null {
  return (place && PLACES[place]) || null;
}

/** Ce qu'elle fait, conjugué pour la ligne d'état (les occupations de `faculties/world/chambre.json`). */
const ACTIVITIES: Record<string, string> = {
  draw: "dessine",
  work: "travaille",
  browse_books: "feuillette un livre",
  water_plant: "arrose sa plante",
  look_outside: "regarde dehors",
};

/**
 * « dessine » ; une occupation que ce client ne connaît pas (un objet ajouté à sa chambre) se dit avec le
 * libellé du serveur, « en train de jongler » ; sans libellé, rien.
 */
export function activityLabel(name: string | null | undefined, label: string | null | undefined): string | null {
  const known = name ? ACTIVITIES[name] : undefined;
  if (known) return known;
  const raw = String(label || "").trim();
  if (!raw) return null;
  const of = /^[aeiouyàâéèêëîïôöùûü]/i.test(raw) ? "d'" : "de ";
  return `en train ${of}${raw}`;
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

/** Le statut d'un de ses projets, tel que le serveur l'envoie (`app/mindport.py` : `active`, `paused`). */
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
