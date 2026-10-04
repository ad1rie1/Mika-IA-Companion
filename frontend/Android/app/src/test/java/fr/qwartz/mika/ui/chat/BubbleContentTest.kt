package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

class BubbleContentTest {
    private val zone = ZoneId.of("Europe/Paris")
    private val at = LocalDateTime.of(2026, 10, 4, 21, 4).atZone(zone).toInstant().toEpochMilli()
    private val photo = MessageAttachment("photo.jpg", "image")

    @Test fun `une bulle avec fichiers n'écrit que ce qui a été tapé`() {
        val mine = StoredMessage("regarde [photo.jpg]", Sender.USER, at, attachments = listOf(photo))
        assertEquals("regarde", BubbleContent.text(mine))
        assertEquals("", BubbleContent.text(mine.copy(text = "[photo.jpg]")))
        assertEquals("tapé ici", BubbleContent.text(mine.copy(matchText = "tapé ici")))
        // Un texte qui ne finit pas par la composition reste entier.
        assertEquals("autre chose", BubbleContent.text(mine.copy(text = "autre chose")))
        // Ses fichiers à elle n'ont jamais de composition dans le texte.
        val hers = StoredMessage("voilà [x]", Sender.MIKA, at, attachments = listOf(MessageAttachment("x")))
        assertEquals("voilà [x]", BubbleContent.text(hers))
    }

    @Test fun `l'heure, écrite et dite`() {
        assertEquals("21:04", BubbleContent.time(at, zone))
        assertEquals("21 h 04", BubbleContent.spokenTime(at, zone))
    }

    @Test fun `une bulle, un nœud décrit`() {
        val sent = StoredMessage("salut", Sender.USER, at, status = MessageStatus.SENT)
        assertEquals("Toi, 21 h 04, envoyé : salut", BubbleContent.describe(sent, read = false, zone = zone))
        assertEquals("Toi, 21 h 04, lu : salut", BubbleContent.describe(sent, read = true, zone = zone))
        val failed = sent.copy(status = MessageStatus.FAILED, reason = "message trop long")
        assertEquals("Toi, 21 h 04, refusé — message trop long : salut", BubbleContent.describe(failed, false, zone))
        val pending = sent.copy(status = MessageStatus.PENDING)
        assertEquals("Toi, 21 h 04, en attente d'envoi : salut", BubbleContent.describe(pending, false, zone))
        val mika = StoredMessage("voici la liste", Sender.MIKA, at, attachments = listOf(MessageAttachment("liste.md")))
        assertEquals("Mika, 21 h 04 : voici la liste. Fichiers : liste.md", BubbleContent.describe(mika, false, zone))
        // Le lecteur d'écran ne dit pas les astérisques du Markdown.
        assertEquals("Mika, 21 h 04 : coucou toi", BubbleContent.describe(StoredMessage("coucou **toi**", Sender.MIKA, at), false, zone))
        val onlyPhoto = StoredMessage("[photo.jpg]", Sender.USER, at, status = MessageStatus.SENT, attachments = listOf(photo))
        assertEquals("Toi, 21 h 04, envoyé : Fichiers : photo.jpg", BubbleContent.describe(onlyPhoto, false, zone))
    }
}
