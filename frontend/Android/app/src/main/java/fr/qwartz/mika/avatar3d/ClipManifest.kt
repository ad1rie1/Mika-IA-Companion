package fr.qwartz.mika.avatar3d

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * Le manifeste des animations du client web (`frontend/Web/public/animations/manifest.json`), embarqué tel quel
 * (`avatar3d/manifest.json`) : une seule source pour les poids des attentes, leurs durées, l'humeur d'un clip
 * (valence, arousal) et les fondus des gestes. Les noms sont ceux des mouvements de l'atelier.
 */
@Serializable
data class ClipManifest(
    val version: Int = 1,
    val clips: Map<String, Entry> = emptyMap(),
    val sleep: Map<String, SleepEntry> = emptyMap(),
) {
    @Serializable
    data class Entry(
        val category: String = "idle",
        val weight: Float = 1f,
        val hold: List<Float>? = null,
        val valence: Float? = null,
        val arousal: Float? = null,
        val fadeIn: Float? = null,
        val fadeOut: Float? = null,
        val loop: Boolean? = null,
        val timeScale: Float? = null,
        /** `false` : pas de jumeau en miroir (un geste qui doit garder sa main). */
        val mirror: Boolean? = null,
    )

    @Serializable
    data class SleepEntry(val clip: String, val timeScale: Float? = null)

    fun byCategory(category: String): List<String> = clips.filterValues { it.category == category }.keys.sorted()

    companion object {
        const val PATH = "avatar3d/manifest.json"
        private val JSON = Json { ignoreUnknownKeys = true }

        fun parse(text: String): ClipManifest = JSON.decodeFromString(serializer(), text)
    }
}
