package fr.qwartz.mika.data.moi.projects

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/*
 * Les règles pures des onglets Activité, Dépendances et Listes, de « Modifier le projet » et du diagramme « Dans le
 * temps » (ADR 0296), portées du client web (`frontendv2/src/screens/projets/` : `views/activity.ts`, `views/more.ts`,
 * `gestures.ts`, `diagram.ts`, `tones.ts`, `time.ts`). Aucune règle du serveur n'est refaite : ce fichier dit où mène
 * une ligne, quelle couleur porte un état, quelle route et quel corps un bouton envoie, et où se pose une barre.
 */

// ── L'activité ──────────────────────────────────────────────────────────

/** Les volets de l'onglet Activité (`activite/<volet>`). */
object ActivityTabs {
    const val FEED = "fil"
    const val RUNS = "executions"
    const val NOTEBOOK = "carnet"
    val ALL = listOf(FEED, RUNS, NOTEBOOK)

    fun of(sub: String): String = sub.substringBefore('/').let { if (it in ALL) it else FEED }

    fun tab(sub: String): String = if (sub == FEED) SheetTabs.ACTIVITY else "${SheetTabs.ACTIVITY}/$sub"
}

/** L'icône d'une sorte du fil, par son nom dans le jeu de la maquette. */
fun happeningIcon(kind: String): String = when (kind) {
    "run" -> "play"
    "commit" -> "commit"
    "pull" -> "pr"
    "ticket" -> "ticket"
    "gesture" -> "user"
    else -> "check"
}

/** L'icône d'une exécution, par sa sorte : cadrage, travail, relecture. */
fun runIcon(sort: String): String = when (sort) {
    "frame" -> "plan"
    "review" -> "eye"
    else -> "code"
}

/** La couleur d'une exécution : elle tourne, elle a terminé, elle bloque, elle demande, elle continue. */
fun runTone(running: Boolean, verdict: String): StateTone = when {
    running -> StateTone.WORK
    verdict == "done" -> StateTone.DONE
    verdict == "blocked" -> StateTone.FAIL
    verdict == "wait" -> StateTone.YOU
    verdict == "continue" -> StateTone.WORK
    else -> StateTone.WAIT
}

fun runTone(r: Run): StateTone = runTone(r.running, r.verdict)

/** La couleur de la tuile d'une ligne du fil ; `null` : neutre (un geste d'une personne, un commit). */
fun happeningTone(x: Happening): StateTone? = when {
    x.kind == "run" -> runTone(false, x.verdict)
    x.what == "merged" -> StateTone.DONE
    else -> null
}

/**
 * La clé d'une ligne du fil. Le serveur rend **deux lignes pour un même événement** quand une exécution a laissé un
 * commit (le même `seq`) : la clé porte donc aussi sa sorte et ce qu'elle dit ; la liste lui ajoute son rang si deux
 * lignes restaient égales ([keyed]).
 */
fun happeningKey(x: Happening): String = "e${x.seq}:${x.kind}:${x.what}"

/** Deux lignes du fil sont-elles la même ? */
fun sameHappening(a: Happening, b: Happening): Boolean = a.seq == b.seq && a.kind == b.kind && a.what == b.what

/**
 * Une liste lue page après page (du plus récent au plus ancien), dont la première page vient d'être relue ([fresh]) :
 * ce qu'on avait de plus ancien qu'elle ([known] : la première page d'avant et sa suite) reste — tant que la page relue
 * rejoint ce qu'on avait. Sinon rien : entre les deux il manquerait des lignes, la suite repart de la page relue.
 */
fun <T> olderKept(known: List<T>, fresh: List<T>, same: (T, T) -> Boolean): List<T> {
    val last = fresh.lastOrNull() ?: return emptyList()
    val at = known.indexOfLast { same(it, last) }
    return if (at < 0) emptyList() else known.drop(at + 1)
}

/** Où mène une ligne du fil. */
sealed interface HappeningTarget {
    data class ToRun(val id: String) : HappeningTarget
    data class ToCommit(val sha: String) : HappeningTarget
    data class ToPull(val number: Int) : HappeningTarget
    data class ToTicket(val number: Int) : HappeningTarget
    data class ToGoal(val objective: Int) : HappeningTarget
    data object Nowhere : HappeningTarget
}

/** Où mène une ligne du fil : son exécution, son commit, sa pull request, son ticket, son objectif. */
fun happeningTarget(x: Happening): HappeningTarget = when {
    x.kind == "run" && x.run.isNotEmpty() -> HappeningTarget.ToRun(x.run)
    x.kind == "commit" && x.sha.isNotEmpty() -> HappeningTarget.ToCommit(x.sha)
    x.pull > 0 -> HappeningTarget.ToPull(x.pull)
    x.ticket > 0 -> HappeningTarget.ToTicket(x.ticket)
    x.objective > 0 -> HappeningTarget.ToGoal(x.objective)
    x.run.isNotEmpty() -> HappeningTarget.ToRun(x.run)
    else -> HappeningTarget.Nowhere
}

/** Une durée en mots : « 45 s », « 14 min », « 1 h 05 » ; rien pour zéro. */
fun duration(seconds: Long): String {
    if (seconds <= 0) return ""
    if (seconds < 60) return "$seconds s"
    val minutes = ((seconds + 30) / 60).toInt()
    return if (minutes < 60) "$minutes min" else "${minutes / 60} h ${(minutes % 60).toString().padStart(2, '0')}"
}

/** Le titre d'une exécution : l'objectif qu'elle visait, sinon sa sorte. */
fun runTitle(r: Run): String = r.objective?.text?.ifBlank { null } ?: r.sortLabel.replaceFirstChar { it.uppercase() }

/** Le compte d'une sorte dans un jour de `…/activite/jours` (vide : son total). */
fun dayCount(day: JsonObject, kind: String = ""): Int = (day[kind.ifEmpty { "total" }] as? JsonPrimitive)?.intOrNull ?: 0

/** Le temps passé à la fin de chaque pas d'une exécution, en secondes, dans leur ordre. */
fun stepsSpent(steps: List<RunStep>): List<Long> {
    var spent = 0L
    return steps.map { s ->
        spent += s.ms
        spent / 1000
    }
}

// ── Les dépendances ─────────────────────────────────────────────────────

/** Les volets de l'onglet Dépendances (`dependances/<volet>`). */
object LinkTabs {
    const val SCHEMA = "schema"
    const val DEMANDS = "demandes"

    fun of(sub: String): String = if (sub.substringBefore('/') == DEMANDS) DEMANDS else SCHEMA

    fun tab(sub: String): String = if (sub == SCHEMA) SheetTabs.LINKS else "${SheetTabs.LINKS}/$sub"
}

/** Un lien, vu de la fiche : ce projet le lit ([reads]), ou il lit ce projet. */
data class Tie(val reads: Boolean, val link: Linked, val key: String)

/** Les liens d'une fiche, ceux qu'il lit d'abord ; la clé d'un lien nomme son sens et son projet (`lit-3`, `luPar-x1`). */
fun ties(links: Links): List<Tie> =
    links.reads.mapIndexed { i, x -> Tie(true, x, "lit-${x.project ?: "x$i"}") } +
        links.readers.mapIndexed { i, x -> Tie(false, x, "luPar-${x.project ?: "x$i"}") }

fun findTie(links: Links, key: String): Tie? = ties(links).firstOrNull { it.key == key }

/** Les quatre choses qu'un lien donne, dans l'ordre de la maquette : son code, et si le lien la donne. */
fun given(g: Gives): List<Pair<String, Boolean>> = listOf("see" to g.see, "detail" to g.detail, "files" to g.files, "docs" to g.docs)

/** Toutes les demandes de la fiche, les plus récentes d'abord : envoyées, reçues, et ses tickets à elle chez un projet lu. */
fun allDemands(links: Links): List<Demand> =
    (links.asks + links.received + links.reads.flatMap { r -> r.asks.filter { it.from == "you" } }).sortedByDescending { it.at }

/** Les projets qu'elle peut lui faire lire : ceux qu'elle voit, qu'il ne lit pas déjà. */
fun linkCandidates(links: Links): List<Linked> {
    val read = links.reads.mapNotNull { it.project }.toSet()
    return links.candidates.filter { it.project != null && it.visible && it.project !in read }
}

fun askTone(status: String): StateTone = when (status) {
    "treated", "done" -> StateTone.DONE
    "dismissed", "refused" -> StateTone.FAIL
    "proposed", "unread" -> StateTone.WAIT
    else -> StateTone.WORK
}

/** Ce qui change dans ce qu'un projet lit, lien par lien. */
object LinkChange {
    const val ADD = "add"
    const val REMOVE = "remove"
    const val DIRECT_ON = "direct_on"
    const val DIRECT_OFF = "direct_off"
}

/**
 * Se mettre à lire un projet, ne plus le lire, laisser ses demandes y entrer directement ou non : ce qui change. Le mot
 * du lien ([why], pourquoi il lit ce projet) se dit en le posant ; il nomme son projet (`why_for`).
 */
fun linkRequest(change: String, project: Int, why: String = ""): GestureRequest {
    val word = why.trim()
    val fields = mutableListOf<Pair<String, Any?>>(change to JsonArray(listOf(JsonPrimitive(project))))
    if (change == LinkChange.ADD && word.isNotEmpty()) {
        fields += "why" to word
        fields += "why_for" to project
    }
    return GestureRequest("liens", bodyOf(*fields.toTypedArray()))
}

/**
 * Le mot d'un lien se laisse-t-il enregistrer ? Il a changé, et il n'est pas vide : sans mot ni lien qui bouge, le
 * serveur ne voit rien à faire et refuse.
 */
fun linkWordReady(word: String, before: String): Boolean = word.isNotBlank() && word.trim() != before.trim()

/** Le mot d'un lien déjà posé, dit seul, plus tard. */
fun linkWhyRequest(project: Int, why: String): GestureRequest = GestureRequest("liens", bodyOf("why" to why.trim(), "why_for" to project))

/** « Lui demander quelque chose » : un ticket qu'elle ouvre elle-même chez le projet lu (sa route est servie : `ticket`). */
fun askRequest(route: String, title: String, text: String): GestureRequest = GestureRequest(route, filled("title" to title.trim(), "text" to text.trim()))

/** Où vit le ticket d'une demande, s'il s'ouvre d'ici : dans ce projet pour une demande reçue, chez l'autre sinon. */
fun demandTicket(project: Int, a: Demand): Pair<Int, Int>? = when {
    a.number <= 0 -> null
    a.direction == "received" -> project to a.number
    a.visible && a.project != null -> a.project to a.number
    else -> null
}

// ── Les listes ──────────────────────────────────────────────────────────

/** La couleur d'un statut d'une liste : clos (fait), son premier statut ouvert (en attente), les autres (en cours). */
fun listStatusTone(list: Listing, code: String): StateTone = when {
    list.closed.any { it.code == code } -> StateTone.DONE
    list.open.firstOrNull()?.code == code -> StateTone.WAIT
    else -> StateTone.WORK
}

/** Les éléments d'un statut, et combien la liste en compte (ce qu'elle a servi, sinon ce qui est lu). */
data class StatusGroup(val status: Coded, val count: Int, val items: List<Entry>)

/** Une liste rangée par statut, dans l'ordre de ses statuts (les ouverts, puis les clos). */
fun listGroups(list: Listing, items: List<Entry>): List<StatusGroup> = (list.open + list.closed).map { s ->
    val mine = items.filter { it.status == s.code }
    StatusGroup(s, list.counts[s.code] ?: mine.size, mine)
}

fun itemStatusRequest(e: Entry, status: String, note: String = ""): GestureRequest =
    GestureRequest("element/statut", filled("list" to e.list, "item" to entryItem(e), "status" to status, "note" to note.trim()))

fun itemAddRequest(list: String, title: String, text: String, status: String, actor: String): GestureRequest =
    GestureRequest("element/ajouter", filled("list" to list, "title" to title.trim(), "text" to text.trim(), "status" to status, "actor" to actor))

/**
 * À qui est un élément qu'on ajoute, tel qu'il part : un de ceux que la liste sert ([Listing.actors]), sinon rien — la
 * liste lui donne alors le sien. Une liste confiée à une personne dit `person`, que l'ajout n'accepte pas d'ici.
 */
fun addActor(list: Listing, picked: String): String = if (list.actors.any { it.code == picked }) picked else ""

fun itemAssignRequest(e: Entry, actor: String): GestureRequest =
    GestureRequest("element/confier", bodyOf("list" to e.list, "item" to entryItem(e), "actor" to actor))

// ── Modifier le projet ──────────────────────────────────────────────────

fun archiveRequest(): GestureRequest = GestureRequest("archiver", JsonObject(emptyMap()))

fun restoreRequest(): GestureRequest = GestureRequest("restaurer", JsonObject(emptyMap()))

/** L'icône d'une section des réglages. */
fun sectionIcon(name: String): String = when (name) {
    "general" -> "flag"
    "rythme" -> "clock"
    "accords" -> "shield-check"
    "depot" -> "code"
    "outils" -> "tools"
    else -> "settings"
}

/** Un champ dont la valeur est une liste (ses jours de travail) : des cases, une par choix. */
fun isListField(f: SettingField): Boolean = f.value is JsonArray

private fun JsonElement.words(): String = when (this) {
    is JsonNull -> ""
    is JsonPrimitive -> content
    else -> ""
}

private fun JsonElement.codes(): List<String> = (this as? JsonArray)?.map { it.words() }.orEmpty()

/** La valeur d'un champ, telle qu'elle s'enregistre : un booléen, un nombre (ou rien), une liste, un texte. */
private fun normal(f: SettingField, v: JsonElement): JsonElement = when {
    f.kind == "bool" -> JsonPrimitive((v as? JsonPrimitive)?.booleanOrNull == true)
    f.value is JsonArray -> JsonArray(v.codes().map(::JsonPrimitive))
    f.kind == "int" -> (v as? JsonPrimitive)?.let { it.intOrNull ?: it.contentOrNull?.trim()?.toIntOrNull() }?.let(::JsonPrimitive) ?: JsonNull
    else -> JsonPrimitive(v.words())
}

/** Ce qui est saisi d'un champ ([typed]), sinon sa valeur servie. */
fun settingValue(f: SettingField, typed: Map<String, JsonElement>): JsonElement = normal(f, typed[f.name] ?: f.value)

fun settingText(f: SettingField, typed: Map<String, JsonElement>): String = (typed[f.name] ?: f.value).words()

fun settingOn(f: SettingField, typed: Map<String, JsonElement>): Boolean = ((typed[f.name] ?: f.value) as? JsonPrimitive)?.booleanOrNull == true

fun settingCodes(f: SettingField, typed: Map<String, JsonElement>): Set<String> = (typed[f.name] ?: f.value).codes().toSet()

/**
 * Les choix d'un sélecteur : **ceux que le serveur sert**, tels quels. Un choix vide n'est ajouté (« — ») que si le
 * champ est servi sans valeur et que rien de vide n'est servi : il ramène à ce qui était là, et ne part donc pas. Un
 * « — » posé d'office ne donnerait, enregistré, que « choisissez une valeur ».
 */
fun settingChoices(f: SettingField): List<Coded> {
    val served = f.choices.map { if (it.code.isEmpty() && it.label.isBlank()) Coded("", "—") else it }
    val unset = !f.required && f.value.words().isEmpty() && served.none { it.code.isEmpty() }
    return if (unset) listOf(Coded("", "—")) + served else served
}

/** Un champ ne sert que pour certaines valeurs d'un autre (`only`) : se montre-t-il, vu ce qui est saisi ? */
fun settingShown(f: SettingField, fields: List<SettingField>, typed: Map<String, JsonElement>): Boolean = f.only.all { o ->
    (typed[o.field] ?: fields.firstOrNull { it.name == o.field }?.value ?: JsonNull).words() in o.values
}

private fun sameValue(a: JsonElement, b: JsonElement): Boolean =
    if (a is JsonArray || b is JsonArray) a.codes().sorted() == b.codes().sorted() else a.words() == b.words()

/**
 * Ce qui change dans une section : seulement les champs dont la valeur saisie n'est plus celle servie, par leur nom. Un
 * champ que le serveur dit réservé (`can: false`) ne part jamais : il se montre verrouillé, rien ne s'y saisit.
 */
fun settingsChanged(fields: List<SettingField>, typed: Map<String, JsonElement>): Map<String, JsonElement> =
    fields.filter { it.can && it.name in typed }.mapNotNull { f ->
        val after = settingValue(f, typed)
        if (sameValue(normal(f, f.value), after)) null else f.name to after
    }.toMap()

/** Les réglages d'une section : `POST …/reglages/enregistrer`, les champs qui changent. */
fun settingsRequest(section: String, fields: List<SettingField>, typed: Map<String, JsonElement>): GestureRequest =
    GestureRequest("reglages/enregistrer", bodyOf("section" to section, "values" to JsonObject(settingsChanged(fields, typed))))

// ── Le diagramme, dans le temps ─────────────────────────────────────────

const val DAY_MS = 86_400_000L

/** La hauteur d'une ligne du diagramme : un objectif ou une mission, un jalon. */
const val ROW_GOAL = 46f
const val ROW_STEP = 36f

fun rowHeight(r: DiagramRow): Float = if (r is DiagramRow.StepRow) ROW_STEP else ROW_GOAL

fun dayStart(ms: Long, zone: ZoneId = ZoneId.systemDefault()): Long =
    Instant.ofEpochMilli(ms).atZone(zone).toLocalDate().atStartOfDay(zone).toInstant().toEpochMilli()

private fun dateOf(ms: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(ms).atZone(zone).toLocalDate()

private fun startOf(date: LocalDate, zone: ZoneId): Long = date.atStartOfDay(zone).toInstant().toEpochMilli()

/**
 * Où tombe un instant sur l'axe, en **jours du calendrier** depuis [from] : le jour où il est, plus la part de ce jour
 * déjà passée. Un jour de 23 h ou de 25 h (le changement d'heure) y vaut un jour, comme les autres — compter par pas
 * de 24 h décalerait tout ce qui le précède.
 */
fun dayOffset(ms: Long, from: LocalDate, zone: ZoneId = ZoneId.systemDefault()): Double {
    val date = dateOf(ms, zone)
    val start = startOf(date, zone)
    val length = startOf(date.plusDays(1), zone) - start
    return ChronoUnit.DAYS.between(from, date) + (ms - start).toDouble() / length
}

/**
 * Une barre de la piste : de [left] sur [width]. [tone] : sa couleur (`null` : un fantôme — pas commencé, sans date) ;
 * [running] : en cours, son bout est hachuré ; [yours] : elle attend la personne ; [goal] : la barre d'un objectif.
 */
data class TimeBar(val left: Float, val width: Float, val tone: StateTone?, val running: Boolean = false, val yours: Boolean = false, val goal: Boolean = false)

/** La piste d'une ligne : ses barres, où se pose son mot ([label] ; -1 : pas de mot), et pour une mission son fil et ses passages. */
data class TimeTrack(val bars: List<TimeBar>, val label: Float, val line: Float = -1f, val passes: List<Float> = emptyList())

data class AxisDay(val x: Float, val at: Long, val today: Boolean)

/** Une flèche d'un objectif à celui qui en dépend. */
data class TimeArrow(val x1: Float, val y1: Float, val x2: Float, val y2: Float)

data class TimeLayout(
    /** La largeur d'un jour. */
    val day: Float,
    /** La largeur de tout le diagramme. */
    val width: Float,
    val origin: Long,
    /** Où tombe maintenant. */
    val today: Float,
    val days: List<AxisDay>,
    val tracks: List<TimeTrack>,
    val arrows: List<TimeArrow>,
)

/** Ce qu'un jour mesure quand rien ne presse, et jusqu'où il se resserre : en jours, en semaines. */
private val DAY_WIDTH = mapOf(false to (124f to 56f), true to (46f to 14f))
private const val TAIL = 150f
private const val GHOST_GAP = 8f

/** Combien de jours l'axe compte avant aujourd'hui : de la première date servie à ce matin. */
fun daysBack(d: Diagram, weeks: Boolean, zone: ZoneId = ZoneId.systemDefault()): Int {
    val dated = (listOf(d.from) + d.objectives.flatMap { listOf(it.startedAt) + it.passes }).filter { it > 0 }
    val first = dated.minOrNull() ?: d.now
    val span = max(0, ChronoUnit.DAYS.between(dateOf(first, zone), dateOf(d.now, zone)).toInt())
    return max(if (weeks) 13 else 2, span + if (weeks) 1 else 0)
}

/**
 * Le diagramme placé dans le temps : un axe en jours, une barre de quand elle s'y est mise à quand c'est atteint
 * (jusqu'à maintenant si c'est en cours), les passages d'une mission en points. **De vraies dates seulement** : ce qui
 * n'a pas commencé n'a pas de date — il se range en fantôme après aujourd'hui, dans l'ordre du plan. [width] : la
 * largeur visible de la piste (0 : inconnue) ; l'axe se resserre pour que la première date y tienne avec aujourd'hui.
 */
fun timeLayout(d: Diagram, rows: List<DiagramRow>, weeks: Boolean, width: Float, zone: ZoneId = ZoneId.systemDefault()): TimeLayout {
    val back = daysBack(d, weeks, zone)
    // l'axe compte des jours du calendrier : chaque trait tombe à minuit, changement d'heure ou non
    val first = dateOf(d.now, zone).minusDays(back.toLong())
    val origin = startOf(first, zone)
    val past = dayOffset(d.now, first, zone)
    val tops = ArrayList<Float>(rows.size)
    var y = 0f
    for (r in rows) {
        tops += y
        y += rowHeight(r)
    }
    val goals = rows.withIndex().filter { it.value is DiagramRow.GoalRow }

    class Ghosts(day: Float) {
        val today = (past * day).roundToInt().toFloat()
        /** La largeur d'un fantôme (un autre nom que la largeur de la piste, que le corps de la fonction lit). */
        val wide = max(74f, (day * 0.8f).roundToInt().toFloat())
        val goal = HashMap<Int, Pair<Float, Float>>()
        val step = HashMap<String, Float>()
        var end = today + TAIL

        init {
            for ((_, r) in goals) {
                val o = r.o
                var cur = today + 34f
                goal[o.after]?.let { cur = max(cur, it.second + 18f) }
                val waiting = o.milestones.filter { it.startedAt <= 0 && it.status != "reached" }
                if (waiting.isEmpty() && (o.startedAt > 0 || o.status == "done")) continue
                val x0 = cur
                for (m in waiting) {
                    step["${o.id}:${m.id}"] = cur
                    cur += wide + GHOST_GAP
                }
                val g = x0 to (if (waiting.isNotEmpty()) cur - GHOST_GAP else cur + wide)
                goal[o.id] = g
                end = max(end, g.second + 40f)
            }
        }
    }

    val (natural, least) = DAY_WIDTH.getValue(weeks)
    var day = natural
    var g = Ghosts(day)
    var tries = 0
    while (tries < 5 && width > 0 && g.end > width && day > least) {
        day = max(least, min(day - 1f, floor((width - (g.end - g.today)) / past).toFloat()))
        g = Ghosts(day)
        tries++
    }
    val scale = day
    fun x(ms: Long): Float = (dayOffset(ms, first, zone) * scale).roundToInt().toFloat()
    fun span(a: Float, b: Float, tone: StateTone?, running: Boolean = false, yours: Boolean = false, goal: Boolean = false) =
        TimeBar(a, max(10f, b - a), tone, running, yours, goal)

    val tracks = rows.map { r ->
        when (r) {
            is DiagramRow.MissionRow -> TimeTrack(emptyList(), g.today + 14f, g.today, r.o.passes.filter { it >= origin }.map(::x))
            is DiagramRow.StepRow -> {
                val m = r.m
                if (m.startedAt <= 0 && m.status != "reached") {
                    val gx = g.step["${r.o.id}:${m.id}"] ?: (g.today + 34f)
                    TimeTrack(listOf(span(gx, gx + g.wide, null)), -1f)
                } else {
                    val a = x(if (m.startedAt > 0) m.startedAt else m.reachedAt)
                    val b = x(if (m.status == "reached" && m.reachedAt > 0) m.reachedAt else d.now)
                    val bars = if (m.ready && m.readyAt > 0) {
                        listOf(span(a, x(m.readyAt), StateTone.WORK), span(x(m.readyAt), b, StateTone.YOU, yours = true))
                    } else {
                        listOf(span(a, b, diagramTone(m), running = m.status != "reached"))
                    }
                    TimeTrack(bars, max(b, a + 10f) + 10f)
                }
            }
            is DiagramRow.GoalRow -> {
                val o = r.o
                val tone = when (o.status) {
                    "done" -> StateTone.DONE
                    "blocked" -> StateTone.FAIL
                    else -> StateTone.WORK
                }
                val ghost = g.goal[o.id]
                val bars = mutableListOf<TimeBar>()
                var label = -1f
                if (o.startedAt > 0) {
                    val running = o.status != "done"
                    val stop = x(if (running) d.now else listOf(o.closedAt, o.lastRun).firstOrNull { it > 0 } ?: d.now)
                    bars += span(x(o.startedAt), stop, tone, running = running, goal = true)
                    // une flèche part de cette barre vers l'objectif qui en dépend : son mot lui laisse la place
                    if (ghost == null) label = stop + if (goals.any { it.value.o.after == o.id }) 24f else 10f
                }
                if (ghost != null) bars += span(ghost.first, ghost.second, null, goal = true)
                TimeTrack(bars, label)
            }
        }
    }
    // les flèches : d'un objectif à celui qui en dépend
    val arrows = goals.mapNotNull { (i, r) ->
        val from = goals.firstOrNull { it.value.o.id == r.o.after && r.o.after != 0 } ?: return@mapNotNull null
        val fo = from.value.o
        val x1 = g.goal[fo.id]?.second ?: if (fo.startedAt > 0) x(if (fo.status == "done" && fo.closedAt > 0) fo.closedAt else d.now) else 0f
        val x2 = g.goal[r.o.id]?.first ?: x(if (r.o.startedAt > 0) r.o.startedAt else d.now)
        TimeArrow(x1, tops[from.index] + ROW_GOAL / 2, x2, tops[i] + ROW_GOAL / 2)
    }
    val days = (0..back).map { AxisDay(it * scale, startOf(first.plusDays(it.toLong()), zone), it == back) }
    return TimeLayout(scale, max(g.end, width), origin, g.today, days, tracks, arrows)
}

/** L'échelle d'office : en jours si la première date et aujourd'hui tiennent ensemble dans la piste, sinon en semaines. */
fun pickWeeks(d: Diagram, width: Float, zone: ZoneId = ZoneId.systemDefault()): Boolean =
    width > 0 && (daysBack(d, false, zone) + 1) * DAY_WIDTH.getValue(false).second + TAIL > width
