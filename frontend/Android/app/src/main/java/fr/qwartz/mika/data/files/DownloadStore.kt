package fr.qwartz.mika.data.files

import android.content.ContentValues
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import androidx.core.content.FileProvider
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.chat.MessageAttachment
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import java.io.File
import java.io.IOException

/**
 * Les fichiers que Mika envoie : les télécharger avec le jeton (le client [http] ne le pose que vers
 * son serveur), puis les ranger dans Téléchargements (MediaStore, sans permission depuis Android 10)
 * ou les préparer pour « Ouvrir avec… » (une copie en cache servie par notre FileProvider).
 */
class DownloadStore(
    private val context: Context,
    private val http: OkHttpClient,
    private val credentials: () -> Credentials?,
    private val logger: Logger = Logger.NONE,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    sealed interface Outcome {
        /** Rangé dans Téléchargements ; [folder] dit où le trouver. */
        data class Saved(val folder: String) : Outcome
        /** Prêt à ouvrir : une adresse `content://` lisible par l'application choisie, et son type. */
        data class Ready(val uri: Uri, val mime: String) : Outcome
        /** [sessionExpired] : un 401, la session est à vérifier. */
        data class Failed(val message: String, val sessionExpired: Boolean = false) : Outcome
    }

    /** Le dossier des copies à ouvrir ; vidé à la déconnexion. */
    val sharedDir: File get() = File(context.cacheDir, "shared")

    suspend fun saveToDownloads(att: MessageAttachment): Outcome = withContext(io) {
        val request = request(att) ?: return@withContext Outcome.Failed(DownloadErrors.NOT_A_FILE)
        try {
            http.newCall(request).execute().use { response ->
                failure(response)?.let { return@withContext it }
                val name = MikaFileRefs.localName(att)
                val mime = storageMime(name, att, response)
                insertDownload(name, mime) { out -> response.body.byteStream().use { it.copyTo(out) } }
            }
        } catch (e: IOException) {
            logger.w(TAG, "téléchargement interrompu", e)
            Outcome.Failed(DownloadErrors.forException(e))
        }
    }

    /** Pour « Ouvrir avec… » : réutilise une copie déjà faite, sinon la télécharge. */
    suspend fun prepareOpen(att: MessageAttachment): Outcome = withContext(io) {
        val request = request(att) ?: return@withContext Outcome.Failed(DownloadErrors.NOT_A_FILE)
        val id = att.id!!.lowercase()
        val dir = File(sharedDir, id)
        val target = File(dir, MikaFileRefs.localName(att))
        if (target.isFile && target.length() > 0) return@withContext ready(target, att, null)
        var partial: File? = null
        try {
            http.newCall(request).execute().use { response ->
                failure(response)?.let { return@withContext it }
                dir.mkdirs()
                // Un nom à part pendant la copie : un fichier tronqué ne passe jamais pour complet.
                val part = File.createTempFile("dl-", ".part", dir).also { partial = it }
                response.body.byteStream().use { input -> part.outputStream().use { input.copyTo(it) } }
                if (!part.renameTo(target)) return@withContext Outcome.Failed(DownloadErrors.STORAGE)
                ready(target, att, response.header("Content-Type"))
            }
        } catch (e: IOException) {
            logger.w(TAG, "téléchargement interrompu", e)
            Outcome.Failed(DownloadErrors.forException(e))
        } finally {
            partial?.takeIf { it.exists() }?.delete()
        }
    }

    /** Déconnexion : plus aucune copie d'un fichier de Mika sur le téléphone. */
    fun clear() {
        sharedDir.deleteRecursively()
    }

    /** L'adresse absolue d'une vignette ou d'une image en plein écran, sur le serveur de la session. */
    fun absoluteUrl(att: MessageAttachment): String? {
        val path = MikaFileRefs.path(att) ?: return null
        return credentials()?.base?.http(path)?.toString()
    }

    private fun request(att: MessageAttachment): Request? {
        val url = absoluteUrl(att) ?: return null
        return Request.Builder().url(url).get().build()
    }

    private fun failure(response: Response): Outcome.Failed? {
        if (response.isSuccessful) return null
        return Outcome.Failed(DownloadErrors.forHttp(response.code), sessionExpired = response.code == 401)
    }

    private fun ready(file: File, att: MessageAttachment, served: String?): Outcome {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
        return Outcome.Ready(uri, MikaFileRefs.openMime(att, served))
    }

    /**
     * Le type annoncé à MediaStore. Il refuse un type qui ne colle pas à l'extension (ou en ajoute
     * une) : celui de l'extension d'abord, puis celui qu'elle a déclaré, puis le type neutre.
     */
    private fun storageMime(name: String, att: MessageAttachment, response: Response): String {
        val ext = name.substringAfterLast('.', "").lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext)
            ?: att.mime?.takeIf { '/' in it }
            ?: response.header("Content-Type")?.substringBefore(';')?.trim()?.takeIf { '/' in it }
            ?: "application/octet-stream"
    }

    /**
     * Écrire dans Téléchargements/Mika : la ligne est d'abord « en cours » (`IS_PENDING`), invisible
     * des autres applications, puis publiée ; un échec l'efface plutôt que de laisser un fichier tronqué.
     */
    private fun insertDownload(name: String, mime: String, write: (java.io.OutputStream) -> Unit): Outcome {
        val resolver = context.contentResolver
        val folder = "${Environment.DIRECTORY_DOWNLOADS}/$FOLDER"
        fun values(type: String) = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, name)
            put(MediaStore.Downloads.MIME_TYPE, type)
            put(MediaStore.Downloads.RELATIVE_PATH, folder)
            put(MediaStore.Downloads.IS_PENDING, 1)
        }
        val uri = try {
            resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values(mime))
        } catch (_: IllegalArgumentException) {
            resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values("application/octet-stream"))
        } ?: return Outcome.Failed(DownloadErrors.STORAGE)
        return try {
            val stream = resolver.openOutputStream(uri) ?: throw IOException("flux d'écriture absent")
            stream.use(write)
            resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            Outcome.Saved(folder)
        } catch (e: IOException) {
            logger.w(TAG, "écriture dans Téléchargements impossible", e)
            resolver.delete(uri, null, null)
            Outcome.Failed(DownloadErrors.forException(e))
        } catch (e: SecurityException) {
            logger.w(TAG, "écriture dans Téléchargements refusée", e)
            resolver.delete(uri, null, null)
            Outcome.Failed(DownloadErrors.STORAGE)
        }
    }

    private companion object {
        const val TAG = "Downloads"
        const val FOLDER = "Mika"
    }
}
