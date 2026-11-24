package fr.qwartz.mika.ui.agenda

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.JC
import fr.qwartz.mika.data.moi.agenda.MOIS
import fr.qwartz.mika.data.moi.agenda.Occ
import fr.qwartz.mika.data.moi.agenda.Sort
import fr.qwartz.mika.data.moi.agenda.WEEK_LETTERS
import fr.qwartz.mika.data.moi.agenda.addDays
import fr.qwartz.mika.data.moi.agenda.addedByHer
import fr.qwartz.mika.data.moi.agenda.busyDays
import fr.qwartz.mika.data.moi.agenda.cap
import fr.qwartz.mika.data.moi.agenda.columns
import fr.qwartz.mika.data.moi.agenda.dayWords
import fr.qwartz.mika.data.moi.agenda.daysFrom
import fr.qwartz.mika.data.moi.agenda.hm
import fr.qwartz.mika.data.moi.agenda.lanes
import fr.qwartz.mika.data.moi.agenda.monthCells
import fr.qwartz.mika.data.moi.agenda.monthDays
import fr.qwartz.mika.data.moi.agenda.partsOf
import fr.qwartz.mika.data.moi.agenda.planningDays
import fr.qwartz.mika.data.moi.agenda.weekday
import fr.qwartz.mika.data.moi.agenda.within
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.theme.mika
import kotlin.math.abs

/*
 * Les vues de l'Agenda (la maquette validée `agenda.js`) : Planning (une liste par jour, la date à gauche, la ligne de
 * l'heure, « Les quatre semaines suivantes »), Jour, 3 jours et Semaine (la grille horaire, les journées entières en
 * bandes au-dessus, toucher une heure vide crée un événement), Mois (une case par jour, toucher ouvre son Jour), et le
 * mini-mois déplié sous le titre. On balaie pour changer de période (sauf en Planning, qui défile).
 */

/** La hauteur d'une heure dans la grille. */
internal val HOUR: Dp = 48.dp

/** Balayer de côté : un geste franc (56 dp au moins) change de période. */
internal fun Modifier.swipe(onSwipe: (Int) -> Unit): Modifier = pointerInput(Unit) {
    var dx = 0f
    detectHorizontalDragGestures(
        onDragStart = { dx = 0f },
        onDragEnd = {
            if (abs(dx) > 56.dp.toPx()) onSwipe(if (dx < 0) 1 else -1)
            dx = 0f
        },
        onDragCancel = { dx = 0f },
    ) { change, amount ->
        dx += amount
        change.consume()
    }
}

// ── Planning ────────────────────────────────────────────────────────────

/** Planning : une liste par jour à partir du jour choisi, quatre semaines ; la ligne de l'heure entre les rendez-vous
 *  d'aujourd'hui ; « Les quatre semaines suivantes » au bout. */
@Composable
internal fun PlanningView(
    occs: List<Occ>,
    first: String,
    after: String,
    today: String,
    nowMinute: Int,
    calendars: List<AgendaCalendar>,
    words: OccTagWords,
    onOpen: (Occ) -> Unit,
    onDay: (String) -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val days = remember(occs, first, after, today, nowMinute) { planningDays(occs, first, after, today, nowMinute) }
    LazyColumn(modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 96.dp)) {
        if (days.isEmpty()) {
            item(key = "vide") {
                Column(Modifier.fillMaxWidth().padding(32.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    MIcon(R.drawable.ic_m_agenda, null, size = 32.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    Text(stringResource(R.string.agenda_nothing), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
                    Text(stringResource(R.string.agenda_nothing_text), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = TextAlign.Center)
                }
            }
        }
        var month = partsOf(first).m
        for (d in days) {
            val m = partsOf(d.day).m
            if (m != month) {
                month = m
                item(key = "m:${d.day}") {
                    Text(
                        "${cap(MOIS[m - 1])} ${partsOf(d.day).y}",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(start = 16.dp, top = 18.dp, bottom = 4.dp),
                    )
                }
            }
            item(key = "d:${d.day}") {
                PlanningDayRow(d.day, d.occs, d.nowAt, today, nowMinute, calendars, words, onOpen, onDay)
            }
        }
        item(key = "suite") {
            Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                FilledTonalButton(onClick = onNext) {
                    MIcon(R.drawable.ic_m_chev_down, null, size = 18.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.agenda_next_weeks))
                }
            }
        }
    }
}

@Composable
private fun PlanningDayRow(
    day: String,
    occs: List<Occ>,
    nowAt: Int,
    today: String,
    nowMinute: Int,
    calendars: List<AgendaCalendar>,
    words: OccTagWords,
    onOpen: (Occ) -> Unit,
    onDay: (String) -> Unit,
) {
    val isToday = day == today
    val scheme = MaterialTheme.colorScheme
    Column {
        Row(Modifier.fillMaxWidth().padding(start = 8.dp, end = 12.dp, top = 10.dp, bottom = 10.dp)) {
            Column(
                Modifier
                    .width(48.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .clickable { onDay(day) }
                    .semantics { contentDescription = cap(dayWords(day, today)) }
                    .padding(vertical = 2.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(JC[weekday(day)], style = MaterialTheme.typography.labelMedium, color = if (isToday) scheme.primary else scheme.onSurfaceVariant)
                Box(
                    Modifier.size(36.dp).clip(CircleShape).background(if (isToday) scheme.primary else androidx.compose.ui.graphics.Color.Transparent),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(partsOf(day).d.toString(), style = MaterialTheme.typography.titleMedium, color = if (isToday) scheme.onPrimary else scheme.onSurface)
                }
            }
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                val said = when (daysFrom(today, day)) {
                    0 -> stringResource(R.string.agenda_today)
                    1 -> stringResource(R.string.agenda_tomorrow)
                    else -> null
                }
                if (said != null) Text(said, style = MaterialTheme.typography.labelLarge, color = if (isToday) scheme.primary else scheme.onSurfaceVariant)
                occs.forEachIndexed { i, o ->
                    if (i == nowAt) NowLine()
                    OccCard(o, calendars, today, nowMinute, words) { onOpen(o) }
                }
                if (nowAt == occs.size && isToday) NowLine()
            }
        }
        HorizontalDivider(color = scheme.outlineVariant.copy(alpha = 0.5f))
    }
}

/** La ligne de l'heure (indigo, un point à gauche). */
@Composable
private fun NowLine() {
    val c = MaterialTheme.colorScheme.primary
    Row(Modifier.fillMaxWidth().height(10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(9.dp).clip(CircleShape).background(c))
        Box(Modifier.weight(1f).height(2.dp).background(c))
    }
}

// ── La grille horaire : Jour, 3 jours, Semaine ─────────────────────────

/**
 * La grille horaire des jours [days] : les têtes (le jour en indigo aujourd'hui ; les toucher ouvre leur Jour), les
 * journées entières en bandes, puis les heures — chaque rendez-vous à sa place, ceux qui se chevauchent côte à côte,
 * la ligne de l'heure aujourd'hui. Toucher une heure vide crée un événement à cette demi-heure.
 */
@Composable
internal fun GridView(
    days: List<String>,
    occs: List<Occ>,
    today: String,
    nowMinute: Int,
    zoneShort: String,
    calendars: List<AgendaCalendar>,
    onOpen: (Occ) -> Unit,
    onDay: (String) -> Unit,
    onSlot: (String, Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val n = days.size
    val scheme = MaterialTheme.colorScheme
    val first = days.first()
    val after = addDays(days.last(), 1)
    val shown = remember(occs, first, after) { within(occs, first, after) }
    val bands = remember(shown, first, n) { lanes(shown.filter { it.allDay }, first, n) }
    val scroll = rememberScrollState()
    val density = LocalDensity.current
    LaunchedEffect(first, n) { scroll.scrollTo(with(density) { (HOUR * 7.5f).roundToPx() }) }
    val gutter = 44.dp
    Column(modifier.fillMaxSize()) {
        // les têtes
        Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
            Box(Modifier.width(gutter).height(52.dp), contentAlignment = Alignment.BottomCenter) {
                if (n < 7) Text(zoneShort, fontSize = 10.sp, color = scheme.onSurfaceVariant, modifier = Modifier.padding(bottom = 4.dp))
            }
            for (d in days) {
                val isToday = d == today
                Column(
                    Modifier.weight(1f).clip(RoundedCornerShape(10.dp)).clickable { onDay(d) }.semantics { contentDescription = cap(dayWords(d, today)) },
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text(JC[weekday(d)], style = MaterialTheme.typography.labelMedium, color = if (isToday) scheme.primary else scheme.onSurfaceVariant, maxLines = 1)
                    Box(Modifier.size(32.dp).clip(CircleShape).background(if (isToday) scheme.primary else androidx.compose.ui.graphics.Color.Transparent), contentAlignment = Alignment.Center) {
                        Text(partsOf(d).d.toString(), style = MaterialTheme.typography.titleMedium, color = if (isToday) scheme.onPrimary else scheme.onSurface)
                    }
                }
            }
        }
        // les journées entières, en bandes
        if (bands.isNotEmpty()) {
            val rows = (bands.maxOf { it.lane } + 1)
            Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
                Spacer(Modifier.width(gutter))
                BoxWithConstraints(Modifier.weight(1f).height(22.dp * rows)) {
                    val col = maxWidth / n
                    for (b in bands) {
                        val look = occLook(b.o, calendars, today, nowMinute)
                        Box(
                            Modifier
                                .offset(x = col * b.from + 1.dp, y = 22.dp * b.lane + 1.dp)
                                .width(col * (b.to - b.from + 1) - 2.dp)
                                .height(20.dp)
                                .alpha(if (look.faded) 0.62f else 1f)
                                .occBackground(look, 5.dp)
                                .clickable { onOpen(b.o) }
                                .padding(horizontal = 4.dp),
                            contentAlignment = Alignment.CenterStart,
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                if (look.sort == Sort.MIKA || look.sort == Sort.PROPOSED || addedByHer(b.o)) MIcon(R.drawable.ic_m_sparkle, null, size = 10.dp, tint = mika.accent)
                                Text(b.o.title, fontSize = 11.sp, fontWeight = FontWeight.Medium, color = look.ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
            }
        }
        HorizontalDivider(color = scheme.outlineVariant)
        // les heures
        Row(Modifier.fillMaxWidth().weight(1f).verticalScroll(scroll)) {
            Box(Modifier.width(gutter).height(HOUR * 24)) {
                for (h in 1 until 24) {
                    Text(
                        "${h.toString().padStart(2, '0')}:00",
                        fontSize = 11.sp,
                        color = scheme.onSurfaceVariant,
                        modifier = Modifier.offset(y = HOUR * h - 7.dp).padding(start = 4.dp),
                    )
                }
            }
            for (d in days) {
                DayColumn(d, shown.filter { !it.allDay && it.day == d }, n, today, nowMinute, calendars, onOpen, onSlot, Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun DayColumn(
    day: String,
    occs: List<Occ>,
    n: Int,
    today: String,
    nowMinute: Int,
    calendars: List<AgendaCalendar>,
    onOpen: (Occ) -> Unit,
    onSlot: (String, Int) -> Unit,
    modifier: Modifier,
) {
    val scheme = MaterialTheme.colorScheme
    val slots = remember(occs) { columns(occs) }
    val slot by rememberUpdatedState(onSlot)
    val density = LocalDensity.current
    BoxWithConstraints(
        modifier
            .height(HOUR * 24)
            .pointerInput(day) {
                detectTapGestures { pos ->
                    val hourPx = with(density) { HOUR.toPx() }
                    val minute = ((pos.y / hourPx * 2).toInt() * 30).coerceIn(0, 1410)
                    slot(day, minute)
                }
            },
    ) {
        val w = maxWidth
        // les lignes des heures, et le filet à gauche de la colonne
        for (h in 0 until 24) Box(Modifier.offset(y = HOUR * h).fillMaxWidth().height(1.dp).background(scheme.outlineVariant.copy(alpha = 0.5f)))
        Box(Modifier.width(1.dp).fillMaxHeight().background(scheme.outlineVariant.copy(alpha = 0.5f)))
        for (s in slots) {
            val look = occLook(s.o, calendars, today, nowMinute)
            val top = HOUR * (s.from / 60f)
            val height = (HOUR * ((s.to - s.from) / 60f) - 2.dp).coerceAtLeast(18.dp)
            val colW = w / s.cols
            val short = height < 34.dp
            Row(
                Modifier
                    .offset(x = colW * s.col + 1.dp, y = top)
                    .width(colW - 3.dp)
                    .height(height)
                    .alpha(if (look.faded) 0.62f else 1f)
                    .occBackground(look, 5.dp)
                    .clickable { onOpen(s.o) },
            ) {
                Box(Modifier.width(3.dp).fillMaxHeight().background(look.bar))
                Column(Modifier.padding(horizontal = 3.dp, vertical = 2.dp)) {
                    // ✦ devant ce qui est à Mika (ce qu'elle a ajouté, ce qu'elle propose, sa mémoire)
                    val mark = if (look.sort == Sort.MIKA || look.sort == Sort.PROPOSED || addedByHer(s.o)) "✦ " else ""
                    val title = mark + s.o.title
                    // ce qui tient dans sa hauteur : le titre, puis l'heure, puis le lieu (jamais coupés à mi-ligne)
                    val lines = ((height.value - 4f) / 14f).toInt().coerceAtLeast(1)
                    val withSub = !short && n < 7 && lines >= 2
                    val place = s.o.item?.location?.substringBefore(" · ").orEmpty()
                    val withPlace = withSub && place.isNotBlank() && lines >= 4
                    Text(
                        if (short && n < 7) "$title ${hm(s.o.start)}" else title,
                        fontSize = if (n == 7) 10.5.sp else 12.sp,
                        lineHeight = if (n == 7) 12.sp else 14.sp,
                        fontWeight = FontWeight.SemiBold,
                        color = look.ink,
                        maxLines = when {
                            short -> 1
                            n == 7 -> lines
                            else -> (lines - (if (withSub) 1 else 0) - (if (withPlace) 1 else 0)).coerceAtLeast(1)
                        },
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (withSub) {
                        val sub = when (look.sort) {
                            Sort.INVITED -> "${hm(s.o.start)} · ${stringResource(R.string.agenda_grid_invited)}"
                            Sort.PROPOSED -> "${hm(s.o.start)} · ${stringResource(R.string.agenda_grid_proposed)}"
                            else -> "${hm(s.o.start)} – ${hm(s.o.end)}"
                        }
                        Text(sub, fontSize = 11.sp, lineHeight = 14.sp, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (withPlace) Text(place, fontSize = 11.sp, lineHeight = 14.sp, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
        if (day == today) {
            val y = HOUR * (nowMinute / 60f)
            Box(Modifier.offset(x = (-4).dp, y = y - 4.dp).size(9.dp).clip(CircleShape).background(scheme.primary))
            Box(Modifier.offset(y = y - 1.dp).fillMaxWidth().height(2.dp).background(scheme.primary))
        }
    }
}

// ── Mois ────────────────────────────────────────────────────────────────

/** Mois : une case par jour, quatre lignes au plus puis « +2 » ; toucher un jour ouvre son Jour. */
@Composable
internal fun MonthView(occs: List<Occ>, month: String, today: String, nowMinute: Int, calendars: List<AgendaCalendar>, onDay: (String) -> Unit, modifier: Modifier = Modifier) {
    val cells = remember(occs, month, today) { monthCells(occs, month, today) }
    val scheme = MaterialTheme.colorScheme
    val rows = cells.size / 7
    Column(modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
            for (l in WEEK_LETTERS) Text(l, Modifier.weight(1f), textAlign = TextAlign.Center, style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
        }
        HorizontalDivider(color = scheme.outlineVariant)
        Column(Modifier.fillMaxWidth().weight(1f)) {
            for (r in 0 until rows) {
                Row(Modifier.fillMaxWidth().weight(1f)) {
                    for (c in 0 until 7) {
                        val cell = cells[r * 7 + c]
                        Column(
                            Modifier
                                .weight(1f)
                                .fillMaxHeight()
                                .background(if (cell.inMonth) scheme.surface else scheme.surfaceContainerLow)
                                .clickable { onDay(cell.day) }
                                .semantics { contentDescription = cap(dayWords(cell.day, today)) }
                                .padding(horizontal = 1.dp, vertical = 2.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            Box(Modifier.size(24.dp).clip(CircleShape).background(if (cell.today) scheme.primary else androidx.compose.ui.graphics.Color.Transparent), contentAlignment = Alignment.Center) {
                                Text(
                                    partsOf(cell.day).d.toString(),
                                    fontSize = 12.sp,
                                    fontWeight = if (cell.today) FontWeight.SemiBold else FontWeight.Normal,
                                    color = when {
                                        cell.today -> scheme.onPrimary
                                        cell.inMonth -> scheme.onSurface
                                        else -> scheme.onSurfaceVariant
                                    },
                                )
                            }
                            for (o in cell.shown) {
                                val look = occLook(o, calendars, today, nowMinute)
                                Text(
                                    o.title,
                                    fontSize = 9.5.sp,
                                    lineHeight = 11.sp,
                                    maxLines = 1,
                                    overflow = TextOverflow.Clip,
                                    color = look.ink,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .alpha(if (look.faded) 0.62f else 1f)
                                        .occBackground(look, 3.dp)
                                        .padding(horizontal = 2.dp),
                                )
                            }
                            if (cell.more > 0) Text("+${cell.more}", fontSize = 9.5.sp, color = scheme.onSurfaceVariant)
                        }
                        if (c < 6) Box(Modifier.width(1.dp).fillMaxHeight().background(scheme.outlineVariant.copy(alpha = 0.4f)))
                    }
                }
                HorizontalDivider(color = scheme.outlineVariant.copy(alpha = 0.4f))
            }
        }
    }
}

// ── Le mini-mois, déplié sous la barre ──────────────────────────────────

/**
 * Le mois déplié sous le titre : un point sous les jours qui ont quelque chose, aujourd'hui en indigo, le jour choisi en
 * tonal ; balayer change de mois, toucher un jour y va et replie. Au pied, « Agendas à afficher » et le mois d'avant
 * et d'après.
 */
@Composable
internal fun MiniMonth(
    month: String,
    occs: List<Occ>,
    today: String,
    selected: String,
    shownCount: Pair<Int, Int>,
    onPick: (String) -> Unit,
    onMove: (Int) -> Unit,
    onCalendars: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val days = remember(month) { monthDays(month) }
    val busy = remember(occs) { busyDays(occs) }
    val m = partsOf(month).m
    Column(Modifier.fillMaxWidth().background(scheme.surface).swipe(onMove).padding(horizontal = 8.dp)) {
        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
            for (l in WEEK_LETTERS) Text(l, Modifier.weight(1f), textAlign = TextAlign.Center, style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
        }
        for (r in 0 until days.size / 7) {
            Row(Modifier.fillMaxWidth()) {
                for (c in 0 until 7) {
                    val d = days[r * 7 + c]
                    val isToday = d == today
                    val sel = d == selected && !isToday
                    Column(
                        Modifier.weight(1f).height(42.dp).clip(RoundedCornerShape(12.dp)).clickable { onPick(d) }.semantics { contentDescription = cap(dayWords(d, today)) },
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Box(
                            Modifier.size(30.dp).clip(CircleShape).background(
                                when {
                                    isToday -> scheme.primary
                                    sel -> scheme.secondaryContainer
                                    else -> androidx.compose.ui.graphics.Color.Transparent
                                },
                            ),
                            contentAlignment = Alignment.Center,
                        ) {
                            Text(
                                partsOf(d).d.toString(),
                                style = MaterialTheme.typography.bodyMedium,
                                color = when {
                                    isToday -> scheme.onPrimary
                                    partsOf(d).m != m -> scheme.onSurfaceVariant.copy(alpha = 0.6f)
                                    else -> scheme.onSurface
                                },
                            )
                        }
                        Box(Modifier.size(4.dp).clip(CircleShape).background(if (d in busy) scheme.onSurfaceVariant else androidx.compose.ui.graphics.Color.Transparent))
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onCalendars) {
                MIcon(R.drawable.ic_m_eye, null, size = 16.dp)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.agenda_calendars_shown, shownCount.first, shownCount.second))
            }
            Spacer(Modifier.weight(1f))
            fr.qwartz.mika.ui.shell.BarAction(R.drawable.ic_m_chev_left, stringResource(R.string.agenda_month_previous), { onMove(-1) })
            fr.qwartz.mika.ui.shell.BarAction(R.drawable.ic_m_chev_right, stringResource(R.string.agenda_month_next), { onMove(1) })
        }
        HorizontalDivider(color = scheme.outlineVariant)
    }
}
