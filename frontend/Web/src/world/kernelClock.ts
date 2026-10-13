/**
 * L'heure du noyau vue d'ici. Les instants du protocole sont en
 * microsecondes depuis l'epoch, sur l'horloge du noyau ; `welcome.now` donne
 * le décalage avec la nôtre. Le premier recalage s'applique tel quel, les
 * suivants sont lissés : une gigue réseau ne doit pas faire sauter une marche
 * en cours. (Le jumeau de `Mika.World.Model.KernelClock` côté Unity.)
 */
export class KernelClock {
  private offsetUs = 0;
  private synced = false;

  /** `now` : millisecondes locales depuis l'epoch (Date.now par défaut). */
  constructor(private readonly now: () => number = Date.now) {}

  get isSynced(): boolean {
    return this.synced;
  }

  /** Microsecondes locales depuis l'epoch. */
  localNowUs(): number {
    return Math.round(this.now() * 1000);
  }

  /** Maintenant, sur l'horloge du noyau. */
  get nowUs(): number {
    return this.localNowUs() + this.offsetUs;
  }

  /** Recale sur un instant lu du noyau, reçu à `receivedLocalUs`. */
  sync(kernelNowUs: number, receivedLocalUs: number, roundTripUs = 0): void {
    const offset = kernelNowUs + roundTripUs / 2 - receivedLocalUs;
    this.offsetUs = this.synced ? (this.offsetUs * 3 + offset) / 4 : offset;
    this.synced = true;
  }

  /** Secondes écoulées (horloge du noyau) depuis un instant du noyau. */
  secondsSince(kernelUs: number): number {
    return (this.nowUs - kernelUs) / 1e6;
  }
}
