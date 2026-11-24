package fr.qwartz.mika.ui.teams

import androidx.compose.animation.animateColorAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.onLongClick
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Caps
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.TeamsLive
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.Mark
import fr.qwartz.mika.data.moi.teams.OwnBubble
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsLimits
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.data.moi.teams.TeamsQuote
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.YOU
import fr.qwartz.mika.data.moi.teams.authorLabel
import fr.qwartz.mika.data.moi.teams.capsOf
import fr.qwartz.mika.data.moi.teams.citable
import fr.qwartz.mika.data.moi.teams.fromHer
import fr.qwartz.mika.data.moi.teams.fromYou
import fr.qwartz.mika.data.moi.teams.isGroup
import fr.qwartz.mika.data.moi.teams.lastReceived
import fr.qwartz.mika.data.moi.teams.mentionRanges
import fr.qwartz.mika.data.moi.teams.ownBubbles
import fr.qwartz.mika.data.moi.teams.prefillOff
import fr.qwartz.mika.data.moi.teams.quietLine
import fr.qwartz.mika.data.moi.teams.quoteAuthor
import fr.qwartz.mika.data.moi.teams.quoteExcerpt
import fr.qwartz.mika.data.moi.teams.quoteTarget
import fr.qwartz.mika.data.moi.teams.quoteWhen
import fr.qwartz.mika.data.moi.teams.readOnlyLine
import fr.qwartz.mika.data.moi.teams.selfName
import fr.qwartz.mika.data.moi.teams.sentUnder
import fr.qwartz.mika.data.moi.teams.threadCards
import fr.qwartz.mika.data.moi.teams.threadMarks
import fr.qwartz.mika.data.moi.teams.threadSubtitle
import fr.qwartz.mika.data.moi.thousands
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.WorkLine
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.CorrectIconButton
import fr.qwartz.mika.ui.shell.CorrectNotices
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.SheetLine
import fr.qwartz.mika.ui.shell.linked
import fr.qwartz.mika.ui.shell.rememberCorrectWords
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.delay

/**
 * Une discussion (la maquette, `vueFil`) : les autres à gauche (leur nom dans un groupe), toi à droite — « Toi »
 * seulement sur un compte à toi ; sur un compte qu'on te partage, son propriétaire à son nom, à gauche —, tes mentions
 * marquées, « Messages plus anciens » en haut, tes messages en attente avec leur état. Ses réponses en carte rose
 * au-dessus du champ ; le champ : ✦ Préremplir et ✓ Corriger (ADR 0307) à gauche, envoyer à droite, et dessous sous
 * quel nom ça part. Un compte qu'on ne te partage qu'en lecture n'a pas de champ : une phrase le dit. ⋮ : « Comment ça
 * part ». La citation (ADR 0305), calquée sur Teams mobile : un appui long sur un message ouvre sa feuille, « Citer »
 * pose sa carte au-dessus du champ ; un message qui en cite un autre le montre en haut de sa bulle, et un appui y mène.
 */
@Composable
fun TeamsThreadScreen(graph: AppGraph, key: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: TeamsThreadViewModel = viewModel(key = "teams.thread|$session") { TeamsThreadViewModel(TeamsDeps(graph)) }
    val arrived = stringResource(R.string.teams_arrived)
    LaunchedEffect(key) { vm.open(key, arrived) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    // le compte de ce fil n'est plus à toi (retiré, plus partagé) : retour à la liste
    LaunchedEffect(vm, key) { vm.left.collect { if (it == key) shell.back() } }
    // « Corriger » (ADR 0307) : combien de fautes, avec « Annuler » quand ton texte a été remplacé
    CorrectNotices(vm.corrector)
    // le direct (ADR 0308) : le fil se relit quand il change, où elle en est d'une réponse quand elle y travaille
    // (ADR 0306) ; relu une fois à chaque retour de l'app au premier plan (l'ouverture, elle, est celle de `open`)
    FollowLive(graph.live, TeamsLive.THREAD, vm, key, onShown = { first -> if (!first) vm.refresh() }) { vm.onLive(it) }
    var asking by remember { mutableStateOf<Pair<Ask, TeamsReply>?>(null) }
    // l'appui long sur un message : sa feuille ; « Citer » rend la main au champ (le clavier monte, comme dans Teams)
    var acting by remember { mutableStateOf<TeamsMessage?>(null) }
    var focusAsk by remember { mutableIntStateOf(0) }
    val t = vm.current?.takeIf { vm.key == key }
    val account = t?.let { vm.account(it.account) }
    // qui est connecté : son nom, sous lequel part ce qu'on écrit d'un compte à soi, et sa mention
    val me by graph.me.me.collectAsStateWithLifecycle()
    val myName = me?.shown.orEmpty()
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = t?.title?.ifBlank { stringResource(R.string.teams_untitled) } ?: stringResource(R.string.nav_teams),
                nav = BarNav.BACK,
                subtitle = t?.let { threadSubtitle(it.kind, account, vm.accountList.size) },
                face = false,
            ) {
                BarMenu(
                    buildList {
                        add(MenuEntry(stringResource(R.string.teams_how), R.drawable.ic_m_shield) { shell.navigate(Route.Tools()) })
                        if (capsOf(account).prepare) add(MenuEntry(stringResource(R.string.teams_her_replies), R.drawable.ic_m_pen) { shell.navigate(Route.TeamsReplies) })
                    },
                )
            }
        },
        bottomBar = {
            if (t != null) Dock(vm, t, account, myName, me?.correct == true, focusAsk, onAsk = { a, r -> asking = a to r })
        },
    ) { modifier ->
        LoadBox(if (vm.key == key) vm.thread else Load.Loading, onRetry = vm::retry, modifier = modifier) { thread ->
            Messages(vm, thread, account, selfName(account, myName), acting = acting?.ref, onLong = { acting = it }, modifier = modifier)
        }
    }
    asking?.let { (a, r) -> ReplyAskDialog(a, r, vm) { asking = null } }
    acting?.let { m ->
        MessageSheet(
            onCite = {
                vm.cite(m)
                focusAsk++
            },
            onDismiss = { acting = null },
        )
    }
}

/** Le message où une citation a mené s'éclaire ce temps-là (comme dans Teams). */
private const val JUMP_GLOW_MS = 1_600L

/** « Citer » : le champ prend la main une fois la feuille refermée. */
private const val FOCUS_AFTER_SHEET_MS = 250L

/**
 * La feuille d'un message (l'appui long, comme dans Teams mobile) : « Citer » — sa carte se pose au-dessus du champ, et
 * ton prochain message le cite. Seulement sur un message qui se cite ici ([citable]).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun MessageSheet(onCite: () -> Unit, onDismiss: () -> Unit) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 12.dp)) {
            SheetLine(
                icon = R.drawable.ic_m_quote,
                title = stringResource(R.string.teams_cite),
                subtitle = stringResource(R.string.teams_cite_line),
                count = 0,
                selected = false,
                onClick = {
                    onDismiss()
                    onCite()
                },
            )
        }
    }
}

/** Une ligne du fil : un repère, un message, un des tiens en attente. */
private sealed interface Line {
    val id: String

    data class Older(val loading: Boolean) : Line {
        override val id = "older"
    }

    data object Start : Line {
        override val id = "start"
    }

    data object Empty : Line {
        override val id = "empty"
    }

    data class Day(val text: String, val ref: String) : Line {
        override val id = "day:$ref"
    }

    data class Message(val m: TeamsMessage, val mark: Mark) : Line {
        override val id = "m:${m.ref}"
    }

    data class Own(val b: OwnBubble, val n: Int) : Line {
        override val id = "own:${b.id.ifEmpty { "here$n" }}"
    }
}

@Composable
private fun Messages(
    vm: TeamsThreadViewModel,
    t: ConversationThread,
    account: TeamsAccount?,
    selfName: String,
    acting: String?,
    onLong: (TeamsMessage) -> Unit,
    modifier: Modifier,
) {
    val now = rememberNow()
    val messages = vm.messages
    val caps = capsOf(account)
    val group = isGroup(t.kind)
    val busy = stringResource(R.string.teams_field_busy)
    val lines = remember(messages, t, vm.sent, vm.loadingOlder, vm.more, now) {
        val marks = threadMarks(messages, now)
        buildList {
            when {
                vm.more -> add(Line.Older(vm.loadingOlder))
                messages.isNotEmpty() -> add(Line.Start)
                else -> add(Line.Empty)
            }
            messages.forEachIndexed { i, m ->
                if (marks[i].day.isNotEmpty()) add(Line.Day(marks[i].day, m.ref))
                add(Line.Message(m, marks[i]))
            }
            ownBubbles(t.pending, vm.sent.filter { it.conversation == t.key }, sentUnder(account)).forEachIndexed { i, b -> add(Line.Own(b, i)) }
        }.asReversed()
    }
    // un appui sur une citation : le fil va au message cité (au tiers du bas), qui s'éclaire un instant
    val list = rememberLazyListState()
    var glowing by remember { mutableStateOf<String?>(null) }
    val jump = vm.jump
    LaunchedEffect(jump) {
        if (jump == null) return@LaunchedEffect
        glowing = null
        val at = lines.indexOfFirst { it is Line.Message && it.m.ref == jump.ref }
        if (at >= 0) {
            list.animateScrollToItem(at)
            list.animateScrollBy(-list.layoutInfo.viewportSize.height / 3f)
            glowing = jump.ref
        }
        vm.jumped(jump)
    }
    LaunchedEffect(glowing) {
        if (glowing == null) return@LaunchedEffect
        delay(JUMP_GLOW_MS)
        glowing = null
    }
    // le plus récent en bas : la liste part du bas, les plus anciens s'ajoutent en haut sans la faire bouger
    LazyColumn(modifier.fillMaxSize(), state = list, reverseLayout = true, contentPadding = PaddingValues(vertical = 8.dp)) {
        items(lines, key = { it.id }) { line ->
            when (line) {
                is Line.Older -> Box(Modifier.fillMaxWidth().padding(4.dp), contentAlignment = Alignment.Center) {
                    TextButton(onClick = vm::loadOlder, enabled = !line.loading) {
                        MIcon(R.drawable.ic_m_history, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(if (line.loading) R.string.teams_loading else R.string.teams_older))
                    }
                }
                Line.Start -> Text(
                    stringResource(R.string.teams_start),
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(12.dp),
                    textAlign = TextAlign.Center,
                )
                Line.Empty -> Text(
                    stringResource(R.string.teams_thread_empty),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().padding(32.dp),
                    textAlign = TextAlign.Center,
                )
                is Line.Day -> DayMark(line.text)
                is Line.Message -> {
                    val m = line.m
                    val shown = m.quote?.let { q ->
                        ShownQuote(q, quoteAuthor(q, messages, account), quoteWhen(q.at, now), quoteTarget(q, messages) != null)
                    }
                    MessageRow(
                        m, line.mark, account, group, selfName, fromHer(m, t.replies),
                        quote = shown,
                        glow = m.ref == glowing || m.ref == acting,
                        onLong = if (citable(m, t.kind, account)) ({ onLong(m) }) else null,
                        onJump = { q -> vm.jumpTo(q) },
                    )
                }
                is Line.Own -> OwnRow(line.b, canRewrite = caps.write) { vm.rewrite(line.b.id, busy) }
            }
        }
    }
}

/** Un repère de jour, au milieu (`.day` de la maquette). */
@Composable
private fun DayMark(text: String) {
    Box(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 6.dp), contentAlignment = Alignment.Center) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.clip(RoundedCornerShape(10.dp)).background(MaterialTheme.colorScheme.surfaceContainerHigh).padding(horizontal = 10.dp, vertical = 3.dp),
        )
    }
}

/** La forme d'une bulle : arrondie, sauf le coin du côté de qui parle. */
private fun bubbleShape(mine: Boolean) =
    if (mine) RoundedCornerShape(20.dp, 20.dp, 6.dp, 20.dp) else RoundedCornerShape(20.dp, 20.dp, 20.dp, 6.dp)

/** La citation d'un message, telle que sa bulle la montre : ce qu'il cite, qui l'a écrit et quand, et si un appui y
 *  mène (le message cité est parmi ceux chargés). */
private data class ShownQuote(val q: TeamsQuote, val author: String, val whenText: String, val reachable: Boolean)

/** L'appui long sur une bulle (ses gestes) : sans onde au simple appui (un message ne s'ouvre pas), dit à TalkBack sous
 *  [label]. [key] : le message (le geste se repose quand il change). */
private fun Modifier.longPress(key: Any, label: String, action: () -> Unit): Modifier =
    pointerInput(key) { detectTapGestures(onLongPress = { action() }) }
        .semantics { onLongClick(label) { action(); true } }

/**
 * Un message (`.tmsg` de la maquette) : les autres à gauche avec leur rond (leur nom au-dessus dans un groupe), toi à
 * droite en indigo ; la suite d'un même auteur se serre. Une mention de toi : un filet indigo à gauche de la bulle, et
 * ton nom en gras. Ce qu'il cite, en haut de sa bulle (comme Teams) ; [onLong] : l'appui long ouvre ses gestes (`null` :
 * il ne se cite pas ici) ; [glow] : le message où une citation vient de mener, ou celui dont la feuille est ouverte.
 */
@Composable
private fun MessageRow(
    m: TeamsMessage,
    mark: Mark,
    account: TeamsAccount?,
    group: Boolean,
    selfName: String,
    byMika: Boolean,
    quote: ShownQuote?,
    glow: Boolean,
    onLong: (() -> Unit)?,
    onJump: (TeamsQuote) -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val mine = fromYou(m, account)
    val name = authorLabel(m, account)
    val bg = if (mine) scheme.primary else scheme.surfaceContainerHigh
    val fg = if (mine) scheme.onPrimary else scheme.onSurface
    val link = if (mine) scheme.onPrimary else scheme.primary
    val ranges = remember(m.text, selfName, m.mentionsMe) { mentionRanges(m.text, selfName, m.mentionsMe) }
    val text = remember(m.text, ranges, link) {
        buildAnnotatedString {
            append(linked(m.text, link))
            for (r in ranges) {
                addStyle(SpanStyle(fontWeight = FontWeight.Bold, color = if (mine) Color.Unspecified else scheme.primary), r.first, r.last + 1)
            }
        }
    }
    val bar = scheme.primary
    val glowColor by animateColorAsState(if (glow) scheme.primary.copy(alpha = 0.12f) else Color.Transparent, label = "glow")
    val haptic = LocalHapticFeedback.current
    val actions = stringResource(R.string.teams_message_actions)
    val long by rememberUpdatedState(onLong)
    val press: () -> Unit = {
        long?.let {
            haptic.performHapticFeedback(HapticFeedbackType.LongPress)
            it()
        }
    }
    Row(
        Modifier
            .fillMaxWidth()
            .background(glowColor)
            .padding(start = if (mine) 56.dp else 12.dp, end = if (mine) 12.dp else 40.dp, top = if (mark.suite) 1.dp else 6.dp),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
    ) {
        if (!mine) {
            if (mark.suite) Spacer(Modifier.width(32.dp)) else PersonAvatar(name, m.authorId.ifBlank { name }, 32.dp)
            Spacer(Modifier.width(8.dp))
        }
        Column(horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
            if (!mine && group && !mark.suite) {
                Text(
                    "$name · ${MoiDates.clock(m.at)}",
                    style = MaterialTheme.typography.labelMedium,
                    color = scheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 6.dp, bottom = 2.dp),
                )
            }
            Column(
                Modifier
                    // la citation prend la largeur de la bulle, et la bulle celle du plus large des deux
                    .then(if (quote != null) Modifier.width(IntrinsicSize.Max) else Modifier)
                    .clip(bubbleShape(mine))
                    .background(bg)
                    .then(if (m.mentionsMe) Modifier.drawBehind { drawRect(bar, size = Size(3.dp.toPx(), size.height)) } else Modifier)
                    .then(if (onLong != null) Modifier.longPress(m.ref, actions, press) else Modifier)
                    .padding(horizontal = 14.dp, vertical = 8.dp),
            ) {
                if (quote != null) {
                    QuoteInBubble(quote, mine, onJump = { onJump(quote.q) }, onLong = if (onLong != null) press else null)
                }
                if (m.text.isNotEmpty() || quote == null) {
                    if (quote != null) Spacer(Modifier.height(6.dp))
                    Text(text, style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, lineHeight = 21.sp), color = fg)
                }
            }
            if (mine || !group || byMika) {
                Row(Modifier.padding(horizontal = 6.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(MoiDates.clock(m.at), style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant)
                    if (byMika) {
                        Text(" · ", style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant)
                        MIcon(R.drawable.ic_m_sparkle, null, size = 12.dp, tint = mika.accent)
                        Spacer(Modifier.width(2.dp))
                        Text(stringResource(R.string.teams_by_mika), style = MaterialTheme.typography.labelSmall, color = mika.accent)
                    }
                }
            }
        }
    }
}

/**
 * Ce qu'un message cite, en haut de sa bulle (comme Teams) : une barre d'accent à gauche, son auteur en gras et son
 * heure en petit, l'extrait sur trois lignes au plus. Un appui mène au message cité quand il est chargé ([ShownQuote.reachable]) ;
 * sinon la carte n'est qu'un texte. Sur ta bulle indigo, elle prend ses teintes.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun QuoteInBubble(quote: ShownQuote, mine: Boolean, onJump: () -> Unit, onLong: (() -> Unit)?) {
    val scheme = MaterialTheme.colorScheme
    val fg = if (mine) scheme.onPrimary else scheme.onSurface
    val muted = if (mine) scheme.onPrimary.copy(alpha = 0.78f) else scheme.onSurfaceVariant
    val card = if (mine) scheme.onPrimary.copy(alpha = 0.14f) else scheme.surface
    val bar = if (mine) scheme.onPrimary.copy(alpha = 0.85f) else scheme.primary
    val go = stringResource(R.string.teams_quote_go)
    val actions = stringResource(R.string.teams_message_actions)
    val preview = quoteExcerpt(quote.q.preview)
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(card)
            .drawBehind { drawRect(bar, size = Size(3.dp.toPx(), size.height)) }
            .then(
                if (quote.reachable) {
                    Modifier.combinedClickable(
                        onClickLabel = go,
                        onLongClickLabel = if (onLong != null) actions else null,
                        onLongClick = onLong,
                        // la vibration de l'appui long, la bulle la donne déjà
                        hapticFeedbackEnabled = false,
                        onClick = onJump,
                    )
                } else {
                    Modifier
                },
            )
            .padding(start = 11.dp, end = 10.dp, top = 6.dp, bottom = 6.dp),
    ) {
        if (quote.author.isNotEmpty() || quote.whenText.isNotEmpty()) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (quote.author.isNotEmpty()) {
                    Text(
                        quote.author,
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.SemiBold,
                        color = fg,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                }
                if (quote.whenText.isNotEmpty()) {
                    if (quote.author.isNotEmpty()) Spacer(Modifier.width(6.dp))
                    Text(quote.whenText, style = MaterialTheme.typography.labelSmall, color = muted, maxLines = 1)
                }
            }
        }
        if (preview.isNotEmpty()) {
            Text(preview, style = MaterialTheme.typography.bodyMedium, color = muted, maxLines = 3, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** Un de tes messages pas encore dans le fil : en file, en cours d'envoi, posé, ou pas parti (« Le réécrire »). */
@Composable
private fun OwnRow(b: OwnBubble, canRewrite: Boolean, onRewrite: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val bg = if (b.failed) scheme.errorContainer else scheme.primary.copy(alpha = 0.55f)
    val fg = if (b.failed) scheme.onErrorContainer else scheme.onPrimary
    Column(Modifier.fillMaxWidth().padding(start = 56.dp, end = 12.dp, top = 6.dp), horizontalAlignment = Alignment.End) {
        Text(
            b.text,
            style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, lineHeight = 21.sp),
            color = fg,
            modifier = Modifier.clip(bubbleShape(true)).background(bg).padding(horizontal = 14.dp, vertical = 8.dp),
        )
        Row(Modifier.padding(horizontal = 6.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            MIcon(if (b.failed) R.drawable.ic_m_alert else if (b.sent) R.drawable.ic_m_check else R.drawable.ic_m_clock, null, size = 13.dp, tint = if (b.failed) scheme.error else scheme.onSurfaceVariant)
            Spacer(Modifier.width(4.dp))
            Text(
                "$YOU · ${MoiDates.clock(b.at)} · ${b.note}",
                style = MaterialTheme.typography.labelSmall,
                color = if (b.failed) scheme.error else scheme.onSurfaceVariant,
                modifier = Modifier.weight(1f, fill = false),
            )
        }
        if (b.failed && b.id.isNotEmpty() && canRewrite) {
            TextButton(onClick = onRewrite) { Text(stringResource(R.string.teams_rewrite)) }
        }
    }
}

/**
 * Le bas du fil : ses réponses en carte rose (celles en chemin, et celle à laquelle tu as répondu autrement tant que
 * rien n'est venu depuis), où elle en est d'une réponse ([WorkSlot], ADR 0306), ce qui retient ce qui part, puis le
 * champ — ou, sur un compte qu'on ne te partage qu'en lecture, la phrase qui le dit (et « Préremplir » si ton partage
 * le permet). [canCorrect] : un modèle corrige (ADR 0307). [focusAsk] : « Citer » vient d'être choisi, le champ prend
 * la main.
 */
@Composable
private fun Dock(
    vm: TeamsThreadViewModel,
    t: ConversationThread,
    account: TeamsAccount?,
    myName: String,
    canCorrect: Boolean,
    focusAsk: Int,
    onAsk: (Ask, TeamsReply) -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val now = rememberNow()
    val caps = capsOf(account)
    val messages = vm.messages
    val cards = threadCards(t.replies, messages.lastOrNull()?.at ?: 0)
    val enabled = vm.accounts?.enabled ?: true
    val noReceived = stringResource(R.string.teams_no_received)
    val askedText = stringResource(R.string.teams_prefill_asked)
    val correctWords = rememberCorrectWords()
    Surface(color = scheme.surface) {
        Column(Modifier.navigationBarsPadding().imePadding()) {
            HorizontalDivider()
            if (cards.isNotEmpty()) {
                Column(
                    Modifier.heightIn(max = 320.dp).verticalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    for (r in cards) {
                        ReplyCard(r, account, vm.deciding, now, onAsk = { onAsk(it, r) }, onSend = { vm.sendReply(r) })
                    }
                }
            }
            WorkSlot(vm, underWay = t.underWay)
            if (caps.write) {
                val quiet = quietLine(enabled, account, now)
                if (quiet.isNotEmpty()) {
                    NoteBox(quiet, R.drawable.ic_m_plug, Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
                }
                Composer(
                    vm = vm,
                    account = account,
                    now = now,
                    focusAsk = focusAsk,
                    title = t.title,
                    canPrefill = lastReceived(messages) != null && prefillOff(enabled, account).isEmpty(),
                    sender = selfName(account, myName),
                    onPrefill = { vm.prefill(noReceived, askedText) },
                    canCorrect = canCorrect,
                    onCorrect = { vm.correct(canCorrect, correctWords) },
                )
            } else {
                ReadOnly(account, caps, onPrefill = { vm.prefill(noReceived, askedText) }, prefilling = vm.prefilling)
            }
        }
    }
}

/**
 * Où elle en est d'une réponse ici (ADR 0306), au-dessus du champ, sur une ligne : son visage, l'étape et son chrono.
 * Elle seule lit [TeamsThreadViewModel.work] : quand l'étape change, rien d'autre ne se redessine (ni le fil, ni le
 * champ et ce qu'on y tape). Sa réponse en chemin : plus rien (sa carte rose est là). Un serveur d'avant qui ne dit pas
 * l'étape : « Elle s'y met… », comme avant.
 */
@Composable
private fun WorkSlot(vm: TeamsThreadViewModel, underWay: Boolean) {
    if (underWay) return
    val work = vm.work
    val line = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)
    when {
        work != null -> WorkLine(work, line) { MikaFace(20.dp) }
        vm.asked -> Row(line, verticalAlignment = Alignment.CenterVertically) {
            MikaFace(20.dp)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.teams_working), style = MaterialTheme.typography.bodySmall, color = mika.accent)
        }
    }
}

/** Le champ (`.composer` de la maquette) : au-dessus, le message que tu cites ; ✦ Préremplir et ✓ Corriger (ADR 0307)
 *  à gauche, ton message, envoyer ; dessous, sous quel nom ça part (et le compte des caractères, près de la borne), ou
 *  « Correction… » pendant que ses fautes se corrigent. [focusAsk] : « Citer » vient d'être choisi — le champ prend la
 *  main et le clavier monte, comme dans Teams. */
@Composable
private fun Composer(
    vm: TeamsThreadViewModel,
    account: TeamsAccount?,
    now: Long,
    focusAsk: Int,
    title: String,
    canPrefill: Boolean,
    sender: String,
    onPrefill: () -> Unit,
    canCorrect: Boolean,
    onCorrect: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val focus = remember { FocusRequester() }
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(focusAsk) {
        if (focusAsk > 0) {
            // la feuille d'où vient « Citer » se referme d'abord : sa fenêtre rend la main à celle du fil
            delay(FOCUS_AFTER_SHEET_MS)
            focus.requestFocus()
            keyboard?.show()
        }
    }
    Column(Modifier.padding(start = 4.dp, end = 8.dp, top = 6.dp, bottom = 6.dp)) {
        vm.citing?.let { m -> CitingCard(m, account, now, onCancel = vm::uncite) }
        Row(verticalAlignment = Alignment.Bottom) {
            IconButton(onClick = onPrefill, enabled = !vm.prefilling, modifier = Modifier.alpha(if (canPrefill) 1f else 0.45f)) {
                MIcon(R.drawable.ic_m_sparkle, stringResource(R.string.teams_prefill), tint = mika.accent)
            }
            CorrectIconButton(on = canCorrect, busy = vm.correcting, onClick = onCorrect)
            Box(
                Modifier.weight(1f).heightIn(min = 48.dp).clip(RoundedCornerShape(24.dp)).background(scheme.surfaceContainerHigh).padding(horizontal = 16.dp, vertical = 12.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                val style = TextStyle(color = scheme.onSurface, fontSize = 16.sp, lineHeight = 22.sp)
                BasicTextField(
                    value = vm.text,
                    onValueChange = vm::type,
                    textStyle = style,
                    cursorBrush = SolidColor(scheme.primary),
                    maxLines = 6,
                    modifier = Modifier.fillMaxWidth().focusRequester(focus),
                    decorationBox = { inner ->
                        Box {
                            if (vm.text.isEmpty()) {
                                Text(
                                    if (title.isNotBlank()) stringResource(R.string.teams_write_to, title.trim()) else stringResource(R.string.teams_write),
                                    style = style,
                                    color = scheme.onSurfaceVariant,
                                    maxLines = 1,
                                )
                            }
                            inner()
                        }
                    },
                )
            }
            Spacer(Modifier.width(6.dp))
            FilledIconButton(onClick = vm::send, enabled = vm.text.isNotBlank() && !vm.sending, modifier = Modifier.size(48.dp)) {
                MIcon(R.drawable.ic_m_send, stringResource(R.string.teams_send), size = 20.dp)
            }
        }
        val n = chars(vm.text)
        val count = if (n > TeamsLimits.BODY * 3 / 4) " · " + stringResource(R.string.teams_count, thousands(n), thousands(TeamsLimits.BODY)) else ""
        val correcting = vm.correcting
        Text(
            when {
                correcting -> stringResource(R.string.correct_busy)
                sender.isNotBlank() -> stringResource(R.string.teams_sent_as, sender) + count
                else -> stringResource(R.string.teams_sent_as_you) + count
            },
            style = MaterialTheme.typography.labelSmall,
            color = if (correcting) mika.accent else scheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 100.dp, top = 2.dp),
        )
    }
}

/**
 * Le message que tu cites, au-dessus du champ (« Citer » de Teams) : une barre d'accent à gauche, qui l'a écrit et
 * quand, en petit, l'extrait sur deux lignes au plus, et × pour ne plus le citer. Aligné sur le champ.
 */
@Composable
private fun CitingCard(m: TeamsMessage, account: TeamsAccount?, now: Long, onCancel: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val bar = scheme.primary
    val whenText = quoteWhen(m.at, now)
    Row(
        Modifier
            .fillMaxWidth()
            // aligné sur le champ, après ✦ et ✓ (deux boutons de 48 dp)
            .padding(start = 96.dp, end = 54.dp, bottom = 6.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(scheme.surfaceContainerHigh)
            .drawBehind { drawRect(bar, size = Size(3.dp.toPx(), size.height)) }
            .padding(start = 13.dp, top = 6.dp, bottom = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    authorLabel(m, account),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = scheme.onSurface,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (whenText.isNotEmpty()) {
                    Spacer(Modifier.width(6.dp))
                    Text(whenText, style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant, maxLines = 1)
                }
            }
            val excerpt = quoteExcerpt(m.text)
            if (excerpt.isNotEmpty()) {
                Text(excerpt, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
        IconButton(onClick = onCancel, modifier = Modifier.size(40.dp)) {
            MIcon(R.drawable.ic_m_x, stringResource(R.string.teams_cite_cancel), size = 18.dp, tint = scheme.onSurfaceVariant)
        }
    }
}

/** Un compte qu'on ne te partage pas pour t'en servir : pas de champ, une phrase qui le dit ; « Préremplir » si ton
 *  partage le permet (sa réponse attendra l'accord de son propriétaire). */
@Composable
private fun ReadOnly(account: TeamsAccount?, caps: Caps, onPrefill: () -> Unit, prefilling: Boolean) {
    Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
        NoteBox(readOnlyLine(account?.level.orEmpty(), account?.ownerName.orEmpty()), R.drawable.ic_m_lock)
        if (caps.prepare) {
            FilledTonalButton(
                onClick = onPrefill,
                enabled = !prefilling,
                colors = ButtonDefaults.filledTonalButtonColors(containerColor = mika.container, contentColor = mika.onContainer),
                modifier = Modifier.padding(top = 8.dp),
            ) {
                MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.teams_prefill))
            }
        }
    }
}
