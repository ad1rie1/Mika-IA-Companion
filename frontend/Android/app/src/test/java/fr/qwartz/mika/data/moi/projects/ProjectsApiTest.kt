package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * Les projets sur l'API par personne (`protocole-moi.md` § 11) : les exemples du protocole lus tels quels (la liste et
 * « À faire », un élément, son parcours), les champs absents ou `null` qui ne cassent rien, ce que chaque appel envoie —
 * sous le jeton de ce téléphone, sans jeton CSRF, avec sa clé d'envoi —, et les refus dits avec les mots du serveur.
 */
class ProjectsApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: ProjectsApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = ProjectsApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())

    private fun JsonObject.text(name: String): String? = (this[name] as? JsonPrimitive)?.content

    @Test fun `la liste se lit comme le protocole l'écrit - un projet, une attente et son geste, sa carte`() = runBlocking {
        ok(
            """{"projects": [{"id": 3, "title": "Outils réseau", "status": "active", "status_label": "actif", "mine": true,
                 "hers": true, "owner_name": "", "steer": "modification", "steer_label": "modification",
                 "detail": true, "where": "Le squelette est posé.", "last_run": 1790790000000, "plan": "planned",
                 "plan_label": "validé", "waiting": 2,
                 "card": {"objectives": {"total": 3, "done": 1, "doing": 1, "todo": 1, "blocked": 0,
                            "states": [{"id": 1, "state": "done", "state_label": "terminé"}, {"id": 2, "state": "doing", "state_label": "en cours"}]},
                          "pulls_open": 3, "tickets_open": 5, "reads": [{"project": null, "title": "", "visible": false}],
                          "readers": [{"project": 8, "title": "Faire connaître", "visible": true}], "led_by": "Mika", "last_activity": 1790790060000}},
                {"id": 9, "title": "Vu seulement", "status": "paused", "status_label": "en pause", "detail": false, "card": null}],
               "todo": [{"project": 3, "project_title": "Outils réseau", "kind": "ticket", "kind_label": "ticket",
                         "what": "validation", "about": "#4 Journaliser les refus — son plan attend ta validation",
                         "since": 1790790000000, "mine": true, "can": true, "why": "", "waits_for": "", "objective": 0,
                         "number": 4, "key": "", "veiled": "", "outside": false,
                         "gesture": {"route": "ticket/trancher", "args": {"item": "#4", "verdict": "validate", "plan": 812},
                                     "label": "Valider ou refuser son plan", "where": "ici", "url": ""}}],
               "todo_total": 7, "create": {"can": true, "why": ""}, "futur": 1}""",
        )
        val o = (api.overview() as MoiApi.Result.Ok).value
        val req = server.takeRequest()
        assertEquals("/api/moi/projets", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertNull(req.headers["Origin"])
        val p = o.projects.first()
        assertEquals("actif", p.statusLabel)
        assertTrue(p.mine && p.hers && p.detail)
        assertEquals(1790790000000L, p.lastRun)
        val card = p.card!!
        assertEquals(listOf("done", "doing"), card.objectives.states.map { it.state })
        assertEquals(3, card.pullsOpen)
        assertNull(card.reads.single().project)
        assertFalse(card.reads.single().visible)
        assertEquals("Mika", card.ledBy)
        assertNull(o.projects.last().card)
        val w = o.todo.single()
        assertEquals("ticket/trancher", w.gesture.route)
        assertEquals("ici", w.gesture.where)
        assertEquals("ticket-4", waitingKey(w))
        assertEquals(7, o.todoTotal)
        assertTrue(o.create.can)
    }

    @Test fun `un élément - sa ligne et son détail dans la même réponse, son parcours, ce que can ouvre`() = runBlocking {
        ok(
            """{"list": "tickets", "handle": "#4", "number": 4, "key": "plan-journal", "title": "Journaliser les refus",
                "veiled": "", "veiled_label": "", "status": "validation", "status_label": "en attente de validation",
                "open": true, "hand": "owner", "hand_label": "au propriétaire", "yours": true, "kind": "task",
                "kind_label": "tâche", "priority": "normal", "priority_label": "normale", "actor": "self", "actor_label": "elle",
                "author_kind": "person", "author": "Adrien Moreau", "outside": false, "objective": 0, "notes": 1, "at": 1790790000000,
                "updated_at": 1790790060000, "plan": 812, "issue": 9, "pull": 0, "step": "validation",
                "step_label": "Validation", "issue_state": "open", "issue_state_label": "ouverte",
                "body": "Quand une connexion est refusée…", "link": "", "plan_text": "1. Un refus = une ligne JSON", "small": false, "statuses": [],
                "thread": [{"seq": 12, "at": 1790790030000, "author_kind": "host", "author": "quelqu'un chez l'hôte du dépôt",
                            "kind": "note", "kind_label": "note", "text": "+1", "outside": true}],
                "journey": {"steps": [{"code": "unread", "label": "Non lu", "state": "done", "state_label": "passée"},
                                      {"code": "validation", "label": "Validation", "state": "current", "state_label": "en cours"},
                                      {"code": "pull", "label": "Pull request", "state": "skipped", "state_label": "sautée"}],
                            "current": "validation", "current_label": "Validation", "fine": "validation", "fine_label": "en attente de validation",
                            "through_pull": false, "skips": ["pull", "merge"], "skips_label": "Ce ticket ne produit pas de code.", "ended": "", "ended_label": ""},
                "linked": {"objective": null, "pull": {"number": 12, "title": "Journal des refus", "state": "open", "state_label": "ouverte",
                           "words": "attend la CI", "said": {"text": "LGTM", "outside": true}}, "checks": {"state": "pending", "state_label": "en cours"}},
                "can": {"note": true, "status": false, "accept": false, "dismiss": true, "dismiss_needs_reason": true, "validate": true, "refuse": true, "modify": true}}""",
        )
        val e = (api.element(3, "tickets", "#4") as MoiApi.Result.Ok).value
        val url = server.takeRequest().url
        assertEquals("/api/moi/projets/3/element", url.encodedPath)
        assertEquals("tickets", url.queryParameter("list"))
        assertEquals("#4", url.queryParameter("item"))
        assertEquals(812, e.line.plan)
        assertTrue(e.line.yours)
        assertEquals("ouverte", e.line.issueStateLabel)
        assertEquals("1. Un refus = une ligne JSON", e.more.planText)
        assertTrue(e.more.thread.single().outside)
        val j = e.more.journey!!
        assertEquals(listOf("done", "current", "skipped"), j.steps.map { it.state })
        assertFalse(j.throughPull)
        assertEquals("Ce ticket ne produit pas de code.", j.skipsLabel)
        assertEquals("LGTM", e.more.linked.pull!!.said!!.text)
        assertEquals("pending", e.more.linked.checks!!.state)
        assertNull(e.more.linked.objective)
        assertTrue(e.more.can.validate && e.more.can.dismissNeedsReason && e.more.can.modify)
        assertFalse(e.more.can.accept || e.more.can.close || e.more.can.reopen)
    }

    @Test fun `la fiche de qui ne fait que voir - project, rights, todo, et rien d'autre ne manque`() = runBlocking {
        ok("""{"project": {"id": 9, "title": "Vu", "status": "active", "status_label": "actif", "description": null},
               "rights": {"steer": "non", "steer_label": "non", "detail": false}, "todo": []}""")
        val s = (api.sheet(9) as MoiApi.Result.Ok).value
        assertEquals("/api/moi/projets/9", server.takeRequest().url.encodedPath)
        assertFalse(s.rights.detail || s.rights.pilot || s.rights.edit || s.rights.settle || s.rights.ticket)
        assertEquals("", s.project.description)
        assertTrue(s.objectives.isEmpty() && s.missions.isEmpty() && s.lists.isEmpty())
        assertNull(s.plan)
        assertNull(s.next)
        assertFalse(s.forms.can)
        assertEquals(listOf("vue"), SheetTabs.of(s))
    }

    @Test fun `la fiche entière - ses droits, un objectif et ses jalons, ses formulaires, la liste des tickets`() = runBlocking {
        ok(
            """{"project": {"id": 3, "title": "Outils réseau", "status": "active", "status_label": "actif", "mine": true, "detail": true, "description": "Un outillage réseau."},
                "rights": {"steer": "modification", "detail": true, "ticket": true, "ticket_born": "open", "note": true, "settle": true, "plan": true,
                           "pilot": true, "edit": true, "work": true, "files": true},
                "todo": [],
                "missions": [{"id": 5, "text": "Traiter les tickets", "status": "open", "status_label": "en cours", "cadence_hours": 0,
                              "cadence_label": "à chaque changement", "on": [{"key": "item:tickets", "label": "ses tickets"}], "only_on_event": true,
                              "passes": 12, "can": {"modify": true, "drop": true, "why": ""}}],
                "objectives": [{"id": 2, "text": "Créer un module RDP", "status": "open", "status_label": "en cours", "done_when": "", "runs": 6,
                                "branch": "mika/objectif-2", "tickets": [{"number": 4, "handle": "#4", "title": "Journaliser les refus", "status": "validation", "open": true}],
                                "milestones": [{"id": 7, "text": "Tu as relu l'écran", "check": "owner", "check_label": "un point d'arrêt", "status": "open",
                                                "status_label": "à atteindre", "ready": true, "ready_at": 1790790000000, "proof": {"text": "3 passed", "outside": true},
                                                "can": {"modify": false, "drop": false, "why": "Seul qui tranche change ce jalon."}}],
                                "pull": null, "checks": null, "review": {"ok": false, "label": "refusée", "refused": 2, "handed_over": true, "last_refusal": "Il manque un test."},
                                "can": {"modify": true, "reopen": false, "done": true, "drop": true, "milestone": true, "why": ""}}],
                "plan": {"state": "planned", "state_label": "validé", "text": "## Plan", "questions": "", "version": 3},
                "lists": [{"name": "tickets", "title": "Tickets", "tickets": true, "open": [{"code": "unread", "label": "non lu"}], "closed": [],
                           "counts": {"unread": 1}, "total": 6, "living": 5, "kinds": [{"code": "bug", "label": "défaut"}], "kind_default": "task",
                           "priorities": [{"code": "low", "label": "basse"}], "priority_default": "normal",
                           "journey": [{"code": "unread", "label": "Non lu", "count": 1}]}],
                "links": {"reads": [{"project": 1, "title": "Inventaire du parc", "visible": true, "gives": {"see": true}}], "readers": [],
                          "labels": {"title": "Dépendances", "reads": "Il dépend de", "readers": "Dépendent de lui", "asks": "Ses demandes"}},
                "repo": {"has_remote": true, "branch": "main", "flow": "pr", "flow_label": "par pull request",
                         "commit": {"sha": "cdd07ae46e31", "short": "cdd07ae", "title": "Ajoute --delai", "at": 1790790000000, "outside": false}},
                "next": {"at": 0, "state": "running", "state_label": "une exécution est en cours", "sort": "run", "sort_label": "du travail", "objective": {"id": 2, "text": "Créer un module RDP", "kind": "once"}},
                "rhythm": {"schedule": "toutes les heures", "window": "de 8 h à 20 h", "summary": "Toutes les heures, de 8 h à 20 h."},
                "instructions": [{"seq": 40, "at": 1790790000000, "text": "Reste sur IPv4.", "veiled": false, "author_kind": "you", "author": "toi"}],
                "forms": {"can": true, "why": "", "triggers": [{"key": "item:tickets", "label": "ses tickets", "sort": "item", "sort_label": "une liste", "project": null, "title": ""}],
                          "triggers_max": 4, "checks": [{"code": "command", "label": "une commande", "help": "Elle la lance.", "fields": [{"name": "command", "label": "La commande", "help": "", "required": true}]}]}}""",
        )
        val s = (api.sheet(3) as MoiApi.Result.Ok).value
        assertTrue(s.rights.pilot && s.rights.edit && s.rights.settle && s.rights.work)
        assertFalse(s.rights.frame || s.rights.merge)
        val m = s.missions.single()
        assertEquals("item:tickets", m.on.single().key)
        assertTrue(m.onlyOnEvent && m.can.drop)
        val o = s.objectives.single()
        assertEquals("#4", o.tickets.single().handle)
        val step = o.milestones.single()
        assertTrue(step.ready)
        assertEquals("3 passed", step.proof!!.text)
        assertEquals("Seul qui tranche change ce jalon.", step.can.why)
        assertNull(o.pull)
        assertEquals("Il manque un test.", o.review!!.lastRefusal)
        assertTrue(o.can.milestone && o.can.done && !o.can.reopen)
        val tickets = ticketList(s)!!
        assertEquals(5, tickets.living)
        assertEquals("défaut", tickets.kinds.single().label)
        assertEquals("task", tickets.kindDefault)
        assertEquals(1, tickets.journey.single().count)
        assertEquals("Inventaire du parc", s.links!!.reads.single().title)
        assertEquals("cdd07ae", s.repo!!.commit!!.short)
        assertEquals("running", s.next!!.state)
        assertEquals(2, s.next!!.objective!!.id)
        assertEquals("Reste sur IPv4.", s.instructions.single().text)
        assertEquals(4, s.forms.triggersMax)
        assertEquals("command", s.forms.checks.single().fields.single().name)
    }

    @Test fun `ce que chaque lecture envoie - la page, le projet d'un accord, le filtre et la recherche, l'objectif d'un fil`() = runBlocking {
        ok("""{"total": 30, "page": 2, "size": 25, "items": []}""")
        api.todo(2)
        val todo = server.takeRequest().url
        assertEquals("/api/moi/projets/a-faire", todo.encodedPath)
        assertEquals("2", todo.queryParameter("page"))

        ok("""{"items": [{"id": 41, "project": 3, "label": "Commenter une issue", "text": "Merci, c'est corrigé.", "digest": "abc", "blocked": "",
               "concerns": {"objective": 0, "ticket": null, "issue": 9, "pull": 0}, "where": "chez l'hôte, en issue", "where_url": "https://hote.example/issues/9"}]}""")
        val a = (api.approvals(3) as MoiApi.Result.Ok).value.items.single()
        val accords = server.takeRequest().url
        assertEquals("/api/moi/projets/accords", accords.encodedPath)
        assertEquals("3", accords.queryParameter("project"))
        assertEquals("abc", a.digest)
        assertEquals(9, a.concerns.issue)
        assertNull(a.concerns.ticket)

        ok("""{"list": "tickets", "total": 0, "page": 1, "size": 100, "items": []}""")
        api.elements(3, state = "open", q = "  délai ")
        val list = server.takeRequest().url
        assertEquals("/api/moi/projets/3/elements", list.encodedPath)
        assertEquals("tickets", list.queryParameter("list"))
        assertEquals("open", list.queryParameter("state"))
        assertEquals("délai", list.queryParameter("q"))
        assertEquals("100", list.queryParameter("size"))

        ok("""{"list": "tickets", "total": 0, "page": 1, "size": 100, "items": []}""")
        api.elements(3)
        val all = server.takeRequest().url
        assertNull(all.queryParameter("state"))
        assertNull(all.queryParameter("q"))

        ok("""{"kinds": [], "size": 30, "next": 0, "items": [{"seq": 4120, "at": 1790790000000, "kind": "run", "title": "Le journal est écrit.", "verdict": "continue", "verdict_label": "continuer", "run": "ep-1"}]}""")
        val runs = (api.activity(3, kind = "run", objective = 2) as MoiApi.Result.Ok).value
        val feed = server.takeRequest().url
        assertEquals("/api/moi/projets/3/activite", feed.encodedPath)
        assertEquals("run", feed.queryParameter("kind"))
        assertEquals("2", feed.queryParameter("objective"))
        assertNull(feed.queryParameter("ticket"))
        assertNull(feed.queryParameter("before"))
        assertEquals("continuer", runs.items.single().verdictLabel)

        ok("""{"item": "#4", "cut": false, "items": [{"seq": 1, "at": 5, "status": "unread", "status_label": "non lu", "was": "", "step": "unread", "author_kind": "you", "author": "toi"}]}""")
        assertEquals("", (api.history(3, "#4") as MoiApi.Result.Ok).value.items.single().was)
        val history = server.takeRequest().url
        assertEquals("/api/moi/projets/3/element/historique", history.encodedPath)
        assertEquals("#4", history.queryParameter("item"))

        ok("""{"now": 10, "from": 1, "cut": false, "objectives": [{"id": 5, "kind": "constant", "passes": [3, 6], "milestones": []}]}""")
        assertEquals(listOf(3L, 6L), (api.diagram(3) as MoiApi.Result.Ok).value.objectives.single().passes)
        assertEquals("/api/moi/projets/3/diagramme", server.takeRequest().url.encodedPath)
    }

    @Test fun `nouveau projet - ses champs sont ceux du serveur, une valeur de toute sorte se lit`() = runBlocking {
        ok(
            """{"can": true, "why": "", "fields": [
                 {"name": "title", "label": "Son titre", "help": "", "kind": "text", "required": true, "choices": [], "value": ""},
                 {"name": "mode", "label": "Son mode", "kind": "select", "choices": [{"code": "auto", "label": "Autonome"}], "value": "auto"},
                 {"name": "at_once", "label": "Tout de suite", "kind": "bool", "value": true},
                 {"name": "hours", "label": "Heures", "kind": "int", "value": 4, "min": 1, "max": null, "only": [{"field": "mode", "values": ["auto", 2]}]},
                 {"name": "rien", "label": "Rien", "kind": "text", "value": null}]}""",
        )
        val form = (api.newProject() as MoiApi.Result.Ok).value
        assertEquals("/api/moi/projets/nouveau", server.takeRequest().url.encodedPath)
        assertTrue(form.can)
        assertEquals(listOf("", "auto", "true", "4", ""), form.fields.map { it.value })
        assertEquals("Autonome", form.fields[1].choices.single().label)
        assertEquals(listOf("auto", "2"), form.fields[3].only.single().values)
    }

    @Test fun `un geste part sous le jeton, sans CSRF, avec sa clé d'envoi et le corps tel quel`() = runBlocking {
        ok("""{"ok": true, "message": "Son plan est validé.", "deduped": false}""")
        val done = api.gesture(3, settleRequest(Entry(list = "tickets", handle = "#4", plan = 812), "validate"), "cle-1")
        assertEquals("Son plan est validé.", (done as MoiApi.Result.Ok).value.message)
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/moi/projets/3/ticket/trancher", req.url.encodedPath)
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertNull(req.headers["X-CSRFToken"])
        assertNull(req.headers["Origin"])
        val body = MikaJson.parseToJsonElement(req.body!!.utf8()).jsonObject
        assertEquals("#4", body.text("item"))
        assertEquals("validate", body.text("verdict"))
        assertEquals("812", body.text("plan"))
        assertFalse((body["plan"] as JsonPrimitive).isString)

        ok("""{"ok": true, "message": "Ticket ouvert.", "number": 7, "proposed": true}""")
        val opened = (api.gesture(3, ticketRequest(TicketForm(title = "Délai réglable"))) as MoiApi.Result.Ok).value
        assertEquals(7, opened.number)
        assertTrue(opened.proposed)
        assertNotNull(server.takeRequest().headers["Idempotency-Key"])

        ok("""{"ok": true, "message": "Projet confié.", "project": 12}""")
        val created = (api.create(newProjectBody(listOf(Field(name = "title")), mapOf("title" to "Inventaire")), "cle-2") as MoiApi.Result.Ok).value
        assertEquals(12, created.project)
        val creation = server.takeRequest()
        assertEquals("/api/moi/projets/nouveau/creer", creation.url.encodedPath)
        assertEquals("cle-2", creation.headers["Idempotency-Key"])
    }

    @Test fun `un refus garde les mots du serveur - 403, 409, un champ refusé, une réponse illisible`() = runBlocking {
        server.enqueue(MockResponse.Builder().code(403).body("""{"error": "Ce n'est pas à toi de trancher : c'est au propriétaire du projet."}""").build())
        val denied = (api.gesture(3, settleRequest(Entry(handle = "#4"), "accept")) as MoiApi.Result.Failed).error
        assertEquals(403, denied.code)
        assertEquals("Ce n'est pas à toi de trancher : c'est au propriétaire du projet.", denied.message)

        server.enqueue(MockResponse.Builder().code(409).body("""{"error": "Son plan a été réécrit depuis : relis-le, puis valide."}""").build())
        val stale = (api.gesture(3, settleRequest(Entry(handle = "#4", plan = 812), "validate")) as MoiApi.Result.Failed).error
        assertTrue(stale.conflict)
        assertEquals("Son plan a été réécrit depuis : relis-le, puis valide.", stale.message)

        server.enqueue(MockResponse.Builder().code(400).body("""{"error": "Une raison est exigée.", "fields": {"reason": "Dis pourquoi tu l'écartes."}}""").build())
        val field = (api.gesture(3, settleRequest(Entry(handle = "#4"), "dismiss")) as MoiApi.Result.Failed).error
        assertEquals(mapOf("reason" to "Dis pourquoi tu l'écartes."), field.fields)
        assertEquals("Une raison est exigée. Dis pourquoi tu l'écartes.", refusalWords(field.message, field.fields))

        server.enqueue(MockResponse.Builder().code(404).body("""{"error": "Ce projet n'existe pas."}""").build())
        assertTrue((api.sheet(99) as MoiApi.Result.Failed).error.gone)

        ok("""{"list": "tickets", "number": "quatre"}""")
        assertEquals(-1, (api.element(3, "tickets", "#4") as MoiApi.Result.Failed).error.code)
    }
}
