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
