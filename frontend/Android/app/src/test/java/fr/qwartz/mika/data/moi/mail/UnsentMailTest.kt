package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.ui.Route
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * Un mail commencé et pas envoyé, quand un lien profond remplace la pile (R1-03) : gardé sous son écriture, rendu une
 * fois à la même (même mode, même mail, même brouillon), jamais à une autre ; effacé à l'envoi, à l'abandon, à la
 * déconnexion.
 */
class UnsentMailTest {
    private val reply = Route.MailCompose("reply", ref = "perso:<m1@x>")
    private val piece = OutgoingPiece("devis.pdf", "application/pdf", 12_000) { error("lu au départ seulement") }
    private val mail = UnsentMail(
        from = "perso", to = listOf(MailPerson("Claire", "claire@x.fr")), cc = emptyList(), bcc = emptyList(),
        toText = "", ccText = "", bccText = "pa", showCc = false, showBcc = true,
        subject = "Re: le devis", body = "Bonjour Claire,\nje te renvoie…", quote = true, carry = true,
        pieces = listOf(piece), fromDraft = "", asked = false,
    )

    @Test fun `la même écriture rouverte retrouve ce qui était écrit, une fois`() {
        val unsent = UnsentMails()
        unsent.keep(reply, mail)
        val back = unsent.take(Route.MailCompose("reply", ref = "perso:<m1@x>"))
        assertEquals(mail, back)
        assertEquals("devis.pdf", back!!.pieces.single().name)
        assertNull(unsent.take(reply))
    }

    @Test fun `une autre écriture ne le reçoit pas`() {
        val unsent = UnsentMails()
        unsent.keep(reply, mail)
        assertNull(unsent.take(Route.MailCompose("reply_all", ref = "perso:<m1@x>")))
        assertNull(unsent.take(Route.MailCompose("reply", ref = "perso:<m2@x>")))
        assertNull(unsent.take(Route.MailCompose("edit", draft = "d1")))
        assertNull(unsent.take(Route.MailCompose()))
        assertEquals(mail, unsent.take(reply))
    }

    @Test fun `parti, abandonné ou la session fermée - plus rien n'attend`() {
        val unsent = UnsentMails()
        unsent.keep(reply, mail)
        unsent.drop(reply)
        assertNull(unsent.take(reply))
        unsent.keep(reply, mail)
        unsent.keep(Route.MailCompose(), mail.copy(to = emptyList()))
        unsent.clear()
        assertNull(unsent.take(reply))
        assertNull(unsent.take(Route.MailCompose()))
    }
}
