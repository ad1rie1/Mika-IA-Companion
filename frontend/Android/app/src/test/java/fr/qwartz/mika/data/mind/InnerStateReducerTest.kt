package fr.qwartz.mika.data.mind

import fr.qwartz.mika.data.net.BlendPart
import fr.qwartz.mika.data.net.Circadian
import fr.qwartz.mika.data.net.IdentityView
import fr.qwartz.mika.data.net.InnerState
import fr.qwartz.mika.data.net.Journal
import fr.qwartz.mika.data.net.Rumination
import fr.qwartz.mika.data.net.SelfNarrative
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class InnerStateReducerTest {
    private val full = InnerState(
        sleepPhase = "awake", energy = 0.8, place = "desk",
        circadian = Circadian("evening", 21.0, 0.8, "dreamy"), estime = 0.6, personScope = true,
        ruminations = listOf(Rumination("hier", 0.5, "thinking")),
        todayJournal = Journal(narrative = "Calme."), selfNarrative = SelfNarrative("Je suis…"),
        identity = IdentityView(knownAs = "Adrien"), pendingCommitments = listOf("le lien"),
    )
    private val known = InnerStateReducer.apply(MindState(), full, 1)

    @Test fun `les clés de base remplacent quand elles sont là`() {
        val next = InnerStateReducer.apply(known, InnerState(sleepPhase = "rem", personScope = true), 2)
        assertEquals("rem", next.sleepPhase)
        assertEquals(0.8, next.energy!!, 0.0)
        assertEquals("desk", next.place)
        assertEquals(2L, next.updatedAtMs)
    }

    @Test fun `une trame qui ne parle de personne garde les sections du panneau`() {
        val next = InnerStateReducer.apply(known, InnerState(sleepPhase = "deep_sleep", personScope = false), 2)
        assertEquals("deep_sleep", next.sleepPhase)
        assertEquals("Adrien", next.identity!!.knownAs)
        assertEquals("Je suis…", next.selfNarrative)
        assertEquals(1, next.ruminations.size)
        assertEquals(listOf("le lien"), next.pendingCommitments)
    }

    @Test fun `une trame à propos de quelqu'un efface ce qu'elle ne porte plus`() {
        val next = InnerStateReducer.apply(known, InnerState(sleepPhase = "awake", personScope = true), 2)
        assertNull(next.identity)
        assertNull(next.selfNarrative)
        assertNull(next.journal)
        assertEquals(emptyList<Rumination>(), next.ruminations)
    }

    @Test fun `une section malformée garde sa valeur`() {
        val next = InnerStateReducer.apply(
            known,
            InnerState(personScope = true, malformed = setOf("energy", "self_narrative", "identity")),
            2,
        )
        assertEquals(0.8, next.energy!!, 0.0)
        assertEquals("Je suis…", next.selfNarrative)
        assertEquals("Adrien", next.identity!!.knownAs)
    }

    @Test fun `une phase inconnue se lit éveillée`() {
        assertEquals("awake", InnerStateReducer.apply(known, InnerState(sleepPhase = "hibernation"), 2).sleepPhase)
    }

    @Test fun `l'humeur suit les émotions, une émotion vide ne dit rien`() {
        val moody = InnerStateReducer.applyMood(known, "curious", 0.5, listOf(BlendPart("curious", 1.0)), 3)
        assertEquals(Mood("curious", 0.5, listOf(BlendPart("curious", 1.0))), moody.mood)
        assertEquals(moody, InnerStateReducer.applyMood(moody, "", 0.9, emptyList(), 4))
        assertEquals(1.0, InnerStateReducer.applyMood(known, "happy", 3.0, emptyList(), 5).mood!!.intensity, 0.0)
    }
}
