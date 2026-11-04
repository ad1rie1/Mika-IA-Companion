/**
 * Le thème : clair, sombre, ou celui du système. Choisi une fois avant le premier rendu (index.html, avec la
 * même clé), puis ici : le bouton de la barre du haut fait le tour des trois, le menu du compte les propose.
 */

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_KEY = "mika-theme";
export const THEME_LABELS: Record<ThemeChoice, string> = { system: "Système", light: "Clair", dark: "Sombre" };
const ORDER: readonly ThemeChoice[] = ["system", "light", "dark"];

export function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

export function nextTheme(current: ThemeChoice): ThemeChoice {
  return ORDER[(ORDER.indexOf(current) + 1) % ORDER.length];
}

export function currentChoice(): ThemeChoice {
  const raw = document.documentElement.dataset.themeChoice;
  return isThemeChoice(raw) ? raw : "system";
}

export function isDark(): boolean {
  return document.documentElement.dataset.theme === "dark";
}

const listeners: Array<(dark: boolean) => void> = [];

/** Suivre le thème (l'aura de Mika en dépend). */
export function onTheme(fn: (dark: boolean) => void): void {
  listeners.push(fn);
}

export function applyTheme(choice: ThemeChoice, remember = true): void {
  const dark = choice === "dark" || (choice === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  const root = document.documentElement;
  root.dataset.theme = dark ? "dark" : "light";
  root.dataset.themeChoice = choice;
  if (remember) {
    try {
      localStorage.setItem(THEME_KEY, choice);
    } catch {
      // stockage fermé : le choix vaut pour cette page
    }
  }
  for (const fn of listeners) fn(dark);
}

/** Le système change de thème : on le suit tant que le choix est « Système ». */
export function followSystem(): void {
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (currentChoice() === "system") applyTheme("system", false);
  });
}
