package fr.qwartz.mika.ui.mind

import fr.qwartz.mika.data.mind.MindState
import fr.qwartz.mika.data.mind.Mood
import fr.qwartz.mika.data.net.BlendPart
import fr.qwartz.mika.data.net.Circadian
import fr.qwartz.mika.data.net.Dream
import fr.qwartz.mika.data.net.Drive
import fr.qwartz.mika.data.net.Journal
import fr.qwartz.mika.data.net.ProjectSummary
import fr.qwartz.mika.data.net.Rumination
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

class MindCardsTest {
    private val zone = ZoneId.of("Europe/Paris")
    private fun build(state: MindState?) = MindCards.build(state, zone)

    @Test fun `rien de connu, aucune carte`() {
        assertTrue(build(null).isEmpty())
        assertTrue(build(MindState()).isEmpty())
    }

    @Test fun `une humeur seule ne dit rien du corps`() {
        val cards = build(MindState(mood = Mood("curious", 0.6)))
        assertEquals(listOf(MindCard.Mood("Curieuse", 60)), cards)
    }

    @Test fun `« mais aussi » seulement quand la seconde émotion pèse assez`() {
        val strong = build(MindState(mood = Mood("happy", 0.7, listOf(BlendPart("happy", 0.6), BlendPart("nostalgic", 0.3)))))
        assertEquals(MindCard.Mood("Contente", 60, "Nostalgique", 30), strong.single())
        val weak = build(MindState(mood = Mood("happy", 0.7, listOf(BlendPart("happy", 0.6), BlendPart("sad", 0.2)))))
        assertEquals(MindCard.Mood("Contente", 60), weak.single())
    }

    @Test fun `le corps - sommeil, énergie, lieu, moment`() {
        val body = build(
            MindState(
                sleepPhase = "rem",
                place = "bed",
                circadian = Circadian("night", 2.0, 0.2, ""),
            ),
        ).single() as MindCard.Body
        assertEquals("endormie (rêve)", body.sleep)
        assertTrue(body.asleep)
        assertEquals(20, body.energyPct) // repli sur l'énergie du rythme
        assertEquals("sur son lit", body.place)
        assertEquals("Nuit · 2 h", body.moment)
    }

    @Test fun `l'ordre des cartes, et seulement celles qui ont quelque chose`() {
        val cards = build(
            MindState(
                energy = 0.8,
                estime = 0.55,
                ruminations = listOf(Rumination("ce qu'il a dit", 0.42, "thinking"), Rumination("  ", 0.9)),
                journal = Journal(title = "Son journal de vendredi", narrative = "Une journée calme.", personsInteracted = listOf("Béa")),
                dream = Dream(content = "Une bibliothèque sans fin", dreamType = "associative", vividness = 0.5, recalled = true),
                selfNarrative = "Je suis curieuse.",
                drives = mapOf("curiosity" to Drive(0.7), "social" to Drive(0.25), "zzz" to Drive(0.1)),
                mood = Mood("dreamy", 0.5),
            ),
        )
        assertEquals(
            listOf("Mood", "Body", "Esteem", "Thoughts", "Dream", "Journal", "Narrative", "Needs"),
            cards.map { it.javaClass.simpleName },
        )
        val thoughts = cards[3] as MindCard.Thoughts
        assertEquals(listOf(MindCard.Thought("ce qu'il a dit", 42, "Réfléchit...")), thoughts.items)
        val dream = cards[4] as MindCard.Dream
        assertEquals("rêve associatif", dream.type)
        assertEquals(0.7f, dream.alpha, 0.001f)
        assertTrue(dream.recalled)
        assertEquals("Son journal de vendredi", (cards[5] as MindCard.Journal).title)
        val needs = cards[7] as MindCard.Needs
        assertEquals(listOf("Compagnie", "Apprendre", "zzz"), needs.items.map { it.label })
        assertEquals(listOf(25, 70, 10), needs.items.map { it.pct })
    }

    @Test fun `les projets, sans jamais d'action en attente`() {
        val cards = build(
            MindState(
                projects = listOf(
                    ProjectSummary(1, "Le potager", modeLabel = "impersonnel", tasksTotal = 4, tasksDone = 1, tasksBlocked = 2,
                        nextRunAt = "2026-10-05T07:00:00+00:00"),
                    ProjectSummary(2, "", scheduleLabel = "les jours ouvrés à 9 h"),
                ),
            ),
        )
        val projects = (cards.single() as MindCard.Projects).items
        assertEquals("dès que possible", projects[0].schedule)
        assertEquals("05/10 09:00", projects[0].nextRun)
        assertEquals("impersonnel", projects[0].mode)
        assertEquals("Projet 2", projects[1].title)
        assertEquals("les jours ouvrés à 9 h", projects[1].schedule)
        assertNull(projects[1].nextRun)
    }

    @Test fun `une date de séance illisible ne s'invente pas`() {
        assertNull(MindCards.formatNextRun("demain", zone))
        assertEquals("05/10 09:30", MindCards.formatNextRun("2026-10-05T09:30:00", zone))
        assertEquals("05/10 09:30", MindCards.formatNextRun("2026-10-05T07:30:00Z", zone))
    }

    @Test fun `mis à jour il y a…`() {
        val t = 1_000_000_000L
        assertNull(MindCards.updatedAgo(0, t))
        assertEquals("Mis à jour à l'instant", MindCards.updatedAgo(t, t + 20_000))
        assertEquals("Mis à jour il y a 3 min", MindCards.updatedAgo(t, t + 3 * 60_000 + 5_000))
        assertEquals("Mis à jour il y a 2 h", MindCards.updatedAgo(t, t + 2 * 3_600_000 + 1))
        assertEquals("Mis à jour il y a 4 j", MindCards.updatedAgo(t, t + 4 * 86_400_000L))
        assertEquals("Mis à jour à l'instant", MindCards.updatedAgo(t, t - 5_000))
    }
}
