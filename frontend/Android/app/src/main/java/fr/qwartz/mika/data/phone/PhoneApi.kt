package fr.qwartz.mika.data.phone

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException

/**
 * Les deux portes du téléphone (ADR 0120) : les messages lus (`POST /api/phone/inbox`) et le sort des réponses proposées
 * (`POST /api/phone/settled`). Sous le jeton de l'app (`Authorization: Bearer mw_…`, client `mobile`), passé à chaque
 * appel ; jamais d'`Origin` : le serveur refuse un jeton à un navigateur. Un appel, une réponse : rien ne reste ouvert
 * (ADR 0077).
 */
class PhoneApi(
    private val client: OkHttpClient,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    sealed interface Result<out T> {
        data class Ok<T>(val value: T) : Result<T>
        /** Une réponse du serveur autre que 2xx, avec son `{"error": …}` et son `Retry-After`. */
        data class Http(val code: Int, val error: String?, val retryAfter: String?) : Result<Nothing>
        data class Network(val error: IOException) : Result<Nothing>
    }

    /** Ce que la porte a fait du lot : accepté, déjà connu, écarté (illisible). */
    data class InboxReply(val accepted: Int, val known: Int, val dropped: Int)

    /** Ce que la porte a fait des sorts : réglés, inconnus (une proposition expirée, oubliée). */
    data class SettledReply(val settled: Int, val unknown: Int)

    @Serializable
    private data class InboxBody(val messages: List<PhoneMessage>)

    @Serializable
    private data class SettledBody(val items: List<PhoneSettled>)

    suspend fun inbox(base: ServerBase, token: String, messages: List<PhoneMessage>): Result<InboxReply> {
        val body = MikaJson.encodeToString(InboxBody.serializer(), InboxBody(messages))
        return post(base, PATH_INBOX, token, body) { o ->
            InboxReply(count(o["accepted"]), count(o["known"]), count(o["dropped"]))
        }
    }

    suspend fun settled(base: ServerBase, token: String, items: List<PhoneSettled>): Result<SettledReply> {
        val body = MikaJson.encodeToString(SettledBody.serializer(), SettledBody(items))
        return post(base, PATH_SETTLED, token, body) { o -> SettledReply(count(o["settled"]), count(o["unknown"])) }
    }

    private suspend fun <T> post(base: ServerBase, path: String, token: String, body: String, parse: (JsonObject) -> T): Result<T> {
        val request = Request.Builder()
            .url(base.http(path))
            .header("Accept", "application/json")
            .header(MikaProtocol.HEADER_AUTHORIZATION, "Bearer $token")
            .post(body.toRequestBody(JSON))
            .build()
        return withContext(io) {
            try {
                client.newCall(request).execute().use { response ->
                    val text = response.body.string()
                    if (!response.isSuccessful) {
                        Result.Http(response.code, errorOf(text), response.header("Retry-After"))
                    } else {
                        // Une réponse 2xx vaut accord, même si son corps a changé de forme : le lot ne repart pas.
                        Result.Ok(parse(objectOf(text) ?: JsonObject(emptyMap())))
                    }
                }
            } catch (e: IOException) {
                Result.Network(e)
            }
        }
    }

    private fun objectOf(text: String): JsonObject? = try {
        MikaJson.parseToJsonElement(text) as? JsonObject
    } catch (_: IllegalArgumentException) {
        null
    }

    private fun errorOf(text: String): String? =
        (objectOf(text)?.get("error") as? JsonPrimitive)?.takeIf { it.isString }?.content

    /** Un nombre, ou la taille d'une liste (le serveur peut nommer les identifiants plutôt que les compter). */
    private fun count(e: JsonElement?): Int = when (e) {
        is JsonPrimitive -> e.intOrNull ?: 0
        is JsonArray -> e.size
        else -> 0
    }

    companion object {
        const val PATH_INBOX = "/api/phone/inbox"
        const val PATH_SETTLED = "/api/phone/settled"
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}
