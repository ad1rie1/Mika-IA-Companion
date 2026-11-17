package fr.qwartz.mika.ui.settings

import fr.qwartz.mika.data.moi.settings.HEADERS_TO_RETYPE
import fr.qwartz.mika.data.moi.settings.Service
import fr.qwartz.mika.data.moi.settings.ServiceTool
import fr.qwartz.mika.data.moi.settings.Services
import fr.qwartz.mika.data.moi.settings.ToolChoices
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Un service, un modèle pour tous les services : les choix d'outils faits sur l'un partent pour lui, jamais pour celui
 * ouvert avant la réponse (R3-01) ; une adresse qui mène ailleurs redemande ses en-têtes gardés, dit sous leur champ
 * avant l'envoi (R3-02, ADR 0236).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ServiceModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeSettingsApi().apply {
        services = Services(
            items = listOf(
                Service(name = "agenda", purpose = "Son agenda", url = "https://agenda.exemple.fr/mcp", headers = true, tools = listOf(ServiceTool(remote = "search", choice = ToolChoices.OFF))),
                Service(name = "meteo", purpose = "La météo", url = "https://meteo.exemple.fr/mcp", tools = listOf(ServiceTool(remote = "search", choice = ToolChoices.OFF))),
            ),
        )
    }
    private val vm by lazy { main.model { ServiceViewModel(testDeps(api)) } }

    @Test fun `les choix d'outils d'agenda partent pour agenda, même météo ouverte avant la réponse`() = runTest {
        vm.open("agenda", "e1")
        advanceUntilIdle()
        vm.pick("search", ToolChoices.ACT)
        vm.onPurpose("Son agenda, et celui du club")
        api.hold("saveService")
        vm.save()
        vm.open("meteo", "e2")
        advanceUntilIdle()
        api.release("saveService")
        advanceUntilIdle()
        assertTrue("tools:agenda:search=action" in api.calls)
        assertFalse(api.calls.any { it.startsWith("tools:meteo") })
        assertEquals("meteo", vm.service?.name)
        assertEquals(ToolChoices.OFF, vm.picks["search"])
    }

    @Test fun `une adresse qui mène ailleurs redemande ses en-têtes, sous leur champ, et rien ne part`() = runTest {
        vm.open("agenda", "e1")
        advanceUntilIdle()
        vm.onUrl("https://autre.example/mcp")
        vm.save()
        advanceUntilIdle()
        assertEquals(mapOf("secret_headers" to HEADERS_TO_RETYPE), vm.errors)
        assertFalse(api.calls.any { it.startsWith("saveService") })
        // les retirer : l'adresse part, avec leur retrait
        vm.onClearHeaders(true)
        vm.save()
        advanceUntilIdle()
        val sent = api.sent.single { it.first == "saveService:agenda" }.second
        assertEquals(JsonPrimitive("https://autre.example/mcp"), sent["url"])
        assertEquals(JsonPrimitive(true), sent["clear_headers"])
    }

    @Test fun `un autre chemin sur le même serveur ne redemande rien`() = runTest {
        vm.open("agenda", "e1")
        advanceUntilIdle()
        vm.onUrl("https://AGENDA.exemple.fr:443/v2/mcp")
        vm.save()
        advanceUntilIdle()
        assertTrue(vm.errors.isEmpty())
        assertTrue("saveService:agenda" in api.calls)
    }
}
