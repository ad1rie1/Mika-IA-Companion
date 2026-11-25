package fr.qwartz.mika.ui.settings

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.settings.GivenShare
import fr.qwartz.mika.data.moi.settings.ShareKinds
import fr.qwartz.mika.data.moi.settings.Shares
import fr.qwartz.mika.ui.components.FakeSettingsApi
import fr.qwartz.mika.ui.components.testDeps
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/** « Retirer » vise le partage touché — sa sorte, sa clé, sa personne —, pas un rang de la liste relue entre-temps
 *  (R3-11). */
@OptIn(ExperimentalCoroutinesApi::class)
class SharesModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val lea = GivenShare(ShareKinds.MAIL, "pro", "Pro", "p-lea", "Léa", Levels.READ)
    private val paul = GivenShare(ShareKinds.TEAMS, "atelier", "Atelier", "p-paul", "Paul", Levels.USE)
    private val julien = GivenShare(ShareKinds.MCP, "meteo", "meteo", "p-julien", "Julien", Levels.READ)
    private val api = FakeSettingsApi().apply { shares = Shares(given = listOf(lea, paul, julien)) }
    private val vm by lazy { main.model { SharesViewModel(testDeps(api)) } }

    @Test fun `la liste se relit pendant la confirmation - c'est le partage touché qui part`() = runTest {
        vm.open("", "e1")
        vm.resume()
        advanceUntilIdle()
        vm.askWithdraw(paul)
        // retiré depuis le web pendant que la fenêtre est ouverte : les rangs glissent
        api.shares = Shares(given = listOf(paul, julien))
        vm.resume()
        advanceUntilIdle()
        assertEquals(paul, vm.withdrawing)
        vm.confirmWithdraw()
        advanceUntilIdle()
        assertEquals(listOf("share:teams:atelier:p-paul:"), api.calls.filter { it.startsWith("share:") })
        assertNull(vm.withdrawing)
    }

    @Test fun `annuler ne retire rien, et une nouvelle ouverture oublie la confirmation`() = runTest {
        vm.open("", "e1")
        vm.resume()
        advanceUntilIdle()
        vm.askWithdraw(julien)
        vm.cancelWithdraw()
        vm.askWithdraw(lea)
        vm.open("", "e2")
        assertNull(vm.withdrawing)
        assertFalse(api.calls.any { it.startsWith("share:") })
    }
}
