package fr.qwartz.mika.ui.settings

import android.os.Build
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.agenda.AgendaApi
import fr.qwartz.mika.data.moi.agenda.accountsSummary
import fr.qwartz.mika.data.moi.agenda.Accounts as AgendaAccounts
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.phone.PhoneDevices
import fr.qwartz.mika.data.moi.phone.phoneBar
import fr.qwartz.mika.data.moi.tools.Services
import fr.qwartz.mika.data.moi.settings.Shares
import fr.qwartz.mika.data.moi.settings.boxesSummary
import fr.qwartz.mika.data.moi.settings.servicesSummary
import fr.qwartz.mika.data.moi.settings.sharesSummary
import fr.qwartz.mika.data.moi.settings.teamsSummary
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.data.push.PushState
import fr.qwartz.mika.data.settings.Settings as AppSettings
import fr.qwartz.mika.data.settings.ThemeMode
import fr.qwartz.mika.service.PhoneListenerService
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.agenda.AgendaAccountPage
import fr.qwartz.mika.ui.agenda.AgendaCalendarPage
import fr.qwartz.mika.ui.agenda.AgendaPlugPage
import fr.qwartz.mika.ui.agenda.AgendasSettingsPage
import fr.qwartz.mika.ui.components.ConfirmDialog
import fr.qwartz.mika.ui.components.DangerButton
import fr.qwartz.mika.ui.components.SetDivider
import fr.qwartz.mika.ui.components.SetGroup
import fr.qwartz.mika.ui.components.SetHead
import fr.qwartz.mika.ui.components.SetItem
import fr.qwartz.mika.ui.components.SettingsLive
import fr.qwartz.mika.ui.components.SettingsModel
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.components.rememberWhereSwitch
import fr.qwartz.mika.ui.components.settingsPage
import fr.qwartz.mika.ui.mail.BoxPage
import fr.qwartz.mika.ui.mail.BoxesPage
import fr.qwartz.mika.ui.mail.NewBoxPage
import fr.qwartz.mika.ui.phone.PhonesPage
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.ComingScreen
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.teams.NewTeamsPage
import fr.qwartz.mika.ui.teams.TeamsAccountPage
import fr.qwartz.mika.ui.teams.TeamsAccountsPage
import fr.qwartz.mika.ui.tools.PlugPage
import fr.qwartz.mika.ui.tools.ServicePage
import fr.qwartz.mika.ui.tools.ServicesPage
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch

/**
 * Ce que la page racine dit de chaque ligne : lu à chaque retour sur elle, une lecture qui échoue laisse la ligne dire
 * ce qu'elle règle, sans chiffres.
 */
class SettingsHomeViewModel(graph: AppGraph) : SettingsModel(graph) {
    var boxes by mutableStateOf<MailBoxes?>(null)
        private set
    var accounts by mutableStateOf<TeamsAccounts?>(null)
        private set
    var phones by mutableStateOf<PhoneDevices?>(null)
        private set
    var shares by mutableStateOf<Shares?>(null)
        private set
    var services by mutableStateOf<Services?>(null)
        private set
    /** Ses comptes d'agenda (ADR 0309) ; `null` tant qu'ils ne se sont pas lus. */
    var agendas by mutableStateOf<AgendaAccounts?>(null)
        private set
    private val agendaApi = AgendaApi(graph.moi)

    fun resume() {
        viewModelScope.launch { read() }
    }

    /** Relu sans bruit : un retour sur la page, ou le direct (ADR 0308) qui dit que ce qu'elle montre a changé. */
    suspend fun read(signal: LiveSignal = LiveSignal.RESYNC) = coroutineScope<Unit> {
        val all = signal.touches(Topics.SETTINGS)
        if (all || signal.touches(Topics.MAIL)) launch { (api.boxes() as? MoiApi.Result.Ok)?.let { boxes = it.value } }
        if (all || signal.touches(Topics.TEAMS)) launch { (api.teamsAccounts() as? MoiApi.Result.Ok)?.let { accounts = it.value } }
        if (all || signal.touches(Topics.PHONE_PHONES)) launch { (api.phones() as? MoiApi.Result.Ok)?.let { phones = it.value } }
        if (all) launch { (api.shares() as? MoiApi.Result.Ok)?.let { shares = it.value } }
        if (all) launch { (api.services() as? MoiApi.Result.Ok)?.let { services = it.value } }
        if (all || signal.touches(Topics.AGENDA)) launch { (agendaApi.accounts() as? MoiApi.Result.Ok)?.let { agendas = it.value } }
    }
}

/**
 * Paramètres, la rubrique du tiroir (ADR 0235, la maquette `ecrans/plus.js`) : en groupes, « Ton compte », « Ce que Mika
 * touche pour toi » (boîtes, comptes Teams, téléphones, partages, services MCP : l'API par personne, comme le
 * frontendv2), puis « Ce téléphone » (ce qu'il règle pour lui seul), et « Se déconnecter ». Une ligne, une page.
 */
@Composable
fun SettingsScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: SettingsHomeViewModel = viewModel(key = "settings.home|$session") { SettingsHomeViewModel(graph) }
    FollowLive(graph.live, SettingsLive.HOME, vm, onShown = { vm.resume() }) { vm.read(it) }
    // « vu il y a 4 min » (tes téléphones) avance tout seul
    val now = rememberNow(wallMs = graph.clock::wallMs)
    val me by graph.me.me.collectAsStateWithLifecycle()
    val settings by graph.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val push by graph.push.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var notifications by remember { mutableStateOf(notificationsEnabled(context)) }
    var phoneGranted by remember { mutableStateOf(PhoneListenerService.granted(context)) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        notifications = notificationsEnabled(context)
        phoneGranted = PhoneListenerService.granted(context)
    }
    val where = rememberWhereSwitch(graph)
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    val go = { page: String -> shell.navigate(settingsPage(page)) }

    SectionScaffold(topBar = { MikaTopBar(stringResource(R.string.nav_settings), BarNav.DRAWER) }) { modifier ->
        Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            SetHead(stringResource(R.string.settings_group_account))
            SetGroup {
                val name = me?.shown ?: settings.username
                SetItem(
                    R.drawable.ic_m_user,
                    stringResource(R.string.settings_account),
                    listOf(name, stringResource(R.string.settings_account_line)).filter { it.isNotBlank() }.joinToString(" · "),
                    onClick = { go(SettingsPages.ACCOUNT) },
                    boxed = false,
                )
            }

            SetHead(stringResource(R.string.settings_group_reach))
            SetGroup {
                SetItem(
                    R.drawable.ic_m_mail,
                    stringResource(R.string.settings_boxes),
                    vm.boxes?.let { boxesSummary(it.boxes) } ?: stringResource(R.string.settings_boxes_line),
                    onClick = { go(SettingsPages.BOXES) },
                    boxed = false,
                )
                SetDivider()
                SetItem(
                    R.drawable.ic_m_teams,
                    stringResource(R.string.settings_teams),
                    vm.accounts?.let { teamsSummary(it.accounts) } ?: stringResource(R.string.settings_teams_line),
                    onClick = { go(SettingsPages.TEAMS) },
                    boxed = false,
                )
                SetDivider()
                // après Comptes Teams (ADR 0309, la maquette `agenda-parametres.js`) : ses comptes d'agenda
                SetItem(
                    R.drawable.ic_m_agenda,
                    stringResource(R.string.agenda_settings_title),
                    vm.agendas?.let { accountsSummary(it.accounts) } ?: stringResource(R.string.agenda_settings_line),
                    onClick = { go(SettingsPages.AGENDAS) },
                    boxed = false,
                )
                SetDivider()
                SetItem(
                    R.drawable.ic_m_phone,
                    stringResource(R.string.settings_phones),
                    vm.phones?.let { phoneBar(it.items, graph.deviceLabel, graph.auth.tokenId(), now).line } ?: stringResource(R.string.settings_phones_line),
                    onClick = { go(SettingsPages.PHONES) },
                    boxed = false,
                )
                SetDivider()
                SetItem(
                    R.drawable.ic_m_share,
                    stringResource(R.string.settings_shares),
                    vm.shares?.let { sharesSummary(it) } ?: stringResource(R.string.settings_shares_line),
                    onClick = { go(SettingsPages.SHARES) },
                    boxed = false,
                )
                SetDivider()
                SetItem(
                    R.drawable.ic_m_plug,
                    stringResource(R.string.settings_services),
                    vm.services?.let { servicesSummary(it) } ?: stringResource(R.string.settings_services_line),
                    onClick = { go(SettingsPages.SERVICES) },
                    boxed = false,
                )
            }

            SetHead(stringResource(R.string.settings_group_phone))
            SetGroup {
                val notifLine = listOf(
                    stringResource(if (notifications) R.string.settings_sum_notif_on else R.string.settings_sum_notif_off),
                    stringResource(
                        when (push) {
                            PushState.Active -> R.string.settings_sum_push_active
                            PushState.ServerWithoutKey -> R.string.settings_sum_push_no_key
                            PushState.Unavailable -> R.string.settings_sum_push_unavailable
                            is PushState.Failed -> R.string.settings_sum_push_failed
                            PushState.Pending, PushState.LoggedOut -> R.string.settings_sum_push_pending
                        },
                    ),
                ).joinToString(" · ")
                SetItem(R.drawable.ic_m_bell, stringResource(R.string.settings_notifications), notifLine, onClick = { go(SettingsPages.NOTIFICATIONS) }, boxed = false)
                SetDivider()
                val whereLine = stringResource(R.string.settings_where_title) + " · " + stringResource(
                    when {
                        where.revoked -> R.string.settings_sum_revoked
                        where.checked -> R.string.settings_sum_on
                        else -> R.string.settings_sum_off
                    },
                )
                SetItem(R.drawable.ic_m_pin, stringResource(R.string.settings_where), whereLine, onClick = { go(SettingsPages.POSITION) }, boxed = false)
                SetDivider()
                val apps = listOfNotNull(
                    stringResource(R.string.settings_phone_whatsapp).takeIf { settings.phoneWhatsApp },
                    stringResource(R.string.settings_phone_messenger).takeIf { settings.phoneMessenger },
                    stringResource(R.string.settings_phone_messages).takeIf { settings.phoneMessages },
                )
                val phoneLine = stringResource(R.string.settings_phone_title) + " · " + when {
                    settings.phoneShare && !phoneGranted -> stringResource(R.string.settings_sum_access_revoked)
                    !settings.phoneShare -> stringResource(R.string.settings_sum_off)
                    apps.isEmpty() -> stringResource(R.string.settings_sum_no_app)
                    else -> apps.joinToString(", ")
                }
                SetItem(R.drawable.ic_m_chat, stringResource(R.string.settings_phone), phoneLine, onClick = { go(SettingsPages.MESSAGES) }, boxed = false)
                SetDivider()
                val looks = listOfNotNull(
                    stringResource(
                        when (settings.theme) {
                            ThemeMode.SYSTEM -> R.string.settings_theme_system
                            ThemeMode.LIGHT -> R.string.settings_theme_light
                            ThemeMode.DARK -> R.string.settings_theme_dark
                        },
                    ),
                    stringResource(R.string.settings_dynamic_color).takeIf { settings.dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S },
                ).joinToString(" · ")
                SetItem(R.drawable.ic_m_sun, stringResource(R.string.settings_appearance), looks, onClick = { go(SettingsPages.APPEARANCE) }, boxed = false)
                SetDivider()
                SetItem(R.drawable.ic_m_archive, stringResource(R.string.settings_data), stringResource(R.string.settings_sum_data), onClick = { go(SettingsPages.DATA) }, boxed = false)
            }
            Column(Modifier.padding(top = 12.dp)) {
                DangerButton(stringResource(R.string.menu_logout), { confirmLogout = true }, icon = R.drawable.ic_m_logout)
            }
        }
    }

    if (confirmLogout) {
        ConfirmDialog(
            title = stringResource(R.string.logout_confirm_title),
            text = stringResource(R.string.logout_confirm_text),
            confirm = stringResource(R.string.menu_logout),
            onConfirm = {
                confirmLogout = false
                // dans la portée du graphe : la session qui se ferme retire cet écran, la déconnexion va au bout
                graph.scope.launch { graph.auth.logout() }
            },
            onDismiss = { confirmLogout = false },
        )
    }
}

/**
 * Une page de Paramètres (`Route.SettingsPage`), par-dessus la racine ou l'écran qui y mène (Mail › Régler les
 * boîtes, la barre du Téléphone…). Chaque route a son propre état : une boîte n'hérite rien de la précédente. La liste
 * des pages est écrite ici ; Compte, Partages et « Ce téléphone » sont à Paramètres, les autres vivent dans le paquet de
 * leur domaine (`ui/mail/BoxPages.kt`, `ui/teams/TeamsPages.kt`, `ui/agenda/AgendaSettingsPages.kt`,
 * `ui/phone/PhonesPage.kt`, `ui/tools/McpPages.kt`), et leurs noms dans `ui/components/SettingsPages.kt`.
 */
@Composable
fun SettingsPageScreen(graph: AppGraph, route: Route.SettingsPage) {
    key(route) {
        when (route.page) {
            SettingsPages.ACCOUNT -> AccountPage(graph)
            SettingsPages.BOXES -> BoxesPage(graph)
            SettingsPages.BOX -> if (route.key.isEmpty()) NewBoxPage(graph) else BoxPage(graph, route.key)
            SettingsPages.TEAMS -> TeamsAccountsPage(graph)
            SettingsPages.TEAMS_ACCOUNT -> if (route.key.isEmpty()) NewTeamsPage(graph) else TeamsAccountPage(graph, route.key)
            SettingsPages.PHONES -> PhonesPage(graph)
            SettingsPages.SHARES -> SharesPage(graph, route.key)
            SettingsPages.SERVICES -> ServicesPage(graph)
            SettingsPages.SERVICE -> if (route.key.isEmpty()) PlugPage(graph) else ServicePage(graph, route.key)
            SettingsPages.NOTIFICATIONS -> NotificationsPage(graph)
            SettingsPages.POSITION -> PositionPage(graph)
            SettingsPages.MESSAGES -> MessagesPage(graph)
            SettingsPages.APPEARANCE -> AppearancePage(graph)
            SettingsPages.DATA -> DataPage(graph)
            SettingsPages.AGENDAS -> AgendasSettingsPage(graph)
            SettingsPages.AGENDA_ACCOUNT -> AgendaAccountPage(graph, route.key)
            SettingsPages.AGENDA_CALENDAR -> AgendaCalendarPage(graph, route.key)
            SettingsPages.AGENDA_PLUG -> AgendaPlugPage(graph, route.key)
            else -> ComingScreen(stringResource(R.string.nav_settings), BarNav.BACK, stringResource(R.string.settings_unknown_page))
        }
    }
}
