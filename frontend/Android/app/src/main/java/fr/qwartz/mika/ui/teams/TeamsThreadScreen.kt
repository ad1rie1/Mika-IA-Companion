package fr.qwartz.mika.ui.teams

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Caps
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.teams.ConversationThread
import fr.qwartz.mika.data.moi.teams.Mark
import fr.qwartz.mika.data.moi.teams.OwnBubble
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsLimits
import fr.qwartz.mika.data.moi.teams.TeamsMessage
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.YOU
import fr.qwartz.mika.data.moi.teams.authorLabel
import fr.qwartz.mika.data.moi.teams.capsOf
import fr.qwartz.mika.data.moi.teams.fromHer
import fr.qwartz.mika.data.moi.teams.fromYou
import fr.qwartz.mika.data.moi.teams.isGroup
import fr.qwartz.mika.data.moi.teams.lastReceived
import fr.qwartz.mika.data.moi.teams.mentionRanges
import fr.qwartz.mika.data.moi.teams.ownBubbles
import fr.qwartz.mika.data.moi.teams.prefillOff
import fr.qwartz.mika.data.moi.teams.quietLine
import fr.qwartz.mika.data.moi.teams.readOnlyLine
import fr.qwartz.mika.data.moi.teams.selfName
import fr.qwartz.mika.data.moi.teams.sentUnder
import fr.qwartz.mika.data.moi.teams.threadCards
import fr.qwartz.mika.data.moi.teams.threadMarks
import fr.qwartz.mika.data.moi.teams.threadSubtitle
import fr.qwartz.mika.data.moi.thousands
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.linked
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.delay

/**
 * Une discussion (la maquette, `vueFil`) : les autres à gauche (leur nom dans un groupe), toi à droite — « Toi »
 * seulement sur un compte à toi ; sur un compte qu'on te partage, son propriétaire à son nom, à gauche —, tes mentions
 * marquées, « Messages plus anciens » en haut, tes messages en attente avec leur état. Ses réponses en carte rose
 * au-dessus du champ ; le champ : ✦ Préremplir à gauche, envoyer à droite, et dessous sous quel nom ça part. Un
 * compte qu'on ne te partage qu'en lecture n'a pas de champ : une phrase le dit. ⋮ : « Comment ça part ».
 */
@Composable
fun TeamsThreadScreen(graph: AppGraph, key: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: TeamsThreadViewModel = viewModel(key = "teams.thread|$session") { TeamsThreadViewModel(graph) }
    val arrived = stringResource(R.string.teams_arrived)
    LaunchedEffect(key) { vm.open(key, arrived) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    // le fil se relit tant qu'il est à l'écran ; une réponse demandée, de plus près
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, key, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                delay(if (vm.watching) ASK_POLL_MS else THREAD_REFRESH_MS)
                vm.refresh()
            }
        }
    }
    var asking by remember { mutableStateOf<Pair<Ask, TeamsReply>?>(null) }
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
            if (t != null) Dock(vm, t, account, myName, onAsk = { a, r -> asking = a to r })
        },
    ) { modifier ->
        LoadBox(if (vm.key == key) vm.thread else Load.Loading, onRetry = vm::retry, modifier = modifier) { thread ->
            Messages(vm, thread, account, selfName(account, myName), modifier)
        }
    }
    asking?.let { (a, r) -> ReplyAskDialog(a, r, vm) { asking = null } }
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
private fun Messages(vm: TeamsThreadViewModel, t: ConversationThread, account: TeamsAccount?, selfName: String, modifier: Modifier) {
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
    // le plus récent en bas : la liste part du bas, les plus anciens s'ajoutent en haut sans la faire bouger
    LazyColumn(modifier.fillMaxSize(), reverseLayout = true, contentPadding = PaddingValues(vertical = 8.dp)) {
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
                is Line.Message -> MessageRow(line.m, line.mark, account, group, selfName, fromHer(line.m, t.replies))
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

/**
 * Un message (`.tmsg` de la maquette) : les autres à gauche avec leur rond (leur nom au-dessus dans un groupe), toi à
 * droite en indigo ; la suite d'un même auteur se serre. Une mention de toi : un filet indigo à gauche de la bulle, et
 * ton nom en gras.
 */
@Composable
private fun MessageRow(m: TeamsMessage, mark: Mark, account: TeamsAccount?, group: Boolean, selfName: String, byMika: Boolean) {
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
    Row(
        Modifier.fillMaxWidth().padding(start = if (mine) 56.dp else 12.dp, end = if (mine) 12.dp else 40.dp, top = if (mark.suite) 1.dp else 6.dp),
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
            Text(
                text,
                style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, lineHeight = 21.sp),
                color = fg,
                modifier = Modifier
                    .clip(bubbleShape(mine))
                    .background(bg)
                    .then(if (m.mentionsMe) Modifier.drawBehind { drawRect(bar, size = Size(3.dp.toPx(), size.height)) } else Modifier)
                    .padding(horizontal = 14.dp, vertical = 8.dp),
            )
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
            MIcon(if (b.failed) R.drawable.ic_m_alert else R.drawable.ic_m_clock, null, size = 13.dp, tint = if (b.failed) scheme.error else scheme.onSurfaceVariant)
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
 * rien n'est venu depuis), « Elle s'y met… », ce qui retient ce qui part, puis le champ — ou, sur un compte qu'on ne te
 * partage qu'en lecture, la phrase qui le dit (et « Préremplir » si ton partage le permet).
 */
@Composable
private fun Dock(vm: TeamsThreadViewModel, t: ConversationThread, account: TeamsAccount?, myName: String, onAsk: (Ask, TeamsReply) -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val now = rememberNow()
    val caps = capsOf(account)
    val messages = vm.messages
    val cards = threadCards(t.replies, messages.lastOrNull()?.at ?: 0)
    val enabled = vm.accounts?.enabled ?: true
    val noReceived = stringResource(R.string.teams_no_received)
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
            if (vm.asked) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 16.dp, tint = mika.accent)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.teams_working), style = MaterialTheme.typography.bodySmall, color = mika.accent)
                }
            }
            if (caps.write) {
                val quiet = quietLine(enabled, account, now)
                if (quiet.isNotEmpty()) {
                    NoteBox(quiet, R.drawable.ic_m_plug, Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
                }
                Composer(
                    vm = vm,
                    title = t.title,
                    canPrefill = lastReceived(messages) != null && prefillOff(enabled, account).isEmpty(),
                    sender = selfName(account, myName),
                    onPrefill = { vm.prefill(noReceived) },
                )
            } else {
                ReadOnly(account, caps, onPrefill = { vm.prefill(noReceived) }, prefilling = vm.prefilling)
            }
        }
    }
}

/** Le champ (`.composer` de la maquette) : ✦ Préremplir à gauche, ton message, envoyer ; dessous, sous quel nom ça
 *  part (et le compte des caractères, près de la borne). */
@Composable
private fun Composer(vm: TeamsThreadViewModel, title: String, canPrefill: Boolean, sender: String, onPrefill: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Column(Modifier.padding(start = 4.dp, end = 8.dp, top = 6.dp, bottom = 6.dp)) {
        Row(verticalAlignment = Alignment.Bottom) {
            IconButton(onClick = onPrefill, enabled = !vm.prefilling, modifier = Modifier.alpha(if (canPrefill) 1f else 0.45f)) {
                MIcon(R.drawable.ic_m_sparkle, stringResource(R.string.teams_prefill), tint = mika.accent)
            }
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
                    modifier = Modifier.fillMaxWidth(),
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
        Text(
            (if (sender.isNotBlank()) stringResource(R.string.teams_sent_as, sender) else stringResource(R.string.teams_sent_as_you)) + count,
            style = MaterialTheme.typography.labelSmall,
            color = scheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 52.dp, top = 2.dp),
        )
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
