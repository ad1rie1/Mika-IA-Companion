package fr.qwartz.mika.avatar3d

import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min

/**
 * Les os des yeux : où Mika regarde, en plus de ce que la tête fait déjà (`GazeController.ts`).
 *
 * Les clips n'animent pas les yeux, donc ces écritures absolues ne se battent avec rien. La composition, en angles
 * sémantiques ([GazeAngles] : pitch > 0 vers le bas, yaw > 0 vers sa gauche) :
 *
 *   contact · (direction du spectateur, mesurée dans la tête FINALE)
 *   + biais de l'émotion · intensité
 *   + décalage de l'attention (détournement / réflexion / murmure)
 *   + bougé de la saccade
 *
 * Le terme du spectateur est mesuré après toutes les couches de la tête : c'est le reste que la tête n'a pas couvert
 * — le réflexe vestibulo-oculaire : le clip tourne la tête, les yeux contre-tournent, le contact tient. Il est
 * appliqué sans filtre (le réflexe prend ~10 ms chez l'humain) ; tout le reste est un saut décidé par
 * [AttentionDirector], suivi d'un adoucissement de ~30 ms qui se lit comme une saccade, jamais comme une glissade.
 *
 * La course de l'œil est prudente : passé l'angle que le modèle permet, un œil VRM montre le blanc. Les yeux
 * s'arrêtent au coin, et la tête ([HeadAttentionOverlay]) porte le reste.
 *
 * @param eyeRange jusqu'où l'os de l'œil peut tourner sur CE modèle (rad, par axe). Les bornes du web
 *   ([EYE_MAX_YAW] 17°, [EYE_MAX_PITCH] 12,6°) restent les bornes du regard ; la plus petite des deux s'applique.
 */
class GazeController(eyeRange: Float = MIKA_EYE_RANGE) {
    val maxYaw: Float = min(EYE_MAX_YAW, eyeRange)
    val maxPitch: Float = min(EYE_MAX_PITCH, eyeRange)

    /** Les angles appliqués (relatifs à la tête), adoucis vers la cible — pour les tests et le débogage. */
    var applied: GazeAngles = GazeAngles.ZERO
        private set

    fun update(dt: Float, ctx: BodyContext, rig: AvatarRig, pose: Pose, intent: GazeIntent?) {
        val head = pose["head"] ?: return
        val hasLeft = pose["leftEye"] != null
        val hasRight = pose["rightEye"] != null
        if (!hasLeft && !hasRight) return

        var tp: Float
        var ty: Float
        if (!ctx.awake) {
            tp = EYE_SLEEP_PITCH
            ty = 0f
        } else {
            val bias = EMOTION_GAZE_BIAS[ctx.emotion] ?: GazeAngles.ZERO
            // Une réflexion légère bouge à peine le regard, une forte regarde clairement ailleurs.
            val biasScale = 0.3f + ctx.intensity * 0.7f
            tp = bias.pitch * biasScale
            ty = bias.yaw * biasScale

            if (intent != null) {
                val viewer = ctx.viewer
                if (intent.contact > 0f && viewer != null) {
                    val d = BodyMath.viewerInHead(rig, pose, viewer)
                    if (d != null) {
                        val v = BodyMath.directionToGaze(d)
                        // Seulement ce que l'œil peut atteindre : un spectateur au-delà du coin de l'œil est regardé
                        // aussi loin que l'œil va.
                        tp += intent.contact * v.pitch.coerceIn(-maxPitch, maxPitch)
                        ty += intent.contact * v.yaw.coerceIn(-maxYaw, maxYaw)
                    }
                }
                tp += intent.offset.pitch + intent.saccade.pitch
                ty += intent.offset.yaw + intent.saccade.yaw
            }
            tp = tp.coerceIn(-maxPitch, maxPitch)
            ty = ty.coerceIn(-maxYaw, maxYaw)
        }

        val k = 1 - exp(-max(0f, dt) / EYE_TAU)
        applied = GazeAngles(applied.pitch + (tp - applied.pitch) * k, applied.yaw + (ty - applied.yaw) * k)

        // Une rotation locale à la tête, comme l'os normalisé du web : dans la pose (orientations monde), tête · regard.
        val eye = (head * BodyMath.gazeToQuaternion(applied)).normalized()
        if (hasLeft) pose["leftEye"] = eye
        if (hasRight) pose["rightEye"] = eye
    }

    companion object {
        const val EYE_MAX_YAW = 0.3f
        const val EYE_MAX_PITCH = 0.22f

        /** ~2 images : l'œil se pose, il ne glisse pas. */
        const val EYE_TAU = 0.03f

        /** Endormie : paupières closes, les yeux reposent un peu vers le bas, comme ceux d'une dormeuse. */
        const val EYE_SLEEP_PITCH = 0.06f

        /**
         * La course de l'œil du VRM de Mika : son `lookAt` de type « Bone » donne 10° de rotation d'os au plus sur
         * chaque axe (`curve [0,0,0,1, 1,1,1,0]`, `xRange 90 → yRange 10`). Au-delà, l'iris quitte l'orbite.
         */
        const val MIKA_EYE_RANGE = 0.17453292f // 10°

        /** Émotion → biais de regard tenu (la base autour de laquelle les saccades bougent). */
        val EMOTION_GAZE_BIAS: Map<String, GazeAngles> = mapOf(
            "embarrassed" to GazeAngles(0.08f, -0.08f), // en bas, ailleurs : elle détourne
            "scared" to GazeAngles(0.1f, 0.06f), // en bas, de côté, tendue
            "jealous" to GazeAngles(0.05f, -0.1f), // un regard de côté
            "anxious" to GazeAngles(0.06f, 0.04f), // en bas, instable
            "lonely" to GazeAngles(0.06f, 0.0f), // en bas, au centre
            "sad" to GazeAngles(0.08f, 0.0f),
            "melancholic" to GazeAngles(0.07f, -0.02f),
            "bored" to GazeAngles(0.0f, 0.1f), // regarde ailleurs
            "thinking" to GazeAngles(-0.06f, 0.08f), // en haut et de côté
            "curious" to GazeAngles(-0.04f, 0.06f), // un peu en haut
            "confused" to GazeAngles(-0.02f, -0.05f),
            "dreamy" to GazeAngles(-0.05f, 0.0f), // le regard en haut, vague
            "love" to GazeAngles(0.0f, 0.0f), // le contact franc
            "grateful" to GazeAngles(0.0f, 0.0f),
            "proud" to GazeAngles(-0.02f, 0.0f), // le menton un peu levé
            "determined" to GazeAngles(0.0f, 0.0f),
            // Les émotions sans entrée gardent un contact et des saccades ordinaires.
        )
    }
}
