package fr.qwartz.mika.avatar3d

import android.content.Context
import fr.qwartz.mika.data.mind.MindState

/**
 * Ce que l'avatar 3D doit savoir d'elle, tiré de ce que l'app sait déjà ([MindState], « Mika écrit… », la barre de
 * saisie) : aucune trame nouvelle côté serveur.
 */
data class Avatar3DState(
    val emotion: String = "neutral",
    val intensity: Float = 0f,
    val blend: List<Pair<String, Float>> = emptyList(),
    /** L'émotion d'une parole (un geste est permis) plutôt qu'une humeur qui dérive. */
    val reply: Boolean = false,
    /** Quand cette humeur est arrivée : une seconde parole à la même émotion est un nouveau geste. */
    val moodAtMs: Long = 0,
    val sleepPhase: String = "awake",
    val energy: Float = 1f,
    /** Elle écrit (« Mika écrit… ») : regard de quelqu'un qui compose sa réponse. */
    val replyPending: Boolean = false,
) {
    companion object {
        fun of(mind: MindState?, mikaTyping: Boolean): Avatar3DState {
            val mood = mind?.mood
            return Avatar3DState(
                emotion = mood?.emotion?.trim()?.lowercase() ?: "neutral",
                intensity = (mood?.intensity ?: 0.0).toFloat(),
                blend = mood?.blend?.map { it.emotion to it.weight.toFloat() }.orEmpty(),
                reply = mood?.reply == true,
                moodAtMs = mood?.atMs ?: 0,
                sleepPhase = mind?.sleepPhase ?: "awake",
                energy = (mind?.energy ?: 1.0).toFloat(),
                replyPending = mikaTyping,
            )
        }

        /** Le VRM préparé est-il dans les assets ? Sans lui, l'app retombe sur les portraits. */
        fun available(context: Context): Boolean =
            context.assets.list("avatar3d")?.contains("mika.glb") == true
    }
}
