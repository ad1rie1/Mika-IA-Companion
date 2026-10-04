package fr.qwartz.mika.data.auth

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException

class AuthErrorsTest {
    private val now = 1_759_572_000_000L

    @Test fun `401 dit ce que le serveur dit, sinon identifiants invalides`() {
        assertEquals("Identifiants invalides.", AuthErrors.forHttp(401, null, null, now).message)
        assertEquals("Compte désactivé.", AuthErrors.forHttp(401, "Compte désactivé.", null, now).message)
    }

    @Test fun `404 veut dire un serveur trop ancien`() {
        assertEquals(AuthErrors.OUTDATED_SERVER, AuthErrors.forHttp(404, null, null, now).message)
    }

    @Test fun `429 donne un compte à rebours`() {
        val e = AuthErrors.forHttp(429, "Trop de tentatives.", "42", now)
        assertEquals("Trop de tentatives. Réessaie dans 42 s.", e.message)
        assertEquals(42L, e.retryAfterSeconds)
        assertEquals(60L, AuthErrors.forHttp(429, null, null, now).retryAfterSeconds)
    }

    @Test fun `Retry-After en date HTTP`() {
        // 2025-10-04T10:00:30Z, 30 s après `now`
        assertEquals(30L, AuthErrors.parseRetryAfter("Sat, 04 Oct 2025 10:00:30 GMT", now))
        assertEquals(1L, AuthErrors.parseRetryAfter("Sat, 04 Oct 2025 09:00:00 GMT", now))
        assertNull(AuthErrors.parseRetryAfter("demain", now))
        assertNull(AuthErrors.parseRetryAfter(null, now))
    }

    @Test fun `403, 5xx et l'inattendu`() {
        assertEquals("Le serveur a refusé la demande (403).", AuthErrors.forHttp(403, "x", null, now).message)
        assertEquals("Erreur du serveur (503).", AuthErrors.forHttp(503, null, null, now).message)
        assertEquals("Réponse inattendue du serveur (418).", AuthErrors.forHttp(418, null, null, now).message)
    }

    @Test fun `les pannes de réseau disent quoi vérifier`() {
        assertEquals(AuthErrors.UNKNOWN_HOST, AuthErrors.forException(UnknownHostException("h"), "h:1").message)
        assertEquals(AuthErrors.TLS_REFUSED, AuthErrors.forException(SSLHandshakeException("x"), "h:1").message)
        val refused = AuthErrors.forException(ConnectException("refused"), "10.0.2.2:8001").message
        assertTrue(refused.contains("10.0.2.2:8001"))
        assertTrue(refused.contains("joignable"))
        assertTrue(AuthErrors.forException(SocketTimeoutException(), "h:1").message.contains("ne répond pas"))
        assertTrue(AuthErrors.forException(IOException("x"), "h:1").message.startsWith("Connexion impossible"))
    }
}
