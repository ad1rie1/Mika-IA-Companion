using System.Collections.Generic;
using Mika.World.Protocol;

namespace Mika.World.Model
{
    /// <summary>Où en est une action à un instant donné : quel pas, et quelle part de ce pas.</summary>
    public readonly struct IntentPoint
    {
        /// <summary>Index du pas en cours ; <c>Steps.Count</c> quand tout est joué.</summary>
        public readonly int Step;
        /// <summary>Part du pas en cours, de 0 à 1.</summary>
        public readonly double Fraction;
        /// <summary>Secondes restantes dans le pas en cours.</summary>
        public readonly double RemainingS;

        public IntentPoint(int step, double fraction, double remainingS)
        {
            Step = step;
            Fraction = fraction;
            RemainingS = remainingS;
        }

        public bool Done(Intent intent) => Step >= intent.Steps.Count;
    }

    /// <summary>
    /// Le calendrier nominal d'une action : chaque pas a sa durée (<c>duration_us</c>), le premier commence à
    /// <c>started</c>. Un écran qui s'ouvre en route place l'acteur sur son trajet par ce calendrier ; l'hôte
    /// s'en sert pour savoir si le jeu prend du retard.
    /// </summary>
    public static class IntentTimeline
    {
        public static IntentPoint At(Intent intent, long kernelNowUs)
        {
            var t = kernelNowUs - intent.Started;
            if (t < 0) t = 0;
            var steps = intent.Steps;
            for (var i = 0; i < steps.Count; i++)
            {
                var d = steps[i].DurationUs;
                if (t < d)
                    return new IntentPoint(i, d <= 0 ? 1 : (double)t / d, (d - t) / 1e6);
                t -= d;
            }
            return new IntentPoint(steps.Count, 1, 0);
        }

        /// <summary>L'instant (noyau) où commence le pas <paramref name="index"/>.</summary>
        public static long StepStart(Intent intent, int index)
        {
            var t = intent.Started;
            for (var i = 0; i < index && i < intent.Steps.Count; i++)
                t += intent.Steps[i].DurationUs;
            return t;
        }

        /// <summary>Le dernier lieu visé par les pas de marche, ou <c>null</c>.</summary>
        public static (string room, string place) Destination(Intent intent)
        {
            string room = null, place = null;
            foreach (var s in intent.Steps)
                if (s.Kind == StepKind.Walk)
                {
                    room = s.ToRoom;
                    place = s.ToPlace;
                }
            return (room, place);
        }

        public static IEnumerable<Step> Walks(Intent intent)
        {
            foreach (var s in intent.Steps)
                if (s.Kind == StepKind.Walk)
                    yield return s;
        }
    }
}
