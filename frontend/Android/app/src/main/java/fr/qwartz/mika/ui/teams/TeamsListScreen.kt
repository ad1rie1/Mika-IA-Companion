package fr.qwartz.mika.ui.teams

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
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
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.levelTag
import fr.qwartz.mika.data.moi.map
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.teams.Conversation
import fr.qwartz.mika.data.moi.teams.Kinds
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsLimits
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.accountTitle
import fr.qwartz.mika.data.moi.teams.decides
import fr.qwartz.mika.data.moi.teams.herMark
import fr.qwartz.mika.data.moi.teams.lastPrefix
import fr.qwartz.mika.data.moi.teams.orderedAccounts
import fr.qwartz.mika.data.moi.teams.waitingYours
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaLine
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.SearchBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.SheetLine
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** La liste se relit à ce rythme tant qu'elle est à l'écran. */
private const val REFRESH_MS = 60_000L
private const val SEARCH_DEBOUNCE_MS = 300L

/**
 * Les discussions (`Route.Teams`) : ses comptes (leur niveau, qui y est connecté), le compte choisi (tous, ou un
 * seul), la recherche, et les conversations, la plus récente d'abord, avec sa réponse en chemin.
 */
class TeamsListViewModel(graph: AppGraph) : TeamsScreenModel(graph) {
    var loaded by mutableStateOf<Load<Unit>>(Load.Loading)
        private set
    /** Le compte dont on lit les discussions ; vide : tous. */
    var chosen by mutableStateOf("")
        private set
    var query by mutableStateOf("")
        private set
    var searching by mutableStateOf(false)
        private set
    var listing by mutableStateOf<Load<List<Conversation>>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set

    private var started = false
    private var generation = 0
    private var listJob: Job? = null
    private var searchJob: Job? = null

    /** L'écran revient (ou une minute a passé) : tout lire la première fois, sinon relire sans bruit. */
    fun resume() {
        if (!started) {
            started = true
            reload(keep = false, silent = false)
        } else {
            reload(keep = true, silent = true)
        }
    }

    /** Tirer pour relire : ce qui est montré reste jusqu'à ce que la relecture arrive. */
    fun pull() {
        refreshing = true
        viewModelScope.launch {
            reload(keep = true, silent = false).join()
            refreshing = false
        }
    }

    fun retry() = reload(keep = false, silent = false)

    fun choose(key: String) {
        chosen = key
        loadList(keep = false, silent = false)
    }

    fun openSearch() {
        searching = true
    }

    fun closeSearch() {
        searching = false
        if (query.isNotEmpty()) search("")
    }

    fun search(text: String) {
        query = text.take(TeamsLimits.SEARCH)
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(SEARCH_DEBOUNCE_MS)
            loadList(keep = true, silent = false)
        }
    }

    /** Ses comptes, puis les discussions : sans compte lu, rien ne se lit (le compte choisi a pu disparaître). */
    private fun reload(keep: Boolean, silent: Boolean): Job = viewModelScope.launch {
        when (val got = loadAccounts()) {
            is MoiApi.Result.Ok -> {
                loaded = Load.Ready(Unit)
                if (chosen.isNotEmpty() && got.value.accounts.none { it.key == chosen }) chosen = ""
                if (got.value.plugged && got.value.accounts.isNotEmpty()) loadList(keep, silent)?.join()
            }
            is MoiApi.Result.Failed -> if (loaded !is Load.Ready) loaded = Load.Failed(got.error) else if (!silent) say(got.error)
        }
    }

    /** Relit les discussions. [keep] : ce qui est montré reste pendant la lecture ; [silent] : un refus ne se dit pas. */
    private fun loadList(keep: Boolean, silent: Boolean): Job? {
        listJob?.cancel()
        val gen = ++generation
        val account = chosen
        val q = query
        if (!keep || listing !is Load.Ready) listing = Load.Loading
        listJob = viewModelScope.launch {
            val got = api.conversations(account = account, q = q).map { items -> items.distinctBy { it.key } }
            if (gen != generation) return@launch
            if (got is MoiApi.Result.Failed && listing is Load.Ready && keep) {
                if (!silent) say(got.error)
            } else {
                listing = Load.of(got)
            }
        }
        return listJob
    }

    override suspend fun afterDecision(r: TeamsReply, redo: Boolean) = Unit
}

/**
 * Teams, la rubrique du tiroir (ADR 0235, la maquette `ecrans/teams.js`) : le compte en sous-titre (le titre ouvre la
 * feuille des comptes), la loupe cherche, « Ses brouillons » en bandeau rose quand l'un attend ta décision, les
 * discussions (un tête-à-tête au nom de l'autre), leur dernier message et sa réponse en chemin, en rose. Tirer relit,
 * et la liste se relit chaque minute. Pas de « nouvelle discussion » : l'extension ne sait que répondre.
 */
@Composable
fun TeamsListScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: TeamsListViewModel = viewModel(key = "teams.list|$session") { TeamsListViewModel(graph) }
    var sheet by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                vm.resume()
                delay(REFRESH_MS)
            }
        }
    }
    BackHandler(enabled = vm.searching) { vm.closeSearch() }
    val accounts = vm.accountList
    val chosen = vm.account(vm.chosen)
    SectionScaffold(
        topBar = {
            if (vm.searching) {
                SearchBar(vm.query, stringResource(R.string.teams_search_hint), vm::search, vm::closeSearch)
            } else {
                MikaTopBar(
                    title = stringResource(R.string.nav_teams),
                    nav = BarNav.DRAWER,
                    subtitle = listSubtitle(accounts, chosen),
                    onTitle = if (accounts.isNotEmpty()) ({ sheet = true }) else null,
                ) {
                    if (accounts.isNotEmpty()) BarAction(R.drawable.ic_m_search, stringResource(R.string.teams_search), vm::openSearch)
                    BarMenu(
                        listOf(
                            MenuEntry(stringResource(R.string.teams_her_replies), R.drawable.ic_m_pen) { shell.navigate(Route.TeamsReplies) },
                            MenuEntry(stringResource(R.string.teams_how), R.drawable.ic_m_shield) { shell.navigate(Route.Tools()) },
                            MenuEntry(stringResource(R.string.teams_settings), R.drawable.ic_m_settings) { shell.navigate(Route.SettingsPage("teams")) },
                        ),
                    )
                }
            }
        },
    ) { modifier ->
        LoadBox(vm.loaded, onRetry = vm::retry, modifier = modifier) {
            val got = vm.accounts
            when {
                got != null && !got.plugged -> Notice(stringResource(R.string.teams_unplugged), modifier)
                accounts.isEmpty() -> Notice(
                    stringResource(R.string.teams_no_account),
                    modifier,
                    action = stringResource(R.string.teams_settings),
                    onAction = { shell.navigate(Route.SettingsPage("teams")) },
                )
                else -> PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = modifier) {
                    LoadBox(vm.listing, onRetry = vm::retry) { list ->
                        ConversationList(
                            list = list,
                            accounts = accounts,
                            many = vm.chosen.isEmpty() && accounts.size > 1,
                            waiting = waitingYours(accounts, vm.chosen),
                            query = vm.query,
                            onOpen = { shell.navigate(Route.TeamsThread(it)) },
                            onReplies = { shell.navigate(Route.TeamsReplies) },
                        )
                    }
                }
            }
        }
    }
    if (sheet) {
        AccountsSheet(
            accounts = accounts,
            chosen = vm.chosen,
            onChoose = vm::choose,
            onReplies = { shell.navigate(Route.TeamsReplies) },
            onSettings = { shell.navigate(Route.SettingsPage("teams")) },
            onDismiss = { sheet = false },
        )
    }
}

/** Le compte sous le titre : le compte choisi (le tien, son nom et qui y est connecté ; partagé, son niveau et son
 *  propriétaire), sinon combien de comptes. */
@Composable
private fun listSubtitle(accounts: List<TeamsAccount>, chosen: TeamsAccount?): String {
    val one = chosen ?: accounts.singleOrNull()
    return when {
        one != null -> accountLine(one)
        accounts.isEmpty() -> ""
        else -> pluralStringResource(R.plurals.teams_accounts_count, accounts.size, accounts.size)
    }
}

/** « Atelier · Adrien Moreau dans Teams » ; partagé : « Atelier · lecture seule · d'Adrien Moreau ». */
@Composable
private fun accountLine(a: TeamsAccount): String {
    val name = a.name.ifBlank { a.key }
    val parts = if (a.own) {
        listOf(name, if (a.selfName.isNotBlank()) stringResource(R.string.teams_in_teams, a.selfName) else "")
    } else {
        listOf(name, levelTag(a.level), ofName(a.ownerName))
    }
    val off = if (!a.enabled) stringResource(R.string.teams_account_off) else ""
    return (parts + off).filter { it.isNotBlank() }.joinToString(" · ")
}

@Composable
private fun ConversationList(
    list: List<Conversation>,
    accounts: List<TeamsAccount>,
    many: Boolean,
    waiting: Int,
    query: String,
    onOpen: (String) -> Unit,
    onReplies: () -> Unit,
) {
    val now = rememberNow()
    LazyColumn(Modifier.fillMaxSize()) {
        if (waiting > 0) {
            item(key = "replies") {
                MikaLine(
                    icon = R.drawable.ic_m_pen,
                    title = stringResource(R.string.teams_her_replies),
                    subtitle = pluralStringResource(R.plurals.teams_her_replies_waiting, waiting, waiting),
                    count = waiting,
                    onClick = onReplies,
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 6.dp),
                )
            }
        }
        if (list.isEmpty()) {
            item(key = "empty") {
                Text(
                    if (query.isNotBlank()) stringResource(R.string.teams_empty_search, query.trim()) else stringResource(R.string.teams_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(32.dp),
                )
            }
        }
        items(list, key = { it.key }) { c ->
            val a = accounts.firstOrNull { it.key == c.account }
            ConversationRow(c, a, if (many && a != null) accountTitle(a) else null, now) { onOpen(c.key) }
        }
        item(key = "end") { Spacer(Modifier.padding(bottom = 24.dp)) }
    }
}

/** Une discussion de la liste (`.li` de la maquette) : son rond, son nom, son heure, son dernier message — en rose,
 *  sa réponse en chemin —, une mention de toi, son compte quand la liste en mêle plusieurs. */
@Composable
private fun ConversationRow(c: Conversation, account: TeamsAccount?, accountName: String?, now: Long, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val title = c.title.ifBlank { stringResource(R.string.teams_untitled) }
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp)) {
        ConversationAvatar(c.title, c.kind, c.key)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Row(Modifier.weight(1f), verticalAlignment = Alignment.CenterVertically) {
                    Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                    if (c.kind == Kinds.MEETING) {
                        Spacer(Modifier.width(6.dp))
                        Tag(stringResource(R.string.teams_meeting), Tone.NEUTRAL, R.drawable.ic_m_calendar)
                    }
                }
                Spacer(Modifier.width(8.dp))
                Text(MoiDates.short(c.lastAt, now), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                val her = c.her
                if (her != null) {
                    MIcon(R.drawable.ic_m_pen, herMark(her.state, decides(account)), size = 13.dp, tint = mika.accent)
                    Spacer(Modifier.width(3.dp))
                    Text(stringResource(R.string.teams_her_prefix), style = MaterialTheme.typography.bodySmall, color = mika.accent, maxLines = 1)
                }
                Text(
                    lastPrefix(c, account) + c.last?.text.orEmpty(),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (c.last?.mentionsMe == true) {
                    Spacer(Modifier.width(6.dp))
                    MIcon(R.drawable.ic_m_at, stringResource(R.string.teams_mentioned), size = 16.dp, tint = scheme.primary)
                }
            }
            if (accountName != null) {
                Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    Tag(accountName, Tone.NEUTRAL, R.drawable.ic_m_teams)
                }
            }
        }
    }
}

/**
 * La feuille qui monte du titre : tous tes comptes, les tiens, ceux qu'on te partage à leur niveau, « Ses
 * brouillons », et « Régler les comptes Teams ». Un compte qu'on te partage dit son niveau et son propriétaire.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AccountsSheet(
    accounts: List<TeamsAccount>,
    chosen: String,
    onChoose: (String) -> Unit,
    onReplies: () -> Unit,
    onSettings: () -> Unit,
    onDismiss: () -> Unit,
) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val ordered = orderedAccounts(accounts)
    val shared = ordered.filterNot { it.own }
    fun pick(key: String) {
        onChoose(key)
        onDismiss()
    }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 12.dp)) {
            Text(
                stringResource(R.string.teams_sheet_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Normal,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
            )
            if (accounts.size > 1) {
                SheetLine(
                    icon = R.drawable.ic_m_teams,
                    title = stringResource(R.string.teams_all_accounts),
                    subtitle = ordered.joinToString(", ") { accountTitle(it) },
                    count = waitingYours(accounts),
                    pinkCount = true,
                    selected = chosen.isEmpty(),
                    onClick = { pick("") },
                )
            }
            for (a in ordered.filter { it.own }) {
                SheetLine(
                    icon = R.drawable.ic_m_teams,
                    title = accountTitle(a),
                    subtitle = accountLine(a),
                    count = a.draftsWaiting,
                    pinkCount = true,
                    selected = chosen == a.key || accounts.size == 1,
                    onClick = { pick(a.key) },
                )
            }
            if (shared.isNotEmpty()) {
                ListHead(pluralStringResource(R.plurals.teams_sheet_shared, shared.size), muted = true)
                for (a in shared) {
                    SheetLine(
                        icon = R.drawable.ic_m_users,
                        title = accountTitle(a),
                        subtitle = accountLine(a),
                        count = 0,
                        selected = chosen == a.key || accounts.size == 1,
                        onClick = { pick(a.key) },
                    )
                }
            }
            HorizontalDivider(Modifier.padding(vertical = 8.dp))
            SheetLine(
                icon = R.drawable.ic_m_pen,
                title = stringResource(R.string.teams_her_replies),
                subtitle = stringResource(R.string.teams_her_replies_sheet),
                count = waitingYours(accounts),
                pink = true,
                pinkCount = true,
                selected = false,
                onClick = {
                    onDismiss()
                    onReplies()
                },
            )
            SheetLine(
                icon = R.drawable.ic_m_settings,
                title = stringResource(R.string.teams_settings),
                subtitle = stringResource(R.string.teams_settings_where),
                count = 0,
                selected = false,
                onClick = {
                    onDismiss()
                    onSettings()
                },
            )
        }
    }
}
