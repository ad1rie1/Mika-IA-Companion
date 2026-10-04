using System;
using System.Collections.Generic;

namespace Mika.Avatar
{
    /// <summary>
    /// Ce que le visage fait et qui n'est PAS une expression : le sang, les larmes, les pupilles. Portage de
    /// <c>frontend/Web/src/vtuber/FacePhysiology.ts</c>.
    /// </summary>
    /// <remarks>
    /// Une expression est un muscle — elle arrive en une fraction de seconde et repart presque aussi vite.
    /// Ceci est de la physiologie, sur des horloges à elle, plus lentes, et c'est précisément ce qui la rend
    /// crédible :
    /// <list type="bullet">
    /// <item>la rougeur monte en une ou deux secondes et met bien plus longtemps à partir — un embarras reste
    /// sur le visage après que l'expression est passée à autre chose ;</item>
    /// <item>les larmes MONTENT : une tristesse qui dure fait d'abord briller les yeux, puis, si elle est forte
    /// et qu'elle dure, une larme se forme — jamais à la première image d'une phrase un peu triste. Le fou rire
    /// et l'émotion profonde peuvent en amener aussi ; elles sèchent lentement ;</item>
    /// <item>les pupilles se dilatent avec l'intérêt, l'affection et la peur, se contractent avec la colère et le
    /// dégoût — petites, lentes, lues sans être remarquées.</item>
    /// </list>
    /// Pilotée par le même couple (émotion, intensité) que le visage ; n'écrit que ses propres morphs
    /// <c>raw:</c>, disjoints de toutes les autres couches.
    /// </remarks>
    public sealed class FacePhysiology
    {
        public static readonly IReadOnlyDictionary<string, float> Blush = new Dictionary<string, float>
        {
            ["embarrassed"] = 0.95f, ["love"] = 0.75f, ["excited"] = 0.3f, ["amused"] = 0.3f, ["angry"] = 0.35f,
            ["grateful"] = 0.25f, ["playful"] = 0.2f, ["proud"] = 0.15f, ["jealous"] = 0.2f, ["frustrated"] = 0.18f,
            ["dreamy"] = 0.2f, ["happy"] = 0.12f, ["hopeful"] = 0.1f,
        };

        /// <summary>À quel point chaque émotion pousse vers les larmes (le chagrin, ou être ému).</summary>
        public static readonly IReadOnlyDictionary<string, float> Tears = new Dictionary<string, float>
        {
            ["sad"] = 1f, ["lonely"] = 0.9f, ["melancholic"] = 0.75f, ["nostalgic"] = 0.45f, ["anxious"] = 0.3f,
            ["scared"] = 0.35f, ["frustrated"] = 0.2f, ["grateful"] = 0.45f, ["relieved"] = 0.35f, ["love"] = 0.3f,
        };

        /// <summary>Taille des pupilles : &gt; 0 dilate, &lt; 0 contracte.</summary>
        public static readonly IReadOnlyDictionary<string, float> Pupil = new Dictionary<string, float>
        {
            ["love"] = 0.6f, ["scared"] = 0.7f, ["excited"] = 0.5f, ["surprised"] = 0.5f, ["curious"] = 0.45f,
            ["dreamy"] = 0.3f, ["hopeful"] = 0.25f, ["happy"] = 0.2f, ["thinking"] = 0.15f,
            ["angry"] = -0.5f, ["disgusted"] = -0.5f, ["frustrated"] = -0.3f, ["bored"] = -0.2f,
        };

        /// <summary>En dessous de ce (poids × intensité), rien ne monte.</summary>
        public const float TearThreshold = 0.45f;
        /// <summary>Rire aux larmes n'arrive qu'en haut de l'échelle.</summary>
        public const float LaughTearFrom = 0.82f;
        /// <summary>Décroissance de la charge (1/s) : fixe à la fois la vitesse de montée et la lenteur du séchage.</summary>
        public const float TearDecay = 0.08f;
        const float WateryLo = 0.15f, WateryHi = 1.2f;
        const float TearLo = 1.2f, TearHi = 3.2f;
        public const float BlushRiseS = 1.6f;
        public const float BlushFallS = 9f;
        public const float PupilWidenS = 0.9f;
        public const float PupilNarrowS = 0.45f;

        /// <summary>Les morphs que la physiologie écrit (en <c>raw:</c>) quand le modèle les porte.</summary>
        public static readonly IReadOnlyList<string> Morphs = new[]
        {
            "FaceRed", "EyeWatery", "Tear",
            "EyeDilationLeft", "EyeDilationRight", "EyeConstrictLeft", "EyeConstrictRight",
        };

        public float BlushLevel { get; private set; }
        public float Watery { get; private set; }
        public float Tear { get; private set; }
        public float PupilLevel { get; private set; }
        /// <summary>La charge lacrymale accumulée (ce qui fait monter, puis sécher, les larmes).</summary>
        public float Load { get; private set; }

        string _emotion = Emotions.Neutral;
        float _intensity;

        public void SetEmotion(string emotion, float intensity)
        {
            _emotion = Emotions.IsEmotion(emotion) ? emotion : Emotions.Neutral;
            _intensity = Emotions.Clamp01(intensity);
        }

        /// <summary>Avance l'état de <paramref name="dt"/> secondes (cœur pur, comme <c>stepPhysiology</c>).</summary>
        public void Step(float dt)
        {
            if (!(dt > 0f))
                return;
            float i = _intensity;

            float blushTarget = Get(Blush, _emotion) * SmoothStep(0.2f, 0.9f, i);
            BlushLevel = Approach(BlushLevel, blushTarget, dt, BlushRiseS, BlushFallS);

            float drive = Math.Max(0f, Get(Tears, _emotion) * i - TearThreshold);
            if (_emotion == "amused" || _emotion == "playful")
                drive = Math.Max(drive, (i - LaughTearFrom) * 2.5f);
            Load = Math.Max(0f, Load + (drive - TearDecay * Load) * dt);
            Watery = SmoothStep(WateryLo, WateryHi, Load);
            Tear = SmoothStep(TearLo, TearHi, Load) * 0.9f;

            float pupilTarget = Get(Pupil, _emotion) * i;
            float tau = pupilTarget > PupilLevel ? PupilWidenS : PupilNarrowS;
            PupilLevel = Approach(PupilLevel, pupilTarget, dt, tau, tau);
        }

        /// <summary>
        /// AJOUTE les poids des morphs physiologiques dans <paramref name="output"/> (noms <c>raw:</c>). Les
        /// morphs absents du modèle sont filtrés plus loin, par le visage.
        /// </summary>
        public void Write(IDictionary<string, float> output)
        {
            Add(output, "FaceRed", BlushLevel);
            Add(output, "EyeWatery", Watery * 0.8f);
            Add(output, "Tear", Tear);
            float dilate = Math.Max(0f, PupilLevel);
            float narrow = Math.Max(0f, -PupilLevel);
            Add(output, "EyeDilationLeft", dilate * 0.6f);
            Add(output, "EyeDilationRight", dilate * 0.6f);
            Add(output, "EyeConstrictLeft", narrow * 0.6f);
            Add(output, "EyeConstrictRight", narrow * 0.6f);
        }

        static void Add(IDictionary<string, float> output, string morph, float v)
        {
            if (!(v > 0.0005f))
                return;
            var name = FaceNames.Raw(morph);
            output.TryGetValue(name, out var w);
            output[name] = w + Emotions.Clamp01(v);
        }

        static float Get(IReadOnlyDictionary<string, float> table, string emotion) =>
            table.TryGetValue(emotion, out var v) ? v : 0f;

        internal static float SmoothStep(float lo, float hi, float x)
        {
            float t = Emotions.Clamp01((x - lo) / (hi - lo));
            return t * t * (3f - 2f * t);
        }

        /// <summary>Approche exponentielle avec des constantes de temps distinctes à la montée et à la descente.</summary>
        static float Approach(float current, float target, float dt, float riseS, float fallS)
        {
            float tau = target > current ? riseS : fallS;
            return current + (target - current) * (1f - MathF.Exp(-dt / tau));
        }
    }
}
