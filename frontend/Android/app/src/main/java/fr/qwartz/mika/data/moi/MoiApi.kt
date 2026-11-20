package fr.qwartz.mika.data.moi

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.net.MikaProtocol
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.DeserializationStrategy
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.UUID

/**
 * L'API par personne (`/api/moi`, `backendv2/docs/protocole-moi.md`), sous le jeton du téléphone : il lit et, depuis
 * l'ADR 0235, écrit comme une session de navigateur, sans CSRF. Jamais d'`Origin` (un navigateur n'a pas de jeton).
 *
 * Une lecture est un `GET`, une écriture un `POST` au corps JSON. Un 401 dit que le jeton ne vaut plus : [onUnauthorized]
 * le fait vérifier par la session (qui se ferme si c'est bien fini). Les erreurs du serveur sont déjà en français
 * (`{"error", "fields"}`) ; celles du réseau se disent ici.
 */
class MoiApi(
    private val client: OkHttpClient,
    private val credentials: () -> Credentials?,
    private val onUnauthorized: suspend () -> Unit,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    /** Ce qu'une requête a donné : la réponse lue, ou un refus en mots. */
    sealed interface Result<out T> {
        data class Ok<T>(val value: T) : Result<T>
        data class Failed(val error: MoiError) : Result<Nothing>
    }

    suspend fun get(path: String, query: Map<String, String?> = emptyMap()): Result<JsonObject> =
        send(path, query) { it.get() }

    suspend fun <T> get(path: String, query: Map<String, String?> = emptyMap(), reader: DeserializationStrategy<T>): Result<T> =
        get(path, query).decode(reader)

    /** Une lecture qui n'est pas du JSON (le HTML d'un mail, `/mail/frame`) : son texte tel quel. Un refus se lit
     *  comme les autres (le serveur le dit en JSON). */
    suspend fun text(path: String, query: Map<String, String?> = emptyMap(), accept: String = "text/html"): Result<String> =
        exchange(path, query, null, accept) { it.get() }

    /** Une écriture. [key] : sa clé d'envoi (`Idempotency-Key`) — la même redite ne refait rien (protocole § 1). */
    suspend fun post(path: String, body: JsonObject = JsonObject(emptyMap()), key: String? = newKey()): Result<JsonObject> =
        send(path, emptyMap(), key) { it.post(body.toString().toRequestBody(JSON)) }

    /** Une écriture en `multipart/form-data` (un mail et ses pièces, ADR 0214). */
    suspend fun postForm(path: String, form: RequestBody, key: String? = newKey()): Result<JsonObject> =
        send(path, emptyMap(), key) { it.post(form) }

    /** L'adresse absolue d'une route (une pièce jointe, une tuile) ; `null` hors session. */
    fun url(path: String, query: Map<String, String?> = emptyMap()): HttpUrl? {
        val c = credentials() ?: return null
        return build(c, path, query)
    }

    private fun build(c: Credentials, path: String, query: Map<String, String?>): HttpUrl {
        val b = c.base.http(PREFIX + path).newBuilder()
        for ((k, v) in query) if (!v.isNullOrEmpty()) b.addQueryParameter(k, v)
        return b.build()
    }

    private suspend fun send(
        path: String,
        query: Map<String, String?>,
        key: String? = null,
        method: (Request.Builder) -> Request.Builder,
    ): Result<JsonObject> = when (val got = exchange(path, query, key, "application/json", method)) {
        is Result.Ok -> Result.Ok(parseObject(got.value) ?: JsonObject(emptyMap()))
        is Result.Failed -> got
    }

    /** Une requête sous le jeton : le corps d'une réponse réussie, tel quel ; un refus, lu dans son JSON. */
    private suspend fun exchange(
        path: String,
        query: Map<String, String?>,
        key: String?,
        accept: String,
        method: (Request.Builder) -> Request.Builder,
    ): Result<String> {
        val c = credentials() ?: return Result.Failed(MoiError(401, MoiError.SIGNED_OUT))
        val builder = Request.Builder()
            .url(build(c, path, query))
            .header("Accept", accept)
            .header(MikaProtocol.HEADER_AUTHORIZATION, "Bearer ${c.token}")
        if (key != null) builder.header("Idempotency-Key", key)
        val request = method(builder).build()
        val result = withContext(io) {
            try {
                client.newCall(request).execute().use { response ->
                    val text = response.body.string()
                    if (response.isSuccessful) {
                        Result.Ok(text)
                    } else {
                        Result.Failed(MoiError.of(response.code, parseObject(text)))
                    }
                }
            } catch (e: IOException) {
                Result.Failed(MoiError(0, MoiError.NETWORK))
            }
        }
        if (result is Result.Failed && result.error.code == 401) onUnauthorized()
        return result
    }

    companion object {
        const val PREFIX = "/api/moi"
        private val JSON = "application/json; charset=utf-8".toMediaType()

        /** Une clé d'envoi neuve : un geste, une clé ; un réessai du même geste la redonne. */
        fun newKey(): String = UUID.randomUUID().toString()

        internal fun parseObject(text: String): JsonObject? = try {
            MikaJson.parseToJsonElement(text) as? JsonObject
        } catch (_: SerializationException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
    }
}

/** Un refus : [code] HTTP (0 : le réseau), [message] en français, et un message par champ refusé ([fields]). */
data class MoiError(val code: Int, val message: String, val fields: Map<String, String> = emptyMap()) {
    /** Pas à toi, ou plus là (le serveur répond pareil, protocole § 1). */
    val gone: Boolean get() = code == 404
    /** La situation a changé (déjà décidé, réglé ailleurs) : relire, puis recommencer. */
    val conflict: Boolean get() = code == 409
    val network: Boolean get() = code == 0

    companion object {
        const val NETWORK = "Le serveur ne répond pas. Vérifie ta connexion, puis réessaie."
        const val SIGNED_OUT = "Tu n'es plus connectée."
        private const val UNREADABLE = "Le serveur a répondu sans dire pourquoi"

        fun of(code: Int, body: JsonObject?): MoiError {
            val error = (body?.get("error") as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }
            val fields = (body?.get("fields") as? JsonObject)?.mapNotNull { (k, v) ->
                (v as? JsonPrimitive)?.contentOrNull?.let { k to it }
            }?.toMap().orEmpty()
            return MoiError(code, error ?: fallback(code), fields)
        }

        private fun fallback(code: Int): String = when (code) {
            401 -> SIGNED_OUT
            403 -> "Ce n'est pas ouvert pour toi."
            404 -> "Introuvable : ce n'est plus là."
            409 -> "La situation a changé entre-temps. Relis, puis recommence."
            413 -> "C'est trop gros pour le serveur."
            429 -> "Trop d'essais d'un coup : attends un peu."
            503 -> "Ce n'est pas encore prêt sur ce serveur."
            else -> "$UNREADABLE ($code)."
        }
    }
}

/** Lire une réponse sous sa forme ; une forme inattendue est un refus, pas une exception. */
fun <T> MoiApi.Result<JsonObject>.decode(reader: DeserializationStrategy<T>): MoiApi.Result<T> = when (this) {
    is MoiApi.Result.Ok -> try {
        MoiApi.Result.Ok(MikaJson.decodeFromJsonElement(reader, value))
    } catch (_: SerializationException) {
        MoiApi.Result.Failed(MoiError(-1, "La réponse du serveur ne se lit pas : mets l'application à jour."))
    } catch (_: IllegalArgumentException) {
        MoiApi.Result.Failed(MoiError(-1, "La réponse du serveur ne se lit pas : mets l'application à jour."))
    }
    is MoiApi.Result.Failed -> this
}

/** Le message d'une écriture réussie (`{"ok": true, "message": "…"}`), s'il y en a un. */
val JsonObject.message: String?
    get() = (this["message"] as? JsonPrimitive)?.contentOrNull?.takeIf { it.isNotBlank() }
