package fr.qwartz.mika.ui.settings

import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.settings.BoxSettings
import fr.qwartz.mika.data.moi.settings.BoxValues
import fr.qwartz.mika.data.moi.settings.Replies
import fr.qwartz.mika.data.moi.settings.RuleEdit
import fr.qwartz.mika.data.moi.settings.RuleLine
import fr.qwartz.mika.data.moi.settings.SendRules
import fr.qwartz.mika.data.moi.settings.text
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Une boîte, un modèle pour toutes les boîtes de la session : un enregistrement fige ce qu'il envoie avant de partir et
 * ne pose rien sur la page d'une autre boîte ouverte avant sa réponse (R3-01) ; une lecture d'une ouverture précédente
 * ne remplit pas la suivante (R3-07) ; une règle changée ailleurs (409) se relit, sa version comprise (R3-10).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class BoxModelTest {
    @get:Rule val main = MainDispatcherRule()

    private fun rules(canal: String, version: String, n: Int) =
        SendRules(canal = canal, set = true, version = version, lines = List(n) { RuleLine(who = "ligne $it", reply = Replies.ASK) }, default = RuleLine(reply = Replies.NO))

    private val api = FakeSettingsApi().apply {
        box["pro"] = BoxSettings("pro", BoxValues(label = "Pro", address = "moi@atelier.fr", signature = "Signature pro"), rules = rules("courrier:pro", "vpro", 2))
        box["perso"] = BoxSettings("perso", BoxValues(label = "Perso", address = "moi@perso.fr", signature = "Signature perso"), rules = rules("courrier:perso", "vperso", 2))
    }
    private val vm by lazy { main.model { BoxViewModel(testDeps(api)) } }

    // ── R3-01 ──

    @Test fun `Pro enregistrée, Perso ouverte avant la réponse - la règle de Pro part avec tes choix, Perso ne bouge pas`() = runTest {
        val said = mutableListOf<String>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.said.collect { said += it } }
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.onLine(0, RuleEdit(false, Replies.ALONE))
        vm.edit("signature") { it.copy(signature = "Nouvelle signature") }
        api.hold("saveBox")
        vm.save()
        // ← puis Perso, lue avant la réponse ; on y tape
        vm.open("perso", "e2")
        advanceUntilIdle()
        vm.edit("label") { it.copy(label = "Perso, la vraie") }
        api.release("saveBox")
        advanceUntilIdle()

        assertEquals("pro", api.sent.first { it.first.startsWith("saveBox") }.first.substringAfter(':'))
        val rule = api.sent.single { it.first == "rules" }.second
        assertEquals("courrier:pro", rule.text("canal"))
        assertEquals("vpro", rule.text("version"))
        assertEquals(listOf("seule", "accord"), rule["lines"]!!.jsonArray.map { it.jsonObject.text("reply") })
        // la page de Perso : ni relue par la réponse de Pro, ni effacée ; ce qu'on y tape reste
        assertEquals("perso", vm.key)
        assertEquals("courrier:perso", vm.settings!!.rules.canal)
        assertEquals("Perso, la vraie", vm.values.label)
        assertEquals("Signature perso", vm.values.signature)
        assertEquals(listOf(Replies.ASK, Replies.ASK), vm.lines.map { it.reply })
        assertFalse(api.calls.drop(api.calls.indexOf("saveBox:pro")).contains("box:pro"))
        // le sort se dit nommé : ce n'est pas celui de Perso
        assertTrue(said.any { it.startsWith("« Pro » :") })
    }

    @Test fun `Perso n'a pas le même nombre de lignes - rien ne plante, la règle de Pro part entière`() = runTest {
        api.box["perso"] = api.box.getValue("perso").copy(rules = rules("courrier:perso", "vperso", 3))
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.onLine(1, RuleEdit(true, Replies.NO))
        vm.edit("tone") { it.copy(tone = "sobre") }
        // la boîte part d'abord ; la règle, après sa réponse — quand Perso est déjà ouverte
        api.hold("saveBox")
        vm.save()
        vm.open("perso", "e2")
        advanceUntilIdle()
        api.release("saveBox")
        advanceUntilIdle()
        val rule = api.sent.single { it.first == "rules" }.second
        assertEquals("courrier:pro", rule.text("canal"))
        assertEquals(2, rule["lines"]!!.jsonArray.size)
        assertEquals(3, vm.lines.size)
    }

    @Test fun `un refus de Pro arrivé sur Perso - rien sous ses champs, le toast nomme Pro`() = runTest {
        val said = mutableListOf<String>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.said.collect { said += it } }
        api.saveBoxResult = MoiApi.Result.Failed(MoiError(400, "Le formulaire a des erreurs.", mapOf("accounts.pro.signature" to "trop longue")))
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.edit("signature") { it.copy(signature = "x".repeat(10)) }
        api.hold("saveBox")
        vm.save()
        vm.open("perso", "e2")
        advanceUntilIdle()
        api.release("saveBox")
        advanceUntilIdle()
        assertTrue(vm.errors.isEmpty())
        assertTrue(said.any { it.startsWith("« Pro » :") && "trop longue" in it })
        assertFalse(vm.busy)
    }

    @Test fun `Tester après l'enregistrement ne teste pas la boîte ouverte entre-temps`() = runTest {
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.edit("signature") { it.copy(signature = "Autre") }
        api.hold("saveBox")
        vm.test()
        vm.open("perso", "e2")
        advanceUntilIdle()
        api.release("saveBox")
        advanceUntilIdle()
        assertFalse(api.calls.any { it.startsWith("testBox") })
    }

    // ── R3-07 ──

    @Test fun `la lecture lente de Pro, revenue après celle de Perso, ne remplit pas Perso`() = runTest {
        api.hold("box:pro")
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.open("perso", "e2")
        advanceUntilIdle()
        api.release("box:pro")
        advanceUntilIdle()
        assertEquals("Signature perso", vm.values.signature)
        assertEquals("courrier:perso", vm.settings!!.rules.canal)
    }

    // ── R3-10 ──

    @Test fun `la règle changée ailleurs (409) se relit avec sa version, et l'enregistrement suivant part sur elle`() = runTest {
        val said = mutableListOf<String>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { vm.said.collect { said += it } }
        vm.open("pro", "e1")
        advanceUntilIdle()
        vm.onLine(0, RuleEdit(true, Replies.ALONE))
        api.rulesResult = MoiApi.Result.Failed(MoiError(409, "La situation a changé entre-temps. Relis, puis recommence."))
        // réglée ailleurs entre-temps : trois lignes, une autre version
        api.box["pro"] = api.box.getValue("pro").copy(rules = rules("courrier:pro", "v2", 3))
        vm.save()
        advanceUntilIdle()
        assertEquals("v2", vm.settings!!.rules.version)
        assertEquals(3, vm.lines.size)
        assertFalse(vm.dirty)
        assertTrue(said.last().endsWith("texte:${fr.qwartz.mika.R.string.settings_rules_reread}"))
        api.rulesResult = null
        vm.onLine(2, RuleEdit(true, Replies.ALONE))
        vm.save()
        advanceUntilIdle()
        assertEquals("v2", api.sent.last { it.first == "rules" }.second.text("version"))
    }
}
