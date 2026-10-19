package fr.qwartz.mika.data.location

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.onCompletion
import kotlinx.coroutines.flow.onStart
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Test

/** Ce qui part à Mika de sa position, selon le réglage et le premier plan (ADR 0119). */
@OptIn(ExperimentalCoroutinesApi::class)
class WhereShareTest {
    private val fix = WhereShare.Fix(45.764043, 4.835659, 12, "Rue de la République, Lyon", fixElapsedMs = 1_000)

    @Test fun `au premier plan et permis, ses mesures - coupé, off - quitté, rien et plus personne n'écoute`() = runTest {
        val sharing = MutableStateFlow(false)
        val visible = MutableStateFlow(false)
        val measures = MutableSharedFlow<WhereShare>()
        var listening = 0
        var subscriptions = 0
        val sent = mutableListOf<WhereShare?>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            WhereShare.follow(sharing, visible) {
                measures.onStart { listening += 1; subscriptions += 1 }.onCompletion { listening -= 1 }
            }.collect { sent += it }
        }
        // l'app fermée : rien
        assertEquals(listOf<WhereShare?>(null), sent)
        visible.value = true
        assertEquals(listOf(null, WhereShare.Off), sent)
        sharing.value = true
        assertEquals(1, listening)
        measures.emit(fix)
        assertEquals(listOf(null, WhereShare.Off, fix), sent)
        // quitter l'écran : rien ne part plus, la localisation n'est plus écoutée
        visible.value = false
        assertEquals(null, sent.last())
        assertEquals(0, listening)
        // y revenir : écoutée de nouveau (l'autorisation y est revue)
        visible.value = true
        assertEquals(1, listening)
        assertEquals(2, subscriptions)
        sharing.value = false
        assertEquals(WhereShare.Off, sent.last())
        assertEquals(0, listening)
    }
}
