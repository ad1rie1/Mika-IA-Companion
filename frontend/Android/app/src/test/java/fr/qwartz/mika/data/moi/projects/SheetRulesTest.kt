package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneOffset

/**
 * Les règles pures des onglets Activité, Dépendances et Listes, de « Modifier le projet » et du diagramme « Dans le
 * temps » : où mène une ligne du fil, les mots d'une durée, ce qu'un geste sur un lien, un élément ou un réglage envoie
 * (seulement ce qui change ; jamais un champ que le serveur réserve), et où se pose une barre — de vraies dates
 * seulement, ce qui n'a pas commencé se rangeant après aujourd'hui.
 */
class SheetRulesTest {
    // ── L'activité ──

    @Test fun `une ligne du fil mène à son exécution, son commit, sa pull request, son ticket, son objectif - ou nulle part`() {
        assertEquals(HappeningTarget.ToRun("ep-1"), happeningTarget(Happening(kind = "run", run = "ep-1", objective = 2)))
        assertEquals(HappeningTarget.ToCommit("cdd07ae"), happeningTarget(Happening(kind = "commit", sha = "cdd07ae", pull = 12)))
        assertEquals(HappeningTarget.ToPull(12), happeningTarget(Happening(kind = "pull", pull = 12, ticket = 5)))
        assertEquals(HappeningTarget.ToTicket(5), happeningTarget(Happening(kind = "ticket", ticket = 5, objective = 2)))
        assertEquals(HappeningTarget.ToGoal(2), happeningTarget(Happening(kind = "gesture", objective = 2)))
        assertEquals(HappeningTarget.ToRun("ep-2"), happeningTarget(Happening(kind = "gesture", run = "ep-2")))
        assertEquals(HappeningTarget.Nowhere, happeningTarget(Happening(kind = "gesture")))
        assertEquals(listOf("play", "commit", "pr", "ticket", "user"), listOf("run", "commit", "pull", "ticket", "gesture").map(::happeningIcon))
    }

    @Test fun `les couleurs d'une exécution et d'une ligne, les mots d'une durée`() {
        assertEquals(StateTone.WORK, runTone(true, "done"))
        assertEquals(StateTone.DONE, runTone(false, "done"))
        assertEquals(StateTone.FAIL, runTone(false, "blocked"))
        assertEquals(StateTone.YOU, runTone(false, "wait"))
        assertEquals(StateTone.WORK, runTone(false, "continue"))
        assertEquals(StateTone.WAIT, runTone(false, ""))
        assertEquals(StateTone.YOU, happeningTone(Happening(kind = "run", verdict = "wait")))
        assertEquals(StateTone.DONE, happeningTone(Happening(kind = "pull", what = "merged")))
        assertNull(happeningTone(Happening(kind = "gesture")))
        assertEquals(listOf("", "45 s", "14 min", "1 h 05", "2 h 00"), listOf(0L, 45, 840, 3900, 7200).map(::duration))
        assertEquals(listOf(60L, 120, 121), stepsSpent(listOf(RunStep(ms = 60_000), RunStep(ms = 60_000), RunStep(ms = 1_500))))
        assertEquals("Créer un module RDP", runTitle(Run(sortLabel = "travail", objective = RunObjective(id = 2, text = "Créer un module RDP"))))
        assertEquals("Cadrage", runTitle(Run(sortLabel = "cadrage")))
        val day = JsonObject(mapOf("day" to JsonPrimitive("2026-11-20"), "run" to JsonPrimitive(2), "total" to JsonPrimitive(5)))
        assertEquals(listOf(2, 0, 5), listOf(dayCount(day, "run"), dayCount(day, "commit"), dayCount(day)))
        assertEquals(ActivityTabs.FEED, ActivityTabs.of(""))
        assertEquals("activite/carnet", ActivityTabs.tab(ActivityTabs.of("carnet")))
    }

    // ── Les dépendances ──

    private val links = MikaJson.decodeFromString(
        Links.serializer(),
        """{"reads":[{"project":7,"title":"Inventaire du parc","visible":true,"suspended":false,"direct":true,"since":1790000000000,"why":"Pour essayer le scan.",
              "gives":{"see":true,"detail":false,"files":true,"docs":false,"ask":"proposed","ask_label":"ses demandes y sont proposées"},
              "commit":{"sha":"7c2f9aa0","short":"7c2f9aa","title":"Fusion","at":1790000000000},
              "asks":[{"project":7,"direction":"sent","from":"project","number":14,"title":"Exposer la liste","status":"analysis","step":"analysis","at":30},
                      {"project":7,"direction":"sent","from":"you","number":15,"title":"Mon ticket","status":"unread","at":50}],
              "ask_here":{"can":true,"why":"","born":"proposed","project":7,"route":"ticket"}},
             {"project":null,"title":"","visible":false,"gives":{"see":true}}],
            "plan_asks":[{"project":9,"title":"Site","visible":true}],
            "readers":[{"project":4,"title":"Faire connaître","visible":true,"gives":{"see":true,"detail":true,"files":true,"docs":true},"asks":[]}],
            "asks":[{"project":7,"direction":"sent","from":"project","number":14,"title":"Exposer la liste","status":"analysis","at":30}],
            "received":[{"project":4,"direction":"received","from":"project","number":6,"title":"","veiled":true,"status":"treated","at":40},
                        {"project":null,"direction":"sent","from":"project","number":0,"status":"proposed","at":10}],
            "can":true,
            "candidates":[{"project":7,"title":"Inventaire du parc","visible":true},{"project":9,"title":"Site","visible":true,"gives":{"see":false}},{"project":null,"visible":false}],
            "labels":{"title":"Dépendances","reads":"Il dépend de","readers":"Dépendent de lui","asks":"Ses demandes"}}""",
    )

    @Test fun `les liens d'une fiche - leur clé, ce qu'ils donnent, toutes les demandes, ceux qu'on peut ajouter`() {
        assertEquals(listOf("lit-7", "lit-x1", "luPar-4"), ties(links).map { it.key })
        assertTrue(findTie(links, "lit-7")!!.reads)
        assertFalse(findTie(links, "luPar-4")!!.reads)
        assertNull(findTie(links, "lit-99"))
        assertEquals(listOf("see" to true, "detail" to false, "files" to true, "docs" to false), given(links.reads[0].gives))
        // envoyées, reçues, et ses tickets à elle chez un projet lu : les plus récentes d'abord
        assertEquals(listOf(15, 6, 14, 0), allDemands(links).map { it.number })
        // ceux qu'elle voit et qu'il ne lit pas déjà
        assertEquals(listOf(9), linkCandidates(links).map { it.project })
        assertEquals(true, links.reads[0].askHere?.can)
        assertEquals("7c2f9aa", links.reads[0].commit?.short)
        assertEquals(LinkTabs.DEMANDS, LinkTabs.of("demandes"))
        assertEquals(LinkTabs.SCHEMA, LinkTabs.of("lit-7"))
        assertEquals("dependances/demandes", LinkTabs.tab(LinkTabs.DEMANDS))
        assertEquals(listOf(StateTone.DONE, StateTone.FAIL, StateTone.WAIT, StateTone.WORK), listOf("treated", "dismissed", "unread", "analysis").map(::askTone))
    }

    @Test fun `un geste sur un lien - ce qui change, par numéro de projet, et le mot du lien`() {
        val add = linkRequest(LinkChange.ADD, 9, "  pour citer ses commandes ")
        assertEquals("liens", add.route)
        assertEquals(setOf("add", "why", "why_for"), add.body.keys)
        // des numéros, pas des textes
        val first = add.body["add"]!!.jsonArray.single() as JsonPrimitive
        assertFalse(first.isString)
        assertEquals(9, first.intOrNull)
        assertEquals("pour citer ses commandes", (add.body["why"] as JsonPrimitive).content)
        assertEquals(9, (add.body["why_for"] as JsonPrimitive).intOrNull)
        // sans mot, ou pour autre chose qu'un ajout : seulement le changement
        assertEquals(setOf("add"), linkRequest(LinkChange.ADD, 9).body.keys)
        assertEquals(setOf("remove"), linkRequest(LinkChange.REMOVE, 7, "ignoré").body.keys)
        assertEquals(setOf("direct_on"), linkRequest(LinkChange.DIRECT_ON, 7).body.keys)
        assertEquals(setOf("direct_off"), linkRequest(LinkChange.DIRECT_OFF, 7).body.keys)
        val why = linkWhyRequest(7, " un mot ")
        assertEquals(mapOf("why" to JsonPrimitive("un mot"), "why_for" to JsonPrimitive(7)), why.body.toMap())
        // lui demander quelque chose : un ticket chez l'autre projet, par la route servie
        val ask = askRequest("ticket", " Exposer la liste ", "")
        assertEquals("ticket", ask.route)
        assertEquals(mapOf<String, JsonElement>("title" to JsonPrimitive("Exposer la liste")), ask.body.toMap())
    }

    @Test fun `le ticket d'une demande s'ouvre là où il vit, si elle voit ce projet`() {
        assertEquals(3 to 6, demandTicket(3, Demand(project = 4, direction = "received", number = 6)))
        assertEquals(7 to 14, demandTicket(3, Demand(project = 7, visible = true, direction = "sent", number = 14)))
        assertNull(demandTicket(3, Demand(project = 7, visible = false, direction = "sent", number = 14)))
        assertNull(demandTicket(3, Demand(project = null, direction = "sent", number = 0)))
    }

    // ── Les listes ──

    private val list = Listing(
        name = "entreprises", title = "Entreprises pilotes",
        open = listOf(Coded("a_contacter", "À contacter"), Coded("contactee", "Contactée")), closed = listOf(Coded("signee", "Signée")),
        counts = mapOf("a_contacter" to 7),
    )

    @Test fun `une liste se range par statut, dans l'ordre de ses statuts, avec les comptes servis`() {
        val items = listOf(Entry(list = "entreprises", key = "garage-martin", status = "contactee"), Entry(list = "entreprises", key = "atelier-brique", status = "a_contacter"))
        val groups = listGroups(list, items)
        assertEquals(listOf("a_contacter", "contactee", "signee"), groups.map { it.status.code })
        // le compte de la liste quand elle le sert (elle en a plus que ce qui est lu), sinon ce qui est lu
        assertEquals(listOf(7, 1, 0), groups.map { it.count })
        assertEquals(listOf("atelier-brique"), groups[0].items.map { it.key })
        assertEquals(listOf(StateTone.WAIT, StateTone.WORK, StateTone.DONE), listOf("a_contacter", "contactee", "signee").map { listStatusTone(list, it) })
    }

    @Test fun `les gestes d'un élément - statut, à qui il est, l'ajouter`() {
        val e = Entry(list = "entreprises", key = "atelier-brique", handle = "atelier-brique")
        val status = itemStatusRequest(e, "contactee")
        assertEquals("element/statut", status.route)
        assertEquals(mapOf<String, JsonElement>("list" to JsonPrimitive("entreprises"), "item" to JsonPrimitive("atelier-brique"), "status" to JsonPrimitive("contactee")), status.body.toMap())
        val assign = itemAssignRequest(e, "self")
        assertEquals("element/confier", assign.route)
        assertEquals("self", (assign.body["actor"] as JsonPrimitive).content)
        val add = itemAddRequest("entreprises", " Lumen Conseil ", "", "a_contacter", "owner")
        assertEquals("element/ajouter", add.route)
        assertEquals(setOf("list", "title", "status", "actor"), add.body.keys)
        assertEquals("Lumen Conseil", (add.body["title"] as JsonPrimitive).content)
        assertEquals("archiver", archiveRequest().route)
        assertEquals("restaurer", restoreRequest().route)
        assertTrue(archiveRequest().body.isEmpty())
    }

    // ── Modifier le projet ──

    private val section = MikaJson.decodeFromString(
        SettingsSection.serializer(),
        """{"name":"rythme","title":"Rythme","summary":"Une fois par jour","can":true,"why":"","fields":[
            {"name":"title","label":"Titre","help":"","kind":"text","required":true,"choices":[],"value":"Outils","min":null,"max":null,"only":[],"can":true,"why":""},
            {"name":"schedule","label":"Elle y passe","kind":"select","choices":[{"code":"daily","label":"Une fois par jour"},{"code":"custom","label":"Autre"}],"value":"daily","can":true},
            {"name":"schedule_rule","label":"Sa règle","kind":"text","value":null,"only":[{"field":"schedule","values":["custom"]}],"can":true},
            {"name":"days","label":"Les jours","kind":"select","choices":[{"code":"mon","label":"Lun"},{"code":"tue","label":"Mar"},{"code":"sat","label":"Sam"}],"value":["mon","tue"],"can":true},
            {"name":"runs_per_day","label":"Passages par jour","kind":"int","value":2,"min":1,"max":24,"can":true},
            {"name":"reread","label":"Elle se relit","kind":"bool","value":true,"can":true},
            {"name":"approval","label":"Ce qui sort attend ton accord","kind":"bool","value":true,"can":false,"why":"Ce réglage ouvre autre chose que ce projet : il est réservé à qui s'occupe d'elle."}]}""",
    )

    @Test fun `un réglage se lit dans la sorte que le serveur lui donne`() {
        val f = section.fields.associateBy { it.name }
        assertEquals("Outils", settingText(f.getValue("title"), emptyMap()))
        assertEquals("", settingText(f.getValue("schedule_rule"), emptyMap()))
        assertTrue(isListField(f.getValue("days")))
        assertFalse(isListField(f.getValue("schedule")))
        assertEquals(setOf("mon", "tue"), settingCodes(f.getValue("days"), emptyMap()))
        assertTrue(settingOn(f.getValue("reread"), emptyMap()))
        assertEquals(1.0, f.getValue("runs_per_day").min)
        assertFalse(f.getValue("approval").can)
        assertEquals("accords", SettingsSection(name = "accords").name)
        // un champ qui ne sert que pour une valeur d'un autre
        assertFalse(settingShown(f.getValue("schedule_rule"), section.fields, emptyMap()))
        assertTrue(settingShown(f.getValue("schedule_rule"), section.fields, mapOf("schedule" to JsonPrimitive("custom"))))
        assertTrue(settingShown(f.getValue("title"), section.fields, emptyMap()))
        assertEquals(listOf("flag", "clock", "shield-check", "code", "tools", "settings"), listOf("general", "rythme", "accords", "depot", "outils", "autre").map(::sectionIcon))
    }

    @Test fun `enregistrer une section n'envoie que ce qui change, dans sa sorte - et jamais un champ réservé`() {
        val typed = mapOf(
            "title" to JsonPrimitive("Outils réseau"),
            "schedule" to JsonPrimitive("daily"),
            // les mêmes jours, dans un autre ordre : rien n'a changé
            "days" to JsonArray(listOf(JsonPrimitive("tue"), JsonPrimitive("mon"))),
            // un nombre tapé arrive en texte
            "runs_per_day" to JsonPrimitive("3"),
            "reread" to JsonPrimitive(false),
            // réservé à qui s'occupe d'elle : même saisi, il ne part pas
            "approval" to JsonPrimitive(false),
        )
        val changed = settingsChanged(section.fields, typed)
        assertEquals(setOf("title", "runs_per_day", "reread"), changed.keys)
        assertEquals("Outils réseau", (changed["title"] as JsonPrimitive).content)
        val runs = changed["runs_per_day"] as JsonPrimitive
        assertFalse(runs.isString)
        assertEquals(3, runs.intOrNull)
        assertEquals(false, (changed["reread"] as JsonPrimitive).booleanOrNull)
        val request = settingsRequest("rythme", section.fields, typed)
        assertEquals("reglages/enregistrer", request.route)
        assertEquals("rythme", (request.body["section"] as JsonPrimitive).content)
        assertEquals(setOf("title", "runs_per_day", "reread"), request.body["values"]!!.jsonObject.keys)
        // une liste qui change part entière ; rien de saisi, ou la valeur servie redite : rien
        val days = settingsChanged(section.fields, mapOf("days" to JsonArray(listOf(JsonPrimitive("mon"), JsonPrimitive("sat")))))
        assertEquals(listOf("mon", "sat"), days.getValue("days").jsonArray.map { (it as JsonPrimitive).content })
        assertTrue(settingsChanged(section.fields, emptyMap()).isEmpty())
        assertTrue(settingsChanged(section.fields, mapOf("title" to JsonPrimitive("Outils"), "runs_per_day" to JsonPrimitive("2"))).isEmpty())
    }

    // ── Le diagramme, dans le temps ──

    private val now = 1_795_600_000_000L
    private val utc = ZoneOffset.UTC

    private val diagram = Diagram(
        now = now,
        from = now - 2 * DAY_MS,
        objectives = listOf(
            DiagramObjective(
                id = 1, kind = "once", status = "open", startedAt = now - 2 * DAY_MS, runs = 3,
                milestones = listOf(
                    DiagramMilestone(id = 1, status = "reached", startedAt = now - 2 * DAY_MS, reachedAt = now - DAY_MS),
                    DiagramMilestone(id = 2, status = "open"),
                ),
            ),
            DiagramObjective(id = 2, kind = "once", status = "open", after = 1, milestones = listOf(DiagramMilestone(id = 3, status = "open"))),
            DiagramObjective(id = 3, kind = "constant", status = "open", passes = listOf(now - DAY_MS)),
        ),
    )

    @Test fun `dans le temps - de vraies dates seulement, ce qui n'a pas commencé se range après aujourd'hui dans l'ordre du plan`() {
        val rows = diagramRows(diagram)
        val t = timeLayout(diagram, rows, weeks = false, width = 0f, zone = utc)
        assertEquals(6, t.tracks.size)
        assertEquals(3, t.days.size)
        assertTrue(t.days.last().today)
        assertEquals(dayStart(now, utc) - 2 * DAY_MS, t.origin)
        // l'objectif en cours : sa barre va de quand elle s'y est mise à maintenant, puis son fantôme pour le jalon à venir
        val goal = t.tracks[0].bars
        assertEquals(t.today, goal[0].left + goal[0].width, 0.01f)
        assertEquals(StateTone.WORK, goal[0].tone)
        assertTrue(goal[0].running && goal[0].goal)
        assertNull(goal[1].tone)
        assertTrue(goal[1].left > t.today)
        // un jalon atteint : de son début à quand il l'a été, hors de « maintenant » ; son mot après sa barre
        val reached = t.tracks[1].bars.single()
        assertEquals(StateTone.DONE, reached.tone)
        assertFalse(reached.running)
        assertTrue(reached.left + reached.width < t.today)
        assertTrue(t.tracks[1].label > reached.left + reached.width)
        // un jalon pas commencé : un fantôme après aujourd'hui, sans mot
        val ghost = t.tracks[2].bars.single()
        assertNull(ghost.tone)
        assertTrue(ghost.left > t.today)
        assertEquals(-1f, t.tracks[2].label, 0f)
        // l'objectif qui dépend du premier se range après lui, et une flèche les relie
        val next = t.tracks[3].bars.single()
        assertNull(next.tone)
        assertTrue(next.left > goal[1].left + goal[1].width)
        val arrow = t.arrows.single()
        assertEquals(goal[1].left + goal[1].width, arrow.x1, 0.01f)
        assertEquals(next.left, arrow.x2, 0.01f)
        assertEquals(ROW_GOAL / 2, arrow.y1, 0.01f)
        assertEquals(ROW_GOAL + 2 * ROW_STEP + ROW_GOAL / 2, arrow.y2, 0.01f)
        // une mission : son fil jusqu'à aujourd'hui, ses passages datés
        val mission = t.tracks[5]
        assertEquals(t.today, mission.line, 0.01f)
        assertEquals(1, mission.passes.size)
        assertTrue(mission.passes[0] < t.today)
        // le diagramme va jusqu'au bout de ce qui est à suivre
        assertTrue(t.width >= next.left + next.width)
    }

    @Test fun `l'axe se resserre pour tenir dans la piste, et passe en semaines quand les jours n'y tiennent pas`() {
        val rows = diagramRows(diagram)
        val wide = timeLayout(diagram, rows, weeks = false, width = 0f, zone = utc)
        val narrow = timeLayout(diagram, rows, weeks = false, width = 360f, zone = utc)
        assertTrue(narrow.day < wide.day)
        assertTrue(narrow.day >= 56f)
        assertTrue(timeLayout(diagram, rows, weeks = true, width = 0f, zone = utc).day < narrow.day)
        assertTrue(pickWeeks(diagram, 300f, utc))
        assertFalse(pickWeeks(diagram, 400f, utc))
        assertFalse(pickWeeks(diagram, 0f, utc))
        assertEquals(2, daysBack(diagram, false, utc))
        assertEquals(13, daysBack(diagram, true, utc))
        // rien n'est daté : l'axe tient en deux jours, tout est à suivre
        val empty = Diagram(now = now, objectives = listOf(DiagramObjective(id = 1, kind = "once", status = "open")))
        val t = timeLayout(empty, diagramRows(empty), weeks = false, width = 0f, zone = utc)
        assertNull(t.tracks.single().bars.single().tone)
        assertTrue(t.arrows.isEmpty())
    }
}
