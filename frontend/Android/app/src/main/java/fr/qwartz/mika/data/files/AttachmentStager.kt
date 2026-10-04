package fr.qwartz.mika.data.files

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.data.net.MikaProtocol
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.io.IOException

/**
 * Préparer ce qu'on joint : copier tout de suite dans l'espace de l'app ce qu'un sélecteur, l'appareil
 * photo ou un partage désigne (leur droit de lecture ne dure pas), réduire les images qui ne tiennent
 * pas, et dire ce qui ne passe pas — avec les formules du client web.
 */
class AttachmentStager(
    private val resolver: ContentResolver,
    private val files: OutboxFiles,
    private val compressor: ImageCompressor,
    private val logger: Logger = Logger.NONE,
    private val io: CoroutineDispatcher = Dispatchers.IO,
) {
    data class Result(val files: List<StagedFile>, val notices: List<String>)

    private data class Meta(val name: String, val mime: String, val size: Long)

    /**
     * [already] : ce qui est déjà joint (compte pour la limite de cinq et pour les 11 Mo d'un message).
     * [fromCamera] : une photo prise pour Mika, toujours réduite ; [displayName] la nomme.
     */
    suspend fun stage(
        uris: List<Uri>,
        already: List<StagedFile>,
        fromCamera: Boolean = false,
        displayName: String? = null,
    ): Result = withContext(io) {
        val notices = mutableListOf<String>()
        val room = (MikaProtocol.MAX_ATTACHMENTS - already.size).coerceAtLeast(0)
        if (uris.size > room) notices += AttachmentPolicy.tooMany(uris.size - room)
        var used = already.sumOf { it.size }
        val staged = mutableListOf<StagedFile>()
        for (uri in uris.take(room)) {
            val meta = describe(uri, displayName)
            // Un fichier dont la taille annoncée suffit à le refuser n'est même pas copié.
            if (meta.size >= 0) {
                val early = ImagePlan.decide(meta.name, meta.mime, meta.size, fromCamera, ImagePlan.capFor(used))
                if (early is ImagePlan.Decision.Reject) {
                    notices += early.notice
                    continue
                }
            }
            val copy = copy(uri)
            if (copy == null) {
                notices += AttachmentPolicy.unreadable(meta.name)
                continue
            }
            if (copy.length() > HARD_LIMIT_BYTES) {
                notices += AttachmentPolicy.tooLarge(meta.name, copy.length())
                copy.delete()
                continue
            }
            when (val d = ImagePlan.decide(meta.name, meta.mime, copy.length(), fromCamera, ImagePlan.capFor(used))) {
                ImagePlan.Decision.Keep -> {
                    staged += StagedFile(meta.name, meta.mime, copy.absolutePath, copy.length())
                    used += copy.length()
                }
                is ImagePlan.Decision.Reencode -> {
                    val out = compressor.reencode(copy, d.budget)
                    copy.delete()
                    if (out == null) {
                        notices += "${meta.name} ignorée : trop lourde, même réduite."
                    } else {
                        staged += StagedFile(ImagePlan.jpegName(meta.name), "image/jpeg", out.absolutePath, out.length())
                        used += out.length()
                        d.notice?.let(notices::add)
                    }
                }
                is ImagePlan.Decision.Reject -> {
                    copy.delete()
                    notices += d.notice
                }
            }
        }
        Result(staged, notices)
    }

    private fun describe(uri: Uri, displayName: String?): Meta {
        var name = displayName
        var size = -1L
        try {
            resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                if (c.moveToFirst()) {
                    val n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    val s = c.getColumnIndex(OpenableColumns.SIZE)
                    if (name == null && n >= 0 && !c.isNull(n)) name = c.getString(n)
                    if (s >= 0 && !c.isNull(s)) size = c.getLong(s)
                }
            }
        } catch (e: RuntimeException) {
            // Un fournisseur qui refuse la requête n'empêche pas forcément la lecture du flux.
            logger.w(TAG, "métadonnées illisibles", e)
        }
        val finalName = name?.trim()?.takeIf { it.isNotEmpty() } ?: uri.lastPathSegment?.substringAfterLast('/') ?: "fichier"
        val mime = typeOf(uri, finalName)
        return Meta(finalName, mime, size)
    }

    private fun typeOf(uri: Uri, name: String): String {
        val declared = try {
            resolver.getType(uri)
        } catch (_: RuntimeException) {
            null
        }
        if (!declared.isNullOrBlank() && declared != "application/octet-stream") return declared
        val ext = name.substringAfterLast('.', "").lowercase()
        return MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext) ?: declared ?: "application/octet-stream"
    }

    /** Copier le flux, borné : un flux sans fin ne remplit pas le téléphone. */
    private fun copy(uri: Uri): File? {
        val target = files.newStagingFile()
        return try {
            val input = resolver.openInputStream(uri) ?: return null.also { target.delete() }
            input.use { src ->
                target.outputStream().use { dst ->
                    val buffer = ByteArray(64 * 1024)
                    var total = 0L
                    while (true) {
                        val n = src.read(buffer)
                        if (n < 0) break
                        total += n
                        dst.write(buffer, 0, n)
                        // Au-delà, on s'arrête : la taille mesurée suffira à refuser.
                        if (total > HARD_LIMIT_BYTES) break
                    }
                }
            }
            target
        } catch (e: IOException) {
            logger.w(TAG, "copie impossible", e)
            target.delete()
            null
        } catch (e: SecurityException) {
            logger.w(TAG, "lecture refusée", e)
            target.delete()
            null
        } catch (e: IllegalArgumentException) {
            logger.w(TAG, "adresse illisible", e)
            target.delete()
            null
        }
    }

    private companion object {
        const val TAG = "Stager"
        /** Une image plus lourde que ça ne se réduit plus raisonnablement sur un téléphone. */
        const val HARD_LIMIT_BYTES = 64L * 1024 * 1024
    }
}
