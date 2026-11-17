package fr.qwartz.mika.ui.carte

import fr.qwartz.mika.R
import fr.qwartz.mika.data.files.DownloadStore
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripDay
import fr.qwartz.mika.data.moi.carte.TripStop
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Un voyage ouvert contre une fausse API (`FakeTripsApi`) : la relecture d'après un geste suit celle qui était partie
 * avant lui, et une relecture en panne ne remet pas le voyage d'avant des gestes aboutis (R4-03) ; « Sur la route »
 * fermé ne laisse ni épingles ni relectures, et ne survit pas à la sortie de l'écran (R4-04) ; le GPX attend les gestes
 * partis avant lui (R4-08).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TripModelTest {
    @get:Rule val main = MainDispatcherRule()

    private fun stop(id: String, lat: Double) = TripStop(id, "Arrêt $id", "", lat, 5.0, "", "toi")

    private val abc = Trip(id = "640", title = "Les Alpes", updated = 1, days = listOf(TripDay(1, "", listOf(stop("A", 50.0), stop("B", 49.0), stop("C", 48.0)))))

    private val api = FakeTripsApi(abc)
    private val session = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val saved = mutableListOf<String>()
    private val reads = TripReads(session, { api.read(it) }, { 1_000_000L })
    private val deps = TripDeps(
        api = api,
        reads = reads,
        saveGpx = { file ->
            saved += file.name
            api.calls += "gpx"
            DownloadStore.Outcome.Saved("Téléchargements/Mika")
        },
    )
    private val vm by lazy { main.model { TripViewModel(deps, "640") } }

    @After fun stop() = session.cancel()

    private fun TestScope.said(): MutableList<String> {
        val got = mutableListOf<String>()
        // de suite, et à chaque message : le fond du test ne tourne pas tant que rien d'autre n'attend
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.said.collect { got += it } }
        return got
    }

    private fun shownStops(): List<String> = vm.shown!!.days.flatMap { d -> d.stops.map { it.id } }

    // ── R4-03 ──

    @Test fun `le geste G2 fini avant la relecture de G1 - sa relecture suit, B ne revient pas`() = runTest {
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf("A", "B", "C"), shownStops())
        // G1 retire A ; sa relecture R1 part et reste en route
        val g1 = api.hold("remove")
        vm.remove("A")
        val r1 = api.hold("read")
        g1.complete(Unit)
        runCurrent()
        assertEquals(2, api.reads)
        // G2 retire B, et son écriture finit avant que R1 ne revienne : R1 ne le connaît pas
        val r2 = api.hold("read")
        vm.remove("B")
        runCurrent()
        assertEquals(listOf("C"), shownStops())
        r1.complete(Unit)
        runCurrent()
        // R1 est revenue avec [B, C] : elle ne lève rien (un geste a fini depuis), une lecture de plus est partie
        assertEquals(listOf("C"), shownStops())
        assertEquals(3, api.reads)
        r2.complete(Unit)
        advanceUntilIdle()
        assertEquals(listOf("C"), shownStops())
        assertEquals(listOf("C"), reads["640"]!!.valueOrNull!!.days.flatMap { d -> d.stops.map { it.id } })
    }

    @Test fun `une relecture en panne après des gestes aboutis garde ce qu'ils ont posé, le dit, et se refait au retour`() = runTest {
        val said = said()
        vm.resume()
        advanceUntilIdle()
        api.readFails = MoiError(0, "Le serveur de Mika ne répond pas.")
        vm.remove("A")
        advanceUntilIdle()
        // le serveur a retiré A : le voyage d'avant (A, B, C) serait faux
        assertEquals(listOf("B", "C"), shownStops())
        assertTrue(vm.unread)
        assertEquals(listOf("${R.string.carte_trip_unread_kept}|Le serveur de Mika ne répond pas."), said.filter { it.startsWith("${R.string.carte_trip_unread_kept}") })
        // le retour sur l'écran le relit comme après les gestes
        api.readFails = null
        vm.resume()
        advanceUntilIdle()
        assertFalse(vm.unread)
        assertEquals(listOf("B", "C"), shownStops())
        assertEquals(listOf("B", "C"), reads["640"]!!.valueOrNull!!.days.flatMap { d -> d.stops.map { it.id } })
    }

    @Test fun `un geste refusé puis une relecture en panne - le dernier voyage lu fait foi`() = runTest {
        val said = said()
        vm.resume()
        advanceUntilIdle()
        api.writeRefused = MoiError(409, "La situation a changé : relis, puis recommence.")
        api.readFails = MoiError(0, "Le serveur de Mika ne répond pas.")
        vm.remove("A")
        advanceUntilIdle()
        assertEquals(listOf("A", "B", "C"), shownStops())
        assertTrue(vm.unread)
        assertTrue(said.contains("${R.string.carte_trip_unread}|Le serveur de Mika ne répond pas."))
    }

    // ── R4-04 ──

    @Test fun `« Sur la route » fermé ou quitté - ni épingles, ni relectures, et rien ne survit à la sortie`() = runTest {
        api.alongPlaces = listOf(Place(id = "l1", name = "Camping", lat = 49.5, lon = 5.1, alongM = 50_000.0))
        vm.resume()
        advanceUntilIdle()
        vm.toggleAlongPanel()
        assertTrue(vm.alongOpen)
        vm.toggleAlong("dormir")
        advanceUntilIdle()
        assertTrue(vm.scene(vm.shown!!).pins.any { it.minor })
        // ouvert : un geste change le trajet, la liste suit
        vm.remove("C")
        advanceUntilIdle()
        assertEquals(2, api.calls.count { it.startsWith("along:") })
        // l'écran s'en va (pas une rotation) : fermé, dans le modèle
        vm.leave()
        assertFalse(vm.alongOpen)
        assertEquals("", vm.along.cat)
        assertTrue(vm.scene(vm.shown!!).pins.none { it.minor })
        // un geste après : son trajet se relit, « Sur la route » non
        vm.step("B", -1)
        advanceUntilIdle()
        assertEquals(2, api.calls.count { it.startsWith("along:") })
        // une seule touche le rouvre, une seule le referme
        vm.toggleAlongPanel()
        assertTrue(vm.alongOpen)
        vm.toggleAlongPanel()
        assertFalse(vm.alongOpen)
    }

    // ── R4-08 ──

    @Test fun `le GPX attend le geste parti avant lui - il dit l'ordre montré`() = runTest {
        vm.resume()
        advanceUntilIdle()
        val post = api.hold("move")
        vm.step("A", 1)
        assertEquals(listOf("B", "A", "C"), shownStops())
        vm.gpx()
        runCurrent()
        assertTrue(saved.isEmpty())
        post.complete(Unit)
        advanceUntilIdle()
        assertEquals(listOf("Les-Alpes.gpx"), saved)
        assertTrue(api.calls.indexOf("gpx") > api.calls.indexOf("move:A"))
    }
}
