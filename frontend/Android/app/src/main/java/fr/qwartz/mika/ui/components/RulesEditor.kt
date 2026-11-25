package fr.qwartz.mika.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.toggleable
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.settings.RuleEdit
import fr.qwartz.mika.data.moi.settings.RulesKind
import fr.qwartz.mika.data.moi.settings.SendRules
import fr.qwartz.mika.data.moi.settings.edit
import fr.qwartz.mika.data.moi.settings.ruleWho
import fr.qwartz.mika.data.moi.settings.rulesHelp
import fr.qwartz.mika.data.moi.settings.sendChoices
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon

/**
 * « Comment part ce que Mika y prépare » (ADR 0207), pour une boîte comme pour un compte Teams : pour chaque ligne de la
 * règle de son canal et pour la ligne par défaut, préparer d'elle-même et comment ça part. Qui écrit, quand, l'ordre et
 * le nombre des lignes restent à la console : ici, elles se lisent. Ce qu'on y change part avec le reste du formulaire,
 * par la même barre « Enregistrer » (`POST /rules`, avec la version lue).
 */
@Composable
internal fun RulesEditor(
    rules: SendRules,
    kind: RulesKind,
    lines: List<RuleEdit>,
    default: RuleEdit,
    onLine: (Int, RuleEdit) -> Unit,
    onDefault: (RuleEdit) -> Unit,
) {
    val shell = LocalShell.current
    SetHead(stringResource(R.string.settings_rules))
    SetGroup {
        rules.lines.forEachIndexed { i, line ->
            if (i > 0) SetDivider()
            RuleRow("${i + 1}", ruleWho(line), "", lines.getOrElse(i) { line.edit }, kind) { onLine(i, it) }
        }
        if (rules.lines.isNotEmpty()) SetDivider()
        RuleRow(null, stringResource(R.string.settings_rules_default), stringResource(R.string.settings_rules_default_help), default, kind, onDefault)
    }
    SetNote(rulesHelp(rules, kind))
    TextButton(onClick = { shell.navigate(Route.Tools()) }, modifier = Modifier.padding(horizontal = 16.dp)) {
        MIcon(R.drawable.ic_m_tools, null, size = 18.dp)
        Spacer(Modifier.width(8.dp))
        Text(stringResource(R.string.settings_rules_tools))
    }
}

/** Une ligne de la règle : qui elle désigne, préparer d'elle-même (un interrupteur), comment ça part (une liste). */
@Composable
private fun RuleRow(n: String?, who: String, help: String, edit: RuleEdit, kind: RulesKind, onEdit: (RuleEdit) -> Unit) {
    Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
        Row(Modifier.padding(horizontal = 14.dp), verticalAlignment = Alignment.CenterVertically) {
            if (n != null) {
                Text(n, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(10.dp))
            }
            Column(Modifier.weight(1f)) {
                Text(who, style = MaterialTheme.typography.bodyLarge, fontWeight = if (n == null) FontWeight.Medium else FontWeight.Normal)
                if (help.isNotBlank()) Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 48.dp)
                .toggleable(value = edit.prepare, role = Role.Switch, onValueChange = { onEdit(edit.copy(prepare = it)) })
                .padding(horizontal = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(stringResource(R.string.settings_rules_prepare), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Switch(checked = edit.prepare, onCheckedChange = null)
        }
        PickField(stringResource(R.string.settings_rules_reply), sendChoices(kind, edit.reply), edit.reply, { onEdit(edit.copy(reply = it)) })
    }
}
