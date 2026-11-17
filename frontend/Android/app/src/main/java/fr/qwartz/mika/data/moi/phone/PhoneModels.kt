package fr.qwartz.mika.data.moi.phone

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes du Téléphone dans l'API par personne (`backendv2/docs/protocole-moi.md` § 5, code `app/me/phone.py`) : ce
 * que l'application a lu dans les notifications de WhatsApp et de Messages, rangé par conversation, les réponses que
 * Mika y a proposées, ta dernière position, tes téléphones. Chaque champ a son défaut : `MikaJson` ignore ce qu'il ne
 * connaît pas, et un champ absent ne casse rien. Les instants sont en millisecondes (0 : jamais). Une conversation se
 * désigne par sa clé (`<appli>|<fil>` : le code de l'appli et la clé opaque que ce téléphone a calculée, `PhoneKeys`).
 */

/** Un message lu sur le téléphone ([own] : écrit par toi) ; [id] : sa référence (« p123 »). */
@Serializable
data class ReadMessage(
    val id: String = "",
    val at: Long = 0,
    val own: Boolean = false,
    /** Qui l'a écrit (vide quand c'est toi). */
    val sender: String = "",
    val text: String = "",
)

/** La réponse de Mika qui compte pour une conversation : son sort, son identifiant, quand il s'est réglé (0 en chemin). */
@Serializable
data class HerReply(
    val state: String = "",
    val id: Long = 0,
    @SerialName("decided_at") val decidedAt: Long = 0,
)

/** Une conversation de la liste. */
@Serializable
data class PhoneConversation(
    /** `<appli>|<fil>`. */
    val key: String = "",
    /** Le code de l'appli (`whatsapp`, `messages`…). */
    val app: String = "",
    @SerialName("app_name") val appName: String = "",
    val group: Boolean = false,
    /** Le groupe, sinon qui écrit ; vide si rien ne la nomme. */
    val title: String = "",
    val count: Int = 0,
    @SerialName("last_at") val lastAt: Long = 0,
    /** Son dernier message, texte coupé. */
    val last: ReadMessage? = null,
    /** Sa réponse en chemin, sinon sa dernière si elle suit le dernier message reçu, sinon `null`. */
    val her: HerReply? = null,
)

@Serializable
data class PhoneConversations(val items: List<PhoneConversation> = emptyList())

/** Les sorts d'une réponse proposée : préparée, offerte au téléphone (qui attend ton geste), puis ce que le téléphone en
 *  dit, ou l'échéance. */
object OfferStates {
    const val PREPARED = "prepared"
    const val OFFERED = "offered"
    const val SENT = "sent"
    const val OTHER = "other"
    const val COPIED = "copied"
    const val IGNORED = "ignored"
    const val FAILED = "failed"
    const val EXPIRED = "expired"
}

/** Une réponse que Mika a proposée dans une conversation ([id] : celui que ce téléphone reçoit par Firebase). */
@Serializable
data class PhoneOffer(
    val id: Long = 0,
    val state: String = "",
    val at: Long = 0,
    val expires: Long = 0,
    @SerialName("decided_at") val decidedAt: Long = 0,
    /** Un code écrit par le code (`no_action`…), jamais un texte venu d'ailleurs. */
    val reason: String = "",
    /** Le message auquel elle répond (« p123 »). */
    @SerialName("reply_to") val replyTo: String = "",
    val text: String = "",
)

/** Le fil d'une conversation : les plus récents de ses messages, et ses dix dernières propositions. */
@Serializable
data class PhoneThread(
    val key: String = "",
    val app: String = "",
    @SerialName("app_name") val appName: String = "",
    val group: Boolean = false,
    /** Le nom du groupe ; vide en tête-à-tête. */
    val title: String = "",
    val messages: List<ReadMessage> = emptyList(),
    /** Il y en a de plus anciens que ceux-ci. */
    val more: Boolean = false,
    val offers: List<PhoneOffer> = emptyList(),
)

@Serializable
data class PhoneCoords(val lat: Double = 0.0, val lon: Double = 0.0)

/** Ta dernière position, si ton téléphone l'a donnée et que rien ne l'a effacée ([known]). */
@Serializable
data class PhonePosition(
    val known: Boolean = false,
    /** `null` : le serveur ne sait plus lire ses coordonnées. */
    val coords: PhoneCoords? = null,
    val label: String = "",
    @SerialName("accuracy_m") val accuracyM: Double = 0.0,
    val at: Long = 0,
)

/** Un de tes téléphones : le jeton `mobile` de son application, jamais son secret ; [push] : il a dit où le notifier. */
@Serializable
data class PhoneDevice(
    val id: Long = 0,
    /** « Android · fabricant modèle », composé par l'application. */
    val label: String = "",
    @SerialName("created_at") val createdAt: Long = 0,
    @SerialName("last_used") val lastUsed: Long = 0,
    val revoked: Boolean = false,
    val push: Boolean = false,
)

@Serializable
data class PhoneDevices(
    val items: List<PhoneDevice> = emptyList(),
    /** L'application est déposée sur le serveur. */
    val apk: Boolean = false,
)

/** Le sort d'une écriture (`{"ok": true, "message": "…"}`). */
@Serializable
data class PhoneDone(val ok: Boolean = false, val message: String = "")
