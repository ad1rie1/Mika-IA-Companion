package fr.qwartz.mika.ui.tools

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.settings.RuleLine
import fr.qwartz.mika.data.moi.settings.SendRules
import fr.qwartz.mika.data.moi.settings.ruleWho
import fr.qwartz.mika.data.moi.tools.LevelWords
import fr.qwartz.mika.data.moi.tools.Pill
import fr.qwartz.mika.data.moi.tools.RightsKeys
import fr.qwartz.mika.data.moi.tools.RightsMoment
import fr.qwartz.mika.data.moi.tools.RightsTool
import fr.qwartz.mika.data.moi.tools.RulesOrigin
import fr.qwartz.mika.data.moi.tools.ToolsResource
import fr.qwartz.mika.data.moi.tools.accountKey
import fr.qwartz.mika.data.moi.tools.canalName
import fr.qwartz.mika.data.moi.tools.chosenCanal
import fr.qwartz.mika.data.moi.tools.conditionOf
import fr.qwartz.mika.data.moi.tools.groupsOf
import fr.qwartz.mika.data.moi.tools.idle
import fr.qwartz.mika.data.moi.tools.labelOf
import fr.qwartz.mika.data.moi.tools.levelOf
import fr.qwartz.mika.data.moi.tools.momentsOf
import fr.qwartz.mika.data.moi.tools.pillsOf
import fr.qwartz.mika.data.moi.tools.replyTone
import fr.qwartz.mika.data.moi.tools.resourcesOf
import fr.qwartz.mika.data.moi.tools.rulesOrigin
import fr.qwartz.mika.data.moi.tools.shownTools
import fr.qwartz.mika.data.moi.tools.summaryOf
import fr.qwartz.mika.ui.settings.SettingsPages
import fr.qwartz.mika.ui.settings.settingsPage
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.toneColors
import fr.qwartz.mika.ui.theme.mika

/** La largeur d'une pastille et de la colonne au-dessus : « quand tu lui parles », « d'elle-même ». */
private val PILL_WIDTH = 60.dp

/** Une ligne de la liste : un titre de groupe, ou une carte. */
private sealed interface RightsRow {
    val key: String

    data class Head(val title: String, override val key: String) : RightsRow
    data class Card(val res: ToolsResource) : RightsRow {
        override val key: String = "r:${res.key}"
    }
}

/** Les deux lignes du haut de la liste (le canal, les noms des colonnes) : une carte se compte après elles. */
private const val TOP_ROWS = 2

/**
 * Droits : par où (le canal dont la colonne se lit, une feuille pour le choisir), les noms des colonnes, puis une carte
 * repliable par ressource, groupées — ses propres outils, tes comptes, les services, les apps —, chacune avec son
 * résumé pour ce canal. Un outil dit ses deux pastilles (quand tu lui parles, d'elle-même ; une seule pour elle seule) ;
 * le toucher ouvre « Ce qui décide ». Un compte dit la règle qui vaut pour lui et mène à sa page de Paramètres.
 */
@Composable
internal fun RightsTab(graph: AppGraph, vm: ToolsViewModel, modifier: Modifier) {
    val shell = LocalShell.current
    val me by graph.me.me.collectAsStateWithLifecycle()
    var picking by rememberSaveable { mutableStateOf(false) }
    /** L'outil dont la feuille est ouverte : `<ressource>|<outil>`. */
    var sheet by rememberSaveable { mutableStateOf("") }
    PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = modifier) {
        LoadBox(vm.rights, onRetry = vm::retry) { rights ->
            val services = vm.services
            val resources = remember(rights, services) { resourcesOf(rights, services) }
            val rows = remember(resources) {
                groupsOf(resources).flatMap { g -> listOf(RightsRow.Head(g.title, "g:${g.key}")) + g.resources.map { RightsRow.Card(it) } }
            }
            val canal = chosenCanal(rights.canals, vm.canal)
            val moments = momentsOf(canal, rights.moments)
            val opened = vm.opened.orEmpty()
            val list = rememberLazyListState()
            LaunchedEffect(vm.focus, rows) {
                val key = vm.focus ?: return@LaunchedEffect
                val at = rows.indexOfFirst { it is RightsRow.Card && it.res.key == key }
                if (at >= 0) list.animateScrollToItem(at + TOP_ROWS)
                vm.focused()
            }
            LazyColumn(state = list, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 24.dp)) {
                item(key = "canal") {
                    CanalChip(rights.canals.firstOrNull { it.key == canal }?.let(::canalName) ?: canal, canal) { picking = true }
                }
                item(key = "moments") { MomentHeads(canal, moments) }
                if (rows.isEmpty()) {
                    item(key = "empty") { Notice(stringResource(R.string.tools_empty), Modifier.padding(top = 32.dp)) }
                }
                for (row in rows) {
                    item(key = row.key) {
                        when (row) {
                            is RightsRow.Head -> ListHead(row.title)
                            is RightsRow.Card -> ResourceCard(
                                res = row.res,
                                canal = canal,
                                moments = moments,
                                expanded = row.res.key in opened,
                                familyShown = row.res.family?.key?.let { f -> resources.any { it.key == f } } == true,
                                onToggle = { vm.toggle(row.res.key) },
                                onTool = { t -> sheet = "${row.res.key}|${t.name}" },
                                onFamily = vm::show,
                                onSettings = {
                                    val page = if (row.res.kind == "teams") SettingsPages.TEAMS_ACCOUNT else SettingsPages.BOX
                                    shell.navigate(settingsPage(page, accountKey(row.res)))
                                },
                            )
                        }
                    }
                }
                item(key = "note") {
                    Text(
                        stringResource(R.string.tools_note),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 16.dp),
                    )
                }
            }
            if (picking) {
                CanalSheet(rights.canals, canal, onPick = vm::choose, onDismiss = { picking = false })
            }
            val (resKey, toolName) = sheet.split('|', limit = 2).let { it.getOrElse(0) { "" } to it.getOrElse(1) { "" } }
            val res = resources.firstOrNull { it.key == resKey }
            val tool = res?.tools?.firstOrNull { it.name == toolName }
            if (res != null && tool != null) {
                ToolSheet(graph, rights, res, tool, canal, operator = me?.operator == true, onDismiss = { sheet = "" })
            }
        }
    }
}

/** « Par où » et le canal lu, en puce : la toucher ouvre la feuille des canaux. */
@Composable
private fun CanalChip(label: String, key: String, onPick: () -> Unit) {
    val described = stringResource(R.string.tools_canal_choose, label)
    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 10.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(stringResource(R.string.tools_by), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(10.dp))
        FilterChip(
            selected = true,
            onClick = onPick,
            label = { Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            leadingIcon = { MIcon(canalIcon(key), null, size = 18.dp) },
            trailingIcon = { MIcon(R.drawable.ic_m_chev_down, null, size = 16.dp) },
            modifier = Modifier.semantics { contentDescription = described },
        )
    }
}

/** Les noms des colonnes, au-dessus des pastilles : quand tu lui parles, d'elle-même ; pour elle seule, quand elle
 *  travaille. */
@Composable
private fun MomentHeads(canal: String, moments: List<RightsMoment>) {
    Row(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 30.dp, bottom = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp, Alignment.End),
    ) {
        for (m in moments) {
            Text(
                momentShort(canal, m.key),
                style = MaterialTheme.typography.labelSmall.copy(fontSize = 10.5.sp, lineHeight = 13.sp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.width(PILL_WIDTH),
            )
        }
    }
}

/** Le nom court d'un moment, au-dessus de sa colonne. */
@Composable
internal fun momentShort(canal: String, moment: String): String = when {
    canal == RightsKeys.ALONE || moment == RightsKeys.WORK -> stringResource(R.string.tools_moment_work)
    moment == RightsKeys.INITIATIVE -> stringResource(R.string.tools_moment_initiative)
    else -> stringResource(R.string.tools_moment_reply)
}

/** Une pastille : le mot d'une case, sur sa couleur ; une case absente, un tiret discret. */
@Composable
internal fun LevelPill(level: LevelWords, modifier: Modifier = Modifier) {
    val (bg, fg) = toneColors(level.tone)
    Box(
        modifier
            .width(PILL_WIDTH)
            .clip(RoundedCornerShape(6.dp))
            .background(if (level.unused) Color.Transparent else bg)
            .padding(horizontal = 4.dp, vertical = 3.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            level.word,
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.SemiBold,
            color = if (level.unused) MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.6f) else fg,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/**
 * Une carte (`.res` de la maquette) : son icône, son nom, ce qu'on en dit, son résumé pour le canal choisi, et le
 * chevron ; dépliée, ses outils (ceux qui ne servent à aucun moment repliés dessous), ou, pour un compte, la règle qui
 * vaut pour lui.
 */
@Composable
private fun ResourceCard(
    res: ToolsResource,
    canal: String,
    moments: List<RightsMoment>,
    expanded: Boolean,
    familyShown: Boolean,
    onToggle: () -> Unit,
    onTool: (RightsTool) -> Unit,
    onFamily: (String) -> Unit,
    onSettings: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val state = stringResource(if (expanded) R.string.tools_expanded else R.string.tools_collapsed)
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = scheme.surfaceContainerLow,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
    ) {
        Column {
            Row(
                Modifier
                    .fillMaxWidth()
                    .clickable(role = Role.Button, onClick = onToggle)
                    .semantics { stateDescription = state }
                    .padding(horizontal = 14.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MIcon(toolIcon(res.icon), null, tint = if (res.aloneOnly) mika.accent else scheme.onSurfaceVariant)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(res.title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    if (res.sub.isNotBlank()) {
                        Text(res.sub, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                    val summary = summaryOf(res.tools, canal, moments)
                    if (!summary.empty) {
                        Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                            if (summary.alone > 0) Tag(stringResource(R.string.tools_summary_alone, summary.alone), Tone.OK)
                            if (summary.ask > 0) Tag(pluralStringResource(R.plurals.tools_summary_ask, summary.ask, summary.ask), Tone.WARN)
                            if (summary.no > 0) Tag(stringResource(R.string.tools_summary_no, summary.no), Tone.NEUTRAL)
                        }
                    }
                }
                Spacer(Modifier.width(8.dp))
                MIcon(if (expanded) R.drawable.ic_m_chev_up else R.drawable.ic_m_chev_down, null, size = 20.dp, tint = scheme.onSurfaceVariant)
            }
            if (expanded) {
                HorizontalDivider(color = scheme.outlineVariant.copy(alpha = 0.6f))
                val rules = res.rules
                if (res.account && rules != null) {
                    AccountBody(res, rules, familyShown, onFamily, onSettings)
                } else {
                    ToolsBody(res, canal, moments, onTool)
                }
            }
        }
    }
}

/** Les outils d'une carte : une ligne chacun, ses pastilles pour le canal choisi ; ceux qui ne servent à aucun moment,
 *  repliés derrière une phrase et nommés pour toi quand on la déplie. */
@Composable
private fun ToolsBody(res: ToolsResource, canal: String, moments: List<RightsMoment>, onTool: (RightsTool) -> Unit) {
    val shown = shownTools(res.tools)
    val quiet = res.tools.filter(::idle)
    shown.forEachIndexed { i, t ->
        if (i > 0) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
        ToolRow(t, pillsOf(t, canal, moments), canal) { onTool(t) }
    }
    if (quiet.isNotEmpty()) {
        var open by rememberSaveable(res.key) { mutableStateOf(false) }
        if (shown.isNotEmpty()) HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.4f))
        val said = if (shown.isNotEmpty()) {
            pluralStringResource(R.plurals.tools_idle_other, quiet.size, quiet.size)
        } else {
            pluralStringResource(R.plurals.tools_idle_only, quiet.size, quiet.size)
        }
        Row(
            Modifier.fillMaxWidth().clickable(role = Role.Button) { open = !open }.padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(said, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
            MIcon(if (open) R.drawable.ic_m_chev_up else R.drawable.ic_m_chev_down, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (open) {
            for (t in quiet) {
                Text(
                    labelOf(t),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.fillMaxWidth().clickable { onTool(t) }.padding(start = 28.dp, end = 14.dp, top = 8.dp, bottom = 8.dp),
                )
            }
        }
    }
}

/** Un outil (`.tool-row`) : son nom pour toi, un cadenas s'il est sous une condition, puis ses pastilles. */
@Composable
private fun ToolRow(tool: RightsTool, pills: List<Pill>, canal: String, onClick: () -> Unit) {
    val condition = conditionOf(tool).isNotEmpty()
    val conditionSaid = stringResource(R.string.tools_condition)
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(labelOf(tool), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        if (condition) {
            Spacer(Modifier.width(6.dp))
            MIcon(R.drawable.ic_m_lock, conditionSaid, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Spacer(Modifier.width(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            for (p in pills) {
                val level = levelOf(p.cell)
                val said = stringResource(R.string.tools_pill, momentShort(canal, p.moment.key), level.long)
                LevelPill(level, Modifier.semantics { contentDescription = said })
            }
        }
    }
}

/** Ce qu'un compte a à lui (ADR 0209) : ses outils sont ceux de sa famille (un lien y mène), la règle qui vaut pour son
 *  canal, lue de haut en bas, d'où elle vient, et sa page de Paramètres. */
@Composable
private fun AccountBody(res: ToolsResource, rules: SendRules, familyShown: Boolean, onFamily: (String) -> Unit, onSettings: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val teams = res.kind == "teams"
    Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp)) {
        val family = res.family
        if (family != null) {
            Text(
                stringResource(if (teams) R.string.tools_account_family_teams else R.string.tools_account_family_mail, family.title),
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
            )
            if (familyShown) {
                TextButton(onClick = { onFamily(family.key) }, contentPadding = PaddingValues(horizontal = 0.dp)) {
                    Text(stringResource(R.string.tools_account_family_show))
                }
            } else {
                Gap(8.dp)
            }
        }
        Text(
            stringResource(if (teams) R.string.tools_rules_title_teams else R.string.tools_rules_title_mail),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Medium,
        )
        Text(stringResource(R.string.tools_rules_order), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
        Gap(6.dp)
        rules.lines.forEachIndexed { i, line -> RuleRow((i + 1).toString(), ruleWho(line), line) }
        RuleRow("—", stringResource(R.string.tools_rules_default), rules.default, strong = true)
        Gap(6.dp)
        val origin = when (rulesOrigin(rules)) {
            RulesOrigin.SET -> ""
            RulesOrigin.COMMON -> stringResource(if (teams) R.string.tools_rules_common_teams else R.string.tools_rules_common_mail)
            RulesOrigin.START -> stringResource(R.string.tools_rules_start)
        }
        val where = stringResource(if (teams) R.string.tools_rules_where_teams else R.string.tools_rules_where_mail)
        Text(listOf(where, origin).filter { it.isNotBlank() }.joinToString(" "), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
        Gap(10.dp)
        OutlinedButton(onClick = onSettings) {
            MIcon(R.drawable.ic_m_settings, null, size = 18.dp)
            Spacer(Modifier.width(8.dp))
            Text(stringResource(R.string.tools_account_settings))
        }
    }
}

/** Une ligne de la règle d'envoi : son rang, qui (et quand), préparer d'elle-même, et comment ça part. */
@Composable
private fun RuleRow(rank: String, who: String, line: RuleLine, strong: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(rank, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(22.dp))
        Column(Modifier.weight(1f)) {
            Text(who, style = MaterialTheme.typography.bodyMedium, fontWeight = if (strong) FontWeight.Medium else FontWeight.Normal)
            Text(
                stringResource(if (line.prepare) R.string.tools_rules_prepare_yes else R.string.tools_rules_prepare_no),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(Modifier.width(8.dp))
        Tag(line.replyWords.ifBlank { line.reply }, replyTone(line.reply))
    }
}
