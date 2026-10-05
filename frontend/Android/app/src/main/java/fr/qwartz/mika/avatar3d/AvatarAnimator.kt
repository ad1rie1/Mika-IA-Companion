package fr.qwartz.mika.avatar3d

import kotlin.math.min

/**
 * Le corps de Mika dans le temps : un mouvement en cours (une attente qui boucle, un geste) et, pendant un
 * changement, le précédent qui s'efface. Le fondu est une interpolation os par os des deux poses (jamais deux images
 * superposées) : une attente qui passe à une autre glisse, un geste démarre d'où le corps était. Pur : testé sur la
 * JVM.
 */
class AvatarAnimator(private val rig: AvatarRig) {
    val pose: Pose = rig.newPose()
    private val fromPose = rig.newPose()

    private var current: MotionClip? = null
    private var currentTime = 0f
    private var currentLoop = true
    private var previous: MotionClip? = null
    private var previousTime = 0f
    private var previousLoop = true
    private var previousScale = 1f

    /** La vitesse de lecture du clip en cours (l'humeur la règle, ± le tirage de chaque choix). */
    var timeScale = 1f
    private var fade = 1f
    private var fadeDuration = 0.5f

    /** Le clip en cours, et s'il est fini (un geste joué une fois). */
    val clip: MotionClip? get() = current
    val finished: Boolean get() = current?.let { !currentLoop && currentTime >= it.duration } ?: true
    val time: Float get() = currentTime
    val duration: Float get() = current?.duration ?: 0f

    /** Le temps restant avant la fin du clip en cours, à la vitesse actuelle (l'infini s'il boucle). */
    val remaining: Float
        get() = current?.let { if (currentLoop) Float.POSITIVE_INFINITY else (it.duration - currentTime) / timeScale.coerceAtLeast(1e-4f) }
            ?: 0f

    /**
     * Joue `clip` depuis `at` (son début par défaut), en fondant depuis la pose actuelle sur `fadeSeconds`.
     * `loop` impose de boucler ou non (un geste « tenu » comme réfléchir boucle, une attente aussi) ; par défaut,
     * ce que dit le mouvement.
     */
    fun play(clip: MotionClip, fadeSeconds: Float = 0.5f, at: Float = 0f, loop: Boolean = clip.loop, timeScale: Float = 1f) {
        if (current != null && fadeSeconds > 0f) {
            previous = current
            previousTime = currentTime
            previousLoop = currentLoop
            previousScale = this.timeScale
            fade = 0f
            fadeDuration = fadeSeconds
        } else {
            previous = null
            fade = 1f
        }
        current = clip
        currentTime = at
        currentLoop = loop
        this.timeScale = timeScale
    }

    /** Avance de `dt` secondes et calcule [pose]. */
    fun update(dt: Float): Pose {
        val c = current ?: return pose
        currentTime += dt * timeScale
        c.sample(currentTime, pose, currentLoop)
        val p = previous
        if (p != null && fade < 1f) {
            previousTime += dt * previousScale
            p.sample(previousTime, fromPose, previousLoop)
            fade = min(1f, fade + dt / fadeDuration)
            // De l'ancienne pose vers la nouvelle, avec une courbe douce.
            val t = fade * fade * (3 - 2 * fade)
            fromPose.blendTowards(pose, t)
            pose.copyFrom(fromPose)
            if (fade >= 1f) previous = null
        }
        return pose
    }
}
