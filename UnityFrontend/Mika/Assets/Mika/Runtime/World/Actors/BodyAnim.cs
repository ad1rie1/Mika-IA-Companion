using Mika.World.Protocol;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>
    /// Le contrat entre le code et le contrôleur d'animation d'un corps humanoïde : les noms des paramètres, et
    /// les valeurs qu'ils prennent. Le contrôleur est généré par l'éditeur (menu Mika › Animation) à partir des
    /// clips présents ; ce fichier est la seule source de ces noms.
    /// </summary>
    public static class BodyAnim
    {
        /// <summary>Vitesse de marche (m/s) : le mélange immobile → marche.</summary>
        public static readonly int Speed = Animator.StringToHash("Speed");
        /// <summary>0 debout, 1 assise, 2 allongée.</summary>
        public static readonly int Posture = Animator.StringToHash("Posture");
        /// <summary>Déclenche le geste <see cref="GestureId"/>.</summary>
        public static readonly int Gesture = Animator.StringToHash("Gesture");
        public static readonly int GestureId = Animator.StringToHash("GestureId");
        /// <summary>Tient quelque chose (bras porteur).</summary>
        public static readonly int Holding = Animator.StringToHash("Holding");
        public static readonly int Talking = Animator.StringToHash("Talking");
        /// <summary>Prendre (1) ou poser (2) : un geste de la main vers le bas, joué pendant que l'IK guide la main.</summary>
        public static readonly int Reach = Animator.StringToHash("Reach");
        /// <summary>Une occupation en cours (lire, dessiner…), voir <see cref="ActivityId"/>.</summary>
        public static readonly int Activity = Animator.StringToHash("Activity");
        public static readonly int Asleep = Animator.StringToHash("Asleep");

        public static int PostureValue(Posture p) => p switch
        {
            Protocol.Posture.Sit => 1,
            Protocol.Posture.Lie => 2,
            _ => 0,
        };

        /// <summary>Les gestes que le contrôleur sait jouer, par identifiant (les gestes du protocole, puis ceux du moteur).</summary>
        public static readonly string[] Gestures =
        {
            "none", "wave", "point", "nod", "shake_head", "bow", "clap", "poke", "pat_head",
            "think", "laugh", "sigh", "stretch", "yawn", "surprised", "bashful", "excited", "angry", "headshake",
        };

        public static int GestureIdOf(string name)
        {
            var i = System.Array.IndexOf(Gestures, name);
            return i < 0 ? 0 : i;
        }

        /// <summary>Les occupations connues du contrôleur (0 : aucune ou inconnue — le corps reste au repos).</summary>
        public static readonly string[] Activities =
        {
            "none", "read", "browse_books", "work", "draw", "look_outside", "water_plant", "nap", "play",
        };

        public static int ActivityId(string name)
        {
            var i = System.Array.IndexOf(Activities, name);
            return i < 0 ? 0 : i;
        }

        public static bool HasParameter(Animator a, int hash)
        {
            if (a == null || a.runtimeAnimatorController == null) return false;
            foreach (var p in a.parameters)
                if (p.nameHash == hash)
                    return true;
            return false;
        }
    }
}
