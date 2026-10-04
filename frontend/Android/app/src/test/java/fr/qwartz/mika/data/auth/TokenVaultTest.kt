package fr.qwartz.mika.data.auth

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.security.InvalidKeyException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Un AES-256-GCM logiciel à la place du Keystore Android : mêmes règles, sans matériel. */
private class SoftwareCipher : KeystoreCipher {
    var key: SecretKey? = null

    private fun keyOrNew(): SecretKey = key ?: KeyGenerator.getInstance("AES").apply { init(256) }.generateKey().also { key = it }

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

class TokenVaultTest {
    @get:Rule val folder = TemporaryFolder()
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var file: File
    private val store: DataStore<Preferences> by lazy {
        file = folder.newFile("auth.preferences_pb").also { it.delete() }
        PreferenceDataStoreFactory.create(scope = scope, produceFile = { file })
    }
    private val cipher = SoftwareCipher()

    @After fun tearDown() = scope.cancel()

    @Test fun `un jeton écrit se relit, même par un coffre neuf`() = runBlocking {
        TokenVault(store, cipher).write("mw_abc123")
        val read = TokenVault(store, cipher).read()
        assertTrue(read is TokenVault.Read.Present)
        assertEquals("mw_abc123", (read as TokenVault.Read.Present).token)
        assertFalse(read.toString().contains("mw_"))
    }

    @Test fun `le jeton n'est jamais en clair sur le disque`() = runBlocking {
        TokenVault(store, cipher).write("mw_secret_qui_ne_doit_pas_fuiter")
        val disk = file.readBytes().toString(Charsets.ISO_8859_1)
        assertFalse(disk.contains("mw_secret"))
        assertTrue(disk.contains("v1:"))
    }

    @Test fun `une clé invalidée vide le coffre et demande de rouvrir la session`() = runBlocking {
        TokenVault(store, cipher).write("mw_abc")
        cipher.deleteKey() // ce que fait le Keystore quand la clé est invalidée
        assertEquals(TokenVault.Read.Invalid, TokenVault(store, cipher).read())
        assertEquals(TokenVault.Read.Absent, TokenVault(store, cipher).read())
    }

    @Test fun `un blob abîmé ou d'un autre format ne lève pas`() = runBlocking {
        store.edit { it[stringPreferencesKey("token")] = "v1:pas-du-base64:???" }
        assertEquals(TokenVault.Read.Invalid, TokenVault(store, cipher).read())
        store.edit { it[stringPreferencesKey("token")] = "v9:AAAA:AAAA" }
        assertEquals(TokenVault.Read.Invalid, TokenVault(store, cipher).read())
    }

    @Test fun `un chiffré lié à un autre usage ne s'ouvre pas ici`() = runBlocking {
        val other = cipher.encrypt("mw_ailleurs".toByteArray(), "autre/usage".toByteArray())
        val b64 = java.util.Base64.getEncoder()
        store.edit {
            it[stringPreferencesKey("token")] = "v1:${b64.encodeToString(other.iv)}:${b64.encodeToString(other.ciphertext)}"
        }
        assertEquals(TokenVault.Read.Invalid, TokenVault(store, cipher).read())
    }

    @Test fun `effacé, il n'y a plus rien`() = runBlocking {
        val vault = TokenVault(store, cipher)
        vault.write("mw_abc")
        vault.clear()
        assertEquals(TokenVault.Read.Absent, vault.read())
        assertEquals(TokenVault.Read.Absent, TokenVault(store, cipher).read())
    }
}
