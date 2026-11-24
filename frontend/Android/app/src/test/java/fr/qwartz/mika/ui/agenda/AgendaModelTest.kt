package fr.qwartz.mika.ui.agenda

import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.agenda.Accounts
import fr.qwartz.mika.data.moi.agenda.Alert
import fr.qwartz.mika.data.moi.agenda.AgendaApi
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaDone
import fr.qwartz.mika.data.moi.agenda.AgendaItem
import fr.qwartz.mika.data.moi.agenda.AgendaKinds
import fr.qwartz.mika.data.moi.agenda.AgendaLevels
import fr.qwartz.mika.data.moi.agenda.AgendaView
import fr.qwartz.mika.data.moi.agenda.CalendarCan
import fr.qwartz.mika.data.moi.agenda.Calendars
import fr.qwartz.mika.data.moi.agenda.EventFields
import fr.qwartz.mika.data.moi.agenda.FormModes
import fr.qwartz.mika.data.moi.agenda.Found
import fr.qwartz.mika.data.moi.agenda.Invitations
import fr.qwartz.mika.data.moi.agenda.MemoryAgendaPrefs
import fr.qwartz.mika.data.moi.agenda.Period
import fr.qwartz.mika.data.moi.agenda.Proposal
import fr.qwartz.mika.data.moi.agenda.ProposalDraft
import fr.qwartz.mika.data.moi.agenda.ProposalPreview
import fr.qwartz.mika.data.moi.agenda.Proposals
import fr.qwartz.mika.data.moi.agenda.ProviderReminders
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.mail.MainDispatcherRule
import fr.qwartz.mika.ui.shell.Load
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.time.OffsetDateTime

/** Une fausse API de l'Agenda : ce qu'elle rend, ce qu'on lui a demandé, et un appel qu'on retient. */
class FakeAgendaApi : AgendaApi(MoiApi(OkHttpClient(), { null }, {})) {
    var calendars = Calendars(zone = "Europe/Paris")
    var period = Period()
    var invitations = Invitations()
    var proposals = Proposals()
    var events = HashMap<Int, AgendaItem>()
    var writeFail: MoiError? = null
    val calls = mutableListOf<String>()
    val sent = mutableListOf<EventFields>()
    var gate: CompletableDeferred<Unit>? = null

    override suspend fun calendars(): MoiApi.Result<Calendars> = MoiApi.Result.Ok(calendars)
    override suspend fun period(start: String, end: String, calendars: List<String>): MoiApi.Result<Period> {
        calls += "period:$start:$end:${calendars.joinToString(",")}"
        return MoiApi.Result.Ok(period)
    }
    override suspend fun invitations(): MoiApi.Result<Invitations> = MoiApi.Result.Ok(invitations)
    override suspend fun proposals(): MoiApi.Result<Proposals> = MoiApi.Result.Ok(proposals)
    override suspend fun accounts(): MoiApi.Result<Accounts> = MoiApi.Result.Ok(Accounts())
    override suspend fun event(event: Int, occurrence: String): MoiApi.Result<AgendaItem> =
        events[event]?.let { MoiApi.Result.Ok(it) } ?: MoiApi.Result.Failed(MoiError(404, "Introuvable."))

    private suspend fun write(call: String, made: Int = 0): MoiApi.Result<AgendaDone> {
        calls += call
        gate?.await()
        writeFail?.let { return MoiApi.Result.Failed(it) }
        return MoiApi.Result.Ok(AgendaDone(message = "Fait.", made = if (made > 0) AgendaDone.Made("c", "u", made) else null))
    }

    override suspend fun create(calendar: String, fields: EventFields, key: String?): MoiApi.Result<AgendaDone> {
        sent += fields
        return write("create:$calendar", made = 51)
    }
    override suspend fun edit(event: Int, occurrence: String, scope: String, fields: EventFields, key: String?): MoiApi.Result<AgendaDone> {
        sent += fields
        return write("edit:$event:$occurrence:$scope")
    }
    override suspend fun delete(event: Int, occurrence: String, scope: String, key: String?) = write("delete:$event:$scope")
    override suspend fun accept(proposal: Int, seen: String, key: String?) = write("accept:$proposal:$seen")
    override suspend fun refuse(proposal: Int, note: String, key: String?) = write("refuse:$proposal")
    override suspend fun respond(event: Int, occurrence: String, answer: String, comment: String, scope: String, key: String?) =
        write("respond:$event:$answer:$comment")
    override suspend fun search(q: String, calendars: List<String>): MoiApi.Result<Found> {
        calls += "search:$q:${calendars.joinToString(",")}"
        return MoiApi.Result.Ok(Found())
    }
    var googleDirect = false
    override suspend fun saveAccount(kind: String, account: String, values: Map<String, Any>, key: String?): MoiApi.Result<AgendaDone> {
        calls += "save:$kind"
        return MoiApi.Result.Ok(AgendaDone(account = "google-1"))
    }
    override suspend fun googleStart(account: String): MoiApi.Result<AgendaDone> {
        calls += "google.start:$account"
        return MoiApi.Result.Ok(AgendaDone(url = "https://accounts.google.com/o/oauth2/v2/auth?state=s", direct = googleDirect))
    }
    override suspend fun googleFinish(account: String, text: String): MoiApi.Result<AgendaDone> {
        calls += "google.finish:$account:$text"
        return MoiApi.Result.Ok(AgendaDone(message = "Connecté à Google : l'agenda se synchronise."))
    }
}

/**
 * Les écrans de l'Agenda contre une fausse API : la vue (ce qu'elle lit, la vue retenue, un pas, décider de ce que Mika
 * propose, le direct), le formulaire (une création qui va à sa fiche, une modification qui n'envoie que ce qui change,
 * la portée d'une série demandée d'abord, un double appui), la fiche (supprimer la quitte).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AgendaModelTest {
    @get:Rule val main = MainDispatcherRule()

    private val api = FakeAgendaApi()
    private val prefs = MemoryAgendaPrefs()
    private var badges = 0
    /** Mardi 24 novembre 2026, 14:20 à Paris. */
    private val now = OffsetDateTime.parse("2026-11-24T14:20:00+01:00").toInstant().toEpochMilli()
    private val deps = AgendaDeps(api, prefs, { now }, { badges++ })

    private fun at(day: String, hhmm: String): Long = OffsetDateTime.parse("${day}T$hhmm:00+01:00").toInstant().toEpochMilli()

    private val mine = AgendaCalendar(
        key = "moi:a~mon-agenda", account = "moi:a", name = "Mon agenda", kind = AgendaKinds.SYSTEM, level = AgendaLevels.OWNER,
        group = "mine", primary = true, writable = true, reminder = "30", can = CalendarCan(write = true, settings = true, share = true, rights = true, remind = true),
    )
    private val google = mine.copy(key = "g~perso", account = "g", name = "Perso", kind = AgendaKinds.GOOGLE, primary = false)

    private suspend fun <T> Flow<T>.next(): T? = withTimeoutOrNull(500) { first() }

    @Test fun `la vue lit ses agendas, la periode sur ceux qu'elle montre et celui de Mika, ce qui attend`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine, google.copy(hidden = true)))
        api.invitations = Invitations(listOf(AgendaItem(event = 9, invitation = true, response = "attente")))
        val vm = main.model { AgendaViewModel(deps) }
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.calendars is Load.Ready)
        assertEquals("2026-11-24", vm.shownDate)
        // Planning d'abord : quatre semaines à partir d'aujourd'hui ; un agenda masqué n'est pas lu
        assertEquals("period:2026-11-24:2026-12-21:moi:a~mon-agenda,mika", api.calls.last())
        assertEquals(1, vm.invitations.size)
        assertTrue(vm.decideUnfolded)
    }

    @Test fun `la vue choisie est retenue, un pas avance d'une periode, aujourd'hui y ramene`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        val vm = main.model { AgendaViewModel(deps) }
        vm.resume()
        advanceUntilIdle()
        vm.choose(AgendaView.WEEK)
        advanceUntilIdle()
        assertEquals(AgendaView.WEEK, prefs.view())
        assertEquals("period:2026-11-23:2026-11-29:moi:a~mon-agenda,mika", api.calls.last())
        assertFalse(vm.decideUnfolded)
        vm.move(1)
        advanceUntilIdle()
        assertEquals("period:2026-11-30:2026-12-06:moi:a~mon-agenda,mika", api.calls.last())
        vm.goToday()
        advanceUntilIdle()
        assertEquals("2026-11-24", vm.shownDate)
        vm.openDay("2026-11-26")
        advanceUntilIdle()
        assertEquals(AgendaView.DAY, vm.view)
        assertEquals("period:2026-11-26:2026-11-26:moi:a~mon-agenda,mika", api.calls.last())
        // une autre ouverture reprend la vue retenue
        assertEquals(AgendaView.DAY, main.model { AgendaViewModel(AgendaDeps(api, prefs, { now })) }.view)
    }

    @Test fun `decocher ne change que l'affichage, sans relire`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine, google))
        val vm = main.model { AgendaViewModel(deps) }
        vm.resume()
        advanceUntilIdle()
        val before = api.calls.size
        vm.setShown("g~perso", false)
        assertEquals(setOf("g~perso"), prefs.off.value)
        assertFalse(vm.shown("g~perso", prefs.off.value))
        assertEquals(before, api.calls.size)
        vm.showOnly("g~perso")
        assertEquals(setOf("moi:a~mon-agenda", AgendaKinds.MIKA), prefs.off.value)
    }

    @Test fun `ajouter ce que Mika propose part tel qu'il a ete lu, une fois, et relit les pastilles`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        val p = Proposal(id = 7, op = Proposal.ADD, calendar = mine.key, decides = true, draft = ProposalDraft("Dîner", at("2026-11-28", "20:00"), at("2026-11-28", "23:00")), preview = ProposalPreview("…", "abc", ""))
        api.proposals = Proposals(listOf(p))
        val vm = main.model { AgendaViewModel(deps) }
        vm.resume()
        advanceUntilIdle()
        assertEquals(listOf(7), vm.adds.map { it.id })
        api.gate = CompletableDeferred()
        vm.accept(p)
        vm.accept(p)
        api.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it == "accept:7:abc" })
        assertEquals(1, badges)
        assertEquals("Fait.", vm.said.next())
    }

    @Test fun `le direct relit la vue quand l'agenda change, rien pour un autre sujet`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        val vm = main.model { AgendaViewModel(deps) }
        vm.resume()
        advanceUntilIdle()
        val before = api.calls.count { it.startsWith("period:") }
        vm.onLive(LiveSignal.of(Topics.MAIL to null))
        advanceUntilIdle()
        assertEquals(before, api.calls.count { it.startsWith("period:") })
        vm.onLive(LiveSignal.of(Topics.AGENDA to setOf(mine.key)))
        advanceUntilIdle()
        assertEquals(before + 1, api.calls.count { it.startsWith("period:") })
    }

    // ── le formulaire ──

    @Test fun `une creation part dans Mon agenda, puis va a la fiche ecrite`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(google, mine))
        val vm = main.model { AgendaFormViewModel(deps) }
        vm.open(Route.AgendaForm(FormModes.NEW, day = "2026-11-26", minute = 9 * 60))
        advanceUntilIdle()
        assertEquals(mine.key, vm.values.calendar)
        assertEquals(9 * 60 to 10 * 60, vm.values.h1 to vm.values.h2)
        vm.edit { it.copy(title = "Coiffeur") }
        vm.save()
        advanceUntilIdle()
        assertEquals("create:${mine.key}", api.calls.last())
        assertEquals("2026-11-26T09:00", api.sent.last().start)
        assertEquals(Route.AgendaEvent(51, ""), vm.done.next())
        assertEquals(1, badges)
    }

    @Test fun `changer d'agenda retire les rappels que le nouveau ne porte pas, adapte les autres`() = runTest {
        val outlook = mine.copy(key = "o~cal", account = "o", name = "Outlook", kind = AgendaKinds.MICROSOFT, primary = false,
            providerReminders = ProviderReminders(max = 1, email = false))
        val withAlerts = google.copy(providerReminders = ProviderReminders(max = 5, email = true))
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(withAlerts, outlook, mine))
        val vm = main.model { AgendaFormViewModel(deps) }
        vm.open(Route.AgendaForm(FormModes.NEW, day = "2026-11-26", minute = 9 * 60))
        advanceUntilIdle()
        vm.chooseCalendar(withAlerts.key)
        vm.addAlert(Alert(Alert.NOTIFICATION, 30))
        vm.addAlert(Alert(Alert.EMAIL, 1440))
        vm.chooseCalendar(outlook.key) // un seul, sans e-mail : le plus tôt, en notification — ce que l'écran montre
        assertEquals(listOf(Alert(Alert.NOTIFICATION, 1440)), vm.values.reminders)
        vm.chooseCalendar(mine.key) // l'agenda du système n'en porte aucun : rien d'invisible ne part
        vm.edit { it.copy(title = "Coiffeur") }
        vm.save()
        advanceUntilIdle()
        assertEquals("create:${mine.key}", api.calls.last())
        assertEquals(null, api.sent.last().reminders)
    }

    @Test fun `une modification n'envoie que ce qui change, une serie demande sa portee d'abord`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        api.events[42] = AgendaItem(
            event = 42, occurrence = "20261126T180000Z", calendar = mine.key, title = "Escalade", start = at("2026-11-26", "19:00"),
            end = at("2026-11-26", "21:00"), zone = "Europe/Paris", recurring = true, rule = "FREQ=WEEKLY;BYDAY=TH",
        )
        val vm = main.model { AgendaFormViewModel(deps) }
        vm.open(Route.AgendaForm(FormModes.EDIT, event = 42, occurrence = "20261126T180000Z"))
        advanceUntilIdle()
        vm.save()
        assertEquals("Rien n'a changé.", vm.said.next())
        vm.edit { it.copy(title = "Escalade · bloc") }
        vm.save()
        assertTrue(vm.askScope)
        assertFalse(api.calls.any { it.startsWith("edit:") })
        vm.save("suivants")
        advanceUntilIdle()
        assertEquals("edit:42:20261126T180000Z:suivants", api.calls.last())
        assertEquals(EventFields(title = "Escalade · bloc"), api.sent.last())
    }

    @Test fun `un double appui n'envoie qu'une fois, un refus se dit et laisse le formulaire`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        val vm = main.model { AgendaFormViewModel(deps) }
        vm.open(Route.AgendaForm(FormModes.NEW))
        advanceUntilIdle()
        api.gate = CompletableDeferred()
        api.writeFail = MoiError(400, "« title » : 300 caractères au plus.", mapOf("title" to "300 caractères au plus"))
        vm.save()
        vm.save()
        api.gate!!.complete(Unit)
        advanceUntilIdle()
        assertEquals(1, api.calls.count { it.startsWith("create:") })
        assertTrue(vm.said.next()!!.contains("300 caractères au plus"))
        assertTrue(vm.ready is Load.Ready)
    }

    @Test fun `la fin avant le debut ne part pas`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        val vm = main.model { AgendaFormViewModel(deps) }
        vm.open(Route.AgendaForm(FormModes.NEW, day = "2026-11-26", minute = 600))
        advanceUntilIdle()
        vm.edit { it.copy(h2 = 500) }
        vm.save()
        advanceUntilIdle()
        assertEquals("La fin est avant le début.", vm.problem)
        assertFalse(api.calls.any { it.startsWith("create:") })
    }

    // ── la fiche ──

    @Test fun `supprimer quitte la fiche, repondre relit les pastilles`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        api.events[42] = AgendaItem(event = 42, calendar = mine.key, title = "Afterwork", invitation = true, response = "attente", organized = false)
        val vm = main.model { AgendaItemViewModel(deps) }
        vm.open(42, "", 0)
        vm.resume()
        advanceUntilIdle()
        assertEquals("Afterwork", vm.item.valueOrNull?.title)
        vm.respond("non", "Désolé")
        advanceUntilIdle()
        assertEquals("respond:42:non:Désolé", api.calls.last())
        assertEquals(1, badges)
        vm.delete("un")
        advanceUntilIdle()
        assertEquals("delete:42:un", api.calls.last())
        assertEquals(Unit, vm.gone.next())
    }

    @Test fun `Google en retour direct - l'adresse de la page du serveur se colle et finit la connexion`() = runTest {
        api.googleDirect = true
        val vm = main.model { AgendaSettingsViewModel(deps) }
        vm.startPlug(AgendaKinds.GOOGLE)
        vm.googleStart {}
        advanceUntilIdle()
        assertTrue(vm.plug!!.direct && vm.plug!!.step == 2)
        val back = "https://mika.example.org/api/moi/agenda/google/retour?state=s&code=4/0A"
        vm.googleFinish(" $back ")
        advanceUntilIdle()
        assertTrue("google.finish:google-1:$back" in api.calls)
        assertEquals(3, vm.plug!!.step)
    }

    @Test fun `aucun agenda coche - aucune recherche, l'ecran le dit sans appeler le serveur`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine, google))
        for (key in listOf(mine.key, google.key, AgendaKinds.MIKA)) prefs.setShown(key, false)
        val vm = main.model { AgendaSearchViewModel(deps) }
        vm.type("dentiste")
        advanceUntilIdle()
        assertTrue(vm.unchecked)
        assertTrue(api.calls.none { it.startsWith("search:") })
        prefs.setShown(google.key, true) // un seul coché : on cherche là, et seulement là
        vm.type("dentist")
        advanceUntilIdle()
        assertFalse(vm.unchecked)
        assertEquals("search:dentist:${google.key}", api.calls.last())
    }

    @Test fun `une proposition qui n'attend plus se dit`() = runTest {
        api.calendars = Calendars(zone = "Europe/Paris", calendars = listOf(mine))
        val vm = main.model { AgendaItemViewModel(deps) }
        vm.open(0, "", 99)
        vm.resume()
        advanceUntilIdle()
        assertTrue(vm.proposal is Load.Failed)
    }
}
