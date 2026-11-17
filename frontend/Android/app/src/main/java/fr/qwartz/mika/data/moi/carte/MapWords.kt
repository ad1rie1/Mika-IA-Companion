package fr.qwartz.mika.data.moi.carte

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale
import kotlin.math.max
import kotlin.math.roundToInt
import kotlin.math.roundToLong

/*
 * Les mots d'une carte, en français, portés de `frontendv2/src/map/words.ts` sans changer leurs règles : distances,
 * durées, modes, ce qu'un trajet peut éviter et ce qu'il évite, les jours d'un voyage (en long, et en court pour un
 * menu), ce qu'est un lieu. Purs : Explorer, et demain Itinéraire et Voyages (lot 6b), les partagent.
 */

/** L'espace insécable entre les milliers : « 1 388 km » ne se coupe pas en fin de ligne. */
private const val NBSP = ' '

private fun grouped(n: Double): String {
    val digits = n.roundToLong().toString()
    return digits.reversed().chunked(3).joinToString(NBSP.toString()).reversed()
}

/** « 850 m », « 5,8 km », « 47 km », « 1 388 km » ; rien pour une distance inconnue. */
fun km(meters: Double?): String {
    if (meters == null || !meters.isFinite() || meters < 0) return ""
    if (meters < 1000) return "${max(0L, (meters / 10).roundToLong() * 10)} m"
    if (meters < 10_000) {
        val text = String.format(Locale.ROOT, "%.1f", meters / 1000).replace(".", ",").replace(",0", "")
        return "$text km"
    }
    return "${grouped(meters / 1000)} km"
}

/** « 1 min », « 45 min », « 7 h 05 », « 16 h » ; rien pour une durée inconnue. */
fun duration(seconds: Double?): String {
    if (seconds == null || !seconds.isFinite() || seconds < 0) return ""
    val minutes = max(1, (seconds / 60).roundToInt())
    if (minutes < 60) return "$minutes min"
    val hours = minutes / 60
    val rest = minutes % 60
    return if (rest != 0) "$hours h ${rest.toString().padStart(2, '0')}" else "$hours h"
}

/** Les modes d'un trajet, dans l'ordre de l'API (`MODES`, `ports/maps.py`). */
val MODES = listOf("voiture", "velo", "pied")

/** Ce qu'un trajet en voiture peut éviter, dans l'ordre de l'API (`AVOIDS`). */
val AVOIDS = listOf("peages", "autoroutes", "ferries")

val MODE_LABELS: Map<String, String> = linkedMapOf("voiture" to "Voiture", "velo" to "Vélo", "pied" to "À pied")
private val MODE_WORDS = mapOf("voiture" to "en voiture", "velo" to "à vélo", "pied" to "à pied")

/** « en voiture », « à vélo », « à pied ». */
fun modeWords(mode: String): String = MODE_WORDS[mode] ?: mode

/**
 * Ce qu'un trajet en voiture peut éviter, dans l'ordre de l'écran : une seule table, que liront Itinéraire (« Éviter
 * les péages ») et les fenêtres d'un voyage (« En voiture, éviter » : « les péages »).
 */
val AVOID_LABELS: Map<String, String> = linkedMapOf("peages" to "les péages", "autoroutes" to "les autoroutes", "ferries" to "les ferries")

/** Ce qu'un trajet évite, en mots : « sans péage ni autoroute », ou « péages acceptés » en voiture. */
fun avoidWords(avoid: List<String>, mode: String = "voiture"): String {
    val parts = buildList {
        if ("peages" in avoid) add("péage")
        if ("autoroutes" in avoid) add("autoroute")
        if ("ferries" in avoid) add("ferry")
    }
    if (parts.isEmpty()) return if (mode == "voiture") "péages acceptés" else ""
    return "sans " + if (parts.size > 1) "${parts.dropLast(1).joinToString(", ")} ni ${parts.last()}" else parts[0]
}

private val WEEKDAYS = listOf("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
private val MONTHS = listOf(
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
private val MONTHS_SHORT = listOf("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
private val ISO_DAY = Regex("""^(\d{4})-(\d{2})-(\d{2})$""")

/** Une date `AAAA-MM-JJ`, sinon `null` (« 2027-02-30 » n'en est pas une). */
fun isoDay(text: String): LocalDate? {
    if (!ISO_DAY.matches(text.trim())) return null
    return try {
        LocalDate.parse(text.trim())
    } catch (_: DateTimeParseException) {
        null
    }
}

/** `AAAA-MM-JJ` d'une date. */
fun isoOf(d: LocalDate): String = d.toString()

private fun weekday(d: LocalDate) = WEEKDAYS[d.dayOfWeek.value - 1]
private fun dayNumber(d: LocalDate): String = if (d.dayOfMonth == 1) "1er" else d.dayOfMonth.toString()
private fun today(now: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(now).atZone(zone).toLocalDate()

/** « sam. 3 avril » (et l'année, si ce n'est pas celle de [now]). */
fun dayLabel(iso: String, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val d = isoDay(iso) ?: return ""
    val year = if (d.year != today(now, zone).year) " ${d.year}" else ""
    return "${weekday(d)} ${dayNumber(d)} ${MONTHS[d.monthValue - 1]}$year"
}

/**
 * Les dates d'un voyage : « sam. 3 avril », « sam. 21 et dim. 22 novembre », « du sam. 3 au mer. 7 avril 2027 » ;
 * « · passé » quand son dernier jour l'est. Sans date de départ : vide.
 */
fun tripDates(start: String, days: Int, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val first = isoDay(start) ?: return ""
    val n = max(1, days)
    val last = first.plusDays((n - 1).toLong())
    val current = today(now, zone)
    val year = if (last.year != current.year) " ${last.year}" else ""
    val sameMonth = first.monthValue == last.monthValue && first.year == last.year
    val a = "${weekday(first)} ${dayNumber(first)}${if (sameMonth) "" else " ${MONTHS[first.monthValue - 1]}"}"
    val b = "${weekday(last)} ${dayNumber(last)} ${MONTHS[last.monthValue - 1]}$year"
    val text = when (n) {
        1 -> b
        2 -> "$a et $b"
        else -> "du $a au $b"
    }
    return if (last.isBefore(current)) "$text · passé" else text
}

/**
 * Les dates d'un voyage en court, là où la place manque (le menu « Ajouter au voyage ») : « 3 avr. », « 3–7 avr. »,
 * « 30 mars–2 avr. 2027 » (l'année, si ce n'est pas celle de [now]). Sans date de départ : vide.
 */
fun tripSpan(start: String, days: Int, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val first = isoDay(start) ?: return ""
    val n = max(1, days)
    val last = first.plusDays((n - 1).toLong())
    val year = if (last.year != today(now, zone).year) " ${last.year}" else ""
    val end = "${dayNumber(last)} ${MONTHS_SHORT[last.monthValue - 1]}$year"
    if (n == 1) return end
    val sameMonth = first.monthValue == last.monthValue && first.year == last.year
    return "${dayNumber(first)}${if (sameMonth) "" else " ${MONTHS_SHORT[first.monthValue - 1]}"}–$end"
}

/** Le dernier jour d'un voyage est-il passé ? */
fun tripPast(start: String, days: Int, now: Long, zone: ZoneId = ZoneId.systemDefault()): Boolean =
    tripDates(start, days, now, zone).endsWith("· passé")

/** « arrivée vers 15:35 si tu pars maintenant ». */
fun arrival(now: Long, seconds: Double, zone: ZoneId = ZoneId.systemDefault()): String {
    if (!seconds.isFinite() || seconds <= 0) return ""
    val at = Instant.ofEpochMilli(now + (seconds * 1000).roundToLong()).atZone(zone)
    return "arrivée vers ${at.format(CLOCK)} si tu pars maintenant"
}

private val CLOCK = DateTimeFormatter.ofPattern("HH:mm", Locale.FRANCE)

/** « 3 jours », « 1 arrêt », « 1 388 lieux ». */
fun plural(n: Long, one: String, many: String = "${one}s"): String = "${grouped(n.toDouble())} ${if (n > 1) many else one}"

/** Ce qu'est un lieu, en une ligne : « Camping · Sévrier » ; une adresse sans sorte : « Adresse · Paris ». */
fun placeWhat(p: Place): String =
    listOf(p.kindFr.ifBlank { if (p.category == "adresse") "Adresse" else "" }, p.town).filter { it.isNotBlank() }.joinToString(" · ")
