package fr.qwartz.mika.ui.agenda

import android.content.Intent
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.agenda.AgendaGroups
import fr.qwartz.mika.data.moi.agenda.AgendaKinds
import fr.qwartz.mika.data.moi.agenda.AgendaSignin
import fr.qwartz.mika.data.moi.agenda.MIKA_REMINDERS
import fr.qwartz.mika.data.moi.agenda.PLUG_KINDS
import fr.qwartz.mika.data.moi.agenda.accountLine
import fr.qwartz.mika.data.moi.agenda.accountState
import fr.qwartz.mika.data.moi.agenda.accountSync
import fr.qwartz.mika.data.moi.agenda.calendarState
import fr.qwartz.mika.data.moi.agenda.colorOf
import fr.qwartz.mika.data.moi.agenda.googleReturn
import fr.qwartz.mika.data.moi.agenda.kindLong
import fr.qwartz.mika.data.moi.agenda.levelWords
import fr.qwartz.mika.data.moi.agenda.mikaReminderWords
import fr.qwartz.mika.data.moi.agenda.needsSignin
import fr.qwartz.mika.data.moi.agenda.nearestColor
import fr.qwartz.mika.data.moi.agenda.providerDefaults
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.service.NotificationChannels
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.components.ActionButton
import fr.qwartz.mika.ui.components.ConfirmDialog
import fr.qwartz.mika.ui.components.DangerButton
import fr.qwartz.mika.ui.components.SaveBar
import fr.qwartz.mika.ui.components.SetDivider
import fr.qwartz.mika.ui.components.SetField
import fr.qwartz.mika.ui.components.SetGroup
import fr.qwartz.mika.ui.components.SetHead
import fr.qwartz.mika.ui.components.SetItem
import fr.qwartz.mika.ui.components.SetNote
import fr.qwartz.mika.ui.components.SetRow
import fr.qwartz.mika.ui.components.SetSwitch
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.components.settingsPage
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import fr.qwartz.mika.ui.theme.states
import kotlinx.coroutines.launch

/*
 * Paramètres › Agendas (ADR 0309, la maquette validée `agenda-parametres.js`) : une ligne après Comptes Teams, puis ses
 * pages, une ligne une page — ses comptes (la sorte, le nom, l'adresse, l'état en mots), ce qu'on lui partage et
 * l'agenda de Mika (« Dans l'Agenda » : l'affichage ici), ce qui vaut pour tous ses agendas ; la page d'un compte (ses
 * agendas, le compte, sa connexion, la synchro, le partage, le retirer) ; la page d'un agenda (son nom, sa couleur,
 * « Dans l'Agenda » — masqué, Mika ne s'en sert plus —, ses rappels, ce que Mika en fait, son partage) ; « Brancher un
 * agenda », un parcours par sorte. Ce que l'API ne sert pas n'y est pas : ni le premier jour de la semaine, ni le rappel
 * de départ ou le fuseau propres à une personne, ni « À qui » (un compte est à toi), ni la fréquence d'un abonnement.
 */

@Composable
private fun settingsVm(graph: AppGraph): AgendaSettingsViewModel {
    val session = rememberSessionKey(graph)
    val vm: AgendaSettingsViewModel = viewModel(key = "agenda.settings|$session") { AgendaSettingsViewModel(AgendaDeps(graph)) }
    val shell = LocalShell.current
    val me by graph.me.me.collectAsStateWithLifecycle()
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm) {
        vm.moved.collect { m ->
            when (m) {
                AgendaMove.Back -> shell.back()
                is AgendaMove.To -> shell.replace(m.route)
            }
        }
    }
    FollowLive(graph.live, AGENDA_TOPICS, vm, me?.person, onShown = { vm.resume(me?.person.orEmpty()) }) { vm.onLive(it) }
    return vm
}

/** L'icône d'une sorte de compte, dans son carré teinté. */
@Composable
internal fun KindIcon(kind: String, size: androidx.compose.ui.unit.Dp = 40.dp) {
    val color = agendaColor(
        when (kind) {
            AgendaKinds.GOOGLE -> "vert"
            AgendaKinds.MICROSOFT -> "bleu"
            AgendaKinds.CALDAV -> "sarcelle"
            AgendaKinds.ICAL -> "ambre"
            else -> "indigo"
        },
    )
    Box(Modifier.size(size).clip(RoundedCornerShape(12.dp)).background(tintOf(color)), contentAlignment = Alignment.Center) {
        MIcon(
            when (kind) {
                AgendaKinds.GOOGLE -> R.drawable.ic_m_globe
                AgendaKinds.MICROSOFT -> R.drawable.ic_m_key
                AgendaKinds.ICAL -> R.drawable.ic_m_link
                else -> R.drawable.ic_m_server
            },
            null,
            tint = color,
        )
    }
}

// ── la liste ────────────────────────────────────────────────────────────

@Composable
fun AgendasSettingsPage(graph: AppGraph) {
    val shell = LocalShell.current
    val vm = settingsVm(graph)
    val now = rememberNow(wallMs = graph.clock::wallMs)
    val off by graph.agendaPrefs.off.collectAsStateWithLifecycle()
    val context = LocalContext.current
    SectionScaffold(
        topBar = {
            MikaTopBar(
                stringResource(R.string.agenda_settings_title),
                BarNav.BACK,
                subtitle = vm.accounts.valueOrNull?.let { pluralStringResource(R.plurals.agenda_settings_sub, it.accounts.size, it.accounts.size) },
                face = false,
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { shell.navigate(settingsPage(SettingsPages.AGENDA_PLUG)) },
                icon = { MIcon(R.drawable.ic_m_plus, null) },
                text = { Text(stringResource(R.string.agenda_plug_short)) },
            )
        },
    ) { modifier ->
        LoadBox(vm.accounts, onRetry = vm::retry, modifier = modifier) { acc ->
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 96.dp)) {
                SetNote(stringResource(R.string.agenda_settings_lede))
                SetHead(stringResource(R.string.agenda_settings_accounts))
                SetGroup {
                    acc.accounts.forEachIndexed { i, a ->
                        if (i > 0) SetDivider()
                        val warn = !a.system && a.enabled && (needsSignin(a) || a.error.isNotBlank())
                        SetItem(
                            null,
                            a.label,
                            listOf(a.address, accountLine(a, now)).filter { it.isNotBlank() }.joinToString("\n"),
                            onClick = { shell.navigate(settingsPage(SettingsPages.AGENDA_ACCOUNT, a.key)) },
                            lead = { KindIcon(a.kind) },
                        ) {
                            if (warn) MIcon(R.drawable.ic_m_alert, null, size = 18.dp, tint = states.warn) else MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp)
                        }
                    }
                }
                val shared = vm.calendars.filter { it.group == AgendaGroups.SHARED }
                if (shared.isNotEmpty()) {
                    SetHead(stringResource(R.string.agenda_settings_shared))
                    SetGroup {
                        shared.forEachIndexed { i, c ->
                            if (i > 0) SetDivider()
                            SetItem(
                                null,
                                c.name,
                                stringResource(R.string.agenda_settings_shared_line, c.ownerName, levelWords(c.level).lowercase()),
                                lead = { PersonAvatar(c.ownerName, c.key, 40.dp) },
                            ) {
                                Switch(checked = c.key !in off, onCheckedChange = { graph.agendaPrefs.setShown(c.key, it) })
                            }
                        }
                    }
                }
                Text(stringResource(R.string.agenda_hers), style = MaterialTheme.typography.titleSmall, color = mika.accent, modifier = Modifier.padding(start = 28.dp, top = 18.dp, bottom = 6.dp))
                Surface(shape = RoundedCornerShape(16.dp), color = mika.soft, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                    Row(Modifier.padding(14.dp), verticalAlignment = Alignment.Top) {
                        MikaFace(40.dp)
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(stringResource(R.string.agenda_hers), style = MaterialTheme.typography.bodyLarge)
                            Text(stringResource(R.string.agenda_settings_hers_text), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                        Switch(checked = AgendaKinds.MIKA !in off, onCheckedChange = { graph.agendaPrefs.setShown(AgendaKinds.MIKA, it) })
                    }
                }
                SetNote(stringResource(R.string.agenda_settings_hers_note))
                SetHead(stringResource(R.string.agenda_settings_all))
                SetGroup {
                    SetItem(null, stringResource(R.string.agenda_settings_zone), stringResource(R.string.agenda_settings_zone_help)) {
                        Tag(zoneOf(vm), Tone.NEUTRAL)
                    }
                    SetDivider()
                    SetItem(null, stringResource(R.string.agenda_settings_window), stringResource(R.string.agenda_settings_window_help)) {
                        Tag(stringResource(R.string.agenda_settings_window_tag), Tone.NEUTRAL)
                    }
                    acc.max?.let { max ->
                        SetDivider()
                        SetItem(null, stringResource(R.string.agenda_settings_max), stringResource(R.string.agenda_settings_max_help)) {
                            Tag(stringResource(R.string.agenda_settings_max_tag, max), Tone.NEUTRAL)
                        }
                    }
                    SetDivider()
                    SetItem(null, stringResource(R.string.agenda_settings_notifications), stringResource(R.string.agenda_settings_notifications_help), onClick = {
                        runCatching {
                            context.startActivity(
                                Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                                    .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
                                    .putExtra(Settings.EXTRA_CHANNEL_ID, NotificationChannels.AGENDA)
                                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                            )
                        }
                    }) {
                        Text(stringResource(R.string.agenda_settings_adjust), color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
                    }
                }
            }
        }
    }
}

/** Le fuseau du serveur (celui où l'Agenda se lit), tel que ses agendas le disent. */
private fun zoneOf(vm: AgendaSettingsViewModel): String = vm.zone.ifBlank { "—" }

// ── un compte ───────────────────────────────────────────────────────────

@Composable
fun AgendaAccountPage(graph: AppGraph, key: String) {
    val shell = LocalShell.current
    val vm = settingsVm(graph)
    val now = rememberNow(wallMs = graph.clock::wallMs)
    val a = vm.account(key)
    var confirm by rememberSaveable { mutableStateOf("") }
    var creating by rememberSaveable { mutableStateOf(false) }
    var share by rememberSaveable { mutableStateOf("") }
    // le formulaire du compte : ce qui est tapé, à côté de ce qui est enregistré
    var label by rememberSaveable(key) { mutableStateOf<String?>(null) }
    var url by rememberSaveable(key) { mutableStateOf<String?>(null) }
    var username by rememberSaveable(key) { mutableStateOf<String?>(null) }
    var password by rememberSaveable(key) { mutableStateOf("") }
    val changed = a != null && ((label != null && label != a.label) || (url != null && url != a.url) || (username != null && username != a.username) || password.isNotEmpty())
    SectionScaffold(
        topBar = {
            MikaTopBar(
                a?.label ?: stringResource(R.string.agenda_settings_title),
                BarNav.BACK,
                subtitle = a?.let { kindLong(it.kind, it.kindLabel) },
                face = false,
                actions = { if (a != null && !a.system) BarAction(R.drawable.ic_m_refresh, stringResource(R.string.agenda_sync), { vm.sync(a.key) }) },
            )
        },
        bottomBar = {
            SaveBar(changed, vm.acting, onCancel = {
                label = null
                url = null
                username = null
                password = ""
            }, onSave = {
                val acc = a ?: return@SaveBar
                val values = buildMap<String, Any> {
                    label?.takeIf { it != acc.label }?.let { put("label", it.trim()) }
                    url?.takeIf { it != acc.url && it.isNotBlank() }?.let { put("url", it.trim()) }
                    username?.takeIf { it != acc.username }?.let { put("username", it.trim()) }
                    if (password.isNotEmpty()) put("password", password)
                }
                vm.saveAccount(acc, values)
                password = ""
            })
        },
    ) { modifier ->
        LoadBox(vm.accounts, onRetry = vm::retry, modifier = modifier) { _ ->
            if (a == null) {
                fr.qwartz.mika.ui.shell.Notice(stringResource(R.string.agenda_account_gone), modifier)
                return@LoadBox
            }
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                    KindIcon(a.kind, 48.dp)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(a.address.ifBlank { a.label }, style = MaterialTheme.typography.titleMedium)
                        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 4.dp)) {
                            val (tone, words) = accountState(a)
                            Tag(words, tone)
                            Tag(stringResource(R.string.agenda_whose_mine), Tone.INFO)
                        }
                    }
                }
                if (!a.system && (a.error.isNotBlank() || (needsSignin(a) && a.enabled))) {
                    Surface(shape = RoundedCornerShape(14.dp), color = states.warnContainer, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
                        Column(Modifier.padding(14.dp)) {
                            Text(a.error.ifBlank { stringResource(R.string.agenda_account_to_connect) }, color = states.warn, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                            Text(accountSync(a, now), style = MaterialTheme.typography.bodySmall, color = states.warn)
                            if (needsSignin(a)) {
                                Button(onClick = { shell.navigate(settingsPage(SettingsPages.AGENDA_PLUG, "${a.kind}/${a.key}")) }, modifier = Modifier.padding(top = 8.dp)) {
                                    MIcon(R.drawable.ic_m_key, null, size = 18.dp)
                                    Spacer(Modifier.width(8.dp))
                                    Text(stringResource(if (a.signin?.state == AgendaSignin.TODO && a.syncedAt <= 0) R.string.agenda_connect else R.string.agenda_reconnect))
                                }
                            }
                        }
                    }
                } else {
                    SetNote(accountSync(a, now))
                }
                SetHead(stringResource(R.string.agenda_account_calendars))
                SetGroup {
                    a.calendars.forEachIndexed { i, c ->
                        if (i > 0) SetDivider()
                        SetItem(null, c.name, calendarState(c), onClick = { shell.navigate(settingsPage(SettingsPages.AGENDA_CALENDAR, c.key)) }, lead = { Swatch(colorOf(c), 22.dp) }) {
                            if (c.primary) Tag(stringResource(R.string.agenda_default_tag), Tone.NEUTRAL)
                            MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp)
                        }
                    }
                    if (a.calendars.isEmpty()) SetRow("", stringResource(R.string.agenda_account_no_calendar))
                    if (a.system || a.abilities.calendars) {
                        SetDivider()
                        SetItem(R.drawable.ic_m_plus, stringResource(R.string.agenda_new_calendar), onClick = {
                            if (a.system) shell.navigate(settingsPage(SettingsPages.AGENDA_PLUG, AgendaKinds.SYSTEM)) else creating = true
                        }, boxed = false)
                    }
                    if (!a.system && a.kind != AgendaKinds.ICAL) {
                        SetDivider()
                        SetItem(R.drawable.ic_m_refresh, stringResource(R.string.agenda_find_more), stringResource(R.string.agenda_find_more_help), onClick = { vm.sync(a.key) }, boxed = false)
                    }
                }
                SetHead(stringResource(R.string.agenda_account_title))
                SetGroup {
                    SetField(stringResource(R.string.agenda_account_name), label ?: a.label, { label = it }, help = stringResource(R.string.agenda_account_name_help), error = vm.fields["label"], max = 200, enabled = !a.system)
                    SetDivider()
                    when (a.kind) {
                        AgendaKinds.SYSTEM -> SetItem(null, stringResource(R.string.agenda_account_connection), stringResource(R.string.agenda_account_connection_system)) { Tag(stringResource(R.string.agenda_on_this_server), Tone.OK) }
                        AgendaKinds.GOOGLE, AgendaKinds.MICROSOFT -> {
                            val signed = a.signin?.state == AgendaSignin.CONNECTED
                            SetRow(
                                stringResource(if (a.kind == AgendaKinds.GOOGLE) R.string.agenda_account_google else R.string.agenda_account_microsoft),
                                stringResource(if (a.kind == AgendaKinds.GOOGLE) R.string.agenda_account_google_help else R.string.agenda_account_microsoft_help),
                            ) {
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 6.dp)) {
                                    Tag(stringResource(if (signed) R.string.agenda_connected else if (a.signin?.state == AgendaSignin.WAITING) R.string.agenda_waiting else R.string.agenda_to_connect), if (signed) Tone.OK else Tone.WARN)
                                    TextButton(onClick = { shell.navigate(settingsPage(SettingsPages.AGENDA_PLUG, "${a.kind}/${a.key}")) }) {
                                        Text(stringResource(if (signed) R.string.agenda_reconnect else R.string.agenda_connect))
                                    }
                                    if (signed) TextButton(onClick = { confirm = "deco" }) { Text(stringResource(R.string.agenda_disconnect), color = MaterialTheme.colorScheme.error) }
                                }
                            }
                        }
                        AgendaKinds.ICAL -> SetField(
                            stringResource(R.string.agenda_account_ics),
                            url ?: "",
                            { url = it },
                            help = stringResource(R.string.agenda_account_ics_help),
                            placeholder = stringResource(if (a.urlSet) R.string.agenda_account_ics_kept else R.string.agenda_account_ics_placeholder),
                            error = vm.fields["url"],
                            mono = true,
                        )
                        else -> {
                            SetField(stringResource(R.string.agenda_account_server), url ?: a.url, { url = it }, error = vm.fields["url"], mono = true)
                            SetField(stringResource(R.string.agenda_account_username), username ?: a.username, { username = it }, error = vm.fields["username"])
                            SetField(
                                stringResource(R.string.agenda_account_password),
                                password,
                                { password = it },
                                help = stringResource(R.string.agenda_account_password_help),
                                placeholder = if (a.secrets.password) stringResource(R.string.agenda_account_password_kept) else "",
                                error = vm.fields["password"],
                                secret = true,
                            )
                            Box(Modifier.padding(horizontal = 14.dp, vertical = 6.dp)) {
                                ActionButton(stringResource(R.string.agenda_try), R.drawable.ic_m_refresh, { vm.tryAccount(a, url ?: a.url, username ?: a.username, password) }, enabled = !vm.acting)
                            }
                        }
                    }
                    if (!a.system) {
                        SetDivider()
                        SetItem(
                            null,
                            stringResource(R.string.agenda_account_sync),
                            if (a.kind == AgendaKinds.ICAL) stringResource(R.string.agenda_account_sync_ical) else stringResource(R.string.agenda_account_sync_help),
                        ) {
                            FilledTonalButton(onClick = { vm.sync(a.key) }, enabled = !vm.acting) {
                                MIcon(R.drawable.ic_m_refresh, null, size = 16.dp)
                                Spacer(Modifier.width(6.dp))
                                Text(stringResource(R.string.agenda_sync))
                            }
                        }
                    }
                }
                val shareable = a.calendars.filter { !it.hidden && it.can.share }
                if (shareable.isNotEmpty()) {
                    SetHead(stringResource(R.string.agenda_account_share))
                    val provider = when (a.kind) {
                        AgendaKinds.GOOGLE -> "Google"
                        AgendaKinds.MICROSOFT -> "Microsoft"
                        AgendaKinds.CALDAV -> stringResource(R.string.agenda_caldav_server)
                        else -> ""
                    }
                    if (provider.isNotEmpty()) NoteBox(stringResource(R.string.agenda_account_share_note, provider), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                    SetGroup {
                        shareable.forEachIndexed { i, c ->
                            if (i > 0) SetDivider()
                            SetItem(
                                null,
                                c.name,
                                if (c.shares.isEmpty()) stringResource(R.string.agenda_nobody) else c.shares.joinToString(" ; ") { "${firstName(it.name)} · ${levelWords(it.level).lowercase()}" },
                                onClick = { share = c.key },
                                lead = { Swatch(colorOf(c), 22.dp) },
                            ) { Text(stringResource(R.string.agenda_share), color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge) }
                        }
                    }
                }
                if (!a.system) {
                    Spacer(Modifier.size(12.dp))
                    DangerButton(stringResource(R.string.agenda_account_remove), { confirm = "retirer" })
                    SetNote(stringResource(R.string.agenda_account_remove_note))
                }
            }
        }
    }
    if (a != null) {
        when (confirm) {
            "retirer" -> ConfirmDialog(
                stringResource(R.string.agenda_account_remove_title),
                stringResource(R.string.agenda_account_remove_text, a.label),
                stringResource(R.string.agenda_remove),
                onConfirm = {
                    confirm = ""
                    vm.remove(a.key)
                },
                onDismiss = { confirm = "" },
                danger = true,
            )
            "deco" -> ConfirmDialog(
                stringResource(R.string.agenda_disconnect_title),
                stringResource(R.string.agenda_disconnect_text),
                stringResource(R.string.agenda_disconnect),
                onConfirm = {
                    confirm = ""
                    vm.disconnect(a.key)
                },
                onDismiss = { confirm = "" },
                danger = true,
            )
        }
        if (creating) {
            var name by rememberSaveable { mutableStateOf("") }
            AlertDialog(
                onDismissRequest = { creating = false },
                title = { Text(stringResource(R.string.agenda_new_calendar)) },
                text = {
                    Column {
                        OutlinedTextField(name, { name = it.take(200) }, label = { Text(stringResource(R.string.agenda_account_name)) }, singleLine = true)
                        Text(stringResource(R.string.agenda_new_calendar_provider), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                    }
                },
                confirmButton = {
                    TextButton(onClick = {
                        if (name.isNotBlank()) {
                            creating = false
                            vm.newCalendar(a.key, name.trim())
                        }
                    }) { Text(stringResource(R.string.agenda_create)) }
                },
                dismissButton = { TextButton(onClick = { creating = false }) { Text(stringResource(R.string.cancel)) } },
            )
        }
        val cal = vm.calendar(share)
        if (share.isNotEmpty() && cal != null) ShareSheet(graph, cal, onDismiss = { share = "" }, onHide = {})
    }
}

// ── un agenda ───────────────────────────────────────────────────────────

@Composable
fun AgendaCalendarPage(graph: AppGraph, key: String) {
    val shell = LocalShell.current
    val vm = settingsVm(graph)
    val c = vm.calendar(key)
    var name by rememberSaveable(key) { mutableStateOf<String?>(null) }
    var remind by rememberSaveable { mutableStateOf(false) }
    var share by rememberSaveable { mutableStateOf(false) }
    val account = c?.let { vm.account(it.account) }
    SectionScaffold(
        topBar = {
            MikaTopBar(c?.name ?: stringResource(R.string.agenda_settings_title), BarNav.BACK, subtitle = account?.let { listOf(it.label, it.address).filter { s -> s.isNotBlank() }.joinToString(" · ") }, face = false)
        },
        bottomBar = {
            SaveBar(c != null && name != null && name != c.name, vm.acting, onCancel = { name = null }, onSave = {
                val n = name ?: return@SaveBar
                vm.saveCalendar(key, mapOf("name" to n.trim()))
                name = null
            })
        },
    ) { modifier ->
        LoadBox(vm.accounts, onRetry = vm::retry, modifier = modifier) { _ ->
            if (c == null) {
                fr.qwartz.mika.ui.shell.Notice(stringResource(R.string.agenda_calendar_gone), modifier)
                return@LoadBox
            }
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
                SetGroup(Modifier.padding(top = 8.dp)) {
                    SetField(
                        stringResource(R.string.agenda_account_name),
                        name ?: c.name,
                        { name = it },
                        help = if (c.providerName.isNotBlank()) stringResource(R.string.agenda_calendar_provider_name, c.providerName) else if (c.kind != AgendaKinds.SYSTEM) stringResource(R.string.agenda_calendar_rename_help) else "",
                        max = 200,
                        enabled = c.can.rename,
                    )
                    SetDivider()
                    SetRow(stringResource(R.string.agenda_color), stringResource(R.string.agenda_color_help)) {
                        Swatches(colorOf(c), { k -> vm.saveCalendar(key, mapOf("color" to k)) }, Modifier.padding(top = 10.dp))
                    }
                    SetDivider()
                    SetSwitch(
                        stringResource(R.string.agenda_in_agenda),
                        stringResource(if (c.hidden) R.string.agenda_in_agenda_off else R.string.agenda_in_agenda_on),
                        !c.hidden,
                        { on -> vm.saveCalendar(key, mapOf("hidden" to !on)) },
                        enabled = c.can.settings && !vm.acting,
                    )
                    SetDivider()
                    SetItem(null, stringResource(R.string.agenda_can)) { Tag(stringResource(if (c.writable) R.string.agenda_can_write else R.string.agenda_can_read), Tone.NEUTRAL) }
                    if (c.primary) {
                        SetDivider()
                        SetItem(null, stringResource(R.string.agenda_default_title), stringResource(R.string.agenda_default_help)) { Tag(stringResource(R.string.agenda_default_tag), Tone.INFO) }
                    }
                }
                SetHead(stringResource(R.string.agenda_reminders))
                SetGroup {
                    SetItem(null, stringResource(R.string.agenda_provider_reminders), providerDefaults(c))
                    if (c.can.remind) {
                        SetDivider()
                        SetItem(R.drawable.ic_m_sparkle, stringResource(R.string.agenda_remind_title), stringResource(R.string.agenda_remind_default_help), onClick = { remind = true }, boxed = false) {
                            // la valeur, et « par défaut » dessous tant que l'agenda n'a pas la sienne (le titre garde sa ligne)
                            Column(horizontalAlignment = Alignment.End) {
                                Text(mikaReminderWords(c.reminder), color = mika.accent, style = MaterialTheme.typography.labelLarge)
                                if (c.reminderSet.isEmpty()) {
                                    Text(stringResource(R.string.agenda_default_tag), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                                }
                            }
                        }
                    }
                }
                if (c.can.rights) {
                    Text(stringResource(R.string.agenda_what_mika_does), style = MaterialTheme.typography.titleSmall, color = mika.accent, modifier = Modifier.padding(start = 28.dp, top = 18.dp, bottom = 6.dp))
                    Surface(onClick = { shell.navigate(Route.CalendarRights(c.key)) }, shape = RoundedCornerShape(16.dp), color = mika.soft, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(vm.summaries[c.key].orEmpty().ifBlank { stringResource(R.string.agenda_rights_its_table) }, style = MaterialTheme.typography.bodyLarge)
                                Text(stringResource(R.string.agenda_rights_its_table_help), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                            Text(stringResource(R.string.agenda_rights_its), color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
                        }
                    }
                }
                if (c.can.share) {
                    SetHead(stringResource(R.string.agenda_account_share))
                    SetGroup {
                        for (s in c.shares) {
                            SetItem(null, s.name, levelWords(s.level), lead = { PersonAvatar(s.name, s.person, 32.dp) })
                            SetDivider()
                        }
                        SetItem(R.drawable.ic_m_user_plus, stringResource(if (c.shares.isEmpty()) R.string.agenda_share else R.string.agenda_share_manage), onClick = { share = true }, boxed = false)
                    }
                }
            }
        }
    }
    if (c != null && remind) {
        ChoiceSheet(
            stringResource(R.string.agenda_remind_calendar_title, c.name),
            listOf("" to stringResource(R.string.agenda_by_default_plain)) + MIKA_REMINDERS,
            c.reminderSet,
            onDismiss = { remind = false },
        ) { k ->
            remind = false
            vm.saveCalendar(key, mapOf("reminder" to k))
        }
    }
    if (c != null && share) ShareSheet(graph, c, onDismiss = { share = false }, onHide = {})
}

// ── brancher un agenda ──────────────────────────────────────────────────

/** « Brancher un agenda » : [spec] vide (la liste des sortes), une sorte, ou `<sorte>/<compte>` (se reconnecter). */
@Composable
fun AgendaPlugPage(graph: AppGraph, spec: String) {
    val shell = LocalShell.current
    val vm = settingsVm(graph)
    val kind = spec.substringBefore('/')
    val account = spec.substringAfter('/', "")
    LaunchedEffect(vm, spec) { if (kind.isNotEmpty()) vm.startPlug(kind, account) }
    SectionScaffold(
        topBar = {
            MikaTopBar(
                if (kind.isEmpty()) stringResource(R.string.agenda_plug) else stringResource(R.string.agenda_plug_kind, kindLong(kind)),
                BarNav.BACK,
                face = false,
            )
        },
    ) { modifier ->
        LoadBox(vm.accounts, onRetry = vm::retry, modifier = modifier) { acc ->
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
                if (kind.isEmpty()) {
                    SetNote(stringResource(R.string.agenda_plug_lede))
                    SetGroup {
                        PLUG_KINDS.forEachIndexed { i, (k, long, help) ->
                            if (i > 0) SetDivider()
                            SetItem(null, long, help, onClick = { shell.navigate(settingsPage(SettingsPages.AGENDA_PLUG, k)) }, lead = { KindIcon(k) }) {
                                MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp)
                            }
                        }
                    }
                    return@Column
                }
                val p = vm.plug
                if (p == null || p.kind != kind) return@Column
                PlugSteps(graph, vm, p, acc.google.app, acc.microsoftApp, acc.services)
            }
        }
    }
}

/** Un parcours en étapes : chacune son numéro, son titre, et ce qu'elle demande quand c'est son tour. */
@Composable
private fun Step(n: Int, title: String, at: Int, onBack: (() -> Unit)? = null, content: @Composable () -> Unit) {
    val done = at > n
    val active = at == n
    val scheme = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.Top) {
        Box(
            Modifier.size(32.dp).clip(CircleShape).background(if (done || active) scheme.primary else scheme.surfaceContainerHigh),
            contentAlignment = Alignment.Center,
        ) {
            if (done) MIcon(R.drawable.ic_m_check, null, size = 16.dp, tint = scheme.onPrimary) else Text("$n", color = if (active) scheme.onPrimary else scheme.onSurfaceVariant, fontWeight = FontWeight.SemiBold)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(title, style = MaterialTheme.typography.titleMedium, color = if (done || active) scheme.onSurface else scheme.onSurfaceVariant, modifier = Modifier.weight(1f).padding(top = 4.dp))
                if (done && onBack != null) TextButton(onClick = onBack) { Text(stringResource(R.string.agenda_modify)) }
            }
            if (active) Column(Modifier.padding(top = 6.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) { content() }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun PlugSteps(graph: AppGraph, vm: AgendaSettingsViewModel, p: Plug, googleApp: Boolean, microsoftApp: Boolean, services: List<fr.qwartz.mika.data.moi.agenda.AgendaService>) {
    val shell = LocalShell.current
    val context = LocalContext.current
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val open = { url: String -> runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }; Unit }
    val err: @Composable () -> Unit = { if (p.error.isNotBlank()) Text(p.error, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
    val body = MaterialTheme.typography.bodyMedium
    when (p.kind) {
        AgendaKinds.SYSTEM -> {
            var name by rememberSaveable { mutableStateOf("") }
            var color by rememberSaveable { mutableStateOf("sarcelle") }
            var reminder by rememberSaveable { mutableStateOf("30") }
            var picking by rememberSaveable { mutableStateOf(false) }
            Step(1, stringResource(R.string.agenda_plug_system_title), 1) {
                Text(stringResource(R.string.agenda_plug_system_text), style = body)
                OutlinedTextField(name, { name = it.take(200) }, label = { Text(stringResource(R.string.agenda_account_name)) }, placeholder = { Text(stringResource(R.string.agenda_plug_system_example)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                Text(stringResource(R.string.agenda_color), style = MaterialTheme.typography.labelLarge)
                Swatches(color, { color = it })
                Row(Modifier.fillMaxWidth().clickable { picking = true }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp, tint = mika.accent)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.agenda_remind_title), modifier = Modifier.weight(1f), color = mika.accent)
                    Text(mikaReminderWords(reminder), color = mika.accent)
                }
                err()
                Button(onClick = { vm.plugSystem(name, color, reminder) }, enabled = !vm.acting, modifier = Modifier.fillMaxWidth()) {
                    MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.agenda_plug_system_create))
                }
                Text(stringResource(R.string.agenda_plug_yours), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (picking) ChoiceSheet(stringResource(R.string.agenda_remind_title), MIKA_REMINDERS, reminder, onDismiss = { picking = false }) {
                reminder = it
                picking = false
            }
        }
        AgendaKinds.GOOGLE -> {
            var pasted by rememberSaveable { mutableStateOf("") }
            Step(1, stringResource(R.string.agenda_plug_google_1), p.step, onBack = { vm.stepBack(1) }) {
                if (!googleApp) {
                    NoteBox(stringResource(R.string.agenda_plug_google_no_app), R.drawable.ic_m_alert, tone = Tone.WARN)
                    Text(stringResource(R.string.agenda_plug_google_ical), style = body)
                    TextButton(onClick = { shell.replace(settingsPage(SettingsPages.AGENDA_PLUG, AgendaKinds.ICAL)) }) { Text(stringResource(R.string.agenda_plug_ical_short)) }
                } else {
                    Text(stringResource(R.string.agenda_plug_google_1_text), style = body)
                    err()
                    Button(onClick = { vm.googleStart(open) }, enabled = !vm.acting, modifier = Modifier.fillMaxWidth()) {
                        MIcon(R.drawable.ic_m_external, null, size = 18.dp)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.agenda_plug_google_open))
                    }
                    Text(stringResource(R.string.agenda_plug_google_app), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            val back = googleReturn(p.direct)
            Step(2, stringResource(if (p.direct) R.string.agenda_plug_google_2_direct else R.string.agenda_plug_google_2), p.step) {
                if (back.waits) {
                    Text(stringResource(R.string.agenda_plug_google_direct), style = body)
                    Waiting(stringResource(R.string.agenda_waiting_google))
                } else {
                    Text(stringResource(R.string.agenda_plug_google_2_text), style = body)
                    FakeAddressBar()
                }
                if (back.pastes) {
                    Text(stringResource(R.string.agenda_plug_google_how), style = body)
                    OutlinedTextField(
                        pasted,
                        { pasted = it },
                        label = { Text(stringResource(R.string.agenda_plug_google_field)) },
                        placeholder = { Text(back.example) },
                        singleLine = true,
                        textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    err()
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        FilledTonalButton(onClick = {
                            scope.launch { clipboard.getClipEntry()?.clipData?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.text?.toString()?.let { pasted = it.trim() } }
                        }) {
                            MIcon(R.drawable.ic_m_copy, null, size = 16.dp)
                            Spacer(Modifier.width(6.dp))
                            Text(stringResource(R.string.agenda_paste))
                        }
                        Spacer(Modifier.weight(1f))
                        Button(onClick = { vm.googleFinish(pasted) }, enabled = !vm.acting) { Text(stringResource(R.string.agenda_validate)) }
                    }
                    if (p.url.isNotEmpty()) TextButton(onClick = { open(p.url) }) { Text(stringResource(R.string.agenda_plug_google_reopen)) }
                    if (!p.direct) Text(stringResource(R.string.agenda_plug_google_https), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Step(3, stringResource(R.string.agenda_plug_choose), p.step) { Chosen(vm, p) }
        }
        AgendaKinds.MICROSOFT -> {
            val existing = vm.account(p.account)
            var address by rememberSaveable { mutableStateOf(existing?.address.orEmpty()) }
            Step(1, stringResource(R.string.agenda_plug_microsoft_1), p.step, onBack = { vm.stepBack(1) }) {
                if (!microsoftApp) {
                    NoteBox(stringResource(R.string.agenda_plug_microsoft_no_app), R.drawable.ic_m_alert, tone = Tone.WARN)
                } else {
                    Text(stringResource(R.string.agenda_plug_microsoft_1_text), style = body)
                    TextButton(onClick = { shell.replace(settingsPage(SettingsPages.AGENDA_PLUG, AgendaKinds.CALDAV)) }) { Text(stringResource(R.string.agenda_plug_davmail_short)) }
                    OutlinedTextField(address, { address = it.trim() }, label = { Text(stringResource(R.string.agenda_plug_address)) }, placeholder = { Text("prenom.nom@outlook.fr") }, singleLine = true, enabled = p.account.isEmpty(), modifier = Modifier.fillMaxWidth())
                    err()
                    Button(onClick = { vm.microsoftStart(address) }, enabled = !vm.acting && (address.contains('@') || p.account.isNotEmpty()), modifier = Modifier.fillMaxWidth()) {
                        MIcon(R.drawable.ic_m_key, null, size = 18.dp)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.agenda_plug_get_code))
                    }
                }
            }
            Step(2, stringResource(R.string.agenda_plug_microsoft_2), p.step) {
                Surface(shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.surfaceContainerHigh, modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(stringResource(R.string.agenda_plug_your_code), style = MaterialTheme.typography.labelMedium)
                        Text(p.code, style = MaterialTheme.typography.headlineMedium, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
                        if (p.until > 0) Text(stringResource(R.string.agenda_plug_until, fr.qwartz.mika.data.moi.agenda.hm(fr.qwartz.mika.data.moi.agenda.localOf(p.until, java.util.TimeZone.getDefault().id).minute)), style = MaterialTheme.typography.bodySmall)
                    }
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    FilledTonalButton(onClick = { scope.launch { fr.qwartz.mika.ui.components.copyText(clipboard, p.code) } }) {
                        MIcon(R.drawable.ic_m_copy, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.agenda_plug_copy_code))
                    }
                    Button(onClick = { open(p.url.ifBlank { "https://microsoft.com/devicelogin" }) }) {
                        MIcon(R.drawable.ic_m_external, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.agenda_plug_open_microsoft))
                    }
                }
                Text(stringResource(R.string.agenda_plug_microsoft_how), style = body)
                err()
                Waiting(stringResource(R.string.agenda_waiting_microsoft))
            }
            Step(3, stringResource(R.string.agenda_plug_choose), p.step) { Chosen(vm, p) }
        }
        AgendaKinds.CALDAV -> {
            var service by rememberSaveable { mutableStateOf(services.firstOrNull()?.key.orEmpty()) }
            val svc = services.firstOrNull { it.key == service }
            var url by rememberSaveable { mutableStateOf("") }
            var user by rememberSaveable { mutableStateOf("") }
            var pass by rememberSaveable { mutableStateOf("") }
            var label by rememberSaveable { mutableStateOf("") }
            Step(1, stringResource(R.string.agenda_plug_caldav_1), p.step, onBack = { vm.stepBack(1) }) {
                if (services.isNotEmpty()) {
                    Text(stringResource(R.string.agenda_plug_help_for), style = MaterialTheme.typography.labelLarge)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        for (s in services) FilterChip(selected = s.key == service, onClick = { service = s.key }, label = { Text(s.name) })
                    }
                    if (svc != null) NoteBox("${svc.name} · ${svc.help}", R.drawable.ic_m_info)
                }
                OutlinedTextField(url, { url = it.trim() }, label = { Text(stringResource(R.string.agenda_account_server)) }, placeholder = { Text(svc?.url ?: "https://…", maxLines = 1, overflow = TextOverflow.Ellipsis) }, singleLine = true, textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), modifier = Modifier.fillMaxWidth())
                OutlinedTextField(user, { user = it.trim() }, label = { Text(stringResource(R.string.agenda_account_username)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                OutlinedTextField(
                    pass,
                    { pass = it },
                    label = { Text(stringResource(R.string.agenda_account_password)) },
                    singleLine = true,
                    visualTransformation = androidx.compose.ui.text.input.PasswordVisualTransformation(),
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(stringResource(R.string.agenda_account_password_help), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                err()
                Button(onClick = { vm.caldavTry(url.ifBlank { svc?.url.orEmpty() }, user, pass) }, enabled = !vm.acting, modifier = Modifier.fillMaxWidth()) {
                    MIcon(R.drawable.ic_m_refresh, null, size = 18.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.agenda_try))
                }
            }
            Step(2, stringResource(R.string.agenda_plug_caldav_2), p.step) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_check, null, size = 18.dp, tint = states.ok)
                    Spacer(Modifier.width(6.dp))
                    Text(pluralStringResource(R.plurals.agenda_plug_caldav_found, p.tried.size, p.tried.size), color = states.ok)
                }
                for (t in p.tried) {
                    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(vertical = 2.dp)) {
                        Swatch(nearestColor(t.color).ifEmpty { "ardoise" }, 14.dp)
                        Spacer(Modifier.width(8.dp))
                        Text(t.name.ifBlank { t.local }, modifier = Modifier.weight(1f))
                        if (!t.writable) Text(stringResource(R.string.agenda_read_only), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
                OutlinedTextField(label.ifEmpty { svc?.name.orEmpty() }, { label = it.take(200) }, label = { Text(stringResource(R.string.agenda_account_name)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                err()
                Button(onClick = { vm.caldavPlug(label.ifEmpty { svc?.name.orEmpty() }) }, enabled = !vm.acting, modifier = Modifier.fillMaxWidth()) {
                    MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.agenda_plug_button))
                }
                Text(stringResource(R.string.agenda_plug_caldav_after), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        AgendaKinds.ICAL -> {
            var url by rememberSaveable { mutableStateOf("") }
            var label by rememberSaveable { mutableStateOf("") }
            Step(1, stringResource(R.string.agenda_plug_ical_1), 1) {
                Text(stringResource(R.string.agenda_plug_ical_text), style = body)
                OutlinedTextField(url, { url = it.trim() }, label = { Text(stringResource(R.string.agenda_account_ics)) }, placeholder = { Text("https://…/basic.ics") }, singleLine = true, textStyle = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), modifier = Modifier.fillMaxWidth())
                Text(stringResource(R.string.agenda_account_ics_help), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                OutlinedTextField(label, { label = it.take(200) }, label = { Text(stringResource(R.string.agenda_account_name)) }, placeholder = { Text(stringResource(R.string.agenda_plug_ical_example)) }, singleLine = true, modifier = Modifier.fillMaxWidth())
                err()
                Button(onClick = { vm.icalPlug(url, label) }, enabled = !vm.acting && url.isNotBlank(), modifier = Modifier.fillMaxWidth()) {
                    MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.agenda_plug_subscribe))
                }
                Text(stringResource(R.string.agenda_plug_ical_after), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** Une attente que le serveur dit quand elle finit (le direct) : un petit rond qui tourne et ses mots. */
@Composable
private fun Waiting(text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
        Spacer(Modifier.width(10.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Le dessin de la barre d'adresse de Chrome sur la page qui n'a pas pu s'ouvrir (l'adresse à copier). */
@Composable
private fun FakeAddressBar() {
    val scheme = MaterialTheme.colorScheme
    Surface(shape = RoundedCornerShape(14.dp), color = scheme.surfaceContainerHigh, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(10.dp)) {
            Surface(shape = RoundedCornerShape(20.dp), color = scheme.surface, modifier = Modifier.fillMaxWidth()) {
                Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_info, null, size = 14.dp)
                    Spacer(Modifier.width(6.dp))
                    Text("127.0.0.1/?state=k2Q…&code=4/0Aan…", fontFamily = FontFamily.Monospace, fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            Column(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                MIcon(R.drawable.ic_m_alert, null, size = 20.dp, tint = scheme.onSurfaceVariant)
                Text(stringResource(R.string.agenda_plug_unreachable), style = MaterialTheme.typography.titleSmall)
                Text(stringResource(R.string.agenda_plug_unreachable_text), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            }
        }
    }
}

/** Les agendas d'un compte qu'on vient de brancher : « Dans l'Agenda », un par un (la synchronisation les apporte). */
@Composable
private fun Chosen(vm: AgendaSettingsViewModel, p: Plug) {
    val a = vm.account(p.account)
    val cals = a?.calendars.orEmpty()
    if (cals.isEmpty()) {
        Waiting(stringResource(R.string.agenda_plug_syncing))
    } else {
        Text(pluralStringResource(R.plurals.agenda_plug_found, cals.size, a?.address?.ifBlank { a.label }.orEmpty(), cals.size), style = MaterialTheme.typography.bodyMedium)
        for (c in cals) {
            Row(
                Modifier.fillMaxWidth().toggleable(!c.hidden, role = Role.Checkbox) { on -> vm.saveCalendar(c.key, mapOf("hidden" to !on)) }.padding(vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                ColorCheck(colorOf(c), !c.hidden)
                Spacer(Modifier.width(12.dp))
                Text(c.name, modifier = Modifier.weight(1f))
                if (!c.writable) Text(stringResource(R.string.agenda_read_only), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
    Button(onClick = vm::plugDone, modifier = Modifier.fillMaxWidth()) {
        MIcon(R.drawable.ic_m_check, null, size = 18.dp)
        Spacer(Modifier.width(8.dp))
        Text(stringResource(R.string.agenda_done))
    }
    Text(stringResource(R.string.agenda_plug_yours), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}
