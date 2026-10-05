package fr.qwartz.mika.avatar3d

/**
 * Ce que chaque émotion fait au CORPS — `frontend/Web/src/vtuber/animation/gestures.ts`, recopié à l'identique.
 * Le visage, le regard et le port de tête réagissent toujours ; un geste n'est qu'un plus, jamais nécessaire.
 *  - oneshot : un geste joué une fois, puis retour à l'attente ;
 *  - idleVariant : l'attente est remplacée par une posture (épaules tombantes, regard qui fuit…) tant qu'elle dure ;
 *  - none : le visage et la tête portent l'émotion seuls — c'est voulu.
 */
object Gestures {
    enum class Kind { NONE, ONESHOT, IDLE_VARIANT }

    data class Mapping(val kind: Kind, val clip: String? = null, val minIntensity: Float = DEFAULT_MIN_INTENSITY)

    sealed interface Decision {
        data class None(val reason: String) : Decision
        data class Oneshot(val clip: String) : Decision
        data class IdleVariant(val clip: String) : Decision
    }

    const val GESTURE_COOLDOWN_S = 8f
    const val DEFAULT_MIN_INTENSITY = 0.6f

    /**
     * Marge d'hystérésis des postures : l'humeur du serveur oscille autour de son équilibre après une impulsion,
     * et un seuil sans marge ferait entrer et sortir de la posture à chaque oscillation.
     */
    const val VARIANT_HYSTERESIS = 0.08f

    /** Deux émotions presque à égalité : le corps reste immobile (l'immobilité se lit ambivalente). */
    const val AMBIVALENCE_RATIO = 0.85f

    private fun none() = Mapping(Kind.NONE)
    private fun once(clip: String, min: Float) = Mapping(Kind.ONESHOT, clip, min)
    private fun posture(clip: String, min: Float) = Mapping(Kind.IDLE_VARIANT, clip, min)

    val EMOTION_GESTURE: Map<String, Mapping> = mapOf(
        "neutral" to none(),
        "happy" to once("gesture_excited", 0.85f),
        "excited" to once("gesture_excited", 0.55f),
        "love" to none(),
        "proud" to none(),
        "grateful" to once("gesture_nod", 0.7f),
        "playful" to once("gesture_laugh", 0.75f),
        "amused" to once("gesture_laugh", 0.65f),
        "hopeful" to none(),
        "relieved" to once("gesture_sigh", 0.7f),
        "sad" to posture("idle_sad", 0.6f),
        "angry" to once("gesture_angry", 0.65f),
        "scared" to none(),
        "disgusted" to once("gesture_headshake", 0.7f),
        "frustrated" to once("gesture_headshake", 0.65f),
        "lonely" to posture("idle_sad", 0.6f),
        "anxious" to posture("idle_nervous", 0.55f),
        "bored" to posture("idle_bored", 0.5f),
        "jealous" to none(),
        "surprised" to once("gesture_surprised", 0.55f),
        "thinking" to once("gesture_think", 0.6f),
        "confused" to once("gesture_think", 0.7f),
        "embarrassed" to once("gesture_bashful", 0.6f),
        "nostalgic" to none(),
        "dreamy" to none(),
        "determined" to none(),
        "mischievous" to none(),
        "curious" to none(),
        "melancholic" to posture("idle_sad", 0.6f),
    )

    /** Les gestes portés par la prosodie ([SIGH], [LAUGH]) : hors délai de recharge, pas hors sommeil. */
    val CUE_GESTURE: Map<String, String?> = mapOf("sigh" to "gesture_sigh", "laugh" to "gesture_laugh", "breath" to null)

    data class Input(
        val emotion: String,
        val intensity: Float,
        val blend: List<Pair<String, Float>> = emptyList(),
        val persona: String? = null,
        val sleepPhase: String = "awake",
        val nowSeconds: Float,
        val lastOneshotAt: Float?,
        /** L'humeur a dérivé d'elle-même (pas une réponse) : les postures suivent, pas les gestes. */
        val ambient: Boolean = false,
        /** La posture que le corps tient déjà : seule entrée de l'hystérésis. */
        val activeVariant: String? = null,
    )

    /** L'ordre des portes est le contrat : sommeil → voix intérieure → ambivalence → table → dérive → seuil → délai. */
    fun decide(input: Input): Decision {
        if (input.sleepPhase != "awake") return Decision.None("asleep")
        if (input.persona == "inner") return Decision.None("inner_persona")
        val blend = input.blend
        if (blend.size >= 2 && blend[0].second > 0f && blend[1].second >= blend[0].second * AMBIVALENCE_RATIO) {
            return Decision.None("ambivalent")
        }
        val mapping = EMOTION_GESTURE[input.emotion] ?: return Decision.None("unmapped")
        val clip = mapping.clip
        if (mapping.kind == Kind.NONE || clip == null) return Decision.None("unmapped")
        if (input.ambient && mapping.kind == Kind.ONESHOT) return Decision.None("ambient_drift")
        val threshold = if (mapping.kind == Kind.IDLE_VARIANT && input.activeVariant == clip) {
            mapping.minIntensity - VARIANT_HYSTERESIS
        } else {
            mapping.minIntensity
        }
        if (input.intensity < threshold) return Decision.None("below_threshold")
        val last = input.lastOneshotAt
        if (mapping.kind == Kind.ONESHOT && last != null && input.nowSeconds - last < GESTURE_COOLDOWN_S) {
            return Decision.None("cooldown")
        }
        return if (mapping.kind == Kind.ONESHOT) Decision.Oneshot(clip) else Decision.IdleVariant(clip)
    }
}
