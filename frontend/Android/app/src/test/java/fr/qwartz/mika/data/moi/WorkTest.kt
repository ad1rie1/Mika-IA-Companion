package fr.qwartz.mika.data.moi

import fr.qwartz.mika.core.MikaJson
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Où elle en est d'une réponse (ADR 0306, porté de `frontendv2/src/mika/work.ts`) : l'étape en mots, le chrono, sa
 * forme lue telle que le serveur la dit, et ce que décide une relecture de `…/work` — guetter, relire, cesser.
 */
class WorkTest {
    private val at = 1_790_000_000_000L

    private fun w(step: String, label: String = "") = Work(step, label, since = at, started = at)

    @Test fun `l'étape en mots - elle s'y met, elle réfléchit, tel outil tourne`() {
        assertEquals("Elle s'y met…", workText(w(WorkSteps.WAITING)))
        assertEquals("Réflexion en cours…", workText(w(WorkSteps.THINKING)))
        assertEquals("Relire une de tes conversations Teams…", workText(w(WorkSteps.TOOL, "Relire une de tes conversations Teams")))
        // jamais deux points de suspension, ni de points avant les siens
        assertEquals("Chercher…", workText(w(WorkSteps.TOOL, "Chercher…")))
        assertEquals("Chercher…", workText(w(WorkSteps.TOOL, "Chercher...")))
        // un outil sans libellé
        assertEquals("Un de ses outils…", workText(w(WorkSteps.TOOL)))
        assertEquals("Un de ses outils…", workText(w(WorkSteps.TOOL, "  ")))
        // une étape qu'on ne connaît pas (un serveur plus récent) : comme l'attente
        assertEquals("Elle s'y met…", workText(w("futur")))
    }

    @Test fun `un chrono qui court - secondes, minutes, heures, jamais négatif`() {
        assertEquals("0:00", elapsed(0))
        assertEquals("0:07", elapsed(7_400))
        assertEquals("0:59", elapsed(59_999))
        assertEquals("1:30", elapsed(90_000))
        assertEquals("59:59", elapsed(3_599_000))
        assertEquals("1:00:00", elapsed(3_600_000))
        assertEquals("1:02:05", elapsed(3_725_000))
        assertEquals("12:00:09", elapsed(43_209_000))
        // une horloge un peu en avance sur le serveur
        assertEquals("0:00", elapsed(-2_000))
        assertEquals("0:00", elapsed(-400))
    }

    @Test fun `sa forme se lit telle que le serveur la dit, l'inconnu ignoré`() {
        val got = MikaJson.decodeFromString(
            Work.serializer(),
            """{"step":"tool","label":"Relire une de tes conversations Teams","since":1790000004000,"started":1790000000000,"futur":1}""",
        )
        assertEquals(Work(WorkSteps.TOOL, "Relire une de tes conversations Teams", 1_790_000_004_000, 1_790_000_000_000), got)
        // ce qui manque prend son défaut
        assertEquals(Work(WorkSteps.THINKING), MikaJson.decodeFromString(Work.serializer(), """{"step":"thinking"}"""))
    }

    @Test fun `juste après un « Préremplir » réussi - elle s'y met, depuis maintenant`() {
        assertEquals(Work(WorkSteps.WAITING, "", at, at), Work.waiting(at))
    }

    @Test fun `une relecture de work - arrivée, finie sans rien rendre, ou en cours`() {
        // sa réponse est là : quoi que disent les autres champs
        assertEquals(WorkTurn.ARRIVED, workTurn(arrived = true, asked = false, work = null))
        assertEquals(WorkTurn.ARRIVED, workTurn(arrived = true, asked = true, work = w(WorkSteps.THINKING)))
        // plus rien de demandé ni d'en cours
        assertEquals(WorkTurn.ENDED, workTurn(arrived = false, asked = false, work = null))
        // demandée, pas encore commencée (un serveur qui ne dit pas l'étape aussi) ; ou en cours, demandée ou d'elle-même
        assertEquals(WorkTurn.GOING, workTurn(arrived = false, asked = true, work = null))
        assertEquals(WorkTurn.GOING, workTurn(arrived = false, asked = true, work = w(WorkSteps.TOOL, "Chercher")))
        assertEquals(WorkTurn.GOING, workTurn(arrived = false, asked = false, work = w(WorkSteps.THINKING)))
    }

    @Test fun `on guette une demande, ou ce qu'elle prépare d'elle-même, jusqu'à son arrivée ou au plafond`() {
        assertTrue(watchWork(asked = true, work = null, arrived = false, gaveUp = false))
        assertTrue(watchWork(asked = false, work = w(WorkSteps.THINKING), arrived = false, gaveUp = false))
        assertFalse(watchWork(asked = false, work = null, arrived = false, gaveUp = false))
        assertFalse(watchWork(asked = true, work = w(WorkSteps.THINKING), arrived = true, gaveUp = false))
        assertFalse(watchWork(asked = true, work = w(WorkSteps.THINKING), arrived = false, gaveUp = true))
        // le plafond : une demi-heure, pas une milliseconde de moins
        assertFalse(workGaveUp(since = at, now = at + WORK_WATCH_MAX_MS))
        assertTrue(workGaveUp(since = at, now = at + WORK_WATCH_MAX_MS + 1))
        assertEquals(2_000L, WORK_POLL_MS)
    }
}
