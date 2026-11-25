package fr.qwartz.mika.ui.chat

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.mail.MailRow
import fr.qwartz.mika.data.moi.teams.Conversation
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.isTopLevel
import fr.qwartz.mika.ui.mail.mailApi
import fr.qwartz.mika.ui.components.SettingsPages
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SearchBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.teams.teamsApi
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.launch
import java.time.ZoneId

/**
 * Ce que le serveur rend pour une recherche ([query] : le texte qu'elle cherchait ; [error] : un refus en mots).
 * Montré seulement s'il répond au texte d'aujourd'hui.
 */
data class RemoteHits<T>(val query: String = "", val loading: Boolean = false, val items: List<T> = emptyList(), val error: String? = null)

/**
 * Les mails et les discussions Teams cherchés au serveur (`mail/messages?q=`, `teams/conversations?q=`), après une
 * pause de frappe ([SearchRules.DEBOUNCE_MS]) et pas à chaque lettre ; une recherche qui n'est plus voulue s'abandonne.
 * Un par session.
 */
@OptIn(FlowPreview::class)
class SearchViewModel(private val graph: AppGraph) : ViewModel() {
    var mail by mutableStateOf(RemoteHits<MailRow>())
        private set
    var teams by mutableStateOf(RemoteHits<Conversation>())
        private set
    private val wanted = MutableStateFlow<Pair<String?, SearchChip>>(null to SearchChip.ALL)

    init {
        viewModelScope.launch {
            wanted.debounce(SearchRules.DEBOUNCE_MS).collectLatest { (q, chip) ->
                coroutineScope {
                    launch { searchMail(q.takeIf { SearchRules.showsMail(chip) }) }
                    launch { searchTeams(q.takeIf { SearchRules.showsTeams(chip) }) }
                }
            }
        }
    }

    /** Ce que la personne cherche, à chaque frappe : la recherche au serveur part après la pause. */
    fun want(query: String, chip: SearchChip) {
        val q = SearchRules.remoteQuery(query)
        wanted.value = q to chip
        // ce qui sera cherché se dit tout de suite (sans montrer ce qui répondait à un autre texte)
        if (q != null && SearchRules.showsMail(chip) && mail.query != q) mail = RemoteHits(q, loading = true)
        if (q != null && SearchRules.showsTeams(chip) && teams.query != q) teams = RemoteHits(q, loading = true)
    }

    private suspend fun searchMail(q: String?) {
        if (q == null) {
            mail = RemoteHits()
            return
        }
        if (mail.query == q && !mail.loading && mail.error == null) return
        mail = mail.copy(query = q, loading = true)
        mail = when (val r = graph.mailApi().messages(mapOf("q" to q, "size" to SearchRules.REMOTE_SIZE.toString()))) {
            is MoiApi.Result.Ok -> RemoteHits(q, items = r.value.items)
            is MoiApi.Result.Failed -> RemoteHits(q, error = r.error.said)
        }
    }

    private suspend fun searchTeams(q: String?) {
        if (q == null) {
            teams = RemoteHits()
            return
        }
        if (teams.query == q && !teams.loading && teams.error == null) return
        teams = teams.copy(query = q, loading = true)
        teams = when (val r = graph.teamsApi().conversations(q = q, size = SearchRules.REMOTE_SIZE)) {
            is MoiApi.Result.Ok -> RemoteHits(q, items = r.value)
            is MoiApi.Result.Failed -> RemoteHits(q, error = r.error.said)
        }
    }
}

/**
 * « Rechercher » (`Route.Search`) : un champ en haut, des puces (Tout, Conversation, Mail, Teams, Écrans), les
 * résultats groupés — les messages gardés sur ce téléphone et ses fils de travail, les mails et les discussions Teams
 * (au serveur, après une pause de frappe), les écrans et pages de l'app. Toucher un résultat ouvre son écran ; un
 * message ramène au chat sur lui, surligné un instant. [scope] `chat` : depuis la loupe du chat, la conversation d'abord.
 */
@Composable
fun SearchScreen(graph: AppGraph, scope: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: SearchViewModel = viewModel(key = "search|$session") { SearchViewModel(graph) }
    val chat = rememberChatModel(graph)
    var query by rememberSaveable { mutableStateOf("") }
    var chip by rememberSaveable { mutableStateOf(SearchRules.chipFor(scope)) }
    LaunchedEffect(query, chip) { vm.want(query, chip) }

    val messages by graph.chat.observe().collectAsStateWithLifecycle(emptyList())
    val strands by chat.strands.collectAsStateWithLifecycle()
    val operator by chat.operator.collectAsStateWithLifecycle()
    val zone = remember { ZoneId.systemDefault() }
    val now = graph.clock.wallMs()
    val screens = screenCatalog()

    val q = SearchRules.fold(query)
    val (chatHits, strandMessageHits) = remember(messages, q, operator) { SearchRules.messages(messages, query, operator) }
    val strandHits = if (operator && SearchRules.showsChat(chip)) SearchRules.strands(strands, query) else emptyList()
    val screenHits = if (SearchRules.showsScreens(chip)) SearchRules.screens(screens, query) else emptyList()
    val remote = SearchRules.remoteQuery(query)
    val mail = vm.mail.takeIf { SearchRules.showsMail(chip) && remote != null && it.query == remote }
    val teams = vm.teams.takeIf { SearchRules.showsTeams(chip) && remote != null && it.query == remote }

    fun goTo(e: ScreenEntry) {
        when {
            e.route == Route.Chat -> shell.open(Route.Chat)
            e.route.isTopLevel -> shell.open(e.route)
            e.parent != null -> {
                shell.open(e.parent)
                shell.navigate(e.route)
            }
            else -> shell.navigate(e.route)
        }
    }

    SectionScaffold(
        topBar = {
            SearchBar(
                query,
                stringResource(if (chip == SearchChip.CHAT) R.string.search_hint_chat else R.string.search_hint),
                onQuery = { query = it },
                onClose = shell.back,
            )
        },
    ) { modifier ->
        Column(modifier.imePadding()) {
            Chips(chip) { chip = it }
            LazyColumn(Modifier.fillMaxWidth().weight(1f)) {
                if (q.isEmpty()) {
                    item(key = "idle") {
                        Hint(
                            stringResource(
                                when (chip) {
                                    SearchChip.CHAT -> R.string.search_idle_chat
                                    SearchChip.MAIL -> R.string.search_idle_mail
                                    SearchChip.TEAMS -> R.string.search_idle_teams
                                    else -> R.string.search_idle
                                },
                            ),
                        )
                    }
                }
                if (SearchRules.showsChat(chip) && chatHits.isNotEmpty()) {
                    item(key = "h-chat") { ListHead(stringResource(R.string.search_group_chat)) }
                    items(chatHits, key = { "c" + ChatItems.keyOf(it.message) }) { hit ->
                        MessageRow(hit, q, zone, now, strandName = null) {
                            chat.showMessage(hit.message)
                            shell.open(Route.Chat)
                        }
                    }
                }
                val strandsShown = SearchRules.showsChat(chip) && (strandHits.isNotEmpty() || strandMessageHits.isNotEmpty())
                if (strandsShown) {
                    item(key = "h-strands") { ListHead(stringResource(R.string.search_group_strands)) }
                    items(strandHits, key = { "s" + it.strand.id }) { hit ->
                        ResultRow(
                            lead = { Lead(R.drawable.ic_m_threads) },
                            title = AnnotatedString(hit.title.ifEmpty { stringResource(R.string.search_strand_untitled) }),
                            sub = hit.sub,
                            side = MoiDates.short(hit.strand.lastAt, now, zone),
                        ) {
                            chat.showStrand(hit.strand.id)
                            shell.open(Route.Chat)
                        }
                    }
                    items(strandMessageHits, key = { "f" + ChatItems.keyOf(it.message) }) { hit ->
                        val name = strands.firstOrNull { it.id == hit.strand }?.let { fr.qwartz.mika.data.chat.Strands.label(it) }
                        MessageRow(hit, q, zone, now, strandName = name ?: stringResource(R.string.search_strand_untitled)) {
                            chat.showMessage(hit.message)
                            shell.open(Route.Chat)
                        }
                    }
                }
                if (mail != null) remoteGroup(R.string.search_group_mail, "mail", mail) { row ->
                    ResultRow(
                        lead = { PersonAvatar(row.from.shown, row.from.address) },
                        title = highlighted(listOf(row.from.shown, row.subject.ifBlank { null } ?: stringResource(R.string.search_no_subject)).joinToString(" · "), q),
                        sub = row.snippet,
                        side = MoiDates.short(row.date, now, zone),
                    ) { shell.navigate(Route.MailMessage(row.ref)) }
                }
                if (teams != null) remoteGroup(R.string.search_group_teams, "teams", teams) { c ->
                    val title = c.title.ifBlank { stringResource(R.string.search_untitled_teams) }
                    ResultRow(
                        lead = { PersonAvatar(title, c.key) },
                        title = highlighted(title, q),
                        sub = c.last?.text.orEmpty(),
                        side = MoiDates.short(c.lastAt, now, zone),
                    ) { shell.navigate(Route.TeamsThread(c.key)) }
                }
                if (screenHits.isNotEmpty()) {
                    item(key = "h-screens") { ListHead(stringResource(R.string.search_group_screens)) }
                    items(screenHits, key = { "e" + it.title }) { e ->
                        ResultRow(lead = { Lead(e.icon) }, title = highlighted(e.title, q), sub = e.sub, side = "") { goTo(e) }
                    }
                }
                val waiting = (mail?.loading == true) || (teams?.loading == true)
                val shortQuery = q.isNotEmpty() && remote == null && (SearchRules.showsMail(chip) || SearchRules.showsTeams(chip))
                if (shortQuery) item(key = "short") { Hint(stringResource(R.string.search_short)) }
                val nothing = q.isNotEmpty() && !waiting && chatHits.isEmpty() && !strandsShown && screenHits.isEmpty() &&
                    mail?.items.isNullOrEmpty() && teams?.items.isNullOrEmpty() && mail?.error == null && teams?.error == null
                if (nothing && !shortQuery) item(key = "nothing") { Hint(stringResource(R.string.search_nothing)) }
                if (chip == SearchChip.CHAT) {
                    item(key = "only") {
                        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                stringResource(R.string.search_chat_only),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.weight(1f),
                            )
                            TextButton(onClick = { chip = SearchChip.ALL }) { Text(stringResource(R.string.search_everywhere)) }
                        }
                    }
                }
            }
        }
    }
}

/** Les puces : où chercher. */
@Composable
private fun Chips(chip: SearchChip, onChip: (SearchChip) -> Unit) {
    val all = listOf(
        SearchChip.ALL to R.string.search_chip_all,
        SearchChip.CHAT to R.string.search_chip_chat,
        SearchChip.MAIL to R.string.search_chip_mail,
        SearchChip.TEAMS to R.string.search_chip_teams,
        SearchChip.SCREENS to R.string.search_chip_screens,
    )
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for ((c, label) in all) {
            FilterChip(selected = chip == c, onClick = { onChip(c) }, label = { Text(stringResource(label)) })
        }
    }
}

/** Un groupe cherché au serveur : sa tête, « Recherche… », un refus en mots, ou ses lignes. */
private fun <T> LazyListScope.remoteGroup(title: Int, key: String, hits: RemoteHits<T>, row: @Composable (T) -> Unit) {
    if (!hits.loading && hits.error == null && hits.items.isEmpty()) return
    item(key = "h-$key") { ListHead(stringResource(title)) }
    when {
        hits.loading && hits.items.isEmpty() -> item(key = "l-$key") {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(10.dp))
                Text(stringResource(R.string.search_loading), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        hits.error != null -> item(key = "e-$key") { Hint(hits.error) }
        else -> items(hits.items.size, key = { "$key$it" }) { i -> row(hits.items[i]) }
    }
}

/** Un message trouvé : qui l'a écrit, le passage trouvé, quand ; dans un fil de travail, lequel. */
@Composable
private fun MessageRow(hit: MessageHit, q: String, zone: ZoneId, now: Long, strandName: String?, onClick: () -> Unit) {
    val m = hit.message
    val hers = m.sender == Sender.MIKA
    val who = if (hers) stringResource(R.string.mika) else stringResource(R.string.search_you)
    val sub = listOfNotNull(who, strandName?.let { stringResource(R.string.search_in_strand, it) }).joinToString(" · ")
    ResultRow(
        lead = { if (hers) MikaFace(40.dp) else PersonAvatar(who, "toi") },
        title = highlighted(hit.title, q),
        sub = sub,
        side = MoiDates.short(m.ts, now, zone),
        twoLines = true,
        onClick = onClick,
    )
}

/** Une ligne de résultat : sa tête, ce qui est trouvé (surligné), une ligne dessous, l'heure au bout. */
@Composable
private fun ResultRow(
    lead: @Composable () -> Unit,
    title: AnnotatedString,
    sub: String,
    side: String,
    twoLines: Boolean = false,
    onClick: () -> Unit,
) {
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 56.dp)
            .clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        lead()
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = if (twoLines) 2 else 1, overflow = TextOverflow.Ellipsis)
            if (sub.isNotBlank()) {
                Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        if (side.isNotEmpty()) {
            Spacer(Modifier.width(8.dp))
            Text(side, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** L'icône d'un écran ou d'un fil, dans son carré. */
@Composable
private fun Lead(@DrawableRes icon: Int) {
    Box(
        Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(MaterialTheme.colorScheme.surfaceContainerHigh),
        contentAlignment = Alignment.Center,
    ) {
        MIcon(icon, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Hint(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
    )
}

/** Le texte, ce qu'on cherche ([q], déjà replié) surligné en rose. */
@Composable
private fun highlighted(text: String, q: String): AnnotatedString {
    val range = SearchRules.matchRange(text, q) ?: return AnnotatedString(text)
    val bg = mika.container
    val fg = mika.onContainer
    return buildAnnotatedString {
        append(text.substring(0, range.first))
        withStyle(SpanStyle(background = bg, color = fg, fontWeight = FontWeight.SemiBold)) { append(text.substring(range.first, range.last + 1)) }
        append(text.substring(range.last + 1))
    }
}

/**
 * Les écrans et pages de l'app que la recherche propose, dans l'ordre du tiroir : chaque rubrique, puis ses onglets et
 * ses pages (« Mail › Ses brouillons », « Paramètres › Boîtes mail »…). Une page s'ouvre sur sa rubrique ([ScreenEntry.parent]).
 */
@Composable
private fun screenCatalog(): List<ScreenEntry> {
    val mail = stringResource(R.string.nav_mail)
    val teams = stringResource(R.string.nav_teams)
    val map = stringResource(R.string.nav_map)
    val phone = stringResource(R.string.nav_phone)
    val tools = stringResource(R.string.nav_tools)
    val settings = stringResource(R.string.nav_settings)
    fun sub(parent: String, title: String) = "$parent › $title"
    val set = Route.Settings
    return listOf(
        ScreenEntry(stringResource(R.string.nav_chat), stringResource(R.string.search_sub_chat), Route.Chat, icon = R.drawable.ic_m_chat),
        ScreenEntry(stringResource(R.string.menu_status), stringResource(R.string.search_sub_mind), Route.Mind, icon = R.drawable.ic_m_sparkle),
        ScreenEntry(stringResource(R.string.files_title), stringResource(R.string.search_sub_files), Route.Files, icon = R.drawable.ic_m_folder),
        // Projets (ADR 0296) : la rubrique et ses deux volets
        ScreenEntry(stringResource(R.string.nav_projects), stringResource(R.string.proj_search_sub), Route.Projects(), icon = R.drawable.ic_m_flag),
        ScreenEntry(sub(stringResource(R.string.nav_projects), stringResource(R.string.proj_tab_todo)), "", Route.Projects("a-faire"), icon = R.drawable.ic_m_inbox),
        ScreenEntry(sub(stringResource(R.string.nav_projects), stringResource(R.string.proj_tab_projects)), "", Route.Projects("projets"), icon = R.drawable.ic_m_grid),
        ScreenEntry(mail, stringResource(R.string.search_sub_mail), Route.Mail, icon = R.drawable.ic_m_mail),
        ScreenEntry(sub(mail, stringResource(R.string.mail_her_drafts)), stringResource(R.string.search_sub_mail_drafts), Route.MailDrafts, parent = Route.Mail, icon = R.drawable.ic_m_pen),
        ScreenEntry(sub(mail, stringResource(R.string.search_screen_write)), stringResource(R.string.search_sub_mail_compose), Route.MailCompose(), parent = Route.Mail, icon = R.drawable.ic_m_pen),
        ScreenEntry(teams, stringResource(R.string.search_sub_teams), Route.Teams, icon = R.drawable.ic_m_teams),
        ScreenEntry(sub(teams, stringResource(R.string.teams_her_replies)), stringResource(R.string.search_sub_teams_replies), Route.TeamsReplies, parent = Route.Teams, icon = R.drawable.ic_m_pen),
        ScreenEntry(map, stringResource(R.string.search_sub_map), Route.Carte(), icon = R.drawable.ic_m_map),
        ScreenEntry(sub(map, stringResource(R.string.carte_tab_explorer)), "", Route.Carte("explorer"), icon = R.drawable.ic_m_search),
        ScreenEntry(sub(map, stringResource(R.string.carte_tab_events)), "", Route.Carte("evenements"), icon = R.drawable.ic_m_calendar),
        ScreenEntry(sub(map, stringResource(R.string.carte_tab_route)), "", Route.Carte("itineraire"), icon = R.drawable.ic_m_route),
        ScreenEntry(sub(map, stringResource(R.string.carte_tab_trips)), "", Route.Carte("voyages"), icon = R.drawable.ic_m_flag),
        ScreenEntry(phone, stringResource(R.string.search_sub_phone), Route.Phone(), icon = R.drawable.ic_m_phone),
        ScreenEntry(sub(phone, stringResource(R.string.phone_tab_messages)), "", Route.Phone("messages"), icon = R.drawable.ic_m_chat),
        ScreenEntry(sub(phone, stringResource(R.string.phone_tab_position)), "", Route.Phone("position"), icon = R.drawable.ic_m_pin),
        ScreenEntry(stringResource(R.string.nav_contacts), stringResource(R.string.search_sub_contacts), Route.Contacts, icon = R.drawable.ic_m_contacts),
        ScreenEntry(tools, stringResource(R.string.search_sub_tools), Route.Tools(), icon = R.drawable.ic_m_tools),
        ScreenEntry(sub(tools, stringResource(R.string.tools_tab_rights)), "", Route.Tools("droits"), icon = R.drawable.ic_m_shield),
        ScreenEntry(sub(tools, stringResource(R.string.tools_tab_services)), "", Route.Tools("services"), icon = R.drawable.ic_m_plug),
        ScreenEntry(sub(tools, stringResource(R.string.tools_tab_agreements)), "", Route.Tools("accords"), icon = R.drawable.ic_m_check),
        ScreenEntry(settings, stringResource(R.string.search_sub_settings), set, icon = R.drawable.ic_m_settings),
        ScreenEntry(sub(settings, stringResource(R.string.settings_account)), stringResource(R.string.settings_account_line), Route.SettingsPage(SettingsPages.ACCOUNT), set, R.drawable.ic_m_user),
        ScreenEntry(sub(settings, stringResource(R.string.settings_boxes)), stringResource(R.string.settings_boxes_line), Route.SettingsPage(SettingsPages.BOXES), set, R.drawable.ic_m_mail),
        ScreenEntry(sub(settings, stringResource(R.string.settings_teams)), stringResource(R.string.settings_teams_line), Route.SettingsPage(SettingsPages.TEAMS), set, R.drawable.ic_m_teams),
        ScreenEntry(sub(settings, stringResource(R.string.settings_phones)), stringResource(R.string.settings_phones_line), Route.SettingsPage(SettingsPages.PHONES), set, R.drawable.ic_m_phone),
        ScreenEntry(sub(settings, stringResource(R.string.settings_shares)), stringResource(R.string.settings_shares_line), Route.SettingsPage(SettingsPages.SHARES), set, R.drawable.ic_m_share),
        ScreenEntry(sub(settings, stringResource(R.string.settings_services)), stringResource(R.string.settings_services_line), Route.SettingsPage(SettingsPages.SERVICES), set, R.drawable.ic_m_plug),
        ScreenEntry(sub(settings, stringResource(R.string.settings_notifications)), "", Route.SettingsPage(SettingsPages.NOTIFICATIONS), set, R.drawable.ic_m_bell),
        ScreenEntry(sub(settings, stringResource(R.string.settings_where)), stringResource(R.string.settings_where_title), Route.SettingsPage(SettingsPages.POSITION), set, R.drawable.ic_m_pin),
        ScreenEntry(sub(settings, stringResource(R.string.settings_phone)), stringResource(R.string.settings_phone_title), Route.SettingsPage(SettingsPages.MESSAGES), set, R.drawable.ic_m_chat),
        ScreenEntry(sub(settings, stringResource(R.string.settings_appearance)), "", Route.SettingsPage(SettingsPages.APPEARANCE), set, R.drawable.ic_m_sun),
        ScreenEntry(sub(settings, stringResource(R.string.settings_data)), stringResource(R.string.settings_sum_data), Route.SettingsPage(SettingsPages.DATA), set, R.drawable.ic_m_trash),
    )
}
