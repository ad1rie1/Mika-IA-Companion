package fr.qwartz.mika.ui.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les voyages lus pour la session (R4-03), comme `kit.ts::Cached` du web : une relecture forcée demandée pendant une
 * lecture en cours la suit — une seule de plus pour toutes —, une demande ordinaire la rejoint ; une relecture qui
 * échoue garde ce qu'on avait lu et le dit, sauf un 404.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TripReadsTest {
    private var version = 1
    private val gates = ArrayDeque<CompletableDeferred<Unit>>()
    private var fails: MoiError? = null
    private var fetched = 0

    private suspend fun fetch(id: String): MoiApi.Result<Trip> {
        fetched += 1
        val seen = Trip(id = id, title = "v$version")
        val error = fails
        gates.removeFirstOrNull()?.await()
        return error?.let { MoiApi.Result.Failed(it) } ?: MoiApi.Result.Ok(seen)
    }

    private fun hold() = CompletableDeferred<Unit>().also { gates.addLast(it) }

    private fun TestScope.reads(now: () -> Long = { 0L }) = TripReads(backgroundScope, ::fetch, now)

    @Test fun `une relecture forcée pendant une lecture la suit, une seule fois pour toutes`() = runTest {
        val reads = reads()
        val first = hold()
        val opening = async { reads.load("640") }
        runCurrent()
        // l'écriture aboutit pendant que la lecture de l'ouverture est en route
        version = 2
        val forced1 = async { reads.load("640", force = true) }
        val forced2 = async { reads.load("640", force = true) }
        val plain = async { reads.load("640") }
        runCurrent()
        assertEquals(1, fetched)
        first.complete(Unit)
        advanceUntilIdle()
        assertEquals("v1", opening.await().load.valueOrNull?.title)
        assertEquals("v1", plain.await().load.valueOrNull?.title)
        // partie avant l'écriture, la première ne la connaît pas : les forcées ont la suivante
        assertEquals("v2", forced1.await().load.valueOrNull?.title)
        assertEquals("v2", forced2.await().load.valueOrNull?.title)
        assertEquals(2, fetched)
        assertEquals("v2", reads["640"]?.valueOrNull?.title)
    }

    @Test fun `gardé dix secondes, une panne garde ce qu'on savait et le dit, un 404 l'efface`() = runTest {
        var clock = 0L
        val reads = reads { clock }
        reads.load("640")
        clock = 5_000
        reads.load("640")
        assertEquals(1, fetched)
        clock = 11_000
        fails = MoiError(0, "Le serveur de Mika ne répond pas.")
        val failed = reads.load("640")
        assertEquals("v1", failed.load.valueOrNull?.title)
        assertEquals(0, failed.error?.code)
        fails = MoiError(404, "Introuvable : ce n'est plus là.")
        val gone = reads.load("640", force = true)
        assertTrue(gone.load is Load.Failed)
        assertTrue(reads["640"] is Load.Failed)
        reads.forget("640")
        assertNull(reads["640"])
    }
}
