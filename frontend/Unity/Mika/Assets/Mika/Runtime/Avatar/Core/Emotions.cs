using System;
using System.Collections.Generic;

namespace Mika.Avatar
{
    /// <summary>
    /// Les 29 émotions de Mika, telles que le noyau les nomme (<c>emotion/types.py</c>) et telles qu'elles
    /// arrivent dans les trames : en anglais, en minuscules. C'est la seule liste du client Unity ; toute table
    /// indexée par émotion est vérifiée contre elle par les tests, pour qu'une trentième émotion ajoutée côté
    /// noyau fasse échouer un test ici plutôt que de tomber silencieusement sur « neutral ».
    /// </summary>
    public static class Emotions
    {
        public const string Neutral = "neutral";

        /// <summary>Dans l'ordre du noyau : neutre, 9 positives, 9 négatives, 10 complexes.</summary>
        public static readonly IReadOnlyList<string> All = new[]
        {
            "neutral",
            "happy", "excited", "love", "proud", "grateful", "playful", "amused", "hopeful", "relieved",
            "sad", "angry", "scared", "disgusted", "frustrated", "lonely", "anxious", "bored", "jealous",
            "surprised", "thinking", "confused", "embarrassed", "nostalgic", "dreamy", "determined", "mischievous",
            "curious", "melancholic",
        };

        static readonly HashSet<string> Set = new HashSet<string>(All, StringComparer.Ordinal);

        public static bool IsEmotion(string name) => name != null && Set.Contains(name);

        /// <summary>
        /// Valence (plaisir) des 29 émotions — la colonne P des ancres PAD du noyau
        /// (<c>emotion/pad.py::PAD_ANCHORS</c>), recopiée comme le fait le client web (<c>affect.ts</c>) plutôt
        /// que réinventée : le visage lit le même affect que le moteur d'humeur calcule.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, float> Valence = new Dictionary<string, float>
        {
            ["neutral"] = 0f,
            ["happy"] = 0.8f, ["excited"] = 0.7f, ["love"] = 0.9f, ["proud"] = 0.7f, ["grateful"] = 0.7f,
            ["playful"] = 0.7f, ["amused"] = 0.7f, ["hopeful"] = 0.6f, ["relieved"] = 0.5f,
            ["sad"] = -0.7f, ["angry"] = -0.6f, ["scared"] = -0.7f, ["disgusted"] = -0.7f, ["frustrated"] = -0.5f,
            ["lonely"] = -0.7f, ["anxious"] = -0.5f, ["bored"] = -0.3f, ["jealous"] = -0.5f,
            ["surprised"] = 0.1f, ["thinking"] = 0.1f, ["confused"] = -0.2f, ["embarrassed"] = -0.3f,
            ["nostalgic"] = 0.2f, ["dreamy"] = 0.4f, ["determined"] = 0.4f, ["mischievous"] = 0.5f,
            ["curious"] = 0.4f, ["melancholic"] = -0.5f,
        };

        /// <summary>Activation (arousal) des 29 émotions — la colonne A des mêmes ancres PAD.</summary>
        public static readonly IReadOnlyDictionary<string, float> Arousal = new Dictionary<string, float>
        {
            ["neutral"] = 0f,
            ["happy"] = 0.3f, ["excited"] = 0.9f, ["love"] = 0.4f, ["proud"] = 0.3f, ["grateful"] = 0.1f,
            ["playful"] = 0.6f, ["amused"] = 0.4f, ["hopeful"] = 0.2f, ["relieved"] = -0.3f,
            ["sad"] = -0.3f, ["angry"] = 0.8f, ["scared"] = 0.7f, ["disgusted"] = 0.3f, ["frustrated"] = 0.6f,
            ["lonely"] = -0.4f, ["anxious"] = 0.6f, ["bored"] = -0.6f, ["jealous"] = 0.5f,
            ["surprised"] = 0.8f, ["thinking"] = 0.1f, ["confused"] = 0.3f, ["embarrassed"] = 0.4f,
            ["nostalgic"] = -0.2f, ["dreamy"] = -0.3f, ["determined"] = 0.5f, ["mischievous"] = 0.5f,
            ["curious"] = 0.5f, ["melancholic"] = -0.5f,
        };

        public static float ArousalOf(string emotion) => emotion != null && Arousal.TryGetValue(emotion, out var a) ? a : 0f;

        public static float ValenceOf(string emotion) => emotion != null && Valence.TryGetValue(emotion, out var v) ? v : 0f;

        /// <summary>
        /// Amplitude de l'articulation quand elle parle (<c>affect.ts::articulationFor</c>) : une voix excitée
        /// articule grand, une voix triste, blasée ou fatiguée entrouvre à peine les lèvres. Activation ×
        /// intensité, moins la fatigue, bornée à [0,6 ; 1,15].
        /// </summary>
        public static float ArticulationFor(string emotion, float intensity, float fatigue = 0f)
        {
            float a = ArousalOf(emotion) * Clamp01(intensity);
            return Math.Max(0.6f, Math.Min(1.15f, 1f + 0.35f * a - 0.25f * Clamp01(fatigue)));
        }

        /// <summary>
        /// Fatigue 0…1 déduite de l'énergie 0…1 (rythme circadien + pulsion de repos, envoyée par le noyau) :
        /// rien au-dessus de 0,55, entière à 0,15. Même seuil que le client web (<c>AnimationSystem.setEnergy</c>),
        /// pour que les paupières lourdes et les clignements lents arrivent au même moment sur les deux clients.
        /// </summary>
        public static float FatigueFromEnergy(float energy) => Clamp01((0.55f - energy) / 0.4f);

        /// <summary>
        /// Part de l'émotion secondaire montrée sur le visage, relativement à son poids dans le mélange. Un vrai
        /// visage est rarement une seule émotion : un sourire à travers la tristesse, une inquiétude sous un rire.
        /// </summary>
        public const float SecondaryShare = 0.45f;

        /// <summary>En dessous de ce rapport de poids, la secondaire est du bruit, pas un sentiment.</summary>
        public const float SecondaryMinRatio = 0.3f;

        /// <summary>
        /// L'émotion la plus forte du mélange autre que la principale (et autre que « neutral »), avec son poids
        /// relatif à celui de la principale ; <c>false</c> quand aucune ne mérite d'être montrée. Seule la
        /// première candidate est examinée, comme sur le web : le mélange arrive trié par poids décroissant.
        /// </summary>
        public static bool TrySecondary(string primary, IReadOnlyList<KeyValuePair<string, float>> blend,
            out string emotion, out float ratio)
        {
            emotion = null;
            ratio = 0f;
            if (blend == null || blend.Count < 2)
                return false;
            float top = blend[0].Value;
            for (int i = 0; i < blend.Count; i++)
            {
                if (blend[i].Key == primary)
                {
                    top = blend[i].Value;
                    break;
                }
            }
            if (!(top > 0f))
                return false;
            for (int i = 0; i < blend.Count; i++)
            {
                var other = blend[i];
                if (other.Key == primary || other.Key == Neutral)
                    continue;
                if (!IsEmotion(other.Key))
                    continue;
                float r = Math.Min(1f, other.Value / top);
                if (r < SecondaryMinRatio)
                    return false;
                emotion = other.Key;
                ratio = r;
                return true;
            }
            return false;
        }

        internal static float Clamp01(float v) => v < 0f ? 0f : v > 1f ? 1f : (float.IsNaN(v) ? 0f : v);

        internal static float Clamp(float v, float lo, float hi) => v < lo ? lo : v > hi ? hi : v;
    }

    /// <summary>Les quatre phases de sommeil du noyau (<c>memory/sleep.py::SleepPhase</c>).</summary>
    public enum SleepPhase
    {
        Awake,
        LightSleep,
        Rem,
        DeepSleep,
    }

    public static class SleepPhases
    {
        /// <summary>
        /// Résout une phase venue du réseau. Une valeur inconnue vaut « éveillée », comme
        /// <c>types/sleep.ts::resolveSleepPhase</c> : un JSON jamais vérifié ne doit pas fermer les yeux de
        /// l'avatar pour toujours ni lever d'exception au milieu d'une trame.
        /// </summary>
        public static SleepPhase Parse(string value)
        {
            switch (value)
            {
                case "light_sleep": return SleepPhase.LightSleep;
                case "rem": return SleepPhase.Rem;
                case "deep_sleep": return SleepPhase.DeepSleep;
                default: return SleepPhase.Awake;
            }
        }

        public static bool IsKnown(string value) =>
            value == "awake" || value == "light_sleep" || value == "rem" || value == "deep_sleep";

        public static string Name(SleepPhase phase)
        {
            switch (phase)
            {
                case SleepPhase.LightSleep: return "light_sleep";
                case SleepPhase.Rem: return "rem";
                case SleepPhase.DeepSleep: return "deep_sleep";
                default: return "awake";
            }
        }
    }
}
