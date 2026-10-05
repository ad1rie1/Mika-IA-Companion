package fr.qwartz.mika.avatar3d

import fr.qwartz.mika.avatar3d.FrenchVisemes.Frame
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Le passage graphème → phonème → visème : `frenchVisemes.test.ts`, cas pour cas. */
class FrenchVisemesTest {

    private fun phonemes(text: String) = FrenchVisemes.phonemes(text).joinToString(" ") { it.ph }
    private fun visemes(frames: List<Frame>) =
        frames.filter { it.viseme != FrenchVisemes.Viseme.SIL }.map { it.viseme.id }
    private fun totalMs(frames: List<Frame>) = frames.sumOf { it.duration }
    private fun collapsed(text: String) = text.replace(Regex("\\s+"), " ").length

    @Test fun `graphème vers phonème`() {
        val cases = listOf(
            "eau" to "o",
            "oiseau" to "w a z o",
            "champagne" to "S a~ p a J",
            "ils mangent" to "i l m a~ Z",
            "beaucoup" to "b o k u",
            "qu'est-ce que" to "k E s @ k @",
            "Mika" to "m i k a",
            "bonjour tout le monde" to "b o~ Z u R t u l @ m o~ d",
            "c'est" to "s E",
            "aujourd'hui" to "o Z u R d H i",
            "les enfants" to "l e a~ f a~",
            "fille" to "f i j",
            "ville" to "v i l",
            "nation" to "n a s j o~",
            "question" to "k E s t j o~",
            "photo" to "f o t o",
            "garçon" to "g a R s o~",
            "guitare" to "g i t a R",
            "taxi" to "t a k s i",
            "homme" to "o m",
            "une" to "y n",
            "bien" to "b j e~",
            "science" to "s j a~ s",
            "pain" to "p e~",
            "loin" to "l w e~",
            "oui" to "w i",
            "étaient" to "e t E",
            "parlent" to "p a R l",
            "souvent" to "s u v a~",
            "manger" to "m a~ Z e",
            "samedi" to "s a m d i",
            "petit" to "p @ t i",
            "SMS" to "E s E m E s",
        )
        for ((text, expected) in cases) assertEquals(text, expected, phonemes(text))
    }

    @Test fun `les nombres sont lus en entier, comme une voix les dit`() {
        assertEquals("quarante-deux", FrenchVisemes.spellNumber("42"))
        assertEquals("soixante et onze", FrenchVisemes.spellNumber("71"))
        assertEquals("quatre-vingts", FrenchVisemes.spellNumber("80"))
        assertEquals("deux mille vingt-six", FrenchVisemes.spellNumber("2026"))
        assertEquals("zéro six un deux", FrenchVisemes.spellNumber("0612"))
        assertEquals("k a R a~ t d 2", phonemes("42"))
        assertEquals("d 2 m i l v e~ s i s", phonemes("2026"))
        assertEquals("v e~ e e~", phonemes("21"))
    }

    @Test fun `un digramme fait une forme de bouche, pas une par lettre`() {
        // « eau » est une voyelle ; « qu » n'arrondit jamais les lèvres ; « gn » n'est pas un « g ».
        assertEquals(listOf("oh"), visemes(FrenchVisemes.frames("eau", 60.0)))
        assertFalse("ou" in visemes(FrenchVisemes.frames("qu'est-ce que", 60.0)))
        assertEquals(listOf("CH", "aa", "PP", "aa", "nn"), visemes(FrenchVisemes.frames("champagne", 60.0)))
    }

    @Test fun `les lettres muettes ne font aucune forme`() {
        // « ils mangent » finit sur le « g » ; « les » ne siffle pas.
        assertEquals("CH", visemes(FrenchVisemes.frames("ils mangent", 60.0)).last())
        assertEquals(listOf("nn", "E"), visemes(FrenchVisemes.frames("les", 60.0)))
    }

    @Test fun `les bilabiales ferment les lèvres, les labiodentales mordent`() {
        for (word in listOf("papa", "beaucoup", "maman", "bonjour")) {
            assertEquals(word, "PP", visemes(FrenchVisemes.frames(word, 60.0))[0])
        }
        assertEquals("FF", visemes(FrenchVisemes.frames("photo", 60.0))[0])
        assertEquals("FF", visemes(FrenchVisemes.frames("vous", 60.0))[0])
        val closure = FrenchVisemes.frames("papa", 60.0).first { it.viseme == FrenchVisemes.Viseme.PP }
        assertEquals(1.0, closure.weight, 0.0)
    }

    @Test fun `les voyelles durent plus que les consonnes`() {
        val frames = FrenchVisemes.frames("papa", 60.0)
        val pp = frames.filter { it.viseme == FrenchVisemes.Viseme.PP }.map { it.duration }
        val aa = frames.filter { it.viseme == FrenchVisemes.Viseme.AA }.map { it.duration }
        assertTrue(aa.min() > pp.max() * 1.5)
        for ((ph, p) in FrenchVisemes.PHONEMES) {
            if (p.vowel && ph != "@") assertTrue(ph, p.length > 0.85)
            if (!p.vowel) assertTrue(ph, p.length < 0.7)
        }
    }

    @Test fun `chaque trame garde l'index d'ORIGINE de ce qu'elle articule, dans l'ordre`() {
        val text = "Mika,  tu as vu l'oiseau ? Beaucoup d'eau — vraiment !"
        val start = 120
        val frames = FrenchVisemes.frames(text, 60.0, start)
        var last = -1
        for (f in frames) {
            assertTrue(f.charOffset >= start && f.charOffset < start + text.length)
            assertTrue(f.charOffset >= last)
            last = f.charOffset
            val ch = text[f.charOffset - start]
            // Une forme se pose sur une lettre ; une pause sur une ponctuation ; un blanc sur un blanc.
            when {
                f.viseme != FrenchVisemes.Viseme.SIL -> assertTrue("$ch", ch.isLetter())
                f.gap -> assertTrue("$ch", ch.isWhitespace() || ch in "«»\"()")
                else -> assertTrue("$ch", ch in ".,;:!?…—–")
            }
        }
        // Le « eau » de « oiseau » est une trame, ancrée sur son « e ».
        val oiseau = text.indexOf("oiseau")
        assertEquals(FrenchVisemes.Viseme.OH, frames.first { it.charOffset == start + oiseau + 3 }.viseme)
        assertFalse(frames.any { it.charOffset == start + oiseau + 4 })
        // Sans position, chaque trame le dit.
        assertTrue(FrenchVisemes.frames(text, 60.0).all { it.charOffset == -1 })
    }

    @Test fun `un segment dure msPerChar fois sa longueur, blancs repliés`() {
        val texts = listOf(
            "bonjour tout le monde",
            "Mika,  tu es là ?",
            "qu'est-ce que tu fais ce soir",
            "  ils mangent des pommes… ",
            "« Hmm » (pff) !",
            "*vraiment* ?",
            "eau",
            "...",
        )
        for (text in texts) {
            for (ms in listOf(30.0, 60.0, 75.0)) {
                assertEquals(text, ms * collapsed(text), totalMs(FrenchVisemes.frames(text, ms, 0)), 1e-6)
            }
            assertEquals(text, collapsed(text), FrenchVisemes.spokenLength(text))
        }
    }

    @Test fun `un nombre dure le temps de sa forme dite`() {
        // « 2026 » se lit « deux mille vingt-six » : 20 caractères de voix.
        assertEquals(3 + "deux mille vingt-six".length, FrenchVisemes.spokenLength("en 2026"))
        assertEquals(60.0 * FrenchVisemes.spokenLength("en 2026"), totalMs(FrenchVisemes.frames("en 2026", 60.0, 0)), 1e-6)
        val frames = FrenchVisemes.frames("en 2026", 60.0, 10)
        val digits = frames.filter { it.charOffset >= 13 }
        assertTrue(digits.size > 6)
        assertTrue(digits.all { it.charOffset < 17 })
    }

    @Test fun `une ponctuation ferme la bouche, un blanc la fait seulement glisser`() {
        val frames = FrenchVisemes.frames("Mika, tu es là ?", 60.0, 0)
        val comma = frames.first { it.charOffset == 4 }
        assertEquals(FrenchVisemes.Viseme.SIL, comma.viseme)
        assertFalse(comma.gap)
        val blank = frames.first { it.charOffset == 5 }
        assertTrue(blank.gap)
        assertTrue(blank.duration < 60.0)
    }

    @Test fun `un astérisque de Markdown ne se dit pas, il glisse comme un blanc`() {
        val frames = FrenchVisemes.frames("*oui*", 60.0, 0)
        assertEquals(listOf("ou", "ih"), visemes(frames))
        for (at in listOf(0, 4)) {
            val star = frames.first { it.charOffset == at }
            assertEquals(FrenchVisemes.Viseme.SIL, star.viseme)
            assertTrue(star.gap)
        }
    }

    @Test fun `un e décomposé reste une lettre, à l'index de sa base`() {
        // « é » écrit e + accent combinant : une seule lettre, un seul [e].
        val decomposed = "été"
        assertEquals(phonemes("été"), phonemes(decomposed))
        assertTrue(FrenchVisemes.frames(decomposed, 60.0, 0).all { it.charOffset != 1 && it.charOffset != 4 })
    }
}
