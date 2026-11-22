package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

/**
 * Les règles pures de l'écran Projets : un geste traduit en requête (la route et le corps que chaque bouton envoie), les
 * boutons d'une attente — ceux que le serveur ouvre, rien d'autre —, les couleurs d'état, ce que l'écran range (« À
 * faire » par projet, les objectifs en trois groupes, les onglets d'une fiche), le parcours et l'histoire d'un ticket,
 * le diagramme en mode « Avancement », et les mots d'un instant.
 */
class ProjectsRulesTest {
    private val paris = ZoneId.of("Europe/Paris")

    private fun waiting(json: String): Waiting = MikaJson.decodeFromString(Waiting.serializer(), json)

    private fun JsonObject.text(name: String): String? = (this[name] as? JsonPrimitive)?.content

    private val ticketPlan = waiting(
        """{"project":3,"project_title":"Outils réseau","kind":"ticket","kind_label":"ticket","what":"validation",
            "about":"#4 Journaliser les refus — son plan attend ta validation","since":1790790000000,"mine":true,"can":true,
            "number":4,"gesture":{"route":"ticket/trancher","args":{"item":"#4","verdict":"validate","plan":812},
            "label":"Valider ou refuser son plan","where":"ici","url":""}}""",
    )
    private val accord = waiting(
        """{"project":3,"kind":"approval","what":"repo.issue.comment","mine":true,"can":true,"number":0,
            "gesture":{"route":"accord","args":{"proposal":41},"label":"Donner ton accord","where":"ici"}}""",
    )
    private val merge = waiting(
        """{"project":3,"kind":"ticket","what":"merge","mine":true,"can":true,"number":2,
            "gesture":{"route":"code/pull/fusionner","args":{"number":12},"label":"Fusionner","where":"ici","url":"https://hote.example/pull/12"}}""",
    )

    private fun entry(line: Entry = Entry(list = "tickets", handle = "#4", number = 4, plan = 812, open = true), more: EntryMore = EntryMore()) = EntryDetail(line, more)

    // ── Un geste devient une requête ──

    @Test fun `un accord accepté renvoie le condensé lu, refusé il n'en porte pas`() {
        val yes = gestureRequest(accord, "accept", digest = "abc123")
        assertEquals("accord", yes.route)
        assertEquals("41", yes.body.text("proposal"))
        assertEquals("accept", yes.body.text("decision"))
        assertEquals("abc123", yes.body.text("seen"))
        val no = gestureRequest(accord, "refuse", typed = "  pas maintenant ")
        assertNull(no.body["seen"])
        assertEquals("pas maintenant", no.body.text("note"))
    }

    @Test fun `valider le plan d'un ticket nomme le plan lu, pas celui que la liste portait`() {
        val shown = gestureRequest(ticketPlan, "validate", plan = 815)
        assertEquals("ticket/trancher", shown.route)
        assertEquals("#4", shown.body.text("item"))
        assertEquals("815", shown.body.text("plan"))
        // sans élément lu, celui du geste servi ; un refus ne nomme aucun plan et porte sa raison
        assertEquals("812", gestureRequest(ticketPlan, "validate").body.text("plan"))
        val refused = gestureRequest(ticketPlan, "refuse", "trop large")
        assertNull(refused.body["plan"])
        assertEquals("trop large", refused.body.text("reason"))
    }

    @Test fun `le plan d'un projet, un point d'arrêt, un statut - chacun complète le geste servi`() {
        val plan = waiting("""{"project":5,"kind":"plan","mine":true,"can":true,"gesture":{"route":"plan","args":{},"where":"ici"}}""")
        assertEquals(mapOf("verdict" to "revise", "words" to "plus court"), gestureRequest(plan, "revise", "plus court").body.mapValues { it.value.jsonPrimitive.content })
        assertEquals(setOf("verdict"), gestureRequest(plan, "approve").body.keys)
        val stop = waiting("""{"project":3,"kind":"checkpoint","objective":2,"mine":true,"can":true,"gesture":{"route":"jalon","args":{"objective":2,"milestone":7},"where":"ici"}}""")
        val refused = gestureRequest(stop, "refuse", "le champ domaine doit rester")
        assertEquals("7", refused.body.text("milestone"))
        assertEquals("refuse", refused.body.text("verdict"))
        assertEquals("le champ domaine doit rester", refused.body.text("reason"))
        val item = waiting("""{"project":8,"kind":"item","what":"entreprises","key":"acme","mine":true,"can":true,"gesture":{"route":"element/statut","args":{"list":"entreprises","item":"acme"},"where":"ici"}}""")
        assertEquals("contacte", gestureRequest(item, "contacte").body.text("status"))
    }

    @Test fun `depuis À faire - une réponse est une note, un verdict passe toujours par trancher`() {
        val question = ticketPlan.copy(what = "question", gesture = ticketPlan.gesture.copy(args = JsonObject(mapOf("item" to JsonPrimitive("#4")))))
        val e = entry()
        val answer = todoRequest(question, "answer", " le port 3389 ", e, null)
        assertEquals("element/noter", answer.route)
        assertEquals("le port 3389", answer.body.text("text"))
        assertEquals("#4", answer.body.text("item"))
        // une pull request prête : écarter son ticket ne demande pas une fusion
        val dismissed = todoRequest(merge, "dismiss", "doublon", entry(Entry(list = "tickets", handle = "#2", number = 2)), null)
        assertEquals("ticket/trancher", dismissed.route)
        assertEquals("#2", dismissed.body.text("item"))
        assertEquals("dismiss", dismissed.body.text("verdict"))
        // un geste que le serveur nomme lui-même part avec ses arguments, sans action de l'écran
        val need = waiting("""{"project":3,"kind":"need","objective":2,"mine":true,"can":true,"gesture":{"route":"piloter","args":{"what":"instruct","objective":2},"where":"ici"}}""")
        val go = todoRequest(need, "go", "prends le port par défaut", null, null)
        assertEquals("instruct", go.body.text("what"))
        assertEquals("prends le port par défaut", go.body.text("text"))
    }

    @Test fun `les gestes de la fiche - piloter, trancher, noter, un jalon`() {
        assertEquals(setOf("what"), pilotRequest("pause").body.keys)
        assertEquals("2", pilotRequest("now", objective = 2).body.text("objective"))
        assertEquals("va au plus simple", pilotRequest("instruct", " va au plus simple ").body.text("text"))
        val e = Entry(list = "tickets", handle = "#4", number = 4, plan = 812)
        assertEquals("812", settleRequest(e, "validate").body.text("plan"))
        assertNull(settleRequest(e, "accept").body["plan"])
        assertEquals(setOf("item", "verdict"), settleRequest(e, "done").body.keys)
        assertEquals(mapOf("list" to "tickets", "item" to "#4", "text" to "vu"), noteRequest(e, "vu").body.mapValues { it.value.jsonPrimitive.content })
        assertEquals("acme", noteRequest(Entry(list = "entreprises", key = "acme"), "x").body.text("item"))
        assertEquals("objectif/statut", objectiveStatusRequest(2, "dropped").route)
        assertEquals(setOf("objective", "milestone"), milestoneDropRequest(2, 7).body.keys)
        assertEquals("validate", checkpointRequest(2, 7, "validate").body.text("verdict"))
    }

    @Test fun `un objectif - ajouté il dit sa sorte, modifié il n'envoie que ce qui change`() {
        val once = goalRequest(GoalForm(text = " Créer un module RDP ", doneWhen = "La connexion aboutit"))
        assertEquals("objectif", once.route)
        assertEquals("once", once.body.text("kind"))
        assertEquals("Créer un module RDP", once.body.text("text"))
        assertNull(once.body["cadence_hours"])
        val mission = goalRequest(GoalForm(mission = true, text = "Traiter les tickets", cadenceHours = 24, on = listOf("item:tickets"), eachPass = "relire"))
        assertEquals("constant", mission.body.text("kind"))
        assertEquals("24", mission.body.text("cadence_hours"))
        assertEquals(listOf("item:tickets"), mission.body["on"]!!.jsonArray.map { it.jsonPrimitive.content })
        assertEquals("true", mission.body.text("at_once"))
        assertNull(mission.body["done_when"])
        // modifié : la mission reste une mission, et seule sa cadence part
        val before = GoalForm(mission = true, text = "Traiter les tickets", cadenceHours = 24, on = listOf("item:tickets"), eachPass = "relire")
        val edit = goalRequest(before.copy(cadenceHours = 12, mission = false), before, objective = 5)
        assertEquals("objectif/modifier", edit.route)
        assertEquals(setOf("objective", "cadence_hours"), edit.body.keys)
        // un texte vidé part vide : il efface
        val cleared = goalRequest(GoalForm(text = "Écrire la doc", doneWhen = ""), GoalForm(text = "Écrire la doc", doneWhen = "Les pages existent"), objective = 3)
        assertEquals("", cleared.body.text("done_when"))
    }

    @Test fun `un jalon et un ticket - ajoutés entiers, modifiés par ce qui change`() {
        val added = milestoneRequest(2, MilestoneForm(text = "Les tests passent", check = "command", command = " pytest -q "))
        assertEquals("jalon/ajouter", added.route)
        assertEquals("pytest -q", added.body.text("command"))
        assertNull(added.body["item"])
        val before = MilestoneForm(text = "Les tests passent", check = "command", command = "pytest -q")
        val edited = milestoneRequest(2, before.copy(command = "pytest -q -k rdp", reason = "plus ciblé"), before, milestone = 7)
        assertEquals("jalon/modifier", edited.route)
        assertEquals(setOf("objective", "milestone", "command", "reason"), edited.body.keys)
        val ticket = ticketRequest(TicketForm(title = " Délai réglable ", text = "", kind = "task", priority = "normal"))
        assertEquals("ticket", ticket.route)
        assertEquals(setOf("title", "kind", "priority"), ticket.body.keys)
        val was = TicketForm("Délai réglable", "Sur le Wi-Fi…", "task", "normal")
        val changed = ticketRequest(was.copy(priority = "high"), was, "#5")
        assertEquals("ticket/modifier", changed.route)
        assertEquals(setOf("item", "priority"), changed.body.keys)
    }

    @Test fun `nouveau projet - ce qui est saisi par le nom des champs servis, sans le vide ni le caché`() {
        val fields = listOf(
            Field(name = "title", kind = "text", required = true),
            Field(name = "request", kind = "textarea"),
            Field(name = "schedule", kind = "select", value = "auto"),
            Field(name = "schedule_rule", kind = "text", only = listOf(OnlyWhen("schedule", listOf("custom")))),
            Field(name = "at_once", kind = "bool", value = "false"),
        )
        val body = newProjectBody(fields, mapOf("title" to " Inventaire ", "schedule_rule" to "0 8 * * *", "at_once" to "true"))
        assertEquals(setOf("title", "schedule", "at_once"), body.keys)
        assertEquals("Inventaire", body.text("title"))
        assertTrue(fieldShown(fields[3], fields, mapOf("schedule" to "custom")))
        assertFalse(fieldShown(fields[3], fields, emptyMap()))
    }

    // ── Les boutons d'une attente ──

    @Test fun `pas de bouton sans le droit servi - ni can, ni mine, ni ailleurs qu'ici`() {
        val e = entry(more = EntryMore(planText = "1. …", can = EntryCan(validate = true, refuse = true)))
        assertEquals(listOf(Verb.TICKET_VALIDATE, Verb.TICKET_REFUSE), todoDecision(ticketPlan, null, null, e).buttons.map { it.verb })
        assertTrue(todoDecision(ticketPlan.copy(can = false, why = "Ce n'est pas à toi de trancher."), null, null, e).buttons.isEmpty())
        assertTrue(todoDecision(ticketPlan.copy(mine = false), null, null, e).buttons.isEmpty())
        assertEquals(GesturePlace.DENIED, gesturePlace(ticketPlan.copy(can = false)))
        assertEquals(GesturePlace.THEIRS, gesturePlace(ticketPlan.copy(mine = false)))
        assertEquals(GesturePlace.HOST, gesturePlace(merge.copy(gesture = merge.gesture.copy(where = "hote"))))
        assertEquals(GesturePlace.CONSOLE, gesturePlace(ticketPlan.copy(gesture = Gesture(where = "console", label = "Dans la console"))))
        // ce que `can` de l'élément n'ouvre pas ne paraît pas, même si l'attente se règle ici
        assertTrue(todoDecision(ticketPlan, null, null, entry()).buttons.isEmpty())
        // un élément qui ne se lit pas : aucun geste
        assertTrue(todoDecision(ticketPlan, null, null, entry(Entry(list = "tickets", veiled = "level"), EntryMore(can = EntryCan(validate = true)))).buttons.isEmpty())
    }

    @Test fun `un accord, une question, un ticket proposé, une pull request prête`() {
        assertTrue(todoDecision(accord, null, null, null).buttons.isEmpty())
        val ready = todoDecision(accord, Approval(id = 41, digest = "abc"), null, null).buttons
        assertEquals(listOf("accept", "refuse"), ready.map { it.action })
        assertTrue(ready.first().enabled)
        // ce qui partirait ne peut pas partir tel quel : « Accorder » s'éteint, la raison est dite à côté
        assertFalse(todoDecision(accord, Approval(id = 41, blocked = "Il reste un passage à compléter."), null, null).buttons.first().enabled)
        val question = ticketPlan.copy(what = "question")
        val asked = todoDecision(question, null, null, entry(more = EntryMore(can = EntryCan(note = true, dismiss = true))))
        assertTrue(asked.answer)
        assertEquals(listOf(false), asked.buttons.map { it.primary })
        val proposed = todoDecision(ticketPlan.copy(what = "accept"), null, null, entry(more = EntryMore(can = EntryCan(accept = true, dismiss = true, dismissNeedsReason = true)))).buttons
        assertEquals(listOf(Verb.TICKET_ACCEPT, Verb.TICKET_DISMISS), proposed.map { it.verb })
        assertEquals(AskFor.WHY, proposed.last().ask)
        assertTrue(proposed.last().ask.required)
        assertFalse(AskFor.WHY_OPTIONAL.required)
        // une pull request prête : sa fusion n'a pas son bouton ici, son ticket se lit, et s'écarte encore
        assertEquals(GestureRead.Element("tickets", "#2"), gestureRead(merge))
        assertTrue(isMerge(merge))
        val onMerge = todoDecision(merge, null, null, entry(more = EntryMore(can = EntryCan(dismiss = true)))).buttons
        assertEquals(listOf(Verb.TICKET_DISMISS), onMerge.map { it.verb })
        assertFalse(onMerge.single().primary)
        assertTrue(todoDecision(merge.copy(number = 0), null, null, null).buttons.isEmpty())
    }

    @Test fun `piloter - seule une consigne se saisit, une reprise part telle quelle`() {
        // le serveur ne lit un texte qu'avec `what: instruct` : une reprise (un projet qui n'avance plus) ne demande rien
        val need = waiting("""{"project":3,"kind":"need","objective":2,"mine":true,"can":true,"gesture":{"route":"piloter","args":{"what":"instruct"},"label":"Lui répondre","where":"ici"}}""")
        val stalled = waiting("""{"project":3,"kind":"stalled","mine":true,"can":true,"gesture":{"route":"piloter","args":{"what":"resume"},"label":"Reprendre","where":"ici"}}""")
        assertTrue(gestureTyped(need))
        assertFalse(gestureTyped(stalled))
        assertEquals(AskFor.REPLY, todoDecision(need, null, null, null).buttons.single().ask)
        val resume = todoDecision(stalled, null, null, null).buttons.single()
        assertEquals(AskFor.NOTHING, resume.ask)
        assertEquals("Reprendre", resume.label)
        // et rien ne part en plus de ce que le serveur a dit du geste
        assertEquals(setOf("what"), gestureRequest(stalled, "", "").body.keys)
        assertEquals("piloter", gestureRequest(stalled, "", "").route)
    }

    @Test fun `un point d'arrêt - aucun bouton tant que son jalon n'est pas lu`() {
        val stop = waiting("""{"project":3,"kind":"checkpoint","objective":2,"mine":true,"can":true,"gesture":{"route":"jalon","args":{"objective":2,"milestone":7},"where":"ici"}}""")
        // la fiche pas encore lue, ou sa lecture en échec : on ne valide pas une preuve qu'on n'a pas sous les yeux
        assertTrue(todoDecision(stop, null, null, null).buttons.isEmpty())
        // lue, mais le jalon n'y est plus (retiré, un autre objectif)
        assertTrue(todoDecision(stop, null, Sheet(objectives = listOf(Objective(id = 2, milestones = listOf(Milestone(id = 8))))), null).buttons.isEmpty())
        assertTrue(todoDecision(stop, null, Sheet(objectives = listOf(Objective(id = 5, milestones = listOf(Milestone(id = 7))))), null).buttons.isEmpty())
        val read = Sheet(objectives = listOf(Objective(id = 2, milestones = listOf(Milestone(id = 7, text = "Le domaine reste")))))
        assertEquals(listOf(Verb.CHECKPOINT_VALIDATE, Verb.CHECKPOINT_REFUSE), todoDecision(stop, null, read, null).buttons.map { it.verb })
        assertEquals("Le domaine reste", checkpointRead(read, GestureRead.Checkpoint(2, 7))?.text)
        // le plan d'un projet : de même, rien avant de l'avoir lu
        val plan = waiting("""{"project":3,"kind":"plan","mine":true,"can":true,"gesture":{"route":"plan","where":"ici"}}""")
        assertTrue(todoDecision(plan, null, Sheet(), null).buttons.isEmpty())
        assertEquals(2, todoDecision(plan, null, Sheet(plan = Plan(text = "1. …")), null).buttons.size)
    }

    @Test fun `une note venue d'ailleurs ne se rend jamais en Markdown`() {
        assertTrue(noteRendered(ThreadNote(kind = "question", text = "**Quel** port ?")))
        assertFalse(noteRendered(ThreadNote(kind = "question", text = "[clique](https://exemple.invalid)", outside = true)))
    }

    @Test fun `ce qu'un geste demande de lire, et la clé d'une attente`() {
        assertEquals(GestureRead.Accord(41), gestureRead(accord))
        assertEquals(GestureRead.Element("tickets", "#4"), gestureRead(ticketPlan))
        assertEquals("accord-41", waitingKey(accord))
        assertEquals("ticket-4", waitingKey(ticketPlan))
        assertEquals("pr-12", waitingKey(merge))
        assertEquals("plan", waitingKey(Waiting(kind = "plan")))
        assertEquals("jalon-2-7", waitingKey(waiting("""{"kind":"checkpoint","objective":2,"gesture":{"route":"jalon","args":{"objective":2,"milestone":7}}}""")))
        assertEquals("element-entreprises-acme", waitingKey(Waiting(kind = "item", what = "entreprises", key = "acme")))
        assertEquals("besoin-2", waitingKey(Waiting(kind = "need", objective = 2)))
        assertEquals("blocked-3", waitingKey(Waiting(kind = "blocked", objective = 3)))
    }

    // ── Les couleurs, les mots ──

    @Test fun `les couleurs d'état sont les mêmes partout`() {
        assertEquals(StateTone.YOU, ticketTone("validation", open = true, yours = true))
        assertEquals(StateTone.WORK, ticketTone("working", open = true, yours = false))
        assertEquals(StateTone.WAIT, ticketTone("proposed", open = true, yours = false))
        assertEquals(StateTone.DONE, ticketTone("treated", open = false, yours = false))
        assertEquals(StateTone.WAIT, ticketTone("dismissed", open = false, yours = false))
        assertEquals(StateTone.YOU, milestoneTone(Milestone(status = "open", ready = true)))
        assertEquals(StateTone.FAIL, milestoneTone(Milestone(status = "open", refusedAt = 5)))
        assertEquals(StateTone.WORK, milestoneTone(Milestone(status = "open", started = true)))
        assertEquals(StateTone.WAIT, milestoneTone(Milestone(status = "dropped", ready = true)))
        assertEquals(StateTone.FAIL, objectiveTone("blocked"))
        assertEquals(StateTone.DONE, pullTone("merged"))
        assertEquals(StateTone.FAIL, checksTone("failed"))
        assertEquals(StateTone.YOU, verdictTone("wait"))
        assertEquals("merge", waitingIcon("ticket", "merge"))
        assertEquals("stop", waitingIcon("checkpoint"))
        assertEquals("alert", waitingIcon("stalled"))
    }

    @Test fun `depuis quand, pour qui, un refus en mots, un lien sûr`() {
        val now = 1_795_600_000_000L // le 25 novembre 2026, 10 h 46 à Paris
        assertEquals("à l'instant", since(now - 20_000, now, paris))
        assertEquals("il y a 6 min", since(now - 6 * 60_000, now, paris))
        assertEquals("6 min", age(now - 6 * 60_000, now, paris))
        assertEquals("", since(0, now, paris))
        assertEquals("hier", since(now - 26 * 3_600_000L, now, paris))
        assertTrue(Regex("\\d+ [a-zéû.]+").matches(since(now - 30 * 86_400_000L, now, paris)))
        assertTrue(moment(now - 3 * 3_600_000L, now, paris).contains(" à "))
        assertEquals("à toi", forWhom(ProjectHead(mine = true)))
        assertEquals("à Mika · tu t'en occupes", forWhom(ProjectHead(mine = true, hers = true)))
        assertEquals("d'Adrien", forWhom(ProjectHead(ownerName = "Adrien")))
        assertEquals("à toi · menée par Mika", whose(ProjectHead(mine = true), "Mika"))
        assertEquals("Une raison est exigée. reason : 2 caractères au moins", refusalWords("Une raison est exigée.", mapOf("reason" to "reason : 2 caractères au moins")))
        assertEquals("Déjà tranché.", refusalWords("Déjà tranché.", mapOf("item" to "Déjà tranché.")))
        assertEquals("https://hote.example/pull/12", safeLink("https://hote.example/pull/12"))
        assertEquals("", safeLink("javascript:alert(1)"))
        assertEquals("", safeLink(null))
        assertEquals(StateTone.YOU to "plan à valider", planState(ProjectHead(plan = "proposed", planLabel = "à valider", waiting = 1)))
        assertNull(planState(ProjectHead(plan = "planned")))
        assertEquals("2 choses attendent quelqu'un d'autre (Léa).", othersWaiting(listOf(Waiting(waitsFor = "Léa"), Waiting())))
        assertEquals("1 sur 3 terminé", doneOf(1, 3))
        assertEquals("2 sur 3 terminés", doneOf(2, 3))
        assertEquals("0 ouvert", plural(0, "ouvert", "ouverts"))
    }

    // ── Ce que l'écran range ──

    @Test fun `À faire par projet dans l'ordre du serveur, les objectifs en trois groupes, les onglets d'une fiche`() {
        val todo = listOf(Waiting(project = 3, projectTitle = "A"), Waiting(project = 8, projectTitle = "B"), Waiting(project = 3, projectTitle = "A"))
        assertEquals(listOf(3 to 2, 8 to 1), todoGroups(todo).map { it.project to it.items.size })
        val sheet = Sheet(
            rights = Rights(detail = true, work = true),
            objectives = listOf(Objective(id = 1, status = "done"), Objective(id = 2, status = "open", need = "Quel port ?"), Objective(id = 3, status = "blocked")),
            missions = listOf(Mission(id = 5)),
            lists = listOf(Listing(name = "tickets", tickets = true)),
            todo = listOf(Waiting(kind = "need", objective = 2, mine = true)),
        )
        assertEquals(listOf("open" to listOf("o2", "o3"), "missions" to listOf("m5"), "done" to listOf("o1")), goalGroups(sheet).map { g -> g.code to g.items.map { it.key } })
        assertEquals(5, findGoal(sheet, "m5")?.id)
        assertNull(findGoal(sheet, "o9"))
        // qui ne connaît qu'un numéro (une attente née d'une mission, un accord, l'objectif lié d'un ticket) ouvre
        // `o<id>` : la mission qui le porte se retrouve — un objectif du même numéro passerait devant, il n'y en a pas
        assertEquals("m5", findGoal(sheet, "o5")?.key)
        assertEquals("o2", findGoal(sheet, "o2")?.key)
        assertNull(findGoal(sheet, "m2"))
        assertNull(findGoal(sheet, "o"))
        assertNull(findGoal(sheet, ""))
        assertTrue(goalAwaits(sheet.objectives[1]))
        assertEquals(2, needWaiting(sheet, 2)?.objective)
        // sans liste de suivi, pas d'onglet « Listes » ; sans le droit de lire l'activité, pas d'« Activité »
        assertEquals(listOf("vue", "objectifs", "tickets", "code", "documentation", "activite", "dependances"), SheetTabs.of(sheet))
        assertEquals(listOf("vue", "objectifs", "tickets", "code", "documentation", "dependances", "listes"), SheetTabs.of(sheet.copy(rights = Rights(detail = true), lists = sheet.lists + Listing(name = "entreprises"))))
        assertEquals(listOf("vue"), SheetTabs.of(sheet.copy(rights = Rights())))
        assertEquals("vue", SheetTabs.shown(sheet, "listes"))
        assertEquals("tickets", SheetTabs.shown(sheet, "tickets"))
    }

    @Test fun `les jalons d'un objectif - sa barre, ce qui compte, un jalon retiré`() {
        val o = Objective(
            status = "open",
            milestones = listOf(Milestone(id = 1, status = "reached"), Milestone(id = 2, status = "open", ready = true), Milestone(id = 3, status = "dropped"), Milestone(id = 4, status = "open")),
        )
        assertEquals(listOf(StateTone.DONE, StateTone.YOU, StateTone.WAIT), milestoneTones(o))
        assertEquals(1, reachedCount(o))
        assertEquals(3, liveMilestones(o).size)
        assertEquals(listOf(StateTone.FAIL), milestoneTones(Objective(status = "blocked")))
    }

    @Test fun `la liste des tickets - À toi se lit dans les ouverts, Tous demande une autre liste`() {
        assertEquals("open", TicketFilters.state(TicketFilters.YOURS))
        assertEquals("open", TicketFilters.state(TicketFilters.OPEN))
        assertEquals("", TicketFilters.state(TicketFilters.ALL))
        val items = listOf(Entry(number = 1, yours = true), Entry(number = 2))
        assertEquals(listOf(1), TicketFilters.shown(TicketFilters.YOURS, items).map { it.number })
        assertEquals(2, TicketFilters.shown(TicketFilters.OPEN, items).size)
    }

    @Test fun `un ticket - le volet qui s'ouvre, son parcours, son histoire mêlée à celle de ses objectifs`() {
        assertEquals(TicketPanes.PLAN, TicketPanes.first(entry(more = EntryMore(can = EntryCan(validate = true))), asks = false))
        assertEquals(TicketPanes.THREAD, TicketPanes.first(entry(), asks = true))
        assertEquals(TicketPanes.DESCRIPTION, TicketPanes.first(entry(), asks = false))
        val j = Journey(fineLabel = "en attente de validation")
        assertEquals("en attente de validation · la main est au propriétaire", stepNote(j, JourneyStep("validation", "Validation", "current"), "au propriétaire"))
        assertEquals("la main est à elle", stepNote(Journey(fineLabel = "En analyse"), JourneyStep("analysis", "En analyse", "current"), "à elle"))
        assertEquals("sautée : pas de code", stepNote(j, JourneyStep("pull", "Pull request", "skipped", "sautée : pas de code"), ""))
        assertEquals("", stepNote(j, JourneyStep("treated", "Traité", "todo"), "à elle"))
        val history = EntryHistory(
            items = listOf(
                Passage(seq = 1, at = 100, status = "unread", statusLabel = "non lu", step = "unread", author = "toi"),
                Passage(seq = 9, at = 300, status = "treated", statusLabel = "traité", was = "pr_ready", step = "treated", author = "toi"),
            ),
        )
        val around = listOf(
            Happening(seq = 5, at = 200, kind = "commit", title = "Ajoute --delai", sha = "cdd07ae46e31"),
            Happening(seq = 6, at = 210, kind = "ticket", title = "redit un passage"),
            Happening(seq = 7, at = 250, kind = "pull", what = "merged", title = "Pull request n° 12 fusionnée"),
        )
        val rows = storyRows(history, around)
        assertEquals(listOf("Ouvert par toi — non lu", "Ajoute --delai", "Pull request n° 12 fusionnée", "Traité — par toi"), rows.map { it.text })
        assertEquals("cdd07ae", rows[1].sha)
        assertEquals(listOf(StateTone.WAIT, null, StateTone.DONE, StateTone.DONE), rows.map { it.tone })
    }

    // ── Le diagramme ──

    @Test fun `le diagramme - ses lignes, la part faite, le mot au bout`() {
        val now = 1_795_600_000_000L
        val reached = DiagramMilestone(id = 1, status = "reached", statusLabel = "atteint", reachedAt = now - 86_400_000L * 3)
        val ready = DiagramMilestone(id = 2, status = "open", ready = true, startedAt = 1)
        val doing = DiagramMilestone(id = 3, status = "open", startedAt = 1, runs = 2)
        val todo = DiagramMilestone(id = 4, status = "open", statusLabel = "à venir")
        val goal = DiagramObjective(id = 2, kind = "once", status = "open", runs = 6, reached = 1, milestonesTotal = 4, milestones = listOf(reached, ready, doing, todo))
        val mission = DiagramObjective(id = 5, kind = "constant", runs = 3, lastRun = now - 5 * 3_600_000L)
        val d = Diagram(objectives = listOf(mission, goal))
        // les objectifs d'abord, chacun suivi de ses jalons, puis les missions ; replié, ses jalons ne paraissent plus
        assertEquals(listOf("o2", "j1", "j2", "j3", "j4", "m5"), diagramRows(d).map { r -> if (r is DiagramRow.StepRow) "j${r.m.id}" else if (r is DiagramRow.MissionRow) "m${r.o.id}" else "o${r.o.id}" })
        assertEquals(2, diagramRows(d, setOf(2)).size)
        assertEquals(1f, milestonePart(reached), 0f)
        assertEquals(1f, milestonePart(ready), 0f)
        assertEquals(0.65f, milestonePart(doing), 0.001f)
        assertEquals(0.9f, milestonePart(doing.copy(runs = 9)), 0.001f)
        assertEquals(0f, milestonePart(todo), 0f)
        val segments = goalSegments(goal)
        assertEquals(listOf(StateTone.DONE, StateTone.YOU, StateTone.WORK), segments.map { it.tone })
        assertEquals(0.25f, segments[0].part, 0.001f)
        assertEquals(0.1625f, segments[2].part, 0.001f)
        assertEquals(listOf(Segment(StateTone.DONE, 1f)), goalSegments(DiagramObjective(status = "done")))
        assertTrue(goalSegments(DiagramObjective(status = "open")).isEmpty())
        assertTrue(milestoneWord(reached, now, paris).startsWith("atteint le "))
        assertEquals("à toi · attend ta validation", milestoneWord(ready, now, paris))
        assertEquals("2 exécutions", milestoneWord(doing, now, paris))
        assertEquals("à venir", milestoneWord(todo, now, paris))
        assertEquals("1 / 4 jalons atteints · 6 exécutions", goalWord(goal, now, paris))
        assertEquals("3 passages · le dernier il y a 5 h", missionWord(mission, now, paris))
    }

    @Test fun `les clés d'une liste - uniques quoi que rende le serveur, et la même tant qu'une ligne est seule de la sienne`() {
        // deux éléments voilés n'ont ni clé ni nom : la même clé, que la liste refuserait
        val veiled = listOf(Entry(list = "entreprises", veiled = "level"), Entry(list = "entreprises", key = "atelier", handle = "atelier"), Entry(list = "entreprises", veiled = "level"))
        val rows = keyed(veiled) { "e${it.key}:${it.handle}" }
        assertEquals(listOf("e:", "eatelier:atelier", "e:#2"), rows.map { it.key })
        assertEquals(veiled, rows.map { it.value })
        // une clé déjà prise par le rang d'une autre ne se redonne pas
        assertEquals(listOf("a", "a#2", "a#2#2", "a#3"), keyed(listOf("a", "a", "a#2", "a")) { it }.map { it.key })
        assertTrue(keyed(emptyList<String>()) { it }.isEmpty())
    }

    @Test fun `la page d'un objectif nommé par son seul numéro - une mission s'ouvre sous m, un objectif sous o`() {
        val sheet = Sheet(objectives = listOf(Objective(id = 2)), missions = listOf(Mission(id = 5)))
        assertEquals("m5", goalKey(sheet, 5))
        assertEquals("o2", goalKey(sheet, 2))
        // la fiche pas encore lue, un objectif qu'elle ne nomme pas : un objectif
        assertEquals("o5", goalKey(null, 5))
        assertEquals("o9", goalKey(sheet, 9))
    }
}
