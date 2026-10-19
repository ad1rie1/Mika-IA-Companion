package fr.qwartz.mika.ui.chat

import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * De quand datait la position qu'elle a regardée (ADR 0119), telle que sa petite bulle le dit : « 📍 Mika a regardé
 * où tu es · lieu · position de 14:10 ». Pur : l'heure de sa réponse et le fuseau sont passés.
 */
object LookedNote {
    /** Une mesure plus jeune que ça, au moment de sa réponse, est « maintenant » : la bulle n'en dit pas l'heure. */
    const val FRESH_MS = 2 * 60_000L

    private val DAY = DateTimeFormatter.ofPattern("dd/MM", Locale.FRENCH)
    private val DAY_YEAR = DateTimeFormatter.ofPattern("dd/MM/yyyy", Locale.FRENCH)
    private val SPOKEN_DAY = DateTimeFormatter.ofPattern("d MMMM", Locale.FRENCH)
    private val SPOKEN_DAY_YEAR = DateTimeFormatter.ofPattern("d MMMM yyyy", Locale.FRENCH)

    /** L'âge de la mesure, en mots : rien, son heure, ou son jour et son heure ; chacun écrit et dit. */
    sealed interface FixAge {
        /** Mesurée juste avant sa réponse (moins de [FRESH_MS]), ou de quand, on ne sait pas : rien à dire. */
        data object Fresh : FixAge

        /** Plus tôt le jour de sa réponse : « position de 14:10 ». */
        data class SameDay(val time: String, val spokenTime: String) : FixAge

        /** Un autre jour (l'année, si elle diffère) : « position du 18/10 à 14:10 ». */
        data class OtherDay(val date: String, val spokenDate: String, val time: String, val spokenTime: String) : FixAge
    }

    /**
     * De quand datait la mesure [at] au moment de sa réponse [messageTs] (millisecondes) : l'heure seulement si elle
     * a au moins [FRESH_MS] de plus que la réponse ; le jour aussi si elle n'est pas du même jour (dans [zone]).
     */
    fun age(at: Long, messageTs: Long, zone: ZoneId): FixAge {
        if (at <= 0 || messageTs - at < FRESH_MS) return FixAge.Fresh
        val time = BubbleContent.time(at, zone)
        val spoken = BubbleContent.spokenTime(at, zone)
        val fixDay = Instant.ofEpochMilli(at).atZone(zone).toLocalDate()
        val replyDay = Instant.ofEpochMilli(messageTs).atZone(zone).toLocalDate()
        if (fixDay == replyDay) return FixAge.SameDay(time, spoken)
        val sameYear = fixDay.year == replyDay.year
        return FixAge.OtherDay(
            date = (if (sameYear) DAY else DAY_YEAR).format(fixDay),
            spokenDate = (if (sameYear) SPOKEN_DAY else SPOKEN_DAY_YEAR).format(fixDay),
            time = time,
            spokenTime = spoken,
        )
    }
}
