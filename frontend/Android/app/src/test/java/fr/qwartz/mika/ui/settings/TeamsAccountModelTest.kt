package fr.qwartz.mika.ui.settings

import fr.qwartz.mika.data.moi.settings.Replies
import fr.qwartz.mika.data.moi.settings.RuleEdit
import fr.qwartz.mika.data.moi.settings.RuleLine
import fr.qwartz.mika.data.moi.settings.SendRules
import fr.qwartz.mika.data.moi.settings.TeamsSettings
import fr.qwartz.mika.data.moi.settings.TeamsValues
import fr.qwartz.mika.data.moi.settings.text
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test

/**
 * Un compte Teams, un modèle pour tous les comptes : la clé neuve de son extension est liée à son compte — montrée sur sa
 * page seulement, même rouverte, jamais sur celle d'un autre — (R3-05) ; un enregistrement fige sa règle avant de partir
 * (R3-01).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class TeamsAccountModelTest {
    @get:Rule val main = MainDispatcherRule()

    private fun rules(canal: String, version: String) =
        SendRules(canal = canal, set = true, version = version, lines = listOf(RuleLine(reply = Replies.ASK)), default = RuleLine(reply = Replies.NO))

    private val api = FakeSettingsApi().apply {
        account["pro"] = TeamsSettings("pro", TeamsValues(label = "Pro"), rules = rules("teams:pro", "vpro"))
        account["perso"] = TeamsSettings("perso", TeamsValues(label = "Perso"), rules = rules("teams:perso", "vperso"))
    }
    private val vm by lazy { main.model { TeamsAccountViewModel(testDeps(api)) } }

    @Test fun `la clé de Pro, revenue pendant qu'on est sur Perso, ne s'y montre pas et attend Pro`() = runTest {
        vm.open("pro", "e1")
        advanceUntilIdle()
        api.hold("newKey")
        vm.newKey()
        // ← avant la réponse, puis Perso
        vm.open("perso", "e2")
        advanceUntilIdle()
        api.release("newKey")
        advanceUntilIdle()
        assertNull(vm.freshKey)
        // retour sur Pro : sa clé t'y attend, nommée
        vm.open("pro", "e3")
        advanceUntilIdle()
        assertEquals(FreshKey("pro", "Pro", "mtk_neuve"), vm.freshKey)
        // « J'ai collé » : elle s'oublie
        vm.keySeen("pro")
        assertNull(vm.freshKey)
    }

    @Test fun `la clé montrée sur sa page reste jusqu'à « J'ai collé », même la page rouverte`() = runTest {
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.newKey()
        advanceUntilIdle()
        assertEquals("mtk_neuve", vm.freshKey?.key)
        vm.open("pro", "e2")
        advanceUntilIdle()
        assertEquals("mtk_neuve", vm.freshKey?.key)
    }

    @Test fun `Pro enregistrée, Perso ouverte avant la réponse - la règle partie est celle de Pro`() = runTest {
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.onLine(0, RuleEdit(true, Replies.DRAFT))
        vm.edit("tone") { it.copy(tone = "chaleureux") }
        api.hold("saveTeams")
        vm.save()
        vm.open("perso", "e2")
        advanceUntilIdle()
        api.release("saveTeams")
        advanceUntilIdle()
        val rule = api.sent.single { it.first == "rules" }.second
        assertEquals("teams:pro", rule.text("canal"))
        assertEquals("vpro", rule.text("version"))
        assertEquals("teams:perso", vm.settings!!.rules.canal)
        assertEquals(Replies.ASK, vm.lines.single().reply)
    }
}
