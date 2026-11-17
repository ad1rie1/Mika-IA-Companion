package fr.qwartz.mika.ui.tools

import android.content.ActivityNotFoundException
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.tools.LevelWords
import fr.qwartz.mika.data.moi.tools.Rights
import fr.qwartz.mika.data.moi.tools.RightsCanal
import fr.qwartz.mika.data.moi.tools.RightsTool
import fr.qwartz.mika.data.moi.tools.ToolsResource
import fr.qwartz.mika.data.moi.tools.askFor
import fr.qwartz.mika.data.moi.tools.canalName
import fr.qwartz.mika.data.moi.tools.canalOrder
import fr.qwartz.mika.data.moi.tools.conditionOf
import fr.qwartz.mika.data.moi.tools.consoleFor
import fr.qwartz.mika.data.moi.tools.consoleUrl
import fr.qwartz.mika.data.moi.tools.labelOf
import fr.qwartz.mika.data.moi.tools.levelOf
import fr.qwartz.mika.data.moi.tools.lineFor
import fr.qwartz.mika.data.moi.tools.openElsewhere
import fr.qwartz.mika.data.moi.tools.pillsOf
import fr.qwartz.mika.data.moi.tools.whyOf
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.SheetLine
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.launch

/** La feuille « Par où elle te parle » : chaque canal, l'app Android d'abord ; le choix vaut pour la session. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun CanalSheet(canals: List<RightsCanal>, chosen: String, onPick: (String) -> Unit, onDismiss: () -> Unit) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(bottom = 12.dp)) {
            Text(
                stringResource(R.string.tools_canal_sheet),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
            )
            for (c in canalOrder(canals)) {
                SheetLine(
                    icon = canalIcon(c.key),
                    title = canalName(c),
                    subtitle = "",
                    count = 0,
                    selected = c.key == chosen,
                    onClick = {
                        onPick(c.key)
                        onDismiss()
                    },
                )
            }
        }
    }
}

/**
 * La feuille d'un outil, « Ce qui décide » : ce qu'il fait (son service en dit plus pour un outil venu d'ailleurs), sa
 * condition, puis, pour le canal choisi et chacun de ses moments, la case — pourquoi (`why`, ce qui le ferme avant ses
 * lignes compris), ce qu'elle garde — et, pour une opératrice, la ligne même ; où elle s'en sert par les autres canaux ;
 * son nom de code, en petit. En bas : sa page dans la console (une opératrice) et « Lui demander ».
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
internal fun ToolSheet(
    graph: AppGraph,
    rights: Rights,
    res: ToolsResource,
    tool: RightsTool,
    canal: String,
    operator: Boolean,
    onDismiss: () -> Unit,
) {
    val shell = LocalShell.current
    val context = LocalContext.current
    val scheme = MaterialTheme.colorScheme
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val canalLabel = rights.canals.firstOrNull { it.key == canal }?.let(::canalName) ?: canal
    val console = consoleFor(res, operator)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.verticalScroll(rememberScrollState()).navigationBarsPadding().padding(start = 24.dp, end = 24.dp, bottom = 16.dp)) {
            Text(labelOf(tool), style = MaterialTheme.typography.titleLarge)
            Text(
                "${res.title} · ${stringResource(if (tool.acts) R.string.tools_sheet_acts else R.string.tools_sheet_reads)}",
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
            )
            if (tool.label.isBlank() && tool.description.isNotBlank()) {
                Gap(8.dp)
                Text(stringResource(R.string.tools_sheet_said, tool.description.trim()), style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant)
            }
            val condition = conditionOf(tool)
            if (condition.isNotEmpty()) {
                Gap(8.dp)
                Row(verticalAlignment = Alignment.Top) {
                    MIcon(R.drawable.ic_m_lock, null, size = 16.dp, tint = scheme.onSurfaceVariant)
                    Spacer(Modifier.width(8.dp))
                    Text(condition, style = MaterialTheme.typography.bodyMedium)
                }
            }

            Gap(16.dp)
            Over(stringResource(R.string.tools_sheet_decides))
            Text(stringResource(R.string.tools_sheet_by, canalLabel), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
            for (p in pillsOf(tool, canal, rights.moments)) {
                val level = levelOf(p.cell)
                Gap(10.dp)
                Text(p.moment.label, style = MaterialTheme.typography.labelLarge, color = scheme.onSurfaceVariant)
                Gap(4.dp)
                CellLine(level, level.long)
                val cell = p.cell
                if (cell != null) {
                    val why = whyOf(cell)
                    if (why.why.isNotEmpty()) Said(stringResource(R.string.tools_sheet_why, why.why))
                    if (why.keep.isNotEmpty()) Said(stringResource(R.string.tools_sheet_keep, why.keep))
                    val line = lineFor(cell, operator)
                    if (line.isNotEmpty()) Said(stringResource(R.string.tools_sheet_line, line), mono = true)
                }
            }

            Gap(16.dp)
            Over(stringResource(R.string.tools_sheet_elsewhere))
            val elsewhere = openElsewhere(tool, rights, canal)
            if (elsewhere.isEmpty()) {
                Text(stringResource(R.string.tools_sheet_elsewhere_none), style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant)
            } else {
                for (o in elsewhere) {
                    Gap(4.dp)
                    CellLine(o.level, stringResource(R.string.tools_sheet_where, o.canal, o.moment))
                }
            }

            Gap(16.dp)
            Text(
                stringResource(R.string.tools_sheet_name, tool.name),
                style = MaterialTheme.typography.labelSmall.copy(fontFamily = FontFamily.Monospace),
                color = scheme.onSurfaceVariant,
            )
            Gap(16.dp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (console != null) {
                    OutlinedButton(onClick = {
                        val url = graph.auth.credentials()?.base?.let { consoleUrl(it, console) }
                        if (url != null) {
                            try {
                                context.startActivity(Intent(Intent.ACTION_VIEW, url.toString().toUri()))
                            } catch (_: ActivityNotFoundException) {
                            }
                        }
                    }) {
                        MIcon(R.drawable.ic_m_external, null, size = 18.dp)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.tools_sheet_console))
                    }
                }
                FilledTonalButton(onClick = {
                    // la demande posée dans le champ du chat, à relire avant d'envoyer (la même aide que Paramètres ›
                    // Compte) ; ce qui y était écrit reste
                    graph.scope.launch { graph.shareInbox.deposit(ComposerDraft(text = askFor(tool))) }
                    onDismiss()
                    shell.open(Route.Chat)
                }) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp, tint = mika.accent)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.tools_sheet_ask))
                }
            }
        }
    }
}

/** Un petit titre de section (`.over` de la maquette). */
@Composable
private fun Over(text: String) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(bottom = 4.dp),
    )
}

/** Une case en une ligne : sa pastille, et ce qu'elle dit. */
@Composable
private fun CellLine(level: LevelWords, text: String) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        LevelPill(level)
        Spacer(Modifier.width(10.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
    }
}

/** Ce que le moteur dit d'une case, sous elle. */
@Composable
private fun Said(text: String, mono: Boolean = false) {
    Text(
        text,
        style = if (mono) MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace) else MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.fillMaxWidth().padding(start = 70.dp, top = 2.dp),
    )
}
