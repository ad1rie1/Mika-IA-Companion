package fr.qwartz.mika.data.net

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * Les trames du serveur, telles que `adapters/web/protocol.py` les écrit et que
 * `frontend/Web/src/types/messages.ts` les lit. Chaque champ a un défaut : une trame à laquelle il
 * manque une clé reste lisible, et `FrameCodec` ne lève jamais.
 */
sealed interface ServerFrame {

    @Serializable
    data class Speech(
        val text: String = "",
        val emotion: String = "",
        @SerialName("emotion_intensity") val emotionIntensity: Double = 0.0,
        @SerialName("emotion_blend") val emotionBlend: List<BlendPart> = emptyList(),
        /** `reply` | `conscience` | `error` */
        val source: String = "",
        @SerialName("person_id") val personId: String? = null,
        val speak: Boolean = false,
        @SerialName("voice_reason") val voiceReason: String = "",
        /** `speaking` | `inner` — une pensée à voix haute n'est pas dans le fil. */
        @SerialName("voice_persona") val voicePersona: String = MikaProtocol.PERSONA_SPEAKING,
        @SerialName("message_id") val messageId: Long? = null,
        @SerialName("user_message_id") val userMessageId: Long? = null,
        @SerialName("client_msg_id") val clientMsgId: String? = null,
        /** Les fichiers que Mika envoie (ADR 0062). */
        val attachments: List<AttachmentRef> = emptyList(),
    ) : ServerFrame {
        val isInner: Boolean get() = voicePersona == MikaProtocol.PERSONA_INNER
    }

    /** Un morceau du fil : `initial` à la connexion, `catchup` en réponse à un `sync`. */
    data class History(
        val mode: String = MikaProtocol.MODE_CATCHUP,
        /** `null` quand la trame n'en portait pas : une trame malformée ne fait pas tomber le fil. */
        val messages: List<HistoryEntry>? = emptyList(),
        val lastId: Long = 0,
        val truncated: Boolean = false,
        /** L'empreinte de sa vie : un fil gardé sous une autre empreinte est vidé avant de fusionner. */
        val life: String? = null,
        /** Le curseur dépassait la tête du fil : ce fil remplace ce que l'écran montre. */
        val reset: Boolean = false,
    ) : ServerFrame {
        val isInitial: Boolean get() = mode == MikaProtocol.MODE_INITIAL
    }

    @Serializable
    data class Ack(
        @SerialName("client_msg_id") val clientMsgId: String = "",
        val status: String = "",
        @SerialName("rejected_attachments") val rejectedAttachments: List<RejectedAttachment> = emptyList(),
        /** Avec `no_reply` : pourquoi, en un mot. */
        val reason: String? = null,
        /** Avec `no_reply`, aux seules connexions opératrices : la cause en clair. */
        val detail: String? = null,
        /** Avec `no_reply`, aux seules opératrices : une page de la console. */
        val href: String? = null,
    ) : ServerFrame

    @Serializable
    data class EmotionUpdate(
        @SerialName("person_id") val personId: String? = null,
        val emotion: String = "",
        @SerialName("emotion_intensity") val emotionIntensity: Double = 0.0,
        @SerialName("emotion_blend") val emotionBlend: List<BlendPart> = emptyList(),
    ) : ServerFrame

    data class InnerStateUpdate(val state: InnerState) : ServerFrame

    data class Pong(val t: Double? = null) : ServerFrame

    /** Un type que cette version ne connaît pas, ou une trame illisible : ignorée, jamais fatale. */
    data class Unknown(val type: String) : ServerFrame
}

@Serializable
data class BlendPart(val emotion: String = "", val weight: Double = 0.0)

/**
 * Une pièce jointe. Côté personne (`history` `user`) : un nom et une sorte. Côté Mika (`speech`,
 * `history` `assistant`) : de quoi la télécharger (`url` relative au serveur).
 */
@Serializable
data class AttachmentRef(
    val id: String? = null,
    val name: String = "",
    /** `image` | `audio` | `file` */
    val kind: String = "file",
    val mime: String? = null,
    val size: Long? = null,
    val url: String? = null,
    val available: Boolean? = null,
)

@Serializable
data class RejectedAttachment(
    val name: String = "",
    /** `too_large` | `too_many` | `invalid` */
    val reason: String = "",
)

@Serializable
data class HistoryEntry(
    val id: Long? = null,
    val role: String = "",
    /** Ce qui a été tapé ; les fichiers sont à part, par leur nom. */
    val text: String = "",
    /** Époque en millisecondes d'après le serveur, normalisée quand même (`Timestamps`). */
    val ts: Double? = null,
    val source: String? = null,
    val emotion: String? = null,
    @SerialName("emotion_intensity") val emotionIntensity: Double? = null,
    val attachments: List<AttachmentRef> = emptyList(),
)

// ── L'état intérieur (`inner_state`), lu section par section ─────────────────────────────

/**
 * Une section absente vaut `null`. Une section malformée vaut aussi `null`, mais son nom est noté
 * dans [malformed] : le réducteur la garde telle qu'elle était au lieu de l'effacer.
 */
data class InnerState(
    val sleepPhase: String? = null,
    val energy: Double? = null,
    val place: String? = null,
    val circadian: Circadian? = null,
    val drives: Map<String, Drive>? = null,
    val estime: Double? = null,
    val personScope: Boolean? = null,
    val ruminations: List<Rumination>? = null,
    val todayJournal: Journal? = null,
    val lastDream: Dream? = null,
    val selfNarrative: SelfNarrative? = null,
    val projects: List<ProjectSummary>? = null,
    val identity: IdentityView? = null,
    val personProfile: PersonProfile? = null,
    val pendingCommitments: List<String>? = null,
    val malformed: Set<String> = emptySet(),
)

@Serializable
data class Circadian(
    /** `morning` | `afternoon` | `evening` | `night` */
    val phase: String = "",
    val hour: Double = 0.0,
    val energy: Double = 0.0,
    @SerialName("bias_emotion") val biasEmotion: String = "",
)

@Serializable
data class Drive(
    val tension: Double = 0.0,
    @SerialName("last_satisfied") val lastSatisfied: Double = 0.0,
)

@Serializable
data class Rumination(val summary: String = "", val intensity: Double = 0.0, val emotion: String = "")

/** Son dernier journal écrit — celui d'une journée passée, malgré le nom historique de la clé. */
@Serializable
data class Journal(
    val date: String = "",
    val title: String? = null,
    val narrative: String = "",
    @SerialName("dominant_emotion") val dominantEmotion: String = "",
    @SerialName("persons_interacted") val personsInteracted: List<String> = emptyList(),
)

@Serializable
data class Dream(
    val content: String = "",
    @SerialName("dream_type") val dreamType: String = "",
    val vividness: Double = 0.0,
    val emotion: String = "",
    @SerialName("night_of") val nightOf: String = "",
    val recalled: Boolean = false,
)

@Serializable
data class SelfNarrative(val content: String = "")

/** Un projet, pour une propriétaire seulement (`app/mindport.py::_work`). */
@Serializable
data class ProjectSummary(
    val id: Long = 0,
    val title: String = "",
    val status: String = "",
    val priority: String = "",
    val origin: String = "",
    /** Son mode en mots (« impersonnel ») ; vide pour son mode à elle. */
    @SerialName("mode_label") val modeLabel: String = "",
    @SerialName("schedule_rule") val scheduleRule: String = "",
    /** Son agenda en mots (« les jours ouvrés à 9 h ») ; vide = « dès que possible ». */
    @SerialName("schedule_label") val scheduleLabel: String = "",
    @SerialName("next_run_at") val nextRunAt: String? = null,
    @SerialName("tasks_total") val tasksTotal: Int = 0,
    @SerialName("tasks_done") val tasksDone: Int = 0,
    @SerialName("tasks_blocked") val tasksBlocked: Int = 0,
)

@Serializable
data class PendingClaim(
    val id: Long = 0,
    val name: String = "",
    val kind: String = "",
    val evidence: String = "",
    @SerialName("created_at") val createdAt: String = "",
)

/** Qui Mika pense avoir en face, et à quel point elle en est sûre. */
@Serializable
data class IdentityView(
    @SerialName("known_as") val knownAs: String = "",
    val certainty: Double = 0.0,
    val level: String = "",
    /** `authenticated` | `account` | `public` | `internal` */
    val trust: String = "",
    @SerialName("pending_claims") val pendingClaims: List<PendingClaim> = emptyList(),
)

@Serializable
data class PersonProfile(
    val name: String = "",
    val summary: String = "",
    val closeness: String = "",
    @SerialName("preferred_tone") val preferredTone: String = "",
    @SerialName("topics_of_interest") val topicsOfInterest: List<String> = emptyList(),
    @SerialName("sensitive_topics") val sensitiveTopics: List<String> = emptyList(),
    @SerialName("interaction_count") val interactionCount: Int = 0,
)
