package fr.qwartz.mika.service

import fr.qwartz.mika.service.ServiceController.Reason
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ServiceControllerTest {
    @Test fun `il faut une session et l'arrière-plan voulu`() {
        assertTrue(ServiceController.shouldRun(loggedIn = true, background = true, startOnBoot = false, reason = Reason.APP))
        assertFalse(ServiceController.shouldRun(loggedIn = false, background = true, startOnBoot = true, reason = Reason.APP))
        assertFalse(ServiceController.shouldRun(loggedIn = true, background = false, startOnBoot = true, reason = Reason.APP))
    }

    @Test fun `au démarrage du téléphone, seulement avec « Démarrer avec le téléphone »`() {
        assertFalse(ServiceController.shouldRun(loggedIn = true, background = true, startOnBoot = false, reason = Reason.BOOT))
        assertTrue(ServiceController.shouldRun(loggedIn = true, background = true, startOnBoot = true, reason = Reason.BOOT))
        assertFalse(ServiceController.shouldRun(loggedIn = true, background = false, startOnBoot = true, reason = Reason.BOOT))
    }

    @Test fun `après une mise à jour, il reprend s'il tournait`() {
        assertTrue(ServiceController.shouldRun(loggedIn = true, background = true, startOnBoot = false, reason = Reason.UPDATE))
        assertFalse(ServiceController.shouldRun(loggedIn = false, background = true, startOnBoot = false, reason = Reason.UPDATE))
    }
}
