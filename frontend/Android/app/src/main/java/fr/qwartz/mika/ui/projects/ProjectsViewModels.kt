package fr.qwartz.mika.ui.projects

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.projects.ActivityPage
import fr.qwartz.mika.data.moi.projects.Approval
import fr.qwartz.mika.data.moi.projects.Approvals
import fr.qwartz.mika.data.moi.projects.Archives
import fr.qwartz.mika.data.moi.projects.Diagram
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.EntryHistory
import fr.qwartz.mika.data.moi.projects.EntryPage
import fr.qwartz.mika.data.moi.projects.GestureDone
import fr.qwartz.mika.data.moi.projects.GestureRead
import fr.qwartz.mika.data.moi.projects.GestureRequest
import fr.qwartz.mika.data.moi.projects.Goal
import fr.qwartz.mika.data.moi.projects.GoalForm
import fr.qwartz.mika.data.moi.projects.Happening
import fr.qwartz.mika.data.moi.projects.MilestoneForm
import fr.qwartz.mika.data.moi.projects.NewProject
import fr.qwartz.mika.data.moi.projects.Overview
import fr.qwartz.mika.data.moi.projects.ProjectsApi
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.TicketFilters
import fr.qwartz.mika.data.moi.projects.TicketForm
import fr.qwartz.mika.data.moi.projects.Waiting
import fr.qwartz.mika.data.moi.projects.checkpointRequest
import fr.qwartz.mika.data.moi.projects.gestureRead
import fr.qwartz.mika.data.moi.projects.mergeNumber
import fr.qwartz.mika.data.moi.projects.goalRequest
import fr.qwartz.mika.data.moi.projects.milestoneDropRequest
import fr.qwartz.mika.data.moi.projects.milestoneRequest
import fr.qwartz.mika.data.moi.projects.newProjectBody
import fr.qwartz.mika.data.moi.projects.noteRequest
import fr.qwartz.mika.data.moi.projects.objectiveStatusRequest
import fr.qwartz.mika.data.moi.projects.pilotRequest
import fr.qwartz.mika.data.moi.projects.refusalWords
import fr.qwartz.mika.data.moi.projects.restoreRequest
import fr.qwartz.mika.data.moi.projects.settleRequest
import fr.qwartz.mika.data.moi.projects.ticketRequest
import fr.qwartz.mika.data.moi.projects.todoRequest
import fr.qwartz.mika.data.moi.projects.waitingKey
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Les modèles de l'écran Projets (ADR 0296) : ce que chaque vue a lu, ce qui est choisi, et ses gestes. Aucun ne décide
 * de ce qu'on peut faire : un bouton n'existe que si le serveur l'ouvre (`can`, `rights`), et un geste refusé se dit
 * sur place, avec ses mots ([Refusal]). Ils prennent ce qu'il leur faut par [ProjectsDeps] et se testent sur la JVM
 * contre une fausse API.
 */

/** Ce dont un modèle de Projets a besoin : l'API, relire les pastilles du tiroir, l'heure. */
class ProjectsDeps(
    val api: ProjectsApi,
    val refreshBadges: () -> Unit = {},
    val now: () -> Long = System::currentTimeMillis,
) {
    /** Une image téléversée part par le client sans délai global (un fichier lourd sur une liaison faible), comme une pièce de Mail. */
    constructor(graph: AppGraph) : this(
        ProjectsApi(graph.moi, MoiApi(graph.filesHttp, { graph.auth.credentials() }, { graph.auth.checkAfterUnauthorized() })),
        { graph.me.refresh() },
        { graph.clock.wallMs() },
    )
}

/** Un refus du serveur, dit sur place : où ([where], la clé de l'endroit), ses mots, et ce qu'il dit champ par champ. */
data class Refusal(val where: String, val text: String, val fields: Map<String, String> = emptyMap())

/**
 * Les gestes d'un modèle, l'un après l'autre : celui qui part ([busy] : ses boutons attendent), son refus dit à son
 * endroit ([refusal]), son sort dit en toast ([said]), et l'endroit du dernier geste abouti ([finished] : l'écran y
 * ferme sa feuille, puis [acknowledge]). Chaque endroit a sa clé d'envoi : un double appui ne part qu'une fois, un
 * réessai après une coupure ne refait rien.
 */
class GestureRunner(private val deps: ProjectsDeps, private val scope: CoroutineScope) {
    var refusal by mutableStateOf<Refusal?>(null)
        private set
    var busy by mutableStateOf("")
        private set
    var finished by mutableStateOf<String?>(null)
        private set

    private val notices = Channel<String>(Channel.BUFFERED)
    val said: Flow<String> = notices.receiveAsFlow()
    private val keys = HashMap<String, SendKey>()

    fun refusalAt(where: String): String = refusal?.takeIf { it.where == where }?.text.orEmpty()

    fun fieldsAt(where: String): Map<String, String> = refusal?.takeIf { it.where == where }?.fields.orEmpty()

    /** Une feuille qui s'ouvre, une vue qu'on quitte : ce qu'on y avait dit ne vaut plus. */
    fun forget(where: String) {
        if (refusal?.where == where) refusal = null
        if (finished == where) finished = null
    }

    fun acknowledge() {
        finished = null
    }

    fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    /** Un refus dit à cet endroit sans qu'un geste soit parti : une lecture d'avant le geste qui échoue, ou qui dit non. */
    fun refuse(where: String, error: MoiError) {
        refusal = Refusal(where, refusalWords(error.message, error.fields), error.fields)
    }

    /**
     * Un geste dans un projet. Rien ne part pendant qu'un autre attend sa réponse, ni sans route (une attente dont le
     * geste ne se fait pas par un bouton générique : la fusion, qui a sa confirmation — [MergeFlow]).
     */
    fun send(project: Int, request: GestureRequest, where: String, after: suspend (GestureDone) -> Unit = {}): Boolean =
        request.route.isNotEmpty() && run(where, request, { key -> deps.api.gesture(project, request, key) }, after = after)

    /**
     * Une écriture qui n'est pas un geste générique (lui confier un projet, fusionner) : [content] est ce qu'elle
     * envoie ; [failed] : ce qui suit un refus (relire ce qu'on montrait).
     */
    fun run(
        where: String,
        content: Any,
        call: suspend (key: String) -> MoiApi.Result<GestureDone>,
        failed: suspend (MoiError) -> Unit = {},
        after: suspend (GestureDone) -> Unit = {},
    ): Boolean {
        if (busy.isNotEmpty()) return false
        busy = where
        refusal = null
        scope.launch {
            val key = keys.getOrPut(where) { SendKey() }
            val got = call(key.of(content))
            key.settled(networkFailure = (got as? MoiApi.Result.Failed)?.error?.network == true)
            busy = ""
            when (got) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    deps.refreshBadges()
                    finished = where
                    after(got.value)
                }
                is MoiApi.Result.Failed -> {
                    refuse(where, got.error)
                    failed(got.error)
                }
            }
        }
        return true
    }
}

// ── La rubrique : À faire, Projets ──────────────────────────────────────

/**
 * La rubrique « Projets », une fois pour la session : ses projets et ce qui l'y attend (`GET /api/moi/projets`), la
 * suite d'« À faire », « Nouveau projet », et l'attente ouverte — ce que son geste demande de lire, puis sa décision.
 */
class ProjectsViewModel(private val deps: ProjectsDeps) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)

    /** Fusionner la pull request prête d'une attente : la même confirmation que dans l'onglet Code. */
    val merge = MergeFlow(deps, viewModelScope, gestures)

    var overview by mutableStateOf<Load<Overview>>(Load.Loading)
        private set
    /** Les attentes lues : la première page, puis la suite. */
    var todo by mutableStateOf<List<Waiting>>(emptyList())
        private set
    var refreshing by mutableStateOf(false)
        private set
    var loadingMore by mutableStateOf(false)
        private set
    /** « À faire » : le projet filtré (0 : tous). */
    var filter by mutableIntStateOf(0)
        private set
    /** « Nouveau projet » : ses champs, tels que le serveur les décrit ; `null` : la feuille est fermée. */
    var fresh by mutableStateOf<Load<NewProject>?>(null)
        private set
    /** Le projet qui vient d'être confié, à ouvrir (une fois). */
    var created by mutableIntStateOf(0)
        private set
    /** Les projets archivés qu'elle peut restaurer (`GET …/projets/archives`). */
    val archives: Kept<Archives> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.archives() }
    /** Le projet qui vient d'être désarchivé, à ouvrir (une fois). */
    var restored by mutableIntStateOf(0)
        private set

    // ── L'attente ouverte ──
    /** L'attente ouverte, telle qu'on l'a lue en dernier ; `null` tant qu'elle n'est pas trouvée. */
    var shown by mutableStateOf<Waiting?>(null)
        private set
    /** Elle n'est plus dans « À faire » : décidée ailleurs, ou plus à elle. */
    var missing by mutableStateOf(false)
        private set
    var approvals by mutableStateOf<Load<Approvals>?>(null)
        private set
    var sheet by mutableStateOf<Load<Sheet>?>(null)
        private set
    var element by mutableStateOf<Load<EntryDetail>?>(null)
        private set
    /** Sa réponse à une question, tapée sur place. */
    var answer by mutableStateOf("")

    private var opened: Pair<Int, String>? = null
    private var started = false
    private var job: Job? = null
    private var readJob: Job? = null

    val todoTotal: Int get() = overview.valueOrNull?.todoTotal ?: 0

    /** L'accord que l'attente ouverte demande de lire : exactement ce qui partirait. */
    val approval: Approval?
        get() = (shown?.let { gestureRead(it) } as? GestureRead.Accord)?.let { r -> approvals?.valueOrNull?.items?.firstOrNull { it.id == r.id } }

    /** L'écran revient : tout lire la première fois, sinon relire sans bruit. */
    fun resume() {
        val first = !started
        started = true
        load(quiet = !first)
        archives.read()
    }

    /** Désarchiver un projet : il revient, en pause ; un refus se dit sous sa ligne. */
    fun restore(project: Int) {
        gestures.send(project, restoreRequest(), restoreWhere(project)) {
            restored = project
            archives.read()
            load(quiet = true)
        }
    }

    fun restoredOpened() {
        restored = 0
    }

    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(quiet = false).join()
            refreshing = false
        }
    }

    fun retry() {
        overview = Load.Loading
        load(quiet = false)
    }

    /** Un projet filtré se retire en le touchant de nouveau (0 : tous). */
    fun pick(project: Int) {
        filter = if (filter == project) 0 else project
    }

    /** « Tout voir » depuis une fiche : « À faire » s'ouvre sur ce projet. */
    fun showOnly(project: Int) {
        filter = project
    }

    /** La suite d'« À faire » : la page d'après, sans redire ce qu'on a déjà. */
    fun more() {
        if (loadingMore) return
        loadingMore = true
        viewModelScope.launch {
            when (val got = deps.api.todo(todo.size / TODO_PAGE + 1)) {
                is MoiApi.Result.Ok -> {
                    val known = todo.map { it.project to waitingKey(it) }.toSet()
                    todo = todo + got.value.items.filterNot { (it.project to waitingKey(it)) in known }
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
            loadingMore = false
        }
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            when (val got = deps.api.overview()) {
                is MoiApi.Result.Ok -> {
                    overview = Load.Ready(got.value)
                    todo = got.value.todo
                    if (filter != 0 && todo.none { it.project == filter }) filter = 0
                    found()
                }
                // une relecture qui échoue garde ce qui était montré
                is MoiApi.Result.Failed -> if (overview is Load.Ready) {
                    if (!quiet) gestures.say(got.error.said)
                } else {
                    overview = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }

    // ── Nouveau projet ──

    fun openNew() {
        gestures.forget(NEW)
        fresh = Load.Loading
        viewModelScope.launch { if (fresh != null) fresh = Load.of(deps.api.newProject()) }
    }

    fun closeNew() {
        fresh = null
    }

    /** Lui confier un projet : ce qui est saisi, par le nom de chaque champ servi. */
    fun create(values: Map<String, String>) {
        val form = fresh?.valueOrNull ?: return
        val body = newProjectBody(form.fields, values)
        gestures.run(NEW, body, { key -> deps.api.create(body, key) }) { done ->
            fresh = null
            created = done.project
            load(quiet = true)
        }
    }

    fun createdOpened() {
        created = 0
    }

    // ── L'attente ouverte ──

    /** Ouvrir une attente : la retrouver dans « À faire », puis lire ce que son geste demande. */
    fun open(project: Int, key: String) {
        val target = project to key
        if (opened != target) {
            opened = target
            shown = null
            missing = false
            approvals = null
            sheet = null
            element = null
            answer = ""
            gestures.forget(todoWhere(project, key))
        }
        if (!started) resume() else found()
    }

    /**
     * L'attente ouverte, dans ce qu'on vient de lire ; hors de la liste lue, celle qu'on montrait reste. Jamais vue
     * (elle est plus loin que la première page d'« À faire », ou l'écran renaît), elle se cherche dans la fiche de son
     * projet, qui rend tout ce qui y attend ; absente là aussi, elle n'est plus à faire.
     */
    private fun found() {
        val (project, key) = opened ?: return
        val now = todo.firstOrNull { it.project == project && waitingKey(it) == key }
        if (now != null) {
            val first = shown == null
            shown = now
            missing = false
            if (first) read()
        } else if (shown == null && overview is Load.Ready) {
            readJob?.cancel()
            readJob = viewModelScope.launch {
                val got = deps.api.sheet(project)
                if (opened != project to key) return@launch
                val there = (got as? MoiApi.Result.Ok)?.value?.todo?.firstOrNull { it.mine && waitingKey(it) == key }
                if (there == null) {
                    missing = true
                } else {
                    shown = there
                    sheet = Load.of(got)
                    read()
                }
            }
        }
    }

    /** Ce que le geste de l'attente demande de lire avant de décider. */
    fun read() {
        val w = shown ?: return
        readJob?.cancel()
        readJob = viewModelScope.launch {
            when (val r = gestureRead(w)) {
                is GestureRead.Accord -> approvals = Load.of(deps.api.approvals(w.project))
                GestureRead.ProjectPlan, is GestureRead.Checkpoint -> sheet = Load.of(deps.api.sheet(w.project))
                is GestureRead.Element -> element = Load.of(deps.api.element(w.project, r.list, r.item))
                GestureRead.Nothing -> Unit
            }
        }
    }

    /**
     * Décider : le bouton touché ([action]), ce qui est saisi ([typed]) et ce qui a été lu — le condensé de l'accord
     * montré, le numéro du plan montré. Abouti, l'attente n'est plus à faire : l'écran revient à la liste.
     */
    fun decide(action: String, typed: String = "") {
        val w = shown ?: return
        val request = todoRequest(w, action, typed, element?.valueOrNull, approval?.digest)
        gestures.send(w.project, request, todoWhere(w.project, waitingKey(w))) {
            answer = ""
            load(quiet = true)
        }
    }

    /**
     * Fusionner la pull request prête de l'attente ouverte : elle se relit, puis sa confirmation dit ce qui va être
     * fusionné ([merge]). Demandée, l'attente n'est plus à faire ; refusée, « À faire » se relit.
     */
    fun askMerge() {
        val w = shown ?: return
        merge.ask(w.project, mergeNumber(w), 0, todoWhere(w.project, waitingKey(w))) { load(quiet = true) }
    }

    fun confirmMerge() {
        merge.confirm(after = { load(quiet = true) }, failed = { load(quiet = true) })
    }

    companion object {
        const val NEW = "new"
        /** La page d'« À faire » (celle du serveur, par défaut). */
        const val TODO_PAGE = 25

        fun todoWhere(project: Int, key: String): String = "todo:$project:$key"

        /** « Désarchiver », dit sous la ligne du projet archivé. */
        fun restoreWhere(project: Int): String = "restore:$project"
    }
}

// ── La fiche d'un projet ────────────────────────────────────────────────

/**
 * La fiche d'un projet et ce que ses onglets lisent en plus : la liste de ses tickets, le diagramme de ses objectifs,
 * les comptes rendus d'un objectif. Un modèle par projet, que ses écrans partagent (la fiche, un objectif, un ticket).
 * Les lots suivants y ajoutent ce que leurs onglets lisent, ou leur propre modèle à côté, sur [ProjectsDeps].
 */
class ProjectViewModel(private val deps: ProjectsDeps, val id: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)

    var sheet by mutableStateOf<Load<Sheet>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set

    // ── Objectifs ──
    /** Le groupe filtré (vide : tous) ; un filtre se retire en le touchant de nouveau. */
    var goalFilter by mutableStateOf("")
        private set
    /** La liste, ou le diagramme. */
    var diagramMode by mutableStateOf(false)
        private set
    var diagram by mutableStateOf<Load<Diagram>?>(null)
        private set
    /** Les objectifs repliés du diagramme. */
    var folded by mutableStateOf<Set<Int>>(emptySet())
        private set
    /** Les comptes rendus d'un objectif (ses exécutions, lues dans le fil d'activité), par son numéro. */
    var reports by mutableStateOf<Map<Int, Load<ActivityPage>>>(emptyMap())
        private set

    // ── Tickets ──
    var ticketFilter by mutableStateOf(TicketFilters.OPEN)
        private set
    var ticketQuery by mutableStateOf("")
        private set
    var tickets by mutableStateOf<Load<EntryPage>?>(null)
        private set

    private var started = false
    private var job: Job? = null
    private var ticketsJob: Job? = null

    fun resume() {
        val first = !started
        started = true
        load(quiet = !first)
        if (!first) {
            if (tickets != null) loadTickets()
            if (diagram != null) loadDiagram()
        }
    }

    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(quiet = false).join()
            if (tickets != null) loadTickets().join()
            if (diagramMode) loadDiagram().join()
            refreshing = false
        }
    }

    fun retry() {
        sheet = Load.Loading
        load(quiet = false)
    }

    /** Après un geste : la fiche relue, et ce que ses onglets avaient lu. */
    fun reload() {
        load(quiet = true)
        if (tickets != null) loadTickets()
        if (diagram != null) loadDiagram()
        if (reports.isNotEmpty()) reports.keys.toList().forEach { loadReports(it, force = true) }
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            when (val got = deps.api.sheet(id)) {
                is MoiApi.Result.Ok -> sheet = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (sheet is Load.Ready) {
                    if (!quiet) gestures.say(got.error.said)
                } else {
                    sheet = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }

    // ── Objectifs ──

    fun pickGoalFilter(code: String) {
        goalFilter = if (goalFilter == code) "" else code
    }

    fun showDiagram(on: Boolean) {
        diagramMode = on
        if (on && diagram == null) loadDiagram()
    }

    fun loadDiagram(): Job = viewModelScope.launch {
        if (diagram == null) diagram = Load.Loading
        val got = deps.api.diagram(id)
        // une relecture qui échoue garde le diagramme montré
        if (got is MoiApi.Result.Ok || diagram !is Load.Ready) diagram = Load.of(got)
    }

    fun fold(objective: Int) {
        folded = if (objective in folded) folded - objective else folded + objective
    }

    /** Les comptes rendus d'un objectif : ses exécutions (`…/activite?kind=run&objective=`), lues une fois. */
    fun loadReports(objective: Int, force: Boolean = false) {
        if (!force && objective in reports) return
        if (objective !in reports) reports = reports + (objective to Load.Loading)
        viewModelScope.launch {
            val got = deps.api.activity(id, kind = "run", objective = objective)
            if (got is MoiApi.Result.Ok || reports[objective] !is Load.Ready) reports = reports + (objective to Load.of(got))
        }
    }

    // ── Tickets ──

    /** L'onglet Tickets s'ouvre : sa liste se lit une fois, puis à chaque retour. */
    fun openTickets() {
        if (tickets == null) loadTickets()
    }

    fun pickTicketFilter(code: String) {
        if (ticketFilter == code) return
        val asked = TicketFilters.state(ticketFilter)
        ticketFilter = code
        // « À toi » se lit dans les ouverts, côté écran : seul « Tous » demande une autre liste
        if (TicketFilters.state(code) != asked) {
            tickets = Load.Loading
            loadTickets()
        }
    }

    /** Chercher : la liste se relit après une pause de frappe. */
    fun search(query: String) {
        ticketQuery = query
        loadTickets(SEARCH_PAUSE_MS)
    }

    fun loadTickets(pauseMs: Long = 0): Job {
        ticketsJob?.cancel()
        return viewModelScope.launch {
            if (pauseMs > 0) delay(pauseMs)
            if (tickets == null) tickets = Load.Loading
            val got = deps.api.elements(id, state = TicketFilters.state(ticketFilter), q = ticketQuery)
            if (got is MoiApi.Result.Ok || tickets !is Load.Ready) tickets = Load.of(got)
        }.also { ticketsJob = it }
    }

    // ── Ses gestes ──

    /** Piloter : une consigne, « vas-y maintenant » (sur un objectif, s'il est nommé), la pause, la reprise. */
    fun pilot(what: String, text: String = "", objective: Int = 0, where: String = TOP) {
        gestures.send(id, pilotRequest(what, text, objective), where) { reload() }
    }

    /** Rouvrir un objectif, le dire terminé, le retirer. */
    fun goalStatus(goal: Goal, status: String) {
        gestures.send(id, objectiveStatusRequest(goal.id, status), goalWhere(goal.id)) { reload() }
    }

    /** Ajouter un objectif ou une mission ([before] `null`), ou le modifier : seulement ce qui change. */
    fun saveGoal(form: GoalForm, before: GoalForm? = null, objective: Int = 0) {
        gestures.send(id, goalRequest(form, before, objective), if (objective == 0) GOAL_NEW else goalFormWhere(objective)) { reload() }
    }

    fun saveMilestone(objective: Int, form: MilestoneForm, before: MilestoneForm? = null, milestone: Int = 0) {
        gestures.send(id, milestoneRequest(objective, form, before, milestone), milestoneWhere(objective)) { reload() }
    }

    fun dropMilestone(objective: Int, milestone: Int, reason: String) {
        gestures.send(id, milestoneDropRequest(objective, milestone, reason), goalWhere(objective)) { reload() }
    }

    /** Un point d'arrêt dit prêt : validé, ou refusé avec ce qui manque. */
    fun checkpoint(objective: Int, milestone: Int, verdict: String, reason: String = "") {
        gestures.send(id, checkpointRequest(objective, milestone, verdict, reason), goalWhere(objective)) { reload() }
    }

    fun openTicket(form: TicketForm) {
        gestures.send(id, ticketRequest(form), TICKET_NEW) {
            if (tickets == null) tickets = Load.Loading
            reload()
        }
    }

    companion object {
        /** L'en-tête de la fiche (piloter). */
        const val TOP = "top"
        const val GOAL_NEW = "goal-new"
        const val TICKET_NEW = "ticket-new"
        const val SEARCH_PAUSE_MS = 300L

        /** Les gestes d'un objectif (son état, ses jalons, un point d'arrêt). */
        fun goalWhere(objective: Int): String = "goal-act:$objective"

        /** Le formulaire d'un objectif. */
        fun goalFormWhere(objective: Int): String = "goal:$objective"

        /** Le formulaire d'un jalon de cet objectif. */
        fun milestoneWhere(objective: Int): String = "milestone:$objective"
    }
}

// ── Un ticket ───────────────────────────────────────────────────────────

/**
 * Un ticket ouvert : sa ligne, son texte, son fil, son parcours, ses gestes du moment (`GET …/element`), et pour son
 * Historique l'histoire de ses étapes mêlée à ce qui est arrivé à ses objectifs. [revision] compte ses gestes aboutis :
 * la fiche du projet se relit alors.
 */
class TicketViewModel(private val deps: ProjectsDeps, val project: Int, val number: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)

    var element by mutableStateOf<Load<EntryDetail>>(Load.Loading)
        private set
    var history by mutableStateOf<Load<EntryHistory>?>(null)
        private set
    /** Ce qui est arrivé à ses objectifs (leurs exécutions, leurs commits, leur pull request) ; vide sans le droit de le lire. */
    var around by mutableStateOf<List<Happening>>(emptyList())
        private set
    /** Le volet montré (vide : celui qui s'ouvre d'office). */
    var pane by mutableStateOf("")
    /** La note en cours d'écriture, dans son fil. */
    var note by mutableStateOf("")
    var revision by mutableIntStateOf(0)
        private set

    private val item = "#$number"
    private var started = false
    private var job: Job? = null

    fun resume() {
        val first = !started
        started = true
        load(quiet = !first)
        if (!first && history != null) loadStory(withActivity = around.isNotEmpty())
    }

    fun retry() {
        element = Load.Loading
        load(quiet = false)
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            when (val got = deps.api.element(project, ProjectsApi.TICKETS, item)) {
                is MoiApi.Result.Ok -> element = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (element is Load.Ready) {
                    if (!quiet) gestures.say(got.error.said)
                } else {
                    element = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }

    /** L'Historique s'ouvre : l'histoire de ses étapes, et — avec le droit de lire l'activité — ce qui l'entoure. */
    fun loadStory(withActivity: Boolean) {
        if (history == null) history = Load.Loading
        viewModelScope.launch {
            val story = async { deps.api.history(project, item) }
            val feed = if (withActivity) async { deps.api.activity(project, ticket = number) } else null
            val got = story.await()
            if (got is MoiApi.Result.Ok || history !is Load.Ready) history = Load.of(got)
            (feed?.await() as? MoiApi.Result.Ok)?.let { around = it.value.items }
        }
    }

    private fun changed() {
        revision++
        load(quiet = true)
        if (history != null) loadStory(withActivity = around.isNotEmpty())
    }

    /** Trancher : accepter, écarter, valider son plan (en nommant le plan lu), le refuser, le fermer, le rouvrir. */
    fun settle(verdict: String, reason: String = "") {
        val e = element.valueOrNull ?: return
        gestures.send(project, settleRequest(e.line, verdict, reason), HERE) { changed() }
    }

    /** Une note dans son fil ; sur un ticket qui pose une question, elle y répond. */
    fun sendNote() {
        val e = element.valueOrNull ?: return
        if (note.isBlank()) return
        gestures.send(project, noteRequest(e.line, note), HERE) {
            note = ""
            changed()
        }
    }

    /** Modifier son titre, sa sorte, sa priorité, sa description : seulement ce qui change. */
    fun modify(form: TicketForm) {
        val e = element.valueOrNull ?: return
        gestures.send(project, ticketRequest(form, TicketForm.of(e), e.line.handle), EDIT) { changed() }
    }

    companion object {
        /** Les gestes du moment, dits sous son en-tête. */
        const val HERE = "ticket"
        /** Le formulaire « Modifier ». */
        const val EDIT = "ticket-edit"
    }
}
