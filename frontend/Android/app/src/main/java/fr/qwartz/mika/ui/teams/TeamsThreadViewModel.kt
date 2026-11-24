package fr.qwartz.mika.ui.teams

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.CorrectWords
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.TeamsLive
import fr.qwartz.mika.data.moi.Work
import fr.qwartz.mika.data.moi.WorkTurn
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.teams.ALREADY_ASKED
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.SentHere
import fr.qwartz.mika.data.moi.teams.TeamsLimits
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.data.moi.teams.TeamsQuote
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.UNDER_WAY
import fr.qwartz.mika.data.moi.teams.citable
import fr.qwartz.mika.data.moi.teams.lastReceived
import fr.qwartz.mika.data.moi.teams.messageProblem
import fr.qwartz.mika.data.moi.teams.prefillOff
import fr.qwartz.mika.data.moi.teams.quoteTarget
import fr.qwartz.mika.data.moi.teams.stillSentHere
import fr.qwartz.mika.data.moi.teams.withoutSent
import fr.qwartz.mika.data.moi.watchWork
import fr.qwartz.mika.data.moi.workTurn
import fr.qwartz.mika.ui.shell.FieldCorrector
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/** Aller au message qu'une citation désigne ([ref]) ; [n] : le geste (deux appuis sur la même citation, deux allers). */
data class QuoteJump(val ref: String, val n: Int)

/**
 * Un fil (`Route.TeamsThread`) : la conversation ouverte, les messages plus anciens lus en plus, tes envois d'ici que
 * le moteur n'a pas encore dits, ce que tu tapes et le message que tu cites (discussion par discussion), ses réponses
 * et ce que tu en décides, ta demande à Mika et où elle en est (ADR 0306), le message cité où aller, « Corriger » ce
 * que tu tapes (ADR 0307). Un modèle par session : rouvrir une discussion la relit sans bruit ; le direct (ADR 0308,
 * [onLive]) relit le fil quand il change, où elle en est quand elle y travaille.
 */
class TeamsThreadViewModel(deps: TeamsDeps) : TeamsScreenModel(deps) {
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
    /** Où elle en est d'une réponse dans la discussion ouverte (ADR 0306) ; `null` : rien en cours. À part du fil : sa
     *  ligne seule se redessine quand l'étape change. */
    var work by mutableStateOf<Work?>(null)
        private set
    private var workJob: Job? = null
    /** Ce que tu as commencé d'écrire, discussion par discussion. */
    private val typed = mutableMapOf<String, String>()
    /** Le message que tu cites, discussion par discussion (« Citer », ADR 0305) : il part avec ton prochain message. */
    private var quoted by mutableStateOf<Map<String, TeamsMessage>>(emptyMap())
    /** Le message cité où le fil doit aller (un appui sur une citation), jusqu'à ce que l'écran y soit allé. */
    var jump by mutableStateOf<QuoteJump?>(null)
        private set
    private var jumps = 0
    private val sendKey = SendKey()
    private val prefillKey = SendKey()
    private var job: Job? = null
    private var seq = 0
    /** Ce qu'on dit quand sa réponse demandée est arrivée (le texte vient de l'écran). */
    private var arrivedText = ""
    private val gone = Channel<String>(Channel.BUFFERED)

    /** Les discussions (leur clé demandée) dont le compte n'est plus à toi — retiré, plus partagé — : l'écran de ce fil
     *  revient à la liste, plutôt qu'un fil figé qu'aucune relecture ne suivrait plus. */
    val left: Flow<String> = gone.receiveAsFlow()

    private fun now(): Long = deps.now()

    /** Le fil de la discussion ouverte ([key], la clé demandée : le serveur rend la sienne, normalisée — `principal~`
     *  en moins —, et une lecture d'une autre discussion n'arrive jamais ici). */
    val current: ConversationThread? get() = thread.valueOrNull

    /** Tous les messages chargés, du plus ancien au plus récent, chacun une fois. */
    val messages: List<TeamsMessage> get() = (older + current?.messages.orEmpty()).distinctBy { it.ref }

    /** Elle prépare une réponse demandée (« Elle s'y met… ») : demandée d'ici ou ailleurs, pas encore arrivée. */
    val asked: Boolean get() = current.let { t -> t != null && !t.underWay && (key in askedSince || t.asked) }

    /** On attend sa réponse ici : demandée, ou qu'elle prépare d'elle-même ([work]), pas encore arrivée. */
    val watching: Boolean
        get() = current.let { t -> t != null && watchWork(asked, work, arrived = t.underWay) }

    /** Ouvrir une discussion ; [arrived] : ce qu'on dit quand sa réponse demandée y arrive. */
    fun open(k: String, arrived: String) {
        arrivedText = arrived
        if (k == key && thread is Load.Ready) {
            refresh()
            return
        }
        key = k
        text = typed[k].orEmpty()
        jump = null
        thread = Load.Loading
        work = null
        workJob?.cancel()
        older = emptyList()
        olderMore = false
        load(quiet = false)
    }

    fun retry() {
        thread = Load.Loading
        load(quiet = false)
    }

    /** Relire sans bruit (un retour sur l'écran) ; une relecture déjà en cours suffit. */
    fun refresh() {
        load(quiet = true)
    }

    /** Les clés du fil ouvert : celle demandée, et celle que le serveur a rendue (normalisée). */
    private fun keys(): List<String> = listOfNotNull(key.takeIf { it.isNotEmpty() }, current?.key)

    /**
     * Le direct (ADR 0308, § 2 bis) : le fil ouvert se relit sans bruit s'il est nommé (`teams` — ses messages, ses
     * réponses, tes envois) ; où elle en est d'une réponse, s'il est nommé par `teams.work`. Une reconnexion relit les
     * deux. Rend la main quand c'est relu.
     */
    suspend fun onLive(signal: LiveSignal) {
        if (current == null) return
        val keys = keys()
        // repartie de zéro : une relecture déjà en vol a pu partir avant ce changement
        val reading = if (TeamsLive.threadShows(keys, signal)) load(quiet = true, force = true) else null
        if (TeamsLive.workShows(keys, signal)) readWork()?.join()
        reading?.join()
    }

    /**
     * Où elle en est (ADR 0306), relu sans relire le fil — le direct dit qu'elle y travaille (`teams.work`) : sa réponse
     * arrivée (`under_way`), ou plus rien de demandé ni d'en cours, le fil se relit ; sinon seule sa ligne change. Une
     * relecture déjà en cours suffit ; une relecture manquée attend le signal suivant.
     */
    fun readWork(): Job? {
        val t = current ?: return null
        workJob?.takeIf { it.isActive }?.let { return it }
        val k = key
        return viewModelScope.launch {
            val got = (api.work(t.key) as? MoiApi.Result.Ok)?.value ?: return@launch
            val shown = current
            if (k != key || shown == null) return@launch
            when (workTurn(arrived = got.underWay, asked = got.asked, work = got.work)) {
                WorkTurn.ARRIVED -> load(quiet = true, force = true)
                WorkTurn.ENDED -> {
                    // elle a fini sans en rendre (ou y a renoncé) : la ligne s'en va, le fil se relit s'il le disait
                    val said = k in askedSince || shown.asked || work != null
                    askedSince = askedSince - k
                    work = null
                    if (said) load(quiet = true, force = true)
                }
                WorkTurn.GOING -> {
                    work = got.work
                    if (got.asked != shown.asked) thread = Load.Ready(shown.copy(asked = got.asked))
                }
            }
        }.also { workJob = it }
    }

    /** Relit le fil. [quiet] : ce qui est montré reste, un refus ne se dit pas ; [force] : après un geste, la relecture
     *  repart de zéro (celle qui était en cours ne savait pas ce geste). */
    private fun load(quiet: Boolean, force: Boolean = false): Job {
        job?.takeIf { quiet && !force && it.isActive }?.let { return it }
        job?.cancel()
        val k = key
        val s = ++seq
        return viewModelScope.launch {
            // le niveau du compte décide de ce que le champ et les cartes offrent (ADR 0188) : ses comptes d'abord
            if (accounts == null || quiet) {
                val read = (loadAccounts() as? MoiApi.Result.Ok)?.value
                val shown = current
                // relu sans bruit, le compte du fil n'est plus à toi : retour à la liste
                if (quiet && read != null && shown != null && TeamsLive.threadGone(shown.account, read.accounts.map { it.key })) {
                    gone.trySend(k)
                    return@launch
                }
            }
            val started = now()
            val got = api.thread(k, size = TeamsLimits.PAGE)
            if (s != seq || k != key) return@launch
            when (got) {
                is MoiApi.Result.Ok -> settle(got.value, quiet, started)
                is MoiApi.Result.Failed -> if (!quiet || thread !is Load.Ready) thread = Load.Failed(got.error)
            }
        }.also { job = it }
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
        work = t.work
        if (t.underWay) askedSince = askedSince - key
        if (came) {
            say(arrivedText)
            deps.refreshBadges()
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

    /** Le message que tu cites dans la discussion ouverte (sa carte au-dessus du champ) ; `null` : aucun. */
    val citing: TeamsMessage? get() = quoted[key]

    /** « Citer » (l'appui long sur un message) : sa carte se pose au-dessus du champ, et ton prochain message le cite. Un
     *  autre message cité la remplace ; un message qui ne se cite pas ici ([citable]) ne change rien. */
    fun cite(m: TeamsMessage) {
        val t = current ?: return
        if (!citable(m, t.kind, account(t.account))) return
        quoted = quoted + (key to m)
    }

    /** Le × de sa carte : ton message ne citera rien. */
    fun uncite() {
        quoted = quoted - key
    }

    /** Un appui sur une citation : le fil va au message cité s'il est parmi les messages chargés ; sinon rien. */
    fun jumpTo(q: TeamsQuote) {
        val ref = quoteTarget(q, messages) ?: return
        jump = QuoteJump(ref, ++jumps)
    }

    /** L'écran y est allé (ou ne l'a pas trouvé) : ce geste est fait. */
    fun jumped(j: QuoteJump) {
        if (jump == j) jump = null
    }

    /** Ce que tu tapes, dans la borne ; un texte qui la dépasse déjà (corrigé, ADR 0307) se raccourcit encore. */
    fun type(value: String) {
        val n = chars(value)
        if (n > TeamsLimits.BODY && n > chars(text)) return
        put(key, value)
    }

    private fun put(k: String, value: String) {
        if (value.isEmpty()) typed -= k else typed[k] = value
        if (key == k) text = value
    }

    /** « Corriger » ce que tu tapes dans la discussion ouverte (ADR 0307), discussion par discussion. */
    val corrector = FieldCorrector(viewModelScope) { api.correct(it) }

    /** La discussion ouverte attend sa correction (« Correction… »). */
    val correcting: Boolean get() = corrector.busy(key)

    /** « Corriger » : les fautes de ce que tu tapes ici, sans changer tes mots ; le texte corrigé remplace le tien, et
     *  « Annuler » te le rend. Changé d'ici la réponse, ou une autre discussion ouverte, rien ne s'y pose. [on] : un
     *  modèle corrige (`GET /api/moi` → `correct`) ; sinon, [words] dit pourquoi. */
    fun correct(on: Boolean, words: CorrectWords) {
        val k = key
        corrector.correct(k, on, words, read = { if (key == k) text else null }, write = { put(k, it) })
    }

    /** Ton message (ADR 0189) : il part par l'extension du compte, sous le nom de sa personne ; une clé par geste. Le
     *  message que tu cites part avec lui (`reply_to`) ; parti, sa carte s'en va — une autre choisie pendant l'envoi
     *  reste ; refusé, elle reste avec ton texte. */
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
        val replyTo = citing?.ref.orEmpty()
        val keyOf = sendKey.of(Triple(t.key, body, replyTo))
        viewModelScope.launch {
            val got = api.send(t.key, body, replyTo = replyTo, key = keyOf)
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
                    if (replyTo.isNotEmpty() && quoted[k]?.ref == replyTo) quoted = quoted - k
                    sent = sent + SentHere(t.key, body, now())
                    say(got.value.message)
                    // sa réponse qui attendait ici ne partira plus (ADR 0199) : la pastille le suit
                    if (t.replies.any { it.waiting && !it.answered }) deps.refreshBadges()
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

    /** « Préremplir avec Mika » : elle s'y met tout de suite (ADR 0306) et prépare une réponse au dernier message de
     *  quelqu'un d'autre ; sa ligne paraît aussitôt (elle s'y met, depuis maintenant), la relecture suivante la corrige.
     *  Demandé, [askedText] le dit ; déjà demandé, ou une réponse déjà en chemin, ce que le serveur répond se dit tel
     *  quel. */
    fun prefill(noReceived: String, askedText: String) {
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
                    val draft = got.value.draft.isNotBlank()
                    say(if (draft || got.value.message == ALREADY_ASKED) got.value.message else askedText)
                    if (!draft && key == k) {
                        val at = now()
                        askedSince = askedSince + (k to at)
                        if (work == null) work = Work.waiting(at)
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
        if (redo) askedSince = askedSince + (key to now())
        load(quiet = true, force = true)
    }
}
