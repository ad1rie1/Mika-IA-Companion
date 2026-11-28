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
        /**
         * Ce qu'elle a fait en l'écrivant, à montrer en petites bulles (ADR 0119 : elle a regardé où tu es) ; `null` :
         * rien. Lues à part par `FrameCodec` : une liste cassée n'emporte pas la parole.
         */
        val notes: List<MessageNote>? = null,
        /** Le fil de travail où elle répond (ADR 0164) ; `null` : le fil avec elle. Validé par `FrameCodec`. */
        val strand: String? = null,
    ) : ServerFrame {
        val isInner: Boolean get() = voicePersona == MikaProtocol.PERSONA_INNER
        val isPro: Boolean get() = mode == MikaProtocol.CHAT_MODE_PRO
    }

    /**
     * Un morceau du fil : `initial` à la connexion, `catchup` en réponse à un `sync` ; `strand` en réponse à un
     * `strand_history` (ADR 0164), avec [strand] et [more] (il en reste de plus anciens).
     */
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
        val strand: String? = null,
        val more: Boolean = false,
    ) : ServerFrame {
        val isInitial: Boolean get() = mode == MikaProtocol.MODE_INITIAL
        val isStrand: Boolean get() = mode == MikaProtocol.MODE_STRAND
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
        /** Le fil de travail où elle répond (ADR 0164) ; `null` : le fil avec elle. */
        val strand: String? = null,
    ) : ServerFrame

    /**
     * Ses fils de travail (ADR 0164) : la liste entière, du plus récemment actif au plus ancien, archivés compris —
     * elle remplace la précédente. Une entrée sans identifiant valide est écartée seule.
     */
    data class Strands(val items: List<StrandInfo>) : ServerFrame

    /** Le sort d'un réglage de fil : `ok`, `invalid`, `forbidden`, `failed` ; une liste `strands` suit s'il a pris. */
    data class StrandResult(val id: String, val status: String) : ServerFrame

    /**
     * Ce qui a changé dans ce que montrent les routes de `/api/moi` (ADR 0308, `protocole-moi.md` § 2 bis) : pour
     * chaque sujet connu ([Topics]), ce qu'il nomme — des boîtes, des mails, des conversations, des projets —, ou
     * `null` : tout le domaine. Jamais le contenu : l'écran relit la route qu'il montre (`data/moi/Live`). Lue à la
     * main par `FrameCodec` : un sujet inconnu se tait ; une clé inconnue, une liste vide ou illisible valent « tout
     * le domaine » ; deux entrées d'un même sujet se réunissent.
     */
    data class Changed(val changes: Map<String, Set<String>?>) : ServerFrame

    /** Un type que cette version ne connaît pas, ou une trame illisible : ignorée, jamais fatale. */
    data class Unknown(val type: String) : ServerFrame
}

/**
 * Les sujets de la trame `changed` (ADR 0308), dans l'ordre du contrat — `backendv2/src/mika/ports/changes.py`
 * (`TOPICS`, `KEYS`), `docs/protocole-moi.md` § 2 bis : chacun dit quelle route se relit, et sa clé ce qui y a changé.
 */
object Topics {
    const val ME = "me"
    const val MAIL = "mail"
    const val MAIL_DRAFTS = "mail.drafts"
    const val MAIL_WORK = "mail.work"
    const val TEAMS = "teams"
    const val TEAMS_REPLIES = "teams.replies"
    const val TEAMS_WORK = "teams.work"
    const val PHONE = "phone"
    const val PHONE_POSITION = "phone.position"
    const val PHONE_PHONES = "phone.phones"
    const val CONTACTS = "contacts"
    /** L'agenda (ADR 0309) : ses comptes, ses agendas, leurs événements, ses invitations, ce que Mika propose. */
    const val AGENDA = "agenda"
    const val PROJECTS = "projects"
    const val TRIPS = "trips"
    const val SETTINGS = "settings"

    val ALL: List<String> = listOf(
        ME, MAIL, MAIL_DRAFTS, MAIL_WORK, TEAMS, TEAMS_REPLIES, TEAMS_WORK, PHONE, PHONE_POSITION, PHONE_PHONES,
        CONTACTS, AGENDA, PROJECTS, TRIPS, SETTINGS,
    )

    /** La clé de chaque sujet qui en a une : ce qu'elle nomme (les autres disent tout leur domaine). */
    val KEYS: Map<String, String> = mapOf(
        MAIL to "boxes", MAIL_DRAFTS to "boxes", MAIL_WORK to "refs", TEAMS to "conversations",
        TEAMS_WORK to "conversations", PHONE to "conversations", AGENDA to "calendars", PROJECTS to "projects",
    )
}

@Serializable
data class BlendPart(val emotion: String = "", val weight: Double = 0.0)

/**
 * Un fil de travail du mode pro (ADR 0164), tel que la trame `strands` le liste : son identifiant, ce que son
 * opératrice en a écrit, archivé ou non, combien de messages (0 : seulement réglé, ou ouvert ici sans encore rien
 * dedans), le premier et le dernier instant (ms) et le début de son premier message — de quoi le nommer sans titre.
 */
data class StrandInfo(
    val id: String,
    val title: String = "",
    val description: String = "",
    val archived: Boolean = false,
    val count: Int = 0,
    val firstAt: Long = 0,
    val lastAt: Long = 0,
    val opener: String = "",
)

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
    /** Ce qu'elle veut faire (`mcp.call`, `email.send`, `teams.send`…) ; vide : non dit. */
    val capability: String = "",
    /**
     * Le brouillon qu'elle a écrit, pour un mail (`email.send`) ou une réponse Teams (`teams.send`) ; vide sinon. Une
     * telle carte se relit et se décide là où elle partira (ADR 0191) : le chat n'en montre qu'un lien.
     */
    val draft: String = "",
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
    /** Une ligne d'elle : ses petites bulles (ADR 0119), lues à part comme ses outils ; `null` : rien à montrer. */
    val notes: List<MessageNote>? = null,
    /** Le fil de travail de la ligne (ADR 0164) ; `null` : le fil avec elle. Validé par `FrameCodec`. */
    val strand: String? = null,
)

/** Un outil dont elle s'est servie pour une réponse pro (ADR 0116) : son nom, et s'il a réussi. */
@Serializable
data class ToolUse(val name: String, val ok: Boolean)

/**
 * Une petite bulle jointe à un de ses messages (ADR 0119, 0196, `protocol.py::note_item`) : ce qu'elle a fait en
 * l'écrivant. [kind] : `location` (elle a regardé où tu es), `look` (elle a cherché des lieux ou calculé un trajet),
 * `map` (elle a montré une carte), `trip` (elle a créé ou changé un voyage) — les seules sortes que `FrameCodec`
 * laisse passer ; [text] : ce qu'elle a vu (le lieu, ce qu'elle a cherché, le titre de la carte ou du voyage), vide une
 * fois oublié ; [at] : de quand datait ce qu'elle a vu (le dernier changement d'un voyage), en millisecondes Unix (0 :
 * inconnu) ; [ref] : ce qu'une note de carte ouvre (le `seq` d'un regard, l'identifiant d'un voyage), vide sinon ou
 * une fois oublié. Gardée telle quelle, une note vidée comprise (elle remplace celle d'avant) ; ce qui se montre est
 * validé à l'affichage (`ui/chat/MapNotes`). L'app compose le texte de la bulle.
 */
@Serializable
data class MessageNote(val kind: String, val text: String = "", val at: Long = 0, val ref: String = "")

// ── L'état intérieur (`inner_state`), lu section par section ─────────────────────────────

/**
 * Une section absente vaut `null`. Une section malformée vaut aussi `null`, mais son nom est noté
 * dans [malformed] : le réducteur la garde telle qu'elle était au lieu de l'effacer.
 */
data class InnerState(
    val sleepPhase: String? = null,
    val energy: Double? = null,
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
