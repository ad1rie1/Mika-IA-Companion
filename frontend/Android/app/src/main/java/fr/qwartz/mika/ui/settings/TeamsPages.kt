package fr.qwartz.mika.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.levelTag
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.settings.GivenShare
import fr.qwartz.mika.data.moi.settings.Replies
import fr.qwartz.mika.data.moi.settings.RuleEdit
import fr.qwartz.mika.data.moi.settings.RulesKind
import fr.qwartz.mika.data.moi.settings.ShareKinds
import fr.qwartz.mika.data.moi.settings.TEAMS_LABELS
import fr.qwartz.mika.data.moi.settings.TeamsSettings
import fr.qwartz.mika.data.moi.settings.TeamsValues
import fr.qwartz.mika.data.moi.settings.batchWords
import fr.qwartz.mika.data.moi.settings.doneText
import fr.qwartz.mika.data.moi.settings.edit
import fr.qwartz.mika.data.moi.settings.ruleBody
import fr.qwartz.mika.data.moi.settings.ruleChanged
import fr.qwartz.mika.data.moi.settings.sharedAccountSentence
import fr.qwartz.mika.data.moi.settings.teamsChanges
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.ui.Route
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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/*
 * Paramètres › Comptes Teams (ADR 0186, 0187) : tes comptes et ceux qu'on te partage ; un compte (comment Mika y écrit à
 * ta place, comment part ce qu'elle y prépare — ADR 0207 —, la clé de son extension — montrée une seule fois à sa
 * création, retirée d'un toucher —, le partager, le retirer) ; en ajouter un. Porté de
 * `frontendv2/src/screens/parametres/teams.ts`.
 */

// ── La liste ────────────────────────────────────────────────────────────

class TeamsAccountsViewModel(graph: AppGraph) : SettingsModel(graph) {
    var load by mutableStateOf<Load<TeamsAccounts>>(Load.Loading)
        private set

    fun resume() {
        viewModelScope.launch {
            when (val got = api.teamsAccounts()) {
                is MoiApi.Result.Ok -> load = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (load !is Load.Ready) load = Load.Failed(got.error) else say(got.error)
            }
        }
    }

    fun retry() {
        load = Load.Loading
        resume()
    }
}

@Composable
internal fun TeamsAccountsPage(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: TeamsAccountsViewModel = viewModel(key = "settings.teams|$session") { TeamsAccountsViewModel(graph) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) { lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { vm.resume() } }
    SettingsEffects(vm)
    val now = graph.clock.wallMs()
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_teams), BarNav.BACK) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { shell.navigate(settingsPage(SettingsPages.TEAMS_ACCOUNT)) },
                icon = { MIcon(R.drawable.ic_m_plus, null) },
                text = { Text(stringResource(R.string.settings_add)) },
            )
        },
    ) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) { got ->
            val own = got.accounts.filter { it.own }
            val shared = got.accounts.filterNot { it.own }
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 96.dp)) {
                if (!got.plugged) NoteBox(stringResource(R.string.settings_teams_unplugged), R.drawable.ic_m_info, Modifier.padding(16.dp))
                SetHead(stringResource(R.string.settings_yours))
                SetGroup {
                    if (own.isEmpty()) SetRow(stringResource(R.string.settings_teams_none), stringResource(R.string.settings_teams_none_help))
                    own.forEachIndexed { i, a ->
                        if (i > 0) SetDivider()
                        val sub = listOf(
                            if (a.selfName.isNotBlank()) stringResource(R.string.settings_teams_self, a.selfName) else "",
                            if (a.draftsWaiting > 0) pluralStringResource(R.plurals.settings_teams_waiting, a.draftsWaiting, a.draftsWaiting) else "",
                        ).filter { it.isNotBlank() }.joinToString(" · ")
                        SetItem(R.drawable.ic_m_teams, a.name.ifBlank { a.key }, sub, onClick = { shell.navigate(settingsPage(SettingsPages.TEAMS_ACCOUNT, a.key)) }) {
                            batchWords(a, now).let { (tone, words) -> Tag(words, tone) }
                        }
                    }
                }
                if (shared.isNotEmpty()) {
                    SetHead(stringResource(R.string.settings_shared_with_you))
                    SetGroup {
                        shared.forEachIndexed { i, a ->
                            if (i > 0) SetDivider()
                            SetItem(
                                R.drawable.ic_m_lock,
                                a.name.ifBlank { a.key },
                                listOf(ofName(a.ownerName), levelTag(a.level)).filter { it.isNotBlank() }.joinToString(" · "),
                                onClick = { shell.navigate(settingsPage(SettingsPages.TEAMS_ACCOUNT, a.key)) },
                            )
                        }
                    }
                }
                SetNote(stringResource(R.string.settings_teams_note))
            }
        }
    }
}

// ── Un compte ───────────────────────────────────────────────────────────

/** La clé neuve de l'extension d'un compte ([account]), montrée sur la page de ce compte seulement. */
data class FreshKey(val account: String, val name: String, val key: String)

/**
 * Un de tes comptes Teams : ses réglages, sa règle d'envoi (une barre « Enregistrer » pour les deux), la clé de son
 * extension. Une clé neuve se montre une seule fois ([freshKey]) : ni gardée sur le téléphone, ni relue ensuite.
 *
 * Un modèle pour tous les comptes de la session, gardé comme celui d'une boîte (`BoxViewModel`) : une lecture d'avant
 * ne pose rien (R3-07), un enregistrement fige ce qu'il envoie et ne pose rien sur la page d'un autre compte (R3-01),
 * une règle changée ailleurs se relit (R3-10). Une clé neuve est liée à son compte (R3-05) : montrée sur sa page
 * seulement — y compris rouverte, si on l'avait quittée avant la réponse —, jamais sur celle d'un autre, et gardée en
 * mémoire jusqu'à « J'ai collé ».
 */
class TeamsAccountViewModel(deps: SettingsDeps) : SettingsModel(deps) {
    var load by mutableStateOf<Load<Unit>>(Load.Loading)
        private set
    var key = ""
        private set
    var account by mutableStateOf<TeamsAccount?>(null)
        private set
    var shared by mutableStateOf<TeamsAccount?>(null)
        private set
    var settings by mutableStateOf<TeamsSettings?>(null)
        private set
    var given by mutableStateOf<List<GivenShare>>(emptyList())
        private set
    var values by mutableStateOf(TeamsValues())
        private set
    var lines by mutableStateOf<List<RuleEdit>>(emptyList())
        private set
    var default by mutableStateOf(RuleEdit(false, Replies.ASK))
        private set
    var errors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    private var busyFor by mutableStateOf<String?>(null)
    val busy: Boolean get() = busyFor != null && busyFor == openedFor
    /** Les clés neuves pas encore vues, par compte : en mémoire pour la session seulement. */
    private var fresh by mutableStateOf<Map<String, FreshKey>>(emptyMap())
    private var loading: Job? = null

    /** La clé neuve à montrer sur la page à l'écran : celle de son compte, jamais celle d'un autre. */
    val freshKey: FreshKey? get() = fresh[key]

    fun open(key: String, entry: String) {
        if (!reopen(entry, key)) return
        this.key = key
        account = null
        shared = null
        settings = null
        given = emptyList()
        errors = emptyMap()
        reload()
    }

    fun retry() = reload()

    private fun reload() {
        loading?.cancel()
        val from = opening
        val k = key
        loading = viewModelScope.launch {
            load = Load.Loading
            val list = api.teamsAccounts()
            if (!stillOn(from)) return@launch
            if (list is MoiApi.Result.Failed) {
                load = Load.Failed(list.error)
                return@launch
            }
            val all = (list as MoiApi.Result.Ok).value.accounts
            val mine = all.firstOrNull { it.key == k && it.own }
            account = mine
            if (mine == null) {
                shared = all.firstOrNull { it.key == k }
                load = if (shared != null) Load.Ready(Unit) else Load.Failed(MoiError(404, text(R.string.settings_teams_not_yours)))
                return@launch
            }
            val got = api.teamsAccount(k)
            if (!stillOn(from)) return@launch
            when (got) {
                is MoiApi.Result.Ok -> {
                    fill(got.value)
                    load = Load.Ready(Unit)
                }
                is MoiApi.Result.Failed -> load = Load.Failed(got.error)
            }
            val s = api.shares()
            if (stillOn(from) && s is MoiApi.Result.Ok) given = s.value.given.filter { it.kind == ShareKinds.TEAMS && it.key == k }
        }
    }

    private fun fill(s: TeamsSettings) {
        settings = s
        values = s.values
        lines = s.rules.lines.map { it.edit }
        default = s.rules.default.edit
        errors = emptyMap()
    }

    /** Relire le compte tel qu'il est enregistré, sur sa page seulement ; [keepForm] : sans toucher une saisie en cours. */
    private suspend fun refresh(k: String, from: String, keepForm: Boolean = false) {
        val list = api.teamsAccounts()
        if (stillOn(from)) (list as? MoiApi.Result.Ok)?.let { l -> l.value.accounts.firstOrNull { it.key == k && it.own }?.let { account = it } }
        val got = api.teamsAccount(k)
        if (!stillOn(from)) return
        (got as? MoiApi.Result.Ok)?.let { g ->
            if (keepForm && dirty) settings = settings?.copy(extensionKey = g.value.extensionKey) else fill(g.value)
        }
    }

    /** Sa règle changée ailleurs (409) : relue, sa version comprise ; le reste du formulaire ne bouge pas. */
    private suspend fun rulesAgain(k: String, from: String) {
        val got = api.teamsAccount(k) as? MoiApi.Result.Ok ?: return
        if (!stillOn(from)) return
        val now = got.value.rules
        settings = settings?.copy(rules = now)
        lines = now.lines.map { it.edit }
        default = now.default.edit
    }

    val dirty: Boolean
        get() {
            val s = settings ?: return false
            return teamsChanges(s.values, values).isNotEmpty() || ruleChanged(s.rules, lines, default)
        }

    private fun named(k: String): String = account?.takeIf { it.key == k }?.name?.ifBlank { k } ?: k

    fun edit(field: String, f: (TeamsValues) -> TeamsValues) {
        values = f(values)
        errors = errors - field
    }

    fun onLine(i: Int, e: RuleEdit) {
        lines = lines.toMutableList().also { if (i in it.indices) it[i] = e }
    }

    fun onDefault(e: RuleEdit) {
        default = e
    }

    fun cancel() {
        settings?.let(::fill)
    }

    /** Enregistrer : le compte, ses changements et le corps de la règle figés avant le premier appel. */
    fun save() {
        if (busy) return
        val s = settings ?: return
        val sent = teamsChanges(s.values, values)
        val ruleMoved = ruleChanged(s.rules, lines, default)
        if (sent.isEmpty() && !ruleMoved) return
        val rules = if (ruleMoved) ruleBody(s.rules, lines, default) ?: return say(text(R.string.settings_rules_mismatch)) else null
        val from = opening
        val k = key
        val what = named(k)
        busyFor = from
        viewModelScope.launch {
            val said = mutableListOf<String>()
            var saved = false
            var ok = true
            var conflict: MoiError? = null
            if (sent.isNotEmpty()) {
                when (val got = api.saveTeamsAccount(sent, k)) {
                    is MoiApi.Result.Ok -> {
                        saved = true
                        said += got.value.message
                    }
                    is MoiApi.Result.Failed -> {
                        ok = false
                        refusedFor(from, what, got.error, TEAMS_LABELS.keys, TEAMS_LABELS)?.let { errors = it }
                    }
                }
            }
            if (ok && rules != null) {
                when (val got = api.saveRules(rules)) {
                    is MoiApi.Result.Ok -> said += got.value.message
                    is MoiApi.Result.Failed -> {
                        ok = false
                        if (got.error.conflict) conflict = got.error else sayFor(from, what, got.error.said)
                    }
                }
            }
            if (ok) sayFor(from, what, said.filter { it.isNotBlank() }.joinToString(" ").ifBlank { text(R.string.settings_saved) })
            when {
                !stillOn(from) -> conflict?.let { sayFor(from, what, it.said) }
                ok || saved -> refresh(k, from)
                conflict != null -> rulesAgain(k, from)
            }
            if (conflict != null && stillOn(from)) say((said.filter { it.isNotBlank() } + text(R.string.settings_rules_reread)).joinToString(" "))
            if (busyFor == from) busyFor = null
        }
    }

    /** Une clé neuve : l'ancienne ne vaut plus ; la neuve se montre une fois, sur la page de son compte. */
    fun newKey() {
        if (busy) return
        val from = opening
        val k = key
        val what = named(k)
        busyFor = from
        viewModelScope.launch {
            when (val got = api.newExtensionKey(k)) {
                is MoiApi.Result.Ok -> {
                    val made = got.value.key.takeIf { it.isNotBlank() }
                    if (made != null) {
                        fresh = fresh + (k to FreshKey(k, what, made))
                        // la page quittée : elle attend son retour sur ce compte (le toast le dit)
                        if (!stillOn(from)) sayFor(from, what, text(R.string.settings_teams_key_waits))
                    } else {
                        sayFor(from, what, doneText(got.value.message, text(R.string.settings_saved)))
                    }
                    refresh(k, from, keepForm = true)
                }
                is MoiApi.Result.Failed -> sayFor(from, what, got.error.said)
            }
            if (busyFor == from) busyFor = null
        }
    }

    /** La clé a été vue (et copiée, on l'espère) : elle s'oublie. */
    fun keySeen(account: String) {
        fresh = fresh - account
    }

    fun revokeKey() {
        val from = opening
        val k = key
        val what = named(k)
        viewModelScope.launch {
            when (val got = api.revokeExtensionKey(k)) {
                is MoiApi.Result.Ok -> {
                    sayFor(from, what, doneText(got.value.message, text(R.string.settings_teams_key_removed)))
                    refresh(k, from, keepForm = true)
                }
                is MoiApi.Result.Failed -> sayFor(from, what, got.error.said)
            }
        }
    }

    fun remove() {
        val from = opening
        val k = key
        val what = named(k)
        viewModelScope.launch {
            when (val got = api.removeTeamsAccount(k)) {
                is MoiApi.Result.Ok -> {
                    fresh = fresh - k
                    sayFor(from, what, doneText(got.value.message, text(R.string.settings_teams_removed)))
                    deps.refreshBadges()
                    move(Move.Back, from)
                }
                is MoiApi.Result.Failed -> sayFor(from, what, got.error.said)
            }
        }
    }
}

@Composable
internal fun TeamsAccountPage(graph: AppGraph, key: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: TeamsAccountViewModel = viewModel(key = "settings.teams.account|$session") { TeamsAccountViewModel(SettingsDeps(graph)) }
    val entry = rememberSaveable { MoiApi.newKey() }
    LaunchedEffect(vm, key, entry) { vm.open(key, entry) }
    SettingsEffects(vm)
    var confirm by rememberSaveable { mutableStateOf("") }
    if (!vm.isOpenFor(entry, key)) return SettingsLoading(stringResource(R.string.settings_teams_account))
    val a = vm.account
    SectionScaffold(
        topBar = {
            MikaTopBar((a ?: vm.shared)?.let { it.name.ifBlank { it.key } } ?: stringResource(R.string.settings_teams_account), BarNav.BACK) {
                if (a != null) {
                    BarMenu(
                        listOf(
                            MenuEntry(stringResource(R.string.settings_share_this), R.drawable.ic_m_users) { shell.navigate(shareRoute(ShareKinds.TEAMS, key)) },
                            MenuEntry(stringResource(R.string.settings_teams_remove), R.drawable.ic_m_trash) { confirm = CONFIRM_REMOVE },
                        ),
                    )
                }
            }
        },
        bottomBar = { SaveBar(vm.dirty, vm.busy, vm::cancel, vm::save) },
    ) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) {
            val s = vm.settings
            val other = vm.shared
            when {
                a == null && other != null -> Column(modifier.verticalScroll(rememberScrollState())) {
                    HeadCard(R.drawable.ic_m_lock, other.name.ifBlank { other.key }, ofName(other.ownerName), Tone.NEUTRAL to levelTag(other.level))
                    NoteBox(sharedAccountSentence(other), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
                    ActionButton(stringResource(R.string.settings_open_teams), R.drawable.ic_m_teams, { shell.open(Route.Teams) }, Modifier.padding(horizontal = 16.dp))
                }
                a != null && s != null -> TeamsForm(graph, vm, a, s, modifier, onConfirm = { confirm = it })
            }
        }
    }
    when (confirm) {
        CONFIRM_REMOVE -> ConfirmDialog(
            title = stringResource(R.string.settings_teams_remove),
            text = stringResource(R.string.settings_teams_remove_text, a?.name?.ifBlank { key } ?: key),
            confirm = stringResource(R.string.settings_remove),
            danger = true,
            onConfirm = { confirm = ""; vm.remove() },
            onDismiss = { confirm = "" },
        )
        CONFIRM_NEW_KEY -> ConfirmDialog(
            title = stringResource(R.string.settings_teams_key_new_title),
            text = stringResource(R.string.settings_teams_key_new_text),
            confirm = stringResource(R.string.settings_teams_key_create),
            onConfirm = { confirm = ""; vm.newKey() },
            onDismiss = { confirm = "" },
        )
        CONFIRM_REVOKE -> ConfirmDialog(
            title = stringResource(R.string.settings_teams_key_revoke),
            text = stringResource(R.string.settings_teams_key_revoke_text),
            confirm = stringResource(R.string.settings_teams_key_revoke),
            danger = true,
            onConfirm = { confirm = ""; vm.revokeKey() },
            onDismiss = { confirm = "" },
        )
    }
    vm.freshKey?.let { fresh -> KeyOnceDialog(fresh) { vm.keySeen(fresh.account) } }
}

private const val CONFIRM_REMOVE = "remove"
private const val CONFIRM_NEW_KEY = "key"
private const val CONFIRM_REVOKE = "revoke"

@Composable
private fun TeamsForm(graph: AppGraph, vm: TeamsAccountViewModel, a: TeamsAccount, s: TeamsSettings, modifier: Modifier, onConfirm: (String) -> Unit) {
    val shell = LocalShell.current
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val v = vm.values
    val e = vm.errors
    val now = graph.clock.wallMs()
    val copied = stringResource(R.string.settings_copied)
    Column(modifier.imePadding().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        val waiting = if (a.draftsWaiting > 0) pluralStringResource(R.plurals.settings_teams_waiting, a.draftsWaiting, a.draftsWaiting) else ""
        HeadCard(
            R.drawable.ic_m_teams,
            a.name.ifBlank { a.key },
            listOf(if (a.selfName.isNotBlank()) stringResource(R.string.settings_teams_self, a.selfName) else "", waiting).filter { it.isNotBlank() }.joinToString(" · "),
            batchWords(a, now),
        )

        SetHead(stringResource(R.string.settings_teams_group_account))
        SetGroup {
            Gap(6.dp)
            SetField(TEAMS_LABELS.getValue("label"), v.label, { x -> vm.edit("label") { it.copy(label = x) } }, help = stringResource(R.string.settings_teams_label_help), error = e["label"], placeholder = a.key, max = 120)
            SetSwitch(TEAMS_LABELS.getValue("enabled"), stringResource(R.string.settings_teams_enabled_help), v.enabled, { x -> vm.edit("enabled") { it.copy(enabled = x) } }, error = e["enabled"])
            SetField(TEAMS_LABELS.getValue("display_name"), v.displayName, { x -> vm.edit("display_name") { it.copy(displayName = x) } }, help = stringResource(R.string.settings_teams_display_help), error = e["display_name"], placeholder = a.selfName, max = 120)
            SetField(TEAMS_LABELS.getValue("tone"), v.tone, { x -> vm.edit("tone") { it.copy(tone = x) } }, help = stringResource(R.string.settings_teams_tone_help), error = e["tone"], max = 2000)
            SetField(TEAMS_LABELS.getValue("instructions"), v.instructions, { x -> vm.edit("instructions") { it.copy(instructions = x) } }, help = stringResource(R.string.settings_teams_instructions_help), error = e["instructions"], singleLine = false, minLines = 3, max = 4000)
            SetSwitch(TEAMS_LABELS.getValue("sign"), stringResource(R.string.settings_teams_sign_help), v.sign, { x -> vm.edit("sign") { it.copy(sign = x) } }, error = e["sign"])
            if (v.sign) SetField(TEAMS_LABELS.getValue("signature"), v.signature, { x -> vm.edit("signature") { it.copy(signature = x) } }, error = e["signature"], max = 500)
            Gap(8.dp)
        }

        RulesEditor(s.rules, RulesKind.TEAMS, vm.lines, vm.default, vm::onLine, vm::onDefault)

        SetHead(stringResource(R.string.settings_teams_group_extension))
        SetGroup {
            val k = s.extensionKey ?: a.extensionKey
            SetRow(
                stringResource(R.string.settings_teams_key),
                if (k != null) {
                    stringResource(R.string.settings_teams_key_line, k.hint, MoiDates.dayAndClock(k.createdAt, now))
                } else {
                    stringResource(R.string.settings_teams_key_none)
                },
            ) {
                Gap(6.dp)
                SetNote(stringResource(R.string.settings_teams_key_help))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ActionButton(stringResource(R.string.settings_teams_key_create), R.drawable.ic_m_key, { if (k != null) onConfirm(CONFIRM_NEW_KEY) else vm.newKey() }, enabled = !vm.busy)
                    if (k != null) {
                        TextButton(onClick = { onConfirm(CONFIRM_REVOKE) }) { Text(stringResource(R.string.settings_teams_key_revoke), color = MaterialTheme.colorScheme.error) }
                    }
                }
            }
            SetDivider()
            val base = graph.auth.credentials()?.base?.canonical.orEmpty()
            SetItem(null, stringResource(R.string.settings_teams_address), base.ifBlank { "—" }) {
                if (base.isNotBlank()) {
                    TextButton(onClick = {
                        scope.launch {
                            copyText(clipboard, base)
                            shell.toast(copied)
                        }
                    }) { Text(stringResource(R.string.settings_copy)) }
                }
            }
            SetDivider()
            SetRow(stringResource(R.string.settings_teams_extension), stringResource(R.string.settings_teams_extension_help))
        }

        SharedWithGroup(vm.given) { shell.navigate(shareRoute(ShareKinds.TEAMS, a.key)) }
        Gap(8.dp)
        DangerButton(stringResource(R.string.settings_teams_remove), { onConfirm(CONFIRM_REMOVE) })
    }
}

/** La clé neuve de l'extension d'un compte, montrée cette fois seulement : à copier maintenant (elle ne reparaîtra
 *  pas). Son titre nomme le compte : elle ne vaut que pour son extension. */
@Composable
private fun KeyOnceDialog(fresh: FreshKey, onDone: () -> Unit) {
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val shell = LocalShell.current
    val copied = stringResource(R.string.settings_teams_key_copied)
    AlertDialog(
        onDismissRequest = {}, // pas d'un toucher à côté : la clé se perdrait
        title = { Text(stringResource(R.string.settings_teams_key_fresh, fresh.name)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(stringResource(R.string.settings_teams_key_fresh_lede))
                Surface(shape = RoundedCornerShape(8.dp), color = MaterialTheme.colorScheme.surfaceContainerHighest, modifier = Modifier.fillMaxWidth()) {
                    Text(fresh.key, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodyMedium, overflow = TextOverflow.Visible, modifier = Modifier.padding(12.dp))
                }
                ActionButton(stringResource(R.string.settings_copy), R.drawable.ic_m_copy, {
                    scope.launch {
                        copyText(clipboard, fresh.key, sensitive = true)
                        shell.toast(copied)
                    }
                })
                NoteBox(stringResource(R.string.settings_teams_key_fresh_warn), R.drawable.ic_m_alert, tone = Tone.WARN)
            }
        },
        confirmButton = { TextButton(onClick = onDone) { Text(stringResource(R.string.settings_teams_key_pasted)) } },
    )
}

// ── Un compte nouveau ───────────────────────────────────────────────────

/** Ajouter un compte Teams : son nom, le tien dans Teams. Une clé d'envoi par création ; créé, sa page s'ouvre. */
class NewTeamsViewModel(graph: AppGraph) : SettingsModel(graph) {
    var label by mutableStateOf("")
        private set
    var displayName by mutableStateOf("")
        private set
    var errors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var busy by mutableStateOf(false)
        private set
    private var createKey = MoiApi.newKey()

    fun open(entry: String) {
        if (!reopen(entry)) return
        label = ""
        displayName = ""
        errors = emptyMap()
        createKey = MoiApi.newKey()
    }

    fun onLabel(v: String) { label = v.take(120); errors = errors - "label" }
    fun onDisplayName(v: String) { displayName = v.take(120); errors = errors - "display_name" }

    fun create() {
        if (busy) return
        busy = true
        val values = JsonObject(mapOf("label" to JsonPrimitive(label.trim()), "display_name" to JsonPrimitive(displayName.trim())))
        val from = opening
        viewModelScope.launch {
            when (val got = api.saveTeamsAccount(values, "", createKey)) {
                is MoiApi.Result.Ok -> {
                    createKey = MoiApi.newKey()
                    say(doneText(got.value.message, text(R.string.settings_saved)) + " " + text(R.string.settings_teams_added_next))
                    val made = got.value.account
                    move(if (made.isNotBlank()) Move.Replace(settingsPage(SettingsPages.TEAMS_ACCOUNT, made)) else Move.Back, from)
                }
                is MoiApi.Result.Failed -> errors = refused(got.error, setOf("label", "display_name"), TEAMS_LABELS)
            }
            busy = false
        }
    }
}

@Composable
internal fun NewTeamsPage(graph: AppGraph) {
    val session = rememberSessionKey(graph)
    val vm: NewTeamsViewModel = viewModel(key = "settings.teams.new|$session") { NewTeamsViewModel(graph) }
    val entry = rememberSaveable { MoiApi.newKey() }
    LaunchedEffect(vm, entry) { vm.open(entry) }
    SettingsEffects(vm)
    if (!vm.isOpenFor(entry)) return SettingsLoading(stringResource(R.string.settings_teams_new))
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_teams_new), BarNav.BACK) },
        bottomBar = { SaveBar(true, vm.busy, null, vm::create, label = stringResource(R.string.settings_add), note = "") },
    ) { modifier ->
        Column(modifier.imePadding().verticalScroll(rememberScrollState()).padding(top = 8.dp, bottom = 24.dp)) {
            SetGroup {
                Gap(6.dp)
                SetField(TEAMS_LABELS.getValue("label"), vm.label, vm::onLabel, error = vm.errors["label"], placeholder = stringResource(R.string.settings_teams_label_placeholder))
                SetField(TEAMS_LABELS.getValue("display_name"), vm.displayName, vm::onDisplayName, error = vm.errors["display_name"], placeholder = stringResource(R.string.settings_teams_display_placeholder))
                Gap(8.dp)
            }
            SetNote(stringResource(R.string.settings_teams_new_note))
        }
    }
}
