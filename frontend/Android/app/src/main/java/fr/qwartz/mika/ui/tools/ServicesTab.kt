package fr.qwartz.mika.ui.tools

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.tools.ServiceRow
import fr.qwartz.mika.data.moi.tools.ServiceTarget
import fr.qwartz.mika.data.moi.tools.resourcesOf
import fr.qwartz.mika.data.moi.tools.serviceIcon
import fr.qwartz.mika.data.moi.tools.servicePurpose
import fr.qwartz.mika.data.moi.tools.serviceRows
import fr.qwartz.mika.data.moi.tools.serviceState
import fr.qwartz.mika.data.moi.tools.serviceTarget
import fr.qwartz.mika.data.moi.tools.serviceTitle
import fr.qwartz.mika.data.moi.tools.serviceTools
import fr.qwartz.mika.data.moi.tools.serviceWhose
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.settings.SettingsPages
import fr.qwartz.mika.ui.settings.settingsPage
import fr.qwartz.mika.ui.shell.ChatCue
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaLine
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.said

/**
 * Services : ceux qui lui sont ouverts pour toi — le web, les tiens, ceux de l'opératrice, ceux qu'on te partage, même
 * quand aucune case ne t'en ouvre encore —, leur état, à qui ils sont, à quoi ils lui servent, combien de leurs outils
 * sont pour toi. Un des tiens, ou qu'on te partage, mène à sa page de Paramètres ; un service de Mika ou une app, à ses
 * droits.
 */
@Composable
internal fun ServicesTab(vm: ToolsViewModel, modifier: Modifier, onRights: (String) -> Unit) {
    val shell = LocalShell.current
    PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = modifier) {
        LoadBox(vm.rights, onRetry = vm::retry) { rights ->
            val services = vm.services
            val rows = remember(rights, services) {
                serviceRows(resourcesOf(rights, services), services?.items.orEmpty(), services?.received.orEmpty())
            }
            val error = vm.servicesError
            val unread = when {
                services == null && error != null -> stringResource(R.string.tools_services_unread, error.said.trimEnd('.'))
                services?.plugged == false -> stringResource(R.string.tools_services_unplugged)
                else -> null
            }
            LazyColumn(Modifier.fillMaxSize()) {
                if (unread != null) {
                    item(key = "unread") {
                        NoteBox(unread, R.drawable.ic_m_info, Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp), tone = Tone.WARN)
                    }
                }
                if (rows.isEmpty()) {
                    item(key = "none") {
                        Notice(stringResource(R.string.tools_services_none) + "\n\n" + stringResource(R.string.tools_services_none_help), Modifier.padding(top = 32.dp))
                    }
                }
                items(rows, key = { it.key }) { row ->
                    ServiceLine(row) {
                        when (val target = serviceTarget(row)) {
                            is ServiceTarget.Settings -> shell.navigate(settingsPage(SettingsPages.SERVICE, target.name))
                            is ServiceTarget.Rights -> onRights(target.key)
                            ServiceTarget.None -> Unit
                        }
                    }
                }
                item(key = "note") {
                    Text(
                        stringResource(R.string.tools_services_note),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.primary,
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable { shell.navigate(settingsPage(SettingsPages.SERVICES)) }
                            .padding(horizontal = 20.dp, vertical = 16.dp),
                    )
                }
            }
        }
    }
}

/** Une ligne de « Services » (`.li` de la maquette) : son icône, son nom, à qui il est et son but, ses outils pour toi,
 *  et son état. */
@Composable
private fun ServiceLine(row: ServiceRow, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val clickable = if (serviceTarget(row) != ServiceTarget.None) Modifier.clickable(onClick = onClick) else Modifier
    Row(Modifier.fillMaxWidth().then(clickable).padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(scheme.surfaceContainerHigh), contentAlignment = Alignment.Center) {
            MIcon(toolIcon(serviceIcon(row)), null, tint = scheme.onSurfaceVariant)
        }
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Text(serviceTitle(row), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(serviceWhose(row), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            val purpose = servicePurpose(row)
            if (purpose.isNotBlank()) {
                Text(purpose, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            val tools = serviceTools(row)
            if (tools != null) {
                val counted = stringResource(R.string.tools_service_tools, tools.open, tools.total)
                val review = if (tools.review > 0) " · " + stringResource(R.string.tools_service_review, tools.review) else ""
                Text(counted + review, style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
            }
        }
        Spacer(Modifier.width(8.dp))
        val (tone, state) = serviceState(row)
        Tag(state, tone)
    }
}

/**
 * Accords : ce que dit la maquette — ses accords se décident dans le chat, une carte au-dessus du champ (combien
 * attendent, quand la socket en tient), le bouton vers le chat — et où se relit ce qu'elle prépare (Mail, Teams, avec
 * leurs pastilles). Aucune liste : aucune route ne rend l'historique des décisions.
 */
@Composable
internal fun AgreementsTab(graph: AppGraph, modifier: Modifier) {
    val shell = LocalShell.current
    val approvals by graph.approvals.state.collectAsStateWithLifecycle()
    val me by graph.me.me.collectAsStateWithLifecycle()
    // ceux qui attendent vraiment : ni expirés, ni décidés (la pastille du chat compte les mêmes) ; relus chaque minute
    val now = rememberNow()
    val waiting = ChatCue.open(approvals, now, graph.clock.elapsedMs())
    Column(modifier.verticalScroll(rememberScrollState()).padding(vertical = 12.dp)) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = MaterialTheme.colorScheme.surfaceContainerLow,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
        ) {
            Column(Modifier.padding(16.dp)) {
                Text(stringResource(R.string.tools_agreements_title), style = MaterialTheme.typography.titleMedium)
                Gap(6.dp)
                Text(stringResource(R.string.tools_agreements_text), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                if (waiting > 0) {
                    Gap(8.dp)
                    Text(
                        pluralStringResource(R.plurals.tools_agreements_waiting, waiting, waiting),
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
                Gap(12.dp)
                FilledTonalButton(onClick = { shell.open(Route.Chat) }) {
                    MIcon(R.drawable.ic_m_chat, null, size = 18.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.tools_agreements_open))
                }
            }
        }
        ListHead(stringResource(R.string.tools_agreements_prepared), pink = true)
        MikaLine(
            icon = R.drawable.ic_m_mail,
            title = stringResource(R.string.tools_agreements_mail),
            subtitle = stringResource(R.string.tools_agreements_mail_sub),
            count = me?.counts?.mail ?: 0,
            onClick = {
                shell.open(Route.Mail)
                shell.navigate(Route.MailDrafts)
            },
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
        )
        MikaLine(
            icon = R.drawable.ic_m_teams,
            title = stringResource(R.string.tools_agreements_teams),
            subtitle = stringResource(R.string.tools_agreements_teams_sub),
            count = me?.counts?.teams ?: 0,
            onClick = {
                shell.open(Route.Teams)
                shell.navigate(Route.TeamsReplies)
            },
            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
        )
    }
}
