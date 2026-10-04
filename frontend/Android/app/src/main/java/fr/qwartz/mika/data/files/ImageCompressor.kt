package fr.qwartz.mika.data.files

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ImageDecoder
import androidx.core.graphics.createBitmap
import java.io.File
import java.io.IOException

/**
 * Réencoder une image en JPEG sous un budget, en suivant [ImagePlan.LADDER]. `ImageDecoder` applique
 * l'orientation EXIF et réduit au décodage (la mémoire reste bornée même pour une photo de 50 Mpx) ;
 * le JPEG écrit depuis un `Bitmap` ne porte plus aucune métadonnée — ni EXIF, ni GPS.
 */
class ImageCompressor(private val workDir: () -> File) {

    /** Le fichier réencodé (dans [workDir]) et sa taille, ou `null` si rien ne tient ou si l'image est illisible. */
    fun reencode(source: File, budget: Long): File? {
        var decodedEdge = -1
        var bitmap: Bitmap? = null
        try {
            for (step in ImagePlan.LADDER) {
                if (step.maxEdge != decodedEdge) {
                    bitmap?.recycle()
                    bitmap = decode(source, step.maxEdge) ?: return null
                    decodedEdge = step.maxEdge
                }
                val out = encode(bitmap!!, step.quality) ?: return null
                if (ImagePlan.fits(out.length(), budget)) return out
                out.delete()
            }
            return null
        } finally {
            bitmap?.recycle()
        }
    }

    private fun decode(source: File, maxEdge: Int): Bitmap? = try {
        val decoded = ImageDecoder.decodeBitmap(ImageDecoder.createSource(source)) { decoder, info, _ ->
            val (w, h) = ImagePlan.targetSize(info.size.width, info.size.height, maxEdge)
            if (w != info.size.width || h != info.size.height) decoder.setTargetSize(w, h)
            // Un bitmap matériel ne se compresse pas ; logiciel, il se lit pour écrire le JPEG.
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
        }
        if (decoded.hasAlpha()) flatten(decoded) else decoded
    } catch (_: IOException) {
        null
    } catch (_: IllegalArgumentException) {
        null
    } catch (_: OutOfMemoryError) {
        null
    }

    /** Le JPEG n'a pas de transparence : sans fond blanc, un PNG détouré deviendrait noir. */
    private fun flatten(src: Bitmap): Bitmap {
        val out = createBitmap(src.width, src.height)
        Canvas(out).apply {
            drawColor(Color.WHITE)
            drawBitmap(src, 0f, 0f, null)
        }
        src.recycle()
        return out
    }

    private fun encode(bitmap: Bitmap, quality: Int): File? {
        val dir = workDir().apply { mkdirs() }
        val out = File.createTempFile("img-", ".jpg", dir)
        return try {
            val ok = out.outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, quality, it) }
            if (ok) out else null.also { out.delete() }
        } catch (_: IOException) {
            out.delete()
            null
        }
    }
}
