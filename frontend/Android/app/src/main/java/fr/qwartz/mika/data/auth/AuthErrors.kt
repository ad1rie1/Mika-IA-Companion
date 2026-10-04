package fr.qwartz.mika.data.auth

import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import javax.net.ssl.SSLException

/** Une erreur de connexion, dite en français ; [retryAfterSeconds] pour un bouton à compte à rebours. */
data class AuthError(val message: String, val retryAfterSeconds: Long? = null)

/** Ce que l'écran de connexion dit d'un refus ou d'une panne — une phrase sur quoi faire, pas un code. */
object AuthErrors {
    const val DEFAULT_RETRY_AFTER_S = 60L

    const val INVALID_CREDENTIALS = "Identifiants invalides."
    const val OUTDATED_SERVER = "Ce serveur ne propose pas encore la connexion par jeton — mets Mika à jour."
    const val UNKNOWN_HOST = "Serveur introuvable : vérifie l'adresse."
    const val TLS_REFUSED = "Certificat HTTPS refusé."
    const val SESSION_EXPIRED = "Ta session a expiré ou a été révoquée — reconnecte-toi."
    const val SESSION_TO_REOPEN = "Session à rouvrir sur cet appareil."

    fun forHttp(code: Int, serverError: String?, retryAfter: String?, nowMs: Long): AuthError {
        val said = serverError?.trim()?.takeIf { it.isNotEmpty() }
        return when {
            code == 401 -> AuthError(said ?: INVALID_CREDENTIALS)
            code == 400 -> AuthError(said ?: "Requête refusée par le serveur (400).")
            code == 403 -> AuthError("Le serveur a refusé la demande (403).")
            code == 404 -> AuthError(OUTDATED_SERVER)
            code == 429 -> {
                val seconds = parseRetryAfter(retryAfter, nowMs) ?: DEFAULT_RETRY_AFTER_S
                AuthError("Trop de tentatives. Réessaie dans $seconds s.", seconds)
            }
            code in 500..599 -> AuthError("Erreur du serveur ($code).")
            else -> AuthError("Réponse inattendue du serveur ($code).")
        }
    }

    fun forException(error: Throwable, hostPort: String): AuthError = when (error) {
        is UnknownHostException -> AuthError(UNKNOWN_HOST)
        is SSLException -> AuthError(TLS_REFUSED)
        is ConnectException, is SocketTimeoutException, is NoRouteToHostException -> AuthError(
            "Le serveur ne répond pas ($hostPort). Est-il lancé et joignable depuis ce téléphone ?",
        )
        is IOException -> AuthError("Connexion impossible au serveur ($hostPort).")
        else -> AuthError("Erreur inattendue : ${error.javaClass.simpleName}.")
    }

    /** `Retry-After` : des secondes, ou une date HTTP. Au moins une seconde ; illisible → `null`. */
    fun parseRetryAfter(header: String?, nowMs: Long): Long? {
        val value = header?.trim()?.takeIf { it.isNotEmpty() } ?: return null
        value.toLongOrNull()?.let { return it.coerceAtLeast(1) }
        return try {
            val at = ZonedDateTime.parse(value, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant().toEpochMilli()
            ((at - nowMs + 999) / 1000).coerceAtLeast(1)
        } catch (_: DateTimeParseException) {
            null
        }
    }
}
