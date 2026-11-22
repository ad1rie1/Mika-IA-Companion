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
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import fr.qwartz.mika.data.moi.projects.isMarkdown
import fr.qwartz.mika.ui.components.ProMarkdown
import kotlinx.coroutines.withContext
import kotlinx.coroutines.CoroutineDispatcher

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
 * qui échoue garde ce qui était montré — et le dit, si on l'a demandée. Tant qu'une relecture n'a pas abouti, ce qu'on
 * montre date d'avant elle ([stale], [staleError]) : un modèle dont les gestes en dépendent n'en laisse partir aucun.
 */
class Kept<T>(
    private val scope: CoroutineScope,
    private val now: () -> Long,
    private val say: (String) -> Unit,
    private val fetch: suspend () -> MoiApi.Result<T>,
) {
    var load by mutableStateOf<Load<T>?>(null)
        private set
    /** Ce qu'on montre se relit, ou sa relecture a échoué : il date d'avant. */
    var stale by mutableStateOf(false)
        private set
    /** Sa relecture a échoué : l'erreur, à dire avec « Réessayer ». */
    var staleError by mutableStateOf<MoiError?>(null)
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
        if (load is Load.Ready) stale = true else load = Load.Loading
        staleError = null
        return scope.launch {
            when (val got = fetch()) {
                is MoiApi.Result.Ok -> {
                    readAt = now()
                    load = Load.Ready(got.value)
                    stale = false
                }
                is MoiApi.Result.Failed -> if (load is Load.Ready) {
                    staleError = got.error
                    if (!quiet) say(got.error.said)
                } else {
                    load = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }

    /**
     * Relire ce qui a déjà été demandé — sauf si c'est lu depuis moins de [maxAgeMs] (ce que l'hôte est seul à savoir).
     * Rend la lecture à attendre : celle qui part, ou celle qui est encore en cours ; `null` : rien ne se lit.
     */
    fun again(maxAgeMs: Long = 0): Job? {
        if (load == null) return null
        if (maxAgeMs > 0 && load is Load.Ready && now() - readAt < maxAgeMs) return job?.takeIf { it.isActive }
        return read()
    }

    /** Un geste vient de changer ce qu'on a lu : le prochain [again] relit, quel que soit son âge. */
    fun expire() {
        readAt = 0
    }

    fun retry() {
        load = Load.Loading
        read(quiet = false)
    }

    fun forget() {
        job?.cancel()
        load = null
        stale = false
        staleError = null
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
    /** Les pages de commits lues, la première comprise. */
    private var commitPages = 1
    /** La dernière page demandée n'était pas pleine : il n'y a pas de suite. */
    private var commitsEnded by mutableStateOf(false)

    private var started = false
    private var shown = CodeTabs.FILES
    private var commitsJob: Job? = null

    /** La branche des fichiers, par son nom : celle qu'on a choisie, sinon la base du dépôt. */
    val filesBranch: String get() = filesRef.ifEmpty { summary.value?.base.orEmpty() }

    val allCommits: List<Commit> get() = commits?.valueOrNull?.items.orEmpty() + moreCommits

    /** Ce qu'il reste à lire des commits (0 : tout est lu, ou la dernière page l'a dit). */
    val commitsRest: Int get() = if (commitsEnded) 0 else ((commits?.valueOrNull?.total ?: 0) - allCommits.size).coerceAtLeast(0)

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
        dropMoreCommits()
        loadCommits()
    }

    private fun dropMoreCommits() {
        moreCommits = emptyList()
        commitPages = 1
        commitsEnded = false
    }

    fun loadCommits(): Job {
        commitsJob?.cancel()
        if (commits !is Load.Ready) commits = Load.Loading
        val ref = commitsRef
        return viewModelScope.launch {
            val got = deps.api.commits(id, ref)
            if (got is MoiApi.Result.Ok) {
                // la première page a changé (un commit de plus, une branche qui a bougé) : la suite lue ne lui fait
                // plus suite — la garder laisserait un trou entre les deux ; inchangée, la suite reste
                val before = commits?.valueOrNull
                if (before == null || before.total != got.value.total || before.items.map { it.sha } != got.value.items.map { it.sha }) dropMoreCommits()
                commits = Load.Ready(got.value)
            } else if (commits !is Load.Ready) {
                commits = Load.of(got)
            }
        }.also { commitsJob = it }
    }

    /** La suite des commits : la page d'après celles qu'on a lues (comptées), sans redire ce qu'on a déjà. */
    fun more() {
        val page = commits?.valueOrNull ?: return
        if (loadingMore || page.size <= 0 || commitsRest <= 0) return
        loadingMore = true
        val ref = commitsRef
        val asked = commitPages + 1
        viewModelScope.launch {
            when (val got = deps.api.commits(id, ref, asked, page.size)) {
                // la branche a changé, ou la première page (et sa suite a été vidée) : cette page n'est plus la suivante
                is MoiApi.Result.Ok -> if (ref == commitsRef && asked == commitPages + 1) {
                    commitPages = asked
                    val known = allCommits.map { it.sha }.toSet()
                    moreCommits = moreCommits + got.value.items.filterNot { it.sha in known }
                    if (got.value.items.size < page.size) commitsEnded = true
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
 *
 * La confirmation n'appartient qu'à l'écran qui l'a demandée ([Asking.where]) : il ne montre que la sienne, et
 * [cancel] l'annule quand on le quitte ou qu'il change de cible.
 */
class MergeFlow(private val deps: ProjectsDeps, private val scope: CoroutineScope, private val gestures: GestureRunner) {
    /** Ce que la confirmation montre, et l'ordre qu'elle enverra. */
    class Asking internal constructor(val project: Int, val where: String, val facts: MergeFacts, internal val order: MergeOrder)

    var asking by mutableStateOf<Asking?>(null)
        private set
    /** La pull request se relit avant sa confirmation. */
    var reading by mutableStateOf(false)
        private set

    private var job: Job? = null

    /**
     * Demander la fusion : relire, puis ouvrir la confirmation — pour l'écran qui la demande ([where]), sur la lecture
     * faite pour elle. [moved] : ce qu'on vient de lire ne permet pas de fusionner.
     */
    fun ask(project: Int, number: Int, objective: Int, where: String, moved: () -> Unit = {}) {
        if (reading || asking != null || gestures.busy.isNotEmpty()) return
        reading = true
        gestures.forget(where)
        job = scope.launch {
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

    /**
     * Annuler : la personne renonce, l'écran est quitté, ou il change de cible. La relecture en cours s'abandonne — une
     * confirmation ne s'ouvre jamais après coup, ailleurs, sur une lecture qui n'est plus celle de l'écran.
     */
    fun cancel() {
        job?.cancel()
        job = null
        reading = false
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

/**
 * Ce qui pèse dans une lecture réussie — un fichier ou un diff mis en lignes, une page découpée — se fait sur [on]
 * (`ProjectsDeps.compute`), **jamais sur le fil principal**, avant que la lecture soit montrée : l'écran ne fait que
 * poser ce qui est déjà calculé. Rend ce que [work] calcule ; `null` pour une lecture refusée.
 */
internal suspend fun <T, R> MoiApi.Result<T>.weighed(on: CoroutineDispatcher, work: (T) -> R): R? =
    (this as? MoiApi.Result.Ok)?.let { withContext(on) { work(it.value) } }

/**
 * Un fichier à une référence : lu à l'ouverture, relu à chaque retour. Ses lignes sont mises en place (`Blob.laid`) et,
 * pour un fichier Markdown, ses blocs lus ([rendered]) hors du fil principal, avant qu'il soit montré.
 */
class FileViewModel(deps: ProjectsDeps, project: Int, ref: String, path: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)

    /** Les blocs d'un fichier Markdown lisible, tels qu'on les montre (aucun lien ne s'y ouvre) ; vide sinon. */
    var rendered by mutableStateOf<List<ProMarkdown.Block>>(emptyList())
        private set

    val read: Kept<Blob> = Kept(viewModelScope, deps.now, gestures::say) {
        val got = deps.api.blob(project, ref, path)
        got.weighed(deps.compute) { blob ->
            blob.laid
            if (blob.readable && isMarkdown(blob.path)) repoMarkdown(blob.text) else emptyList()
        }?.let { rendered = it }
        got
    }

    fun resume() {
        if (read.load == null) read.read() else read.again()
    }
}

/** Une branche : ce qu'elle a d'avance, ses fichiers changés. */
internal fun branchModel(deps: ProjectsDeps, project: Int, name: String) = CodeReadViewModel<BranchDetail>(deps) { it.branch(project, name) }

/** Un commit : lui, ce qui lui est lié, son diff — et ses fichiers coupés, relus seuls à la demande. */
class CommitViewModel(deps: ProjectsDeps, val project: Int, val sha: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    // son diff est mis en rangées hors du fil principal, avant d'être montré
    val detail: Kept<CommitDetail> = Kept(viewModelScope, deps.now, gestures::say) {
        deps.api.commit(project, sha).also { got -> got.weighed(deps.compute) { it.diff.lay() } }
    }
    val whole = WholeFiles(viewModelScope) { path ->
        when (val got = deps.api.commit(project, sha, path)) {
            is MoiApi.Result.Ok -> MoiApi.Result.Ok(got.value.diff).also { it.weighed(deps.compute) { d -> d.lay() } }
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

    // son diff est mis en rangées hors du fil principal, avant d'être montré
    val detail: Kept<PullDetail> = Kept(viewModelScope, deps.now, gestures::say) {
        deps.api.pull(project, named.number, named.objective).also { got -> got.weighed(deps.compute) { it.diff.lay() } }
    }
    val host: Kept<PullHost> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.pullHost(project, number) }
    val whole = WholeFiles(viewModelScope) { path ->
        when (val got = deps.api.pull(project, named.number, named.objective, path)) {
            is MoiApi.Result.Ok -> MoiApi.Result.Ok(got.value.diff).also { it.weighed(deps.compute) { d -> d.lay() } }
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

    private var settling: Job? = null

    /**
     * Après un geste. Ce que le journal en sait se relit tout de suite. Mais un geste chez l'hôte — y répondre, la
     * modifier, la fusionner — n'y arrive qu'**après** la réponse du serveur (il ne fait que le demander : son effet
     * part une fois le geste enregistré) : relu à l'instant, l'hôte ne le montrerait pas encore, et cette lecture
     * toute fraîche empêcherait de le relire avant [HOST_AGE_MS]. Il se relit donc un peu plus tard, deux fois
     * ([HOST_SETTLES_MS]) — la pull request avec lui (son état après une fusion) —, et le prochain retour sur l'écran
     * le relit aussi, quel que soit son âge.
     */
    private fun changed() {
        revision++
        detail.read()
        whole.forget()
        host.expire()
        settling?.cancel()
        settling = viewModelScope.launch {
            for (wait in HOST_SETTLES_MS) {
                delay(wait)
                detail.read()
                if (host.load != null) host.read().join()
                host.expire()
            }
        }
    }

    /** L'écran est quitté : la confirmation d'une fusion demandée là s'annule. */
    fun leave() {
        merge.cancel()
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

    /**
     * Modifier son titre et son texte chez l'hôte : seulement ce qui change de ce dont le formulaire est parti
     * ([from] : ce que [editable] rendait quand il s'est rempli). L'hôte relu depuis — il était muet, ou quelqu'un l'a
     * retouchée — ne fait partir ni effacer un champ qu'elle n'a pas touché.
     */
    fun edit(title: String, body: String, from: Pair<String, String> = editable()) {
        gestures.send(project, pullEditRequest(number, title, body, from.first, from.second), EDIT) { changed() }
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

        /** Après un geste chez l'hôte : dans combien de temps le relire, puis encore (l'effet part après la réponse). */
        internal val HOST_SETTLES_MS = listOf(2_000L, 6_000L)
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
    /** Les relectures parties dont le ticket n'est pas encore redemandé au registre (l'issue se relit d'abord). */
    private var rereads by mutableIntStateOf(0)

    /**
     * Le ticket lié montré date d'avant — l'écran revient devant, un geste vient d'aboutir ou d'être refusé — et se
     * relit (l'issue d'abord, puis lui) : tant que le registre n'a pas redit ce qu'elle peut en faire, il ne se tranche
     * pas d'ici.
     */
    val stale: Boolean get() = rereads > 0 || ticket.stale

    /** La relecture de son ticket a échoué : on le dit, et « Réessayer » ([reread]). */
    val staleError: MoiError? get() = ticket.staleError

    /** Ce qui attend son accord sur cette issue. */
    val waiting: List<Approval> get() = approvals.value?.items.orEmpty().filter { it.concerns.issue == number }

    /** Le ticket lié, tel que le registre le sert ; `null` : aucun, pas encore lu, ou une issue qu'elle ne lit pas. */
    val entry: EntryDetail? get() = ticket.value?.takeIf { it.line.number != 0 && it.line.number == issue.value?.ticket?.number }

    /** [approve] : elle peut donner un accord dans ce projet (`rights.approve`) — sinon rien ne s'en demande. */
    fun resume(approve: Boolean) {
        val first = !started
        started = true
        // son ticket se lit dans le registre une fois l'issue lue : la lecture qui part, ou celle déjà en cours
        // (un second retour pendant la première lecture la relance) — jamais avant elle
        relit { if (first) issue.read() else issue.again(HOST_AGE_MS) }
        if (approve) approvals.read()
    }

    /** L'issue ([first]), puis son ticket ; d'ici à ce qu'il soit redemandé, celui qu'on montre date d'avant ([stale]). */
    private fun relit(first: () -> Job?) {
        rereads++
        viewModelScope.launch {
            try {
                first()?.join()
                readTicket()
            } finally {
                rereads--
            }
        }
    }

    private fun readTicket() {
        val x = issue.value ?: return
        if (x.ticket != null && x.veiled.isEmpty()) ticket.read()
    }

    private fun changed() {
        revision++
        relit { issue.read() }
    }

    /** « Réessayer », après une relecture de son ticket qui a échoué. */
    fun reread() {
        relit { issue.again(HOST_AGE_MS) }
    }

    /**
     * Trancher le ticket proposé d'ici : l'accepter, l'écarter — les gestes du ticket lui-même. Faux : rien n'est parti
     * (il se relit, un autre geste attend sa réponse).
     */
    fun settle(verdict: String, reason: String = ""): Boolean {
        val e = entry ?: return false
        if (stale) return false
        return gestures.send(project, settleRequest(e.line, verdict, reason), TICKET, failed = { changed() }) { changed() }
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
