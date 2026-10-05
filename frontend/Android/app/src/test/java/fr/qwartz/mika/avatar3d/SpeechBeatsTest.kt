package fr.qwartz.mika.avatar3d

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Les temps forts de la parole, extraits de phrases françaises (port de `speechBody.test.ts`, partie `planSpeechBeats`). */
class SpeechBeatsTest {
    /** Chaque temps fort, avec le mot (ou la ponctuation) sur lequel il tombe. */
    private fun kinds(text: String): List<Pair<String, BeatKind>> =
        SpeechBeats.plan(text).map { text.substring(it.at).split(Regex("""(?U)[\s,]"""))[0] to it.kind }

    private fun beatOn(text: String, word: String, kind: BeatKind) =
        SpeechBeats.plan(text).any { it.kind == kind && text.startsWith(word, it.at) }

    @Test fun `une question se ferme sur son dernier mot, une affirmation d'un hochement`() {
        assertEquals("bien" to BeatKind.QUESTION, kinds("Tu vas bien ?").last())
        assertEquals("tard." to BeatKind.FINAL, kinds("Je suis rentrée tard.").last())
        assertEquals("génial" to BeatKind.EMPHASIS, kinds("C'est génial !").last())
        assertEquals("pas…" to BeatKind.TRAIL, kinds("Je ne sais pas…").last())
        assertEquals("pas..." to BeatKind.TRAIL, kinds("Je ne sais pas...").last())
        // Une espace insécable devant le point d'interrogation, un saut de ligne final : la même question.
        assertEquals("soir" to BeatKind.QUESTION, kinds("Tu viens ce soir\u00A0?\n").last())
    }

    @Test fun `la pause tombe sur la virgule même, et l'accent sur le mot qui ferme le groupe`() {
        val text = "Franchement mardi, demain soir ça me va."
        val pause = SpeechBeats.plan(text).first { it.kind == BeatKind.PAUSE }
        assertEquals(',', text[pause.at])
        assertTrue(beatOn(text, "mardi", BeatKind.STRESS))
    }

    @Test fun `la typographie française - une espace insécable devant le point-virgule ne cache pas la pause`() {
        val text = "Franchement mardi\u00A0; demain soir ça me va."
        val pause = SpeechBeats.plan(text).first { it.kind == BeatKind.PAUSE }
        assertEquals(';', text[pause.at])
        assertTrue(beatOn(text, "mardi", BeatKind.STRESS))
    }

    @Test fun `elle insiste sur les capitales, les mots entre étoiles et les intensifs`() {
        val text = "Non mais c'est TROP bien, et vraiment *magique* quoi."
        val emphasized = SpeechBeats.plan(text)
            .filter { it.kind == BeatKind.EMPHASIS }
            .map { Regex("""\p{L}+""").find(text, it.at)!!.value }
        assertTrue("$emphasized", emphasized.containsAll(listOf("TROP", "vraiment", "magique")))
        // Le temps fort d'un *mot* tombe sur sa première lettre, pas sur l'étoile.
        val magique = SpeechBeats.plan(text).first { text.startsWith("magique", it.at) }
        assertEquals('*', text[magique.at - 1])
    }

    @Test fun `jamais de temps fort dans un jeton de prosodie, et les indices restent ceux du texte complet`() {
        val text = "[SIGH] Bon. [PAUSE:400] On y va ?"
        val beats = SpeechBeats.plan(text)
        for (b in beats) {
            assertTrue(text.substring(b.at), !Regex("""^[A-Z_]+[:\]]""").containsMatchIn(text.substring(b.at)))
            assertTrue(text.substring(b.at), Regex("""[\p{L},]""").matches(text[b.at].toString()))
        }
        assertTrue(text.startsWith("va", beats.last().at))
    }

    @Test fun `un jeton en minuscules n'est pas lu comme un mot`() {
        val text = "[sigh] Bon, [breath] on y va."
        for (b in SpeechBeats.plan(text)) {
            assertTrue("${b.at}", b.at !in 0..5 && b.at !in 12..19)
        }
    }

    @Test fun `une longue proposition bouge encore - jamais plus de 36 caractères sans ponctuation du corps`() {
        val text = "Je me disais que les longues soirées passées à regarder les étoiles depuis le balcon étaient précieuses."
        val at = SpeechBeats.plan(text).map { it.at }
        for (i in 1 until at.size) assertTrue("${at[i - 1]} → ${at[i]}", at[i] - at[i - 1] <= 36)
        assertTrue("$at", at.size >= 4)
    }

    @Test fun `trié, un seul temps fort par position`() {
        val beats = SpeechBeats.plan("Coucou ! Tu sais, j'ai repensé à tout ça. Et toi ?")
        for (i in 1 until beats.size) assertTrue(beats[i].at > beats[i - 1].at)
    }

    @Test fun `une proposition commence par une prise d'air - une phrase d'un mot garde plutôt son battement de fin`() {
        val text = "Bon. Alors, on y va ? Oui."
        val starts = SpeechBeats.plan(text).filter { it.kind == BeatKind.PHRASE_START }.map { it.at }
        assertEquals(listOf(text.indexOf("Alors")), starts)
        // « Bon. » et « Oui. » tiennent en un mot : leur battement de fin l'emporte sur la prise d'air au même caractère.
        assertTrue(beatOn(text, "Bon", BeatKind.FINAL))
    }

    @Test fun `rien à ponctuer dans un texte vide ou fait de jetons`() {
        assertTrue(SpeechBeats.plan("").isEmpty())
        assertTrue(SpeechBeats.plan("   ").isEmpty())
        assertTrue(SpeechBeats.plan("[SIGH] [PAUSE:300]").isEmpty())
        assertTrue(SpeechBeats.plan("…?!").isEmpty())
    }

    @Test fun `les jetons de prosodie sont repérés à leur crochet, sans égard à la casse - une pause n'en est pas un`() {
        val text = "[SIGH] Bon. [breath] On y va [PAUSE:400] ? [Laugh]"
        assertEquals(
            listOf(
                SpeechCue(0, SpeechCueKind.SIGH),
                SpeechCue(text.indexOf("[breath]"), SpeechCueKind.BREATH),
                SpeechCue(text.indexOf("[Laugh]"), SpeechCueKind.LAUGH),
            ),
            SpeechBeats.cues(text),
        )
    }
}
