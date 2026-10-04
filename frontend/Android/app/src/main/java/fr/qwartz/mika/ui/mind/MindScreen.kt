package fr.qwartz.mika.ui.mind

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LargeTopAppBar
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.ui.components.TitledCard
import fr.qwartz.mika.ui.components.rememberNow
import java.time.ZoneId

/** « Ce qu'elle fait » : ce que l'app sait de son état, carte par carte, daté. */
@Composable
fun MindScreen(graph: AppGraph, onBack: () -> Unit) {
    val state by graph.mind.state.collectAsStateWithLifecycle()
    val now = rememberNow(wallMs = graph.clock::wallMs)
    val zone = remember { ZoneId.systemDefault() }
    val cards = remember(state) { MindCards.build(state, zone) }
    MindContent(cards, state?.let { MindCards.updatedAgo(it.updatedAtMs, now) }, onBack)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MindContent(cards: List<MindCard>, updated: String?, onBack: () -> Unit) {
    val scroll = TopAppBarDefaults.exitUntilCollapsedScrollBehavior()
    Scaffold(
        modifier = Modifier.nestedScroll(scroll.nestedScrollConnection),
        topBar = {
            LargeTopAppBar(
                title = { Text(stringResource(R.string.menu_status)) },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(painterResource(R.drawable.ic_arrow_back), stringResource(R.string.back))
                    }
                },
                scrollBehavior = scroll,
            )
        },
    ) { padding ->
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(
                start = 16.dp,
                end = 16.dp,
                top = padding.calculateTopPadding() + 8.dp,
                bottom = padding.calculateBottomPadding() + 24.dp,
            ),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            if (cards.isEmpty()) {
                item {
                    Text(
                        stringResource(R.string.mind_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(vertical = 24.dp),
                    )
                }
            }
            items(cards, key = { it.javaClass.simpleName }) { card -> MindCardView(card) }
            if (updated != null) {
                item {
                    Text(
                        updated,
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun MindCardView(card: MindCard) {
    when (card) {
        is MindCard.Mood -> TitledCard(stringResource(R.string.mind_mood)) {
            Text(
                card.primary,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.semantics { contentDescription = "${card.primary}, ${card.primaryPct} %" },
            )
            Meter(card.primaryPct, stringResource(R.string.mind_intensity))
            if (card.secondary != null && card.secondaryPct != null) {
                Text(stringResource(R.string.mind_but_also, card.secondary, card.secondaryPct))
            }
        }
        is MindCard.Body -> TitledCard(stringResource(R.string.mind_body)) {
            Text(card.sleep.replaceFirstChar { it.uppercase() }, style = MaterialTheme.typography.titleSmall)
            card.energyPct?.let { Meter(it, stringResource(R.string.mind_energy)) }
            card.place?.let { Text(it.replaceFirstChar { c -> c.uppercase() }) }
            card.moment?.let { Text(it, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        is MindCard.Esteem -> TitledCard(stringResource(R.string.mind_esteem)) {
            Meter(card.pct, stringResource(R.string.mind_esteem_meter))
        }
        is MindCard.Thoughts -> TitledCard(stringResource(R.string.mind_thoughts)) {
            for (t in card.items) {
                Row(verticalAlignment = Alignment.Top, modifier = Modifier.clearAndSetSemantics {
                    contentDescription = "${t.text}, ${t.pct} %"
                }) {
                    Text("${t.pct} %", style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(end = 12.dp))
                    Text(t.text, modifier = Modifier.weight(1f))
                }
            }
        }
        is MindCard.Dream -> TitledCard(stringResource(R.string.mind_dream)) {
            val meta = listOfNotNull(
                card.type,
                card.emotion,
                stringResource(R.string.mind_vividness, card.vividnessPct),
                if (card.recalled) stringResource(R.string.mind_dream_recalled) else null,
            ).joinToString(" · ")
            Text(meta, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(
                card.text,
                fontStyle = FontStyle.Italic,
                color = MaterialTheme.colorScheme.onSurface.copy(alpha = card.alpha),
            )
        }
        is MindCard.Journal -> TitledCard(card.title) {
            card.emotion?.let { Text(it, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            Text(card.text)
            if (card.persons.isNotEmpty()) {
                Text(
                    stringResource(R.string.mind_with, card.persons.joinToString(", ")),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        is MindCard.Narrative -> TitledCard(stringResource(R.string.mind_narrative)) { Text(card.text) }
        is MindCard.Needs -> TitledCard(stringResource(R.string.mind_needs)) {
            for (need in card.items) Meter(need.pct, need.label)
        }
        is MindCard.Projects -> TitledCard(stringResource(R.string.mind_projects)) {
            for (p in card.items) ProjectRow(p)
        }
    }
}

@Composable
private fun ProjectRow(p: MindCard.Project) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp), modifier = Modifier.padding(vertical = 4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(p.title, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            p.mode?.let {
                Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.secondary)
            }
        }
        val fraction = if (p.total > 0) p.done.toFloat() / p.total else 0f
        val progress = stringResource(R.string.mind_project_progress, p.done, p.total)
        Row(verticalAlignment = Alignment.CenterVertically) {
            LinearProgressIndicator(
                progress = { fraction },
                modifier = Modifier.weight(1f).semantics { stateDescription = progress },
            )
            Text(" ${p.done}/${p.total}", style = MaterialTheme.typography.labelMedium)
        }
        if (p.blocked > 0) {
            Text(
                pluralStringResource(R.plurals.mind_project_blocked, p.blocked, p.blocked),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.error,
            )
        }
        val schedule = if (p.nextRun != null) {
            stringResource(R.string.mind_project_next, p.schedule, p.nextRun)
        } else {
            p.schedule
        }
        Text(schedule, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Une jauge avec son libellé ; un lecteur d'écran l'entend « Énergie, 72 % ». */
@Composable
private fun Meter(pct: Int, label: String) {
    Column(
        Modifier.fillMaxWidth().semantics(mergeDescendants = true) {
            stateDescription = "$pct %"
            progressBarRangeInfo = ProgressBarRangeInfo(pct / 100f, 0f..1f)
        },
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Row {
            Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            Text("$pct %", style = MaterialTheme.typography.labelMedium)
        }
        LinearProgressIndicator(progress = { pct / 100f }, modifier = Modifier.fillMaxWidth())
    }
}
