package fr.qwartz.mika.data.net

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ServerBaseTest {
    private fun ok(input: String): ServerBase {
        val parsed = ServerBase.parse(input)
        assertTrue("$input → $parsed", parsed is ServerBase.Parsed.Ok)
        return (parsed as ServerBase.Parsed.Ok).base
    }

    private fun error(input: String): String {
        val parsed = ServerBase.parse(input)
        assertTrue("$input → $parsed", parsed is ServerBase.Parsed.Error)
        return (parsed as ServerBase.Parsed.Error).message
    }

    @Test fun `une adresse sans schéma devient http, sans barre finale`() {
        assertEquals("http://192.168.1.20:8001", ok("  192.168.1.20:8001/ ").canonical)
        assertEquals("http://mika.local:8001", ok("MIKA.local:8001").canonical)
    }

    @Test fun `le préfixe de chemin est gardé`() {
        val base = ok("https://exemple.org/mika/")
        assertEquals("https://exemple.org/mika", base.canonical)
        assertEquals("https://exemple.org/mika/auth/token", base.http("/auth/token").toString())
        assertEquals("wss://exemple.org/mika/ws", base.ws())
    }

    @Test fun `la socket suit le schéma`() {
        assertEquals("ws://10.0.2.2:8001/ws", ok("http://10.0.2.2:8001").ws())
        assertEquals("wss://mika.tail1234.ts.net/ws", ok("https://mika.tail1234.ts.net").ws())
        assertEquals("http://10.0.2.2:8001/files/abc", ok("10.0.2.2:8001").http("files/abc").toString())
    }

    @Test fun `requête, fragment, identifiants et schémas étrangers sont refusés`() {
        assertTrue(error("http://h:8001/?x=1").contains("?"))
        assertTrue(error("http://h:8001/#a").contains("#"))
        assertTrue(error("http://moi:secret@h:8001").contains("identifiants"))
        assertTrue(error("ftp://h").contains("http"))
        assertEquals("Indique l'adresse du serveur.", error("   "))
        error("http://")
    }

    @Test fun `ce que l'écran de connexion signale`() {
        val lan = ok("http://192.168.1.20:8001")
        assertTrue(lan.isInsecure)
        assertTrue(lan.isLan)
        assertFalse(lan.isTailscale)
        val ts = ok("http://100.101.102.103:8001")
        assertTrue(ts.isTailscale)
        assertTrue(ts.isInsecure)
        assertTrue(ok("http://mika.tail1234.ts.net").isTailscale)
        assertFalse(ok("http://100.128.0.1").isTailscale)
        assertFalse(ok("http://127.0.0.1:8001").isInsecure)
        assertFalse(ok("http://localhost:8001").isInsecure)
        assertFalse(ok("https://exemple.org").isInsecure)
        assertTrue(ok("http://172.20.1.1").isLan)
        assertFalse(ok("http://172.32.1.1").isLan)
    }

    @Test fun `le jeton ne part que vers la même origine`() {
        val base = ok("http://192.168.1.20:8001")
        assertTrue(base.sameOrigin("http://192.168.1.20:8001/files/x".toHttpUrl()))
        assertFalse(base.sameOrigin("http://192.168.1.20:8002/files/x".toHttpUrl()))
        assertFalse(base.sameOrigin("https://192.168.1.20:8001/files/x".toHttpUrl()))
        assertFalse(base.sameOrigin("http://ailleurs.test:8001/".toHttpUrl()))
    }

    @Test fun `une adresse canonique se relit à l'identique`() {
        val base = ok("https://exemple.org/mika")
        assertEquals(base, ServerBase.fromCanonical(base.canonical))
        assertNull(ServerBase.fromCanonical(null))
        assertNull(ServerBase.fromCanonical("ftp://x"))
        assertEquals("[::1]:8001", ok("http://[::1]:8001").hostPort)
    }
}
