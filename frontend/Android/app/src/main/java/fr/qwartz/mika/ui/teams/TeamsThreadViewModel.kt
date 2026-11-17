package fr.qwartz.mika.ui.teams

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.SentHere
import fr.qwartz.mika.data.moi.teams.TeamsLimits
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.UNDER_WAY
import fr.qwartz.mika.data.moi.teams.lastReceived
import fr.qwartz.mika.data.moi.teams.messageProblem
import fr.qwartz.mika.data.moi.teams.prefillOff
import fr.qwartz.mika.data.moi.teams.stillSentHere
import fr.qwartz.mika.data.moi.teams.withoutSent
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/** Une réponse demandée se guette à ce rythme… */
internal const val ASK_POLL_MS = 10_000L
/** …au plus si longtemps (elle travaille à son prochain moment, qui peut tarder) ; le fil, lui, se relit à ce rythme. */
internal const val ASK_POLL_MAX_MS = 30 * 60_000L
internal const val THREAD_REFRESH_MS = 20_000L

/**
 * Un fil (`Route.TeamsThread`) : la conversation ouverte, les messages plus anciens lus en plus, tes envois d'ici que
 * le moteur n'a pas encore dits, ce que tu tapes (discussion par discussion), ses réponses et ce que tu en décides, ta
 * demande à Mika et sa réponse guettée. Un modèle par session : rouvrir une discussion la relit sans bruit.
 */
class TeamsThreadViewModel(graph: AppGraph) : TeamsScreenModel(graph) {
    var key by mutableStateOf("")
        private set
    var thread by mutableStateOf<Load<ConversationThread>>(Load.Loading)
        private set
    /** Les messages d'avant la page des plus récents, lus par « Messages plus anciens ». */
    var older by mutableStateOf<List<TeamsMessage>>(emptyList())
        private set
    /** Il en reste de plus anciens que [older]. */
    var olderMore by mutableStateOf(false)
        private set
    var loadingOlder by mutableStateOf(false)
        private set
    /** Ce que tu tapes dans la discussion ouverte. */
    var text by mutableStateOf("")
        private set
    var sending by mutableStateOf(false)
        private set
    var prefilling by mutableStateOf(false)
        private set
    /** Tes envois d'ici que le moteur n'a pas encore pu dire (sa liste `pending` les remplace dès qu'il les connaît). */
    var sent by mutableStateOf<List<SentHere>>(emptyList())
        private set
    /** Les discussions où tu lui as demandé une réponse, et depuis quand. */
    private var askedSince by mutableStateOf<Map<String, Long>>(emptyMap())
    /** Les demandes guettées sans réponse au-delà du plafond : on cesse de les guetter (une nouvelle demande, si). */
    private val gaveUp = mutableSetOf<String>()
    /** Ce que tu as commencé d'écrire, discussion par discussion. */
    private val typed = mutableMapOf<String, String>()
    private val sendKey = SendKey()
    private val prefillKey = SendKey()
    private var job: Job? = null
    private var seq = 0
    /** Ce qu'on dit quand sa réponse demandée est arrivée (le texte vient de l'écran). */
    private var arrivedText = ""

    private fun now(): Long = graph.clock.wallMs()

    /** Le fil de la discussion ouverte ([key], la clé demandée : le serveur rend la sienne, normalisée — `principal~`
     *  en moins —, et une lecture d'une autre discussion n'arrive jamais ici). */
    val current: ConversationThread? get() = thread.valueOrNull

    /** Tous les messages chargés, du plus ancien au plus récent, chacun une fois. */
    val messages: List<TeamsMessage> get() = (older + current?.messages.orEmpty()).distinctBy { it.ref }

    /** Elle prépare une réponse demandée (« Elle s'y met… ») : demandée d'ici ou ailleurs, pas encore arrivée. */
    val asked: Boolean get() = current.let { t -> t != null && !t.underWay && (key in askedSince || t.asked) }

    /** La réponse demandée se guette de près (toutes les dix secondes), jusqu'au plafond. */
    val watching: Boolean get() = asked && key !in gaveUp

    /** Ouvrir une discussion ; [arrived] : ce qu'on dit quand sa réponse demandée y arrive. */
    fun open(k: String, arrived: String) {
        arrivedText = arrived
        if (k == key && thread is Load.Ready) {
            refresh()
            return
        }
        key = k
        text = typed[k].orEmpty()
        thread = Load.Loading
        older = emptyList()
        olderMore = false
        load(quiet = false)
    }

    fun retry() {
        thread = Load.Loading
        load(quiet = false)
    }

    /** Relire sans bruit (le rythme de l'écran) ; une relecture déjà en cours suffit. */
    fun refresh() {
        val since = askedSince[key]
        if (since != null && now() - since > ASK_POLL_MAX_MS) {
            // elle n'a rien rendu depuis si longtemps : on cesse de guetter ici (la relecture du fil la verra arriver)
            gaveUp += key
            askedSince = askedSince - key
        }
        load(quiet = true)
    }

    /** Relit le fil. [quiet] : ce qui est montré reste, un refus ne se dit pas ; [force] : après un geste, la relecture
     *  repart de zéro (celle qui était en cours ne savait pas ce geste). */
    private fun load(quiet: Boolean, force: Boolean = false) {
        if (quiet && !force && job?.isActive == true) return
        job?.cancel()
        val k = key
        val s = ++seq
        job = viewModelScope.launch {
            // le niveau du compte décide de ce que le champ et les cartes offrent (ADR 0188) : ses comptes d'abord
            if (accounts == null || quiet) loadAccounts()
            val started = now()
            val got = api.thread(k, size = TeamsLimits.PAGE)
            if (s != seq || k != key) return@launch
            when (got) {
                is MoiApi.Result.Ok -> settle(got.value, quiet, started)
                is MoiApi.Result.Failed -> if (!quiet || thread !is Load.Ready) thread = Load.Failed(got.error)
            }
        }
    }

    private fun settle(t: ConversationThread, quiet: Boolean, started: Long) {
        val before = current
        if (quiet && before != null) {
            // ce qui sort de la page des plus récents (des messages arrivés entre-temps) reste affiché, plus haut
            val fresh = t.messages.mapTo(HashSet()) { it.ref }
            val kept = (older + before.messages).filter { it.ref !in fresh }
            if (kept.isNotEmpty() && older.isEmpty()) olderMore = before.more
            older = kept
        }
        // tes envois d'ici : le moteur dit maintenant ce qu'ils sont devenus (`pending`), ou ils sont revenus dans le fil
        sent = stillSentHere(sent, t, started)
        // elle a fini (ou renoncé) : le moteur ne dit plus qu'on le lui a demandé
        if (before?.asked == true && !t.asked) askedSince = askedSince - key
        val came = quiet && before != null &&
            t.replies.any { r -> r.state in UNDER_WAY && !r.answered && before.replies.none { it.id == r.id } }
        thread = Load.Ready(t)
        if (t.underWay || !t.asked) gaveUp -= key
        if (t.underWay) askedSince = askedSince - key
        if (came) {
            say(arrivedText)
            graph.me.refresh()
        }
    }

    /** Les messages d'avant les plus anciens chargés. */
    fun loadOlder() {
        val t = current ?: return
        if (loadingOlder) return
        val first = messages.firstOrNull() ?: return
        loadingOlder = true
        val k = key
        viewModelScope.launch {
            when (val got = api.thread(t.key, before = first.at, size = TeamsLimits.PAGE)) {
                is MoiApi.Result.Ok -> if (key == k) {
                    val known = messages.mapTo(HashSet()) { it.ref }
                    older = got.value.messages.filter { it.ref !in known } + older
                    olderMore = got.value.more
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
            loadingOlder = false
        }
    }

    /** Il en reste de plus anciens à lire. */
    val more: Boolean get() = if (older.isNotEmpty()) olderMore else current?.more == true

    // ── Écrire ──

    fun type(value: String) {
        if (chars(value) > TeamsLimits.BODY) return
        text = value
        if (value.isEmpty()) typed -= key else typed[key] = value
    }

    /** Ton message (ADR 0189) : il part par l'extension du compte, sous le nom de sa personne ; une clé par geste. */
    fun send() {
        val t = current ?: return
        if (sending) return
        val body = text.trim()
        if (body.isEmpty()) return
        val problem = messageProblem(body)
        if (problem.isNotEmpty()) return say(problem)
        sending = true
        // [k] : ce que tu tapes ici, et la discussion ouverte ; [t.key] : la clé du serveur (tes envois d'ici)
        val k = key
        val keyOf = sendKey.of(t.key to body)
        viewModelScope.launch {
            val got = api.send(t.key, body, key = keyOf)
            sendKey.settled(networkFailure = got is MoiApi.Result.Failed && got.error.network)
            sending = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    // le texte parti se retire du champ ; ce qu'on a tapé pendant l'envoi reste
                    when (val rest = withoutSent(typed[k].orEmpty(), body)) {
                        null -> Unit
                        "" -> typed -= k
                        else -> typed[k] = rest
                    }
                    if (key == k) text = typed[k].orEmpty()
                    sent = sent + SentHere(t.key, body, now())
                    say(got.value.message)
                    // sa réponse qui attendait ici ne partira plus (ADR 0199) : la pastille le suit
                    if (t.replies.any { it.waiting && !it.answered }) graph.me.refresh()
                    if (key == k) load(quiet = true, force = true)
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
        }
    }

    /** « Le réécrire » : le texte d'un de tes messages qui n'est pas parti revient dans le champ, pour le renvoyer. */
    fun rewrite(id: String, busy: String) {
        val p = current?.pending?.firstOrNull { it.id == id } ?: return
        if (text.isNotBlank() && text.trim() != p.body.trim()) return say(busy)
        type(p.body)
    }

    /** « Préremplir avec Mika » : elle prépare une réponse au dernier message de quelqu'un d'autre. Ce que le serveur
     *  répond (demandé, déjà demandé, une réponse déjà en chemin) se dit tel quel. */
    fun prefill(noReceived: String) {
        val t = current ?: return
        if (prefilling) return
        val off = prefillOff(accounts?.enabled ?: true, account(t.account))
        if (off.isNotEmpty()) return say(off)
        val last = lastReceived(messages) ?: return say(noReceived)
        prefilling = true
        val k = key
        val keyOf = prefillKey.of(last.ref)
        viewModelScope.launch {
            val got = api.prefill(last.ref, key = keyOf)
            prefillKey.settled(networkFailure = got is MoiApi.Result.Failed && got.error.network)
            when (got) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    if (got.value.draft.isBlank() && key == k) {
                        askedSince = askedSince + (k to now())
                        gaveUp -= k
                    }
                    if (key == k) load(quiet = true, force = true)
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
            prefilling = false
        }
    }

    override suspend fun afterDecision(r: TeamsReply, redo: Boolean) {
        // une décision se prend depuis le fil ouvert : sa réponse est de cette discussion
        if (current?.key != r.conversation) return
        if (redo) {
            askedSince = askedSince + (key to now())
            gaveUp -= key
        }
        load(quiet = true, force = true)
    }
}
