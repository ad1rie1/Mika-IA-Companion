package fr.qwartz.mika.data.moi.agenda

import java.time.DateTimeException
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeParseException
import kotlin.math.abs

/*
 * Les dates de l'Agenda, pures (portées de `frontend/Web/src/screens/agenda/dates.ts`, avec les vues du téléphone de la
 * maquette validée `frontend/Android/maquette/ecrans/agenda.js`) : des jours `AAAA-MM-JJ` comptés sans heure d'été, des
 * instants lus à l'heure d'un fuseau — celui du serveur : une période et ce qu'on écrit s'y lisent (`protocole-moi.md`
 * § 13) —, les mots d'un jour, d'une heure, d'une période, et les bornes des cinq vues. La semaine commence le lundi.
 */

val JOURS = listOf("dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi")
val JC = listOf("dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam.")
val MOIS = listOf("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre")
val MC = listOf("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")

/** Les titres d'une colonne de semaine, d'un caractère (la semaine sur 384 dp, recommandation validée). */
val WEEK_LETTERS = listOf("L", "M", "M", "J", "V", "S", "D")

/** Les cinq vues du téléphone (dans ⋮), Planning d'abord. */
enum class AgendaView(val code: String) {
    PLANNING("planning"), DAY("jour"), THREE("3jours"), WEEK("semaine"), MONTH("mois");

    companion object {
        fun of(code: String?): AgendaView = entries.firstOrNull { it.code == code } ?: PLANNING
    }
}

/** Le Planning montre quatre semaines. */
const val PLANNING_DAYS = 28

fun pad(n: Int): String = n.toString().padStart(2, '0')

fun cap(s: String): String = if (s.isEmpty()) s else s.substring(0, 1).uppercase() + s.substring(1)

/** `minutes` depuis minuit → « 09:30 ». */
fun hm(minutes: Int): String {
    val m = minutes.coerceAtLeast(0)
    return "${pad((m / 60) % 24)}:${pad(m % 60)}"
}

// ── des jours ───────────────────────────────────────────────────────────

private fun date(key: String): LocalDate? = try {
    LocalDate.parse(key)
} catch (_: DateTimeParseException) {
    null
}

fun isDay(text: String): Boolean = Regex("""^\d{4}-\d{2}-\d{2}$""").matches(text) && date(text) != null

/** Le 1er janvier 1970, le repli d'une date illisible (`LocalDate.EPOCH` demande l'API 34). */
private val EPOCH_DAY: LocalDate = LocalDate.of(1970, 1, 1)

fun addDays(key: String, n: Int): String = (date(key) ?: EPOCH_DAY).plusDays(n.toLong()).toString()

/** Combien de jours de [a] à [b] ([b] après [a] : positif). */
fun daysFrom(a: String, b: String): Int {
    val x = date(a) ?: return 0
    val y = date(b) ?: return 0
    return (y.toEpochDay() - x.toEpochDay()).toInt()
}

/** 0 : dimanche… 6 : samedi. */
fun weekday(key: String): Int = (date(key)?.dayOfWeek?.value ?: 7) % 7

fun mondayOf(key: String): String = addDays(key, -((weekday(key) + 6) % 7))

data class DayParts(val y: Int, val m: Int, val d: Int)

fun partsOf(key: String): DayParts {
    val x = date(key) ?: EPOCH_DAY
    return DayParts(x.year, x.monthValue, x.dayOfMonth)
}

fun monthStart(key: String): String = "${key.take(7)}-01"

/** Le premier jour du mois, [n] mois plus loin. */
fun addMonths(key: String, n: Int): String = (date(monthStart(key)) ?: EPOCH_DAY).plusMonths(n.toLong()).toString()

/** « 1er », « 23 ». */
fun dayNumber(key: String): String = partsOf(key).d.let { if (it == 1) "1er" else it.toString() }

/** « lundi 23 novembre » (l'année si ce n'est pas celle d'aujourd'hui). */
fun dayWords(key: String, today: String): String {
    val p = partsOf(key)
    return "${JOURS[weekday(key)]} ${dayNumber(key)} ${MOIS[p.m - 1]}${if (p.y != partsOf(today).y) " ${p.y}" else ""}"
}

/** « lun. 23 nov. ». */
fun shortDay(key: String): String {
    val p = partsOf(key)
    return "${JC[weekday(key)]} ${p.d} ${MC[p.m - 1]}"
}

/** « lun. 23 nov. 2026 » : un jour du formulaire. */
fun formDay(key: String): String = "${shortDay(key)} ${partsOf(key).y}"

/** « aujourd'hui », « demain », « hier », sinon le jour en mots. */
fun nearDay(key: String, today: String): String = when (daysFrom(today, key)) {
    0 -> "aujourd'hui"
    1 -> "demain"
    -1 -> "hier"
    else -> dayWords(key, today)
}

// ── des instants, à l'heure d'un fuseau ────────────────────────────────

/** Le fuseau d'un nom IANA ; illisible : UTC. */
fun zoneOf(name: String): ZoneId = try {
    if (name.isBlank()) ZoneOffset.UTC else ZoneId.of(name)
} catch (_: DateTimeException) {
    ZoneOffset.UTC
}

data class Local(val day: String, val minute: Int)

/** Le jour et la minute d'un instant (ms), à l'heure de [zone]. */
fun localOf(ms: Long, zone: String): Local {
    val t = Instant.ofEpochMilli(ms).atZone(zoneOf(zone)).toLocalDateTime()
    return Local(t.toLocalDate().toString(), t.hour * 60 + t.minute)
}

/** Ce qu'un champ de formulaire écrit : « 2026-11-23T14:30 », à l'heure de [zone]. */
fun localInput(ms: Long, zone: String): String {
    val l = localOf(ms, zone)
    return "${l.day}T${hm(l.minute)}"
}

/** L'instant (ms) d'un jour et d'une minute à l'heure de [zone]. */
fun instantOf(day: String, minute: Int, zone: String): Long {
    val d = date(day) ?: EPOCH_DAY
    return LocalDateTime.of(d, java.time.LocalTime.MIDNIGHT).plusMinutes(minute.toLong()).atZone(zoneOf(zone)).toInstant().toEpochMilli()
}

/** Le décalage d'un fuseau à un instant, en mots courts : « UTC+1 », « UTC-5 », « UTC+5:30 ». */
fun offsetWords(zone: String, ms: Long): String {
    val off = zoneOf(zone).rules.getOffset(Instant.ofEpochMilli(ms)).totalSeconds / 60
    if (off == 0) return "UTC"
    val a = abs(off)
    return "UTC${if (off > 0) "+" else "-"}${a / 60}${if (a % 60 != 0) ":${pad(a % 60)}" else ""}"
}

// ── les vues ────────────────────────────────────────────────────────────

/** Le premier jour d'une vue et le jour qui suit son dernier. */
fun bounds(view: AgendaView, date: String): Pair<String, String> = when (view) {
    AgendaView.DAY -> date to addDays(date, 1)
    AgendaView.THREE -> date to addDays(date, 3)
    AgendaView.WEEK -> mondayOf(date).let { it to addDays(it, 7) }
    AgendaView.MONTH -> monthDays(date).let { it.first() to addDays(it.last(), 1) } // autant de semaines qu'elle en dessine
    AgendaView.PLANNING -> date to addDays(date, PLANNING_DAYS)
}

/** Les jours d'une grille horaire (Jour, 3 jours, Semaine). */
fun gridDays(view: AgendaView, date: String): List<String> {
    val (first, after) = bounds(view, date)
    return (0 until daysFrom(first, after)).map { addDays(first, it) }
}

/** La date d'une vue un pas plus loin ([sense] : 1) ou plus tôt (-1) ; un mois qui revient à celui d'aujourd'hui y
 *  revient à aujourd'hui. */
fun step(view: AgendaView, date: String, sense: Int, today: String): String = when (view) {
    AgendaView.MONTH -> addMonths(date, sense).let { if (it.take(7) == today.take(7)) today else it }
    AgendaView.DAY -> addDays(date, sense)
    AgendaView.THREE -> addDays(date, 3 * sense)
    AgendaView.WEEK -> addDays(date, 7 * sense)
    AgendaView.PLANNING -> addDays(date, PLANNING_DAYS * sense)
}

/** « Novembre », « Novembre 2027 » : le mois, son année si ce n'est pas celle d'aujourd'hui. */
fun monthTitle(key: String, today: String): String {
    val p = partsOf(key)
    return cap(MOIS[p.m - 1]) + if (p.y != partsOf(today).y) " ${p.y}" else ""
}

/** Le titre de la barre (la maquette) : le mois de la vue ; une semaine ou trois jours sur deux mois, « Nov. – déc. » ;
 *  le mini-mois déplié, son mois ([mini]). */
fun barTitle(view: AgendaView, date: String, today: String, mini: String? = null): String {
    if (mini != null) return monthTitle(mini, today)
    if (view == AgendaView.THREE || view == AgendaView.WEEK) {
        val (first, after) = bounds(view, date)
        val last = addDays(after, -1)
        val a = partsOf(first)
        val b = partsOf(last)
        if (a.m != b.m) return "${cap(MC[a.m - 1])} – ${MC[b.m - 1]}${if (b.y != partsOf(today).y) " ${b.y}" else ""}"
        return monthTitle(first, today)
    }
    return monthTitle(date, today)
}

/** Les jours du mini-mois (et de la vue Mois) : à partir du lundi, cinq ou six semaines. */
fun monthDays(month: String): List<String> {
    val first = mondayOf(monthStart(month))
    val m = partsOf(monthStart(month)).m
    val rows = if (partsOf(addDays(first, 35)).m != m) 5 else 6
    return (0 until rows * 7).map { addDays(first, it) }
}

/** « 14 h 05 », « 30 min » : une durée du formulaire. */
fun durationShort(minutes: Int): String = when {
    minutes < 60 -> "$minutes min"
    minutes % 60 == 0 -> "${minutes / 60} h"
    else -> "${minutes / 60} h ${pad(minutes % 60)}"
}
