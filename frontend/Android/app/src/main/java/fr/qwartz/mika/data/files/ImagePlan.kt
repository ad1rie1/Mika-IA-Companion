package fr.qwartz.mika.data.files

import fr.qwartz.mika.data.net.MikaProtocol
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Que faire d'un fichier avant de le joindre — la décision, pure ; `ImageCompressor` l'exécute.
 *
 * Une image est gardée telle quelle quand elle tient et que le serveur sait la lire ; sinon elle est
 * réencodée en JPEG (côté long ≤ 2 048 px, qualité 85 → 75 → 65, puis 1 600 px), ce qui retire du
 * même coup l'EXIF et la position GPS. Une photo prise pour Mika l'est toujours : l'appareil en fait
 * de 8 Mo, et ce qu'elle en verra est une description, pas un tirage.
 */
object ImagePlan {
    data class Step(val maxEdge: Int, val quality: Int)

    /** Du plus fidèle au plus léger ; au-delà, l'image ne tient pas et le dit. */
    val LADDER: List<Step> = listOf(
        Step(2048, 85),
        Step(2048, 75),
        Step(2048, 65),
        Step(1600, 75),
        Step(1600, 65),
    )

    /** Ce que le serveur décrit sans conversion (`protocol.py`) : gardé tel quel quand ça tient. */
    val SERVER_IMAGE_TYPES: Set<String> = setOf("image/jpeg", "image/png", "image/webp", "image/gif")

    /**
     * Ce qu'on ne réencode jamais : un GIF perdrait son animation, un SVG n'est pas une image
     * matricielle. Ils passent comme des fichiers ordinaires, ou pas du tout.
     */
    private val NEVER_REENCODE = setOf("image/gif", "image/svg+xml")

    /** En dessous, réencoder ne sert à rien : même la plus petite marche ne tiendrait pas. */
    const val MIN_REENCODE_BUDGET = 64L * 1024

    sealed interface Decision {
        data object Keep : Decision
        /** Réencoder sous [budget] octets ; [notice] est ce qu'il faut en dire (null : rien à dire). */
        data class Reencode(val budget: Long, val notice: String?) : Decision
        data class Reject(val notice: String) : Decision
    }

    /**
     * La place laissée à un fichier : 5 Mio, et ce qui reste des 11 Mio d'un message une fois comptés
     * les fichiers déjà joints.
     */
    fun capFor(alreadyAttachedBytes: Long): Long =
        minOf(MikaProtocol.MAX_FILE_BYTES, MikaProtocol.MAX_FILES_BYTES_PER_MESSAGE - alreadyAttachedBytes).coerceAtLeast(0)

    fun decide(name: String, mime: String, size: Long, fromCamera: Boolean, cap: Long): Decision {
        if (size < 0) return Decision.Reject(AttachmentPolicy.unreadable(name))
        val type = mime.lowercase().substringBefore(';').trim()
        val image = type.startsWith("image/") && type !in NEVER_REENCODE
        if (!image) return keepOrReject(name, size, cap)
        val tooBig = size > cap
        val foreign = type !in SERVER_IMAGE_TYPES
        if (!fromCamera && !foreign && !tooBig) return Decision.Keep
        if (cap < MIN_REENCODE_BUDGET) return Decision.Reject(AttachmentPolicy.TOO_HEAVY)
        val notice = if (tooBig) AttachmentPolicy.reduced(name, toFitMessage = cap < MikaProtocol.MAX_FILE_BYTES) else null
        return Decision.Reencode(cap, notice)
    }

    private fun keepOrReject(name: String, size: Long, cap: Long): Decision = when {
        size <= cap -> Decision.Keep
        size > MikaProtocol.MAX_FILE_BYTES -> Decision.Reject(AttachmentPolicy.tooLarge(name, size))
        else -> Decision.Reject(AttachmentPolicy.TOO_HEAVY)
    }

    /** Les dimensions sous [maxEdge] (côté long), proportions gardées ; jamais agrandies. */
    fun targetSize(width: Int, height: Int, maxEdge: Int): Pair<Int, Int> {
        val longEdge = max(width, height)
        if (longEdge <= maxEdge || longEdge <= 0) return width to height
        val ratio = maxEdge.toDouble() / longEdge
        return max(1, (width * ratio).roundToInt()) to max(1, (height * ratio).roundToInt())
    }

    /** Un JPEG s'appelle `.jpg` : `IMG_0001.HEIC` → `IMG_0001.jpg`. */
    fun jpegName(name: String): String {
        val base = name.substringBeforeLast('.', name).ifBlank { "photo" }
        return "$base.jpg"
    }

    fun fits(bytes: Long, budget: Long): Boolean = bytes in 1..budget
}
