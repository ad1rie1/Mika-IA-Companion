package fr.qwartz.mika.data.moi.mail

import android.content.ContentResolver
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.RequestBody
import okio.BufferedSink
import okio.source
import java.io.IOException

/**
 * Un document choisi dans le sélecteur du système (`OpenMultipleDocuments`), prêt à joindre : son nom et sa taille
 * lus du fournisseur, son contenu lu seulement au moment de partir, sans copie (25 Mo par pièce, ADR 0214). Un
 * fournisseur muet (ni nom ni taille) : `null`, la pièce n'est pas jointe — sa taille est ce que les bornes jugent.
 */
fun ContentResolver.outgoingPiece(uri: Uri): OutgoingPiece? {
    var name: String? = null
    var size = -1L
    try {
        query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
            if (c.moveToFirst()) {
                val n = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val s = c.getColumnIndex(OpenableColumns.SIZE)
                if (n >= 0 && !c.isNull(n)) name = c.getString(n)
                if (s >= 0 && !c.isNull(s)) size = c.getLong(s)
            }
        }
    } catch (_: RuntimeException) {
        return null
    }
    if (size < 0) return null
    val shown = name?.substringAfterLast('/')?.trim()?.takeIf { it.isNotEmpty() } ?: uri.lastPathSegment?.substringAfterLast('/') ?: "fichier"
    val mime = getType(uri)?.takeIf { '/' in it }
        ?: MimeTypeMap.getSingleton().getMimeTypeFromExtension(shown.substringAfterLast('.', "").lowercase())
        ?: "application/octet-stream"
    return OutgoingPiece(shown, mime, size) { UriBody(this, uri, mime) }
}

/** Le flux d'un document, copié tel quel dans la requête. Sa longueur n'est pas annoncée : certains fournisseurs
 *  donnent une taille fausse, et une longueur qui ne colle pas ferait échouer l'envoi entier. */
private class UriBody(private val resolver: ContentResolver, private val uri: Uri, private val mime: String) : RequestBody() {
    override fun contentType() = mime.toMediaTypeOrNull()

    override fun writeTo(sink: BufferedSink) {
        val input = try {
            resolver.openInputStream(uri)
        } catch (e: SecurityException) {
            throw IOException("document illisible", e)
        } ?: throw IOException("document introuvable")
        input.source().use { sink.writeAll(it) }
    }
}
