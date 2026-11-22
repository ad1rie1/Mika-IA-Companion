package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.projects.CheckField
import fr.qwartz.mika.data.moi.projects.Coded
import fr.qwartz.mika.data.moi.projects.Field
import fr.qwartz.mika.data.moi.projects.Goal
import fr.qwartz.mika.data.moi.projects.GoalForm
import fr.qwartz.mika.data.moi.projects.Listing
import fr.qwartz.mika.data.moi.projects.Milestone
import fr.qwartz.mika.data.moi.projects.MilestoneForm
import fr.qwartz.mika.data.moi.projects.Objective
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.TicketForm
import fr.qwartz.mika.data.moi.projects.fieldShown
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.snapshots.SnapshotStateMap
import androidx.compose.runtime.saveable.Saver

/*
 * Les formulaires de l'écran Projets (ADR 0296) : chacun s'ouvre en feuille, par-dessus la vue, sans quitter où l'on
 * était — ajouter ou modifier un objectif, une mission, un jalon, un ticket ; lui confier un projet. Ce qu'ils
 * proposent vient du serveur : ce qui peut déclencher une mission et les façons de vérifier un jalon (`forms`), les
 * sortes et les priorités d'un ticket (`lists`), les champs de « Nouveau projet » (`GET …/nouveau`). Un refus se dit
 * en tête de la feuille, et sous le champ qu'il nomme.
 */

/**
 * Un formulaire en feuille : son titre, une ligne sous lui, ses champs qui défilent, puis « Annuler » et son bouton.
 * [busy] : son geste est parti, le bouton attend ; [error] : le refus du serveur, avec ses mots.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun FormSheet(
    title: String,
    sub: String,
    submit: String,
    busy: Boolean,
    error: String,
    onDismiss: () -> Unit,
    onSubmit: () -> Unit,
    enabled: Boolean = true,
    content: @Composable ColumnScope.() -> Unit,
) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding()) {
            Column(Modifier.padding(horizontal = 20.dp)) {
                Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.semantics { heading() })
                if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Column(
                Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 14.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                RefusalNote(error)
                content()
            }
            HorizontalDivider()
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) }
                Spacer(Modifier.width(8.dp))
                Button(onClick = onSubmit, enabled = enabled && !busy) { Text(submit) }
            }
        }
    }
}

/**
 * La feuille se ferme quand son geste a abouti — celui qu'elle a envoyé : en s'ouvrant, elle oublie ce qu'on avait dit
 * à son endroit (un refus d'avant, un geste abouti après qu'on l'a quittée, qui la refermerait aussitôt).
 */
@Composable
private fun CloseWhenDone(runner: GestureRunner, where: String, onDismiss: () -> Unit) {
    FreshEntry(runner, where)
    LaunchedEffect(runner.finished) {
        if (runner.finished == where) {
            runner.acknowledge()
            onDismiss()
        }
    }
}

@Composable
private fun FieldLabel(text: String, help: String = "") {
    Column {
        Text(text, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
        if (help.isNotBlank()) Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Un champ d'une ligne ; [error] : ce que le serveur en a refusé, dit sous lui. */
@Composable
internal fun FormText(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    hint: String = "",
    help: String = "",
    error: String? = null,
    number: Boolean = false,
    mono: Boolean = false,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        placeholder = if (hint.isNotBlank()) ({ Text(hint) }) else null,
        singleLine = true,
        isError = !error.isNullOrBlank(),
        supportingText = (error?.takeIf { it.isNotBlank() } ?: help).takeIf { it.isNotBlank() }?.let { said -> { Text(said) } },
        keyboardOptions = if (number) KeyboardOptions(keyboardType = KeyboardType.Number) else KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        textStyle = if (mono) MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace) else MaterialTheme.typography.bodyLarge,
        modifier = Modifier.fillMaxWidth(),
    )
}

/** Un champ de plusieurs lignes. */
@Composable
internal fun FormLong(
    label: String,
    value: String,
    onChange: (String) -> Unit,
    rows: Int = 3,
    hint: String = "",
    help: String = "",
    error: String? = null,
) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        placeholder = if (hint.isNotBlank()) ({ Text(hint) }) else null,
        minLines = rows,
        maxLines = rows + 8,
        isError = !error.isNullOrBlank(),
        supportingText = (error?.takeIf { it.isNotBlank() } ?: help).takeIf { it.isNotBlank() }?.let { said -> { Text(said) } },
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        modifier = Modifier.fillMaxWidth(),
    )
}

/** Un choix en grandes cartes (ce que c'est, comment on le vérifie) : le titre et l'aide de chaque option. */
@Composable
internal fun FormCards(label: String, options: List<Triple<String, String, String>>, value: String, onPick: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        FieldLabel(label)
        for ((code, title, help) in options) {
            val on = code == value
            Surface(
                shape = RoundedCornerShape(14.dp),
                color = if (on) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surface,
                border = BorderStroke(if (on) 2.dp else 1.dp, if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant),
                modifier = Modifier.fillMaxWidth().selectable(selected = on, role = Role.RadioButton, onClick = { onPick(code) }),
            ) {
                Column(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                    Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                    if (help.isNotBlank()) Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

/** Un choix parmi les options que le serveur sert (une sorte, une priorité, une liste), en pastilles. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun FormChoice(label: String, options: List<Coded>, value: String, onPick: (String) -> Unit, help: String = "", error: String? = null) {
    if (options.isEmpty()) return
    Column {
        FieldLabel(label, help)
        Gap(4.dp)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            for (o in options) FilterChip(selected = o.code == value, onClick = { onPick(o.code) }, label = { Text(o.label) })
        }
        if (!error.isNullOrBlank()) Text(error, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
    }
}

/** Une case à cocher, son nom et une ligne sous lui. */
@Composable
internal fun FormCheck(label: String, help: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().toggleable(value = checked, role = Role.Checkbox, onValueChange = onChange).padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = checked, onCheckedChange = null)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(label, style = MaterialTheme.typography.bodyLarge)
            if (help.isNotBlank()) Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

// ── Un objectif, une mission ────────────────────────────────────────────

/** « Ajouter un objectif » ([goal] `null` : ponctuel ou mission), ou le modifier. Ses déclencheurs sont ceux de `forms`. */
@Composable
internal fun GoalFormSheet(vm: ProjectViewModel, sheet: Sheet, goal: Goal?, onDismiss: () -> Unit) {
    val before = remember(goal?.key) {
        when (goal) {
            is Goal.Once -> GoalForm.of(goal.o)
            is Goal.Constant -> GoalForm.of(goal.m)
            null -> null
        }
    }
    // ce qui est saisi survit à une rotation
    var form by rememberSaveable(goal?.key) { mutableStateOf(before ?: GoalForm()) }
    var cadence by rememberSaveable(goal?.key) { mutableStateOf((before?.cadenceHours ?: 0).toString()) }
    val where = if (goal == null) ProjectViewModel.GOAL_NEW else ProjectViewModel.goalFormWhere(goal.id)
    val errors = vm.gestures.fieldsAt(where)
    CloseWhenDone(vm.gestures, where, onDismiss)
    FormSheet(
        title = stringResource(
            when {
                goal == null -> R.string.proj_goal_add
                form.mission -> R.string.proj_mission_edit
                else -> R.string.proj_goal_edit
            },
        ),
        sub = stringResource(if (goal == null) R.string.proj_goal_add_sub else R.string.proj_goal_edit_sub),
        submit = stringResource(if (goal == null) R.string.proj_add else R.string.proj_save),
        // rien ne part tant que la fiche se relit : le bouton attend, et une relecture en panne se dit ici
        busy = vm.gestures.busy == where || vm.stale,
        error = vm.saidAt(where),
        onDismiss = onDismiss,
        onSubmit = { vm.saveGoal(form.copy(cadenceHours = cadence.trim().toIntOrNull() ?: 0), before, goal?.id ?: 0) },
        enabled = form.text.isNotBlank(),
    ) {
        if (goal == null) {
            FormCards(
                stringResource(R.string.proj_goal_kind),
                listOf(
                    Triple("once", stringResource(R.string.proj_goal_kind_once), stringResource(R.string.proj_goal_kind_once_help)),
                    Triple("constant", stringResource(R.string.proj_goal_kind_mission), stringResource(R.string.proj_goal_kind_mission_help)),
                ),
                if (form.mission) "constant" else "once",
            ) { form = form.copy(mission = it == "constant") }
        }
        FormText(
            stringResource(if (form.mission) R.string.proj_goal_text_mission else R.string.proj_goal_text),
            form.text,
            { form = form.copy(text = it) },
            hint = stringResource(R.string.proj_goal_text_hint),
            error = errors["text"],
        )
        if (!form.mission) {
            FormLong(
                stringResource(R.string.proj_goal_done_when),
                form.doneWhen,
                { form = form.copy(doneWhen = it) },
                rows = 2,
                hint = stringResource(R.string.proj_goal_done_when_hint),
                error = errors["done_when"],
            )
        } else {
            FormText(
                stringResource(R.string.proj_goal_cadence),
                cadence,
                { cadence = it.filter(Char::isDigit).take(5) },
                help = stringResource(R.string.proj_goal_cadence_help),
                error = errors["cadence_hours"],
                number = true,
            )
            val triggers = sheet.forms.triggers
            if (triggers.isNotEmpty()) {
                Column {
                    FieldLabel(
                        stringResource(R.string.proj_goal_triggers),
                        if (sheet.forms.triggersMax > 0) stringResource(R.string.proj_goal_triggers_max, sheet.forms.triggersMax) else "",
                    )
                    for (t in triggers) {
                        FormCheck(t.label, t.sortLabel, t.key in form.on) { on ->
                            form = form.copy(on = if (on) form.on + t.key else form.on - t.key)
                        }
                    }
                    errors["on"]?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
                }
            }
            FormCheck(stringResource(R.string.proj_goal_only_event), stringResource(R.string.proj_goal_only_event_help), form.onlyOnEvent) {
                form = form.copy(onlyOnEvent = it)
            }
            FormLong(
                stringResource(R.string.proj_goal_each_pass),
                form.eachPass,
                { form = form.copy(eachPass = it) },
                rows = 3,
                hint = stringResource(R.string.proj_goal_each_pass_hint),
                error = errors["each_pass"],
            )
            if (goal == null) {
                FormCheck(stringResource(R.string.proj_goal_at_once), stringResource(R.string.proj_goal_at_once_help), form.atOnce) {
                    form = form.copy(atOnce = it)
                }
            }
        }
    }
}

// ── Un jalon ────────────────────────────────────────────────────────────

/** « Ajouter un jalon » ([milestone] `null`), ou le modifier : les façons de le vérifier, leurs mots et leurs champs sont ceux de `forms.checks`. */
@Composable
internal fun MilestoneFormSheet(vm: ProjectViewModel, sheet: Sheet, objective: Objective, milestone: Milestone?, onDismiss: () -> Unit) {
    val checks = sheet.forms.checks
    val before = remember(milestone?.id) { milestone?.let { MilestoneForm.of(it) } }
    var form by rememberSaveable(milestone?.id) { mutableStateOf(before ?: MilestoneForm(check = checks.firstOrNull()?.code ?: "prose")) }
    val where = ProjectViewModel.milestoneWhere(objective.id)
    val errors = vm.gestures.fieldsAt(where)
    CloseWhenDone(vm.gestures, where, onDismiss)
    FormSheet(
        title = stringResource(if (milestone == null) R.string.proj_milestone_add else R.string.proj_milestone_edit),
        sub = objective.text,
        submit = stringResource(if (milestone == null) R.string.proj_add else R.string.proj_save),
        busy = vm.gestures.busy == where || vm.stale,
        error = vm.saidAt(where),
        onDismiss = onDismiss,
        onSubmit = { vm.saveMilestone(objective.id, form, before, milestone?.id ?: 0) },
        enabled = form.text.isNotBlank(),
    ) {
        FormText(
            stringResource(R.string.proj_milestone_text),
            form.text,
            { form = form.copy(text = it) },
            hint = stringResource(R.string.proj_milestone_text_hint),
            error = errors["text"],
        )
        if (checks.isNotEmpty()) {
            FormCards(stringResource(R.string.proj_milestone_check), checks.map { Triple(it.code, it.label, it.help) }, form.check) {
                form = form.copy(check = it)
            }
            errors["check"]?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error) }
        }
        for (f in checks.firstOrNull { it.code == form.check }?.fields.orEmpty()) {
            CheckFieldInput(sheet, f, form, errors[f.name]) { form = form.with(f.name, it) }
        }
        if (milestone != null) {
            FormText(stringResource(R.string.proj_milestone_reason), form.reason, { form = form.copy(reason = it) })
        }
    }
}

/**
 * Un champ d'une façon de vérifier un jalon : son libellé et son aide sont ceux du serveur ; la liste et le statut se
 * choisissent parmi ceux que la fiche sert, le reste se saisit.
 */
@Composable
private fun CheckFieldInput(sheet: Sheet, f: CheckField, form: MilestoneForm, error: String?, onChange: (String) -> Unit) {
    val lists = sheet.lists
    val value = form.field(f.name)
    when {
        f.name == "item_list" && lists.isNotEmpty() ->
            FormChoice(f.label, lists.map { Coded(it.name, it.title) }, value, onChange, f.help, error)
        f.name == "item_status" && lists.isNotEmpty() -> {
            val chosen = lists.firstOrNull { it.name == form.itemList }
            val options = if (chosen != null) {
                chosen.open + chosen.closed
            } else {
                lists.flatMap { l -> (l.open + l.closed).map { Coded(it.code, "${l.title} · ${it.label}") } }
            }
            FormChoice(f.label, options.distinctBy { it.code }, value, onChange, f.help, error)
        }
        else -> FormText(f.label, value, onChange, help = f.help, error = error, mono = f.name == "command")
    }
}

// ── Un ticket ───────────────────────────────────────────────────────────

/** « Nouveau ticket », ou « Modifier » : son titre, sa sorte, sa priorité (celles que la fiche sert), sa description. */
@Composable
internal fun TicketFormSheet(
    title: String,
    sub: String,
    submit: String,
    list: Listing?,
    initial: TicketForm,
    editing: Boolean,
    born: String,
    runner: GestureRunner,
    where: String,
    onSubmit: (TicketForm) -> Unit,
    onDismiss: () -> Unit,
    /** Ce dont le geste dépend se relit : rien ne part d'ici là ; [waitsWhy] : sa relecture a échoué, avec ses mots. */
    waits: Boolean = false,
    waitsWhy: String = "",
) {
    var form by rememberSaveable(where) { mutableStateOf(initial) }
    val errors = runner.fieldsAt(where)
    CloseWhenDone(runner, where, onDismiss)
    FormSheet(
        title = title,
        sub = sub,
        submit = submit,
        busy = runner.busy == where || waits,
        error = runner.refusalAt(where).ifBlank { waitsWhy },
        onDismiss = onDismiss,
        onSubmit = { onSubmit(form) },
        enabled = form.title.isNotBlank(),
    ) {
        FormText(
            stringResource(R.string.proj_ticket_title),
            form.title,
            { form = form.copy(title = it) },
            hint = stringResource(R.string.proj_ticket_title_hint),
            error = errors["title"],
        )
        FormChoice(stringResource(R.string.proj_ticket_kind), list?.kinds.orEmpty(), form.kind, { form = form.copy(kind = it) }, error = errors["kind"])
        FormChoice(stringResource(R.string.proj_ticket_priority), list?.priorities.orEmpty(), form.priority, { form = form.copy(priority = it) }, error = errors["priority"])
        FormLong(
            stringResource(if (editing) R.string.proj_ticket_body else R.string.proj_ticket_expect),
            form.text,
            { form = form.copy(text = it) },
            rows = if (editing) 8 else 6,
            hint = stringResource(R.string.proj_ticket_body_hint),
            help = stringResource(R.string.proj_ticket_body_help),
            error = errors["text"],
        )
        if (born == "proposed") Hint(stringResource(R.string.proj_ticket_born_proposed))
    }
}

// ── Nouveau projet ──────────────────────────────────────────────────────

/** Ce qui est saisi dans des champs servis, par leur nom, gardé avec l'écran. */
private val FieldValuesSaver: Saver<SnapshotStateMap<String, String>, HashMap<String, String>> = Saver(
    save = { HashMap(it) },
    restore = { saved -> mutableStateMapOf<String, String>().apply { putAll(saved) } },
)

/** « Nouveau projet » : ses champs sont ceux que le serveur décrit (`GET …/projets/nouveau`), l'app n'écrit aucun libellé. */
@Composable
internal fun NewProjectSheet(vm: ProjectsViewModel) {
    val load = vm.fresh ?: return
    // ce qui est saisi survit à une rotation (la feuille, elle, est tenue par le modèle)
    val values = rememberSaveable(saver = FieldValuesSaver) { mutableStateMapOf() }
    val where = ProjectsViewModel.NEW
    val form = load.valueOrNull
    val errors = vm.gestures.fieldsAt(where)
    FormSheet(
        title = stringResource(R.string.proj_new_title),
        sub = stringResource(R.string.proj_new_sub),
        submit = stringResource(R.string.proj_new_submit),
        busy = vm.gestures.busy == where,
        error = vm.gestures.refusalAt(where).ifBlank { form?.takeIf { !it.can }?.why.orEmpty() },
        onDismiss = vm::closeNew,
        onSubmit = { vm.create(values.toMap()) },
        enabled = form?.can == true,
    ) {
        when (load) {
            Load.Loading -> Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            is Load.Failed -> {
                RefusalNote(load.error.said)
                TextButton(onClick = vm::openNew) { Text(stringResource(R.string.retry)) }
            }
            is Load.Ready -> {
                val fields = load.value.fields
                for (f in fields.filter { fieldShown(it, fields, values) }) {
                    ServedField(f, values[f.name] ?: f.value, errors[f.name]) { values[f.name] = it }
                }
            }
        }
    }
}

/** Un champ décrit par le serveur : son libellé, son aide et ses choix sont les siens (les réglages d'un projet s'en serviront aussi). */
@Composable
internal fun ServedField(f: Field, value: String, error: String?, onChange: (String) -> Unit) {
    when {
        f.kind == "bool" -> FormCheck(f.label, f.help, value == "true") { onChange(if (it) "true" else "false") }
        f.choices.isNotEmpty() -> FormChoice(f.label, f.choices, value, onChange, f.help, error)
        f.kind == "textarea" -> FormLong(f.label, value, onChange, rows = 4, help = f.help, error = error)
        else -> FormText(f.label, value, onChange, help = f.help, error = error, number = f.kind == "int")
    }
}
