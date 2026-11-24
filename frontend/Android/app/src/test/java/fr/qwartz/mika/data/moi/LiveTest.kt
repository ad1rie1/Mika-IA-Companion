package fr.qwartz.mika.data.moi

import fr.qwartz.mika.data.net.FrameCodec
import fr.qwartz.mika.data.net.ServerFrame
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.shell.firstShown
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Le direct (ADR 0308) : chaque écran ne reçoit que ses sujets, avec ce qu'ils nomment ; un sujet inconnu se tait ;
 * chaque ouverture, la première comprise, fait tout relire — et l'écran qui a lu avant une ouverture sans être encore
 * abonné relit à son abonnement ; une rafale pendant une lecture se réunit en une seule après ; un écran parti ne
 * reçoit plus rien. Et la lecture une à la fois des pastilles.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LiveTest {
    private val live = Live()

    /** La trame telle que le serveur l'écrit, lue par `FrameCodec`, donnée au service comme le fait la connexion. */
    private fun frame(json: String) {
        live.onChanged((FrameCodec.decode(json) as ServerFrame.Changed).changes)
    }

    @Test fun `chaque écran reçoit ses sujets seulement, avec ce qu'ils nomment`() = runTest {
        val mail = mutableListOf<LiveSignal>()
        val teams = mutableListOf<LiveSignal>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { live.follow(setOf(Topics.MAIL, Topics.MAIL_WORK)) { mail += it } }
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { live.follow(setOf(Topics.TEAMS)) { teams += it } }
        assertEquals(2, live.followers)
        frame("""{"type":"changed","changes":[{"topic":"mail","boxes":["pro"]},{"topic":"me"},{"topic":"mail.work","refs":["pro:<a@x>"]}]}""")
        advanceUntilIdle()
        assertEquals(listOf(LiveSignal.of(Topics.MAIL to setOf("pro"), Topics.MAIL_WORK to setOf("pro:<a@x>"))), mail)
        assertTrue(teams.isEmpty())
        val s = mail.single()
        assertTrue(s.names(Topics.MAIL, "pro"))
        assertFalse(s.names(Topics.MAIL, "perso"))
        assertFalse(s.names(Topics.MAIL, ""))
        assertFalse(s.touches(Topics.ME))
    }

    @Test fun `un sujet inconnu ne réveille personne, une clé inconnue réveille tout le domaine`() = runTest {
        val got = mutableListOf<LiveSignal>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { live.follow(setOf(Topics.MAIL)) { got += it } }
        frame("""{"type":"changed","changes":[{"topic":"meteo","days":["lundi"]}]}""")
        advanceUntilIdle()
        assertTrue(got.isEmpty())
        frame("""{"type":"changed","changes":[{"topic":"mail","folders":["INBOX"]}]}""")
        advanceUntilIdle()
        val s = got.single()
        assertTrue(s.names(Topics.MAIL, "pro"))
        assertTrue(s.names(Topics.MAIL, "perso"))
        // tout le domaine, même sans rien d'ouvert
        assertTrue(s.names(Topics.MAIL, ""))
    }

    @Test fun `un sujet que le contrat ne connaît pas ne s'écoute pas`() = runTest {
        val refused = runCatching { live.follow(setOf("meteo")) {} }
        assertTrue(refused.exceptionOrNull() is IllegalArgumentException)
        assertEquals(0, live.followers)
    }

    @Test fun `chaque ouverture fait tout relire, la première comprise`() = runTest {
        val got = mutableListOf<LiveSignal>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { live.follow(setOf(Topics.PROJECTS)) { got += it } }
        assertEquals(0L, live.opens)
        live.onOpened()
        advanceUntilIdle()
        // au démarrage, l'écran a lu pendant la poignée de main : un changement de cet instant lui aurait échappé
        assertEquals(listOf(LiveSignal.RESYNC), got)
        val s = got.single()
        assertTrue(s.names(Topics.PROJECTS, "12"))
        assertTrue(s.touches(Topics.MAIL))
        assertTrue(s.names(Topics.MAIL_WORK, ""))
        got.clear()
        live.onOpened()
        advanceUntilIdle()
        assertEquals(listOf(LiveSignal.RESYNC), got)
        assertEquals(2L, live.opens)
    }

    @Test fun `un écran composé avant une ouverture, abonné après, relit à son abonnement`() {
        // composé (sa première lecture) à 0 ouverture ; abonné quand la connexion s'est ouverte entre-temps
        assertFalse(firstShown(first = true, composedAt = 0, opensNow = 1))
        // rien ne s'est ouvert entre-temps : sa première lecture suffit
        assertTrue(firstShown(first = true, composedAt = 1, opensNow = 1))
        // un retour reste un retour
        assertFalse(firstShown(first = false, composedAt = 1, opensNow = 1))
    }

    @Test fun `une rafale pendant une lecture se réunit en un seul signal après`() = runTest {
        val got = mutableListOf<LiveSignal>()
        val reading = CompletableDeferred<Unit>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            live.follow(setOf(Topics.MAIL, Topics.TEAMS)) {
                got += it
                // la première lecture prend son temps : tout ce qui arrive pendant elle attend
                if (got.size == 1) reading.await()
            }
        }
        frame("""{"type":"changed","changes":[{"topic":"mail","boxes":["pro"]}]}""")
        advanceUntilIdle()
        assertEquals(1, got.size)
        for (box in listOf("perso", "pro", "asso")) frame("""{"type":"changed","changes":[{"topic":"mail","boxes":["$box"]}]}""")
        frame("""{"type":"changed","changes":[{"topic":"teams"}]}""")
        frame("""{"type":"changed","changes":[{"topic":"teams","conversations":["principal~19:marc"]}]}""")
        advanceUntilIdle()
        assertEquals(1, got.size)
        reading.complete(Unit)
        advanceUntilIdle()
        // une seule lecture de plus, pour tout ce qui est arrivé : les boîtes réunies, tout Teams
        assertEquals(2, got.size)
        assertEquals(LiveSignal.of(Topics.MAIL to setOf("perso", "pro", "asso"), Topics.TEAMS to null), got[1])
    }

    @Test fun `une reconnexion pendant une lecture l'emporte sur ce qui attendait`() {
        val merged = LiveSignal.of(Topics.MAIL to setOf("pro")).merge(LiveSignal.RESYNC)
        assertEquals(LiveSignal.RESYNC, merged)
        assertEquals(LiveSignal.of(Topics.MAIL to null), LiveSignal.of(Topics.MAIL to null).merge(LiveSignal.of(Topics.MAIL to setOf("pro"))))
    }

    @Test fun `abonné, puis relire - rien de ce qui change pendant la relecture ne lui échappe`() = runTest {
        val got = mutableListOf<LiveSignal>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            live.follow(setOf(Topics.CONTACTS), ready = {
                // la relecture du retour part : un changement qui arrive maintenant est déjà entendu
                frame("""{"type":"changed","changes":[{"topic":"contacts"}]}""")
            }) { got += it }
        }
        advanceUntilIdle()
        assertEquals(listOf(LiveSignal.of(Topics.CONTACTS to null)), got)
    }

    @Test fun `un écran parti ne reçoit plus rien`() = runTest {
        val got = mutableListOf<LiveSignal>()
        val job = backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { live.follow(setOf(Topics.TRIPS)) { got += it } }
        assertEquals(1, live.followers)
        job.cancel()
        advanceUntilIdle()
        assertEquals(0, live.followers)
        frame("""{"type":"changed","changes":[{"topic":"trips"}]}""")
        live.onOpened()
        live.onOpened()
        advanceUntilIdle()
        assertTrue(got.isEmpty())
    }

    @Test fun `une lecture à la fois - une rafale de demandes, une en vol et une seule après`() = runTest {
        var reads = 0
        val gate = CompletableDeferred<Unit>()
        val once = OneAtATime(this) {
            reads++
            if (reads == 1) gate.await()
        }
        once.run()
        advanceUntilIdle()
        assertTrue(once.running)
        repeat(10) { once.run() }
        advanceUntilIdle()
        assertEquals(1, reads)
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(2, reads)
        assertFalse(once.running)
        // finie, la suivante repart
        once.run()
        advanceUntilIdle()
        assertEquals(3, reads)
    }
}
