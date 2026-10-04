package fr.qwartz.mika.ui.avatar

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.data.avatar.AvatarManifest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.FileNotFoundException
import java.io.IOException

/** Un portrait prêt à dessiner : l'image, ses yeux fermés, et où les poser. */
class LoadedPortrait(
    val id: String,
    val image: ImageBitmap,
    val blink: ImageBitmap?,
    val entry: AvatarManifest.PortraitEntry,
    /** La taille de rendu du manifeste : les positions s'y rapportent, quelle que soit la taille décodée. */
    val width: Int,
    val height: Int,
)

/**
 * Les portraits des assets (`avatar/`), décodés à la demande hors du fil principal et gardés en petit
 * nombre : celui qu'on montre, celui qu'on quitte pendant le fondu, et deux de rab (≈ 6 Mo chacun en
 * pleine taille, la moitié par côté sur un écran étroit).
 */
class AvatarAssets(private val context: Context, private val logger: Logger) {
    private val mutex = Mutex()
    private var manifestRead = false
    private var manifest: AvatarManifest? = null
    private val cache = LinkedHashMap<String, LoadedPortrait>(8, 0.75f, true)

    /** Le manifeste, lu une fois ; `null` quand l'app a été construite sans portraits. */
    suspend fun manifest(): AvatarManifest? = mutex.withLock { manifestLocked() }

    suspend fun load(id: String): LoadedPortrait? = mutex.withLock {
        cache[id]?.let { return it }
        val m = manifestLocked() ?: return null
        val entry = m.portraits[id] ?: return null
        val loaded = withContext(Dispatchers.IO) {
            val sample = sampleSize(m.width)
            val image = decode(entry.file, sample) ?: return@withContext null
            val blink = entry.blink?.let { decode(it.file, sample) }
            LoadedPortrait(id, image.asImageBitmap(), blink?.asImageBitmap(), entry, m.width, m.height)
        } ?: return null
        cache[id] = loaded
        while (cache.size > CACHE_SIZE) cache.remove(cache.keys.first())
        loaded
    }

    private suspend fun manifestLocked(): AvatarManifest? {
        if (!manifestRead) {
            manifest = withContext(Dispatchers.IO) {
                try {
                    context.assets.open(AvatarManifest.PATH).bufferedReader().use { AvatarManifest.parse(it.readText()) }
                } catch (_: FileNotFoundException) {
                    null
                } catch (e: IOException) {
                    logger.w(TAG, "manifeste des portraits illisible", e)
                    null
                }
            }
            manifestRead = true
        }
        return manifest
    }

    /** Pleine taille sur un écran large, moitié par côté quand l'écran fait moins de 700 px de large. */
    private fun sampleSize(renderWidth: Int): Int {
        val screen = context.resources.displayMetrics.widthPixels
        return if (screen in 1 until renderWidth * 2 / 3) 2 else 1
    }

    private fun decode(file: String, sample: Int): Bitmap? = try {
        context.assets.open("${AvatarManifest.DIR}/$file").use { input ->
            BitmapFactory.decodeStream(input, null, BitmapFactory.Options().apply { inSampleSize = sample })
        }
    } catch (e: IOException) {
        logger.w(TAG, "portrait illisible : $file", e)
        null
    }

    private companion object {
        const val TAG = "AvatarAssets"
        const val CACHE_SIZE = 4
    }
}
