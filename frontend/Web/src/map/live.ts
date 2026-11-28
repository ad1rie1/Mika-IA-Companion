/**
 * Le cycle de vie d'une carte vivante (ADR 0193, 0194), le même pour l'écran Carte et la Position du Téléphone : la vue
 * (`MapView`) montée dans le cadre que l'écran dessine, gardée d'un dessin à l'autre et reposée dans le nouveau cadre ;
 * une autre carte servie, relue pendant qu'elle est ouverte, qui se repose sur elle (`restyle`) ; seul le dernier
 * montage demandé qui se pose (MapLibre se charge à part) ; et la carte qui ne se dessine pas ici — ses tuiles en échec
 * de suite, MapLibre qui ne vient pas, pas de WebGL — : le plan dessiné et sa note, sans réessayer à chaque dessin,
 * jusqu'à ce qu'une autre carte soit servie. Ce qui est propre à chaque écran reste chez lui : la scène qu'il montre et
 * son cadrage, ses épingles, ses gestes, sa minuterie. Les miniatures du chat ont le leur (`minis.ts`).
 *
 * MapLibre et la vue arrivent par `load.ts` : ce module n'en importe que les types.
 */
import type { MapInfo } from "../api/carte";
import { failureText } from "../shared/kit";
import { isDark } from "../shell/theme";
import { infoKey } from "./info";
import { loadMapView, noteWebglMissing, webglMissing } from "./load";
import { covers } from "./mapgeo";
import type { LatLon } from "./polyline";
import type { Scene } from "./scene";
import type { MapView, MapViewOptions } from "./view";

/** Pourquoi la carte ne s'est pas dessinée ici : ses tuiles, MapLibre qui ne vient pas, ou ce navigateur (pas de WebGL). */
export type LiveFailure = "tiles" | "load" | "webgl";

/**
 * La vraie carte se montre-t-elle pour cette scène ? La carte servie est prête, elle ne s'est pas refusée ici
 * (`refused`), et elle couvre ce que la scène montre : une de ses épingles ou un point de ses tracés au moins (une scène
 * vide : le fond de carte). `needsHere` (la Position du Téléphone) : elle couvre sa position, sans laquelle rien ne se
 * montre.
 */
export function liveWanted(info: MapInfo | null, scene: Scene, refused: boolean, needsHere = false): boolean {
  if (!info?.ready || !info.tiles || refused) return false;
  if (needsHere) return !!scene.here && covers(info, scene.here.lat, scene.here.lon);
  const points: LatLon[] = [...scene.pins.map((p): LatLon => [p.lat, p.lon]), ...scene.lines.flatMap((l) => l.points)];
  return !points.length || points.some(([la, lo]) => covers(info, la, lo));
}

/**
 * Pourquoi un plan plutôt que la carte, en mots (la note du plan de la Carte) : la carte servie qui se lit encore ou ne
 * se lit pas (`error`), aucune de réglée, son refus ici (`failure`), sinon des lieux hors de sa zone.
 */
export function planWhy(info: MapInfo | null, error: unknown, failure: LiveFailure | null): string {
  if (!info) return error ? failureText(error) : "la carte du serveur se lit…";
  if (!info.ready) return info.reason || "aucune carte n'est réglée sur ce serveur.";
  if (failure === "tiles") return "ses tuiles ne se lisent pas sur ce serveur en ce moment.";
  if (failure === "load") return "elle n'a pas pu se charger : recharge la page.";
  if (failure === "webgl") return "elle ne se dessine pas dans ce navigateur.";
  return "ces lieux sont hors de la zone qu'elle couvre.";
}

/** Ce que la carte vivante demande à son écran. */
export interface LiveHooks {
  /** Le cadre de la carte dans le dessin d'aujourd'hui (aucun : le plan, ou un autre onglet). */
  slot(): HTMLElement | null;
  /** L'écran la montre encore (ouvert, sur l'onglet de la carte) : un montage arrivé après coup ne se pose pas. */
  showing(): boolean;
  /** Redessiner l'écran : la carte ne se dessine pas ici, le plan et sa note reprennent sa place. */
  repaint(): void;
  /** La scène d'aujourd'hui, que la vue montre à sa création. */
  scene(): Scene;
  /** Ses options à la création (les gestes, un clic sur une épingle) ; le thème et l'échec de ses tuiles sont d'ici. */
  options: Omit<MapViewOptions, "dark" | "onFail">;
  /** La vue vient de se monter, sur la scène d'aujourd'hui. */
  mounted?(view: MapView): void;
  /** La Position du Téléphone : sans sa position, ou hors de la carte, le plan (`liveWanted`). */
  needsHere?: boolean;
  /** MapLibre et la vue (par défaut, `loadMapView`) : un test donne les siens. */
  load?: typeof loadMapView;
}

/** La carte vivante d'un écran : une à la fois, gardée d'un dessin à l'autre, rendue quand son cadre disparaît. */
export class LiveMap {
  private current: MapView | null = null;
  /** La carte servie qu'elle dessine (`infoKey`) : une autre, relue, se repose sur elle. */
  private key = "";
  /** Le dernier montage demandé : seul le plus récent se pose. */
  private token = 0;
  /** La carte servie qui ne s'est pas dessinée ici, et pourquoi : le plan, sans réessayer, jusqu'à une autre. */
  private failedKey: string | null = null;
  private failedWhy: LiveFailure = "webgl";

  constructor(private readonly hooks: LiveHooks) {}

  /** La vue montée, s'il y en a une (le thème la suit, l'écran lit ce qu'elle montre). */
  get view(): MapView | null {
    return this.current;
  }

  /** La vraie carte se montre-t-elle pour cette scène (`liveWanted`) ? Une autre carte servie depuis un échec se réessaie. */
  wanted(info: MapInfo | null, scene: Scene): boolean {
    // le serveur l'a dite injoignable, puis de nouveau prête (une autre clé) : on réessaie
    if (this.failedKey !== null && this.failedKey !== infoKey(info)) this.failedKey = null;
    return liveWanted(info, scene, this.failure(info) !== null, this.hooks.needsHere);
  }

  /** Pourquoi un plan plutôt que la carte, en mots (`planWhy`) ; `error` : la lecture en échec de la carte servie. */
  why(info: MapInfo | null, error: unknown): string {
    return planWhy(info, error, this.failure(info));
  }

  /**
   * Après chaque dessin de l'écran : la vue se repose dans le nouveau cadre (une autre carte servie : son style se repose
   * sur elle) et se rend, pour que l'écran y montre sa scène ; pas encore de vue : elle se monte (rien à rendre) ; plus
   * de cadre : elle est rendue, son contexte WebGL avec.
   */
  lodge(info: MapInfo | null): MapView | null {
    const slot = this.hooks.slot();
    if (!slot) {
      this.drop();
      return null;
    }
    if (!info) return null;
    const view = this.current;
    if (!view) {
      void this.mount(info);
      return null;
    }
    slot.replaceWith(view.host);
    const key = infoKey(info);
    if (key !== this.key) {
      view.restyle(info);
      this.key = key;
    }
    view.resize();
    return view;
  }

  /** Rendre la vue (l'écran quitté, un onglet sans carte) ; un montage en cours ne se posera pas. */
  drop(): void {
    this.token += 1;
    this.current?.remove();
    this.current = null;
    this.key = "";
  }

  /** Pourquoi elle ne se dessine pas ici, pour cette carte servie (rien : elle le peut). */
  private failure(info: MapInfo | null): LiveFailure | null {
    if (webglMissing()) return "webgl";
    return this.failedKey !== null && this.failedKey === infoKey(info) ? this.failedWhy : null;
  }

  private async mount(info: MapInfo): Promise<void> {
    const token = ++this.token;
    const key = infoKey(info);
    let kit: Awaited<ReturnType<typeof loadMapView>>;
    try {
      kit = await (this.hooks.load ?? loadMapView)();
    } catch {
      this.fail(key, "load"); // le morceau de MapLibre ne vient pas (un nouveau déploiement) : le plan dessiné
      return;
    }
    if (token !== this.token || this.current || !this.hooks.showing()) return;
    const slot = this.hooks.slot();
    if (!slot) return;
    try {
      this.current = new kit.MapView(kit.lib, slot, info, this.hooks.scene(), {
        ...this.hooks.options,
        dark: isDark(),
        // ses tuiles en échec : pour la carte servie qu'elle dessine alors (elle a pu se reposer sur une autre)
        onFail: () => this.fail(this.key || key, "tiles"),
      });
      this.key = key;
      this.hooks.mounted?.(this.current);
    } catch {
      noteWebglMissing(); // pas de WebGL : ni ici ni ailleurs, on ne réessaie pas
      this.fail(key, "webgl");
    }
  }

  /** La carte ne se dessine pas ici : le plan dessiné reprend sa place, avec sa note, pour cette carte servie. */
  private fail(key: string, why: LiveFailure): void {
    this.failedKey = key;
    this.failedWhy = why;
    this.drop();
    if (this.hooks.showing()) this.hooks.repaint();
  }
}
