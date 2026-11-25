package fr.qwartz.mika.ui.agenda

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.InputChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.agenda.ALERT_PRESETS
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaKinds
import fr.qwartz.mika.data.moi.agenda.Alert
import fr.qwartz.mika.data.moi.agenda.CustomRule
import fr.qwartz.mika.data.moi.agenda.FormModes
import fr.qwartz.mika.data.moi.agenda.FormValues
import fr.qwartz.mika.data.moi.agenda.RepeatChoice
import fr.qwartz.mika.data.moi.agenda.WEEK_LETTERS
import fr.qwartz.mika.data.moi.agenda.alertWords
import fr.qwartz.mika.data.moi.agenda.cap
import fr.qwartz.mika.data.moi.agenda.colorOf
import fr.qwartz.mika.data.moi.agenda.formDay
import fr.qwartz.mika.data.moi.agenda.formFoot
import fr.qwartz.mika.data.moi.agenda.hm
import fr.qwartz.mika.data.moi.agenda.hourChoices
import fr.qwartz.mika.data.moi.agenda.isDay
import fr.qwartz.mika.data.moi.agenda.mikaReminderLine
import fr.qwartz.mika.data.moi.agenda.offsetWords
import fr.qwartz.mika.data.moi.agenda.providerShort
import fr.qwartz.mika.data.moi.agenda.remindChoices
import fr.qwartz.mika.data.moi.agenda.repeatChoices
import fr.qwartz.mika.data.moi.agenda.ruleOf
import fr.qwartz.mika.data.moi.agenda.ruleWords
import fr.qwartz.mika.data.moi.agenda.withStartDay
import fr.qwartz.mika.data.moi.agenda.withStartMinute
import fr.qwartz.mika.data.moi.agenda.writableCalendars
import fr.qwartz.mika.data.moi.agenda.zoneChoices
import fr.qwartz.mika.data.moi.agenda.zoneLabel
import fr.qwartz.mika.data.moi.contacts.ContactsApi
import fr.qwartz.mika.data.moi.contacts.RecipientSuggester
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.mail.RecipientSuggestions
import fr.qwartz.mika.data.moi.mail.mailApi
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaFace
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import java.time.LocalDate
import java.time.ZoneOffset

/*
 * Créer et modifier un événement, en plein écran (la maquette validée `agenda-edition.js`, comme Google Agenda sur
 * Android) : ✕ et « Enregistrer » en haut ; le titre ; journée entière, début, fin (la date dans le calendrier d'Android,
 * l'heure dans une liste de demi-heures), le fuseau, la répétition ; les participants, tirés de tes contacts ; la visio
 * (un lien collé) ; le lieu ; les rappels du fournisseur et « Mika te le rappelle » (rose) ; l'agenda ; la description ;
 * occupé ou disponible, la visibilité. Ce que l'API ne sert pas n'y est pas : ni « Trouver un créneau avec eux », ni la
 * visio créée chez le fournisseur, ni la visibilité « Publique ».
 */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AgendaFormScreen(graph: AppGraph, route: Route.AgendaForm) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: AgendaFormViewModel = viewModel(key = "agenda.form|$session|$route") {
        val suggester = RecipientSuggester(ContactsApi(graph.moi), graph.mailApi())
        AgendaFormViewModel(AgendaDeps(graph)) { text, chosen -> suggester.lookup(text, chosen) }
    }
    LaunchedEffect(vm, route) { vm.open(route) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm) {
        vm.done.collect { next ->
            // la fiche de ce qu'il a écrit remplace le formulaire ; une modification revient à sa fiche
            if (next != null && route.mode != FormModes.EDIT) shell.replace(next) else shell.back()
        }
    }
    var sheet by rememberSaveable { mutableStateOf("") }
    val title = stringResource(
        when (route.mode) {
            FormModes.EDIT -> R.string.agenda_form_edit
            FormModes.COPY -> R.string.agenda_form_copy
            FormModes.PROPOSAL -> R.string.agenda_form_proposal
            else -> R.string.agenda_form_new
        },
    )
    SectionScaffold(
        topBar = {
            TopAppBar(
                navigationIcon = { BarAction(R.drawable.ic_m_x, stringResource(R.string.agenda_form_close), shell.back) },
                title = { Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                actions = {
                    Button(onClick = { vm.save() }, enabled = !vm.saving && vm.ready.valueOrNull != null, modifier = Modifier.padding(end = 8.dp)) {
                        if (route.mode == FormModes.PROPOSAL) {
                            MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                            Spacer(Modifier.width(6.dp))
                        }
                        Text(stringResource(if (route.mode == FormModes.PROPOSAL) R.string.agenda_add else R.string.agenda_save))
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
            )
        },
    ) { modifier ->
        LoadBox(vm.ready, onRetry = vm::retry, modifier = modifier) { f ->
            FormBody(vm, f.calendars, f.zone, route.mode, f.item != null && (f.item.participants.size > 1), onSheet = { sheet = it }, modifier = modifier)
        }
    }
    val f = vm.ready.valueOrNull
    if (f != null) {
        val v = vm.values
        val cal = f.calendars.firstOrNull { it.key == v.calendar }
        when (sheet) {
            "d1", "d2" -> DayDialog(if (sheet == "d1") v.d1 else v.d2, onDismiss = { sheet = "" }) { day ->
                if (sheet == "d1") vm.edit { withStartDay(it, day) } else vm.edit { it.copy(d2 = day) }
                sheet = ""
            }
            "h1", "h2" -> HourSheet(if (sheet == "h1") stringResource(R.string.agenda_form_start) else stringResource(R.string.agenda_form_end), sheet == "h2", v, onDismiss = { sheet = "" }) { m ->
                if (sheet == "h1") vm.edit { withStartMinute(it, m) } else vm.edit { it.copy(h2 = m) }
                sheet = ""
            }
            "zone" -> ChoiceSheet(stringResource(R.string.agenda_form_zone), zoneChoices(v.zone).map { it to "${zoneLabel(it)} · ${offsetWords(it, System.currentTimeMillis())}" }, v.zone, onDismiss = { sheet = "" }) { z ->
                vm.edit { it.copy(zone = z) }
                sheet = ""
            }
            "repeat" -> ChoiceSheet(stringResource(R.string.agenda_form_repeat), repeatChoices(v.d1).map { it.first.code to it.second }, v.repeat.code, onDismiss = { sheet = "" }) { code ->
                val c = RepeatChoice.entries.first { it.code == code }
                vm.edit { it.copy(repeat = c) }
                sheet = if (c == RepeatChoice.CUSTOM) "custom" else ""
            }
            "custom" -> CustomDialog(v, onDismiss = { sheet = "" }) { rule ->
                vm.edit { it.copy(repeat = RepeatChoice.CUSTOM, custom = rule) }
                sheet = ""
            }
            "visio" -> ChoiceSheet(stringResource(R.string.agenda_form_visio), listOf("" to stringResource(R.string.agenda_form_no_visio), "lien" to stringResource(R.string.agenda_form_paste_link)), if (v.visio) "lien" else "", onDismiss = { sheet = "" }) { k ->
                vm.edit { it.copy(visio = k == "lien", conference = if (k == "lien") it.conference else "") }
                sheet = ""
            }
            "alert" -> ChoiceSheet(
                stringResource(R.string.agenda_form_add_alert),
                ALERT_PRESETS.map { "notification:$it" to cap(alertWords(Alert(Alert.NOTIFICATION, it))) } +
                    if (cal?.providerReminders?.email == true) ALERT_PRESETS.map { "email:$it" to cap(alertWords(Alert(Alert.EMAIL, it))) } else emptyList(),
                "",
                onDismiss = { sheet = "" },
            ) { k ->
                vm.addAlert(Alert(k.substringBefore(':'), k.substringAfter(':').toInt()))
                sheet = ""
            }
            "mika" -> ChoiceSheet(stringResource(R.string.agenda_remind_title), remindChoices(cal), v.remind, onDismiss = { sheet = "" }) { k ->
                vm.edit { it.copy(remind = k) }
                sheet = ""
            }
            "calendar" -> ChoiceSheet(
                stringResource(R.string.agenda_form_calendar),
                writableCalendars(f.calendars).map { it.key to "${it.name} · ${providerShort(it)}" },
                v.calendar,
                onDismiss = { sheet = "" },
            ) { k ->
                vm.chooseCalendar(k)
                sheet = ""
            }
            "visibility" -> ChoiceSheet(stringResource(R.string.agenda_form_visibility), listOf("defaut" to stringResource(R.string.agenda_visibility_default_cap), "prive" to stringResource(R.string.agenda_form_private)), if (v.private) "prive" else "defaut", onDismiss = { sheet = "" }) { k ->
                vm.edit { it.copy(private = k == "prive") }
                sheet = ""
            }
        }
        if (vm.askScope) {
            ScopeDialog(stringResource(R.string.agenda_edit_series), danger = false, confirm = stringResource(R.string.agenda_ok), onDismiss = vm::dropScope) { vm.save(it) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun FormBody(vm: AgendaFormViewModel, calendars: List<AgendaCalendar>, zone: String, mode: String, warned: Boolean, onSheet: (String) -> Unit, modifier: Modifier) {
    val v = vm.values
    val cal = calendars.firstOrNull { it.key == v.calendar }
    val scheme = MaterialTheme.colorScheme
    Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 32.dp)) {
        if (mode == FormModes.PROPOSAL) {
            PinkBox(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
                Row(verticalAlignment = Alignment.Top) {
                    MikaFace(28.dp)
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text(stringResource(R.string.agenda_form_proposal_title), style = MaterialTheme.typography.labelLarge, color = mika.accent)
                        Text(stringResource(R.string.agenda_form_proposal_text), style = MaterialTheme.typography.bodyMedium)
                    }
                }
            }
        }
        TextField(
            value = v.title,
            onValueChange = { t -> vm.edit { it.copy(title = t.take(300)) } },
            placeholder = { Text(stringResource(R.string.agenda_form_title), fontSize = 24.sp) },
            textStyle = MaterialTheme.typography.headlineSmall,
            colors = TextFieldDefaults.colors(focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent),
            modifier = Modifier.fillMaxWidth().padding(start = 40.dp, end = 12.dp),
        )
        // quand
        FormRow(R.drawable.ic_m_clock) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.agenda_form_all_day), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                Switch(checked = v.allDay, onCheckedChange = { on -> vm.edit { it.copy(allDay = on) } })
            }
        }
        WhenRow(formDay(v.d1), if (v.allDay) null else hm(v.h1), { onSheet("d1") }, { onSheet("h1") })
        WhenRow(formDay(v.d2), if (v.allDay) null else hm(v.h2), { onSheet("d2") }, { onSheet("h2") })
        vm.problem?.let { Text(it, color = scheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 56.dp, bottom = 4.dp)) }
        if (!v.allDay) {
            FormRow(R.drawable.ic_m_globe, onClick = { onSheet("zone") }) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(zoneLabel(v.zone.ifBlank { zone }), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    Text(offsetWords(v.zone.ifBlank { zone }, System.currentTimeMillis()), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                }
            }
        }
        FormRow(R.drawable.ic_m_repeat, onClick = { onSheet("repeat") }) {
            val rule = ruleOf(v.repeat, v.d1, v.custom)
            Text(
                if (v.repeat == RepeatChoice.NONE) stringResource(R.string.agenda_form_no_repeat) else ruleWords(rule, v.d1, v.d1),
                style = MaterialTheme.typography.bodyLarge,
            )
        }
        HorizontalDivider()
        // les participants
        FormRow(R.drawable.ic_m_users) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                for (g in v.invite) {
                    InputChip(
                        selected = false,
                        onClick = { vm.removeGuest(g.address) },
                        label = { Text(g.name.ifBlank { g.address }, maxLines = 1) },
                        trailingIcon = { MIcon(R.drawable.ic_m_x, stringResource(R.string.agenda_form_guest_remove, g.name.ifBlank { g.address }), size = 16.dp) },
                    )
                }
            }
            TextField(
                value = vm.typed,
                onValueChange = vm::type,
                placeholder = { Text(stringResource(R.string.agenda_form_guests)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Done),
                keyboardActions = KeyboardActions(onDone = { vm.takeTyped() }),
                colors = TextFieldDefaults.colors(focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        RecipientSuggestions(vm.typed, vm.suggestions, vm.typed.trim()) { vm.pick(it) }
        Text(
            stringResource(if (cal?.kind == AgendaKinds.SYSTEM) R.string.agenda_form_guests_system else R.string.agenda_form_guests_provider),
            style = MaterialTheme.typography.bodySmall,
            color = scheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 56.dp, end = 16.dp, bottom = 8.dp),
        )
        HorizontalDivider()
        // la visio
        FormRow(R.drawable.ic_m_video, onClick = { onSheet("visio") }) {
            Text(stringResource(if (v.visio) R.string.agenda_form_paste_link else R.string.agenda_form_add_visio), style = MaterialTheme.typography.bodyLarge, color = if (v.visio) scheme.onSurface else scheme.onSurfaceVariant)
        }
        if (v.visio) {
            OutlinedTextField(
                value = v.conference,
                onValueChange = { t -> vm.edit { it.copy(conference = t.take(1000)) } },
                placeholder = { Text("https://…") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth().padding(start = 56.dp, end = 16.dp, bottom = 8.dp),
            )
        }
        HorizontalDivider()
        // le lieu
        FormRow(R.drawable.ic_m_pin) {
            TextField(
                value = v.location,
                onValueChange = { t -> vm.edit { it.copy(location = t.take(300)) } },
                placeholder = { Text(stringResource(R.string.agenda_form_place)) },
                colors = TextFieldDefaults.colors(focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        HorizontalDivider()
        // les rappels
        val max = cal?.providerReminders?.max ?: 0
        when {
            cal?.kind == AgendaKinds.SYSTEM -> FormRow(R.drawable.ic_m_bell) {
                Text(stringResource(R.string.agenda_system_no_reminders), style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant)
            }
            max == 0 -> FormRow(R.drawable.ic_m_bell) {
                Text(stringResource(R.string.agenda_form_no_alert, cal?.name.orEmpty()), style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant)
            }
            else -> {
                v.reminders.forEachIndexed { i, a ->
                    FormRow(if (i == 0) R.drawable.ic_m_bell else null) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(cap(alertWords(a)), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                            BarAction(R.drawable.ic_m_x, stringResource(R.string.agenda_form_alert_remove), { vm.removeAlert(i) })
                        }
                    }
                }
                if (max == 1) Text(stringResource(R.string.agenda_form_one_alert), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(start = 56.dp))
                if (v.reminders.size < max) {
                    FormRow(if (v.reminders.isEmpty()) R.drawable.ic_m_bell else null, onClick = { onSheet("alert") }) {
                        Text(stringResource(R.string.agenda_form_add_alert), style = MaterialTheme.typography.bodyLarge, color = scheme.primary)
                    }
                }
            }
        }
        if (cal?.owned == true) {
            FormRow(R.drawable.ic_m_sparkle, tint = mika.accent, onClick = { onSheet("mika") }) {
                Text(mikaReminderLine(v.remind.ifEmpty { cal.reminder }), style = MaterialTheme.typography.bodyLarge, color = mika.accent)
                Text(
                    (if (v.remind.isEmpty()) stringResource(R.string.agenda_remind_calendar, cal.name) + " · " else "") + stringResource(R.string.agenda_remind_how),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                )
            }
        }
        HorizontalDivider()
        // l'agenda
        FormRow(R.drawable.ic_m_agenda, onClick = if (mode == FormModes.EDIT) null else ({ onSheet("calendar") })) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Swatch(colorOf(cal), 12.dp)
                Spacer(Modifier.width(6.dp))
                Text(cal?.name.orEmpty(), style = MaterialTheme.typography.bodyLarge)
            }
            if (cal != null) Text(providerShort(cal), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            if (mode == FormModes.EDIT) Text(stringResource(R.string.agenda_form_stays), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
        }
        HorizontalDivider()
        FormRow(R.drawable.ic_m_threads) {
            TextField(
                value = v.description,
                onValueChange = { t -> vm.edit { it.copy(description = t.take(8000)) } },
                placeholder = { Text(stringResource(R.string.agenda_form_description)) },
                minLines = 2,
                colors = TextFieldDefaults.colors(focusedContainerColor = Color.Transparent, unfocusedContainerColor = Color.Transparent),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        HorizontalDivider()
        FormRow(R.drawable.ic_m_eye) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.agenda_form_show_as), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                SingleChoiceSegmentedButtonRow {
                    SegmentedButton(selected = !v.free, onClick = { vm.edit { it.copy(free = false) } }, shape = SegmentedButtonDefaults.itemShape(0, 2)) { Text(stringResource(R.string.agenda_busy)) }
                    SegmentedButton(selected = v.free, onClick = { vm.edit { it.copy(free = true) } }, shape = SegmentedButtonDefaults.itemShape(1, 2)) { Text(stringResource(R.string.agenda_free)) }
                }
            }
        }
        FormRow(R.drawable.ic_m_lock, onClick = { onSheet("visibility") }) {
            Text(stringResource(if (v.private) R.string.agenda_form_private else R.string.agenda_visibility_default_cap), style = MaterialTheme.typography.bodyLarge)
        }
        Row(Modifier.padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.Top) {
            MIcon(R.drawable.ic_m_refresh, null, size = 14.dp, tint = scheme.onSurfaceVariant)
            Spacer(Modifier.width(8.dp))
            Text(
                formFoot(cal) + if (warned && v.invite.isNotEmpty()) " " + stringResource(R.string.agenda_participants_warned) else "",
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
            )
        }
    }
}

/** Une ligne du formulaire : son icône (ou rien), son contenu, et ce qu'elle ouvre. */
@Composable
private fun FormRow(icon: Int?, onClick: (() -> Unit)? = null, tint: Color? = null, content: @Composable () -> Unit) {
    Row(
        Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).heightIn(min = 52.dp).padding(horizontal = 16.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) MIcon(icon, null, tint = tint ?: MaterialTheme.colorScheme.onSurfaceVariant) else Spacer(Modifier.width(24.dp))
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) { content() }
    }
}

/** Le jour et l'heure d'un bout de l'événement : chacun s'ouvre (le calendrier, la liste des heures). */
@Composable
private fun WhenRow(day: String, hour: String?, onDay: () -> Unit, onHour: () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(start = 56.dp, end = 16.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(day, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f).clickable(onClick = onDay).padding(vertical = 12.dp))
        if (hour != null) Text(hour, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.clickable(onClick = onHour).padding(12.dp))
    }
}

/** La date : le calendrier d'Android, dans une fenêtre. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DayDialog(day: String, onDismiss: () -> Unit, onPick: (String) -> Unit) {
    val initial = if (isDay(day)) LocalDate.parse(day).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli() else null
    val state = rememberDatePickerState(initialSelectedDateMillis = initial)
    DatePickerDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = {
                val ms = state.selectedDateMillis
                if (ms != null) onPick(java.time.Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate().toString()) else onDismiss()
            }) { Text(stringResource(R.string.agenda_ok)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    ) { DatePicker(state = state) }
}

/** L'heure : une liste de demi-heures, celle choisie en vue ; la fin dit sa durée. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun HourSheet(title: String, end: Boolean, v: FormValues, onDismiss: () -> Unit, onPick: (Int) -> Unit) {
    val current = if (end) v.h2 else v.h1
    val choices = (if (end && v.d2 == v.d1) hourChoices(true, v.h1) else hourChoices(false, 0)).let { list -> if (list.none { it.minute == current }) (list + fr.qwartz.mika.data.moi.agenda.HourChoice(current, hm(current), "")).sortedBy { it.minute } else list }
    val state = rememberLazyListState(initialFirstVisibleItemIndex = (choices.indexOfFirst { it.minute == current } - 2).coerceAtLeast(0))
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = 24.dp, bottom = 8.dp))
        LazyColumn(state = state, modifier = Modifier.navigationBarsPadding()) {
            items(choices, key = { it.minute }) { c ->
                val on = c.minute == current
                Row(
                    Modifier
                        .fillMaxWidth()
                        .selectable(on, role = Role.RadioButton) { onPick(c.minute) }
                        .padding(horizontal = 24.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(c.label, style = MaterialTheme.typography.bodyLarge, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal, modifier = Modifier.weight(1f))
                    if (c.duration.isNotEmpty()) Text(c.duration, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    if (on) {
                        Spacer(Modifier.width(12.dp))
                        MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                    }
                }
            }
        }
    }
}

/** Une feuille à choisir une valeur dans une liste ([selected] cochée). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ChoiceSheet(title: String, options: List<Pair<String, String>>, selected: String, onDismiss: () -> Unit, onPick: (String) -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 12.dp)) {
            Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = 24.dp, bottom = 8.dp))
            for ((k, label) in options) {
                val on = k == selected
                Row(
                    Modifier.fillMaxWidth().selectable(on, role = Role.RadioButton) { onPick(k) }.padding(horizontal = 24.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(label, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    if (on) MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                }
            }
        }
    }
}

/** « Personnalisée… » : tous les N jours, semaines, mois, ans ; les jours d'une semaine ; jamais, le…, après N fois. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun CustomDialog(v: FormValues, onDismiss: () -> Unit, onDone: (CustomRule) -> Unit) {
    var interval by rememberSaveable { mutableStateOf(v.custom.interval.toString()) }
    var unit by rememberSaveable { mutableStateOf(v.custom.unit) }
    var days by rememberSaveable { mutableStateOf(v.custom.days) }
    var ends by rememberSaveable { mutableStateOf(v.custom.ends) }
    var until by rememberSaveable { mutableStateOf(v.custom.until) }
    var count by rememberSaveable { mutableStateOf(v.custom.count.toString()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.agenda_form_custom)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(stringResource(R.string.agenda_form_every))
                    Spacer(Modifier.width(8.dp))
                    OutlinedTextField(interval, { interval = it.filter(Char::isDigit).take(3) }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.width(72.dp))
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    for (u in listOf("jours", "semaines", "mois", "ans")) FilterChip(selected = u == unit, onClick = { unit = u }, label = { Text(u) })
                }
                if (unit == "semaines") {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                        WEEK_LETTERS.forEachIndexed { i, l ->
                            val d = (i + 1) % 7
                            FilterChip(selected = d in days, onClick = { days = if (d in days) days - d else days + d }, label = { Text(l) }, modifier = Modifier)
                        }
                    }
                }
                Text(stringResource(R.string.agenda_form_ends))
                for ((k, label) in listOf("jamais" to stringResource(R.string.agenda_form_ends_never), "le" to stringResource(R.string.agenda_form_ends_on), "apres" to stringResource(R.string.agenda_form_ends_after))) {
                    Row(Modifier.selectable(ends == k, role = Role.RadioButton) { ends = k }, verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = ends == k, onClick = null)
                        Spacer(Modifier.width(6.dp))
                        Text(label)
                    }
                }
                if (ends == "le") OutlinedTextField(until, { until = it.take(10) }, singleLine = true, placeholder = { Text("AAAA-MM-JJ") }, label = { Text(stringResource(R.string.agenda_form_last_day)) })
                if (ends == "apres") OutlinedTextField(count, { count = it.filter(Char::isDigit).take(4) }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), label = { Text(stringResource(R.string.agenda_form_times)) })
                Text(
                    ruleWords(ruleOf(RepeatChoice.CUSTOM, v.d1, CustomRule(interval.toIntOrNull() ?: 1, unit, days, ends, until, count.toIntOrNull() ?: 1)), v.d1, v.d1),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { onDone(CustomRule(interval.toIntOrNull()?.coerceAtLeast(1) ?: 1, unit, days, ends, until, count.toIntOrNull() ?: 1)) }) {
                Text(stringResource(R.string.agenda_ok))
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}
