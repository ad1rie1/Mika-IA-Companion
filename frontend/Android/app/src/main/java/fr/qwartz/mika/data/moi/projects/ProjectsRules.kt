package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.ofName
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/*
 * Les règles pures de l'écran Projets, portées du client web sans les réinventer (`frontendv2/src/screens/projets/` :
 * `gestures.ts`, `tones.ts`, `state.ts`, `routes.ts`, `diagram.ts`, `time.ts`). Aucune règle du moteur n'est refaite
 * ici : ce qu'on peut faire vient du serveur (`can`, `why`, `rights`), et lui seul dit si ce qui est saisi suffit. Ce
 * fichier dit quelle route et quel corps un bouton envoie, quelle couleur porte un état (les mots, eux, sont ceux du
 * serveur), et comment ce qui est lu se range à l'écran. Tout se teste sur la JVM.
 */

// ── Les couleurs d'état ─────────────────────────────────────────────────

/**
 * Les couleurs d'état, les mêmes partout (la maquette) : à toi (ambre), elle y travaille (bleu), fait ou fusionné
 * (vert), en échec ou refusé (rouge), en attente (gris-bleu).
 */
enum class StateTone { YOU, WORK, DONE, FAIL, WAIT }

fun projectTone(status: String): StateTone = if (status == "active") StateTone.WORK else StateTone.WAIT

fun objectiveTone(status: String): StateTone = when (status) {
    "done" -> StateTone.DONE
    "blocked" -> StateTone.FAIL
    else -> StateTone.WORK
}

/** Un objectif sur la carte d'un projet (`card.objectives.states`) : fait, en cours, à venir, bloqué. */
fun progressTone(state: String): StateTone = when (state) {
    "done" -> StateTone.DONE
    "blocked" -> StateTone.FAIL
    "doing" -> StateTone.WORK
    else -> StateTone.WAIT
}

/** Un jalon : atteint, retiré, prêt (à toi), refusé, commencé (elle s'y est mise), sinon à faire. */
fun milestoneTone(m: Milestone): StateTone = when {
    m.status == "reached" -> StateTone.DONE
    m.status == "dropped" -> StateTone.WAIT
    m.ready -> StateTone.YOU
    m.refusedAt > 0 -> StateTone.FAIL
    m.started -> StateTone.WORK
    else -> StateTone.WAIT
}

fun ticketTone(status: String, open: Boolean, yours: Boolean): StateTone = when {
    status == "treated" -> StateTone.DONE
    !open -> StateTone.WAIT
    yours -> StateTone.YOU
    status == "unread" || status == "proposed" -> StateTone.WAIT
    else -> StateTone.WORK
}

fun ticketTone(e: Entry): StateTone = ticketTone(e.status, e.open, e.yours)

fun pullTone(state: String): StateTone = when (state) {
    "merged" -> StateTone.DONE
    "ready" -> StateTone.YOU
    "open" -> StateTone.WORK
    else -> StateTone.WAIT
}

fun checksTone(state: String): StateTone = when (state) {
    "passed" -> StateTone.DONE
    "failed" -> StateTone.FAIL
    "pending" -> StateTone.WORK
    else -> StateTone.WAIT
}

/** Le verdict d'une exécution : continuer (bleu), terminé (vert), bloqué (rouge), elle attend quelqu'un (ambre). */
fun verdictTone(verdict: String): StateTone = when (verdict) {
    "done" -> StateTone.DONE
    "blocked" -> StateTone.FAIL
    "wait" -> StateTone.YOU
    "continue" -> StateTone.WORK
    else -> StateTone.WAIT
}

/** L'icône d'une attente d'« À faire », d'après sa sorte (et ce qu'un ticket attend) : un nom du jeu de la maquette. */
fun waitingIcon(kind: String, what: String = ""): String = when (kind) {
    "approval" -> "shield-check"
    "plan" -> "plan"
    "need" -> "question"
    "ticket" -> when (what) {
        "merge" -> "merge"
        "question" -> "question"
        "validation" -> "plan"
        else -> "ticket"
    }
    "checkpoint" -> "stop"
    "item" -> "board"
    "review" -> "eye"
    else -> "alert"
}

/** L'icône d'un jalon, d'après sa couleur. */
fun milestoneIcon(tone: StateTone): String = when (tone) {
    StateTone.DONE -> "check"
    StateTone.YOU -> "stop"
    StateTone.WORK -> "play"
    StateTone.FAIL -> "x"
    StateTone.WAIT -> "minus"
}

// ── Les mots ────────────────────────────────────────────────────────────

fun plural(n: Int, one: String, many: String): String = "$n ${if (n > 1) many else one}"

/** Les objectifs terminés d'un projet, en mots : « 1 sur 3 terminé », « 2 sur 3 terminés ». */
fun doneOf(done: Int, total: Int): String = "$done sur $total ${if (done > 1) "terminés" else "terminé"}"

/** Pour qui est un projet, tel que le serveur le dit (`mine`, `hers`, `owner_name`). */
fun forWhom(p: ProjectHead): String = when {
    p.mine -> if (p.hers) "à Mika · tu t'en occupes" else "à toi"
    p.ownerName.isNotBlank() -> ofName(p.ownerName)
    else -> "à quelqu'un d'autre"
}

/** Pour qui est un projet, et par qui il est mené (`led_by` : son nom à elle, servi avec le détail). */
fun whose(p: ProjectHead, ledBy: String = ""): String = forWhom(p) + if (ledBy.isBlank()) "" else " · menée par $ledBy"

/** Un lien qu'on peut ouvrir : http ou https seulement (une adresse venue d'ailleurs ne devient jamais autre chose). */
fun safeLink(url: String?): String = if (url != null && Regex("^https?://", RegexOption.IGNORE_CASE).containsMatchIn(url)) url else ""

/** Ce que dit un refus : son message, puis ce que disent ses champs (une raison exigée, un statut inconnu). */
fun refusalWords(message: String, fields: Map<String, String> = emptyMap()): String {
    val more = fields.values.filter { it.isNotBlank() && it !in message }
    return if (more.isEmpty()) message else "$message ${more.joinToString(" ; ")}"
}

/** Ce qui attend quelqu'un d'autre dans un projet, en une phrase : « 2 choses attendent quelqu'un d'autre (Léa). » */
fun othersWaiting(theirs: List<Waiting>): String {
    val who = theirs.firstOrNull()?.waitsFor.orEmpty()
    return plural(theirs.size, "chose attend", "choses attendent") + " quelqu'un d'autre" + (if (who.isBlank()) "" else " ($who)") + "."
}

/** Le plan d'un projet quand il attend quelque chose (proposé, à cadrer) : sa couleur et ses mots ; `null` sinon. */
fun planState(p: ProjectHead): Pair<StateTone, String>? =
    if (p.plan == "proposed" || p.plan == "to_frame") {
        (if (p.plan == "proposed" && p.waiting > 0) StateTone.YOU else StateTone.WAIT) to "plan ${p.planLabel}"
    } else {
        null
    }

/** Son prochain passage, en une ligne : quand (daté par le moteur, jamais estimé), sinon ce que le serveur en dit. */
fun nextWhen(next: NextPass, now: Long, zone: ZoneId = ZoneId.systemDefault()): String =
    if (next.state == "due" && next.at > 0) moment(next.at, now, zone) else next.stateLabel

/** Sur quoi portera son prochain passage : sa sorte, et l'objectif s'il en vise un. */
fun nextAbout(next: NextPass): String = listOf(next.sortLabel, next.objective?.text.orEmpty()).filter { it.isNotBlank() }.joinToString(" · ")

/** Qui a donné une consigne : « Ta consigne », « Consigne de Léa ». */
fun instructionBy(c: Instruction): String = if (c.authorKind == "you") "Ta consigne" else "Consigne ${ofName(c.author)}".trim()

// ── Les instants ────────────────────────────────────────────────────────

private val DAYS = listOf("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
private val MONTHS = listOf("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")

private fun dayOf(ms: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(ms).atZone(zone).toLocalDate()

/** « 3 nov. » (l'année si ce n'est pas celle-ci). */
fun shortDate(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (ms <= 0) return ""
    val d = dayOf(ms, zone)
    val label = "${d.dayOfMonth} ${MONTHS[d.monthValue - 1]}"
    return if (d.year == dayOf(now, zone).year) label else "$label ${d.year}"
}

/** Depuis quand, comme une ligne de liste : « à l'instant », « il y a 6 min », « il y a 4 h », « hier », « samedi », « 29 oct. ». */
fun since(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (ms <= 0) return ""
    val minutes = Math.floorDiv(now - ms, 60_000L)
    if (minutes < 1) return "à l'instant"
    if (minutes < 60) return "il y a $minutes min"
    val days = ChronoUnit.DAYS.between(dayOf(ms, zone), dayOf(now, zone))
    return when {
        days <= 0 -> "il y a ${minutes / 60} h"
        days == 1L -> "hier"
        days < 7 -> DAYS[dayOf(ms, zone).dayOfWeek.value - 1]
        else -> shortDate(ms, now, zone)
    }
}

/** L'âge d'une ligne serrée : [since] sans « il y a ». */
fun age(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String = since(ms, now, zone).removePrefix("il y a ")

/** Un instant dit en entier : « aujourd'hui à 14:14 », « hier à 09:02 », « lundi 2 novembre à 18:40 ». */
fun moment(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (ms <= 0) return ""
    if (now >= ms && now - ms < 60_000) return "à l'instant"
    return "${MoiDates.dayLabel(ms, now, zone).lowercase()} à ${MoiDates.clock(ms, zone)}"
}

// ── Une requête ─────────────────────────────────────────────────────────

/** Ce qu'un bouton envoie : [route] sous `/api/moi/projets/<id>/`, et son corps. */
data class GestureRequest(val route: String, val body: JsonObject)

private fun json(value: Any?): JsonElement = when (value) {
    null -> JsonNull
    is JsonElement -> value
    is Boolean -> JsonPrimitive(value)
    is Number -> JsonPrimitive(value)
    is List<*> -> JsonArray(value.map { JsonPrimitive(it.toString()) })
    else -> JsonPrimitive(value.toString())
}

private fun JsonElement.blank(): Boolean = this is JsonNull || (this as? JsonPrimitive)?.let { it.isString && it.content.isEmpty() } == true

/** Un corps tel quel : ses champs dans l'ordre, un champ vide compris (il efface, dans une modification). */
internal fun bodyOf(vararg fields: Pair<String, Any?>): JsonObject = JsonObject(fields.associate { (k, v) -> k to json(v) })

/** Un corps sans ses champs vides (ni `null`, ni texte vide) ; un nombre, un booléen, une liste restent. */
internal fun filled(vararg fields: Pair<String, Any?>): JsonObject =
    JsonObject(fields.map { (k, v) -> k to json(v) }.filterNot { it.second.blank() }.toMap())

/** Ce que le serveur sait déjà d'un geste ([args]), complété par l'écran ([more] ; `null` retire le champ). */
private fun completed(args: JsonObject, vararg more: Pair<String, Any?>): JsonObject {
    val out = LinkedHashMap<String, JsonElement>(args)
    for ((k, v) in more) out[k] = json(v)
    return JsonObject(out.filterNot { it.value.blank() })
}

private fun JsonObject.int(name: String): Int? = (this[name] as? JsonPrimitive)?.let { it.intOrNull ?: it.contentOrNull?.toIntOrNull() }
private fun JsonObject.str(name: String): String? = (this[name] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.contentOrNull

// ── Une attente et son geste ────────────────────────────────────────────

/** La clé d'une attente dans « À faire » : stable d'une lecture à l'autre, celle du client web. */
fun waitingKey(w: Waiting): String {
    val args = w.gesture.args
    return when (w.kind) {
        "approval" -> "accord-${args.str("proposal") ?: w.number}"
        "plan" -> "plan"
        "ticket" -> if (w.what == "merge") "pr-${args.str("number") ?: w.number}" else "ticket-${w.number}"
        "checkpoint" -> "jalon-${w.objective}-${args.str("milestone") ?: 0}"
        "item" -> "element-${w.what}-${w.key}"
        "need" -> "besoin-${w.objective}"
        else -> listOf(w.kind, w.objective.takeIf { it != 0 }?.toString().orEmpty(), w.number.takeIf { it != 0 }?.toString().orEmpty(), w.key)
            .filter { it.isNotEmpty() }.joinToString("-")
    }
}

/** Ce qu'un geste demande de lire avant de décider : ce qui partirait, la fiche (son plan, un jalon), un élément. */
sealed interface GestureRead {
    data object Nothing : GestureRead
    data class Accord(val id: Int) : GestureRead
    data object ProjectPlan : GestureRead
    data class Checkpoint(val objective: Int, val milestone: Int) : GestureRead
    data class Element(val list: String, val item: String) : GestureRead
}

fun gestureRead(w: Waiting): GestureRead {
    val args = w.gesture.args
    return when (w.gesture.route) {
        "accord" -> GestureRead.Accord(args.int("proposal") ?: 0)
        "plan" -> GestureRead.ProjectPlan
        "jalon" -> GestureRead.Checkpoint(args.int("objective") ?: w.objective, args.int("milestone") ?: 0)
        "element/statut", "element/noter", "ticket/trancher" ->
            GestureRead.Element(args.str("list") ?: ProjectsApi.TICKETS, args.str("item") ?: if (w.number != 0) "#${w.number}" else w.key)
        // une pull request à fusionner : son ticket se lit (ce qui lui est lié — son objectif, sa pull request, sa CI)
        MERGE_ROUTE -> if (w.kind == "ticket" && w.number != 0) GestureRead.Element(ProjectsApi.TICKETS, "#${w.number}") else GestureRead.Nothing
        else -> GestureRead.Nothing
    }
}

/**
 * La route de la fusion d'une pull request. Aucun geste générique ne l'envoie ([gestureRequest], `ProjectsApi.gesture`) :
 * elle n'a qu'un chemin, sa confirmation — `ProjectsApi.merge`, sur un [MergeOrder] né de la pull request relue.
 */
const val MERGE_ROUTE = "code/pull/fusionner"

/** Où se règle une attente : ici (et elle le peut), ici mais pas par elle, dans la console, chez l'hôte, par un autre. */
enum class GesturePlace { HERE, DENIED, CONSOLE, HOST, THEIRS }

fun gesturePlace(w: Waiting): GesturePlace = when {
    !w.mine -> GesturePlace.THEIRS
    w.gesture.where == "hote" -> GesturePlace.HOST
    w.gesture.where != "ici" || w.gesture.route.isEmpty() -> GesturePlace.CONSOLE
    w.can -> GesturePlace.HERE
    else -> GesturePlace.DENIED
}

/** Une pull request prête : sa fusion a sa confirmation, la même que dans l'onglet Code. */
fun isMerge(w: Waiting): Boolean = w.kind == "ticket" && w.what == "merge"

/** Le numéro de la pull request qu'une attente demande de fusionner (`gesture.args.number`) ; 0 : il n'est pas dit. */
fun mergeNumber(w: Waiting): Int = if (w.gesture.route == MERGE_ROUTE) w.gesture.args.int("number") ?: 0 else 0

/**
 * La requête d'un geste d'« À faire » : la route et les arguments que le serveur a donnés (`gesture`), complétés par
 * le bouton touché ([action]), ce qui est saisi ([typed]) et ce qui a été lu — le condensé d'un accord ([digest]), le
 * numéro du plan d'un ticket ([plan] : celui qu'on a montré, pas celui que la liste portait).
 */
fun gestureRequest(w: Waiting, action: String, typed: String = "", digest: String? = null, plan: Int? = null): GestureRequest {
    val route = w.gesture.route
    val args = w.gesture.args
    val text = typed.trim()
    if (route == MERGE_ROUTE) {
        // une pull request prête : sa route est la fusion, mais ce qu'on lit dans « À faire » est son ticket. Un verdict
        // touché là tranche le ticket, il ne fusionne pas ; et la fusion ne part jamais d'un geste générique : elle a sa
        // confirmation, qui nomme le commit lu ([MergeOrder]). Sans route, rien ne part.
        if (w.kind == "ticket" && w.number != 0 && action in SETTLES) {
            return GestureRequest("ticket/trancher", filled("item" to "#${w.number}", "verdict" to action, "reason" to text, "plan" to if (action == "validate") plan else null))
        }
        return GestureRequest("", JsonObject(emptyMap()))
    }
    val body = when (route) {
        "accord" -> completed(args, "decision" to action, "seen" to if (action == "accept") digest.orEmpty() else null, "note" to text)
        "plan" -> completed(args, "verdict" to action, "words" to text)
        "piloter" -> completed(args, "text" to text)
        "jalon" -> completed(args, "verdict" to action, "reason" to text)
        "element/statut" -> completed(args, "status" to action, "note" to text)
        "element/noter" -> completed(args, "text" to text)
        "ticket/trancher" -> filled(
            "item" to args.str("item"),
            "verdict" to action,
            "reason" to text,
            "plan" to if (action == "validate") plan ?: args.int("plan") ?: 0 else null,
        )
        else -> completed(args)
    }
    return GestureRequest(route, body)
}

/** Les verdicts qui tranchent un ticket (`POST …/ticket/trancher`). */
private val SETTLES = setOf("accept", "dismiss", "validate", "refuse", "done", "reopen")

/**
 * Ce que part d'« À faire » pour l'attente [w] : une réponse à sa question est une note dans le fil de son ticket ; un
 * verdict sur un ticket passe toujours par `ticket/trancher`, en nommant le plan lu — même quand l'attente porte un
 * autre geste (une pull request prête, dont le ticket s'écarte encore) ; le reste suit le geste servi.
 */
fun todoRequest(w: Waiting, action: String, typed: String, element: EntryDetail?, digest: String?): GestureRequest {
    val ticket = element?.line?.takeIf { it.list == ProjectsApi.TICKETS }
    if (action == "answer" && element != null && w.gesture.route != "element/noter") return noteRequest(element.line, typed)
    if (ticket != null && action in SETTLES && w.gesture.route != "ticket/trancher") return settleRequest(ticket, action, typed)
    return gestureRequest(w, if (action == "answer" || action == "go") "" else action, typed, digest, element?.line?.plan)
}

/** Ce que dit un bouton d'« À faire » : l'écran a ses mots pour chacun, sauf [GO] et [STATUS], qui portent ceux du serveur. */
enum class Verb {
    ACCORD_ACCEPT, ACCORD_REFUSE, PLAN_APPROVE, PLAN_REVISE, CHECKPOINT_VALIDATE, CHECKPOINT_REFUSE,
    TICKET_VALIDATE, TICKET_REFUSE, TICKET_ACCEPT, TICKET_DISMISS, STATUS, GO,
}

/** Ce qu'un bouton demande de saisir avant de partir : rien, ou un mot — exigé, sauf [WHY_OPTIONAL]. */
enum class AskFor {
    NOTHING, REVISE, MISSING, WRONG, WHY, WHY_OPTIONAL, REPLY;

    val required: Boolean get() = this != NOTHING && this != WHY_OPTIONAL
}

/** Un bouton d'une décision : ce qu'il envoie ([action]), ce qu'il dit, s'il est le geste principal, ce qu'il demande. */
data class TodoButton(
    val action: String,
    val verb: Verb,
    val primary: Boolean = false,
    val ask: AskFor = AskFor.NOTHING,
    /** Les mots du serveur, pour [Verb.GO] (le libellé du geste) et [Verb.STATUS] (le statut visé). */
    val label: String = "",
    /** Éteint, avec sa raison dite à côté (un accord qui ne peut pas partir tel quel : `blocked`). */
    val enabled: Boolean = true,
)

/** La décision d'une attente : ses boutons, et si une réponse se tape sur place ([answer] : sa question). */
data class TodoDecision(val buttons: List<TodoButton> = emptyList(), val answer: Boolean = false)

/**
 * Les boutons d'une attente, une fois lu ce que son geste demande ([approval], [plan], [element]) : seulement si le
 * serveur dit le geste faisable ici ([gesturePlace]), et pour un élément, ceux que son `can` ouvre — rien d'autre. Une
 * pull request prête n'a pas son bouton ici : sa fusion est dans l'onglet Code.
 */
fun todoDecision(w: Waiting, approval: Approval?, plan: Plan?, element: EntryDetail?): TodoDecision {
    if (gesturePlace(w) != GesturePlace.HERE) return TodoDecision()
    return when (gestureRead(w)) {
        is GestureRead.Accord -> if (approval == null) TodoDecision() else TodoDecision(
            listOf(
                TodoButton("accept", Verb.ACCORD_ACCEPT, primary = true, enabled = approval.blocked.isBlank()),
                TodoButton("refuse", Verb.ACCORD_REFUSE),
            ),
        )
        GestureRead.ProjectPlan -> if (plan == null) TodoDecision() else TodoDecision(
            listOf(TodoButton("approve", Verb.PLAN_APPROVE, primary = true), TodoButton("revise", Verb.PLAN_REVISE, ask = AskFor.REVISE)),
        )
        is GestureRead.Checkpoint -> TodoDecision(
            listOf(TodoButton("validate", Verb.CHECKPOINT_VALIDATE, primary = true), TodoButton("refuse", Verb.CHECKPOINT_REFUSE, ask = AskFor.MISSING)),
        )
        is GestureRead.Element -> when {
            element == null || element.line.veiled.isNotEmpty() -> TodoDecision()
            element.line.list != ProjectsApi.TICKETS -> TodoDecision(
                if (!element.more.can.status) {
                    emptyList()
                } else {
                    element.more.statuses.filter { it.code != element.line.status }.take(4)
                        .mapIndexed { i, s -> TodoButton(s.code, Verb.STATUS, primary = i == 0, label = s.label) }
                },
            )
            else -> {
                val can = element.more.can
                val asks = w.what == "question"
                val buttons = mutableListOf<TodoButton>()
                if (can.validate) buttons += TodoButton("validate", Verb.TICKET_VALIDATE, primary = true)
                if (can.refuse) buttons += TodoButton("refuse", Verb.TICKET_REFUSE, ask = AskFor.WRONG)
                if (can.accept) buttons += TodoButton("accept", Verb.TICKET_ACCEPT, primary = true)
                // « Écarter » n'est le geste principal que s'il est le seul : une question a sa réponse, une pull request prête sa fusion
                if (can.dismiss) {
                    buttons += TodoButton(
                        "dismiss", Verb.TICKET_DISMISS,
                        primary = !can.accept && !can.validate && !asks && w.what != "merge",
                        ask = if (can.dismissNeedsReason) AskFor.WHY else AskFor.WHY_OPTIONAL,
                    )
                }
                TodoDecision(buttons, answer = asks && can.note)
            }
        }
        GestureRead.Nothing -> if (w.gesture.route == MERGE_ROUTE) TodoDecision() else TodoDecision(
            listOf(TodoButton("go", Verb.GO, primary = true, ask = if (w.gesture.route == "piloter") AskFor.REPLY else AskFor.NOTHING, label = w.gesture.label)),
        )
    }
}

// ── Les gestes de la fiche ──────────────────────────────────────────────

/** Ce que l'API nomme `item` : `#n` pour un ticket, sa clé sinon. */
fun entryItem(e: Entry): String = if (e.list == ProjectsApi.TICKETS) e.handle else e.key

/** Trancher un ticket : `accept`, `dismiss`, `validate` (en nommant le plan lu), `refuse`, `done`, `reopen`. */
fun settleRequest(e: Entry, verdict: String, reason: String = ""): GestureRequest = GestureRequest(
    "ticket/trancher",
    filled("item" to e.handle, "verdict" to verdict, "reason" to reason.trim(), "plan" to if (verdict == "validate") e.plan else null),
)

/** Une note dans le fil d'un élément ; sur un ticket qui pose une question, elle y répond. */
fun noteRequest(e: Entry, text: String): GestureRequest =
    GestureRequest("element/noter", filled("list" to e.list, "item" to entryItem(e), "text" to text.trim()))

/** Piloter : une consigne (`instruct`), « vas-y maintenant » (`now`, sur un objectif s'il est nommé), `pause`, `resume`. */
fun pilotRequest(what: String, text: String = "", objective: Int = 0): GestureRequest =
    GestureRequest("piloter", filled("what" to what, "text" to text.trim(), "objective" to objective.takeIf { it != 0 }))

/** Un point d'arrêt dit prêt : validé, ou refusé avec ce qui manque. */
fun checkpointRequest(objective: Int, milestone: Int, verdict: String, reason: String = ""): GestureRequest =
    GestureRequest("jalon", filled("objective" to objective, "milestone" to milestone, "verdict" to verdict, "reason" to reason.trim()))

/** L'état d'un objectif : `open` (le rouvrir), `done` (le dire terminé), `dropped` (le retirer). */
fun objectiveStatusRequest(objective: Int, status: String): GestureRequest =
    GestureRequest("objectif/statut", bodyOf("objective" to objective, "status" to status))

/** Retirer un jalon : il reste lisible, retiré. */
fun milestoneDropRequest(objective: Int, milestone: Int, reason: String = ""): GestureRequest =
    GestureRequest("jalon/retirer", filled("objective" to objective, "milestone" to milestone, "reason" to reason.trim()))

private fun same(a: Any?, b: Any?): Boolean =
    if (a is List<*> || b is List<*>) {
        (a as? List<*>).orEmpty().map { it.toString() }.sorted() == (b as? List<*>).orEmpty().map { it.toString() }.sorted()
    } else {
        (a ?: "").toString() == (b ?: "").toString()
    }

/** Seulement ce qui change entre ce qui était servi et ce qui est saisi : le reste garde sa valeur. */
internal fun changed(before: Map<String, Any?>, after: Map<String, Any?>): List<Pair<String, Any?>> =
    after.entries.filterNot { (k, v) -> same(before[k], v) }.map { it.key to it.value }

/** Ce qu'on saisit d'un objectif ponctuel (« fini quand ») ou d'une mission (sa cadence, ce qui la déclenche…). */
data class GoalForm(
    val mission: Boolean = false,
    val text: String = "",
    val doneWhen: String = "",
    val cadenceHours: Int = 0,
    /** Les clés de ce qui la déclenche, telles que la fiche les sert (`forms.triggers`). */
    val on: List<String> = emptyList(),
    val onlyOnEvent: Boolean = false,
    val eachPass: String = "",
    /** Premier passage tout de suite (à la création d'une mission seulement). */
    val atOnce: Boolean = true,
) {
    internal fun values(): Map<String, Any?> = if (mission) {
        linkedMapOf("text" to text.trim(), "cadence_hours" to cadenceHours, "on" to on, "only_on_event" to onlyOnEvent, "each_pass" to eachPass.trim())
    } else {
        linkedMapOf("text" to text.trim(), "done_when" to doneWhen.trim())
    }

    companion object {
        fun of(o: Objective) = GoalForm(mission = false, text = o.text, doneWhen = o.doneWhen)
        fun of(m: Mission) = GoalForm(
            mission = true, text = m.text, cadenceHours = m.cadenceHours, on = m.on.map { it.key }, onlyOnEvent = m.onlyOnEvent, eachPass = m.eachPass,
        )
    }
}

/**
 * Ajouter un objectif (ou une mission), ou le modifier ([objective] nommé et [before] : seuls les champs changés
 * partent). `cadence_hours` est un nombre ; `on` une liste de clés ; `each_pass`, une ligne par chose.
 */
fun goalRequest(form: GoalForm, before: GoalForm? = null, objective: Int = 0): GestureRequest {
    val mission = before?.mission ?: form.mission
    val v = form.copy(mission = mission).values()
    if (objective != 0 && before != null) {
        return GestureRequest("objectif/modifier", bodyOf("objective" to objective, *changed(before.values(), v).toTypedArray()))
    }
    val born = ArrayList<Pair<String, Any?>>(v.map { it.key to it.value })
    born += "kind" to if (mission) "constant" else "once"
    if (mission && form.atOnce) born += "at_once" to true
    return GestureRequest("objectif", filled(*born.toTypedArray()))
}

/** Ce qu'on saisit d'un jalon : son texte, comment on le vérifie, et ce que cette façon demande. */
data class MilestoneForm(
    val text: String = "",
    val check: String = "prose",
    val command: String = "",
    val itemList: String = "",
    val item: String = "",
    val itemStatus: String = "",
    /** Pourquoi ce changement (facultatif, à la modification). */
    val reason: String = "",
) {
    internal fun values(): Map<String, Any?> {
        val v = linkedMapOf<String, Any?>("text" to text.trim(), "check" to check)
        if (check == "command") v["command"] = command.trim()
        if (check == "item") {
            v["item_list"] = itemList.trim()
            v["item"] = item.trim()
            v["item_status"] = itemStatus.trim()
        }
        return v
    }

    /** La valeur d'un champ servi par `forms.checks[].fields`, par son nom. */
    fun field(name: String): String = when (name) {
        "command" -> command
        "item_list" -> itemList
        "item" -> item
        "item_status" -> itemStatus
        else -> ""
    }

    fun with(name: String, value: String): MilestoneForm = when (name) {
        "command" -> copy(command = value)
        "item_list" -> copy(itemList = value)
        "item" -> copy(item = value)
        "item_status" -> copy(itemStatus = value)
        else -> this
    }

    companion object {
        fun of(m: Milestone) = MilestoneForm(
            text = m.text, check = m.check.ifBlank { "prose" }, command = m.command, itemList = m.itemList, item = m.item, itemStatus = m.itemStatus,
        )
    }
}

/** Ajouter un jalon, ou le modifier ([milestone] nommé et [before] : seulement ce qui change). */
fun milestoneRequest(objective: Int, form: MilestoneForm, before: MilestoneForm? = null, milestone: Int = 0): GestureRequest {
    val v = form.values()
    if (milestone != 0 && before != null) {
        val reason = form.reason.trim().takeIf { it.isNotEmpty() }?.let { listOf("reason" to it) }.orEmpty()
        return GestureRequest(
            "jalon/modifier",
            bodyOf("objective" to objective, "milestone" to milestone, *(changed(before.values(), v) + reason).toTypedArray()),
        )
    }
    return GestureRequest("jalon/ajouter", filled("objective" to objective, *v.map { it.key to it.value }.toTypedArray()))
}

/** Ce qu'on saisit d'un ticket : ses sortes et ses priorités sont celles que la fiche sert, avec leurs mots. */
data class TicketForm(val title: String = "", val text: String = "", val kind: String = "", val priority: String = "") {
    internal fun values(): Map<String, Any?> = linkedMapOf("title" to title.trim(), "text" to text, "kind" to kind, "priority" to priority)

    companion object {
        fun of(e: EntryDetail) = TicketForm(e.line.title, e.more.body, e.line.kind, e.line.priority)
        fun fresh(list: Listing?) = TicketForm(kind = list?.kindDefault.orEmpty(), priority = list?.priorityDefault.orEmpty())
    }
}

/** Ouvrir un ticket, ou le modifier ([item] nommé et [before] : seulement ce qui change ; son étape ne change pas). */
fun ticketRequest(form: TicketForm, before: TicketForm? = null, item: String = ""): GestureRequest {
    val v = form.values()
    if (item.isNotEmpty() && before != null) {
        return GestureRequest("ticket/modifier", bodyOf("item" to item, *changed(before.values(), v).toTypedArray()))
    }
    return GestureRequest("ticket", filled(*v.map { it.key to it.value }.toTypedArray()))
}

/** Un champ ne sert que pour certaines valeurs d'un autre (`only`) : se montre-t-il, vu ce qui est saisi ? */
fun fieldShown(f: Field, fields: List<Field>, values: Map<String, String>): Boolean = f.only.all { o ->
    (values[o.field] ?: fields.firstOrNull { it.name == o.field }?.value.orEmpty()) in o.values
}

/** « Nouveau projet » : ce qui est saisi, par le nom de chaque champ servi ; un champ vide ou une case décochée ne part pas. */
fun newProjectBody(fields: List<Field>, values: Map<String, String>): JsonObject = filled(
    *fields.filter { fieldShown(it, fields, values) }.mapNotNull<Field, Pair<String, Any?>> { f ->
        val raw = values[f.name] ?: f.value
        when {
            f.kind == "bool" -> if (raw == "true") f.name to true else null
            f.kind == "int" -> raw.trim().toIntOrNull()?.let { f.name to it }
            else -> f.name to raw.trim()
        }
    }.toTypedArray(),
)

// ── Ce que l'écran range ────────────────────────────────────────────────

/** « À faire », un groupe par projet. */
data class TodoGroup(val project: Int, val title: String, val items: List<Waiting>)

/** « À faire », groupé par projet : les projets dans l'ordre où le serveur les fait paraître, ses attentes dans le sien. */
fun todoGroups(todo: List<Waiting>): List<TodoGroup> {
    val groups = LinkedHashMap<Int, MutableList<Waiting>>()
    for (w in todo) groups.getOrPut(w.project) { mutableListOf() }.add(w)
    return groups.map { (project, items) -> TodoGroup(project, items.first().projectTitle, items) }
}

/** Un objectif ponctuel ou une mission, sous une même ligne ; sa clé : `o2`, `m5`. */
sealed interface Goal {
    val id: Int
    val text: String
    val can: ObjectiveCan
    val key: String

    data class Once(val o: Objective) : Goal {
        override val id get() = o.id
        override val text get() = o.text
        override val can get() = o.can
        override val key get() = "o${o.id}"
    }

    data class Constant(val m: Mission) : Goal {
        override val id get() = m.id
        override val text get() = m.text
        override val can get() = m.can
        override val key get() = "m${m.id}"
    }
}

/** Un groupe de la liste des objectifs : `open` (en cours), `missions`, `done` (terminés). */
data class GoalGroup(val code: String, val items: List<Goal>)

/** Les objectifs en trois groupes, comme la maquette : en cours, les missions, terminés. */
fun goalGroups(sheet: Sheet): List<GoalGroup> {
    val once = sheet.objectives.map { Goal.Once(it) }
    return listOf(
        GoalGroup("open", once.filter { it.o.status != "done" }),
        GoalGroup("missions", sheet.missions.map { Goal.Constant(it) }),
        GoalGroup("done", once.filter { it.o.status == "done" }),
    )
}

fun findGoal(sheet: Sheet, key: String): Goal? = goalGroups(sheet).flatMap { it.items }.firstOrNull { it.key == key }

/** Quelque chose attend la personne sur cet objectif : un point d'arrêt prêt, ou elle a besoin d'elle. */
fun goalAwaits(o: Objective): Boolean = o.need.isNotBlank() || o.milestones.any { it.ready }

/** Les jalons vivants d'un objectif (un jalon retiré reste lisible, mais ne compte plus). */
fun liveMilestones(o: Objective): List<Milestone> = o.milestones.filter { it.status != "dropped" }

/** Les couleurs des jalons d'un objectif, pour sa barre ; sans jalon, celle de son état. */
fun milestoneTones(o: Objective): List<StateTone> = liveMilestones(o).map { milestoneTone(it) }.ifEmpty { listOf(objectiveTone(o.status)) }

fun reachedCount(o: Objective): Int = liveMilestones(o).count { it.status == "reached" }

/** L'attente d'« À faire » où lui répondre quand elle a besoin de quelque chose sur cet objectif (celle que le serveur a comptée). */
fun needWaiting(sheet: Sheet, objective: Int): Waiting? =
    sheet.todo.firstOrNull { it.objective == objective && it.kind in setOf("need", "blocked", "stalled") }

/** La liste des tickets de la fiche, et ses listes de suivi. */
fun ticketList(sheet: Sheet): Listing? = sheet.lists.firstOrNull { it.tickets }

fun followLists(sheet: Sheet): List<Listing> = sheet.lists.filterNot { it.tickets }

/** Les onglets d'une fiche, dans l'ordre de la maquette. */
object SheetTabs {
    const val OVERVIEW = "vue"
    const val OBJECTIVES = "objectifs"
    const val TICKETS = "tickets"
    const val CODE = "code"
    const val DOCS = "documentation"
    const val ACTIVITY = "activite"
    const val LINKS = "dependances"
    const val LISTS = "listes"

    private val ALL = listOf(OVERVIEW, OBJECTIVES, TICKETS, CODE, DOCS, ACTIVITY, LINKS, LISTS)

    /**
     * Ceux que le serveur ouvre : sans le détail, la Vue d'ensemble seule ; « Listes » seulement pour un projet qui a
     * une liste de suivi ; « Activité » seulement avec le droit de la lire.
     */
    fun of(sheet: Sheet): List<String> {
        if (!sheet.rights.detail) return listOf(OVERVIEW)
        return ALL.filter { (it != LISTS || followLists(sheet).isNotEmpty()) && (it != ACTIVITY || sheet.rights.work) }
    }

    /**
     * L'onglet d'une adresse ; inconnu, ou fermé pour elle : la Vue d'ensemble. Une adresse peut nommer un volet de
     * l'onglet (`code/pulls`) : l'onglet est ce qui précède la barre.
     */
    fun shown(sheet: Sheet, tab: String): String = tab.substringBefore('/').let { if (it in of(sheet)) it else OVERVIEW }

    /** Le volet que nomme une adresse dans son onglet (`code/pulls` : `pulls`) ; vide : celui qui s'ouvre d'office. */
    fun sub(tab: String): String = tab.substringAfter('/', "")
}

/** Les filtres de la liste des tickets : à toi (lu dans les ouverts, côté écran), ouverts, tous. */
object TicketFilters {
    const val YOURS = "yours"
    const val OPEN = "open"
    const val ALL = "all"

    /** Ce que la liste demande au serveur pour un filtre (`state`). */
    fun state(filter: String): String = if (filter == ALL) "" else "open"

    fun shown(filter: String, items: List<Entry>): List<Entry> = if (filter == YOURS) items.filter { it.yours } else items
}

/** Les volets d'un ticket. */
object TicketPanes {
    const val DESCRIPTION = "description"
    const val PLAN = "plan"
    const val THREAD = "fil"
    const val HISTORY = "historique"
    const val INFOS = "infos"

    /** Celui qui s'ouvre d'office : son plan s'il se valide, son fil s'il pose une question ou attend d'être accepté. */
    fun first(e: EntryDetail, asks: Boolean): String = when {
        e.more.can.validate -> PLAN
        asks || e.more.can.accept -> THREAD
        else -> DESCRIPTION
    }
}

/** Ce qu'une étape du parcours dit sous son nom : la précision de l'étape en cours et à qui est la main ; pourquoi elle est sautée. */
fun stepNote(j: Journey, s: JourneyStep, handLabel: String): String = when (s.state) {
    "current" -> listOfNotNull(
        j.fineLabel.takeIf { it.isNotBlank() && !it.equals(s.label, ignoreCase = true) },
        handLabel.takeIf { j.ended.isEmpty() && it.isNotBlank() }?.let { "la main est $it" },
    ).joinToString(" · ")
    "skipped" -> s.stateLabel
    else -> ""
}

/** Une ligne de l'Historique d'un ticket : un passage d'étape, ou ce qui est arrivé à ses objectifs. */
data class StoryRow(val at: Long, val seq: Long, val tone: StateTone?, val text: String, val sha: String = "", val outside: Boolean = false)

private fun passageTone(p: Passage): StateTone = when {
    p.status == "treated" -> StateTone.DONE
    p.status == "dismissed" -> StateTone.FAIL
    p.step == "unread" || p.step.isEmpty() -> StateTone.WAIT
    p.step == "validation" -> StateTone.YOU
    else -> StateTone.WORK
}

/**
 * L'Historique : l'histoire de ses étapes (des faits, rejoués par le serveur) et, mêlé à elle dans le temps, ce qui est
 * arrivé à ses objectifs — leurs exécutions, leurs commits, leur pull request. Les lignes du fil qui redisent un passage
 * (la sorte « ticket », un geste) n'y sont pas : le passage le dit déjà.
 */
fun storyRows(history: EntryHistory, around: List<Happening>): List<StoryRow> {
    val rows = history.items.map { p ->
        val text = if (p.was.isNotEmpty()) "${p.statusLabel.replaceFirstChar { it.uppercase() }} — par ${p.author}" else "Ouvert par ${p.author} — ${p.statusLabel}"
        StoryRow(p.at, p.seq, passageTone(p), text, outside = p.outside)
    } + around.filter { it.kind != "ticket" && it.kind != "gesture" }.map { x ->
        StoryRow(x.at, x.seq, if (x.what == "merged") StateTone.DONE else null, x.title, sha = x.sha.take(7), outside = x.outside)
    }
    return rows.sortedWith(compareBy<StoryRow> { it.at }.thenBy { it.seq })
}

// ── Le diagramme ────────────────────────────────────────────────────────

/** Une ligne du diagramme : un objectif, un de ses jalons (en retrait), une mission. */
sealed interface DiagramRow {
    val o: DiagramObjective

    data class GoalRow(override val o: DiagramObjective, val folded: Boolean) : DiagramRow
    data class StepRow(override val o: DiagramObjective, val m: DiagramMilestone) : DiagramRow
    data class MissionRow(override val o: DiagramObjective) : DiagramRow
}

/** Les lignes : les objectifs dans l'ordre servi (celui du plan), chacun suivi de ses jalons sauf replié, puis les missions. */
fun diagramRows(d: Diagram, folded: Set<Int> = emptySet()): List<DiagramRow> {
    val out = mutableListOf<DiagramRow>()
    for (o in d.objectives.filter { it.kind != "constant" }) {
        val closed = o.id in folded
        out += DiagramRow.GoalRow(o, closed)
        if (!closed) for (m in o.milestones) out += DiagramRow.StepRow(o, m)
    }
    for (o in d.objectives.filter { it.kind == "constant" }) out += DiagramRow.MissionRow(o)
    return out
}

/** La couleur d'un jalon du diagramme : atteint, prêt (à toi), commencé, à venir. */
fun diagramTone(m: DiagramMilestone): StateTone = when {
    m.status == "reached" -> StateTone.DONE
    m.ready -> StateTone.YOU
    m.startedAt > 0 -> StateTone.WORK
    else -> StateTone.WAIT
}

/** La part faite d'un jalon : atteint ou prêt, entière ; commencé, selon ses exécutions (jamais entière) ; sinon rien. */
fun milestonePart(m: DiagramMilestone): Float = when {
    m.status == "reached" || m.ready -> 1f
    m.startedAt <= 0 -> 0f
    else -> minOf(0.9f, 0.15f + 0.25f * maxOf(1, m.runs))
}

/** Un segment de la barre d'un objectif : sa couleur, et sa part (de 0 à 1). */
data class Segment(val tone: StateTone, val part: Float)

private val SEGMENT_ORDER = listOf(StateTone.DONE, StateTone.YOU, StateTone.WORK, StateTone.FAIL)

/** La barre d'un objectif : la somme de ses jalons, couleur par couleur ; sans jalon, son état seul. */
fun goalSegments(o: DiagramObjective): List<Segment> {
    val n = o.milestones.size
    if (n == 0) {
        return when {
            o.status == "done" -> listOf(Segment(StateTone.DONE, 1f))
            o.status == "blocked" -> listOf(Segment(StateTone.FAIL, if (o.runs > 0) 0.5f else 0.15f))
            o.runs > 0 -> listOf(Segment(StateTone.WORK, 0.5f))
            else -> emptyList()
        }
    }
    val sums = HashMap<StateTone, Float>()
    for (m in o.milestones) sums[diagramTone(m)] = (sums[diagramTone(m)] ?: 0f) + milestonePart(m) / n
    return SEGMENT_ORDER.filter { (sums[it] ?: 0f) > 0f }.map { Segment(it, sums.getValue(it)) }
}

private fun runsWord(n: Int): String = plural(maxOf(1, n), "exécution", "exécutions")

/** Le mot au bout de la barre d'un jalon : quand il a été atteint, ce qu'il attend, ce qu'il a pris ; sinon son état servi. */
fun milestoneWord(m: DiagramMilestone, now: Long, zone: ZoneId = ZoneId.systemDefault()): String = when {
    m.status == "reached" -> if (m.reachedAt > 0) "atteint le ${shortDate(m.reachedAt, now, zone)}" else m.statusLabel
    m.ready -> "à toi · attend ta validation"
    m.startedAt > 0 -> runsWord(m.runs)
    else -> m.statusLabel
}

fun goalWord(o: DiagramObjective, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val base = when {
        o.milestonesTotal > 0 -> "${o.reached} / ${plural(o.milestonesTotal, "jalon atteint", "jalons atteints")}"
        o.status == "done" && o.closedAt > 0 -> "${o.statusLabel} le ${shortDate(o.closedAt, now, zone)}"
        else -> o.statusLabel
    }
    return base + if (o.runs > 0) " · ${runsWord(o.runs)}" else ""
}

fun missionWord(o: DiagramObjective, now: Long, zone: ZoneId = ZoneId.systemDefault()): String =
    plural(o.runs, "passage", "passages") + if (o.lastRun > 0) " · le dernier ${since(o.lastRun, now, zone)}" else ""
