package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Les règles de Paramètres › Comptes Teams (`frontend/Web/src/screens/teams/settings.ts`) : ce qu'on sait de son extension. */
class TeamsSettingsRulesTest {
    private val now = 1_790_800_000_000L

    // ── Teams ──

    @Test fun `ce qu'on sait de son extension`() {
        assertEquals(Tone.NEUTRAL to "inactif", batchWords(TeamsAccount(enabled = false, lastBatch = now), now))
        assertEquals(Tone.WARN to "rien reçu de son extension", batchWords(TeamsAccount(), now))
        assertEquals(Tone.OK to "dernier envoi il y a 3 h", batchWords(TeamsAccount(lastBatch = now - 3 * 3_600_000), now))
        assertTrue(sharedAccountSentence(TeamsAccount(level = Levels.READ, ownerName = "Léa")).startsWith("Léa te l'a ouvert : lire."))
    }
}
