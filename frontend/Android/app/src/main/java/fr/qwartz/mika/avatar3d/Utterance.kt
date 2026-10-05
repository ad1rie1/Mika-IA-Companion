package fr.qwartz.mika.avatar3d

import kotlin.math.min

/**
 * Une réplique de Mika « dite » : l'app n'a pas de voix, alors sa réponse s'écrit dans la bulle pendant que sa bouche
 * la prononce. Une seule horloge pour les deux — le texte affiché et le curseur de la bouche se lisent ici, au même
 * instant (`System.nanoTime`, la base du `Choreographer` et de `withFrameNanos`), si bien qu'ils ne peuvent pas se
 * décaler.
 *
 * `text` est le texte tel que la bulle le montre, sans les marques du Markdown ([fr.qwartz.mika.ui.components.InlineMarkup.plain]) :
 * ce qu'on voit est ce qu'elle dit. Toucher la bulle ([skippedAtNanos]) affiche tout d'un coup et lui ferme la bouche.
 */
data class Utterance(
    /** La clé de la bulle (celle de la liste du fil). */
    val key: String,
    val text: String,
    val startNanos: Long,
    val charsPerSecond: Float,
    val skippedAtNanos: Long? = null,
) {
    val length: Int get() = text.length

    private val naturalEndNanos: Long
        get() = startNanos + (length / charsPerSecond.coerceAtLeast(1f) * 1e9f).toLong()

    /** Quand elle a fini de la dire : plus tôt si la personne a tout affiché, même avant qu'elle ne commence. */
    val endNanos: Long get() = skippedAtNanos?.let { min(it, naturalEndNanos) } ?: naturalEndNanos

    /** Combien de caractères sont dits à `now`, avec leur fraction (le dernier apparaît en fondu). */
    fun revealAt(now: Long): Float = when {
        skippedAtNanos != null && now >= skippedAtNanos -> length.toFloat()
        now <= startNanos -> 0f
        else -> min(length.toFloat(), (now - startNanos) / 1e9f * charsPerSecond)
    }

    /** Le caractère que sa bouche prononce à `now`. */
    fun cursorAt(now: Long): Int = revealAt(now).toInt()

    fun started(now: Long): Boolean = now >= startNanos

    fun finished(now: Long): Boolean = now >= endNanos

    companion object {
        /** Le débit d'une parole posée : un peu moins de 16 caractères par seconde, espaces compris. */
        const val SPEAKING_CPS = 16f

        /** Une longue réponse accélère, jusque-là : au-delà, la bouche ne serait plus qu'un frémissement. */
        const val MAX_CPS = 34f

        /** La durée visée d'une réponse ordinaire ; plus long, elle parle plus vite plutôt que de faire attendre. */
        const val TARGET_SECONDS = 7f

        /** Entre deux bulles dites l'une après l'autre : le temps d'un souffle. */
        const val GAP_NANOS = 350_000_000L

        fun charsPerSecond(length: Int): Float = (length / TARGET_SECONDS).coerceIn(SPEAKING_CPS, MAX_CPS)
    }
}
