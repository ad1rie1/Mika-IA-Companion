package fr.qwartz.mika.ui.phone

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.phone.OfferStates
import fr.qwartz.mika.data.moi.phone.PhoneMoiApi
import fr.qwartz.mika.data.moi.phone.PhoneOffer
import fr.qwartz.mika.data.moi.phone.PhoneThread
import fr.qwartz.mika.data.moi.phone.ReadMessage
import fr.qwartz.mika.data.phone.HereOutcome
import fr.qwartz.mika.data.phone.PhoneDraft
import fr.qwartz.mika.data.phone.PhoneHere
import fr.qwartz.mika.data.phone.PhoneHereGestures
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Répondre d'ici dans un fil du Téléphone : le champ ne garde pas sa proposition telle quelle une fois réglée, et une
 * proposition qui n'attend plus ne fait rien partir toute seule (R3-04) ; un geste fini après qu'on a quitté l'écran ne
 * se rejoue pas ailleurs (R3-08) ; un geste parti va au bout même si l'écran s'en va (R3-12) ; ce qui part d'ici vise le
 * fil montré (R3-06).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PhoneThreadModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val now = 1_800_000_000_000L
    private val hex = "611ae22e6d5c431f8b537e638278435d"
    private val key = "whatsapp|$hex"
    private val other = "whatsapp|${"b".repeat(32)}"
    private val proposed = "9h ça me va 👍"
    private val offer = PhoneOffer(7, OfferStates.OFFERED, now - 60_000, now + 3_600_000, text = proposed)
    private val draft = PhoneDraft(7, "whatsapp", hex, "Léa", proposed, now + 3_600_000, now - 60_000)

    private class FakeApi : PhoneMoiApi(MoiApi(OkHttpClient(), { null }, {})) {
        val threads = HashMap<String, PhoneThread>()
        override suspend fun thread(conversation: String, size: Int): MoiApi.Result<PhoneThread> =
            threads[conversation]?.let { MoiApi.Result.Ok(it) } ?: MoiApi.Result.Failed(MoiError(404, "Introuvable : ce n'est plus là."))
    }

    /** Ce que fait `PhoneDraftNotifier` : [gate] retient le geste entre l'envoi et son règlement au carnet. */
    private class FakeHere(var drafts: List<PhoneDraft>) : PhoneHereGestures {
        var kept = mapOf<String, String>()
        var sendResult = HereOutcome.SENT
        var gate: CompletableDeferred<Unit>? = null
        val calls = mutableListOf<String>()
        val settled = mutableListOf<Long>()

        override suspend fun waiting(): List<PhoneDraft> = drafts
        override fun replyTo(thread: String): String? = kept[thread]
        override suspend fun sendHere(id: Long, typed: String?, to: String): HereOutcome {
            calls += "send:$id:${typed ?: "-"}:$to"
            gate?.await()
            if (sendResult != HereOutcome.GONE) {
                settled += id
                drafts = drafts.filterNot { it.id == id }
            }
            return sendResult
        }
        override suspend fun ignoreHere(id: Long): HereOutcome {
            calls += "ignore:$id"
            settled += id
            drafts = drafts.filterNot { it.id == id }
            return HereOutcome.IGNORED
        }
        override suspend fun replyHere(thread: String, text: String, to: String): HereOutcome {
            calls += "reply:$thread:$text:$to"
            return if (PhoneHere.canDeliver(kept[thread], to)) HereOutcome.SENT else HereOutcome.COPIED
        }
        override suspend fun flushNow() {
            calls += "flush"
        }
    }

    private val api = FakeApi().apply {
        threads[key] = PhoneThread(key, "whatsapp", "WhatsApp", messages = listOf(ReadMessage("p1", now - 120_000, false, "Léa", "On se retrouve à quelle heure ?")), offers = listOf(offer))
        threads[other] = PhoneThread(other, "whatsapp", "WhatsApp", messages = listOf(ReadMessage("p9", now - 60_000, false, "Paul", "Ça marche")))
    }
    private val here = FakeHere(listOf(draft))
    private val app = CoroutineScope(SupervisorJob() + Dispatchers.Main)
    private val deps = PhoneThreadDeps(api, here, { now }, app)
    private val vm by lazy { main.model { PhoneThreadViewModel(deps) } }

    @After fun stop() = app.cancel()

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(200) { first() }

    // ── R3-04 ──

    @Test fun `« Écrire autre chose » puis « Envoyer » sur la carte - son texte ne reste pas dans le champ`() = runTest {
        vm.open(key, "v1")
        advanceUntilIdle()
        vm.writeOther(offer, draft, "occupé")
        assertEquals(proposed, vm.text)
        vm.sendOffer(offer)
        advanceUntilIdle()
        assertEquals("", vm.text)
        assertEquals(0L, vm.editing)
        // un toucher de plus n'envoie rien une seconde fois
        vm.send()
        advanceUntilIdle()
        assertEquals(listOf("send:7:-:Léa"), here.calls.filter { it.startsWith("send") || it.startsWith("reply") })
    }

    @Test fun `« Écrire autre chose » puis « Ignorer » - sa proposition ne repart pas comme ton message`() = runTest {
        vm.open(key, "v1")
        advanceUntilIdle()
        vm.writeOther(offer, draft, "occupé")
        vm.ignore(offer)
        advanceUntilIdle()
        assertEquals("", vm.text)
        vm.send()
        advanceUntilIdle()
        assertFalse(here.calls.any { it.startsWith("reply") })
    }

    @Test fun `ta version retouchée reste quand sa proposition est réglée, et l'écran le dit`() = runTest {
        vm.open(key, "v1")
        advanceUntilIdle()
        val done = vm.gestures("v1")
        vm.writeOther(offer, draft, "occupé")
        vm.type("9h30 plutôt")
        vm.ignore(offer)
        advanceUntilIdle()
        assertEquals("9h30 plutôt", vm.text)
        assertEquals(0L, vm.editing)
        assertEquals(FieldNote.KEPT_AS_YOURS, done.next()?.field)
    }

    @Test fun `elle n'attend plus quand tu envoies ta version - rien ne part tout seul par « Répondre »`() = runTest {
        vm.open(key, "v1")
        advanceUntilIdle()
        val done = vm.gestures("v1")
        here.sendResult = HereOutcome.GONE
        vm.writeOther(offer, draft, "occupé")
        vm.type("9h30 plutôt")
        vm.send()
        advanceUntilIdle()
        assertFalse(here.calls.any { it.startsWith("reply") })
        assertEquals("9h30 plutôt", vm.text)
        assertEquals(0L, vm.editing)
        val d = done.next()
        assertEquals(HereOutcome.GONE, d?.outcome)
        assertEquals(FieldNote.NOT_SENT, d?.field)
    }

    @Test fun `envoyée depuis sa notification pendant que le champ la tient - la relecture la retire du champ`() = runTest {
        vm.open(key, "v1")
        advanceUntilIdle()
        vm.writeOther(offer, draft, "occupé")
        api.threads[key] = api.threads.getValue(key).copy(offers = listOf(offer.copy(state = OfferStates.SENT)))
        vm.refresh()
        advanceUntilIdle()
        assertEquals("", vm.text)
        assertEquals(0L, vm.editing)
    }

    // ── R3-08 ──

    @Test fun `un geste fini après avoir quitté l'écran ne se rejoue pas sur le fil suivant`() = runTest {
        vm.open(key, "v1")
        advanceUntilIdle()
        here.gate = CompletableDeferred()
        vm.sendOffer(offer)
        // ← aussitôt, puis une autre conversation
        vm.open(other, "v2")
        advanceUntilIdle()
        here.gate!!.complete(Unit)
        advanceUntilIdle()
        assertNull(vm.gestures("v2").next())
    }

    // ── R3-12 ──

    @Test fun `un geste parti va au bout même si l'écran s'en va entre l'envoi et le carnet`() = runTest {
        val store = ViewModelStore()
        val factory = object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T = modelClass.cast(PhoneThreadViewModel(deps))!!
        }
        val model = ViewModelProvider(store, factory)[PhoneThreadViewModel::class.java]
        model.open(key, "v1")
        advanceUntilIdle()
        here.gate = CompletableDeferred()
        model.sendOffer(offer)
        // l'activité finie : le modèle est détruit pendant le geste
        store.clear()
        here.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(listOf(7L), here.settled)
        assertTrue("flush" in here.calls)
    }

    // ── R3-06 ──

    @Test fun `ton message vise le fil montré - l'action gardée pour une autre conversation ne sert pas`() = runTest {
        here.kept = mapOf(hex to "Maman")
        vm.open(key, "v1")
        advanceUntilIdle()
        assertEquals("Maman", vm.replyTo)
        val done = vm.gestures("v1")
        vm.type("J'arrive")
        vm.send()
        advanceUntilIdle()
        assertTrue("reply:$hex:J'arrive:Léa" in here.calls)
        assertEquals(HereOutcome.COPIED, done.next()?.outcome)
    }
}
