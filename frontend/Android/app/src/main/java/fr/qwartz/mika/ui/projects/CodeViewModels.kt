package fr.qwartz.mika.ui.projects

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.projects.Approval
import fr.qwartz.mika.data.moi.projects.Approvals
import fr.qwartz.mika.data.moi.projects.Blob
import fr.qwartz.mika.data.moi.projects.BranchDetail
import fr.qwartz.mika.data.moi.projects.BranchList
import fr.qwartz.mika.data.moi.projects.ChecksList
import fr.qwartz.mika.data.moi.projects.CodeSummary
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.Commit
import fr.qwartz.mika.data.moi.projects.CommitDetail
import fr.qwartz.mika.data.moi.projects.CommitPage
import fr.qwartz.mika.data.moi.projects.Diff
import fr.qwartz.mika.data.moi.projects.DiffFile
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.GestureDone
import fr.qwartz.mika.data.moi.projects.HostChecks
import fr.qwartz.mika.data.moi.projects.Issue
import fr.qwartz.mika.data.moi.projects.IssuePage
import fr.qwartz.mika.data.moi.projects.MERGE_NOT_NOW
import fr.qwartz.mika.data.moi.projects.MergeFacts
import fr.qwartz.mika.data.moi.projects.MergeOrder
import fr.qwartz.mika.data.moi.projects.ProjectsApi
import fr.qwartz.mika.data.moi.projects.PullDetail
import fr.qwartz.mika.data.moi.projects.PullHost
import fr.qwartz.mika.data.moi.projects.PullPage
import fr.qwartz.mika.data.moi.projects.TrackedChecks
import fr.qwartz.mika.data.moi.projects.Tree
import fr.qwartz.mika.data.moi.projects.bySha
import fr.qwartz.mika.data.moi.projects.mergeFacts
import fr.qwartz.mika.data.moi.projects.parsePullKey
import fr.qwartz.mika.data.moi.projects.pullCommentRequest
import fr.qwartz.mika.data.moi.projects.pullEditRequest
import fr.qwartz.mika.data.moi.projects.hostText
import fr.qwartz.mika.data.moi.projects.settleRequest
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/*
 * Les modèles de l'onglet Code (ADR 0296) : ce que chaque vue a lu du code d'un projet (`…/code/…`), ce qui y est
 * choisi, et les gestes d'une pull request — la modifier, y répondre, **la fusionner** ([MergeFlow] : la relire, une
 * confirmation qui dit ce qui va être fusionné, puis la demande qui nomme le commit de tête lu). Aucun ne décide de ce
 * qu'on peut faire : `rights`, `merge.can` et `can` viennent du serveur, un refus se dit sur place avec ses mots. Ils
 * prennent ce qu'il leur faut par [ProjectsDeps] et se testent sur la JVM contre une fausse API.
 */

/** Ce que l'hôte est seul à savoir se relit moins souvent : chaque lecture le joint (soixante par minute et par compte). */
internal const val HOST_AGE_MS = 60_000L

/**
 * Une lecture gardée : `null` tant qu'on ne l'a pas demandée, puis en cours, lue, ou refusée (en mots). Une relecture
 * qui échoue garde ce qui était montré — et le dit, si on l'a demandée.
 */
class Kept<T>(
    private val scope: CoroutineScope,
    private val now: () -> Long,
    private val say: (String) -> Unit,
    private val fetch: suspend () -> MoiApi.Result<T>,
) {
    var load by mutableStateOf<Load<T>?>(null)
        private set
    private var job: Job? = null
    private var readAt = 0L

    val value: T? get() = load?.valueOrNull

    /** La première fois seulement : ce qui est déjà lu reste. */
    fun open() {
        if (load == null) read()
    }

    /** Lire, ou relire. */
    fun read(quiet: Boolean = true): Job {
        job?.cancel()
        if (load !is Load.Ready) load = Load.Loading
        return scope.launch {
            when (val got = fetch()) {
                is MoiApi.Result.Ok -> {
                    readAt = now()
                    load = Load.Ready(got.value)
                }
                is MoiApi.Result.Failed -> if (load is Load.Ready) {
                    if (!quiet) say(got.error.said)
                } else {
                    load = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }

    /** Relire ce qui a déjà été demandé — sauf si c'est lu depuis moins de [maxAgeMs] (ce que l'hôte est seul à savoir). */
    fun again(maxAgeMs: Long = 0) {
        if (load == null) return
        if (maxAgeMs > 0 && load is Load.Ready && now() - readAt < maxAgeMs) return
        read()
    }

    fun retry() {
        load = Load.Loading
        read(quiet = false)
    }

    fun forget() {
        job?.cancel()
        load = null
    }
}

// ── L'onglet : ses six volets ───────────────────────────────────────────

/**
 * L'onglet Code d'un projet, un par projet et par session : le dépôt en bref, puis ce que chaque volet lit quand il
 * s'ouvre — l'arborescence un dossier à la fois, à la branche choisie ; les commits d'une branche ou de toutes, et leur
 * suite ; les pull requests ; les branches ; les issues ; les vérifications. Ses pages de détail le partagent (ses
 * droits, son dépôt distant, la branche choisie).
 */
class CodeViewModel(private val deps: ProjectsDeps, val id: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)

    private fun <T> kept(fetch: suspend () -> MoiApi.Result<T>) = Kept(viewModelScope, deps.now, gestures::say, fetch)

    val summary: Kept<CodeSummary> = kept { deps.api.code(id) }
    val branches: Kept<BranchList> = kept { deps.api.branches(id) }
    val pulls: Kept<PullPage> = kept { deps.api.pulls(id) }
    val issues: Kept<IssuePage> = kept { deps.api.issues(id) }
    val checks: Kept<ChecksList> = kept { deps.api.checks(id) }

    // ── Fichiers ──
    /** La branche dont on lit les fichiers (vide : la base). */
    var filesRef by mutableStateOf("")
        private set
    /** Les dossiers lus, par leur chemin, à la branche choisie. */
    var trees by mutableStateOf<Map<String, Load<Tree>>>(emptyMap())
        private set
    /** Les dossiers ouverts, à la branche choisie. */
    var open by mutableStateOf<Set<String>>(emptySet())
        private set

    // ── Commits ──
    /** La branche filtrée (vide : toutes). */
    var commitsRef by mutableStateOf("")
        private set
    var commits by mutableStateOf<Load<CommitPage>?>(null)
        private set
    /** Ceux des pages suivantes, déjà lus. */
    var moreCommits by mutableStateOf<List<Commit>>(emptyList())
        private set
    var loadingMore by mutableStateOf(false)
        private set

    private var started = false
    private var shown = CodeTabs.FILES
    private var commitsJob: Job? = null

    /** La branche des fichiers, par son nom : celle qu'on a choisie, sinon la base du dépôt. */
    val filesBranch: String get() = filesRef.ifEmpty { summary.value?.base.orEmpty() }

    val allCommits: List<Commit> get() = commits?.valueOrNull?.items.orEmpty() + moreCommits

    /** L'écran revient : le dépôt en bref, puis ce que le volet montré avait lu. */
    fun resume() {
        if (!started) {
            started = true
            summary.read()
        } else {
            summary.again()
            reread(force = false)
        }
    }

    /** Tirer pour relire : le dépôt en bref et le volet montré, l'hôte compris. */
    fun reload() {
        summary.read(quiet = false)
        reread(force = true)
    }

    private fun reread(force: Boolean) {
        when (shown) {
            CodeTabs.FILES -> {
                branches.again()
                trees.keys.toList().forEach { loadTree(it) }
            }
            CodeTabs.COMMITS -> {
                branches.again()
                if (commits != null) loadCommits()
            }
            CodeTabs.PULLS -> pulls.again()
            CodeTabs.BRANCHES -> branches.again()
            CodeTabs.ISSUES -> issues.again(if (force) 0 else HOST_AGE_MS)
            CodeTabs.CI -> checks.again()
        }
    }

    /** Un volet s'ouvre : ce qu'il montre se lit une fois, puis à chaque retour. */
    fun show(sub: String) {
        shown = sub
        when (sub) {
            CodeTabs.FILES -> {
                branches.open()
                if ("" !in trees) loadTree("")
            }
            CodeTabs.COMMITS -> {
                branches.open()
                if (commits == null) loadCommits()
            }
            CodeTabs.PULLS -> pulls.open()
            CodeTabs.BRANCHES -> branches.open()
            CodeTabs.ISSUES -> issues.open()
            CodeTabs.CI -> checks.open()
        }
    }

    // ── Fichiers ──

    /** Changer de branche : l'arborescence repart de sa racine. */
    fun pickFilesRef(name: String) {
        if (name == filesRef) return
        filesRef = name
        trees = emptyMap()
        open = emptySet()
        loadTree("")
    }

    /** Ouvrir ou replier un dossier ; il ne se lit qu'en s'ouvrant. */
    fun fold(dir: String) {
        if (dir in open) {
            open = open - dir
        } else {
            open = open + dir
            if (trees[dir] !is Load.Ready) loadTree(dir)
        }
    }

    fun loadTree(dir: String) {
        val ref = filesRef
        if (trees[dir] !is Load.Ready) trees = trees + (dir to Load.Loading)
        viewModelScope.launch {
            val got = deps.api.tree(id, ref, dir)
            // la branche a changé entre-temps : cette lecture ne vaut plus
            if (ref != filesRef) return@launch
            if (got is MoiApi.Result.Ok || trees[dir] !is Load.Ready) trees = trees + (dir to Load.of(got))
        }
    }

    // ── Commits ──

    fun pickCommitsRef(name: String) {
        if (name == commitsRef) return
        commitsRef = name
        commits = Load.Loading
        moreCommits = emptyList()
        loadCommits()
    }

    fun loadCommits(): Job {
        commitsJob?.cancel()
        if (commits !is Load.Ready) commits = Load.Loading
        val ref = commitsRef
        return viewModelScope.launch {
            val got = deps.api.commits(id, ref)
            if (got is MoiApi.Result.Ok) {
                commits = Load.Ready(got.value)
                // la première page relue : la suite déjà lue reste, sans redire ce que la page porte
                val known = got.value.items.map { it.sha }.toSet()
                moreCommits = moreCommits.filterNot { it.sha in known }
            } else if (commits !is Load.Ready) {
                commits = Load.of(got)
            }
        }.also { commitsJob = it }
    }

    /** La suite des commits : la page d'après, sans redire ce qu'on a déjà. */
    fun more() {
        val page = commits?.valueOrNull ?: return
        if (loadingMore || page.size <= 0) return
        loadingMore = true
        val ref = commitsRef
        viewModelScope.launch {
            when (val got = deps.api.commits(id, ref, allCommits.size / page.size + 1, page.size)) {
                is MoiApi.Result.Ok -> if (ref == commitsRef) {
                    val known = allCommits.map { it.sha }.toSet()
                    moreCommits = moreCommits + got.value.items.filterNot { it.sha in known }
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
            loadingMore = false
        }
    }

    /** « Ses fichiers », « Ses commits » depuis une branche : le volet s'ouvrira sur elle. */
    fun aim(sub: String, branch: String) {
        if (sub == CodeTabs.FILES) pickFilesRef(branch) else pickCommitsRef(branch)
    }
}

// ── Fusionner : une confirmation, puis la demande ───────────────────────

/**
 * La fusion d'une pull request, la même où qu'on la demande (sa page dans l'onglet Code, son attente d'« À faire ») :
 *
 * 1. [ask] **relit la pull request à l'instant** ; si le serveur ne l'ouvre plus (`merge.can`), sa raison se dit sur
 *    place et rien ne s'ouvre ;
 * 2. la confirmation ([asking]) dit ce qui va être fusionné — son titre, sa branche et sa base, ses commits, ses
 *    fichiers, où elle en est — et le commit de tête que la demande nommera ;
 * 3. [confirm] envoie la demande, par le seul chemin vers la route de la fusion (`ProjectsApi.merge`, sur le
 *    [MergeOrder] né de cette lecture). Refusée — la branche a bougé, l'hôte ne veut pas —, les mots du serveur se
 *    disent là où était le bouton.
 */
class MergeFlow(private val deps: ProjectsDeps, private val scope: CoroutineScope, private val gestures: GestureRunner) {
    /** Ce que la confirmation montre, et l'ordre qu'elle enverra. */
    class Asking internal constructor(val project: Int, val where: String, val facts: MergeFacts, internal val order: MergeOrder)

    var asking by mutableStateOf<Asking?>(null)
        private set
    /** La pull request se relit avant sa confirmation. */
    var reading by mutableStateOf(false)
        private set

    /** Demander la fusion : relire, puis ouvrir la confirmation. [moved] : ce qu'on vient de lire ne permet pas de fusionner. */
    fun ask(project: Int, number: Int, objective: Int, where: String, moved: () -> Unit = {}) {
        if (reading || asking != null || gestures.busy.isNotEmpty()) return
        reading = true
        gestures.forget(where)
        scope.launch {
            val got = deps.api.pull(project, number, objective)
            reading = false
            when (got) {
                is MoiApi.Result.Failed -> gestures.refuse(where, got.error)
                is MoiApi.Result.Ok -> {
                    val order = MergeOrder.of(got.value)
                    if (order == null) {
                        gestures.refuse(where, MoiError(409, got.value.pull.merge.why.ifBlank { MERGE_NOT_NOW }))
                        moved()
                    } else {
                        asking = Asking(project, where, mergeFacts(got.value), order)
                    }
                }
            }
        }
    }

    fun cancel() {
        asking = null
    }

    /** La personne a confirmé : la demande part, en nommant le commit de tête que la confirmation montrait. */
    fun confirm(after: suspend (GestureDone) -> Unit = {}, failed: suspend (MoiError) -> Unit = {}) {
        val a = asking ?: return
        asking = null
        gestures.run(a.where, a.order.body, { key -> deps.api.merge(a.project, a.order, key) }, failed = failed, after = after)
    }
}

/** Les fichiers d'un diff coupé qu'on relit seuls (`path=`), par leur chemin. */
class WholeFiles(private val scope: CoroutineScope, private val fetch: suspend (path: String) -> MoiApi.Result<Diff>) {
    var files by mutableStateOf<Map<String, Load<DiffFile>>>(emptyMap())
        private set

    fun read(path: String) {
        if (files[path] is Load.Loading || files[path] is Load.Ready) return
        files = files + (path to Load.Loading)
        scope.launch {
            files = files + (
                path to when (val got = fetch(path)) {
                    is MoiApi.Result.Failed -> Load.Failed(got.error)
                    is MoiApi.Result.Ok -> got.value.files.firstOrNull { it.path == path }?.let { Load.Ready(it) }
                        ?: Load.Failed(MoiError(404, got.value.filesWhy.ifBlank { MoiError.NETWORK }))
                }
                )
        }
    }

    fun forget() {
        files = emptyMap()
    }
}

// ── Les pages qui ne font que lire ──────────────────────────────────────

/** Une page qui ne fait que lire une chose du code (un fichier, une branche) : lue à l'ouverture, relue à chaque retour. */
class CodeReadViewModel<T>(deps: ProjectsDeps, fetch: suspend (ProjectsApi) -> MoiApi.Result<T>) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val read: Kept<T> = Kept(viewModelScope, deps.now, gestures::say) { fetch(deps.api) }

    fun resume() {
        if (read.load == null) read.read() else read.again()
    }
}

/** Un fichier à une référence. */
internal fun fileModel(deps: ProjectsDeps, project: Int, ref: String, path: String) = CodeReadViewModel<Blob>(deps) { it.blob(project, ref, path) }

/** Une branche : ce qu'elle a d'avance, ses fichiers changés. */
internal fun branchModel(deps: ProjectsDeps, project: Int, name: String) = CodeReadViewModel<BranchDetail>(deps) { it.branch(project, name) }

/** Un commit : lui, ce qui lui est lié, son diff — et ses fichiers coupés, relus seuls à la demande. */
class CommitViewModel(deps: ProjectsDeps, val project: Int, val sha: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val detail: Kept<CommitDetail> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.commit(project, sha) }
    val whole = WholeFiles(viewModelScope) { path ->
        when (val got = deps.api.commit(project, sha, path)) {
            is MoiApi.Result.Ok -> MoiApi.Result.Ok(got.value.diff)
            is MoiApi.Result.Failed -> got
        }
    }

    fun resume() {
        if (detail.load == null) detail.read() else detail.again()
    }
}

// ── Une pull request ────────────────────────────────────────────────────

/**
 * Une pull request ouverte ([key] : son numéro, ou `o<objectif>` tant qu'elle n'en a pas) : ce que le journal et
 * l'atelier en savent ([detail] — dont `pull.head`), ce que l'hôte en dit maintenant ([host] : son titre, son texte,
 * ses échanges, ses vérifications une à une), et ses gestes — la modifier, y répondre, la fusionner. [revision] compte
 * ses gestes aboutis ou refusés : l'onglet et la fiche se relisent alors.
 */
class PullViewModel(private val deps: ProjectsDeps, val project: Int, val key: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val merge = MergeFlow(deps, viewModelScope, gestures)
    private val named = parsePullKey(key)

    val detail: Kept<PullDetail> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.pull(project, named.number, named.objective) }
    val host: Kept<PullHost> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.pullHost(project, number) }
    val whole = WholeFiles(viewModelScope) { path ->
        when (val got = deps.api.pull(project, named.number, named.objective, path)) {
            is MoiApi.Result.Ok -> MoiApi.Result.Ok(got.value.diff)
            is MoiApi.Result.Failed -> got
        }
    }

    /** Sa réponse en cours d'écriture, dans Échanges. */
    var reply by mutableStateOf("")
    var revision by mutableIntStateOf(0)
        private set

    /** Son numéro chez l'hôte : celui de son adresse, sinon celui qu'on vient de lire (0 : elle n'en a pas encore). */
    val number: Int get() = detail.value?.pull?.number?.takeIf { it > 0 } ?: named.number

    fun resume() {
        if (detail.load == null) detail.read() else detail.again()
        host.again(HOST_AGE_MS)
    }

    /** Ce que l'hôte en dit : demandé une fois qu'on la sait chez lui (un numéro, un dépôt distant). */
    fun openHost() {
        if (number > 0) host.open()
    }

    private fun changed() {
        revision++
        detail.read()
        whole.forget()
        if (host.load != null) host.read()
    }

    /** Demander sa fusion : elle se relit, puis la confirmation s'ouvre. */
    fun askMerge() {
        merge.ask(project, named.number, named.objective, MERGE) { changed() }
    }

    fun confirmMerge() {
        merge.confirm(after = { changed() }, failed = { changed() })
    }

    /** Ce que l'hôte dit de son titre et de son texte, à défaut ce que le moteur en sait : d'où part « Modifier ». */
    fun editable(): Pair<String, String> {
        val seen = host.value
        return hostText(seen?.title).ifBlank { detail.value?.pull?.title.orEmpty() } to hostText(seen?.body)
    }

    /** Modifier son titre et son texte chez l'hôte : seulement ce qui change de ce qu'on a relu. */
    fun edit(title: String, body: String) {
        val (beforeTitle, beforeBody) = editable()
        gestures.send(project, pullEditRequest(number, title, body, beforeTitle, beforeBody), EDIT) { changed() }
    }

    /** Répondre dans la pull request : le commentaire part chez l'hôte. */
    fun comment() {
        if (reply.isBlank() || number <= 0) return
        gestures.send(project, pullCommentRequest(number, reply), TALK) {
            reply = ""
            changed()
        }
    }

    companion object {
        /** Sa fusion : le bouton, et ce que le serveur en refuse. */
        const val MERGE = "pull-merge"
        const val EDIT = "pull-edit"
        const val TALK = "pull-talk"
    }
}

// ── Une issue ───────────────────────────────────────────────────────────

/**
 * Une issue du dépôt : ce que l'hôte en dit, le ticket qui la reflète — lu dans le registre, pour ce qu'elle peut en
 * faire (`can` : l'accepter, l'écarter) et ce qui lui est lié — et ce qui attend son accord à son sujet (une réponse à
 * publier : `concerns.issue`).
 */
class IssueViewModel(private val deps: ProjectsDeps, val project: Int, val number: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val issue: Kept<Issue> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.issue(project, number) }
    val approvals: Kept<Approvals> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.approvals(project) }
    val ticket: Kept<EntryDetail> = Kept(viewModelScope, deps.now, gestures::say) {
        deps.api.element(project, ProjectsApi.TICKETS, "#${issue.value?.ticket?.number ?: 0}")
    }
    var revision by mutableIntStateOf(0)
        private set
    private var started = false

    /** Ce qui attend son accord sur cette issue. */
    val waiting: List<Approval> get() = approvals.value?.items.orEmpty().filter { it.concerns.issue == number }

    /** Le ticket lié, tel que le registre le sert ; `null` : aucun, pas encore lu, ou une issue qu'elle ne lit pas. */
    val entry: EntryDetail? get() = ticket.value?.takeIf { it.line.number != 0 && it.line.number == issue.value?.ticket?.number }

    /** [approve] : elle peut donner un accord dans ce projet (`rights.approve`) — sinon rien ne s'en demande. */
    fun resume(approve: Boolean) {
        val first = !started
        started = true
        viewModelScope.launch {
            if (first) issue.read().join() else issue.again(HOST_AGE_MS)
            readTicket()
        }
        if (approve) approvals.read()
    }

    private fun readTicket() {
        val x = issue.value ?: return
        if (x.ticket != null && x.veiled.isEmpty()) ticket.read()
    }

    private fun changed() {
        revision++
        viewModelScope.launch {
            issue.read().join()
            readTicket()
        }
    }

    /** Trancher le ticket proposé d'ici : l'accepter, l'écarter — les gestes du ticket lui-même. */
    fun settle(verdict: String, reason: String = "") {
        val e = entry ?: return
        gestures.send(project, settleRequest(e.line, verdict, reason), TICKET) { changed() }
    }

    companion object {
        const val TICKET = "issue-ticket"
    }
}

// ── Les vérifications d'un commit ───────────────────────────────────────

/**
 * Les vérifications d'un commit : celles que le moteur suit ([tracked], lues dans la liste), et ce que l'hôte en dit
 * maintenant ([live]) — relu seulement si le projet a un dépôt distant.
 */
class ChecksViewModel(private val deps: ProjectsDeps, val project: Int, val sha: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val list: Kept<ChecksList> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.checks(project) }
    val live: Kept<HostChecks> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.commitChecks(project, tracked?.sha ?: sha) }

    val tracked: TrackedChecks? get() = bySha(list.value?.items.orEmpty(), sha) { it.sha }

    fun resume(remote: Boolean) {
        viewModelScope.launch {
            if (list.load == null) list.read().join() else list.again()
            if (remote) {
                if (live.load == null) live.read() else live.again(HOST_AGE_MS)
            }
        }
    }
}
