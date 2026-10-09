package fr.qwartz.mika.data.push

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.Serializable
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
 * Données du message Firebase : `{"v": "1", "n": <nonce base64>, "c": <chiffré base64>}` ; le clair :
 * `{"t": "speech", "id", "text", "ts", "files"}`.
 */
object PushPayload {
    const val VERSION = "1"
    const val KEY_BYTES = 32
    private const val TAG_BITS = 128
    private const val SPEECH = "speech"

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

    /** Une clé neuve, tirée à la connexion. */
    fun newKey(random: SecureRandom = SecureRandom()): ByteArray = ByteArray(KEY_BYTES).also(random::nextBytes)

    /**
     * Le message, ou `null` : une autre version, une autre clé, un chiffré abîmé, autre chose qu'une parole — on
     * ne montre jamais ce qu'on n'a pas su ouvrir.
     */
    fun open(key: ByteArray, data: Map<String, String>): Message? {
        if (data["v"] != VERSION || key.size != KEY_BYTES) return null
        return try {
            val decoder = Base64.getDecoder()
            val nonce = decoder.decode(data["n"] ?: return null)
            val sealed = decoder.decode(data["c"] ?: return null)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BITS, nonce))
            cipher.updateAAD(AAD)
            val message = MikaJson.decodeFromString(Message.serializer(), String(cipher.doFinal(sealed), Charsets.UTF_8))
            message.takeIf { it.t == SPEECH && it.id > 0 && it.text.isNotBlank() }
        } catch (_: GeneralSecurityException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
    }
}
