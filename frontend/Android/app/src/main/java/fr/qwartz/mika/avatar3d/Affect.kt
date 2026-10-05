package fr.qwartz.mika.avatar3d

/**
 * L'humeur dans le corps — `frontend/Web/src/vtuber/animation/affect.ts`, à l'identique : la valence et l'arousal de
 * chaque émotion (les P et A des ancres PAD du serveur), qui pèsent le choix d'une attente selon l'humeur qu'un clip
 * déclare, règlent son tempo et la durée où elle est tenue.
 */
object Affect {
    val VALENCE: Map<String, Float> = mapOf(
        "neutral" to 0.0f,
        "happy" to 0.8f, "excited" to 0.7f, "love" to 0.9f, "proud" to 0.7f, "grateful" to 0.7f,
        "playful" to 0.7f, "amused" to 0.7f, "hopeful" to 0.6f, "relieved" to 0.5f,
        "sad" to -0.7f, "angry" to -0.6f, "scared" to -0.7f, "disgusted" to -0.7f, "frustrated" to -0.5f,
        "lonely" to -0.7f, "anxious" to -0.5f, "bored" to -0.3f, "jealous" to -0.5f,
        "surprised" to 0.1f, "thinking" to 0.1f, "confused" to -0.2f, "embarrassed" to -0.3f,
        "nostalgic" to 0.2f, "dreamy" to 0.4f, "determined" to 0.4f, "mischievous" to 0.5f,
        "curious" to 0.4f, "melancholic" to -0.5f,
    )

    val AROUSAL: Map<String, Float> = mapOf(
        "neutral" to 0.0f,
        "happy" to 0.3f, "excited" to 0.9f, "love" to 0.4f, "proud" to 0.3f, "grateful" to 0.1f,
        "playful" to 0.6f, "amused" to 0.4f, "hopeful" to 0.2f, "relieved" to -0.3f,
        "sad" to -0.3f, "angry" to 0.8f, "scared" to 0.7f, "disgusted" to 0.3f, "frustrated" to 0.6f,
        "lonely" to -0.4f, "anxious" to 0.6f, "bored" to -0.6f, "jealous" to 0.5f,
        "surprised" to 0.8f, "thinking" to 0.1f, "confused" to 0.3f, "embarrassed" to 0.4f,
        "nostalgic" to -0.2f, "dreamy" to -0.3f, "determined" to 0.5f, "mischievous" to 0.5f,
        "curious" to 0.5f, "melancholic" to -0.5f,
    )

    const val AFFINITY_GAIN = 1.5f
    const val AFFINITY_MIN = 0.15f
    const val AFFINITY_MAX = 2.5f
    const val TEMPO_GAIN = 0.12f
    const val TEMPO_MIN = 0.85f
    const val TEMPO_MAX = 1.15f
    const val HOLD_GAIN = 0.35f
    const val HOLD_MIN = 0.6f
    const val HOLD_MAX = 1.4f

    /** Un clip qui déclare son humeur est favorisé quand elle s'accorde, raréfié sinon — jamais impossible. */
    fun clipAffinity(entry: ClipManifest.Entry, emotion: String, intensity: Float): Float {
        val a = entry.arousal ?: 0f
        val v = entry.valence ?: 0f
        if (a == 0f && v == 0f) return 1f
        val s = intensity.coerceIn(0f, 1f)
        val match = a * (AROUSAL[emotion] ?: 0f) * s + v * (VALENCE[emotion] ?: 0f) * s
        return (1 + AFFINITY_GAIN * match).coerceIn(AFFINITY_MIN, AFFINITY_MAX)
    }

    fun timeScale(emotion: String, intensity: Float): Float =
        (1 + TEMPO_GAIN * (AROUSAL[emotion] ?: 0f) * intensity.coerceIn(0f, 1f)).coerceIn(TEMPO_MIN, TEMPO_MAX)

    fun holdScale(emotion: String, intensity: Float): Float =
        (1 - HOLD_GAIN * (AROUSAL[emotion] ?: 0f) * intensity.coerceIn(0f, 1f)).coerceIn(HOLD_MIN, HOLD_MAX)
}
