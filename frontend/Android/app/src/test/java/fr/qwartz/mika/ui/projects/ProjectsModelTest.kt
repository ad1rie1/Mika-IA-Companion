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
import fr.qwartz.mika.data.moi.projects.LinkChange
import fr.qwartz.mika.data.moi.projects.MilestoneForm
import fr.qwartz.mika.data.moi.projects.NewProject
import fr.qwartz.mika.data.moi.projects.Objective
import fr.qwartz.mika.data.moi.projects.Overview
import fr.qwartz.mika.data.moi.projects.ProjectHead
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.TicketFilters
import fr.qwartz.mika.data.moi.projects.TicketForm
import fr.qwartz.mika.data.moi.projects.TodoPage
import fr.qwartz.mika.data.moi.projects.Waiting
import fr.qwartz.mika.data.moi.projects.linkRequest
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.Dispatchers
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
import fr.qwartz.mika.data.moi.projects.Plan

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
    private val deps = ProjectsDeps(api, { badges++ }, { 1_795_600_000_000L }, Dispatchers.Unconfined)

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
        // un refus relit la fiche lui aussi : il dit le plus souvent que la situation a changé
        assertEquals(3, api.calls.count { it == "sheet:3" })
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

    // ── Une attente rouverte : toujours ce que le serveur dit maintenant ──

    private val projectPlan = waiting(
        """{"project":3,"project_title":"Outils réseau","kind":"plan","mine":true,"can":true,"gesture":{"route":"plan","where":"ici"}}""",
    )

    @Test fun `une attente rouverte montre ce que le serveur dit maintenant - ni l'ancien plan, ni un bouton avant de l'avoir relu`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(projectPlan), todoTotal = 1))
        api.sheet = MoiApi.Result.Ok(Sheet(plan = Plan(state = "proposed", text = "Plan A")))
        val vm = section()
        vm.open(3, "plan")
        advanceUntilIdle()
        assertEquals("Plan A", vm.sheet?.valueOrNull?.plan?.text)
        assertEquals(listOf("approve", "revise"), vm.decision.buttons.map { it.action })
        // une révision demandée : l'attente est décidée, son écran quitté
        vm.decide("revise", "plus court")
        advanceUntilIdle()
        assertEquals(ProjectsViewModel.todoWhere(3, "plan"), vm.gestures.finished)
        vm.leave(3, "plan")
        // elle a réécrit son plan : la même attente revient, sous la même clé
        api.sheet = MoiApi.Result.Ok(Sheet(plan = Plan(state = "proposed", text = "Plan B")))
        api.hold("sheet:3")
        vm.open(3, "plan")
        advanceUntilIdle()
        // tant que le plan d'aujourd'hui n'est pas lu : ni l'ancien plan, ni un bouton, ni le geste abouti d'avant
        assertNull(vm.sheet?.valueOrNull)
        assertTrue(vm.decision.buttons.isEmpty())
        assertNull(vm.gestures.finished)
        val sent = api.sent.size
        vm.decide("approve")
        advanceUntilIdle()
        assertEquals(sent, api.sent.size)
        api.release("sheet:3")
        advanceUntilIdle()
        assertEquals("Plan B", vm.sheet?.valueOrNull?.plan?.text)
        assertEquals(listOf("approve", "revise"), vm.decision.buttons.map { it.action })
    }

    @Test fun `une saisie confirmée pendant une relecture ne part pas - et le modèle le dit, pour que l'écran la garde`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(projectPlan), todoTotal = 1))
        api.sheet = MoiApi.Result.Ok(Sheet(plan = Plan(state = "proposed", text = "Plan A")))
        val vm = section()
        vm.open(3, "plan")
        advanceUntilIdle()
        // l'écran revient devant pendant que la fenêtre « Demander une révision » est ouverte : l'attente se relit
        api.hold("sheet:3")
        vm.open(3, "plan")
        advanceUntilIdle()
        val sent = api.sent.size
        // confirmée à cet instant : rien ne part, et le modèle répond non — l'écran garde la fenêtre et ce qui est tapé
        assertFalse(vm.decide("revise", "plus court"))
        advanceUntilIdle()
        assertEquals(sent, api.sent.size)
        api.release("sheet:3")
        advanceUntilIdle()
        // relue : la même saisie, confirmée de nouveau, part
        assertTrue(vm.decide("revise", "plus court"))
        advanceUntilIdle()
        assertEquals(sent + 1, api.sent.size)
    }

    private val question = waiting(
        """{"project":3,"project_title":"Outils réseau","kind":"ticket","what":"question","number":4,"mine":true,"can":true,
            "gesture":{"route":"element/noter","args":{"list":"tickets","item":"#4"},"where":"ici"}}""",
    )
    private val asked = EntryDetail(Entry(list = "tickets", handle = "#4", number = 4), EntryMore(can = EntryCan(note = true)))

    @Test fun `une attente quittée vers un autre écran puis retrouvée garde ce qu'on y tapait - elle se relit quand même, sans rien offrir d'ici là`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(question, accord), todoTotal = 2))
        api.element = MoiApi.Result.Ok(asked)
        api.approvals = Approvals(listOf(Approval(id = 41, project = 3, text = "Merci.", digest = "d1")))
        val vm = section()
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertTrue(vm.decision.answer)
        vm.answer = "Garde le port 3389."
        // « Ouvrir dans le projet », son fil, son objectif, sa pull request : son écran quitte la pile
        vm.leave(3, "ticket-4")
        // de retour : ce qui était tapé est là ; elle se relit, et rien ne s'offre ni ne part d'ici là
        api.hold("element:3:tickets:#4")
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertEquals("Garde le port 3389.", vm.answer)
        assertTrue(vm.rereading)
        assertFalse(vm.decision.answer)
        assertFalse(vm.decide("answer", vm.answer))
        assertTrue(api.sent.isEmpty())
        api.release("element:3:tickets:#4")
        advanceUntilIdle()
        assertTrue(vm.decision.answer)
        assertEquals("Garde le port 3389.", vm.answer)
        // une autre attente s'ouvre : la saisie de la précédente tombe, et ne revient pas avec elle
        vm.leave(3, "ticket-4")
        vm.open(3, "accord-41")
        advanceUntilIdle()
        assertEquals("", vm.answer)
        vm.leave(3, "accord-41")
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertEquals("", vm.answer)
        // envoyée, la réponse s'efface
        vm.answer = "Garde le port 3389."
        assertTrue(vm.decide("answer", vm.answer))
        advanceUntilIdle()
        assertEquals("Garde le port 3389.", text("text"))
        assertEquals("", vm.answer)
    }

    @Test fun `pendant une relecture le champ de réponse reste posé avec sa saisie - seul Répondre attend`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(question), todoTotal = 1))
        api.element = MoiApi.Result.Ok(asked)
        val vm = section()
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertTrue(vm.answering)
        vm.answer = "Garde le port"
        // l'app revient de l'arrière-plan : elle se relit — le champ ne sort pas de l'écran, ce qui est tapé reste
        api.hold("element:3:tickets:#4")
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertTrue(vm.rereading)
        assertTrue(vm.answering)
        assertEquals("Garde le port", vm.answer)
        // … mais rien ne part sur l'ancienne lecture
        assertFalse(vm.decision.answer)
        assertFalse(vm.decide("answer", vm.answer))
        assertTrue(api.sent.isEmpty())
        api.release("element:3:tickets:#4")
        advanceUntilIdle()
        assertTrue(vm.answering)
        assertTrue(vm.decision.answer)
        // « À faire » illisible au retour : le champ et la saisie restent, rien ne part non plus
        api.overview = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertEquals(MoiError.NETWORK, vm.failure?.message)
        assertTrue(vm.answering)
        assertFalse(vm.decision.answer)
        assertEquals("Garde le port", vm.answer)
        // elle n'attend plus de réponse (répondue ailleurs, son plan est venu) : le champ s'en va
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(question.copy(what = "validation")), todoTotal = 1))
        vm.reread()
        advanceUntilIdle()
        assertFalse(vm.answering)
        // et quand le serveur dit qu'elle n'est plus à faire, ce qu'on y tapait ne ressortira pas avec la suivante
        api.overview = MoiApi.Result.Ok(Overview())
        vm.reread()
        advanceUntilIdle()
        assertTrue(vm.missing)
        assertEquals("", vm.answer)
    }

    @Test fun `une attente quittée avant la réponse de son geste ne se referme pas seule à son retour`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 1))
        api.approvals = Approvals(listOf(Approval(id = 41, project = 3, text = "Merci.", digest = "d1")))
        val vm = section()
        val where = ProjectsViewModel.todoWhere(3, "accord-41")
        vm.open(3, "accord-41")
        advanceUntilIdle()
        api.hold("gesture:accord")
        assertTrue(vm.decide("accept"))
        // son écran est quitté avant la réponse
        vm.leave(3, "accord-41")
        api.release("gesture:accord")
        advanceUntilIdle()
        assertEquals(1, api.sent.size)
        // abouti, mais personne n'est là pour la refermer : rien ne reste qui la refermerait quand on la retrouve
        assertNull(vm.gestures.finished)
        // devant son écran, le geste abouti se dit : c'est lui qui la referme
        vm.open(3, "accord-41")
        advanceUntilIdle()
        assertTrue(vm.decide("refuse"))
        advanceUntilIdle()
        assertEquals(where, vm.gestures.finished)
        // quittée sans que son écran ait eu le temps de le suivre : il ne la refermera pas à son retour
        vm.leave(3, "accord-41")
        assertNull(vm.gestures.finished)
    }

    @Test fun `le retour sur l'écran relit l'attente - l'ancienne lecture reste lisible, sans ses boutons`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 1))
        api.approvals = Approvals(listOf(Approval(id = 41, project = 3, text = "Merci.", digest = "d1")))
        val vm = section()
        vm.open(3, "accord-41")
        advanceUntilIdle()
        assertEquals(2, vm.decision.buttons.size)
        // l'app revient de l'arrière-plan : elle a retouché sa réponse entre-temps
        api.approvals = Approvals(listOf(Approval(id = 41, project = 3, text = "Merci, c'est corrigé.", digest = "d2")))
        api.hold("approvals:3")
        vm.open(3, "accord-41")
        advanceUntilIdle()
        assertTrue(vm.rereading)
        assertEquals("Merci.", vm.approval?.text)
        assertTrue(vm.decision.buttons.isEmpty())
        vm.decide("accept")
        advanceUntilIdle()
        assertTrue(api.sent.isEmpty())
        api.release("approvals:3")
        advanceUntilIdle()
        assertFalse(vm.rereading)
        vm.decide("accept")
        advanceUntilIdle()
        assertEquals("d2", text("seen"))
    }

    @Test fun `un refus du serveur relit l'attente, ses mots restent dits`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 1))
        api.approvals = Approvals(listOf(Approval(id = 41, project = 3, text = "Merci.", digest = "d1")))
        val vm = section()
        vm.open(3, "accord-41")
        advanceUntilIdle()
        // sa réponse a changé depuis la lecture : le serveur refuse le condensé d'avant
        api.approvals = Approvals(listOf(Approval(id = 41, project = 3, text = "Merci, c'est corrigé.", digest = "d2")))
        api.refuse(409, "Ce qui partirait a changé : relis, puis décide.")
        vm.decide("accept")
        advanceUntilIdle()
        assertEquals("d1", text("seen"))
        assertEquals("Ce qui partirait a changé : relis, puis décide.", vm.gestures.refusalAt(ProjectsViewModel.todoWhere(3, "accord-41")))
        assertEquals("Merci, c'est corrigé.", vm.approval?.text)
        assertEquals(2, api.calls.count { it == "approvals:3" })
        api.gestureResult = null
        vm.decide("accept")
        advanceUntilIdle()
        assertEquals("d2", text("seen"))
    }

    @Test fun `une panne n'est pas une absence - son erreur se dit, réessayer relit, et seul le serveur dit qu'elle n'est plus à faire`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(accord), todoTotal = 40))
        api.sheet = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        val vm = section()
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertFalse(vm.missing)
        assertEquals(MoiError.NETWORK, vm.failure?.message)
        // le réseau revient
        api.sheet = MoiApi.Result.Ok(Sheet(todo = listOf(ticketPlan)))
        api.element = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#4", number = 4, plan = 812), EntryMore(can = EntryCan(validate = true))))
        vm.reread()
        advanceUntilIdle()
        assertNull(vm.failure)
        assertEquals(ticketPlan, vm.shown)
        assertEquals(1, vm.decision.buttons.size)
        // « À faire » illisible au retour sur l'écran : ce qu'on montrait reste, sans ses boutons, et on le dit
        api.overview = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.open(3, "ticket-4")
        advanceUntilIdle()
        assertEquals(ticketPlan, vm.shown)
        assertEquals(MoiError.NETWORK, vm.failure?.message)
        assertTrue(vm.decision.buttons.isEmpty())
        // et seulement quand le serveur le dit, elle n'est plus à faire
        api.overview = MoiApi.Result.Ok(Overview())
        api.sheet = MoiApi.Result.Ok(Sheet())
        vm.reread()
        advanceUntilIdle()
        assertTrue(vm.missing)
        assertNull(vm.shown)
        assertNull(vm.failure)
    }

    @Test fun `la suite d'À faire compte ses pages - une ligne déjà connue écartée ne fait pas revenir la même page`() = runTest {
        api.overview = MoiApi.Result.Ok(Overview(todo = (1..25).map { ticketPlan.copy(number = it) }, todoTotal = 60))
        // la page 2 redit une ligne de la première (une attente décidée entre-temps a décalé la liste)
        api.pages[2] = TodoPage(total = 60, page = 2, size = 25, items = (25..49).map { ticketPlan.copy(number = it) })
        api.pages[3] = TodoPage(total = 60, page = 3, size = 25, items = (50..59).map { ticketPlan.copy(number = it) })
        val vm = section()
        vm.resume()
        advanceUntilIdle()
        vm.more()
        advanceUntilIdle()
        assertEquals(49, vm.todo.size)
        vm.more()
        advanceUntilIdle()
        assertEquals(listOf("todo:2", "todo:3"), api.calls.filter { it.startsWith("todo:") })
        assertEquals(59, vm.todo.size)
        // la dernière page n'était pas pleine : il n'y a plus de suite, même si le compte n'y est pas
        assertEquals(0, vm.todoRest)
        vm.more()
        advanceUntilIdle()
        assertEquals(2, api.calls.count { it.startsWith("todo:") })
        // la première page relue rejoint ce qu'on avait : la suite chargée reste. Le serveur en compte une de plus que
        // ce qu'on tient : la page entamée se redemande, une fois — et ne rend rien de neuf
        vm.resume()
        advanceUntilIdle()
        assertEquals(59, vm.todo.size)
        assertEquals(1, vm.todoRest)
        vm.more()
        advanceUntilIdle()
        assertEquals(listOf("todo:2", "todo:3", "todo:3"), api.calls.filter { it.startsWith("todo:") })
        assertEquals(59, vm.todo.size)
        assertEquals(0, vm.todoRest)
        // une première page qui ne rejoint plus rien de ce qu'on avait : la suite repart d'elle
        api.overview = MoiApi.Result.Ok(Overview(todo = (100..124).map { ticketPlan.copy(number = it) }, todoTotal = 60))
        vm.resume()
        advanceUntilIdle()
        assertEquals(25, vm.todo.size)
        assertEquals(35, vm.todoRest)
        vm.more()
        advanceUntilIdle()
        assertEquals("todo:2", api.calls.last { it.startsWith("todo:") })
    }

    @Test fun `la suite chargée d'À faire reste quand une attente s'ouvre - décidée, elle quitte la liste et la page entamée se redemande`() = runTest {
        val first = (1..25).map { ticketPlan.copy(number = it) }
        api.overview = MoiApi.Result.Ok(Overview(todo = first, todoTotal = 51))
        api.pages[2] = TodoPage(total = 51, page = 2, size = 25, items = (26..50).map { ticketPlan.copy(number = it) })
        val vm = section()
        vm.resume()
        advanceUntilIdle()
        vm.more()
        advanceUntilIdle()
        assertEquals(50, vm.todo.size)
        // une attente de la suite s'ouvre : « À faire » se relit pour elle, la suite chargée reste dans la liste
        api.sheet = MoiApi.Result.Ok(Sheet(todo = listOf(ticketPlan.copy(number = 30))))
        api.element = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#4", number = 30, plan = 812), EntryMore(can = EntryCan(validate = true))))
        vm.open(3, "ticket-30")
        advanceUntilIdle()
        assertEquals(50, vm.todo.size)
        assertEquals(1, vm.todoRest)
        // elle n'est pas lue dans la suite gardée, qui date d'avant : sa fiche dit ce qu'elle est maintenant
        assertTrue("sheet:3" in api.calls)
        assertEquals(1, vm.decision.buttons.size)
        // décidée : elle quitte la liste, le reste de la suite est gardé
        api.overview = MoiApi.Result.Ok(Overview(todo = first, todoTotal = 50))
        api.sheet = MoiApi.Result.Ok(Sheet())
        assertTrue(vm.decide("validate"))
        advanceUntilIdle()
        vm.leave(3, "ticket-30")
        assertEquals(49, vm.todo.size)
        assertTrue(vm.todo.none { it.number == 30 })
        // les suivantes ont remonté d'un rang : la page entamée se redemande — celle d'après aurait sauté une attente
        api.pages[2] = TodoPage(total = 50, page = 2, size = 25, items = ((26..29) + (31..51)).map { ticketPlan.copy(number = it) })
        vm.more()
        advanceUntilIdle()
        assertEquals("todo:2", api.calls.last { it.startsWith("todo:") })
        assertEquals(50, vm.todo.size)
        assertTrue(vm.todo.any { it.number == 51 })
        assertEquals(0, vm.todoRest)
        // le retour sur la liste la relit en place ; tirer relit tout : la suite repart de la première page
        vm.resume()
        advanceUntilIdle()
        assertEquals(50, vm.todo.size)
        vm.pull()
        advanceUntilIdle()
        assertEquals(25, vm.todo.size)
        assertEquals(25, vm.todoRest)
        // la page relue est tout ce que le serveur compte encore : rien de la suite chargée ne reste
        vm.more()
        advanceUntilIdle()
        assertEquals(50, vm.todo.size)
        api.overview = MoiApi.Result.Ok(Overview(todo = first.take(10), todoTotal = 10))
        vm.resume()
        advanceUntilIdle()
        assertEquals(10, vm.todo.size)
        assertEquals(0, vm.todoRest)
    }

    // ── Le socle : un geste abouti d'avant, une fiche d'avant ──

    @Test fun `un geste qui part efface le geste abouti d'avant - retirer ne ramène pas en arrière avant la réponse`() = runTest {
        val vm = project()
        vm.resume()
        advanceUntilIdle()
        val where = ProjectViewModel.goalWhere(2)
        vm.checkpoint(2, 7, "validate")
        advanceUntilIdle()
        assertEquals(where, vm.gestures.finished)
        // « Retirer » part du même endroit : tant que le serveur n'a pas répondu, rien n'a abouti
        api.hold("gesture:objectif/statut")
        assertTrue(vm.goalStatus(Goal.Once(Objective(id = 2)), "dropped"))
        advanceUntilIdle()
        assertNull(vm.gestures.finished)
        // un second geste pendant le premier ne part pas : l'écran n'a rien à attendre de lui
        assertFalse(vm.goalStatus(Goal.Once(Objective(id = 2)), "done"))
        api.refuse(409, "Un objectif en cours ne se retire pas.")
        api.release("gesture:objectif/statut")
        advanceUntilIdle()
        assertNull(vm.gestures.finished)
        assertEquals("Un objectif en cours ne se retire pas.", vm.gestures.refusalAt(where))
        // l'écran, la feuille qui se rouvrent oublient ce qu'on y avait dit
        vm.gestures.forget(where)
        assertEquals("", vm.gestures.refusalAt(where))
    }

    @Test fun `aucun geste de la fiche ne part pendant sa relecture - ni d'une fenêtre restée ouverte, ni sur un lien - et chacun repart après`() = runTest {
        val o = Objective(id = 2, text = "Créer un module RDP", status = "open")
        api.sheet = MoiApi.Result.Ok(Sheet(objectives = listOf(o)))
        val vm = project()
        vm.resume()
        advanceUntilIdle()
        // tous les gestes de la fiche, comme une fenêtre ou une feuille restée ouverte les enverrait
        val gestures: List<Pair<String, () -> Boolean>> = listOf(
            "piloter" to { vm.pilot("instruct", "Reste sur IPv4.") },
            "objectif/statut" to { vm.goalStatus(Goal.Once(o), "done") },
            "objectif" to { vm.saveGoal(GoalForm(text = "Écrire la documentation")) },
            "jalon/ajouter" to { vm.saveMilestone(2, MilestoneForm(text = "La connexion aboutit")) },
            "jalon/retirer" to { vm.dropMilestone(2, 7, "inutile") },
            "jalon" to { vm.checkpoint(2, 7, "validate") },
            "ticket" to { vm.openTicket(TicketForm(title = "Délai réglable", kind = "task", priority = "normal")) },
            "liens" to { vm.link(linkRequest(LinkChange.REMOVE, 9), "link-remove") },
        )
        // l'écran revient devant (une rotation, l'arrière-plan) : la fiche se relit
        api.hold("sheet:3")
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.stale)
        for ((name, send) in gestures) assertFalse(name, send())
        advanceUntilIdle()
        assertTrue(api.sent.isEmpty())
        assertEquals("", vm.gestures.busy)
        // relue : chacun part
        api.release("sheet:3")
        advanceUntilIdle()
        assertFalse(vm.stale)
        for ((name, send) in gestures) {
            assertTrue(name, send())
            advanceUntilIdle()
        }
        assertEquals(gestures.size, api.sent.size)
        // sa relecture en panne : rien ne part non plus, et une feuille ouverte dit pourquoi
        api.sheet = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.stale)
        for ((name, send) in gestures) assertFalse(name, send())
        assertEquals(gestures.size, api.sent.size)
        assertEquals(MoiError.NETWORK, vm.saidAt(ProjectViewModel.GOAL_NEW))
    }

    @Test fun `un ticket et une fiche rouverts - rien ne s'y décide avant leur relecture, un refus les relit, une panne se dit`() = runTest {
        val read = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#4", number = 4, plan = 812), EntryMore(can = EntryCan(validate = true, note = true))))
        api.element = read
        val t = ticket()
        t.resume()
        advanceUntilIdle()
        assertFalse(t.stale)
        // l'écran revient devant : ce qu'il montre date d'avant, jusqu'à sa relecture
        api.hold("element:3:tickets:#4")
        t.resume()
        advanceUntilIdle()
        assertTrue(t.stale)
        t.settle("refuse", "trop large")
        t.note = "Le port 3389."
        t.sendNote()
        advanceUntilIdle()
        assertTrue(api.sent.isEmpty())
        api.release("element:3:tickets:#4")
        advanceUntilIdle()
        assertFalse(t.stale)
        // sa relecture échoue : il reste d'avant, on le dit, « Réessayer » relit
        api.element = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        t.resume()
        advanceUntilIdle()
        assertTrue(t.stale)
        assertEquals(MoiError.NETWORK, t.staleError?.message)
        api.element = read
        t.reread()
        advanceUntilIdle()
        assertFalse(t.stale)
        assertNull(t.staleError)
        // un refus relit : il dit le plus souvent que la situation a changé
        val reads = api.calls.count { it == "element:3:tickets:#4" }
        api.refuse(409, "Son plan a été réécrit depuis : relis-le, puis valide.")
        t.settle("validate")
        advanceUntilIdle()
        assertEquals(reads + 1, api.calls.count { it == "element:3:tickets:#4" })
        // la fiche d'un projet : de même
        val p = project()
        p.resume()
        advanceUntilIdle()
        assertFalse(p.stale)
        api.hold("sheet:3")
        p.resume()
        advanceUntilIdle()
        assertTrue(p.stale)
        api.release("sheet:3")
        advanceUntilIdle()
        assertFalse(p.stale)
        val sheets = api.calls.count { it == "sheet:3" }
        p.checkpoint(2, 7, "validate")
        advanceUntilIdle()
        assertEquals(sheets + 1, api.calls.count { it == "sheet:3" })
        api.sheet = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        p.resume()
        advanceUntilIdle()
        assertTrue(p.stale)
        assertEquals(MoiError.NETWORK, p.staleError?.message)
    }
}
