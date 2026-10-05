package fr.qwartz.mika.avatar3d

import org.junit.Assert.assertTrue
import org.junit.Test

/** Les signes du repère, vérifiés par la géométrie (jamais par une constante : c'est un commentaire qui s'était trompé sur le web). */
class CharacterFrameTest {
    @Test fun `pitch positif baisse le regard`() {
        assertTrue(CharacterFrame.pitch(0.3f).rotate(CharacterFrame.FORWARD).y < -0.2f)
    }

    @Test fun `yaw positif tourne vers sa droite`() {
        assertTrue(CharacterFrame.yaw(0.3f).rotate(CharacterFrame.FORWARD).x > 0.2f)
    }

    @Test fun `roll positif penche le haut de la tête vers sa droite`() {
        assertTrue(CharacterFrame.roll(0.3f).rotate(CharacterFrame.UP).x > 0.2f)
    }
}
