package fr.qwartz.mika.ui.settings

import android.Manifest
import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.settings.Settings as AppSettings
import fr.qwartz.mika.data.settings.ThemeMode
import kotlinx.coroutines.launch

/** Les paramètres : le compte, l'arrière-plan, la batterie, les notifications, l'apparence, les données. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(graph: AppGraph, onBack: () -> Unit) {
    val settings by graph.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val session by graph.auth.session.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    var confirmClear by rememberSaveable { mutableStateOf(false) }
    var unrestricted by remember { mutableStateOf(isUnrestricted(context)) }
    var notifications by remember { mutableStateOf(notificationsEnabled(context)) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        unrestricted = isUnrestricted(context)
        notifications = notificationsEnabled(context)
    }
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        notifications = notificationsEnabled(context)
        scope.launch { graph.settings.setNotificationsAsked() }
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

            Section(stringResource(R.string.settings_background))
            SwitchRow(
                title = stringResource(R.string.settings_background_title),
                summary = stringResource(R.string.settings_background_summary),
                checked = settings.background,
                onChange = { on -> scope.launch { graph.settings.setBackground(on) } },
            )
            SwitchRow(
                title = stringResource(R.string.settings_boot_title),
                summary = stringResource(R.string.settings_boot_summary),
                checked = settings.startOnBoot && settings.background,
                enabled = settings.background,
                onChange = { on -> scope.launch { graph.settings.setStartOnBoot(on) } },
            )
            InfoRow(
                title = stringResource(R.string.settings_battery_title),
                summary = stringResource(
                    if (unrestricted) R.string.settings_battery_unrestricted else R.string.settings_battery_restricted,
                ),
                action = if (unrestricted) null else stringResource(R.string.settings_battery_action),
                onAction = { requestUnrestricted(context) },
            )

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
            SwitchRow(
                title = stringResource(R.string.settings_reads_title),
                summary = stringResource(R.string.settings_reads_summary),
                checked = settings.shareReads,
                onChange = { on -> scope.launch { graph.settings.setShareReads(on) } },
            )

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

private fun isUnrestricted(context: Context): Boolean =
    context.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(context.packageName) == true

private fun notificationsEnabled(context: Context): Boolean {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
    ) {
        return false
    }
    return androidx.core.app.NotificationManagerCompat.from(context).areNotificationsEnabled()
}

/**
 * « Ne pas restreindre Mika » : la demande directe, que seule une messagerie peut justifier — c'est le
 * cas ici, et elle n'est jamais faite d'office, seulement sur ce bouton. Si le téléphone ne la propose
 * pas, la liste des applications optimisées.
 */
@SuppressLint("BatteryLife")
private fun requestUnrestricted(context: Context) {
    val direct = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, "package:${context.packageName}".toUri())
    try {
        context.startActivity(direct)
    } catch (_: ActivityNotFoundException) {
        try {
            context.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        } catch (_: ActivityNotFoundException) {
        }
    }
}

private fun openNotificationSettings(context: Context) {
    val intent = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName)
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
    }
}
