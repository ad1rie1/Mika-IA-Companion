package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.Tone
import java.time.DayOfWeek
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit

/*
 * Carte › Événements (ADR 0259), sans Compose ni réseau, porté de `frontendv2/src/screens/carte/agenda.ts` et `fiche.ts`
 * sans changer leurs règles : quand chercher (aujourd'hui, ce week-end, cette semaine, des dates), les événements
 * groupés par jour et leur ligne, le jour d'un voyage où un événement tombe, son prix et ses thèmes en mots, la phrase
 * qu'on prépare pour Mika, ce que la fiche d'un événement montre (et toujours qui l'a écrite). Les événements viennent
 * des offices de tourisme, par DATAtourisme : une base de ce serveur, lue par cases autour des personnes.
 */

// ── Quand ───────────────────────────────────────────────────────────────

/** Quand chercher, dans l'ordre des puces. */
enum class WhenKind(val id: String, val label: String) {
    TODAY("today", "Aujourd'hui"),
    WEEKEND("weekend", "Ce week-end"),
    WEEK("week", "Cette semaine"),
    DATES("dates", "Des dates…"),
}

/** Des jours, `AAAA-MM-JJ` (vide : pas choisi). */
data class DayRange(val start: String = "", val end: String = "")

/** L'heure des dates des événements (`protocole-moi.md` § 10) : celle de Paris, quel que soit le fuseau du téléphone. */
val PARIS: ZoneId = ZoneId.of("Europe/Paris")

private fun today(now: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(now).atZone(zone).toLocalDate()

/**
 * Les jours d'une recherche, à l'heure de Paris (R2-A09 : celle des événements, pas celle du téléphone) : aujourd'hui ; ce week-end (le samedi et le dimanche qui viennent —
 * un samedi, lui et demain ; un dimanche, lui seul) ; cette semaine (jusqu'au dimanche ; un dimanche, la semaine qui
 * vient) ; des dates (celles qu'on a choisies, remises dans l'ordre ; une seule : ce jour-là ; aucune : sept jours).
 */
fun whenRange(kind: WhenKind, now: Long, zone: ZoneId = PARIS, dates: DayRange = DayRange()): DayRange {
    val day = today(now, zone)
    val dow = day.dayOfWeek
    return when (kind) {
        WhenKind.TODAY -> DayRange(isoOf(day), isoOf(day))
        WhenKind.WEEKEND -> if (dow == DayOfWeek.SUNDAY) {
            DayRange(isoOf(day), isoOf(day))
        } else {
            val saturday = day.plusDays((DayOfWeek.SATURDAY.value - dow.value).toLong())
            DayRange(isoOf(saturday), isoOf(saturday.plusDays(1)))
        }
        WhenKind.WEEK -> DayRange(isoOf(day), isoOf(day.plusDays(if (dow == DayOfWeek.SUNDAY) 7 else (7 - dow.value).toLong())))
        WhenKind.DATES -> {
            val a = dates.start.takeIf { isoDay(it) != null }
            val b = dates.end.takeIf { isoDay(it) != null }
            when {
                a == null && b == null -> DayRange(isoOf(day), isoOf(day.plusDays(6)))
                a == null || b == null -> (a ?: b!!).let { DayRange(it, it) }
                a <= b -> DayRange(a, b)
                else -> DayRange(b, a)
            }
        }
    }
}

/** « du 21 au 22 nov. », « 21 nov. » : les dates choisies, en court, sur la puce « Des dates… ». */
fun rangeWords(r: DayRange, now: Long, zone: ZoneId = PARIS): String {
    val a = isoDay(r.start) ?: return ""
    val b = isoDay(r.end) ?: a
    val n = (ChronoUnit.DAYS.between(a, b) + 1).toInt().coerceAtLeast(1)
    val span = tripSpan(isoOf(a), n, now, zone)
    return if (n > 1) "du ${span.replace("–", " au ")}" else span
}

// ── Les jours ───────────────────────────────────────────────────────────

private val WEEKDAYS = listOf("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
private val WEEKDAYS_SHORT = listOf("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
private val MONTHS = listOf(
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)
private val MONTHS_SHORT = listOf("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")
private val ISO_START = Regex("""^(\d{4}-\d{2}-\d{2})""")

/** Le jour d'un événement (`AAAA-MM-JJ`), de sa prochaine date (`start` : une date, ou une date et une heure) ; sinon vide. */
fun eventDayOf(e: EventItem): String {
    val day = ISO_START.find(e.start)?.groupValues?.get(1) ?: return ""
    return if (isoDay(day) != null) day else ""
}

/** La tête d'un jour : « Aujourd'hui · vendredi 20 novembre », « Demain · samedi 21 novembre », « Lundi 23 novembre ». */
fun dayHeading(iso: String, now: Long, zone: ZoneId = PARIS): String {
    val d = isoDay(iso) ?: return "Plus tard"
    val t = today(now, zone)
    val year = if (d.year != t.year) " ${d.year}" else ""
    val day = "${WEEKDAYS[d.dayOfWeek.value - 1]} ${if (d.dayOfMonth == 1) "1er" else d.dayOfMonth} ${MONTHS[d.monthValue - 1]}$year"
    return when (ChronoUnit.DAYS.between(t, d)) {
        0L -> "Aujourd'hui · $day"
        1L -> "Demain · $day"
        else -> day.replaceFirstChar { it.uppercase() }
    }
}

/** « sam. 21 nov. » d'un jour : ce par quoi commence le `when_text` d'un événement de ce jour-là. */
private fun shortDay(iso: String): String {
    val d = isoDay(iso) ?: return ""
    return "${WEEKDAYS_SHORT[d.dayOfWeek.value - 1]} ${if (d.dayOfMonth == 1) "1er" else d.dayOfMonth} ${MONTHS_SHORT[d.monthValue - 1]}"
}

/** Son quand, sous la tête de son jour : sans le jour qu'elle dit déjà (« sam. 21 nov. · 19:00–22:00 » → « 19:00–22:00 »). */
fun whenInDay(e: EventItem): String {
    val text = e.whenText.trim()
    val day = shortDay(eventDayOf(e))
    return if (day.isNotEmpty() && text.startsWith("$day · ")) text.substring(day.length + 3) else text
}

/** Un jour de la liste : `AAAA-MM-JJ` (vide : une date illisible, à la fin), sa tête, ses événements. */
data class EventDay(val day: String, val title: String, val events: List<EventItem>)

/** Les événements groupés par jour, dans l'ordre du serveur (les plus tôt d'abord, puis les plus proches). */
fun eventDays(events: List<EventItem>, now: Long, zone: ZoneId = PARIS): List<EventDay> {
    val groups = LinkedHashMap<String, MutableList<EventItem>>()
    for (e in events) groups.getOrPut(eventDayOf(e)) { mutableListOf() } += e
    return groups.entries
        .sortedWith { a, b ->
            when {
                a.key == b.key -> 0
                a.key.isEmpty() -> 1
                b.key.isEmpty() -> -1
                else -> a.key.compareTo(b.key)
            }
        }
        .map { (day, list) -> EventDay(day, dayHeading(day, now, zone), list) }
}

// ── Ce qu'on en dit ─────────────────────────────────────────────────────

/** Ses thèmes, en mots, depuis ce que le serveur sait (`GET /carte` : `themes`) : « Concerts, Spectacles ». */
fun themeWords(themes: List<String>, labels: List<Category>): String {
    val names = labels.associate { it.id to it.label }
    return themes.mapNotNull { names[it]?.takeIf { l -> l.isNotBlank() } }.joinToString(", ")
}

/** Son prix en court : « Gratuit » (et ce que ses tarifs en disent, sans le redire), ses tarifs, ou rien. */
fun priceWords(e: EventItem): String {
    val price = e.price.trim()
    if (e.free != true) return price
    if (price.isEmpty()) return "Gratuit"
    return if (price.startsWith("gratuit", ignoreCase = true)) price.replaceFirstChar { it.uppercase() } else "Gratuit · $price"
}

/** La ligne d'un événement sous son nom : son premier thème, son quand (sans son jour, sous la tête du jour), son lieu. */
fun eventLine(e: EventItem, labels: List<Category>, inDay: Boolean): String =
    listOf(themeWords(e.themes.take(1), labels), if (inDay) whenInDay(e) else e.whenText, e.place)
        .map { it.trim() }.filter { it.isNotEmpty() }.joinToString(" · ")

/** « En parler à Mika » d'un événement : la phrase qu'on lui prépare, à compléter. */
fun askAboutEvent(e: EventItem): String {
    val what = listOf(e.whenText, e.place).map { it.trim() }.filter { it.isNotEmpty() }.joinToString(", ")
    return "Tu as vu « ${e.name} »${if (what.isNotEmpty()) " ($what)" else ""} ? "
}

/** Un événement comme lieu (un arrêt de voyage, la fin d'un itinéraire) : son nom, et où. */
fun eventAsPlace(e: EventItem): Place =
    Place(name = e.name, kindFr = "Événement", lat = e.lat, lon = e.lon, distanceM = e.distanceM)

/**
 * Le jour d'un voyage où tombe un événement (« Ajouter au voyage », au bon jour) : [start] sa date de départ, [days]
 * combien de jours ; hors du voyage ou sans date : −1 (son dernier jour, alors).
 */
fun eventTripDay(start: String, days: Int, e: EventItem): Int {
    val first = isoDay(start) ?: return -1
    val day = isoDay(eventDayOf(e)) ?: return -1
    val n = ChronoUnit.DAYS.between(first, day).toInt() + 1
    return if (n >= 1 && n <= maxOf(1, days)) n else -1
}

/** Ses épingles : un événement par point (sans coordonnées, aucune), le choisi cerclé, ceux de Mika en rose. */
fun eventPins(events: List<EventItem>, sel: String?, mika: Boolean): List<ScenePin> = events.mapNotNull { e ->
    val at = e.at ?: return@mapNotNull null
    ScenePin(e.id, at.lat, at.lon, mika = mika, selected = e.id == sel, title = e.name)
}

// ── La fiche d'un événement ─────────────────────────────────────────────

/**
 * Ce que montre la fiche d'un événement : ses étiquettes (quand, combien, à quelle distance), son programme, ses dates,
 * le pratique — le lieu nommé ([venueId] : sa fiche, s'il est rapproché), l'adresse, les tarifs, les contacts — et qui
 * l'a écrite ([attribution], [licence], [fiche]), toujours.
 */
data class EventShown(
    val tags: List<FicheTag>,
    val paragraphs: List<String>,
    val dates: List<String>,
    val moreDates: String,
    val venue: String,
    val venueId: String?,
    val rows: List<Fact>,
    val attribution: String,
    val licence: LinkText,
    val fiche: LinkText?,
    val merged: String,
)

/** Ses étiquettes : quand, son prix (vert s'il est gratuit), sa distance. */
fun eventTags(e: EventItem): List<FicheTag> = buildList {
    e.whenText.trim().takeIf { it.isNotEmpty() }?.let { add(FicheTag(TagKind.WHEN, it, Tone.INFO)) }
    priceWords(e).takeIf { it.isNotEmpty() }?.let { add(FicheTag(TagKind.PRICE, it, if (e.free == true) Tone.OK else Tone.NEUTRAL)) }
    km(e.distanceM).takeIf { it.isNotEmpty() }?.let { add(FicheTag(TagKind.DISTANCE, "à $it")) }
}

/** La fiche d'un événement telle qu'on la montre ; [hint] : sa ligne de la liste (sa distance, que la fiche n'a pas). */
fun eventShown(f: EventFiche, hint: EventItem? = null): EventShown {
    val e = if (f.event.distanceM == null && hint?.distanceM != null) f.event.copy(distanceM = hint.distanceM) else f.event
    val town = f.town.trim()
    val where = listOf(f.address.trim(), if (town.isNotEmpty() && f.address.contains(town)) "" else town)
        .filter { it.isNotEmpty() }.joinToString(", ")
    val rows = shownFacts(
        listOfNotNull(
            where.takeIf { it.isNotEmpty() }?.let { Fact("Adresse", it) },
            f.prices.trim().takeIf { it.isNotEmpty() }?.let { Fact("Tarifs", it) },
        ) + f.contacts,
    )
    val more = f.moreDates.coerceAtLeast(0)
    return EventShown(
        tags = eventTags(e),
        paragraphs = paragraphs(f.description),
        dates = f.dates.map { it.text.trim() }.filter { it.isNotEmpty() },
        moreDates = if (more > 0) "Et $more autre${if (more > 1) "s" else ""} date${if (more > 1) "s" else ""}." else "",
        venue = f.venue.trim(),
        venueId = if (f.venue.isNotBlank()) placeRef(f.venuePlace) else null,
        rows = rows,
        attribution = f.attribution.trim().ifEmpty { TOURISM_SOURCE },
        licence = linkText(f.licence.trim().ifEmpty { TOURISM_LICENCE }, f.licenceUrl),
        fiche = safeHref(f.url)?.let { LinkText("Sa fiche", it) },
        merged = if (f.merged > 1) "${f.merged} fiches de l'office réunies" else "",
    )
}

/** La ligne sous le nom d'une fiche d'événement : « Concerts · Roubaix ». */
fun eventSub(e: EventItem, town: String, labels: List<Category>): String =
    listOf(themeWords(e.themes, labels), town.trim()).filter { it.isNotEmpty() }.joinToString(" · ")
