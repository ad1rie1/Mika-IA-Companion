package fr.qwartz.mika.data.push

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.phone.PhoneDraft
import fr.qwartz.mika.data.phone.PhoneDrafts
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.security.GeneralSecurityException
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * Ce qu'une notification Firebase apporte (ADR 0077) : un message de Mika scellé par le serveur avec la clé que ce
 * téléphone lui a confiée — AES-GCM, nonce de 96 bits, données associées [AAD]. Google ne transporte qu'un chiffré.
 * Le pendant de `backendv2/src/mika/adapters/push/seal.py` ; un vecteur produit par lui est vérifié dans les tests.
 *
 * Données du message Firebase : `{"v": "1", "n": <nonce base64>, "c": <chiffré base64>}` ; le clair est une parole,
 * `{"t": "speech", "id", "text", "ts", "files"}`, ou une réponse proposée pour WhatsApp ou Messages (ADR 0120),
 * `{"t": "phone_draft", "id", "app", "thread", "to", "text", "exp", "ts"}`. Ouvrir ([unseal]) et comprendre ([read])
 * sont deux temps : un type inconnu, comme un scellé abîmé, ne se montre jamais.
 */
object PushPayload {
    const val VERSION = "1"
    const val KEY_BYTES = 32
    private const val TAG_BITS = 128
    private const val SPEECH = "speech"
    private const val PHONE_DRAFT = "phone_draft"

    /** Lié au sens du chiffré : le même que le serveur. */
    val AAD: ByteArray = "fr.qwartz.mika/push/v1".toByteArray(Charsets.UTF_8)

    /** Une parole de Mika, telle que la notification la montre. */
    @Serializable
    data class Message(
        val t: String = "",
        /** Son identifiant dans le fil : au-delà du lu et du notifié, elle est nouvelle. */
        val id: Long = 0,
        val text: String = "",
        /** L'heure du serveur, en ms. */
        val ts: Long = 0,
        /** Les fichiers joints (montrés à l'ouverture). */
        val files: Int = 0,
    )

    /** Ce qu'un message Firebase apporte, une fois ouvert et compris. */
    sealed interface Pushed {
        /** Une parole de Mika : la notification de conversation habituelle. */
        data class Speech(val message: Message) : Pushed
        /** Une réponse qu'elle propose d'envoyer à la place de la personne (ADR 0120) : une notification d'autorisation. */
        data class Draft(val draft: PhoneDraft) : Pushed
    }

    /** Une clé neuve, tirée à la connexion. */
    fun newKey(random: SecureRandom = SecureRandom()): ByteArray = ByteArray(KEY_BYTES).also(random::nextBytes)

    /**
     * Le message, ou `null` : une autre version, une autre clé, un chiffré abîmé, un type inconnu, une parole sans texte —
     * on ne montre jamais ce qu'on n'a pas su ouvrir.
     */
    fun open(key: ByteArray, data: Map<String, String>): Pushed? = unseal(key, data)?.let(::read)

    /** Le clair d'un scellé, ou `null` : une autre version, une autre clé, un chiffré abîmé. Rien n'y est encore compris. */
    fun unseal(key: ByteArray, data: Map<String, String>): String? {
        if (data["v"] != VERSION || key.size != KEY_BYTES) return null
        return try {
            val decoder = Base64.getDecoder()
            val nonce = decoder.decode(data["n"] ?: return null)
            val sealed = decoder.decode(data["c"] ?: return null)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BITS, nonce))
            cipher.updateAAD(AAD)
            String(cipher.doFinal(sealed), Charsets.UTF_8)
        } catch (_: GeneralSecurityException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    /**
     * Ce que dit un clair : une parole (un identifiant et du texte), une proposition de réponse lisible
     * ([PhoneDrafts.isValid]), sinon `null` — un type que cette version ne connaît pas n'est pas montré.
     */
    fun read(plain: String): Pushed? = try {
        (MikaJson.parseToJsonElement(plain) as? JsonObject)?.let { json ->
            when ((json["t"] as? JsonPrimitive)?.takeIf { it.isString }?.content) {
                SPEECH -> MikaJson.decodeFromJsonElement(Message.serializer(), json)
                    .takeIf { it.id > 0 && it.text.isNotBlank() }
                    ?.let(Pushed::Speech)
                PHONE_DRAFT -> MikaJson.decodeFromJsonElement(PhoneDraft.serializer(), json)
                    .takeIf(PhoneDrafts::isValid)
                    ?.let(Pushed::Draft)
                else -> null
            }
        }
    } catch (_: IllegalArgumentException) {
        null
    }
}
