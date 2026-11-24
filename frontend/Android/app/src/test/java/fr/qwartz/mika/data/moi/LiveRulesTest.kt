package fr.qwartz.mika.data.moi

import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailFolder
import fr.qwartz.mika.data.moi.mail.MailView
import fr.qwartz.mika.data.net.Topics
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Ce qu'un signal du direct fait relire à chaque écran (ADR 0308, la colonne « Ce qu'on relit » du § 2 bis) : la page
 * de Mail si elle montre une boîte nommée (ou toutes tes réceptions), le mail ouvert s'il est dans l'une d'elles, où
 * elle en est s'il est nommé ; le fil Teams ouvert sous l'une ou l'autre de ses clés ; le fil du téléphone ; la fiche
 * d'un projet par son numéro. Une reconnexion relit tout ; rien d'ouvert, rien ne se relit.
 */
class LiveRulesTest {
    private val pro = LiveSignal.of(Topics.MAIL to setOf("pro"))
    private val allMail = LiveSignal.of(Topics.MAIL to null)
    private val drafts = LiveSignal.of(Topics.MAIL_DRAFTS to setOf("pro"))

    @Test fun `Mail - la page affichée relit si elle montre une boîte nommée, ou toutes tes réceptions`() {
        assertTrue(MailLive.pageShows(MailView.All, pro))
        assertTrue(MailLive.pageShows(MailView.Folder("pro", "INBOX"), pro))
        assertFalse(MailLive.pageShows(MailView.Folder("perso", "INBOX"), pro))
        assertTrue(MailLive.pageShows(MailView.Sent("pro"), pro))
        assertFalse(MailLive.pageShows(MailView.Sent("perso"), pro))
        assertTrue(MailLive.pageShows(MailView.Folder("perso", "Archives"), allMail))
        // ses brouillons ont leur sujet : la page ne relit pas, ses boîtes si (le bandeau de ses brouillons)
        assertFalse(MailLive.pageShows(MailView.All, drafts))
        assertTrue(MailLive.boxes(drafts))
        assertFalse(MailLive.boxes(LiveSignal.of(Topics.MAIL_WORK to setOf("pro:<a@x>"))))
        assertTrue(MailLive.pageShows(MailView.Folder("perso", "INBOX"), LiveSignal.RESYNC))
    }

    @Test fun `Mail - le mail ouvert relit s'il est dans une boîte nommée, où elle en est s'il est nommé`() {
        assertTrue(MailLive.openShows("pro", pro))
        assertFalse(MailLive.openShows("perso", pro))
        assertTrue(MailLive.openShows("pro", drafts))
        assertFalse(MailLive.openShows(null, pro))
        assertTrue(MailLive.openShows("perso", LiveSignal.RESYNC))
        val work = LiveSignal.of(Topics.MAIL_WORK to setOf("pro:<a@x>"))
        assertTrue(MailLive.workShows("pro:<a@x>", work))
        assertFalse(MailLive.workShows("pro:<b@x>", work))
        assertFalse(MailLive.workShows("pro:<a@x>", pro))
        assertTrue(MailLive.workShows("pro:<b@x>", LiveSignal.of(Topics.MAIL_WORK to null)))
        assertFalse(MailLive.workShows("", LiveSignal.of(Topics.MAIL_WORK to setOf("pro:<a@x>"))))
    }

    @Test fun `Teams - le fil ouvert relit sous la clé demandée ou celle que le serveur a rendue`() {
        // le compte d'avant (« principal ») se nomme par l'identifiant seul ; un autre compte, « compte~identifiant »
        val marc = LiveSignal.of(Topics.TEAMS to setOf("19:marc"))
        assertTrue(TeamsLive.threadShows(listOf("principal~19:marc", "19:marc"), marc))
        assertTrue(TeamsLive.threadShows(listOf("19:marc"), marc))
        assertFalse(TeamsLive.threadShows(listOf("pro~19:marc"), marc))
        assertTrue(TeamsLive.threadShows(listOf("pro~19:lumen"), LiveSignal.of(Topics.TEAMS to setOf("pro~19:lumen"))))
        assertTrue(TeamsLive.threadShows(listOf("19:lumen"), LiveSignal.of(Topics.TEAMS to null)))
        assertFalse(TeamsLive.threadShows(emptyList(), marc))
        val work = LiveSignal.of(Topics.TEAMS_WORK to setOf("19:marc"))
        assertTrue(TeamsLive.workShows(listOf("principal~19:marc", "19:marc"), work))
        assertFalse(TeamsLive.workShows(listOf("19:marc"), marc))
        assertFalse(TeamsLive.threadShows(listOf("19:marc"), work))
        assertTrue(TeamsLive.repliesShow(LiveSignal.of(Topics.TEAMS_REPLIES to null)))
        assertTrue(TeamsLive.repliesShow(marc))
        assertFalse(TeamsLive.repliesShow(work))
    }

    @Test fun `Téléphone et Projets - le fil, la fiche, par ce qu'ils nomment`() {
        val t1 = LiveSignal.of(Topics.PHONE to setOf("whatsapp|t1"))
        assertTrue(PhoneLive.threadShows("whatsapp|t1", t1))
        assertFalse(PhoneLive.threadShows("sms|t1", t1))
        assertFalse(PhoneLive.threadShows("", t1))
        val twelve = LiveSignal.of(Topics.PROJECTS to setOf("12"))
        assertTrue(ProjectsLive.shows(12, twelve))
        assertFalse(ProjectsLive.shows(7, twelve))
        assertTrue(ProjectsLive.shows(7, LiveSignal.of(Topics.PROJECTS to null)))
        assertTrue(ProjectsLive.shows(7, LiveSignal.RESYNC))
        // rien d'ouvert : rien à relire
        assertFalse(ProjectsLive.shows(0, LiveSignal.RESYNC))
    }

    @Test fun `une boîte, un dossier, un compte qui ne sont plus à toi - retour à la liste`() {
        val boxes = listOf(
            MailBox(key = "pro", folders = listOf(MailFolder(name = "INBOX"), MailFolder(name = "Factures"))),
            MailBox(key = "vide"),
        )
        // la boîte partie (son partage retiré), ses envoyés, un dossier disparu : toutes les réceptions
        assertTrue(MailLive.viewGone(MailView.Folder("anna", "INBOX"), boxes))
        assertTrue(MailLive.viewGone(MailView.Sent("anna"), boxes))
        assertTrue(MailLive.viewGone(MailView.Folder("pro", "Archives"), boxes))
        // ce qui tient encore reste ; une boîte dont les dossiers ne se disent pas garde sa vue
        assertFalse(MailLive.viewGone(MailView.Folder("pro", "Factures"), boxes))
        assertFalse(MailLive.viewGone(MailView.Sent("pro"), boxes))
        assertFalse(MailLive.viewGone(MailView.Folder("vide", "INBOX"), boxes))
        assertFalse(MailLive.viewGone(MailView.All, emptyList()))
        // le mail ouvert d'une boîte partie
        assertTrue(MailLive.openGone("anna", boxes))
        assertFalse(MailLive.openGone("pro", boxes))
        assertFalse(MailLive.openGone(null, boxes))
        // le fil d'un compte Teams parti
        assertTrue(TeamsLive.threadGone("anna", listOf("principal")))
        assertFalse(TeamsLive.threadGone("principal", listOf("principal", "anna")))
        assertFalse(TeamsLive.threadGone("", emptyList()))
    }
}
