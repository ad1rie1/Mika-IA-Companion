/**
 * Les pastilles de la barre du haut : ce qui attend la personne, domaine par domaine, lu dans `GET /api/moi`.
 * Relues au démarrage, quand le direct dit `me` (ADR 0308 : `protocole-moi.md` § 2 bis), à chaque ouverture de la
 * connexion (la première comprise), et quand un écran le demande (`refreshCounts`, après un geste qui les change).
 * L'onglet caché ne relit rien : il se relit à son retour s'il a manqué un changement. Une lecture qui échoue garde les
 * dernières valeurs.
 *
 * La même lecture dit aussi qui est connecté : son nom, que le menu du compte suit quand on l'a renommé ailleurs (un
 * autre appareil, la console). `startCounts` la passe à qui la demande.
 */
import { fetchMe, type Counts, type Me } from "../api/me";
import { Freshness, live, OneAtATime, pageShown } from "../live/live";

const current: Counts = { mail: 0, teams: 0, phone: 0, projects: 0 };
let painter: (() => void) | null = null;
let reader: ((me: Me) => void) | null = null;

/** Une lecture à la fois ; demandée pendant qu'une est en vol, elle se refait une fois après. */
const reading = new OneAtATime(async () => {
  try {
    const me = await fetchMe();
    Object.assign(current, me.counts);
    painter?.();
    reader?.(me);
  } catch {
    // le serveur ne répond pas, ou la session est partie : la connexion du chat le dira
  }
});

/** La pastille d'un domaine (`""` : rien à montrer). */
export function countOf(domain: keyof Counts): number | "" {
  return current[domain] || "";
}

export function refreshCounts(): Promise<void> {
  return reading.run();
}

/**
 * Démarre les pastilles ; ``paint`` les repeint (``Shell.updateCounts``) ; ``read`` reçoit chaque lecture entière
 * (``main.ts`` : le nom du compte).
 */
export function startCounts(paint: () => void, read?: (me: Me) => void): void {
  painter = paint;
  reader = read ?? null;
  // la barre du haut est toujours là : seul l'onglet caché attend
  const fresh = new Freshness(pageShown, () => void refreshCounts());
  live.onChange("me", () => fresh.touch(() => void refreshCounts()));
  void refreshCounts();
}
