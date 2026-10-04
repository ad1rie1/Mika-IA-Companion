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
        /// <summary>Quelle attente (index d'une variante, voir <see cref="BodyClipSet"/>).</summary>
        public static readonly int IdleVariant = Animator.StringToHash("IdleVariant");
        /// <summary>Quelle manière de parler.</summary>
        public static readonly int TalkVariant = Animator.StringToHash("TalkVariant");
        /// <summary>Le tempo des attentes et des paroles (0,85 → 1,15 selon l'activation).</summary>
        public static readonly int Tempo = Animator.StringToHash("Tempo");
        /// <summary>La cadence du clip de marche, réglée sur la vitesse au sol (pieds sans glisse).</summary>
        public static readonly int WalkPlayback = Animator.StringToHash("WalkPlayback");
        /// <summary>Le calque additif du souffle et des micro-mouvements.</summary>
        public const string LifeLayer = "Vie";
        /// <summary>La pose du haut du corps pendant une occupation (voir <see cref="Poses"/>) ; l'IK pose les mains.</summary>
        public static readonly int Pose = Animator.StringToHash("Pose");
        /// <summary>Allongée : 0 sur le dos, 1 sur le côté gauche, 2 sur le côté droit.</summary>
        public static readonly int LieSide = Animator.StringToHash("LieSide");
        /// <summary>Sous la couette (les bras restent dessous, le corps plus ramassé).</summary>
        public static readonly int Covered = Animator.StringToHash("Covered");
        public const string PoseLayer = "Occupation";

        /// <summary>
        /// Les poses d'occupation, par identifiant (0 : aucune, le clip de posture seul). Ce sont des intentions
        /// de buste et de bras ; les mains, elles, sont posées par l'IK à l'endroit exact (une touche, une page).
        /// </summary>
        public static readonly string[] Poses =
        {
            "none", "type", "write", "read", "lap", "mattress", "sill", "reach_high", "pour", "lean_desk",
            "desk", "mouse", "drink", "take", "stretch", "turn_left_45", "turn_right_45", "turn_left_90", "turn_right_90",
            "pull_in", "push_out", "write_start", "write_end", "browse",
        };

        /// <summary>
        /// Les poses jouées par un clip de l'atelier du bureau (assise seulement, calque <see cref="PoseLayer"/>) : le
        /// corps entier, mains comprises, réglé sur le bureau tel que la chaise le présente (voir BodyActivity). Les
        /// autres poses restent des intentions que l'IK réalise.
        /// </summary>
        public static readonly (string pose, string clip)[] DeskClips =
        {
            ("desk", "desk_rest"), ("type", "desk_type"), ("mouse", "desk_mouse"), ("write", "desk_write"), ("read", "desk_read"),
            ("lap", "desk_lap"), ("lean_desk", "desk_think"), ("drink", "desk_drink"), ("take", "desk_take"), ("stretch", "desk_stretch"),
            ("turn_left_45", "chair_turn_left_45"), ("turn_right_45", "chair_turn_right_45"),
            ("turn_left_90", "chair_turn_left_90"), ("turn_right_90", "chair_turn_right_90"),
            ("pull_in", "chair_pull_in"), ("push_out", "chair_push_out"),
            ("write_start", "desk_write_start"), ("write_end", "desk_write_end"),
        };

        /// <summary>
        /// Les poses debout jouées par un clip de l'atelier (debout seulement, même calque) : devant un meuble, le corps
        /// entier, réglé dans l'atelier contre le vrai meuble (atelier_stand.py) — à la fenêtre, devant la bibliothèque.
        /// </summary>
        public static readonly (string pose, string clip)[] StandClips =
        {
            ("sill", "window_lean"), ("browse", "shelf_browse"),
        };

        /// <summary>
        /// Les courbes des gestes de l'atelier, devenues paramètres de l'Animator (préfixe « Geste ») : ce que le geste fait
        /// bouger, image par image. La chaise : pivot et roulement faits (0 → 1) ; les mains posées sur le bureau ; l'objet
        /// dans la main (0 posé, 0,5 tenu tel qu'il a été pris, 1 tenu en main pour écrire).
        /// </summary>
        public static readonly int ChairYaw = Animator.StringToHash("GesteChairYaw");
        public static readonly int ChairRoll = Animator.StringToHash("GesteChairRoll");
        public static readonly int HandsOnDesk = Animator.StringToHash("GesteHandsOnDesk");
        public static readonly int Hold = Animator.StringToHash("GesteHold");
        public static readonly string[] GestureCurves = { "GesteChairYaw", "GesteChairRoll", "GesteHandsOnDesk", "GesteHold" };

        public static int PoseId(string name)
        {
            var i = System.Array.IndexOf(Poses, name);
            return i < 0 ? 0 : i;
        }

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
