package fr.qwartz.mika.data.mind

import fr.qwartz.mika.data.net.BlendPart
import fr.qwartz.mika.data.net.Circadian
import fr.qwartz.mika.data.net.Drive
import fr.qwartz.mika.data.net.Dream
import fr.qwartz.mika.data.net.FrameCodec
import fr.qwartz.mika.data.net.IdentityView
import fr.qwartz.mika.data.net.InnerState
import fr.qwartz.mika.data.net.Journal
import fr.qwartz.mika.data.net.PersonProfile
import fr.qwartz.mika.data.net.ProjectSummary
import fr.qwartz.mika.data.net.Rumination
import kotlinx.serialization.Serializable

/** Son humeur du moment : l'émotion dominante, son intensité, et ce qui s'y mêle. */
@Serializable
data class Mood(
    val emotion: String = "neutral",
    val intensity: Double = 0.0,
    val blend: List<BlendPart> = emptyList(),
)

/**
 * Ce que l'app sait de ce qu'elle fait, assemblé trame après trame (`inner_state_update`,
 * `emotion_update`, l'émotion des `speech`). Gardé en base (`kv`, clé `mind_state`) pour qu'une
 * réouverture hors ligne montre la dernière chose connue, datée par [updatedAtMs].
 */
@Serializable
data class MindState(
    val sleepPhase: String = SleepPhases.AWAKE,
    val energy: Double? = null,
    val place: String? = null,
    val circadian: Circadian? = null,
    val drives: Map<String, Drive> = emptyMap(),
    val estime: Double? = null,
    val ruminations: List<Rumination> = emptyList(),
    val journal: Journal? = null,
    val dream: Dream? = null,
    val selfNarrative: String? = null,
    val projects: List<ProjectSummary> = emptyList(),
    val identity: IdentityView? = null,
    val personProfile: PersonProfile? = null,
    val pendingCommitments: List<String> = emptyList(),
    val mood: Mood? = null,
    val updatedAtMs: Long = 0,
) {
    val asleep: Boolean get() = sleepPhase != SleepPhases.AWAKE
}

/** Les phases de sommeil que le serveur envoie (`contracts/body.py`). */
object SleepPhases {
    const val AWAKE = "awake"
    const val LIGHT = "light_sleep"
    const val REM = "rem"
    const val DEEP = "deep_sleep"
    val ALL = setOf(AWAKE, LIGHT, REM, DEEP)

    /** Une phase inconnue se lit « éveillée » : du JSON venu du réseau n'est jamais cru sur parole. */
    fun resolve(value: String?): String = if (value != null && value in ALL) value else AWAKE
}

/**
 * Plier une trame `inner_state` dans l'état connu (InnerLifePanel.ts:261-283).
 *
 * Les clés de base (sommeil, énergie, lieu, rythme, besoins, estime) remplacent quand elles sont
 * présentes. Les sections du panneau (pensées, journal, rêve, récit, projets, identité, fiche) :
 * quand `person_scope` vaut `false`, la trame ne parle de personne et ne dit rien d'elles — elles
 * restent telles quelles ; sinon elles sont remplacées, et une section absente est effacée. Une
 * section malformée garde toujours sa valeur précédente.
 */
object InnerStateReducer {

    fun apply(prev: MindState, s: InnerState, nowMs: Long): MindState {
        val bad = s.malformed
        fun <T> base(key: String, value: T?, old: T): T = if (key in bad || value == null) old else value

        var next = prev.copy(
            sleepPhase = if (FrameCodec.K_SLEEP_PHASE in bad || s.sleepPhase == null) {
                prev.sleepPhase
            } else {
                SleepPhases.resolve(s.sleepPhase)
            },
            energy = base(FrameCodec.K_ENERGY, s.energy, prev.energy),
            place = base(FrameCodec.K_PLACE, s.place, prev.place),
            circadian = base(FrameCodec.K_CIRCADIAN, s.circadian, prev.circadian),
            drives = base(FrameCodec.K_DRIVES, s.drives, prev.drives),
            estime = base(FrameCodec.K_ESTIME, s.estime, prev.estime),
            updatedAtMs = nowMs,
        )
        if (s.personScope == false) return next

        fun <T> panel(key: String, value: T, old: T): T = if (key in bad) old else value
        next = next.copy(
            ruminations = panel(FrameCodec.K_RUMINATIONS, s.ruminations.orEmpty(), prev.ruminations),
            journal = panel(FrameCodec.K_JOURNAL, s.todayJournal?.takeIf { it.narrative.isNotBlank() }, prev.journal),
            dream = panel(FrameCodec.K_DREAM, s.lastDream?.takeIf { it.content.isNotBlank() }, prev.dream),
            selfNarrative = panel(
                FrameCodec.K_NARRATIVE,
                s.selfNarrative?.content?.takeIf { it.isNotBlank() },
                prev.selfNarrative,
            ),
            projects = panel(FrameCodec.K_PROJECTS, s.projects.orEmpty(), prev.projects),
            identity = panel(FrameCodec.K_IDENTITY, s.identity, prev.identity),
            personProfile = panel(FrameCodec.K_PROFILE, s.personProfile, prev.personProfile),
            pendingCommitments = panel(FrameCodec.K_COMMITMENTS, s.pendingCommitments.orEmpty(), prev.pendingCommitments),
        )
        return next
    }

    /** L'humeur d'un `emotion_update` ou d'une parole : une émotion vide ne dit rien, l'humeur reste. */
    fun applyMood(prev: MindState, emotion: String, intensity: Double, blend: List<BlendPart>, nowMs: Long): MindState {
        if (emotion.isBlank()) return prev
        return prev.copy(mood = Mood(emotion, intensity.coerceIn(0.0, 1.0), blend), updatedAtMs = nowMs)
    }
}
