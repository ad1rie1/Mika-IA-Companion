/**
 * La palette Ctrl K : « Rechercher partout ». Les routes de chaque écran et de ses onglets (« Aller à »),
 * puis ce que chaque écran sait chercher (les derniers messages du chat, les fils de travail). La part
 * pure : quelles entrées montrer pour ce qui est tapé.
 */
import { norm } from "./dom";
import type { IconName } from "./icons";

export interface PaletteEntry {
  group: string;
  title: string;
  sub?: string;
  side?: string;
  icon?: IconName;
  /** Une route (`#mail/contacts`), ou une action. */
  route?: string;
  action?: () => void;
}

export const GO_TO = "Aller à";
const MAX_RESULTS = 40;
/** Sans rien de tapé : les écrans, puis quelques entrées des écrans. */
const IDLE_EXTRA = 6;

export function filterPalette(entries: readonly PaletteEntry[], query: string): PaletteEntry[] {
  const q = norm(query.trim());
  if (!q) {
    const screens = entries.filter((e) => e.group === GO_TO && !e.title.includes("›"));
    const extra = entries.filter((e) => e.group !== GO_TO).slice(0, IDLE_EXTRA);
    return [...screens, ...extra].slice(0, MAX_RESULTS);
  }
  return entries
    .filter((e) => norm(`${e.title} ${e.sub ?? ""} ${e.group}`).includes(q))
    .slice(0, MAX_RESULTS);
}
