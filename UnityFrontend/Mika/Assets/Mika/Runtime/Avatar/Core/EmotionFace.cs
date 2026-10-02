using System;
using System.Collections.Generic;

namespace Mika.Avatar
{
    /// <summary>
    /// Le visage des émotions : les 29 émotions traduites en poids d'expressions, avec l'intensité, la
    /// secondaire du mélange, des vitesses de montée propres à chaque émotion et une descente plus lente.
    /// Portage de <c>frontend/src/vtuber/EmotionController.ts</c>.
    /// </summary>
    /// <remarks>
    /// Pur : aucune dépendance au modèle chargé. Ce qui existe sur le modèle arrive par deux prédicats au
    /// constructeur, et la sortie est un dictionnaire « nom d'expression → poids » que <see cref="MikaFace"/>
    /// envoie à UniVRM. Les noms riches sont ceux des copies nettoyées (<see cref="FaceNames.Clean"/>) des groupes
    /// du modèle Perula ; les noms standard sont les presets VRM 1.0 (<c>happy</c>, <c>sad</c>…).
    /// </remarks>
    public sealed class EmotionFace
    {
        /// <summary>
        /// Repli pour un modèle qui n'expose que les presets VRM (poids à intensité 1). Un VRM 0.x migré par
        /// UniVRM nomme joy/sorrow/fun happy/sad/relaxed, comme three-vrm côté web.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, float>> StandardMap =
            new Dictionary<string, IReadOnlyDictionary<string, float>>
            {
                ["neutral"] = R(),
                ["happy"] = R(("happy", 1f)),
                ["excited"] = R(("happy", 0.8f), ("surprised", 0.4f)),
                ["love"] = R(("happy", 0.7f), ("relaxed", 0.6f)),
                ["proud"] = R(("happy", 0.6f), ("relaxed", 0.3f)),
                ["grateful"] = R(("happy", 0.7f), ("relaxed", 0.4f)),
                ["playful"] = R(("happy", 0.7f), ("surprised", 0.2f)),
                ["amused"] = R(("happy", 0.8f), ("surprised", 0.15f)),
                ["hopeful"] = R(("happy", 0.4f), ("relaxed", 0.3f)),
                ["relieved"] = R(("relaxed", 0.8f), ("happy", 0.3f)),
                ["sad"] = R(("sad", 1f)),
                ["angry"] = R(("angry", 1f)),
                ["scared"] = R(("surprised", 0.6f), ("sad", 0.4f)),
                ["disgusted"] = R(("angry", 0.6f), ("sad", 0.3f)),
                ["frustrated"] = R(("angry", 0.7f), ("sad", 0.3f)),
                ["lonely"] = R(("sad", 0.7f), ("relaxed", 0.2f)),
                ["anxious"] = R(("sad", 0.4f), ("surprised", 0.3f)),
                ["bored"] = R(("relaxed", 0.3f), ("neutral", 0.4f)),
                ["jealous"] = R(("angry", 0.5f), ("sad", 0.4f)),
                ["surprised"] = R(("surprised", 1f)),
                ["thinking"] = R(("neutral", 0.3f), ("relaxed", 0.2f)),
                ["confused"] = R(("surprised", 0.4f), ("sad", 0.25f)),
                ["embarrassed"] = R(("happy", 0.3f), ("sad", 0.3f), ("surprised", 0.2f)),
                ["nostalgic"] = R(("sad", 0.4f), ("happy", 0.3f), ("relaxed", 0.2f)),
                ["dreamy"] = R(("relaxed", 0.7f), ("happy", 0.3f)),
                ["determined"] = R(("angry", 0.3f), ("neutral", 0.3f)),
                ["mischievous"] = R(("happy", 0.6f), ("surprised", 0.2f)),
                ["curious"] = R(("surprised", 0.4f), ("happy", 0.2f)),
                ["melancholic"] = R(("sad", 0.6f), ("relaxed", 0.3f)),
            };

        /// <summary>
        /// Les groupes du modèle Perula (build PerfectSync), bien plus riches que les presets — son preset
        /// <c>angry</c> est même vide, la colère DOIT passer par ses groupes. Joués à travers leurs copies
        /// nettoyées : les sourcils, paupières et bouche de l'auteur, SANS les symboles manga qu'il y a mis
        /// (<c>Shocked</c> dessinait des yeux en spirale et une goutte de sueur à chaque surprise, <c>Sad1</c> une
        /// larme à toute intensité…). La rougeur et les larmes viennent de <see cref="FacePhysiology"/>.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, IReadOnlyDictionary<string, float>> RichMap =
            new Dictionary<string, IReadOnlyDictionary<string, float>>
            {
                ["neutral"] = R(),
                ["happy"] = R(("Smile1", 1f)),
                ["excited"] = R(("Joy2", 0.9f), ("InWonder", 0.2f)),
                ["love"] = R(("Love1", 0.9f)),
                ["proud"] = R(("Prond", 0.9f)), // sic : l'auteur du modèle a écrit « proud » ainsi
                ["grateful"] = R(("Smile2", 0.8f), ("Relaxy", 0.15f)),
                ["playful"] = R(("Smile4", 0.7f), ("Wink1", 0.25f)),
                ["amused"] = R(("LMAO", 0.8f)),
                ["hopeful"] = R(("Smile3", 0.5f), ("InWonder", 0.35f)),
                ["relieved"] = R(("Relaxy", 0.7f), ("Smile2", 0.2f)),
                ["sad"] = R(("Sad1", 0.85f)),
                ["angry"] = R(("Angry4", 0.7f), ("Angry1", 0.3f)),
                ["scared"] = R(("Shocked2", 0.7f), ("Pain", 0.25f)),
                ["disgusted"] = R(("Disgust", 0.85f)),
                ["frustrated"] = R(("Angry2", 0.6f), ("GiveUp", 0.25f)),
                ["lonely"] = R(("Sad3", 0.8f)),
                ["anxious"] = R(("Pain", 0.45f), ("Sad1", 0.25f)),
                ["bored"] = R(("Boring", 0.85f)),
                ["jealous"] = R(("BadSmile2", 0.5f), ("Angry2", 0.35f)),
                ["surprised"] = R(("Shocked", 0.9f)),
                ["thinking"] = R(("Numbly", 0.35f), ("Interesting", 0.15f)),
                ["confused"] = R(("Hau", 0.55f)),
                ["embarrassed"] = R(("Shy", 0.85f)),
                ["nostalgic"] = R(("Sad2", 0.3f), ("Smile2", 0.35f), ("Relaxy", 0.2f)),
                ["dreamy"] = R(("InWonder", 0.55f), ("Relaxy", 0.3f)),
                ["determined"] = R(("Healthy", 0.6f), ("Angry4", 0.2f)),
                ["mischievous"] = R(("BadSmile1", 0.65f), ("Taunt1", 0.2f)),
                ["curious"] = R(("Interesting", 0.75f)),
                ["melancholic"] = R(("Sad2", 0.55f), ("Relaxy", 0.2f)),
            };

        /// <summary>Le visage endormi du modèle (paupières lourdes, lèvres entrouvertes), nettoyé.</summary>
        public const string TiredGroup = "Sleepy";

        /// <summary>…au plus ça sur un visage fatigué mais éveillé : c'est une fatigue, pas une expression.</summary>
        public const float TiredMax = 0.32f;

        /// <summary>
        /// Vitesse de montée par émotion (1/s du lissage exponentiel). Une surprise arrive en 100–200 ms, un
        /// sourire en 300–500 ms, la tristesse et la rêverie s'installent sur presque une seconde.
        /// </summary>
        public static readonly IReadOnlyDictionary<string, float> OnsetSpeed = new Dictionary<string, float>
        {
            ["surprised"] = 9f, ["scared"] = 8f, ["excited"] = 6f, ["angry"] = 5f, ["amused"] = 5f,
            ["playful"] = 5f, ["disgusted"] = 4.5f, ["frustrated"] = 4f, ["curious"] = 4f, ["happy"] = 3.5f,
            ["sad"] = 1.8f, ["lonely"] = 1.8f, ["melancholic"] = 1.6f, ["nostalgic"] = 1.6f, ["dreamy"] = 1.6f,
            ["relieved"] = 2.2f, ["bored"] = 2f, ["love"] = 2.2f, ["grateful"] = 2.5f, ["hopeful"] = 2.5f,
        };

        public const float DefaultOnsetSpeed = 3f;

        /// <summary>
        /// Toute expression REPART plus lentement qu'elle n'est arrivée : un visage qui revient au neutre au
        /// rythme où il s'est allumé est l'un des signes les plus sûrs d'un rig.
        /// </summary>
        public const float OffsetRatio = 0.6f;

        /// <summary>Une expression ne traîne jamais plus de ~0,8 s de constante de temps.</summary>
        public const float MinOffsetSpeed = 1.2f;

        /// <summary>
        /// Amplitude de la « respiration » d'une expression tenue : quelques pour cent, pour que le visage ne
        /// soit jamais identique au bit près d'une image à l'autre.
        /// </summary>
        public const float PulseAmplitude = 0.05f;

        public static float OnsetSpeedFor(string emotion) =>
            emotion != null && OnsetSpeed.TryGetValue(emotion, out var s) ? s : DefaultOnsetSpeed;

        public static float OffsetSpeedFor(string emotion) => Math.Max(MinOffsetSpeed, OnsetSpeedFor(emotion) * OffsetRatio);

        readonly Dictionary<string, Dictionary<string, float>> _active = new Dictionary<string, Dictionary<string, float>>();
        readonly Dictionary<string, float> _target = new Dictionary<string, float>();
        readonly Dictionary<string, float> _current = new Dictionary<string, float>();
        readonly List<string> _names = new List<string>();
        readonly string _tiredName;
        float _tiredTarget;
        float _time;
        string _blendKey = "";

        /// <summary>Combien d'émotions passent par les groupes riches du modèle (les autres par les presets).</summary>
        public int RichCount { get; }

        public string Emotion { get; private set; } = Emotions.Neutral;
        public float Intensity { get; private set; } = 0.5f;

        /// <param name="hasGroup">Le modèle porte ce groupe (et sa copie nettoyée a pu être créée).</param>
        /// <param name="hasPreset">Le modèle porte ce preset VRM (<c>happy</c>, <c>sad</c>…).</param>
        public EmotionFace(Func<string, bool> hasGroup, Func<string, bool> hasPreset)
        {
            hasGroup ??= _ => false;
            hasPreset ??= _ => false;
            int rich = 0;
            foreach (var emotion in Emotions.All)
            {
                var recipe = RichMap[emotion];
                bool allRich = recipe.Count > 0;
                foreach (var group in recipe.Keys)
                {
                    if (!hasGroup(group))
                    {
                        allRich = false;
                        break;
                    }
                }
                var resolved = new Dictionary<string, float>();
                if (allRich)
                {
                    foreach (var kv in recipe)
                        resolved[FaceNames.Clean(kv.Key)] = kv.Value;
                    rich++;
                }
                else
                {
                    // Un modèle partiel se dégrade émotion par émotion, pas globalement.
                    foreach (var kv in StandardMap[emotion])
                        if (hasPreset(kv.Key))
                            resolved[kv.Key] = kv.Value;
                }
                _active[emotion] = resolved;
            }
            RichCount = rich;
            _tiredName = hasGroup(TiredGroup) ? FaceNames.Clean(TiredGroup) : null;
        }

        /// <summary>Les poids visés par l'émotion courante (après intensité et secondaire) — tests et debug.</summary>
        public IReadOnlyDictionary<string, float> Targets => _target;

        /// <summary>La recette résolue d'une émotion sur ce modèle — tests et debug.</summary>
        public IReadOnlyDictionary<string, float> RecipeOf(string emotion) =>
            _active.TryGetValue(emotion ?? "", out var r) ? r : (IReadOnlyDictionary<string, float>)new Dictionary<string, float>();

        public void SetEmotion(string emotion, float intensity, IReadOnlyList<KeyValuePair<string, float>> blend)
        {
            if (!Emotions.IsEmotion(emotion))
                emotion = Emotions.Neutral;
            float clamped = Emotions.Clamp01(intensity);
            bool hasSecondary = Emotions.TrySecondary(emotion, blend, out var secondary, out var ratio);
            string blendKey = hasSecondary ? $"{secondary}:{ratio:0.00}" : "";
            if (emotion == Emotion && clamped == Intensity && blendKey == _blendKey)
                return;

            Emotion = emotion;
            Intensity = clamped;
            _blendKey = blendKey;

            // Une secondaire transparaît à une part de son poids, en faisant un peu de place dans la principale.
            float primaryScale = hasSecondary ? 1f - 0.25f * ratio : 1f;
            _target.Clear();
            foreach (var kv in _active[emotion])
                _target[kv.Key] = kv.Value * clamped * primaryScale;
            if (hasSecondary)
            {
                float share = clamped * ratio * Emotions.SecondaryShare;
                foreach (var kv in _active[secondary])
                {
                    _target.TryGetValue(kv.Key, out var w);
                    _target[kv.Key] = Math.Min(1f, w + kv.Value * share);
                }
            }
        }

        /// <summary>
        /// Énergie 0…1 : passé ~0,55 de fatigue les paupières s'alourdissent et les lèvres s'entrouvrent un
        /// peu — lentement, ce n'est pas une expression.
        /// </summary>
        public void SetEnergy(float energy) => _tiredTarget = TiredMax * Emotions.FatigueFromEnergy(energy);

        /// <summary>
        /// Avance d'un pas et AJOUTE les poids à écrire dans <paramref name="output"/>. Montée à la vitesse de
        /// l'émotion, descente plus lente — forme par forme, puisqu'une forme qui part (celle de l'émotion
        /// précédente) et une qui arrive coexistent.
        /// </summary>
        public void Step(float dt, IDictionary<string, float> output)
        {
            if (!(dt > 0f))
                dt = 0f;
            _time += dt;
            float onset = Math.Min(1f, dt * OnsetSpeedFor(Emotion));
            float offset = Math.Min(1f, dt * OffsetSpeedFor(Emotion));

            _names.Clear();
            foreach (var name in _target.Keys)
                _names.Add(name);
            foreach (var name in _current.Keys)
                if (!_target.ContainsKey(name))
                    _names.Add(name);
            if (_tiredName != null && _tiredTarget > 0f && !_target.ContainsKey(_tiredName) && !_current.ContainsKey(_tiredName))
                _names.Add(_tiredName);

            int seed = 0;
            foreach (var name in _names)
            {
                seed++;
                _target.TryGetValue(name, out var target);
                if (name == _tiredName)
                    target += _tiredTarget;
                _current.TryGetValue(name, out var current);
                float k = target > current ? onset : offset;
                float next = current + (target - current) * k;
                if (target == 0f && next < 0.001f)
                {
                    _current.Remove(name);
                    continue;
                }
                // On suit la valeur lissée propre ; la pulsation ne fait que nuancer ce qui est écrit, elle ne
                // peut donc pas s'accumuler dans l'état du lissage.
                _current[name] = next;
                float shaded = next * (1f + Pulse(_time, seed) * PulseAmplitude);
                output.TryGetValue(name, out var w);
                output[name] = w + Emotions.Clamp01(shaded);
            }
        }

        /// <summary>Le poids lissé courant d'une expression (sans la pulsation) — tests et debug.</summary>
        public float CurrentWeight(string name) => _current.TryGetValue(name, out var w) ? w : 0f;

        static float Pulse(float t, int seed) =>
            (MathF.Sin(t * 0.43f + seed * 2.1f) + MathF.Sin(t * 0.79f + seed * 4.3f) * 0.5f) / 1.5f;

        static IReadOnlyDictionary<string, float> R(params (string name, float weight)[] parts)
        {
            var d = new Dictionary<string, float>();
            foreach (var (name, weight) in parts)
                d[name] = weight;
            return d;
        }
    }
}
