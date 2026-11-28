package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.data.moi.Caps
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ago
import fr.qwartz.mika.data.moi.caps
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.thousands
import fr.qwartz.mika.data.moi.toFill
import java.text.Normalizer
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/*
 * Les règles de Teams, pures (portées de `frontend/Web/src/screens/teams/format.ts` et `markup.ts`, sans les réinventer) :
 * qui a écrit — « Toi » sur un compte à toi seulement —, l'état de ses réponses et de tes messages en attente, les
 * repères de jour du fil, une mention de toi, ce qui reste du champ une fois parti, ce qui empêche d'écrire ou de
 * préremplir ; et la citation (ADR 0305, calquée sur « Citer » de Teams mobile, pas encore dans le web) : ce qui se
 * cite, son extrait, son heure, où elle mène. Tout se teste sur la JVM.
 */

/** Les bornes que l'API tient (`app/domains/teams/api.py`, en caractères) : au-delà, elle refuse — elle ne coupe jamais. */
object TeamsLimits {
    const val BODY = 4000
    const val NOTE = 500
    const val INSTRUCTION = 4000
    /** `q` de `/teams/conversations`. */
    const val SEARCH = 100
    /** Une lecture de la liste ; une page du fil. */
    const val CONVERSATIONS = 100
    const val PAGE = 50
}

/** Une réponse encore en chemin (une autre ne se prépare pas dans la même conversation). */
val UNDER_WAY: Set<String> = setOf(ReplyStates.WAITING, ReplyStates.APPROVED, ReplyStates.QUEUED, ReplyStates.PLACED)

/** Ce que dit le serveur d'une demande déjà faite (`app/domains/teams/api.py::prefill`). */
const val ALREADY_ASKED = "Elle y travaille déjà."

/** Au-delà, l'extension ne s'est pas manifestée depuis trop longtemps pour que ce qui part parte vite. */
const val QUIET_MS = 2 * 3600_000L

// ── Qui a écrit (un compte à toi, ou qu'on te partage) ──────────────────

/** Ce qu'ouvre ton niveau sur ce compte ; un compte qu'on ne connaît pas (pas encore lu) n'ouvre que la lecture. */
fun capsOf(a: TeamsAccount?): Caps = caps(a?.level ?: Levels.READ)

/** Le compte est-il à toi (le tien, ou « à toi », commun à ses propriétaires) ? Un compte qu'on ne connaît pas ne
 *  l'est pas : on ne t'attribue jamais un message sans le savoir. */
fun ownAccount(a: TeamsAccount?): Boolean = a?.level == Levels.OWNER

/** Un message de toi : écrit par la personne du compte, sur un compte à toi (à droite, comme dans Teams). Sur un
 *  compte qu'on te partage, la personne du compte est quelqu'un d'autre : son message est à gauche, comme les autres. */
fun fromYou(m: TeamsMessage, a: TeamsAccount?): Boolean = m.own && ownAccount(a)

/** Ce que dit « Toi ». */
const val YOU = "Toi"

/** Qui a écrit un message, tel qu'on le montre : « Toi » sur un compte à toi ; sur un compte qu'on te partage, la
 *  personne du compte (son nom dans Teams, à défaut son propriétaire) ; sinon son auteur. */
fun authorLabel(own: Boolean, author: String, a: TeamsAccount?): String {
    if (!own) return author.ifBlank { "?" }
    if (ownAccount(a)) return YOU
    return a?.selfName?.ifBlank { null } ?: a?.ownerName?.ifBlank { null } ?: author.ifBlank { "?" }
}

fun authorLabel(m: TeamsMessage, a: TeamsAccount?): String = authorLabel(m.own, m.author, a)

/** La personne de ce compte, à son nom (sa mention, et sous quel nom part ce qu'on y écrit) : la tienne sur un compte
 *  à toi ([myName] à défaut de son nom dans Teams) ; sur un compte qu'on te partage, celle de son propriétaire — jamais
 *  ton nom à toi. */
fun selfName(a: TeamsAccount?, myName: String): String =
    a?.selfName?.ifBlank { null } ?: (if (ownAccount(a)) myName else a?.ownerName).orEmpty()

/** Sous quel nom part ce qui part de ce compte, en mots : « sous ton nom » sur un compte à toi ; sur un compte qu'on
 *  te partage, sous celui de sa personne (son nom dans Teams, à défaut son propriétaire) — jamais le tien. Un compte
 *  qu'on ne connaît pas (pas encore lu) : « sous le nom du compte ». */
fun sentUnder(a: TeamsAccount?): String = when {
    a == null -> "sous le nom du compte"
    ownAccount(a) -> "sous ton nom"
    else -> "sous le nom ${ofName(selfName(a, "").ifBlank { "son propriétaire" })}"
}

/** Tu décides de ce qui part de ce compte (ses réponses qui attendent) ; sinon c'est son propriétaire. */
fun decides(a: TeamsAccount?): Boolean = capsOf(a).decide

/** Le nom d'un compte : le tien, son nom ; partagé, à son propriétaire (« Atelier d'Adrien Moreau », ADR 0188). */
fun accountTitle(a: TeamsAccount): String {
    val name = a.name.ifBlank { a.key }
    return if (a.own || a.ownerName.isBlank()) name else "$name ${ofName(a.ownerName)}"
}

/** Les tiens d'abord, puis ceux qu'on te partage. */
fun orderedAccounts(accounts: List<TeamsAccount>): List<TeamsAccount> = accounts.filter { it.own } + accounts.filterNot { it.own }

/** Ses réponses qui attendent une décision que tu peux prendre : sur tes comptes (ce que compte la pastille). */
fun waitingYours(accounts: List<TeamsAccount>, account: String = ""): Int =
    accounts.filter { it.own && (account.isEmpty() || it.key == account) }.sumOf { it.draftsWaiting }

/** Ses réponses qui attendent ta décision, dans une liste lue (répondu autrement : plus rien à décider, ADR 0199). */
fun waitingCount(replies: List<TeamsReply>, accounts: List<TeamsAccount>): Int =
    replies.count { r -> r.waiting && !r.answered && capsOf(accounts.firstOrNull { it.key == r.account }).decide }

/** Tu décides de cette réponse ici : elle attend, personne n'a répondu autrement, et le compte est à toi. */
fun decidable(r: TeamsReply, a: TeamsAccount?): Boolean = r.waiting && !r.answered && capsOf(a).decide

// ── La liste ────────────────────────────────────────────────────────────

/** Ce qui précède le dernier message d'une ligne : la personne du compte (« Toi », ou son prénom sur un compte qu'on te
 *  partage) ; dans un groupe, le prénom de qui a écrit ; rien dans un tête-à-tête (c'est l'autre). */
fun lastPrefix(c: Conversation, a: TeamsAccount?): String {
    val last = c.last ?: return ""
    return when {
        last.own -> "${firstName(authorLabel(last, a))} : "
        c.kind != Kinds.DM -> "${firstName(last.author)} : "
        else -> ""
    }
}

/** Ce que dit une réponse qui attend : ton accord, ou celui du propriétaire du compte quand ce n'est pas toi qui
 *  décides (un compte qu'on te partage). */
private fun awaits(decides: Boolean): String = if (decides) "attend ton accord" else "attend l'accord de son propriétaire"

/** Ce que dit une ligne d'une réponse d'elle en chemin ([decides] : tu décides sur ce compte). */
fun herMark(state: String, decides: Boolean = true): String = when (state) {
    ReplyStates.WAITING -> awaits(decides)
    ReplyStates.PLACED -> "posée dans Teams"
    ReplyStates.QUEUED, ReplyStates.APPROVED -> "en file"
    else -> "brouillon de Mika"
}

/** Une conversation de groupe (plusieurs personnes) : son rond est un carré, ses messages disent qui les a écrits. */
fun isGroup(kind: String): Boolean = kind != Kinds.DM && kind != Kinds.OTHER

fun kindLabel(kind: String): String = when (kind) {
    Kinds.DM -> "tête-à-tête"
    Kinds.GROUP -> "groupe"
    Kinds.CHANNEL -> "canal"
    Kinds.MEETING -> "réunion"
    else -> "conversation"
}

/** Ce que dit la barre d'un fil sous son titre : sa sorte, et son compte quand il y en a plusieurs ou qu'il est
 *  partagé (« groupe · compte Atelier d'Adrien Moreau »). */
fun threadSubtitle(kind: String, a: TeamsAccount?, accounts: Int): String {
    val shared = a != null && !a.own
    val account = if (a != null && (accounts > 1 || shared)) {
        "compte ${a.name.ifBlank { a.key }}" + if (shared && a.ownerName.isNotBlank()) " ${ofName(a.ownerName)}" else ""
    } else {
        ""
    }
    return listOf(kindLabel(kind), account).filter { it.isNotBlank() }.joinToString(" · ")
}

// ── L'état de ses réponses ──────────────────────────────────────────────

private fun plain(text: String): String =
    Normalizer.normalize(text, Normalizer.Form.NFKC).replace(Regex("""\s+"""), " ").trim().lowercase()

/** Ce qui est parti diffère de ce qu'elle avait écrit (retouchée ici, ou dans Teams avant l'envoi). */
fun retouched(r: TeamsReply): Boolean {
    if (r.edited) return true
    return r.sentText.isNotEmpty() && r.body.isNotEmpty() && !plain(r.sentText).contains(plain(r.body))
}

/** L'état d'une réponse, en mots, et son ton ([decides] : tu décides sur son compte ; sinon elle attend son
 *  propriétaire). Une réponse à laquelle on a répondu autrement n'attend plus rien, même avant que le moteur ne l'ait
 *  refusée, et son refus le dit (ADR 0199). */
fun replyState(r: TeamsReply, zone: ZoneId = ZoneId.systemDefault(), decides: Boolean = true): Pair<Tone, String> {
    if (r.answered && r.state == ReplyStates.WAITING) return Tone.NEUTRAL to "répondu autrement"
    if (r.answered && r.state == ReplyStates.REFUSED) return Tone.NEUTRAL to "refusée · répondu autrement"
    return when (r.state) {
        ReplyStates.WAITING -> Tone.WARN to (awaits(decides) + if (r.expires > 0) " · jusqu'à ${MoiDates.clock(r.expires, zone)}" else "")
        ReplyStates.APPROVED -> Tone.INFO to "approuvée, en partance"
        ReplyStates.QUEUED -> Tone.INFO to "en file"
        ReplyStates.PLACED -> Tone.INFO to "posée dans Teams"
        ReplyStates.SENT -> Tone.OK to (if (retouched(r)) "partie · retouchée" else "partie")
        ReplyStates.UNUSED -> Tone.DANGER to "pas servie"
        ReplyStates.REFUSED -> Tone.NEUTRAL to "refusée"
        ReplyStates.EXPIRED -> Tone.NEUTRAL to "expirée"
        ReplyStates.FAILED -> Tone.DANGER to "échec"
        else -> Tone.NEUTRAL to r.state
    }
}

/** Ce que dit la carte d'une réponse en chemin, dans sa conversation ; vide pour une autre. [under] : sous quel nom
 *  part ce qui part du compte ([sentUnder]) ; [decides] : tu décides sur ce compte (sinon son propriétaire). */
fun cardState(
    r: TeamsReply,
    zone: ZoneId = ZoneId.systemDefault(),
    under: String = "sous ton nom",
    decides: Boolean = true,
): Pair<Tone, String> = when (r.state) {
    ReplyStates.WAITING -> Tone.WARN to (
        (if (decides) "Ton accord : elle part quand tu l'acceptes, ici" else "L'accord de son propriétaire : elle part quand il l'accepte") +
            if (r.expires > 0) " · jusqu'à ${MoiDates.clock(r.expires, zone)}" else ""
        )
    ReplyStates.APPROVED, ReplyStates.QUEUED -> Tone.INFO to "En file : l'extension l'envoie dans Teams, $under"
    ReplyStates.PLACED -> Tone.INFO to "Posée dans la zone de saisie de Teams : tu l'envoies là-bas"
    else -> Tone.NEUTRAL to ""
}

/** Comment part ce qu'elle prépare, en mots. */
fun modeLabel(mode: String): String = when (mode) {
    ReplyModes.DRAFT -> "brouillon"
    ReplyModes.APPROVAL -> "ton accord"
    ReplyModes.ALONE -> "seule"
    else -> mode
}

fun modeTitle(mode: String): String = when (mode) {
    ReplyModes.DRAFT -> "Posée dans la zone de saisie de Teams : c'est toi qui l'envoies"
    ReplyModes.APPROVAL -> "Après ton accord : elle part une fois que tu l'as acceptée"
    ReplyModes.ALONE -> "Seule : elle part sans te demander"
    else -> ""
}

/** Il ne peut pas partir tel quel : ce que dit l'aperçu, ou un passage à compléter. */
fun replyBlocked(r: TeamsReply): String = r.preview?.blocked?.takeIf { it.isNotBlank() }
    ?: if (r.waiting && r.toFill) "il reste des passages à compléter" else ""

/** Le texte qu'on montre d'une réponse : ce qui est parti, sinon exactement ce qui partira, sinon ce qu'elle a écrit. */
fun replyText(r: TeamsReply): String =
    if (r.state == ReplyStates.SENT && r.sentText.isNotBlank()) r.sentText else r.preview?.text ?: r.body

/** Les réponses d'elle que le fil montre en carte : celles en chemin ; et celle à laquelle on a répondu autrement,
 *  tant que rien n'est venu dans le fil depuis (la carte dit qu'elle ne partira pas). [lastAt] : le dernier message
 *  du fil chargé. */
fun threadCards(replies: List<TeamsReply>, lastAt: Long): List<TeamsReply> =
    replies.filter { r -> if (r.answered) maxOf(r.decidedAt, r.at) >= lastAt else r.state in UNDER_WAY }

/** Un message de toi qui est ce qu'elle avait préparé (une réponse partie, au même texte) : « rédigé avec Mika ». */
fun fromHer(m: TeamsMessage, replies: List<TeamsReply>): Boolean {
    if (!m.own) return false
    val text = plain(m.text)
    return replies.any { r ->
        r.state == ReplyStates.SENT && text.isNotEmpty() &&
            (plain(r.sentText) == text || plain(r.sentText).startsWith(text) || plain(r.body) == text)
    }
}

// ── Le fil ──────────────────────────────────────────────────────────────

private fun day(ms: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(ms).atZone(zone).toLocalDate()

/** « Aujourd'hui », « Hier », sinon « lundi 2 novembre » : le repère que partagent les fils ([MoiDates.dayLabel]). */
fun dayLabel(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String = MoiDates.dayLabel(ms, now, zone)

/** Ce qui précède un message : un repère de jour quand il change (vide sinon), et s'il continue le même auteur. */
data class Mark(val day: String, val suite: Boolean)

/** Les repères de chaque message : le jour quand il change ; la suite d'un même auteur, à moins de dix minutes. */
fun threadMarks(messages: List<TeamsMessage>, now: Long, zone: ZoneId = ZoneId.systemDefault()): List<Mark> =
    messages.mapIndexed { i, m ->
        val prev = messages.getOrNull(i - 1)
        val newDay = prev == null || day(prev.at, zone) != day(m.at, zone)
        val same = prev != null && prev.authorId.ifEmpty { prev.author } == m.authorId.ifEmpty { m.author } && prev.own == m.own
        Mark(if (newDay) dayLabel(m.at, now, zone) else "", !newDay && same && m.at - prev!!.at < 10 * 60_000L)
    }

/** Les mentions de toi dans un texte (« @Adrien Moreau », « @Adrien »), pour les mettre en valeur — seulement quand le
 *  serveur dit que le message te mentionne. */
fun mentionRanges(text: String, selfName: String, mentioned: Boolean): List<IntRange> {
    val name = selfName.trim()
    if (!mentioned || name.isEmpty()) return emptyList()
    val names = listOf(name, firstName(name)).filter { it.isNotEmpty() }.distinct()
    val pattern = Regex("@(?:" + names.joinToString("|") { Regex.escape(it) } + ")")
    return pattern.findAll(text).map { it.range }.toList()
}

/** Le dernier message de quelqu'un d'autre (celui auquel « Préremplir » répond). */
fun lastReceived(messages: List<TeamsMessage>): TeamsMessage? = messages.lastOrNull { !it.own }

// ── La citation (ADR 0305, « Citer » de Teams) ──────────────────────────

/** Les conversations où un envoi cite : un tête-à-tête, un groupe (`QUOTE_KINDS` du serveur). Dans un canal ou une
 *  réunion, une réponse est un fil : le serveur n'y cite pas, l'écran n'offre pas « Citer ». */
val QUOTE_KINDS: Set<String> = setOf(Kinds.DM, Kinds.GROUP)

/** « Citer » s'offre sur ce message : il a sa référence (le serveur cite d'après elle), la conversation cite, et tu
 *  peux écrire de ce compte (un compte qu'on ne connaît pas encore n'ouvre que la lecture). */
fun citable(m: TeamsMessage, kind: String, a: TeamsAccount?): Boolean =
    m.ref.isNotBlank() && kind in QUOTE_KINDS && capsOf(a).write

/** L'extrait d'un message cité, ses blancs serrés en une ligne (l'écran le coupe à deux lignes au-dessus du champ, à
 *  trois dans la bulle). */
fun quoteExcerpt(text: String): String = text.replace(Regex("""\s+"""), " ").trim()

/** Quand le message cité a été écrit, en petit : l'heure aujourd'hui, sinon le jour et l'heure (« hier 21:41 »,
 *  « lun. 08:12 », « 28 oct. 13:31 ») ; vide sans heure. */
fun quoteWhen(at: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val day = MoiDates.short(at, now, zone)
    val time = MoiDates.clock(at, zone)
    return if (day.isEmpty() || day == time) day else "$day $time"
}

/** Le message du fil chargé qu'une citation désigne (sa référence), pour y aller ; `null` : le message cité n'est pas
 *  chez Mika, ou pas parmi les messages chargés — l'appui ne mène à rien. */
fun quoteTarget(q: TeamsQuote, messages: List<TeamsMessage>): String? =
    q.ref.takeIf { ref -> ref.isNotBlank() && messages.any { it.ref == ref } }

/** Qui a écrit le message cité, tel que la citation le dit ; à défaut, l'auteur du message désigné s'il est chargé
 *  (comme le fil le nomme) ; sinon « Quelqu'un » (comme le web). */
fun quoteAuthor(q: TeamsQuote, messages: List<TeamsMessage>, a: TeamsAccount?): String =
    q.author.trim().ifEmpty {
        val target = quoteTarget(q, messages)?.let { ref -> messages.first { it.ref == ref } }
        target?.let { authorLabel(it, a) } ?: SOMEONE
    }

/** Ce que dit une citation dont on ne sait pas l'auteur. */
const val SOMEONE = "Quelqu'un"

// ── Ce que tu as écrit toi-même et qui n'est pas encore dans le fil (ADR 0189) ──

/** Ton envoi depuis cet écran, que le moteur n'a pas encore pu dire ([at] : quand il l'a accepté). */
data class SentHere(val conversation: String, val text: String, val at: Long)

/** Une bulle de toi qui n'est pas (encore) un message du fil : ce qu'elle dit d'elle-même, et si elle n'est pas
 *  partie. [id] : son brouillon chez le moteur (vide pour un envoi d'ici pas encore relu). */
data class OwnBubble(
    val id: String, val text: String, val at: Long, val note: String, val failed: Boolean,
    /** Parti : envoyé par l'extension, pas encore revenu dans le fil (ADR 0308). */
    val sent: Boolean = false,
)

/** Ce que dit l'état d'un de tes messages en attente, et s'il ne partira pas. [under] : sous quel nom il part
 *  ([sentUnder] : sur un compte qu'on te partage, celui de sa personne). */
fun pendingNote(state: String, reason: String = "", under: String = "sous ton nom"): Pair<String, Boolean> = when (state) {
    OwnStates.QUEUED -> "en file : l'extension l'envoie dans Teams, $under" to false
    OwnStates.SENDING -> "en cours d'envoi par l'extension" to false
    OwnStates.PLACED -> "posé dans la zone de saisie de Teams : c'est toi qui l'envoies, de là-bas" to false
    OwnStates.SENT -> "parti dans Teams" to false
    OwnStates.UNUSED -> "pas parti : l'extension ne l'a pas relevé à temps (Teams web n'était pas ouvert avec elle)" to true
    OwnStates.FAILED -> "pas parti : l'envoi a échoué${if (reason.isNotBlank()) " ($reason)" else ""}" to true
    else -> state.ifBlank { "en attente" } to false
}

private fun norm(text: String): String = Normalizer.normalize(text, Normalizer.Form.NFD).replace(Regex("[̀-ͯ]"), "").lowercase()

/**
 * Tes envois d'ici qui restent à montrer après une lecture du fil. Un moteur qui dit `pending` connaît tout envoi qu'il
 * a accepté avant que la lecture ne commence ([started]) : sa liste fait foi, l'envoi d'ici s'efface. Un moteur qui ne
 * le dit pas : l'envoi s'efface quand un message de toi au même texte revient dans le fil.
 */
fun stillSentHere(local: List<SentHere>, t: ConversationThread, started: Long): List<SentHere> = local.filter { p ->
    when {
        p.conversation != t.key -> true
        t.pending != null -> p.at > started
        else -> {
            val text = norm(p.text).trim()
            t.messages.none { m -> m.own && norm(m.text).trim() == text && m.at >= p.at - 120_000L }
        }
    }
}

/** Les bulles de toi au bas du fil : ce que le moteur dit de tes messages en attente, du plus ancien au plus récent,
 *  puis tes envois d'ici qu'il n'a pas encore pu dire. [under] : sous quel nom ils partent ([sentUnder]). */
fun ownBubbles(pending: List<OwnPending>?, local: List<SentHere>, under: String = "sous ton nom"): List<OwnBubble> {
    val fromEngine = pending.orEmpty().sortedBy { it.at }.map { p ->
        val (note, failed) = pendingNote(p.state, p.reason, under)
        OwnBubble(p.id, p.body, p.at, note, failed, sent = p.state == OwnStates.SENT)
    }
    val (note, failed) = pendingNote(OwnStates.QUEUED, under = under)
    return fromEngine + local.map { OwnBubble("", it.text, it.at, note, failed) }
}

/** Ce qui reste d'une saisie une fois [sent] parti : ce qu'on a tapé après lui (vide s'il n'y a rien d'autre), ou
 *  `null` quand la saisie ne commence plus par lui (on y a tapé autre chose : elle reste telle quelle). */
fun withoutSent(value: String, sent: String): String? {
    val lead = value.trimStart()
    return if (sent.isNotEmpty() && lead.startsWith(sent)) lead.substring(sent.length).trimStart() else null
}

/** Ce qui empêche ton message de partir tel quel (une phrase à dire) ; vide : il peut partir. Le serveur refuserait
 *  de toute façon : rien ne part coupé. */
fun messageProblem(text: String): String {
    val t = text.trim()
    if (toFill(t)) return "Il reste des passages [À COMPLÉTER] à remplir."
    val n = chars(t)
    if (n > TeamsLimits.BODY) {
        return "Ton message est trop long : ${thousands(TeamsLimits.BODY)} caractères au plus (il en a ${thousands(n)})."
    }
    return ""
}

// ── Ce qui part, et ce qu'elle prépare ──────────────────────────────────

/** Teams coupé, ou ce compte décoché : rien n'en part, et elle n'y prépare rien (l'API refuse « Préremplir », 409). */
fun accountOff(enabled: Boolean, a: TeamsAccount?): String = when {
    !enabled -> "Teams est désactivé"
    a != null && !a.enabled -> "Ce compte Teams est décoché"
    else -> ""
}

/** Pourquoi « Préremplir » ne servirait à rien ici ; vide : il sert. */
fun prefillOff(enabled: Boolean, a: TeamsAccount?): String =
    accountOff(enabled, a).let { if (it.isEmpty()) "" else "$it : elle n'y prépare rien." }

/** Ce qui retient ce qui part de ce compte : Teams coupé, le compte décoché, ou une extension qui se tait depuis
 *  longtemps (ou ne s'est jamais manifestée) ; vide : rien ne le retient. */
fun quietLine(enabled: Boolean, a: TeamsAccount?, now: Long): String {
    val off = accountOff(enabled, a)
    return when {
        !enabled -> "Teams est désactivé : rien ne part."
        off.isNotEmpty() -> "$off : rien n'en part."
        a == null -> ""
        a.lastBatch <= 0 -> "L'extension de ce compte ne s'est encore jamais manifestée : rien ne partira tant que Teams web n'est pas ouvert avec elle."
        now - a.lastBatch > QUIET_MS ->
            "L'extension ne s'est pas manifestée depuis ${ago(a.lastBatch, now).removePrefix("il y a ")} : ce qui part attend que Teams web soit ouvert avec elle."
        else -> ""
    }
}

/** Ce que dit un compte qu'on ne te partage pas pour t'en servir, à la place du champ. */
fun readOnlyLine(level: String, owner: String): String =
    if (level == Levels.PREPARE) {
        "Ce compte t'est partagé en lecture et préparation : Mika peut t'y préparer une réponse, que ${owner.ifBlank { "son propriétaire" }} approuve."
    } else {
        "Ce compte t'est partagé en lecture : tu lis ses discussions, sans y écrire."
    }
