using System;
using System.Collections.Generic;

namespace Mika.Avatar
{
    /// <summary>
    /// Clignements, fermeture des yeux dans le sommeil et frémissement du sommeil paradoxal, sur la seule
    /// expression <c>blink</c>. Portage de <c>frontend/Web/src/vtuber/animation/BlinkController.ts</c>.
    /// </summary>
    /// <remarks>
    /// Trois clignements (rapide / double / doux), une cadence modulée par l'émotion et la fatigue, un peu plus
    /// rapide en parlant, et un clignement qui accompagne parfois un grand saut du regard — un seul motif de
    /// clignement en boucle est l'un des signes les plus nets d'un rig, et le clignement est presque tout ce
    /// que fait le visage quand aucune émotion n'est active. Pur : l'aléa est injectable.
    /// </remarks>
    public sealed class BlinkModel
    {
        readonly struct Shape
        {
            public readonly float Close, Hold, Open;
            public Shape(float close, float hold, float open) { Close = close; Hold = hold; Open = open; }
            public float Total => Close + Hold + Open;
        }

        /// <summary>Un vrai clignement ferme vite et rouvre plus lentement.</summary>
        static readonly Shape Quick = new Shape(0.055f, 0.02f, 0.09f);
        static readonly Shape Soft = new Shape(0.13f, 0.07f, 0.2f);

        public const float EaseSeconds = 1.2f;
        public const float GazeBlinkMinShift = 0.12f;
        public const float GazeBlinkP = 0.35f;
        public const float GazeBlinkRefractoryS = 0.6f;

        /// <summary>Les émotions en alerte clignent plus souvent…</summary>
        public static readonly IReadOnlyCollection<string> Restless = new HashSet<string>
        {
            "excited", "scared", "anxious", "surprised", "angry", "frustrated",
        };

        /// <summary>…les émotions basses clignent plus lentement et préfèrent le clignement long et lourd.</summary>
        public static readonly IReadOnlyCollection<string> Heavy = new HashSet<string>
        {
            "bored", "dreamy", "melancholic", "sad", "lonely", "relieved", "nostalgic",
        };

        /// <summary>Fermeture visée par phase : éveillée, le cycle de clignement mène ; endormie, les yeux restent fermés.</summary>
        public static float PhaseClosure(SleepPhase phase)
        {
            switch (phase)
            {
                case SleepPhase.LightSleep: return 0.85f;
                case SleepPhase.Rem: return 0.95f;
                case SleepPhase.DeepSleep: return 1f;
                default: return 0f;
            }
        }

        readonly Func<float> _random;
        float _blinkTimer;
        float _nextBlinkAt;
        float _eyeClosure;
        float _remTimer;
        bool _blinking;
        float _elapsed;
        Shape _shape = Quick;
        bool _doublePending;
        bool _secondBeatArmed;

        /// <summary>Combien de clignements ont commencé — tests et debug.</summary>
        public int BlinkCount { get; private set; }

        /// <summary>La valeur écrite sur <c>blink</c> à ce pas.</summary>
        public float Value { get; private set; }

        public BlinkModel(Func<float> random = null)
        {
            _random = random ?? DefaultRandom();
            _nextBlinkAt = 3f + _random() * 2f;
        }

        /// <param name="dt">Pas en secondes.</param>
        /// <param name="emotion">Émotion courante (cadence et forme).</param>
        /// <param name="fatigue">0…1 : des paupières fatiguées clignent plus lentement et plus longtemps.</param>
        /// <param name="speaking">On cligne plus en parlant.</param>
        /// <param name="phase">Phase de sommeil.</param>
        /// <param name="gazeShift">Saut du regard décidé à ce pas (rad).</param>
        public float Step(float dt, string emotion, float fatigue, bool speaking, SleepPhase phase, float gazeShift)
        {
            if (!(dt > 0f))
                dt = 0f;
            float target = PhaseClosure(phase);
            float rate = Math.Min(1f, dt / EaseSeconds * 4f);
            float diff = target - _eyeClosure;
            _eyeClosure = Math.Abs(diff) < 0.0005f ? target : _eyeClosure + diff * rate;

            if (phase == SleepPhase.Awake)
            {
                // Fermeture résiduelle juste après le réveil : elle redescend avant que le cycle normal reprenne.
                if (_eyeClosure > 0.02f)
                    return Value = _eyeClosure;
                return Value = StepBlink(dt, emotion, fatigue, speaking, gazeShift);
            }

            float value = _eyeClosure;
            // Le frémissement ne commence qu'une fois les paupières vraiment près de la fermeture du paradoxal :
            // son plancher de 0,7 claquerait sinon les yeux sur une transition directe éveil → paradoxal.
            if (phase == SleepPhase.Rem && _eyeClosure > 0.75f)
            {
                _remTimer += dt;
                value += MathF.Sin(_remTimer * 8f) * 0.04f;
                value = Math.Max(0.7f, Math.Min(1f, value));
            }
            return Value = value;
        }

        float StepBlink(float dt, string emotion, float fatigue, bool speaking, float gazeShift)
        {
            if (!_blinking)
            {
                _blinkTimer += dt;
                if (_blinkTimer >= _nextBlinkAt)
                    StartBlink(emotion, fatigue, false);
                else if (gazeShift >= GazeBlinkMinShift && _blinkTimer >= GazeBlinkRefractoryS && _random() < GazeBlinkP)
                    StartBlink(emotion, fatigue, true);
                else
                    return 0f;
            }

            _elapsed += dt;
            var s = _shape;
            float value;
            if (_elapsed < s.Close)
                value = _elapsed / s.Close;
            else if (_elapsed < s.Close + s.Hold)
                value = 1f;
            else if (_elapsed < s.Total)
                value = 1f - (_elapsed - s.Close - s.Hold) / s.Open;
            else
            {
                value = 0f;
                _blinking = false;
                _blinkTimer = 0f;
                if (_doublePending)
                {
                    // Second temps d'un double clignement : un court écart, puis un autre rapide. Le drapeau passe
                    // la main à _secondBeatArmed au lieu d'être consommé : StartBlink doit savoir, 70 ms plus tard,
                    // que ce clignement-là EST le second temps et non un nouveau tirage.
                    _doublePending = false;
                    _secondBeatArmed = true;
                    _nextBlinkAt = 0.07f;
                }
                else
                {
                    _nextBlinkAt = SampleInterval(emotion, fatigue, speaking);
                }
            }
            return Emotions.Clamp01(value);
        }

        void StartBlink(string emotion, float fatigue, bool forcedQuick)
        {
            _blinking = true;
            _elapsed = 0f;
            _blinkTimer = 0f;
            BlinkCount++;
            if (forcedQuick)
            {
                // Un clignement porté par un saut du regard est rapide et ne se double jamais.
                _shape = Quick;
                _doublePending = false;
                return;
            }
            if (_secondBeatArmed)
            {
                // Rapide, et surtout pas de nouveau tirage : un second temps DOUX 70 ms après un rapide se lit
                // comme un bug, pas comme un tic.
                _secondBeatArmed = false;
                _shape = Quick;
                return;
            }
            bool heavy = (emotion != null && ((HashSet<string>)Heavy).Contains(emotion)) || fatigue > 0.5f;
            float roll = _random();
            if (roll < (heavy ? 0.45f : 0.15f))
                _shape = Soft;
            else
            {
                _shape = Quick;
                // Doubles seulement sur des clignements rapides, et pas aux paupières lourdes.
                _doublePending = !heavy && roll > 0.85f;
            }
        }

        float SampleInterval(string emotion, float fatigue, bool speaking)
        {
            float b = 2.5f + _random() * 3f;
            if (emotion != null && ((HashSet<string>)Restless).Contains(emotion))
                b *= 0.65f;
            else if (emotion != null && ((HashSet<string>)Heavy).Contains(emotion))
                b *= 1.3f;
            b *= 1f + 0.3f * Emotions.Clamp01(fatigue);
            if (speaking)
                b *= 0.85f;
            return b;
        }

        internal static Func<float> DefaultRandom()
        {
            var rng = new Random();
            return () => (float)rng.NextDouble();
        }
    }
}
