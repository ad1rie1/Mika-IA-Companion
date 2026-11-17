package fr.qwartz.mika.data.auth

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.data.settings.SettingsStore
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.security.InvalidKeyException
import java.util.concurrent.TimeUnit
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Fermer une session : jusqu'au bout même si la portée qui l'a demandée s'en va (un écran quitté pendant le contrôle
 * d'un 401), et en rendant le jeton au serveur quand le mot de passe vient de changer.
 */
class AuthRepositoryTest {
    @get:Rule val folder = TemporaryFolder()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(5, TimeUnit.SECONDS).build()
    private val hooks = FakeHooks()
    private val clock = object : Clock {
        override fun wallMs() = 1_800_000_000_000L
        override fun elapsedMs() = 0L
    }
    private lateinit var vault: TokenVault
    private lateinit var settings: SettingsStore
    private lateinit var repo: AuthRepository

    /** Ce que la session fait ailleurs ; [gate] retient la coupure de la connexion, le temps d'annuler l'appelant. */
    private class FakeHooks : SessionHooks {
        @Volatile var gate: CompletableDeferred<Unit>? = null
        val entered = CompletableDeferred<Unit>()
        @Volatile var wiped = 0
        @Volatile private var owner: String? = null

        override suspend fun beforeSignOut() {
            entered.complete(Unit)
            gate?.await()
        }

        override suspend fun wipeLocalData(keepDraft: Boolean) {
            if (!keepDraft) wiped++
        }

        override suspend fun localOwner(): String? = owner
        override suspend fun setLocalOwner(owner: String) {
            this.owner = owner
        }
    }

    /** Un AES-256-GCM logiciel à la place du Keystore Android. */
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
            c.init(Cipher.DECRYPT_MODE, key ?: throw InvalidKeyException("clé absente"), GCMParameterSpec(128, iv))
            c.updateAAD(aad)
            return c.doFinal(ciphertext)
        }
        override fun deleteKey() {
            key = null
        }
    }

    private fun store(name: String) =
        PreferenceDataStoreFactory.create(scope = scope, produceFile = { folder.root.resolve("$name.preferences_pb") })

    private fun json(code: Int, body: String) =
        MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    @Before fun setUp() {
        server.start()
        vault = TokenVault(store("auth"), SoftwareCipher())
        settings = SettingsStore(store("settings"))
        repo = AuthRepository(AuthApi(client), vault, settings, hooks, clock, "Android · test")
    }

    @After fun tearDown() {
        server.close()
        client.dispatcher.executorService.shutdown()
        scope.cancel()
    }

    /** Une session ouverte par un jeton (`whoami`), comme « Utiliser un jeton (dev) ». */
    private suspend fun signIn() {
        server.enqueue(json(200, """{"authenticated":true,"username":"adrien","person_id":"p-1"}"""))
        assertEquals(AuthRepository.LoginResult.Success, repo.loginWithToken(server.url("/").toString(), "mw_telephone"))
        assertNotNull(server.takeRequest(5, TimeUnit.SECONDS))
    }

    @Test fun `une déconnexion commencée va au bout, même si la portée qui l'a lancée est annulée`() = runBlocking {
        signIn()
        val gate = CompletableDeferred<Unit>()
        hooks.gate = gate
        server.enqueue(json(401, """{"error":"Authentification requise."}"""))
        val check = scope.launch { repo.checkAfterUnauthorized() }
        withTimeout(5_000) { hooks.entered.await() }
        // l'écran qui lisait s'en va pendant que la session se ferme (la connexion coupée, Firebase oublié…)
        check.cancel()
        gate.complete(Unit)
        withTimeout(5_000) { check.join() }
        assertTrue(repo.session.value is Session.LoggedOut)
        assertNull(repo.credentials())
        assertTrue(vault.read() is TokenVault.Read.Absent)
        assertEquals(1, hooks.wiped)
    }

    @Test fun `le mot de passe changé - la session se ferme en rendant le jeton, avec son mot`() = runBlocking {
        signIn()
        server.enqueue(json(200, """{"ok":true}"""))
        repo.closeSession("Mot de passe changé : reconnecte-toi.")
        val revoked = server.takeRequest(5, TimeUnit.SECONDS)
        assertNotNull("le jeton n'a pas été rendu", revoked)
        assertEquals("DELETE", revoked!!.method)
        assertEquals("/auth/token", revoked.url.encodedPath)
        assertEquals("Bearer mw_telephone", revoked.headers["Authorization"])
        assertEquals(Session.LoggedOut("Mot de passe changé : reconnecte-toi."), repo.session.value)
        assertNull(repo.credentials())
        assertEquals(1, hooks.wiped)
    }

    @Test fun `un jeton déjà révoqué - la session se ferme quand même`() = runBlocking {
        signIn()
        server.enqueue(json(401, """{"error":"Authentification requise."}"""))
        repo.closeSession("Mot de passe changé : reconnecte-toi.")
        assertEquals("DELETE", server.takeRequest(5, TimeUnit.SECONDS)?.method)
        assertEquals(Session.LoggedOut("Mot de passe changé : reconnecte-toi."), repo.session.value)
        assertTrue(vault.read() is TokenVault.Read.Absent)
    }

    @Test fun `la session garde l'identifiant de son jeton, relu au démarrage (R3-03)`() = runBlocking {
        server.enqueue(json(200, """{"token":"mw_telephone","token_id":42,"client":"mobile","authenticated":true,"username":"adrien","person_id":"p-1"}"""))
        assertEquals(AuthRepository.LoginResult.Success, repo.login(server.url("/").toString(), "adrien", "un-mot-de-passe"))
        assertEquals(42L, repo.tokenId())
        // l'application relancée : la session rouverte sans réseau le garde
        val again = AuthRepository(AuthApi(client), vault, settings, hooks, clock, "Android · test")
        again.restore()
        assertEquals(42L, again.tokenId())
    }

    @Test fun `une session sans l'identifiant de son jeton n'en invente pas`() = runBlocking {
        signIn()
        assertNull(repo.tokenId())
    }
}
