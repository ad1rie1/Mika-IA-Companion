package fr.qwartz.mika.data.moi.tools

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.settings.RuleLine
import fr.qwartz.mika.data.moi.settings.SendRules
import fr.qwartz.mika.data.net.ServerBase
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles d'Outils, portées de `frontendv2/src/screens/outils/matrix.ts` : les mots d'une case, le canal lu sur ce
 * téléphone et ses moments, le nom d'un outil pour toi, les ressources et leurs groupes, le résumé d'une carte, ce qui
 * décide d'une case, ce qu'une opératrice voit de plus, les lignes de « Services ».
 */
class ToolsRulesTest {
    private fun cell(level: String, why: String = "tout le monde, toujours", keep: String = Keeps.PUBLIC, reason: String = "", line: String = "", owned: Boolean = false) =
        RightsCell(level = level, keep = keep, why = why, line = line, reason = reason, owned = owned)

    private fun tool(name: String, cells: Map<String, RightsCell?>, label: String = "", acts: Boolean = false, description: String = "$name : ce qu'il fait.") =
        RightsTool(name = name, label = label, description = description, acts = acts, cells = cells)

    private val canals = listOf(
        RightsCanal("web", "Chat web"), RightsCanal("salon", "Un salon"), RightsCanal("mobile", "App Android"),
        RightsCanal("teams", "Teams"), RightsCanal("courrier", "Courrier"), RightsCanal("seule", "Elle seule"),
    )
    private val moments = listOf(
        RightsMoment("reply", "quand elle te répond"), RightsMoment("initiative", "quand elle te parle d'elle-même"),
        RightsMoment("work", "quand elle travaille seule"),
    )

    private val email = RightsResource(
        key = "famille:email", title = "Courrier", description = "tes boîtes",
        tools = listOf(
            tool("email_read", mapOf("web/reply" to cell("seule"), "mobile/reply" to cell("toi"), "mobile/initiative" to cell("seule"), "salon/reply" to cell("non"), "seule/work" to cell("seule")), label = "Ouvrir un de tes mails"),
            tool("email_tidy", mapOf("web/reply" to cell("carte"), "mobile/reply" to cell("carte"), "mobile/initiative" to cell("non"), "seule/work" to null), label = "Ranger tes mails", acts = true),
            tool("email_send", mapOf("mobile/reply" to cell("non", keep = Keeps.NOTHING), "mobile/initiative" to cell("non", keep = Keeps.NOTHING)), label = "Envoyer un mail", acts = true),
            tool("goal_drop", mapOf("web/reply" to null, "seule/work" to null), label = "Renoncer à un but qu'elle s'était donné"),
        ),
    )
    private val self = RightsResource(
        key = "famille:self", title = "Son journal", description = "relire son journal",
        tools = listOf(tool("self_journal", mapOf("web/reply" to cell("non"), "seule/work" to cell("seule")), label = "Relire son journal")),
    )
    private val rules = SendRules(
        canal = "courrier:pro", set = false, common = false,
        lines = listOf(RuleLine(who = "Tout le monde", whenWords = "toujours", prepare = true, reply = "accord", replyWords = "ton accord")),
        default = RuleLine(whenWords = "toujours", reply = "non", replyWords = "non"),
    )
    private val rights = Rights(
        canals = canals, moments = moments,
        groups = listOf(
            RightsGroup("families", "Ses propres outils", listOf(email, self)),
            RightsGroup("accounts", "Tes comptes", listOf(RightsResource(key = "courrier:pro", kind = "mail", title = "Boîte Pro", address = "a@b.test", family = "famille:email", rules = rules))),
            // un service de Mika : l'API ne rend pas son but, la ligne de son catalogue écrite pour elle (ADR 0209)
            RightsGroup("services", "Services", listOf(
                RightsResource(key = "mcp:web", title = "Le web", description = "chercher et lire une page", tools = listOf(tool("mcp_web_search", mapOf("web/reply" to cell("seule")), description = "Search the web. Returns titles."))),
                RightsResource(key = "mcp:meteo", title = "Service « meteo »", description = "La météo d'une ville.", tools = listOf(tool("mcp_meteo_now", mapOf("mobile/reply" to cell("toi"))))),
            )),
            RightsGroup("apps", "Apps de la Forge", emptyList()),
        ),
    )

    private fun line(who: String, mine: Boolean) = AccessLine(who = who, whenWords = "toujours", mine = mine, read = "seule", act = "carte", keep = "prive", keepWords = "une confidence")

    private val ownMeteo = Service(name = "meteo", purpose = "La météo d'une ville.", url = "https://m.example.test/mcp", state = "connecte",
        tools = listOf(ServiceTool(remote = "now", name = "mcp_meteo_now", choice = "lecture"), ServiceTool(remote = "week", choice = "")), access = listOf(line("Léa", true)))
    private val factures = Service(name = "factures", purpose = "Ses factures.", state = "erreur", tools = listOf(ServiceTool(remote = "list", choice = "lecture")))
    private val shared = ReceivedService(name = "agenda", purpose = "L'agenda de Léa.", state = "jamais", level = Levels.USE, ownerName = "Léa",
        tools = listOf(SharedTool(remote = "day", choice = "lecture")), line = line("toi", true))

    // ── les cases ──

    @Test fun `dit chaque niveau, et « — » pour un outil qui ne sert pas à ce moment`() {
        assertEquals(Tone.OK to "Seule", levelOf(cell("seule")).let { it.tone to it.word })
        assertEquals(Tone.WARN to "Demande", levelOf(cell("carte")).let { it.tone to it.word })
        assertEquals(Tone.WARN to "Accord", levelOf(cell("toi")).let { it.tone to it.word })
        assertEquals(Tone.NEUTRAL to "Non", levelOf(cell("non")).let { it.tone to it.word })
        assertEquals("Elle attend ton accord avant de s'en servir.", levelOf(cell("toi")).long)
        assertTrue(levelOf(null).unused)
        assertEquals("—", levelOf(null).word)
        assertFalse(levelOf(cell("non")).unused)
        // un niveau inconnu se dit tel quel, sans rien inventer
        assertEquals("plus tard", levelOf(cell("plus tard")).word)
    }

    @Test fun `ce qu'elle garde, en mots`() {
        assertEquals(listOf("un savoir", "un souvenir", "une confidence", "rien", "autre"),
            listOf(Keeps.PUBLIC, Keeps.PERSONAL, Keeps.PRIVATE, Keeps.NOTHING, "autre").map(::keepWords))
    }

    @Test fun `dit pourquoi avec les mots du moteur, sa condition, ce qu'elle garde`() {
        assertEquals(Why("tout le monde, toujours", "un savoir"), whyOf(cell("seule")))
        assertEquals(Why("par défaut : personne", ""), whyOf(cell("non", why = "par défaut : personne", keep = Keeps.NOTHING)))
        assertEquals(Why("sa condition : En tête-à-tête.", ""), whyOf(cell("non", why = "En tête-à-tête.", reason = Reasons.WHEN)))
        val owned = "une boîte ou un compte à ton nom, ou qu'on te partage"
        assertEquals(Why(owned, "un souvenir"), whyOf(cell("seule", why = owned, keep = Keeps.PERSONAL, owned = true)))
        val guarded = tool("location_where", mapOf("web/reply" to cell("seule"), "salon/reply" to cell("non", why = "En tête-à-tête.", reason = Reasons.WHEN)))
        assertEquals("En tête-à-tête.", conditionOf(guarded))
        assertEquals("", conditionOf(email.tools[0]))
        assertEquals(listOf("un savoir"), keepsOf(email.tools[0]))
        assertEquals(emptyList<String>(), keepsOf(email.tools[2]))
    }

    // ── le canal choisi ──

    @Test fun `l'app Android d'abord, le choix retenu tant qu'il existe`() {
        assertEquals(listOf("mobile", "web", "salon", "teams", "courrier", "seule"), canalOrder(canals).map { it.key })
        assertEquals("mobile", chosenCanal(canals, ""))
        assertEquals("teams", chosenCanal(canals, "teams"))
        assertEquals("mobile", chosenCanal(canals, "disparu"))
        assertEquals("web", chosenCanal(listOf(RightsCanal("web", "Chat web")), "mobile"))
        assertEquals("Chat web · en privé", canalName(canals[0]))
        assertEquals("Un salon · à plusieurs", canalName(canals[1]))
        assertEquals("App Android", canalName(canals[2]))
        assertEquals("Elle seule · au travail", canalName(canals[5]))
    }

    @Test fun `un canal qui parle a ses deux moments, elle seule son travail`() {
        assertEquals(listOf("reply", "initiative"), momentsOf("mobile", moments).map { it.key })
        assertEquals(listOf("work"), momentsOf("seule", moments).map { it.key })
        val pills = pillsOf(email.tools[0], "mobile", moments)
        assertEquals(listOf("toi", "seule"), pills.map { it.cell?.level })
        assertEquals(listOf("seule"), pillsOf(email.tools[0], "seule", moments).map { it.cell?.level })
        // une case absente : l'outil ne sert pas à ce moment
        assertEquals(listOf(null, null), pillsOf(email.tools[0], "teams", moments).map { it.cell })
    }

    @Test fun `le résumé compte chaque outil une fois pour le canal choisi`() {
        // email_read : seule d'elle-même ; email_tidy : te demande ; email_send : non ; goal_drop : rien par ce canal
        assertEquals(Summary(alone = 1, ask = 1, no = 1), summaryOf(email.tools, "mobile", moments))
        assertEquals(Summary(alone = 1, ask = 1, no = 0), summaryOf(email.tools, "web", moments))
        assertTrue(summaryOf(email.tools, "teams", moments).empty)
        assertEquals(RightsLevel.YOU, toolLevelIn(email.tools[1], "mobile", moments))
        assertNull(toolLevelIn(email.tools[3], "mobile", moments))
    }

    // ── le nom d'un outil ──

    @Test fun `prend son libellé pour toi, un outil venu d'ailleurs, la première proposition de sa description`() {
        val remind = tool("goal_remind", emptyMap(), label = "Te promettre un rappel", description = "Promettre un rappel à la personne à qui tu parles.")
        assertEquals("Te promettre un rappel", labelOf(remind))
        assertEquals("Tu peux te servir de « Te promettre un rappel » pour moi ?", askFor(remind))
        assertEquals("Liste ses factures", labelOf(tool("mcp_x", emptyMap(), description = "Liste ses factures. Pour un mois.")))
        assertEquals("mcp_y", labelOf(tool("mcp_y", emptyMap(), label = "  ", description = "")))
    }

    @Test fun `le repli coupe une description à sa première proposition, comme le web`() {
        assertEquals("Renoncer à ce but", toolLabel("Renoncer à ce but (seulement ce que tu as entrepris).", "goal_drop"))
        assertEquals("Tes boîtes aux lettres", toolLabel("Tes boîtes aux lettres : leurs dossiers, ce qui n'est pas lu.", "x"))
        assertEquals("Ouvrir un mail de ta boîte", toolLabel("Ouvrir un mail de ta boîte.", "x"))
        assertEquals("Conclure cette séance par un verdict", toolLabel("Conclure cette séance par un verdict. « done » n'est cru que…", "x"))
        assertEquals("Lister les mails d'une boîte ou d'un dossier",
            toolLabel("Lister les mails d'une boîte ou d'un dossier, du plus récent au plus ancien, page par page : leur date", "x"))
        assertEquals("Activer, arrêter, revenir à la version précédente", toolLabel("Activer, arrêter, revenir à la version précédente (le code seulement)", "x"))
        assertEquals("forge_help", toolLabel("", "forge_help"))
        assertEquals("Search the web", toolLabel("search the web. Returns titles.", "x"))
    }

    @Test fun `un outil qui ne sert à aucun moment se replie, ce qu'elle seule utilise se dit`() {
        assertTrue(idle(email.tools[3]))
        assertEquals(listOf("email_read", "email_tidy", "email_send"), shownTools(email.tools).map { it.name })
        assertTrue(internalOnly(self.tools))
        assertFalse(internalOnly(email.tools))
        assertFalse(internalOnly(emptyList()))
    }

    @Test fun `la fiche dit où elle s'en sert par les autres canaux`() {
        val open = openElsewhere(email.tools[0], rights, "mobile")
        assertEquals(listOf("Chat web · en privé|quand elle te répond|Seule", "Elle seule · au travail|quand elle travaille seule|Seule"),
            open.map { "${it.canal}|${it.moment}|${it.level.word}" })
        assertEquals(emptyList<OpenCell>(), openElsewhere(email.tools[2], rights, "web").filter { it.canal.startsWith("App") })
    }

    // ── les ressources et leurs groupes ──

    @Test fun `un compte ne recopie pas les outils de sa famille, dit sa sorte et qu'il est à toi`() {
        val res = resourcesOf(rights)
        assertEquals(listOf("famille:email", "famille:self", "courrier:pro", "mcp:web", "mcp:meteo"), res.map { it.key })
        val pro = res.first { it.key == "courrier:pro" }
        assertEquals("Courrier · Boîte Pro", pro.title)
        assertEquals("a@b.test · à toi", pro.sub)
        assertEquals(emptyList<RightsTool>(), pro.tools)
        assertEquals(FamilyRef("famille:email", "Courrier"), pro.family)
        assertTrue(pro.account)
        assertEquals("pro", accountKey(pro))
        assertEquals("mail", pro.icon)
        val journal = res.first { it.key == "famille:self" }
        assertTrue(journal.aloneOnly)
        assertEquals("relire son journal · ce qu'elle seule utilise", journal.sub)
        assertEquals("heart", journal.icon)
        assertEquals("tools", familyIcon("famille:inconnue"))
    }

    @Test fun `un service dit son but et à qui il est, d'après ce que ses services en disent`() {
        val res = resourcesOf(rights, Services(items = listOf(ownMeteo)))
        assertEquals("chercher et lire une page · un service de Mika", res.first { it.key == "mcp:web" }.sub)
        assertEquals("globe", res.first { it.key == "mcp:web" }.icon)
        assertEquals("La météo d'une ville. · à toi", res.first { it.key == "mcp:meteo" }.sub)
        val shared = resourcesOf(rights, Services(received = listOf(this.shared.copy(name = "meteo"))))
        assertEquals("La météo d'une ville. · partagé avec toi par Léa (s'en servir)", shared.first { it.key == "mcp:meteo" }.sub)
    }

    @Test fun `les groupes dans l'ordre de la matrice, sans groupe vide`() {
        val out = Rights(groups = listOf(
            RightsGroup("services", "Services", listOf(RightsResource(key = "mcp:web", title = "Le web"))),
            RightsGroup("futur", "Autre chose", listOf(RightsResource(key = "x:1", title = "X"))),
            RightsGroup("families", "Ses propres outils", listOf(self)),
            RightsGroup("apps", "Apps de la Forge", emptyList()),
        ))
        assertEquals(listOf("families", "services", "futur"), groupsOf(resourcesOf(out)).map { it.key })
        assertEquals(listOf("Ses propres outils", "Tes comptes", "Services"), groupsOf(resourcesOf(rights)).map { it.title })
    }

    @Test fun `la règle d'un compte dit d'où elle vient, et le ton de comment ça part`() {
        assertEquals(RulesOrigin.START, rulesOrigin(rules))
        assertEquals(RulesOrigin.COMMON, rulesOrigin(rules.copy(common = true)))
        assertEquals(RulesOrigin.SET, rulesOrigin(rules.copy(set = true, common = true)))
        assertEquals(listOf(Tone.OK, Tone.WARN, Tone.INFO, Tone.NEUTRAL), listOf("seule", "accord", "brouillon", "non").map(::replyTone))
    }

    // ── ce qu'une opératrice voit de plus ──

    @Test fun `la ligne même et la page de la console ne vont qu'à une opératrice, et rien d'autre ne s'ouvre`() {
        val c = cell("toi", line = " ligne 2 — serré par le canal ")
        assertEquals("ligne 2 — serré par le canal", lineFor(c, operator = true))
        assertEquals("", lineFor(c, operator = false))
        assertEquals("", lineFor(null, operator = true))
        val res = resourcesOf(rights.copy(groups = listOf(RightsGroup("families", "Ses propres outils", listOf(email.copy(href = "/admin/reglages/droits?detail=famille%3Aemail")))))).single()
        assertEquals("/admin/reglages/droits?detail=famille%3Aemail", consoleFor(res, operator = true))
        assertNull(consoleFor(res, operator = false))
        assertNull(consoleHref("https://ailleurs.test/admin/x"))
        assertNull(consoleHref("/admin/x?y=<script>"))
        assertNull(consoleHref("/api/moi/rights"))
        assertEquals("/admin/reglages/droits", consoleHref("/admin/reglages/droits"))
    }

    @Test fun `la page de la console s'ouvre sur le serveur de la session, sa requête gardée telle quelle`() {
        val base = (ServerBase.parse("http://192.168.1.22:8001/mika") as ServerBase.Parsed.Ok).base
        assertEquals("http://192.168.1.22:8001/mika/admin/reglages/droits?detail=famille%3Aemail",
            consoleUrl(base, "/admin/reglages/droits?detail=famille%3Aemail").toString())
        assertEquals("http://192.168.1.22:8001/mika/admin/reglages/droits", consoleUrl(base, "/admin/reglages/droits").toString())
        assertNull(consoleUrl(base, "//ailleurs.test/admin"))
    }

    // ── les services ──

    @Test fun `montre aussi tes services et ceux qu'on te partage, même sans case ouverte`() {
        val res = resourcesOf(rights, Services(items = listOf(ownMeteo, factures), received = listOf(shared)))
        val rows = serviceRows(res, listOf(ownMeteo, factures), listOf(shared))
        assertEquals(listOf("mcp:web", "mcp:meteo", "mcp:factures", "mcp:agenda"), rows.map { it.key })
        val (web, meteo, fact, agenda) = rows
        assertEquals("Le web", serviceTitle(web))
        assertEquals("Service « factures »", serviceTitle(fact))
        assertEquals(listOf("un service de Mika", "à toi", "à toi", "partagé avec toi par Léa (s'en servir)"), rows.map(::serviceWhose))
        assertEquals(listOf("chercher et lire une page", "La météo d'une ville.", "Ses factures.", "L'agenda de Léa."), rows.map(::servicePurpose))
        assertEquals(Tone.OK to "ouvert", serviceState(web))
        assertEquals(Tone.OK to "connecté", serviceState(meteo))
        assertEquals(Tone.DANGER to "erreur", serviceState(fact))
        assertEquals(Tone.NEUTRAL to "jamais joint", serviceState(agenda))
        // dans la matrice : ce qu'une case t'ouvre ; sinon ce qu'il sert ; et tes outils à regarder
        assertEquals(ServiceTools(1, 1, 1), serviceTools(meteo))
        assertEquals(ServiceTools(1, 1, 0), serviceTools(fact))
        assertEquals(ServiceTools(0, 1, 0), serviceTools(agenda))
        assertNull(serviceTools(ServiceRow("mcp:vide", "vide", received = shared.copy(tools = emptyList()))))
        assertEquals(listOf("globe", "plug", "plug", "plug"), rows.map(::serviceIcon))
    }

    @Test fun `un service à toi ou partagé mène à sa page, un service de Mika à ses droits`() {
        val res = resourcesOf(rights)
        val rows = serviceRows(res, listOf(ownMeteo), listOf(shared))
        assertEquals(ServiceTarget.Rights("mcp:web"), serviceTarget(rows[0]))
        assertEquals(ServiceTarget.Settings("meteo"), serviceTarget(rows[1]))
        assertEquals(ServiceTarget.Settings("agenda"), serviceTarget(rows[2]))
        assertEquals(ServiceTarget.None, serviceTarget(ServiceRow("x", "x")))
        val app = resourcesOf(Rights(groups = listOf(RightsGroup("apps", "Apps de la Forge", listOf(RightsResource(key = "forge:devis", title = "App « Devis »"))))))
        val appRow = serviceRows(app, emptyList(), emptyList()).single()
        assertEquals("une app de la Forge", serviceWhose(appRow))
        assertEquals("code", serviceIcon(appRow))
        assertEquals(ServiceTarget.Rights("forge:devis"), serviceTarget(appRow))
    }
}
