/**
 * Ses réponses en plusieurs bulles, comme quelqu'un qui écrit vraiment
 * (ADR 0112). Le serveur garde une seule réponse, un seul message — sa
 * mémoire, son humeur et la notification n'en voient qu'un —, et sépare ses
 * bulles par une ligne vide ; le client les montre l'une après l'autre, « Mika
 * écrit… » entre deux, au rythme de la frappe.
 */

/** Ce qui sépare deux bulles : une ligne vide. */
const BREAK = /\n\s*\n/;

/** Les bulles d'une réponse, dans l'ordre (une seule s'il n'y a pas de ligne vide). */
export function splitBubbles(text: string): string[] {
  const parts = text
    .split(BREAK)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
  return parts.length ? parts : [text.trim()];
}

/** Le temps qu'on met à taper une bulle : un temps de base, puis par caractère, borné. */
export const TYPING_BASE_MS = 700;
export const TYPING_PER_CHAR_MS = 30;
export const TYPING_MIN_MS = 900;
export const TYPING_MAX_MS = 3500;

export function typingDelayMs(bubble: string): number {
  const ms = TYPING_BASE_MS + TYPING_PER_CHAR_MS * bubble.length;
  return Math.min(TYPING_MAX_MS, Math.max(TYPING_MIN_MS, ms));
}

interface Timers {
  set(fn: () => void, ms: number): number;
  clear(handle: number): void;
}

const WINDOW_TIMERS: Timers = {
  set: (fn, ms) => window.setTimeout(fn, ms),
  clear: (handle) => window.clearTimeout(handle),
};

/**
 * Une réponse qui s'écrit bulle par bulle. `start` montre la première ;
 * chaque suivante vient après le temps de la taper. `shown(key)` dit combien
 * en montrer (toutes, pour une réponse qui ne s'écrit pas). Une nouvelle
 * réponse, ou `finish`, montre aussitôt tout ce qui restait.
 */
export class BubbleReveal<K> {
  private current: { key: K; parts: string[]; shown: number; timer: number | null } | null = null;

  constructor(
    /** Une bulle de plus est visible (`done` : c'était la dernière). */
    private readonly onStep: (done: boolean) => void,
    private readonly timers: Timers = WINDOW_TIMERS
  ) {}

  /** Combien de bulles montrer de cette réponse. */
  shown(key: K, total: number): number {
    return this.current && this.current.key === key ? this.current.shown : total;
  }

  /** Une réponse s'écrit-elle encore ? */
  get writing(): boolean {
    return this.current !== null;
  }

  start(key: K, text: string): void {
    this.finish();
    const parts = splitBubbles(text);
    if (parts.length < 2) return;
    this.current = { key, parts, shown: 1, timer: null };
    this.next();
  }

  finish(): void {
    const cur = this.current;
    if (!cur) return;
    if (cur.timer !== null) this.timers.clear(cur.timer);
    this.current = null;
    this.onStep(true);
  }

  private next(): void {
    const cur = this.current;
    if (!cur) return;
    cur.timer = this.timers.set(() => {
      if (this.current !== cur) return;
      cur.shown += 1;
      const done = cur.shown >= cur.parts.length;
      if (done) this.current = null;
      this.onStep(done);
      if (!done) this.next();
    }, typingDelayMs(cur.parts[cur.shown]));
  }
}
