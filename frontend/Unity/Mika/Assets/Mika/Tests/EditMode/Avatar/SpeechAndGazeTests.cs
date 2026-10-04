using System;
using System.Collections.Generic;
using System.Linq;
using NUnit.Framework;

namespace Mika.Avatar.Tests
{
    public class SpeechPlanTests
    {
        [Test]
        public void ProsodicTokensAreSilencesNotWords()
        {
            const string text = "Hmm... [SIGH] bon écoute, [PAUSE:400] je crois que oui.";
            var segments = SpeechPlan.Parse(text);
            Assert.AreEqual(5, segments.Count);
            Assert.IsTrue(segments[0].IsSpeech);
            Assert.AreEqual("Hmm...", segments[0].Text);
            Assert.AreEqual(0, segments[0].Start);
            Assert.AreEqual("sigh", segments[1].Cue);
            Assert.AreEqual(SpeechPlan.CueDurationMs["sigh"], segments[1].SilenceMs);
            Assert.AreEqual("bon écoute,", segments[2].Text);
            Assert.AreEqual(text.IndexOf("bon", StringComparison.Ordinal), segments[2].Start);
            Assert.IsNull(segments[3].Cue);
            Assert.AreEqual(400f, segments[3].SilenceMs);
            Assert.AreEqual(text.IndexOf("je", StringComparison.Ordinal), segments[4].Start);
        }

        [Test]
        public void PausesAreBoundedAndDefaulted()
        {
            Assert.AreEqual(SpeechPlan.DefaultPauseMs, SpeechPlan.Parse("[PAUSE]").Single().SilenceMs);
            Assert.AreEqual(50f, SpeechPlan.Parse("[PAUSE:1]").Single().SilenceMs);
            Assert.AreEqual(3000f, SpeechPlan.Parse("[pause:99999]").Single().SilenceMs);
            Assert.AreEqual("laugh", SpeechPlan.Parse("[laugh]").Single().Cue);
            Assert.AreEqual("breath", SpeechPlan.Parse("[BREATH]").Single().Cue);
        }

        [Test]
        public void TheMouthNeverArticulatesATokenAndTheTimeAddsUp()
        {
            const string text = "oui [LAUGH] non";
            var frames = SpeechPlan.Frames(text, 60f);
            int open = text.IndexOf('[');
            int close = text.IndexOf(']');
            Assert.IsFalse(frames.Any(f => f.CharOffset >= open && f.CharOffset <= close));
            float expected = (60f * FrenchVisemes.SpokenLength("oui") + 900f + 60f * FrenchVisemes.SpokenLength("non")) / 1000f;
            Assert.AreEqual(expected, SpeechPlan.DurationSeconds(frames), 1e-4f);
            Assert.AreEqual("oui non", SpeechPlan.Strip(text));
        }

        [Test]
        public void CuesAreReportedWhenTheirSilenceIsReached()
        {
            var lip = new LipSyncModel();
            lip.Begin(SpeechPlan.Frames("[BREATH] oui [SIGH] bon", 60f));
            var cues = new List<string>();
            lip.DrainCues(cues);
            CollectionAssert.AreEqual(new[] { "breath" }, cues, "un repère en tête part tout de suite");
            cues.Clear();
            lip.Update(0.35f + 0.05f);
            lip.DrainCues(cues);
            Assert.IsEmpty(cues);
            for (int i = 0; i < 20; i++)
                lip.Update(0.05f);
            lip.DrainCues(cues);
            CollectionAssert.AreEqual(new[] { "sigh" }, cues);
            lip.DrainCues(cues);
            Assert.AreEqual(1, cues.Count, "vidés à la lecture");
        }

        [Test]
        public void EmptyTextHasNothingToSay()
        {
            Assert.IsEmpty(SpeechPlan.Frames("", 60f));
            Assert.IsEmpty(SpeechPlan.Frames("   ", 60f));
            Assert.IsEmpty(SpeechPlan.Parse(null));
        }
    }

    public class SpeechBeatsTests
    {
        [Test]
        public void AQuestionEndsOnItsLastWord()
        {
            const string text = "Tu viens ce soir ?";
            var beats = SpeechBeats.Plan(text);
            Assert.AreEqual(BeatKind.PhraseStart, beats[0].Kind);
            var last = beats[beats.Count - 1];
            Assert.AreEqual(BeatKind.Question, last.Kind);
            Assert.AreEqual(text.IndexOf("soir", StringComparison.Ordinal), last.At);
        }

        [Test]
        public void CapitalsAndIntensifiersAreEmphasis()
        {
            const string text = "Bon, je suis VRAIMENT contente de te voir.";
            var beats = SpeechBeats.Plan(text);
            Assert.IsTrue(beats.Any(b => b.Kind == BeatKind.Emphasis && b.At == text.IndexOf("VRAIMENT", StringComparison.Ordinal) && b.Strength == 1f));
            Assert.IsTrue(beats.Any(b => b.Kind == BeatKind.Pause && b.At == text.IndexOf(',')));
        }

        [Test]
        public void ProsodicTokensAreMaskedButIndicesStay()
        {
            const string text = "[SIGH] Bon. Allez !";
            var beats = SpeechBeats.Plan(text);
            Assert.IsTrue(beats.All(b => b.At >= text.IndexOf("Bon", StringComparison.Ordinal)));
            Assert.AreEqual(BeatKind.Emphasis, beats.Last().Kind);
            Assert.AreEqual(text.IndexOf("Allez", StringComparison.Ordinal), beats.Last().At);
        }

        [Test]
        public void BrowsFlashOnEmphasisAndHoldOnAQuestion()
        {
            const string text = "C'est GÉNIAL, tu crois ?";
            var brows = new SpeechBrows();
            brows.Begin(SpeechBeats.Plan(text));
            var fired = new List<SpeechBeat>();
            brows.Step(0.02f, text.IndexOf("GÉNIAL", StringComparison.Ordinal), true, 1f, fired);
            Assert.Greater(brows.Emphasis, 0.8f);
            for (int i = 0; i < 30; i++)
                brows.Step(0.02f, text.IndexOf("crois", StringComparison.Ordinal), true, 1f, fired);
            Assert.Greater(brows.Question, 0.9f);
            Assert.IsTrue(fired.Any(b => b.Kind == BeatKind.Question));
            for (int i = 0; i < 150; i++)
                brows.Step(0.02f, -1, false, 1f, fired);
            Assert.Less(brows.Question, 0.05f);
            Assert.Less(brows.Emphasis, 0.05f);
        }
    }

    public class AttentionTests
    {
        static Func<float> Seeded(int seed)
        {
            var rng = new Random(seed);
            return () => (float)rng.NextDouble();
        }

        static AttentionInput Input(string emotion = "neutral") => new AttentionInput
        {
            Emotion = emotion,
            Intensity = 0.7f,
            SleepPhase = SleepPhase.Awake,
            Reachable = true,
            ViewerAngle = 0.2f,
        };

        [Test]
        public void AsleepNobodyIsLookedAt()
        {
            var director = new AttentionDirector(Seeded(1));
            var input = Input();
            input.SleepPhase = SleepPhase.DeepSleep;
            var intent = director.Update(0.05f, input);
            Assert.AreEqual(AttentionState.Asleep, intent.State);
            Assert.AreEqual(0f, intent.Contact);
        }

        [Test]
        public void APendingReplyIsThoughtAboutUpAndToTheSide()
        {
            var director = new AttentionDirector(Seeded(2));
            var input = Input();
            input.ReplyPending = true;
            var intent = director.Update(0.05f, input);
            Assert.AreEqual(AttentionState.Thinking, intent.State);
            Assert.AreEqual(AttentionDirector.ThinkingContact, intent.Contact);
            Assert.Less(intent.Offset.Pitch, 0f, "en haut");
            // …mais une phrase en cours se finit d'abord.
            input.Speaking = true;
            Assert.AreNotEqual(AttentionState.Thinking, director.Update(0.05f, input).State);
        }

        [Test]
        public void AMurmurToHerselfIsNotForYou()
        {
            var director = new AttentionDirector(Seeded(3));
            var input = Input();
            input.Speaking = true;
            input.InnerVoice = true;
            var intent = director.Update(0.05f, input);
            Assert.AreEqual(AttentionState.Inner, intent.State);
            Assert.AreEqual(AttentionDirector.InnerContact, intent.Contact);
            Assert.Greater(intent.Offset.Pitch, 0f, "en bas");
        }

        [Test]
        public void NobodyInReachMeansForwardGaze()
        {
            var director = new AttentionDirector(Seeded(4));
            var input = Input();
            input.Reachable = false;
            var intent = director.Update(0.05f, input);
            Assert.AreEqual(AttentionState.Away, intent.State);
            Assert.AreEqual(0f, intent.Contact);
        }

        [Test]
        public void EmbarrassmentLooksAwayMoreOftenThanLove()
        {
            int Averted(string emotion)
            {
                var director = new AttentionDirector(Seeded(5));
                int n = 0;
                for (int i = 0; i < 600 * 60; i++)
                {
                    var input = Input(emotion);
                    input.Listening = true; // quelqu'un est là et tape : pas de rêverie, des évitements de conversation
                    if (director.Update(1f / 60f, input).State == AttentionState.Avert)
                        n++;
                }
                return n;
            }
            Assert.Greater(Averted("embarrassed"), Averted("love") * 2);
        }

        [Test]
        public void SaccadesAreStepsAndReportTheirJump()
        {
            var director = new AttentionDirector(Seeded(6));
            float shifts = 0f;
            int jumps = 0;
            for (int i = 0; i < 600; i++)
            {
                var intent = director.Update(1f / 60f, Input());
                if (intent.Shift > 0f)
                {
                    jumps++;
                    shifts += intent.Shift;
                }
            }
            Assert.Greater(jumps, 0);
            Assert.Less(jumps, 600 / 10, "un saut de temps en temps, pas un tremblement continu");
        }

        [Test]
        public void TheEyesStayWithinTheirRangeAndLandFast()
        {
            var gaze = new GazeModel();
            var intent = new GazeIntent { Contact = 1f };
            var viewer = new GazeAngles(0.9f, -1.2f);
            GazeAngles g = default;
            for (int i = 0; i < 10; i++)
                g = gaze.Step(1f / 60f, intent, "neutral", 0.5f, false, viewer);
            Assert.AreEqual(GazeModel.EyeMaxPitch, g.Pitch, 0.01f);
            Assert.AreEqual(-GazeModel.EyeMaxYaw, g.Yaw, 0.01f);
            // En deux images à 60 Hz l'œil a fait l'essentiel du chemin : un saut, pas un glissement.
            var fresh = new GazeModel();
            fresh.Step(1f / 60f, intent, "neutral", 0.5f, false, new GazeAngles(0f, 0.2f));
            var after = fresh.Step(1f / 60f, intent, "neutral", 0.5f, false, new GazeAngles(0f, 0.2f));
            Assert.Greater(after.Yaw, 0.2f * 0.6f);
        }

        [Test]
        public void AsleepTheEyesRestSlightlyDown()
        {
            var gaze = new GazeModel();
            GazeAngles g = default;
            for (int i = 0; i < 30; i++)
                g = gaze.Step(1f / 60f, default, "neutral", 0.5f, true, new GazeAngles(0f, 0.3f));
            Assert.AreEqual(GazeModel.EyeSleepPitch, g.Pitch, 1e-3f);
            Assert.AreEqual(0f, g.Yaw, 1e-3f);
        }

        [Test]
        public void TheInverseCurveTurnsTheEyeByTheWantedAngle()
        {
            // Courbe VRM linéaire : 90° d'entrée → 10° d'œil. Pour 5° d'œil, il faut 45° d'entrée.
            Assert.AreEqual(45f, GazeModel.InverseCurve(5f, 90f, 10f), 1e-4f);
            Assert.AreEqual(-45f, GazeModel.InverseCurve(-5f, 90f, 10f), 1e-4f);
            // Au-delà de la courbe de l'auteur, l'œil s'arrête à sa borne.
            Assert.AreEqual(90f, GazeModel.InverseCurve(30f, 90f, 10f), 1e-4f);
            Assert.AreEqual(0f, GazeModel.InverseCurve(5f, 90f, 0f));
        }
    }
}
