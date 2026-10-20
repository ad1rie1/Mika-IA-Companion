package fr.qwartz.mika.data.push

import fr.qwartz.mika.data.phone.PhoneDraft
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
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
        assertEquals(
            PushPayload.Pushed.Speech(PushPayload.Message("speech", 4242, "Tu es rentrée ? 🙂 « bien » é", 1791000000000, 2)),
            m,
        )
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

    private val thread = "611ae22e6d5c431f8b537e638278435d"

    @Test
    fun `une réponse proposée s'ouvre à part de la parole`() {
        val m = PushPayload.open(
            key,
            seal(
                """{"t":"phone_draft","id":77,"app":"whatsapp","thread":"$thread","to":"Léa","text":"J'arrive dans 10 min 🙂",""" +
                    """"exp":1791007200000,"ts":1791000000000,"futur":1}""",
            ),
        )
        assertEquals(
            PushPayload.Pushed.Draft(PhoneDraft(77, "whatsapp", thread, "Léa", "J'arrive dans 10 min 🙂", 1791007200000, 1791000000000)),
            m,
        )
        // la parole n'est pas une proposition, ni l'inverse
        assertTrue(PushPayload.open(key, seal("""{"t":"speech","id":1,"text":"coucou"}""")) is PushPayload.Pushed.Speech)
    }

    @Test
    fun `une proposition illisible ne se montre jamais`() {
        fun draft(fields: String) = PushPayload.open(key, seal("""{"t":"phone_draft",$fields}"""))
        val ok = """"id":5,"app":"messages","thread":"$thread","to":"Sam","text":"oui","exp":1791007200000"""
        assertNotNull(draft(ok))
        assertNull(draft(ok.replace(""""id":5""", """"id":0""")))
        assertNull(draft(ok.replace(""""app":"messages"""", """"app":"telegram"""")))
        assertNull(draft(ok.replace(thread, "pas-une-cle")))
        assertNull(draft(ok.replace(""""text":"oui"""", """"text":"  """")))
        assertNull(draft(ok.replace(""""exp":1791007200000""", """"exp":0""")))
        // le même scellé abîmé ne s'ouvre pas, quel que soit son type
        val sealed = seal("""{"t":"phone_draft",$ok}""")
        assertNull(PushPayload.open(ByteArray(32), sealed))
        // ouvrir puis comprendre : deux temps
        assertEquals("""{"t":"phone_draft",$ok}""", PushPayload.unseal(key, sealed))
        assertNull(PushPayload.read("""{"t":"phone_draft"}"""))
        assertNull(PushPayload.read("""["phone_draft"]"""))
    }

    @Test
    fun aNewKeyIs32RandomBytes() {
        val a = PushPayload.newKey()
        assertEquals(32, a.size)
        assertEquals(false, a.contentEquals(PushPayload.newKey()))
    }
}
