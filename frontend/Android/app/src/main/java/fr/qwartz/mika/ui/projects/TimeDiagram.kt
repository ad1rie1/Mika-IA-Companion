package fr.qwartz.mika.ui.projects

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.projects.Diagram
import fr.qwartz.mika.data.moi.projects.DiagramRow
import fr.qwartz.mika.data.moi.projects.ROW_GOAL
import fr.qwartz.mika.data.moi.projects.Sheet
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.TimeBar
import fr.qwartz.mika.data.moi.projects.TimeLayout
import fr.qwartz.mika.data.moi.projects.diagramRows
import fr.qwartz.mika.data.moi.projects.diagramTone
import fr.qwartz.mika.data.moi.projects.goalWord
import fr.qwartz.mika.data.moi.projects.milestoneWord
import fr.qwartz.mika.data.moi.projects.missionWord
import fr.qwartz.mika.data.moi.projects.pickWeeks
import fr.qwartz.mika.data.moi.projects.rowHeight
import fr.qwartz.mika.data.moi.projects.shortDate
import fr.qwartz.mika.data.moi.projects.timeLayout
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import java.time.Instant
import java.time.ZoneId

/*
 * Le diagramme des objectifs « Dans le temps » (ADR 0296) : les noms à gauche, qui restent en place ; à droite une piste
 * qui défile en largeur, avec son axe en jours (ou en semaines), un trait pour aujourd'hui, une barre de quand elle s'y
 * est mise à quand c'est atteint — jusqu'à maintenant, le bout éclairci, si c'est en cours —, les passages d'une mission
 * en points, une flèche d'un objectif à celui qui en dépend. **De vraies dates seulement**, celles de `GET …/diagramme` :
 * ce qui n'a pas commencé n'a pas de date, et se montre en fantôme après aujourd'hui, dans l'ordre du plan. Où chaque
 * barre se pose est une règle pure ([timeLayout]) ; ici, on la dessine.
 */

private val NAMES = 132.dp
private val AXIS = 30.dp
private val DAYS = listOf("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")

/** Les couleurs du dessin, lues une fois hors du trait. */
private class TimeColors(val tones: Map<StateTone, ToneColors>, val line: Color, val ghost: Color, val ink: Color, val today: Color, val surface: Color)

/**
 * [weeks] : l'échelle choisie (`null` : celle qui fait tenir la première date et aujourd'hui dans la piste), dite à
 * [onScale]. Toucher un nom ouvre son objectif, où sont ses gestes.
 */
@Composable
internal fun TimeDiagram(vm: ProjectViewModel, sheet: Sheet, d: Diagram, now: Long, weeks: Boolean?, onScale: (Boolean) -> Unit) {
    val shell = LocalShell.current
    val rows = remember(d, vm.folded) { diagramRows(d, vm.folded) }
    val colors = TimeColors(
        StateTone.entries.associateWith { toneOf(it) },
        MaterialTheme.colorScheme.outlineVariant,
        MaterialTheme.colorScheme.outline,
        MaterialTheme.colorScheme.onSurfaceVariant,
        MaterialTheme.colorScheme.primary,
        MaterialTheme.colorScheme.surface,
    )
    val measurer = rememberTextMeasurer()
    val small = MaterialTheme.typography.labelSmall
    val later = stringResource(R.string.proj_time_later)
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val track = (maxWidth - NAMES).value.coerceAtLeast(0f)
        val byWeeks = weeks ?: pickWeeks(d, track)
        LaunchedEffect(byWeeks) { onScale(byWeeks) }
        val layout = remember(d, rows, byWeeks, track) { timeLayout(d, rows, byWeeks, track) }
        val side = rememberScrollState()
        val pxPerDp = with(androidx.compose.ui.platform.LocalDensity.current) { 1.dp.toPx() }
        // la piste s'ouvre sur aujourd'hui, la suite sans date à sa droite — une fois par échelle : ni une largeur qui
        // change (une rotation, un écran partagé) ni une relecture ne la ramènent d'où on l'a fait défiler
        var placed by rememberSaveable(byWeeks) { mutableStateOf(false) }
        LaunchedEffect(byWeeks, track > 0f) {
            if (!placed && track > 0f) {
                placed = true
                side.scrollTo(((layout.today - track * 0.55f) * pxPerDp).toInt().coerceAtLeast(0))
            }
        }
        val height = rows.sumOf { rowHeight(it).toDouble() }.toFloat()
        val words = rows.map { r ->
            when (r) {
                is DiagramRow.StepRow -> milestoneWord(r.m, now)
                is DiagramRow.GoalRow -> goalWord(r.o, now)
                is DiagramRow.MissionRow -> missionWord(r.o, now)
            }
        }
        Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
            Row(Modifier.background(MaterialTheme.colorScheme.surfaceContainerLow)) {
                Box(Modifier.width(NAMES).height(AXIS).padding(horizontal = 12.dp), contentAlignment = Alignment.CenterStart) {
                    Text(stringResource(R.string.proj_diagram_names).uppercase(), style = small, fontWeight = FontWeight.Bold, color = colors.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Box(Modifier.weight(1f).horizontalScroll(side)) {
                    Canvas(Modifier.size(layout.width.dp, AXIS)) { drawAxis(layout, byWeeks, now, later, measurer, small, colors) }
                }
            }
            Row {
                Column(Modifier.width(NAMES)) {
                    for (r in rows) {
                        val key = if (r.o.kind == "constant") "m${r.o.id}" else "o${r.o.id}"
                        val known = sheet.objectives.any { it.id == r.o.id } || sheet.missions.any { it.id == r.o.id }
                        Box(
                            Modifier.fillMaxWidth().height(rowHeight(r).dp).then(if (known) Modifier.clickable { shell.navigate(Route.ProjectGoal(vm.id, key)) } else Modifier),
                            contentAlignment = Alignment.CenterStart,
                        ) { TimeName(vm, r) }
                    }
                }
                Box(Modifier.weight(1f).horizontalScroll(side)) {
                    Canvas(Modifier.size(layout.width.dp, height.dp)) { drawTracks(layout, rows, words, measurer, small, colors) }
                }
            }
            if (rows.isEmpty()) EmptyNote(R.drawable.ic_m_target, stringResource(R.string.proj_goals_none), stringResource(R.string.proj_goals_none_sub))
            if (d.cut) Hint(stringResource(R.string.proj_diagram_cut), modifier = Modifier.padding(12.dp))
            Hint(stringResource(R.string.proj_time_hint), modifier = Modifier.padding(12.dp))
        }
    }
}

/** Le nom d'une ligne, à gauche : un objectif (et de quoi replier ses jalons), un jalon en retrait, une mission. */
@Composable
private fun TimeName(vm: ProjectViewModel, r: DiagramRow) {
    Row(Modifier.padding(end = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        when (r) {
            is DiagramRow.GoalRow -> {
                if (r.o.milestones.isNotEmpty()) {
                    val label = stringResource(if (r.folded) R.string.proj_diagram_unfold else R.string.proj_diagram_fold)
                    Box(Modifier.size(26.dp).clip(CircleShape).clickable(onClickLabel = label) { vm.fold(r.o.id) }, contentAlignment = Alignment.Center) {
                        MIcon(if (r.folded) R.drawable.ic_m_chev_right else R.drawable.ic_m_chev_down, label, size = 14.dp)
                    }
                } else {
                    Spacer(Modifier.width(26.dp))
                }
                Text(r.o.text, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            is DiagramRow.StepRow -> {
                Spacer(Modifier.width(26.dp))
                val tone = diagramTone(r.m)
                Box(Modifier.size(8.dp).clip(RoundedCornerShape(2.dp)).background(toneOf(tone).let { if (tone == StateTone.WAIT) it.ink else it.bar }))
                Spacer(Modifier.width(6.dp))
                Text(r.m.text, style = MaterialTheme.typography.labelSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            is DiagramRow.MissionRow -> {
                Box(Modifier.size(26.dp), contentAlignment = Alignment.Center) { MIcon(R.drawable.ic_m_refresh, null, size = 14.dp, tint = toneOf(StateTone.WORK).ink) }
                Text(r.o.text, style = MaterialTheme.typography.bodySmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/** L'axe : un trait et un nom par jour (en semaines : les lundis), aujourd'hui marqué, et « à suivre · sans date » après lui. */
private fun DrawScope.drawAxis(layout: TimeLayout, weeks: Boolean, now: Long, later: String, measurer: TextMeasurer, style: TextStyle, c: TimeColors) {
    val zone = ZoneId.systemDefault()
    for (day in layout.days) {
        val x = day.x.dp.toPx()
        val date = Instant.ofEpochMilli(day.at).atZone(zone).toLocalDate()
        val monday = date.dayOfWeek.value == 1
        drawLine(c.line, Offset(x, if (weeks && !monday) size.height * 0.6f else 0f), Offset(x, size.height), strokeWidth = 1.dp.toPx())
        val label = when {
            day.today -> null
            weeks -> if (monday) shortDate(day.at, now, zone) else null
            else -> "${date.dayOfMonth} ${DAYS[date.dayOfWeek.value - 1]}"
        }
        if (label != null) drawText(measurer, label, Offset(x + 4.dp.toPx(), 8.dp.toPx()), style.copy(color = c.ink), maxLines = 1, overflow = TextOverflow.Clip)
    }
    val today = layout.today.dp.toPx()
    drawLine(c.today, Offset(today, 0f), Offset(today, size.height), strokeWidth = 2.dp.toPx())
    drawText(measurer, later, Offset(today + 8.dp.toPx(), 8.dp.toPx()), style.copy(color = c.ink, fontStyle = androidx.compose.ui.text.font.FontStyle.Italic), maxLines = 1)
}

/** La piste : la grille des jours, le trait d'aujourd'hui, les barres de chaque ligne et leur mot, les flèches. */
private fun DrawScope.drawTracks(layout: TimeLayout, rows: List<DiagramRow>, words: List<String>, measurer: TextMeasurer, style: TextStyle, c: TimeColors) {
    for (day in layout.days) {
        val x = day.x.dp.toPx()
        drawLine(c.line.copy(alpha = 0.5f), Offset(x, 0f), Offset(x, size.height), strokeWidth = 1.dp.toPx())
    }
    var top = 0f
    rows.forEachIndexed { i, r ->
        val h = rowHeight(r).dp.toPx()
        val mid = top + h / 2
        drawLine(c.line, Offset(0f, top + h), Offset(size.width, top + h), strokeWidth = 1.dp.toPx())
        val t = layout.tracks[i]
        val thick = (if (r is DiagramRow.StepRow) 10 else 14).dp.toPx()
        for (b in t.bars) drawBar(b, mid, thick, c)
        if (t.line >= 0f) {
            // une mission : son fil jusqu'à aujourd'hui, un point par passage
            val work = c.tones.getValue(StateTone.WORK).bar
            drawLine(work.copy(alpha = 0.4f), Offset(0f, mid), Offset(t.line.dp.toPx(), mid), strokeWidth = 2.dp.toPx())
            for (p in t.passes) drawCircle(work, radius = 4.dp.toPx(), center = Offset(p.dp.toPx(), mid))
        }
        if (t.label >= 0f && words[i].isNotBlank()) {
            val ready = r is DiagramRow.StepRow && r.m.ready
            val x = t.label.dp.toPx()
            if (x < size.width - 8.dp.toPx()) {
                val text = measurer.measure(words[i], style.copy(color = if (ready) c.tones.getValue(StateTone.YOU).ink else c.ink, fontWeight = if (ready) FontWeight.SemiBold else FontWeight.Normal), maxLines = 1)
                clipRect(left = x, right = size.width) { drawText(text, topLeft = Offset(x, mid - text.size.height / 2)) }
            }
        }
        top += h
    }
    val today = layout.today.dp.toPx()
    drawLine(c.today, Offset(today, 0f), Offset(today, size.height), strokeWidth = 2.dp.toPx())
    // les flèches : d'un objectif à celui qui en dépend, en équerre
    for (a in layout.arrows) {
        val x1 = a.x1.dp.toPx()
        val x2 = a.x2.dp.toPx()
        val y1 = a.y1.dp.toPx()
        val y2 = a.y2.dp.toPx()
        val step = 8.dp.toPx()
        val path = Path().apply {
            moveTo(x1 + 2.dp.toPx(), y1)
            if (x2 >= x1 + 2 * step) {
                lineTo(x1 + step, y1)
                lineTo(x1 + step, y2)
            } else {
                // la cible est avant la source : la flèche la contourne par le haut de sa ligne
                val above = y2 - (ROW_GOAL / 2).dp.toPx() + 3.dp.toPx()
                lineTo(x1 + step, y1)
                lineTo(x1 + step, above)
                lineTo(x2 - 12.dp.toPx(), above)
                lineTo(x2 - 12.dp.toPx(), y2)
            }
            lineTo(x2 - 3.dp.toPx(), y2)
        }
        drawPath(path, c.ghost, style = Stroke(width = 1.5.dp.toPx()))
        val head = Path().apply {
            moveTo(x2 - 8.dp.toPx(), y2 - 4.dp.toPx())
            lineTo(x2 - 2.dp.toPx(), y2)
            lineTo(x2 - 8.dp.toPx(), y2 + 4.dp.toPx())
        }
        drawPath(head, c.ghost, style = Stroke(width = 1.5.dp.toPx()))
    }
}

/** Une barre : pleine à la couleur de son état ; en cours, son bout éclairci ; à toi, hachurée ; pas commencée, un fantôme en tirets. */
private fun DrawScope.drawBar(b: TimeBar, mid: Float, thick: Float, c: TimeColors) {
    val left = b.left.dp.toPx()
    val width = b.width.dp.toPx()
    val top = mid - thick / 2
    val round = CornerRadius(thick / 2)
    val tone = b.tone
    if (tone == null) {
        drawRoundRect(c.ghost, Offset(left, top), Size(width, thick), round, style = Stroke(width = 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx()))))
        return
    }
    val color = c.tones.getValue(tone).bar
    drawRoundRect(color, Offset(left, top), Size(width, thick), round)
    val tip = minOf(14.dp.toPx(), width / 2)
    if (b.running) drawRect(c.surface.copy(alpha = 0.55f), Offset(left + width - tip, top), Size(tip, thick))
    if (b.yours) {
        // des hachures : cette part attend la personne
        clipRect(left, top, left + width, top + thick) {
            var x = left - thick
            while (x < left + width) {
                drawLine(c.surface.copy(alpha = 0.7f), Offset(x, top + thick), Offset(x + thick, top), strokeWidth = 2.dp.toPx())
                x += 7.dp.toPx()
            }
        }
    }
}
