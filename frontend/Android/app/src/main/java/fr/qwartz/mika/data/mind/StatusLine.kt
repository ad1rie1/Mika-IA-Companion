package fr.qwartz.mika.data.mind

import fr.qwartz.mika.data.net.LinkState
import kotlin.math.ceil

/**
 * La ligne sous son nom, par priorité : un problème de lien d'abord (on ne dit pas « éveillée » de
 * quelqu'un qu'on ne joint pas), puis « en train d'écrire… », puis son sommeil, puis ce qu'elle fait.
 */
object StatusLine {
    /** En dessous, l'émotion n'est pas assez marquée pour être dite. */
    const val EMOTION_MIN_INTENSITY = 0.25

    /**
     * [nowWallMs] (heure murale) éteint une occupation minutée passé sa fin prévue, sans attendre de trame ;
     * `null` : on s'en tient à ce que dit la dernière trame.
     */
    fun of(link: LinkState, typing: Boolean, mind: MindState?, nowElapsedMs: Long, nowWallMs: Long? = null): String {
        linkProblem(link, nowElapsedMs)?.let { return it }
        if (typing) return "en train d'écrire…"
        if (mind == null) return "en ligne"
        when (mind.sleepPhase) {
            SleepPhases.LIGHT -> return "dort"
            SleepPhases.REM -> return "dort · rêve"
            SleepPhases.DEEP -> return "dort profondément"
        }
        val parts = mutableListOf("éveillée")
        // « dessine à son bureau » : ce qu'elle fait, puis où
        val doing = mind.activity
            ?.takeIf { a -> nowWallMs == null || a.until == null || a.until > nowWallMs }
            ?.let { MindLabels.activity(it.name, it.label) }
        val where = listOfNotNull(doing, MindLabels.place(mind.place))
        if (where.isNotEmpty()) parts += where.joinToString(" ")
        val mood = mind.mood
        if (mood != null && mood.emotion != "neutral" && mood.intensity >= EMOTION_MIN_INTENSITY) {
            parts += MindLabels.emotionLower(mood.emotion)
        }
        return parts.joinToString(" · ")
    }

    fun linkProblem(link: LinkState, nowElapsedMs: Long): String? = when (link) {
        LinkState.Online -> null
        LinkState.Connecting -> "connexion…"
        LinkState.Idle -> "hors ligne"
        LinkState.NoNetwork -> "pas de réseau"
        LinkState.SessionExpired -> "session expirée"
        is LinkState.Refused -> "connexion refusée"
        is LinkState.Offline -> {
            val seconds = ceil((link.retryAtElapsedMs - nowElapsedMs) / 1000.0).toLong()
            if (seconds <= 0) "connexion…" else "hors ligne · nouvel essai dans $seconds s"
        }
    }
}
