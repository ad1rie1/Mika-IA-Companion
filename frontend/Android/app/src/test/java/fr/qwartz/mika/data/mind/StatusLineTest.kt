package fr.qwartz.mika.data.mind

import fr.qwartz.mika.data.net.LinkState
import org.junit.Assert.assertEquals
import org.junit.Test

class StatusLineTest {
    private val awake = MindState(place = "desk", mood = Mood("curious", 0.6))

    @Test fun `un problème de lien passe avant tout`() {
        assertEquals("hors ligne · nouvel essai dans 4 s", StatusLine.of(LinkState.Offline(10_000), true, awake, 6_200))
        assertEquals("connexion…", StatusLine.of(LinkState.Offline(10_000), false, awake, 10_000))
        assertEquals("connexion…", StatusLine.of(LinkState.Connecting, true, awake, 0))
        assertEquals("pas de réseau", StatusLine.of(LinkState.NoNetwork, false, awake, 0))
        assertEquals("session expirée", StatusLine.of(LinkState.SessionExpired, false, awake, 0))
        assertEquals("connexion refusée", StatusLine.of(LinkState.Refused(1008), false, awake, 0))
    }

    @Test fun `puis elle écrit`() {
        assertEquals("en train d'écrire…", StatusLine.of(LinkState.Online, true, awake.copy(sleepPhase = "rem"), 0))
    }

    @Test fun `puis son sommeil`() {
        assertEquals("dort", StatusLine.of(LinkState.Online, false, awake.copy(sleepPhase = "light_sleep"), 0))
        assertEquals("dort · rêve", StatusLine.of(LinkState.Online, false, awake.copy(sleepPhase = "rem"), 0))
        assertEquals("dort profondément", StatusLine.of(LinkState.Online, false, awake.copy(sleepPhase = "deep_sleep"), 0))
    }

    @Test fun `puis ce qu'elle fait, l'émotion seulement quand elle est marquée`() {
        assertEquals("éveillée · à son bureau · curieuse", StatusLine.of(LinkState.Online, false, awake, 0))
        assertEquals("éveillée · à son bureau", StatusLine.of(LinkState.Online, false, awake.copy(mood = Mood("curious", 0.2)), 0))
        assertEquals("éveillée · à son bureau", StatusLine.of(LinkState.Online, false, awake.copy(mood = Mood("neutral", 0.9)), 0))
        assertEquals("éveillée", StatusLine.of(LinkState.Online, false, MindState(), 0))
        assertEquals("en ligne", StatusLine.of(LinkState.Online, false, null, 0))
    }
}
