package fr.qwartz.mika.data.moi.phone

import fr.qwartz.mika.data.approvals.Approvals
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ago
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.phone.PhoneDraft
import fr.qwartz.mika.data.phone.PhoneHere
import fr.qwartz.mika.data.phone.PhoneReading
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/*
 * Les règles du Téléphone, pures (portées de `frontend/Web/src/screens/telephone/view.ts` sans les réinventer, plus ce que
 * le téléphone sait de lui-même) : le sort d'une proposition de Mika et ce qui s'en décide d'ici, l'appli d'une
 * conversation, le fil et ses jours, l'état de tes téléphones dans la barre de titre (ADR 0233) — « ce téléphone »
 * parmi eux —, la position, son plan et le regard de Mika, ce que dit un Téléphone d'où rien ne vient. Tout se teste
 * sur la JVM.
 */

/** Les bornes du Téléphone : ce que le serveur rend au plus (`app/domains/phone/api.py`), ce que tu écris d'ici. */
object PhoneLimits {
    /** Un fil s'ouvre sur ses messages les plus récents ; « Messages plus anciens » en lit jusqu'à [MAX]. */
    const val PAGE = 50
    /** Ce que le serveur rend au plus, d'un fil comme de la liste. */
    const val MAX = 100
    const val CONVERSATIONS = 100
    /** Ton message, au plus : ce que la porte du téléphone garde d'un message lu ([PhoneReading.MAX_TEXT]). */
    const val TEXT = PhoneReading.MAX_TEXT
}

// ── Ses propositions ────────────────────────────────────────────────────

/** Une proposition encore en chemin : préparée, ou au téléphone. */
fun underWay(state: String): Boolean = state == OfferStates.PREPARED || state == OfferStates.OFFERED

/** Ce qu'est devenue une proposition, en mots, et son ton (le web, `OFFER_WORDS`). */
fun offerWords(state: String): Pair<Tone, String> = when (state) {
    OfferStates.PREPARED -> Tone.MIKA to "préparée"
    OfferStates.OFFERED -> Tone.WARN to "au téléphone — attend ton geste"
    OfferStates.SENT -> Tone.OK to "envoyée"
    OfferStates.OTHER -> Tone.NEUTRAL to "tu as écrit autre chose"
    OfferStates.COPIED -> Tone.INFO to "copiée"
    OfferStates.IGNORED -> Tone.NEUTRAL to "laissée"
    OfferStates.FAILED -> Tone.DANGER to "échec"
    OfferStates.EXPIRED -> Tone.NEUTRAL to "expirée"
    else -> Tone.NEUTRAL to state
}

/** Le titre de sa carte dans le fil : elle propose tant que c'est en chemin, puis partie ou non. */
fun offerTitle(state: String): String = when {
    underWay(state) -> "Mika propose de répondre"
    state == OfferStates.SENT || state == OfferStates.COPIED -> "Réponse de Mika"
    else -> "Réponse de Mika, non partie"
}

/**
 * La marque d'une conversation d'après la réponse de Mika qui y compte (`her`) : en chemin, elle attend ton geste ;
 * partie, copiée ou en échec, c'est une nouvelle ; laissée, remplacée par ce que tu as écrit ou expirée, non (`null`).
 */
fun herMark(state: String?): Pair<Tone, String>? = when {
    state == null -> null
    underWay(state) -> Tone.MIKA to "réponse proposée"
    state == OfferStates.SENT -> Tone.OK to "Mika a répondu"
    state == OfferStates.COPIED -> Tone.INFO to "copiée"
    state == OfferStates.FAILED -> Tone.DANGER to "échec"
    else -> null
}

/** Le fil d'une clé de conversation (`<appli>|<fil>`) : la clé sous laquelle ce téléphone garde son action « Répondre ». */
fun threadPart(key: String): String = key.substringAfter('|', "")

/** Le code de l'appli d'une clé de conversation. */
fun appPart(key: String): String = key.substringBefore('|', "")

/**
 * La proposition que ce téléphone tient encore pour [offer] — celle qui se décide d'ici —, ou `null`. Seulement une
 * proposition offerte au téléphone, que **ce** téléphone a reçue (par Firebase, gardée dans son carnet, [waiting]) pour
 * la même appli et la même conversation, et qui n'a pas expiré : une proposition d'un autre téléphone, ou déjà réglée,
 * ne se décide pas d'ici.
 */
fun decidableHere(offer: PhoneOffer, key: String, waiting: List<PhoneDraft>, now: Long): PhoneDraft? {
    if (offer.state != OfferStates.OFFERED) return null
    val thread = threadPart(key)
    val app = appPart(key)
    return waiting.firstOrNull { it.id == offer.id && it.exp > now && it.thread == thread && it.app == app }
}

/** Le sort à montrer : celui que tu as décidé d'ici, tant que le serveur ne l'a pas encore appris ; sinon le sien. */
fun shownState(offer: PhoneOffer, decidedHere: Map<Long, String>): String =
    decidedHere[offer.id]?.takeIf { underWay(offer.state) } ?: offer.state

/** Les conversations où une réponse d'elle est en chemin (le bandeau rose). */
fun proposals(conversations: List<PhoneConversation>): List<PhoneConversation> =
    conversations.filter { underWay(it.her?.state.orEmpty()) }

/** La proposition de [c] que ce téléphone tient, s'il la tient. */
fun draftFor(c: PhoneConversation, waiting: List<PhoneDraft>): PhoneDraft? =
    c.her?.let { h -> waiting.firstOrNull { it.id == h.id && it.app == appPart(c.key) && it.thread == threadPart(c.key) } }

/** La ligne du bandeau : « Rando dimanche · « 9h ça me va 👍… » · expire dans 1 h 52 » (son texte et son échéance,
 *  quand ce téléphone tient la proposition). */
fun proposalLine(c: PhoneConversation, draft: PhoneDraft?, now: Long): String =
    listOfNotNull(
        conversationTitle(c),
        draft?.let { "« ${lead(it.text, LEAD)} »" },
        draft?.let { Approvals.expiryLabel(it.exp, now) },
    ).filter { it.isNotBlank() }.joinToString(" · ")

private const val LEAD = 32

/** Le début d'un texte, sur une ligne : au-delà de [max] caractères, coupé (jamais au milieu d'un émoji) et « … ». */
fun lead(text: String, max: Int): String {
    val all = text.trim()
    val line = all.lineSequence().first().trim()
    val n = line.codePointCount(0, line.length)
    val cut = if (n > max) line.substring(0, line.offsetByCodePoints(0, max)).trimEnd() else line
    return if (n > max || line.length < all.length) "$cut…" else cut
}

// ── Les conversations ───────────────────────────────────────────────────

/** Ce qui se dit pour toi, devant ton dernier message. */
const val YOU = "Toi"

/** Le titre d'une conversation : le groupe ou qui écrit ; sinon l'appli. */
fun conversationTitle(title: String, appName: String): String =
    title.trim().ifEmpty { appName.trim().ifEmpty { "Conversation" } }

fun conversationTitle(c: PhoneConversation): String = conversationTitle(c.title, c.appName)

/** Le titre d'un fil : le groupe, sinon qui a écrit en dernier (comme la liste) ; sinon l'appli. */
fun threadTitle(t: PhoneThread): String =
    conversationTitle(t.title.ifBlank { t.messages.lastOrNull { !it.own && it.sender.isNotBlank() }?.sender.orEmpty() }, t.appName)

/** À qui répond ce fil, tel qu'il le dit : le groupe, sinon qui y a écrit en dernier (le nom que la notification de
 *  l'appli lui donnait) ; vide si rien ne le dit. */
fun replyName(t: PhoneThread): String =
    if (t.group) t.title.trim() else t.messages.lastOrNull { !it.own && it.sender.isNotBlank() }?.sender?.trim().orEmpty()

/** Comment part ce qu'on envoie d'ici dans un fil (la ligne sous le champ, dite avant le geste). */
sealed interface ReplyWay {
    /** Par l'action « Répondre » gardée de l'appli, à [to]. */
    data class Action(val to: String) : ReplyWay

    /** Aucune action gardée : le texte est copié, l'appli s'ouvre pour le coller. */
    data object Copy : ReplyWay

    /** L'action gardée répond à [kept], pas à [shown] (deux conversations sous la même clé) : pas d'envoi d'ici, le
     *  texte est copié — tu choisis la conversation dans l'appli. */
    data class Other(val kept: String, val shown: String) : ReplyWay
}

/** [kept] : le nom à qui répond l'action gardée pour ce fil (`PhoneHereGestures.replyTo`), `null` sans action. */
fun replyWay(kept: String?, t: PhoneThread): ReplyWay {
    val shown = replyName(t)
    return when {
        kept == null -> ReplyWay.Copy
        PhoneHere.canDeliver(kept, shown) -> ReplyWay.Action(kept.trim())
        else -> ReplyWay.Other(kept.trim(), shown)
    }
}

/** Qui a écrit le dernier message, devant son texte : « Toi : », « Julien : » dans un groupe, rien sinon. */
fun snippetOf(c: PhoneConversation): String {
    val last = c.last ?: return ""
    val who = when {
        last.own -> "$YOU : "
        c.group && last.sender.isNotBlank() -> "${firstName(last.sender)} : "
        else -> ""
    }
    return who + last.text
}

/** Sous le titre d'un fil : son appli ; dans un groupe, aussi ceux qui y écrivent (les plus récents d'abord). */
fun threadSubtitle(t: PhoneThread): String {
    val app = t.appName.trim().ifEmpty { "Téléphone" }
    if (!t.group) return app
    val names = t.messages.asReversed().filter { !it.own && it.sender.isNotBlank() }.map { firstName(it.sender) }.distinct()
    if (names.isEmpty()) return "Groupe $app"
    return "$app · " + names.take(MEMBERS).joinToString(", ") + if (names.size > MEMBERS) "…" else ""
}

private const val MEMBERS = 4

/** Les sortes d'appli, pour la pastille d'une conversation. */
enum class AppKind { WHATSAPP, MESSENGER, MESSAGES, OTHER }

/** La pastille d'une appli : sa sorte (sa couleur) et sa lettre. */
data class AppBadge(val kind: AppKind, val letter: String)

fun appBadge(app: String, appName: String): AppBadge = when (app) {
    "whatsapp", "whatsapp_business" -> AppBadge(AppKind.WHATSAPP, "W")
    "messenger" -> AppBadge(AppKind.MESSENGER, "M")
    "messages", "samsung_messages", "sms" -> AppBadge(AppKind.MESSAGES, "M")
    else -> {
        val name = appName.trim()
        AppBadge(AppKind.OTHER, if (name.isEmpty()) "?" else name.substring(0, name.offsetByCodePoints(0, 1)).uppercase())
    }
}

// ── Le fil ──────────────────────────────────────────────────────────────

/** Une ligne du fil : un repère de jour, un message (et s'il continue le même auteur), une proposition de Mika. */
sealed interface ThreadItem {
    data class Day(val label: String) : ThreadItem
    data class Message(val m: ReadMessage, val suite: Boolean) : ThreadItem
    data class Offer(val o: PhoneOffer) : ThreadItem
}

private fun dayOf(ms: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(ms).atZone(zone).toLocalDate()

/**
 * Les messages et ses propositions, dans l'ordre du temps (à égalité, le message d'abord : elle y répond), avec un
 * repère à chaque jour nouveau ; un message suit le précédent quand c'est le même auteur, à moins de dix minutes.
 */
fun timeline(messages: List<ReadMessage>, offers: List<PhoneOffer>, now: Long, zone: ZoneId = ZoneId.systemDefault()): List<ThreadItem> {
    val all = (messages.map { Triple(it.at, 0, it as Any) } + offers.map { Triple(it.at, 1, it as Any) })
        .sortedWith(compareBy({ it.first }, { it.second }))
    val out = mutableListOf<ThreadItem>()
    var day: LocalDate? = null
    var prev: ReadMessage? = null
    for ((at, _, item) in all) {
        val d = dayOf(at, zone)
        if (d != day) {
            out += ThreadItem.Day(MoiDates.dayLabel(at, now, zone))
            day = d
            prev = null
        }
        when (item) {
            is ReadMessage -> {
                val p = prev
                val suite = p != null && p.own == item.own && p.sender == item.sender && item.at - p.at < SUITE_MS
                out += ThreadItem.Message(item, suite)
                prev = item
            }
            is PhoneOffer -> {
                out += ThreadItem.Offer(item)
                prev = null
            }
        }
    }
    return out
}

private const val SUITE_MS = 10 * 60_000L

// ── Ce que tu as écrit d'ici ────────────────────────────────────────────

/** Ton message parti d'ici par l'action « Répondre » de l'appli, que le serveur n'a pas encore lu ([at] : quand). */
data class SentHere(val conversation: String, val text: String, val at: Long)

/** On le montre au plus si longtemps : passé ce délai, le fil le dit lui-même, ou ne le dira pas. */
const val SENT_HERE_MS = 10 * 60_000L

private fun same(a: String, b: String): Boolean = a.trim().replace(Regex("\\s+"), " ") == b.trim().replace(Regex("\\s+"), " ")

/** Tes messages d'ici qui ne sont pas encore revenus dans le fil de [thread] (lus par le téléphone, puis le serveur). */
fun stillSentHere(sent: List<SentHere>, thread: PhoneThread, now: Long): List<SentHere> = sent.filter { s ->
    now - s.at < SENT_HERE_MS &&
        (s.conversation != thread.key || thread.messages.none { it.own && same(it.text, s.text) && it.at >= s.at - SENT_HERE_SLACK_MS })
}

/** L'heure d'un message lu peut précéder un peu celle de l'envoi (l'horloge de l'appli). */
private const val SENT_HERE_SLACK_MS = 60_000L

// ── Tes téléphones, dans la barre de titre (ADR 0233) ───────────────────

/** Le nom court d'un téléphone : « samsung SM-S931B » pour « Android · samsung SM-S931B ». */
fun shortPhone(label: String): String =
    label.replace(Regex("""^Android\s*·\s*"""), "").trim().ifEmpty { label.trim().ifEmpty { "Téléphone" } }

/** Tes téléphones qui reçoivent encore (un révoqué ne reçoit plus rien). */
fun activePhones(phones: List<PhoneDevice>): List<PhoneDevice> = phones.filterNot { it.revoked }

/**
 * Ce téléphone parmi les tiens : celui dont le jeton est celui de la session ([tokenId], rendu à la connexion et gardé
 * avec elle) — `null` s'il n'est pas parmi les actifs. Une session ouverte avant que l'app le garde ([tokenId] `null`)
 * le reconnaît à son nom (« Android · fabricant modèle », `AppGraph.deviceLabel`), le plus récemment servi s'il y en a
 * deux du même modèle : une supposition, que Paramètres › Téléphones dit (`PhoneRow.unsure`).
 */
fun thisPhone(phones: List<PhoneDevice>, deviceLabel: String, tokenId: Long?): PhoneDevice? {
    val active = activePhones(phones)
    if (tokenId != null) return active.firstOrNull { it.id == tokenId }
    return active.filter { it.label.trim() == deviceLabel.trim() }.maxWithOrNull(compareBy({ it.lastUsed }, { it.id }))
}

/** Ce que dit le point d'un téléphone : s'il reçoit les notifications de Mika, même application fermée. */
fun pushNote(push: Boolean): String = if (push) "reçoit les notifications" else "ne reçoit pas les notifications"

/** Ce que dit le point de plusieurs téléphones. */
fun pushNotes(phones: List<PhoneDevice>): String {
    val without = phones.count { !it.push }
    return when (without) {
        0 -> "les ${phones.size} reçoivent les notifications"
        phones.size -> "aucun ne reçoit les notifications"
        else -> "$without sur ${phones.size} ne ${if (without > 1) "reçoivent" else "reçoit"} pas les notifications"
    }
}

private fun seen(lastUsed: Long, now: Long): String = if (lastUsed > 0) "vu ${ago(lastUsed, now)}" else ""

/**
 * L'état de tes téléphones tel que la barre de titre le dit : un état, pas un choix (ADR 0233) — le serveur ne dit pas
 * encore quel téléphone a reçu quel message. [line] : sous le titre ; [warn] : un d'eux ne reçoit pas les
 * notifications ; [description] : tout, téléphone par téléphone, pour un lecteur d'écran.
 */
data class PhoneBar(val label: String, val detail: String, val warn: Boolean, val description: String) {
    val line: String get() = listOf(label, detail).filter { it.isNotBlank() }.joinToString(" · ")
}

/** Où mène l'état : Paramètres › Téléphones, qui les détaille. */
private const val WHERE = "Paramètres › Téléphones"

fun phoneBar(phones: List<PhoneDevice>, deviceLabel: String, tokenId: Long?, now: Long): PhoneBar {
    val active = activePhones(phones)
    if (active.isEmpty()) return PhoneBar("Aucun téléphone", "", false, "Aucun téléphone : en connecter un, dans $WHERE")
    val mine = thisPhone(active, deviceLabel, tokenId)
    val warn = active.any { !it.push }
    // ce téléphone sert à l'instant même : dire quand on l'a vu n'apprendrait rien
    fun sentence(p: PhoneDevice) = listOf(if (p == mine) "" else seen(p.lastUsed, now), pushNote(p.push)).filter { it.isNotBlank() }.joinToString(", ")
    fun name(p: PhoneDevice) = if (p == mine) "ce téléphone (${shortPhone(p.label)})" else shortPhone(p.label)
    if (active.size == 1) {
        val one = active[0]
        val label = if (one == mine) "Ce téléphone · ${shortPhone(one.label)}" else shortPhone(one.label)
        val detail = listOf(if (one == mine) "" else seen(one.lastUsed, now), if (one.push) "" else pushNote(false))
            .filter { it.isNotBlank() }.joinToString(" · ")
        return PhoneBar(label, detail, warn, "${name(one).replaceFirstChar { it.uppercase() }}, ${sentence(one)} — $WHERE")
    }
    val label = "${active.size} téléphones"
    val detail = when {
        warn -> pushNotes(active)
        mine != null -> "dont celui-ci"
        else -> seen(active.maxOf { it.lastUsed }, now)
    }
    val each = active.joinToString(" ; ") { "${name(it)} : ${sentence(it)}" }
    return PhoneBar(label, detail, warn, "$label — $each — $WHERE")
}

// ── Quand rien ne vient du téléphone ────────────────────────────────────

/** Pourquoi Messages est vide : un compte qui n'est pas propriétaire (la porte refuse ses lots), la lecture coupée sur
 *  ce téléphone, ou rien encore. */
enum class EmptyWhy { NOT_OWNER, READING_OFF, NOTHING_YET }

/** [owner] : celui de `GET /api/moi` (pas encore lu : `null`, le conseil d'une propriétaire) ; [readingHere] : « Lui
 *  montrer mes messages » allumé sur ce téléphone. */
fun emptyWhy(owner: Boolean?, readingHere: Boolean): EmptyWhy = when {
    owner == false -> EmptyWhy.NOT_OWNER
    !readingHere -> EmptyWhy.READING_OFF
    else -> EmptyWhy.NOTHING_YET
}

// ── La position ─────────────────────────────────────────────────────────

/** « 12 m », « 1,3 km » ; rien pour une distance inconnue. */
fun distanceWords(meters: Double): String {
    if (!meters.isFinite() || meters <= 0) return ""
    if (meters < 1000) return "${meters.roundToInt()} m"
    val tenths = (meters / 100).roundToLong()
    return if (tenths % 10 == 0L) "${tenths / 10} km" else String.format(Locale.FRANCE, "%.1f km", tenths / 10.0)
}

/** « 50.636512, 3.058271 ». */
fun coordsText(c: PhoneCoords): String = String.format(Locale.ROOT, "%.6f, %.6f", c.lat, c.lon)

/** Quand, dans une phrase : « à 14:10 », « hier à 22:05 », « lundi 2 novembre à 08:12 » ; rien pour un instant inconnu. */
fun whenWords(at: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (at <= 0) return ""
    val time = MoiDates.clock(at, zone)
    return when (val day = MoiDates.dayLabel(at, now, zone)) {
        "Aujourd'hui" -> "à $time"
        "Hier" -> "hier à $time"
        else -> "$day à $time"
    }
}

/** « mesurée à 14:10 », « mesurée hier à 22:05 », « mesurée lundi 2 novembre à 08:12 ». */
fun measuredWords(at: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String =
    whenWords(at, now, zone).let { if (it.isEmpty()) "" else "mesurée $it" }

/** La fiche d'une position, sous son lieu : « ±12 m · mesurée à 14:10 · 50.636512, 3.058271 ». */
fun positionLine(p: PhonePosition, now: Long, zone: ZoneId = ZoneId.systemDefault()): String =
    listOf(
        distanceWords(p.accuracyM).let { if (it.isEmpty()) "" else "±$it" },
        measuredWords(p.at, now, zone),
        p.coords?.let(::coordsText).orEmpty(),
    ).filter { it.isNotBlank() }.joinToString(" · ")

/** Le plus petit plan autour d'une position, en mètres : sa rue et ses voisines (le web, `HERE_SPAN_M`). */
const val PLAN_MIN_SPAN_M = 300.0

/**
 * L'échelle du plan dessiné d'une position : [metersPerPx], le rayon de sa précision en pixels, et le pas du
 * quadrillage (et de la barre d'échelle) en mètres et en pixels. Le plan montre quelques fois son rayon, 300 m au
 * moins, sur son côté le plus court ([sidePx]) — comme la Carte du web (`map/scene.ts::hereSpan`).
 */
data class PlanScale(val metersPerPx: Double, val radiusPx: Float, val stepM: Int, val stepPx: Float)

private val STEPS = intArrayOf(10, 20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 50_000, 100_000)

fun planScale(accuracyM: Double, sidePx: Float): PlanScale {
    val r = if (accuracyM.isFinite() && accuracyM > 0) accuracyM else 0.0
    val span = max(PLAN_MIN_SPAN_M, 5 * r)
    val mpp = span / max(sidePx, 1f)
    val step = STEPS.firstOrNull { it >= span / 5 } ?: STEPS.last()
    return PlanScale(mpp, (r / mpp).toFloat(), step, (step / mpp).toFloat())
}

/** Un regard de Mika sur ta position, tel que sa bulle 📍 le garde dans le chat : l'instant de la mesure regardée
 *  ([fixAt]) et celui de sa réponse ([at]). */
data class Look(val fixAt: Long, val at: Long)

/** Ce que le chat dit de ses regards : le dernier sur cette position-ci ([thisFix]), et son dernier tout court. */
data class Looked(val thisFix: Look?, val last: Look?)

/** Ses regards ([looks]) face à la position montrée (mesurée à [fixAt]) : le même instant de mesure, à la seconde. */
fun lookedAt(looks: List<Look>, fixAt: Long): Looked = Looked(
    thisFix = if (fixAt > 0) looks.filter { abs(it.fixAt - fixAt) < SAME_FIX_MS }.maxByOrNull { it.at } else null,
    last = looks.maxByOrNull { it.at },
)

private const val SAME_FIX_MS = 1_000L
