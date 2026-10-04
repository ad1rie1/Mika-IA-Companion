package fr.qwartz.mika.data.files

import fr.qwartz.mika.data.chat.MessageAttachment
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URLDecoder
import java.net.UnknownHostException
import java.nio.charset.StandardCharsets
import javax.net.ssl.SSLException

/**
 * Les fichiers que Mika envoie (`/files/<id>`, ADR 0062) : les reconnaître, nommer ce qu'on en fait
 * sur le téléphone, et dire en français pourquoi un téléchargement n'a pas abouti.
 */
object MikaFileRefs {
    private val ID = Regex("^[0-9a-f]{32}$")

    /**
     * La route d'un fichier de Mika, relative au serveur — ou `null` si l'entrée n'en désigne pas une
     * qu'on accepte de suivre. Jamais une adresse absolue : le jeton ne part que vers son serveur, et
     * un lien venu du fil ne doit pas pouvoir choisir où.
     */
    fun path(att: MessageAttachment): String? {
        val id = att.id?.lowercase()?.takeIf { ID.matches(it) } ?: return null
        val expected = "/files/$id"
        val url = att.url?.trim()
        if (url.isNullOrEmpty()) return expected
        return if (url.lowercase() == expected) expected else null
    }

    fun isMikaFile(att: MessageAttachment): Boolean = path(att) != null

    /** Retiré par la rétention : on le dit au lieu de proposer un téléchargement voué au 410. */
    fun isRemoved(att: MessageAttachment): Boolean = att.available == false

    fun isImage(att: MessageAttachment): Boolean =
        att.kind == "image" || att.mime?.lowercase()?.startsWith("image/") == true

    /** Le nom sous lequel le ranger : celui qu'elle a donné, nettoyé ; à défaut, d'après l'identifiant. */
    fun localName(att: MessageAttachment): String {
        val cleaned = OutboxFiles.sanitize(att.name)
        return if (att.name.isBlank()) "fichier-${att.id?.take(8) ?: "mika"}" else cleaned
    }

    /**
     * Le type à annoncer à l'application qui l'ouvrira : celui qu'elle a déclaré (ADR 0062 : « il sert à
     * choisir l'application ») ; un texte de programmeur (`text/x-python`) s'ouvre comme du texte, que
     * presque tout téléphone sait afficher.
     */
    fun openMime(att: MessageAttachment, served: String?): String {
        val declared = att.mime?.lowercase()?.substringBefore(';')?.trim()?.takeIf { '/' in it }
        val type = declared ?: served?.lowercase()?.substringBefore(';')?.trim()?.takeIf { '/' in it }
            ?: return "application/octet-stream"
        if (type.startsWith("text/") && type !in COMMON_TEXT) return "text/plain"
        return type
    }

    private val COMMON_TEXT = setOf("text/plain", "text/html", "text/csv", "text/markdown", "text/calendar", "text/vcard")

    /**
     * `Content-Disposition: attachment; filename*=UTF-8''…` (RFC 6266/5987), à défaut `filename="…"`.
     * Sert seulement de repli quand l'entrée du fil n'a pas de nom.
     */
    fun filenameFromDisposition(header: String?): String? {
        if (header.isNullOrBlank()) return null
        val parts = header.split(';').map { it.trim() }
        parts.firstOrNull { it.startsWith("filename*=", ignoreCase = true) }?.let { p ->
            val value = p.substringAfter('=').trim().trim('"')
            val encoded = value.substringAfter("''", value)
            val declared = value.substringBefore("''", "UTF-8").ifBlank { "UTF-8" }
            // `+` n'est pas une espace ici (ce n'est pas un formulaire) : on le protège du décodeur.
            val raw = encoded.replace("+", "%2B")
            return try {
                URLDecoder.decode(raw, declared).takeIf { it.isNotBlank() }
            } catch (_: IllegalArgumentException) {
                null
            } catch (_: java.io.UnsupportedEncodingException) {
                URLDecoder.decode(raw, StandardCharsets.UTF_8.name()).takeIf { it.isNotBlank() }
            }
        }
        parts.firstOrNull { it.startsWith("filename=", ignoreCase = true) }?.let { p ->
            return p.substringAfter('=').trim().trim('"').takeIf { it.isNotBlank() }
        }
        return null
    }
}

/** Ce qu'on dit d'un téléchargement qui n'a pas abouti. */
object DownloadErrors {
    const val NOT_FOUND = "Fichier introuvable"
    const val GONE = "Fichier retiré"
    const val SESSION_EXPIRED = "Session expirée"
    const val RATE_LIMITED = "Trop de téléchargements — réessaie dans une minute."
    const val UNREACHABLE = "Serveur injoignable : téléchargement impossible."
    const val INTERRUPTED = "Téléchargement interrompu."
    const val TLS = "Certificat HTTPS refusé."
    const val NOT_A_FILE = "Ce fichier ne vient pas de Mika."
    const val STORAGE = "Impossible d'écrire le fichier sur le téléphone."

    /** 404 : inconnu *ou* pas à toi (le serveur ne distingue pas) ; 410 : retiré par la rétention. */
    fun forHttp(code: Int): String = when (code) {
        401 -> SESSION_EXPIRED
        404 -> NOT_FOUND
        410 -> GONE
        429 -> RATE_LIMITED
        in 500..599 -> "Erreur du serveur ($code)."
        else -> "Téléchargement refusé ($code)."
    }

    fun forException(error: Throwable): String = when (error) {
        is UnknownHostException, is ConnectException, is NoRouteToHostException, is SocketTimeoutException -> UNREACHABLE
        is SSLException -> TLS
        is IOException -> INTERRUPTED
        else -> INTERRUPTED
    }
}
