package fr.qwartz.mika.data.avatar

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.SerializationException
import kotlinx.serialization.Serializable

/**
 * Ses portraits, tels que `frontend/Web/assets-src/blender/portraits.py` les écrit dans les assets
 * (`avatar/manifest.json`) : un par émotion, plus « coucou », « fatiguée » et « endormie ».
 *
 * Les images viennent d'un modèle sous licence et ne sont pas versionnées : une app construite sans
 * elles n'a pas de manifeste, et n'affiche simplement pas d'avatar.
 */
@Serializable
data class AvatarManifest(
    val version: Int = 1,
    /** La taille de rendu, à laquelle les positions (visage, clignements) se rapportent. */
    val width: Int = 0,
    val height: Int = 0,
    val portraits: Map<String, PortraitEntry> = emptyMap(),
) {
    val ids: Set<String> get() = portraits.keys

    companion object {
        const val DIR = "avatar"
        const val PATH = "$DIR/manifest.json"

        /**
         * Lu une fois au lancement. Un manifeste illisible, sans portrait neutre ou qui pointerait hors
         * du dossier vaut « pas d'avatar », jamais une exception : c'est un décor.
         */
        fun parse(raw: String): AvatarManifest? {
            val m = try {
                MikaJson.decodeFromString(serializer(), raw)
            } catch (_: SerializationException) {
                return null
            } catch (_: IllegalArgumentException) {
                return null
            }
            if (m.width <= 0 || m.height <= 0) return null
            // Un portrait au nom douteux disparaît ; un clignement hors de l'image, seul le clignement.
            val clean = m.portraits
                .filterValues { safeName(it.file) }
                .mapValues { (_, p) -> if (p.blink?.fits(m.width, m.height) == false) p.copy(blink = null) else p }
            return if (AvatarDirector.NEUTRAL in clean) m.copy(portraits = clean) else null
        }

        private fun safeName(file: String) =
            file.isNotBlank() && '/' !in file && '\\' !in file && !file.startsWith(".")
    }

    @Serializable
    data class PortraitEntry(
        val file: String,
        /** Le milieu des yeux, en fraction de la largeur et de la hauteur (0,0 en haut à gauche). */
        val face: List<Double> = listOf(0.5, 0.25),
        /** Les yeux fermés, à poser par-dessus le portrait le temps d'un clignement. */
        val blink: BlinkPatch? = null,
    ) {
        val faceX: Float get() = face.getOrNull(0)?.toFloat()?.coerceIn(0f, 1f) ?: 0.5f
        val faceY: Float get() = face.getOrNull(1)?.toFloat()?.coerceIn(0f, 1f) ?: 0.25f
    }

    /** Une incrustation, en pixels de la taille de rendu. */
    @Serializable
    data class BlinkPatch(val file: String, val x: Int, val y: Int, val w: Int, val h: Int) {
        internal fun fits(width: Int, height: Int): Boolean =
            safeName(file) && w > 0 && h > 0 && x >= 0 && y >= 0 && x + w <= width && y + h <= height
    }
}
