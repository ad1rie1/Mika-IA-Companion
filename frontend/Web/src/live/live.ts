/**
 * Le direct (ADR 0308) : ce qui change ce que montrent les routes de `/api/moi` est poussé sur la connexion du chat
 * (`/ws`), en une trame `changed` qui dit **quoi** a changé, jamais le contenu ; l'écran relit la route qu'il montre.
 * Le contrat — les sujets, leurs clés, ce qu'on relit : `backend/docs/protocole-moi.md`, § 2 bis.
 *
 * Ce module est le seul à lire la trame : il se branche sur chaque client de la connexion (`bind` — une reconnexion
 * après 4401 en crée un nouveau), réveille les abonnés d'un sujet (`onChange`) avec les clés nommées, ou « tout le
 * domaine » (`null`) quand la trame n'en a pas ou qu'une clé lui est inconnue ; un sujet inconnu se tait. Rien n'est
 * rattrapé : à chaque ouverture de la connexion, la première comprise, il dit à tous de relire ce qu'ils montrent
 * (`onResync`) — l'écran lu au démarrage l'a été avant que la connexion l'écoute, un changement de cet instant lui
 * aurait échappé ; un écran qui n'a encore rien lu n'a rien à relire (son `Freshness` l'oublie à sa première lecture).
 * Un écran qui relit tout pour plusieurs sujets s'abonne à eux ensemble (`onAny`) : une trame, une relecture.
 *
 * Un écran au second plan, ou l'onglet caché, ne relit rien sur le moment (`Freshness`) : il se marque périmé et se
 * relit tout entier à son retour — son `render`, ou l'onglet qui revient au premier plan (`onVisible`). Une rafale ne
 * lance pas dix lectures de la même route (`OneAtATime`). Sans DOM : testable tel quel.
 */

/** Les sujets de la trame, dans l'ordre du contrat (`backend/src/mika/ports/changes.py`, `TOPICS`). */
export const TOPICS = [
  "me",
  "mail",
  "mail.drafts",
  "mail.work",
  "teams",
  "teams.replies",
  "teams.work",
  "phone",
  "phone.position",
  "phone.phones",
  "contacts",
  "agenda",
  "projects",
  "trips",
  "settings",
] as const;

export type Topic = (typeof TOPICS)[number];

/** La clé de chaque sujet qui en a une : ce qu'elle nomme (les autres disent tout leur domaine). */
export const KEYS: Readonly<Partial<Record<Topic, string>>> = {
  mail: "boxes",
  "mail.drafts": "boxes",
  "mail.work": "refs",
  teams: "conversations",
  "teams.work": "conversations",
  phone: "conversations",
  agenda: "calendars",
  projects: "projects",
};

/** Ce qu'un changement nomme : ces clés-là (des boîtes, des mails, des conversations, des projets), ou `null` : tout
 *  le domaine. */
export type Changed = ReadonlySet<string> | null;

const KNOWN = new Set<string>(TOPICS);

/** Ce changement concerne-t-il `key` (une boîte, le mail ou la conversation ouverts, un projet) ? Tout le domaine :
 *  oui ; une clé vide (rien d'ouvert) : non, sauf tout le domaine. */
export function names(changed: Changed, key: string | number | null | undefined): boolean {
  if (changed === null) return true;
  if (key === null || key === undefined || key === "") return false;
  return changed.has(String(key));
}

/** Les clés d'une entrée de la trame, ou `null` (tout le domaine) : pas de clé, une liste vide ou illisible, un champ
 *  que le contrat ne connaît pas pour ce sujet. */
function keysOf(topic: Topic, entry: Record<string, unknown>): Changed {
  const key = KEYS[topic];
  for (const field of Object.keys(entry)) if (field !== "topic" && field !== key) return null;
  if (!key) return null;
  const raw = entry[key];
  if (!Array.isArray(raw) || !raw.length) return null;
  const out = new Set<string>();
  for (const item of raw) {
    if (typeof item === "string" && item) out.add(item);
    else if (typeof item === "number" && Number.isFinite(item)) out.add(String(item));
    else return null;
  }
  return out;
}

/** Ce que dit une trame `changed`, sujet par sujet (deux entrées du même sujet se réunissent ; « tout le domaine »
 *  l'emporte). Un sujet inconnu, une entrée illisible : rien. Pur. */
export function parseChanged(frame: unknown): Map<Topic, Changed> {
  const out = new Map<Topic, Changed>();
  const changes = (frame as { changes?: unknown } | null)?.changes;
  if (!Array.isArray(changes)) return out;
  for (const raw of changes) {
    if (!raw || typeof raw !== "object") continue;
    const entry = raw as Record<string, unknown>;
    const topic = entry.topic;
    if (typeof topic !== "string" || !KNOWN.has(topic)) continue;
    const t = topic as Topic;
    const keys = keysOf(t, entry);
    if (!out.has(t)) out.set(t, keys);
    else {
      const before = out.get(t)!;
      out.set(t, before === null || keys === null ? null : new Set([...before, ...keys]));
    }
  }
  return out;
}

/** Ce que le service écoute d'un client de la connexion : `WebSocketClient` (`network/WebSocketClient`) l'est. */
export interface Socket {
  on(type: string, handler: (data: any) => void): void;
}

/** La page, pour savoir si l'onglet est au premier plan (absente hors navigateur : toujours visible). */
interface Page {
  visibilityState?: string;
  addEventListener?: (type: string, listener: () => void) => void;
}

function page(): Page | null {
  return typeof document === "undefined" ? null : (document as unknown as Page);
}

/** L'onglet est-il au premier plan ? (Hors navigateur, ou sans le savoir : oui.) */
export function pageShown(): boolean {
  return page()?.visibilityState !== "hidden";
}

function quietly(run: () => void): void {
  try {
    run();
  } catch (err) {
    // un abonné qui lève ne fait pas taire les suivants
    console.error("Le direct : un abonné a échoué :", err);
  }
}

export class Live {
  /** Le client de la connexion qu'on écoute : celui d'avant une reconnexion après 4401 se tait. */
  private socket: Socket | null = null;
  private readonly topics = new Map<Topic, Set<(changed: Changed) => void>>();
  /** Ceux qui suivent plusieurs sujets ensemble (`onAny`) : un appel par trame. */
  private readonly anys = new Set<{ topics: ReadonlySet<Topic>; handler: (changes: ReadonlyMap<Topic, Changed>) => void }>();
  private readonly resyncs = new Set<() => void>();
  private readonly visibles = new Set<() => void>();
  private watching = false;

  /** Se brancher sur un client de la connexion (chaque `WebSocketClient` créé : une reconnexion après 4401 en crée un
   *  nouveau, qui remplace le précédent). */
  bind(socket: Socket): void {
    this.socket = socket;
    socket.on("changed", (data) => {
      if (this.socket === socket) this.receive(data);
    });
    socket.on("connection", (data) => {
      if (this.socket === socket && (data as { status?: unknown } | null)?.status === "connected") this.connected();
    });
  }

  /** Une trame `changed` : chaque sujet réveille ses abonnés, avec ce qu'il nomme ; qui suit plusieurs sujets est
   *  réveillé une fois, avec ceux de la trame qu'il suit. */
  receive(frame: unknown): void {
    const parsed = parseChanged(frame);
    for (const [topic, changed] of parsed) {
      for (const handler of [...(this.topics.get(topic) ?? [])]) quietly(() => handler(changed));
    }
    for (const any of [...this.anys]) {
      const mine = new Map([...parsed].filter(([topic]) => any.topics.has(topic)));
      if (mine.size) quietly(() => any.handler(mine));
    }
  }

  /** S'abonner à un sujet ; rend de quoi se désabonner. */
  onChange(topic: Topic, handler: (changed: Changed) => void): () => void {
    let set = this.topics.get(topic);
    if (!set) {
      set = new Set();
      this.topics.set(topic, set);
    }
    const mine = (changed: Changed) => handler(changed);
    set.add(mine);
    return () => {
      this.topics.get(topic)?.delete(mine);
    };
  }

  /** Suivre plusieurs sujets ensemble : une trame qui en nomme plusieurs n'appelle [handler] qu'une fois, avec ceux
   *  qu'il suit (ce que chacun nomme). Pour l'écran qui relit tout ce qu'il montre, quel que soit le sujet : trois
   *  sujets dans une trame, une relecture. Rend de quoi se désabonner. */
  onAny(topics: readonly Topic[], handler: (changes: ReadonlyMap<Topic, Changed>) => void): () => void {
    const mine = { topics: new Set(topics), handler };
    this.anys.add(mine);
    return () => {
      this.anys.delete(mine);
    };
  }

  /** « Relis tout ce que tu montres » : à chaque ouverture de la connexion, la première comprise (rien de ce qui a
   *  changé avant qu'elle écoute, ni pendant une coupure, n'est rattrapé). Rend de quoi se désabonner. */
  onResync(handler: () => void): () => void {
    const mine = () => handler();
    this.resyncs.add(mine);
    return () => {
      this.resyncs.delete(mine);
    };
  }

  /** L'onglet revient au premier plan. Rend de quoi se désabonner. */
  onVisible(handler: () => void): () => void {
    this.watchPage();
    const mine = () => handler();
    this.visibles.add(mine);
    return () => {
      this.visibles.delete(mine);
    };
  }

  /** L'onglet revient au premier plan : ceux qui attendaient leur retour se relisent (`visibilitychange`). */
  shown(): void {
    for (const handler of [...this.visibles]) quietly(handler);
  }

  /** Une ouverture, la première comprise : ce qu'un écran a lu avant elle a pu manquer un changement (au démarrage,
   *  il lit pendant la poignée de main ; après une coupure, rien n'est rattrapé). */
  private connected(): void {
    for (const handler of [...this.resyncs]) quietly(handler);
  }

  private watchPage(): void {
    if (this.watching) return;
    const p = page();
    if (!p || typeof p.addEventListener !== "function") return;
    this.watching = true;
    p.addEventListener("visibilitychange", () => {
      if (pageShown()) this.shown();
    });
  }
}

/** Le service de la page. */
export const live = new Live();

/**
 * Un écran face au direct : montré (son écran ouvert, l'onglet au premier plan), il relit aussitôt ce qui le
 * concerne ; sinon il se marque périmé et se relit tout entier à son retour. Branché sur le service : chaque
 * ouverture de la connexion le fait tout relire (`all`), l'onglet qui revient le relit s'il est périmé (`back`). Son
 * `render` appelle `back` aussi (un retour sur l'écran), et sa première lecture `fresh` — un écran pas encore ouvert
 * que l'ouverture a marqué périmé n'en lit pas deux fois.
 */
export class Freshness {
  private stale = false;

  constructor(
    private readonly shown: () => boolean,
    private readonly whole: () => void,
    service: Live = live,
  ) {
    service.onResync(() => this.all());
    service.onVisible(() => this.back());
  }

  /** Un changement qui le concerne : `now` s'il est montré, sinon il se marque périmé. */
  touch(now: () => void): void {
    if (this.shown()) now();
    else this.stale = true;
  }

  /** Tout relire (une ouverture de la connexion) : maintenant s'il est montré, sinon à son retour. */
  all(): void {
    this.touch(this.whole);
  }

  /** Il revient (son `render`, l'onglet au premier plan) : périmé, il se relit tout entier. Rend vrai s'il l'a fait. */
  back(): boolean {
    if (!this.stale || !this.shown()) return false;
    this.stale = false;
    this.whole();
    return true;
  }

  /** Il vient de tout lire de lui-même (sa première ouverture) : rien n'attend plus. */
  fresh(): void {
    this.stale = false;
  }

  /** Périmé, en attente de son retour. */
  get pending(): boolean {
    return this.stale;
  }
}

/**
 * Une lecture à la fois : redemandée pendant qu'elle est en vol, elle se refait une fois après (ce qui a changé
 * entre-temps a pu partir après elle) — une rafale de trames, deux lectures au plus. Une lecture qui échoue se tait
 * ici (chaque écran dit lui-même ses erreurs).
 */
export class OneAtATime {
  private running: Promise<void> | null = null;
  private again = false;

  constructor(private readonly read: () => Promise<unknown>) {}

  run(): Promise<void> {
    if (this.running) {
      this.again = true;
      return this.running;
    }
    this.running = (async () => {
      try {
        do {
          this.again = false;
          try {
            await this.read();
          } catch {
            // l'écran dit ses erreurs lui-même ; la suivante, s'il y en a une, repart
          }
        } while (this.again);
      } finally {
        this.running = null;
      }
    })();
    return this.running;
  }

  /** Une lecture en vol. */
  get busy(): boolean {
    return this.running !== null;
  }
}
