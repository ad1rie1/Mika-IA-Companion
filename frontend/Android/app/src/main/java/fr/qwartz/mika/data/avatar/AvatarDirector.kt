package fr.qwartz.mika.data.avatar

import fr.qwartz.mika.data.mind.MindLabels
import fr.qwartz.mika.data.mind.MindState
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

/**
 * Quel portrait montrer, d'après ce que l'app sait d'elle. Les règles, dans l'ordre :
 *
 * 1. endormie → « sleep » : rien ne la réveille à l'écran, ni un coucou ni un message ;
 * 2. on vient de la retrouver après une vraie absence ([greeting]) et son humeur le permet → « wave »,
 *    le temps d'un salut ; sinon un simple hochement, qui laisse son visage au portrait ;
 * 3. elle écrit → « thinking » : la main au menton pendant « Mika écrit… » ;
 * 4. son humeur, si elle est assez marquée (le portrait de l'émotion) — sinon « tired » quand
 *    l'énergie est basse, « neutral » au repos.
 *
 * Un portrait absent des assets retombe sur « neutral » : une app construite avec une partie des
 * rendus montre ce qu'elle a. Pur, testé sans Android.
 */
object AvatarDirector {
    const val NEUTRAL = "neutral"
    const val WAVE = "wave"
    const val THINKING = "thinking"
    const val TIRED = "tired"
    const val SLEEP = "sleep"

    /**
     * En dessous, l'émotion se lit « à peine » : le visage au repos. Le portrait d'une émotion est
     * rendu à pleine intensité, il exagérerait une humeur légère.
     */
    const val MIN_INTENSITY = 0.25

    /** L'énergie sous laquelle elle a l'air fatiguée (le web alourdit les paupières sous 0,55). */
    const val TIRED_ENERGY = 0.3

    /** Une émotion plus forte que ça se voit même fatiguée. */
    const val TIRED_OVERRIDE = 0.5

    /**
     * Une émotion négative au moins aussi marquée (blessée, fâchée…) : pas de coucou joyeux à qui revient,
     * un hochement, et son visage reste le sien.
     */
    const val COLD_GREETING_INTENSITY = 0.4

    /** Revenir plus tôt n'est pas « se retrouver » : aucun salut. */
    const val NOD_AFTER_MS = 20 * 60_000L

    /** Au-delà, et dans une autre demi-journée, l'absence vaut un vrai coucou. */
    const val WAVE_AFTER_MS = 6 * 3_600_000L

    /** Avant cette heure, la nuit compte encore avec la veille au soir. */
    const val NIGHT_END_HOUR = 5

    /** La lumière autour d'elle : la famille de l'émotion, ou la nuit. */
    enum class Aura { NEUTRAL, WARM, COOL, DUSK, NIGHT }

    /** Ses retrouvailles : rien, un regard et un hochement, ou un coucou de la main. */
    enum class Greeting { NONE, NOD, WAVE }

    data class Scene(
        val portrait: String,
        val aura: Aura,
        val asleep: Boolean = false,
        /** Le geste de retrouvailles qu'elle fait vraiment, une fois son sommeil, son humeur et sa fatigue lus. */
        val greeting: Greeting = Greeting.NONE,
    )

    fun scene(mind: MindState?, mikaTyping: Boolean, greeting: Greeting, available: Set<String>): Scene {
        fun pick(id: String) = if (id in available) id else NEUTRAL
        if (mind?.asleep == true) return Scene(pick(SLEEP), Aura.NIGHT, asleep = true)

        val mood = mind?.mood
        val emotion = mood?.emotion?.trim()?.lowercase()
        val intensity = mood?.intensity ?: 0.0
        val tired = (mind?.energy ?: 1.0) < TIRED_ENERGY
        val reunion = allowed(greeting, emotion, intensity, tired)
        if (reunion == Greeting.WAVE) return Scene(pick(WAVE), Aura.WARM, greeting = reunion)

        val strong = emotion != null && MindLabels.isEmotionName(emotion) && intensity >= MIN_INTENSITY
        val face = when {
            mikaTyping -> Scene(pick(THINKING), Aura.DUSK)
            strong && !(tired && intensity < TIRED_OVERRIDE) -> Scene(pick(emotion!!), auraOf(emotion))
            tired -> Scene(pick(TIRED), Aura.NEUTRAL)
            else -> Scene(NEUTRAL, Aura.NEUTRAL)
        }
        return face.copy(greeting = reunion)
    }

    /**
     * Les retrouvailles, à la mesure de l'absence (en heure murale : elle survit à la mort du processus).
     * Moins de [NOD_AFTER_MS] : rien. Moins de [WAVE_AFTER_MS], ou dans la même demi-journée : elle lève les
     * yeux et hoche la tête. Au-delà — après sa nuit, au retour de vacances — un coucou ; jamais vue non plus.
     * Ainsi, au plus un coucou par demi-journée. Une horloge qui recule se lit comme une absence nulle.
     */
    fun greeting(lastSeenWallMs: Long?, nowWallMs: Long, zone: ZoneId): Greeting {
        if (lastSeenWallMs == null) return Greeting.WAVE
        val away = nowWallMs - lastSeenWallMs
        return when {
            away < NOD_AFTER_MS -> Greeting.NONE
            away < WAVE_AFTER_MS || halfDay(lastSeenWallMs, zone) == halfDay(nowWallMs, zone) -> Greeting.NOD
            else -> Greeting.WAVE
        }
    }

    /**
     * Le salut que son humeur permet : blessée ou fâchée, elle ne fait pas coucou à qui revient ; fatiguée,
     * le coucou se réduit au hochement.
     */
    private fun allowed(greeting: Greeting, emotion: String?, intensity: Double, tired: Boolean): Greeting {
        if (greeting != Greeting.WAVE) return greeting
        val upset = emotion != null &&
            MindLabels.EMOTIONS[emotion]?.category == MindLabels.Category.NEGATIVE &&
            intensity >= COLD_GREETING_INTENSITY
        return if (upset || tired) Greeting.NOD else Greeting.WAVE
    }

    /**
     * La demi-journée d'un instant : le matin jusqu'à midi, puis l'après-midi et le soir. La nuit compte avec
     * la veille au soir : se quitter à 1 h et se revoir à 9 h, c'est la retrouver après sa nuit.
     */
    private fun halfDay(wallMs: Long, zone: ZoneId): Pair<LocalDate, Boolean> {
        val t = Instant.ofEpochMilli(wallMs).atZone(zone).minusHours(NIGHT_END_HOUR.toLong())
        return t.toLocalDate() to (t.hour < 12 - NIGHT_END_HOUR)
    }

    fun auraOf(emotion: String): Aura = when (MindLabels.EMOTIONS[emotion]?.category) {
        MindLabels.Category.POSITIVE -> Aura.WARM
        MindLabels.Category.NEGATIVE -> Aura.COOL
        MindLabels.Category.COMPLEX -> Aura.DUSK
        else -> Aura.NEUTRAL
    }
}
