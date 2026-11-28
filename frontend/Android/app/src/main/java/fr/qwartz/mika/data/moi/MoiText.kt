package fr.qwartz.mika.data.moi

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit
import java.util.Locale

/*
 * Ce que les domaines de l'API par personne écrivent d'un instant et d'une personne : en français, comme le client web
 * (`frontend/Web/src/screens/chat/markup.ts`, `shell/dom.ts`), pur et testé sur la JVM.
 */

object MoiDates {
    private val WEEKDAYS = listOf("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
    private val MONTHS = listOf("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
    private val MONTH_NAMES = listOf(
        "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
    )

    private fun day(ms: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(ms).atZone(zone).toLocalDate()

    /** Combien de jours avant aujourd'hui (0 : aujourd'hui ; négatif : demain ou plus tard). */
    private fun daysAgo(ms: Long, now: Long, zone: ZoneId): Long = ChronoUnit.DAYS.between(day(ms, zone), day(now, zone))

    /** « 14:05 ». */
    fun clock(ms: Long, zone: ZoneId = ZoneId.systemDefault()): String {
        if (ms <= 0) return ""
        val t = Instant.ofEpochMilli(ms).atZone(zone)
        return String.format(Locale.ROOT, "%02d:%02d", t.hour, t.minute)
    }

    /** Quand, en court, comme une liste de messagerie : « 13:31 », « hier », « lun. », « 28 oct. », « 28 oct. 2025 ». */
    fun short(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
        if (ms <= 0) return ""
        val days = daysAgo(ms, now, zone)
        if (days <= 0) return clock(ms, zone)
        if (days == 1L) return "hier"
        val d = day(ms, zone)
        if (days < 7) return WEEKDAYS[d.dayOfWeek.value - 1]
        val label = "${d.dayOfMonth} ${MONTHS[d.monthValue - 1]}"
        return if (d.year == day(now, zone).year) label else "$label ${d.year}"
    }

    /** « aujourd'hui 14:05 », « hier 21:41 », « lun. 08:12 », « 28 oct. 13:31 ». */
    fun dayAndClock(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
        val d = short(ms, now, zone)
        if (d.isEmpty()) return ""
        val time = clock(ms, zone)
        return if (d == time) "aujourd'hui $time" else "$d $time"
    }

    private val DAY_NAMES = listOf("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    private val MONTHS_LONG = listOf(
        "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre",
    )

    /** Le repère de jour d'un fil : « Aujourd'hui », « Hier », sinon « lundi 2 novembre » (l'année si ce n'est pas
     *  celle-ci, « 1er » le premier). */
    fun dayLabel(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
        val d = day(ms, zone)
        val today = day(now, zone)
        if (d == today) return "Aujourd'hui"
        if (d == today.minusDays(1)) return "Hier"
        val n = if (d.dayOfMonth == 1) "1er" else d.dayOfMonth.toString()
        val label = "${DAY_NAMES[d.dayOfWeek.value - 1]} $n ${MONTHS_LONG[d.monthValue - 1]}"
        return if (d.year == today.year) label else "$label ${d.year}"
    }

    /** Le groupe d'une ligne dans la liste : « Aujourd'hui », « Hier », « Cette semaine », puis le mois (et l'année si
     *  ce n'est pas celle-ci). Un instant inconnu : « Plus ancien ». */
    fun group(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
        if (ms <= 0) return "Plus ancien"
        val days = daysAgo(ms, now, zone)
        return when {
            days <= 0 -> "Aujourd'hui"
            days == 1L -> "Hier"
            days < 7 -> "Cette semaine"
            else -> {
                val d = day(ms, zone)
                val month = MONTH_NAMES[d.monthValue - 1]
                if (d.year == day(now, zone).year) month else "$month ${d.year}"
            }
        }
    }
}

/** Les initiales d'un nom : « Claire Dubois » → « CD », « noreply@x.fr » → « NF » ; « ? » sans lettre. */
fun initials(name: String): String {
    val cleaned = name.replace(Regex("""[^\p{L}\p{N}\s._-]"""), "")
    val words = cleaned.split(Regex("""[\s._-]+""")).filter { it.isNotEmpty() }.take(2)
    return words.joinToString("") { it.substring(0, it.offsetByCodePoints(0, 1)).uppercase() }.ifEmpty { "?" }
}

/** Une teinte d'avatar stable (0 à 7) pour un nom, la même que celle du client web. */
fun hue(key: String): Int {
    var x = 0L
    var i = 0
    while (i < key.length) {
        x = (x * 31 + key[i].code) and 0xFFFFFFFFL
        i = key.offsetByCodePoints(i, 1)
    }
    return (x % 8).toInt()
}

/** Depuis quand, en mots : « à l'instant », « il y a 5 min », « il y a 3 h », « il y a 2 j » ; « jamais » pour 0. */
fun ago(ms: Long, now: Long): String {
    if (ms <= 0) return "jamais"
    val s = Math.round(maxOf(0L, now - ms) / 1000.0)
    if (s < 45) return "à l'instant"
    val min = Math.round(s / 60.0)
    if (min < 60) return "il y a $min min"
    val hours = Math.round(min / 60.0)
    if (hours < 24) return "il y a $hours h"
    return "il y a ${Math.round(hours / 24.0)} j"
}
