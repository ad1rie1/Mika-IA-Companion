package fr.qwartz.mika.ui.mail

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxDefaults
import androidx.compose.material3.SwipeToDismissBoxState
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.levelTag
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailRow
import fr.qwartz.mika.data.moi.mail.MailStates
import fr.qwartz.mika.data.moi.mail.MailView
import fr.qwartz.mika.data.moi.mail.SentMail
import fr.qwartz.mika.data.moi.mail.allUnseen
import fr.qwartz.mika.data.moi.mail.boxTitle
import fr.qwartz.mika.data.moi.mail.howLabel
import fr.qwartz.mika.data.moi.mail.inboxOf
import fr.qwartz.mika.data.moi.mail.manyBoxes
import fr.qwartz.mika.data.moi.mail.swipeTrashable
import fr.qwartz.mika.data.moi.mail.triageMark
import fr.qwartz.mika.data.moi.mail.viewTitle
import fr.qwartz.mika.data.moi.mail.waitingYours
import fr.qwartz.mika.data.moi.mail.writableBoxes
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaLine
import fr.qwartz.mika.ui.shell.MikaMark
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SearchBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import fr.qwartz.mika.ui.theme.states
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.launch

/** La liste se relit à ce rythme tant qu'elle est à l'écran (comme le client web). */
private const val REFRESH_MS = 60_000L

/**
 * Mail, la rubrique du tiroir (ADR 0235, la maquette `ecrans/mail.js`) : le titre est la vue et ouvre la feuille des
 * boîtes ; les puces filtrent ; la loupe cherche ; « Ses brouillons » en bandeau rose ; les lignes, groupées par jour,
 * avec ton non-lu (le point indigo) à part de ce qu'elle en a fait (en rose) ; un appui long sélectionne ; « Écrire »
 * en bouton flottant.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MailListScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: MailListViewModel = viewModel(key = "mail.list|$session") { MailListViewModel(MailDeps(graph)) }
    var sheet by rememberSaveable { mutableStateOf(false) }
    var moving by remember { mutableStateOf(false) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    // une ligne glissée à la corbeille : « Annuler » la remet dans son dossier, le temps du message
    val trashedText = stringResource(R.string.mail_trashed)
    val undoText = stringResource(R.string.mail_trash_undo)
    LaunchedEffect(vm) {
        vm.trashed.collect { t ->
            if (t.row.folder.isBlank()) shell.toast(trashedText) else shell.offer(trashedText, undoText) { vm.untrash(t) }
        }
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                vm.resume()
                delay(REFRESH_MS)
            }
        }
    }
    val selecting = vm.selected.isNotEmpty()
    LaunchedEffect(selecting) { if (!selecting) moving = false }
    BackHandler(enabled = selecting) { vm.clearSelection() }
    BackHandler(enabled = !selecting && vm.searching) { vm.closeSearch() }

    val boxes = vm.boxList
    val listState = rememberLazyListState()
    val readOnly = stringResource(R.string.mail_read_only_tidy)
    val noPoll = stringResource(R.string.mail_poll_none)
    val manyBoxesMove = stringResource(R.string.mail_move_many_boxes)
    SectionScaffold(
        topBar = {
            when {
                selecting -> SelectionBar(
                    count = vm.selected.size,
                    unread = vm.selectionUnread,
                    flagged = vm.selectionFlagged,
                    onClose = vm::clearSelection,
                    onGesture = { vm.tidySelected(it) },
                    onMove = { if (vm.moveChoices() == null) shell.toast(manyBoxesMove) else moving = true },
                )
                vm.searching -> SearchBar(vm.query, stringResource(R.string.mail_search_hint), vm::search, vm::closeSearch)
                else -> MikaTopBar(
                    title = viewTitle(vm.view, boxes),
                    nav = BarNav.DRAWER,
                    subtitle = listSubtitle(vm.view, boxes, vm.common.size),
                    onTitle = { sheet = true },
                ) {
                    BarAction(R.drawable.ic_m_search, stringResource(R.string.mail_search), vm::openSearch)
                    BarMenu(
                        listOf(
                            MenuEntry(stringResource(R.string.mail_poll), R.drawable.ic_m_refresh) { vm.poll(noPoll) },
                            MenuEntry(stringResource(R.string.mail_settings_boxes), R.drawable.ic_m_settings) { shell.navigate(Route.SettingsPage("boites")) },
                        ),
                    )
                }
            }
        },
        floatingActionButton = {
            if (!selecting && writableBoxes(boxes).isNotEmpty()) {
                val expanded by remember { derivedStateOf { listState.firstVisibleItemIndex == 0 } }
                ExtendedFloatingActionButton(
                    text = { Text(stringResource(R.string.mail_write)) },
                    icon = { MIcon(R.drawable.ic_m_pen, null) },
                    onClick = { shell.navigate(Route.MailCompose()) },
                    expanded = expanded,
                )
            }
        },
    ) { modifier ->
        val loadedBoxes = vm.boxes.valueOrNull
        when {
            loadedBoxes != null && !loadedBoxes.plugged -> Notice(stringResource(R.string.mail_unplugged), modifier)
            loadedBoxes != null && loadedBoxes.boxes.isEmpty() -> Notice(
                stringResource(R.string.mail_no_box),
                modifier,
                action = stringResource(R.string.mail_settings_boxes),
                onAction = { shell.navigate(Route.SettingsPage("boites")) },
            )
            else -> Column(modifier) {
                if (vm.view !is MailView.Sent) FilterChips(vm.filter, vm.needsReply, vm::toggleFilter)
                PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = Modifier.fillMaxSize()) {
                    LoadBox(vm.listing, onRetry = vm::retry) { listing ->
                        MailList(
                            vm = vm,
                            listing = listing,
                            listState = listState,
                            onOpen = { shell.navigate(Route.MailMessage(it)) },
                            onLong = { vm.toggle(it, readOnly) },
                            onDrafts = { shell.navigate(Route.MailDrafts) },
                        )
                    }
                }
            }
        }
    }
    if (sheet) {
        MailBoxesSheet(
            boxes = boxes,
            view = vm.view,
            onView = vm::showView,
            onDrafts = { shell.navigate(Route.MailDrafts) },
            onSettings = { shell.navigate(Route.SettingsPage("boites")) },
            onDismiss = { sheet = false },
        )
    }
    val choices = if (moving) vm.moveChoices() else null
    if (choices != null) {
        FolderPicker(choices.first, choices.second, onPick = { f -> moving = false; vm.tidySelected("move", f.name) }, onDismiss = { moving = false })
    }
}

/** La ligne sous le titre : combien de boîtes et de non-lus ; une boîte partagée dit son niveau. */
@Composable
private fun listSubtitle(view: MailView, boxes: List<MailBox>, common: Int): String {
    val box = view.boxKey?.let { key -> boxes.firstOrNull { it.key == key } }
    return when {
        boxes.isEmpty() -> ""
        view == MailView.All -> {
            val unseen = allUnseen(boxes)
            val n = pluralStringResource(R.plurals.mail_boxes_count, common, common)
            if (unseen > 0) "$n · ${pluralStringResource(R.plurals.mail_unseen_count, unseen, unseen)}" else n
        }
        box == null -> ""
        view is MailView.Sent -> boxTitle(box, boxes)
        !box.own -> listOf(levelTag(box.level), box.ownerName).filter { it.isNotBlank() }.joinToString(" · ")
        else -> {
            val folder = (view as MailView.Folder).folder
            val f = box.folders.firstOrNull { it.name == folder }
            val unseen = f?.unseen ?: 0
            val where = if (f == null || f == inboxOf(box)) box.address else boxTitle(box, boxes)
            if (unseen > 0) "$where · ${pluralStringResource(R.plurals.mail_unseen_count, unseen, unseen)}" else where
        }
    }
}

/** Les puces de la maquette : un seul filtre à la fois ; « Où Mika est passée » en rose. */
@Composable
private fun FilterChips(filter: String, needsReply: Int, onToggle: (String) -> Unit) {
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Chip(stringResource(R.string.mail_filter_needs_reply), R.drawable.ic_m_reply, filter == MailStates.NEEDS_REPLY, count = needsReply) { onToggle(MailStates.NEEDS_REPLY) }
        Chip(stringResource(R.string.mail_filter_unread), R.drawable.ic_m_mail, filter == MailStates.UNREAD) { onToggle(MailStates.UNREAD) }
        Chip(stringResource(R.string.mail_filter_flagged), R.drawable.ic_m_flag, filter == MailStates.FLAGGED) { onToggle(MailStates.FLAGGED) }
        Chip(stringResource(R.string.mail_filter_noticed), R.drawable.ic_m_eye, filter == MailStates.NOTICED, pink = true) { onToggle(MailStates.NOTICED) }
    }
}

@Composable
private fun Chip(label: String, icon: Int, selected: Boolean, count: Int = 0, pink: Boolean = false, onClick: () -> Unit) {
    val pinkColors = FilterChipDefaults.filterChipColors(
        labelColor = mika.accent,
        iconColor = mika.accent,
        selectedContainerColor = mika.container,
        selectedLabelColor = mika.onContainer,
        selectedLeadingIconColor = mika.onContainer,
    )
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = { Text(if (count > 0) "$label  $count" else label) },
        leadingIcon = { MIcon(icon, null, size = 18.dp) },
        colors = if (pink) pinkColors else FilterChipDefaults.filterChipColors(),
        border = if (pink) FilterChipDefaults.filterChipBorder(enabled = true, selected = selected, borderColor = mika.line) else FilterChipDefaults.filterChipBorder(enabled = true, selected = selected),
    )
}

/** Une ligne de la liste : un en-tête de jour, un mail reçu, un envoi, ou le bandeau de ses brouillons. */
private sealed interface Item {
    val key: String

    data class Head(val text: String, val at: Int) : Item {
        override val key = "head:$at:$text"
    }

    data class Mail(val row: MailRow) : Item {
        override val key = "mail:${row.ref}"
    }

    data class Out(val sent: SentMail) : Item {
        override val key = "sent:${sent.ref}"
    }
}

@Composable
private fun MailList(
    vm: MailListViewModel,
    listing: MailListing,
    listState: androidx.compose.foundation.lazy.LazyListState,
    onOpen: (String) -> Unit,
    onLong: (MailRow) -> Unit,
    onDrafts: () -> Unit,
) {
    val now = rememberNow()
    val boxes = vm.boxList
    val many = manyBoxes(vm.view, boxes)
    val waiting = waitingYours(boxes, vm.view)
    val items = remember(listing, now) {
        val out = mutableListOf<Item>()
        var group = ""
        val rows = if (listing.sent.isNotEmpty()) listing.sent.map { it.date to Item.Out(it) } else listing.rows.map { it.date to Item.Mail(it) }
        for ((date, item) in rows) {
            val g = MoiDates.group(date, now)
            if (g != group) {
                out += Item.Head(g, out.size)
                group = g
            }
            out += item
        }
        out
    }
    // la page suivante, quand la fin de la liste approche
    LaunchedEffect(listState, listing) {
        snapshotFlow { listState.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0 }
            .distinctUntilChanged()
            .filter { last -> last >= listState.layoutInfo.totalItemsCount - 4 }
            .collect { vm.loadMore() }
    }
    LazyColumn(state = listState, modifier = Modifier.fillMaxSize()) {
        if (waiting > 0) {
            item(key = "drafts") {
                MikaLine(
                    icon = R.drawable.ic_m_pen,
                    title = stringResource(R.string.mail_her_drafts),
                    subtitle = pluralStringResource(R.plurals.mail_her_drafts_waiting, waiting, waiting),
                    count = waiting,
                    onClick = onDrafts,
                    modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 6.dp),
                )
            }
        }
        if (items.isEmpty()) {
            item(key = "empty") {
                Text(
                    emptyText(vm.filter, vm.query, vm.view),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(32.dp),
                )
            }
        }
        items(items, key = { it.key }) { item ->
            when (item) {
                is Item.Head -> ListHead(item.text, muted = true)
                is Item.Mail -> SwipeToTrash(
                    allowed = swipeTrashable(item.row, vm.boxOf(item.row.box)),
                    enabled = vm.selected.isEmpty(),
                    pending = item.row.ref in vm.trashing,
                    onTrash = { vm.swipeTrash(item.row) },
                ) {
                    MailRowItem(
                        row = item.row,
                        now = now,
                        boxName = if (many) vm.boxOf(item.row.box)?.let { boxTitle(it, boxes) } else null,
                        selected = item.row.ref in vm.selected,
                        onClick = { if (vm.selected.isNotEmpty()) onLong(item.row) else onOpen(item.row.ref) },
                        onLong = { onLong(item.row) },
                    )
                }
                is Item.Out -> SentRowItem(item.sent, now, onClick = { onOpen(item.sent.ref) })
            }
        }
        if (vm.loadingMore) {
            item(key = "more") {
                Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(24.dp)) }
            }
        }
        // de quoi faire défiler la dernière ligne au-dessus du bouton « Écrire »
        item(key = "end") { Spacer(Modifier.padding(bottom = 80.dp)) }
    }
}

@Composable
private fun emptyText(filter: String, query: String, view: MailView): String = when {
    query.isNotBlank() -> stringResource(R.string.mail_empty_search, query.trim())
    view is MailView.Sent -> stringResource(R.string.mail_empty_sent)
    filter == MailStates.NEEDS_REPLY -> stringResource(R.string.mail_empty_needs_reply)
    filter == MailStates.UNREAD -> stringResource(R.string.mail_empty_unread)
    filter == MailStates.FLAGGED -> stringResource(R.string.mail_empty_flagged)
    filter == MailStates.NOTICED -> stringResource(R.string.mail_empty_noticed)
    else -> stringResource(R.string.mail_empty)
}

/** Un mail de la liste (`.mail-row` de la maquette). */
@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
private fun MailRowItem(
    row: MailRow,
    now: Long,
    boxName: String?,
    selected: Boolean,
    onClick: () -> Unit,
    onLong: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val unread = !row.seen
    val from = row.from.shown.ifBlank { stringResource(R.string.mail_no_sender) }
    Row(
        Modifier
            .fillMaxWidth()
            .background(if (selected) scheme.secondaryContainer else Color.Transparent)
            .combinedClickable(onClick = onClick, onLongClick = onLong)
            .padding(horizontal = 16.dp, vertical = 10.dp),
    ) {
        if (selected) {
            Box(Modifier.size(40.dp).clip(CircleShape).background(scheme.primary), contentAlignment = Alignment.Center) {
                MIcon(R.drawable.ic_m_check, stringResource(R.string.mail_selected), tint = scheme.onPrimary, size = 22.dp)
            }
        } else {
            PersonAvatar(from, row.from.address)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    from,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    MoiDates.short(row.date, now),
                    style = MaterialTheme.typography.labelMedium,
                    color = if (unread) scheme.primary else scheme.onSurfaceVariant,
                    fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal,
                )
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    row.subject.ifBlank { stringResource(R.string.mail_no_subject) },
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (row.attachments > 0) MIcon(R.drawable.ic_m_clip, stringResource(R.string.mail_has_pieces), size = 16.dp, tint = scheme.onSurfaceVariant)
                if (row.flagged) MIcon(R.drawable.ic_m_flag, stringResource(R.string.mail_flagged), size = 16.dp, tint = scheme.primary)
                if (row.her?.important == true) MIcon(R.drawable.ic_m_star, stringResource(R.string.mail_important), size = 16.dp, tint = states.warn)
                if (unread) {
                    Spacer(Modifier.width(6.dp))
                    UnreadDot()
                }
            }
            if (row.snippet.isNotBlank()) {
                Text(row.snippet, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            val her = row.her
            val sorted = triageMark(row.triage)
            val marks = boxName != null || her?.needsReply == true || her?.draft?.isNotBlank() == true || her?.asked == true || her?.read == true || row.answered || sorted != null
            if (marks) {
                FlowRow(
                    Modifier.padding(top = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    if (boxName != null) Tag(boxName, Tone.NEUTRAL)
                    if (her?.needsReply == true) Tag(stringResource(R.string.mail_needs_reply), Tone.WARN)
                    if (her?.draft?.isNotBlank() == true) {
                        Tag(stringResource(R.string.mail_her_draft_tag), Tone.MIKA, R.drawable.ic_m_pen)
                    } else if (her?.asked == true) {
                        MikaMark(stringResource(R.string.mail_her_asked), R.drawable.ic_m_sparkle)
                    }
                    if (her?.read == true) {
                        val (text, kind) = howLabel(her.how)
                        MikaMark(text, howIcon(kind))
                    }
                    if (sorted != null) TriageMark(sorted)
                    if (row.answered) Tag(stringResource(R.string.mail_answered), Tone.NEUTRAL)
                }
            }
        }
    }
}

/**
 * Une ligne qui se glisse d'un côté ou de l'autre vers la corbeille : un fond rouge, la corbeille du côté où l'on
 * glisse. [allowed] : là où la barre de rangement la rangerait ([swipeTrashable]) ; [enabled] : pas pendant une
 * sélection ; [pending] : le serveur n'a pas encore répondu — elle reste écartée, puis s'en va ; refusée, elle revient.
 * [onTrash] faux : rien n'est parti, elle revient aussitôt.
 * Un lecteur d'écran a la même chose en action (« Corbeille »).
 */
@Composable
private fun SwipeToTrash(allowed: Boolean, enabled: Boolean, pending: Boolean, onTrash: () -> Boolean, content: @Composable () -> Unit) {
    if (!allowed) {
        content()
        return
    }
    val threshold = SwipeToDismissBoxDefaults.positionalThreshold
    // pas `rememberSwipeToDismissBoxState`, qui se garde : une ligne refusée hors de l'écran reviendrait écartée, et
    // repartirait d'elle-même à la corbeille
    val state = remember { SwipeToDismissBoxState(SwipeToDismissBoxValue.Settled, threshold) }
    val scope = rememberCoroutineScope()
    // parti au serveur d'ici : sa réponse arrivée (la ligne encore là, donc refusée), elle revient — même si un serveur
    // proche a répondu avant l'image suivante, sans que [pending] ait jamais paru vrai
    var sent by remember { mutableStateOf(false) }
    LaunchedEffect(sent, pending) {
        if (sent && !pending) {
            state.reset()
            sent = false
        }
    }
    val label = stringResource(R.string.mail_trash)
    SwipeToDismissBox(
        state = state,
        backgroundContent = { TrashBehind(state.dismissDirection) },
        modifier = Modifier.semantics {
            if (enabled) customActions = listOf(CustomAccessibilityAction(label) { onTrash() })
        },
        gesturesEnabled = enabled,
        onDismiss = { if (onTrash()) sent = true else scope.launch { state.reset() } },
    ) {
        // la ligne est opaque : le rouge ne paraît que là où elle s'est écartée
        Box(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.background)) { content() }
    }
}

/** Le fond d'une ligne qu'on glisse : rouge, la corbeille du côté où elle s'écarte. */
@Composable
private fun TrashBehind(direction: SwipeToDismissBoxValue) {
    if (direction == SwipeToDismissBoxValue.Settled) return
    val scheme = MaterialTheme.colorScheme
    Box(
        Modifier.fillMaxSize().background(scheme.error).padding(horizontal = 24.dp),
        contentAlignment = if (direction == SwipeToDismissBoxValue.StartToEnd) Alignment.CenterStart else Alignment.CenterEnd,
    ) {
        MIcon(R.drawable.ic_m_trash, null, tint = scheme.onError)
    }
}

/** L'icône de ce qu'elle a fait d'un mail. */
internal fun howIcon(kind: String): Int = when (kind) {
    "archive" -> R.drawable.ic_m_archive
    "trash" -> R.drawable.ic_m_trash
    "reply" -> R.drawable.ic_m_reply
    else -> R.drawable.ic_m_eye
}

/** Ce qui est parti d'une boîte (la vue « Envoyés »). */
@Composable
private fun SentRowItem(sent: SentMail, now: Long, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val first = sent.to.firstOrNull()
    val names = sent.to.map { it.shown }
    val to = when {
        names.isEmpty() -> stringResource(R.string.mail_nobody)
        names.size > 2 -> "${names.take(2).joinToString(", ")} +${names.size - 2}"
        else -> names.joinToString(", ")
    }
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp),
    ) {
        PersonAvatar(first?.shown ?: "?", first?.address ?: "?")
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.mail_to_names, to), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(8.dp))
                Text(MoiDates.short(sent.date, now), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(sent.subject.ifBlank { stringResource(R.string.mail_no_subject) }, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                if (sent.attachments > 0) MIcon(R.drawable.ic_m_clip, stringResource(R.string.mail_has_pieces), size = 16.dp, tint = scheme.onSurfaceVariant)
            }
            if (sent.snippet.isNotBlank()) {
                Text(sent.snippet, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (sent.by.isBlank()) {
                Spacer(Modifier.padding(top = 4.dp))
                MikaMark(stringResource(R.string.mail_sent_by_her), R.drawable.ic_m_pen)
            }
        }
    }
}

/** La barre du haut pendant une sélection : combien, et les gestes de « ranger ». */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SelectionBar(count: Int, unread: Boolean, flagged: Boolean, onClose: () -> Unit, onGesture: (String) -> Unit, onMove: () -> Unit) {
    TopAppBar(
        navigationIcon = { BarAction(R.drawable.ic_m_x, stringResource(R.string.mail_selection_cancel), onClose) },
        title = { Text(pluralStringResource(R.plurals.mail_selected_count, count, count)) },
        actions = {
            BarAction(R.drawable.ic_m_archive, stringResource(R.string.mail_archive), { onGesture("archive") })
            if (unread) {
                BarAction(R.drawable.ic_m_check, stringResource(R.string.mail_mark_read), { onGesture("read") })
            } else {
                BarAction(R.drawable.ic_m_mail, stringResource(R.string.mail_mark_unread), { onGesture("unread") })
            }
            BarAction(R.drawable.ic_m_flag, stringResource(if (flagged) R.string.mail_unflag else R.string.mail_flag), { onGesture(if (flagged) "unflag" else "flag") })
            BarAction(R.drawable.ic_m_trash, stringResource(R.string.mail_trash), { onGesture("trash") })
            BarMenu(listOf(MenuEntry(stringResource(R.string.mail_move), R.drawable.ic_m_folder, onMove)))
        },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
    )
}
