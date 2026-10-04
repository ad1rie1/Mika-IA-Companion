package fr.qwartz.mika.ui.mind

import fr.qwartz.mika.data.mind.MindLabels
import fr.qwartz.mika.data.mind.MindState
import fr.qwartz.mika.data.mind.SleepPhases
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale
import kotlin.math.roundToInt

/** Une carte de l'écran « Ce qu'elle fait », déjà mise en mots : l'écran ne fait que dessiner. */
sealed interface MindCard {
    /** Son humeur : l'émotion dominante et, quand elle pèse assez, celle qui s'y mêle (« mais aussi »). */
    data class Mood(
        val primary: String,
        val primaryPct: Int,
        val secondary: String? = null,
        val secondaryPct: Int? = null,
    ) : MindCard

    /** Son corps : sommeil, énergie, où elle est dans sa chambre, le moment de sa journée. */
    data class Body(
        val sleep: String,
        val asleep: Boolean,
        val energyPct: Int?,
        val place: String?,
        val moment: String?,
    ) : MindCard

    data class Esteem(val pct: Int) : MindCard

    /** « Elle repense à… » */
    data class Thoughts(val items: List<Thought>) : MindCard
    data class Thought(val text: String, val pct: Int, val emotion: String?)

    data class Dream(
        val type: String,
        val emotion: String?,
        val vividnessPct: Int,
        val recalled: Boolean,
        val text: String,
        /** Un rêve pâle s'écrit pâle (InnerLifePanel.ts : 0,4 + 0,6 × netteté). */
        val alpha: Float,
    ) : MindCard

    data class Journal(val title: String, val text: String, val emotion: String?, val persons: List<String>) : MindCard

    /** « Qui elle est devenue » : son récit d'elle-même. */
    data class Narrative(val text: String) : MindCard

    /** Ses besoins (Compagnie, S'exprimer, Apprendre), en tension de 0 à 100. */
    data class Needs(val items: List<Need>) : MindCard
    data class Need(val label: String, val pct: Int)

    /** Ses projets — le serveur ne les envoie qu'à une propriétaire. Jamais les actions en attente d'accord. */
    data class Projects(val items: List<Project>) : MindCard
    data class Project(
        val title: String,
        val mode: String?,
        val done: Int,
        val total: Int,
        val blocked: Int,
        val schedule: String,
        val nextRun: String?,
    )
}

/**
 * Choisir et mettre en mots les cartes de « Ce qu'elle fait » — d'après `InnerLifePanel.ts`. Pur : le
 * fuseau est passé, l'état aussi. Une carte sans données n'existe pas (on ne montre pas « — »).
 */
object MindCards {
    /** « mais aussi » : la seconde émotion n'est dite que si elle pèse au moins 40 % de la première. */
    const val SECONDARY_MIN_RATIO = 0.4

    private val NEXT_RUN = DateTimeFormatter.ofPattern("dd/MM HH:mm", Locale.FRENCH)

    fun build(state: MindState?, zone: ZoneId): List<MindCard> {
        if (state == null) return emptyList()
        val out = mutableListOf<MindCard>()
        mood(state)?.let(out::add)
        body(state)?.let(out::add)
        state.estime?.let { out += MindCard.Esteem(pct(it)) }
        val thoughts = state.ruminations.filter { it.summary.isNotBlank() }.map {
            MindCard.Thought(it.summary.trim(), pct(it.intensity), it.emotion.takeIf(String::isNotBlank)?.let(MindLabels::emotion))
        }
        if (thoughts.isNotEmpty()) out += MindCard.Thoughts(thoughts)
        state.dream?.takeIf { it.content.isNotBlank() }?.let { d ->
            val vividness = d.vividness.coerceIn(0.0, 1.0)
            out += MindCard.Dream(
                type = MindLabels.dreamType(d.dreamType).ifBlank { "rêve" },
                emotion = d.emotion.takeIf(String::isNotBlank)?.let(MindLabels::emotion),
                vividnessPct = pct(vividness),
                recalled = d.recalled,
                text = d.content.trim(),
                alpha = (0.4 + 0.6 * vividness).toFloat(),
            )
        }
        state.journal?.takeIf { it.narrative.isNotBlank() }?.let { j ->
            out += MindCard.Journal(
                title = MindLabels.journalTitle(j.title),
                text = j.narrative.trim(),
                emotion = j.dominantEmotion.takeIf(String::isNotBlank)?.let(MindLabels::emotion),
                persons = j.personsInteracted.filter(String::isNotBlank),
            )
        }
        state.selfNarrative?.takeIf { it.isNotBlank() }?.let { out += MindCard.Narrative(it.trim()) }
        needs(state)?.let(out::add)
        if (state.projects.isNotEmpty()) {
            out += MindCard.Projects(
                state.projects.map { p ->
                    MindCard.Project(
                        title = p.title.ifBlank { "Projet ${p.id}" },
                        mode = p.modeLabel.takeIf(String::isNotBlank),
                        done = p.tasksDone,
                        total = p.tasksTotal,
                        blocked = p.tasksBlocked,
                        schedule = p.scheduleLabel.ifBlank { "dès que possible" },
                        nextRun = formatNextRun(p.nextRunAt, zone),
                    )
                },
            )
        }
        return out
    }

    private fun mood(state: MindState): MindCard.Mood? {
        val mood = state.mood ?: return null
        val blend = mood.blend.filter { it.emotion.isNotBlank() }.sortedByDescending { it.weight }
        if (blend.isEmpty()) return MindCard.Mood(MindLabels.emotion(mood.emotion), pct(mood.intensity))
        val primary = blend[0]
        val secondary = blend.getOrNull(1)?.takeIf { it.weight >= primary.weight * SECONDARY_MIN_RATIO }
        return MindCard.Mood(
            primary = MindLabels.emotion(primary.emotion),
            primaryPct = pct(primary.weight),
            secondary = secondary?.let { MindLabels.emotion(it.emotion) },
            secondaryPct = secondary?.let { pct(it.weight) },
        )
    }

    /**
     * Le corps n'est montré que si on en sait quelque chose : une humeur seule (venue d'une parole) ne
     * dit pas qu'elle est éveillée, la phase « awake » n'étant alors qu'une valeur par défaut.
     */
    private fun body(state: MindState): MindCard.Body? {
        val energy = state.energy ?: state.circadian?.energy
        val place = MindLabels.place(state.place)
        val moment = state.circadian?.let { MindLabels.momentOfDay(it.phase, it.hour) }
        if (energy == null && place == null && moment == null && !state.asleep) return null
        return MindCard.Body(
            sleep = MindLabels.sleepPhase(state.sleepPhase),
            asleep = state.sleepPhase != SleepPhases.AWAKE,
            energyPct = energy?.let(::pct),
            place = place,
            moment = moment,
        )
    }

    private fun needs(state: MindState): MindCard.Needs? {
        if (state.drives.isEmpty()) return null
        val known = MindLabels.DRIVES.keys.filter { it in state.drives }
        val others = state.drives.keys.filter { it !in MindLabels.DRIVES }.sorted()
        return MindCard.Needs((known + others).map { MindCard.Need(MindLabels.drive(it), pct(state.drives.getValue(it).tension)) })
    }

    /** `next_run_at` arrive en ISO (avec ou sans décalage) ; illisible → rien plutôt qu'une date fausse. */
    fun formatNextRun(raw: String?, zone: ZoneId): String? {
        val value = raw?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        val instant = try {
            OffsetDateTime.parse(value).toInstant()
        } catch (_: DateTimeParseException) {
            try {
                Instant.parse(value)
            } catch (_: DateTimeParseException) {
                try {
                    LocalDateTime.parse(value).atZone(zone).toInstant()
                } catch (_: DateTimeParseException) {
                    return null
                }
            }
        }
        return NEXT_RUN.format(instant.atZone(zone))
    }

    /** « Mis à jour à l'instant », « … il y a 3 min », « … il y a 2 h », « … il y a 4 j ». */
    fun updatedAgo(updatedAtMs: Long, nowMs: Long): String? {
        if (updatedAtMs <= 0) return null
        val seconds = ((nowMs - updatedAtMs) / 1000).coerceAtLeast(0)
        return when {
            seconds < 60 -> "Mis à jour à l'instant"
            seconds < 3600 -> "Mis à jour il y a ${seconds / 60} min"
            seconds < 86_400 -> "Mis à jour il y a ${seconds / 3600} h"
            else -> "Mis à jour il y a ${seconds / 86_400} j"
        }
    }

    private fun pct(value: Double): Int = (value.coerceIn(0.0, 1.0) * 100).roundToInt()
}
