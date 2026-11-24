package fr.qwartz.mika.ui.contacts

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.contacts.CONTACT_KIND_CHOICES
import fr.qwartz.mika.data.moi.contacts.ContactKinds
import fr.qwartz.mika.data.moi.contacts.ContactLine
import fr.qwartz.mika.data.moi.contacts.ContactsCounts
import fr.qwartz.mika.data.moi.contacts.ContactsLimits
import fr.qwartz.mika.data.moi.contacts.clippedQuery
import fr.qwartz.mika.data.moi.contacts.lineSub
import fr.qwartz.mika.data.moi.contacts.of
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

private const val SEARCH_DEBOUNCE_MS = 300L
/** « Lui présenter quelqu'un » : la phrase posée dans le champ du chat (celle du web), à compléter. */
private const val INTRODUCE = "Je voudrais te présenter quelqu'un : "

/** Ce que la liste montre : ses contacts lus (la première page et la suite), combien en tout, pour quelle recherche et
 *  quelle sorte. */
data class ContactsListing(
    val items: List<ContactLine> = emptyList(),
    val total: Int = 0,
    val q: String = "",
    val kind: String = "",
)

/**
 * La liste de Contacts (`Route.Contacts`) : tes contacts, le dernier vu d'abord (l'ordre du serveur), la recherche (le
 * serveur cherche, dans ce que tes comptes en montrent), la sorte (Tous · Personnes · Organisations, et leurs nombres,
 * sans la recherche), la suite en fin de liste. Une relecture discrète garde la suite déjà lue si rien n'a changé
 * devant (comme le web) ; un contact oublié depuis sa fiche la quitte aussitôt.
 */
class ContactsListViewModel(deps: ContactsDeps) : ViewModel() {
    private val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des gestes, une fois chacun. */
    val said: Flow<String> = notices.receiveAsFlow()

    var query by mutableStateOf("")
        private set
    var kind by mutableStateOf("")
        private set
    var listing by mutableStateOf<Load<ContactsListing>>(Load.Loading)
        private set
    /** Les nombres de chaque sorte, sans la recherche : ils restent pendant qu'une recherche se lit. */
    var counts by mutableStateOf<ContactsCounts?>(null)
        private set
    var refreshing by mutableStateOf(false)
        private set
    var loadingMore by mutableStateOf(false)
        private set
    /** La suite n'a pas pu se lire : elle ne se redemande qu'à « Réessayer ». */
    var moreError by mutableStateOf("")
        private set

    private var started = false
    private var generation = 0
    private var listJob: Job? = null
    private var searchJob: Job? = null
    /** Oubliés pendant la session : une lecture partie avant l'oubli ne les ramène pas. */
    private val forgotten = HashSet<Int>()

    init {
        viewModelScope.launch { ContactsChanges.flow.collect { forgot(it) } }
    }

    private fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    /** L'écran revient (l'app au premier plan, ou depuis une fiche) : tout lire la première fois, sinon relire sans
     *  bruit. */
    fun resume() {
        if (!started) {
            started = true
            load(keep = false, silent = false)
        } else {
            load(keep = true, silent = true)
        }
    }

    /** Le direct (ADR 0308) : ses contacts ont changé (`contacts`) — la liste se relit sans bruit, la suite déjà lue
     *  gardée si rien n'a changé devant. Rend la main quand c'est relu. */
    suspend fun onLive(signal: LiveSignal) {
        if (started && signal.touches(Topics.CONTACTS)) load(keep = true, silent = true).join()
    }

    /** Tirer pour relire : ce qui est montré reste jusqu'à ce que la relecture arrive. */
    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(keep = true, silent = false).join()
            refreshing = false
        }
    }

    fun retry() = load(keep = false, silent = false)

    fun search(text: String) {
        query = clippedQuery(text)
        searchJob?.cancel()
        searchJob = viewModelScope.launch {
            delay(SEARCH_DEBOUNCE_MS)
            load(keep = true, silent = false)
        }
    }

    fun choose(k: String) {
        if (k == kind) return
        kind = k
        searchJob?.cancel()
        load(keep = false, silent = false)
    }

    /**
     * La première page de la recherche et de la sorte du moment. [keep] : ce qui est montré reste pendant la lecture
     * (et, la même recherche relue, la suite déjà lue si rien n'a changé devant) ; [silent] : un refus ne se dit pas.
     */
    private fun load(keep: Boolean, silent: Boolean): Job {
        listJob?.cancel()
        val gen = ++generation
        val q = query.trim()
        val k = kind
        if (!keep || listing !is Load.Ready) listing = Load.Loading
        loadingMore = false
        moreError = ""
        val job = viewModelScope.launch {
            val got = api.page(q, k, 1, ContactsLimits.PAGE)
            if (gen != generation) return@launch
            when (got) {
                is MoiApi.Result.Ok -> {
                    val page = got.value
                    counts = page.counts
                    val fresh = page.items.filter { it.id !in forgotten }
                    val cur = listing.valueOrNull
                    val items = if (cur != null && cur.q == q && cur.kind == k && cur.items.size > fresh.size && cur.items.take(fresh.size) == fresh) cur.items else fresh
                    listing = Load.Ready(ContactsListing(items, page.total, q, k))
                }
                is MoiApi.Result.Failed -> if (keep && listing is Load.Ready) {
                    if (!silent) say(got.error.said)
                } else {
                    listing = Load.Failed(got.error)
                }
            }
        }
        listJob = job
        return job
    }

    /** La suite, en fin de liste : la page d'après, ajoutée (sans doubler un contact déjà lu). */
    fun more() {
        val cur = listing.valueOrNull ?: return
        if (loadingMore || cur.items.size >= cur.total) return
        val gen = generation
        loadingMore = true
        moreError = ""
        viewModelScope.launch {
            val next = cur.items.size / ContactsLimits.PAGE + 1
            val got = api.page(cur.q, cur.kind, next, ContactsLimits.PAGE)
            if (gen != generation) return@launch
            loadingMore = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    val now = listing.valueOrNull ?: return@launch
                    val known = now.items.mapTo(HashSet()) { it.id }
                    val added = got.value.items.filter { it.id !in known && it.id !in forgotten }
                    // rien de neuf (le serveur a bougé entre deux pages) : la liste s'arrête là, sans redemander en boucle
                    val total = if (added.isEmpty()) now.items.size else got.value.total
                    listing = Load.Ready(now.copy(items = now.items + added, total = total))
                }
                is MoiApi.Result.Failed -> moreError = got.error.said
            }
        }
    }

    /** Oublié depuis sa fiche : il quitte la liste aussitôt, et ses nombres avec lui. */
    private fun forgot(id: Int) {
        forgotten += id
        val cur = listing.valueOrNull ?: return
        val gone = cur.items.firstOrNull { it.id == id } ?: return
        listing = Load.Ready(cur.copy(items = cur.items - gone, total = (cur.total - 1).coerceAtLeast(0)))
        counts = counts?.let { c ->
            if (gone.org) c.copy(all = (c.all - 1).coerceAtLeast(0), org = (c.org - 1).coerceAtLeast(0))
            else c.copy(all = (c.all - 1).coerceAtLeast(0), person = (c.person - 1).coerceAtLeast(0))
        }
    }
}

/**
 * Contacts, la rubrique du tiroir après Téléphone (ADR 0298, la maquette validée `ecrans/contacts.js`) : « N pour
 * toi » sous le titre, la recherche (un nom, un e-mail, un numéro), Tous · Personnes · Organisations et leurs nombres,
 * puis une ligne par contact — son rond (un carré pour une organisation), son nom, son poste et son organisation, d'où
 * elle le connaît et combien, le dernier échange. Toucher ouvre sa fiche ; « Lui présenter quelqu'un » ouvre le chat, la
 * phrase à compléter. Tirer relit, et la liste suit le direct (ADR 0308).
 */
@Composable
fun ContactsScreen(graph: AppGraph, nav: BarNav) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: ContactsListViewModel = viewModel(key = "contacts.list|$session") { ContactsListViewModel(ContactsDeps(graph)) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    FollowLive(graph.live, CONTACTS_TOPICS, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val introduce = {
        graph.scope.launch { graph.shareInbox.deposit(ComposerDraft(text = INTRODUCE)) }
        shell.open(Route.Chat)
    }
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = stringResource(R.string.nav_contacts),
                nav = nav,
                subtitle = vm.counts?.let { stringResource(R.string.contacts_for_you, it.all) },
            )
        },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { introduce() },
                icon = { MIcon(R.drawable.ic_m_user_plus, null) },
                text = { Text(stringResource(R.string.contacts_introduce)) },
            )
        },
    ) { modifier ->
        Column(modifier) {
            SearchField(vm.query, vm::search)
            KindChips(vm.kind, vm.counts, vm::choose)
            PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = Modifier.fillMaxSize()) {
                LoadBox(vm.listing, onRetry = vm::retry) { listing ->
                    ContactList(vm, listing, onOpen = { shell.navigate(Route.Contact(it)) })
                }
            }
        }
    }
}

/** Le champ de la recherche (`.cx-search .field`) : sa loupe, ce qu'on cherche, de quoi l'effacer. */
@Composable
private fun SearchField(query: String, onQuery: (String) -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val label = stringResource(R.string.contacts_search_label)
    Surface(
        shape = RoundedCornerShape(28.dp),
        color = scheme.surfaceContainerHigh,
        modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 2.dp).height(48.dp),
    ) {
        Row(Modifier.padding(start = 16.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            MIcon(R.drawable.ic_m_search, null, size = 20.dp, tint = scheme.onSurfaceVariant)
            Spacer(Modifier.width(10.dp))
            BasicTextField(
                value = query,
                onValueChange = onQuery,
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                textStyle = TextStyle(color = scheme.onSurface, fontSize = 16.sp),
                cursorBrush = SolidColor(scheme.primary),
                modifier = Modifier.weight(1f).semantics { contentDescription = label },
                decorationBox = { inner ->
                    Box(contentAlignment = Alignment.CenterStart) {
                        if (query.isEmpty()) Text(stringResource(R.string.contacts_search_hint), color = scheme.onSurfaceVariant, fontSize = 16.sp, maxLines = 1)
                        inner()
                    }
                },
            )
            if (query.isNotEmpty()) {
                IconButton(onClick = { onQuery("") }) { MIcon(R.drawable.ic_m_x, stringResource(R.string.contacts_search_clear), size = 20.dp) }
            } else {
                Spacer(Modifier.width(12.dp))
            }
        }
    }
}

/** Tous · Personnes · Organisations (`.chips`), avec leur nombre (sans la recherche, comme l'API). */
@Composable
private fun KindChips(kind: String, counts: ContactsCounts?, onChoose: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (k in CONTACT_KIND_CHOICES) {
            val label = stringResource(
                when (k) {
                    ContactKinds.PERSON -> R.string.contacts_kind_person
                    ContactKinds.ORG -> R.string.contacts_kind_org
                    else -> R.string.contacts_kind_all
                },
            )
            val on = kind == k
            FilterChip(
                selected = on,
                onClick = { onChoose(k) },
                label = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(label)
                        if (counts != null) {
                            Spacer(Modifier.width(6.dp))
                            Text("${counts.of(k)}", style = MaterialTheme.typography.labelSmall)
                        }
                    }
                },
                leadingIcon = if (on) {
                    { MIcon(R.drawable.ic_m_check, null, size = 18.dp) }
                } else {
                    null
                },
            )
        }
    }
}

@Composable
private fun ContactList(vm: ContactsListViewModel, listing: ContactsListing, onOpen: (Int) -> Unit) {
    val now = rememberNow()
    LazyColumn(Modifier.fillMaxSize()) {
        if (listing.items.isEmpty()) {
            item(key = "empty") { EmptyList(listing) }
        }
        items(listing.items, key = { it.id }) { c -> ContactRow(c, now) { onOpen(c.id) } }
        if (listing.items.size < listing.total) {
            item(key = "more") {
                Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                    when {
                        vm.moreError.isNotEmpty() -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(stringResource(R.string.contacts_more_failed, vm.moreError), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
                            Spacer(Modifier.height(8.dp))
                            FilledTonalButton(onClick = vm::more) { Text(stringResource(R.string.retry)) }
                        }
                        else -> {
                            CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
                            // la fin de la liste est à l'écran : la suite se lit
                            LaunchedEffect(listing.items.size, listing.q, listing.kind) { vm.more() }
                        }
                    }
                }
            }
        } else if (listing.items.isNotEmpty()) {
            item(key = "note") {
                Text(
                    stringResource(R.string.contacts_list_note),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp),
                )
            }
        }
        // la place du bouton flottant
        item(key = "end") { Spacer(Modifier.height(96.dp)) }
    }
}

/** Rien à montrer : la recherche ne trouve personne, aucune organisation, ou aucun contact encore. */
@Composable
private fun EmptyList(listing: ContactsListing) {
    val scheme = MaterialTheme.colorScheme
    val (icon, title, text) = when {
        listing.q.isNotBlank() -> Triple(R.drawable.ic_m_search, stringResource(R.string.contacts_empty_search_title), stringResource(R.string.contacts_empty_search, listing.q.trim()))
        listing.kind == ContactKinds.ORG -> Triple(R.drawable.ic_m_users, stringResource(R.string.contacts_empty_org_title), stringResource(R.string.contacts_empty_org))
        else -> Triple(R.drawable.ic_m_users, stringResource(R.string.contacts_empty_title), stringResource(R.string.contacts_empty))
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 56.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        MIcon(icon, null, size = 32.dp, tint = scheme.onSurfaceVariant)
        Spacer(Modifier.height(6.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Medium)
        Spacer(Modifier.height(4.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, textAlign = TextAlign.Center)
    }
}

/** Une ligne (`.cx-row`) : son rond, son nom, son poste et son organisation (ou ce qu'est une organisation), d'où elle
 *  le connaît et combien, le dernier échange. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ContactRow(c: ContactLine, now: Long, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
        ContactAvatar(c.name, contactKey(c.id), c.org)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(c.name, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(8.dp))
                Text(MoiDates.short(c.last, now), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
            }
            val sub = lineSub(c)
            if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (c.sources.isNotEmpty()) {
                FlowRow(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                    for (s in c.sources) {
                        val described = if (s.count > 0) "${s.label} · ${s.count}" else s.label
                        Row(Modifier.semantics { contentDescription = described }, verticalAlignment = Alignment.CenterVertically) {
                            MIcon(sourceIcon(s.source), null, size = 14.dp, tint = scheme.onSurfaceVariant)
                            if (s.count > 0) {
                                Spacer(Modifier.width(3.dp))
                                Text("${s.count}", style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
        }
    }
}
