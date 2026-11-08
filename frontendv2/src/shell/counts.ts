/**
 * Les pastilles de la barre du haut : ce qui attend la personne, domaine par domaine, lu dans `GET /api/moi`.
 * Relues au démarrage, toutes les minutes, quand l'onglet revient au premier plan, et quand un écran le demande
 * (`refreshCounts`, après un geste qui les change). Une lecture qui échoue garde les dernières valeurs.
 *
 * La même lecture dit aussi qui est connecté : son nom, que le menu du compte suit quand on l'a renommé ailleurs (un
 * autre appareil, la console). `startCounts` la passe à qui la demande.
 */
import { fetchMe, type Counts, type Me } from "../api/me";

const EVERY_MS = 60_000;
const current: Counts = { mail: 0, teams: 0, phone: 0 };
let painter: (() => void) | null = null;
let reader: ((me: Me) => void) | null = null;
let inflight: Promise<void> | null = null;

/** La pastille d'un domaine (`""` : rien à montrer). */
export function countOf(domain: keyof Counts): number | "" {
  return current[domain] || "";
}

export function refreshCounts(): Promise<void> {
  if (inflight) return inflight;
  inflight = fetchMe()
    .then((me) => {
      Object.assign(current, me.counts);
      painter?.();
      reader?.(me);
    })
    .catch(() => {
      // le serveur ne répond pas, ou la session est partie : la connexion du chat le dira
    })
    .finally(() => {
      inflight = null;
    });
  return inflight;
}

/**
 * Démarre la relecture ; ``paint`` repeint les pastilles (``Shell.updateCounts``) ; ``read`` reçoit chaque lecture
 * entière (``main.ts`` : le nom du compte).
 */
export function startCounts(paint: () => void, read?: (me: Me) => void): void {
  painter = paint;
  reader = read ?? null;
  void refreshCounts();
  window.setInterval(() => void refreshCounts(), EVERY_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") void refreshCounts();
  });
}
