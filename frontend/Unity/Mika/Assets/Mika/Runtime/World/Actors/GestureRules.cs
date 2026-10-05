using System.Collections.Generic;

namespace Mika.World.Engine
{
    /// <summary>Ce qu'une émotion fait au corps : un geste joué une fois, une posture d'attente tenue, ou rien.</summary>
    public enum GestureKind
    {
        None,
        OneShot,
        IdleVariant,
    }

    public readonly struct GestureDecision
    {
        public readonly GestureKind Kind;
        /// <summary>Le geste (nom de <see cref="BodyAnim.Gestures"/>) ou le clip d'attente.</summary>
        public readonly string Target;
        public readonly string Reason;

        public GestureDecision(GestureKind kind, string target, string reason)
        {
            Kind = kind;
            Target = target;
            Reason = reason;
        }
    }

    /// <summary>
    /// Quand une émotion se voit dans le corps — portage des règles du client web (<c>gestures.ts</c>), pur et
    /// testable. L'ordre des portes est le contrat : sommeil → monologue intérieur → ambivalence → table →
    /// dérive → seuil → délai. Le visage, lui, réagit toujours ; un geste n'est qu'un plus.
    /// </summary>
    public static class GestureRules
    {
        public const float CooldownS = 8f;
        public const float DefaultMinIntensity = 0.6f;
        /// <summary>Une posture tenue ne se relâche qu'en dessous du seuil moins cette marge (l'humeur oscille).</summary>
        public const float VariantHysteresis = 0.08f;
        /// <summary>La deuxième émotion du mélange presque aussi forte que la première : le corps reste immobile.</summary>
        public const float AmbivalenceRatio = 0.85f;

        public static readonly IReadOnlyDictionary<string, (GestureKind kind, string target, float min)> Table =
            new Dictionary<string, (GestureKind, string, float)>
            {
                ["neutral"] = (GestureKind.None, null, 0),
                ["happy"] = (GestureKind.OneShot, "excited", 0.85f),
                ["excited"] = (GestureKind.OneShot, "excited", 0.55f),
                ["love"] = (GestureKind.None, null, 0),
                ["proud"] = (GestureKind.None, null, 0),
                ["grateful"] = (GestureKind.OneShot, "nod", 0.7f),
                ["playful"] = (GestureKind.OneShot, "laugh", 0.75f),
                ["amused"] = (GestureKind.OneShot, "laugh", 0.65f),
                ["hopeful"] = (GestureKind.None, null, 0),
                ["relieved"] = (GestureKind.OneShot, "sigh", 0.7f),
                ["sad"] = (GestureKind.IdleVariant, "idle_sad", 0.6f),
                ["angry"] = (GestureKind.OneShot, "angry", 0.65f),
                ["scared"] = (GestureKind.None, null, 0),
                ["disgusted"] = (GestureKind.OneShot, "shake_head", 0.7f),
                ["frustrated"] = (GestureKind.OneShot, "shake_head", 0.65f),
                ["lonely"] = (GestureKind.IdleVariant, "idle_sad", 0.6f),
                ["anxious"] = (GestureKind.IdleVariant, "idle_nervous", 0.55f),
                ["bored"] = (GestureKind.IdleVariant, "idle_bored", 0.5f),
                ["jealous"] = (GestureKind.None, null, 0),
                ["surprised"] = (GestureKind.OneShot, "surprised", 0.55f),
                ["thinking"] = (GestureKind.OneShot, "think", 0.6f),
                ["confused"] = (GestureKind.OneShot, "think", 0.7f),
                ["embarrassed"] = (GestureKind.OneShot, "bashful", 0.6f),
                ["nostalgic"] = (GestureKind.None, null, 0),
                ["dreamy"] = (GestureKind.None, null, 0),
                ["determined"] = (GestureKind.None, null, 0),
                ["mischievous"] = (GestureKind.None, null, 0),
                ["curious"] = (GestureKind.None, null, 0),
                ["melancholic"] = (GestureKind.IdleVariant, "idle_sad", 0.6f),
            };

        /// <summary>Un repère prosodique de la voix et son geste (il passe outre le délai, pas le sommeil).</summary>
        public static string CueGesture(string cue) => cue switch
        {
            "sigh" => "sigh",
            "laugh" => "laugh",
            _ => null,
        };

        /// <summary>
        /// Un geste qu'on lui fait et la réaction brève de son corps : une caresse sur la tête lui fait baisser un
        /// peu la tête, une pichenette la fait sursauter. Ce qu'elle en ressent revient ensuite par la dérive d'humeur.
        /// </summary>
        public static string TouchGesture(string gesture) => gesture switch
        {
            "pat_head" => "bashful",
            "poke" => "surprised",
            _ => null,
        };

        /// <param name="ambient">Dérive d'humeur entre deux répliques : les postures suivent, les gestes non.</param>
        /// <param name="activeVariant">La posture déjà tenue (clip), pour l'hystérésis.</param>
        public static GestureDecision Decide(string emotion, float intensity, float firstWeight, float secondWeight,
            bool inner, bool asleep, bool ambient, double now, double lastOneShot, string activeVariant)
        {
            if (asleep) return new GestureDecision(GestureKind.None, null, "asleep");
            if (inner) return new GestureDecision(GestureKind.None, null, "inner_persona");
            if (firstWeight > 0 && secondWeight >= firstWeight * AmbivalenceRatio)
                return new GestureDecision(GestureKind.None, null, "ambivalent");
            if (emotion == null || !Table.TryGetValue(emotion, out var m) || m.kind == GestureKind.None)
                return new GestureDecision(GestureKind.None, null, "unmapped");
            if (ambient && m.kind == GestureKind.OneShot)
                return new GestureDecision(GestureKind.None, null, "ambient_drift");
            var min = m.min > 0 ? m.min : DefaultMinIntensity;
            var threshold = m.kind == GestureKind.IdleVariant && activeVariant == m.target ? min - VariantHysteresis : min;
            if (intensity < threshold) return new GestureDecision(GestureKind.None, null, "below_threshold");
            if (m.kind == GestureKind.OneShot && lastOneShot > double.MinValue && now - lastOneShot < CooldownS)
                return new GestureDecision(GestureKind.None, null, "cooldown");
            return new GestureDecision(m.kind, m.target, "ok");
        }

        // --- l'humeur des clips (affect.ts) ------------------------------------------------------------------
        public const float AffinityGain = 1.5f, AffinityMin = 0.15f, AffinityMax = 2.5f;
        public const float TempoGain = 0.12f, TempoMin = 0.85f, TempoMax = 1.15f;
        public const float HoldGain = 0.35f, HoldMin = 0.6f, HoldMax = 1.4f;

        /// <summary>Combien un clip convient à l'humeur : rare s'il la contredit, jamais impossible.</summary>
        public static float Affinity(BodyVariant v, float valence, float arousal, float intensity)
        {
            if (v.valence == 0 && v.arousal == 0) return 1f;
            var s = Clamp(intensity, 0, 1);
            var match = v.arousal * arousal * s + v.valence * valence * s;
            return Clamp(1 + AffinityGain * match, AffinityMin, AffinityMax);
        }

        /// <summary>Le tempo des clips selon l'activation (±15 %).</summary>
        public static float Tempo(float arousal, float intensity) => Clamp(1 + TempoGain * arousal * Clamp(intensity, 0, 1), TempoMin, TempoMax);

        /// <summary>Combien de temps tenir une attente : moins longtemps quand elle est agitée.</summary>
        public static float HoldScale(float arousal, float intensity) => Clamp(1 - HoldGain * arousal * Clamp(intensity, 0, 1), HoldMin, HoldMax);

        static float Clamp(float v, float lo, float hi) => v < lo ? lo : v > hi ? hi : v;
    }
}
