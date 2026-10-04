package fr.qwartz.mika.data.auth

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class AuthApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient()
    private val api = AuthApi(client)
    private lateinit var base: ServerBase

    @Before fun setUp() {
        server.start()
        base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
    }

    @After fun tearDown() {
        server.close()
        client.dispatcher.executorService.shutdown()
    }

    private fun json(code: Int, body: String, vararg headers: Pair<String, String>) = MockResponse.Builder()
        .code(code).body(body).addHeader("Content-Type", "application/json")
        .apply { headers.forEach { (k, v) -> addHeader(k, v) } }
        .build()

    @Test fun `la connexion demande un jeton mobile, sans Origin`() = runBlocking {
        server.enqueue(
            json(
                200,
                """{"token":"mw_xyz","token_id":12,"client":"mobile","authenticated":true,"auth_required":true,
                   "needs_bootstrap":false,"username":"adrien","display_name":"Adrien","person_id":"user_3","operator":true}""",
            ),
        )
        val r = api.login(base, "adrien", "secret", "Android · Google Pixel 8")
        assertTrue(r is AuthApi.Result.Ok)
        val grant = (r as AuthApi.Result.Ok).value
        assertEquals("mw_xyz", grant.token)
        assertEquals(Profile("adrien", "Adrien", "user_3", true), grant.profile)
        assertFalse(grant.toString().contains("mw_xyz"))

        val request = server.takeRequest(5, TimeUnit.SECONDS)!!
        assertEquals("POST", request.method)
        assertEquals("/auth/token", request.url.encodedPath)
        assertNull(request.headers["Origin"])
        val body = MikaJson.parseToJsonElement(request.body!!.utf8()) as JsonObject
        assertEquals("adrien", body["username"]!!.jsonPrimitive.content)
        assertEquals("secret", body["password"]!!.jsonPrimitive.content)
        assertEquals("Android · Google Pixel 8", body["label"]!!.jsonPrimitive.content)
        assertEquals("mobile", body["client"]!!.jsonPrimitive.content)
    }

    @Test fun `un refus garde le message du serveur et son Retry-After`() = runBlocking {
        server.enqueue(json(401, """{"error":"Identifiants invalides."}"""))
        assertEquals(AuthApi.Result.Http(401, "Identifiants invalides.", null), api.login(base, "a", "b", "x"))
        server.enqueue(json(429, """{"error":"Trop de tentatives."}""", "Retry-After" to "60"))
        assertEquals(AuthApi.Result.Http(429, "Trop de tentatives.", "60"), api.login(base, "a", "b", "x"))
        server.enqueue(MockResponse.Builder().code(404).body("Not Found").build())
        assertEquals(AuthApi.Result.Http(404, null, null), api.login(base, "a", "b", "x"))
    }

    @Test fun `whoami présente le jeton`() = runBlocking {
        server.enqueue(json(200, """{"authenticated":false,"auth_required":true,"needs_bootstrap":false}"""))
        val r = api.whoami(base, "mw_abc") as AuthApi.Result.Ok
        assertFalse(r.value.authenticated)
        val request = server.takeRequest(5, TimeUnit.SECONDS)!!
        assertEquals("GET", request.method)
        assertEquals("/auth/whoami", request.url.encodedPath)
        assertEquals("Bearer mw_abc", request.headers["Authorization"])
    }

    @Test fun `rendre le jeton à la déconnexion`() = runBlocking {
        server.enqueue(json(200, """{"ok":true}"""))
        assertTrue(api.revoke(base, "mw_abc"))
        val request = server.takeRequest(5, TimeUnit.SECONDS)!!
        assertEquals("DELETE", request.method)
        assertEquals("Bearer mw_abc", request.headers["Authorization"])
    }

    @Test fun `un serveur éteint est une panne de réseau, pas une exception`() = runBlocking {
        val nobody = (ServerBase.parse("http://127.0.0.1:1") as ServerBase.Parsed.Ok).base
        assertTrue(api.login(nobody, "a", "b", "x") is AuthApi.Result.Network)
        assertFalse(api.revoke(nobody, "mw_abc"))
    }
}
