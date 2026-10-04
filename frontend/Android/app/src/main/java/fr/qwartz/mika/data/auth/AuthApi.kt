package fr.qwartz.mika.data.auth

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit

/** Qui est connecté (`/auth/whoami`), tel que l'app le garde. */
@Serializable
data class Profile(
    val username: String = "",
    @SerialName("display_name") val displayName: String = "",
    @SerialName("person_id") val personId: String = "",
    val operator: Boolean = false,
)

/**
 * Les routes d'authentification d'un client natif (ADR 0062) : identifiant et mot de passe contre un
 * jeton, `whoami` avec ce jeton, et le jeton rendu à la déconnexion. Jamais d'`Origin` : le serveur
 * refuse un jeton à un navigateur.
 */
class AuthApi(
    private val client: OkHttpClient,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    sealed interface Result<out T> {
        data class Ok<T>(val value: T) : Result<T>
        /** Une réponse du serveur autre que 2xx, avec son `{"error": …}` et son `Retry-After`. */
        data class Http(val code: Int, val error: String?, val retryAfter: String?) : Result<Nothing>
        data class Network(val error: IOException) : Result<Nothing>
    }

    @Serializable
    data class TokenGrant(
        val token: String = "",
        @SerialName("token_id") val tokenId: Long? = null,
        val client: String? = null,
        val authenticated: Boolean = false,
        val username: String = "",
        @SerialName("display_name") val displayName: String = "",
        @SerialName("person_id") val personId: String = "",
        val operator: Boolean = false,
    ) {
        val profile: Profile get() = Profile(username, displayName, personId, operator)
        override fun toString() = "TokenGrant(tokenId=$tokenId, client=$client, personId=$personId)"
    }

    @Serializable
    data class Whoami(
        val authenticated: Boolean = false,
        val username: String = "",
        @SerialName("display_name") val displayName: String = "",
        @SerialName("person_id") val personId: String = "",
        val operator: Boolean = false,
        val client: String? = null,
        @SerialName("token_id") val tokenId: Long? = null,
    ) {
        val profile: Profile get() = Profile(username, displayName, personId, operator)
    }

    suspend fun login(base: ServerBase, username: String, password: String, label: String): Result<TokenGrant> {
        val body = buildJsonObject {
            put("username", username)
            put("password", password)
            put("label", label)
            put("client", MikaProtocol.CLIENT_MOBILE)
        }.toString()
        val request = Request.Builder()
            .url(base.http(MikaProtocol.PATH_TOKEN))
            .header("Accept", "application/json")
            .post(body.toRequestBody(JSON))
            .build()
        return call(request) { MikaJson.decodeFromString(TokenGrant.serializer(), it) }
    }

    suspend fun whoami(base: ServerBase, token: String): Result<Whoami> {
        val request = Request.Builder()
            .url(base.http(MikaProtocol.PATH_WHOAMI))
            .header("Accept", "application/json")
            .header(MikaProtocol.HEADER_AUTHORIZATION, "Bearer $token")
            .get()
            .build()
        return call(request) { MikaJson.decodeFromString(Whoami.serializer(), it) }
    }

    /** Rendre le jeton (au mieux, 5 s) : ses connexions se ferment côté serveur. */
    suspend fun revoke(base: ServerBase, token: String): Boolean {
        val request = Request.Builder()
            .url(base.http(MikaProtocol.PATH_TOKEN))
            .header(MikaProtocol.HEADER_AUTHORIZATION, "Bearer $token")
            .delete()
            .build()
        val quick = client.newBuilder().callTimeout(5, TimeUnit.SECONDS).build()
        return withContext(io) {
            try {
                quick.newCall(request).execute().use { it.isSuccessful }
            } catch (_: IOException) {
                false
            }
        }
    }

    private suspend fun <T> call(request: Request, parse: (String) -> T): Result<T> = withContext(io) {
        try {
            client.newCall(request).execute().use { response -> read(response, parse) }
        } catch (e: IOException) {
            Result.Network(e)
        }
    }

    private fun <T> read(response: Response, parse: (String) -> T): Result<T> {
        val text = response.body.string()
        if (!response.isSuccessful) {
            return Result.Http(response.code, errorOf(text), response.header("Retry-After"))
        }
        return try {
            Result.Ok(parse(text))
        } catch (_: IllegalArgumentException) {
            Result.Http(response.code, "Réponse illisible du serveur.", null)
        }
    }

    private fun errorOf(text: String): String? = try {
        ((MikaJson.parseToJsonElement(text) as? JsonObject)?.get("error") as? JsonPrimitive)
            ?.takeIf { it.isString }?.content
    } catch (_: IllegalArgumentException) {
        null
    }

    private companion object {
        val JSON = "application/json; charset=utf-8".toMediaType()
    }
}
