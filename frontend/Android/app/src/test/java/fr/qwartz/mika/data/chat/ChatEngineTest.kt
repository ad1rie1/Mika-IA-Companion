package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.db.OutboxEntity
import fr.qwartz.mika.data.files.OutboxFiles
import fr.qwartz.mika.data.net.FakeClock
import fr.qwartz.mika.data.net.FrameCodec
import fr.qwartz.mika.data.net.HistoryEntry
import fr.qwartz.mika.data.net.RejectedAttachment
import fr.qwartz.mika.data.net.ServerFrame
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** Le moteur du fil contre un fil en mémoire : ce que chaque trame fait de la conversation. */
@OptIn(ExperimentalCoroutinesApi::class)
class ChatEngineTest {
    @get:Rule val folder = TemporaryFolder()

    private class Rig(scope: TestScope, root: java.io.File) {
        val store = MemoryThreadStore()
        val engine = ChatEngine(
            store, OutboxFiles(root), FakeClock(scope.testScheduler), scope.backgroundScope,
            io = StandardTestDispatcher(scope.testScheduler),
        )
        val events = mutableListOf<ChatEvent>()

        suspend fun pending(text: String, cid: String) = store.mutate {
            thread.add(StoredMessage(text, Sender.USER, 1, cid = cid, status = MessageStatus.PENDING))
            outboxPut(OutboxEntity(cid, text, "[]", 10, 1))
        }

        fun speech(json: String) = FrameCodec.decode("""{"type":"speech",$json}""") as ServerFrame.Speech
    }

    private fun test(body: suspend Rig.(TestScope) -> Unit) = runTest {
        val rig = Rig(this, folder.newFolder())
        // Un collecteur « immédiat » : chaque annonce est reçue avant que l'émetteur ne reprenne.
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            rig.engine.events.collect { rig.events += it }
        }
        rig.body(this)
    }

    @Test fun `une réponse rattache la question, s'ajoute au fil et s'annonce`() = test {
        pending("salut", "c1")
        engine.onSpeech(speech(""""text":"Coucou ! [LAUGH]","message_id":12,"user_message_id":11,"client_msg_id":"c1""""))
        val thread = store.sorted()
        assertEquals(listOf("salut", "Coucou!"), thread.map { it.text })
        assertEquals(11L, thread[0].id)
        assertEquals(MessageStatus.SENT, thread[0].status)
        assertEquals(12L, engine.cursor)
        val event = events.single() as ChatEvent.MikaSpoke
        assertTrue(event.live)
        assertEquals("c1", event.replyToClientMsgId)
        assertEquals(0L, event.cursorBefore)
    }

    @Test fun `la même réponse rejouée n'est pas ajoutée deux fois`() = test {
        engine.onSpeech(speech(""""text":"une fois","message_id":5"""))
        engine.onSpeech(speech(""""text":"une fois","message_id":5"""))
        assertEquals(1, store.rows.size)
    }

    @Test fun `elle dort - la bulle le dit, rien n'est ajouté`() = test {
        pending("tu dors ?", "n1")
        engine.onSpeech(speech(""""text":"","voice_reason":"asleep","user_message_id":4,"client_msg_id":"n1""""))
        val bubble = store.rows.single()
        assertEquals(ChatSync.ASLEEP, bubble.waiting)
        assertEquals(4L, bubble.id)
        assertTrue(events.isEmpty())
    }

    @Test fun `une pensée à voix haute ne va jamais en base, et seulement à qui regarde`() = test {
        engine.onSpeech(speech(""""text":"hmm…","voice_persona":"inner""""))
        assertTrue(engine.ephemeral.value.isEmpty())
        engine.foreground = true
        engine.onSpeech(speech(""""text":"c'est qui ça ?","voice_persona":"inner""""))
        assertTrue(store.rows.isEmpty())
        val thought = engine.ephemeral.value.single()
        assertTrue(thought.inner)
        assertTrue(thought.localId < 0)
        engine.clearEphemeral()
        assertTrue(engine.ephemeral.value.isEmpty())
    }

    @Test fun `une réponse ratée sans identifiant est une note de la machine`() = test {
        engine.onSpeech(speech(""""text":"Désolée…","source":"error","message_id":null"""))
        assertTrue(store.rows.isEmpty())
        assertEquals("error", engine.ephemeral.value.single().source)
    }

    @Test fun `un accusé accepté allume « Mika écrit… », la réponse l'éteint, la file d'envoi oublie le message`() = test { scope ->
        pending("salut", "c1")
        engine.onAck(ServerFrame.Ack("c1", "accepted"))
        assertTrue(engine.typing.value)
        assertTrue(store.outbox.isEmpty())
        assertEquals(MessageStatus.SENT, store.rows.single().status)
        engine.onSpeech(speech(""""text":"Hello","message_id":3,"client_msg_id":"c1""""))
        assertFalse(engine.typing.value)
        // et le plafond : cinq minutes sans réponse éteignent l'indicateur
        pending("encore", "c2")
        engine.onAck(ServerFrame.Ack("c2", "accepted"))
        scope.testScheduler.advanceTimeBy(300_001)
        assertFalse(engine.typing.value)
    }

    @Test fun `un refus est un échec raisonné, et rien n'est attendu`() = test {
        pending("photos", "c1")
        engine.onAck(ServerFrame.Ack("c1", "accepted", listOf(RejectedAttachment("gros.png", "too_large"))))
        assertTrue(store.rows.single().note!!.contains("gros.png"))
        pending("spam", "c2")
        engine.onAck(ServerFrame.Ack("c2", "rate_limited"))
        val refused = store.rows.first { it.cid == "c2" }
        assertEquals(MessageStatus.FAILED, refused.status)
        assertEquals("trop de messages d'affilée", refused.reason)
        assertFalse(engine.typing.value)
    }

    @Test fun `un historique d'une autre vie vide le fil sauf ce qui part encore`() = test {
        store.kv[Kv.LIFE] = "ancienne"
        store.mutate { thread.add(StoredMessage("vieux", Sender.MIKA, 1, id = 900)) }
        pending("en partance", "c9")
        engine.onHistory(
            ServerFrame.History(
                mode = "initial",
                messages = listOf(HistoryEntry(id = 3, role = "assistant", text = "coucou", ts = 1.0)),
                life = "neuve",
            ),
        )
        assertEquals(listOf("coucou", "en partance"), store.sorted().map { it.text })
        assertEquals("neuve", store.kv[Kv.LIFE])
        assertEquals(3L, engine.cursor)
        val event = events.single() as ChatEvent.MikaSpoke
        assertFalse(event.live)
        assertEquals(listOf("coucou"), event.messages.map { it.text })
    }

    @Test fun `la troncature - une fenêtre initiale tranche, un rattrapage s'ajoute`() = test {
        engine.onHistory(ServerFrame.History(mode = "catchup", messages = listOf(HistoryEntry(7, "user", "a")), truncated = true))
        assertTrue(engine.truncated.value)
        assertEquals("7", store.kv[Kv.GAP_BEFORE_ID])
        engine.onHistory(ServerFrame.History(mode = "catchup", messages = emptyList(), truncated = false))
        assertTrue(engine.truncated.value)
        engine.onHistory(ServerFrame.History(mode = "initial", messages = emptyList(), truncated = false))
        assertFalse(engine.truncated.value)
        assertNull(store.kv[Kv.TRUNCATED])
    }

    @Test fun `un rattrapage qui contient sa réponse éteint « Mika écrit… »`() = test {
        pending("q", "c1")
        engine.onAck(ServerFrame.Ack("c1", "accepted"))
        engine.onHistory(
            ServerFrame.History(messages = listOf(HistoryEntry(1, "user", "q"), HistoryEntry(2, "assistant", "r"))),
        )
        assertFalse(engine.typing.value)
        assertEquals(listOf(1L, 2L), store.sorted().map { it.id })
    }

    @Test fun `un rattrapage signale les réponses aux questions posées d'ailleurs`() = test {
        // Une question tapée ici (la nôtre), puis, pendant l'absence, une question tapée sur la page web.
        pending("depuis le téléphone", "c1")
        engine.onHistory(
            ServerFrame.History(
                messages = listOf(
                    HistoryEntry(10, "user", "depuis le téléphone"),
                    HistoryEntry(11, "assistant", "réponse au téléphone"),
                    HistoryEntry(12, "user", "depuis la page web"),
                    HistoryEntry(13, "assistant", "réponse à la page"),
                    HistoryEntry(14, "assistant", "et un rappel, plus tard"),
                ),
            ),
        )
        val event = events.single() as ChatEvent.MikaSpoke
        assertEquals(listOf(11L, 13L, 14L), event.messages.map { it.id })
        assertEquals(setOf(13L), event.answeredElsewhere)
    }
}
