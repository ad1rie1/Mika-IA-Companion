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
 */
class TokenVault(
    private val store: DataStore<Preferences>,
    private val cipher: KeystoreCipher,
) {
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
        val blob = store.data.first()[KEY] ?: return Read.Absent
        return try {
            val token = open(blob)
            cache.set(token)
            Read.Present(token)
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) {
            // KeyPermanentlyInvalidatedException, AEADBadTagException, blob abîmé…
            clear()
            try {
                cipher.deleteKey()
            } catch (_: Exception) {
                // déjà absente
            }
            Read.Invalid
        }
    }

    suspend fun write(token: String) {
        val sealed = cipher.encrypt(token.toByteArray(Charsets.UTF_8), AAD)
        val encoder = Base64.getEncoder()
        val blob = "$VERSION:${encoder.encodeToString(sealed.iv)}:${encoder.encodeToString(sealed.ciphertext)}"
        store.edit { it[KEY] = blob }
        cache.set(token)
    }

    suspend fun clear() {
        cache.set(null)
        store.edit { it.remove(KEY) }
    }

    private fun open(blob: String): String {
        val parts = blob.split(':')
        require(parts.size == 3 && parts[0] == VERSION) { "format inconnu" }
        val decoder = Base64.getDecoder()
        val plain = cipher.decrypt(decoder.decode(parts[1]), decoder.decode(parts[2]), AAD)
        return String(plain, Charsets.UTF_8)
    }

    companion object {
        private const val VERSION = "v1"
        private val KEY = stringPreferencesKey("token")
        /** Lié au sens du blob : un chiffré d'ailleurs ne s'ouvre pas ici. */
        val AAD = "fr.qwartz.mika/token/v1".toByteArray(Charsets.UTF_8)
    }
}
