using System;

namespace Mika.World.Model
{
    /// <summary>
    /// L'heure du noyau vue d'ici. Les instants du protocole sont en microsecondes depuis l'epoch, sur l'horloge
    /// du noyau ; <c>welcome.now</c> donne le décalage avec la nôtre, recalé à chaque <c>pong</c> (le temps de
    /// l'aller-retour compte pour moitié).
    /// </summary>
    public sealed class KernelClock
    {
        long _offsetUs;
        bool _synced;

        public bool Synced => _synced;

        /// <summary>Microsecondes locales depuis l'epoch (UTC).</summary>
        public static long LocalNowUs() => (DateTime.UtcNow.Ticks - DateTime.UnixEpoch.Ticks) / 10;

        /// <summary>Maintenant, sur l'horloge du noyau.</summary>
        public long NowUs => LocalNowUs() + _offsetUs;

        /// <summary>Recale sur un instant lu du noyau (<c>welcome.now</c>), reçu à <paramref name="receivedLocalUs"/>.</summary>
        public void Sync(long kernelNowUs, long receivedLocalUs, long roundTripUs = 0)
        {
            var offset = kernelNowUs + roundTripUs / 2 - receivedLocalUs;
            // Un premier recalage s'applique tel quel ; ensuite on lisse (une gigue réseau ne doit pas faire sauter
            // une marche en cours).
            _offsetUs = _synced ? (_offsetUs * 3 + offset) / 4 : offset;
            _synced = true;
        }

        /// <summary>Secondes écoulées (sur l'horloge du noyau) depuis un instant du noyau.</summary>
        public double SecondsSince(long kernelUs) => (NowUs - kernelUs) / 1e6;
    }
}
