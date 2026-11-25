package fr.qwartz.mika.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.Me
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.settings.ASK_ME
import fr.qwartz.mika.data.moi.settings.NAME_MAX
import fr.qwartz.mika.data.moi.settings.PASSWORD_HELP
import fr.qwartz.mika.data.moi.settings.PASSWORD_MAX
import fr.qwartz.mika.data.moi.settings.doneText
import fr.qwartz.mika.data.moi.settings.fieldErrors
import fr.qwartz.mika.data.moi.settings.nameProblem
import fr.qwartz.mika.data.moi.settings.passwordProblems
import fr.qwartz.mika.data.moi.settings.roleHelp
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.ActionButton
import fr.qwartz.mika.ui.components.FieldError
import fr.qwartz.mika.ui.components.SaveBar
import fr.qwartz.mika.ui.components.SetDivider
import fr.qwartz.mika.ui.components.SetField
import fr.qwartz.mika.ui.components.SetGroup
import fr.qwartz.mika.ui.components.SetHead
import fr.qwartz.mika.ui.components.SetItem
import fr.qwartz.mika.ui.components.SetRow
import fr.qwartz.mika.ui.components.SettingsEffects
import fr.qwartz.mika.ui.components.SettingsLoading
import fr.qwartz.mika.ui.components.SettingsModel
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.components.settingsPage
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.launch

/**
 * Paramètres › Compte : son nom (celui sous lequel elle te connaît), son identifiant, son rôle, ce qu'elle sait de toi
 * (« Lui demander » ouvre le chat, la question posée) ; son mot de passe (le changer ferme toutes tes sessions, celle de
 * ce téléphone comprise : on se reconnecte). Les mots de passe tapés ne vivent qu'ici, en mémoire.
 */
class AccountViewModel(private val graph: AppGraph) : SettingsModel(graph) {
    var name by mutableStateOf("")
        private set
    private var initial = ""
    private var known = false
    var errors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var saving by mutableStateOf(false)
        private set

    // la fenêtre du mot de passe
    var passwordOpen by mutableStateOf(false)
        private set
    var current by mutableStateOf("")
        private set
    var password by mutableStateOf("")
        private set
    var again by mutableStateOf("")
        private set
    var passwordErrors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    /** Un refus sans champ (trop d'essais), dit dans la fenêtre, qui reste ouverte. */
    var passwordSaid by mutableStateOf("")
        private set
    var changing by mutableStateOf(false)
        private set

    val dirty: Boolean get() = known && name != initial

    /** Une nouvelle ouverture de la page ([entry]) repart de ce que dit le serveur. */
    fun open(entry: String, me: Me?) {
        if (reopen(entry)) {
            known = false
            errors = emptyMap()
            closePassword()
        }
        if (!known && me != null) {
            known = true
            initial = me.name
            name = me.name
        }
        if (me == null) viewModelScope.launch { graph.me.load() }
    }

    fun onName(v: String) {
        name = v.take(NAME_MAX)
        errors = emptyMap()
    }

    fun cancel() {
        name = initial
        errors = emptyMap()
    }

    fun save() {
        if (saving) return
        val problem = nameProblem(name)
        if (problem != null) {
            errors = mapOf("name" to problem)
            return
        }
        val sent = name.trim()
        saving = true
        viewModelScope.launch {
            when (val got = api.saveName(sent)) {
                is MoiApi.Result.Ok -> {
                    initial = sent
                    name = sent
                    say(doneText(got.value.message, text(R.string.settings_saved)))
                    graph.me.refresh()
                }
                is MoiApi.Result.Failed -> errors = refused(got.error, setOf("name"), mapOf("name" to text(R.string.settings_name)))
            }
            saving = false
        }
    }

    fun openPassword() {
        closePassword()
        passwordOpen = true
    }

    fun closePassword() {
        passwordOpen = false
        current = ""
        password = ""
        again = ""
        passwordErrors = emptyMap()
        passwordSaid = ""
    }

    fun onCurrent(v: String) { current = v.take(PASSWORD_MAX); passwordErrors = passwordErrors - "current" }
    fun onPassword(v: String) { password = v.take(PASSWORD_MAX); passwordErrors = passwordErrors - "password" }
    fun onAgain(v: String) { again = v.take(PASSWORD_MAX); passwordErrors = passwordErrors - "again" }

    /** Changer son mot de passe ; réussi, ses sessions sont fermées : celle-ci aussi, avec le mot qui le dit. */
    fun changePassword() {
        if (changing) return
        val problems = passwordProblems(current, password, again)
        passwordSaid = ""
        if (problems.isNotEmpty()) {
            passwordErrors = problems
            return
        }
        changing = true
        viewModelScope.launch {
            when (val got = api.savePassword(current, password)) {
                is MoiApi.Result.Ok -> {
                    val said = doneText(got.value.message, text(R.string.settings_password_changed))
                    closePassword()
                    if (got.value.relogin) {
                        // le serveur a fermé ses sessions : se déconnecter comme d'habitude, en le disant sur l'écran de
                        // connexion ; le jeton lui est rendu quand même (un jeton de débogage, lui, n'est pas tombé)
                        graph.scope.launch { graph.auth.closeSession(said) }
                    } else {
                        say(said)
                    }
                }
                is MoiApi.Result.Failed -> {
                    val fields = fieldErrors(got.error.fields).filterKeys { it == "current" || it == "password" }
                    passwordErrors = fields
                    if (fields.isEmpty()) passwordSaid = got.error.said
                }
            }
            changing = false
        }
    }

    /** « Lui demander » : la question dans le champ du chat, à relire avant de l'envoyer ; ce qui y était écrit reste. */
    fun askMika() {
        graph.scope.launch { graph.shareInbox.deposit(ComposerDraft(text = ASK_ME)) }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun AccountPage(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: AccountViewModel = viewModel(key = "settings.account|$session") { AccountViewModel(graph) }
    val entry = rememberSaveable { MoiApi.newKey() }
    val me by graph.me.me.collectAsStateWithLifecycle()
    val signed by graph.auth.session.collectAsStateWithLifecycle()
    LaunchedEffect(vm, entry, me) { vm.open(entry, me) }
    SettingsEffects(vm)
    if (!vm.isOpenFor(entry)) return SettingsLoading(stringResource(R.string.settings_account))
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_account), BarNav.BACK) },
        bottomBar = { SaveBar(vm.dirty, vm.saving, vm::cancel, vm::save) },
    ) { modifier ->
        Column(modifier.imePadding().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            SetHead(stringResource(R.string.settings_group_account))
            SetGroup {
                Gap(8.dp)
                SetField(
                    label = stringResource(R.string.settings_name),
                    value = vm.name,
                    onValue = vm::onName,
                    help = stringResource(R.string.settings_name_help),
                    error = vm.errors["name"],
                    max = NAME_MAX,
                )
                SetDivider()
                val username = me?.username ?: (signed as? Session.LoggedIn)?.profile?.username.orEmpty()
                SetItem(null, stringResource(R.string.settings_username), username) {
                    Tag(stringResource(R.string.settings_username_fixed), Tone.NEUTRAL)
                }
                (signed as? Session.LoggedIn)?.base?.let { base ->
                    SetDivider()
                    SetItem(null, stringResource(R.string.settings_server), base.canonical)
                }
                me?.let { m ->
                    SetDivider()
                    SetRow(stringResource(R.string.settings_role), roleHelp(m.owner, m.operator)) {
                        Gap(6.dp)
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            if (m.owner) Tag(stringResource(R.string.settings_role_owner), Tone.INFO)
                            if (m.operator) Tag(stringResource(R.string.settings_role_operator), Tone.NEUTRAL)
                            if (!m.owner && !m.operator) Tag(stringResource(R.string.settings_role_person), Tone.NEUTRAL)
                        }
                    }
                }
                SetDivider()
                SetRow(stringResource(R.string.settings_knows), stringResource(R.string.settings_knows_help)) {
                    Gap(8.dp)
                    FilledTonalButton(onClick = {
                        vm.askMika()
                        shell.open(Route.Chat)
                    }) { Text(stringResource(R.string.settings_ask)) }
                }
            }

            SetHead(stringResource(R.string.settings_password_group))
            SetGroup {
                SetRow(stringResource(R.string.settings_password), PASSWORD_HELP) {
                    Gap(8.dp)
                    ActionButton(stringResource(R.string.settings_password_change), R.drawable.ic_m_key, vm::openPassword)
                }
                SetDivider()
                SetItem(
                    R.drawable.ic_m_phone,
                    stringResource(R.string.settings_phones),
                    stringResource(R.string.settings_phones_own_key),
                    onClick = { shell.navigate(settingsPage(SettingsPages.PHONES)) },
                )
            }
        }
    }
    if (vm.passwordOpen) PasswordDialog(vm)
}

/** Changer le mot de passe : l'actuel, le nouveau deux fois ; ce qui manque sous son champ, un refus sans champ dessous. */
@Composable
private fun PasswordDialog(vm: AccountViewModel) {
    AlertDialog(
        onDismissRequest = { if (!vm.changing) vm.closePassword() },
        title = { Text(stringResource(R.string.settings_password_change)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                SetField(stringResource(R.string.settings_password_current), vm.current, vm::onCurrent, error = vm.passwordErrors["current"], secret = true, modifier = Modifier.padding(0.dp))
                SetField(stringResource(R.string.settings_password_new), vm.password, vm::onPassword, error = vm.passwordErrors["password"], secret = true)
                SetField(stringResource(R.string.settings_password_again), vm.again, vm::onAgain, error = vm.passwordErrors["again"], secret = true)
                Text(
                    PASSWORD_HELP + " " + stringResource(R.string.settings_password_relogin),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                )
                if (vm.passwordSaid.isNotBlank()) FieldError(vm.passwordSaid, Modifier.padding(horizontal = 14.dp))
            }
        },
        confirmButton = { TextButton(onClick = vm::changePassword, enabled = !vm.changing) { Text(stringResource(R.string.settings_password_ok)) } },
        dismissButton = { TextButton(onClick = vm::closePassword, enabled = !vm.changing) { Text(stringResource(R.string.cancel)) } },
    )
}
