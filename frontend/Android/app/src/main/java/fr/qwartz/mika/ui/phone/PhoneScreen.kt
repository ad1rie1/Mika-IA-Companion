package fr.qwartz.mika.ui.phone

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.PhoneLive
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.map
import fr.qwartz.mika.data.moi.phone.EmptyWhy
import fr.qwartz.mika.data.moi.phone.OfferStates
import fr.qwartz.mika.data.moi.phone.PhoneConversation
import fr.qwartz.mika.data.moi.phone.conversationTitle
import fr.qwartz.mika.data.moi.phone.draftFor
import fr.qwartz.mika.data.moi.phone.emptyWhy
import fr.qwartz.mika.data.moi.phone.herMark
import fr.qwartz.mika.data.moi.phone.proposalLine
import fr.qwartz.mika.data.moi.phone.proposals
import fr.qwartz.mika.data.moi.phone.snippetOf
import fr.qwartz.mika.data.moi.phone.underWay
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.data.phone.PhoneDraft
import fr.qwartz.mika.data.settings.Settings
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaLine
import fr.qwartz.mika.ui.shell.MikaMark
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch

/**
 * Messages (`Route.Phone("messages")`) : les conversations que l'application a lues (la plus récente d'abord), et ce
 * que ce téléphone tient de ses propositions — leur texte et leur échéance, pour le bandeau rose.
 */
class PhoneMessagesViewModel(graph: AppGraph) : PhoneModel(graph) {
    var listing by mutableStateOf<Load<List<PhoneConversation>>>(Load.Loading)
        private set
    /** Les propositions que ce téléphone a reçues et qui attendent ton geste. */
    var waiting by mutableStateOf<List<PhoneDraft>>(emptyList())
        private set
    var refreshing by mutableStateOf(false)
        private set

    private var started = false
    private var job: Job? = null

    /** L'écran revient (l'app au premier plan, ou depuis un fil) : tout lire la première fois, sinon relire sans bruit. */
    fun resume() {
        if (!started) {
            started = true
            load(quiet = false)
        } else {
            load(quiet = true)
        }
    }

    /** Le direct (ADR 0308) : ses conversations ont changé (`phone` — un message, une de ses propositions) : relues
     *  sans bruit. Rend la main quand c'est relu. */
    suspend fun onLive(signal: LiveSignal) {
        if (started && signal.touches(Topics.PHONE)) load(quiet = true).join()
    }

    /** Tirer pour relire : ce qui est montré reste jusqu'à ce que la relecture arrive. */
    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(quiet = false).join()
            refreshing = false
        }
    }

    fun retry() {
        listing = Load.Loading
        load(quiet = false)
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            waiting = graph.phoneDrafts.waiting()
            // le serveur range par clé ; deux fois la même ne ferait qu'une ligne pour la liste paresseuse
            val got = api.conversations().map { items -> items.distinctBy { it.key } }
            when (got) {
                is MoiApi.Result.Ok -> listing = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (listing is Load.Ready) {
                    if (!quiet) say(got.error)
                } else {
                    listing = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }
}

/**
 * Le Téléphone, la rubrique du tiroir (ADR 0235, la maquette `ecrans/telephone.js` ; ADR 0233) : en titre, l'état de
 * tes téléphones, qui mène à Paramètres › Téléphones ; deux onglets, Messages et Position ([tab]).
 */
@Composable
fun PhoneScreen(graph: AppGraph, tab: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val phones: PhonesViewModel = viewModel(key = "phone.phones|$session") { PhonesViewModel(graph) }
    val shown = PhoneTabs.of(tab)
    // tes téléphones (la barre) : lus à l'ouverture et à chaque retour, et quand le direct dit qu'ils ont changé
    FollowLive(graph.live, PhoneLive.PHONES, phones, onShown = { phones.load() }) { phones.onLive(it) }
    val now = rememberNow()
    SectionScaffold(topBar = { PhoneTopBar(phones.bar(now), shown) }) { modifier ->
        when (shown) {
            PhoneTabs.POSITION -> PositionTab(graph, session, modifier, onPull = { phones.load() })
            else -> MessagesTab(graph, session, modifier, onPull = { phones.load() }, onPosition = { shell.replace(Route.Phone(PhoneTabs.POSITION)) })
        }
    }
}

/**
 * L'onglet Messages : le bandeau rose de ses propositions qui attendent ton geste (`counts.phone`), puis les
 * conversations — le groupe ou qui écrit, la pastille de l'appli, le dernier message, l'heure, sa réponse en chemin en
 * rose. Tirer relit, la liste suit le direct (ADR 0308). Un compte qui n'est pas une de ses propriétaires : une phrase
 * le dit et mène à Position.
 */
@Composable
private fun MessagesTab(graph: AppGraph, session: String, modifier: Modifier, onPull: () -> Unit, onPosition: () -> Unit) {
    val shell = LocalShell.current
    val vm: PhoneMessagesViewModel = viewModel(key = "phone.messages|$session") { PhoneMessagesViewModel(graph) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    FollowLive(graph.live, PhoneLive.MESSAGES, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val me by graph.me.me.collectAsStateWithLifecycle()
    val settings by graph.settings.settings.collectAsStateWithLifecycle(Settings())
    PullToRefreshBox(
        isRefreshing = vm.refreshing,
        onRefresh = {
            vm.pull()
            onPull()
            graph.me.refresh()
        },
        modifier = modifier,
    ) {
        LoadBox(vm.listing, onRetry = vm::retry) { list ->
            if (list.isEmpty()) {
                EmptyMessages(emptyWhy(me?.owner, settings.phoneShare), onPosition = onPosition, onSettings = { shell.navigate(Route.SettingsPage("messages")) })
            } else {
                ConversationList(
                    list = list,
                    waiting = vm.waiting,
                    offered = me?.counts?.phone ?: 0,
                    onOpen = { shell.navigate(Route.PhoneThread(it)) },
                )
            }
        }
    }
}

/** Messages vide : pourquoi, et où l'on peut quelque chose (sa position pour un compte qui n'est pas propriétaire). */
@Composable
private fun EmptyMessages(why: EmptyWhy, onPosition: () -> Unit, onSettings: () -> Unit) {
    val text = stringResource(R.string.phone_empty_title) + "\n\n" + stringResource(
        when (why) {
            EmptyWhy.NOT_OWNER -> R.string.phone_empty_not_owner
            EmptyWhy.READING_OFF -> R.string.phone_empty_reading_off
            EmptyWhy.NOTHING_YET -> R.string.phone_empty_nothing
        },
    )
    // une liste qui défile, pour que « tirer pour relire » marche aussi sur la page vide
    LazyColumn(Modifier.fillMaxSize()) {
        item {
            when (why) {
                EmptyWhy.NOT_OWNER -> Notice(text, Modifier.padding(top = 48.dp), action = stringResource(R.string.phone_empty_not_owner_action), onAction = onPosition)
                EmptyWhy.READING_OFF -> Notice(text, Modifier.padding(top = 48.dp), action = stringResource(R.string.phone_empty_reading_off_action), onAction = onSettings)
                EmptyWhy.NOTHING_YET -> Notice(text, Modifier.padding(top = 48.dp))
            }
        }
    }
}

@Composable
private fun ConversationList(list: List<PhoneConversation>, waiting: List<PhoneDraft>, offered: Int, onOpen: (String) -> Unit) {
    val now = rememberNow()
    val proposed = proposals(list)
    // ce qui attend ton geste : le compte du serveur (toutes conversations), au moins celles que la liste montre
    val count = maxOf(offered, proposed.count { it.her?.state == OfferStates.OFFERED })
    LazyColumn(Modifier.fillMaxSize()) {
        val first = proposed.firstOrNull()
        if (count > 0 && first != null) {
            item(key = "proposals") {
                MikaLine(
                    icon = R.drawable.ic_m_sparkle,
                    title = pluralStringResource(R.plurals.phone_banner_title, count, count),
                    subtitle = proposalLine(first, draftFor(first, waiting), now),
                    count = count,
                    onClick = { onOpen(first.key) },
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 6.dp),
                )
            }
        }
        items(list, key = { it.key }) { c -> ConversationRow(c, now) { onOpen(c.key) } }
        item(key = "note") {
            Text(
                stringResource(R.string.phone_list_note),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 20.dp),
            )
        }
    }
}

/** Une conversation de la liste (`.li` de la maquette) : son rond et la pastille de l'appli, son nom, son heure, son
 *  dernier message — précédé, en rose, de sa réponse en chemin ; partie, copiée, ou en échec (en rouge), dessous. */
@Composable
private fun ConversationRow(c: PhoneConversation, now: Long, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val title = conversationTitle(c)
    val mark = herMark(c.her?.state)
    val pending = underWay(c.her?.state.orEmpty())
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp)) {
        ConversationFace(title, c.group, c.key, c.app, appLabel(c.app, c.appName))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    title,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = if (pending) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Text(MoiDates.short(c.lastAt, now), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (pending && mark != null) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 13.dp, tint = mika.accent)
                    Spacer(Modifier.width(3.dp))
                    Text("${mark.second} · ", style = MaterialTheme.typography.bodySmall, color = mika.accent, maxLines = 1)
                }
                Text(
                    snippetOf(c),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
            }
            if (!pending && mark != null) {
                Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (mark.first == Tone.DANGER) {
                        Tag(mark.second, Tone.DANGER, R.drawable.ic_m_alert)
                    } else {
                        MikaMark(mark.second, if (mark.first == Tone.INFO) R.drawable.ic_m_copy else R.drawable.ic_m_check)
                    }
                }
            }
        }
    }
}
