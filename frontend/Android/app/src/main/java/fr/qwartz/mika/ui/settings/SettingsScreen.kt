package fr.qwartz.mika.ui.settings

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.ComponentName
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.text.format.DateUtils
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.core.LocationMonitor
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.phone.PhoneStatus
import fr.qwartz.mika.data.push.PushState
import fr.qwartz.mika.data.settings.Settings as AppSettings
import fr.qwartz.mika.data.settings.ThemeMode
import fr.qwartz.mika.service.PhoneListenerService
import kotlinx.coroutines.launch
import java.text.DateFormat

/**
 * Les paramètres : le compte, les notifications (et si elles arrivent app fermée, par Firebase), la position (« Lui
 * dire où je suis », ADR 0119), ses messages (« Lui montrer mes messages », ADR 0120), l'apparence, les données. Il n'y
 * a plus de connexion en arrière-plan à régler (ADR 0077) : l'app ne se connecte qu'ouverte.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(graph: AppGraph, onBack: () -> Unit) {
    val settings by graph.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val session by graph.auth.session.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    var confirmClear by rememberSaveable { mutableStateOf(false) }
    var notifications by remember { mutableStateOf(notificationsEnabled(context)) }
    val push by graph.push.state.collectAsStateWithLifecycle()
    // La localisation peut être retirée (ou donnée) dans les réglages du téléphone : revue à chaque retour.
    var locationGranted by remember { mutableStateOf(LocationMonitor.permitted(context)) }
    var locationRefused by rememberSaveable { mutableStateOf(false) }
    // L'accès aux notifications (ADR 0120) se donne et se retire dans les réglages d'Android : revu à chaque retour. Parti
    // le donner depuis ici ([phoneWanted]), l'interrupteur s'allume au retour s'il a été accordé.
    var phoneGranted by remember { mutableStateOf(PhoneListenerService.granted(context)) }
    var phoneWanted by rememberSaveable { mutableStateOf(false) }
    val phoneStatus by graph.phone.status.collectAsStateWithLifecycle()
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        notifications = notificationsEnabled(context)
        locationGranted = LocationMonitor.permitted(context)
        if (locationGranted) locationRefused = false
        phoneGranted = PhoneListenerService.granted(context)
        if (phoneWanted && phoneGranted) {
            phoneWanted = false
            scope.launch { graph.settings.setPhoneShare(true) }
        }
    }
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        notifications = notificationsEnabled(context)
        scope.launch { graph.settings.setNotificationsAsked() }
    }
    // Précise ou approximative (Android 12 et plus laisse choisir) : l'une ou l'autre suffit pour l'allumer.
    val askLocation = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        locationGranted = result.values.any { it } || LocationMonitor.permitted(context)
        locationRefused = !locationGranted
        if (locationGranted) scope.launch { graph.settings.setShareWhere(true) }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text(stringResource(R.string.menu_settings)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(painterResource(R.drawable.ic_arrow_back), stringResource(R.string.back))
                    }
                },
            )
        },
    ) { padding ->
        Column(
            Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(bottom = 24.dp),
        ) {
            val profile = (session as? Session.LoggedIn)?.profile
            val base = (session as? Session.LoggedIn)?.base
            Section(stringResource(R.string.settings_account))
            Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    profile?.displayName?.ifBlank { profile.username } ?: settings.username,
                    style = MaterialTheme.typography.titleMedium,
                )
                base?.let { Text(it.canonical, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                OutlinedButton(onClick = { confirmLogout = true }, modifier = Modifier.padding(top = 8.dp)) {
                    Text(stringResource(R.string.menu_logout))
                }
            }

            Section(stringResource(R.string.settings_notifications))
            InfoRow(
                title = stringResource(R.string.settings_notifications_title),
                summary = stringResource(if (notifications) R.string.settings_notifications_on else R.string.settings_notifications_off),
                action = if (notifications) null else stringResource(R.string.notif_prompt_allow),
                onAction = {
                    val canAsk = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
                        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
                        PackageManager.PERMISSION_GRANTED &&
                        !settings.notificationsAsked
                    if (canAsk) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS) else openNotificationSettings(context)
                },
            )
            InfoRow(
                title = stringResource(R.string.settings_push_title),
                summary = when (val p = push) {
                    PushState.Active -> stringResource(R.string.settings_push_active)
                    PushState.Pending -> stringResource(R.string.settings_push_pending)
                    PushState.ServerWithoutKey -> stringResource(R.string.settings_push_server_without_key)
                    PushState.Unavailable -> stringResource(R.string.settings_push_unavailable)
                    PushState.LoggedOut -> stringResource(R.string.settings_push_pending)
                    is PushState.Failed -> p.reason
                },
                action = when (push) {
                    PushState.Pending, PushState.ServerWithoutKey, is PushState.Failed -> stringResource(R.string.settings_push_retry)
                    else -> null
                },
                onAction = { scope.launch { graph.push.sync(force = true) } },
            )
            SwitchRow(
                title = stringResource(R.string.settings_reads_title),
                summary = stringResource(R.string.settings_reads_summary),
                checked = settings.shareReads,
                onChange = { on -> scope.launch { graph.settings.setShareReads(on) } },
            )

            Section(stringResource(R.string.settings_where))
            SwitchRow(
                title = stringResource(R.string.settings_where_title),
                // allumé mais l'autorisation retirée : rien ne part, et le dire
                summary = stringResource(
                    if (settings.shareWhere && !locationGranted) R.string.settings_where_revoked else R.string.settings_where_summary,
                ),
                checked = settings.shareWhere && locationGranted,
                onChange = { on ->
                    when {
                        !on -> scope.launch { graph.settings.setShareWhere(false) }
                        locationGranted -> scope.launch { graph.settings.setShareWhere(true) }
                        else -> askLocation.launch(
                            arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION),
                        )
                    }
                },
            )
            if (locationRefused && !locationGranted) {
                // Refusée deux fois, Android ne redemande plus : seuls ses réglages peuvent la donner.
                InfoRow(
                    title = stringResource(R.string.settings_where_refused_title),
                    summary = stringResource(R.string.settings_where_refused),
                    action = stringResource(R.string.settings_where_open_settings),
                    onAction = { openAppSettings(context) },
                )
            }

            Section(stringResource(R.string.settings_phone))
            SwitchRow(
                title = stringResource(R.string.settings_phone_title),
                // allumé mais l'accès retiré : rien ne part, et le dire
                summary = stringResource(
                    if (settings.phoneShare && !phoneGranted) R.string.settings_phone_revoked else R.string.settings_phone_summary,
                ),
                checked = settings.phoneShare && phoneGranted,
                enabled = phoneGranted || settings.phoneShare,
                onChange = { on -> scope.launch { graph.settings.setPhoneShare(on && phoneGranted) } },
            )
            if (!phoneGranted) {
                InfoRow(
                    title = stringResource(R.string.settings_phone_access_title),
                    summary = stringResource(R.string.settings_phone_access),
                    action = stringResource(R.string.settings_phone_access_open),
                    onAction = {
                        phoneWanted = true
                        openListenerSettings(context)
                    },
                )
            } else if (settings.phoneShare) {
                CheckRow(
                    title = stringResource(R.string.settings_phone_whatsapp),
                    summary = stringResource(R.string.settings_phone_whatsapp_summary),
                    checked = settings.phoneWhatsApp,
                    onChange = { on -> scope.launch { graph.settings.setPhoneWhatsApp(on) } },
                )
                CheckRow(
                    title = stringResource(R.string.settings_phone_messages),
                    summary = stringResource(R.string.settings_phone_messages_summary),
                    checked = settings.phoneMessages,
                    onChange = { on -> scope.launch { graph.settings.setPhoneMessages(on) } },
                )
                CheckRow(
                    title = stringResource(R.string.settings_phone_groups),
                    summary = stringResource(R.string.settings_phone_groups_summary),
                    checked = settings.phoneGroups,
                    onChange = { on -> scope.launch { graph.settings.setPhoneGroups(on) } },
                )
                InfoRow(
                    title = stringResource(R.string.settings_phone_state_title),
                    summary = phoneStateText(phoneStatus),
                    action = null,
                    onAction = {},
                )
            }

            Section(stringResource(R.string.settings_appearance))
            Column(Modifier.selectableGroup()) {
                ThemeRow(R.string.settings_theme_system, settings.theme == ThemeMode.SYSTEM) {
                    scope.launch { graph.settings.setTheme(ThemeMode.SYSTEM) }
                }
                ThemeRow(R.string.settings_theme_light, settings.theme == ThemeMode.LIGHT) {
                    scope.launch { graph.settings.setTheme(ThemeMode.LIGHT) }
                }
                ThemeRow(R.string.settings_theme_dark, settings.theme == ThemeMode.DARK) {
                    scope.launch { graph.settings.setTheme(ThemeMode.DARK) }
                }
            }
            // Sans portraits dans cette version de l'app, l'interrupteur dirait une chose qu'il ne peut pas faire.
            val portraits by produceState(false) { value = graph.avatar.manifest() != null }
            if (portraits) {
                SwitchRow(
                    title = stringResource(R.string.settings_avatar),
                    summary = stringResource(R.string.settings_avatar_summary),
                    checked = settings.avatar,
                    onChange = { on -> scope.launch { graph.settings.setAvatar(on) } },
                )
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                SwitchRow(
                    title = stringResource(R.string.settings_dynamic_color),
                    summary = stringResource(R.string.settings_dynamic_color_summary),
                    checked = settings.dynamicColor,
                    onChange = { on -> scope.launch { graph.settings.setDynamicColor(on) } },
                )
            }

            Section(stringResource(R.string.settings_data))
            InfoRow(
                title = stringResource(R.string.settings_clear_title),
                summary = stringResource(R.string.settings_clear_summary),
                action = stringResource(R.string.settings_clear_action),
                onAction = { confirmClear = true },
            )
        }
    }

    if (confirmLogout) {
        ConfirmDialog(
            title = stringResource(R.string.logout_confirm_title),
            text = stringResource(R.string.logout_confirm_text),
            confirm = stringResource(R.string.menu_logout),
            onConfirm = {
                confirmLogout = false
                scope.launch { graph.auth.logout() }
            },
            onDismiss = { confirmLogout = false },
        )
    }
    if (confirmClear) {
        ConfirmDialog(
            title = stringResource(R.string.settings_clear_confirm_title),
            text = stringResource(R.string.settings_clear_confirm_text),
            confirm = stringResource(R.string.settings_clear_action),
            onConfirm = {
                confirmClear = false
                scope.launch { graph.clearLocalMessages() }
            },
            onDismiss = { confirmClear = false },
        )
    }
}

@Composable
private fun Section(title: String) {
    HorizontalDivider(Modifier.padding(top = 16.dp))
    Text(
        title,
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 12.dp).semantics { heading() },
    )
}

@Composable
private fun SwitchRow(title: String, summary: String, checked: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true) {
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onChange)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f).padding(end = 16.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(summary, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        // Le rang entier est l'interrupteur : le Switch lui-même ne capte rien.
        Switch(checked = checked, onCheckedChange = null, enabled = enabled)
    }
}

@Composable
private fun CheckRow(title: String, summary: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .toggleable(value = checked, role = Role.Checkbox, onValueChange = onChange)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Le rang entier est la case : la Checkbox elle-même ne capte rien.
        Checkbox(checked = checked, onCheckedChange = null)
        Column(Modifier.weight(1f).padding(start = 16.dp)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(summary, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Où en sont ses messages (ADR 0120) : refusés par le serveur, serveur trop ancien, en attente, ou tout est parti. */
@Composable
private fun phoneStateText(status: PhoneStatus): String = when {
    status.refused -> stringResource(R.string.settings_phone_state_refused)
    status.outdated -> stringResource(R.string.settings_phone_state_outdated)
    status.queued > 0 -> pluralStringResource(R.plurals.settings_phone_state_queued, status.queued, status.queued)
    status.sentAt > 0 -> stringResource(
        R.string.settings_phone_state_sent,
        DateUtils.formatSameDayTime(status.sentAt, System.currentTimeMillis(), DateFormat.SHORT, DateFormat.SHORT).toString(),
    )
    else -> stringResource(R.string.settings_phone_state_empty)
}

@Composable
private fun InfoRow(title: String, summary: String, action: String?, onAction: () -> Unit) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(title, style = MaterialTheme.typography.bodyLarge)
        Text(summary, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (action != null) {
            OutlinedButton(onClick = onAction, modifier = Modifier.padding(top = 8.dp)) { Text(action) }
        }
    }
}

@Composable
private fun ThemeRow(label: Int, selected: Boolean, onSelect: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 48.dp)
            .selectable(selected = selected, role = Role.RadioButton, onClick = onSelect)
            .padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        RadioButton(selected = selected, onClick = null)
        Text(stringResource(label), modifier = Modifier.padding(start = 16.dp))
    }
}

@Composable
private fun ConfirmDialog(title: String, text: String, confirm: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = { TextButton(onClick = onConfirm) { Text(confirm) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

private fun notificationsEnabled(context: Context): Boolean {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
    ) {
        return false
    }
    return androidx.core.app.NotificationManagerCompat.from(context).areNotificationsEnabled()
}

/** La fiche de l'app dans les réglages du téléphone, où se donnent les autorisations qu'Android ne redemande plus. */
private fun openAppSettings(context: Context) {
    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
    }
}

/**
 * L'accès aux notifications de cette app dans les réglages d'Android (ADR 0120) : sa page à elle quand Android la connaît
 * (11 et plus), sinon la liste des lecteurs.
 */
private fun openListenerSettings(context: Context) {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        val detail = Intent(Settings.ACTION_NOTIFICATION_LISTENER_DETAIL_SETTINGS).putExtra(
            Settings.EXTRA_NOTIFICATION_LISTENER_COMPONENT_NAME,
            ComponentName(context, PhoneListenerService::class.java).flattenToString(),
        )
        try {
            context.startActivity(detail)
            return
        } catch (_: ActivityNotFoundException) {
        }
    }
    try {
        context.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS))
    } catch (_: ActivityNotFoundException) {
    }
}

private fun openNotificationSettings(context: Context) {
    val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
    }
}
