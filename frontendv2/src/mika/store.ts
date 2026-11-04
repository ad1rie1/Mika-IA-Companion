/**
 * Mika en ce moment, partagée par la pastille du haut, sa colonne du chat, son coin et sa VRM : ce qu'on sait
 * d'elle (state.ts), si elle écrit, l'état de la connexion, et quand elle « parle » (sa bouche bouge).
 * La pastille et la VRM ne lisent qu'ici ; seules les trames et le chat y écrivent.
 */
import { EMPTY_MIKA, withInnerState, withMood, type MikaState, type MoodFrame } from "./state";
import type { LinkState } from "./view";

export interface MikaSnapshot {
  state: MikaState;
  typing: boolean;
  link: LinkState;
}

type Listener = (snap: MikaSnapshot) => void;
type TalkListener = (ms: number) => void;

export class MikaStore {
  private snap: MikaSnapshot = { state: EMPTY_MIKA, typing: false, link: "connecting" };
  private readonly listeners = new Set<Listener>();
  private readonly talkers = new Set<TalkListener>();
  /** Une minuterie de l'horloge : une occupation minutée s'éteint à l'heure, sans attendre de trame. */
  private expiry: number | null = null;

  get current(): MikaSnapshot {
    return this.snap;
  }

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    fn(this.snap);
    return () => this.listeners.delete(fn);
  }

  onTalk(fn: TalkListener): () => void {
    this.talkers.add(fn);
    return () => this.talkers.delete(fn);
  }

  innerState(raw: unknown): void {
    this.set({ state: withInnerState(this.snap.state, raw) });
  }

  mood(frame: MoodFrame): void {
    const state = withMood(this.snap.state, frame);
    if (state !== this.snap.state) this.set({ state });
  }

  setTyping(typing: boolean): void {
    if (typing !== this.snap.typing) this.set({ typing });
  }

  setLink(link: LinkState): void {
    if (link !== this.snap.link) this.set({ link });
  }

  /** Elle dit quelque chose : sa bouche bouge ce temps-là. */
  talk(ms: number): void {
    for (const fn of this.talkers) fn(ms);
  }

  private set(change: Partial<MikaSnapshot>): void {
    this.snap = { ...this.snap, ...change };
    this.armExpiry();
    for (const fn of this.listeners) fn(this.snap);
  }

  private armExpiry(): void {
    if (this.expiry !== null) window.clearTimeout(this.expiry);
    this.expiry = null;
    const until = this.snap.state.activity?.until;
    if (!until) return;
    const delay = until - Date.now();
    if (delay <= 0 || delay > 24 * 3600_000) return;
    this.expiry = window.setTimeout(() => {
      this.expiry = null;
      for (const fn of this.listeners) fn(this.snap);
    }, delay + 50);
  }
}
