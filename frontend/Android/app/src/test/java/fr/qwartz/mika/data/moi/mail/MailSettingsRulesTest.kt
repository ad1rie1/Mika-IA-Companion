package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.settings.text
import fr.qwartz.mika.data.moi.settings.unseenOf
import fr.qwartz.mika.data.moi.teams.TeamsValues
import fr.qwartz.mika.data.moi.teams.teamsChanges
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles de Paramètres › Boîtes mail, portées du client web (`frontend/Web/src/screens/mail/words.ts`, ses tests
 * `settings.test.ts`) : l'état d'une boîte, ce que la liste en dit, ses fournisseurs, une boîte nouvelle, ses dossiers,
 * ce qu'un formulaire envoie (et ce qu'il garde), ses bornes, les secrets à redonner.
 */
class MailSettingsRulesTest {
    private val now = 1_790_800_000_000L

    // ── les boîtes ──

    @Test fun `l'état d'une boîte, dans l'ordre du web`() {
        assertEquals(Tone.NEUTRAL to "inactive", boxState(false, false, "panne"))
        assertEquals(Tone.WARN to "incomplète", boxState(true, false, "panne"))
        assertEquals(Tone.DANGER to "erreur", boxState(true, true, "panne"))
        assertEquals(Tone.OK to "prête", boxState(true, true, ""))
    }

    @Test fun `ce que la liste dit d'une boîte`() {
        val inbox = MailFolder(name = "INBOX", role = "inbox", unseen = 3)
        val b = MailBox(key = "pro", lastPoll = now - 5 * 60_000, folders = listOf(inbox, MailFolder(name = "Archive", unseen = 9)), draftsWaiting = 2)
        assertEquals(3, unseenOf(b))
        assertEquals("relevée il y a 5 min · 3 non lus · 2 brouillons d'elle à relire", boxStatusLine(b, now))
        assertEquals("pas encore relevée", boxStatusLine(MailBox(), now))
        assertEquals("dernier relevé il y a 5 min : refusé", boxStatusLine(b.copy(error = "refusé"), now))
        val shared = MailBox(key = "x", name = "Perso", ownerName = "Léa Moreau", level = Levels.PREPARE)
        assertEquals("Boîte de Léa", sharedBoxTitle(shared))
        assertTrue(sharedBoxSentence(shared).startsWith("Léa Moreau te l'a ouverte en lecture et préparation"))
        assertEquals("Boîte d'Adrien", sharedBoxTitle(shared.copy(ownerName = "Adrien")))
    }

    @Test fun `les fournisseurs, DavMail seulement pour une opératrice`() {
        assertFalse(Provider.DAVMAIL in providersFor(false))
        assertTrue(Provider.DAVMAIL in providersFor(true))
        assertTrue(Provider.DAVMAIL in providersFor(null))
        assertEquals("ssl", securityFor(465, "none"))
        assertEquals("starttls", securityFor(587, "none"))
        assertEquals("none", securityFor(2525, "none"))
        assertEquals("1143", NewBox.of(Provider.DAVMAIL).imapPort)
        assertEquals("consumers", NewBox.of(Provider.MICROSOFT).oauthTenant)
    }

    @Test fun `une boîte nouvelle, le préréglage, l'adresse pour utilisateur, le nom tiré de l'adresse`() {
        val gmail = newBoxValues(Provider.GMAIL, NewBox(address = " moi@gmail.com ", password = "app", imapHost = "imap.gmail.com", imapPort = "993", smtpHost = "smtp.gmail.com", smtpPort = "465"))
        assertEquals("moi@gmail.com", gmail.text("user"))
        assertEquals("moi", gmail.text("label"))
        assertEquals("app", gmail.text("password"))
        assertEquals(465, gmail["smtp_port"]!!.jsonPrimitive.int)
        assertEquals("ssl", gmail.text("smtp_security"))
        assertFalse(gmail["save_sent"]!!.jsonPrimitive.boolean)
        val ms = newBoxValues(Provider.MICROSOFT, NewBox(address = "moi@outlook.com", label = "Perso", oauthClientId = " abc ", oauthTenant = ""))
        assertEquals(Auths.MICROSOFT, ms.text("auth"))
        assertEquals("abc", ms.text("oauth_client_id"))
        assertEquals("consumers", ms.text("oauth_tenant"))
        assertEquals("outlook.office365.com", ms.text("imap_host"))
        assertNull(ms["password"])
        // un port vide ou nul : celui du fournisseur
        val other = newBoxValues(Provider.IMAP, NewBox(address = "a@b.fr", imapPort = "", smtpPort = "0"))
        assertEquals(993, other["imap_port"]!!.jsonPrimitive.int)
        assertEquals(587, other["smtp_port"]!!.jsonPrimitive.int)
    }

    @Test fun `avant d'envoyer une boîte nouvelle, son adresse, des ports qui en sont`() {
        assertEquals(setOf("address"), newBoxProblems(Provider.MICROSOFT, NewBox()).keys)
        val bad = newBoxProblems(Provider.IMAP, NewBox(address = "a@b.fr", imapPort = "70000", smtpPort = ""))
        assertEquals(mapOf("imap_port" to "un port entre 1 et 65535"), bad)
        assertTrue(newBoxProblems(Provider.IMAP, NewBox(address = "a@b.fr", imapPort = "993", smtpPort = "587")).isEmpty())
    }

    @Test fun `les dossiers, tapés ou à cocher`() {
        assertEquals(listOf("INBOX", "Sent", "A b"), foldersOf("INBOX, Sent,\n A b ,,"))
        val box = MailBox(folders = listOf(MailFolder(name = "INBOX", label = "Réception"), MailFolder(name = "Sent")))
        assertEquals(listOf("INBOX" to "Réception", "Sent" to "Sent", "Vieux" to "Vieux"), folderChoices(box, listOf("INBOX", "Vieux")))
    }

    // ── les formulaires ──

    @Test fun `seul ce qui a changé part, un secret seulement s'il est tapé`() {
        val before = BoxValues(label = "Pro", imapPort = 993, folders = listOf("INBOX"))
        assertTrue(boxChanges(before, before).isEmpty())
        val sent = boxChanges(before, before.copy(label = "Travail", imapPort = 143, folders = listOf("INBOX", "Sent")), password = "neuf")
        assertEquals(setOf("label", "imap_port", "folders", "password"), sent.keys)
        assertEquals(143, sent["imap_port"]!!.jsonPrimitive.int)
        assertEquals(JsonArray(listOf(JsonPrimitive("INBOX"), JsonPrimitive("Sent"))), sent["folders"])
        assertNull(boxChanges(before, before, password = "", smtpPassword = "")["password"])
        val t = TeamsValues(label = "A", sign = false)
        assertEquals(setOf("sign"), teamsChanges(t, t.copy(sign = true)).keys)
        // ses consignes de tri partent sous leur nom du moteur, comme les autres (ADR 0243)
        val sorted = boxChanges(before, before.copy(triageInstructions = "préviens-moi de la banque"))
        assertEquals(setOf("triage_instructions"), sorted.keys)
        assertEquals("préviens-moi de la banque", sorted["triage_instructions"]!!.jsonPrimitive.content)
        assertEquals("Consignes de tri", BOX_LABELS["triage_instructions"])
        assertTrue("triage_instructions" in boxShownFields(before))
    }

    @Test fun `les bornes que le serveur ne vérifie pas d'avance`() {
        assertEquals(
            mapOf("imap_port" to "un port entre 1 et 65535", "since_days" to "entre 1 et 60 jours"),
            rangeProblems(mapOf("imap_port" to "0", "smtp_port" to "587", "since_days" to "61")),
        )
        assertEquals(setOf("smtp_port"), rangeProblems(mapOf("smtp_port" to "")).keys)
        assertTrue(rangeProblems(mapOf("since_days" to "60")).isEmpty())
    }

    @Test fun `un secret gardé se redonne quand sa connexion change`() {
        val kept = BoxSecrets(password = true, smtpPassword = false)
        val host = JsonObject(mapOf("imap_host" to JsonPrimitive("imap.autre.fr")))
        assertEquals(setOf("password"), secretsToRetype(host, kept, Auths.PASSWORD, "imap.autre.fr", "smtp.b.fr").keys)
        // redonné dans le même envoi : rien à redire
        assertTrue(secretsToRetype(JsonObject(host + ("password" to JsonPrimitive("x"))), kept, Auths.PASSWORD, "imap.autre.fr", "smtp.b.fr").isEmpty())
        // l'envoi sans mot de passe à lui se sert de celui de la lecture : changer le serveur d'envoi le redemande
        val smtp = JsonObject(mapOf("smtp_port" to JsonPrimitive(465)))
        assertEquals(setOf("smtp_password"), secretsToRetype(smtp, kept, Auths.PASSWORD, "imap.a.fr", "smtp.b.fr").keys)
        // … sauf si celui de la lecture est redonné dans le même envoi
        assertTrue(secretsToRetype(JsonObject(smtp + ("password" to JsonPrimitive("x"))), kept, Auths.PASSWORD, "imap.a.fr", "smtp.b.fr").isEmpty())
        // un serveur vidé : la connexion est retirée, rien ne part
        assertTrue(secretsToRetype(JsonObject(mapOf("smtp_host" to JsonPrimitive(""))), kept, Auths.PASSWORD, "imap.a.fr", "").isEmpty())
        // Microsoft : aucun mot de passe ; rien de gardé : rien à redonner
        assertTrue(secretsToRetype(host, kept, Auths.MICROSOFT, "imap.autre.fr", "smtp.b.fr").isEmpty())
        assertTrue(secretsToRetype(host, BoxSecrets(), Auths.PASSWORD, "imap.autre.fr", "smtp.b.fr").isEmpty())
        // ce qui ne touche pas la connexion ne redemande rien
        assertTrue(secretsToRetype(JsonObject(mapOf("label" to JsonPrimitive("x"))), kept, Auths.PASSWORD, "imap.a.fr", "smtp.b.fr").isEmpty())
    }
}
