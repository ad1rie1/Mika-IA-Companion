package fr.qwartz.mika.ui.projects

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.projects.ActivityPage
import fr.qwartz.mika.data.moi.projects.Approvals
import fr.qwartz.mika.data.moi.projects.ActivityDays
import fr.qwartz.mika.data.moi.projects.ActivityTotals
import fr.qwartz.mika.data.moi.projects.Archives
import fr.qwartz.mika.data.moi.projects.Decision
import fr.qwartz.mika.data.moi.projects.DecisionList
import fr.qwartz.mika.data.moi.projects.DocFound
import fr.qwartz.mika.data.moi.projects.DocHistory
import fr.qwartz.mika.data.moi.projects.DocPage
import fr.qwartz.mika.data.moi.projects.DocSave
import fr.qwartz.mika.data.moi.projects.DocSpace
import fr.qwartz.mika.data.moi.projects.DocUpload
import fr.qwartz.mika.data.moi.projects.DocVersion
import fr.qwartz.mika.data.moi.projects.ImageSaved
import fr.qwartz.mika.data.moi.projects.NotebookPage
import fr.qwartz.mika.data.moi.projects.PageSaved
import fr.qwartz.mika.data.moi.projects.ProjectSettings
import fr.qwartz.mika.data.moi.projects.Run
import fr.qwartz.mika.data.moi.projects.RunPage
import fr.qwartz.mika.data.moi.projects.Blob
import fr.qwartz.mika.data.moi.projects.Branch
import fr.qwartz.mika.data.moi.projects.BranchDetail
import fr.qwartz.mika.data.moi.projects.BranchList
import fr.qwartz.mika.data.moi.projects.ChecksList
import fr.qwartz.mika.data.moi.projects.CodeLinked
import fr.qwartz.mika.data.moi.projects.CodePull
import fr.qwartz.mika.data.moi.projects.CodeSummary
import fr.qwartz.mika.data.moi.projects.Commit
import fr.qwartz.mika.data.moi.projects.CommitDetail
import fr.qwartz.mika.data.moi.projects.CommitPage
import fr.qwartz.mika.data.moi.projects.Diff
import fr.qwartz.mika.data.moi.projects.Diagram
import fr.qwartz.mika.data.moi.projects.Entry
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.EntryHistory
import fr.qwartz.mika.data.moi.projects.EntryMore
import fr.qwartz.mika.data.moi.projects.EntryPage
import fr.qwartz.mika.data.moi.projects.GestureDone
import fr.qwartz.mika.data.moi.projects.GestureRequest
import fr.qwartz.mika.data.moi.projects.HostChecks
import fr.qwartz.mika.data.moi.projects.Issue
import fr.qwartz.mika.data.moi.projects.IssuePage
import fr.qwartz.mika.data.moi.projects.MergeOrder
import fr.qwartz.mika.data.moi.projects.NewProject
import fr.qwartz.mika.data.moi.projects.Overview
import fr.qwartz.mika.data.moi.projects.ProjectsApi
import fr.qwartz.mika.data.moi.projects.PullDetail
import fr.qwartz.mika.data.moi.projects.PullHost
import fr.qwartz.mika.data.moi.projects.PullPage
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.TodoPage
import fr.qwartz.mika.data.moi.projects.Tree
import kotlinx.coroutines.CompletableDeferred
import kotlinx.serialization.json.JsonObject
import okhttp3.OkHttpClient

/**
 * Une fausse API des projets pour les modèles d'écran : ce qu'elle rend se pose par le test, chaque appel se note
 * ([calls]), chaque geste aussi ([sent] : son projet, sa requête, sa clé d'envoi), et un appel retenu ([hold]) ne répond
 * que quand le test le lâche.
 */
class FakeProjectsApi : ProjectsApi(MoiApi(OkHttpClient(), { null }, {})) {
    var overview: MoiApi.Result<Overview> = MoiApi.Result.Ok(Overview())
    val pages = HashMap<Int, TodoPage>()
    var approvals = Approvals()
    var sheet: MoiApi.Result<Sheet> = MoiApi.Result.Ok(Sheet())
    var tickets: MoiApi.Result<EntryPage> = MoiApi.Result.Ok(EntryPage())
    var element: MoiApi.Result<EntryDetail> = MoiApi.Result.Ok(EntryDetail(Entry(), EntryMore()))
    var history = EntryHistory()
    var activity = ActivityPage()
    var diagram = Diagram()
    var fresh = NewProject(can = true)

    /** Ce qu'un geste rend, si le test l'impose (sinon : fait, avec un message). */
    var gestureResult: MoiApi.Result<GestureDone>? = null

    val calls = mutableListOf<String>()
    val sent = mutableListOf<Triple<Int, GestureRequest, String?>>()
    private val gates = HashMap<String, CompletableDeferred<Unit>>()

    fun hold(name: String) {
        gates[name] = CompletableDeferred()
    }

    fun release(name: String) {
        gates.remove(name)?.complete(Unit)
    }

    fun refuse(code: Int, message: String, fields: Map<String, String> = emptyMap()) {
        gestureResult = MoiApi.Result.Failed(MoiError(code, message, fields))
    }

    private suspend fun <T> answer(name: String, value: T): T {
        calls += name
        gates[name]?.await()
        return value
    }

    override suspend fun overview(): MoiApi.Result<Overview> = answer("overview", overview)

    override suspend fun todo(page: Int): MoiApi.Result<TodoPage> = answer("todo:$page", MoiApi.Result.Ok(pages[page] ?: TodoPage()))

    override suspend fun approvals(project: Int): MoiApi.Result<Approvals> = answer("approvals:$project", MoiApi.Result.Ok(approvals))

    override suspend fun sheet(id: Int): MoiApi.Result<Sheet> = answer("sheet:$id", sheet)

    override suspend fun elements(id: Int, list: String, state: String, q: String, size: Int): MoiApi.Result<EntryPage> =
        if (list == TICKETS) answer("elements:$id:$state:$q", tickets) else answer("list:$id:$list", MoiApi.Result.Ok(listPages[list] ?: EntryPage(list = list)))

    override suspend fun element(id: Int, list: String, item: String): MoiApi.Result<EntryDetail> = answer("element:$id:$list:$item", element)

    override suspend fun history(id: Int, item: String): MoiApi.Result<EntryHistory> = answer("history:$id:$item", MoiApi.Result.Ok(history))

    override suspend fun activity(id: Int, kind: String, objective: Int, ticket: Int, before: Long): MoiApi.Result<ActivityPage> =
        answer("activity:$id:$kind:$objective:$ticket" + (if (before > 0) ":$before" else ""), MoiApi.Result.Ok(feeds["$kind|$objective|$before"] ?: activity))

    override suspend fun diagram(id: Int): MoiApi.Result<Diagram> = answer("diagram:$id", MoiApi.Result.Ok(diagram))

    override suspend fun newProject(): MoiApi.Result<NewProject> = answer("newProject", MoiApi.Result.Ok(fresh))

    override suspend fun create(body: JsonObject, key: String?): MoiApi.Result<GestureDone> {
        sent += Triple(0, GestureRequest("nouveau/creer", body), key)
        answer("create", Unit)
        // lu après la barrière : le test pose le sort du geste pendant qu'il est retenu
        return gestureResult ?: MoiApi.Result.Ok(GestureDone(ok = true, message = "Projet confié.", project = 12))
    }

    override suspend fun gesture(project: Int, request: GestureRequest, key: String?): MoiApi.Result<GestureDone> {
        sent += Triple(project, request, key)
        answer("gesture:${request.route}", Unit)
        return gestureResult ?: MoiApi.Result.Ok(GestureDone(ok = true, message = "Fait."))
    }

    // ── Son code ──

    var code: MoiApi.Result<CodeSummary> = MoiApi.Result.Ok(CodeSummary(hasRepo = true, base = "main"))
    /** Les dossiers, par `branche|chemin` ; un dossier que le test n'a pas posé est vide. */
    val trees = HashMap<String, MoiApi.Result<Tree>>()
    var blob: MoiApi.Result<Blob> = MoiApi.Result.Ok(Blob())
    /** Les pages de commits, par `branche|page`. */
    val commitPages = HashMap<String, CommitPage>()
    var commit: MoiApi.Result<CommitDetail> = MoiApi.Result.Ok(CommitDetail(Commit(), CodeLinked(), Diff()))
    var branches: MoiApi.Result<BranchList> = MoiApi.Result.Ok(BranchList())
    var branch: MoiApi.Result<BranchDetail> = MoiApi.Result.Ok(BranchDetail(Branch(), emptyList(), Diff()))
    var pulls: MoiApi.Result<PullPage> = MoiApi.Result.Ok(PullPage())
    /** La pull request telle que le serveur la rend **maintenant** : le test la change entre deux lectures. */
    var pull: MoiApi.Result<PullDetail> = MoiApi.Result.Ok(PullDetail(CodePull(), emptyList(), Diff()))
    var pullHost: MoiApi.Result<PullHost> = MoiApi.Result.Ok(PullHost())
    var issues: MoiApi.Result<IssuePage> = MoiApi.Result.Ok(IssuePage())
    var issue: MoiApi.Result<Issue> = MoiApi.Result.Ok(Issue())
    var checks: MoiApi.Result<ChecksList> = MoiApi.Result.Ok(ChecksList())
    var commitChecks: MoiApi.Result<HostChecks> = MoiApi.Result.Ok(HostChecks())

    /** Les fusions demandées : le projet, le numéro et le commit de tête nommés, la clé d'envoi. */
    val merges = mutableListOf<Triple<Int, MergeOrder, String?>>()

    override suspend fun code(id: Int): MoiApi.Result<CodeSummary> = answer("code:$id", code)

    override suspend fun tree(id: Int, ref: String, path: String): MoiApi.Result<Tree> =
        answer("tree:$id:$ref:$path", trees["$ref|$path"] ?: MoiApi.Result.Ok(Tree(ref = ref, path = path)))

    override suspend fun blob(id: Int, ref: String, path: String): MoiApi.Result<Blob> = answer("blob:$id:$ref:$path", blob)

    override suspend fun commits(id: Int, ref: String, page: Int, size: Int): MoiApi.Result<CommitPage> =
        answer("commits:$id:$ref:$page", MoiApi.Result.Ok(commitPages["$ref|$page"] ?: CommitPage(ref = ref, page = page, size = size)))

    override suspend fun commit(id: Int, sha: String, path: String): MoiApi.Result<CommitDetail> = answer("commit:$id:$sha:$path", commit)

    override suspend fun branches(id: Int): MoiApi.Result<BranchList> = answer("branches:$id", branches)

    override suspend fun branch(id: Int, name: String): MoiApi.Result<BranchDetail> = answer("branch:$id:$name", branch)

    override suspend fun pulls(id: Int): MoiApi.Result<PullPage> = answer("pulls:$id", pulls)

    override suspend fun pull(id: Int, number: Int, objective: Int, path: String): MoiApi.Result<PullDetail> {
        answer("pull:$id:$number:$objective:$path", Unit)
        // lue après la barrière : le test change la pull request pendant que sa lecture est retenue
        return pull
    }

    override suspend fun pullHost(id: Int, number: Int): MoiApi.Result<PullHost> = answer("pullHost:$id:$number", pullHost)

    override suspend fun issues(id: Int): MoiApi.Result<IssuePage> = answer("issues:$id", issues)

    override suspend fun issue(id: Int, number: Int): MoiApi.Result<Issue> = answer("issue:$id:$number", issue)

    override suspend fun checks(id: Int): MoiApi.Result<ChecksList> = answer("checks:$id", checks)

    override suspend fun commitChecks(id: Int, sha: String): MoiApi.Result<HostChecks> = answer("commitChecks:$id:$sha", commitChecks)

    // ── Sa documentation, son activité, ses réglages ──

    var docs: MoiApi.Result<DocSpace> = MoiApi.Result.Ok(DocSpace())
    /** La page telle que le serveur la rend **maintenant** : le test la change entre deux lectures. */
    var docPage: MoiApi.Result<DocPage> = MoiApi.Result.Ok(DocPage())
    var docHistory: MoiApi.Result<DocHistory> = MoiApi.Result.Ok(DocHistory())
    var docVersion: MoiApi.Result<DocVersion> = MoiApi.Result.Ok(DocVersion())
    var docFound = DocFound()
    var decisions: MoiApi.Result<DecisionList> = MoiApi.Result.Ok(DecisionList())
    var decision: MoiApi.Result<Decision> = MoiApi.Result.Ok(Decision())
    /** Ce qu'un enregistrement rend, si le test l'impose (sinon : la version d'après celle qu'il nomme). */
    var saveResult: MoiApi.Result<PageSaved>? = null
    var uploadResult: MoiApi.Result<ImageSaved> = MoiApi.Result.Ok(ImageSaved(ok = true, message = "Image ajoutée.", name = "schema.png", path = "images/schema.png"))
    /** Les enregistrements demandés : le projet, ce qui est envoyé (dont la version lue), la clé d'envoi. */
    val saves = mutableListOf<Triple<Int, DocSave, String?>>()
    val uploads = mutableListOf<Pair<DocUpload, String?>>()
    var days = ActivityDays()
    var totals = ActivityTotals()
    /** Les pages du fil d'après un curseur, par `sorte|objectif|curseur` (la première : curseur 0, sinon [activity]). */
    val feeds = HashMap<String, ActivityPage>()
    val runPages = HashMap<Long, RunPage>()
    var run: MoiApi.Result<Run> = MoiApi.Result.Ok(Run())
    val notebooks = HashMap<String, NotebookPage>()
    var settings: MoiApi.Result<ProjectSettings> = MoiApi.Result.Ok(ProjectSettings())
    var archives = Archives()
    /** Les éléments d'une liste de suivi, par son nom (la liste des tickets : [tickets]). */
    val listPages = HashMap<String, EntryPage>()

    override suspend fun docs(id: Int): MoiApi.Result<DocSpace> = answer("docs:$id", docs)

    override suspend fun docPage(id: Int, path: String): MoiApi.Result<DocPage> {
        answer("docPage:$id:$path", Unit)
        return docPage
    }

    override suspend fun docHistory(id: Int, path: String): MoiApi.Result<DocHistory> = answer("docHistory:$id:$path", docHistory)

    override suspend fun docVersion(id: Int, path: String, n: Int): MoiApi.Result<DocVersion> = answer("docVersion:$id:$path:$n", docVersion)

    override suspend fun docSearch(id: Int, q: String): MoiApi.Result<DocFound> = answer("docSearch:$id:$q", MoiApi.Result.Ok(docFound))

    override fun docImageUrl(id: Int, name: String): String? = "https://mika.invalid/api/moi/projets/$id/documentation/image?name=$name"

    override suspend fun decisions(id: Int): MoiApi.Result<DecisionList> = answer("decisions:$id", decisions)

    override suspend fun decision(id: Int, number: Int): MoiApi.Result<Decision> = answer("decision:$id:$number", decision)

    override suspend fun saveDoc(id: Int, save: DocSave, key: String?): MoiApi.Result<PageSaved> {
        saves += Triple(id, save, key)
        answer("saveDoc:${save.path}", Unit)
        return saveResult ?: MoiApi.Result.Ok(PageSaved(ok = true, message = "Page enregistrée.", path = save.path, version = save.base + 1))
    }

    override suspend fun uploadDocImage(id: Int, image: DocUpload, key: String?): MoiApi.Result<ImageSaved> {
        uploads += image to key
        return answer("upload:${image.name}", uploadResult)
    }

    override suspend fun activityDays(id: Int): MoiApi.Result<ActivityDays> = answer("days:$id", MoiApi.Result.Ok(days))

    override suspend fun activityTotals(id: Int, objective: Int): MoiApi.Result<ActivityTotals> = answer("totals:$id:$objective", MoiApi.Result.Ok(totals))

    override suspend fun runs(id: Int, before: Long): MoiApi.Result<RunPage> = answer("runs:$id:$before", MoiApi.Result.Ok(runPages[before] ?: RunPage()))

    override suspend fun run(id: Int, run: String): MoiApi.Result<Run> = answer("run:$id:$run", this.run)

    override suspend fun notebook(id: Int, objective: Int, before: Long): MoiApi.Result<NotebookPage> =
        answer("notebook:$id:$objective:$before", MoiApi.Result.Ok(notebooks["$objective|$before"] ?: NotebookPage()))

    override suspend fun settings(id: Int): MoiApi.Result<ProjectSettings> = answer("settings:$id", settings)

    /** Lus à chaque retour sur la rubrique : pas notés dans [calls], que les tests d'avant comptent. */
    override suspend fun archives(): MoiApi.Result<Archives> = MoiApi.Result.Ok(archives)

    override suspend fun merge(project: Int, order: MergeOrder, key: String?): MoiApi.Result<GestureDone> {
        merges += Triple(project, order, key)
        answer("merge:${order.number}", Unit)
        return gestureResult ?: MoiApi.Result.Ok(GestureDone(ok = true, message = "La fusion est demandée.", number = order.number))
    }
}
