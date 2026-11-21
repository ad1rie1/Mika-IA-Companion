package fr.qwartz.mika.ui.projects

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.projects.Allowed
import fr.qwartz.mika.data.moi.projects.Approval
import fr.qwartz.mika.data.moi.projects.Approvals
import fr.qwartz.mika.data.moi.projects.Entry
import fr.qwartz.mika.data.moi.projects.EntryCan
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.EntryMore
import fr.qwartz.mika.data.moi.projects.EntryPage
import fr.qwartz.mika.data.moi.projects.Field
import fr.qwartz.mika.data.moi.projects.Goal
import fr.qwartz.mika.data.moi.projects.GoalForm
import fr.qwartz.mika.data.moi.projects.NewProject
import fr.qwartz.mika.data.moi.projects.Objective
import fr.qwartz.mika.data.moi.projects.Overview
import fr.qwartz.mika.data.moi.projects.ProjectHead
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.TicketFilters
import fr.qwartz.mika.data.moi.projects.TicketForm
import fr.qwartz.mika.data.moi.projects.TodoPage
import fr.qwartz.mika.data.moi.projects.Waiting
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Les modèles de l'écran Projets contre une fausse API : l'état d'un écran (ce qui est lu, relu, gardé quand une
 * relecture échoue), une attente ouverte et sa décision (le condensé lu, le plan lu), un geste refusé dit sur place avec
 * les mots du serveur, un double appui qui ne part qu'une fois, la clé d'envoi d'un réessai, et ce qui se relit après un
 * geste abouti.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ProjectsModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeProjectsApi()
    private var badges = 0
    private val deps = ProjectsDeps(api, { badges++ }, { 1_795_600_000_000L })

    private fun waiting(json: String): Waiting = MikaJson.decodeFromString(Waiting.serializer(), json)

    private val accord = waiting(
        """{"project":3,"project_title":"Outils réseau","kind":"approval","mine":true,"can":true,"about":"Répondre sur l'issue n° 9",
            "gesture":{"route":"accord","args":{"proposal":41},"label":"Donner ton accord","where":"ici"}}""",
    )
    private val ticketPlan = waiting(
        """{"project":3,"project_title":"Outils réseau","kind":"ticket","what":"validation","number":4,"mine":true,"can":true,
            "gesture":{"route":"ticket/trancher","args":{"item":"#4","verdict":"validate","plan":812},"where":"ici"}}""",
    )

    private fun section() = main.model { ProjectsViewModel(deps) }
    private fun project() = main.model { ProjectViewModel(deps, 3) }
    private fun ticket() = main.model { TicketViewModel(deps, 3, 4) }

    private fun body(i: Int = api.sent.lastIndex) = api.sent[i].second.body
    private fun text(name: String, i: Int = api.sent.lastIndex) = (body(i)[name] as? JsonPrimitive)?.content

    // ── La rubrique ──

    @Test fun `la rubrique se lit, une relecture qui échoue garde ce qui était montré et le dit`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(projects = listOf(ProjectHead(id = 3, title = "Outils réseau")), todo = listOf(accord), todoTotal = 1))
        val vm = section()
        vm.resume()
        advanceUntilIdle()
        assertEquals(1, vm.overview.valueOrNull?.projects?.size)
        assertEquals(listOf(accord), vm.todo)
        // hors ligne : ce qui était lu reste ; une relecture demandée le dit, celle d'un retour sur l'écran non
        api.overview = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.resume()
        advanceUntilIdle()
        assertEquals(1, vm.todoTotal)
        vm.pull()
        advanceUntilIdle()
        assertTrue(vm.overview is Load.Ready)
        assertFalse(vm.refreshing)
    }

    @Test fun `hors ligne dès l'ouverture - l'écran le dit et réessayer relit`() = runTest {
        api.overview = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        val vm = section()
        vm.resume()
        advanceUntilIdle()
        assertEquals(MoiError.NETWORK, (vm.overview as Load.Failed).error.message)
        api.overview = MoiApi.Result.Ok(Overview(todoTotal = 0))
        vm.retry()
        advanceUntilIdle()
        assertTrue(vm.overview is Load.Ready)
    }

    @Test fun `la suite d'À faire s'ajoute sans redire, un projet filtré se retire en le touchant de nouveau`() = runTest {
        val first = (1..25).map { ticketPlan.copy(number = it) }
        api.overview = MoiApi.Result.Ok(Overview(todo = first, todoTotal = 27))
        api.pages[2] = TodoPage(total = 27, page = 2, items = listOf(ticketPlan.copy(number = 25), ticketPlan.copy(number = 26), accord))
        val vm = section()
        vm.resume()
        advanceUntilIdle()
        vm.more()
        advanceUntilIdle()
        assertTrue("todo:2" in api.calls)
        assertEquals(27, vm.todo.size)
        vm.pick(3)
        assertEquals(3, vm.filter)
        vm.pick(3)
        assertEquals(0, vm.filter)
    }

    @Test fun `un accord - ce qui partirait se lit, accepter renvoie son condensé, puis l'attente n'est plus à faire`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 1))
        api.approvals = Approvals(listOf(Approval(id = 41, project = 3, text = "Merci, c'est corrigé.", digest = "abc123")))
        val vm = section()
        vm.open(3, "accord-41")
        advanceUntilIdle()
        assertEquals(accord, vm.shown)
        assertTrue("approvals:3" in api.calls)
        assertEquals("Merci, c'est corrigé.", vm.approval?.text)
        api.overview = MoiApi.Result.Ok(Overview())
        vm.decide("accept")
        advanceUntilIdle()
        assertEquals("accord", api.sent.single().second.route)
        assertEquals("abc123", text("seen"))
        assertEquals("accept", text("decision"))
        assertEquals(ProjectsViewModel.todoWhere(3, "accord-41"), vm.gestures.finished)
        assertEquals(1, badges)
        assertTrue(vm.todo.isEmpty())
    }

    @Test fun `le plan d'un ticket - valider nomme le plan qu'on a lu, et un plan réécrit depuis se dit sur place`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(ticketPlan), todoTotal = 1))
        api.element = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#4", number = 4, plan = 815), EntryMore(planText = "1. …", can = EntryCan(validate = true, refuse = true))))
        val vm = section()
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertTrue("element:3:tickets:#4" in api.calls)
        api.refuse(409, "Son plan a été réécrit depuis : relis-le, puis valide.")
        vm.decide("validate")
        advanceUntilIdle()
        assertEquals("815", text("plan"))
        val where = ProjectsViewModel.todoWhere(3, "ticket-4")
        assertEquals("Son plan a été réécrit depuis : relis-le, puis valide.", vm.gestures.refusalAt(where))
        assertEquals("", vm.gestures.refusalAt("ailleurs"))
        assertNull(vm.gestures.finished)
        assertEquals(0, badges)
        // refuser porte la raison saisie
        api.gestureResult = null
        vm.decide("refuse", "trop large")
        advanceUntilIdle()
        assertEquals("trop large", text("reason"))
        assertEquals("", vm.gestures.refusalAt(where))
    }

    @Test fun `une attente qui n'est plus là se dit, sans rien lire de plus`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 1))
        val vm = section()
        vm.open(3, "ticket-99")
        advanceUntilIdle()
        assertNull(vm.shown)
        assertTrue(vm.missing)
        assertFalse(api.calls.any { it.startsWith("element") || it.startsWith("approvals") })
    }

    @Test fun `une attente plus loin que la première page se retrouve dans la fiche de son projet`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 40))
        api.sheet = MoiApi.Result.Ok(Sheet(todo = listOf(ticketPlan.copy(mine = false, number = 7), ticketPlan)))
        api.element = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#4", number = 4, plan = 812), EntryMore(can = EntryCan(validate = true))))
        val vm = section()
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertEquals(ticketPlan, vm.shown)
        assertFalse(vm.missing)
        assertTrue("sheet:3" in api.calls && "element:3:tickets:#4" in api.calls)
        // celle qui attend quelqu'un d'autre ne s'ouvre pas comme la sienne
        vm.open(3, "ticket-7")
        advanceUntilIdle()
        assertNull(vm.shown)
        assertTrue(vm.missing)
    }

    @Test fun `un double appui ne part qu'une fois, un réessai après une coupure garde sa clé, un refus en donne une neuve`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 1))
        api.approvals = Approvals(listOf(Approval(id = 41, digest = "abc")))
        val vm = section()
        vm.open(3, "accord-41")
        advanceUntilIdle()
        api.hold("gesture:accord")
        vm.decide("refuse")
        vm.decide("refuse")
        assertEquals(1, api.sent.size)
        assertEquals(ProjectsViewModel.todoWhere(3, "accord-41"), vm.gestures.busy)
        api.gestureResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        api.release("gesture:accord")
        advanceUntilIdle()
        assertEquals("", vm.gestures.busy)
        assertEquals(MoiError.NETWORK, vm.gestures.refusalAt(ProjectsViewModel.todoWhere(3, "accord-41")))
        // le réseau a coupé : on ne sait pas s'il est parti — le même geste redit porte la même clé
        api.refuse(409, "Déjà décidé.")
        vm.decide("refuse")
        advanceUntilIdle()
        assertEquals(api.sent[0].third, api.sent[1].third)
        // le serveur a répondu : le geste suivant a sa propre clé
        api.gestureResult = null
        vm.decide("refuse")
        advanceUntilIdle()
        assertNotEquals(api.sent[1].third, api.sent[2].third)
    }

    @Test fun `nouveau projet - ses champs servis, un champ refusé dit sous lui, créé il s'ouvre`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(create = Allowed(can = true)))
        api.fresh = NewProject(can = true, fields = listOf(Field(name = "title", label = "Son titre", required = true), Field(name = "request", kind = "textarea")))
        val vm = section()
        vm.resume()
        vm.openNew()
        advanceUntilIdle()
        assertEquals(2, vm.fresh?.valueOrNull?.fields?.size)
        api.refuse(400, "Un titre est exigé.", mapOf("title" to "Dis-lui comment il s'appelle."))
        vm.create(mapOf("request" to "Un inventaire du parc"))
        advanceUntilIdle()
        assertEquals("Un titre est exigé. Dis-lui comment il s'appelle.", vm.gestures.refusalAt(ProjectsViewModel.NEW))
        assertEquals("Dis-lui comment il s'appelle.", vm.gestures.fieldsAt(ProjectsViewModel.NEW)["title"])
        assertEquals(0, vm.created)
        api.gestureResult = null
        vm.create(mapOf("title" to "Inventaire", "request" to "Un inventaire du parc"))
        advanceUntilIdle()
        assertEquals("nouveau/creer", api.sent.last().second.route)
        assertEquals("Inventaire", text("title"))
        assertEquals(12, vm.created)
        assertNull(vm.fresh)
        vm.createdOpened()
        assertEquals(0, vm.created)
    }

    // ── La fiche ──

    @Test fun `piloter - la consigne part et la fiche se relit, sur accord le refus du serveur se dit en tête`() = runTest {
        api.sheet = MoiApi.Result.Ok(Sheet(project = ProjectHead(id = 3, status = "active")))
        val vm = project()
        vm.resume()
        advanceUntilIdle()
        vm.pilot("instruct", "Reste sur IPv4.")
        advanceUntilIdle()
        assertEquals("piloter", api.sent.single().second.route)
        assertEquals("instruct", text("what"))
        assertEquals("Reste sur IPv4.", text("text"))
        assertEquals(2, api.calls.count { it == "sheet:3" })
        api.refuse(403, "Ce geste demande l'accord de son propriétaire : il se demande dans le chat.")
        vm.pilot("pause")
        advanceUntilIdle()
        assertEquals("Ce geste demande l'accord de son propriétaire : il se demande dans le chat.", vm.gestures.refusalAt(ProjectViewModel.TOP))
        assertEquals(2, api.calls.count { it == "sheet:3" })
    }

    @Test fun `un objectif - ajouté, modifié par ce qui change, un point d'arrêt refusé avec ce qui manque, retiré`() = runTest {
        val o = Objective(id = 2, text = "Créer un module RDP", doneWhen = "La connexion aboutit", status = "open")
        api.sheet = MoiApi.Result.Ok(Sheet(objectives = listOf(o)))
        val vm = project()
        vm.resume()
        advanceUntilIdle()
        vm.saveGoal(GoalForm(text = "Écrire la documentation"))
        advanceUntilIdle()
        assertEquals("objectif", api.sent.last().second.route)
        assertEquals(ProjectViewModel.GOAL_NEW, vm.gestures.finished)
        vm.gestures.acknowledge()
        vm.saveGoal(GoalForm.of(o).copy(doneWhen = "La connexion aboutit, journalisée"), GoalForm.of(o), o.id)
        advanceUntilIdle()
        assertEquals("objectif/modifier", api.sent.last().second.route)
        assertEquals(setOf("objective", "done_when"), body().keys)
        assertEquals(ProjectViewModel.goalFormWhere(2), vm.gestures.finished)
        vm.checkpoint(2, 7, "refuse", "le champ domaine doit rester")
        advanceUntilIdle()
        assertEquals("jalon", api.sent.last().second.route)
        assertEquals("le champ domaine doit rester", text("reason"))
        vm.goalStatus(Goal.Once(o), "dropped")
        advanceUntilIdle()
        assertEquals("objectif/statut", api.sent.last().second.route)
        assertEquals("dropped", text("status"))
        assertEquals(ProjectViewModel.goalWhere(2), vm.gestures.finished)
    }

    @Test fun `la liste des tickets - À toi ne redemande rien, Tous relit, chercher attend une pause de frappe`() = runTest {
        api.sheet = MoiApi.Result.Ok(Sheet())
        api.tickets = MoiApi.Result.Ok(EntryPage(total = 2, items = listOf(Entry(number = 1, yours = true), Entry(number = 2))))
        val vm = project()
        vm.resume()
        vm.openTickets()
        advanceUntilIdle()
        assertEquals(listOf("elements:3:open:"), api.calls.filter { it.startsWith("elements") })
        vm.pickTicketFilter(TicketFilters.YOURS)
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it.startsWith("elements") })
        assertEquals(listOf(1), TicketFilters.shown(vm.ticketFilter, vm.tickets?.valueOrNull?.items.orEmpty()).map { it.number })
        vm.pickTicketFilter(TicketFilters.ALL)
        advanceUntilIdle()
        assertEquals("elements:3::", api.calls.last { it.startsWith("elements") })
        vm.search("dé")
        vm.search("délai")
        advanceUntilIdle()
        assertEquals(listOf("elements:3::délai"), api.calls.filter { it.startsWith("elements") }.drop(2))
        // un ticket ouvert d'ici : la liste se relit
        vm.openTicket(TicketForm(title = "Délai réglable", kind = "task", priority = "normal"))
        advanceUntilIdle()
        assertEquals("ticket", api.sent.last().second.route)
        assertEquals(4, api.calls.count { it.startsWith("elements") })
    }

    @Test fun `le diagramme et les comptes rendus se lisent à la demande, une fois`() = runTest {
        api.sheet = MoiApi.Result.Ok(Sheet())
        val vm = project()
        vm.resume()
        advanceUntilIdle()
        assertFalse(api.calls.any { it.startsWith("diagram") || it.startsWith("activity") })
        vm.showDiagram(true)
        vm.showDiagram(false)
        vm.showDiagram(true)
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it == "diagram:3" })
        assertTrue(vm.diagram is Load.Ready)
        vm.fold(2)
        assertEquals(setOf(2), vm.folded)
        vm.fold(2)
        assertTrue(vm.folded.isEmpty())
        vm.loadReports(2)
        vm.loadReports(2)
        advanceUntilIdle()
        assertEquals(listOf("activity:3:run:2:0"), api.calls.filter { it.startsWith("activity") })
        assertTrue(vm.reports[2] is Load.Ready)
    }

    // ── Un ticket ──

    @Test fun `un ticket - trancher nomme le plan lu, une note part et s'efface, un refus garde la note`() = runTest {
        val e = EntryDetail(Entry(list = "tickets", handle = "#4", number = 4, plan = 812, title = "Journaliser les refus", kind = "task", priority = "normal"), EntryMore(body = "Quand…", can = EntryCan(validate = true, note = true, modify = true)))
        api.element = MoiApi.Result.Ok(e)
        val vm = ticket()
        vm.resume()
        advanceUntilIdle()
        assertEquals(e, vm.element.valueOrNull)
        vm.settle("validate")
        advanceUntilIdle()
        assertEquals("ticket/trancher", api.sent.last().second.route)
        assertEquals("812", text("plan"))
        assertEquals(1, vm.revision)
        assertEquals(2, api.calls.count { it == "element:3:tickets:#4" })
        vm.note = "  le port 3389  "
        api.refuse(403, "Tu ne peux pas noter ce ticket : il ne se lit pas d'ici.")
        vm.sendNote()
        advanceUntilIdle()
        assertEquals("Tu ne peux pas noter ce ticket : il ne se lit pas d'ici.", vm.gestures.refusalAt(TicketViewModel.HERE))
        assertEquals("  le port 3389  ", vm.note)
        assertEquals(1, vm.revision)
        api.gestureResult = null
        vm.sendNote()
        advanceUntilIdle()
        assertEquals("element/noter", api.sent.last().second.route)
        assertEquals("le port 3389", text("text"))
        assertEquals("", vm.note)
        assertEquals(2, vm.revision)
        // modifier : seulement ce qui change, par son `#n`
        vm.modify(TicketForm.of(e).copy(priority = "high"))
        advanceUntilIdle()
        assertEquals("ticket/modifier", api.sent.last().second.route)
        assertEquals(setOf("item", "priority"), body().keys)
        assertEquals(TicketViewModel.EDIT, vm.gestures.finished)
    }

    @Test fun `l'historique d'un ticket - son histoire toujours, ce qui l'entoure seulement avec le droit de lire l'activité`() = runTest {
        api.element = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#4", number = 4), EntryMore()))
        val vm = ticket()
        vm.resume()
        vm.loadStory(withActivity = false)
        advanceUntilIdle()
        assertTrue(vm.history is Load.Ready)
        assertTrue("history:3:#4" in api.calls)
        assertFalse(api.calls.any { it.startsWith("activity") })
        vm.loadStory(withActivity = true)
        advanceUntilIdle()
        assertTrue("activity:3::0:4" in api.calls)
    }
}
