package fr.qwartz.mika.data.files

import fr.qwartz.mika.data.files.ImagePlan.Decision
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ImagePlanTest {
    private val mo = 1024L * 1024
    private val five = 5 * mo

    @Test fun `une image qui tient et que le serveur lit reste telle quelle`() {
        assertEquals(Decision.Keep, ImagePlan.decide("chat.png", "image/png", 2 * mo, fromCamera = false, cap = five))
        assertEquals(Decision.Keep, ImagePlan.decide("a.webp", "image/webp", 10, fromCamera = false, cap = five))
    }

    @Test fun `une photo prise pour Mika est toujours réduite, sans rien en dire`() {
        assertEquals(Decision.Reencode(five, null), ImagePlan.decide("photo.jpg", "image/jpeg", 2 * mo, fromCamera = true, cap = five))
    }

    @Test fun `une image trop lourde est réduite, et on le dit`() {
        assertEquals(
            Decision.Reencode(five, "photo.jpg réduite pour tenir sous 5 Mo."),
            ImagePlan.decide("photo.jpg", "image/jpeg", 9 * mo, fromCamera = false, cap = five),
        )
        // Le message est déjà presque plein : réduite pour tenir dans ce qui reste.
        assertEquals(
            Decision.Reencode(mo, "photo.jpg réduite pour tenir dans un seul message."),
            ImagePlan.decide("photo.jpg", "image/jpeg", 2 * mo, fromCamera = false, cap = mo),
        )
    }

    @Test fun `un format que le serveur ne lit pas est converti en JPEG`() {
        assertEquals(Decision.Reencode(five, null), ImagePlan.decide("IMG.HEIC", "image/heic", 2 * mo, fromCamera = false, cap = five))
        assertEquals("IMG.jpg", ImagePlan.jpegName("IMG.HEIC"))
        assertEquals("photo.jpg", ImagePlan.jpegName(".heic"))
        assertEquals("sans-extension.jpg", ImagePlan.jpegName("sans-extension"))
    }

    @Test fun `un GIF ou un fichier ordinaire n'est jamais réencodé`() {
        assertEquals(Decision.Keep, ImagePlan.decide("anim.gif", "image/gif", 3 * mo, fromCamera = false, cap = five))
        assertEquals(
            Decision.Reject("anim.gif ignoré : 7 Mo (maximum 5 Mo)."),
            ImagePlan.decide("anim.gif", "image/gif", 7 * mo, fromCamera = false, cap = five),
        )
        assertEquals(
            Decision.Reject(AttachmentPolicy.TOO_HEAVY),
            ImagePlan.decide("notes.pdf", "application/pdf", 3 * mo, fromCamera = false, cap = 2 * mo),
        )
        assertEquals(Decision.Keep, ImagePlan.decide("notes.pdf", "application/pdf", 3 * mo, fromCamera = false, cap = five))
    }

    @Test fun `illisible, ou plus de place du tout`() {
        assertEquals(Decision.Reject("x.png illisible : non joint."), ImagePlan.decide("x.png", "image/png", -1, false, five))
        assertEquals(Decision.Reject(AttachmentPolicy.TOO_HEAVY), ImagePlan.decide("p.jpg", "image/jpeg", 9 * mo, false, cap = 1024))
    }

    @Test fun `la place laissée à un fichier`() {
        assertEquals(five, ImagePlan.capFor(0))
        assertEquals(five, ImagePlan.capFor(6 * mo))
        assertEquals(mo, ImagePlan.capFor(10 * mo))
        assertEquals(0, ImagePlan.capFor(12 * mo))
    }

    @Test fun `les dimensions - le côté long borné, les proportions gardées, jamais agrandies`() {
        assertEquals(2048 to 1536, ImagePlan.targetSize(4032, 3024, 2048))
        assertEquals(1200 to 1600, ImagePlan.targetSize(3000, 4000, 1600))
        assertEquals(800 to 600, ImagePlan.targetSize(800, 600, 2048))
        assertEquals(2048 to 1, ImagePlan.targetSize(10000, 2, 2048))
    }

    @Test fun `l'échelle des essais - 85, 75, 65, puis 1 600 px`() {
        assertEquals(listOf(85, 75, 65), ImagePlan.LADDER.filter { it.maxEdge == 2048 }.map { it.quality })
        assertEquals(1600, ImagePlan.LADDER.last().maxEdge)
        assertTrue(ImagePlan.fits(10, 10))
        assertFalse(ImagePlan.fits(11, 10))
        assertFalse(ImagePlan.fits(0, 10))
    }
}
