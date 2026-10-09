package fr.qwartz.mika.data.push

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

class PushPayloadTest {
    private val key = ByteArray(32) { it.toByte() }

    /** Produit par `backendv2/src/mika/adapters/push/seal.py` (clé 0..31, nonce 100..111) : les deux bouts s'accordent. */
    private val fromServer = mapOf(
        "v" to "1",
        "n" to "ZGVmZ2hpamtsbW5v",
        "c" to "MzmqREPLJe5bBzyA+ElIlCbgPD65WMFehaXJMI+Bn2rAnGClPzLpYZOHCvxUJ+rwO6sHfqJqg4Pak8WzgaFnMShPciz6aU92qVXcdCi7" +
            "AdZUSC8El/W96v2XX6geYGxrvAz+l6L7+21dA8PxH9JtEoXA",
    )

    private fun seal(plain: String, aad: ByteArray = PushPayload.AAD, k: ByteArray = key): Map<String, String> {
        val nonce = ByteArray(12) { (it * 7).toByte() }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(k, "AES"), GCMParameterSpec(128, nonce))
        cipher.updateAAD(aad)
        val enc = Base64.getEncoder()
        return mapOf("v" to "1", "n" to enc.encodeToString(nonce), "c" to enc.encodeToString(cipher.doFinal(plain.toByteArray())))
    }

    @Test
    fun opensWhatTheServerSealed() {
        val m = PushPayload.open(key, fromServer)
        assertEquals(PushPayload.Message("speech", 4242, "Tu es rentrée ? 🙂 « bien » é", 1791000000000, 2), m)
    }

    @Test
    fun anotherKeyOpensNothing() {
        assertNull(PushPayload.open(ByteArray(32), fromServer))
        assertNull(PushPayload.open(ByteArray(16), fromServer))
    }

    @Test
    fun aTamperedOrForeignSealOpensNothing() {
        val c = fromServer.getValue("c")
        val flipped = (if (c[10] == 'A') 'B' else 'A').toString()
        assertNull(PushPayload.open(key, fromServer + ("c" to c.substring(0, 10) + flipped + c.substring(11))))
        assertNull(PushPayload.open(key, fromServer + ("v" to "2")))
        assertNull(PushPayload.open(key, fromServer - "n"))
        assertNull(PushPayload.open(key, fromServer + ("n" to "pas du base64 !")))
        // un chiffré d'un autre usage (autres données associées) ne s'ouvre pas ici
        assertNull(PushPayload.open(key, seal("""{"t":"speech","id":1,"text":"x"}""", aad = "autre".toByteArray())))
    }

    @Test
    fun onlyASpeechWithTextAndAnIdIsShown() {
        assertNotNull(PushPayload.open(key, seal("""{"t":"speech","id":1,"text":"coucou","futur":true}""")))
        assertNull(PushPayload.open(key, seal("""{"t":"autre","id":1,"text":"coucou"}""")))
        assertNull(PushPayload.open(key, seal("""{"t":"speech","id":0,"text":"coucou"}""")))
        assertNull(PushPayload.open(key, seal("""{"t":"speech","id":3,"text":"  "}""")))
        assertNull(PushPayload.open(key, seal("""pas du json""")))
    }

    @Test
    fun aNewKeyIs32RandomBytes() {
        val a = PushPayload.newKey()
        assertEquals(32, a.size)
        assertEquals(false, a.contentEquals(PushPayload.newKey()))
    }
}
