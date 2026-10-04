package fr.qwartz.mika.data.avatar

import fr.qwartz.mika.data.avatar.AvatarDirector.Aura
import fr.qwartz.mika.data.mind.MindLabels
import fr.qwartz.mika.data.mind.MindState
import fr.qwartz.mika.data.mind.Mood
import fr.qwartz.mika.data.mind.SleepPhases
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AvatarDirectorTest {
    /** Ce que `portraits.py` rend : les 29 émotions et les trois états. */
    private val all = MindLabels.EMOTIONS.keys + setOf(
        AvatarDirector.WAVE, AvatarDirector.TIRED, AvatarDirector.SLEEP,
    )

    private fun mind(emotion: String? = null, intensity: Double = 0.8, energy: Double? = null, sleep: String = SleepPhases.AWAKE) =
        MindState(sleepPhase = sleep, energy = energy, mood = emotion?.let { Mood(it, intensity) })

    private fun scene(mind: MindState?, typing: Boolean = false, greeting: Boolean = false, available: Set<String> = all) =
        AvatarDirector.scene(mind, typing, greeting, available)

    @Test fun `chaque émotion a son portrait et sa lumière`() {
        for ((name, meta) in MindLabels.EMOTIONS) {
            val s = scene(mind(name))
            assertEquals(name, name, s.portrait)
            val expected = when (meta.category) {
                MindLabels.Category.POSITIVE -> Aura.WARM
                MindLabels.Category.NEGATIVE -> Aura.COOL
                MindLabels.Category.COMPLEX -> Aura.DUSK
                MindLabels.Category.NEUTRAL -> Aura.NEUTRAL
            }
            assertEquals(name, expected, s.aura)
        }
    }

    @Test fun `endormie, rien ne la réveille à l'écran`() {
        val asleep = mind("excited", sleep = SleepPhases.REM)
        val s = scene(asleep, typing = true, greeting = true)
        assertEquals(AvatarDirector.SLEEP, s.portrait)
        assertEquals(Aura.NIGHT, s.aura)
        assertTrue(s.asleep)
    }

    @Test fun `le salut passe avant ce qu'elle écrit, qui passe avant son humeur`() {
        assertEquals(AvatarDirector.WAVE, scene(mind("sad"), typing = true, greeting = true).portrait)
        assertEquals(AvatarDirector.THINKING, scene(mind("sad"), typing = true).portrait)
        assertEquals("sad", scene(mind("sad")).portrait)
    }

    @Test fun `une émotion à peine marquée laisse le visage au repos`() {
        assertEquals(AvatarDirector.NEUTRAL, scene(mind("angry", intensity = 0.2)).portrait)
        assertEquals("angry", scene(mind("angry", intensity = AvatarDirector.MIN_INTENSITY)).portrait)
    }

    @Test fun `fatiguée, une humeur légère cède à la fatigue, une forte se voit quand même`() {
        assertEquals(AvatarDirector.TIRED, scene(mind("happy", intensity = 0.4, energy = 0.1)).portrait)
        assertEquals(AvatarDirector.TIRED, scene(mind(null, energy = 0.1)).portrait)
        assertEquals("happy", scene(mind("happy", intensity = 0.7, energy = 0.1)).portrait)
        assertEquals("happy", scene(mind("happy", intensity = 0.4, energy = 0.6)).portrait)
    }

    @Test fun `rien de connu, une émotion inconnue ou un portrait manquant donnent le visage neutre`() {
        assertEquals(AvatarDirector.NEUTRAL, scene(null).portrait)
        assertEquals(AvatarDirector.NEUTRAL, scene(mind("ecstatic")).portrait)
        val partial = setOf(AvatarDirector.NEUTRAL, "happy")
        assertEquals(AvatarDirector.NEUTRAL, scene(mind("sad"), available = partial).portrait)
        assertEquals(AvatarDirector.NEUTRAL, scene(mind("sad", sleep = SleepPhases.DEEP), available = partial).portrait)
        assertEquals("happy", scene(mind(" Happy "), available = partial).portrait)
    }
}
