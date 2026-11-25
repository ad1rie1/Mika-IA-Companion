package fr.qwartz.mika.ui.tools

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.tools.AccessLine
import fr.qwartz.mika.data.moi.tools.CHOICES
import fr.qwartz.mika.data.moi.tools.McpLimits
import fr.qwartz.mika.data.moi.tools.ReceivedService
import fr.qwartz.mika.data.moi.tools.SERVICE_LABELS
import fr.qwartz.mika.data.moi.tools.Service
import fr.qwartz.mika.data.moi.tools.ServiceTool
import fr.qwartz.mika.data.moi.tools.Services
import fr.qwartz.mika.data.moi.settings.ShareKinds
import fr.qwartz.mika.data.moi.tools.choiceWords
import fr.qwartz.mika.data.moi.tools.defaultWords
import fr.qwartz.mika.data.moi.settings.doneText
import fr.qwartz.mika.data.moi.tools.forYou
import fr.qwartz.mika.data.moi.tools.headersToRetype
import fr.qwartz.mika.data.moi.tools.receivedSentence
import fr.qwartz.mika.data.moi.tools.servedOf
import fr.qwartz.mika.data.moi.tools.serviceChanges
import fr.qwartz.mika.data.moi.tools.serviceNameProblem
import fr.qwartz.mika.data.moi.tools.serviceTrouble
import fr.qwartz.mika.data.moi.tools.sharedWith
import fr.qwartz.mika.data.moi.tools.shownChoice
import fr.qwartz.mika.data.moi.tools.stateWords
import fr.qwartz.mika.data.moi.tools.toolChoiceChanges
import fr.qwartz.mika.data.moi.tools.toolState
import fr.qwartz.mika.data.moi.tools.urlProblem
import fr.qwartz.mika.data.moi.tools.whoWords
import fr.qwartz.mika.ui.components.ActionButton
import fr.qwartz.mika.ui.components.ChoiceSeg
import fr.qwartz.mika.ui.components.ConfirmDialog
import fr.qwartz.mika.ui.components.DangerButton
import fr.qwartz.mika.ui.components.HeadCard
import fr.qwartz.mika.ui.components.Move
import fr.qwartz.mika.ui.components.SaveBar
import fr.qwartz.mika.ui.components.SetDivider
import fr.qwartz.mika.ui.components.SetField
import fr.qwartz.mika.ui.components.SetGroup
import fr.qwartz.mika.ui.components.SetHead
import fr.qwartz.mika.ui.components.SetItem
import fr.qwartz.mika.ui.components.SetNote
import fr.qwartz.mika.ui.components.SetRow
import fr.qwartz.mika.ui.components.SetSwitch
import fr.qwartz.mika.ui.components.SettingsDeps
import fr.qwartz.mika.ui.components.SettingsEffects
import fr.qwartz.mika.ui.components.SettingsLive
import fr.qwartz.mika.ui.components.SettingsLoading
import fr.qwartz.mika.ui.components.SettingsModel
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.components.settingsPage
import fr.qwartz.mika.ui.components.shareRoute
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/*
 * Paramètres › Services MCP (ADR 0192) : tes services — distants, par une adresse https, à toi seule —, leur état et
 * leurs outils (coupé, il lit, il agit : ADR 0129 ; un outil nouveau ou changé attend son choix), les brancher, les
 * tester, les régler, les retirer ; ceux qu'on te partage, en lecture. Porté de `frontendv2/src/screens/outils/settings.ts`.
 */

// ── La liste ────────────────────────────────────────────────────────────

class ServicesViewModel(graph: AppGraph) : SettingsModel(graph) {
    var load by mutableStateOf<Load<Services>>(Load.Loading)
        private set

    fun resume() {
        viewModelScope.launch { read() }
    }

    /** Relu sans bruit : un retour sur la page, ou le direct (ADR 0308) qui dit que ce qu'elle montre a changé. */
    suspend fun read() {
        when (val got = api.services()) {
            is MoiApi.Result.Ok -> load = Load.Ready(got.value)
            is MoiApi.Result.Failed -> if (load !is Load.Ready) load = Load.Failed(got.error) else say(got.error)
        }
    }

    fun retry() {
        load = Load.Loading
        resume()
    }
}

@Composable
internal fun ServicesPage(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: ServicesViewModel = viewModel(key = "settings.services|$session") { ServicesViewModel(graph) }
    FollowLive(graph.live, SettingsLive.SERVICES, vm, onShown = { vm.resume() }) { vm.read() }
    SettingsEffects(vm)
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_services), BarNav.BACK) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { shell.navigate(settingsPage(SettingsPages.SERVICE)) },
                icon = { MIcon(R.drawable.ic_m_plus, null) },
                text = { Text(stringResource(R.string.settings_services_plug)) },
            )
        },
    ) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) { got ->
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 96.dp)) {
                if (!got.plugged) NoteBox(stringResource(R.string.settings_services_unplugged), R.drawable.ic_m_info, Modifier.padding(16.dp))
                SetHead(stringResource(R.string.settings_yours))
                SetGroup {
                    if (got.items.isEmpty()) SetRow(stringResource(R.string.settings_services_none), stringResource(R.string.settings_services_none_help))
                    got.items.forEachIndexed { i, s ->
                        if (i > 0) SetDivider()
                        val served = servedOf(s.tools)
                        val sub = listOf(
                            s.url,
                            pluralStringResource(R.plurals.settings_services_served, served.total, served.served, served.total),
                            if (served.review > 0) stringResource(R.string.settings_services_review, served.review) else "",
                            sharedWith(s).takeIf { it.isNotBlank() }?.let { stringResource(R.string.settings_services_shared_with, it) }.orEmpty(),
                        ).filter { it.isNotBlank() }.joinToString(" · ")
                        SetItem(R.drawable.ic_m_plug, s.name, sub, onClick = { shell.navigate(settingsPage(SettingsPages.SERVICE, s.name)) }) {
                            stateWords(s.state).let { (tone, words) -> Tag(words, tone) }
                        }
                    }
                }
                if (got.received.isNotEmpty()) {
                    SetHead(stringResource(R.string.settings_shared_with_you))
                    SetGroup {
                        got.received.forEachIndexed { i, r ->
                            if (i > 0) SetDivider()
                            SetItem(
                                R.drawable.ic_m_lock,
                                r.name,
                                listOf(ofName(r.ownerName), pluralTools(r.tools.size)).filter { it.isNotBlank() }.joinToString(" · "),
                                onClick = { shell.navigate(settingsPage(SettingsPages.SERVICE, r.name)) },
                            ) { stateWords(r.state).let { (tone, words) -> Tag(words, tone) } }
                        }
                    }
                }
                SetNote(stringResource(R.string.settings_services_note))
            }
        }
    }
}

@Composable
private fun pluralTools(n: Int): String =
    if (n == 0) stringResource(R.string.settings_services_no_tool) else pluralStringResource(R.plurals.settings_services_tools, n, n)

// ── Un service ──────────────────────────────────────────────────────────

/**
 * Un de tes services : ses réglages et le choix de chacun de ses outils (une barre « Enregistrer » pour les deux), ses
 * lignes d'accès en lecture ; ou un service qu'on te partage, en lecture seulement.
 *
 * Un modèle pour tous les services de la session, gardé comme celui d'une boîte (`BoxViewModel`) : un enregistrement
 * fige le service, ses réglages et ses choix d'outils avant de partir, et rien ne se pose sur la page d'un autre service
 * ouvert avant sa réponse (R3-01). Une adresse qui mène ailleurs redemande ses en-têtes gardés, dit sous leur champ
 * avant l'envoi (ADR 0236).
 */
class ServiceViewModel(deps: SettingsDeps) : SettingsModel(deps) {
    var load by mutableStateOf<Load<Unit>>(Load.Loading)
        private set
    var name = ""
        private set
    var service by mutableStateOf<Service?>(null)
        private set
    var received by mutableStateOf<ReceivedService?>(null)
        private set
    var purpose by mutableStateOf("")
        private set
    var whenToUse by mutableStateOf("")
        private set
    var url by mutableStateOf("")
        private set
    var headers by mutableStateOf("")
        private set
    /** Retirer ses en-têtes gardés à l'enregistrement. */
    var clearHeaders by mutableStateOf(false)
        private set
    var enabled by mutableStateOf(true)
        private set
    /** Les choix d'outils tapés, par outil (son nom sur le serveur). */
    var picks by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var errors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    private var busyFor by mutableStateOf<String?>(null)
    val busy: Boolean get() = busyFor != null && busyFor == openedFor
    private var loading: Job? = null

    fun open(name: String, entry: String) {
        if (!reopen(entry, name)) return
        this.name = name
        service = null
        received = null
        errors = emptyMap()
        reload()
    }

    fun retry() = reload()

    private fun reload() {
        loading?.cancel()
        val from = opening
        val n = name
        loading = viewModelScope.launch {
            load = Load.Loading
            val got = api.services()
            if (!stillOn(from)) return@launch
            when (got) {
                is MoiApi.Result.Ok -> {
                    val mine = got.value.items.firstOrNull { it.name == n }
                    if (mine != null) {
                        fill(mine)
                        load = Load.Ready(Unit)
                    } else {
                        received = got.value.received.firstOrNull { it.name == n }
                        load = if (received != null) Load.Ready(Unit) else Load.Failed(MoiError(404, text(R.string.settings_service_not_yours)))
                    }
                }
                is MoiApi.Result.Failed -> load = Load.Failed(got.error)
            }
        }
    }

    private fun fill(s: Service) {
        service = s
        purpose = s.purpose
        whenToUse = s.whenToUse
        url = s.url
        headers = ""
        clearHeaders = false
        enabled = s.enabled
        picks = s.tools.associate { it.remote to shownChoice(it) }
        errors = emptyMap()
    }

    private suspend fun refresh(n: String, from: String) {
        val got = api.services()
        if (stillOn(from)) (got as? MoiApi.Result.Ok)?.value?.items?.firstOrNull { it.name == n }?.let(::fill)
    }

    val dirty: Boolean
        get() {
            val s = service ?: return false
            return serviceChanges(s, purpose, whenToUse, url, enabled, headers, clearHeaders).isNotEmpty() ||
                toolChoiceChanges(s.tools, picks).isNotEmpty()
        }

    fun onPurpose(v: String) { purpose = v.take(McpLimits.PURPOSE); errors = errors - "purpose" }
    fun onWhenToUse(v: String) { whenToUse = v.take(McpLimits.PURPOSE); errors = errors - "when_to_use" }
    fun onUrl(v: String) { url = v.take(McpLimits.URL); errors = errors - "url" - "secret_headers" }
    fun onHeaders(v: String) { headers = v.take(McpLimits.HEADERS); errors = errors - "secret_headers" }
    fun onClearHeaders(v: Boolean) { clearHeaders = v; errors = errors - "secret_headers" }
    fun onEnabled(v: Boolean) { enabled = v; errors = errors - "enabled" }
    fun pick(remote: String, choice: String) { picks = picks + (remote to choice) }

    fun cancel() {
        service?.let(::fill)
    }

    /** Enregistrer : le service, ses réglages et ses choix d'outils figés avant le premier appel ; [then] : le geste qui
     *  attendait, s'il est fait et que sa page est encore à l'écran. */
    fun save(then: (suspend () -> Unit)? = null) {
        if (busy) return
        val s = service ?: return
        val values = serviceChanges(s, purpose, whenToUse, url, enabled, headers, clearHeaders)
        val choices = toolChoiceChanges(s.tools, picks)
        if (values.isEmpty() && choices.isEmpty()) {
            if (then != null) viewModelScope.launch { then() }
            return
        }
        if ("url" in values) {
            val bad = urlProblem(url)
            if (bad.isNotEmpty()) {
                errors = mapOf("url" to bad)
                return
            }
        }
        // une adresse qui mène ailleurs : ses en-têtes gardés se redonnent ou se retirent (le serveur refuserait sinon)
        val retype = headersToRetype(s, values)
        if (retype.isNotEmpty()) {
            errors = retype
            say(text(R.string.settings_service_headers_retype))
            return
        }
        val from = opening
        val n = name
        busyFor = from
        viewModelScope.launch {
            val said = mutableListOf<String>()
            var ok = true
            var saved = false
            if (values.isNotEmpty()) {
                when (val got = api.saveService(n, values)) {
                    is MoiApi.Result.Ok -> {
                        saved = true
                        said += got.value.message
                    }
                    is MoiApi.Result.Failed -> {
                        ok = false
                        refusedFor(from, n, got.error, setOf("purpose", "when_to_use", "url", "secret_headers", "enabled"), SERVICE_LABELS)
                            ?.let { errors = it }
                    }
                }
            }
            if (ok && choices.isNotEmpty()) {
                when (val got = api.chooseTools(n, choices)) {
                    is MoiApi.Result.Ok -> said += got.value.message
                    is MoiApi.Result.Failed -> {
                        ok = false
                        sayFor(from, n, got.error.said)
                    }
                }
            }
            if (ok) sayFor(from, n, said.filter { it.isNotBlank() }.joinToString(" ").ifBlank { text(R.string.settings_saved) })
            if (ok || saved) refresh(n, from)
            if (busyFor == from) busyFor = null
            if (ok && then != null && stillOn(from)) then()
        }
    }

    /** Un service dont on vient de changer l'adresse se teste à sa nouvelle adresse : enregistrée d'abord. Le service
     *  est figé au toucher. */
    fun test() {
        val n = name
        val from = opening
        val gesture: suspend () -> Unit = {
            say(text(R.string.settings_testing))
            when (val got = api.testService(n)) {
                is MoiApi.Result.Ok -> sayFor(
                    from, n,
                    got.value.message.ifBlank { text(if (got.value.ok) R.string.settings_service_answers else R.string.settings_service_silent) },
                )
                is MoiApi.Result.Failed -> sayFor(from, n, got.error.said)
            }
            if (stillOn(from) && !dirty) refresh(n, from)
        }
        if (dirty) save(gesture) else viewModelScope.launch { gesture() }
    }

    fun remove() {
        val from = opening
        val n = name
        viewModelScope.launch {
            when (val got = api.removeService(n)) {
                is MoiApi.Result.Ok -> {
                    sayFor(from, n, doneText(got.value.message, text(R.string.settings_service_removed)))
                    move(Move.Back, from)
                }
                is MoiApi.Result.Failed -> sayFor(from, n, got.error.said)
            }
        }
    }
}

@Composable
internal fun ServicePage(graph: AppGraph, name: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: ServiceViewModel = viewModel(key = "settings.service|$session") { ServiceViewModel(SettingsDeps(graph)) }
    val entry = rememberSaveable { MoiApi.newKey() }
    LaunchedEffect(vm, name, entry) { vm.open(name, entry) }
    SettingsEffects(vm)
    var confirmRemove by rememberSaveable { mutableStateOf(false) }
    if (!vm.isOpenFor(entry, name)) return SettingsLoading(name)
    val s = vm.service
    SectionScaffold(
        topBar = {
            MikaTopBar(name, BarNav.BACK) {
                if (s != null) {
                    BarMenu(
                        listOf(
                            MenuEntry(stringResource(R.string.settings_test), R.drawable.ic_m_refresh, vm::test),
                            MenuEntry(stringResource(R.string.settings_share_this), R.drawable.ic_m_users) { shell.navigate(shareRoute(ShareKinds.MCP, name)) },
                            MenuEntry(stringResource(R.string.settings_service_remove), R.drawable.ic_m_trash) { confirmRemove = true },
                        ),
                    )
                }
            }
        },
        bottomBar = { SaveBar(vm.dirty, vm.busy, vm::cancel, { vm.save() }) },
    ) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) {
            val r = vm.received
            when {
                s != null -> ServiceForm(vm, s, modifier, onRemove = { confirmRemove = true })
                r != null -> ReceivedServiceView(r, modifier)
            }
        }
    }
    if (confirmRemove) {
        ConfirmDialog(
            title = stringResource(R.string.settings_service_remove),
            text = stringResource(R.string.settings_service_remove_text, name),
            confirm = stringResource(R.string.settings_remove),
            danger = true,
            onConfirm = {
                confirmRemove = false
                vm.remove()
            },
            onDismiss = { confirmRemove = false },
        )
    }
}

@Composable
private fun ServiceForm(vm: ServiceViewModel, s: Service, modifier: Modifier, onRemove: () -> Unit) {
    val shell = LocalShell.current
    val e = vm.errors
    Column(modifier.imePadding().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        HeadCard(R.drawable.ic_m_plug, s.name, s.url, stateWords(s.state))
        if (serviceTrouble(s.state) && s.detail.isNotBlank()) {
            NoteBox(s.detail, R.drawable.ic_m_alert, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), Tone.DANGER)
        }

        SetHead(stringResource(R.string.settings_service_group))
        SetGroup {
            Gap(6.dp)
            SetField(SERVICE_LABELS.getValue("purpose"), vm.purpose, vm::onPurpose, help = stringResource(R.string.settings_service_purpose_help), error = e["purpose"], max = McpLimits.PURPOSE)
            SetField(SERVICE_LABELS.getValue("when_to_use"), vm.whenToUse, vm::onWhenToUse, help = stringResource(R.string.settings_service_when_help), error = e["when_to_use"], singleLine = false, minLines = 2, max = McpLimits.PURPOSE)
            SetField(SERVICE_LABELS.getValue("url"), vm.url, vm::onUrl, help = stringResource(R.string.settings_service_url_help), error = e["url"], mono = true, keyboard = KeyboardType.Uri, max = McpLimits.URL)
            SetField(
                SERVICE_LABELS.getValue("secret_headers"), vm.headers, vm::onHeaders,
                help = stringResource(if (s.headers) R.string.settings_service_headers_kept else R.string.settings_service_headers_help),
                error = e["secret_headers"], mono = true, singleLine = false, minLines = 2, max = McpLimits.HEADERS,
                placeholder = if (s.headers) stringResource(R.string.settings_service_headers_kept_hint) else "Authorization: Bearer …",
            )
            if (s.headers) {
                SetSwitch(stringResource(R.string.settings_service_headers_clear), stringResource(R.string.settings_service_headers_clear_help), vm.clearHeaders, vm::onClearHeaders, enabled = vm.headers.isBlank())
            }
            SetSwitch(SERVICE_LABELS.getValue("enabled"), stringResource(R.string.settings_service_enabled_help), vm.enabled, vm::onEnabled, error = e["enabled"])
            Row(Modifier.padding(horizontal = 14.dp, vertical = 8.dp)) {
                ActionButton(stringResource(R.string.settings_test), R.drawable.ic_m_refresh, vm::test, enabled = !vm.busy)
            }
        }

        SetHead(stringResource(R.string.settings_service_tools))
        SetGroup {
            if (s.tools.isEmpty()) {
                SetRow("", stringResource(if (s.state == "connecte") R.string.settings_service_no_tools else R.string.settings_service_tools_later))
            }
            s.tools.forEachIndexed { i, t ->
                if (i > 0) SetDivider()
                ToolRow(t, vm.picks[t.remote].orEmpty()) { vm.pick(t.remote, it) }
            }
        }
        SetNote(stringResource(R.string.settings_service_tools_help))

        SetHead(stringResource(R.string.settings_service_access))
        SetGroup {
            s.access.forEachIndexed { i, a ->
                if (i > 0) SetDivider()
                AccessRow(i + 1, a)
            }
            if (s.access.isNotEmpty()) SetDivider()
            SetItem(null, stringResource(R.string.settings_rules_default), defaultWords(s.default))
        }
        SetNote(stringResource(R.string.settings_service_access_help))
        Row(Modifier.padding(horizontal = 16.dp)) {
            ActionButton(stringResource(R.string.settings_share_this), R.drawable.ic_m_users, { shell.navigate(shareRoute(ShareKinds.MCP, s.name)) })
        }
        Gap(8.dp)
        DangerButton(stringResource(R.string.settings_service_remove), onRemove)
    }
}

/** Un outil : son nom sur le serveur (et chez Mika), ce qu'il fait, son état, et son choix (aucun tant qu'il attend). */
@Composable
private fun ToolRow(t: ServiceTool, picked: String, onPick: (String) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Row(Modifier.padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(t.remote, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodyMedium)
                if (t.name.isNotBlank() && t.name != t.remote) {
                    Text(t.name, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.width(8.dp))
            toolState(t).let { (tone, words) -> Tag(words, tone) }
        }
        if (t.description.isNotBlank()) {
            Text(t.description, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 14.dp, vertical = 2.dp))
        }
        if (t.changed && t.choice.isNotEmpty()) {
            Text(
                stringResource(R.string.settings_service_tool_before, choiceWords(t.choice).lowercase()),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 14.dp),
            )
        }
        ChoiceSeg(CHOICES, picked, onPick)
    }
}

/** Une ligne d'accès : qui (« toi » pour la tienne, un partage marqué), quand, ce qu'il lit, ce qu'il fait, ce qu'elle
 *  en garde. */
@Composable
private fun AccessRow(n: Int, a: AccessLine) {
    SetItem(
        null,
        "$n · ${whoWords(a)}" + (a.whenWords.takeIf { it.isNotBlank() && it != "toujours" }?.let { " · $it" } ?: ""),
        stringResource(R.string.settings_service_access_line, a.readWords, a.actWords, a.keepWords),
    ) {
        if (a.who.isNotBlank() && !a.mine) Tag(stringResource(R.string.settings_service_share_tag), Tone.INFO)
    }
}

/** Un service qu'on te partage, en lecture : ses outils servis, et ce que Mika en fait pour toi. */
@Composable
private fun ReceivedServiceView(r: ReceivedService, modifier: Modifier) {
    Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        HeadCard(R.drawable.ic_m_lock, r.name, stringResource(R.string.settings_service_of, ofName(r.ownerName.ifBlank { "son propriétaire" })), stateWords(r.state))
        if (r.purpose.isNotBlank()) SetNote(r.purpose)
        NoteBox(
            receivedSentence(r) + " " + stringResource(R.string.settings_service_keeps, r.line.keepWords.ifBlank { "rien" }),
            R.drawable.ic_m_info,
            Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
        )
        SetHead(stringResource(R.string.settings_service_served_tools))
        SetGroup {
            if (r.tools.isEmpty()) SetRow("", stringResource(R.string.settings_service_none_served))
            r.tools.forEachIndexed { i, t ->
                if (i > 0) SetDivider()
                SetItem(null, t.remote, listOf(t.description, stringResource(R.string.settings_service_for_you, forYou(r, t.choice))).filter { it.isNotBlank() }.joinToString(" · ")) {
                    Tag(choiceWords(t.choice), Tone.INFO)
                }
            }
        }
    }
}

// ── Brancher un service ─────────────────────────────────────────────────

/** Brancher un service distant : son nom, à quoi il sert, son adresse https, ses en-têtes. Une clé d'envoi par
 *  branchement ; branché, il se teste, puis sa page s'ouvre (ses outils, à choisir un par un). */
class PlugViewModel(graph: AppGraph) : SettingsModel(graph) {
    var name by mutableStateOf("")
        private set
    var purpose by mutableStateOf("")
        private set
    var url by mutableStateOf("")
        private set
    var headers by mutableStateOf("")
        private set
    var whenToUse by mutableStateOf("")
        private set
    var errors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var busy by mutableStateOf(false)
        private set
    private var createKey = MoiApi.newKey()

    fun open(entry: String) {
        if (!reopen(entry)) return
        name = ""
        purpose = ""
        url = ""
        headers = ""
        whenToUse = ""
        errors = emptyMap()
        createKey = MoiApi.newKey()
    }

    fun onName(v: String) { name = v.take(McpLimits.NAME); errors = errors - "name" }
    fun onPurpose(v: String) { purpose = v.take(McpLimits.PURPOSE); errors = errors - "purpose" }
    fun onUrl(v: String) { url = v.take(McpLimits.URL); errors = errors - "url" }
    fun onHeaders(v: String) { headers = v.take(McpLimits.HEADERS); errors = errors - "headers" }
    fun onWhenToUse(v: String) { whenToUse = v.take(McpLimits.PURPOSE); errors = errors - "when_to_use" }

    fun plug() {
        if (busy) return
        val n = name.trim().lowercase()
        val problems = buildMap {
            serviceNameProblem(n).takeIf { it.isNotEmpty() }?.let { put("name", it) }
            urlProblem(url).takeIf { it.isNotEmpty() }?.let { put("url", it) }
        }
        if (problems.isNotEmpty()) {
            errors = problems
            return
        }
        busy = true
        val from = opening
        viewModelScope.launch {
            when (val got = api.plugService(n, purpose.trim(), url.trim(), headers, whenToUse, createKey)) {
                is MoiApi.Result.Ok -> {
                    createKey = MoiApi.newKey()
                    val made = got.value.name.ifBlank { n }
                    when (val t = api.testService(made)) {
                        is MoiApi.Result.Ok -> say(
                            if (t.value.ok) "${got.value.message} ${t.value.message}".trim()
                            else text(R.string.settings_service_plugged_silent, t.value.message),
                        )
                        is MoiApi.Result.Failed -> say(text(R.string.settings_service_plugged_silent, t.error.said))
                    }
                    move(Move.Replace(settingsPage(SettingsPages.SERVICE, made)), from)
                }
                is MoiApi.Result.Failed -> errors = refused(got.error, setOf("name", "purpose", "url", "headers", "when_to_use"), SERVICE_LABELS)
            }
            busy = false
        }
    }
}

@Composable
internal fun PlugPage(graph: AppGraph) {
    val session = rememberSessionKey(graph)
    val vm: PlugViewModel = viewModel(key = "settings.service.plug|$session") { PlugViewModel(graph) }
    val entry = rememberSaveable { MoiApi.newKey() }
    LaunchedEffect(vm, entry) { vm.open(entry) }
    SettingsEffects(vm)
    if (!vm.isOpenFor(entry)) return SettingsLoading(stringResource(R.string.settings_services_plug_title))
    val e = vm.errors
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_services_plug_title), BarNav.BACK) },
        bottomBar = { SaveBar(true, vm.busy, null, vm::plug, label = stringResource(R.string.settings_services_plug_test), note = "") },
    ) { modifier ->
        Column(modifier.imePadding().verticalScroll(rememberScrollState()).padding(top = 8.dp, bottom = 24.dp)) {
            SetGroup {
                Gap(6.dp)
                SetField(SERVICE_LABELS.getValue("name"), vm.name, vm::onName, help = stringResource(R.string.settings_service_name_help), error = e["name"], mono = true, placeholder = "agenda_club", max = McpLimits.NAME)
                SetField(SERVICE_LABELS.getValue("purpose"), vm.purpose, vm::onPurpose, help = stringResource(R.string.settings_service_purpose_help), error = e["purpose"], max = McpLimits.PURPOSE)
                SetField(SERVICE_LABELS.getValue("url"), vm.url, vm::onUrl, help = stringResource(R.string.settings_service_url_new_help), error = e["url"], mono = true, keyboard = KeyboardType.Uri, placeholder = "https://…/mcp", max = McpLimits.URL)
                SetField(SERVICE_LABELS.getValue("headers"), vm.headers, vm::onHeaders, help = stringResource(R.string.settings_service_headers_new_help), error = e["headers"], mono = true, singleLine = false, minLines = 2, placeholder = "Authorization: Bearer …", max = McpLimits.HEADERS)
                SetField(SERVICE_LABELS.getValue("when_to_use"), vm.whenToUse, vm::onWhenToUse, help = stringResource(R.string.settings_service_when_new_help), error = e["when_to_use"], max = McpLimits.PURPOSE)
                Gap(8.dp)
            }
            NoteBox(stringResource(R.string.settings_services_plug_note), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        }
    }
}
