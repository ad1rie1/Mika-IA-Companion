package fr.qwartz.mika.data.moi.settings

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.mail.Auths
import fr.qwartz.mika.data.moi.mail.BOX_LABELS
import fr.qwartz.mika.data.moi.mail.BoxValues
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.Voices
import fr.qwartz.mika.data.moi.mail.boxShownFields
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.tools.ReceivedService
import fr.qwartz.mika.data.moi.tools.Service
import fr.qwartz.mika.data.moi.tools.Services
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles que les pages de Paramètres partagent, portées du client web (`frontend/Web/src/shared/sharing.ts`,
 * `shared/settings.ts`, `shared/sendrules.ts`, `screens/parametres/account.ts`) : les niveaux d'un partage, les refus
 * par champ, ton compte, la règle d'envoi et sa version, les lignes de la page racine. Celles d'un domaine se testent
 * dans son paquet (`MailSettingsRulesTest`, `TeamsSettingsRulesTest`, `ToolsSettingsRulesTest`,
 * `PhoneSettingsRulesTest`).
 */
class SettingsRulesTest {

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

    // ── les formulaires ──

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
