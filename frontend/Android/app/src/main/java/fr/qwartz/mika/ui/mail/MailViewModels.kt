package fr.qwartz.mika.ui.mail

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Caps
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.caps
import fr.qwartz.mika.data.moi.mail.MailApi
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.mail.MailFolder
import fr.qwartz.mika.data.moi.mail.MailLimits
import fr.qwartz.mika.data.moi.mail.MailRow
import fr.qwartz.mika.data.moi.mail.MailStates
import fr.qwartz.mika.data.moi.mail.MailView
import fr.qwartz.mika.data.moi.mail.SentMail
import fr.qwartz.mika.data.moi.mail.commonBoxes
import fr.qwartz.mika.data.moi.mail.leftView
import fr.qwartz.mika.data.moi.mail.messagesQuery
import fr.qwartz.mika.data.moi.mail.moveTargets
import fr.qwartz.mika.data.moi.mail.nextPage
import fr.qwartz.mika.data.moi.mail.tidiedRows
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/**
 * Ce que les écrans de Mail prennent de la session : l'API, les mails commencés, relire les pastilles, savoir si la
 * session est ouverte, et dire un sort où qu'on soit (un envoi fini après qu'on a quitté son écran). Un test JVM les
 * donne sans le graphe de l'app.
 */
class MailDeps(
    val api: MailApi,
    val unsent: UnsentMails = UnsentMails(),
    val refreshBadges: () -> Unit = {},
    val signedIn: () -> Boolean = { true },
    val notices: MailNotices = MailNotices(),
) {
    constructor(graph: AppGraph) : this(
        api = graph.mailApi(),
        unsent = graph.unsentMail,
        refreshBadges = { graph.me.refresh() },
        signedIn = { graph.auth.credentials() != null },
        notices = graph.mailNotices,
    )
}

/** Ce que tous les écrans de Mail ont : l'API, et le sort d'un geste à dire (l'écran le montre en toast). */
abstract class MailScreenModel(protected val deps: MailDeps) : ViewModel() {
    protected val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des gestes, une fois chacun. */
    val said: Flow<String> = notices.receiveAsFlow()

    protected open fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    protected fun say(error: MoiError) = say(error.said)
}

/** Ce que la liste montre : ses lignes (ou ce qui est parti), combien en tout, combien de pages lues, et combien de
 *  ses lignes ont pu quitter la vue du serveur depuis qu'elle a été lue d'un coup ([drift] : rangées ici). */
data class MailListing(
    val rows: List<MailRow> = emptyList(),
    val sent: List<SentMail> = emptyList(),
    val total: Int = 0,
    val pages: Int = 1,
    val drift: Int = 0,
)

/**
 * La liste de Mail (`Route.Mail`) : la vue choisie (toutes les réceptions, une boîte, un dossier, ses envoyés), son
 * filtre, sa recherche, ses pages, la sélection et ses gestes. Les boîtes (leur niveau, leurs dossiers et leurs non-lus)
 * se relisent avec la liste.
 */
class MailListViewModel(deps: MailDeps) : MailScreenModel(deps) {
    var boxes by mutableStateOf<Load<MailBoxes>>(Load.Loading)
        private set
    var view by mutableStateOf<MailView>(MailView.All)
        private set
    var filter by mutableStateOf(MailStates.ALL)
        private set
    var query by mutableStateOf("")
        private set
    var searching by mutableStateOf(false)
        private set
    var listing by mutableStateOf<Load<MailListing>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set
    var loadingMore by mutableStateOf(false)
        private set
    /** Ce qui attend une réponse selon elle, dans la vue (le compte de sa puce). */
    var needsReply by mutableIntStateOf(0)
        private set
    var selected by mutableStateOf<Set<String>>(emptySet())
        private set
    var busy by mutableStateOf(false)
        private set

    private var started = false
    private var generation = 0
    private var listJob: Job? = null
    private var searchJob: Job? = null

    /** Un rangement fait ici ou depuis la liseuse, dans l'ordre. */
    private class Tidy(val seq: Int, val refs: Set<String>, val gesture: String)

    /** Les derniers rangements : une lecture partie avant l'un d'eux le rejoue sur ce qu'elle rapporte (le serveur a
     *  pu répondre avant d'avoir rangé) — un mail archivé pendant la lecture ne revient pas. */
    private val tidies = ArrayDeque<Tidy>()
    private var tidySeq = 0

    private fun replay(rows: List<MailRow>, since: Int): List<MailRow> =
        tidies.filter { it.seq > since }.fold(rows) { acc, t -> tidiedRows(acc, t.refs, t.gesture) }

    init {
        viewModelScope.launch { MailChanges.flow.collect(::apply) }
    }

    val boxList: List<MailBox> get() = boxes.valueOrNull?.boxes.orEmpty()

    fun boxOf(key: String): MailBox? = boxList.firstOrNull { it.key == key }

    fun capsOf(key: String): Caps = caps(boxOf(key)?.level ?: Levels.READ)

    /** L'écran revient (ou une minute a passé) : tout lire la première fois, sinon relire sans bruit. */
    fun resume() {
        if (!started) {
            started = true
            viewModelScope.launch { loadBoxes() }
            loadList(keep = false, silent = false)
        } else {
            refreshQuietly()
        }
    }

    /** Tirer pour relire : les boîtes et la liste, ce qui est montré reste jusqu'à ce que la relecture arrive. */
    fun pull() {
        refreshing = true
        viewModelScope.launch {
            loadBoxes()
            loadList(keep = true, silent = false, pages = currentPages())?.join()
            refreshing = false
        }
    }

    fun retry() {
        viewModelScope.launch { loadBoxes() }
        loadList(keep = false, silent = false)
    }

    private fun refreshQuietly() {
        viewModelScope.launch { loadBoxes() }
        // une sélection en cours ne bouge pas sous le doigt ; au-delà de cent lignes, on ne relit pas tout
        if (selected.isEmpty() && currentPages() * PAGE <= MAX_SIZE) loadList(keep = true, silent = true, pages = currentPages())
    }

    private fun currentPages(): Int = listing.valueOrNull?.pages ?: 1

    fun showView(v: MailView) {
        view = v
        selected = emptySet()
        loadList(keep = false, silent = false)
    }

    /** Une puce : la même, rappuyée, l'éteint (un seul état à la fois, comme l'API). */
    fun toggleFilter(state: String) {
        filter = if (filter == state) MailStates.ALL else state
        selected = emptySet()
        loadList(keep = false, silent = false)
    }

    fun openSearch() {
        searching = true
    }

    fun closeSearch() {
        searching = false
        if (query.isNotEmpty()) search("")
    }

    fun search(text: String) {
        query = text.take(MailLimits.SEARCH)
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(SEARCH_DEBOUNCE_MS)
            loadList(keep = true, silent = false)
        }
    }

    private suspend fun loadBoxes() {
        val got = api.boxes()
        if (got is MoiApi.Result.Ok || boxes !is Load.Ready) boxes = Load.of(got)
        // la boîte de la vue n'est plus à toi (retirée, plus partagée) : retour à toutes les réceptions
        val key = view.boxKey
        if (got is MoiApi.Result.Ok && key != null && got.value.boxes.none { it.key == key }) showView(MailView.All)
    }

    /** Relit la liste ([pages] pages d'un coup, cent lignes au plus). [keep] : ce qui est montré reste pendant la
     *  lecture ; [silent] : un refus ne se dit pas (une relecture de fond). */
    private fun loadList(keep: Boolean, silent: Boolean, pages: Int = 1): Job? {
        listJob?.cancel()
        val gen = ++generation
        val v = view
        val f = filter
        val q = query
        if (!keep || listing !is Load.Ready) listing = Load.Loading
        val since = tidySeq
        listJob = viewModelScope.launch {
            val got: Load<MailListing> = when (v) {
                is MailView.Sent -> when (val r = api.sent(v.box)) {
                    is MoiApi.Result.Ok -> {
                        val found = sentMatching(r.value.distinctBy { it.ref }, q)
                        Load.Ready(MailListing(sent = found, total = found.size))
                    }
                    is MoiApi.Result.Failed -> Load.Failed(r.error)
                }
                else -> {
                    val size = (PAGE * pages).coerceAtMost(MAX_SIZE)
                    when (val r = api.messages(messagesQuery(v, f, q, 1, size))) {
                        is MoiApi.Result.Ok -> {
                            val read = r.value.items.distinctBy { it.ref }
                            val rows = replay(read, since)
                            val total = (r.value.total - (read.size - rows.size)).coerceAtLeast(rows.size)
                            Load.Ready(MailListing(rows = rows, total = total, pages = size / PAGE))
                        }
                        is MoiApi.Result.Failed -> Load.Failed(r.error)
                    }
                }
            }
            if (gen != generation) return@launch
            if (got is Load.Failed && listing is Load.Ready && keep) {
                if (!silent) say(got.error)
            } else {
                listing = got
            }
            if (v !is MailView.Sent) countNeedsReply(v, gen)
        }
        return listJob
    }

    private suspend fun countNeedsReply(v: MailView, gen: Int) {
        val got = api.messages(messagesQuery(v, MailStates.NEEDS_REPLY, "", 1, 1))
        if (gen == generation && got is MoiApi.Result.Ok) needsReply = got.value.total
    }

    /**
     * La page suivante, en fin de liste. Jusqu'à cent lignes, la liste se relit d'un coup depuis le début, une page de
     * plus (comme le web lit des pages entières) : un mail rangé entre-temps ne décale rien, aucun ne tombe entre deux
     * pages. Au-delà, la page qui contient la première ligne pas encore lue, reculée de ce qui a pu quitter la vue.
     */
    fun loadMore() {
        val cur = listing.valueOrNull ?: return
        val v = view
        if (loadingMore || v is MailView.Sent || cur.rows.size >= cur.total) return
        loadingMore = true
        val next = cur.pages + 1
        if (next * PAGE <= MAX_SIZE) {
            val job = loadList(keep = true, silent = false, pages = next)
            viewModelScope.launch {
                job?.join()
                loadingMore = false
            }
            return
        }
        val gen = generation
        val since = tidySeq
        val page = nextPage(cur.rows.size, cur.drift, PAGE)
        viewModelScope.launch {
            val got = api.messages(messagesQuery(v, filter, query, page, PAGE))
            val now = listing.valueOrNull
            if (gen == generation && now != null) {
                when (got) {
                    is MoiApi.Result.Ok -> {
                        // à la liste du moment (rangée pendant la lecture, peut-être), sans ce qui a été rangé depuis
                        val known = now.rows.mapTo(HashSet()) { it.ref }
                        val more = replay(got.value.items, since).filter { it.ref !in known }.distinctBy { it.ref }
                        val rows = now.rows + more
                        // lue jusque-là, la liste suit de nouveau le serveur : ce qui dépasse sa page, plus ce qui a été
                        // rangé pendant la lecture (le serveur a pu répondre avant), reste à reculer la fois suivante
                        val drift = (rows.size - ((page - 1) * PAGE + got.value.items.size)).coerceAtLeast(0) + (now.drift - cur.drift).coerceAtLeast(0)
                        listing = Load.Ready(now.copy(rows = rows, total = got.value.total.coerceAtLeast(rows.size), pages = next, drift = drift))
                    }
                    is MoiApi.Result.Failed -> say(got.error)
                }
            }
            loadingMore = false
        }
    }

    // ── La sélection ──

    /** Un appui long (ou un appui pendant la sélection) : une boîte qu'on ne te partage qu'en lecture ne se range pas. */
    fun toggle(row: MailRow, readOnly: String) {
        if (!capsOf(row.box).write) {
            say(readOnly)
            return
        }
        selected = if (row.ref in selected) selected - row.ref else selected + row.ref
    }

    fun clearSelection() {
        selected = emptySet()
    }

    private fun selectedRows(): List<MailRow> = listing.valueOrNull?.rows.orEmpty().filter { it.ref in selected }

    /** Au moins un non-lu parmi la sélection : le geste est « Marquer lu ». */
    val selectionUnread: Boolean get() = selectedRows().any { !it.seen }

    /** Tous suivis : le geste est « Ne plus suivre ». */
    val selectionFlagged: Boolean get() = selectedRows().let { rows -> rows.isNotEmpty() && rows.all { it.flagged } }

    /** Où déplacer la sélection : les dossiers de sa boîte, si elle n'est que d'une boîte (`null` sinon). */
    fun moveChoices(): Pair<MailBox, List<MailFolder>>? {
        val rows = selectedRows()
        val box = rows.map { it.box }.distinct().singleOrNull()?.let(::boxOf) ?: return null
        val current = rows.map { it.folder }.distinct().singleOrNull().orEmpty()
        return box to moveTargets(box, current)
    }

    fun tidySelected(gesture: String, folder: String = "") {
        val refs = selected.toList()
        if (refs.isEmpty() || busy) return
        busy = true
        viewModelScope.launch {
            when (val got = api.tidy(refs, gesture, folder)) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    patch(refs, gesture)
                    selected = emptySet()
                    loadBoxes()
                    if (filter == MailStates.UNREAD || filter == MailStates.FLAGGED) loadList(keep = true, silent = true, pages = currentPages())
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
            busy = false
        }
    }

    /** Ce qu'un geste change aux lignes montrées, sans tout relire ; retenu pour les lectures en cours. */
    private fun patch(refs: List<String>, gesture: String) {
        val set = refs.toSet()
        tidies.addLast(Tidy(++tidySeq, set, gesture))
        while (tidies.size > TIDIES_KEPT) tidies.removeFirst()
        val cur = listing.valueOrNull ?: return
        val rows = tidiedRows(cur.rows, set, gesture)
        val removed = cur.rows.size - rows.size
        listing = Load.Ready(
            cur.copy(
                rows = rows,
                total = (cur.total - removed).coerceAtLeast(rows.size),
                drift = cur.drift + leftView(cur.rows, set, gesture, filter),
            ),
        )
    }

    private fun apply(change: MailChanges.Change) {
        when (change) {
            is MailChanges.Change.Tidied -> {
                patch(change.refs, change.gesture)
                selected = selected - change.refs.toSet()
                viewModelScope.launch { loadBoxes() }
            }
            MailChanges.Change.Drafts -> if (started) refreshQuietly()
        }
    }

    /** « Relever maintenant » : par la boîte de la vue si tu peux la relever, sinon la première prête ; la relève passe
     *  sur toutes les boîtes du serveur (trente demandes par minute au plus). */
    fun poll(none: String) {
        val writable = boxList.filter { caps(it.level).write }
        val key = view.boxKey?.takeIf { capsOf(it).write } ?: (writable.firstOrNull { it.ready } ?: writable.firstOrNull())?.key
        if (key == null) {
            say(none)
            return
        }
        viewModelScope.launch {
            when (val got = api.poll(key)) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    delay(POLL_SETTLE_MS)
                    refreshQuietly()
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
        }
    }

    /** Les boîtes des vues communes (pour le sous-titre de « Toutes les réceptions »). */
    val common: List<MailBox> get() = commonBoxes(boxList)

    private fun sentMatching(items: List<SentMail>, q: String): List<SentMail> {
        val needle = q.trim().lowercase()
        if (needle.isEmpty()) return items
        return items.filter { s ->
            "${s.subject} ${s.snippet} ${s.to.joinToString(" ") { "${it.name} ${it.address}" }}".lowercase().contains(needle)
        }
    }

    private companion object {
        const val PAGE = 25
        const val MAX_SIZE = 100
        const val SEARCH_DEBOUNCE_MS = 350L
        const val POLL_SETTLE_MS = 3_000L
        const val TIDIES_KEPT = 64
    }
}
