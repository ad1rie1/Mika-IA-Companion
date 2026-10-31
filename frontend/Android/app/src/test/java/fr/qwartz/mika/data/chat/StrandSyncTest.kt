package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.db.OutboxEntity
import fr.qwartz.mika.data.files.OutboxFiles
import fr.qwartz.mika.data.net.FakeClock
import fr.qwartz.mika.data.net.FrameCodec
import fr.qwartz.mika.data.net.HistoryEntry
import fr.qwartz.mika.data.net.ServerFrame
import fr.qwartz.mika.data.net.StrandInfo
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * Les fils de travail dans le fil local (ADR 0164) : chaque message garde son fil, une bulle n'est adoptée que par une
 * ligne de son fil, l'historique d'un fil se fond sans toucher au reste, « Mika écrit… » et les cartes de travail
 * vont au fil où elle répond.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class StrandSyncTest {
    @get:Rule val folder = TemporaryFolder()

    private class Rig(scope: TestScope, root: java.io.File) {
        val store = MemoryThreadStore()
        val engine = ChatEngine(
            store, OutboxFiles(root), FakeClock(scope.testScheduler), scope.backgroundScope,
            io = StandardTestDispatcher(scope.testScheduler),
        )
        val events = mutableListOf<ChatEvent>()
        val notices = mutableListOf<String>()

        suspend fun pending(text: String, cid: String, strand: String? = null) = store.mutate {
            thread.add(StoredMessage(text, Sender.USER, 1, cid = cid, status = MessageStatus.PENDING, strand = strand,
                mode = if (strand != null) "pro" else null))
            outboxPut(OutboxEntity(cid, text, "[]", 10, 1, mode = if (strand != null) "pro" else null, strand = strand))
        }
    }

    private fun test(body: suspend Rig.(TestScope) -> Unit) = runTest {
        val rig = Rig(this, folder.newFolder())
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { rig.engine.events.collect { rig.events += it } }
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) {
            rig.engine.strandNotices.collect { rig.notices += it }
        }
        rig.body(this)
    }

    @Test fun `une ligne d'un fil de travail garde son fil, et n'adopte que la bulle de son fil`() {
        // « ok » tapé dans deux fils : la ligne du fil devis n'adopte que la bulle du fil devis
        val history = mutableListOf(
            StoredMessage("ok", Sender.USER, 1, cid = "c1", status = MessageStatus.PENDING, strand = "code"),
            StoredMessage("ok", Sender.USER, 2, cid = "c2", status = MessageStatus.PENDING, strand = "devis"),
        )
        val merged = ChatSync.mergeHistory(
            history,
            listOf(
                HistoryEntry(id = 10, role = "user", text = "ok", ts = 1.0, mode = "pro", strand = "devis"),
                HistoryEntry(id = 11, role = "assistant", text = "Voilà.", ts = 2.0, mode = "pro", strand = "devis"),
            ),
            50,
        ).history
        assertEquals(10L, merged.first { it.cid == "c2" }.id)
        assertNull(merged.first { it.cid == "c1" }.id)
        assertEquals("devis", merged.first { it.id == 11L }.strand)
    }

    @Test fun `le serveur fait foi - un message qu'il a rangé hors d'un fil y retourne`() {
        val shown = StoredMessage("salut", Sender.USER, 1, id = 5, strand = "devis")
        val merged = ChatSync.mergeHistory(mutableListOf(shown), listOf(HistoryEntry(id = 5, role = "user", text = "salut")), 50)
        assertEquals(1, merged.reworked)
        assertNull(merged.history.single().strand)
    }

    @Test fun `sa réponse dans un fil y va, et « Mika écrit… » se dit dans le fil où elle écrit`() = test {
        pending("liste moi les devis", "c1", strand = "devis")
        engine.onAck(ServerFrame.Ack("c1", "accepted"))
        assertTrue(engine.typing.value)
        assertEquals("devis", engine.typingIn.value)
        engine.onSpeech(
            FrameCodec.decode(
                """{"type":"speech","text":"Voilà.","mode":"pro","strand":"devis","message_id":12,"user_message_id":11,"client_msg_id":"c1"}""",
            ) as ServerFrame.Speech,
        )
        val reply = store.sorted().last()
        assertEquals("devis", reply.strand)
        assertEquals(12L, reply.id)
        // un message du fil avec elle : « Mika écrit… » y revient
        pending("salut", "c2")
        engine.onAck(ServerFrame.Ack("c2", "accepted"))
        assertNull(engine.typingIn.value)
    }

    @Test fun `l'historique d'un fil se fond sans avancer le curseur ni rien annoncer`() = test {
        engine.onHistory(
            ServerFrame.History(mode = "catchup", messages = listOf(HistoryEntry(id = 20, role = "assistant", text = "coucou"))),
        )
        events.clear()
        engine.onHistory(
            ServerFrame.History(
                mode = "strand",
                strand = "devis",
                more = false,
                life = "une autre empreinte",
                messages = listOf(
                    HistoryEntry(id = 4, role = "user", text = "liste", mode = "pro", strand = "devis"),
                    HistoryEntry(id = 5, role = "assistant", text = "Voilà.", mode = "pro", strand = "devis"),
                    // plus récent que le curseur : le rattrapage l'apportera, avec ce qui le précède
                    HistoryEntry(id = 30, role = "assistant", text = "plus tard", mode = "pro", strand = "devis"),
                    // une ligne d'un autre fil n'a rien à faire là
                    HistoryEntry(id = 6, role = "user", text = "ailleurs", strand = "code"),
                ),
            ),
        )
        assertEquals(listOf("liste", "Voilà.", "coucou"), store.sorted().map { it.text })
        assertEquals(20L, engine.cursor)
        // ni vie changée (le fil ordinaire reste), ni annonce : ce sont de vieux messages
        assertTrue(events.isEmpty())
        assertTrue(store.sorted().any { it.text == "coucou" })
    }

    @Test fun `la liste de ses fils remplace la précédente, un refus de réglage se dit`() = test {
        engine.onStrands(ServerFrame.Strands(listOf(StrandInfo("devis", title = "Devis"))))
        engine.onStrands(ServerFrame.Strands(listOf(StrandInfo("code"))))
        assertEquals(listOf("code"), engine.strands.value.map { it.id })
        engine.onStrandResult(ServerFrame.StrandResult("code", "ok"))
        assertTrue(notices.isEmpty())
        engine.onStrandResult(ServerFrame.StrandResult("code", "invalid"))
        engine.onStrandNotSent()
        assertEquals(listOf(Strands.resultNotice("invalid"), Strands.NOT_SENT), notices)
        engine.reset()
        assertTrue(engine.strands.value.isEmpty())
    }

    @Test fun `une carte de travail garde le fil où elle répond`() {
        val f = FrameCodec.decode(
            """{"type":"tool","episode":"e1","reply_to":11,"phase":"start","call_id":"t1","name":"devis_list","strand":"devis"}""",
        ) as ServerFrame.Tool
        assertEquals("devis", WorkLog().apply(f).cards.single().strand)
        val ordinary = FrameCodec.decode("""{"type":"tool","episode":"e2","reply_to":12,"phase":"start","call_id":"t2","name":"x"}""")
            as ServerFrame.Tool
        assertNull(WorkLog().apply(ordinary).cards.single().strand)
    }
}
