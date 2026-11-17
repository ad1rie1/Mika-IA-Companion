package fr.qwartz.mika.data.moi.settings

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailFolder
import fr.qwartz.mika.data.moi.phone.PhoneDevice
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles de Paramètres, portées de `frontendv2/src/screens/parametres/` : les niveaux d'un partage, l'état d'une
 * boîte ou d'un service, ce qu'un formulaire envoie (et ce qu'il garde), les secrets à redonner, les refus par champ, la
 * règle d'envoi et sa version, les outils d'un service, tes téléphones, les lignes de la page racine.
 */
class SettingsRulesTest {
    private val now = 1_790_800_000_000L

    // ── les partages ──

    @Test fun `un service ne se partage pas pour préparer, les mots des niveaux`() {
        assertEquals(listOf(Levels.READ, Levels.PREPARE, Levels.USE), shareLevelsFor(ShareKinds.MAIL).map { it.first })
        assertEquals(listOf(Levels.READ, Levels.USE), shareLevelsFor(ShareKinds.MCP).map { it.first })
        assertEquals("Propriétaire", shareWords(Levels.OWNER))
        assertEquals("Lire et préparer", shareWords(Levels.PREPARE))
        assertEquals("autre", shareWords("autre"))
        assertEquals("Boîte « Pro »", whatLabel(ShareKinds.MAIL, "Pro"))
        assertEquals("Service « meteo »", whatLabel(ShareKinds.MCP, "meteo"))
    }

    @Test fun `ce que la personne pourra, dit par son prénom`() {
        assertEquals(
            "Julien verra « Pro » dans son Mail, en lecture seule : ni répondre ni ranger.",
            sharePhrase(ShareKinds.MAIL, "Pro", "Julien Martin", Levels.READ),
        )
        assertEquals(
            "Léa verra « meteo » dans ses Outils, pour que Mika s'en serve pour elle ou lui, sur son accord pour ce qui agit.",
            sharePhrase(ShareKinds.MCP, "meteo", "Léa", Levels.USE),
        )
        assertTrue(sharePhrase(ShareKinds.TEAMS, "Atelier", "Léa", Levels.PREPARE).contains("dans son Teams, en lecture, et Mika pourra"))
    }

    @Test fun `on ne partage que ce qui est à soi, et ce qui est « à toi » pas à ses propriétaires`() {
        val boxes = listOf(
            MailBox(key = "pro", name = "Pro", address = "a@b.fr", level = Levels.OWNER, common = true),
            MailBox(key = "lea", name = "Léa", level = Levels.READ),
        )
        val accounts = listOf(TeamsAccount(key = "t1", name = "", level = Levels.OWNER, selfName = "Adrien"), TeamsAccount(key = "t2", level = Levels.USE))
        val got = shareables(boxes, accounts, listOf(Service(name = "meteo", purpose = "la météo")))
        assertEquals(listOf("mail:pro", "teams:t1", "mcp:meteo"), got.map { "${it.kind}:${it.key}" })
        assertEquals("t1", got[1].title)
        assertEquals("ton nom dans Teams : Adrien", got[1].sub)
        assertTrue(got[0].common)
        val people = listOf(Person("p1", "Léa", owner = true), Person("p2", "Julien"))
        assertEquals(listOf("p2"), sharePeople(true, people).map { it.person })
        assertEquals(2, sharePeople(false, people).size)
    }

    @Test fun `un partage ne se change plus quand sa personne est partie ou devenue propriétaire`() {
        val people = listOf(Person("p1", "Léa", owner = true), Person("p2", "Julien"))
        val share = GivenShare(ShareKinds.MAIL, "pro", "Pro", "p3", "Ancien", Levels.READ)
        assertTrue(shareGone(share, people, common = false))
        assertFalse(shareGone(share.copy(person = "p2"), people, common = true))
        assertTrue(shareGone(share.copy(person = "p1"), people, common = true))
        assertFalse(shareGone(share.copy(person = "p1"), people, common = false))
        assertEquals(ShareOpens.SERVICE, openOf(ShareKinds.MCP))
        assertEquals(ShareOpens.MAIL, openOf("inconnu"))
    }

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

    @Test fun `un refus par champ, sous son champ ou dit à part`() {
        val errors = fieldErrors(mapOf("accounts.pro.imap_port" to "trop grand", "imap_port" to "un nombre", "label" to "requis"))
        assertEquals(mapOf("imap_port" to "trop grand ; un nombre", "label" to "requis"), errors)
        val shown = boxShownFields(BoxValues(auth = Auths.MICROSOFT, voice = Voices.HER))
        assertTrue("oauth_client_id" in shown && "sender_name" in shown)
        assertFalse("password" in shown || "smtp_password" in shown || "display_name" in shown)
        assertEquals(listOf("Mot de passe : à redonner"), unplaced(mapOf("password" to "à redonner", "label" to "x"), shown, BOX_LABELS))
        assertEquals("Le formulaire a des erreurs.", refusalToast("Le formulaire a des erreurs.", emptyList()))
        assertEquals("Refusé (Port IMAP : x)", refusalToast("Refusé", listOf("Port IMAP : x")))
    }

    // ── le compte ──

    @Test fun `ce qui manque avant de changer un nom ou un mot de passe`() {
        assertEquals("un nom", nameProblem("  "))
        assertNull(nameProblem("Adrien"))
        assertEquals("120 caractères au plus", nameProblem("a".repeat(121)))
        assertEquals(setOf("current", "password"), passwordProblems("", "", "").keys)
        assertEquals(mapOf("again" to "les deux ne sont pas les mêmes"), passwordProblems("vieux", "neuf", "nef"))
        assertTrue(passwordProblems("vieux", "neuf", "neuf").isEmpty())
        assertTrue(roleHelp(owner = true, operator = true).startsWith("Un opérateur"))
        assertTrue(roleHelp(owner = false, operator = false).contains("à toi seule"))
    }

    // ── la règle d'envoi (ADR 0207) ──

    private val rules = SendRules(
        canal = "courrier:pro",
        version = "abc123",
        lines = listOf(RuleLine(who = "Claire", whenWords = "toujours", prepare = true, reply = Replies.ASK), RuleLine(who = "", whenWords = "en semaine", reply = Replies.DRAFT)),
        default = RuleLine(prepare = false, reply = Replies.NO),
    )

    @Test fun `le courrier n'a pas de brouillon que tu envoies, sauf sur une ligne qui l'a`() {
        assertFalse(Replies.DRAFT in sendChoices(RulesKind.MAIL, Replies.ASK).map { it.first })
        assertTrue(Replies.DRAFT in sendChoices(RulesKind.MAIL, Replies.DRAFT).map { it.first })
        assertTrue(Replies.DRAFT in sendChoices(RulesKind.TEAMS, Replies.ASK).map { it.first })
        assertEquals("Claire", ruleWho(rules.lines[0]))
        assertEquals("Tout le monde · en semaine", ruleWho(rules.lines[1]))
        assertEquals("préparer : oui · envoi : ton accord", ruleSummary(RuleEdit(true, Replies.ASK)))
    }

    @Test fun `la règle part entière, avec la version lue`() {
        val lines = rules.lines.map { it.edit }
        assertFalse(ruleChanged(rules, lines, rules.default.edit))
        val moved = listOf(lines[0].copy(reply = Replies.ALONE), lines[1])
        assertTrue(ruleChanged(rules, moved, rules.default.edit))
        assertTrue(ruleChanged(rules, lines, RuleEdit(true, Replies.NO)))
        val body = ruleBody(rules, moved, RuleEdit(true, Replies.ASK))!!
        assertEquals("courrier:pro", body.text("canal"))
        assertEquals("abc123", body.text("version"))
        val sent = body["lines"]!!.jsonArray.map { it.jsonObject }
        assertEquals(listOf("seule", "brouillon"), sent.map { it.text("reply") })
        assertEquals(setOf("prepare", "reply"), sent[0].keys)
        assertTrue(body["default"]!!.jsonObject["prepare"]!!.jsonPrimitive.boolean)
    }

    @Test fun `une règle se renvoie avec autant de lignes qu'elle en a, sinon rien ne part (sans exception, R3-01)`() {
        assertNull(ruleBody(rules, listOf(RuleEdit(true, Replies.ASK)), RuleEdit(false, Replies.NO)))
    }

    @Test fun `d'où vient la règle, dit sous elle`() {
        assertTrue(rulesHelp(rules.copy(set = false, common = true), RulesKind.MAIL).endsWith("l'enregistrer ici lui en donne une à lui."))
        assertTrue(rulesHelp(rules.copy(set = false, common = false), RulesKind.TEAMS).endsWith("c'est sa règle de départ."))
        assertTrue(rulesHelp(rules.copy(set = true), RulesKind.MAIL).contains("« ton accord » en tient lieu"))
        assertFalse(rulesHelp(rules.copy(set = true), RulesKind.TEAMS).contains("ton accord"))
    }

    // ── Teams ──

    @Test fun `ce qu'on sait de son extension`() {
        assertEquals(Tone.NEUTRAL to "inactif", batchWords(TeamsAccount(enabled = false, lastBatch = now), now))
        assertEquals(Tone.WARN to "rien reçu de son extension", batchWords(TeamsAccount(), now))
        assertEquals(Tone.OK to "dernier envoi il y a 3 h", batchWords(TeamsAccount(lastBatch = now - 3 * 3_600_000), now))
        assertTrue(sharedAccountSentence(TeamsAccount(level = Levels.READ, ownerName = "Léa")).startsWith("Léa te l'a ouvert : lire."))
    }

    // ── les services ──

    @Test fun `l'état d'un service et de ses outils`() {
        assertEquals(Tone.OK to "connecté", stateWords("connecte"))
        assertEquals(Tone.NEUTRAL to "jamais joint", stateWords("jamais"))
        assertEquals(Tone.NEUTRAL to "bizarre", stateWords("bizarre"))
        assertTrue(serviceTrouble("panne") && !serviceTrouble("connecte"))
        val tools = listOf(
            ServiceTool(remote = "a", choice = ToolChoices.READ),
            ServiceTool(remote = "b", choice = ToolChoices.OFF),
            ServiceTool(remote = "c", choice = "", new = true),
            ServiceTool(remote = "d", choice = ToolChoices.ACT, changed = true),
        )
        assertEquals(Served(served = 2, total = 4, review = 2), servedOf(tools))
        assertEquals(Tone.INFO to "nouveau", toolState(tools[2]))
        assertEquals(Tone.WARN to "changé", toolState(tools[3]))
        assertEquals(Tone.NEUTRAL to "coupé", toolState(tools[1]))
        assertEquals("", shownChoice(tools[3]))
        assertEquals("Il agit", choiceWords(ToolChoices.ACT))
    }

    @Test fun `ne partent que les choix d'outils qui ont bougé, un outil qui attend se décide même comme avant`() {
        val tools = listOf(
            ServiceTool(remote = "a", choice = ToolChoices.READ),
            ServiceTool(remote = "d", choice = ToolChoices.ACT, changed = true),
            ServiceTool(remote = "c", new = true),
        )
        val picks = mapOf("a" to ToolChoices.READ, "d" to ToolChoices.ACT, "c" to "", "zz" to ToolChoices.READ)
        assertEquals(mapOf("d" to ToolChoices.ACT), toolChoiceChanges(tools, picks))
        assertEquals(mapOf("a" to ToolChoices.OFF, "d" to ToolChoices.ACT), toolChoiceChanges(tools, picks + ("a" to ToolChoices.OFF)))
    }

    @Test fun `ce qui part d'un service réglé, des en-têtes seulement s'ils sont tapés`() {
        val s = Service(name = "meteo", purpose = "météo", url = "https://m.example/mcp", enabled = true, headers = true)
        assertTrue(serviceChanges(s, "météo", "", " https://m.example/mcp ", true, "").isEmpty())
        val sent = serviceChanges(s, "la météo", "le matin", "https://n.example/mcp", false, "Authorization: Bearer x")
        assertEquals(setOf("purpose", "when_to_use", "url", "enabled", "secret_headers"), sent.keys)
        assertFalse(sent["enabled"]!!.jsonPrimitive.boolean)
    }

    @Test fun `le nom et l'adresse d'un service`() {
        assertEquals("Un nom court.", serviceNameProblem(""))
        assertEquals("", serviceNameProblem("agenda_club"))
        assertTrue(serviceNameProblem("Agenda").isNotEmpty())
        assertTrue(serviceNameProblem("a".repeat(25)).isNotEmpty())
        assertEquals("Son adresse.", urlProblem(" "))
        assertEquals("", urlProblem("https://x.example/mcp"))
        assertTrue(urlProblem("http://x.example/mcp").startsWith("Une adresse https"))
    }

    @Test fun `ses lignes d'accès, la tienne est « toi », un partage par son nom`() {
        val mine = AccessLine(who = "Adrien", mine = true)
        val lea = AccessLine(who = "Léa")
        assertEquals("toi", whoWords(mine))
        assertEquals("tout le monde", whoWords(AccessLine()))
        assertEquals("Léa", sharedWith(Service(access = listOf(mine, lea, AccessLine()))))
        assertEquals("fermé : personne d'autre", defaultWords(AccessLine(read = "non", act = "non")))
        assertEquals("fermé : personne d'autre", defaultWords(null))
        assertEquals("il lit : seule · il agit : non · privé", defaultWords(AccessLine(read = "seule", act = "x", readWords = "seule", actWords = "non", keepWords = "privé")))
        val r = ReceivedService(level = Levels.USE, ownerName = "Léa", line = AccessLine(readWords = "seule", actWords = ""))
        assertTrue(receivedSentence(r).contains("et ceux qui agissent"))
        assertEquals("seule", forYou(r, ToolChoices.READ))
        assertEquals("non", forYou(r, ToolChoices.ACT))
    }

    @Test fun `une adresse qui mène ailleurs redemande ses en-têtes gardés (ADR 0236)`() {
        val kept = Service(name = "agenda", url = "https://agenda.exemple.fr/mcp", headers = true)
        fun changes(url: String, headers: String = "", clear: Boolean = false) = serviceChanges(kept, "", "", url, true, headers, clear)
        assertEquals(mapOf("secret_headers" to HEADERS_TO_RETYPE), headersToRetype(kept, changes("https://autre.example/mcp")))
        assertEquals(mapOf("secret_headers" to HEADERS_TO_RETYPE), headersToRetype(kept, changes("https://agenda.exemple.fr:8443/mcp")))
        assertTrue(headersToRetype(kept, changes("https://autre.example/mcp", headers = "Authorization: Bearer x")).isEmpty())
        val cleared = changes("https://autre.example/mcp", clear = true)
        assertEquals(true, cleared["clear_headers"]?.jsonPrimitive?.boolean)
        assertTrue(headersToRetype(kept, cleared).isEmpty())
        assertTrue(headersToRetype(kept, changes("https://AGENDA.exemple.fr:443/v2/mcp")).isEmpty())
        assertTrue(headersToRetype(kept.copy(headers = false), changes("https://autre.example/mcp")).isEmpty())
        // retirer ce qu'il n'a pas ne part pas
        assertFalse("clear_headers" in serviceChanges(kept.copy(headers = false), "", "", kept.url, true, "", true))
        assertEquals(urlOrigin("https://Agenda.exemple.fr/x"), urlOrigin("https://agenda.exemple.fr:443/mcp"))
    }

    // ── tes téléphones ──

    @Test fun `celui-ci d'abord, les révoqués à la fin`() {
        val label = "Android · samsung SM-S931B"
        val phones = listOf(
            PhoneDevice(1, "Android · Google Pixel 7a", lastUsed = 5, revoked = true),
            PhoneDevice(2, "Android · Google Pixel 8", lastUsed = 9),
            PhoneDevice(3, label, lastUsed = 7),
            PhoneDevice(4, "Android · Fairphone 5", lastUsed = 8),
        )
        val rows = phoneRows(phones, label, tokenId = 3)
        assertEquals(listOf(3L, 2L, 4L, 1L), rows.map { it.phone.id })
        assertEquals(listOf(true, false, false, false), rows.map { it.mine })
        assertEquals(listOf(false, true, true, false), rows.map { it.revocable })
        assertEquals("même application fermée", pushWords(true))
        assertEquals("sans notifications", pushWords(false))
    }

    @Test fun `ce téléphone se reconnaît au jeton de sa session, même si l'autre du même nom a servi après (R3-03)`() {
        val label = "Android · samsung SM-S921B"
        // le perdu, resté connecté, pousse ses messages lus : son jeton a servi après celui du neuf
        val lost = PhoneDevice(7, label, lastUsed = 9_000)
        val mine = PhoneDevice(9, label, lastUsed = 5_000)
        val rows = phoneRows(listOf(lost, mine), label, tokenId = 9)
        assertEquals(listOf(9L, 7L), rows.map { it.phone.id })
        assertEquals(listOf(true, false), rows.map { it.mine })
        assertTrue(rows[1].revocable)
        assertFalse(rows.any { it.unsure })
    }

    @Test fun `une session d'avant, sans l'identifiant de son jeton - pas de « Révoquer » sur l'autre du même nom`() {
        val label = "Android · samsung SM-S921B"
        val rows = phoneRows(
            listOf(PhoneDevice(7, label, lastUsed = 9_000), PhoneDevice(9, label, lastUsed = 5_000), PhoneDevice(4, "Android · Google Pixel 8", lastUsed = 1)),
            label,
            tokenId = null,
        )
        // reconnu par son nom (le plus récent) : une supposition ; l'autre pourrait être celui-ci
        assertEquals(listOf(true, false, false), rows.map { it.mine })
        assertEquals(listOf(false, true, false), rows.map { it.unsure })
        assertEquals(listOf(false, false, true), rows.map { it.revocable })
    }

    // ── la page racine ──

    @Test fun `ce que dit chaque ligne de la page racine`() {
        val boxes = listOf(MailBox(level = Levels.OWNER), MailBox(level = Levels.OWNER), MailBox(level = Levels.READ))
        assertEquals("2 à toi · 1 partagée avec toi", boxesSummary(boxes))
        assertEquals("aucune boîte", boxesSummary(emptyList()))
        assertEquals("Atelier · 2 partagés avec toi", teamsSummary(listOf(TeamsAccount(name = "Atelier", level = Levels.OWNER), TeamsAccount(), TeamsAccount())))
        val shares = Shares(
            given = listOf(
                GivenShare(title = "Rando", name = "Julien Martin"),
                GivenShare(title = "Météo", name = "Léa"),
                GivenShare(title = "Pro", name = "Paul"),
            ),
            received = listOf(ReceivedShare()),
        )
        assertEquals("Rando → Julien · Météo → Léa · +1 · 1 partagé avec toi", sharesSummary(shares))
        assertEquals("rien de partagé", sharesSummary(Shares()))
        assertEquals("meteo, agenda · 1 partagé avec toi", servicesSummary(Services(items = listOf(Service(name = "meteo"), Service(name = "agenda")), received = listOf(ReceivedService()))))
        assertEquals("aucun service", servicesSummary(Services()))
        assertEquals("Fait.", doneText("", "Fait."))
    }
}
