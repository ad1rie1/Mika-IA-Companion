package fr.qwartz.mika.ui.phone

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.PhoneLive
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.phone.OfferStates
import fr.qwartz.mika.data.moi.phone.PhoneLimits
import fr.qwartz.mika.data.moi.phone.PhoneMoiApi
import fr.qwartz.mika.data.moi.phone.PhoneOffer
import fr.qwartz.mika.data.moi.phone.PhoneThread
import fr.qwartz.mika.data.moi.phone.SentHere
import fr.qwartz.mika.data.moi.phone.decidableHere
import fr.qwartz.mika.data.moi.phone.phoneApi
import fr.qwartz.mika.data.moi.phone.replyName
import fr.qwartz.mika.data.moi.phone.stillSentHere
import fr.qwartz.mika.data.moi.phone.threadPart
import fr.qwartz.mika.data.moi.phone.underWay
import fr.qwartz.mika.data.phone.HereOutcome
import fr.qwartz.mika.data.phone.PhoneDraft
import fr.qwartz.mika.data.phone.PhoneHere
import fr.qwartz.mika.data.phone.PhoneHereGestures
import fr.qwartz.mika.ui.mail.VisitOrders
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/** Ce que l'écran dit du champ quand la proposition qu'il tenait s'est réglée (R3-04). */
enum class FieldNote {
    /** Sa proposition est réglée : ton texte retouché reste dans le champ, et partira comme ton message. */
    KEPT_AS_YOURS,

    /** Elle n'attendait plus quand tu as envoyé ta version : rien n'est parti d'ici, ton texte reste. */
    NOT_SENT,
}

/**
 * Ce qu'un geste d'ici a donné ([outcome]), ou ce que devient le champ ([field]), pour l'écran du fil [thread]
 * (`<appli>|<fil>`) : le dire, et ouvrir l'appli quand le texte a été copié — sur l'écran de la visite où le geste a
 * commencé seulement (R3-08).
 */
data class HereDone(val thread: String, val app: String, val outcome: HereOutcome? = null, val field: FieldNote? = null)

/**
 * Ce qu'un fil du Téléphone demande : l'API, les gestes d'ici (`PhoneDraftNotifier`), l'heure, les pastilles, et la
 * portée de l'application, où un geste d'ici va au bout — parti, il se règle — même si l'écran s'en va entre-temps
 * (R3-12, comme le geste fait depuis la notification).
 */
class PhoneThreadDeps(
    val api: PhoneMoiApi,
    val here: PhoneHereGestures,
    val now: () -> Long,
    val scope: CoroutineScope,
    val refreshBadges: () -> Unit = {},
) {
    constructor(graph: AppGraph) : this(graph.phoneApi(), graph.phoneDrafts, graph.clock::wallMs, graph.scope, { graph.me.refresh() })
}

/**
 * Un fil (`Route.PhoneThread`) : la conversation ouverte, ses propositions et ce que ce téléphone en tient (celles qui se
 * décident d'ici), ce que tu en as décidé d'ici tant que le serveur ne le sait pas, ce que tu tapes (conversation par
 * conversation) et ce qui en est parti. Les gestes passent par `PhoneDraftNotifier` : l'action « Répondre » de l'appli
 * gardée en mémoire — si elle répond bien à ce fil (R3-06) —, sinon le texte copié ; le geste sur ce téléphone vaut
 * accord (ADR 0120). Un modèle par session.
 *
 * Le champ qui tient sa proposition (« Écrire autre chose ») ne la garde pas une fois réglée : inchangée, elle s'en va
 * (elle ne repartirait pas comme ton message) ; retouchée, elle reste et l'écran dit qu'elle partira comme la tienne.
 * Une proposition qui n'attend plus quand tu envoies ta version : rien ne part tout seul (R3-04).
 */
class PhoneThreadViewModel(private val deps: PhoneThreadDeps) : ViewModel() {
    private val api = deps.api
    private val here = deps.here
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des relectures demandées, une fois chacun. */
    val said: Flow<String> = notices.receiveAsFlow()

    var key by mutableStateOf("")
        private set
    var thread by mutableStateOf<Load<PhoneThread>>(Load.Loading)
        private set
    /** Combien de messages on lit : la page, puis tous ceux que le serveur rend (« Messages plus anciens »). */
    var size by mutableStateOf(PhoneLimits.PAGE)
        private set
    var loadingOlder by mutableStateOf(false)
        private set
    /** Les propositions que ce téléphone a reçues et qui attendent ton geste. */
    var waiting by mutableStateOf<List<PhoneDraft>>(emptyList())
        private set
    /** À qui répond l'action « Répondre » gardée pour la conversation ouverte ; `null` : aucune (le texte est copié). */
    var replyTo by mutableStateOf<String?>(null)
        private set
    /** Ce que tu as décidé d'ici, par proposition, tant que le serveur dit encore qu'elle attend. */
    var decidedHere by mutableStateOf<Map<Long, String>>(emptyMap())
        private set
    /** Tes messages partis d'ici, tant que le fil ne les montre pas. */
    var sent by mutableStateOf<List<SentHere>>(emptyList())
        private set
    /** Ce que tu tapes dans la conversation ouverte. */
    var text by mutableStateOf("")
        private set
    /** La proposition que le champ retouche (« Écrire autre chose ») ; 0 : ton propre message. */
    var editing by mutableStateOf(0L)
        private set
    /** Un geste en cours : les boutons s'éteignent. */
    var busy by mutableStateOf(false)
        private set

    private val typed = mutableMapOf<String, String>()
    private val editingOf = mutableMapOf<String, Long>()
    /** Le texte de sa proposition tel que « Écrire autre chose » l'a mis dans le champ, par conversation. */
    private val proposedOf = mutableMapOf<String, String>()
    private val orders = VisitOrders<HereDone>()
    private var job: Job? = null
    private var seq = 0

    /** Ce que les gestes ont donné, pour l'écran de [visit] seulement : un geste fini après qu'on a quitté son écran ne
     *  se rejoue sur aucun autre, ni sur le même fil rouvert plus tard (R3-08). */
    fun gestures(visit: String): Flow<HereDone> = orders.of(visit)

    val current: PhoneThread? get() = thread.valueOrNull

    private fun now(): Long = deps.now()

    private fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    /** L'écran de [k] s'ouvre ([visit] : son passage, gardé à la rotation). */
    fun open(k: String, visit: String) {
        orders.open(visit)
        if (k == key && thread is Load.Ready) {
            refresh()
            return
        }
        key = k
        text = typed[k].orEmpty()
        editing = editingOf[k] ?: 0L
        size = PhoneLimits.PAGE
        thread = Load.Loading
        load(quiet = false)
    }

    fun retry() {
        thread = Load.Loading
        load(quiet = false)
    }

    /** Relire sans bruit (un retour sur l'écran) ; une relecture en cours suffit. */
    fun refresh() = load(quiet = true)

    /** Le direct (ADR 0308) : le fil ouvert se relit sans bruit s'il est nommé (`phone` : un message, une de ses
     *  propositions et son sort), repartant de zéro — une relecture en vol a pu partir avant ce changement. Rend la main
     *  quand c'est relu. */
    suspend fun onLive(signal: LiveSignal) {
        if (current != null && PhoneLive.threadShows(key, signal)) load(quiet = true, force = true).join()
    }

    /** « Messages plus anciens » : tous ceux que le serveur rend d'un fil. */
    fun loadOlder() {
        if (loadingOlder || size >= PhoneLimits.MAX) return
        size = PhoneLimits.MAX
        loadingOlder = true
        load(quiet = true, force = true)
    }

    /** Il en reste de plus anciens, que « Messages plus anciens » peut encore lire. */
    val canLoadOlder: Boolean get() = current?.more == true && size < PhoneLimits.MAX

    /** Ce qui se décide d'ici d'une de ses propositions : celle que ce téléphone tient, ou `null`. */
    fun decidable(o: PhoneOffer): PhoneDraft? =
        if (o.id in decidedHere) null else decidableHere(o, key, waiting, now())

    private fun load(quiet: Boolean, force: Boolean = false): Job {
        job?.takeIf { quiet && !force && it.isActive }?.let { return it }
        job?.cancel()
        val k = key
        val s = ++seq
        return viewModelScope.launch {
            val drafts = here.waiting()
            val got = api.thread(k, size)
            if (s != seq || k != key) return@launch
            waiting = drafts
            replyTo = here.replyTo(threadPart(k))
            loadingOlder = false
            when (got) {
                is MoiApi.Result.Ok -> settle(got.value)
                is MoiApi.Result.Failed -> if (!quiet || thread !is Load.Ready) thread = Load.Failed(got.error)
            }
        }.also { job = it }
    }

    private fun settle(t: PhoneThread) {
        sent = stillSentHere(sent, t, now())
        // ce que le serveur a appris de ce que tu as décidé d'ici : sa propre parole reprend
        decidedHere = decidedHere.filterKeys { id -> t.offers.any { it.id == id && underWay(it.state) } }
        // la proposition retouchée n'attend plus (réglée ailleurs, expirée) : le champ ne la garde pas telle quelle
        if (editing != 0L && t.offers.none { it.id == editing && underWay(it.state) }) {
            settledWhileEditing(key)?.let { orders.send(orders.visit, HereDone(key, t.app, field = it)) }
        }
        thread = Load.Ready(t)
    }

    // ── Écrire ──

    fun type(value: String) {
        if (chars(value) > PhoneLimits.TEXT) return
        text = value
        if (value.isEmpty()) typed -= key else typed[key] = value
    }

    /** « Écrire autre chose » : sa proposition dans le champ, à retoucher ; ce que tu enverras partira à sa place. Un
     *  champ qui a déjà ton propre texte n'est pas écrasé ([busyText]). */
    fun writeOther(o: PhoneOffer, draft: PhoneDraft, busyText: String) {
        if (text.isNotBlank() && editing != o.id && !PhoneHere.unchanged(text, draft.text)) return say(busyText)
        editing = o.id
        editingOf[key] = o.id
        proposedOf[key] = draft.text
        type(draft.text)
    }

    /** « Laisser la sienne » : le champ redevient ton propre message ; sa proposition attend encore ton geste. */
    fun stopEditing() {
        editing = 0L
        editingOf -= key
        proposedOf -= key
    }

    /**
     * Sa proposition s'est réglée (ou n'attend plus) pendant que le champ de [k] la tenait : le champ cesse de la
     * retoucher. Son texte inchangé s'en va — il ne repartirait pas comme ton message — ; retouché, il reste, et l'écran
     * le dit ([FieldNote.KEPT_AS_YOURS]).
     */
    private fun settledWhileEditing(k: String): FieldNote? {
        val proposed = proposedOf.remove(k)
        editingOf -= k
        if (key == k) editing = 0L
        val field = typed[k].orEmpty()
        if (field.isBlank()) return null
        if (proposed != null && PhoneHere.unchanged(field, proposed)) {
            typed -= k
            if (key == k) text = ""
            return null
        }
        return FieldNote.KEPT_AS_YOURS
    }

    /** Un geste d'ici, dans la portée de l'application : parti, il se règle jusqu'au bout (le carnet, la notification,
     *  son sort en file) même si l'écran s'en va pendant ce temps (R3-12). */
    private suspend fun <T> inApp(block: suspend () -> T): T = deps.scope.async { block() }.await()

    /**
     * Le champ : ta version de sa proposition (après « Écrire autre chose »), sinon ton propre message. Une proposition
     * qui n'attend plus quand tu envoies ta version : rien ne part tout seul — ton texte inchangé s'en va, retouché il
     * reste et l'écran le dit ; le renvoyer le fait partir comme ton message.
     */
    fun send() {
        val t = current ?: return
        val body = text.trim()
        if (body.isEmpty() || busy) return
        busy = true
        val k = key
        val from = orders.visit
        val offer = editing
        val proposed = proposedOf[k]
        val to = replyName(t)
        viewModelScope.launch {
            val outcome = inApp {
                if (offer != 0L) {
                    here.sendHere(offer, body, to).also { if (settles(it)) here.flushNow() }
                } else {
                    here.replyHere(threadPart(t.key), body, to)
                }
            }
            var field: FieldNote? = null
            when {
                offer != 0L && outcome == HereOutcome.GONE -> field = settledWhileEditing(k)?.let { FieldNote.NOT_SENT }
                outcome == HereOutcome.SENT || outcome == HereOutcome.COPIED -> {
                    typed -= k
                    if (key == k) text = ""
                    if (offer != 0L) {
                        editingOf -= k
                        proposedOf -= k
                        if (key == k) editing = 0L
                    }
                }
            }
            if (offer == 0L && outcome == HereOutcome.SENT) sent = sent + SentHere(t.key, body, now())
            val settled = offer != 0L && settles(outcome)
            if (settled) keep(offer, outcome, mine = proposed == null || !PhoneHere.unchanged(body, proposed))
            finish(from, HereDone(k, t.app, outcome, field), settled)
        }
    }

    /** « Envoyer » sur sa carte : sa proposition telle quelle. */
    fun sendOffer(o: PhoneOffer) {
        val to = current?.let(::replyName) ?: return
        decide(o) { here.sendHere(o.id, null, to) }
    }

    /** « Ignorer » : rien ne part, et elle le saura. */
    fun ignore(o: PhoneOffer) = decide(o) { here.ignoreHere(o.id) }

    private fun decide(o: PhoneOffer, gesture: suspend () -> HereOutcome) {
        val t = current ?: return
        if (busy) return
        busy = true
        val k = key
        val from = orders.visit
        viewModelScope.launch {
            val outcome = inApp { gesture().also { if (settles(it)) here.flushNow() } }
            keep(o.id, outcome, mine = false)
            // le champ tenait cette proposition : réglée (ou qui n'attendait plus), il ne la garde pas telle quelle
            val field = if (editingOf[k] == o.id) settledWhileEditing(k) else null
            finish(from, HereDone(k, t.app, outcome, field), settles(outcome))
        }
    }

    /** Ce geste a réglé sa proposition (son sort part au serveur). */
    private fun settles(outcome: HereOutcome): Boolean = outcome != HereOutcome.GONE && outcome != HereOutcome.NOTHING

    /** Ce que tu as décidé d'ici, montré jusqu'à ce que le serveur le dise. */
    private fun keep(id: Long, outcome: HereOutcome, mine: Boolean) {
        val state = when (outcome) {
            HereOutcome.SENT -> if (mine) OfferStates.OTHER else OfferStates.SENT
            HereOutcome.COPIED -> OfferStates.COPIED
            HereOutcome.FAILED -> OfferStates.FAILED
            HereOutcome.IGNORED -> OfferStates.IGNORED
            HereOutcome.GONE, HereOutcome.NOTHING -> return
        }
        decidedHere = decidedHere + (id to state)
    }

    /** Le geste fait : le dire à l'écran de sa visite ; son sort est déjà parti au serveur, le fil et les pastilles se
     *  relisent. */
    private fun finish(from: String, d: HereDone, settled: Boolean) {
        orders.send(from, d)
        busy = false
        if (settled) deps.refreshBadges()
        load(quiet = true, force = true)
    }
}
