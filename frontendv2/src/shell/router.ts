/**
 * Les routes : `#<écran>[/<onglet>[/<objet>]]`, comme dans la maquette. Pur, sans DOM.
 *
 * Un écran inconnu mène au chat ; un onglet inconnu, à l'onglet par défaut de l'écran (son premier). Ce qui
 * suit l'onglet est l'objet ouvert (`#mail/messages/m-claire`), barres comprises : la route se découpe encore
 * encodée, puis chaque segment se décode — un « / » encodé (`%2F`) reste dans son segment, et l'objet garde ses
 * segments vides (une référence `boîte:<ab//cd@x>` reste elle-même).
 */

export interface ScreenShape {
  tabs: readonly { id: string }[];
  /** L'onglet ouvert quand la route n'en nomme pas ; sinon le premier. */
  defaultTab?: string;
}

export interface Route {
  screen: string;
  tab: string | null;
  item: string | null;
}

export const HOME = "chat";

function decoded(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    // un encodage illisible : le segment tel quel, sans décodage
    return segment;
  }
}

/** L'écran, l'onglet et l'objet d'une route : les segments vides ne comptent pas avant l'objet (`#/mail//x`),
 *  mais l'objet les garde tous (le reste de la route, segment par segment décodé). */
function parts(hash: string): { first: string; second: string; rest: string[]; afterFirst: string[] } {
  const segments = hash.replace(/^#/, "").split("/");
  let i = 0;
  const next = (): string => {
    while (i < segments.length && !segments[i]) i++;
    return i < segments.length ? decoded(segments[i++]) : "";
  };
  const first = next();
  const afterFirst = segments.slice(i).map(decoded);
  const second = next();
  const rest = segments.slice(i).map(decoded);
  return { first, second, rest, afterFirst };
}

/** L'objet : le reste de la route, ses barres et ses segments vides compris ; rien qu'une barre finale : pas d'objet. */
function itemOf(segments: readonly string[]): string {
  return segments.some(Boolean) ? segments.join("/") : "";
}

export function parseRoute(hash: string, screens: ReadonlyMap<string, ScreenShape>, home: string = HOME): Route {
  const { first, second, rest, afterFirst } = parts(hash);
  const screen = first && screens.has(first) ? first : home;
  const shape = screens.get(screen);
  const tabs = shape?.tabs ?? [];
  if (!tabs.length) {
    // un écran sans onglets : tout ce qui suit son nom est l'objet
    const item = itemOf(afterFirst);
    return { screen, tab: null, item: screen === first && item ? item : null };
  }
  const known = !!second && tabs.some((t) => t.id === second);
  const tab = known ? second : shape?.defaultTab ?? tabs[0].id;
  const item = screen === first ? itemOf(rest) : "";
  return { screen, tab, item: item || null };
}

/** L'adresse d'une route : `#mail/messages/m-claire`. */
export function routeHash(screen: string, tab?: string | null, item?: string | null): string {
  return `#${[screen, tab, item].filter((p): p is string => !!p).join("/")}`;
}
