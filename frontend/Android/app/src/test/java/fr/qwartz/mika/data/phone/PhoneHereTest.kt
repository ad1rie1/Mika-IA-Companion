package fr.qwartz.mika.data.phone

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** « Envoyer » depuis l'écran après « Écrire autre chose » : sa proposition inchangée part comme la sienne. */
class PhoneHereTest {
    private val draft = PhoneDraft(7, "whatsapp", "611ae22e6d5c431f8b537e638278435d", "Léa", "J'arrive dans 10 min", 9, 1)

    @Test fun `sa proposition inchangée, aux espaces près, part comme la sienne`() {
        assertNull(PhoneHere.typedOrNull(null, draft))
        assertNull(PhoneHere.typedOrNull("  J'arrive dans 10 min \n", draft))
    }

    @Test fun `ce que tu as changé part comme le tien, sans ses espaces autour`() {
        assertEquals("J'arrive dans 20 min", PhoneHere.typedOrNull(" J'arrive dans 20 min ", draft))
    }

    @Test fun `le champ tient encore sa proposition, aux espaces près`() {
        assertTrue(PhoneHere.unchanged(" J'arrive dans 10 min\n", draft.text))
        assertFalse(PhoneHere.unchanged("J'arrive dans 20 min", draft.text))
    }

    @Test fun `l'action gardée ne sert que si elle répond au fil montré (R3-06)`() {
        assertTrue(PhoneHere.canDeliver("Maman", "maman "))
        assertTrue(PhoneHere.canDeliver("Rando  dimanche", "Rando dimanche"))
        // une autre conversation sous la même clé : copié
        assertFalse(PhoneHere.canDeliver("Maman", "Plombier"))
        // aucune action, ou une action qui ne dit pas à qui elle répond : copié
        assertFalse(PhoneHere.canDeliver(null, "Maman"))
        assertFalse(PhoneHere.canDeliver("", "Maman"))
        assertFalse(PhoneHere.canDeliver("Maman", ""))
        // depuis la notification d'une proposition (rien à comparer : elle nomme déjà à qui)
        assertTrue(PhoneHere.canDeliver("", null))
    }
}
