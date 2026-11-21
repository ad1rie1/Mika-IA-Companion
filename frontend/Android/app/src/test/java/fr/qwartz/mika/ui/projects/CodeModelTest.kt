package fr.qwartz.mika.ui.projects

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.projects.Approval
import fr.qwartz.mika.data.moi.projects.Approvals
import fr.qwartz.mika.data.moi.projects.BranchList
import fr.qwartz.mika.data.moi.projects.Branch
import fr.qwartz.mika.data.moi.projects.CodePull
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.Commit
import fr.qwartz.mika.data.moi.projects.CommitPage
import fr.qwartz.mika.data.moi.projects.Concerns
import fr.qwartz.mika.data.moi.projects.Diff
import fr.qwartz.mika.data.moi.projects.DiffFile
import fr.qwartz.mika.data.moi.projects.Entry
import fr.qwartz.mika.data.moi.projects.EntryCan
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.EntryMore
import fr.qwartz.mika.data.moi.projects.Issue
import fr.qwartz.mika.data.moi.projects.MERGE_NOT_NOW
import fr.qwartz.mika.data.moi.projects.MERGE_ROUTE
import fr.qwartz.mika.data.moi.projects.MergeState
import fr.qwartz.mika.data.moi.projects.OutsideText
import fr.qwartz.mika.data.moi.projects.Overview
import fr.qwartz.mika.data.moi.projects.PullDetail
import fr.qwartz.mika.data.moi.projects.PullHost
import fr.qwartz.mika.data.moi.projects.TicketLine
import fr.qwartz.mika.data.moi.projects.Tree
import fr.qwartz.mika.data.moi.projects.TreeEntry
import fr.qwartz.mika.data.moi.projects.Waiting
import fr.qwartz.mika.data.moi.projects.waitingKey
import fr.qwartz.mika.ui.components.ProMarkdown
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Les modèles de l'onglet Code contre une fausse API : **la fusion** — la pull request relue à l'instant, la
 * confirmation qui dit ce qui va être fusionné, la demande qui nomme le commit de tête lu (pas celui d'avant), ses
 * refus dits sur place avec les mots du serveur, un double appui qui ne part qu'une fois, depuis sa page comme depuis
 * « À faire », où aucun autre bouton n'y mène — ; modifier une pull request et y répondre ; ce que chaque volet lit ; le
 * ticket d'une issue ; et un fichier Markdown du dépôt rendu sans un lien qui s'ouvre.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CodeModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeProjectsApi()
    private var clock = 1_795_600_000_000L
    private val deps = ProjectsDeps(api, {}, { clock })

    private val headA = "a".repeat(40)
    private val headB = "b".repeat(40)

    private fun ready(head: String, can: Boolean = true, why: String = "") = PullDetail(
        CodePull(number = 11, title = "Exporter en CSV", state = "ready", stateLabel = "prête à fusionner", branch = "ticket-2-export-csv", base = "main", head = head, merge = MergeState(can = can, why = why)),
        listOf(Commit(sha = "c1"), Commit(sha = "c2")),
        Diff(files = listOf(DiffFile(path = "export.py")), insertions = 38, deletions = 1),
    )

    private fun serve(d: PullDetail) {
        api.pull = MoiApi.Result.Ok(d)
    }

    private fun pullModel(key: String = "11") = main.model { PullViewModel(deps, 3, key) }

    private fun text(name: String, i: Int = api.sent.lastIndex) = (api.sent[i].second.body[name] as? JsonPrimitive)?.content

    // ── Fusionner ──

    @Test fun `fusionner - la pull request se relit, la confirmation dit ce qui part, la demande nomme le commit de tête relu`() = runTest {
        serve(ready(headA))
        val vm = pullModel()
        vm.resume()
        advanceUntilIdle()
        assertEquals(headA, vm.detail.value?.pull?.head)
        // sa branche a avancé depuis que l'écran l'a lue : c'est la relecture de l'instant qui compte
        serve(ready(headB))
        vm.askMerge()
        advanceUntilIdle()
        val asking = vm.merge.asking
        assertNotNull(asking)
        assertEquals(headB, asking!!.facts.head)
        assertEquals(11, asking.facts.number)
        assertEquals("ticket-2-export-csv" to "main", asking.facts.branch to asking.facts.base)
        assertEquals(listOf(2, 1, 38, 1), with(asking.facts) { listOf(commits, files, insertions, deletions) })
        // rien n'est parti tant qu'elle n'a pas confirmé
        assertTrue(api.merges.isEmpty())
        vm.confirmMerge()
        advanceUntilIdle()
        val (project, order, key) = api.merges.single()
        assertEquals(3, project)
        assertEquals(11, order.number)
        assertEquals(headB, order.head)
        assertNotNull(key)
        assertNull(vm.merge.asking)
        assertEquals(PullViewModel.MERGE, vm.gestures.finished)
        // abouti : elle se relit (son état qui suit : demandée), et l'onglet et la fiche avec elle
        assertEquals(1, vm.revision)
        assertEquals(3, api.calls.count { it == "pull:3:11:0:" })
        // aucun geste générique n'a porté la route
        assertTrue(api.sent.none { it.second.route == MERGE_ROUTE })
    }

    @Test fun `annuler la confirmation ne fait rien partir`() = runTest {
        serve(ready(headA))
        val vm = pullModel()
        vm.askMerge()
        advanceUntilIdle()
        assertNotNull(vm.merge.asking)
        vm.merge.cancel()
        vm.confirmMerge()
        advanceUntilIdle()
        assertTrue(api.merges.isEmpty())
        assertNull(vm.merge.asking)
    }

    @Test fun `ce que la relecture ne permet plus ne s'ouvre pas - la raison du serveur se dit sur place`() = runTest {
        serve(ready(headA, can = false, why = "La CI tourne encore sur le dernier commit."))
        val vm = pullModel()
        vm.askMerge()
        advanceUntilIdle()
        assertNull(vm.merge.asking)
        assertEquals("La CI tourne encore sur le dernier commit.", vm.gestures.refusalAt(PullViewModel.MERGE))
        assertTrue(api.merges.isEmpty())
        // sans commit de tête lu, rien à nommer : l'écran le dit, et ne demande rien
        serve(ready("", can = true))
        vm.askMerge()
        advanceUntilIdle()
        assertNull(vm.merge.asking)
        assertEquals(MERGE_NOT_NOW, vm.gestures.refusalAt(PullViewModel.MERGE))
        // la relecture qui échoue : ses mots, et rien ne s'ouvre
        api.pull = MoiApi.Result.Failed(MoiError(404, "Cette pull request n'existe pas, ou ne t'est pas ouverte."))
        vm.askMerge()
        advanceUntilIdle()
        assertNull(vm.merge.asking)
        assertEquals("Cette pull request n'existe pas, ou ne t'est pas ouverte.", vm.gestures.refusalAt(PullViewModel.MERGE))
        assertTrue(api.merges.isEmpty())
    }

    @Test fun `une fusion refusée se dit sur place avec les mots du serveur, et la pull request se relit`() = runTest {
        serve(ready(headA))
        val vm = pullModel()
        vm.askMerge()
        advanceUntilIdle()
        api.refuse(409, "La branche a bougé depuis ta lecture : relis la pull request, puis fusionne.")
        vm.confirmMerge()
        advanceUntilIdle()
        assertEquals(1, api.merges.size)
        assertEquals("La branche a bougé depuis ta lecture : relis la pull request, puis fusionne.", vm.gestures.refusalAt(PullViewModel.MERGE))
        assertNull(vm.gestures.finished)
        assertEquals(1, vm.revision)
        // redemander : une nouvelle relecture, une nouvelle confirmation, une clé d'envoi neuve (le serveur a répondu)
        api.gestureResult = null
        serve(ready(headB))
        vm.askMerge()
        advanceUntilIdle()
        assertEquals("", vm.gestures.refusalAt(PullViewModel.MERGE))
        vm.confirmMerge()
        advanceUntilIdle()
        assertEquals(listOf(headA, headB), api.merges.map { it.second.head })
        assertNotEquals(api.merges[0].third, api.merges[1].third)
    }

    @Test fun `un double appui ne relit et ne part qu'une fois, une coupure du réseau garde la clé d'envoi`() = runTest {
        serve(ready(headA))
        val vm = pullModel()
        api.hold("pull:3:11:0:")
        vm.askMerge()
        vm.askMerge()
        assertTrue(vm.merge.reading)
        api.release("pull:3:11:0:")
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it == "pull:3:11:0:" })
        api.hold("merge:11")
        vm.confirmMerge()
        vm.confirmMerge()
        vm.askMerge()
        api.release("merge:11")
        advanceUntilIdle()
        assertEquals(1, api.merges.size)
        // le réseau coupe : on ne sait pas si elle est partie — la redire avec le même commit de tête ne la refait pas
        api.gestureResult = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.askMerge()
        advanceUntilIdle()
        vm.confirmMerge()
        advanceUntilIdle()
        vm.askMerge()
        advanceUntilIdle()
        vm.confirmMerge()
        advanceUntilIdle()
        assertEquals(3, api.merges.size)
        assertEquals(api.merges[1].third, api.merges[2].third)
        assertNotEquals(api.merges[0].third, api.merges[1].third)
    }

    // ── Depuis « À faire » ──

    private val mergeWaiting: Waiting = MikaJson.decodeFromString(
        Waiting.serializer(),
        """{"project":3,"project_title":"Outils réseau","kind":"ticket","what":"merge","number":2,"mine":true,"can":true,"about":"#2 Export CSV — sa pull request est prête",
            "gesture":{"route":"code/pull/fusionner","args":{"number":11},"label":"Fusionner","where":"ici"}}""",
    )

    private fun section(): ProjectsViewModel {
        api.overview = MoiApi.Result.Ok(Overview(todo = listOf(mergeWaiting), todoTotal = 1))
        api.element = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#2", number = 2, title = "Export CSV"), EntryMore(can = EntryCan(dismiss = true, dismissNeedsReason = true))))
        return main.model { ProjectsViewModel(deps) }
    }

    @Test fun `depuis À faire, la fusion passe par la même confirmation - la pull request de l'attente, relue, son commit de tête nommé`() = runTest {
        serve(ready(headB))
        val vm = section()
        vm.open(3, waitingKey(mergeWaiting))
        advanceUntilIdle()
        assertEquals(mergeWaiting, vm.shown)
        vm.askMerge()
        advanceUntilIdle()
        assertTrue("pull:3:11:0:" in api.calls)
        assertEquals(headB, vm.merge.asking?.facts?.head)
        assertTrue(api.merges.isEmpty())
        vm.confirmMerge()
        advanceUntilIdle()
        assertEquals(11 to headB, api.merges.single().second.let { it.number to it.head })
        // demandée : l'attente est décidée, l'écran revient à la liste
        assertEquals(ProjectsViewModel.todoWhere(3, waitingKey(mergeWaiting)), vm.gestures.finished)
    }

    @Test fun `depuis À faire, aucun autre bouton ne mène à la fusion - un verdict tranche le ticket, le reste ne part pas`() = runTest {
        serve(ready(headA))
        val vm = section()
        vm.open(3, waitingKey(mergeWaiting))
        advanceUntilIdle()
        vm.decide("dismiss", "hors sujet")
        advanceUntilIdle()
        assertEquals("ticket/trancher", api.sent.single().second.route)
        assertEquals("#2", text("item"))
        for (action in listOf("go", "", "merge", "fusionner", "answer")) {
            vm.decide(action, "x")
            advanceUntilIdle()
        }
        assertTrue(api.merges.isEmpty())
        assertTrue(api.sent.none { it.second.route == MERGE_ROUTE || it.second.route.isEmpty() })
        // refusée par le serveur depuis « À faire » : ses mots, à l'endroit de l'attente
        serve(ready(headA, can = false, why = "Une fusion est déjà demandée."))
        vm.askMerge()
        advanceUntilIdle()
        assertEquals("Une fusion est déjà demandée.", vm.gestures.refusalAt(ProjectsViewModel.todoWhere(3, waitingKey(mergeWaiting))))
        assertTrue(api.merges.isEmpty())
    }

    // ── Modifier, répondre ──

    @Test fun `modifier part de ce que l'hôte dit maintenant et n'envoie que ce qui change, répondre vide son champ`() = runTest {
        serve(ready(headA))
        api.pullHost = MoiApi.Result.Ok(PullHost(number = 11, title = OutsideText("Export CSV"), body = OutsideText("Ancien texte")))
        val vm = pullModel()
        vm.resume()
        vm.openHost()
        advanceUntilIdle()
        assertEquals("Export CSV" to "Ancien texte", vm.editable())
        vm.edit("Export CSV", "Nouveau texte")
        advanceUntilIdle()
        assertEquals("code/pull/modifier", api.sent.single().second.route)
        assertEquals(setOf("number", "body"), api.sent.single().second.body.keys)
        assertEquals("Nouveau texte", text("body"))
        assertEquals(PullViewModel.EDIT, vm.gestures.finished)
        // refusé : ses mots sous le champ, la feuille reste
        vm.gestures.acknowledge()
        api.refuse(400, "Le titre est trop long.", mapOf("title" to "400 caractères au plus"))
        vm.edit("x".repeat(500), "Nouveau texte")
        advanceUntilIdle()
        assertEquals("400 caractères au plus", vm.gestures.fieldsAt(PullViewModel.EDIT)["title"])
        assertNull(vm.gestures.finished)
        // répondre : rien sans texte ; envoyé, le champ se vide
        api.gestureResult = null
        vm.comment()
        advanceUntilIdle()
        assertEquals(2, api.sent.size)
        vm.reply = "  Oui, j'ajoute le test.  "
        vm.comment()
        advanceUntilIdle()
        assertEquals("code/pull/commenter", api.sent.last().second.route)
        assertEquals("Oui, j'ajoute le test.", text("text"))
        assertEquals("", vm.reply)
    }

    @Test fun `une pull request sans numéro se lit par son objectif et ne demande rien à l'hôte`() = runTest {
        serve(PullDetail(CodePull(number = 0, state = "proposed"), emptyList(), Diff()))
        val vm = pullModel("o4")
        vm.resume()
        vm.openHost()
        advanceUntilIdle()
        assertTrue("pull:3:0:4:" in api.calls)
        assertTrue(api.calls.none { it.startsWith("pullHost") })
        vm.comment()
        advanceUntilIdle()
        assertTrue(api.sent.isEmpty())
    }

    // ── Les volets ──

    @Test fun `chaque volet lit ce qu'il montre, une fois - l'arborescence un dossier à la fois, à la branche choisie`() = runTest {
        api.branches = MoiApi.Result.Ok(BranchList("main", listOf(Branch(name = "main", base = true), Branch(name = "ticket-2"))))
        api.trees["|"] = MoiApi.Result.Ok(Tree(items = listOf(TreeEntry("src", "src", "dir"), TreeEntry("README.md", "README.md", "file"))))
        api.trees["|src"] = MoiApi.Result.Ok(Tree(path = "src", items = listOf(TreeEntry("src/a.py", "a.py", "file"))))
        val vm = main.model { CodeViewModel(deps, 3) }
        vm.resume()
        vm.show(CodeTabs.FILES)
        advanceUntilIdle()
        assertEquals(listOf("code:3", "branches:3", "tree:3::"), api.calls)
        // un dossier ne se lit qu'en s'ouvrant, et une seule fois
        vm.fold("src")
        advanceUntilIdle()
        vm.fold("src")
        vm.fold("src")
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it == "tree:3::src" })
        assertEquals(setOf("src"), vm.open)
        // une autre branche : l'arborescence repart de sa racine
        vm.pickFilesRef("ticket-2")
        advanceUntilIdle()
        assertTrue(vm.open.isEmpty())
        assertEquals(setOf(""), vm.trees.keys)
        assertTrue("tree:3:ticket-2:" in api.calls)
        assertEquals("ticket-2", vm.filesBranch)
        // les autres volets ne se lisent qu'en s'ouvrant
        assertTrue(api.calls.none { it.startsWith("pulls") || it.startsWith("issues") || it.startsWith("checks") })
        vm.show(CodeTabs.PULLS)
        vm.show(CodeTabs.ISSUES)
        vm.show(CodeTabs.CI)
        vm.show(CodeTabs.PULLS)
        advanceUntilIdle()
        assertEquals(listOf(1, 1, 1), listOf("pulls:3", "issues:3", "checks:3").map { name -> api.calls.count { it == name } })
    }

    @Test fun `les commits - la suite s'ajoute sans redire, le filtre par branche repart du début, une relecture en panne garde ce qui était montré`() = runTest {
        api.commitPages["|1"] = CommitPage(total = 5, page = 1, size = 2, items = listOf(Commit(sha = "a"), Commit(sha = "b")))
        api.commitPages["|2"] = CommitPage(total = 5, page = 2, size = 2, items = listOf(Commit(sha = "b"), Commit(sha = "c")))
        val vm = main.model { CodeViewModel(deps, 3) }
        vm.resume()
        vm.show(CodeTabs.COMMITS)
        advanceUntilIdle()
        assertEquals(listOf("a", "b"), vm.allCommits.map { it.sha })
        vm.more()
        advanceUntilIdle()
        assertEquals(listOf("a", "b", "c"), vm.allCommits.map { it.sha })
        assertTrue("commits:3::2" in api.calls)
        // hors ligne au retour sur l'écran : le dépôt en bref et la liste restent
        api.code = MoiApi.Result.Failed(MoiError(0, MoiError.NETWORK))
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.summary.load is Load.Ready)
        assertEquals(3, vm.allCommits.size)
        // une branche filtrée : sa première page, sans la suite de l'autre
        api.commitPages["main|1"] = CommitPage(ref = "main", total = 1, page = 1, size = 2, items = listOf(Commit(sha = "m")))
        vm.pickCommitsRef("main")
        advanceUntilIdle()
        assertEquals(listOf("m"), vm.allCommits.map { it.sha })
    }

    @Test fun `ce que l'hôte est seul à savoir ne se relit pas à chaque retour sur l'écran`() = runTest {
        val vm = main.model { CodeViewModel(deps, 3) }
        vm.resume()
        vm.show(CodeTabs.ISSUES)
        advanceUntilIdle()
        vm.resume()
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it == "issues:3" })
        // une minute plus tard, ou en tirant : il se relit
        clock += HOST_AGE_MS + 1
        vm.resume()
        advanceUntilIdle()
        assertEquals(2, api.calls.count { it == "issues:3" })
        vm.reload()
        advanceUntilIdle()
        assertEquals(3, api.calls.count { it == "issues:3" })
    }

    @Test fun `une issue - son ticket se lit dans le registre s'il se lit, et s'y tranche - ce qui attend son accord sur elle`() = runTest {
        api.issue = MoiApi.Result.Ok(Issue(number = 9, title = OutsideText("Le scan plante"), state = "open", ticket = TicketLine(number = 5, status = "proposed", yours = true)))
        api.element = MoiApi.Result.Ok(EntryDetail(Entry(list = "tickets", handle = "#5", number = 5), EntryMore(can = EntryCan(accept = true, dismiss = true))))
        api.approvals = Approvals(listOf(Approval(id = 41, concerns = Concerns(issue = 9)), Approval(id = 42, concerns = Concerns(issue = 7))))
        val vm = main.model { IssueViewModel(deps, 3, 9) }
        vm.resume(approve = true)
        advanceUntilIdle()
        assertTrue("element:3:tickets:#5" in api.calls)
        assertTrue(vm.entry!!.more.can.accept)
        assertEquals(listOf(41), vm.waiting.map { it.id })
        vm.settle("accept")
        advanceUntilIdle()
        assertEquals("ticket/trancher", api.sent.single().second.route)
        assertEquals("#5" to "accept", text("item") to text("verdict"))
        assertEquals(1, vm.revision)
        // une issue qu'elle ne lit pas, ou sans ticket : rien ne se demande au registre, rien ne se tranche
        val calls = api.calls.size
        api.issue = MoiApi.Result.Ok(Issue(number = 8, veiled = "proposed", veiledLabel = "Une issue d'un inconnu.", ticket = TicketLine(number = 6)))
        val veiled = main.model { IssueViewModel(deps, 3, 8) }
        veiled.resume(approve = false)
        advanceUntilIdle()
        assertEquals(listOf("issue:3:8"), api.calls.drop(calls))
        assertNull(veiled.entry)
        veiled.settle("accept")
        advanceUntilIdle()
        assertEquals(1, api.sent.size)
    }

    @Test fun `un fichier coupé d'un diff se relit seul, une fois`() = runTest {
        val vm = main.model { CommitViewModel(deps, 3, "abc") }
        vm.whole.read("gros.py")
        advanceUntilIdle()
        // la réponse ne porte pas ce fichier : cela se dit, rien n'est inventé
        assertTrue(vm.whole.files["gros.py"] is Load.Failed)
        api.commit = MoiApi.Result.Ok(fr.qwartz.mika.data.moi.projects.CommitDetail(Commit(sha = "abc"), fr.qwartz.mika.data.moi.projects.CodeLinked(), Diff(files = listOf(DiffFile(path = "autre.py")))))
        vm.whole.read("autre.py")
        vm.whole.read("autre.py")
        advanceUntilIdle()
        assertEquals("autre.py", vm.whole.files["autre.py"]?.valueOrNull?.path)
        assertEquals(1, api.calls.count { it == "commit:3:abc:autre.py" })
    }

    // ── Les textes venus d'ailleurs ──

    @Test fun `un fichier Markdown du dépôt se rend sans un lien qui s'ouvre, et rien n'y est du HTML`() {
        val text = """
            # Outils réseau <script>alert(1)</script>

            Voir [la doc](https://exemple.invalid/doc) ou https://exemple.invalid/nu, et ![une image](https://exemple.invalid/i.png).

            - un point avec [un lien](https://exemple.invalid/a)

            | Colonne | Lien |
            |---|---|
            | a | [b](https://exemple.invalid/b) |
        """.trimIndent()
        // le rendu du mode pro, lui, rend ces liens cliquables : c'est ce que le fichier du dépôt n'a pas
        fun urls(blocks: List<ProMarkdown.Block>): List<String> = blocks.flatMap { b ->
            when (b) {
                is ProMarkdown.Block.Paragraph -> b.spans
                is ProMarkdown.Block.Heading -> b.spans
                is ProMarkdown.Block.Item -> b.spans
                is ProMarkdown.Block.Quote -> b.spans
                is ProMarkdown.Block.Table -> b.header.flatten() + b.rows.flatten().flatten()
                else -> emptyList()
            }
        }.mapNotNull { it.url }
        assertTrue(urls(ProMarkdown.parse(text)).size >= 4)
        val shown = repoMarkdown(text)
        assertTrue(urls(shown).isEmpty())
        // le texte, lui, est là : le titre garde ses chevrons comme du texte, le lien son libellé
        val heading = shown.first() as ProMarkdown.Block.Heading
        assertEquals("Outils réseau <script>alert(1)</script>", heading.spans.joinToString("") { it.text })
        assertTrue(shown.any { b -> b is ProMarkdown.Block.Paragraph && b.spans.any { it.text == "la doc" } })
        assertFalse(shown.any { it is ProMarkdown.Block.Code })
    }
}
