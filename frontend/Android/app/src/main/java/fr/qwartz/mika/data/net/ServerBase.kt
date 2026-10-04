package fr.qwartz.mika.data.net

import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

/**
 * L'adresse du serveur, telle que saisie à la connexion (LAN, Tailscale ou https://…), mise en forme
 * canonique : un schéma, un hôte, un port s'il n'est pas celui par défaut, un préfixe de chemin
 * éventuel (un mandataire qui sert Mika sous `/mika`), jamais de `/` final.
 */
class ServerBase private constructor(private val url: HttpUrl) {

    /** `https://mika.example.ts.net` ou `http://192.168.1.20:8001/mika`. */
    val canonical: String = url.toString().removeSuffix("/")
    val scheme: String get() = url.scheme
    val host: String get() = url.host
    val port: Int get() = url.port
    val isHttps: Boolean get() = url.isHttps
    val isLoopback: Boolean get() = isLoopbackHost(url.host)
    val isTailscale: Boolean get() = isTailscaleHost(url.host)
    val isLan: Boolean get() = isPrivateHost(url.host)
    /** En clair sur un réseau : ce que l'écran de connexion signale. */
    val isInsecure: Boolean get() = !isHttps && !isLoopback

    /** `hôte:port`, pour les messages d'erreur. */
    val hostPort: String get() = if (host.contains(':')) "[$host]:$port" else "$host:$port"

    private val prefix: String = url.encodedPath.removeSuffix("/")

    /** Une route HTTP sous ce serveur (`/auth/token`, `/files/<id>`). */
    fun http(path: String): HttpUrl =
        url.newBuilder().encodedPath(prefix + "/" + path.removePrefix("/")).build()

    /** L'adresse de la socket : `ws://…/ws` ou `wss://…/ws`. */
    fun ws(): String {
        val http = http(MikaProtocol.PATH_WS).toString()
        return if (isHttps) "wss" + http.removePrefix("https") else "ws" + http.removePrefix("http")
    }

    /** Même schéma, même hôte, même port : le jeton ne part que vers son serveur. */
    fun sameOrigin(other: HttpUrl): Boolean =
        other.scheme == url.scheme && other.host == url.host && other.port == url.port

    override fun equals(other: Any?): Boolean = other is ServerBase && other.canonical == canonical
    override fun hashCode(): Int = canonical.hashCode()
    override fun toString(): String = canonical

    sealed interface Parsed {
        data class Ok(val base: ServerBase) : Parsed
        data class Error(val message: String) : Parsed
    }

    companion object {
        fun parse(input: String): Parsed {
            val raw = input.trim()
            if (raw.isEmpty()) return Parsed.Error("Indique l'adresse du serveur.")
            val withScheme = if ("://" in raw) raw else "http://$raw"
            val scheme = withScheme.substringBefore("://").lowercase()
            if (scheme != "http" && scheme != "https") {
                return Parsed.Error("Adresse invalide : elle commence par http:// ou https://.")
            }
            val url = withScheme.toHttpUrlOrNull() ?: return Parsed.Error("Adresse invalide.")
            if (url.encodedQuery != null || url.encodedFragment != null || '?' in raw || '#' in raw) {
                return Parsed.Error("L'adresse ne doit contenir ni « ? » ni « # ».")
            }
            if (url.username.isNotEmpty() || url.password.isNotEmpty()) {
                return Parsed.Error("L'adresse ne doit pas contenir d'identifiants.")
            }
            val path = url.encodedPath.trimEnd('/').ifEmpty { "/" }
            return Parsed.Ok(ServerBase(url.newBuilder().encodedPath(path).build()))
        }

        /** Relire une adresse déjà canonique (gardée en réglage) ; `null` si elle ne l'est plus. */
        fun fromCanonical(value: String?): ServerBase? =
            value?.let { (parse(it) as? Parsed.Ok)?.base }

        fun isLoopbackHost(host: String): Boolean {
            val h = host.lowercase()
            if (h == "localhost" || h.endsWith(".localhost") || h == "::1") return true
            val v4 = ipv4(h) ?: return false
            return v4[0] == 127
        }

        /** MagicDNS (`*.ts.net`) ou l'espace CGNAT que Tailscale attribue (100.64.0.0/10). */
        fun isTailscaleHost(host: String): Boolean {
            val h = host.lowercase()
            if (h.endsWith(".ts.net")) return true
            val v4 = ipv4(h) ?: return false
            return v4[0] == 100 && v4[1] in 64..127
        }

        fun isPrivateHost(host: String): Boolean {
            val h = host.lowercase()
            if (h.endsWith(".local") || h.endsWith(".lan") || h.endsWith(".home.arpa")) return true
            if (h.startsWith("fe80:") || h.startsWith("fc") || h.startsWith("fd")) return ':' in h
            val v4 = ipv4(h) ?: return false
            return v4[0] == 10 ||
                (v4[0] == 172 && v4[1] in 16..31) ||
                (v4[0] == 192 && v4[1] == 168) ||
                (v4[0] == 169 && v4[1] == 254)
        }

        private fun ipv4(host: String): IntArray? {
            val parts = host.split('.')
            if (parts.size != 4) return null
            val out = IntArray(4)
            for ((i, p) in parts.withIndex()) {
                val n = p.toIntOrNull() ?: return null
                if (n !in 0..255) return null
                out[i] = n
            }
            return out
        }
    }
}
