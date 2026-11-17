package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Ménager ce qui sort du serveur, porté de `frontendv2/src/screens/carte/requests.ts` (ses tests : `requests.test.ts`,
 * mêmes cas) : le trajet d'un voyage, celui de ses arrêts, relu une fois qu'ils ne bougent plus ; les gestes l'un après
 * l'autre ; ce qu'un refus fait de la clé ; quand « Sur la route » se recherche.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TripRequestsTest {
    private fun stop(id: String, lat: Double?, lon: Double? = 3.0) = TripStop(id, "Arrêt $id", "", lat, lon, "", "toi")

    private val trip = Trip(
        id = "640", title = "Les Alpes", mode = "voiture",
        days = listOf(TripDay(1, "", listOf(stop("1", 50.0), stop("2", 49.0), stop("3", 48.0))), TripDay(2, "", listOf(stop("4", 47.0)))),
    )

    private fun route(km: Int) = TripRoute(distanceM = km * 1000.0, durationS = km * 40.0)

    @Test fun `ouvert, lu de suite, puis gardé tant que ses arrêts ne changent pas (une note, un titre n'y font rien)`() = runTest {
        var calls = 0
        val landed = mutableListOf<String>()
        val routes = TripRoutes(this, { calls += 1; MoiApi.Result.Ok(route(500)) }, { landed += it })
        assertEquals(TripRoutes.Shown(null, null, true), routes.shown(trip))
        routes.want(trip, soon = true)
        advanceUntilIdle()
        assertEquals(1, calls)
        assertEquals(listOf("640"), landed)
        assertEquals(500_000.0, routes.shown(trip).route!!.distanceM, 0.0)
        val renamed = trip.copy(title = "Autre", updated = 2, days = trip.days.map { d -> d.copy(stops = d.stops.map { it.copy(note = "réserver") }) })
        routes.want(renamed, soon = true)
        routes.want(renamed)
        advanceUntilIdle()
        assertEquals(1, calls)
        assertEquals(500_000.0, routes.shown(renamed).route!!.distanceM, 0.0)
    }

    @Test fun `dix gestes d'affilée, une seule relecture, après le dernier, d'ici là, le trajet d'avant ne se montre pas`() = runTest {
        var km = 500
        var calls = 0
        val routes = TripRoutes(this, { calls += 1; MoiApi.Result.Ok(route(km)) }, {})
        // onze arrêts : le premier passe au bout, dix fois (jamais revenu à l'ordre du départ)
        val long = trip.copy(days = listOf(TripDay(1, "", (0 until 11).map { stop("s$it", 45 + it / 10.0) })))
        routes.want(long, soon = true)
        advanceUntilIdle()
        var t = long
        repeat(10) {
            t = movedTrip(t, t.days[0].stops[0].id, 1, -1)
            routes.want(t)
            assertNull(routes.shown(t).route) // ce n'est plus celui de ces arrêts
            assertTrue(routes.shown(t).pending)
            advanceTimeBy(ROUTE_WAIT_MS - 200)
            runCurrent()
            routes.want(t, soon = true) // un dessin entre deux gestes n'écourte pas l'attente
        }
        assertEquals(1, calls)
        km = 620
        advanceTimeBy(ROUTE_WAIT_MS)
        runCurrent()
        assertEquals(2, calls)
        assertEquals(620_000.0, routes.shown(t).route!!.distanceM, 0.0)
    }

    @Test fun `monté puis redescendu, revenu à ses arrêts, rien ne se relit`() = runTest {
        var calls = 0
        val routes = TripRoutes(this, { calls += 1; MoiApi.Result.Ok(route(500)) }, {})
        routes.want(trip, soon = true)
        advanceUntilIdle()
        routes.want(movedTrip(trip, "3", 1, 0))
        routes.want(trip)
        advanceUntilIdle()
        assertEquals(1, calls)
        assertNotNull(routes.shown(trip).route)
    }

    @Test fun `une relecture refusée (429, 503), le refus, et plus le trajet d'avant à côté, Réessayer la refait`() = runTest {
        var fail = false
        val routes = TripRoutes(this, {
            if (fail) MoiApi.Result.Failed(MoiError(429, "Trop de trajets ou d'adresses demandés d'affilée : attends une minute.")) else MoiApi.Result.Ok(route(500))
        }, {})
        routes.want(trip, soon = true)
        advanceUntilIdle()
        fail = true
        val moved = movedTrip(trip, "1", 1, 2)
        routes.want(moved)
        advanceUntilIdle()
        val shown = routes.shown(moved)
        assertNull(shown.route)
        assertEquals(429, shown.error!!.code)
        assertFalse(shown.pending)
        fail = false
        routes.want(moved, soon = true) // le même refus : pas de relance d'elle-même
        advanceUntilIdle()
        assertNotNull(routes.shown(moved).error)
        routes.want(moved, force = true) // « Réessayer »
        advanceUntilIdle()
        assertEquals(500_000.0, routes.shown(moved).route!!.distanceM, 0.0)
    }

    @Test fun `sous deux arrêts, pas de trajet, rien ne se demande`() = runTest {
        var calls = 0
        val routes = TripRoutes(this, { calls += 1; MoiApi.Result.Ok(route(500)) }, {})
        val two = removedTrip(removedTrip(trip, "3"), "4")
        routes.want(two, soon = true)
        advanceUntilIdle()
        assertNotNull(routes.shown(two).route)
        val one = removedTrip(two, "2")
        routes.want(one)
        advanceUntilIdle()
        assertEquals(1, calls)
        assertEquals(TripRoutes.Shown(null, null, false), routes.shown(one))
        routes.want(two) // revenu à deux : relu (l'ancien n'a pas été gardé)
        advanceUntilIdle()
        assertEquals(2, calls)
    }

    @Test fun `une relecture partie avant un autre geste ne remplace pas celle qui la suit`() = runTest {
        val answers = mutableListOf<CompletableDeferred<TripRoute>>()
        val routes = TripRoutes(this, { CompletableDeferred<TripRoute>().also { answers += it }.let { MoiApi.Result.Ok(it.await()) } }, {})
        routes.want(trip, soon = true)
        val moved = movedTrip(trip, "1", 1, 2)
        routes.want(moved, soon = true)
        runCurrent()
        assertEquals(2, answers.size)
        answers[1].complete(route(700))
        runCurrent()
        answers[0].complete(route(500)) // la plus vieille arrive après
        advanceUntilIdle()
        assertEquals(700_000.0, routes.shown(moved).route!!.distanceM, 0.0)
    }

    @Test fun `les gestes l'un après l'autre, un refus annule ceux qui attendaient derrière lui`() = runTest {
        val done = mutableListOf<String>()
        val queue = GestureQueue()
        val gate = CompletableDeferred<Unit>()
        val first = async { queue.run { gate.await(); done += "premier"; null } }
        val second = async { queue.run { done += "second"; null } }
        runCurrent()
        assertTrue(queue.busy)
        assertEquals(emptyList<String>(), done) // le second attend
        gate.complete(Unit)
        assertEquals(GestureQueue.Outcome.Done, first.await())
        assertEquals(GestureQueue.Outcome.Done, second.await())
        assertEquals(listOf("premier", "second"), done)
        assertFalse(queue.busy)
        // le refus arrive pendant que le geste suivant attend derrière lui
        val answer = CompletableDeferred<Unit>()
        val refusedOne = async { queue.run { answer.await(); MoiError(409, "La situation a changé.") } }
        val after = async { queue.run { done += "après le refus"; null } }
        runCurrent()
        answer.complete(Unit)
        assertEquals(409, (refusedOne.await() as GestureQueue.Outcome.Refused).error.code)
        assertEquals(GestureQueue.Outcome.Cancelled, after.await())
        assertFalse("après le refus" in done)
        assertEquals(GestureQueue.Outcome.Done, queue.run { done += "un geste neuf"; null })
        assertTrue("un geste neuf" in done)
    }

    @Test fun `un envoi refusé a usé sa clé, une panne ou un 429, non (on le refait avec la même)`() {
        assertTrue(refused(MoiError(409, "Un voyage a 60 arrêts au plus.")))
        assertTrue(refused(MoiError(400, "Un voyage a un titre.")))
        assertTrue(refused(MoiError(404, "Introuvable.")))
        assertFalse(refused(MoiError(429, "Trop de demandes.")))
        assertFalse(refused(MoiError(503, "Le serveur n'a pas pu répondre.")))
        assertFalse(refused(MoiError(0, MoiError.NETWORK)))
        assertFalse(refused(null))
    }

    @Test fun `Sur la route ne se recherche que si le trajet a changé`() {
        val along = AlongState("640", cat = "voir", key = "k1")
        assertEquals(AlongNext.KEEP, alongAfterRoute(along, "k1"))
        assertEquals(AlongNext.KEEP, alongAfterRoute(along.copy(cat = ""), "k2")) // fermé
        assertEquals(AlongNext.RELOAD, alongAfterRoute(along, "k2"))
        assertEquals(AlongNext.ADOPT, alongAfterRoute(along.copy(adopt = true), "k2"))
        assertEquals(AlongNext.RELOAD, alongAfterRoute(along.copy(adopt = true, loading = true), "k2")) // une recherche partie avant
    }
}
