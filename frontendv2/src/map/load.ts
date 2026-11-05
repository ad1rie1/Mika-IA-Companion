/**
 * MapLibre, chargé une seule fois et à part (import dynamique, avec sa feuille) : aucun écran ne l'attend, et la
 * première carte qui paraît le fait venir pour toutes. Le style de Protomaps et la vue (`view.ts`, `base.ts`,
 * `mapstyle.ts`) viennent de même, à la première carte : rien de la carte n'alourdit le premier chargement.
 *
 * Un chargement qui échoue (le morceau retiré par un nouveau déploiement) le reste jusqu'au rechargement de la page :
 * chaque carte garde alors son plan dessiné, sans réessayer à chaque dessin. Un navigateur qui ne dessine pas (pas de
 * WebGL) se retient de même, à la première carte qui lève.
 */
import type { MapLib } from "./base";

let lib: Promise<MapLib> | null = null;
let views: Promise<typeof import("./view")> | null = null;
let noWebgl = false;

export function loadMapLibre(): Promise<MapLib> {
  lib ??= import("./maplibre").then((m) => m.maplibre);
  return lib;
}

/** MapLibre et la vue d'une carte de l'écran Carte ou d'une miniature. */
export async function loadMapView(): Promise<{ lib: MapLib; MapView: typeof import("./view").MapView }> {
  views ??= import("./view");
  const [got, mod] = await Promise.all([loadMapLibre(), views]);
  return { lib: got, MapView: mod.MapView };
}

/** Ce navigateur ne dessine pas de carte (une première a levé à sa création). */
export function webglMissing(): boolean {
  return noWebgl;
}

/** Une carte a levé à sa création : les suivantes ne réessaient pas. */
export function noteWebglMissing(): void {
  noWebgl = true;
}
