package fr.qwartz.mika.data.avatar

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class AvatarManifestTest {
    private val sample = """
        {"portraits": {
          "neutral": {"file": "neutral.webp", "face": [0.5, 0.26],
                      "blink": {"file": "neutral.blink.webp", "x": 500, "y": 300, "w": 120, "h": 60}},
          "happy": {"file": "happy.webp", "face": [0.57, 0.25]},
          "sleep": {"file": "sleep.webp"}
        }, "version": 1, "width": 1080, "height": 1440, "extra": "ignoré"}
    """.trimIndent()

    @Test fun `le manifeste de portraits_py se lit`() {
        val m = AvatarManifest.parse(sample)!!
        assertEquals(1080, m.width)
        assertEquals(setOf("neutral", "happy", "sleep"), m.ids)
        val neutral = m.portraits.getValue("neutral")
        assertEquals(500, neutral.blink?.x)
        assertEquals(0.26f, neutral.faceY, 1e-6f)
        // Sans visage noté, le milieu haut de l'image.
        assertEquals(0.5f, m.portraits.getValue("sleep").faceX, 1e-6f)
    }

    @Test fun `illisible, sans taille ou sans portrait neutre, pas d'avatar`() {
        assertNull(AvatarManifest.parse("pas du json"))
        assertNull(AvatarManifest.parse("""{"width": 0, "height": 10, "portraits": {"neutral": {"file": "n.webp"}}}"""))
        assertNull(AvatarManifest.parse("""{"width": 10, "height": 10, "portraits": {"happy": {"file": "h.webp"}}}"""))
    }

    @Test fun `un fichier hors du dossier fait disparaître le portrait, un clignement hors de l'image seulement le clignement`() {
        val m = AvatarManifest.parse(
            """
            {"width": 100, "height": 100, "portraits": {
              "neutral": {"file": "n.webp", "blink": {"file": "b.webp", "x": 90, "y": 0, "w": 20, "h": 10}},
              "happy": {"file": "../secret"},
              "sad": {"file": ".hidden"},
              "angry": {"file": "a.webp", "blink": {"file": "x/b.webp", "x": 0, "y": 0, "w": 5, "h": 5}}
            }}
            """.trimIndent(),
        )!!
        assertEquals(setOf("neutral", "angry"), m.ids)
        assertNull(m.portraits.getValue("neutral").blink)
        assertNull(m.portraits.getValue("angry").blink)
    }

    @Test fun `un manifeste dont le neutre est douteux ne vaut rien`() {
        assertNull(AvatarManifest.parse("""{"width": 10, "height": 10, "portraits": {"neutral": {"file": "a/b.webp"}}}"""))
    }
}
