using System;
using System.Collections.Generic;

namespace Mika.Avatar
{
    /// <summary>
    /// Couche de micro-expressions — l'équivalent, pour le visage, des clips d'attente du corps. Portage de
    /// <c>frontend/Web/src/vtuber/animation/FaceIdleController.ts</c>.
    /// </summary>
    /// <remarks>
    /// Sans elle le visage ne fait que cligner et tenir la forme d'émotion, ce qui, à côté d'un corps animé,
    /// se lit comme un masque. Elle pilote les formes ARKit « perfect sync » du modèle (<c>BrowInnerUp</c>,
    /// <c>MouthDimpleLeft</c>…), un jeu DISJOINT de toutes les autres couches (émotions, visèmes, clignement),
    /// pour que tout se compose sans arbitrage. Deux contributions : une dérive continue, lente et
    /// volontairement asymétrique (un visage parfaitement symétrique est le signe le plus fort d'une
    /// marionnette), et des accents par émotion (sourcils, nez, joues) qui donnent à l'émotion sa lecture avant
    /// même que la forme principale arrive — et à <c>neutral</c>, VIDE sur ce modèle, quelque chose à faire.
    /// Amplitudes petites exprès : les liaisons VRM s'additionnent sur les sommets.
    /// </remarks>
    public sealed class FaceIdleModel
    {
        public readonly struct MicroChannel
        {
            public readonly string Name;
            public readonly float Amp, Bias, Rate, Seed, TalkBoost;

            public MicroChannel(string name, float amp, float bias, float rate, float seed, float talkBoost = 1f)
            {
                Name = name; Amp = amp; Bias = bias; Rate = rate; Seed = seed; TalkBoost = talkBoost;
            }
        }

        public static readonly IReadOnlyList<MicroChannel> MicroChannels = new[]
        {
            new MicroChannel("BrowInnerUp", 0.07f, 0.05f, 0.55f, 1, 1.5f),
            new MicroChannel("BrowOuterUpLeft", 0.06f, 0.04f, 0.47f, 2, 1.4f),
            new MicroChannel("BrowOuterUpRight", 0.06f, 0.04f, 0.53f, 3, 1.4f),
            new MicroChannel("EyeSquintLeft", 0.05f, 0.03f, 0.61f, 4),
            new MicroChannel("EyeSquintRight", 0.05f, 0.03f, 0.67f, 5),
            new MicroChannel("MouthDimpleLeft", 0.06f, 0.05f, 0.42f, 6, 1.6f),
            new MicroChannel("MouthDimpleRight", 0.06f, 0.05f, 0.38f, 7, 1.6f),
            new MicroChannel("MouthPressLeft", 0.04f, 0.02f, 0.35f, 8),
            new MicroChannel("MouthPressRight", 0.04f, 0.02f, 0.31f, 9),
            new MicroChannel("MouthShrugUpper", 0.04f, 0.03f, 0.29f, 10),
            new MicroChannel("CheekSquintLeft", 0.035f, 0.02f, 0.44f, 11),
            new MicroChannel("CheekSquintRight", 0.035f, 0.02f, 0.48f, 12),
        };

        /// <summary>
        /// Nuances ARKit par émotion, à intensité 1, gardées ≤ 0,45 pour se lire comme une nuance par-dessus la
        /// forme d'émotion et non comme une seconde expression concurrente.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, float>> EmotionAccent =
            new Dictionary<string, IReadOnlyDictionary<string, float>>
            {
                ["happy"] = A(("MouthSmileLeft", 0.3f), ("MouthSmileRight", 0.3f), ("CheekSquintLeft", 0.25f), ("CheekSquintRight", 0.25f)),
                ["excited"] = A(("EyeWideLeft", 0.35f), ("EyeWideRight", 0.35f), ("BrowOuterUpLeft", 0.3f), ("BrowOuterUpRight", 0.3f), ("MouthSmileLeft", 0.25f), ("MouthSmileRight", 0.25f)),
                ["love"] = A(("CheekSquintLeft", 0.3f), ("CheekSquintRight", 0.3f), ("BrowInnerUp", 0.2f), ("MouthSmileLeft", 0.2f), ("MouthSmileRight", 0.2f)),
                ["proud"] = A(("BrowOuterUpLeft", 0.2f), ("BrowOuterUpRight", 0.2f), ("MouthSmileLeft", 0.22f), ("MouthSmileRight", 0.22f)),
                ["grateful"] = A(("BrowInnerUp", 0.25f), ("MouthSmileLeft", 0.25f), ("MouthSmileRight", 0.25f), ("CheekSquintLeft", 0.2f), ("CheekSquintRight", 0.2f)),
                ["playful"] = A(("MouthSmileLeft", 0.35f), ("MouthSmileRight", 0.15f), ("EyeSquintLeft", 0.2f), ("BrowOuterUpRight", 0.25f)),
                ["amused"] = A(("MouthSmileLeft", 0.3f), ("MouthSmileRight", 0.3f), ("CheekSquintLeft", 0.3f), ("CheekSquintRight", 0.3f), ("EyeSquintLeft", 0.25f), ("EyeSquintRight", 0.25f)),
                ["hopeful"] = A(("BrowInnerUp", 0.3f), ("BrowOuterUpLeft", 0.2f), ("BrowOuterUpRight", 0.2f), ("MouthSmileLeft", 0.15f), ("MouthSmileRight", 0.15f)),
                ["relieved"] = A(("BrowInnerUp", 0.2f), ("MouthShrugUpper", 0.2f), ("EyeSquintLeft", 0.2f), ("EyeSquintRight", 0.2f)),
                ["sad"] = A(("BrowInnerUp", 0.45f), ("MouthFrownLeft", 0.3f), ("MouthFrownRight", 0.3f)),
                ["angry"] = A(("BrowDownLeft", 0.45f), ("BrowDownRight", 0.45f), ("NoseSneerLeft", 0.2f), ("NoseSneerRight", 0.2f), ("MouthPressLeft", 0.25f), ("MouthPressRight", 0.25f)),
                ["scared"] = A(("BrowInnerUp", 0.4f), ("EyeWideLeft", 0.4f), ("EyeWideRight", 0.4f), ("MouthStretchLeft", 0.2f), ("MouthStretchRight", 0.2f)),
                ["disgusted"] = A(("NoseSneerLeft", 0.45f), ("NoseSneerRight", 0.45f), ("BrowDownLeft", 0.25f), ("BrowDownRight", 0.25f), ("MouthFrownLeft", 0.2f), ("MouthFrownRight", 0.2f)),
                ["frustrated"] = A(("BrowDownLeft", 0.35f), ("BrowDownRight", 0.35f), ("MouthPressLeft", 0.3f), ("MouthPressRight", 0.3f)),
                ["lonely"] = A(("BrowInnerUp", 0.35f), ("MouthFrownLeft", 0.2f), ("MouthFrownRight", 0.2f), ("EyeSquintLeft", 0.15f), ("EyeSquintRight", 0.15f)),
                ["anxious"] = A(("BrowInnerUp", 0.4f), ("MouthPressLeft", 0.3f), ("MouthPressRight", 0.3f), ("EyeWideLeft", 0.2f), ("EyeWideRight", 0.2f)),
                ["bored"] = A(("BrowDownLeft", 0.15f), ("BrowDownRight", 0.15f), ("EyeSquintLeft", 0.3f), ("EyeSquintRight", 0.3f), ("MouthShrugLower", 0.2f)),
                ["jealous"] = A(("BrowDownLeft", 0.3f), ("BrowDownRight", 0.2f), ("MouthPressLeft", 0.3f), ("EyeSquintRight", 0.2f)),
                ["surprised"] = A(("BrowInnerUp", 0.45f), ("BrowOuterUpLeft", 0.4f), ("BrowOuterUpRight", 0.4f), ("EyeWideLeft", 0.45f), ("EyeWideRight", 0.45f)),
                ["thinking"] = A(("BrowDownLeft", 0.3f), ("BrowInnerUp", 0.2f), ("MouthPressLeft", 0.3f), ("EyeSquintLeft", 0.2f)),
                ["confused"] = A(("BrowInnerUp", 0.3f), ("BrowDownRight", 0.3f), ("BrowOuterUpLeft", 0.25f), ("MouthShrugUpper", 0.2f)),
                ["embarrassed"] = A(("BrowInnerUp", 0.3f), ("EyeSquintLeft", 0.25f), ("EyeSquintRight", 0.25f), ("MouthShrugUpper", 0.25f), ("CheekSquintLeft", 0.2f), ("CheekSquintRight", 0.2f)),
                ["nostalgic"] = A(("BrowInnerUp", 0.3f), ("MouthSmileLeft", 0.15f), ("MouthSmileRight", 0.15f), ("EyeSquintLeft", 0.15f), ("EyeSquintRight", 0.15f)),
                ["dreamy"] = A(("BrowOuterUpLeft", 0.2f), ("BrowOuterUpRight", 0.2f), ("EyeSquintLeft", 0.25f), ("EyeSquintRight", 0.25f)),
                ["determined"] = A(("BrowDownLeft", 0.3f), ("BrowDownRight", 0.3f), ("MouthPressLeft", 0.25f), ("MouthPressRight", 0.25f)),
                ["mischievous"] = A(("MouthSmileLeft", 0.35f), ("EyeSquintLeft", 0.3f), ("BrowDownLeft", 0.2f), ("BrowOuterUpRight", 0.25f)),
                ["curious"] = A(("BrowInnerUp", 0.25f), ("BrowOuterUpLeft", 0.3f), ("EyeWideLeft", 0.2f), ("EyeWideRight", 0.2f)),
                ["melancholic"] = A(("BrowInnerUp", 0.4f), ("MouthFrownLeft", 0.25f), ("MouthFrownRight", 0.25f), ("EyeSquintLeft", 0.15f), ("EyeSquintRight", 0.15f)),
            };

        /// <summary>Réponse des sourcils et paupières aux temps de la parole, à emphase = 1 / question = 1.</summary>
        public static readonly IReadOnlyDictionary<string, (float emphasis, float question)> SpeechBrows =
            new Dictionary<string, (float, float)>
            {
                ["BrowInnerUp"] = (0.28f, 0.22f),
                ["BrowOuterUpLeft"] = (0.32f, 0.3f),
                ["BrowOuterUpRight"] = (0.3f, 0.26f),
                ["EyeWideLeft"] = (0.12f, 0.08f),
                ["EyeWideRight"] = (0.12f, 0.08f),
            };

        /// <summary>Vitesse à laquelle les accents suivent un changement d'émotion.</summary>
        public const float AccentEase = 2.5f;

        /// <summary>Amplitude gardée dans le sommeil — un visage endormi respire encore.</summary>
        public const float SleepMicroScale = 0.18f;

        /// <summary>Toutes les formes que cette couche peut écrire (pour savoir lesquelles le modèle porte).</summary>
        public static IEnumerable<string> CandidateShapes()
        {
            var set = new HashSet<string>();
            foreach (var c in MicroChannels)
                set.Add(c.Name);
            foreach (var name in SpeechBrows.Keys)
                set.Add(name);
            foreach (var accents in EmotionAccent.Values)
                foreach (var name in accents.Keys)
                    set.Add(name);
            return set;
        }

        readonly Func<string, bool> _available;
        readonly Dictionary<string, float> _accent = new Dictionary<string, float>();
        readonly List<string> _names = new List<string>();
        readonly Dictionary<string, float> _values = new Dictionary<string, float>();
        float _time;

        public FaceIdleModel(Func<string, bool> available) => _available = available ?? (_ => false);

        /// <summary>
        /// Avance d'un pas et AJOUTE dans <paramref name="output"/> dérive + accent + sourcils de la parole, une
        /// valeur par forme, bornée à [0, 1].
        /// </summary>
        public void Step(float dt, string emotion, float intensity, bool speaking, bool asleep,
            float speechEmphasis, float speechQuestion, IDictionary<string, float> output)
        {
            if (!(dt > 0f))
                dt = 0f;
            _time += dt;

            IReadOnlyDictionary<string, float> target = null;
            if (!asleep && emotion != null)
                EmotionAccent.TryGetValue(emotion, out target);
            float scale = 0.35f + Emotions.Clamp01(intensity) * 0.65f;
            float ease = Math.Min(1f, dt * AccentEase);
            _names.Clear();
            _names.AddRange(_accent.Keys);
            if (target != null)
                foreach (var name in target.Keys)
                    if (!_accent.ContainsKey(name))
                        _names.Add(name);
            foreach (var name in _names)
            {
                float want = 0f;
                if (target != null && target.TryGetValue(name, out var w))
                    want = w * scale;
                _accent.TryGetValue(name, out var current);
                float next = current + (want - current) * ease;
                if (want == 0f && next < 0.001f)
                    _accent.Remove(name);
                else
                    _accent[name] = next;
            }

            var values = _values;
            values.Clear();
            float microScale = asleep ? SleepMicroScale : 1f;
            foreach (var channel in MicroChannels)
            {
                if (!_available(channel.Name))
                    continue;
                float boost = speaking ? channel.TalkBoost : 1f;
                values[channel.Name] = (channel.Bias + Noise(_time * channel.Rate, channel.Seed) * channel.Amp * boost) * microScale;
            }
            foreach (var kv in _accent)
            {
                if (!_available(kv.Key))
                    continue;
                values.TryGetValue(kv.Key, out var v);
                values[kv.Key] = v + kv.Value;
            }
            // Ponctuation de la parole : les sourcils se lèvent sur un mot accentué et restent hauts sur une question.
            if (!asleep)
            {
                foreach (var kv in SpeechBrows)
                {
                    if (!_available(kv.Key))
                        continue;
                    float v = kv.Value.emphasis * speechEmphasis + kv.Value.question * speechQuestion;
                    if (v > 0.001f)
                    {
                        values.TryGetValue(kv.Key, out var cur);
                        values[kv.Key] = cur + v;
                    }
                }
            }
            foreach (var kv in values)
            {
                output.TryGetValue(kv.Key, out var w);
                output[kv.Key] = w + Emotions.Clamp01(kv.Value);
            }
        }

        /// <summary>Bruit organique bon marché : trois sinus incommensurables, jamais visiblement répétés.</summary>
        static float Noise(float t, float seed) =>
            (MathF.Sin(t * 0.37f + seed * 1.7f) + MathF.Sin(t * 0.91f + seed * 3.1f) * 0.5f +
             MathF.Sin(t * 1.53f + seed * 5.3f) * 0.25f) / 1.75f;

        static IReadOnlyDictionary<string, float> A(params (string name, float weight)[] parts)
        {
            var d = new Dictionary<string, float>();
            foreach (var (name, weight) in parts)
                d[name] = weight;
            return d;
        }
    }
}
