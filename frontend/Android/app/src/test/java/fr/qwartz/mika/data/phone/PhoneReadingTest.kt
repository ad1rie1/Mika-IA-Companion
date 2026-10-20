package fr.qwartz.mika.data.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Le tri des notifications (ADR 0120) : seulement les applis cochées, jamais un résumé ni une notification sans
 * `MessagingStyle`, les groupes sur demande ; la conversation, l'expéditeur, et ce qui est de la personne elle-même.
 */
class PhoneReadingTest {
    private val on = PhoneGate(enabled = true)
    private val me = PostedPerson(key = "me", name = "Vous")
    private val lea = PostedPerson(key = "key-lea", name = "Léa")

    private fun notification(
        pkg: String = "com.whatsapp",
        shortcut: String? = "33612345678@s.whatsapp.net",
        tag: String? = null,
        summary: Boolean = false,
        style: PostedStyle? = PostedStyle(me, null, false, listOf(PostedMessage("Tu viens ce soir ?", 1_791_000_000_000, lea))),
    ) = PostedNotification(pkg, summary, shortcut, tag, 1_791_000_999_000, style)

    @Test fun `un message de WhatsApp part avec ses clés opaques`() {
        val r = PhoneReading.read(notification(), on)!!
        assertEquals(PhoneApp.WHATSAPP, r.app)
        assertEquals(PhoneKeys.thread("com.whatsapp", "33612345678@s.whatsapp.net"), r.thread)
        val m = r.messages.single()
        assertEquals("whatsapp", m.app)
        assertEquals(r.thread, m.thread)
        assertEquals(PhoneKeys.sender("com.whatsapp", "key-lea"), m.sender)
        assertEquals("Léa", m.name)
        assertEquals("", m.title)
        assertFalse(m.group)
        assertFalse(m.own)
        assertEquals(1_791_000_000_000, m.time)
        assertEquals(PhoneKeys.id("com.whatsapp", r.thread, m.sender, m.time, "Tu viens ce soir ?"), m.id)
        // une notification mise à jour redit le message : même identifiant
        assertEquals(m.id, PhoneReading.read(notification(), on)!!.messages.single().id)
    }

    @Test fun `seules les applis cochées se lisent, et rien quand l'interrupteur est coupé`() {
        assertNull(PhoneReading.read(notification(pkg = "com.mabanque"), on))
        assertNull(PhoneReading.read(notification(), PhoneGate(enabled = false)))
        assertNull(PhoneReading.read(notification(), on.copy(whatsapp = false)))
        assertNull(PhoneReading.read(notification(pkg = "com.whatsapp.w4b"), on.copy(whatsapp = false)))
        assertEquals("whatsapp_business", PhoneReading.read(notification(pkg = "com.whatsapp.w4b"), on)!!.messages.single().app)
        assertNull(PhoneReading.read(notification(pkg = "com.google.android.apps.messaging"), on.copy(messages = false)))
        assertEquals("messages", PhoneReading.read(notification(pkg = "com.google.android.apps.messaging"), on)!!.app.code)
        assertEquals("samsung_messages", PhoneReading.read(notification(pkg = "com.samsung.android.messaging"), on)!!.app.code)
    }

    @Test fun `ni résumé de groupe ni notification sans MessagingStyle`() {
        assertNull(PhoneReading.read(notification(summary = true), on))
        assertNull(PhoneReading.read(notification(style = null), on))
    }

    @Test fun `un groupe ne part que si les groupes sont cochés, avec son nom`() {
        val group = PostedStyle(me, "Famille", true, listOf(PostedMessage("On mange à 20h", 5, lea)))
        assertNull(PhoneReading.read(notification(style = group), on))
        val m = PhoneReading.read(notification(style = group), on.copy(groups = true))!!.messages.single()
        assertTrue(m.group)
        assertEquals("Famille", m.title)
    }

    @Test fun `la conversation, faute de raccourci, est le tag, puis le titre, puis l'expéditeur`() {
        val pkg = "com.whatsapp"
        assertEquals(PhoneKeys.thread(pkg, "le-tag"), PhoneReading.read(notification(shortcut = " ", tag = "le-tag"), on)!!.thread)
        val titled = PostedStyle(me, "Bureau", false, listOf(PostedMessage("x", 5, lea)))
        assertEquals(PhoneKeys.thread(pkg, "Bureau"), PhoneReading.read(notification(shortcut = null, style = titled), on)!!.thread)
        assertEquals(PhoneKeys.thread(pkg, "Léa"), PhoneReading.read(notification(shortcut = null), on)!!.thread)
        // rien pour la nommer : rien ne part
        val mine = PostedStyle(me, null, false, listOf(PostedMessage("x", 5, null)))
        assertNull(PhoneReading.read(notification(shortcut = null, style = mine), on))
    }

    @Test fun `sans expéditeur, ou la user du style, c'est la personne elle-même`() {
        val style = PostedStyle(
            me,
            null,
            false,
            listOf(
                PostedMessage("à toi", 1, lea),
                PostedMessage("ma réponse", 2, null),
                PostedMessage("encore moi", 3, PostedPerson(key = "me", name = "Moi")),
            ),
        )
        val ms = PhoneReading.read(notification(style = style), on)!!.messages
        assertEquals(listOf(false, true, true), ms.map { it.own })
        assertEquals(listOf(true, false, false), ms.map { it.sender.isNotEmpty() })
        assertEquals(listOf("Léa", "", ""), ms.map { it.name })
        // sans clé de part et d'autre : même nom et même adresse
        assertTrue(PhoneReading.isUser(PostedPerson(name = "Vous"), PostedPerson(name = "Vous")))
        assertFalse(PhoneReading.isUser(PostedPerson(name = "Léa"), PostedPerson(name = "Vous")))
        assertFalse(PhoneReading.isUser(PostedPerson(key = "x", name = "Vous"), PostedPerson(name = "Vous")))
    }

    @Test fun `la clé d'expéditeur est key, sinon uri, sinon le nom`() {
        assertEquals("k", PostedPerson("k", "tel:1", "Léa").senderKey)
        assertEquals("tel:1", PostedPerson(null, "tel:1", "Léa").senderKey)
        assertEquals("Léa", PostedPerson(" ", null, "Léa").senderKey)
        assertNull(PostedPerson().senderKey)
    }

    @Test fun `un texte vide ne part pas, un texte trop long est coupé sans casser un émoji`() {
        val long = "a".repeat(PhoneReading.MAX_TEXT - 1) + "🙂🙂"
        val style = PostedStyle(me, null, false, listOf(PostedMessage("   ", 1, lea), PostedMessage(long, 2, lea)))
        val m = PhoneReading.read(notification(style = style), on)!!.messages.single()
        assertEquals(PhoneReading.MAX_TEXT - 1, m.text.length)
        assertFalse(Character.isHighSurrogate(m.text.last()))
    }

    @Test fun `un message sans heure prend celle de la notification`() {
        val style = PostedStyle(me, null, false, listOf(PostedMessage("x", 0, lea)))
        assertEquals(1_791_000_999_000, PhoneReading.read(notification(style = style), on)!!.messages.single().time)
    }

    @Test fun `l'action Répondre est une saisie libre, de préférence déclarée réponse`() {
        assertNull(PhoneReading.pickReply(emptyList()))
        assertNull(PhoneReading.pickReply(listOf(ActionShape(2, 0), ActionShape(1, 0))))
        assertEquals(1, PhoneReading.pickReply(listOf(ActionShape(0, 0), ActionShape(0, 1))))
        assertEquals(2, PhoneReading.pickReply(listOf(ActionShape(0, 0), ActionShape(0, 1), ActionShape(PhoneReading.SEMANTIC_ACTION_REPLY, 1))))
    }

    @Test fun `le registre garde la dernière action de chaque conversation, borné`() {
        val r = ReplyRegistry<String>(max = 2)
        r.put("a", "a1")
        r.put("a", "a2")
        r.put("b", "b1")
        assertEquals("a2", r.get("a"))
        r.put("c", "c1")
        // « a » vient d'être lue : c'est « b » la plus ancienne
        assertNull(r.get("b"))
        assertNotNull(r.get("a"))
        r.clear()
        assertEquals(0, r.size())
    }
}
