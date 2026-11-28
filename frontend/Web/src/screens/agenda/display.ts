/**
 * Ce que l'Agenda montre, retenu par ce navigateur : les agendas décochés (l'affichage seulement — les masquer dans
 * Paramètres › Agendas coupe aussi Mika, recommandation 8 de l'ADR 0309) et la dernière vue choisie. L'écran Agenda et
 * Paramètres › Agendas (« Dans l'Agenda » d'un agenda qu'on te partage, de celui de Mika) lisent la même copie.
 */
import { read, write } from "../../shared/storage";
import { VIEWS, type View } from "./dates";

const OFF_KEY = "mika2_agenda_decoches";
const VIEW_KEY = "mika2_agenda_vue";

let off: Set<string> | null = null;
const listeners = new Set<() => void>();

function load(): Set<string> {
  if (off) return off;
  try {
    const got = JSON.parse(read(() => localStorage, OFF_KEY) ?? "[]") as unknown;
    off = new Set(Array.isArray(got) ? got.filter((x): x is string => typeof x === "string") : []);
  } catch {
    off = new Set();
  }
  return off;
}

/** Les agendas décochés. */
export function hiddenHere(): ReadonlySet<string> {
  return load();
}

/** Cocher ou décocher un agenda dans la vue (ou tous ceux-là d'un coup : `only`). */
export function setShown(key: string, on: boolean): void {
  const set = load();
  if (on) set.delete(key);
  else set.add(key);
  save();
}

/** N'afficher que celui-ci parmi `all`. */
export function showOnly(key: string, all: readonly string[]): void {
  off = new Set(all.filter((k) => k !== key));
  save();
}

function save(): void {
  write(() => localStorage, OFF_KEY, JSON.stringify([...load()]));
  for (const fn of [...listeners]) fn();
}

/** Prévenu quand l'affichage change (un autre écran a coché ou décoché). */
export function onShownChange(fn: () => void): void {
  listeners.add(fn);
}

export function savedView(fallback: View): View {
  const got = read(() => localStorage, VIEW_KEY);
  return VIEWS.some(([k]) => k === got) ? (got as View) : fallback;
}

export function saveView(view: View): void {
  write(() => localStorage, VIEW_KEY, view);
}
