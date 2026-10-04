package fr.qwartz.mika.data.avatar

import fr.qwartz.mika.data.mind.MindLabels
import fr.qwartz.mika.data.mind.MindState

/**
 * Quel portrait montrer, d'après ce que l'app sait d'elle. Les règles, dans l'ordre :
 *
 * 1. endormie → « sleep » : rien ne la réveille à l'écran, ni un coucou ni un message ;
 * 2. on vient de la retrouver → « wave », le temps d'un salut ;
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

    /** La lumière autour d'elle : la famille de l'émotion, ou la nuit. */
    enum class Aura { NEUTRAL, WARM, COOL, DUSK, NIGHT }

    data class Scene(
        val portrait: String,
        val aura: Aura,
        val asleep: Boolean = false,
    )

    fun scene(mind: MindState?, mikaTyping: Boolean, greeting: Boolean, available: Set<String>): Scene {
        fun pick(id: String) = if (id in available) id else NEUTRAL
        if (mind?.asleep == true) return Scene(pick(SLEEP), Aura.NIGHT, asleep = true)
        if (greeting) return Scene(pick(WAVE), Aura.WARM)
        if (mikaTyping) return Scene(pick(THINKING), Aura.DUSK)

        val mood = mind?.mood
        val emotion = mood?.emotion?.trim()?.lowercase()
        val intensity = mood?.intensity ?: 0.0
        val tired = (mind?.energy ?: 1.0) < TIRED_ENERGY
        val strong = emotion != null && MindLabels.isEmotionName(emotion) && intensity >= MIN_INTENSITY
        return when {
            strong && !(tired && intensity < TIRED_OVERRIDE) -> Scene(pick(emotion!!), auraOf(emotion))
            tired -> Scene(pick(TIRED), Aura.NEUTRAL)
            else -> Scene(NEUTRAL, Aura.NEUTRAL)
        }
    }

    fun auraOf(emotion: String): Aura = when (MindLabels.EMOTIONS[emotion]?.category) {
        MindLabels.Category.POSITIVE -> Aura.WARM
        MindLabels.Category.NEGATIVE -> Aura.COOL
        MindLabels.Category.COMPLEX -> Aura.DUSK
        else -> Aura.NEUTRAL
    }
}
