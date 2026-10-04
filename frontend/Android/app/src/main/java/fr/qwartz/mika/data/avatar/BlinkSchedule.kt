package fr.qwartz.mika.data.avatar

import kotlin.random.Random

/**
 * Quand elle cligne des yeux. Une personne cligne toutes les 2 à 6 secondes, irrégulièrement, et
 * parfois deux fois de suite ; un rythme fixe se repère tout de suite (le web l'a appris avec son
 * `BlinkController`). Pur : le hasard est passé en paramètre.
 */
object BlinkSchedule {
    /** Les yeux fermés : assez pour être vu, trop court pour être lu comme un regard baissé. */
    const val CLOSED_MS = 110L

    /** Entre les deux d'un double clignement. */
    const val DOUBLE_GAP_MS = 140L

    const val MIN_GAP_MS = 2_200L
    const val MAX_GAP_MS = 6_400L
    const val DOUBLE_CHANCE = 0.15

    /** L'attente avant le prochain clignement ; plus longue quand elle est fatiguée (des paupières lourdes). */
    fun nextGapMs(random: Random, tired: Boolean = false): Long {
        // La somme de deux tirages : rarement aux extrêmes, comme un vrai rythme.
        val t = (random.nextDouble() + random.nextDouble()) / 2
        val gap = MIN_GAP_MS + (t * (MAX_GAP_MS - MIN_GAP_MS)).toLong()
        return if (tired) gap * 3 / 2 else gap
    }

    fun isDouble(random: Random): Boolean = random.nextDouble() < DOUBLE_CHANCE
}
