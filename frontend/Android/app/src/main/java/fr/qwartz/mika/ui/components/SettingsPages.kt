package fr.qwartz.mika.ui.components

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.settings.GivenShare
import fr.qwartz.mika.data.moi.settings.shareWords
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.MIcon

/*
 * Les pages de Paramètres et ce qui y mène, depuis n'importe quel écran : leurs noms (`Route.SettingsPage.page`), la
 * page des partages ouverte sur une ressource, le groupe « Partager » d'une boîte ou d'un compte Teams. L'écran
 * Paramètres (`ui/settings/SettingsScreen.kt`) aiguille chaque nom vers sa page, qui vit dans le paquet de son domaine.
 */

/** Les pages de Paramètres (`Route.SettingsPage.page`) ; une clé ([Route.SettingsPage.key]) dit ce qu'elles règlent. */
object SettingsPages {
    const val ACCOUNT = "compte"
    const val BOXES = "boites"
    /** Une boîte ; clé vide : une boîte nouvelle. */
    const val BOX = "boite"
    const val TEAMS = "teams"
    /** Un compte Teams ; clé vide : un compte nouveau. */
    const val TEAMS_ACCOUNT = "compte-teams"
    const val PHONES = "telephones"
    /** Ses partages ; clé `<sorte>:<clé>` : la fenêtre « Partager » s'ouvre sur cette ressource. */
    const val SHARES = "partages"
    const val SERVICES = "mcp"
    /** Un service ; nom vide : en brancher un. */
    const val SERVICE = "service"
    const val NOTIFICATIONS = "notifications"
    const val POSITION = "position"
    const val MESSAGES = "messages"
    const val APPEARANCE = "apparence"
    const val DATA = "donnees"
    /** Paramètres › Agendas (ADR 0309) : ses comptes ; un compte (clé : le compte) ; un agenda (clé : l'agenda) ;
     *  « Brancher un agenda » (clé vide, une sorte, ou `<sorte>/<compte>` pour se reconnecter). */
    const val AGENDAS = "agendas"
    const val AGENDA_ACCOUNT = "compte-agenda"
    const val AGENDA_CALENDAR = "agenda"
    const val AGENDA_PLUG = "brancher-agenda"
}

/** Une page de Paramètres, par-dessus la racine. */
internal fun settingsPage(page: String, key: String = ""): Route = Route.SettingsPage(page, key)

/** Partager cette ressource : la page des partages, sa fenêtre ouverte sur elle. */
internal fun shareRoute(kind: String, key: String): Route = settingsPage(SettingsPages.SHARES, "$kind:$key")

/** Avec qui une ressource est partagée, et « Partager… ». */
@Composable
internal fun SharedWithGroup(given: List<GivenShare>, onShare: () -> Unit) {
    SetHead(stringResource(R.string.settings_share_group))
    SetGroup {
        SetItem(
            R.drawable.ic_m_users,
            if (given.isEmpty()) stringResource(R.string.settings_share_nobody) else given.joinToString(", ") { "${it.name} · ${shareWords(it.level).lowercase()}" },
            stringResource(R.string.settings_share_help),
            onClick = onShare,
        ) { MIcon(R.drawable.ic_m_chev_right, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}
