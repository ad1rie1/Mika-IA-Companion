package fr.qwartz.mika.data.net

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put

/**
 * Lecture et écriture des trames. Le décodage ne lève jamais : sans `type`, rien (`null`) ; un type
 * connu mais illisible devient [ServerFrame.Unknown] ; un message de l'historique ou une section de
 * l'état intérieur malformés sont écartés seuls, sans emporter la trame.
 */
object FrameCodec {
    private val json = MikaJson

    fun decode(text: String): ServerFrame? {
        val obj = try {
            json.parseToJsonElement(text) as? JsonObject
        } catch (_: IllegalArgumentException) {
            null
        } ?: return null
        val type = (obj["type"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return null
        return try {
            when (type) {
                MikaProtocol.TYPE_SPEECH -> json.decodeFromJsonElement(ServerFrame.Speech.serializer(), obj)
                MikaProtocol.TYPE_HISTORY -> decodeHistory(obj)
                MikaProtocol.TYPE_ACK -> json.decodeFromJsonElement(ServerFrame.Ack.serializer(), obj)
                MikaProtocol.TYPE_EMOTION_UPDATE ->
                    json.decodeFromJsonElement(ServerFrame.EmotionUpdate.serializer(), obj)
                MikaProtocol.TYPE_INNER_STATE_UPDATE -> ServerFrame.InnerStateUpdate(decodeInnerState(obj["inner_state"]))
                MikaProtocol.TYPE_PONG -> ServerFrame.Pong((obj["t"] as? JsonPrimitive)?.doubleOrNull)
                MikaProtocol.TYPE_APPROVALS -> decodeApprovals(obj)
                MikaProtocol.TYPE_APPROVAL_RESULT -> decodeApprovalResult(obj)
                else -> ServerFrame.Unknown(type)
            }
        } catch (_: IllegalArgumentException) {
            ServerFrame.Unknown(type)
        }
    }

    @Serializable
    private data class HistoryHead(
        val mode: String = MikaProtocol.MODE_CATCHUP,
        @SerialName("last_id") val lastId: Long = 0,
        val truncated: Boolean = false,
        val life: String? = null,
        val reset: Boolean = false,
    )

    private fun decodeHistory(obj: JsonObject): ServerFrame.History {
        val head = json.decodeFromJsonElement(HistoryHead.serializer(), JsonObject(obj - "messages"))
        val raw = obj["messages"] as? JsonArray
        val entries = raw?.mapNotNull { item ->
            try {
                json.decodeFromJsonElement(HistoryEntry.serializer(), item)
            } catch (_: IllegalArgumentException) {
                null
            }
        }
        return ServerFrame.History(head.mode, entries, head.lastId, head.truncated, head.life, head.reset)
    }

    /**
     * La liste entière des cartes d'accord. Sans `items` lisible, la trame est inconnue (la liste
     * affichée ne se vide pas sur une trame cassée) ; une carte mal formée est écartée seule, un
     * identifiant répété ne compte qu'une fois.
     */
    private fun decodeApprovals(obj: JsonObject): ServerFrame {
        val items = obj["items"] as? JsonArray ?: return ServerFrame.Unknown(MikaProtocol.TYPE_APPROVALS)
        val seen = HashSet<Long>()
        val cards = ArrayList<ApprovalCard>()
        for (item in items) {
            if (cards.size >= MikaProtocol.MAX_APPROVAL_CARDS) break
            val card = approvalCard(item) ?: continue
            if (seen.add(card.id)) cards += card
        }
        return ServerFrame.Approvals(cards)
    }

    /**
     * Une carte, ou `null` si elle est mal formée : identifiant entier positif, empreinte hexadécimale
     * (128 au plus), titre, texte et raison de blocage en chaînes (absents : vides), échéance en
     * millisecondes ou `null`. Le titre et la raison trop longs sont coupés ; le texte aussi, mais la
     * carte est alors marquée incomplète (elle ne pourra qu'être refusée).
     */
    fun approvalCard(element: JsonElement): ApprovalCard? {
        val o = element as? JsonObject ?: return null
        val id = positiveLong(o["id"]) ?: return null
        val digest = stringField(o["digest"]) ?: return null
        if (!MikaProtocol.APPROVAL_DIGEST.matches(digest)) return null
        val title = stringField(o["title"]) ?: return null
        val text = stringField(o["text"]) ?: return null
        val blocked = stringField(o["blocked"]) ?: return null
        val expiresAt = when (val raw = o["expires_at"]) {
            null, JsonNull -> null
            else -> timestampMs(raw) ?: return null
        }
        val complete = text.length <= MikaProtocol.MAX_APPROVAL_TEXT_CHARS
        return ApprovalCard(
            id = id,
            title = clip(title, MikaProtocol.MAX_APPROVAL_TITLE_CHARS),
            text = if (complete) text else text.take(MikaProtocol.MAX_APPROVAL_TEXT_CHARS),
            digest = digest,
            blocked = clip(blocked, MikaProtocol.MAX_APPROVAL_BLOCKED_CHARS),
            expiresAt = expiresAt,
            complete = complete,
        )
    }

    private fun decodeApprovalResult(obj: JsonObject): ServerFrame {
        val unknown = ServerFrame.Unknown(MikaProtocol.TYPE_APPROVAL_RESULT)
        val id = positiveLong(obj["id"]) ?: return unknown
        val status = (obj["status"] as? JsonPrimitive)?.takeIf { it.isString }?.content ?: return unknown
        return ServerFrame.ApprovalResult(id, status.take(MAX_STATUS_CHARS))
    }

    /** Un entier JSON strictement positif (jamais une chaîne, jamais un nombre à virgule). */
    private fun positiveLong(element: JsonElement?): Long? =
        (element as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull?.takeIf { it > 0 }

    /** Une heure en millisecondes : un entier, ou un nombre à virgule fini ; positive. */
    private fun timestampMs(element: JsonElement): Long? {
        val p = (element as? JsonPrimitive)?.takeIf { !it.isString } ?: return null
        val ms = p.longOrNull ?: p.doubleOrNull?.takeIf { it.isFinite() }?.toLong() ?: return null
        return ms.takeIf { it > 0 }
    }

    /** Absent ou `null` : vide ; une chaîne : elle ; autre chose : `null` (ce qui la porte est écarté). */
    private fun stringField(element: JsonElement?): String? = when {
        element == null || element is JsonNull -> ""
        element is JsonPrimitive && element.isString -> element.content
        else -> null
    }

    private fun clip(text: String, max: Int): String = if (text.length <= max) text else text.take(max - 1) + "…"

    /** Section par section : une section illisible est notée, jamais fatale au panneau. */
    fun decodeInnerState(element: JsonElement?): InnerState {
        val obj = element as? JsonObject ?: return InnerState()
        val malformed = mutableSetOf<String>()

        fun <T> section(key: String, serializer: KSerializer<T>): T? {
            val value = obj[key] ?: return null
            if (value is JsonNull) return null
            return try {
                json.decodeFromJsonElement(serializer, value)
            } catch (_: IllegalArgumentException) {
                malformed += key
                null
            }
        }

        return InnerState(
            sleepPhase = section(K_SLEEP_PHASE, String.serializer()),
            energy = section(K_ENERGY, Double.serializer()),
            place = section(K_PLACE, String.serializer()),
            circadian = section(K_CIRCADIAN, Circadian.serializer()),
            drives = section(K_DRIVES, MapSerializer(String.serializer(), Drive.serializer())),
            estime = section(K_ESTIME, Double.serializer()),
            personScope = section(K_PERSON_SCOPE, Boolean.serializer()),
            ruminations = section(K_RUMINATIONS, ListSerializer(Rumination.serializer())),
            todayJournal = section(K_JOURNAL, Journal.serializer()),
            lastDream = section(K_DREAM, Dream.serializer()),
            selfNarrative = section(K_NARRATIVE, SelfNarrative.serializer()),
            projects = section(K_PROJECTS, ListSerializer(ProjectSummary.serializer())),
            identity = section(K_IDENTITY, IdentityView.serializer()),
            personProfile = section(K_PROFILE, PersonProfile.serializer()),
            pendingCommitments = section(K_COMMITMENTS, ListSerializer(String.serializer())),
            malformed = malformed,
        )
    }

    // ── Trames du client : de contrôle seulement (le chat passe par ChatFrameWriter) ──

    fun sync(afterId: Long): String = buildJsonObject {
        put("type", MikaProtocol.TYPE_SYNC)
        put("after_id", afterId)
    }.toString()

    fun ping(t: Long): String = buildJsonObject {
        put("type", MikaProtocol.TYPE_PING)
        put("t", t)
    }.toString()

    fun presence(here: Boolean): String = buildJsonObject {
        put("type", MikaProtocol.TYPE_PRESENCE)
        put("here", here)
    }.toString()

    /** Une décision sur une carte d'accord, avec l'empreinte de la carte telle qu'elle était montrée. */
    fun approval(id: Long, decision: ApprovalDecision, digest: String): String = buildJsonObject {
        put("type", MikaProtocol.TYPE_APPROVAL)
        put("id", id)
        put("decision", decision.wire)
        put("digest", digest)
    }.toString()

    private const val MAX_STATUS_CHARS = 64

    const val K_SLEEP_PHASE = "sleep_phase"
    const val K_ENERGY = "energy"
    const val K_PLACE = "place"
    const val K_CIRCADIAN = "circadian"
    const val K_DRIVES = "drives"
    const val K_ESTIME = "estime"
    const val K_PERSON_SCOPE = "person_scope"
    const val K_RUMINATIONS = "ruminations"
    const val K_JOURNAL = "today_journal"
    const val K_DREAM = "last_dream"
    const val K_NARRATIVE = "self_narrative"
    const val K_PROJECTS = "projects"
    const val K_IDENTITY = "identity"
    const val K_PROFILE = "person_profile"
    const val K_COMMITMENTS = "pending_commitments"
}
