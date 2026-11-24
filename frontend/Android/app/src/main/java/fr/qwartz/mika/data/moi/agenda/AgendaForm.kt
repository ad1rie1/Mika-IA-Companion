package fr.qwartz.mika.data.moi.agenda

/*
 * Créer et modifier un événement, pur (porté de `frontendv2/src/screens/agenda/form.ts` et `model.ts`, la forme de la
 * maquette validée `agenda-edition.js`) : les valeurs de départ du formulaire (un événement nouveau, à un créneau
 * touché ; une modification ; une copie ; ce que Mika propose), la répétition (RFC 5545 : chaque jour, semaine, mois,
 * année, « Personnalisée »), les rappels du fournisseur, l'heure dans une liste de demi-heures, et ce qui part : tout
 * pour une création, seulement ce qui a changé pour une modification.
 */

/** Ce que le formulaire ouvre. */
object FormModes {
    const val NEW = "nouveau"
    const val EDIT = "modifier"
    const val COPY = "dupliquer"
    const val PROPOSAL = "proposition"
}

enum class RepeatChoice(val code: String) { NONE(""), DAILY("jour"), WEEKLY("semaine"), MONTHLY("mois"), YEARLY("an"), CUSTOM("perso") }

/** Une répétition « Personnalisée » : tous les [interval] [unit], ses jours (0 : dimanche… 6 : samedi), sa fin. */
data class CustomRule(
    val interval: Int = 1,
    /** `jours`, `semaines`, `mois`, `ans`. */
    val unit: String = "semaines",
    val days: List<Int> = emptyList(),
    /** `jamais`, `le` (une date), `apres` (tant de fois). */
    val ends: String = "jamais",
    val until: String = "",
    val count: Int = 10,
)

private val BYDAY = listOf("SU", "MO", "TU", "WE", "TH", "FR", "SA")

/** La règle RFC 5545 d'un choix du formulaire, au jour [day] ; « Ne se répète pas » : vide. */
fun ruleOf(choice: RepeatChoice, day: String, custom: CustomRule? = null): String = when (choice) {
    RepeatChoice.NONE -> ""
    RepeatChoice.DAILY -> "FREQ=DAILY"
    RepeatChoice.WEEKLY -> "FREQ=WEEKLY;BYDAY=${BYDAY[weekday(day)]}"
    RepeatChoice.MONTHLY -> "FREQ=MONTHLY;BYMONTHDAY=${partsOf(day).d}"
    RepeatChoice.YEARLY -> "FREQ=YEARLY"
    RepeatChoice.CUSTOM -> if (custom == null) "" else {
        val freq = mapOf("jours" to "DAILY", "semaines" to "WEEKLY", "mois" to "MONTHLY", "ans" to "YEARLY")[custom.unit] ?: "WEEKLY"
        val parts = mutableListOf("FREQ=$freq")
        if (custom.interval > 1) parts += "INTERVAL=${minOf(999, custom.interval)}"
        if (custom.unit == "semaines") {
            val days = if (custom.days.isEmpty()) listOf(weekday(day)) else custom.days.distinct().sortedBy { (it + 6) % 7 }
            parts += "BYDAY=${days.joinToString(",") { BYDAY[it] }}"
        }
        if (custom.ends == "le" && isDay(custom.until)) parts += "UNTIL=${custom.until.replace("-", "")}"
        if (custom.ends == "apres" && custom.count > 0) parts += "COUNT=${minOf(9999, custom.count)}"
        parts.joinToString(";")
    }
}

/** Le choix du formulaire qui redit une règle au jour [day] (une autre : « Personnalisée »). */
fun choiceOf(rule: String, day: String): RepeatChoice {
    if (rule.isEmpty()) return RepeatChoice.NONE
    for (c in listOf(RepeatChoice.DAILY, RepeatChoice.WEEKLY, RepeatChoice.MONTHLY, RepeatChoice.YEARLY)) if (ruleOf(c, day) == rule) return c
    return RepeatChoice.CUSTOM
}

private fun parts(rule: String): Map<String, String> =
    rule.split(';').mapNotNull { p -> p.split('=', limit = 2).takeIf { it.size == 2 }?.let { it[0] to it[1] } }.toMap()

/** Une règle lue dans les champs de « Personnalisée ». */
fun customOf(rule: String, day: String): CustomRule {
    val p = parts(rule)
    val unit = mapOf("DAILY" to "jours", "WEEKLY" to "semaines", "MONTHLY" to "mois", "YEARLY" to "ans")[p["FREQ"]] ?: "semaines"
    val days = p["BYDAY"].orEmpty().split(',').map { BYDAY.indexOf(it.replace(Regex("^[+-]?\\d+"), "")) }.filter { it >= 0 }
    val until = p["UNTIL"]?.takeIf { Regex("^\\d{8}").containsMatchIn(it) }?.let { "${it.substring(0, 4)}-${it.substring(4, 6)}-${it.substring(6, 8)}" }.orEmpty()
    return CustomRule(
        interval = p["INTERVAL"]?.toIntOrNull() ?: 1,
        unit = unit,
        days = days.ifEmpty { listOf(weekday(day)) },
        ends = if (until.isNotEmpty()) "le" else if (p["COUNT"] != null) "apres" else "jamais",
        until = until,
        count = p["COUNT"]?.toIntOrNull() ?: 10,
    )
}

/** Une règle en mots : « Chaque lundi », « Chaque année, le 28 novembre », « Toutes les 2 semaines, le lundi et
 *  jeudi », « jusqu'au … », « 5 fois ». */
fun ruleWords(rule: String, day: String, today: String): String {
    if (rule.isEmpty()) return ""
    val c = customOf(rule, day)
    val p = parts(rule)
    fun names(days: List<Int>): String {
        val w = days.map { JOURS[it] }
        return if (w.size == 1) w[0] else "${w.dropLast(1).joinToString(", ")} et ${w.last()}"
    }
    var base = when (c.unit) {
        "jours" -> if (c.interval > 1) "Tous les ${c.interval} jours" else "Chaque jour"
        "semaines" -> if (c.interval > 1) "Toutes les ${c.interval} semaines, le ${names(c.days)}" else "Chaque ${names(c.days)}"
        "mois" -> "${if (c.interval > 1) "Tous les ${c.interval} mois" else "Chaque mois"}, le ${p["BYMONTHDAY"]?.let { if (it == "1") "1er" else it } ?: dayNumber(day)}"
        else -> "${if (c.interval > 1) "Tous les ${c.interval} ans" else "Chaque année"}, le ${dayNumber(day)} ${MOIS[partsOf(day).m - 1]}"
    }
    if (c.ends == "le" && c.until.isNotEmpty()) base += ", jusqu'au ${dayWords(c.until, today)}"
    if (c.ends == "apres" && p["COUNT"] != null) base += ", ${p["COUNT"]} fois"
    return base
}

/** Les choix du formulaire, dits pour le jour [day]. */
fun repeatChoices(day: String): List<Pair<RepeatChoice, String>> = listOf(
    RepeatChoice.NONE to "Ne se répète pas",
    RepeatChoice.DAILY to "Chaque jour",
    RepeatChoice.WEEKLY to "Chaque semaine, le ${JOURS[weekday(day)]}",
    RepeatChoice.MONTHLY to "Chaque mois, le ${dayNumber(day)}",
    RepeatChoice.YEARLY to "Chaque année, le ${dayNumber(day)} ${MOIS[partsOf(day).m - 1]}",
    RepeatChoice.CUSTOM to "Personnalisée…",
)

/** Les fuseaux qu'on choisit d'ici (celui du serveur d'abord). */
val ZONES = listOf("Europe/Paris", "Europe/London", "Europe/Brussels", "Europe/Berlin", "America/New_York", "America/Montreal", "Asia/Tokyo", "UTC")

fun zoneChoices(current: String): List<String> = if (current in ZONES || current.isEmpty()) ZONES else listOf(current) + ZONES

fun zoneLabel(zone: String): String = zone.replace('_', ' ').replaceFirst("/", " · ")

/** Une heure du formulaire : sa minute, ses mots, et pour la fin sa durée (« 1 h 30 »). */
data class HourChoice(val minute: Int, val label: String, val duration: String)

/** Les heures d'une liste de demi-heures : le début, toute la journée ; la fin, après le début, avec sa durée. */
fun hourChoices(end: Boolean, from: Int): List<HourChoice> {
    val out = ArrayList<HourChoice>()
    var m = if (end) from + 30 else 0
    while (m < 1440) {
        out += HourChoice(m, hm(m), if (end) durationShort(m - from) else "")
        m += 30
    }
    return out
}

/** Une personne invitée. */
data class Guest(val name: String, val address: String)

/** Ce que le formulaire tient. Les jours sont `AAAA-MM-JJ`, les heures des minutes depuis minuit. */
data class FormValues(
    val calendar: String = "",
    val title: String = "",
    val d1: String = "",
    val h1: Int = 600,
    val d2: String = "",
    val h2: Int = 660,
    val allDay: Boolean = false,
    val zone: String = "",
    val repeat: RepeatChoice = RepeatChoice.NONE,
    val custom: CustomRule = CustomRule(),
    val location: String = "",
    val conference: String = "",
    /** « Coller un lien… » choisi (le champ du lien se montre). */
    val visio: Boolean = false,
    val description: String = "",
    val invite: List<Guest> = emptyList(),
    val reminders: List<Alert> = emptyList(),
    /** Les rappels du fournisseur ont été touchés (sinon ils ne partent pas : ceux de l'agenda chez lui, ou tels quels). */
    val remindersTouched: Boolean = false,
    /** « Mika te le rappelle » (vide : le choix de l'agenda). */
    val remind: String = "",
    val free: Boolean = false,
    val private: Boolean = false,
)

/**
 * Les valeurs de départ : une occurrence ([o], son événement [item] ou ce que Mika propose [proposal]) ; un événement
 * nouveau ([slot] : un créneau touché dans la grille, sinon le jour [day] de la vue — aujourd'hui, la demi-heure qui
 * vient ; un autre jour, 10:00).
 */
fun initialValues(
    mode: String,
    calendar: String,
    zone: String,
    today: String,
    nowMinute: Int,
    calendars: List<AgendaCalendar>,
    o: Occ? = null,
    day: String = "",
    slotMinute: Int = -1,
): FormValues {
    val item = o?.item
    val draft = o?.proposal?.draft
    val z = (item?.takeIf { !it.allDay }?.zone?.ifBlank { null }) ?: draft?.zone?.ifBlank { null } ?: zone
    var d1: String
    var h1: Int
    var d2: String
    var h2: Int
    var allDay = false
    if (o != null) {
        allDay = o.allDay && (item?.allDay ?: draft?.allDay ?: false)
        if (allDay) {
            d1 = o.day
            d2 = o.last
            h1 = 540
            h2 = 600
        } else {
            val a = localOf(o.startMs, z)
            val b = localOf(o.endMs, z)
            d1 = a.day
            h1 = a.minute
            d2 = b.day
            h2 = b.minute
        }
    } else {
        val start0 = if (slotMinute >= 0) slotMinute else if (day.isEmpty() || day == today) minOf(23 * 60, ((nowMinute + 1 + 29) / 30) * 30) else 600
        d1 = day.ifEmpty { today }
        h1 = start0.coerceIn(0, 1410)
        d2 = if (h1 + 60 >= 1440) addDays(d1, 1) else d1
        h2 = (h1 + 60) % 1440
    }
    val rule = item?.rule?.ifBlank { null } ?: draft?.rule.orEmpty()
    val cal = calendars.firstOrNull { it.key == calendar }
    val invite = item?.participants?.filter { !it.me && it.address.isNotBlank() }?.map { Guest(it.name, it.address) }
        ?: draft?.invite.orEmpty().map { Guest("", it) }
    val copy = mode == FormModes.COPY
    // une copie d'un « Occupé » (le privé d'une autre) ou d'un événement oublié prend le mot qu'il montre, comme le web :
    // un titre vide serait refusé à l'enregistrement
    val title = (if (copy) item?.title?.ifBlank { null } else item?.title) ?: draft?.title ?: o?.title.orEmpty()
    return FormValues(
        calendar = calendar,
        title = if (copy) "$title${if (calendar == item?.calendar) " (copie)" else ""}" else title,
        d1 = d1, h1 = h1, d2 = d2, h2 = h2, allDay = allDay, zone = z,
        repeat = choiceOf(rule, d1),
        custom = customOf(rule.ifEmpty { ruleOf(RepeatChoice.WEEKLY, d1) }, d1),
        location = item?.location ?: draft?.location.orEmpty(),
        conference = item?.conference.orEmpty(),
        visio = !item?.conference.isNullOrBlank(),
        description = item?.description ?: draft?.description.orEmpty(),
        invite = if (copy) emptyList() else invite,
        reminders = item?.reminders ?: cal?.providerReminders?.defaults.orEmpty(),
        remind = if (copy) "" else item?.remind ?: o?.proposal?.remind.orEmpty(),
        free = item?.let { !it.busy } ?: false,
        private = item?.private ?: false,
    )
}

/** La date de début changée : la fin suit (la même durée en jours). */
fun withStartDay(v: FormValues, day: String): FormValues {
    val shift = daysFrom(v.d1, day)
    return v.copy(d1 = day, d2 = addDays(v.d2.ifEmpty { v.d1 }, shift))
}

/** L'heure de début changée : la fin suit (la même durée, une demi-heure au moins), le jour de la fin aussi — un
 *  rendez-vous qui passe minuit ou dure plusieurs jours garde sa longueur. */
fun withStartMinute(v: FormValues, minute: Int): FormValues {
    val dur = maxOf(30, daysFrom(v.d1, v.d2.ifEmpty { v.d1 }) * 1440 + v.h2 - v.h1)
    val end = minute + dur
    return v.copy(h1 = minute, h2 = end % 1440, d2 = addDays(v.d1, end / 1440))
}

/** Ce qui part : tout pour une création ; pour une modification, ce qui a changé depuis le départ ([start]).
 *  [owner] : « Mika te le rappelle » est à son propriétaire. */
fun fieldsOf(mode: String, v: FormValues, start: FormValues, owner: Boolean): EventFields {
    val all = allFields(v, owner)
    if (mode != FormModes.EDIT) return all
    val before = allFields(start, owner)
    val whenChanged = all.start != before.start || all.end != before.end || all.allDay != before.allDay || all.zone != before.zone
    return EventFields(
        title = all.title.takeIf { it != before.title },
        start = all.start.takeIf { whenChanged },
        end = all.end.takeIf { whenChanged },
        allDay = all.allDay.takeIf { whenChanged },
        zone = if (whenChanged && !v.allDay) v.zone else null,
        location = all.location.takeIf { it != before.location },
        description = all.description.takeIf { it != before.description },
        conference = all.conference.takeIf { it != before.conference },
        rule = all.rule.takeIf { it != before.rule },
        invite = all.invite.takeIf { it != before.invite },
        free = all.free.takeIf { it != before.free },
        private = all.private.takeIf { it != before.private },
        remind = if (owner && all.remind != before.remind) all.remind else null,
        reminders = if (v.remindersTouched) v.reminders else null,
    )
}

private fun allFields(v: FormValues, owner: Boolean): EventFields {
    val rule = ruleOf(v.repeat, v.d1, v.custom)
    return EventFields(
        title = v.title.trim(),
        start = if (v.allDay) v.d1 else "${v.d1}T${hm(v.h1)}",
        end = if (v.allDay) (if (v.d2 < v.d1) v.d1 else v.d2) else "${v.d2}T${hm(v.h2)}",
        allDay = v.allDay,
        zone = if (v.allDay) null else v.zone,
        location = v.location.trim(),
        description = v.description,
        conference = if (v.visio) v.conference.trim() else "",
        rule = rule,
        invite = v.invite.map { it.address },
        free = v.free,
        private = v.private,
        remind = if (owner) v.remind else null,
        reminders = if (v.remindersTouched) v.reminders else null,
    )
}

/**
 * Les rappels du fournisseur qu'un agenda sait porter — ce que l'écran montre, et rien d'autre ne part : aucun là où il
 * n'en écrit pas (l'agenda du système, dont Mika se charge ; un abonnement), une notification là où il n'envoie pas
 * d'e-mail, [ProviderReminders.max] au plus, les plus tôt d'abord (ce que le serveur garderait d'une liste plus longue).
 */
fun fitAlerts(alerts: List<Alert>, can: ProviderReminders): List<Alert> {
    if (can.max <= 0) return emptyList()
    val adapted = alerts.map { if (it.method == Alert.EMAIL && !can.email) it.copy(method = Alert.NOTIFICATION) else it }.distinct()
    return if (adapted.size <= can.max) adapted else adapted.sortedByDescending { it.minutes }.take(can.max)
}

/** Ce qu'on ne peut pas enregistrer tel quel : la fin avant le début. */
fun formProblem(v: FormValues): String? = when {
    v.d2 < v.d1 -> "La fin est avant le début."
    !v.allDay && v.d2 == v.d1 && v.h2 <= v.h1 -> "La fin est avant le début."
    else -> null
}

/** Le pied du formulaire : où il part. */
fun formFoot(cal: AgendaCalendar?): String = if (cal == null) "" else "Enregistré dans « ${cal.name} », il part tout de suite ${whereWords(cal.kind)}."

/** Les portées d'une écriture sur une série : cet événement, celui-ci et les suivants, tous. */
val SCOPES = listOf("un" to "Cet événement", "suivants" to "Celui-ci et les suivants", "tous" to "Tous les événements")
