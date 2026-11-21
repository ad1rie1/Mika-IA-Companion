package fr.qwartz.mika.ui.carte

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.PlaceFiche
import fr.qwartz.mika.data.moi.carte.PlaceRefreshed
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * La fiche d'un lieu contre une fausse API : « Actualiser » sur un 503 dit ce qui n'a pas pu se relire et relit la fiche
 * une fois, sur un 429 ne relit rien ; réussi, il remplace une lecture en cours (qui ne revient pas l'écraser) et passe
 * le lieu relu à la liste d'Explorer (R2-A06) ; ce qui n'a pas pu se relire ne reste pas affiché à la visite suivante,
 * quand la fiche se relit (R2-A07).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PlaceFicheModelTest {
    @get:Rule val main = MainDispatcherRule()

    private var clock = 1_000_000L
    private val reads = mutableListOf<String>()
    private var gate: CompletableDeferred<Unit>? = null
    private var rating = 4.7
    private var refreshed: MoiApi.Result<PlaceRefreshed> = MoiApi.Result.Failed(MoiError(503, "Rien de réglé."))

    private fun fiche(r: Double) = PlaceFiche(place = Place(id = "l22871", osm = "n4021153781", name = "Magmatic", rating = r))

    private val deps = FicheDeps(
        read = { id ->
            reads += id
            val r = rating
            gate?.await()
            MoiApi.Result.Ok(fiche(r))
        },
        refresh = { refreshed },
        now = { clock },
        refreshedWord = "Fiche relue.",
    )
    private val vm by lazy { main.model { PlaceFicheViewModel(deps, "n4021153781") } }

    private fun shownRating(): Double? = (vm.load as? Load.Ready)?.value?.place?.rating

    @Test fun `un 503 se dit et la fiche se relit une fois, un 429 ne relit rien`() = runTest {
        vm.resume()
        advanceUntilIdle()
        assertEquals(1, reads.size)
        refreshed = MoiApi.Result.Failed(MoiError(503, "le quota du jour de ce serveur (« Actualiser ») est atteint : il revient à 14:05."))
        vm.refresh()
        advanceUntilIdle()
        assertEquals("le quota du jour de ce serveur (« Actualiser ») est atteint : il revient à 14:05.", vm.refreshNote)
        assertEquals(2, reads.size)
        refreshed = MoiApi.Result.Failed(MoiError(429, "Trop de fiches actualisées d'affilée : attends une minute."))
        vm.refresh()
        advanceUntilIdle()
        assertEquals("Trop de fiches actualisées d'affilée : attends une minute.", vm.refreshNote)
        assertEquals(2, reads.size)
    }

    @Test fun `réussi, il remplace la lecture en cours et passe le lieu relu à la liste`() = runTest {
        val passed = mutableListOf<Place>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.refreshedPlace.collect { passed += it } }
        gate = CompletableDeferred()
        vm.resume()
        advanceUntilIdle()
        refreshed = MoiApi.Result.Ok(PlaceRefreshed(ok = true, message = "Fiche relue.", place = fiche(4.8).place))
        vm.refresh()
        advanceUntilIdle()
        assertEquals(4.8, shownRating()!!, 0.0)
        // la lecture partie avant revient : elle ne remet pas l'ancienne note
        gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(4.8, shownRating()!!, 0.0)
        assertEquals(listOf(4.8), passed.map { it.rating })
    }

    @Test fun `après un 503, la fiche relue passe aussi le lieu à la liste`() = runTest {
        // R3-03 : Google relu (4,7 → 4,8), DATAtourisme retenu par son quota de l'heure — un 503, ce qui a pu se relire
        // est gardé ; la fiche relue montre 4,8, et la ligne d'Explorer doit le suivre, comme sur le web
        val passed = mutableListOf<Place>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.refreshedPlace.collect { passed += it } }
        vm.resume()
        advanceUntilIdle()
        assertEquals(emptyList<Place>(), passed)
        rating = 4.8
        refreshed = MoiApi.Result.Failed(MoiError(503, "le quota de l'heure de DATAtourisme est atteint : il revient à 11:00."))
        vm.refresh()
        advanceUntilIdle()
        assertEquals(4.8, shownRating()!!, 0.0)
        assertEquals(listOf(4.8), passed.map { it.rating })
        // une simple relecture au retour sur l'écran ne passe rien à la liste
        clock += 3 * 60_000
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf(4.8), passed.map { it.rating })
    }

    @Test fun `ce qui n'a pas pu se relire ne reste pas à la visite suivante, quand la fiche se relit`() = runTest {
        vm.resume()
        advanceUntilIdle()
        refreshed = MoiApi.Result.Failed(MoiError(503, "le quota du jour de ce serveur (« Actualiser ») est atteint : il revient à 14:05."))
        vm.refresh()
        advanceUntilIdle()
        assertEquals("le quota du jour de ce serveur (« Actualiser ») est atteint : il revient à 14:05.", vm.refreshNote)
        // de retour un peu plus tard : la fiche est encore fraîche, la note reste (elle vient d'être dite)
        clock += 60_000
        vm.resume()
        advanceUntilIdle()
        assertEquals("le quota du jour de ce serveur (« Actualiser ») est atteint : il revient à 14:05.", vm.refreshNote)
        // trois minutes plus tard : la fiche se relit, et ce qui datait de 10:00 ne se dit plus
        clock += 3 * 60_000
        vm.resume()
        advanceUntilIdle()
        assertEquals(3, reads.size)
        assertEquals("", vm.refreshNote)
    }
}
