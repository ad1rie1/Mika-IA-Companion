package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.chat.ChatSync.RESTORED_PENDING_REASON
import fr.qwartz.mika.data.chat.ChatSync.ackReason
import fr.qwartz.mika.data.chat.ChatSync.applyAck
import fr.qwartz.mika.data.chat.ChatSync.asleepNoteShown
import fr.qwartz.mika.data.chat.ChatSync.bindServerId
import fr.qwartz.mika.data.chat.ChatSync.coerceStatus
import fr.qwartz.mika.data.chat.ChatSync.cursorOf
import fr.qwartz.mika.data.chat.ChatSync.fromAnotherLife
import fr.qwartz.mika.data.chat.ChatSync.keepAcrossLives
import fr.qwartz.mika.data.chat.ChatSync.markAsleep
import fr.qwartz.mika.data.chat.ChatSync.mergeHistory
import fr.qwartz.mika.data.chat.ChatSync.noReplyNote
import fr.qwartz.mika.data.chat.ChatSync.restoredStatus
import fr.qwartz.mika.data.chat.ChatSync.sortMessages
import fr.qwartz.mika.data.chat.ChatSync.stripProsody
import fr.qwartz.mika.data.chat.ChatSync.withAttachments
import fr.qwartz.mika.data.net.AttachmentRef
import fr.qwartz.mika.data.net.HistoryEntry
import fr.qwartz.mika.data.net.RejectedAttachment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Portage 1:1 de `frontend/Web/src/ui/__tests__/chatSync.test.ts`, noms gardés. Écarts :
 * `restoredStatus` sait si la ligne a encore sa file d'envoi (elle survit ici à la mort du
 * processus) ; `readCache`/`writeCache` n'existent pas (l'empreinte de vie est gardée en base,
 * clé `life`), leurs tests se lisent donc avec une empreinte vide pour « cache d'avant ».
 */
class ChatSyncTest {
    private val MAX = 50
    private val USER = Sender.USER
    private val VTUBER = Sender.MIKA

    private fun entry(
        id: Long?,
        role: String,
        text: String,
        ts: Double = (id ?: 0L) * 1000.0,
        attachments: List<AttachmentRef> = emptyList(),
    ) = HistoryEntry(id = id, role = role, text = text, ts = ts, attachments = attachments)

    private fun local(
        text: String,
        sender: Sender,
        id: Long? = null,
        cid: String? = null,
        status: MessageStatus? = null,
        ts: Long = System.currentTimeMillis(),
        matchText: String? = null,
        after: Long? = null,
        inner: Boolean = false,
        reason: String? = null,
    ) = StoredMessage(
        text = text, sender = sender, ts = ts, id = id, cid = cid, status = status, matchText = matchText,
        reason = reason, after = after, inner = inner,
    )

    private fun texts(list: List<StoredMessage>) = list.map { it.text }

    // ── cursorOf ──

    @Test fun `is the highest server id actually held`() {
        assertEquals(
            9L,
            cursorOf(listOf(local("a", USER, id = 4), local("b", VTUBER, id = 9), local("c", USER, id = 7))),
        )
    }

    @Test fun `ignores messages that exist only in this browser`() {
        assertEquals(0L, cursorOf(listOf(local("pas encore envoye", USER, cid = "c1"))))
    }

    @Test fun `is zero on an empty thread rather than undefined`() {
        assertEquals(0L, cursorOf(emptyList()))
    }

    // ── sortMessages ──

    @Test fun `orders by server id, not by local timestamp`() {
        val history = mutableListOf(local("deuxieme", USER, id = 2, ts = 1_000), local("premier", USER, id = 1, ts = 9_999))
        assertEquals(listOf("premier", "deuxieme"), texts(sortMessages(history)))
    }

    @Test fun `puts un-persisted messages last`() {
        val history = mutableListOf(local("en attente", USER, cid = "c1", ts = 1), local("ecrit", USER, id = 5, ts = 99_999))
        assertEquals(listOf("ecrit", "en attente"), texts(sortMessages(history)))
    }

    @Test fun `places a message that will never have an id where it arrived`() {
        val history = mutableListOf(
            local("question", USER, id = 10),
            local("[Projet] fini", VTUBER, after = 10, ts = 5),
            local("reponse plus tard", VTUBER, id = 11),
        )
        assertEquals(listOf("question", "[Projet] fini", "reponse plus tard"), texts(sortMessages(history)))
    }

    @Test fun `still sorts a queued message last, after a local-only one`() {
        val history = mutableListOf(
            local("pas encore envoye", USER, cid = "c1", ts = 1),
            local("[Projet] fini", VTUBER, after = 3, ts = 999),
        )
        assertEquals(listOf("[Projet] fini", "pas encore envoye"), texts(sortMessages(history)))
    }

    @Test fun `orders un-persisted messages among themselves by local time`() {
        val history = mutableListOf(local("b", USER, cid = "c2", ts = 200), local("a", USER, cid = "c1", ts = 100))
        assertEquals(listOf("a", "b"), texts(sortMessages(history)))
    }

    // ── mergeHistory ──

    @Test fun `inserts what the client missed`() {
        val history = mutableListOf(local("ma question", USER, id = 1))
        val r = mergeHistory(history, listOf(entry(2, "assistant", "la reponse ratee")), MAX)
        assertEquals(1, r.added)
        assertEquals(listOf("ma question", "la reponse ratee"), texts(r.history))
    }

    @Test fun `does not duplicate a message it already holds`() {
        val history = mutableListOf(local("deja la", VTUBER, id = 7))
        val r = mergeHistory(history, listOf(entry(7, "assistant", "deja la")), MAX)
        assertEquals(0, r.added)
        assertEquals(1, history.size)
    }

    @Test fun `adopts the id of a bubble it painted itself`() {
        val mine = local("envoye pendant la coupure", USER, cid = "c1")
        val history = mutableListOf(mine)
        val r = mergeHistory(history, listOf(entry(12, "user", "envoye pendant la coupure")), MAX)
        assertEquals(0, r.added)
        assertEquals(1, history.size)
        assertEquals(12L, mine.id)
        assertEquals(MessageStatus.SENT, mine.status)
    }

    @Test fun `strips prosodic tokens from a replayed reply`() {
        val r = mergeHistory(mutableListOf(), listOf(entry(3, "assistant", "Encore une danse ! [LAUGH] Bravo.")), MAX)
        assertEquals("Encore une danse! Bravo.", r.history[0].text)
    }

    @Test fun `leaves a user message untouched`() {
        val r = mergeHistory(mutableListOf(), listOf(entry(3, "user", "regarde [PAUSE:200] ca")), MAX)
        assertEquals("regarde [PAUSE:200] ca", r.history[0].text)
    }

    @Test fun `reports whether a reply arrived`() {
        assertFalse(mergeHistory(mutableListOf(), listOf(entry(1, "user", "moi")), MAX).sawReply)
        assertTrue(mergeHistory(mutableListOf(), listOf(entry(2, "assistant", "elle")), MAX).sawReply)
    }

    @Test fun `interleaves a missed reply before what was typed after it`() {
        val history = mutableListOf(local("question", USER, id = 1), local("tape depuis", USER, cid = "c9"))
        val r = mergeHistory(history, listOf(entry(2, "assistant", "la reponse manquee")), MAX)
        assertEquals(listOf("question", "la reponse manquee", "tape depuis"), texts(r.history))
    }

    @Test fun `keeps the newest when the thread exceeds the ceiling`() {
        val entries = (0 until 6).map { i -> entry(i + 1L, "user", "m$i") }
        val r = mergeHistory(mutableListOf(), entries, 3)
        assertEquals(listOf("m3", "m4", "m5"), texts(r.history))
    }

    @Test fun `ignores rows with no id and empty text`() {
        val r = mergeHistory(mutableListOf(), listOf(entry(null, "user", "x", ts = 1.0), entry(4, "assistant", "   ")), MAX)
        assertEquals(0, r.added)
    }

    @Test fun `reports an adoption as a change even though nothing appears`() {
        val mine = local("envoye pendant la coupure", USER, cid = "c1")
        val r = mergeHistory(mutableListOf(mine), listOf(entry(12, "user", "envoye pendant la coupure")), MAX)
        assertEquals(0, r.added)
        assertEquals(1, r.adopted)
    }

    @Test fun `shows a reloaded message with files as it was sent, never what the files became`() {
        val r = mergeHistory(
            mutableListOf(),
            listOf(
                entry(5, "user", "regarde", attachments = listOf(AttachmentRef(name = "note.txt", kind = "file"))),
                entry(
                    6, "user", "",
                    attachments = listOf(AttachmentRef(name = "a.png", kind = "image"), AttachmentRef(name = "b.ogg", kind = "audio")),
                ),
            ),
            MAX,
        )
        assertEquals(listOf("regarde [note.txt]", "[a.png, b.ogg]"), texts(r.history))
    }

    @Test fun `keeps the display of a message from an older journal`() {
        val r = mergeHistory(mutableListOf(), listOf(entry(5, "user", "vieux [fichier « a.txt »]")), MAX)
        assertEquals("vieux [fichier « a.txt »]", r.history[0].text)
    }

    @Test fun `adopts its own bubble by the same composition`() {
        val mine = local(withAttachments("regarde ça", listOf("photo.png")), USER, cid = "c1", matchText = "regarde ça")
        val r = mergeHistory(
            mutableListOf(mine),
            listOf(entry(5, "user", "regarde ça", attachments = listOf(AttachmentRef(name = "photo.png", kind = "image")))),
            MAX,
        )
        assertEquals(0, r.added)
        assertEquals(1, r.adopted)
        assertEquals(5L, mine.id)
        assertEquals("regarde ça [photo.png]", mine.text)
    }

    @Test fun `still adopts its bubble when a file did not make it`() {
        val mine = local("regarde ça [photo.png, gros.bin]", USER, cid = "c1", matchText = "regarde ça")
        val r = mergeHistory(
            mutableListOf(mine),
            listOf(entry(5, "user", "regarde ça", attachments = listOf(AttachmentRef(name = "photo.png", kind = "image")))),
            MAX,
        )
        assertEquals(1, r.adopted)
        assertEquals(5L, mine.id)
    }

    @Test fun `no longer adopts a row that merely starts with what was typed`() {
        val mine = local("regarde ça [chat.png]", USER, cid = "c1", matchText = "regarde ça")
        val r = mergeHistory(mutableListOf(mine), listOf(entry(5, "user", "regarde ça, encore")), MAX)
        assertEquals(0, r.adopted)
        assertEquals(1, r.added)
        assertNull(mine.id)
    }

    @Test fun `never lets an attachment-only bubble match any user row`() {
        val mine = local("[chat.png]", USER, cid = "c1", matchText = "")
        val r = mergeHistory(mutableListOf(mine), listOf(entry(5, "user", "un message sans aucun rapport")), MAX)
        assertEquals(0, r.adopted)
        assertEquals(1, r.added)
        assertNull(mine.id)
    }

    @Test fun `clears a stale failure when the message turns out to have landed`() {
        val mine = local("parti quand meme", USER, cid = "c1", status = MessageStatus.FAILED, reason = "trop de messages d'affilée")
        mergeHistory(mutableListOf(mine), listOf(entry(3, "user", "parti quand meme")), MAX)
        assertEquals(MessageStatus.SENT, mine.status)
        assertNull(mine.reason)
    }

    @Test fun `binds every bubble of a burst, not only the one the reply names`() {
        val history = mutableListOf(
            local("bonjour", VTUBER, id = 20),
            local("salut", USER, cid = "r1", status = MessageStatus.SENT, ts = 1),
            local("t'as vu le match ?", USER, cid = "r2", status = MessageStatus.SENT, ts = 2),
            local("allo ?", USER, cid = "r3", status = MessageStatus.SENT, ts = 3),
        )
        // sans le rattrapage : la réponse lie « allo ? », les deux autres tombent sous elle
        val unbound = history.map { it.copy() }.toMutableList()
        bindServerId(unbound, "r3", 25)
        unbound.add(local("Oui, quel match !", VTUBER, id = 26))
        assertEquals(listOf("salut", "t'as vu le match ?"), texts(sortMessages(unbound)).takeLast(2))
        // avec : les lignes du tour d'abord, puis la réponse
        val result = mergeHistory(history, listOf(entry(22, "user", "salut"), entry(23, "user", "t'as vu le match ?")), MAX)
        assertEquals(2, result.adopted)
        assertFalse(result.sawReply) // « Mika écrit… » attend toujours la réponse
        bindServerId(result.history, "r3", 25)
        result.history.add(local("Oui, quel match !", VTUBER, id = 26))
        assertEquals(
            listOf("bonjour", "salut", "t'as vu le match ?", "allo ?", "Oui, quel match !"),
            texts(sortMessages(result.history)),
        )
    }

    @Test fun `tolerates a missing message list`() {
        val history = mutableListOf(local("a", USER, id = 1))
        mergeHistory(history, null, MAX)
        assertEquals(1, history.size)
    }

    // ── applyAck ──

    @Test fun `marks an accepted message as sent`() {
        val history = listOf(local("coucou", USER, cid = "c1", status = MessageStatus.PENDING))
        assertEquals(ChatSync.AckResult(changed = true, failed = false, settled = false), applyAck(history, "c1", "accepted"))
        assertEquals(MessageStatus.SENT, history[0].status)
    }

    @Test fun `keeps a received message sent when its reply will not come`() {
        val history = listOf(local("allo ?", USER, cid = "c1", status = MessageStatus.PENDING))
        applyAck(history, "c1", "accepted")
        val result = applyAck(history, "c1", "no_reply", reason = "no_model")
        assertEquals(ChatSync.AckResult(changed = true, failed = false, settled = true), result)
        assertEquals(MessageStatus.SENT, history[0].status)
        assertNull(history[0].reason)
        assertEquals("Mika n'a pas pu répondre — réessaie.", history[0].replyNote)
        // contre-exemple : une vraie saturation (le message n'est pas pris) reste un refus
        val full = listOf(local("encore", USER, cid = "c2", status = MessageStatus.PENDING))
        assertTrue(applyAck(full, "c2", "overloaded").failed)
        assertEquals(MessageStatus.FAILED, full[0].status)
    }

    @Test fun `gives an operator the cause and a console page, nobody else`() {
        val history = listOf(local("salut", USER, cid = "c1", status = MessageStatus.SENT))
        applyAck(
            history, "c1", "no_reply",
            reason = "no_model",
            detail = "aucun modèle ne sert encore à répondre : déclare un fournisseur dans la console",
            href = "/inspecteur/reglages/fournisseurs",
        )
        assertTrue(history[0].replyNote!!.contains("aucun modèle"))
        assertEquals("/inspecteur/reglages/fournisseurs", history[0].replyHref)
        // un lien d'ailleurs n'est jamais posé sous une bulle
        val other = listOf(local("salut", USER, cid = "c2", status = MessageStatus.SENT))
        applyAck(other, "c2", "no_reply", reason = "error", href = "https://ailleurs.test/x")
        assertNull(other[0].replyHref)
    }

    @Test fun `keeps the note of a partial send when the reply then fails`() {
        val history = listOf(local("deux photos", USER, cid = "c1", status = MessageStatus.PENDING))
        applyAck(history, "c1", "accepted", listOf(RejectedAttachment("gros.png", "too_large")))
        applyAck(history, "c1", "no_reply", reason = "timeout")
        assertTrue(history[0].note!!.contains("gros.png"))
        assertNotNull(history[0].replyNote)
    }

    @Test fun `says a question abandoned as too old differently`() {
        val history = listOf(local("tu es là ?", USER, cid = "c1", status = MessageStatus.SENT))
        applyAck(history, "c1", "no_reply", reason = "too_late")
        assertTrue(history[0].replyNote!!.contains("à temps"))
        // l'ancien statut d'un serveur d'avant `no_reply` se lit pareil
        val legacy = listOf(local("tu es là ?", USER, cid = "c2", status = MessageStatus.SENT))
        assertFalse(applyAck(legacy, "c2", "too_late").failed)
        assertEquals(MessageStatus.SENT, legacy[0].status)
        assertEquals(noReplyNote("too_late"), legacy[0].replyNote)
    }

    @Test fun `marks a refusal as failed rather than leaving it pending`() {
        val history = listOf(local("spam", USER, cid = "c1", status = MessageStatus.PENDING))
        assertTrue(applyAck(history, "c1", "rate_limited").failed)
        assertEquals(MessageStatus.FAILED, history[0].status)
    }

    @Test fun `ignores an ack for a message it does not know`() {
        val history = listOf(local("coucou", USER, cid = "c1"))
        assertFalse(applyAck(history, "inconnu", "accepted").changed)
    }

    @Test fun `records why it failed, not just that it did`() {
        val history = listOf(local("x", USER, cid = "c1", status = MessageStatus.PENDING))
        applyAck(history, "c1", "attachments_rejected")
        assertTrue(history[0].reason!!.contains("pièces jointes"))
    }

    @Test fun `treats a status it has never heard of as a refusal`() {
        val history = listOf(local("x", USER, cid = "c1", status = MessageStatus.PENDING))
        assertTrue(applyAck(history, "c1", "quelque_chose_de_neuf").failed)
        assertEquals("refusé par le serveur", history[0].reason)
    }

    // ── ackReason ──

    @Test fun `names the refusals the consumer can actually send`() {
        assertTrue(ackReason("overloaded").contains("saturée"))
        assertTrue(ackReason("too_long").contains("trop long"))
        assertTrue(ackReason("rate_limited").contains("messages"))
    }

    @Test fun `does not call a question abandoned as too old a saturation`() {
        assertTrue(noReplyNote("too_late").contains("à temps"))
        assertFalse(noReplyNote("too_late").contains("saturée"))
    }

    @Test fun `keeps the web wording verbatim`() {
        assertEquals(
            mapOf(
                "rate_limited" to "trop de messages d'affilée",
                "empty" to "message vide",
                "overloaded" to "Mika est saturée, réessaie dans un instant",
                "too_long" to "message trop long",
                "attachments_rejected" to "pièces jointes refusées (format ou taille)",
                "frame_too_large" to "envoi trop volumineux — retire une pièce jointe",
                "send_abandoned" to "envoi abandonné après plusieurs tentatives",
                "unauthorized" to "session expirée — reconnecte-toi",
            ),
            ChatSync.ACK_REASONS,
        )
    }

    // ── asleep ──

    @Test fun `says she is asleep under the bubble until she speaks again`() {
        val history = mutableListOf(local("tu dors ?", USER, id = 4, cid = "n1", status = MessageStatus.SENT))
        assertTrue(markAsleep(history, "n1"))
        assertTrue(asleepNoteShown(history, 0))
        // un murmure n'est pas sa réponse
        history.add(local("hmm…", VTUBER, after = 4, inner = true))
        assertTrue(asleepNoteShown(history, 0))
        // sa réponse au réveil (même arrivée par un rattrapage) la rend caduque
        history.add(local("Bonjour ! Je dormais.", VTUBER, id = 9))
        assertFalse(asleepNoteShown(history, 0))
    }

    @Test fun `is cleared by the frame that answers or settles that message`() {
        val history = listOf(local("tu dors ?", USER, cid = "n1", status = MessageStatus.SENT))
        markAsleep(history, "n1")
        bindServerId(history, "n1", 4)
        assertNull(history[0].waiting)
    }

    @Test fun `never shows on a message that was not held for her morning`() {
        assertFalse(asleepNoteShown(listOf(local("coucou", USER, id = 1)), 0))
    }

    // ── another life ──

    private val v1Cache = (0 until 50).map { i -> local("v1 $i", if (i % 2 == 1) VTUBER else USER, id = 1201L + i) }
    private val v2Rows = listOf(
        entry(17, "user", "salut"),
        entry(23, "assistant", "coucou !"),
        entry(1210, "user", "ça va ?"),
        entry(1300, "assistant", "oui et toi ?"),
    )

    @Test fun `hides what she said when the old cache is merged as is`() {
        val r = mergeHistory(v1Cache.map { it.copy() }.toMutableList(), v2Rows, MAX)
        assertEquals(listOf(1300L), r.history.filter { !it.text.startsWith("v1") }.map { it.id })
    }

    @Test fun `drops a cache from another life before merging`() {
        val cachedLife = "" // un fil gardé sans empreinte : d'avant l'empreinte, vie inconnue
        assertTrue(fromAnotherLife(cachedLife, "a1b2c3d4e5f60708", null))
        val kept = keepAcrossLives(v1Cache)
        val r = mergeHistory(kept, v2Rows, MAX)
        assertEquals(listOf(17L, 23L, 1210L, 1300L), r.history.map { it.id })
        assertEquals(1300L, cursorOf(r.history))
    }

    @Test fun `drops it when the server says the cursor went past its thread`() {
        assertTrue(fromAnotherLife("a1", "a1", true))
        // contre-exemples : la même vie, ou un serveur qui ne donne pas d'empreinte
        assertFalse(fromAnotherLife("a1", "a1", false))
        assertFalse(fromAnotherLife("a1", null, null))
        assertFalse(fromAnotherLife("", "", null))
    }

    @Test fun `keeps only what this tab is still sending`() {
        val history = listOf(
            local("v1", USER, id = 1250, status = MessageStatus.SENT),
            local("restauré", USER, status = MessageStatus.FAILED, reason = "x"),
            local("pensée", VTUBER, after = 1250, inner = true),
            local("en partance", USER, cid = "c9", status = MessageStatus.PENDING),
        )
        assertEquals(listOf("en partance"), texts(keepAcrossLives(history)))
    }

    // ── bindServerId ──

    @Test fun `binds the id the reply reports for the question`() {
        val history = listOf(local("question", USER, cid = "c1", status = MessageStatus.PENDING))
        assertTrue(bindServerId(history, "c1", 42))
        assertEquals(42L, history[0].id)
        assertEquals(MessageStatus.SENT, history[0].status)
    }

    @Test fun `still confirms delivery when the server sent no id`() {
        val history = listOf(local("question", USER, cid = "c1", status = MessageStatus.PENDING))
        assertTrue(bindServerId(history, "c1", null))
        assertNull(history[0].id)
        assertEquals(MessageStatus.SENT, history[0].status)
    }

    // ── coerceStatus ──

    @Test fun `keeps the three known states`() {
        assertEquals(MessageStatus.SENT, coerceStatus("sent"))
        assertEquals(MessageStatus.PENDING, coerceStatus("pending"))
        assertEquals(MessageStatus.FAILED, coerceStatus("failed"))
    }

    @Test fun `drops anything else`() {
        assertNull(coerceStatus("delivered"))
        assertNull(coerceStatus(null))
        assertNull(coerceStatus("7"))
    }

    // ── restoredStatus ──

    @Test fun `turns a restored pending into a failed refusal`() {
        assertEquals(
            ChatSync.Restored(MessageStatus.FAILED, RESTORED_PENDING_REASON),
            restoredStatus("pending", hasOutbox = false),
        )
    }

    @Test fun `keeps a restored pending that still has its outbox row`() {
        // propre à l'app : la file d'envoi survit en base, le message partira à la prochaine connexion
        assertEquals(ChatSync.Restored(MessageStatus.PENDING), restoredStatus("pending", hasOutbox = true))
    }

    @Test fun `leaves a restored sent or failed status untouched`() {
        assertEquals(ChatSync.Restored(MessageStatus.SENT), restoredStatus("sent", hasOutbox = false))
        assertEquals(ChatSync.Restored(MessageStatus.FAILED), restoredStatus("failed", hasOutbox = false))
    }

    @Test fun `drops an unknown cached status like coerceStatus does`() {
        assertEquals(ChatSync.Restored(null), restoredStatus("delivered", hasOutbox = false))
        assertEquals(ChatSync.Restored(null), restoredStatus(null, hasOutbox = false))
    }

    // ── stripProsody ──

    @Test fun `removes stage directions and emotion tags`() {
        assertEquals("Salut ca va?", stripProsody("Salut [SIGH] ca va ? [EMOTION:happy:0.8]"))
    }

    @Test fun `closes the gap a removed token leaves before punctuation`() {
        assertEquals("Ah!", stripProsody("Ah [PAUSE:400] !"))
    }

    // ── nextClientMsgId (propre à l'app) ──

    @Test fun `mints a base-36 id that stays under the server limit`() {
        val a = ChatSync.nextClientMsgId(1_700_000_000_000)
        val b = ChatSync.nextClientMsgId(1_700_000_000_000)
        assertTrue(a.matches(Regex("""c[0-9a-z]+-\d+""")))
        assertTrue(a != b)
        assertTrue(a.length <= 64)
    }
}
