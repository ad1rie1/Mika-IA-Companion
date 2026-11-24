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
import fr.qwartz.mika.data.moi.projects.TodoDecision
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
import fr.qwartz.mika.data.moi.projects.olderKept
import fr.qwartz.mika.data.moi.projects.pilotRequest
import fr.qwartz.mika.data.moi.projects.refusalWords
import fr.qwartz.mika.data.moi.projects.restoreRequest
import fr.qwartz.mika.data.moi.projects.settleRequest
import fr.qwartz.mika.data.moi.projects.todoDecision
import fr.qwartz.mika.data.moi.projects.ticketRequest
import fr.qwartz.mika.data.moi.projects.todoRequest
import fr.qwartz.mika.data.moi.projects.waitingKey
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
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

/**
 * Ce dont un modèle de Projets a besoin : l'API, relire les pastilles du tiroir, l'heure, et [compute] — là où se fait
 * ce qui pèse (un fichier ou un diff mis en lignes, une page découpée), jamais sur le fil principal.
 */
class ProjectsDeps(
    val api: ProjectsApi,
    val refreshBadges: () -> Unit = {},
    val now: () -> Long = System::currentTimeMillis,
    val compute: CoroutineDispatcher = Dispatchers.Default,
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
 * ferme sa feuille, puis [acknowledge]). [finished] ne vaut que pour le geste qui vient d'aboutir : un geste qui part
 * l'efface, et un écran ou une feuille qui s'ouvre oublie ce qu'on avait dit à son endroit ([forget]). Chaque endroit
 * a sa clé d'envoi : un double appui ne part qu'une fois, un réessai après une coupure ne refait rien.
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
    fun send(
        project: Int,
        request: GestureRequest,
        where: String,
        failed: suspend (MoiError) -> Unit = {},
        after: suspend (GestureDone) -> Unit = {},
    ): Boolean = request.route.isNotEmpty() && run(where, request, { key -> deps.api.gesture(project, request, key) }, failed = failed, after = after)

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
        // le geste d'avant n'a plus rien à fermer : seul celui qui part dira qu'il a abouti
        finished = null
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
    /** Elle n'est plus dans « À faire » : décidée ailleurs, ou plus à elle — le serveur l'a dit, pas une panne. */
    var missing by mutableStateOf(false)
        private set
    /** Ce qu'elle dit maintenant n'a pas pu se lire (le réseau, le serveur) : son erreur, et « Réessayer ». */
    var failure by mutableStateOf<MoiError?>(null)
        private set
    /**
     * L'attente ouverte se relit — elle s'ouvre, l'écran revient devant, le serveur vient de refuser : tant qu'il n'a
     * pas redit où elle en est, rien ne s'y décide ([decision]).
     */
    var rereading by mutableStateOf(false)
        private set
    var approvals by mutableStateOf<Load<Approvals>?>(null)
        private set
    var sheet by mutableStateOf<Load<Sheet>?>(null)
        private set
    var element by mutableStateOf<Load<EntryDetail>?>(null)
        private set
    /** Sa réponse à une question, tapée sur place : celle de la dernière attente ouverte ([last]). */
    var answer by mutableStateOf("")

    /** L'attente dont l'écran est ouvert ; `null` : aucun (rien ne s'en relit). */
    private var opened: Pair<Int, String>? = null
    /**
     * La dernière attente ouverte, que son écran soit encore devant ou non : ce qu'on y tapait ([answer]) ne tombe que
     * quand une autre s'ouvre — pas quand on la quitte pour son projet, son fil, sa pull request, puis qu'on y revient.
     */
    private var last: Pair<Int, String>? = null
    private var started = false
    private var job: Job? = null
    private var readJob: Job? = null
    /** Les pages d'« À faire » lues, la première comprise. */
    private var todoPages = 1
    /** La taille d'une page d'« À faire », telle que le serveur l'a dite. */
    private var todoSize = TODO_PAGE
    /** La dernière page demandée n'était pas pleine : il n'y a pas de suite. */
    private var todoEnded = false

    val todoTotal: Int get() = overview.valueOrNull?.todoTotal ?: 0

    /** Ce qu'il reste à lire d'« À faire » (0 : tout est lu, ou la dernière page l'a dit). */
    val todoRest: Int get() = if (todoEnded) 0 else (todoTotal - todo.size).coerceAtLeast(0)

    /**
     * Les boutons de l'attente ouverte, d'après ce qu'on vient d'en lire. Aucun tant qu'elle se relit ou que sa
     * relecture a échoué : une décision ne se prend jamais sur l'ancienne lecture.
     */
    val decision: TodoDecision
        get() {
            val w = shown ?: return TodoDecision()
            return if (rereading || failure != null) TodoDecision() else todoDecision(w, approval, sheet?.valueOrNull, element?.valueOrNull)
        }

    /**
     * Une réponse se tape sur place — ce que dit la dernière lecture, même pendant qu'elle se relit ou si sa relecture
     * a échoué : le champ reste posé, avec ce qu'on y tape (et le clavier). Seul l'envoi attend la relecture
     * ([decision] : rien ne part d'ici là).
     */
    val answering: Boolean
        get() = shown?.let { todoDecision(it, approval, sheet?.valueOrNull, element?.valueOrNull).answer } == true

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

    /** Tirer relit tout : « À faire » repart de sa première page (la suite chargée a pu vieillir). */
    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(quiet = false, keep = false).join()
            refreshing = false
        }
    }

    fun retry() {
        overview = Load.Loading
        load(quiet = false, keep = false)
    }

    /** Un projet filtré se retire en le touchant de nouveau (0 : tous). */
    fun pick(project: Int) {
        filter = if (filter == project) 0 else project
    }

    /** « Tout voir » depuis une fiche : « À faire » s'ouvre sur ce projet. */
    fun showOnly(project: Int) {
        filter = project
    }

    /**
     * La suite d'« À faire » : la page d'après celles qu'on a lues — comptées, pas déduites du nombre de lignes (une
     * ligne déjà connue s'écarte, et la même page reviendrait sans fin) —, sans redire ce qu'on a déjà.
     */
    fun more() {
        if (loadingMore || todoRest <= 0) return
        loadingMore = true
        val asked = todoPages + 1
        viewModelScope.launch {
            when (val got = deps.api.todo(asked)) {
                // la première page relue entre-temps : cette suite n'est plus la sienne
                is MoiApi.Result.Ok -> if (asked == todoPages + 1) {
                    todoPages = asked
                    if (got.value.size > 0) todoSize = got.value.size
                    val known = todo.map { it.project to waitingKey(it) }.toSet()
                    todo = todo + got.value.items.filterNot { (it.project to waitingKey(it)) in known }
                    if (got.value.items.size < maxOf(got.value.size, 1)) todoEnded = true
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
            loadingMore = false
        }
    }

    /** [keep] : relue en place (un retour sur l'écran, une attente ouverte ou décidée), la suite déjà chargée reste si la page relue la rejoint. */
    private fun load(quiet: Boolean, keep: Boolean = true): Job {
        job?.cancel()
        return viewModelScope.launch {
            when (val got = deps.api.overview()) {
                is MoiApi.Result.Ok -> {
                    overview = Load.Ready(got.value)
                    firstRead(got.value.todo, keep)
                    if (filter != 0 && todo.none { it.project == filter }) filter = 0
                    found()
                }
                is MoiApi.Result.Failed -> {
                    // une relecture qui échoue garde ce qui était montré
                    if (overview is Load.Ready) {
                        if (!quiet) gestures.say(got.error.said)
                    } else {
                        overview = Load.Failed(got.error)
                    }
                    // l'attente ouverte n'a pas pu se relire : on le dit là, et rien ne s'y décide
                    if (opened != null) failure = got.error
                }
            }
        }.also { job = it }
    }

    /**
     * La première page d'« À faire » vient d'être relue ([fresh]). **Relue en place** ([keep]), la suite déjà chargée
     * reste tant que la page relue la rejoint ([olderKept]) : ouvrir une attente, en revenir, ne la fait pas retomber.
     * Ses pages se recomptent alors d'après ce qu'on tient — une attente partie a décalé les suivantes d'un rang : la
     * page entamée se redemande (ce qu'on a déjà s'écarte), celle d'après aurait sauté une ligne. Sinon — tirer, une
     * page relue qui ne rejoint plus rien, ou qui est tout ce que le serveur compte — la suite repart d'elle.
     */
    private fun firstRead(fresh: List<Waiting>, keep: Boolean) {
        val listed = fresh.map { it.project to waitingKey(it) }.toSet()
        // rien au-delà de la page relue : ce qu'on tenait de plus n'est plus à faire
        val older: List<Waiting> = if (!keep || todoTotal <= fresh.size) {
            emptyList()
        } else {
            olderKept(todo, fresh) { a, b -> a.project == b.project && waitingKey(a) == waitingKey(b) }
                .filterNot { (it.project to waitingKey(it)) in listed }
        }
        todo = fresh + older
        if (older.isEmpty()) {
            todoPages = 1
            todoEnded = false
        } else {
            todoPages = maxOf(1, todo.size / maxOf(todoSize, 1))
            // la fin atteinte ne vaut plus si le serveur en compte davantage que ce qu'on tient
            if (todo.size < todoTotal) todoEnded = false
        }
    }

    /** Une attente qui n'est plus à faire — décidée d'ici, ou le serveur le dit — quitte la liste, où qu'elle y soit. */
    private fun unlist(project: Int, key: String) {
        todo = todo.filterNot { it.project == project && waitingKey(it) == key }
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

    /**
     * L'écran d'une attente est devant — il s'ouvre, ou il revient (l'app sort de l'arrière-plan, l'écran tourne) :
     * elle se relit, toujours. Une autre attente, ou la même rouverte après avoir quitté son écran, repart de rien : ni
     * l'ancienne lecture, ni ce qu'on y avait dit. **Ce qu'on y tapait** ([answer]) **ne tombe que pour une autre
     * attente** : quittée pour un autre écran (son projet, son fil, son objectif, sa pull request) puis retrouvée, la
     * même le garde — et se relit quand même, sans rien offrir d'ici là.
     */
    fun open(project: Int, key: String) {
        val target = project to key
        if (opened != target) {
            opened = target
            shown = null
            missing = false
            approvals = null
            sheet = null
            element = null
            if (last != target) {
                last = target
                answer = ""
            }
            merge.cancel()
            gestures.forget(todoWhere(project, key))
        }
        reread()
    }

    /**
     * L'écran de l'attente est quitté : plus rien ne s'y relit, la confirmation d'une fusion demandée là s'annule, et
     * un geste abouti qu'il n'a pas eu le temps de suivre ne le refermera pas à son retour.
     */
    fun leave(project: Int, key: String) {
        if (opened != project to key) return
        opened = null
        readJob?.cancel()
        rereading = false
        failure = null
        merge.cancel()
        if (gestures.finished == todoWhere(project, key)) gestures.acknowledge()
    }

    /**
     * Relire l'attente ouverte : « À faire » d'abord (y est-elle encore, que dit son geste maintenant), puis ce que son
     * geste demande de lire. D'ici là, ce qu'on montrait reste lisible, sans ses boutons.
     */
    fun reread() {
        if (opened == null) return
        started = true
        failure = null
        rereading = true
        load(quiet = true)
    }

    /**
     * L'attente ouverte, dans ce qu'on vient de lire. Hors de la première page d'« À faire » (elle est plus loin, ou
     * elle n'y est plus), elle se cherche dans la fiche de son projet, qui rend tout ce qui y attend : absente là
     * aussi, elle n'est plus à faire ; la fiche illisible, c'est une panne, pas une absence.
     */
    private fun found() {
        val (project, key) = opened ?: return
        readJob?.cancel()
        rereading = true
        // dans la page qu'on vient de relire, pas dans la suite gardée : elle date d'avant
        val listed = overview.valueOrNull?.todo.orEmpty().firstOrNull { it.project == project && waitingKey(it) == key }
        readJob = viewModelScope.launch {
            if (listed != null) {
                show(listed)
                return@launch
            }
            when (val got = deps.api.sheet(project)) {
                is MoiApi.Result.Failed -> failure = got.error
                is MoiApi.Result.Ok -> {
                    val there = got.value.todo.firstOrNull { it.mine && waitingKey(it) == key }
                    if (there == null) {
                        shown = null
                        missing = true
                        rereading = false
                        // plus à faire : ni sa ligne dans la suite gardée, ni ce qu'on y tapait
                        unlist(project, key)
                        answer = ""
                    } else {
                        show(there, got.value)
                    }
                }
            }
        }
    }

    /** L'attente telle que le serveur la dit maintenant, puis ce que son geste demande de lire ([known] : sa fiche, si on vient de la lire). */
    private suspend fun show(w: Waiting, known: Sheet? = null) {
        shown = w
        missing = false
        when (val r = gestureRead(w)) {
            is GestureRead.Accord -> approvals = Load.of(deps.api.approvals(w.project))
            GestureRead.ProjectPlan, is GestureRead.Checkpoint -> sheet = if (known != null) Load.Ready(known) else Load.of(deps.api.sheet(w.project))
            is GestureRead.Element -> element = Load.of(deps.api.element(w.project, r.list, r.item))
            GestureRead.Nothing -> Unit
        }
        rereading = false
    }

    /** Relire ce que le geste de l'attente demande de lire (« Réessayer », après une lecture refusée). */
    fun read() {
        val w = shown ?: return
        readJob?.cancel()
        rereading = true
        readJob = viewModelScope.launch { show(w) }
    }

    /**
     * Décider : le bouton touché ([action]), ce qui est saisi ([typed]) et ce qui a été lu — le condensé de l'accord
     * montré, le numéro du plan montré. Rien ne part pendant une relecture, ni pour un bouton que la lecture du moment
     * n'offre pas. Abouti, l'attente n'est plus à faire :
     * l'écran revient à la liste ; refusé (la situation a changé), elle se relit — les mots du serveur restent dits.
     * Faux : rien n'est parti (elle se relit, ce bouton ne s'offre plus, un autre geste attend sa réponse) — l'écran
     * garde alors ce qui était tapé, et le dit.
     */
    fun decide(action: String, typed: String = ""): Boolean {
        val w = shown ?: return false
        // seulement un bouton que ce qu'on vient de lire offre encore (aucun pendant une relecture)
        val offered = decision
        if (if (action == "answer") !offered.answer else offered.buttons.none { it.action == action && it.enabled }) return false
        val request = todoRequest(w, action, typed, element?.valueOrNull, approval?.digest)
        val key = waitingKey(w)
        return gestures.send(w.project, request, todoWhere(w.project, key), failed = { reread() }) {
            if (last == w.project to key) answer = ""
            settled(w.project, key)
        }
    }

    /**
     * Un geste a abouti : l'attente décidée quitte la liste, et ce qu'on montrait n'est plus ce que le serveur dit —
     * « À faire » se relit, et l'attente ouverte avec lui. Si l'écran de ce geste n'est plus devant (quitté avant la
     * réponse, ou une autre attente ouverte depuis), personne n'y refermera rien : le geste abouti s'oublie, pour que
     * l'attente retrouvée plus tard ne se referme pas seule.
     */
    private fun settled(project: Int, key: String) {
        unlist(project, key)
        if (opened != null) rereading = true
        if (opened != project to key) gestures.forget(todoWhere(project, key))
        load(quiet = true)
    }

    /**
     * Fusionner la pull request prête de l'attente ouverte : elle se relit, puis sa confirmation dit ce qui va être
     * fusionné ([merge]). Demandée, l'attente n'est plus à faire ; refusée, ou plus fusionnable, elle se relit.
     */
    fun askMerge() {
        val w = shown ?: return
        if (rereading || failure != null) return
        merge.ask(w.project, mergeNumber(w), 0, todoWhere(w.project, waitingKey(w))) { reread() }
    }

    fun confirmMerge() {
        // l'attente dont la fusion est confirmée : celle de l'écran qui l'a demandée
        val (project, key) = opened ?: return
        merge.confirm(after = { settled(project, key) }, failed = { reread() })
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
    /**
     * La fiche montrée date d'avant — l'écran revient devant, un geste vient d'aboutir ou d'être refusé — et se relit :
     * tant que le serveur n'a pas redit où elle en est, aucun geste ne s'y offre (un plan, la preuve d'un point d'arrêt
     * ne se décident pas sur l'ancienne lecture).
     */
    var stale by mutableStateOf(false)
        private set
    /** Sa relecture a échoué : on le dit, et « Réessayer » ([reread]). */
    var staleError by mutableStateOf<MoiError?>(null)
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
    private val gone = Channel<Unit>(Channel.BUFFERED)

    /** Relue sans bruit, la fiche n'est plus à toi (introuvable : plus partagée, retirée — ADR 0308) : l'écran revient
     *  à la liste des projets, plutôt qu'une fiche figée sous « introuvable ». */
    val left: Flow<Unit> = gone.receiveAsFlow()

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

    /** « Réessayer », après une relecture qui a échoué. */
    fun reread() {
        load(quiet = false)
    }

    /** Après un geste, abouti ou refusé : la fiche relue, et ce que ses onglets avaient lu. */
    fun reload() {
        load(quiet = true)
        if (tickets != null) loadTickets()
        if (diagram != null) loadDiagram()
        if (reports.isNotEmpty()) reports.keys.toList().forEach { loadReports(it, force = true) }
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        // ce qu'on montre date d'avant cette lecture : rien ne s'y décide tant qu'elle n'a pas abouti
        if (sheet is Load.Ready) stale = true
        staleError = null
        return viewModelScope.launch {
            when (val got = deps.api.sheet(id)) {
                is MoiApi.Result.Ok -> {
                    sheet = Load.Ready(got.value)
                    stale = false
                }
                is MoiApi.Result.Failed -> if (sheet is Load.Ready && quiet && got.error.gone) {
                    // lue, puis introuvable : elle n'est plus à toi — retour à la liste, sans le refus
                    stale = false
                    gone.trySend(Unit)
                } else if (sheet is Load.Ready) {
                    staleError = got.error
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

    // Aucun ne part tant que la fiche se relit ([stale]) : la garde est ici, pas seulement dans les boutons — une
    // fenêtre ou une feuille restée ouverte (une rotation relance la relecture) ne décide pas sur l'ancienne lecture.
    // Chacun rend faux quand rien n'est parti (elle se relit, un autre geste attend sa réponse) : l'écran garde alors
    // ce qui était tapé. Un geste refusé relit la fiche comme un geste abouti : un refus dit le plus souvent que la
    // situation a changé.

    /** Ce qu'une feuille de la fiche dit en tête : le refus de son geste, sinon pourquoi rien ne peut en partir (sa relecture a échoué). */
    fun saidAt(where: String): String = gestures.refusalAt(where).ifBlank { staleError?.message.orEmpty() }

    /** Piloter : une consigne, « vas-y maintenant » (sur un objectif, s'il est nommé), la pause, la reprise. */
    fun pilot(what: String, text: String = "", objective: Int = 0, where: String = TOP): Boolean =
        !stale && gestures.send(id, pilotRequest(what, text, objective), where, failed = { reload() }) { reload() }

    /** Rouvrir un objectif, le dire terminé, le retirer. */
    fun goalStatus(goal: Goal, status: String): Boolean =
        !stale && gestures.send(id, objectiveStatusRequest(goal.id, status), goalWhere(goal.id), failed = { reload() }) { reload() }

    /** Ajouter un objectif ou une mission ([before] `null`), ou le modifier : seulement ce qui change. */
    fun saveGoal(form: GoalForm, before: GoalForm? = null, objective: Int = 0): Boolean =
        !stale && gestures.send(id, goalRequest(form, before, objective), if (objective == 0) GOAL_NEW else goalFormWhere(objective), failed = { reload() }) { reload() }

    fun saveMilestone(objective: Int, form: MilestoneForm, before: MilestoneForm? = null, milestone: Int = 0): Boolean =
        !stale && gestures.send(id, milestoneRequest(objective, form, before, milestone), milestoneWhere(objective), failed = { reload() }) { reload() }

    fun dropMilestone(objective: Int, milestone: Int, reason: String): Boolean =
        !stale && gestures.send(id, milestoneDropRequest(objective, milestone, reason), goalWhere(objective), failed = { reload() }) { reload() }

    /** Un point d'arrêt dit prêt : validé, ou refusé avec ce qui manque. */
    fun checkpoint(objective: Int, milestone: Int, verdict: String, reason: String = ""): Boolean =
        !stale && gestures.send(id, checkpointRequest(objective, milestone, verdict, reason), goalWhere(objective), failed = { reload() }) { reload() }

    fun openTicket(form: TicketForm): Boolean =
        !stale && gestures.send(id, ticketRequest(form), TICKET_NEW) {
            if (tickets == null) tickets = Load.Loading
            reload()
        }

    /**
     * Un geste sur ses liens — en poser un, changer son mot, le mode direct, le retirer, demander quelque chose au
     * projet lu ([project] : celui qui reçoit la demande) : ce qu'on en montre vient de la fiche, il ne part pas non
     * plus tant qu'elle se relit.
     */
    fun link(request: GestureRequest, where: String, project: Int = id): Boolean =
        !stale && gestures.send(project, request, where) { reload() }

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
    /**
     * Le ticket montré date d'avant — l'écran revient devant, un geste vient d'aboutir ou d'être refusé — et se relit :
     * tant que le serveur n'a pas redit où il en est, aucun geste ne s'y offre (sa question, son plan ne se décident
     * pas sur l'ancienne lecture).
     */
    var stale by mutableStateOf(false)
        private set
    /** Sa relecture a échoué : on le dit, et « Réessayer » ([reread]). */
    var staleError by mutableStateOf<MoiError?>(null)
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

    /** « Réessayer », après une relecture qui a échoué. */
    fun reread() {
        load(quiet = false)
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        // ce qu'on montre date d'avant cette lecture : rien ne s'y décide tant qu'elle n'a pas abouti
        if (element is Load.Ready) stale = true
        staleError = null
        return viewModelScope.launch {
            when (val got = deps.api.element(project, ProjectsApi.TICKETS, item)) {
                is MoiApi.Result.Ok -> {
                    element = Load.Ready(got.value)
                    stale = false
                }
                is MoiApi.Result.Failed -> if (element is Load.Ready) {
                    staleError = got.error
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

    /**
     * Trancher : accepter, écarter, valider son plan (en nommant le plan lu), le refuser, le fermer, le rouvrir. Faux :
     * rien n'est parti (il se relit, un autre geste attend sa réponse) — l'écran garde ce qui était tapé, et le dit.
     */
    fun settle(verdict: String, reason: String = ""): Boolean {
        val e = element.valueOrNull ?: return false
        if (stale) return false
        return gestures.send(project, settleRequest(e.line, verdict, reason), HERE, failed = { load(quiet = true) }) { changed() }
    }

    /** Une note dans son fil ; sur un ticket qui pose une question, elle y répond. */
    fun sendNote() {
        val e = element.valueOrNull ?: return
        if (note.isBlank() || stale) return
        gestures.send(project, noteRequest(e.line, note), HERE, failed = { load(quiet = true) }) {
            note = ""
            changed()
        }
    }

    /** Modifier son titre, sa sorte, sa priorité, sa description : seulement ce qui change. */
    fun modify(form: TicketForm) {
        val e = element.valueOrNull ?: return
        gestures.send(project, ticketRequest(form, TicketForm.of(e), e.line.handle), EDIT, failed = { load(quiet = true) }) { changed() }
    }

    companion object {
        /** Les gestes du moment, dits sous son en-tête. */
        const val HERE = "ticket"
        /** Le formulaire « Modifier ». */
        const val EDIT = "ticket-edit"
    }
}
