/**
 * Les cartes miniatures d'une liste qui défile (le fil du chat, les voyages) : chacune montre d'abord son plan dessiné
 * (`cards.ts`) ; quand elle paraît (IntersectionObserver), ce qu'elle montre se lit au serveur, puis une vraie carte
 * MapLibre, non interactive, prend sa place — **au plus quatre à la fois** (chacune tient un contexte WebGL) : au-delà,
 * le plan reste. Une miniature qui sort de la vue rend sa carte, qu'une autre visible reprend. D'un dessin de la liste
 * à l'autre, une carte vivante se reloge dans le nouveau balisage, sans se refaire.
 *
 * La clé d'une miniature (`data-mini`) est `<ce qui la porte>|<sorte>:<ref>` : deux messages qui montrent le même
 * voyage ont chacun la leur ; ce qu'elles montrent se lit une fois (par `<sorte>:<ref>`), pour toute la page
 * (`MiniStore`) : le chat et l'écran Carte le partagent — un voyage changé dans l'un se relit dans l'autre quand sa
 * miniature reparaît, et une liste qui dit un changement plus récent (`updated`) la fait relire aussi.
 */
import { ApiError } from "../api/moi";
import { fetchRegard, fetchTrip } from "../api/carte";
import type { MapInfo } from "../api/phone";
import { $$ } from "../shell/dom";
import { isDark } from "../shell/theme";
import { goneMini, miniPlan, regardMini, tripMini, type MiniData } from "./cards";
import { mapInfo } from "./info";
import { loadMapView, noteWebglMissing, webglMissing } from "./load";
import { coversAll } from "./mapgeo";
import { noteKey, type MapNote, type MapNoteKind } from "./notes";
import type { LatLon } from "./polyline";
import type { MapView } from "./view";

/** Combien de miniatures vivantes à la fois (un navigateur tient une quinzaine de contextes WebGL en tout). */
export const MAX_LIVE = 4;
/** Une lecture qui a échoué ne se refait pas avant. */
const RETRY_MS = 30_000;

/** Les places des cartes vivantes : au plus `max`. */
export class MiniPool {
  private readonly live = new Set<string>();

  constructor(readonly max = MAX_LIVE) {}

  get size(): number {
    return this.live.size;
  }

  has(key: string): boolean {
    return this.live.has(key);
  }

  /** Une place pour cette miniature (elle l'a déjà, ou il en reste une). */
  take(key: string): boolean {
    if (this.live.has(key)) return true;
    if (this.live.size >= this.max) return false;
    this.live.add(key);
    return true;
  }

  give(key: string): void {
    this.live.delete(key);
  }
}

/** La clé d'une miniature : ce qui la porte (un message), et sa note. */
export function slotKey(owner: string, note: Pick<MapNote, "kind" | "ref">): string {
  return `${owner}|${noteKey(note)}`;
}

/** La note d'une clé de miniature, sinon `null`. */
export function slotNote(key: string): { kind: MapNoteKind; ref: string } | null {
  const m = /\|(trip|map|look):(\d{1,18})$/.exec(key);
  return m ? { kind: m[1] as MapNoteKind, ref: m[2] } : null;
}

/** Les points d'une scène : ceux que la carte doit couvrir pour la montrer. */
function scenePoints(data: MiniData): LatLon[] {
  return [...data.scene.pins.map((p): LatLon => [p.lat, p.lon]), ...data.scene.lines.flatMap((l) => [l.points[0], l.points[l.points.length - 1]])];
}

/** Ce que montre une note, lu au serveur : un voyage, un regard, une carte ; plus là (404) : `gone`. */
export async function loadMini(note: { kind: MapNoteKind; ref: string }): Promise<MiniData> {
  try {
    if (note.kind === "trip") return tripMini(await fetchTrip(note.ref));
    return regardMini(note.ref, await fetchRegard(note.ref));
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return goneMini({ ...note, text: "", at: 0 });
    throw err;
  }
}

/**
 * Ce que montrent les notes (par `<sorte>:<ref>`), lu une fois à la fois. Ce qui a vieilli (un voyage changé) se montre
 * encore jusqu'à sa relecture ; une lecture partie avant le changement ne le rajeunit pas ; une lecture qui a échoué ne
 * se refait pas avant `RETRY_MS`.
 */
export class MiniStore {
  private readonly entries = new Map<string, { data: MiniData; stale: boolean }>();
  private readonly loading = new Map<string, Promise<MiniData | null>>();
  private readonly retryAt = new Map<string, number>();
  /** Combien de fois chaque note a vieilli. */
  private readonly ages = new Map<string, number>();

  /**
   * Ce qu'on sait d'une note, même vieilli, sinon `null`. `version` : son dernier changement selon une liste (un voyage
   * changé ailleurs — elle dans le chat, un autre appareil) ; plus récent que ce qu'on a lu, il vieillit.
   */
  peek(id: string, version?: number): MiniData | null {
    const entry = this.entries.get(id);
    if (!entry) return null;
    if (!entry.stale && version !== undefined && entry.data.version !== undefined && version > entry.data.version) this.invalidate(id);
    return entry.data;
  }

  /** Lu, et pas vieilli depuis. */
  fresh(id: string): boolean {
    return this.entries.get(id)?.stale === false;
  }

  /** Elle a changé : relue quand une de ses miniatures reparaît. */
  invalidate(id: string): void {
    const entry = this.entries.get(id);
    if (entry) entry.stale = true;
    this.ages.set(id, (this.ages.get(id) ?? 0) + 1);
    this.retryAt.delete(id);
  }

  /** Ce qu'elle montre : gardé, sinon lu (une fois à la fois, pour tous ceux qui attendent) ; `null` : lecture en échec. */
  read(id: string, load: () => Promise<MiniData>, now = Date.now()): Promise<MiniData | null> {
    const entry = this.entries.get(id);
    if (entry && !entry.stale) return Promise.resolve(entry.data);
    if (now < (this.retryAt.get(id) ?? 0)) return Promise.resolve(null);
    let pending = this.loading.get(id);
    if (!pending) {
      const age = this.ages.get(id) ?? 0;
      pending = load()
        .then((data) => {
          this.entries.set(id, { data, stale: (this.ages.get(id) ?? 0) !== age });
          return data;
        })
        .catch(() => {
          this.retryAt.set(id, Date.now() + RETRY_MS);
          return null;
        })
        .finally(() => this.loading.delete(id));
      this.loading.set(id, pending);
    }
    return pending;
  }
}

/** Celui de la page : le chat et l'écran Carte. */
export const MINI_STORE = new MiniStore();

interface Live {
  host: HTMLElement;
  view: MapView;
}

export class MiniMaps {
  private readonly pool = new MiniPool();
  private readonly views = new Map<string, Live>();
  /** Les miniatures qui n'auront pas de carte (ses tuiles ont échoué) : leur plan reste. */
  private readonly failed = new Set<string>();
  private readonly slots = new Map<string, HTMLElement>();
  private readonly shown = new Set<string>();
  private observer: IntersectionObserver | null = null;

  constructor(
    private readonly load: (note: { kind: MapNoteKind; ref: string }) => Promise<MiniData> = loadMini,
    private readonly store: MiniStore = MINI_STORE,
  ) {}

  /**
   * Ce qu'on sait déjà d'une note (pour le dessin pur de la liste), sinon `null`. `version` : son dernier changement
   * selon la liste qui la montre (un voyage : `updated`) ; plus récent, la miniature se relit quand elle paraît.
   */
  dataOf(note: Pick<MapNote, "kind" | "ref">, version?: number): MiniData | null {
    return this.store.peek(noteKey(note), version);
  }

  /** Ce qu'on avait lu d'une note a vieilli (un voyage changé) : ses miniatures, ici et ailleurs, se relisent quand elles reparaissent. */
  invalidate(note: Pick<MapNote, "kind" | "ref">): void {
    this.store.invalidate(noteKey(note));
  }

  /** Après chaque dessin de la liste : reloger les cartes vivantes, observer les miniatures du nouveau balisage. */
  attach(root: ParentNode): void {
    if (typeof IntersectionObserver === "undefined") return;
    this.observer ??= new IntersectionObserver((entries) => this.seen(entries), { threshold: 0 });
    this.observer.disconnect();
    this.slots.clear();
    for (const el of $$<HTMLElement>("[data-mini]", root)) {
      const key = el.dataset.mini ?? "";
      if (!key || this.slots.has(key)) continue;
      this.slots.set(key, el);
      const live = this.views.get(key);
      if (live) this.lodge(el, live);
      this.observer.observe(el);
    }
    for (const key of [...this.views.keys()]) if (!this.slots.has(key)) this.drop(key);
    for (const key of [...this.shown]) if (!this.slots.has(key)) this.shown.delete(key);
    // la carte du serveur relue (toutes les cinq minutes) : les cartes vivantes la suivent, ou rendent leur place
    const info = mapInfo.value;
    if (info && !info.ready) for (const key of [...this.views.keys()]) this.drop(key);
    else if (info) for (const live of this.views.values()) live.view.restyle(info);
  }

  /** Le thème change : les cartes vivantes suivent (les plans suivent d'eux-mêmes, par leurs couleurs). */
  theme(dark: boolean): void {
    for (const live of this.views.values()) live.view.theme(dark);
  }

  /** Tout rendre (l'écran se ferme). */
  release(): void {
    this.observer?.disconnect();
    for (const key of [...this.views.keys()]) this.drop(key);
    this.shown.clear();
    this.slots.clear();
  }

  private seen(entries: IntersectionObserverEntry[]): void {
    for (const entry of entries) {
      const el = entry.target as HTMLElement;
      const key = el.dataset.mini ?? "";
      if (this.slots.get(key) !== el) continue;
      if (entry.isIntersecting) {
        this.shown.add(key);
        void this.ready(key);
      } else {
        this.shown.delete(key);
        if (this.views.has(key)) {
          this.drop(key);
          this.promote();
        }
      }
    }
  }

  /** Une miniature visible : ce qu'elle montre (lu une fois, relu s'il a vieilli), puis sa carte s'il reste une place. */
  private async ready(key: string): Promise<void> {
    const note = slotNote(key);
    if (!note) return;
    const id = noteKey(note);
    if (!this.store.fresh(id)) {
      const got = await this.store.read(id, () => this.load(note));
      if (got) this.landed(id, got);
    }
    await this.live(key);
  }

  /** Ce qui vient d'être lu : posé dans ses miniatures ; relu après un changement, ses cartes vivantes suivent. */
  private landed(id: string, got: MiniData): void {
    this.paint(id, got);
    for (const [key, live] of [...this.views]) {
      const of = slotNote(key);
      if (!of || noteKey(of) !== id) continue;
      if (got.gone) this.drop(key);
      else live.view.show(got.scene);
    }
  }

  /** Ce qui vient d'être lu, posé dans chaque miniature de cette note (son plan, ce qu'elle est, où elle mène). */
  private paint(id: string, data: MiniData): void {
    for (const [key, el] of this.slots) {
      const note = slotNote(key);
      if (!note || noteKey(note) !== id) continue;
      const plan = el.querySelector<HTMLElement>("[data-mini-plan]");
      if (plan) plan.innerHTML = miniPlan(data);
      const sub = el.querySelector<HTMLElement>("[data-mini-sub]");
      if (sub) sub.textContent = data.sub;
      const title = el.querySelector<HTMLElement>(".mm-text b");
      if (title) title.textContent = data.title;
      if (el instanceof HTMLAnchorElement) el.href = data.href;
      el.classList.toggle("gone", !!data.gone);
    }
  }

  private async live(key: string): Promise<void> {
    if (this.views.has(key) || this.failed.has(key) || !this.shown.has(key) || webglMissing()) return;
    const note = slotNote(key);
    const data = note ? this.store.peek(noteKey(note)) : null;
    if (!data || data.gone || !data.scene.pins.length) return;
    const info: MapInfo | null = await mapInfo.load();
    if (!info || !coversAll(info, scenePoints(data))) return;
    let kit: Awaited<ReturnType<typeof loadMapView>>;
    try {
      kit = await loadMapView();
    } catch {
      return; // le morceau de MapLibre ne vient pas : les plans restent
    }
    const el = this.slots.get(key);
    if (!el || this.views.has(key) || this.failed.has(key) || !this.shown.has(key) || !this.pool.take(key)) return;
    const holder = el.querySelector<HTMLElement>("[data-mini-map]");
    if (!holder) {
      this.pool.give(key);
      return;
    }
    const host = document.createElement("div");
    host.className = "mm-live";
    holder.insertBefore(host, holder.firstChild);
    try {
      const view = new kit.MapView(kit.lib, host, info, data.scene, { dark: isDark(), interactive: false, onFail: () => this.fail(key) });
      this.views.set(key, { host, view });
      this.lodge(el, { host, view });
    } catch {
      host.remove();
      this.pool.give(key);
      noteWebglMissing(); // pas de WebGL : aucune autre ne réessaiera
    }
  }

  /** Ses tuiles échouent : sa carte s'en va, son plan reste, pour de bon. */
  private fail(key: string): void {
    this.failed.add(key);
    this.drop(key);
    this.promote();
  }

  private lodge(el: HTMLElement, live: Live): void {
    const holder = el.querySelector<HTMLElement>("[data-mini-map]");
    const plan = el.querySelector<HTMLElement>("[data-mini-plan]");
    if (!holder) return;
    if (live.host.parentElement !== holder) {
      holder.insertBefore(live.host, holder.firstChild);
      live.view.resize();
    }
    if (plan) plan.hidden = true;
  }

  private drop(key: string): void {
    const live = this.views.get(key);
    this.views.delete(key);
    this.pool.give(key);
    if (!live) return;
    live.view.remove();
    const plan = live.host.parentElement?.querySelector<HTMLElement>("[data-mini-plan]");
    if (plan) plan.hidden = false;
    live.host.remove();
  }

  /** Une place s'est libérée : une miniature visible qui n'a pas de carte la prend (les places restent bornées). */
  private promote(): void {
    for (const key of this.shown) {
      if (!this.views.has(key) && !this.failed.has(key)) void this.live(key);
    }
  }
}
