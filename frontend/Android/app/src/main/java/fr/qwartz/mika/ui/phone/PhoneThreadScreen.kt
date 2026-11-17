package fr.qwartz.mika.ui.phone

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.approvals.Approvals
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.ago
import fr.qwartz.mika.data.moi.phone.OfferStates
import fr.qwartz.mika.data.moi.phone.PhoneOffer
import fr.qwartz.mika.data.moi.phone.PhoneThread
import fr.qwartz.mika.data.moi.phone.ReadMessage
import fr.qwartz.mika.data.moi.phone.ReplyWay
import fr.qwartz.mika.data.moi.phone.SentHere
import fr.qwartz.mika.data.moi.phone.ThreadItem
import fr.qwartz.mika.data.moi.phone.offerTitle
import fr.qwartz.mika.data.moi.phone.offerWords
import fr.qwartz.mika.data.moi.phone.replyWay
import fr.qwartz.mika.data.moi.phone.shownState
import fr.qwartz.mika.data.moi.phone.threadSubtitle
import fr.qwartz.mika.data.moi.phone.threadTitle
import fr.qwartz.mika.data.moi.phone.timeline
import fr.qwartz.mika.data.moi.phone.underWay
import fr.qwartz.mika.data.phone.HereOutcome
import fr.qwartz.mika.data.phone.PhoneDraft
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
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.linked
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.delay

/**
 * Une conversation lue sur le téléphone (la maquette, `vueConv`) : les autres à gauche (leur nom dans un groupe), toi à
 * droite ; ses propositions en carte rose dans le fil, à leur place, avec leur sort ; « Messages plus anciens » en haut.
 *
 * Ce que le téléphone fait de plus que le web : répondre d'ici. « Envoyer » sur sa proposition, ou ton propre texte
 * dans le champ, part par l'action « Répondre » de la notification de WhatsApp ou de Messages gardée en mémoire — le
 * geste sur ce téléphone vaut accord (ADR 0120) ; sans elle, le texte est copié et l'appli s'ouvre pour le coller. Une
 * proposition que ce téléphone n'a pas reçue, ou déjà réglée, ne se décide pas d'ici. Pas de ✦ « Préremplir » : le
 * serveur n'a pas cette route pour le téléphone (protocole § 5) ; ⋮ « Lui en parler dans le chat » ouvre le chat.
 */
@Composable
fun PhoneThreadScreen(graph: AppGraph, key: String) {
    val shell = LocalShell.current
    val context = LocalContext.current
    // les mots d'un geste se lisent au moment du geste : par les ressources de la composition, pas du contexte
    val res = LocalResources.current
    val session = rememberSessionKey(graph)
    val vm: PhoneThreadViewModel = viewModel(key = "phone.thread|$session") { PhoneThreadViewModel(PhoneThreadDeps(graph)) }
    // ce passage sur le fil (gardé à la rotation) : ce qu'un geste donne ne se dit que sur l'écran où il a commencé
    val visit = rememberSaveable(key) { MoiApi.newKey() }
    LaunchedEffect(key, visit) { vm.open(key, visit) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm, key, visit) {
        vm.gestures(visit).collect { d ->
            if (d.thread != key) return@collect
            val app = vm.current?.appName?.ifBlank { null } ?: res.getString(appLabelRes(d.app))
            val words = when (d.outcome) {
                HereOutcome.SENT -> res.getString(R.string.phone_said_sent, app)
                // le texte est dans le presse-papier : l'appli s'ouvre pour le coller, si elle est là
                HereOutcome.COPIED -> res.getString(if (openApp(context, d.app)) R.string.phone_said_copied else R.string.phone_copied_title, app)
                HereOutcome.FAILED -> res.getString(R.string.phone_said_failed)
                HereOutcome.IGNORED -> res.getString(R.string.phone_said_ignored)
                HereOutcome.GONE -> res.getString(R.string.phone_said_gone)
                HereOutcome.NOTHING, null -> ""
            }
            val field = when (d.field) {
                FieldNote.KEPT_AS_YOURS -> res.getString(R.string.phone_field_kept)
                FieldNote.NOT_SENT -> res.getString(R.string.phone_field_not_sent)
                null -> ""
            }
            val said = listOf(words, field).filter { it.isNotBlank() }.joinToString(" ")
            if (said.isNotBlank()) shell.toast(said)
        }
    }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, key, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                delay(PHONE_THREAD_REFRESH_MS)
                vm.refresh()
            }
        }
    }
    val t = vm.current?.takeIf { vm.key == key }
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = t?.let(::threadTitle) ?: stringResource(R.string.nav_phone),
                nav = BarNav.BACK,
                subtitle = t?.let(::threadSubtitle),
                face = false,
            ) {
                // ADR 0233 : le menu d'un fil ne garde que « Lui en parler dans le chat »
                BarMenu(listOf(MenuEntry(stringResource(R.string.phone_ask_chat), R.drawable.ic_m_chat) { shell.open(Route.Chat) }))
            }
        },
        bottomBar = { if (t != null) Dock(vm, t) },
    ) { modifier ->
        LoadBox(if (vm.key == key) vm.thread else Load.Loading, onRetry = vm::retry, modifier = modifier) { thread ->
            Messages(vm, thread, modifier)
        }
    }
}

/** Une ligne du fil, avec sa clé stable. */
private sealed interface Line {
    val id: String

    data class Older(val loading: Boolean) : Line {
        override val id = "older"
    }

    data object Hidden : Line {
        override val id = "hidden"
    }

    data object Empty : Line {
        override val id = "empty"
    }

    data class Day(val label: String) : Line {
        override val id = "day:$label"
    }

    data class Message(val m: ReadMessage, val suite: Boolean, val n: Int) : Line {
        override val id = "m:${m.id.ifEmpty { "n$n" }}"
    }

    data class Offer(val o: PhoneOffer) : Line {
        override val id = "o:${o.id}"
    }

    data class Sent(val s: SentHere, val n: Int) : Line {
        override val id = "sent:${s.at}:$n"
    }
}

@Composable
private fun Messages(vm: PhoneThreadViewModel, t: PhoneThread, modifier: Modifier) {
    val now = rememberNow()
    val lines = remember(t, vm.sent, vm.loadingOlder, vm.size, now) {
        buildList {
            when {
                vm.canLoadOlder -> add(Line.Older(vm.loadingOlder))
                t.more -> add(Line.Hidden)
                t.messages.isEmpty() && t.offers.isEmpty() -> add(Line.Empty)
            }
            timeline(t.messages, t.offers, now).forEachIndexed { n, item ->
                add(
                    when (item) {
                        is ThreadItem.Day -> Line.Day(item.label)
                        is ThreadItem.Message -> Line.Message(item.m, item.suite, n)
                        is ThreadItem.Offer -> Line.Offer(item.o)
                    },
                )
            }
            vm.sent.filter { it.conversation == t.key }.forEachIndexed { n, s -> add(Line.Sent(s, n)) }
        }.distinctBy { it.id }.asReversed()
    }
    val app = appLabel(t.app, t.appName)
    // le plus récent en bas : la liste part du bas
    LazyColumn(modifier.fillMaxSize(), reverseLayout = true, contentPadding = PaddingValues(vertical = 8.dp)) {
        items(lines, key = { it.id }) { line ->
            when (line) {
                is Line.Older -> Box(Modifier.fillMaxWidth().padding(4.dp), contentAlignment = Alignment.Center) {
                    TextButton(onClick = vm::loadOlder, enabled = !line.loading) {
                        MIcon(R.drawable.ic_m_history, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(if (line.loading) R.string.phone_loading else R.string.phone_older))
                    }
                }
                Line.Hidden -> CenterNote(stringResource(R.string.phone_older_hidden))
                Line.Empty -> CenterNote(stringResource(R.string.phone_thread_empty))
                is Line.Day -> DayMark(line.label)
                is Line.Message -> MessageRow(line.m, line.suite, t.group)
                is Line.Offer -> OfferCard(line.o, vm, app, now)
                is Line.Sent -> SentRow(line.s)
            }
        }
    }
}

@Composable
private fun CenterNote(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        textAlign = TextAlign.Center,
        modifier = Modifier.fillMaxWidth().padding(16.dp),
    )
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

private fun bubbleShape(mine: Boolean) =
    if (mine) RoundedCornerShape(20.dp, 20.dp, 6.dp, 20.dp) else RoundedCornerShape(20.dp, 20.dp, 20.dp, 6.dp)

/** Un message (`.tmsg`) : les autres à gauche avec leur rond (leur nom au-dessus dans un groupe), toi à droite en
 *  indigo ; la suite d'un même auteur se serre. */
@Composable
private fun MessageRow(m: ReadMessage, suite: Boolean, group: Boolean) {
    val scheme = MaterialTheme.colorScheme
    val mine = m.own
    val name = m.sender.ifBlank { "?" }
    val bg = if (mine) scheme.primary else scheme.surfaceContainerHigh
    val fg = if (mine) scheme.onPrimary else scheme.onSurface
    val link = if (mine) scheme.onPrimary else scheme.primary
    val text = remember(m.text, link) { linked(m.text, link) }
    Row(
        Modifier.fillMaxWidth().padding(start = if (mine) 56.dp else 12.dp, end = if (mine) 12.dp else 40.dp, top = if (suite) 1.dp else 6.dp),
        horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start,
    ) {
        if (!mine) {
            if (suite) Spacer(Modifier.width(32.dp)) else PersonAvatar(name, name, 32.dp)
            Spacer(Modifier.width(8.dp))
        }
        Column(horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
            if (!mine && group && !suite) {
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
                modifier = Modifier.clip(bubbleShape(mine)).background(bg).padding(horizontal = 14.dp, vertical = 8.dp),
            )
            if (mine || !group) {
                Text(
                    MoiDates.clock(m.at),
                    style = MaterialTheme.typography.labelSmall,
                    color = scheme.onSurfaceVariant,
                    modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
                )
            }
        }
    }
}

/** Ton message parti d'ici, que le fil ne montre pas encore (le téléphone le lira, puis le serveur). */
@Composable
private fun SentRow(s: SentHere) {
    val scheme = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(start = 56.dp, end = 12.dp, top = 6.dp), horizontalAlignment = Alignment.End) {
        Text(
            s.text,
            style = MaterialTheme.typography.bodyLarge.copy(fontSize = 15.sp, lineHeight = 21.sp),
            color = scheme.onPrimary,
            modifier = Modifier.clip(bubbleShape(true)).background(scheme.primary.copy(alpha = 0.6f)).padding(horizontal = 14.dp, vertical = 8.dp),
        )
        Row(Modifier.padding(horizontal = 6.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            MIcon(R.drawable.ic_m_check, null, size = 13.dp, tint = scheme.onSurfaceVariant)
            Spacer(Modifier.width(4.dp))
            Text("${MoiDates.clock(s.at)} · ${stringResource(R.string.phone_sent_here)}", style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant)
        }
    }
}

/**
 * Sa proposition dans le fil (`.prop` de la maquette) : ce qu'elle propose et quand ; si ce téléphone la tient,
 * Ignorer · Écrire autre chose · Envoyer, avec son échéance et comment elle part ; sinon son sort (au téléphone,
 * partie, laissée…), atténué une fois réglée.
 */
@Composable
private fun OfferCard(o: PhoneOffer, vm: PhoneThreadViewModel, app: String, now: Long) {
    val scheme = MaterialTheme.colorScheme
    val draft: PhoneDraft? = vm.decidable(o)
    val state = shownState(o, vm.decidedHere)
    val open = underWay(state)
    val busyText = stringResource(R.string.phone_field_busy)
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = if (open) mika.soft else scheme.surfaceContainerLow,
        border = BorderStroke(1.dp, if (open) mika.line else scheme.outlineVariant),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
    ) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_sparkle, null, size = 16.dp, tint = mika.accent)
                Spacer(Modifier.width(6.dp))
                Text(
                    "${offerTitle(state)} · ${MoiDates.clock(o.at)}",
                    style = MaterialTheme.typography.labelLarge,
                    color = mika.accent,
                    fontWeight = FontWeight.Medium,
                )
            }
            Text(
                "« ${draft?.text ?: o.text} »",
                style = MaterialTheme.typography.bodyLarge.copy(lineHeight = 21.sp),
                color = if (open) scheme.onSurface else scheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 6.dp),
            )
            if (draft != null) {
                val expiry = Approvals.expiryLabel(draft.exp, now).orEmpty()
                Text(
                    listOf(expiry, stringResource(R.string.phone_offer_how, app)).filter { it.isNotBlank() }.joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp),
                )
                Row(
                    Modifier.fillMaxWidth().padding(top = 8.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.End),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    TextButton(onClick = { vm.ignore(o) }, enabled = !vm.busy) { Text(stringResource(R.string.phone_offer_ignore), maxLines = 1) }
                    OutlinedButton(onClick = { vm.writeOther(o, draft, busyText) }, enabled = !vm.busy) {
                        Text(stringResource(R.string.phone_offer_other), maxLines = 1)
                    }
                    Button(
                        onClick = { vm.sendOffer(o) },
                        enabled = !vm.busy,
                        colors = ButtonDefaults.buttonColors(containerColor = mika.fill, contentColor = mika.onFill),
                    ) {
                        MIcon(R.drawable.ic_m_send, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.phone_offer_send), maxLines = 1)
                    }
                }
            } else {
                val (tone, words) = offerWords(state)
                val here = o.id in vm.decidedHere
                val whenText = when {
                    here -> stringResource(R.string.phone_offer_here)
                    state == OfferStates.OFFERED && o.expires > 0 -> Approvals.expiryLabel(o.expires, now).orEmpty()
                    !open && o.decidedAt > 0 -> ago(o.decidedAt, now)
                    else -> ""
                }
                Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Tag(words, tone)
                    if (whenText.isNotBlank()) {
                        Spacer(Modifier.width(8.dp))
                        Text(whenText, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                    }
                }
                val help = when (state) {
                    OfferStates.PREPARED -> R.string.phone_offer_prepared
                    OfferStates.OFFERED -> R.string.phone_offer_elsewhere
                    else -> null
                }
                if (help != null && !here) {
                    Text(stringResource(help), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
                }
            }
        }
    }
}

/** Le bas du fil : ta version de sa proposition (si tu l'as prise), le champ « Répondre par WhatsApp », envoyer, et
 *  dessous comment ça part — par la notification de l'appli tant qu'elle est là, sinon copié. */
@Composable
private fun Dock(vm: PhoneThreadViewModel, t: PhoneThread) {
    val scheme = MaterialTheme.colorScheme
    val app = appLabel(t.app, t.appName)
    Surface(color = scheme.surface) {
        Column(Modifier.navigationBarsPadding().imePadding()) {
            HorizontalDivider()
            if (vm.editing != 0L) {
                Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    MIcon(R.drawable.ic_m_pen, null, size = 16.dp, tint = mika.accent)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.phone_field_editing), style = MaterialTheme.typography.bodySmall, color = mika.accent, modifier = Modifier.weight(1f))
                    TextButton(onClick = vm::stopEditing) { Text(stringResource(R.string.phone_field_editing_stop)) }
                }
            }
            Row(Modifier.padding(start = 12.dp, end = 8.dp, top = 6.dp), verticalAlignment = Alignment.Bottom) {
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
                                    Text(stringResource(R.string.phone_field_hint, app), style = style, color = scheme.onSurfaceVariant, maxLines = 1)
                                }
                                inner()
                            }
                        },
                    )
                }
                Spacer(Modifier.width(6.dp))
                FilledIconButton(onClick = vm::send, enabled = vm.text.isNotBlank() && !vm.busy, modifier = Modifier.size(48.dp)) {
                    MIcon(R.drawable.ic_m_send, stringResource(R.string.phone_send), size = 20.dp)
                }
            }
            // comment part ce que tu envoies, dit avant le geste : à qui répond l'action gardée, si c'est bien ce fil
            val way = replyWay(vm.replyTo, t)
            Text(
                when {
                    way is ReplyWay.Action -> stringResource(R.string.phone_field_by_action, app, way.to)
                    way is ReplyWay.Other && way.kept.isNotBlank() && way.shown.isNotBlank() -> stringResource(R.string.phone_field_other, way.kept, way.shown, app)
                    way is ReplyWay.Other -> stringResource(R.string.phone_field_unnamed, app)
                    else -> stringResource(R.string.phone_field_by_copy, app)
                },
                style = MaterialTheme.typography.labelSmall,
                color = if (way is ReplyWay.Other) MaterialTheme.colorScheme.error else scheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 28.dp, end = 16.dp, top = 2.dp, bottom = 6.dp),
            )
        }
    }
}
