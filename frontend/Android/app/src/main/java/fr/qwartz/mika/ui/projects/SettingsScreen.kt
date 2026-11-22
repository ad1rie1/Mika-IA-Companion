package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.ProjectSettings
import fr.qwartz.mika.data.moi.projects.SettingField
import fr.qwartz.mika.data.moi.projects.SettingsSection
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.forWhom
import fr.qwartz.mika.data.moi.projects.isListField
import fr.qwartz.mika.data.moi.projects.planState
import fr.qwartz.mika.data.moi.projects.projectTone
import fr.qwartz.mika.data.moi.projects.sectionIcon
import fr.qwartz.mika.data.moi.projects.settingChoices
import fr.qwartz.mika.data.moi.projects.settingCodes
import fr.qwartz.mika.data.moi.projects.settingOn
import fr.qwartz.mika.data.moi.projects.settingShown
import fr.qwartz.mika.data.moi.projects.settingText
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

/*
 * « Modifier le projet » (ADR 0296), ouvert par le menu de la fiche : **ce que la gestion sert, rien de plus**. Ses
 * réglages en sections (`GET …/reglages`) : une liste — chaque section en une ligne —, puis la section en page, dont les
 * champs sont ceux que le serveur décrit (libellé, aide, choix, valeur) : l'app n'écrit aucun libellé. **Un champ
 * qu'elle ne peut pas changer** (`can: false` — son cadre n'est pas à elle, ou il est réservé à qui s'occupe de Mika)
 * **ne s'offre pas** : sa valeur se lit, verrouillée, avec la raison du serveur, et il ne part jamais. Enregistrer
 * n'envoie que ce qui change ; un refus se dit sur place, et sous le champ qu'il nomme. Et le projet lui-même : le
 * mettre en pause, le reprendre (`rights.pilot`), l'archiver (`archive.can`).
 */

@Composable
internal fun SettingsScreen(graph: AppGraph, route: Route.ProjectPage) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val project = rememberProjectModel(graph, route.id)
    val vm: SettingsViewModel = viewModel(key = "settings|$session|${route.id}") { SettingsViewModel(ProjectsDeps(graph), route.id) }
    Toasts(vm.gestures)
    Toasts(project.gestures)
    // la page s'ouvre : ce qu'on y avait dit avant de la quitter (un refus d'un autre jour) ne vaut plus
    FreshEntry(vm.gestures, SettingsViewModel.where(route.key), SettingsViewModel.PROJECT)
    FreshEntry(project.gestures, ProjectViewModel.TOP)
    // par page : la liste des sections et chaque section se relisent quand on y arrive
    OnResume(vm to route.key) {
        project.resume()
        vm.resume()
    }
    // la page d'une section quittée : ce qu'on y avait saisi sans l'enregistrer ne revient pas à la visite suivante
    OnLeave(vm, route.key) { vm.leave(route.key) }
    LaunchedEffect(vm.revision) { if (vm.revision > 0) project.reload() }
    // archivé, il n'existe plus dans cette API : retour à la rubrique, où il se désarchive
    LaunchedEffect(vm.archived) {
        if (vm.archived) {
            vm.archivedSeen()
            shell.open(Route.Projects(ProjectsTabs.PROJECTS))
        }
    }
    var archiving by rememberSaveable(route.id, route.key) { mutableStateOf(false) }
    val sheet = project.sheet.valueOrNull
    val settings = vm.settings.value
    val section = settings?.sections?.firstOrNull { it.name == route.key }?.takeIf { route.key.isNotEmpty() }
    // rien ne s'enregistre ni ne s'archive sur des réglages d'avant : ils se relisent au retour sur l'écran et après
    // un enregistrement
    val busy = vm.gestures.busy.isNotEmpty() || project.gestures.busy.isNotEmpty() || vm.settings.stale
    val notSentPlain = stringResource(R.string.proj_not_sent_plain)
    DetailPage(
        title = stringResource(R.string.proj_set_title),
        projectTitle = sheet?.project?.title,
        load = vm.settings.load,
        onRetry = vm.settings::retry,
        panes = { emptyList() },
        pane = "",
        onPane = {},
        head = { s ->
            val p = sheet?.project
            if (section != null) {
                CodeHead(projectIcon(sectionIcon(section.name)), StateTone.WORK, stringResource(R.string.proj_set_title), section.title, meta = { MetaText(section.summary) })
            } else if (p != null) {
                val plan = planState(p)
                CodeHead(R.drawable.ic_m_settings, projectTone(p.status), stringResource(R.string.proj_set_title), p.title, meta = {
                    StatePill(plan?.first ?: projectTone(p.status), plan?.second ?: p.statusLabel)
                    MetaText(forWhom(p))
                })
            }
            if (!s.can && s.why.isNotBlank()) Hint(s.why, R.drawable.ic_m_lock, Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
        },
        bottomBar = { s ->
            if (section != null && s.can && section.can) {
                Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp, shadowElevation = 6.dp) {
                    // au-dessus du clavier : la liste se resserre, et le champ qu'on remplit ne passe pas dessous
                    Row(Modifier.fillMaxWidth().navigationBarsPadding().imePadding().padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.End) {
                        Button(onClick = { vm.save(section) }, enabled = !busy && vm.changes(section).isNotEmpty()) {
                            MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                            Spacer(Modifier.width(6.dp))
                            Text(stringResource(R.string.proj_save))
                        }
                    }
                }
            }
        },
    ) { s ->
        if (section == null) {
            item(key = "what") { GroupLabel(stringResource(R.string.proj_set_what)) }
            keyedItems(s.sections, { "s${it.name}" }) { x -> SectionRow(x, s.can) { shell.navigate(Route.ProjectPage(route.id, SheetPages.SETTINGS, x.name)) } }
            if (s.sections.isEmpty()) item(key = "none") { EmptyNote(R.drawable.ic_m_settings, stringResource(R.string.proj_set_none), s.why.ifBlank { stringResource(R.string.proj_set_none_sub) }) }
            if (sheet != null) {
                paneBlock("project") { ProjectBlock(sheet, s, project, vm, busy) { archiving = true } }
            }
        } else {
            val where = SettingsViewModel.where(section.name)
            val typed = vm.typedIn(section.name)
            val errors = vm.gestures.fieldsAt(where)
            paneBlock("form") {
                RefusalNote(vm.gestures.refusalAt(where))
                // leur relecture a échoué : ce qu'on montre date d'avant, rien ne s'enregistre — on le dit
                StaleNote(vm.settings.staleError, { vm.settings.read(quiet = false) })
                if (s.can && !section.can && section.why.isNotBlank()) Hint(section.why, R.drawable.ic_m_lock)
                if (section.fields.isEmpty()) Muted(section.summary.ifBlank { stringResource(R.string.proj_set_none_sub) })
                for (f in section.fields.filter { settingShown(it, section.fields, typed) }) {
                    // un projet qu'elle a ouvert d'elle-même ne se renomme pas : le serveur le dit (`renamable`)
                    val locked = !s.can || !f.can || (f.name == "title" && !s.renamable)
                    val why = when {
                        f.why.isNotBlank() -> f.why
                        f.name == "title" && !s.renamable -> stringResource(R.string.proj_set_not_renamable)
                        else -> ""
                    }
                    if (locked) LockedField(f, typed, why) else SettingInput(f, typed, errors[f.name]) { vm.set(section.name, f.name, it) }
                }
            }
        }
    }
    if (archiving && sheet != null) {
        ConfirmDialog(
            stringResource(R.string.proj_set_archive),
            stringResource(R.string.proj_set_archive_text, sheet.project.title),
            stringResource(R.string.proj_set_archive_ok),
            onDismiss = { archiving = false },
            onConfirm = { if (!vm.archive()) shell.toast(notSentPlain) },
        )
    }
}

/** Une section dans la liste : son icône, son titre, elle en une ligne ; un cadenas quand rien ne s'y change d'ici. */
@Composable
private fun SectionRow(x: SettingsSection, can: Boolean, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Tile(projectIcon(sectionIcon(x.name)), StateTone.WORK)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(x.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold)
                Text(x.summary, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            if (can && !x.can) MIcon(R.drawable.ic_m_lock, x.why.ifBlank { null }, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

/** Le projet lui-même : le mettre en pause, le reprendre, l'archiver — chacun selon le droit servi, un refus dit sur place. */
@Composable
private fun ProjectBlock(sheet: Sheet, s: ProjectSettings, project: ProjectViewModel, vm: SettingsViewModel, busy: Boolean, onArchive: () -> Unit) {
    SideTitle(stringResource(R.string.proj_set_project))
    RefusalNote(vm.gestures.refusalAt(SettingsViewModel.PROJECT))
    RefusalNote(project.gestures.refusalAt(ProjectViewModel.TOP))
    // ses réglages ou sa fiche n'ont pas pu se relire : ce qu'on montre date d'avant, rien ne s'y décide — on le dit
    StaleNote(vm.settings.staleError, { vm.settings.read(quiet = false) })
    StaleNote(project.staleError, project::reread)
    val paused = sheet.project.status == "paused"
    if (sheet.rights.pilot) {
        // la pause et la reprise sont des gestes de la fiche : pas tant qu'elle se relit
        OutlinedButton(onClick = { project.pilot(if (paused) "resume" else "pause") }, enabled = !busy && !project.stale) {
            MIcon(if (paused) R.drawable.ic_m_play else R.drawable.ic_m_pause, null, size = 18.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(if (paused) R.string.proj_pilot_resume else R.string.proj_pilot_pause))
        }
    }
    if (s.archive.can) {
        OutlinedButton(onClick = onArchive, enabled = !busy) {
            MIcon(R.drawable.ic_m_archive, null, size = 18.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.proj_set_archive))
        }
        Hint(stringResource(R.string.proj_set_archive_hint))
    } else if (s.archive.why.isNotBlank()) {
        Hint(s.archive.why, R.drawable.ic_m_lock)
    }
}

/** Les mots de la valeur d'un champ, pour la lire : le libellé de son choix, « oui » ou « non », ses choix cochés. */
@Composable
private fun shownValue(f: SettingField, typed: Map<String, JsonElement>): String {
    val label: (String) -> String = { code -> f.choices.firstOrNull { it.code == code }?.label ?: code }
    return when {
        f.kind == "bool" -> stringResource(if (settingOn(f, typed)) R.string.proj_set_yes else R.string.proj_set_no)
        isListField(f) -> f.choices.filter { it.code in settingCodes(f, typed) }.joinToString(", ") { it.label }
        else -> label(settingText(f, typed))
    }.ifBlank { stringResource(R.string.proj_set_empty) }
}

/** Un champ qu'elle ne peut pas changer : son libellé, sa valeur à lire, et pourquoi — rien ne s'y saisit. */
@Composable
private fun LockedField(f: SettingField, typed: Map<String, JsonElement>, why: String) {
    Column {
        Text(f.label, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(shownValue(f, typed), style = MaterialTheme.typography.bodyLarge)
        if (why.isNotBlank()) {
            Row(Modifier.padding(top = 2.dp), verticalAlignment = Alignment.Top) {
                MIcon(R.drawable.ic_m_lock, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
                Spacer(Modifier.width(6.dp))
                Text(why, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/**
 * Un champ d'un réglage, décrit par le serveur : une case, des choix (un seul, ou plusieurs pour une liste), un texte
 * long, un nombre, un texte. Sa valeur saisie garde la sorte que le serveur attend.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SettingInput(f: SettingField, typed: Map<String, JsonElement>, error: String?, onChange: (JsonElement) -> Unit) {
    when {
        f.kind == "bool" -> {
            FormCheck(f.label, f.help, settingOn(f, typed)) { onChange(JsonPrimitive(it)) }
            if (!error.isNullOrBlank()) Text(error, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        isListField(f) -> Column {
            Text(f.label, style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
            if (f.help.isNotBlank()) Text(f.help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Gap(4.dp)
            val on = settingCodes(f, typed)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                for (c in f.choices) {
                    FilterChip(
                        selected = c.code in on,
                        onClick = {
                            val next = if (c.code in on) on - c.code else on + c.code
                            // dans l'ordre des choix servis
                            onChange(JsonArray(f.choices.filter { it.code in next }.map { JsonPrimitive(it.code) }))
                        },
                        label = { Text(c.label) },
                    )
                }
            }
            if (!error.isNullOrBlank()) Text(error, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        // les choix que le serveur sert, tels quels : un « — » posé d'office ne donnerait que « choisissez une valeur »
        f.choices.isNotEmpty() -> FormChoice(
            f.label,
            settingChoices(f),
            settingText(f, typed),
            { onChange(JsonPrimitive(it)) },
            f.help,
            error,
        )
        f.kind == "textarea" -> FormLong(f.label, settingText(f, typed), { onChange(JsonPrimitive(it)) }, rows = 4, help = f.help, error = error)
        f.kind == "int" -> FormText(
            f.label,
            settingText(f, typed),
            { onChange(JsonPrimitive(it.filter { ch -> ch.isDigit() || ch == '-' }.take(9))) },
            help = listOfNotNull(f.help.ifBlank { null }, bounds(f)).joinToString(" · "),
            error = error,
            number = true,
        )
        else -> FormText(f.label, settingText(f, typed), { onChange(JsonPrimitive(it)) }, help = f.help, error = error)
    }
}

/** Les bornes d'un nombre, telles que le serveur les dit : « de 1 à 24 ». */
private fun bounds(f: SettingField): String? {
    val lo = f.min?.toLong()
    val hi = f.max?.toLong()
    return when {
        lo != null && hi != null -> "de $lo à $hi"
        lo != null -> "au moins $lo"
        hi != null -> "au plus $hi"
        else -> null
    }
}
