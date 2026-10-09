package fr.qwartz.mika.data.auth

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import java.util.Base64
import java.util.concurrent.atomic.AtomicReference

/**
 * Le jeton de l'app (`mw_…`), chiffré au repos : `v1:<iv base64>:<chiffré base64>` dans un DataStore
 * à lui. Gardé en mémoire une fois lu. Une clé invalidée (verrouillage changé, restauration sur un
 * autre appareil) ou un blob illisible ne bloque rien : le blob et la clé sont effacés, et la session
 * est à rouvrir.
 *
 * Le même coffre garde, sous un autre nom et d'autres données associées, la clé qui scelle les
 * notifications (ADR 0077) : illisible, celle-là est seulement oubliée — la clé du Keystore, qui ouvre
 * aussi le jeton, reste ([forgetKeyWhenUnreadable] faux).
 */
class TokenVault(
    private val store: DataStore<Preferences>,
    private val cipher: KeystoreCipher,
    name: String = "token",
    private val aad: ByteArray = AAD,
    private val forgetKeyWhenUnreadable: Boolean = true,
) {
    private val key = stringPreferencesKey(name)

    sealed interface Read {
        data object Absent : Read
        class Present(val token: String) : Read {
            override fun toString() = "Present(…)"
        }
        data object Invalid : Read
    }

    private val cache = AtomicReference<String?>(null)

    suspend fun read(): Read {
        cache.get()?.let { return Read.Present(it) }
        val blob = store.data.first()[key] ?: return Read.Absent
        return try {
            val token = open(blob)
            cache.set(token)
            Read.Present(token)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            // KeyPermanentlyInvalidatedException, AEADBadTagException, blob abîmé…
            clear()
            if (forgetKeyWhenUnreadable) {
                try {
                    cipher.deleteKey()
                } catch (_: Exception) {
                    // déjà absente
                }
            }
            Read.Invalid
        }
    }

    suspend fun write(token: String) {
        val sealed = cipher.encrypt(token.toByteArray(Charsets.UTF_8), aad)
        val encoder = Base64.getEncoder()
        val blob = "$VERSION:${encoder.encodeToString(sealed.iv)}:${encoder.encodeToString(sealed.ciphertext)}"
        store.edit { it[key] = blob }
        cache.set(token)
    }

    suspend fun clear() {
        cache.set(null)
        store.edit { it.remove(key) }
    }

    private fun open(blob: String): String {
        val parts = blob.split(':')
        require(parts.size == 3 && parts[0] == VERSION) { "format inconnu" }
        val decoder = Base64.getDecoder()
        val plain = cipher.decrypt(decoder.decode(parts[1]), decoder.decode(parts[2]), aad)
        return String(plain, Charsets.UTF_8)
    }

    companion object {
        private const val VERSION = "v1"
        /** Lié au sens du blob : un chiffré d'ailleurs ne s'ouvre pas ici. */
        val AAD = "fr.qwartz.mika/token/v1".toByteArray(Charsets.UTF_8)
        /** La clé des notifications (base64), sous son propre nom et ses propres données associées. */
        const val PUSH_KEY_NAME = "push_key"
        val PUSH_KEY_AAD = "fr.qwartz.mika/push-key/v1".toByteArray(Charsets.UTF_8)
    }
}
