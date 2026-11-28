/**
 * Les âges qu'un écran montre (« il y a 3 min », « relevée il y a 2 min », le dernier signe de l'extension Teams, « vu
 * il y a 4 min ») avancent d'eux-mêmes : toutes les 30 s, l'onglet au premier plan, chaque écran abonné les repeint —
 * d'ici, sans rien demander au serveur (ADR 0308 : ce qui change est poussé, rien ne se relit à intervalles). Comme
 * `rememberNow` dans l'app Android. Chaque écran décide de ce qu'il repeint, et ne touche ni une saisie ni ce qui a
 * défilé.
 */
import { pageShown } from "../live/live";

/** Le pas des âges : une minute affichée n'attend jamais plus d'une demi-minute. */
export const AGES_MS = 30_000;

export class Ages {
  private readonly painters = new Set<() => void>();
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(private readonly shown: () => boolean = pageShown) {}

  /** Repeindre ses âges à chaque pas ; rend de quoi se désabonner. La minuterie part au premier abonné. */
  onTick(paint: () => void): () => void {
    const mine = () => paint();
    this.painters.add(mine);
    this.start();
    return () => {
      this.painters.delete(mine);
    };
  }

  /** Un pas : l'onglet caché ne repeint rien (il se repeindra au suivant, ou en revenant). */
  tick(): void {
    if (!this.shown()) return;
    for (const paint of [...this.painters]) {
      try {
        paint();
      } catch (err) {
        // un écran qui lève ne fait pas taire les suivants
        console.error("Les âges : un écran a échoué :", err);
      }
    }
  }

  private start(): void {
    if (this.timer !== null) return;
    this.timer = setInterval(() => this.tick(), AGES_MS);
  }
}

/** Les âges de la page. */
export const ages = new Ages();
