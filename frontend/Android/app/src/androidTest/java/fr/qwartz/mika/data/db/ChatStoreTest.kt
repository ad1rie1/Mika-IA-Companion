package fr.qwartz.mika.data.db

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import fr.qwartz.mika.data.chat.ChatSync
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

/** Le fil dans un vrai Room (en mémoire) : la différence écrite, les clés, la file d'envoi, l'effacement. */
@RunWith(AndroidJUnit4::class)
class ChatStoreTest {
    private lateinit var db: MikaDatabase
    private lateinit var store: ChatStore

    @Before fun open() {
        db = Room.inMemoryDatabaseBuilder(ApplicationProvider.getApplicationContext(), MikaDatabase::class.java).build()
        store = ChatStore(db)
    }

    @After fun close() = db.close()

    @Test fun uneMutationEcritLaDifferenceEtDonneDesClesLocales() = runTest {
        store.mutate {
            thread.add(StoredMessage("salut", Sender.USER, 1, cid = "c1", status = MessageStatus.PENDING))
            thread.add(StoredMessage("coucou", Sender.MIKA, 2, id = 7, attachments = listOf(MessageAttachment("liste.md", id = "a".repeat(32)))))
        }
        val rows = store.observe().first()
        assertEquals(listOf("coucou", "salut"), rows.map { it.text })
        assertTrue(rows.all { it.localId > 0 })
        assertEquals("liste.md", rows.first().attachments.single().name)
        assertEquals(7L, store.maxServerId())
        assertEquals(setOf("c1"), store.ownClientMsgIds())
    }

    @Test fun unAccuseMetAJourLaBulleEtOublieLaLigneDEnvoi() = runTest {
        store.mutate {
            thread.add(StoredMessage("salut", Sender.USER, 1, cid = "c1", status = MessageStatus.PENDING))
            outboxPut(OutboxEntity("c1", "salut", "[]", 100, 1))
        }
        store.mutate {
            outboxDelete("c1")
            ChatSync.applyAck(thread, "c1", "accepted")
        }
        assertEquals(MessageStatus.SENT, store.observe().first().single().status)
        assertTrue(store.outboxRows().isEmpty())
    }

    @Test fun uneLigneRetireeDuFilEstSupprimee() = runTest {
        store.mutate { thread.add(StoredMessage("x", Sender.MIKA, 1, id = 1)) }
        store.mutate { thread.clear() }
        assertTrue(store.observe().first().isEmpty())
    }

    @Test fun leffacementGardeSeulementLesClesDemandees() = runTest {
        store.mutate { thread.add(StoredMessage("x", Sender.MIKA, 1, id = 1)) }
        store.kvPut(Kv.DRAFT, "brouillon")
        store.kvPut(Kv.LIFE, "vie")
        store.wipe(keep = setOf(Kv.DRAFT))
        assertTrue(store.observe().first().isEmpty())
        assertEquals("brouillon", store.kvGet(Kv.DRAFT))
        assertNull(store.kvGet(Kv.LIFE))
    }
}
