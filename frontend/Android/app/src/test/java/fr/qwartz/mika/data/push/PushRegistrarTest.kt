package fr.qwartz.mika.data.push

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.AuthApi
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.auth.KeystoreCipher
import fr.qwartz.mika.data.auth.TokenVault
import fr.qwartz.mika.data.net.ServerBase
import fr.qwartz.mika.data.settings.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.util.Base64
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Dire au serveur où notifier ce téléphone fermé (ADR 0077) : à chaque ouverture, au plus tous les quarts d'heure tant
 * que rien ne change ; tout de suite quand le jeton Firebase, la clé ou le serveur changent, ou que le serveur n'avait
 * pas de clé Firebase ; hors de portée, ce qui a été dit vaut toujours ; la déconnexion oublie tout, sans attendre.
 */
class PushRegistrarTest {
    @get:Rule val folder = TemporaryFolder()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var base: ServerBase
    private var credentials: Credentials? = null
    private var now = 1_800_000_000_000L
    private val port = FakePort()
    private lateinit var settings: SettingsStore
    private lateinit var registrar: PushRegistrar
    private val clock = object : Clock {
        override fun wallMs() = now
        override fun elapsedMs() = now
    }

    private fun store(name: String) =
        PreferenceDataStoreFactory.create(scope = scope, produceFile = { folder.root.resolve("$name.preferences_pb") })

    private class FakePort(override var available: Boolean = true, var token: String? = "fcm-1") : PushPort {
        var forgotten = 0
        var slowForget = false
        override suspend fun token(): String? = token
        override suspend fun forget() {
            forgotten++
            if (slowForget) kotlinx.coroutines.delay(60_000)
        }
    }

    @Test fun `une tache Firebase en echec n'arrete pas l'inscription`() = runBlocking {
        val failing = object : PushPort {
            override val available = true
            override suspend fun token(): String? = throw IllegalStateException("tâche Firebase annulée")
            override suspend fun forget() = Unit
        }
        val keys = TokenVault(store("push2"), SoftwareCipher(), name = TokenVault.PUSH_KEY_NAME,
            aad = TokenVault.PUSH_KEY_AAD, forgetKeyWhenUnreadable = false)
        val r = PushRegistrar(failing, AuthApi(client), keys, settings, { credentials }, clock)
        r.sync()
        assertTrue(r.state.value is PushState.Failed)
        assertEquals(0, server.requestCount)
    }

    private class SoftwareCipher : KeystoreCipher {
        private var key: SecretKey? = null
        private fun keyOrNew() = key ?: KeyGenerator.getInstance("AES").apply { init(256) }.generateKey().also { key = it }
        override fun encrypt(plain: ByteArray, aad: ByteArray): KeystoreCipher.Sealed {
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.ENCRYPT_MODE, keyOrNew())
            c.updateAAD(aad)
            return KeystoreCipher.Sealed(c.iv, c.doFinal(plain))
        }
        override fun decrypt(iv: ByteArray, ciphertext: ByteArray, aad: ByteArray): ByteArray {
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, keyOrNew(), GCMParameterSpec(128, iv))
            c.updateAAD(aad)
            return c.doFinal(ciphertext)
        }
        override fun deleteKey() {
            key = null
        }
    }

    @Before fun setUp() {
        server.start()
        base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        credentials = Credentials(base, "mw_telephone")
        settings = SettingsStore(store("settings"))
        val keys = TokenVault(store("push"), SoftwareCipher(), name = TokenVault.PUSH_KEY_NAME, aad = TokenVault.PUSH_KEY_AAD,
            forgetKeyWhenUnreadable = false)
        registrar = PushRegistrar(port, AuthApi(client), keys, settings, { credentials }, clock)
    }

    @After fun tearDown() {
        server.close()
        client.dispatcher.executorService.shutdown()
        scope.cancel()
    }

    private fun reply(code: Int = 200, available: Boolean = true) = MockResponse.Builder()
        .code(code).addHeader("Content-Type", "application/json")
        .body(if (code == 200) """{"ok":true,"available":$available}""" else """{"error":"non"}""")
        .build()

    /** Le corps de l'inscription suivante : son jeton Firebase et sa clé. */
    private fun registered(): Pair<String, String> {
        val request = server.takeRequest(5, TimeUnit.SECONDS)!!
        assertEquals("POST", request.method)
        assertEquals("/auth/push", request.url.encodedPath)
        assertEquals("Bearer mw_telephone", request.headers["Authorization"])
        assertNull(request.headers["Origin"])
        val body = MikaJson.parseToJsonElement(request.body!!.utf8()) as JsonObject
        return body.getValue("token").jsonPrimitive.content to body.getValue("key").jsonPrimitive.content
    }

    @Test fun `sans Firebase ou sans session, rien ne part`() = runBlocking {
        port.available = false
        registrar.sync()
        assertEquals(PushState.Unavailable, registrar.state.value)
        port.available = true
        credentials = null
        registrar.sync()
        assertEquals(PushState.LoggedOut, registrar.state.value)
        assertEquals(0, server.requestCount)
    }

    @Test fun `la premiere ouverture dit au serveur le jeton et une cle de 32 octets`() = runBlocking {
        server.enqueue(reply())
        registrar.sync()
        val (device, key) = registered()
        assertEquals("fcm-1", device)
        assertEquals(32, Base64.getDecoder().decode(key).size)
        assertEquals(PushState.Active, registrar.state.value)
        assertArrayEquals(Base64.getDecoder().decode(key), registrar.key())
    }

    @Test fun `ensuite a chaque ouverture au plus tous les quarts d'heure, ou des que le jeton change`() = runBlocking {
        server.enqueue(reply())
        registrar.sync()
        val (_, key) = registered()
        now += 60_000
        registrar.sync()
        assertEquals(1, server.requestCount)
        now += PushRegistrar.REFRESH_MS
        server.enqueue(reply())
        registrar.sync()
        assertEquals("fcm-1" to key, registered())  // la même clé, redite
        port.token = "fcm-2"
        server.enqueue(reply())
        registrar.sync()
        assertEquals("fcm-2", registered().first)
        assertEquals(3, server.requestCount)
    }

    @Test fun `un serveur sans cle Firebase est redemande a chaque ouverture`() = runBlocking {
        server.enqueue(reply(available = false))
        registrar.sync()
        assertEquals(PushState.ServerWithoutKey, registrar.state.value)
        server.enqueue(reply(available = true))
        registrar.sync()
        assertEquals(PushState.Active, registrar.state.value)
        assertEquals(2, server.requestCount)
    }

    @Test fun `hors de portee, ce qui a ete dit vaut toujours`() = runBlocking {
        server.close()  // le serveur de la maison, vu de la 4G
        registrar.sync()
        assertEquals(PushState.Pending, registrar.state.value)
    }

    @Test fun `deja dit puis hors de portee au rafraichissement reste actif`() = runBlocking {
        server.enqueue(reply())
        registrar.sync()
        now += PushRegistrar.REFRESH_MS + 1
        server.close()
        registrar.sync()
        assertEquals(PushState.Active, registrar.state.value)
    }

    @Test fun `un serveur trop ancien le dit`() = runBlocking {
        server.enqueue(reply(code = 404))
        registrar.sync()
        val state = registrar.state.value
        assertTrue(state is PushState.Failed && state.reason.contains("mets Mika à jour"))
    }

    @Test fun `la deconnexion oublie le jeton, la cle et ce qui a ete dit`() = runBlocking {
        server.enqueue(reply())
        registrar.sync()
        val (_, first) = registered()
        assertNotNull(registrar.key())
        port.slowForget = true  // Firebase injoignable : la déconnexion n'attend pas plus de quelques secondes
        val started = System.nanoTime()
        registrar.forget()
        assertTrue(System.nanoTime() - started < 8_000_000_000L)
        assertEquals(1, port.forgotten)
        assertNull(registrar.key())
        assertEquals(PushState.LoggedOut, registrar.state.value)
        server.enqueue(reply())
        registrar.sync()  // une nouvelle session : tout est redit, avec une clé neuve
        val (_, second) = registered()
        assertFalse(first == second)
    }
}
