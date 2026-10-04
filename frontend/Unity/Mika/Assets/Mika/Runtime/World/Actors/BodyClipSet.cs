using System;
using System.Collections.Generic;
using UnityEngine;

namespace Mika.World.Engine
{
    /// <summary>Une variante d'attente ou de parole du contrôleur, et ce qu'elle exprime.</summary>
    [Serializable]
    public sealed class BodyVariant
    {
        [Tooltip("Nom du clip (idle_happy, talk_heated…).")]
        public string clip;
        [Tooltip("Index dans le contrôleur (paramètre IdleVariant ou TalkVariant).")]
        public int index;
        [Tooltip("Poids du tirage au repos ; 0 : jamais tirée d'elle-même (une posture que l'émotion appelle).")]
        public float weight = 1f;
        [Tooltip("Combien de temps la tenir (s), entre min et max.")]
        public Vector2 hold = new Vector2(8, 14);
        [Range(-1, 1)] public float valence;
        [Range(-1, 1)] public float arousal;
    }

    /// <summary>
    /// Ce que le contrôleur du corps sait jouer, décrit pour le code qui choisit : les attentes et les paroles
    /// (avec leur humeur, comme le manifeste d'animations du client web), et les gestes disponibles. Écrit par
    /// l'éditeur en même temps que le contrôleur (menu Mika › Animation), lu par <see cref="BodyExpression"/>.
    /// </summary>
    [CreateAssetMenu(menuName = "Mika/Monde/Clips du corps", fileName = "BodyClipSet")]
    public sealed class BodyClipSet : ScriptableObject
    {
        public List<BodyVariant> idles = new List<BodyVariant>();
        public List<BodyVariant> talks = new List<BodyVariant>();
        [Tooltip("Les gestes qui ont un clip (noms de BodyAnim.Gestures).")]
        public List<string> gestures = new List<string>();
        [Tooltip("Vitesse au sol (m/s) à laquelle le clip de marche est juste (pieds sans glisse).")]
        public float walkClipSpeed = 1.0f;

        // Les grandeurs suivantes sont « humaines » : en unités de taille (la hauteur des hanches, Animator.humanScale),
        // si bien qu'elles valent pour n'importe quel avatar. 0 : le clip n'existe pas (le corps se débrouille).
        [Tooltip("Marche capturée : vitesses (tailles/s) de la marche lente et de la marche normale.")]
        public float walkSlowNorm, walkNorm;
        [Tooltip("Durées (s) d'un cycle de la marche lente et de la marche normale : le mélange les synchronise.")]
        public float walkSlowSeconds, walkSeconds;
        [Tooltip("S'asseoir capturé : de combien les hanches reculent (tailles) et à quelle hauteur elles finissent.")]
        public float sitTravelNorm, sitHipsNorm;
        [Tooltip("Se lever capturé : de combien les hanches avancent (tailles).")]
        public float standTravelNorm;
        [Tooltip("Durées (s) des clips de transition s'asseoir / se lever.")]
        public float sitDownSeconds, standUpSeconds;

        public BodyVariant Idle(string clip) => idles.Find(v => v.clip == clip);
        public bool HasGesture(string name) => gestures.Contains(name);
    }
}
