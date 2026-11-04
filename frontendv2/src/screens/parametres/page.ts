/**
 * Ce qu'une page de Paramètres (un onglet) donne à l'écran : ce qu'il faut lire avant de la montrer, ce qui peut
 * arriver après, son dessin, ses actions de barre de titre, ses gestes (`data-act`), l'enregistrement de ses
 * formulaires. L'écran (`index.ts`) s'occupe du reste : lire, redessiner, la barre d'enregistrement, les sous-onglets.
 */
import type { PaletteEntry } from "../../shell/palette";
import type { Shell } from "../../shell/shell";
import type { SaveBar } from "./form";
import type { Cached, CachedMap } from "./kit";
import type { FormValue } from "./words";

export interface Host {
  shell: Shell;
  bar: SaveBar;
  /** Le sous-onglet choisi d'une page (`fallback` tant qu'on n'en a pas choisi). */
  sub(page: string, fallback: string): string;
  setSub(page: string, value: string): void;
  /** Redessiner la page ouverte, depuis ce qui est lu. */
  repaint(): void;
  /** Relire ces ressources (ou toutes celles de la page), puis redessiner. */
  reload(...caches: (Cached<unknown> | CachedMap<unknown>)[]): Promise<void>;
  go(hash: string): void;
}

export interface Page {
  id: string;
  /** Ce qu'il faut avoir lu pour la dessiner. */
  needs(item: string | null): Cached<unknown>[];
  /** Ce qui l'enrichit quand ça arrive (elle se redessine alors). */
  extras?(item: string | null): Cached<unknown>[];
  view(item: string | null, host: Host): string;
  actions?(item: string | null, host: Host): string;
  act?(name: string, el: HTMLElement, item: string | null, host: Host): void;
  save?(form: HTMLElement, changes: Record<string, FormValue>, values: Record<string, FormValue>, item: string | null, host: Host): Promise<boolean>;
  /** Après chaque dessin (ses formulaires y sont déjà suivis). */
  after?(root: HTMLElement, item: string | null, host: Host): void;
  search?(): PaletteEntry[];
}
