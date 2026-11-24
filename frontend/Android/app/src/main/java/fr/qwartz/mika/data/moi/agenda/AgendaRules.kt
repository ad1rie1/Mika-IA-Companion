package fr.qwartz.mika.data.moi.agenda

import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.net.Topics

/*
 * Ce que l'Agenda montre, pur (porté de `frontendv2/src/screens/agenda/model.ts` et de la maquette validée
 * `frontend/Android/maquette/ecrans/agenda.js`, sans rien réinventer) : les occurrences d'une période (les événements
 * de ses agendas, les dates de « L'agenda de Mika », ce que Mika propose d'ajouter), leur sorte, leur couleur, leur
 * place dans une grille (les chevauchements en colonnes, les journées en bandes), le Planning jour par jour, les cases
 * du mois ; les mots d'un moment, d'un rappel, d'un fournisseur, d'un partage ; « À décider » ; ce que Mika fait d'un
 * agenda ; ce que le direct fait relire. Rien ne se décide ici : un geste n'existe que si le serveur l'ouvre (`can`).
 */

/** Ce que l'app écrit pour l'Agenda : la capacité de ses cartes d'accord (`protocole-chat.md` § 4). */
const val CAPABILITY_AGENDA_WRITE = "agenda.write"

// ── les occurrences ─────────────────────────────────────────────────────

enum class OccKind { EVENT, HER, PROPOSAL }

/** Une occurrence à montrer : un événement, une date de sa mémoire, ou ce qu'elle propose d'ajouter. */
data class Occ(
    val kind: OccKind,
    /** Sa clé stable (une ligne de liste). */
    val key: String,
    val title: String,
    /** La clé de son agenda (`mika` pour sa mémoire). */
    val calendar: String,
    /** Son premier et son dernier jour (compris), à l'heure du serveur. */
    val day: String,
    val last: String,
    /** Une journée entière (ou plusieurs), ou un rendez-vous de 24 h et plus : une bande. */
    val allDay: Boolean,
    /** Ses minutes dans son premier jour (la fin bornée à minuit). */
    val start: Int,
    val end: Int,
    val startMs: Long,
    val endMs: Long,
    val item: AgendaItem? = null,
    val her: HerDate? = null,
    val proposal: Proposal? = null,
)

private const val HOUR_MS = 3_600_000L
private const val DAY_MS = 86_400_000L

private data class Placed(val day: String, val last: String, val allDay: Boolean, val start: Int, val end: Int)

private fun placed(startMs: Long, endMs: Long, allDay: Boolean, firstDay: String, lastDay: String, zone: String): Placed {
    if (allDay && firstDay.isNotEmpty()) return Placed(firstDay, lastDay.ifEmpty { firstDay }, true, 0, 1440)
    val a = localOf(startMs, zone)
    val b = localOf(maxOf(startMs, endMs), zone)
    if (endMs - startMs >= 24 * HOUR_MS) {
        // un rendez-vous de plusieurs jours : une bande, du jour où il commence à celui où il finit
        val last = if (b.minute == 0 && b.day > a.day) addDays(b.day, -1) else b.day
        return Placed(a.day, last, true, a.minute, 1440)
    }
    val end = if (b.day > a.day) 1440 else maxOf(b.minute, a.minute)
    return Placed(a.day, a.day, false, a.minute, end)
}

fun occOfItem(item: AgendaItem, zone: String): Occ {
    val p = placed(item.start, item.end, item.allDay, item.firstDay, item.lastDay, zone)
    return Occ(
        OccKind.EVENT, "e:${item.event}:${item.occurrence}", if (item.masked) "Occupé" else item.title.ifBlank { NO_TITLE },
        item.calendar, p.day, p.last, p.allDay, p.start, p.end, item.start, item.end, item = item,
    )
}

fun occOfHer(her: HerDate, zone: String): Occ {
    val day = if (her.allDay) her.day.ifEmpty { localOf(her.start, zone).day } else ""
    val p = placed(her.start, maxOf(her.end, her.start), her.allDay, day, day, zone)
    return Occ(OccKind.HER, "m:${her.ref}", her.title, AgendaKinds.MIKA, p.day, p.last, p.allDay, p.start, p.end, her.start, her.end, her = her)
}

fun occOfProposal(p: Proposal, zone: String): Occ? {
    val d = p.draft ?: return null
    val first = if (d.allDay) localOf(d.start, "UTC").day else ""
    val last = if (d.allDay) localOf(maxOf(d.start, d.end - DAY_MS), "UTC").day else ""
    val x = placed(d.start, d.end, d.allDay, first, last, zone)
    return Occ(OccKind.PROPOSAL, "p:${p.id}", d.title.ifBlank { NO_TITLE }, p.calendar, x.day, x.last, x.allDay, x.start, x.end, d.start, d.end, proposal = p)
}

const val NO_TITLE = "(sans titre)"

/** Dans l'ordre : par jour, les journées d'abord, puis l'heure. */
fun sortOccs(occs: List<Occ>): List<Occ> =
    occs.sortedWith(compareBy<Occ> { it.day }.thenByDescending { it.allDay }.thenBy { it.start }.thenBy { it.title })

/** Les occurrences qui touchent [first, after[. */
fun within(occs: List<Occ>, first: String, after: String): List<Occ> = occs.filter { it.last >= first && it.day < after }

/**
 * Ce que la vue montre d'une période lue : les occurrences des agendas qui s'y affichent ([shown]), les dates de sa
 * mémoire si elle s'affiche, et ce que Mika propose — toujours, elle attend ta décision.
 */
fun periodOccs(period: Period, zone: String, shown: (String) -> Boolean): List<Occ> {
    val out = ArrayList<Occ>()
    for (item in period.items) if (shown(item.calendar)) out += occOfItem(item, zone)
    if (shown(AgendaKinds.MIKA)) for (d in period.her) out += occOfHer(d, zone)
    for (p in period.proposals) occOfProposal(p, zone)?.let { out += it }
    return sortOccs(out)
}

// ── leur sorte, leur couleur ────────────────────────────────────────────

enum class Sort { PLAIN, PROPOSED, INVITED, MAYBE, MIKA }

fun sortOf(o: Occ): Sort = when {
    o.kind == OccKind.PROPOSAL -> Sort.PROPOSED
    o.kind == OccKind.HER -> Sort.MIKA
    o.item?.invitation == true -> Sort.INVITED
    o.item?.response == "peut" -> Sort.MAYBE
    else -> Sort.PLAIN
}

/** Ce que Mika y a mis (✦ « ajouté par Mika »). */
fun addedByHer(o: Occ): Boolean = o.item?.added?.by == "elle"

/** La palette des agendas (le rose n'y est pas : il est à Mika). */
val PALETTE = listOf("indigo", "bleu", "sarcelle", "vert", "ambre", "orange", "violet", "ardoise")

/** Les mots de chaque couleur. */
val PALETTE_WORDS = mapOf(
    "indigo" to "Indigo", "bleu" to "Bleu", "sarcelle" to "Sarcelle", "vert" to "Vert", "ambre" to "Ambre",
    "orange" to "Orange", "violet" to "Violet", "ardoise" to "Ardoise",
)

private val RGB = mapOf(
    "indigo" to Triple(79, 70, 229), "bleu" to Triple(31, 111, 208), "sarcelle" to Triple(15, 139, 128), "vert" to Triple(30, 154, 75),
    "ambre" to Triple(192, 132, 6), "orange" to Triple(226, 106, 27), "violet" to Triple(139, 92, 246), "ardoise" to Triple(102, 116, 138),
)

/** La couleur de la palette la plus proche d'une couleur `#rrggbb` du fournisseur ; illisible : rien. */
fun nearestColor(hex: String): String {
    val m = Regex("""^#?([0-9a-fA-F]{2})([0-9a-fA-F]{2})([0-9a-fA-F]{2})$""").find(hex.trim()) ?: return ""
    val (r, g, b) = (1..3).map { m.groupValues[it].toInt(16) }
    return PALETTE.minBy { name ->
        val (x, y, z) = RGB.getValue(name)
        (r - x) * (r - x) + (g - y) * (g - y) + (b - z) * (b - z)
    }
}

/** La couleur d'un agenda : la sienne, celle du fournisseur rapprochée de la palette, sinon une couleur stable ; le
 *  rose est à Mika ; « Mon agenda » est indigo. */
fun colorOf(cal: AgendaCalendar?): String {
    if (cal == null) return "ardoise"
    if (cal.kind == AgendaKinds.MIKA) return "rose"
    if (cal.color.isNotEmpty()) return cal.color
    if (cal.kind == AgendaKinds.SYSTEM && cal.primary && cal.level.ifEmpty { AgendaLevels.OWNER } == AgendaLevels.OWNER) return "indigo"
    nearestColor(cal.providerColor).takeIf { it.isNotEmpty() }?.let { return it }
    var x = 0L
    for (ch in cal.key) x = (x * 31 + ch.code) and 0xFFFFFFFFL
    return PALETTE[(x % PALETTE.size).toInt()]
}

/** La couleur d'une occurrence : rose pour ce que Mika propose, sinon celle de son agenda. */
fun occColor(o: Occ, calendars: List<AgendaCalendar>): String =
    if (o.kind == OccKind.PROPOSAL || o.kind == OccKind.HER) "rose" else colorOf(calendars.firstOrNull { it.key == o.calendar })

// ── la grille ───────────────────────────────────────────────────────────

/** Un rendez-vous placé dans sa journée : ses minutes (une demi-heure au moins de haut), sa colonne. */
data class GridSlot(val o: Occ, val from: Int, val to: Int, val col: Int, val cols: Int)

/** Les rendez-vous d'une journée : ceux qui se touchent se partagent la largeur, en colonnes. */
fun columns(occs: List<Occ>): List<GridSlot> {
    val evs = occs.map { GridSlot(it, it.start, maxOf(it.end, it.start + 24), 0, 1) }.sortedWith(compareBy<GridSlot> { it.from }.thenByDescending { it.to })
    val out = ArrayList<GridSlot>()
    var group = ArrayList<GridSlot>()
    var end = -1
    fun flush() {
        val cols = ArrayList<Int>()
        val placed = group.map { e ->
            var c = cols.indexOfFirst { it <= e.from }
            if (c < 0) {
                c = cols.size
                cols += e.to
            } else {
                cols[c] = e.to
            }
            e.copy(col = c)
        }
        out += placed.map { it.copy(cols = cols.size) }
        group = ArrayList()
    }
    for (e in evs) {
        if (group.isNotEmpty() && e.from >= end) {
            flush()
            end = -1
        }
        group += e
        end = maxOf(end, e.to)
    }
    if (group.isNotEmpty()) flush()
    return out
}

/** Une journée (ou plusieurs) dans les bandes d'une semaine : ses colonnes, sa ligne. */
data class Lane(val o: Occ, val from: Int, val to: Int, val lane: Int)

/** Les journées d'une semaine (ou d'un jour) en bandes : chacune sur sa ligne libre. */
fun lanes(occs: List<Occ>, first: String, n: Int): List<Lane> {
    val items = occs.map { Lane(it, maxOf(0, daysFrom(first, it.day)), minOf(n - 1, daysFrom(first, it.last)), 0) }
        .sortedWith(compareBy<Lane> { it.from }.thenByDescending { it.to - it.from })
    val ends = ArrayList<Int>()
    return items.map { x ->
        var l = ends.indexOfFirst { it < x.from }
        if (l < 0) {
            l = ends.size
            ends += x.to
        } else {
            ends[l] = x.to
        }
        x.copy(lane = l)
    }
}

// ── le Planning et le mois ──────────────────────────────────────────────

/** Un jour du Planning : ses occurrences, et où la ligne de l'heure s'y glisse aujourd'hui (son rang, -1 : nulle part). */
data class PlanningDay(val day: String, val occs: List<Occ>, val nowAt: Int)

/**
 * Le Planning : une liste par jour, de [first] à [after] exclu, aujourd'hui toujours là (même vide, la ligne de
 * l'heure), une occurrence de plusieurs jours sous chacun d'eux ; aujourd'hui, la ligne de l'heure avant le premier
 * rendez-vous qui n'a pas commencé.
 */
fun planningDays(occs: List<Occ>, first: String, after: String, today: String, nowMinute: Int): List<PlanningDay> {
    val days = sortedMapOf<String, MutableList<Occ>>()
    if (today >= first && today < after) days[today] = ArrayList()
    for (o in occs) {
        val end = if (o.allDay) o.last else o.day
        var d = o.day
        while (d <= end) {
            if (d >= after) break
            if (d >= first) days.getOrPut(d) { ArrayList() } += o
            d = addDays(d, 1)
        }
    }
    return days.map { (d, list) ->
        val sorted = list.sortedWith(compareByDescending<Occ> { it.allDay }.thenBy { it.start })
        val at = if (d == today) sorted.indexOfFirst { !it.allDay && it.start > nowMinute }.let { if (it < 0) sorted.size else it } else -1
        PlanningDay(d, sorted, at)
    }
}

/** Une case du mois : son jour, ses occurrences montrées (quatre au plus, ou trois et « +n »), ce qui reste. */
data class MonthCell(val day: String, val inMonth: Boolean, val today: Boolean, val shown: List<Occ>, val more: Int)

fun monthCells(occs: List<Occ>, month: String, today: String, max: Int = 4): List<MonthCell> {
    val m = partsOf(monthStart(month)).m
    return monthDays(month).map { d ->
        val here = occs.filter { it.day <= d && it.last >= d }
        val shown = here.take(if (here.size > max) max - 1 else max)
        MonthCell(d, partsOf(d).m == m, d == today, shown, here.size - shown.size)
    }
}

/** Les jours qui ont quelque chose (un point sous le jour du mini-mois). */
fun busyDays(occs: List<Occ>): Set<String> {
    val out = HashSet<String>()
    for (o in occs) {
        var d = o.day
        var guard = 0
        while (d <= o.last && guard++ < 400) {
            out += d
            d = addDays(d, 1)
        }
    }
    return out
}

// ── les mots ────────────────────────────────────────────────────────────

/** « Lundi 23 novembre · 14:00 – 15:00 », « Du … au … · journées entières ». */
fun whenWords(o: Occ, today: String): String = when {
    o.allDay && o.day == o.last -> "${cap(dayWords(o.day, today))} · journée entière"
    o.allDay -> "Du ${dayWords(o.day, today)} au ${dayWords(o.last, today)}"
    else -> "${cap(dayWords(o.day, today))} · ${hm(o.start)} – ${hm(o.end)}"
}

/** Le moment d'une ligne du Planning : « 09:00 – 09:30 », « Journée entière », « Jusqu'au mer. 25 nov. ». */
fun shortWhen(o: Occ): String = when {
    o.allDay && o.day == o.last -> "Journée entière"
    o.allDay -> "Jusqu'au ${shortDay(o.last)}"
    else -> "${hm(o.start)} – ${hm(o.end)}"
}

/** Où il en est par rapport à maintenant : son ton et ses mots (« dans 40 min », « en cours », « passé »…). */
fun relative(o: Occ, today: String, nowMinute: Int): Pair<Tone, String> {
    val e = daysFrom(today, o.day)
    if (o.allDay) {
        if (daysFrom(today, o.last) < 0) return Tone.NEUTRAL to "passé"
        if (e <= 0) return Tone.INFO to "aujourd'hui"
        return Tone.NEUTRAL to if (e == 1) "demain" else "dans $e jours"
    }
    if (isPast(o, today, nowMinute)) return Tone.NEUTRAL to "passé"
    if (e == 0 && o.start <= nowMinute) return Tone.OK to "en cours"
    if (e == 0) {
        val m = o.start - nowMinute
        return Tone.INFO to if (m < 60) "dans $m min" else "dans ${m / 60} h${if (m % 60 != 0) " ${pad(m % 60)}" else ""}"
    }
    if (e < 0) return Tone.NEUTRAL to "passé"
    return Tone.NEUTRAL to if (e == 1) "demain" else "dans $e jours"
}

fun isPast(o: Occ, today: String, nowMinute: Int): Boolean =
    daysFrom(today, o.last) < 0 || (o.last == today && !o.allDay && o.end <= nowMinute)

/** « Mika te le rappelle » : les choix, dans l'ordre. */
val MIKA_REMINDERS = listOf("non" to "Non", "15" to "15 min avant", "30" to "30 min avant", "60" to "1 h avant", "veille" to "La veille au soir")

fun mikaReminderWords(value: String): String = when (value) {
    "non" -> "non"
    "15" -> "15 min avant"
    "30" -> "30 min avant"
    "60" -> "1 h avant"
    "veille" -> "la veille au soir"
    else -> value
}

/** « Mika te le rappelle 30 min avant », « Mika ne te le rappelle pas ». */
fun mikaReminderLine(value: String): String =
    if (value == "non" || value.isEmpty()) "Mika ne te le rappelle pas" else "Mika te le rappelle ${mikaReminderWords(value)}"

/** Les choix du menu « Changer » d'un événement, celui de l'agenda en premier. */
fun remindChoices(cal: AgendaCalendar?): List<Pair<String, String>> =
    listOf("" to "Comme l'agenda (${mikaReminderWords(cal?.reminder ?: "non")})") + MIKA_REMINDERS

/** Un rappel du fournisseur en mots : « notification 10 min avant », « e-mail 1 jour avant ». */
fun alertWords(a: Alert): String = "${if (a.method == Alert.EMAIL) "e-mail" else "notification"} ${durationWords(a.minutes)} avant"

fun durationWords(minutes: Int): String = when {
    minutes == 0 -> "au début,"
    minutes % 1440 == 0 -> "${minutes / 1440} jour${if (minutes / 1440 > 1) "s" else ""}"
    minutes % 60 == 0 -> "${minutes / 60} h"
    else -> "$minutes min"
}

/** Les rappels du fournisseur qu'on ajoute d'un toucher (« Ajouter une notification »). */
val ALERT_PRESETS = listOf(5, 10, 30, 60, 1440)

/** Où part une écriture, selon la sorte de l'agenda. */
fun whereWords(kind: String): String = when (kind) {
    AgendaKinds.SYSTEM -> "sur ce serveur"
    AgendaKinds.GOOGLE -> "chez Google"
    AgendaKinds.MICROSOFT -> "chez Microsoft"
    AgendaKinds.CALDAV -> "chez le serveur CalDAV"
    else -> ""
}

/** D'où un événement supprimé disparaît aussi : « de ce serveur », « chez Google »… */
fun deletedWhere(kind: String): String = if (kind == AgendaKinds.SYSTEM) "de ce serveur" else whereWords(kind).ifEmpty { "de l'agenda" }

/** Ce que le fournisseur d'un agenda est, en court. */
fun providerShort(cal: AgendaCalendar): String = when {
    cal.group == AgendaGroups.SHARED -> "de ${firstName(cal.ownerName).ifEmpty { "quelqu'un" }} · ${levelWords(cal.level).lowercase()}"
    cal.kind == AgendaKinds.MIKA -> "sa mémoire · lecture seule"
    cal.kind == AgendaKinds.ICAL -> "abonnement iCal"
    cal.kind == AgendaKinds.SYSTEM -> "Système"
    cal.kind == AgendaKinds.MICROSOFT -> "Outlook"
    cal.kind == AgendaKinds.CALDAV -> "CalDAV"
    cal.kind == AgendaKinds.GOOGLE -> "Google"
    else -> cal.kindLabel
}

/** Les trois niveaux d'un partage, dits en entier (la fenêtre « Partager »). */
val LEVELS: List<Triple<String, String, String>> = listOf(
    Triple(AgendaLevels.READ, "Lire", "Voit ses événements dans son Agenda, sans rien y changer."),
    Triple(AgendaLevels.PREPARE, "Lire et préparer", "Les voit, et Mika peut y préparer un ajout pour elle ou lui : il n'entre qu'avec ton accord."),
    Triple(AgendaLevels.USE, "S'en servir", "Mika s'en sert avec elle ou lui, en tête-à-tête : trouver un créneau, y ajouter un rendez-vous, selon ton tableau de droits."),
)

fun levelWords(level: String): String = LEVELS.firstOrNull { it.first == level }?.second ?: level

/** Le nom qu'on montre d'un agenda : « Mon agenda » d'une autre personne, qu'elle te partage, devient « Agenda de Léa ». */
fun shownName(cal: AgendaCalendar): String =
    if (cal.group == AgendaGroups.SHARED && cal.kind == AgendaKinds.SYSTEM && cal.primary && cal.name == "Mon agenda" && cal.ownerName.isNotBlank()) {
        "Agenda ${ofName(firstName(cal.ownerName).ifEmpty { cal.ownerName })}"
    } else {
        cal.name
    }

fun withShownNames(list: List<AgendaCalendar>): List<AgendaCalendar> = list.map { c -> shownName(c).let { if (it == c.name) c else c.copy(name = it) } }

/** Les groupes de la feuille « Agendas à afficher » et de Paramètres : Mes agendas · Partagés avec moi · Abonnements ·
 *  L'agenda de Mika ; un agenda masqué dans Paramètres n'y est pas. */
val CALENDAR_GROUPS = listOf(
    AgendaGroups.MINE to "Mes agendas",
    AgendaGroups.SHARED to "Partagés avec moi",
    AgendaGroups.SUBSCRIPTIONS to "Abonnements",
    AgendaGroups.MIKA to "L'agenda de Mika",
)

fun groupedCalendars(list: List<AgendaCalendar>): List<Pair<String, List<AgendaCalendar>>> =
    CALENDAR_GROUPS.mapNotNull { (g, title) -> list.filter { it.group == g && !it.hidden }.takeIf { it.isNotEmpty() }?.let { title to it } }

/** Ce qu'une ligne de la feuille dit sous le nom d'un agenda : son fournisseur, et combien de partages. */
fun calendarLine(cal: AgendaCalendar): String = providerShort(cal) + if (cal.shares.isNotEmpty()) " · partagé à ${cal.shares.size}" else ""

/** Les agendas où elle écrit (le choix de l'agenda du formulaire). */
fun writableCalendars(list: List<AgendaCalendar>): List<AgendaCalendar> = list.filter { it.writable && it.can.write && !it.hidden }

/** L'agenda de départ d'un événement nouveau : « Mon agenda », sinon le premier où elle écrit. */
fun defaultCalendar(list: List<AgendaCalendar>): String {
    val w = writableCalendars(list)
    return (w.firstOrNull { it.kind == AgendaKinds.SYSTEM && it.primary } ?: w.firstOrNull())?.key.orEmpty()
}

/** Les agendas qu'on lit : tous ceux qu'elle voit (sauf les masqués), et celui de Mika. */
fun readKeys(list: List<AgendaCalendar>): List<String> {
    val keys = list.filter { !it.hidden }.map { it.key }
    return if (AgendaKinds.MIKA in keys) keys else keys + AgendaKinds.MIKA
}

/** Un agenda s'affiche-t-il : ni décoché ici ([off]), ni masqué dans Paramètres ; celui de Mika, sauf décoché. */
fun shownHere(key: String, list: List<AgendaCalendar>, off: Set<String>): Boolean {
    if (key in off) return false
    if (key == AgendaKinds.MIKA) return true
    val c = list.firstOrNull { it.key == key } ?: return false
    return !c.hidden
}

// ── la fiche ────────────────────────────────────────────────────────────

/** La réponse d'un participant en mots, et son ton. */
fun responseTag(p: AgendaPerson, organizer: Boolean): Pair<Tone, String> = when {
    organizer -> Tone.INFO to "organise"
    p.response == "oui" -> Tone.OK to "oui"
    p.response == "peut" -> Tone.WARN to "peut-être"
    p.response == "non" -> Tone.DANGER to "non"
    p.response == "attente" -> Tone.NEUTRAL to "sans réponse"
    else -> Tone.NEUTRAL to "invité"
}

/** Une personne de la fiche : son nom (celui que le serveur donne, sinon celui d'une personne qui a un compte ici, sinon
 *  son adresse), si c'est toi, sa réponse. */
data class PersonRow(val name: String, val address: String, val me: Boolean, val tone: Tone, val word: String)

/** Les participants d'un événement, l'organisateur d'abord ; rien s'il n'y a que soi. */
fun peopleOf(item: AgendaItem, names: Map<String, String> = emptyMap()): List<PersonRow> {
    val list = ArrayList<Pair<AgendaPerson, Boolean>>()
    item.organizer?.let { list += it to true }
    for (p in item.participants) if (item.organizer == null || p.address != item.organizer.address || p.address.isEmpty()) list += p to false
    if (list.size < 2 && item.participants.isEmpty()) return emptyList()
    return list.map { (p, org) ->
        val me = p.me || (org && item.organized)
        val name = p.name.ifBlank { names[p.person].orEmpty() }.ifBlank { p.address }.ifBlank { if (me) "Toi" else "Une personne qui a un compte ici" }
        val (tone, word) = responseTag(p, org)
        PersonRow(name, if (p.name.isNotBlank()) p.address else "", me, tone, word)
    }
}

/** « 5 participants · 3 oui · 1 peut-être · 1 sans réponse ». */
fun peopleSummary(rows: List<PersonRow>): String {
    var yes = 0
    var maybe = 0
    var no = 0
    var wait = 0
    for (r in rows) when (r.word) {
        "organise", "oui" -> yes++
        "peut-être" -> maybe++
        "non" -> no++
        else -> wait++
    }
    return listOf(
        if (yes > 0) "$yes oui" else "", if (maybe > 0) "$maybe peut-être" else "", if (no > 0) "$no non" else "",
        if (wait > 0) "$wait sans réponse" else "",
    ).filter { it.isNotEmpty() }.joinToString(" · ")
}

/** Qui t'invite : l'organisateur nommé, sinon une personne qui a un compte ici, sinon son adresse. */
fun inviter(item: AgendaItem, names: Map<String, String> = emptyMap()): String {
    val o = item.organizer ?: return ""
    return o.name.ifBlank { names[o.person].orEmpty() }.ifBlank { o.address }
}

/** Les trois réponses à une invitation. */
val ANSWERS = listOf("oui" to "Accepter", "peut" to "Peut-être", "non" to "Refuser")

fun answerWord(answer: String): String = when (answer) {
    "oui" -> "oui"
    "peut" -> "peut-être"
    "non" -> "non"
    else -> answer
}

/** La réponse que Mika a préparée en mots : « Refuser, avec un mot : « … » ». */
fun preparedWords(p: Proposal): String {
    val verb = ANSWERS.firstOrNull { it.first == p.answer }?.second ?: p.answer
    return if (p.comment.isNotBlank()) "$verb, avec un mot : « ${p.comment} »" else verb
}

/** Une invitation ou un événement qu'on n'organise pas : le supprimer, c'est le retirer (le refuser). */
fun removesInvitation(item: AgendaItem): Boolean = item.invitation || !item.organized

/** Le pied de la fiche : pourquoi on n'y change rien, ou où part une modification. */
fun ficheFoot(item: AgendaItem, cal: AgendaCalendar?): String = when {
    item.masked -> "Un événement privé : tu n'en vois que le créneau."
    cal?.group == AgendaGroups.SHARED && !cal.writable ->
        "${cal.ownerName.ifBlank { "Son propriétaire" }} partage cet agenda avec toi${if (cal.level == AgendaLevels.PREPARE) " en lecture et préparation" else " en lecture"} : tu le vois, tu n'y changes rien."
    cal?.kind == AgendaKinds.ICAL -> "Un abonnement est en lecture seule : ni toi ni Mika n'y écrivez."
    cal?.readOnly == true -> "Son fournisseur ne laisse pas écrire dans cet agenda."
    cal != null && cal.writable -> "Une modification part tout de suite ${whereWords(cal.kind)}${if (cal.kind == AgendaKinds.SYSTEM) "" else ", puis l'agenda se relit"}."
    else -> ""
}

/** Les rappels du fournisseur d'un événement, en lignes. */
fun providerReminderLines(item: AgendaItem, cal: AgendaCalendar?): List<String> {
    if (cal == null) return emptyList()
    if (cal.kind == AgendaKinds.SYSTEM) return listOf("L'agenda du système n'envoie rien lui-même : c'est Mika qui te le rappelle.")
    val who = when (cal.kind) {
        AgendaKinds.GOOGLE -> "par Google"
        AgendaKinds.MICROSOFT -> "par Outlook"
        AgendaKinds.CALDAV -> "par le serveur CalDAV"
        AgendaKinds.ICAL -> "dans l'abonnement"
        else -> ""
    }
    if (item.reminders.isEmpty()) return listOf(if (cal.providerReminders.max > 0 || cal.kind == AgendaKinds.ICAL) "Aucun rappel $who" else "Aucun rappel du fournisseur")
    return item.reminders.map { a -> cap(alertWords(a)) + (if (who.isNotEmpty()) ", $who" else "") + if (item.remindersDefault) " · le réglage de l'agenda" else "" }
}

// ── ce que Mika fait d'un agenda (son tableau) ──────────────────────────

/** La ligne de son propriétaire quand Mika lui répond : la première qui la nomme (`personne:<sa clé>`, ou « toi »). */
fun ownerLine(t: AgendaRights, me: String, moment: String = "conversation"): AgendaRule? =
    t.lines.firstOrNull { l -> ("personne:$me" in l.who || "proprietaire" in l.who) && (l.moment.isEmpty() || moment in l.moment) }

/** Ce que Mika fait d'un agenda, en une ligne : « Avec toi, elle le lit, y ajoute avec ton accord, prépare tes
 *  réponses ; elle te rappelle ses rendez-vous · aussi avec Léa ». */
fun rightsSummary(t: AgendaRights, me: String, shares: List<AgendaShare> = emptyList(), writable: Boolean = true): String {
    val l = ownerLine(t, me) ?: return ""
    val write = if (writable) when (l.write) {
        "non" -> "n'y écrit pas"
        "accord" -> "y ajoute avec ton accord"
        "seule" -> "y ajoute seule"
        else -> ""
    } else {
        ""
    }
    val parts = listOf(if (l.read) "le lit" else "ne le lit pas", if (l.read) write else "", if (writable && l.respond == "accord") "prépare tes réponses" else "").filter { it.isNotEmpty() }
    val initiative = ownerLine(t, me, "initiative")
    val remind = if (initiative != null && initiative != l && initiative.read) " ; elle te rappelle ses rendez-vous" else ""
    val others = if (shares.isNotEmpty()) " · aussi avec ${shares.joinToString(" et ") { firstName(it.name).ifEmpty { it.name } }}" else ""
    return "Avec toi, elle ${parts.joinToString(", ")}$remind$others"
}

/** Combien d'outils seule, avec ton accord, non — pour son propriétaire quand elle lui répond (les pastilles). */
data class RightsPills(val alone: Int, val ask: Int, val no: Int)

fun rightsPills(t: AgendaRights, me: String): RightsPills? {
    val l = ownerLine(t, me) ?: return null
    val cells = listOf(if (l.read) "S" else "N", when (l.write) { "seule" -> "S"; "accord" -> "A"; else -> "N" }, if (l.respond == "accord") "A" else "N")
    return RightsPills(cells.count { it == "S" }, cells.count { it == "A" }, cells.count { it == "N" })
}

/** Les colonnes d'un tableau d'agenda : leur nom, leurs outils, leurs choix. */
object RightsColumns {
    const val READ = "read"
    const val WRITE = "write"
    const val RESPOND = "respond"
    const val KEEP = "keep"

    val ALL = listOf(
        Triple(READ, "Lire", "agenda_list · agenda_events · agenda_free"),
        Triple(WRITE, "Ajouter, modifier, supprimer", "agenda_create · agenda_edit · agenda_delete"),
        Triple(RESPOND, "Répondre aux invitations", "agenda_respond"),
        Triple(KEEP, "Ce qu'elle en garde", ""),
    )

    fun choices(col: String): List<Pair<String, String>> = when (col) {
        READ -> listOf("oui" to "Oui", "non" to "Non")
        WRITE -> listOf("non" to "Non", "accord" to "Avec ton accord", "seule" to "Seule")
        RESPOND -> listOf("non" to "Non", "accord" to "Avec ton accord")
        else -> listOf("rien" to "Rien", "perso" to "Un souvenir", "public" to "Un savoir", "prive" to "Une confidence")
    }

    fun valueOf(line: AgendaRule, col: String): String = when (col) {
        READ -> if (line.read) "oui" else "non"
        WRITE -> line.write
        RESPOND -> line.respond
        else -> line.keep
    }

    fun words(col: String, value: String): String = choices(col).firstOrNull { it.first == value }?.second ?: value

    /** Le ton d'une case : seule en vert, ton accord en ambre, non en gris. */
    fun tone(value: String): Tone = when (value) {
        "oui", "seule" -> Tone.OK
        "accord" -> Tone.WARN
        else -> Tone.NEUTRAL
    }

    /** La ligne avec cette case changée. */
    fun set(line: AgendaRule, col: String, value: String): AgendaRule = when (col) {
        READ -> line.copy(read = value == "oui")
        WRITE -> line.copy(write = value)
        RESPOND -> line.copy(respond = value)
        else -> line.copy(keep = value)
    }
}

/** La personne d'une ligne qui ne nomme qu'elle (`personne:<clé>`), si elle a un partage de cet agenda. */
fun sharedPerson(cal: AgendaCalendar, line: AgendaRule): String {
    if (line.who.size != 1 || !line.who[0].startsWith("personne:")) return ""
    val person = line.who[0].removePrefix("personne:")
    return if (cal.shares.any { it.person == person }) person else ""
}

/** Qui une ligne nomme, en mots : « Toi », « Mika », sinon le nom du serveur. */
fun ruleWho(line: AgendaRule, me: String): String = when {
    "proprietaire" in line.who || (me.isNotEmpty() && line.who == listOf("personne:$me")) -> "Toi"
    line.who == listOf("elle") -> "Mika"
    else -> line.words?.who?.ifBlank { null } ?: line.who.joinToString(", ")
}

/** Les règles en tête d'un tableau. */
fun rightsRules(cal: AgendaCalendar, t: AgendaRights): List<String> = buildList {
    add("Lues de haut en bas : la première ligne qui correspond décide")
    add("Le propriétaire et le partage d'abord : une ligne n'ouvre jamais un agenda à qui il n'est pas")
    if (!cal.writable) add(if (cal.kind == AgendaKinds.ICAL) "Un abonnement est en lecture seule : ni toi ni elle n'y écrivez" else "Son fournisseur ne laisse pas écrire dans cet agenda")
    if (cal.shares.isNotEmpty()) add("Partagé dans Mika avec ${cal.shares.joinToString(" et ") { it.name }} : une ligne chacun")
    if (!t.set) add("Le tableau de départ, que son propriétaire et ses partages donnent")
}

// ── À décider ───────────────────────────────────────────────────────────

/** Ce que Mika propose d'ajouter et dont tu décides (le bandeau, la vue, les notifications). */
fun pendingAdds(proposals: List<Proposal>): List<Proposal> = proposals.filter { it.op == Proposal.ADD && it.decides && it.draft != null }

/** « Mika propose « Dîner chez Léa » · 2 invitations » : le bandeau replié. */
fun decideSummary(adds: List<Proposal>, invitations: Int): String = listOf(
    adds.firstOrNull()?.let { "Mika propose « ${it.draft?.title?.ifBlank { NO_TITLE }} »" }.orEmpty(),
    if (invitations > 0) "$invitations invitation${if (invitations > 1) "s" else ""}" else "",
).filter { it.isNotEmpty() }.joinToString(" · ")

/** Le moment d'une proposition, dans le bandeau : « Sam. 28 nov. · 20:00 – 23:00 ». */
fun proposalWhen(o: Occ): String =
    if (o.allDay) cap(shortDay(o.day)) else "${cap(shortDay(o.day))} · ${hm(o.start)} – ${hm(o.end)}"

// ── le direct (ADR 0308) ────────────────────────────────────────────────

/** Ce que les écrans de l'Agenda suivent : l'agenda (`agenda`, clé `calendars`), et `me` pour les pastilles. */
object AgendaLive {
    val TOPICS = setOf(Topics.AGENDA)

    /** La période affichée se relit-elle ? Tout l'agenda, ou un des agendas qu'elle montre. */
    fun periodShows(keys: Collection<String>, s: LiveSignal): Boolean = s.namesAny(Topics.AGENDA, keys)

    /** L'événement ouvert (dans [calendar]) se relit-il ? */
    fun eventShows(calendar: String, s: LiveSignal): Boolean = s.names(Topics.AGENDA, calendar)
}

// ── les adresses d'une notification (le canal « Agenda ») ───────────────

/** Ce qu'ouvre une notification de l'Agenda : une invitation (son événement et son occurrence), ou une proposition. */
sealed interface AgendaTarget {
    data class Event(val event: Int, val occurrence: String) : AgendaTarget
    data class Ask(val proposal: Int) : AgendaTarget

    fun encode(): String = when (this) {
        is Event -> "agenda:e:$event:$occurrence"
        is Ask -> "agenda:p:$proposal"
    }

    companion object {
        fun decode(raw: String?): AgendaTarget? {
            val parts = raw?.split(':', limit = 4) ?: return null
            if (parts.size < 3 || parts[0] != "agenda") return null
            return when (parts[1]) {
                "e" -> parts[2].toIntOrNull()?.let { Event(it, parts.getOrElse(3) { "" }) }
                "p" -> parts[2].toIntOrNull()?.let { Ask(it) }
                else -> null
            }
        }
    }
}

/** Une notification de l'Agenda : sa clé (une fois chacune), ce qu'elle dit, ce qu'elle ouvre. */
data class AgendaNote(val key: String, val title: String, val text: String, val target: AgendaTarget)

/**
 * Ce que l'Agenda notifie (un seul canal « Agenda », recommandation 11 de la conception) : chaque invitation qui attend
 * ta réponse, et chaque ajout que Mika propose dont tu décides — avec ce qu'elle a préparé.
 */
fun agendaNotes(invitations: List<AgendaItem>, proposals: List<Proposal>, calendars: List<AgendaCalendar>, zone: String, today: String): List<AgendaNote> {
    val out = ArrayList<AgendaNote>()
    for (i in invitations) {
        val o = occOfItem(i, zone)
        val who = inviter(i).ifBlank { "Quelqu'un" }
        val where = i.location.substringBefore(" · ").takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty()
        val prep = i.prepared?.takeIf { it.decides }?.let { " Mika a préparé : ${preparedWords(it).replaceFirstChar { c -> c.lowercase() }}." }.orEmpty()
        out += AgendaNote("i:${i.event}:${i.occurrence}", "$who t'invite : ${o.title}", "${cap(whenWords(o, today))}$where.$prep", AgendaTarget.Event(i.event, i.occurrence))
    }
    for (p in pendingAdds(proposals)) {
        val o = occOfProposal(p, zone) ?: continue
        val cal = calendars.firstOrNull { it.key == p.calendar }?.let(::shownName) ?: "ton agenda"
        val where = p.draft?.location?.takeIf { it.isNotBlank() }?.let { " · $it" }.orEmpty()
        val remind = p.remind?.takeIf { it.isNotEmpty() && it != "non" }?.let { " Elle te le rappellera ${mikaReminderWords(it)}." }.orEmpty()
        out += AgendaNote("p:${p.id}", "Ajouter « ${o.title} » à $cal ?", "${proposalWhen(o)}$where.$remind", AgendaTarget.Ask(p.id))
    }
    return out
}

// ── ses comptes (Paramètres › Agendas) ──────────────────────────────────

/** Les cinq sortes qu'on branche, dans l'ordre : leur nom long, ce qu'il faut pour les brancher. */
val PLUG_KINDS: List<Triple<String, String, String>> = listOf(
    Triple(AgendaKinds.SYSTEM, "Agenda du système", "Sur ce serveur : rien ne sort d'ici. Chaque personne qui a un compte a déjà « Mon agenda »."),
    Triple(AgendaKinds.GOOGLE, "Google Agenda", "Se connecter à Google, puis coller l'adresse de retour."),
    Triple(AgendaKinds.MICROSOFT, "Outlook.com / Microsoft 365", "Un code à entrer chez Microsoft, comme pour une boîte Outlook."),
    Triple(AgendaKinds.CALDAV, "CalDAV", "Une adresse, un identifiant, un mot de passe d'application. Outlook pro par DavMail, iCloud, Nextcloud, Fastmail."),
    Triple(AgendaKinds.ICAL, "Abonnement iCal", "Une adresse .ics, en lecture seule : jours fériés, adresse secrète d'un agenda."),
)

fun kindLong(kind: String, label: String = ""): String = PLUG_KINDS.firstOrNull { it.first == kind }?.second ?: label.ifBlank { kind }

/** Google ou Microsoft, pas encore (ou plus) connecté. */
fun needsSignin(a: AgendaAccount): Boolean =
    (a.kind == AgendaKinds.GOOGLE || a.kind == AgendaKinds.MICROSOFT) && a.signin?.state != AgendaSignin.CONNECTED

/** L'état d'un compte en mots : à jour, décoché, à connecter, en panne, pas encore synchronisé, synchronisé. */
fun accountState(a: AgendaAccount): Pair<Tone, String> = when {
    a.system -> Tone.OK to "à jour"
    !a.enabled -> Tone.NEUTRAL to "décoché"
    needsSignin(a) -> Tone.WARN to "à connecter"
    a.error.isNotBlank() -> Tone.WARN to "en panne"
    a.syncedAt <= 0 -> Tone.NEUTRAL to "pas encore synchronisé"
    else -> Tone.OK to if (a.kind == AgendaKinds.ICAL) "relu" else "synchronisé"
}

/** Sa dernière synchronisation, en mots. */
fun accountSync(a: AgendaAccount, now: Long): String = when {
    a.system -> "Toujours à jour : il est sur ce serveur."
    a.syncedAt <= 0 -> if (a.triedAt > 0) "Dernier essai ${fr.qwartz.mika.data.moi.ago(a.triedAt, now)}." else "Pas encore synchronisé."
    else -> "${if (a.kind == AgendaKinds.ICAL) "Relu" else "Synchronisé"} ${fr.qwartz.mika.data.moi.ago(a.syncedAt, now)}."
}

/** La ligne d'un compte dans la liste : sa panne, ou sa synchro et combien d'agendas. */
fun accountLine(a: AgendaAccount, now: Long): String = when {
    needsSignin(a) && a.enabled -> "À reconnecter${a.signin?.error?.takeIf { it.isNotBlank() }?.let { " : $it" }.orEmpty()}"
    a.error.isNotBlank() && a.enabled -> a.error
    else -> "${accountSync(a, now).removeSuffix(".")} · ${a.calendars.size} agenda${if (a.calendars.size > 1) "s" else ""}"
}

/** La ligne « Agendas » de la page racine de Paramètres : « 4 comptes · 1 à reconnecter ». */
fun accountsSummary(accounts: List<AgendaAccount>): String {
    val n = accounts.size
    val broken = accounts.count { !it.system && it.enabled && (needsSignin(it) || it.error.isNotBlank()) }
    return "$n compte${if (n > 1) "s" else ""}${if (broken > 0) " · $broken à reconnecter" else ""}"
}

/** Ce que la ligne d'un agenda dit dans la page de son compte. */
fun calendarState(c: AgendaCalendar): String =
    if (c.hidden) "Masqué : Mika ne s'en sert pas" else "Dans l'Agenda · Mika te le rappelle : ${mikaReminderWords(c.reminder)}"

/** Les rappels de son fournisseur, en une ligne (la page d'un agenda). */
fun providerDefaults(c: AgendaCalendar): String = when {
    c.kind == AgendaKinds.SYSTEM -> "Aucun : l'agenda du système n'envoie rien lui-même, Mika te le rappelle."
    c.kind == AgendaKinds.ICAL -> "Ceux de l'abonnement, en lecture seule."
    c.providerReminders.defaults.isEmpty() -> "Aucun par défaut."
    else -> c.providerReminders.defaults.joinToString(", ") { cap(alertWords(it)) }
}

// ── la carte d'accord d'un ajout, dans le chat ──────────────────────────

/** Ce que la carte d'un ajout à l'agenda montre (la maquette validée `agenda-chat.js`) : l'événement qu'elle ajouterait. */
data class AgendaCard(
    val id: Int,
    val calendar: String,
    val color: String,
    val title: String,
    val whenWords: String,
    val place: String,
    /** « la veille au soir » : « Mika te le rappelle » qu'elle poserait ; vide sinon. */
    val remind: String,
)

/** Les cartes d'un ajout, par numéro (celui de la carte d'accord, le même que la proposition) : lues dans ce que Mika
 *  propose ; une autre sorte de proposition n'en a pas. */
fun agendaCards(items: List<Proposal>, calendars: List<AgendaCalendar>, zone: String, now: Long): Map<Int, AgendaCard> {
    val today = localOf(now, zone).day
    val out = LinkedHashMap<Int, AgendaCard>()
    for (p in items) {
        if (p.op != Proposal.ADD) continue
        val o = occOfProposal(p, zone) ?: continue
        val cal = calendars.firstOrNull { it.key == p.calendar }
        out[p.id] = AgendaCard(
            id = p.id,
            calendar = cal?.let(::shownName) ?: "ton agenda",
            color = colorOf(cal),
            title = p.draft?.title?.ifBlank { NO_TITLE } ?: NO_TITLE,
            whenWords = whenWords(o, today),
            place = p.draft?.location.orEmpty(),
            remind = p.remind?.takeIf { it.isNotEmpty() && it != "non" }?.let(::mikaReminderWords).orEmpty(),
        )
    }
    return out
}

/**
 * Le pas 2 d'une connexion Google : ce qu'on y colle (l'adresse de la page où Google a renvoyé le navigateur, dont
 * [example] montre la forme) et s'il faut aussi attendre que le serveur la finisse seul. En retour direct, le
 * navigateur du téléphone n'a pas de session : la page du serveur demande de copier son adresse et de la coller ici,
 * où elle se finit pour ton compte (le serveur ne finit rien sur la seule foi du `state`) ; un navigateur où tu es
 * connectée la finit seul, d'où l'attente.
 */
data class GoogleReturn(val pastes: Boolean, val waits: Boolean, val example: String)

fun googleReturn(direct: Boolean): GoogleReturn =
    if (direct) GoogleReturn(pastes = true, waits = true, example = "https://…/api/moi/agenda/google/retour?state=…")
    else GoogleReturn(pastes = true, waits = false, example = "http://127.0.0.1/?state=…&code=…")

/** La ligne sous les réponses d'une invitation : rien, que la réponse vaut pour toute la série (le choix du lot 6), ou
 *  pourquoi on ne répond pas d'ici (ce que le serveur en dit, `respond_why`). */
enum class AnswerNote { NONE, SERIES, WHY }

fun answerNote(i: AgendaItem): AnswerNote = when {
    i.response.isEmpty() -> AnswerNote.NONE
    !i.can.respond -> if (i.respondWhy.isNotBlank()) AnswerNote.WHY else AnswerNote.NONE
    i.recurring -> AnswerNote.SERIES
    else -> AnswerNote.NONE
}
