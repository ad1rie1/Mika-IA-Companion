package fr.qwartz.mika.data.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les clés opaques (ADR 0120) : les 16 premiers octets de SHA-256 en hexadécimal minuscule, stables d'une notification à
 * l'autre. Les vecteurs viennent de Python (`hashlib.sha256(s.encode()).digest()[:16].hex()`), comme le serveur.
 */
class PhoneKeysTest {
    private val pkg = "com.whatsapp"
    private val thread = "611ae22e6d5c431f8b537e638278435d"
    private val sender = "ad1a8f0892e6237390883850a4b0cd49"

    @Test fun `une clé fait 32 caractères hexadécimaux minuscules`() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb924", PhoneKeys.hash(""))
        val k = PhoneKeys.hash("n'importe quoi 🙂")
        assertEquals(32, k.length)
        assertTrue(PhoneKeys.isKey(k))
    }

    @Test fun `les clés suivent la formule du protocole`() {
        assertEquals(thread, PhoneKeys.thread(pkg, "33612345678@s.whatsapp.net"))
        assertEquals(sender, PhoneKeys.sender(pkg, "key-lea"))
        assertEquals("1c8f00f0d06d31f3dbf46991cab79431", PhoneKeys.id(pkg, thread, sender, 1791000000000, "Tu viens ce soir ? é🙂"))
    }

    @Test fun `les mêmes entrées donnent la même clé, une autre appli une autre`() {
        assertEquals(PhoneKeys.thread(pkg, "conv"), PhoneKeys.thread(pkg, "conv"))
        assertNotEquals(PhoneKeys.thread(pkg, "conv"), PhoneKeys.thread("com.whatsapp.w4b", "conv"))
        assertNotEquals(PhoneKeys.id(pkg, thread, sender, 1, "a"), PhoneKeys.id(pkg, thread, sender, 2, "a"))
    }

    @Test fun `une clé se reconnaît`() {
        assertTrue(PhoneKeys.isKey(thread))
        assertFalse(PhoneKeys.isKey(thread.uppercase()))
        assertFalse(PhoneKeys.isKey(thread.dropLast(1)))
        assertFalse(PhoneKeys.isKey("z" + thread.drop(1)))
    }
}
