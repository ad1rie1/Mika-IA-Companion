using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using NUnit.Framework;

namespace Mika.Avatar.Tests
{
    /// <summary>Les cas de <c>frontend/src/audio/__tests__/frenchVisemes.test.ts</c>, portés tels quels : le web
    /// et Unity doivent articuler la même bouche sur le même texte.</summary>
    public class FrenchVisemesTests
    {
        static List<Viseme> Visemes(IEnumerable<VisemeFrame> frames) =>
            frames.Where(f => f.Viseme != Viseme.Sil).Select(f => f.Viseme).ToList();

        static double TotalMs(IEnumerable<VisemeFrame> frames) => frames.Sum(f => (double)f.Duration);

        static int Collapsed(string text) => Regex.Replace(text, @"\s+", " ").Length;

        [TestCase("eau", "o")]
        [TestCase("oiseau", "w a z o")]
        [TestCase("champagne", "S a~ p a J")]
        [TestCase("ils mangent", "i l m a~ Z")]
        [TestCase("beaucoup", "b o k u")]
        [TestCase("qu'est-ce que", "k E s @ k @")]
        [TestCase("Mika", "m i k a")]
        [TestCase("bonjour tout le monde", "b o~ Z u R t u l @ m o~ d")]
        [TestCase("c'est", "s E")]
        [TestCase("aujourd'hui", "o Z u R d H i")]
        [TestCase("les enfants", "l e a~ f a~")]
        [TestCase("fille", "f i j")]
        [TestCase("ville", "v i l")]
        [TestCase("nation", "n a s j o~")]
        [TestCase("question", "k E s t j o~")]
        [TestCase("photo", "f o t o")]
        [TestCase("garçon", "g a R s o~")]
        [TestCase("guitare", "g i t a R")]
        [TestCase("taxi", "t a k s i")]
        [TestCase("homme", "o m")]
        [TestCase("une", "y n")]
        [TestCase("bien", "b j e~")]
        [TestCase("science", "s j a~ s")]
        [TestCase("pain", "p e~")]
        [TestCase("loin", "l w e~")]
        [TestCase("oui", "w i")]
        [TestCase("étaient", "e t E")]
        [TestCase("parlent", "p a R l")]
        [TestCase("souvent", "s u v a~")]
        [TestCase("manger", "m a~ Z e")]
        [TestCase("samedi", "s a m d i")]
        [TestCase("petit", "p @ t i")]
        [TestCase("SMS", "E s E m E s")]
        public void GraphemeToPhoneme(string text, string expected) =>
            Assert.AreEqual(expected, FrenchVisemes.PhonemeString(text));

        [Test]
        public void NumbersAreReadInFull()
        {
            Assert.AreEqual("quarante-deux", FrenchVisemes.SpellNumber("42"));
            Assert.AreEqual("soixante et onze", FrenchVisemes.SpellNumber("71"));
            Assert.AreEqual("quatre-vingts", FrenchVisemes.SpellNumber("80"));
            Assert.AreEqual("deux mille vingt-six", FrenchVisemes.SpellNumber("2026"));
            Assert.AreEqual("zéro six un deux", FrenchVisemes.SpellNumber("0612"));
            Assert.AreEqual("k a R a~ t d 2", FrenchVisemes.PhonemeString("42"));
            Assert.AreEqual("d 2 m i l v e~ s i s", FrenchVisemes.PhonemeString("2026"));
            Assert.AreEqual("v e~ e e~", FrenchVisemes.PhonemeString("21"));
        }

        [Test]
        public void DigraphsAreOneMouthShape()
        {
            CollectionAssert.AreEqual(new[] { Viseme.OH }, Visemes(FrenchVisemes.Frames("eau", 60)));
            CollectionAssert.DoesNotContain(Visemes(FrenchVisemes.Frames("qu'est-ce que", 60)), Viseme.OU);
            CollectionAssert.AreEqual(new[] { Viseme.CH, Viseme.AA, Viseme.PP, Viseme.AA, Viseme.NN },
                Visemes(FrenchVisemes.Frames("champagne", 60)));
        }

        [Test]
        public void SilentLettersMakeNoShape()
        {
            var mangent = Visemes(FrenchVisemes.Frames("ils mangent", 60));
            Assert.AreEqual(Viseme.CH, mangent[mangent.Count - 1]);
            CollectionAssert.AreEqual(new[] { Viseme.NN, Viseme.E }, Visemes(FrenchVisemes.Frames("les", 60)));
        }

        [Test]
        public void BilabialsCloseTheLipsLabiodentalsBite()
        {
            foreach (var word in new[] { "papa", "beaucoup", "maman", "bonjour" })
                Assert.AreEqual(Viseme.PP, Visemes(FrenchVisemes.Frames(word, 60))[0], word);
            Assert.AreEqual(Viseme.FF, Visemes(FrenchVisemes.Frames("photo", 60))[0]);
            Assert.AreEqual(Viseme.FF, Visemes(FrenchVisemes.Frames("vous", 60))[0]);
            Assert.AreEqual(1f, FrenchVisemes.Frames("papa", 60).First(f => f.Viseme == Viseme.PP).Weight);
        }

        [Test]
        public void VowelsLastLongerThanConsonants()
        {
            var frames = FrenchVisemes.Frames("papa", 60);
            float maxPp = frames.Where(f => f.Viseme == Viseme.PP).Max(f => f.Duration);
            float minAa = frames.Where(f => f.Viseme == Viseme.AA).Min(f => f.Duration);
            Assert.Greater(minAa, maxPp * 1.5f);
            foreach (Phoneme ph in System.Enum.GetValues(typeof(Phoneme)))
            {
                var info = FrenchVisemes.Info(ph);
                if (info.Vowel && ph != Phoneme.Schwa)
                    Assert.Greater(info.Length, 0.85f, ph.ToString());
                if (!info.Vowel)
                    Assert.Less(info.Length, 0.7f, ph.ToString());
            }
        }

        [Test]
        public void EveryFrameKeepsTheOriginalIndexInOrder()
        {
            const string text = "Mika,  tu as vu l'oiseau ? Beaucoup d'eau — vraiment !";
            const int start = 120;
            var frames = FrenchVisemes.Frames(text, 60, start);
            int last = -1;
            foreach (var f in frames)
            {
                Assert.GreaterOrEqual(f.CharOffset, start);
                Assert.Less(f.CharOffset, start + text.Length);
                Assert.GreaterOrEqual(f.CharOffset, last);
                last = f.CharOffset;
                char ch = text[f.CharOffset - start];
                if (f.Viseme != Viseme.Sil)
                    Assert.IsTrue(char.IsLetter(ch), $"forme sur « {ch} »");
                else if (f.Gap)
                    Assert.IsTrue(char.IsWhiteSpace(ch) || "«»\"()".IndexOf(ch) >= 0, $"blanc sur « {ch} »");
                else
                    Assert.IsTrue(".,;:!?…—–".IndexOf(ch) >= 0, $"pause sur « {ch} »");
            }
            int oiseau = text.IndexOf("oiseau");
            Assert.AreEqual(Viseme.OH, frames.First(f => f.CharOffset == start + oiseau + 3).Viseme);
            Assert.IsFalse(frames.Any(f => f.CharOffset == start + oiseau + 4));
            Assert.IsTrue(FrenchVisemes.Frames(text, 60).All(f => f.CharOffset == -1));
        }

        [Test]
        public void ASegmentLastsMsPerCharTimesItsCollapsedLength()
        {
            var texts = new[]
            {
                "bonjour tout le monde", "Mika,  tu es là ?", "qu'est-ce que tu fais ce soir",
                "  ils mangent des pommes… ", "« Hmm » (pff) !", "eau", "...",
            };
            foreach (var text in texts)
            {
                foreach (var ms in new[] { 30f, 60f, 75f })
                    Assert.AreEqual(ms * Collapsed(text), TotalMs(FrenchVisemes.Frames(text, ms, 0)), 1e-3, text);
                Assert.AreEqual(Collapsed(text), FrenchVisemes.SpokenLength(text), text);
            }
        }

        [Test]
        public void ANumberLastsAsLongAsItsSpokenForm()
        {
            Assert.AreEqual(3 + "deux mille vingt-six".Length, FrenchVisemes.SpokenLength("en 2026"));
            Assert.AreEqual(60.0 * FrenchVisemes.SpokenLength("en 2026"), TotalMs(FrenchVisemes.Frames("en 2026", 60, 0)), 1e-3);
            var digits = FrenchVisemes.Frames("en 2026", 60, 10).Where(f => f.CharOffset >= 13).ToList();
            Assert.Greater(digits.Count, 6);
            Assert.IsTrue(digits.All(f => f.CharOffset < 17));
        }

        [Test]
        public void PunctuationPausesCloseTheMouthBlanksOnlyGlide()
        {
            var frames = FrenchVisemes.Frames("Mika, tu es là ?", 60, 0);
            var comma = frames.First(f => f.CharOffset == 4);
            Assert.AreEqual(Viseme.Sil, comma.Viseme);
            Assert.IsFalse(comma.Gap);
            var blank = frames.First(f => f.CharOffset == 5);
            Assert.IsTrue(blank.Gap);
            Assert.Less(blank.Duration, 60f);
        }

        [Test]
        public void VrcMorphNamesMatchTheModel()
        {
            Assert.AreEqual("vrc.v_aa", FrenchVisemes.VrcMorph(Viseme.AA));
            Assert.AreEqual("vrc.v_pp", FrenchVisemes.VrcMorph(Viseme.PP));
            Assert.AreEqual("vrc.v_kk", FrenchVisemes.VrcMorph(Viseme.KK));
            Assert.AreEqual("vrc.v_e", FrenchVisemes.VrcMorph(Viseme.E));
            Assert.AreEqual(14, VisemeRouting.VrcMorphs().Count());
        }
    }
}
