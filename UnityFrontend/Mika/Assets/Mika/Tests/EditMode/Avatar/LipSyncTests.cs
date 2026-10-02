using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;

namespace Mika.Avatar.Tests
{
    /// <summary>Le curseur, le recalage, la coarticulation et le plafond d'ouverture — les cas de
    /// <c>frontend/src/audio/__tests__/LipSyncController.test.ts</c>, sur le cœur pur.</summary>
    public class LipSyncTests
    {
        const float Step = 1f / 120f;
        static readonly string[] Presets = { "aa", "ih", "ou", "ee", "oh" };

        static LipSyncModel Start(string text, float msPerChar = 60f, int start = 0)
        {
            var lip = new LipSyncModel();
            lip.Begin(FrenchVisemes.Frames(text, msPerChar, start));
            return lip;
        }

        [Test]
        public void MsPerCharFollowsTheRateBoundedLikeAVoice()
        {
            Assert.AreEqual(SpeechCadence.DefaultMsPerChar, SpeechCadence.MsPerCharForRate(1f));
            Assert.AreEqual(SpeechCadence.DefaultMsPerChar / 2f, SpeechCadence.MsPerCharForRate(2f));
            Assert.AreEqual(SpeechCadence.DefaultMsPerChar * 2f, SpeechCadence.MsPerCharForRate(0.5f));
            Assert.AreEqual(SpeechCadence.DefaultMsPerChar / 2f, SpeechCadence.MsPerCharForRate(10f));
            Assert.AreEqual(SpeechCadence.DefaultMsPerChar, SpeechCadence.MsPerCharForRate(float.NaN));
            Assert.AreEqual(SpeechCadence.DefaultMsPerChar, SpeechCadence.MsPerCharForRate(0f));
        }

        [Test]
        public void TheEstimateAdvancesAndABoundaryReSeatsIt()
        {
            var lip = Start("bonjour tout le monde");
            Assert.AreEqual(0, lip.CurrentCharOffset);
            // 130 ms : passé la fermeture du « b », dans la nasale « on » — une frame pour le digraphe.
            lip.Update(0.13f);
            Assert.AreEqual(1, lip.CurrentCharOffset);
            Assert.AreEqual(Viseme.OH, lip.CurrentViseme);
            Assert.IsTrue(lip.Seek(8));
            Assert.AreEqual(8, lip.CurrentCharOffset);
            Assert.IsTrue(lip.IsSpeaking);
        }

        [Test]
        public void SeekingBackwardWorks()
        {
            var lip = Start("bonjour tout le monde");
            lip.Update(1f);
            Assert.Greater(lip.CurrentCharOffset, 10);
            lip.Seek(3);
            Assert.AreEqual(3, lip.CurrentCharOffset);
        }

        [Test]
        public void SilencesCarryNoIndexAndAreSkippedBySeek()
        {
            var lip = new LipSyncModel();
            lip.Begin(SpeechPlan.Frames("ok [PAUSE:600] oui", 60f));
            Assert.IsTrue(lip.Seek(15));
            Assert.AreEqual(15, lip.CurrentCharOffset);
            Assert.IsTrue(lip.Frames.Any(f => f.CharOffset == -1 && f.Duration == 600f));
        }

        [Test]
        public void CollapsedWhitespaceKeepsTheOriginalIndices()
        {
            var lip = Start("a  b");
            lip.Seek(3);
            Assert.AreEqual(3, lip.CurrentCharOffset);
            // Le double blanc est une seule frame courte, pas deux.
            lip.Seek(1);
            Assert.AreEqual(1, lip.CurrentCharOffset);
            lip.Update(0.035f);
            Assert.AreEqual(3, lip.CurrentCharOffset);
        }

        [Test]
        public void ABoundaryPastTheLastVoicedCharacterLandsOnTheLastVoicedFrame()
        {
            var lip = Start("ok.", 60f, 4);
            Assert.IsTrue(lip.Seek(500));
            Assert.AreEqual(6, lip.CurrentCharOffset);
        }

        [Test]
        public void AnEstimateThatFinishedEarlyIsRevivedByTheNextBoundary()
        {
            var lip = Start("salut");
            lip.Update(5f);
            Assert.IsFalse(lip.IsSpeaking);
            Assert.IsTrue(lip.Seek(3));
            Assert.IsTrue(lip.IsSpeaking);
            Assert.AreEqual(3, lip.CurrentCharOffset);
        }

        [Test]
        public void APlanWithoutPositionsPlaysAndRefusesSeeks()
        {
            var lip = new LipSyncModel();
            lip.Begin(FrenchVisemes.Frames("bonjour", 60f));
            Assert.IsTrue(lip.IsSpeaking);
            Assert.AreEqual(-1, lip.CurrentCharOffset);
            Assert.IsFalse(lip.Seek(2));
            lip.Stop();
            Assert.IsFalse(lip.Seek(0));
        }

        [Test]
        public void TheEstimateLastsAsLongAsTheCharacterBudget()
        {
            var lip = Start("bonjour tout le monde");
            lip.Update(21 * 0.06f - 0.01f);
            Assert.IsTrue(lip.IsSpeaking);
            lip.Update(0.02f);
            Assert.IsFalse(lip.IsSpeaking);
        }

        [Test]
        public void HoldAtEndKeepsSpeakingUntilStopped()
        {
            var lip = Start("salut");
            lip.HoldAtEnd = true;
            lip.Update(5f);
            Assert.IsTrue(lip.IsSpeaking, "une vraie voix plus lente que l'estimation n'est pas coupée");
            lip.Stop();
            Assert.IsFalse(lip.IsSpeaking);
        }

        // ── Rendu ───────────────────────────────────────────────────────────

        sealed class Sample
        {
            public int Offset;
            public Dictionary<string, float> Values;
            public float Get(string name) => Values.TryGetValue(name, out var v) ? v : 0f;
        }

        static string Raw(string morph) => FaceNames.Raw(morph);

        static VisemeRouting AllVisemes() => new VisemeRouting(_ => true, _ => true);

        static List<Sample> Play(LipSyncModel lip, VisemeRouting routing, string text, float load = 0f)
        {
            lip.Begin(FrenchVisemes.Frames(text, 60f, 0));
            var samples = new List<Sample>();
            for (int k = 0; k < 400 && lip.IsSpeaking; k++)
            {
                lip.Update(Step);
                var values = new Dictionary<string, float>();
                routing.Write(lip.Levels, load, values);
                samples.Add(new Sample { Offset = lip.CurrentCharOffset, Values = values });
            }
            return samples;
        }

        static float VisemeSum(Sample s) => VisemeRouting.VrcMorphs().Sum(m => s.Get(Raw(m)));
        static float Peak(List<Sample> samples, string key) => samples.Max(s => s.Get(key));

        [Test]
        public void DrivesTheVrcMorphsWhenPresentLeavingThePresetsAlone()
        {
            var routing = AllVisemes();
            Assert.AreEqual("visemes", routing.Mode);
            var samples = Play(new LipSyncModel(), routing, "papa");
            Assert.Greater(Peak(samples, Raw("vrc.v_aa")), 0.6f);
            Assert.Greater(Peak(samples, Raw("vrc.v_pp")), 0.7f);
            foreach (var p in Presets)
                Assert.AreEqual(0f, Peak(samples, p));
        }

        [Test]
        public void ABilabialActuallyClosesTheMouthBetweenTwoVowels()
        {
            var samples = Play(new LipSyncModel(), AllVisemes(), "papa");
            int opened = samples.FindIndex(s => s.Get(Raw("vrc.v_aa")) > 0.5f);
            Assert.Greater(opened, -1);
            Assert.IsTrue(samples.Skip(opened).Any(s => s.Get(Raw("vrc.v_pp")) > 0.6f && s.Get(Raw("vrc.v_aa")) < 0.35f));
        }

        [Test]
        public void TheVowelAfterAClosureOpensClearly()
        {
            var firstA = Play(new LipSyncModel(), AllVisemes(), "papa").Where(s => s.Offset == 1).ToList();
            Assert.IsTrue(firstA.Any(s => s.Get(Raw("vrc.v_aa")) > 0.72f && s.Get(Raw("vrc.v_pp")) < 0.2f));
        }

        [Test]
        public void TheLipsStartClosingForThePBeforeTheAEnds()
        {
            var firstA = Play(new LipSyncModel(), AllVisemes(), "papa").Where(s => s.Offset == 1).ToList();
            Assert.Greater(firstA.Count, 3);
            float lowest = firstA.Min(s => s.Get(Raw("vrc.v_pp")));
            Assert.Greater(firstA[firstA.Count - 1].Get(Raw("vrc.v_pp")), lowest + 0.1f);
        }

        [Test]
        public void NeverSumsTheVisemesPastOneMouth()
        {
            foreach (var s in Play(new LipSyncModel(), AllVisemes(), "oiseau, champagne, beaucoup !"))
                Assert.LessOrEqual(VisemeSum(s), 1f + 1e-5f);
        }

        [Test]
        public void LeavesRoomForAnEmotionThatAlreadyOpensTheMouth()
        {
            float free = Play(new LipSyncModel(), AllVisemes(), "papa").Max(VisemeSum);
            // Une expression qui ouvre la bouche à fond : la parole garde son plancher, pas plus.
            float openLoad = MouthLoad.Combine(new[] { (1f, MouthLoad.Involvement(new[] { ("MouthOpen4", 1f) })) });
            float shocked = Play(new LipSyncModel(), AllVisemes(), "papa", openLoad).Max(VisemeSum);
            Assert.Greater(free, 0.8f);
            Assert.LessOrEqual(shocked, VisemeRouting.MinVisemeAllowance + 1e-5f);
            Assert.Greater(shocked, 0.3f);
            // Un sourire n'est pas une ouverture : il coûte bien moins.
            float smileLoad = MouthLoad.Combine(new[] { (1f, MouthLoad.Involvement(new[] { ("MouthSmile2", 1f) })) });
            Assert.Greater(Play(new LipSyncModel(), AllVisemes(), "papa", smileLoad).Max(VisemeSum), 0.8f);
        }

        [Test]
        public void ALowerArticulationShrinksOpeningsButKeepsClosures()
        {
            var full = Play(new LipSyncModel(), AllVisemes(), "papa");
            var tiredLip = new LipSyncModel();
            tiredLip.SetArticulation(0.6f);
            var tired = Play(tiredLip, AllVisemes(), "papa");
            Assert.Less(Peak(tired, Raw("vrc.v_aa")), Peak(full, Raw("vrc.v_aa")) * 0.7f);
            Assert.Greater(Peak(tired, Raw("vrc.v_pp")), Peak(full, Raw("vrc.v_pp")) * 0.85f);
        }

        [Test]
        public void FallsBackOnTheFivePresetsWithoutVisemes()
        {
            var routing = new VisemeRouting(_ => false, p => Presets.Contains(p));
            Assert.AreEqual("presets", routing.Mode);
            var lip = new LipSyncModel();
            var samples = Play(lip, routing, "bonjour Mika");
            Assert.Greater(Peak(samples, "oh"), 0.3f);
            Assert.Greater(Peak(samples, "ou"), 0.3f);
            Assert.Greater(Peak(samples, "ih"), 0.3f);
            Assert.Greater(Peak(samples, "aa"), 0.3f);
            // Puis la bouche revient au repos.
            lip.Stop();
            for (int k = 0; k < 120; k++)
                lip.Update(Step);
            var rest = new Dictionary<string, float>();
            routing.Write(lip.Levels, 0f, rest);
            foreach (var p in Presets)
                Assert.Less(rest.TryGetValue(p, out var v) ? v : 0f, 0.01f);
        }

        [Test]
        public void AnIncompleteVisemeSetIsCompletedByThePresets()
        {
            var routing = new VisemeRouting(m => m == "vrc.v_aa" || m == "vrc.v_oh", p => Presets.Contains(p));
            Assert.AreEqual("mixed", routing.Mode);
            var samples = Play(new LipSyncModel(), routing, "papa oui");
            Assert.Greater(Peak(samples, Raw("vrc.v_aa")), 0.6f);
            Assert.Less(Peak(samples, "aa"), 0.35f);
            Assert.Greater(Peak(samples, "ou"), 0.3f);
        }

        [Test]
        public void AllowanceStaysBetweenItsFloorAndOneMouth()
        {
            Assert.AreEqual(1f, VisemeRouting.Allowance(0f));
            Assert.AreEqual(VisemeRouting.MinVisemeAllowance, VisemeRouting.Allowance(1f));
            Assert.AreEqual(1f, VisemeRouting.Allowance(0.3f), 1e-6);
            Assert.AreEqual(0f, MouthLoad.Involvement(new[] { ("EyeBlink_L", 1f), ("BrowInnerUp", 1f) }));
            Assert.AreEqual(1f, MouthLoad.Involvement(new[] { ("JawOpen", 1f) }));
            Assert.AreEqual(MouthLoad.ShapeMorphFactor, MouthLoad.Involvement(new[] { ("MouthSmileLeft", 1f) }), 1e-6);
        }
    }
}
