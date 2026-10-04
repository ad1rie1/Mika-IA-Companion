package fr.qwartz.mika.core

/** Un journal injectable : le cœur reste du Kotlin pur, testable sur la JVM. */
fun interface Logger {
    fun log(level: Level, tag: String, message: String, error: Throwable?)

    enum class Level { DEBUG, INFO, WARN, ERROR }

    fun d(tag: String, message: String) = log(Level.DEBUG, tag, Redact.secrets(message), null)
    fun i(tag: String, message: String) = log(Level.INFO, tag, Redact.secrets(message), null)
    fun w(tag: String, message: String, error: Throwable? = null) =
        log(Level.WARN, tag, Redact.secrets(message), error)
    fun e(tag: String, message: String, error: Throwable? = null) =
        log(Level.ERROR, tag, Redact.secrets(message), error)

    companion object {
        val NONE = Logger { _, _, _, _ -> }
    }
}

/** Un jeton ne doit jamais atteindre un journal, même glissé dans un message d'erreur. */
object Redact {
    private val TOKEN = Regex("""mw_[A-Za-z0-9_\-]+""")
    private val BEARER = Regex("""(?i)(bearer\s+)\S+""")

    fun secrets(text: String): String =
        BEARER.replace(TOKEN.replace(text, "mw_…")) { it.groupValues[1] + "…" }
}
