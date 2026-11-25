package fr.qwartz.mika.ui.agenda

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.agenda.AgendaApi
import fr.qwartz.mika.data.moi.agenda.AgendaCalendar
import fr.qwartz.mika.data.moi.agenda.AgendaPrefs
import fr.qwartz.mika.data.moi.agenda.MemoryAgendaPrefs
import fr.qwartz.mika.data.moi.agenda.Occ
import fr.qwartz.mika.data.moi.agenda.Sort
import fr.qwartz.mika.data.moi.agenda.addedByHer
import fr.qwartz.mika.data.moi.agenda.agendaApi
import fr.qwartz.mika.data.moi.agenda.isPast
import fr.qwartz.mika.data.moi.agenda.occColor
import fr.qwartz.mika.data.moi.agenda.shortWhen
import fr.qwartz.mika.data.moi.agenda.sortOf
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Shell
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.launch

/*
 * Ce que les écrans de l'Agenda partagent (ADR 0309, la maquette validée `frontend/Android/maquette/ecrans/agenda*.js`) :
 * l'API, ce que l'app retient (la dernière vue, les agendas décochés), les couleurs des agendas (`--ag-*` de
 * `agenda.css`), la carte d'une occurrence (le Planning, la recherche), « Demander à Mika ».
 */

/**
 * Ce que les écrans de l'Agenda prennent de la session : l'API, ce que l'app retient, l'heure, relire les pastilles du
 * tiroir. Un test JVM les donne sans le graphe de l'app.
 */
class AgendaDeps(
    val api: AgendaApi,
    val prefs: AgendaPrefs = MemoryAgendaPrefs(),
    val now: () -> Long = System::currentTimeMillis,
    val refreshBadges: () -> Unit = {},
) {
    constructor(graph: AppGraph) : this(graph.agendaApi(), graph.agendaPrefs, graph.clock::wallMs, { graph.me.refresh() })

    constructor(api: AgendaApi, clock: Clock) : this(api, MemoryAgendaPrefs(), clock::wallMs)
}

// ── Les couleurs ────────────────────────────────────────────────────────

private val LIGHT = mapOf(
    "indigo" to Color(0xFF4F46E5), "bleu" to Color(0xFF1F6FD0), "sarcelle" to Color(0xFF0F8B80), "vert" to Color(0xFF1E9A4B),
    "ambre" to Color(0xFFC08406), "orange" to Color(0xFFE26A1B), "violet" to Color(0xFF8B5CF6), "ardoise" to Color(0xFF66748A),
)
private val DARK = mapOf(
    "indigo" to Color(0xFFA3A0FF), "bleu" to Color(0xFF62A8FF), "sarcelle" to Color(0xFF3FCBBB), "vert" to Color(0xFF55CF86),
    "ambre" to Color(0xFFF0C04E), "orange" to Color(0xFFFF9A57), "violet" to Color(0xFFB89DFF), "ardoise" to Color(0xFF9AA6B8),
)

private val dark: Boolean
    @Composable @ReadOnlyComposable
    get() = MaterialTheme.colorScheme.surface.luminance() < 0.5f

/** La couleur d'un agenda (son nom dans la palette) ; le rose est celui de Mika. */
@Composable
@ReadOnlyComposable
internal fun agendaColor(name: String): Color = when {
    name == "rose" -> if (dark) mika.accent else mika.fill
    dark -> DARK[name] ?: DARK.getValue("ardoise")
    else -> LIGHT[name] ?: LIGHT.getValue("ardoise")
}

/** Le fond teinté d'une occurrence : sa couleur mêlée à la surface (16 % en clair, 24 % en sombre). */
@Composable
@ReadOnlyComposable
internal fun tintOf(color: Color): Color = lerp(MaterialTheme.colorScheme.surface, color, if (dark) 0.24f else 0.16f)

/** Le carré de la couleur d'un agenda. */
@Composable
internal fun Swatch(color: String, size: Dp, modifier: Modifier = Modifier) {
    Box(modifier.size(size).clip(RoundedCornerShape(size * 0.28f)).background(agendaColor(color)))
}

/** Les hachures roses de ce que Mika propose (pas encore dans ton agenda). */
internal fun Modifier.hatched(color: Color, surface: Color): Modifier = drawBehind {
    drawRect(surface)
    val step = 11.dp.toPx()
    val w = 6.dp.toPx()
    var x = -size.height
    while (x < size.width) {
        drawLine(color, Offset(x, size.height), Offset(x + size.height, 0f), strokeWidth = w * 0.7f)
        x += step
    }
}

/** Un contour en pointillés (une invitation qui attend ta réponse). */
internal fun Modifier.dashed(color: Color, radius: Dp = 8.dp): Modifier = drawBehind {
    drawRoundRect(
        color,
        cornerRadius = CornerRadius(radius.toPx()),
        style = Stroke(width = 1.4.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx()))),
    )
}

/** Le fond, le contour et l'encre d'une occurrence, selon sa sorte et si elle est passée. */
internal data class OccLook(val bar: Color, val fill: Color, val ink: Color, val faded: Boolean, val sort: Sort)

@Composable
internal fun occLook(o: Occ, calendars: List<AgendaCalendar>, today: String, nowMinute: Int): OccLook {
    val color = agendaColor(occColor(o, calendars))
    val sort = sortOf(o)
    return OccLook(
        bar = color,
        fill = tintOf(color),
        ink = if (sort == Sort.MIKA || sort == Sort.PROPOSED) mika.accent else MaterialTheme.colorScheme.onSurface,
        faded = isPast(o, today, nowMinute),
        sort = sort,
    )
}

/** Le fond d'une occurrence, selon sa sorte : hachuré pour une proposition, en pointillés pour une invitation. */
@Composable
internal fun Modifier.occBackground(look: OccLook, radius: Dp = 8.dp): Modifier {
    val shape = RoundedCornerShape(radius)
    return when (look.sort) {
        Sort.PROPOSED -> this.clip(shape).hatched(look.fill, MaterialTheme.colorScheme.surface).border(1.dp, mika.line, shape)
        Sort.INVITED -> this.clip(shape).background(MaterialTheme.colorScheme.surface).dashed(look.bar, radius)
        else -> this.clip(shape).background(look.fill)
    }
}

/** Les étiquettes d'une occurrence : invitation de qui, peut-être, proposé ou ajouté par Mika, promis. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun OccTags(o: Occ, words: OccTagWords) {
    val tags = buildList {
        when (sortOf(o)) {
            Sort.INVITED -> add(Triple(words.invited(firstName(o.item?.organizer?.name.orEmpty()).ifBlank { o.item?.organizer?.address.orEmpty() }), Tone.WARN, false))
            Sort.MAYBE -> add(Triple(words.maybe, Tone.NEUTRAL, false))
            Sort.PROPOSED -> add(Triple(words.proposed, Tone.MIKA, true))
            Sort.MIKA -> add(Triple(if (o.her?.kind == "promesse") words.promised else words.remembers, Tone.MIKA, true))
            Sort.PLAIN -> Unit
        }
        if (addedByHer(o)) add(Triple(words.added, Tone.MIKA, true))
    }
    if (tags.isEmpty()) return
    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp), modifier = Modifier.padding(top = 4.dp)) {
        for ((text, tone, sparkle) in tags) Tag(text, tone, if (sparkle) R.drawable.ic_m_sparkle else null)
    }
}

/** Les mots des étiquettes (les chaînes `agenda_tag_*`). */
internal data class OccTagWords(
    val invited: (String) -> String,
    val maybe: String,
    val proposed: String,
    val promised: String,
    val remembers: String,
    val added: String,
    val visio: String,
)

/**
 * Une occurrence dans une liste (le Planning, la recherche) : la barre de sa couleur, son titre (✦ si elle est de Mika,
 * ↻ si elle se répète), son moment, son lieu et son agenda, ses étiquettes. Passée, elle pâlit.
 */
@Composable
internal fun OccCard(o: Occ, calendars: List<AgendaCalendar>, today: String, nowMinute: Int, words: OccTagWords, onClick: () -> Unit) {
    val look = occLook(o, calendars, today, nowMinute)
    val cal = calendars.firstOrNull { it.key == o.calendar }
    val where = o.item?.location?.substringBefore(" · ")?.takeIf { it.isNotBlank() }
        ?: o.proposal?.draft?.location?.takeIf { it.isNotBlank() }
        ?: o.item?.conference?.takeIf { it.isNotBlank() }?.let { words.visio }
    val sub = listOfNotNull(shortWhen(o), where, cal?.name?.takeIf { o.her == null && o.proposal == null }).joinToString(" · ")
    Row(
        Modifier
            .fillMaxWidth()
            .height(IntrinsicSize.Min)
            .alpha(if (look.faded) 0.62f else 1f)
            .occBackground(look)
            .clickable(onClick = onClick),
    ) {
        Box(Modifier.width(4.dp).fillMaxHeight().background(look.bar))
        Column(Modifier.weight(1f).padding(horizontal = 10.dp, vertical = 7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (look.sort == Sort.MIKA || look.sort == Sort.PROPOSED || addedByHer(o)) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 13.dp, tint = mika.accent)
                    Spacer(Modifier.width(4.dp))
                }
                Text(
                    o.title,
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                    color = look.ink,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f, fill = false),
                )
                if (o.item?.recurring == true) {
                    Spacer(Modifier.width(4.dp))
                    MIcon(R.drawable.ic_m_repeat, null, size = 13.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            OccTags(o, words)
        }
    }
}

/** La route qui ouvre une occurrence : sa fiche, ce que Mika propose, une date de sa mémoire. */
internal fun routeOf(o: Occ): Route? = when {
    o.item != null -> Route.AgendaEvent(o.item.event, o.item.occurrence)
    o.proposal != null -> Route.AgendaProposal(o.proposal.id)
    o.her != null -> Route.AgendaHer(o.her)
    else -> null
}

/** « Demander à Mika », « Lui en parler » : la phrase dans le champ du chat, à compléter, puis le chat. */
internal fun askMika(shell: Shell, text: String) {
    shell.graph.scope.launch { shell.graph.shareInbox.deposit(ComposerDraft(text = text)) }
    shell.open(Route.Chat)
}

/** Un des trois boutons de réponse (Accepter · Peut-être · Refuser) : serré, pour que les trois tiennent sur un
 *  téléphone ; plein quand c'est ta réponse. */
@Composable
internal fun AnswerButton(answer: String, label: String, on: Boolean, enabled: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val pad = PaddingValues(horizontal = 8.dp, vertical = 8.dp)
    val content: @Composable () -> Unit = {
        when (answer) {
            "oui" -> MIcon(R.drawable.ic_m_check, null, size = 16.dp)
            "non" -> MIcon(R.drawable.ic_m_x, null, size = 16.dp)
        }
        if (answer == "oui" || answer == "non") Spacer(Modifier.width(4.dp))
        Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.labelLarge)
    }
    if (on) {
        Button(onClick = onClick, enabled = enabled, contentPadding = pad, modifier = modifier) { content() }
    } else {
        OutlinedButton(onClick = onClick, enabled = enabled, contentPadding = pad, modifier = modifier) { content() }
    }
}

/** Une note de bas de fiche (`.ag-ro`) : un cadenas ou ↻, et ce qu'elle dit. */
@Composable
internal fun FootNote(text: String, icon: Int, modifier: Modifier = Modifier) {
    if (text.isBlank()) return
    Surface(shape = RoundedCornerShape(14.dp), color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
            MIcon(icon, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(10.dp))
            Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** La boîte rose de ce qui est à Mika (`.ag-box.mk`). */
@Composable
internal fun PinkBox(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Surface(
        shape = RoundedCornerShape(18.dp),
        color = mika.soft,
        border = BorderStroke(1.dp, mika.line),
        modifier = modifier.fillMaxWidth(),
    ) { Box(Modifier.padding(14.dp)) { content() } }
}

/** Le petit filet d'un séparateur de groupe. */
@Composable
internal fun Rule(modifier: Modifier = Modifier) {
    val c = MaterialTheme.colorScheme.outlineVariant
    Canvas(modifier.fillMaxWidth().height(1.dp)) { drawRect(c) }
}
