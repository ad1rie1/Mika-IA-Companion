using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;

namespace Mika.Avatar.Tests
{
    /// <summary>Les tables par émotion couvrent exactement les 29 émotions, et rien d'autre.</summary>
    public class EmotionTableTests
    {
        static readonly string[] Expected =
        {
            "neutral", "happy", "excited", "love", "proud", "grateful", "playful", "amused", "hopeful", "relieved",
            "sad", "angry", "scared", "disgusted", "frustrated", "lonely", "anxious", "bored", "jealous",
            "surprised", "thinking", "confused", "embarrassed", "nostalgic", "dreamy", "determined", "mischievous",
            "curious", "melancholic",
        };

        [Test]
        public void TheCatalogueIsExactlyTheKernels29()
        {
            Assert.AreEqual(29, Emotions.All.Count);
            CollectionAssert.AreEqual(Expected, Emotions.All);
            CollectionAssert.AllItemsAreUnique(Emotions.All);
            Assert.IsFalse(Emotions.IsEmotion("bogus"));
            Assert.IsFalse(Emotions.IsEmotion("Happy"));
            Assert.IsFalse(Emotions.IsEmotion(null));
        }

        static void Complete<T>(IReadOnlyDictionary<string, T> table, string what) =>
            CollectionAssert.AreEquivalent(Expected, table.Keys, what);

        static void Subset<T>(IEnumerable<string> keys, string what) =>
            CollectionAssert.IsSubsetOf(keys.ToList(), Expected, what);

        [Test]
        public void TablesThatMustCoverEveryEmotionDo()
        {
            Complete(Emotions.Valence, "valence");
            Complete(Emotions.Arousal, "activation");
            Complete(EmotionFace.RichMap, "groupes du modèle");
            Complete(EmotionFace.StandardMap, "presets VRM");
            Complete(SpeechCadence.EmotionRate, "débit de voix");
        }

        [Test]
        public void PartialTablesNameOnlyRealEmotions()
        {
            Subset<float>(EmotionFace.OnsetSpeed.Keys, "vitesses de montée");
            Subset<float>(FacePhysiology.Blush.Keys, "rougeur");
            Subset<float>(FacePhysiology.Tears.Keys, "larmes");
            Subset<float>(FacePhysiology.Pupil.Keys, "pupilles");
            Subset<float>(FaceIdleModel.EmotionAccent.Keys, "accents");
            Subset<float>(AttentionDirector.Aversion.Keys, "évitements");
            Subset<float>(GazeModel.EmotionBias.Keys, "biais de regard");
            Subset<float>(BlinkModel.Restless, "clignements agités");
            Subset<float>(BlinkModel.Heavy, "clignements lourds");
        }

        [Test]
        public void EveryEmotionButNeutralHasARichRecipeAndAFallback()
        {
            foreach (var e in Expected.Where(e => e != "neutral"))
            {
                Assert.IsNotEmpty(EmotionFace.RichMap[e], e);
                Assert.IsNotEmpty(EmotionFace.StandardMap[e], e);
            }
        }

        [Test]
        public void ArticulationFollowsArousalAndFatigue()
        {
            Assert.Greater(Emotions.ArticulationFor("excited", 1f), Emotions.ArticulationFor("neutral", 1f));
            Assert.Less(Emotions.ArticulationFor("bored", 1f), Emotions.ArticulationFor("neutral", 1f));
            Assert.Less(Emotions.ArticulationFor("neutral", 1f, 1f), Emotions.ArticulationFor("neutral", 1f, 0f));
            Assert.GreaterOrEqual(Emotions.ArticulationFor("bored", 1f, 1f), 0.6f);
            Assert.LessOrEqual(Emotions.ArticulationFor("excited", 1f), 1.15f);
        }

        [Test]
        public void SleepPhasesResolveUnknownToAwake()
        {
            Assert.AreEqual(SleepPhase.DeepSleep, SleepPhases.Parse("deep_sleep"));
            Assert.AreEqual(SleepPhase.Rem, SleepPhases.Parse("rem"));
            Assert.AreEqual(SleepPhase.LightSleep, SleepPhases.Parse("light_sleep"));
            Assert.AreEqual(SleepPhase.Awake, SleepPhases.Parse("awake"));
            Assert.AreEqual(SleepPhase.Awake, SleepPhases.Parse("hibernating"));
            Assert.AreEqual(SleepPhase.Awake, SleepPhases.Parse(null));
        }
    }

    public class EmotionFaceTests
    {
        static KeyValuePair<string, float> B(string e, float w) => new KeyValuePair<string, float>(e, w);

        [Test]
        public void ASecondaryShowsOnlyWhenItWeighsEnough()
        {
            Assert.IsTrue(Emotions.TrySecondary("happy", new[] { B("happy", 0.6f), B("sad", 0.4f) }, out var e, out var r));
            Assert.AreEqual("sad", e);
            Assert.AreEqual(0.667f, r, 0.01f);
            Assert.IsFalse(Emotions.TrySecondary("happy", new[] { B("happy", 0.9f), B("sad", 0.1f) }, out _, out _));
            Assert.IsFalse(Emotions.TrySecondary("happy", new[] { B("happy", 1f) }, out _, out _));
            Assert.IsFalse(Emotions.TrySecondary("happy", new[] { B("happy", 0.6f), B("bogus", 0.5f) }, out _, out _));
            Assert.IsFalse(Emotions.TrySecondary("happy", null, out _, out _));
        }

        [Test]
        public void AStartleLandsFasterThanSadnessAndEveryOffsetIsSlower()
        {
            Assert.Greater(EmotionFace.OnsetSpeedFor("surprised"), EmotionFace.OnsetSpeedFor("happy"));
            Assert.Greater(EmotionFace.OnsetSpeedFor("happy"), EmotionFace.OnsetSpeedFor("sad"));
            foreach (var name in Emotions.All)
            {
                Assert.Less(EmotionFace.OffsetSpeedFor(name), EmotionFace.OnsetSpeedFor(name), name);
                Assert.GreaterOrEqual(EmotionFace.OffsetSpeedFor(name), EmotionFace.MinOffsetSpeed, name);
            }
        }

        static EmotionFace PresetsOnly() => new EmotionFace(_ => false, _ => true);

        static float After(EmotionFace face, float dt, string name)
        {
            var output = new Dictionary<string, float>();
            face.Step(dt, output);
            return output.TryGetValue(name, out var v) ? v : 0f;
        }

        [Test]
        public void SurpriseIsMostlyThereAfter100msSadnessIsNot()
        {
            var fast = PresetsOnly();
            fast.SetEmotion("surprised", 1f, null);
            Assert.Greater(After(fast, 0.1f, "surprised"), 0.75f);
            var slow = PresetsOnly();
            slow.SetEmotion("sad", 1f, null);
            Assert.Less(After(slow, 0.1f, "sad"), 0.25f);
        }

        [Test]
        public void AnExpressionFadesOutMoreSlowlyThanItCameIn()
        {
            var face = PresetsOnly();
            face.SetEmotion("happy", 1f, null);
            face.Step(0.1f, new Dictionary<string, float>());
            float risen = face.CurrentWeight("happy");
            for (int i = 0; i < 60; i++)
                face.Step(0.05f, new Dictionary<string, float>());
            float before = face.CurrentWeight("happy");
            face.SetEmotion("neutral", 1f, null);
            face.Step(0.1f, new Dictionary<string, float>());
            float fell = before - face.CurrentWeight("happy");
            Assert.Less(fell, risen * 0.75f);
        }

        [Test]
        public void RichGroupsArePlayedThroughTheirCleanCopies()
        {
            var face = new EmotionFace(_ => true, _ => true);
            Assert.AreEqual(28, face.RichCount, "toutes sauf neutral, vide par construction");
            face.SetEmotion("surprised", 1f, null);
            CollectionAssert.AreEquivalent(new[] { "clean:Shocked" }, face.Targets.Keys);
            Assert.AreEqual(0.9f, face.Targets["clean:Shocked"], 1e-5f);
        }

        [Test]
        public void AModelMissingAGroupDegradesThatEmotionOnly()
        {
            var face = new EmotionFace(g => g != "Shocked", _ => true);
            Assert.AreEqual(27, face.RichCount);
            CollectionAssert.AreEquivalent(new[] { "surprised" }, face.RecipeOf("surprised").Keys);
            CollectionAssert.AreEquivalent(new[] { "clean:Smile1" }, face.RecipeOf("happy").Keys);
        }

        [Test]
        public void TheSecondaryTransparesAtAReducedShare()
        {
            var face = new EmotionFace(_ => true, _ => true);
            face.SetEmotion("happy", 1f, new[] { B("happy", 0.6f), B("sad", 0.4f) });
            float ratio = 0.4f / 0.6f;
            Assert.AreEqual(1f * (1f - 0.25f * ratio), face.Targets["clean:Smile1"], 1e-4f);
            Assert.AreEqual(0.85f * ratio * Emotions.SecondaryShare, face.Targets["clean:Sad1"], 1e-4f);
            Assert.Less(face.Targets["clean:Sad1"], face.Targets["clean:Smile1"]);
        }

        [Test]
        public void TirednessWeighsTheLidsOnlyBelowTheEnergyThreshold()
        {
            var face = new EmotionFace(_ => true, _ => true);
            face.SetEnergy(0.9f);
            for (int i = 0; i < 100; i++)
                face.Step(0.05f, new Dictionary<string, float>());
            Assert.AreEqual(0f, face.CurrentWeight("clean:Sleepy"));
            face.SetEnergy(0.1f);
            for (int i = 0; i < 100; i++)
                face.Step(0.05f, new Dictionary<string, float>());
            Assert.AreEqual(EmotionFace.TiredMax, face.CurrentWeight("clean:Sleepy"), 0.01f);
        }

        [Test]
        public void StrippedMorphsAreSymbolsAndGaze()
        {
            Assert.IsTrue(FaceNames.IsStripped("Tear"));
            Assert.IsTrue(FaceNames.IsStripped("Eye@@"));
            Assert.IsTrue(FaceNames.IsStripped("FaceSweat"));
            Assert.IsTrue(FaceNames.IsStripped("eyeLookUpLeft"));
            Assert.IsTrue(FaceNames.IsStripped("EyeLookInRight"));
            Assert.IsFalse(FaceNames.IsStripped("BrowInnerUp"));
            Assert.IsFalse(FaceNames.IsStripped("MouthSmileLeft"));
            Assert.IsFalse(FaceNames.IsStripped("EyeBlinkLeft"));
        }
    }

    /// <summary>Les cas de <c>faceHuman.test.ts</c> : la physiologie a ses propres horloges.</summary>
    public class PhysiologyTests
    {
        static FacePhysiology Hold(string emotion, float intensity, float seconds, FacePhysiology state = null)
        {
            state ??= new FacePhysiology();
            state.SetEmotion(emotion, intensity);
            for (float t = 0f; t < seconds; t += 1f / 30f)
                state.Step(1f / 30f);
            return state;
        }

        [Test]
        public void TearsWellUpNeverOnTheFirstSecondOnlyAfterStrongSadnessLasts()
        {
            Assert.AreEqual(0f, Hold("sad", 0.95f, 1f).Tear);
            var s = Hold("sad", 0.95f, 10f);
            Assert.Greater(s.Watery, 0.9f);
            Assert.Greater(s.Tear, 0.4f);
        }

        [Test]
        public void AMildSadnessHoweverLongNeverCries()
        {
            var s = Hold("sad", 0.5f, 60f);
            Assert.AreEqual(0f, s.Tear);
            Assert.Less(s.Watery, 0.5f);
        }

        [Test]
        public void LaughingToTearsOnlyAtTheTopOfTheScale()
        {
            Assert.AreEqual(0f, Hold("amused", 0.7f, 20f).Watery);
            Assert.Greater(Hold("amused", 1f, 8f).Watery, 0.3f);
        }

        [Test]
        public void TearsDrySlowlyAfterTheSadnessPasses()
        {
            var s = Hold("sad", 0.95f, 10f);
            float before = s.Watery;
            Hold("neutral", 0.5f, 3f, s);
            Assert.Greater(s.Watery, before * 0.5f);
            Hold("neutral", 0.5f, 40f, s);
            Assert.Less(s.Watery, 0.05f);
        }

        [Test]
        public void ABlushComesInOverASecondOrTwoAndLeavesMuchMoreSlowly()
        {
            var s = Hold("embarrassed", 0.9f, 0.3f);
            Assert.Less(s.BlushLevel, 0.3f);
            Hold("embarrassed", 0.9f, 5f, s);
            float peak = s.BlushLevel;
            Assert.Greater(peak, 0.7f);
            Hold("happy", 0.6f, 2f, s);
            Assert.Greater(s.BlushLevel, peak * 0.7f);
        }

        [Test]
        public void PupilsWidenWithLoveAndFearNarrowWithAnger()
        {
            Assert.Greater(Hold("love", 0.9f, 3f).PupilLevel, 0.3f);
            Assert.Greater(Hold("scared", 0.9f, 3f).PupilLevel, 0.3f);
            Assert.Less(Hold("angry", 0.9f, 3f).PupilLevel, -0.2f);
        }

        [Test]
        public void WritesOnlyItsOwnRawMorphs()
        {
            var s = Hold("sad", 0.95f, 10f);
            var output = new Dictionary<string, float>();
            s.Write(output);
            Assert.IsTrue(output.Keys.All(k => k.StartsWith(FaceNames.RawPrefix)));
            Assert.IsTrue(output.ContainsKey("raw:Tear"));
            Assert.IsTrue(output.Values.All(v => v >= 0f && v <= 1f));
        }
    }

    public class BlinkTests
    {
        /// <summary>Un aléa déterministe (générateur congruentiel), pour que les tests ne clignotent pas.</summary>
        static Func<float> Seeded(int seed)
        {
            var rng = new Random(seed);
            return () => (float)rng.NextDouble();
        }

        static int CountBlinks(string emotion, float seconds, bool speaking = false, float fatigue = 0f)
        {
            var blink = new BlinkModel(Seeded(7));
            for (float t = 0f; t < seconds; t += 1f / 60f)
                blink.Step(1f / 60f, emotion, fatigue, speaking, SleepPhase.Awake, 0f);
            return blink.BlinkCount;
        }

        [Test]
        public void SheBlinksEveryFewSecondsAwake()
        {
            int n = CountBlinks("neutral", 120f);
            Assert.Greater(n, 120f / 7f);
            Assert.Less(n, 120f / 2f);
        }

        [Test]
        public void AlertEmotionsBlinkMoreOftenThanHeavyOnesAndSpeechAddsSome()
        {
            Assert.Greater(CountBlinks("anxious", 300f), CountBlinks("melancholic", 300f));
            Assert.Greater(CountBlinks("neutral", 300f, speaking: true), CountBlinks("neutral", 300f));
            Assert.Greater(CountBlinks("neutral", 300f), CountBlinks("neutral", 300f, fatigue: 1f));
        }

        [Test]
        public void ABlinkClosesFullyAndReopens()
        {
            var blink = new BlinkModel(Seeded(3));
            float max = 0f;
            for (float t = 0f; t < 10f; t += 1f / 240f)
                max = Math.Max(max, blink.Step(1f / 240f, "neutral", 0f, false, SleepPhase.Awake, 0f));
            Assert.AreEqual(1f, max, 0.05f);
        }

        [Test]
        public void SleepClosesTheEyesGentlyAndWakingOpensThem()
        {
            var blink = new BlinkModel(Seeded(1));
            float v = blink.Step(0.05f, "neutral", 0f, false, SleepPhase.DeepSleep, 0f);
            Assert.Less(v, 0.5f, "les paupières se ferment en douceur, elles ne claquent pas");
            for (int i = 0; i < 100; i++)
                v = blink.Step(0.05f, "neutral", 0f, false, SleepPhase.DeepSleep, 0f);
            Assert.AreEqual(1f, v, 0.01f);
            // Réveil : la fermeture redescend en ~1 s, puis le cycle normal reprend — et le premier clignement
            // n'arrive pas avant 3 s, d'où la mesure à 3 s.
            v = blink.Step(0.05f, "neutral", 0f, false, SleepPhase.Awake, 0f);
            Assert.Greater(v, 0.5f, "on ne rouvre pas les yeux d'un coup");
            for (int i = 0; i < 60; i++)
                v = blink.Step(0.05f, "neutral", 0f, false, SleepPhase.Awake, 0f);
            Assert.Less(v, 0.05f);
        }

        [Test]
        public void RemLidsFlickerButStayAlmostClosed()
        {
            var blink = new BlinkModel(Seeded(1));
            float lo = 1f, hi = 0f;
            for (int i = 0; i < 400; i++)
            {
                float v = blink.Step(0.05f, "neutral", 0f, false, SleepPhase.Rem, 0f);
                if (i > 100)
                {
                    lo = Math.Min(lo, v);
                    hi = Math.Max(hi, v);
                }
            }
            Assert.GreaterOrEqual(lo, 0.7f);
            Assert.LessOrEqual(hi, 1f);
            Assert.Greater(hi - lo, 0.02f, "le paradoxal frémit");
        }
    }

    public class FaceIdleTests
    {
        [Test]
        public void MicroDriftAndAccentNeverPushAShapePastOne()
        {
            var idle = new FaceIdleModel(_ => true);
            foreach (var emotion in Emotions.All)
            {
                for (int i = 0; i < 200; i++)
                {
                    var output = new Dictionary<string, float>();
                    idle.Step(0.05f, emotion, 1f, true, false, 1f, 1f, output);
                    foreach (var kv in output)
                        Assert.That(kv.Value, Is.InRange(0f, 1f), $"{emotion}/{kv.Key}");
                }
            }
        }

        [Test]
        public void NeutralStillMovesAndSleepAlmostStills()
        {
            var awake = new FaceIdleModel(_ => true);
            var asleep = new FaceIdleModel(_ => true);
            float awakeSum = 0f, asleepSum = 0f;
            for (int i = 0; i < 100; i++)
            {
                var a = new Dictionary<string, float>();
                awake.Step(0.05f, "neutral", 0.5f, false, false, 0f, 0f, a);
                var b = new Dictionary<string, float>();
                asleep.Step(0.05f, "neutral", 0.5f, false, true, 0f, 0f, b);
                awakeSum += a.Values.Sum();
                asleepSum += b.Values.Sum();
            }
            Assert.Greater(awakeSum, 0f);
            Assert.Less(asleepSum, awakeSum * 0.5f);
        }

        [Test]
        public void OnlyShapesTheModelCarriesAreWritten()
        {
            var idle = new FaceIdleModel(n => n == "BrowInnerUp");
            var output = new Dictionary<string, float>();
            idle.Step(0.05f, "sad", 1f, false, false, 0f, 0f, output);
            CollectionAssert.AreEquivalent(new[] { "BrowInnerUp" }, output.Keys);
        }
    }
}
