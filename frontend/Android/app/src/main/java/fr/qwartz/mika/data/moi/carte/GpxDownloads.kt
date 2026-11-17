package fr.qwartz.mika.data.moi.carte

import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import fr.qwartz.mika.data.files.DownloadErrors
import fr.qwartz.mika.data.files.DownloadStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.IOException

/**
 * Le GPX d'un itinéraire, fait sur le téléphone (rien ne part), rangé dans Téléchargements/Mika comme les fichiers de
 * Mika (`DownloadStore` : MediaStore, sans permission depuis Android 10) : la ligne est d'abord « en cours »
 * (`IS_PENDING`), invisible des autres applications, puis publiée ; un échec l'efface plutôt que de laisser un fichier
 * tronqué. Le GPX d'un voyage, lui, vient du serveur (`DownloadStore.saveToDownloads`).
 */
object GpxDownloads {
    private const val FOLDER = "Mika"
    const val MIME = "application/gpx+xml"

    suspend fun save(context: Context, name: String, text: String): DownloadStore.Outcome = withContext(Dispatchers.IO) {
        val resolver = context.contentResolver
        val folder = "${Environment.DIRECTORY_DOWNLOADS}/$FOLDER"
        fun values(type: String) = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, type)
            put(MediaStore.Downloads.RELATIVE_PATH, folder)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        // un type que MediaStore refuse pour cette extension : le type neutre
        val uri = try {
            resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values(MIME))
        } catch (_: IllegalArgumentException) {
            resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values("application/octet-stream"))
        } ?: return@withContext DownloadStore.Outcome.Failed(DownloadErrors.STORAGE)
        try {
            val stream = resolver.openOutputStream(uri) ?: throw IOException("flux d'écriture absent")
            stream.use { it.write(text.toByteArray(Charsets.UTF_8)) }
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            DownloadStore.Outcome.Saved(folder)
        } catch (_: IOException) {
            resolver.delete(uri, null, null)
            DownloadStore.Outcome.Failed(DownloadErrors.STORAGE)
        } catch (_: SecurityException) {
            resolver.delete(uri, null, null)
            DownloadStore.Outcome.Failed(DownloadErrors.STORAGE)
        }
    }
}
