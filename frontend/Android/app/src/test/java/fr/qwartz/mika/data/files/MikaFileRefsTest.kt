package fr.qwartz.mika.data.files

import fr.qwartz.mika.data.chat.MessageAttachment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.ConnectException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException

class MikaFileRefsTest {
    private val id = "9f2c" + "0".repeat(28)
    private fun att(
        name: String = "courses.md",
        id: String? = this.id,
        url: String? = "/files/$id",
        mime: String? = "text/markdown",
        kind: String = "file",
        available: Boolean? = true,
    ) = MessageAttachment(name, kind, mime, 312, id, url, available)

    @Test fun `seule la route d'un fichier de Mika est suivie, jamais une adresse absolue`() {
        assertEquals("/files/$id", MikaFileRefs.path(att()))
        assertEquals("/files/$id", MikaFileRefs.path(att(url = null)))
        assertNull(MikaFileRefs.path(att(url = "https://ailleurs.example/files/$id")))
        assertNull(MikaFileRefs.path(att(url = "/files/autre")))
        assertNull(MikaFileRefs.path(att(id = "../../etc/passwd")))
        assertNull(MikaFileRefs.path(att(id = null)))
        assertFalse(MikaFileRefs.isMikaFile(MessageAttachment("photo.jpg", "image")))
    }

    @Test fun `retiré, image, nom local`() {
        assertTrue(MikaFileRefs.isRemoved(att(available = false)))
        assertFalse(MikaFileRefs.isRemoved(att(available = null)))
        assertTrue(MikaFileRefs.isImage(att(kind = "image", mime = null)))
        assertTrue(MikaFileRefs.isImage(att(mime = "image/png")))
        assertEquals("courses.md", MikaFileRefs.localName(att()))
        assertEquals("b.txt", MikaFileRefs.localName(att(name = "../a/b.txt")))
        assertEquals("fichier-9f2c0000", MikaFileRefs.localName(att(name = "")))
    }

    @Test fun `le type annoncé à l'application qui l'ouvrira`() {
        assertEquals("text/markdown", MikaFileRefs.openMime(att(), "application/octet-stream"))
        assertEquals("text/plain", MikaFileRefs.openMime(att(mime = "text/x-python"), null))
        assertEquals("application/pdf", MikaFileRefs.openMime(att(mime = null), "application/pdf; charset=binary"))
        assertEquals("application/octet-stream", MikaFileRefs.openMime(att(mime = null), null))
    }

    @Test fun `le nom donné par Content-Disposition`() {
        assertEquals("liste de courses.md", MikaFileRefs.filenameFromDisposition("attachment; filename*=UTF-8''liste%20de%20courses.md"))
        assertEquals("a+b.txt", MikaFileRefs.filenameFromDisposition("attachment; filename*=UTF-8''a+b.txt"))
        assertEquals("plain.txt", MikaFileRefs.filenameFromDisposition("attachment; filename=\"plain.txt\""))
        assertNull(MikaFileRefs.filenameFromDisposition("attachment"))
        assertNull(MikaFileRefs.filenameFromDisposition(null))
    }

    @Test fun `ce qu'on dit d'un téléchargement raté`() {
        assertEquals("Fichier introuvable", DownloadErrors.forHttp(404))
        assertEquals("Fichier retiré", DownloadErrors.forHttp(410))
        assertEquals("Session expirée", DownloadErrors.forHttp(401))
        assertEquals(DownloadErrors.RATE_LIMITED, DownloadErrors.forHttp(429))
        assertEquals("Erreur du serveur (502).", DownloadErrors.forHttp(502))
        assertEquals("Téléchargement refusé (403).", DownloadErrors.forHttp(403))
        assertEquals(DownloadErrors.UNREACHABLE, DownloadErrors.forException(UnknownHostException("x")))
        assertEquals(DownloadErrors.UNREACHABLE, DownloadErrors.forException(ConnectException("x")))
        assertEquals(DownloadErrors.TLS, DownloadErrors.forException(SSLHandshakeException("x")))
        assertEquals(DownloadErrors.INTERRUPTED, DownloadErrors.forException(IOException("coupé")))
    }
}
