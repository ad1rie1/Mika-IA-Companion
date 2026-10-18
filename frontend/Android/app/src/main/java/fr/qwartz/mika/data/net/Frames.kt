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
        /** `pro` : une réponse de travail (ADR 0116) — une seule bulle, du Markdown, jamais lue à voix haute. */
        val mode: String = "",
    ) : ServerFrame {
        val isInner: Boolean get() = voicePersona == MikaProtocol.PERSONA_INNER
        val isPro: Boolean get() = mode == MikaProtocol.CHAT_MODE_PRO
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

    /**
     * Les cartes d'accord de la personne (ADR 0064) : la liste entière, qui remplace la précédente —
     * une carte absente n'attend plus rien. Les cartes illisibles sont écartées une à une.
     */
    data class Approvals(val items: List<ApprovalCard>) : ServerFrame

    /** Le sort d'une décision (`approved`, `rejected`, `unknown`…) ; une liste `approvals` à jour suit. */
    data class ApprovalResult(val id: Long, val status: String) : ServerFrame

    /**
     * Le sort d'un avis sur une de ses réponses (ADR 0113) : `ok`, `invalid`, `forbidden`, `failed`.
     * [verdict] vide : l'avis retiré.
     */
    data class VerdictResult(val messageId: Long, val verdict: String, val comment: String, val status: String) :
        ServerFrame

    /**
     * Un de ses outils en direct, pendant une réponse pro (ADR 0116) — aux connexions d'opératrice seulement,
     * jamais dans l'historique ni en base : l'app la garde en mémoire. Lue à la main par `FrameCodec` : une trame
     * sans phase connue est inconnue ; les textes trop longs sont coupés.
     *
     * [phase] : `start` ([callId], [name], [args]) ; `end` (les mêmes, [ok], [result], [durationMs]) ; `note`
     * ([text], ce qu'elle écrit entre deux outils) ; `done` ([outcome] : `done`, `failed`, `timeout`…).
     * [replyTo] : le message de la personne auquel elle répond (le `user_message_id` de la `speech` qui suivra).
     */
    data class Tool(
        val episode: String,
        val replyTo: Long?,
        val phase: String,
        val callId: String = "",
        val name: String = "",
        /** Les arguments en JSON (texte), à montrer tels quels, jamais interprétés. */
        val args: String = "",
        val ok: Boolean? = null,
        /** Ce que l'outil a rendu, en texte brut. */
        val result: String = "",
        val durationMs: Long? = null,
        val text: String = "",
        val outcome: String = "",
        /** Millisecondes Unix ; `null` si la trame n'en portait pas de lisible. */
        val at: Long? = null,
    ) : ServerFrame

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

/**
 * Une carte d'accord : un appel que Mika veut faire à un service extérieur et qui attend l'accord de
 * la personne. Lue à la main par `FrameCodec` (pas de défauts : une carte à laquelle il manque l'essentiel
 * est écartée, jamais complétée).
 */
data class ApprovalCard(
    val id: Long,
    val title: String,
    /** Exactement ce qui partira : montré tel quel, en texte brut, jamais interprété. */
    val text: String,
    /** L'empreinte de [text] : renvoyée avec la décision, le serveur refuse un accord sur autre chose. */
    val digest: String,
    /** Non vide : ça ne peut pas partir tel quel, seul le refus est possible. */
    val blocked: String = "",
    /** Époque en millisecondes ; `null` : pas d'échéance. */
    val expiresAt: Long? = null,
    /** Faux quand [text] a été coupé à la lecture : on n'accepte pas ce qu'on n'a pas lu en entier. */
    val complete: Boolean = true,
)

/** Ce que la personne décide d'une carte, tel que la trame `approval` l'écrit. */
enum class ApprovalDecision(val wire: String) {
    ACCEPT(MikaProtocol.DECISION_ACCEPT),
    REFUSE(MikaProtocol.DECISION_REFUSE),
}

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
    /** L'avis de l'opératrice sur cette réponse (ADR 0113), pour une connexion d'opératrice seulement. */
    val verdict: String? = null,
    @SerialName("verdict_note") val verdictNote: String? = null,
    /** `pro` : une ligne écrite en mode pro (ADR 0116) ; absent sinon. */
    val mode: String? = null,
    /**
     * Une ligne d'elle en mode pro : les outils dont elle s'est servie, dans l'ordre des appels (`null` : la
     * ligne n'en dit rien). Lus à part par `FrameCodec` : une liste cassée n'emporte pas le message.
     */
    val tools: List<ToolUse>? = null,
)

/** Un outil dont elle s'est servie pour une réponse pro (ADR 0116) : son nom, et s'il a réussi. */
@Serializable
data class ToolUse(val name: String, val ok: Boolean)

// ── L'état intérieur (`inner_state`), lu section par section ─────────────────────────────

/**
 * Une section absente vaut `null`. Une section malformée vaut aussi `null`, mais son nom est noté
 * dans [malformed] : le réducteur la garde telle qu'elle était au lieu de l'effacer.
 */
data class InnerState(
    val sleepPhase: String? = null,
    val energy: Double? = null,
    val place: String? = null,
    val activity: Doing? = null,
    /** La clé `activity` est dans la trame : `null` y dit qu'elle ne fait rien (absente : un serveur plus ancien). */
    val hasActivity: Boolean = false,
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

/**
 * Ce qu'elle fait dans sa chambre (`adapters/web/protocol.py::activity`, le fait `world.doing`) : le nom, le
 * libellé tel qu'elle le dit (« regarder dehors »), son début et sa fin prévue en millisecondes (`until` nul :
 * jusqu'à ce qu'elle s'arrête ; une occupation minutée finit sans trame du serveur).
 */
@Serializable
data class Doing(
    val name: String = "",
    val label: String = "",
    val since: Long = 0,
    val until: Long? = null,
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
