package fr.qwartz.mika.data.net

/**
 * L'heure d'un message du fil, en millisecondes. Le serveur l'envoie en millisecondes
 * (`protocol.py::history_item`, `row.at // 1000` depuis des microsecondes), mais un ancien serveur,
 * ou un autre, a pu envoyer des secondes ou des microsecondes : l'ordre de grandeur suffit à trancher.
 */
object Timestamps {
    /** En dessous : des secondes (en millisecondes, ce serait avant 1973). */
    private const val SECONDS_BELOW = 1e11
    /** Au-dessus : des microsecondes (en millisecondes, ce serait après l'an 5000). */
    private const val MICROS_ABOVE = 1e14
    /** Au-dessus : des nanosecondes. */
    private const val NANOS_ABOVE = 1e17

    fun normalize(raw: Double?, nowMs: Long): Long {
        if (raw == null || raw.isNaN() || raw <= 0.0) return nowMs
        return when {
            raw < SECONDS_BELOW -> (raw * 1000).toLong()
            raw > NANOS_ABOVE -> (raw / 1_000_000).toLong()
            raw > MICROS_ABOVE -> (raw / 1000).toLong()
            else -> raw.toLong()
        }
    }
}
