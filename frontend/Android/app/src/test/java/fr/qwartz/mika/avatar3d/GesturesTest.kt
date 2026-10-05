package fr.qwartz.mika.avatar3d

import fr.qwartz.mika.avatar3d.Gestures.Decision
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** L'ordre des portes de `gestures.ts`, à l'identique. */
class GesturesTest {
    private fun decide(
        emotion: String,
        intensity: Float = 0.9f,
        blend: List<Pair<String, Float>> = emptyList(),
        persona: String? = null,
        sleep: String = "awake",
        last: Float? = null,
        ambient: Boolean = false,
        active: String? = null,
    ) = Gestures.decide(Gestures.Input(emotion, intensity, blend, persona, sleep, nowSeconds = 100f, lastOneshotAt = last, ambient = ambient, activeVariant = active))

    @Test fun `les 29 émotions ont leur ligne`() {
        assertEquals(29, Gestures.EMOTION_GESTURE.size)
    }

    @Test fun `endormie, une pensée murmurée ou une ambivalence ne font aucun geste`() {
        assertEquals(Decision.None("asleep"), decide("excited", sleep = "rem"))
        assertEquals(Decision.None("inner_persona"), decide("excited", persona = "inner"))
        assertEquals(Decision.None("ambivalent"), decide("excited", blend = listOf("excited" to 0.5f, "sad" to 0.45f)))
    }

    @Test fun `la dérive change la posture, jamais un geste`() {
        assertEquals(Decision.None("ambient_drift"), decide("excited", ambient = true))
        assertEquals(Decision.IdleVariant("idle_sad"), decide("sad", intensity = 0.7f, ambient = true))
    }

    @Test fun `le seuil, son hystérésis pour une posture tenue, et le délai entre deux gestes`() {
        assertEquals(Decision.None("below_threshold"), decide("sad", intensity = 0.55f))
        assertEquals(Decision.IdleVariant("idle_sad"), decide("sad", intensity = 0.55f, active = "idle_sad"))
        assertEquals(Decision.None("cooldown"), decide("excited", last = 95f))
        assertTrue(decide("excited", last = 80f) is Decision.Oneshot)
    }
}
