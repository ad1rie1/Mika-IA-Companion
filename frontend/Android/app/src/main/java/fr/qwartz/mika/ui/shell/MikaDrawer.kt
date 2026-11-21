package fr.qwartz.mika.ui.shell

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Badge
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalDrawerSheet
import androidx.compose.material3.NavigationDrawerItem
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.Me
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.theme.mika

/** Une rubrique du tiroir : sa route, son icône, son nom, et ce qui y attend ta décision. */
private data class Destination(val route: Route, @param:DrawableRes val icon: Int, val label: Int, val count: (Me?) -> Int = { 0 })

private val DESTINATIONS = listOf(
    Destination(Route.Chat, R.drawable.ic_m_chat, R.string.nav_chat),
    // juste après la conversation, à la place que la maquette du web lui donne (ADR 0296) : ce qui t'attend dans tes projets
    Destination(Route.Projects(), R.drawable.ic_m_flag, R.string.nav_projects) { it?.counts?.projects ?: 0 },
    Destination(Route.Mail, R.drawable.ic_m_mail, R.string.nav_mail) { it?.counts?.mail ?: 0 },
    Destination(Route.Teams, R.drawable.ic_m_teams, R.string.nav_teams) { it?.counts?.teams ?: 0 },
    Destination(Route.Carte(), R.drawable.ic_m_map, R.string.nav_map),
    Destination(Route.Phone(), R.drawable.ic_m_phone, R.string.nav_phone) { it?.counts?.phone ?: 0 },
    Destination(Route.Tools(), R.drawable.ic_m_tools, R.string.nav_tools),
    Destination(Route.Settings, R.drawable.ic_m_settings, R.string.nav_settings),
)

/** La rubrique d'une route, comparée par sa sorte (un autre onglet de la Carte reste la Carte). */
private fun Route.sameSection(other: Route): Boolean = this::class == other::class

/**
 * Le tiroir (ADR 0235, la variante choisie sur la maquette) : Mika en haut (vers « Ce qu'elle fait »), « Rechercher
 * partout », les rubriques et ce qui y attend, puis ton compte et « Se déconnecter ». [chatCue] : un point rose sur
 * « Chat » (un accord y attend, ou elle y a écrit depuis ton dernier lu), posé par le cadre hors du chat seulement.
 */
@Composable
fun MikaDrawerSheet(
    section: Route,
    me: Me?,
    status: String,
    chatCue: Boolean,
    onOpen: (Route) -> Unit,
    onMind: () -> Unit,
    onSearch: () -> Unit,
    onAccount: () -> Unit,
    onLogout: () -> Unit,
) {
    val pink = mika
    ModalDrawerSheet {
        Column(Modifier.verticalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 12.dp)) {
            Surface(
                shape = RoundedCornerShape(20.dp),
                color = pink.soft,
                border = BorderStroke(1.dp, pink.line),
                modifier = Modifier.fillMaxWidth().clickable(onClick = onMind),
            ) {
                Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                    MikaFace(48.dp)
                    Spacer(Modifier.width(14.dp))
                    Column(Modifier.weight(1f)) {
                        Text(stringResource(R.string.mika), style = MaterialTheme.typography.titleMedium)
                        Text(
                            status,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            maxLines = 2,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            }
            Spacer(Modifier.height(10.dp))
            Surface(
                shape = RoundedCornerShape(28.dp),
                color = MaterialTheme.colorScheme.surfaceContainerHigh,
                modifier = Modifier.fillMaxWidth().height(48.dp).clickable(onClick = onSearch),
            ) {
                Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_search, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(12.dp))
                    Text(stringResource(R.string.drawer_search), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Spacer(Modifier.height(8.dp))
            val waiting = stringResource(R.string.nav_chat_waiting)
            for (d in DESTINATIONS) {
                val n = d.count(me)
                NavigationDrawerItem(
                    label = { Text(stringResource(d.label)) },
                    icon = { MIcon(d.icon, null) },
                    selected = section.sameSection(d.route),
                    onClick = { onOpen(d.route) },
                    badge = when {
                        n > 0 -> {
                            { Badge(containerColor = if (d.route is Route.Phone) pink.fill else MaterialTheme.colorScheme.primary) { Text("$n") } }
                        }
                        d.route == Route.Chat && chatCue -> {
                            { Badge(containerColor = pink.fill, modifier = Modifier.semantics { contentDescription = waiting }) }
                        }
                        else -> null
                    },
                )
            }
            HorizontalDivider(Modifier.padding(horizontal = 16.dp, vertical = 12.dp))
            Text(
                stringResource(R.string.drawer_account),
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 16.dp, bottom = 4.dp),
            )
            NavigationDrawerItem(
                label = {
                    Column {
                        Text(me?.shown ?: "…")
                        val role = when {
                            me == null -> ""
                            me.owner && me.operator -> stringResource(R.string.drawer_role_owner_operator)
                            me.owner -> stringResource(R.string.drawer_role_owner)
                            me.operator -> stringResource(R.string.drawer_role_operator)
                            else -> ""
                        }
                        if (role.isNotEmpty()) {
                            Text(role, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                },
                icon = { MIcon(R.drawable.ic_m_user, null) },
                selected = false,
                onClick = onAccount,
            )
            NavigationDrawerItem(
                label = { Text(stringResource(R.string.menu_logout)) },
                icon = { MIcon(R.drawable.ic_m_logout, null) },
                selected = false,
                onClick = onLogout,
            )
        }
    }
}
