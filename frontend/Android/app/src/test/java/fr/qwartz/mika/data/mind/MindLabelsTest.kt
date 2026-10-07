package fr.qwartz.mika.data.mind

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MindLabelsTest {
    /** `backendv2/src/mika/vocab/affect.py::Emotion`, dans l'ordre de `emotions.ts`. */
    private val all29 = listOf(
        "neutral", "happy", "excited", "love", "proud", "grateful", "playful", "amused", "hopeful", "relieved",
        "sad", "angry", "scared", "disgusted", "frustrated", "lonely", "anxious", "bored", "jealous",
        "surprised", "thinking", "confused", "embarrassed", "nostalgic", "dreamy", "determined", "mischievous",
        "curious", "melancholic",
    )

    @Test fun `les 29 émotions, ni plus ni moins, chacune traduite`() {
        assertEquals(29, MindLabels.EMOTIONS.size)
        assertEquals(all29, MindLabels.EMOTIONS.keys.toList())
        for (name in all29) {
            val label = MindLabels.emotion(name)
            assertFalse(name, label == name)
            assertTrue(name, MindLabels.isEmotionName(name))
        }
    }

    @Test fun `un nom inconnu est rendu tel quel, jamais replié sur neutre`() {
        assertEquals("ecstatic", MindLabels.emotion("ecstatic"))
        assertEquals("Curieuse", MindLabels.emotion(" Curious "))
        assertFalse(MindLabels.isEmotionName("ecstatic"))
    }

    @Test fun `la forme de la ligne d'état est en minuscules et sans ponctuation`() {
        assertEquals("curieuse", MindLabels.emotionLower("curious"))
        assertEquals("excitée", MindLabels.emotionLower("excited"))
        assertEquals("s'ennuie", MindLabels.emotionLower("bored"))
        assertEquals("surprise", MindLabels.emotionLower("surprised"))
        assertEquals("pleine d'espoir", MindLabels.emotionLower("hopeful"))
    }

    @Test fun `sommeil, lieux, moments, rêves et besoins`() {
        assertEquals("éveillée", MindLabels.sleepPhase("awake"))
        assertEquals("sommeil paradoxal (elle rêve)", MindLabels.sleepPhase("rem"))
        assertEquals("à son bureau", MindLabels.place("desk"))
        assertNull(MindLabels.place("cuisine"))
        assertEquals(6, MindLabels.PLACES.size)
        assertEquals("Soir · 21 h", MindLabels.momentOfDay("evening", 21.0))
        assertEquals("rêve mélancolique", MindLabels.dreamType("melancholic"))
        assertEquals(5, MindLabels.DREAM_TYPES.size)
        assertEquals(listOf("Compagnie", "S'exprimer", "Apprendre"), MindLabels.DRIVES.values.toList())
        assertEquals("Son dernier journal", MindLabels.journalTitle("  "))
        assertEquals("Son journal d'hier", MindLabels.journalTitle("Son journal d'hier"))
    }
}
