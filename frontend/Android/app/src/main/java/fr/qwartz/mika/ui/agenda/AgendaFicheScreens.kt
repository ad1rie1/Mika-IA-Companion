package fr.qwartz.mika.ui.agenda

import android.content.Intent
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.agenda.ANSWERS
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaItem
import fr.qwartz.mika.data.moi.agenda.AgendaKinds
import fr.qwartz.mika.data.moi.agenda.AnswerNote
import fr.qwartz.mika.data.moi.agenda.FormModes
import fr.qwartz.mika.data.moi.agenda.Occ
import fr.qwartz.mika.data.moi.agenda.Proposal
import fr.qwartz.mika.data.moi.agenda.SCOPES
import fr.qwartz.mika.data.moi.agenda.Sort
import fr.qwartz.mika.data.moi.agenda.answerNote
import fr.qwartz.mika.data.moi.agenda.answerWord
import fr.qwartz.mika.data.moi.agenda.colorOf
import fr.qwartz.mika.data.moi.agenda.dayWords
import fr.qwartz.mika.data.moi.agenda.deletedWhere
import fr.qwartz.mika.data.moi.agenda.ficheFoot
import fr.qwartz.mika.data.moi.agenda.hm
import fr.qwartz.mika.data.moi.agenda.inviter
import fr.qwartz.mika.data.moi.agenda.localOf
import fr.qwartz.mika.data.moi.agenda.mikaReminderLine
import fr.qwartz.mika.data.moi.agenda.mikaReminderWords
import fr.qwartz.mika.data.moi.agenda.occOfHer
import fr.qwartz.mika.data.moi.agenda.occOfItem
import fr.qwartz.mika.data.moi.agenda.occOfProposal
import fr.qwartz.mika.data.moi.agenda.peopleOf
import fr.qwartz.mika.data.moi.agenda.peopleSummary
import fr.qwartz.mika.data.moi.agenda.preparedWords
import fr.qwartz.mika.data.moi.agenda.providerReminderLines
import fr.qwartz.mika.data.moi.agenda.providerShort
import fr.qwartz.mika.data.moi.agenda.relative
import fr.qwartz.mika.data.moi.agenda.remindChoices
import fr.qwartz.mika.data.moi.agenda.removesInvitation
import fr.qwartz.mika.data.moi.agenda.ruleWords
import fr.qwartz.mika.data.moi.agenda.shortDay
import fr.qwartz.mika.data.moi.agenda.sortOf
import fr.qwartz.mika.data.moi.agenda.whenWords
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.settings.SettingsPages
import fr.qwartz.mika.ui.settings.settingsPage
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import fr.qwartz.mika.ui.theme.states

/*
 * La fiche d'un événement, en page (la maquette validée `agenda.js`, comme Google Agenda sur Android) : ✦ « Demander à
 * Mika », Modifier, Supprimer, ⋮ (Dupliquer ou « Copier dans mes agendas », Partager l'agenda, ses paramètres) ; le
 * carré de sa couleur, son titre, quand, ce qui reste ; l'invitation et la réponse que Mika a préparée ; la
 * répétition, le lieu, la visio, la description, l'agenda, occupé ou disponible, les participants ; les rappels — ceux
 * du fournisseur, puis « Mika te le rappelle » ; « Participer ? » en barre du bas. Et la fiche de ce que Mika propose,
 * et d'une date de sa mémoire. Un bouton n'existe que si le serveur l'ouvre (`can`).
 */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun FicheBar(actions: @Composable () -> Unit) {
    val shell = LocalShell.current
    TopAppBar(
        navigationIcon = { BarAction(R.drawable.ic_m_back, stringResource(R.string.shell_back), shell.back) },
        title = {},
        actions = { actions() },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
    )
}

/** Le carré, le titre (✦ s'il est de Mika), quand, et ses étiquettes. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TitleBlock(o: Occ, color: String, today: String, nowMinute: Int, extra: List<Pair<String, Tone>> = emptyList()) {
    val (tone, rel) = relative(o, today, nowMinute)
    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp)) {
        Swatch(color, 22.dp, Modifier.padding(top = 6.dp))
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                val s = sortOf(o)
                if (s == Sort.MIKA || s == Sort.PROPOSED) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp, tint = mika.accent)
                    Spacer(Modifier.width(6.dp))
                }
                Text(o.title, style = MaterialTheme.typography.headlineSmall, modifier = Modifier.semantics { heading() })
            }
            Text(whenWords(o, today), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(top = 6.dp)) {
                Tag(rel, tone)
                for ((t, tn) in extra) Tag(t, tn)
            }
        }
    }
}

/** Une ligne de la fiche : son icône, ce qu'elle dit, et ce qu'elle ouvre ([onClick]). */
@Composable
private fun InfoRow(icon: Int, onClick: (() -> Unit)? = null, content: @Composable () -> Unit) {
    Row(
        Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).heightIn(min = 52.dp).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.Top,
    ) {
        MIcon(icon, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) { content() }
        if (onClick != null) MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Group(content: @Composable () -> Unit) {
    Surface(shape = RoundedCornerShape(16.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        Column { content() }
    }
}

@Composable
private fun SectionHead(text: String, pink: Boolean = false) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        color = if (pink) mika.accent else MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 28.dp, top = 14.dp, bottom = 4.dp).semantics { heading() },
    )
}

/** La ligne de son agenda : sa couleur, son nom, son fournisseur ; elle mène à ses paramètres (le sien). */
@Composable
private fun CalendarRow(cal: AgendaCalendar?, color: String, onOpen: (() -> Unit)?) {
    InfoRow(R.drawable.ic_m_agenda, onOpen) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Swatch(color, 12.dp)
            Spacer(Modifier.width(6.dp))
            Text(cal?.name.orEmpty(), style = MaterialTheme.typography.bodyLarge)
        }
        if (cal != null) Text(providerShort(cal), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ── un événement ────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgendaEventScreen(graph: AppGraph, route: Route.AgendaEvent) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: AgendaItemViewModel = viewModel(key = "agenda.event|$session|${route.event}|${route.occurrence}") { AgendaItemViewModel(AgendaDeps(graph)) }
    LaunchedEffect(vm, route) { vm.open(route.event, route.occurrence, 0) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm) { vm.gone.collect { shell.back() } }
    FollowLive(graph.live, AGENDA_TOPICS, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val wall = rememberNow(wallMs = graph.clock::wallMs)
    var menu by remember { mutableStateOf(false) }
    var ask by rememberSaveable { mutableStateOf("") }
    var share by rememberSaveable { mutableStateOf(false) }
    val item = vm.item.valueOrNull
    val cal = vm.calendar
    SectionScaffold(
        topBar = {
            FicheBar {
                if (item != null) {
                    val o = occOfItem(item, vm.zone)
                    BarAction(R.drawable.ic_m_sparkle, stringResource(R.string.agenda_ask_mika), {
                        askMika(shell, shell.graph.context.getString(R.string.agenda_ask_about, o.title, "${shortDay(o.day)}${if (o.allDay) "" else " à " + hm(o.start)}"))
                    }, tint = mika.accent)
                    if (item.can.edit) BarAction(R.drawable.ic_m_pen, stringResource(R.string.agenda_modify), { shell.navigate(Route.AgendaForm(FormModes.EDIT, item.event, item.occurrence)) })
                    if (item.can.delete) BarAction(R.drawable.ic_m_trash, stringResource(if (removesInvitation(item)) R.string.agenda_remove else R.string.agenda_delete), { ask = ASK_DELETE })
                    Box {
                        BarAction(R.drawable.ic_m_more, stringResource(R.string.agenda_menu), { menu = true })
                        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                            if (item.can.duplicate) {
                                DropdownMenuItem(
                                    text = { Text(stringResource(if (cal?.writable == true && cal.can.write) R.string.agenda_duplicate else R.string.agenda_copy_to_mine)) },
                                    leadingIcon = { MIcon(R.drawable.ic_m_copy, null, size = 20.dp) },
                                    onClick = {
                                        menu = false
                                        shell.navigate(Route.AgendaForm(FormModes.COPY, item.event, item.occurrence))
                                    },
                                )
                            }
                            if (cal != null && cal.kind != AgendaKinds.MIKA) {
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.agenda_share_named, cal.name)) },
                                    leadingIcon = { MIcon(R.drawable.ic_m_user_plus, null, size = 20.dp) },
                                    onClick = {
                                        menu = false
                                        share = true
                                    },
                                )
                            }
                            if (cal != null && cal.owned) {
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.agenda_settings_named, cal.name)) },
                                    leadingIcon = { MIcon(R.drawable.ic_m_settings, null, size = 20.dp) },
                                    onClick = {
                                        menu = false
                                        shell.navigate(settingsPage(SettingsPages.AGENDA_CALENDAR, cal.key))
                                    },
                                )
                            }
                        }
                    }
                }
            }
        },
        bottomBar = { if (item != null && item.response.isNotEmpty() && item.can.respond) AnswerBar(item, vm.acting, vm::respond) },
    ) { modifier ->
        LoadBox(vm.item, onRetry = vm::retry, modifier = modifier) { i ->
            val (today, nowMinute) = vm.now(wall)
            EventFiche(graph, vm, i, cal, today, nowMinute, onWord = { ask = ASK_WORD }, onRemind = { ask = ASK_REMIND }, modifier = modifier)
        }
    }
    if (item != null) {
        when (ask) {
            ASK_DELETE -> DeleteAsk(item, cal, onDismiss = { ask = "" }) { scope ->
                ask = ""
                vm.delete(scope)
            }
            ASK_WORD -> item.prepared?.let { p ->
                WordSheet(inviter(item).ifBlank { stringResource(R.string.agenda_organizer) }, p, cal, onDismiss = { ask = "" }) { answer, comment ->
                    ask = ""
                    vm.respond(answer, comment)
                }
            }
            ASK_REMIND -> RemindSheet(item, cal, onDismiss = { ask = "" }) {
                ask = ""
                vm.remind(it)
            }
        }
    }
    if (share && cal != null) ShareSheet(graph, cal, onDismiss = { share = false }, onHide = { graph.agendaPrefs.setShown(cal.key, false) })
}

private const val ASK_DELETE = "supprimer"
private const val ASK_WORD = "mot"
private const val ASK_REMIND = "rappel"

@Composable
private fun EventFiche(
    graph: AppGraph,
    vm: AgendaItemViewModel,
    i: AgendaItem,
    cal: AgendaCalendar?,
    today: String,
    nowMinute: Int,
    onWord: () -> Unit,
    onRemind: () -> Unit,
    modifier: Modifier,
) {
    val shell = LocalShell.current
    val context = LocalContext.current
    val o = occOfItem(i, vm.zone)
    val color = colorOf(cal)
    Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        val extra = buildList {
            if (i.invitation) add(stringResource(R.string.agenda_tag_invitation) to Tone.WARN)
            if (i.response == "peut") add(stringResource(R.string.agenda_tag_said_maybe) to Tone.NEUTRAL)
        }
        TitleBlock(o, color, today, nowMinute, extra)
        if (i.response.isNotEmpty()) InvitationBox(i, vm.acting, onSend = vm::sendPrepared, onWord = onWord, onDrop = vm::dropPrepared)
        Group {
            if (i.recurring) {
                InfoRow(R.drawable.ic_m_repeat) {
                    Text(if (i.rule.isNotEmpty()) ruleWords(i.rule, o.day, today) else stringResource(R.string.agenda_one_of_series), style = MaterialTheme.typography.bodyLarge)
                }
            }
            if (i.location.isNotBlank()) InfoRow(R.drawable.ic_m_pin) { Text(i.location, style = MaterialTheme.typography.bodyLarge) }
            if (Regex("^https?://", RegexOption.IGNORE_CASE).containsMatchIn(i.conference)) {
                InfoRow(R.drawable.ic_m_video, onClick = {
                    runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, i.conference.toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                }) {
                    Text(stringResource(R.string.agenda_join), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.primary)
                    Text(i.conference, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace, maxLines = 1, overflow = TextOverflow.Ellipsis, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (i.description.isNotBlank()) InfoRow(R.drawable.ic_m_threads) { Text(i.description, style = MaterialTheme.typography.bodyMedium) }
            CalendarRow(cal, color, if (cal?.owned == true) ({ shell.navigate(settingsPage(SettingsPages.AGENDA_CALENDAR, cal.key)) }) else null)
            InfoRow(R.drawable.ic_m_clock) {
                Text(
                    stringResource(if (i.busy) R.string.agenda_busy else R.string.agenda_free) + " · " +
                        stringResource(if (i.private) R.string.agenda_private else R.string.agenda_visibility_default),
                    style = MaterialTheme.typography.bodyLarge,
                )
                val org = if (i.organizer != null && !i.organizer.me && !i.organized) inviter(i) else ""
                if (org.isNotBlank()) Text(stringResource(R.string.agenda_organized_by, org), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            if (!i.masked) People(i)
        }
        Reminders(i, cal, onRemind)
        if (i.added?.by == "elle") {
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
                MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp, tint = mika.accent)
                Spacer(Modifier.width(10.dp))
                Column {
                    val at = i.added.at.takeIf { it > 0 }?.let { dayWords(localOf(it, vm.zone).day, today) }
                    Text(if (at != null) stringResource(R.string.agenda_added_on, at) else stringResource(R.string.agenda_added), style = MaterialTheme.typography.bodyMedium, color = mika.accent, fontWeight = FontWeight.Medium)
                    if (i.added.conversation.isNotBlank()) {
                        Text(stringResource(R.string.agenda_see_conversation), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.primary, modifier = Modifier.clickable { shell.open(Route.Chat) })
                    }
                }
            }
        }
        FootNote(ficheFoot(i, cal), if (i.masked || cal?.writable != true) R.drawable.ic_m_lock else R.drawable.ic_m_refresh, Modifier.padding(horizontal = 16.dp, vertical = 10.dp))
    }
}

/** L'invitation : qui t'invite (et où), ce que tu as répondu, la réponse que Mika a préparée. */
@Composable
private fun InvitationBox(i: AgendaItem, acting: Boolean, onSend: (Proposal) -> Unit, onWord: () -> Unit, onDrop: (Proposal) -> Unit) {
    val who = inviter(i)
    Group {
        if (who.isNotBlank()) {
            Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                PersonAvatar(who, i.organizer?.address.orEmpty(), 36.dp)
                Spacer(Modifier.width(12.dp))
                Column {
                    Text(stringResource(R.string.agenda_invites_you, who), style = MaterialTheme.typography.titleSmall)
                    if (i.calendarName.isNotBlank()) Text(stringResource(R.string.agenda_in_calendar, i.calendarName), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        if (i.response.isNotEmpty() && i.response != "attente") {
            Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_check, null, size = 18.dp, tint = states.ok)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.agenda_you_answered, answerWord(i.response)), style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (answerNote(i) == AnswerNote.WHY) { // la barre « Participer ? » n'est pas là : on dit pourquoi
            Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp), verticalAlignment = Alignment.Top) {
                MIcon(R.drawable.ic_m_alert, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(8.dp))
                Text(i.respondWhy, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        val p = i.prepared?.takeIf { it.decides && i.invitation }
        if (p != null) {
            PinkBox(Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    MikaFace(32.dp)
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                            Spacer(Modifier.width(4.dp))
                            Text(stringResource(R.string.agenda_prepared_title), style = MaterialTheme.typography.labelLarge, color = mika.accent)
                        }
                        Text(preparedWords(p), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
                        if (p.why.isNotBlank()) Text(p.why, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
                        if (p.preview?.blocked?.isNotBlank() == true) Text(p.preview.blocked, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                        Button(onClick = { onSend(p) }, enabled = !acting && p.preview?.blocked.isNullOrBlank(), modifier = Modifier.padding(top = 8.dp)) {
                            MIcon(R.drawable.ic_m_send, null, size = 18.dp)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.agenda_send_hers))
                        }
                        Row {
                            TextButton(onClick = onWord, enabled = !acting) { Text(stringResource(R.string.agenda_edit_word)) }
                            TextButton(onClick = { onDrop(p) }, enabled = !acting) { Text(stringResource(R.string.agenda_no_thanks)) }
                        }
                    }
                }
            }
        }
    }
}

/** « Participer ? » : Accepter · Peut-être · Refuser, la réponse donnée pleine. */
@Composable
private fun AnswerBar(i: AgendaItem, acting: Boolean, onAnswer: (String, String) -> Unit) {
    Surface(tonalElevation = 3.dp, shadowElevation = 6.dp) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 8.dp)) {
            Text(stringResource(R.string.agenda_participate), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), modifier = Modifier.padding(top = 4.dp)) {
                for ((k, label) in ANSWERS) {
                    AnswerButton(k, label, on = i.response == k, enabled = !acting, modifier = Modifier.weight(1f)) { onAnswer(k, "") }
                }
            }
            if (answerNote(i) == AnswerNote.SERIES) {
                Text(stringResource(R.string.agenda_answer_series), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 6.dp))
            }
        }
    }
}

/** Les participants : combien, leurs réponses, puis chacun (l'organisateur d'abord). */
@Composable
private fun People(i: AgendaItem) {
    val rows = peopleOf(i)
    if (rows.isEmpty()) return
    InfoRow(R.drawable.ic_m_users) {
        Text(pluralStringResource(R.plurals.agenda_participants, rows.size, rows.size), style = MaterialTheme.typography.bodyLarge)
        Text(peopleSummary(rows), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    for (r in rows) {
        Row(Modifier.fillMaxWidth().padding(start = 56.dp, end = 16.dp, bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            PersonAvatar(r.name, r.address.ifBlank { r.name }, 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(if (r.me && r.name != "Toi") "${r.name} ${stringResource(R.string.agenda_you)}" else r.name, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (r.address.isNotBlank()) Text(r.address, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Tag(r.word, r.tone)
        }
    }
}

/** Les rappels : ceux du fournisseur, puis, en rose, « Mika te le rappelle » (l'agenda, ou le sien) et « Changer ». */
@Composable
private fun Reminders(i: AgendaItem, cal: AgendaCalendar?, onChange: () -> Unit) {
    if (cal == null) return
    SectionHead(stringResource(R.string.agenda_reminders))
    Group {
        for (line in providerReminderLines(i, cal)) InfoRow(R.drawable.ic_m_bell) { Text(line, style = MaterialTheme.typography.bodyLarge) }
        if (cal.can.remind || i.can.remind) {
            val own = i.remind.ifEmpty { cal.reminder }
            Row(Modifier.fillMaxWidth().clickable(onClick = onChange).padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_sparkle, null, tint = mika.accent)
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(mikaReminderLine(own), style = MaterialTheme.typography.bodyLarge, color = mika.accent)
                    Text(
                        (if (i.remind.isNotEmpty()) stringResource(R.string.agenda_remind_this) else stringResource(R.string.agenda_remind_calendar, cal.name)) +
                            " · " + stringResource(R.string.agenda_remind_how),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(stringResource(R.string.agenda_change), color = mika.accent, style = MaterialTheme.typography.labelLarge)
            }
        }
    }
}

/** Supprimer : une série demande lequel ; sinon une confirmation (une invitation : la retirer, c'est la refuser). */
@Composable
private fun DeleteAsk(i: AgendaItem, cal: AgendaCalendar?, onDismiss: () -> Unit, onDelete: (String) -> Unit) {
    if (i.recurring && i.occurrence.isNotEmpty()) {
        ScopeDialog(stringResource(R.string.agenda_delete_series), danger = true, confirm = stringResource(R.string.agenda_delete), onDismiss = onDismiss, onScope = onDelete)
        return
    }
    val invitation = removesInvitation(i)
    val title = if (invitation) stringResource(R.string.agenda_remove_invitation) else stringResource(R.string.agenda_delete_event)
    val o = i.title.ifBlank { stringResource(R.string.agenda_no_title) }
    val text = if (invitation) {
        stringResource(R.string.agenda_remove_invitation_text, o)
    } else {
        stringResource(R.string.agenda_delete_text, o, deletedWhere(cal?.kind.orEmpty())) +
            if (i.participants.size > 1) " " + stringResource(R.string.agenda_participants_warned) else ""
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(onClick = { onDelete("un") }) {
                Text(stringResource(if (invitation) R.string.agenda_remove else R.string.agenda_delete), color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** La portée d'un geste sur une série : Cet événement · Celui-ci et les suivants · Tous les événements. */
@Composable
internal fun ScopeDialog(title: String, danger: Boolean, confirm: String, onDismiss: () -> Unit, withFollowing: Boolean = true, onScope: (String) -> Unit) {
    var scope by rememberSaveable { mutableStateOf("un") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                for ((k, label) in SCOPES) {
                    if (k == "suivants" && !withFollowing) continue
                    Row(Modifier.fillMaxWidth().selectable(scope == k, role = Role.RadioButton) { scope = k }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = scope == k, onClick = null)
                        Spacer(Modifier.width(10.dp))
                        Text(label)
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { onScope(scope) }) { Text(confirm, color = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.primary) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** « Modifier le mot » : la réponse, et le mot qui part avec — préparés par Mika, envoyés par toi. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun WordSheet(to: String, p: Proposal, cal: AgendaCalendar?, onDismiss: () -> Unit, onSend: (String, String) -> Unit) {
    var answer by rememberSaveable { mutableStateOf(p.answer.ifEmpty { "oui" }) }
    var word by rememberSaveable { mutableStateOf(p.comment) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.navigationBarsPadding().padding(horizontal = 24.dp, vertical = 8.dp)) {
            Text(stringResource(R.string.agenda_answer_to, to), style = MaterialTheme.typography.titleLarge)
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(vertical = 12.dp)) {
                ANSWERS.forEachIndexed { n, (k, label) ->
                    SegmentedButton(selected = answer == k, onClick = { answer = k }, shape = SegmentedButtonDefaults.itemShape(n, ANSWERS.size)) { Text(label, maxLines = 1) }
                }
            }
            OutlinedTextField(value = word, onValueChange = { word = it.take(500) }, label = { Text(stringResource(R.string.agenda_word_label)) }, minLines = 3, modifier = Modifier.fillMaxWidth())
            Text(
                stringResource(R.string.agenda_word_via, if (cal?.kind == AgendaKinds.SYSTEM) stringResource(R.string.agenda_word_in_agenda) else cal?.let { providerShort(it) }.orEmpty()),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 6.dp),
            )
            Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) }
                Spacer(Modifier.width(8.dp))
                Button(onClick = { onSend(answer, word.trim()) }) {
                    MIcon(R.drawable.ic_m_send, null, size = 18.dp)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.agenda_send))
                }
            }
        }
    }
}

/** « Mika te le rappelle » pour cet événement : comme l'agenda, ou un autre délai. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RemindSheet(i: AgendaItem, cal: AgendaCalendar?, onDismiss: () -> Unit, onPick: (String) -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 12.dp)) {
            Text(stringResource(R.string.agenda_remind_title), style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 24.dp))
            Text(
                stringResource(R.string.agenda_remind_sheet_note, i.title, cal?.name.orEmpty()),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 6.dp),
            )
            for ((k, label) in remindChoices(cal)) {
                val on = i.remind == k
                Row(
                    Modifier.fillMaxWidth().selectable(on, role = Role.RadioButton) { onPick(k) }.padding(horizontal = 24.dp, vertical = 12.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    MIcon(if (k == "non") R.drawable.ic_m_x else R.drawable.ic_m_bell, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Spacer(Modifier.width(16.dp))
                    Text(label, modifier = Modifier.weight(1f))
                    if (on) MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                }
            }
        }
    }
}

// ── ce que Mika propose ─────────────────────────────────────────────────

@Composable
fun AgendaProposalScreen(graph: AppGraph, route: Route.AgendaProposal) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: AgendaItemViewModel = viewModel(key = "agenda.proposal|$session|${route.id}") { AgendaItemViewModel(AgendaDeps(graph)) }
    LaunchedEffect(vm, route) { vm.open(0, "", route.id) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm) { vm.gone.collect { shell.back() } }
    FollowLive(graph.live, AGENDA_TOPICS, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val wall = rememberNow(wallMs = graph.clock::wallMs)
    var raw by rememberSaveable { mutableStateOf(false) }
    val p = vm.proposal.valueOrNull
    SectionScaffold(
        topBar = {
            FicheBar {
                val o = p?.let { occOfProposal(it, vm.zone) }
                if (o != null) {
                    BarAction(R.drawable.ic_m_sparkle, stringResource(R.string.agenda_ask_mika), {
                        askMika(shell, shell.graph.context.getString(R.string.agenda_ask_about, o.title, "${shortDay(o.day)}${if (o.allDay) "" else " à " + hm(o.start)}"))
                    }, tint = mika.accent)
                }
            }
        },
    ) { modifier ->
        LoadBox(vm.proposal, onRetry = vm::retry, modifier = modifier) { prop ->
            val (today, nowMinute) = vm.now(wall)
            val o = occOfProposal(prop, vm.zone)
            val cal = vm.calendar
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
                PinkBox(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                    Row(verticalAlignment = Alignment.Top) {
                        MikaFace(36.dp)
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                                Spacer(Modifier.width(4.dp))
                                Text(stringResource(R.string.agenda_proposes_to, cal?.name ?: stringResource(R.string.agenda_your_agenda)), style = MaterialTheme.typography.labelLarge, color = mika.accent)
                            }
                            if (prop.summary.isNotBlank()) Text(prop.summary, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(top = 4.dp))
                            if (prop.conversation.isNotBlank()) {
                                Text(stringResource(R.string.agenda_see_conversation), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary, modifier = Modifier.clickable { shell.open(Route.Chat) }.padding(vertical = 2.dp))
                            }
                            if (prop.decides) {
                                Row(Modifier.fillMaxWidth().padding(top = 6.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                                    TextButton(onClick = vm::refuse, enabled = !vm.acting) { Text(stringResource(R.string.agenda_refuse)) }
                                    if (prop.op == Proposal.ADD) TextButton(onClick = { shell.navigate(Route.AgendaForm(FormModes.PROPOSAL, proposal = prop.id)) }, enabled = !vm.acting) { Text(stringResource(R.string.agenda_modify)) }
                                    Button(onClick = vm::accept, enabled = !vm.acting && prop.preview?.blocked.isNullOrBlank()) {
                                        MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                                        Spacer(Modifier.width(6.dp))
                                        Text(stringResource(if (prop.op == Proposal.ADD) R.string.agenda_add else R.string.agenda_accept))
                                    }
                                }
                                if (prop.preview?.blocked?.isNotBlank() == true) Text(prop.preview.blocked, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
                            } else {
                                Text(stringResource(R.string.agenda_owner_decides), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
                            }
                        }
                    }
                }
                if (o != null) {
                    TitleBlock(o, "rose", today, nowMinute, listOf(stringResource(R.string.agenda_tag_not_yet) to Tone.MIKA))
                    val d = prop.draft
                    Group {
                        if (d != null && d.rule.isNotEmpty()) InfoRow(R.drawable.ic_m_repeat) { Text(ruleWords(d.rule, o.day, today), style = MaterialTheme.typography.bodyLarge) }
                        if (d != null && d.location.isNotBlank()) InfoRow(R.drawable.ic_m_pin) { Text(d.location, style = MaterialTheme.typography.bodyLarge) }
                        if (d != null && d.description.isNotBlank()) InfoRow(R.drawable.ic_m_threads) { Text(d.description, style = MaterialTheme.typography.bodyMedium) }
                        if (d != null && d.invite.isNotEmpty()) InfoRow(R.drawable.ic_m_users) { Text(stringResource(R.string.agenda_invited, d.invite.joinToString(", ")), style = MaterialTheme.typography.bodyMedium) }
                        CalendarRow(cal, colorOf(cal), null)
                    }
                    val remind = prop.remind?.takeIf { it.isNotEmpty() && it != "non" }
                    if (remind != null) {
                        SectionHead(stringResource(R.string.agenda_reminders))
                        Group { InfoRow(R.drawable.ic_m_sparkle) { Text(stringResource(R.string.agenda_will_remind, mikaReminderWords(remind)), style = MaterialTheme.typography.bodyLarge, color = mika.accent) } }
                    }
                }
                val text = prop.preview?.text.orEmpty()
                if (text.isNotBlank()) {
                    Row(Modifier.fillMaxWidth().clickable { raw = !raw }.padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        MIcon(if (raw) R.drawable.ic_m_chev_down else R.drawable.ic_m_chev_right, null, size = 16.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.agenda_what_leaves), style = MaterialTheme.typography.bodyMedium)
                    }
                    if (raw) {
                        Surface(shape = RoundedCornerShape(10.dp), color = MaterialTheme.colorScheme.surfaceContainerHigh, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
                            Text(text, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(10.dp))
                        }
                        Text(stringResource(R.string.agenda_only_buttons), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp))
                    }
                }
            }
        }
    }
}

// ── une date de sa mémoire ──────────────────────────────────────────────

@Composable
fun AgendaHerScreen(graph: AppGraph, route: Route.AgendaHer) {
    val shell = LocalShell.current
    val d = route.date
    val wall = rememberNow(wallMs = graph.clock::wallMs)
    // le fuseau du serveur : celui de la date, lu avec ses agendas (UTC tant qu'ils ne sont pas lus)
    val zone = remember { mutableStateOf("UTC") }
    LaunchedEffect(Unit) {
        (graph.agendaApi().calendars() as? fr.qwartz.mika.data.moi.MoiApi.Result.Ok)?.let { zone.value = it.value.zone.ifBlank { "UTC" } }
    }
    val o = occOfHer(d, zone.value)
    val today = localOf(wall, zone.value).day
    val nowMinute = localOf(wall, zone.value).minute
    SectionScaffold(
        topBar = {
            FicheBar {
                BarAction(R.drawable.ic_m_sparkle, stringResource(R.string.agenda_talk_to_her), {
                    askMika(shell, shell.graph.context.getString(R.string.agenda_talk_about, o.title.replaceFirstChar { it.lowercase() }))
                }, tint = mika.accent)
            }
        },
    ) { modifier ->
        Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            PinkBox(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    MikaFace(36.dp)
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                            Spacer(Modifier.width(4.dp))
                            Text(
                                stringResource(
                                    when (d.kind) {
                                        "promesse" -> R.string.agenda_her_promise
                                        "chaque_annee" -> R.string.agenda_her_yearly
                                        else -> R.string.agenda_her_moment
                                    },
                                ),
                                style = MaterialTheme.typography.labelLarge,
                                color = mika.accent,
                            )
                        }
                        if (d.source.isNotBlank()) Text(d.source, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, modifier = Modifier.padding(top = 4.dp))
                        if (d.conversation.isNotBlank()) {
                            Text(stringResource(R.string.agenda_see_conversation), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.primary, modifier = Modifier.clickable { shell.open(Route.Chat) }.padding(vertical = 2.dp))
                        }
                        if (d.saidAt > 0) Text(stringResource(R.string.agenda_said_on, dayWords(localOf(d.saidAt, zone.value).day, today)), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            TitleBlock(o, "rose", today, nowMinute)
            Group {
                InfoRow(R.drawable.ic_m_agenda) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Swatch("rose", 12.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.agenda_hers), style = MaterialTheme.typography.bodyLarge)
                    }
                    Text(stringResource(R.string.agenda_hers_line), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            FootNote(stringResource(R.string.agenda_hers_note), R.drawable.ic_m_lock, Modifier.padding(horizontal = 16.dp, vertical = 10.dp))
        }
    }
}
