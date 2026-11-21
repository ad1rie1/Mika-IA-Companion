package fr.qwartz.mika.data.moi.carte

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Le cache disque des photos suit ce que le serveur dit d'elles (`Cache-Control: private, max-age=86400`, R2-A08) : la
 * stratégie de Coil 3 par défaut ressert ce qu'elle a gardé sans jamais regarder `max-age` — une photo dont les droits
 * ont pris fin (le serveur répond 404) resterait visible jusqu'à la déconnexion. Au-delà de son âge, elle se redemande.
 */
class PhotoCacheTest {
    private val at = 1_795_000_000_000L
    private val hour = 3_600_000L

    @Test fun `gardée moins d'un jour, elle se ressert, au-delà, elle se redemande`() {
        assertTrue(photoFresh("private, max-age=86400", at, at + hour))
        assertTrue(photoFresh("Private, Max-Age=86400", at, at + 23 * hour))
        assertFalse(photoFresh("private, max-age=86400", at, at + 25 * hour))
    }

    @Test fun `sans âge dit, ou qu'on ne doit pas garder - elle se redemande`() {
        assertFalse(photoFresh(null, at, at + 1))
        assertFalse(photoFresh("", at, at + 1))
        assertFalse(photoFresh("private, max-age=0", at, at + 1))
        assertFalse(photoFresh("no-store", at, at + 1))
        assertFalse(photoFresh("no-cache, max-age=86400", at, at + 1))
        assertFalse(photoFresh("max-age=abc", at, at + 1))
        // une réponse d'une horloge en avance (gardée « dans le futur ») ne dure pas pour autant
        assertFalse(photoFresh("max-age=86400", at + 48 * hour, at))
    }

    @Test fun `le cache mémoire ne la ressert pas plus d'une heure sans repasser par le disque`() {
        // R3-11 : le cache mémoire de Coil 3 ressert une image avant toute requête, sans passer par la stratégie du
        // disque — une photo aux droits finis restait visible tant que l'application vivait. Sa clé change chaque heure :
        // passé ce temps, la photo repasse par le disque (son max-age), puis par le serveur (son 404)
        val url = "https://mika.example/api/moi/carte/photo/p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02"
        val start = at - at % hour
        assertEquals(photoMemoryKey(url, start), photoMemoryKey(url, start + hour - 1))
        assertNotEquals(photoMemoryKey(url, start), photoMemoryKey(url, start + hour))
        assertNotEquals(photoMemoryKey(url, start), photoMemoryKey(url, start + 25 * hour))
        assertNotEquals(photoMemoryKey(url, start), photoMemoryKey(url.replace("p:3f", "p:4f"), start))
        assertTrue(photoMemoryKey(url, start).startsWith(url))
    }
}
