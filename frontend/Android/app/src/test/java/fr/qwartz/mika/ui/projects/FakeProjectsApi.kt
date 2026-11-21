package fr.qwartz.mika.ui.projects

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.projects.ActivityPage
import fr.qwartz.mika.data.moi.projects.Approvals
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
        answer("elements:$id:$state:$q", tickets)

    override suspend fun element(id: Int, list: String, item: String): MoiApi.Result<EntryDetail> = answer("element:$id:$list:$item", element)

    override suspend fun history(id: Int, item: String): MoiApi.Result<EntryHistory> = answer("history:$id:$item", MoiApi.Result.Ok(history))

    override suspend fun activity(id: Int, kind: String, objective: Int, ticket: Int, before: Long): MoiApi.Result<ActivityPage> =
        answer("activity:$id:$kind:$objective:$ticket", MoiApi.Result.Ok(activity))

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

    override suspend fun merge(project: Int, order: MergeOrder, key: String?): MoiApi.Result<GestureDone> {
        merges += Triple(project, order, key)
        answer("merge:${order.number}", Unit)
        return gestureResult ?: MoiApi.Result.Ok(GestureDone(ok = true, message = "La fusion est demandée.", number = order.number))
    }
}
