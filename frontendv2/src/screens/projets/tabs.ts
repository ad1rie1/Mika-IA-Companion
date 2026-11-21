/**
 * Les onglets d'une fiche qui s'écrivent à part : **Code** et **Documentation** (lot S4b). Chacun se branche ici, sur
 * le socle de l'écran : il rend le corps de son onglet depuis la fiche et le reste de l'adresse, et déclare ses gestes
 * et ses formulaires, que l'écran délègue comme les siens (`data-p2="<nom>"`, `data-p2-form="<nom>"`).
 *
 *   registerTab("code", { render: (sheet, rest, host) => codeView(…), acts: { merge: … }, forms: { pull: … } });
 *
 * `host` donne ce que le socle partage : les lectures gardées (`read`), l'envoi d'un geste avec son refus dit sur place
 * (`send`), les fenêtres (`ask`, `confirm`), le panneau qui s'ouvre (`drawer`), l'état de l'écran (`ui`) et de quoi
 * redessiner (`repaint`). Les morceaux à réutiliser sont dans `parts.ts` (les trois zones, les pastilles, les
 * formulaires, un texte venu d'ailleurs), `tones.ts`, `time.ts`, `md.ts`.
 */
import type { EntryDetail, GestureDone, Sheet } from "../../api/projects";
import type { Cached } from "../../shared/kit";
import type { GestureRequest, Values } from "./gestures";
import type { DrawerOpts } from "./parts";
import type { UiState } from "./state";
import type { Ctx, Got } from "./views/todo";

export interface TabHost {
  ui: UiState;
  /** Ce que les vues reçoivent : maintenant, téléphone ou non, l'état, le nom de la personne. */
  ctx(): Ctx;
  /** Une lecture gardée : la lance si besoin, et redessine quand elle arrive. */
  read<T>(cached: Cached<T>): Got<T>;
  /** Un élément du registre (`item` : `#n` pour un ticket), lu et gardé par le socle : ses gestes (`data-p2="settle"`) le retrouvent. */
  readElement(project: number, list: string, item: string): Got<EntryDetail>;
  /** Un geste : la requête part ; refusée, ses mots se disent à `where` (`refusalAt(ui, where)`), sinon tout se relit. */
  send(project: number, request: GestureRequest, where: string, done?: (r: GestureDone) => void): Promise<boolean>;
  /** Une question dans une fenêtre (une raison, un mot) : le texte saisi, ou `null` si on renonce. */
  ask(o: { title: string; label: string; ok: string; required?: boolean; danger?: boolean }): Promise<string | null>;
  confirm(o: { title: string; text: string; ok: string; danger?: boolean }): Promise<boolean>;
  /** Un panneau qui s'ouvre à droite ; `make` est rappelé pour le redessiner (un refus s'y dit). */
  drawer(make: () => DrawerOpts): void;
  closeDrawer(): void;
  repaint(): void;
  go(hash: string): void;
}

export type Act = (data: DOMStringMap, el: HTMLElement, host: TabHost) => void | Promise<void>;
/** La suite d'un formulaire : ses valeurs par nom, ses `data-…`, lui-même. */
export type FormAct = (values: Values, data: DOMStringMap, form: HTMLFormElement, host: TabHost) => void | Promise<void>;

export interface TabView {
  /** Le corps de l'onglet (du HTML) : ce qui va sous les onglets de la fiche. */
  render(sheet: Sheet, rest: string[], host: TabHost): string;
  /** Après chaque dessin : poser un éditeur, mesurer, faire défiler. */
  after?(body: HTMLElement, sheet: Sheet, rest: string[], host: TabHost): void;
  acts?: Record<string, Act>;
  forms?: Record<string, FormAct>;
  /** Après un geste de l'écran : ce que l'onglet garde et qu'un geste d'ailleurs a pu changer (un accord décidé) se relit. */
  invalidate?(): void;
}

export type PluggedTab = "code" | "documentation";

const plugged = new Map<PluggedTab, TabView>();

export function registerTab(name: PluggedTab, view: TabView): void {
  plugged.set(name, view);
}

export function pluggedTab(name: string): TabView | undefined {
  return plugged.get(name as PluggedTab);
}

export function pluggedTabs(): TabView[] {
  return [...plugged.values()];
}
