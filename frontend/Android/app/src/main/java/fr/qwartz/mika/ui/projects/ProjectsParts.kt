package fr.qwartz.mika.ui.projects

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SecondaryScrollableTabRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.projects.Checks
import fr.qwartz.mika.data.moi.projects.Pull
import fr.qwartz.mika.data.moi.projects.Review
import fr.qwartz.mika.data.moi.projects.Segment
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.checksTone
import fr.qwartz.mika.data.moi.projects.pullTone
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.ui.components.ProMarkdownText
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.theme.mika
import fr.qwartz.mika.ui.theme.states
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.LaunchedEffect
import fr.qwartz.mika.data.moi.MoiError
import androidx.compose.material3.OutlinedButton

/*
 * Les formes que les vues de l'écran Projets partagent (ADR 0296), d'après sa maquette validée en largeur de téléphone
 * (les captures `-390-` de `output/chaines-de-travail/web/v3/captures`) et dans le thème de l'app : les pastilles d'état et leurs
 * couleurs, les mêmes partout ; les barres de jalons ; les lignes de liste serrées ; les volets d'un détail ; un texte
 * venu d'ailleurs, toujours présenté comme tel ; la pull request liée et son statut. Les lots suivants (Code,
 * Documentation, Activité, Dépendances, Listes) s'en servent tels quels.
 */

/** Les couleurs d'un état : son fond léger, son encre (texte, icône, point), et ce qui remplit un segment de barre. */
internal data class ToneColors(val container: Color, val ink: Color, val bar: Color)

/**
 * Les couleurs d'état de la maquette, les mêmes partout : à toi (ambre), elle y travaille (bleu), fait ou fusionné
 * (vert), en échec ou refusé (rouge), en attente (gris-bleu — jamais un gris pâle sur fond clair).
 */
@Composable
@ReadOnlyComposable
internal fun toneOf(tone: StateTone): ToneColors {
    val dark = MaterialTheme.colorScheme.surface.luminance() < 0.5f
    val scheme = MaterialTheme.colorScheme
    return when (tone) {
        StateTone.YOU -> ToneColors(states.warnContainer, states.warn, if (dark) Color(0xFFF6BD5C) else Color(0xFFB45309))
        StateTone.WORK -> if (dark) ToneColors(Color(0xFF11294D), Color(0xFF9CC2FF), Color(0xFF7DB0FF)) else ToneColors(Color(0xFFE3EEFF), Color(0xFF0B5CC4), Color(0xFF1565D8))
        StateTone.DONE -> ToneColors(states.okContainer, states.ok, states.ok)
        StateTone.FAIL -> ToneColors(scheme.errorContainer, if (dark) scheme.onErrorContainer else scheme.error, scheme.error)
        StateTone.WAIT -> if (dark) ToneColors(Color(0xFF263042), Color(0xFFB6C2D4), Color(0xFF465066)) else ToneColors(Color(0xFFE8ECF3), Color(0xFF475569), Color(0xFFD5D9E6))
    }
}

/** Une icône du jeu de la maquette, par son nom (les règles pures les nomment ainsi) ; un nom inconnu : l'alerte. */
@DrawableRes
internal fun projectIcon(name: String): Int = when (name) {
    "shield-check" -> R.drawable.ic_m_shield_check
    "plan" -> R.drawable.ic_m_plan
    "question" -> R.drawable.ic_m_question
    "ticket" -> R.drawable.ic_m_ticket
    "merge" -> R.drawable.ic_m_merge
    "stop" -> R.drawable.ic_m_stop
    "board" -> R.drawable.ic_m_board
    "eye" -> R.drawable.ic_m_eye
    "check" -> R.drawable.ic_m_check
    "play" -> R.drawable.ic_m_play
    "x" -> R.drawable.ic_m_x
    "minus" -> R.drawable.ic_m_minus
    "target" -> R.drawable.ic_m_target
    "pr" -> R.drawable.ic_m_pr
    "branch" -> R.drawable.ic_m_branch
    "refresh" -> R.drawable.ic_m_refresh
    "clock" -> R.drawable.ic_m_clock
    "commit" -> R.drawable.ic_m_commit
    "issue" -> R.drawable.ic_m_issue
    "bolt" -> R.drawable.ic_m_bolt
    "user" -> R.drawable.ic_m_user
    "code" -> R.drawable.ic_m_code
    "flag" -> R.drawable.ic_m_flag
    "tools" -> R.drawable.ic_m_tools
    "settings" -> R.drawable.ic_m_settings
    else -> R.drawable.ic_m_alert
}

/** La pastille d'un état : un point à sa couleur et les mots du serveur, sur son fond léger. */
@Composable
internal fun StatePill(tone: StateTone, label: String, modifier: Modifier = Modifier) {
    if (label.isBlank()) return
    val c = toneOf(tone)
    Row(
        modifier.heightIn(min = 22.dp).clip(RoundedCornerShape(50)).background(c.container).padding(horizontal = 8.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).background(c.ink, CircleShape))
        Spacer(Modifier.width(5.dp))
        Text(label, color = c.ink, style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** Une petite étiquette sans couleur d'état (la sorte d'un ticket). */
@Composable
internal fun KindChip(label: String) {
    if (label.isBlank()) return
    Text(
        label,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurface,
        maxLines = 1,
        modifier = Modifier.border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(6.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

/** « venu d'ailleurs » : la marque d'un texte ou d'un objet qui ne vient ni d'elle ni du propriétaire (un liseré en tirets). */
@Composable
internal fun OutsideMark(modifier: Modifier = Modifier) {
    val line = MaterialTheme.colorScheme.outline
    Row(
        modifier
            .drawBehind {
                drawRoundRect(
                    line,
                    cornerRadius = CornerRadius(size.height / 2),
                    style = Stroke(width = 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 3.dp.toPx()))),
                )
            }
            .padding(horizontal = 8.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(R.drawable.ic_m_external, null, size = 12.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(4.dp))
        Text(stringResource(R.string.proj_outside), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
    }
}

/**
 * Un texte venu d'ailleurs (une issue d'un inconnu, un commentaire de l'hôte, la fin d'un journal) : cité comme une
 * donnée, sous son liseré, en texte brut — jamais mis en forme, aucun lien ; [mono] : en chasse fixe (un journal).
 */
@Composable
internal fun OutsideBlock(from: String, text: String, modifier: Modifier = Modifier, mono: Boolean = false) {
    val line = MaterialTheme.colorScheme.outline
    Column(
        modifier
            .fillMaxWidth()
            .drawBehind { drawLine(line, Offset(1.dp.toPx(), 0f), Offset(1.dp.toPx(), size.height), strokeWidth = 2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx()))) }
            .padding(start = 12.dp, top = 2.dp, bottom = 2.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            MIcon(R.drawable.ic_m_external, null, size = 13.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(5.dp))
            Text(
                if (from.isBlank()) stringResource(R.string.proj_outside) else stringResource(R.string.proj_outside_from, from),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Gap(4.dp)
        SelectionContainer {
            if (mono) {
                Text(
                    text,
                    style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace, lineHeight = 17.sp),
                    modifier = Modifier.horizontalScroll(rememberScrollState()),
                )
            } else {
                Text(text, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

/** Un texte d'elle ou de la personne, en Markdown (le rendu du mode pro : aucun HTML interprété). */
@Composable
internal fun MdText(text: String, modifier: Modifier = Modifier) {
    ProMarkdownText(text, MaterialTheme.colorScheme.onSurface, modifier)
}

/** La barre de jalons : un segment par jalon, à la couleur de son état. */
@Composable
internal fun MilestoneBar(tones: List<StateTone>, modifier: Modifier = Modifier, height: Dp = 5.dp) {
    Row(modifier, horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        for (t in tones) Box(Modifier.weight(1f).height(height).clip(RoundedCornerShape(50)).background(toneOf(t).bar))
    }
}

/** Une barre d'avancement (le diagramme) : ses parts faites, couleur par couleur, sur sa piste ; « à toi » en hachures. */
@Composable
internal fun SegmentBar(segments: List<Segment>, modifier: Modifier = Modifier, height: Dp = 12.dp) {
    val track = toneOf(StateTone.WAIT).container
    val colors = segments.map { toneOf(it.tone) to it }
    val stripe = MaterialTheme.colorScheme.surface
    Box(
        modifier.height(height).clip(RoundedCornerShape(50)).background(track).drawBehind {
            var x = 0f
            for ((c, s) in colors) {
                val w = size.width * s.part.coerceIn(0f, 1f)
                drawRect(c.bar, topLeft = Offset(x, 0f), size = androidx.compose.ui.geometry.Size(w, size.height))
                if (s.tone == StateTone.YOU) {
                    // des hachures : ce segment attend la personne
                    val step = 7.dp.toPx()
                    clipRect(x, 0f, x + w, size.height) {
                        var sx = x - size.height
                        while (sx < x + w) {
                            drawLine(stripe, Offset(sx, size.height), Offset(sx + size.height, 0f), strokeWidth = 2.dp.toPx())
                            sx += step
                        }
                    }
                }
                x += w
            }
        },
    )
}

/** La tuile d'un objet : son icône sur le fond de son état. */
@Composable
internal fun Tile(@DrawableRes icon: Int, tone: StateTone, size: Dp = 36.dp) {
    val c = toneOf(tone)
    Box(Modifier.size(size).clip(RoundedCornerShape(10.dp)).background(c.container), contentAlignment = Alignment.Center) {
        MIcon(icon, null, size = size * 0.5f, tint = c.ink)
    }
}

/** Le titre d'un groupe d'une liste : en petites capitales, son compte au bout. */
@Composable
internal fun GroupLabel(text: String, count: Int? = null) {
    Row(
        Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerLow).padding(horizontal = 16.dp, vertical = 8.dp).semantics { heading() },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text.uppercase(),
            style = MaterialTheme.typography.labelMedium,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        if (count != null) Text(count.toString(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

/** Un filtre en pastille : son code, ses mots, son compte (`null` : pas de compte). */
internal data class Chip(val code: String, val label: String, val count: Int? = null)

/** Des filtres en pastilles, qui défilent en largeur. */
@Composable
internal fun ChipRow(chips: List<Chip>, selected: String, onPick: (String) -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (c in chips) {
            FilterChip(
                selected = c.code == selected,
                onClick = { onPick(c.code) },
                label = { Text(if (c.count == null) c.label else "${c.label}  ${c.count}", maxLines = 1) },
            )
        }
    }
}

/** Un volet d'un détail : son code, ses mots, son compte. */
internal data class Pane(val code: String, val label: String, val count: String = "")

/** Les volets d'un détail (ce que le web met en onglets dans le contenu, et son panneau latéral en « Infos »), qui défilent en largeur. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun PaneTabs(panes: List<Pane>, active: String, onPick: (String) -> Unit) {
    val index = panes.indexOfFirst { it.code == active }.coerceAtLeast(0)
    SecondaryScrollableTabRow(selectedTabIndex = index, edgePadding = 8.dp) {
        for (p in panes) {
            Tab(
                selected = p.code == active,
                onClick = { onPick(p.code) },
                text = {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(p.label, maxLines = 1)
                        if (p.count.isNotBlank()) {
                            Spacer(Modifier.width(6.dp))
                            CountChip(p.count)
                        }
                    }
                },
            )
        }
    }
}

/** Un compte à côté d'un nom d'onglet ou d'une carte. */
@Composable
internal fun CountChip(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.SemiBold,
        color = MaterialTheme.colorScheme.onSecondaryContainer,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(MaterialTheme.colorScheme.secondaryContainer).padding(horizontal = 6.dp, vertical = 1.dp),
    )
}

/** Le titre d'une partie du volet « Infos » (« Son parcours », « En bref », « Ce qui est lié »). */
@Composable
internal fun SideTitle(text: String) {
    Text(
        text.uppercase(),
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.Bold,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(top = 16.dp, bottom = 8.dp).semantics { heading() },
    )
}

/** Une propriété du volet « Infos » : son nom, puis sa valeur. */
@Composable
internal fun Fact(label: String, content: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(128.dp))
        Box(Modifier.weight(1f)) { content() }
    }
}

@Composable
internal fun Fact(label: String, value: String) {
    if (value.isBlank()) return
    Fact(label) { Text(value, style = MaterialTheme.typography.bodyMedium) }
}

/** Un refus du serveur, dit sur place avec ses mots ; rien sans refus. */
@Composable
internal fun RefusalNote(text: String, modifier: Modifier = Modifier) {
    if (text.isBlank()) return
    NoteBox(text, R.drawable.ic_m_alert, modifier, tone = Tone.DANGER)
}

/**
 * Ce qu'on montre date d'avant le retour sur l'écran et n'a pas pu se relire : l'erreur dite avec ses mots, et
 * « Réessayer ». D'ici là rien ne s'y décide (le modèle n'offre aucun geste sur une lecture ancienne).
 */
@Composable
internal fun StaleNote(error: MoiError?, onRetry: () -> Unit, modifier: Modifier = Modifier) {
    if (error == null) return
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        RefusalNote(error.message)
        OutlinedButton(onClick = onRetry) { Text(stringResource(R.string.retry)) }
    }
}

/**
 * Un écran qui s'ouvre ne porte pas ce qu'on avait dit à ses endroits ([wheres]) avant de le quitter — un refus d'un
 * autre jour, un geste abouti après son départ, qui le refermerait. Une fois par ouverture : une rotation n'efface pas
 * le refus qu'on est en train de lire.
 */
@Composable
internal fun FreshEntry(runner: GestureRunner, vararg wheres: String) {
    var entered by rememberSaveable(runner, *wheres) { mutableStateOf(false) }
    LaunchedEffect(runner, *wheres) {
        if (!entered) {
            entered = true
            wheres.forEach(runner::forget)
        }
    }
}

/** Pourquoi un geste ne se fait pas d'ici, ou ce qu'il fera : les mots du serveur, ou une phrase de l'écran. */
@Composable
internal fun Hint(text: String, @DrawableRes icon: Int = R.drawable.ic_m_info, modifier: Modifier = Modifier) {
    if (text.isBlank()) return
    NoteBox(text, icon, modifier)
}

/** Rien à montrer ici : une icône, un titre, une phrase. */
@Composable
internal fun EmptyNote(@DrawableRes icon: Int, title: String, text: String, modifier: Modifier = Modifier, action: (@Composable () -> Unit)? = null) {
    Column(modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 40.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        MIcon(icon, null, size = 32.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Gap(10.dp)
        Text(title, style = MaterialTheme.typography.titleMedium)
        Gap(4.dp)
        Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        if (action != null) {
            Gap(14.dp)
            action()
        }
    }
}

/** Une carte courte de la Vue d'ensemble : son icône, son titre, un lien au bout, puis son contenu. */
@Composable
internal fun OverviewCard(
    @DrawableRes icon: Int,
    title: String,
    modifier: Modifier = Modifier,
    link: String = "",
    onLink: (() -> Unit)? = null,
    container: Color = MaterialTheme.colorScheme.surface,
    border: Color = MaterialTheme.colorScheme.outlineVariant,
    content: @Composable ColumnScope.() -> Unit,
) {
    Surface(shape = RoundedCornerShape(18.dp), color = container, border = BorderStroke(1.dp, border), modifier = modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                MIcon(icon, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(8.dp))
                Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f).semantics { heading() })
                if (onLink != null && link.isNotBlank()) {
                    Row(Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onLink).padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(link, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
                        MIcon(R.drawable.ic_m_chev_right, null, size = 14.dp, tint = MaterialTheme.colorScheme.primary)
                    }
                }
            }
            Gap(10.dp)
            content()
        }
    }
}

/** Une ligne de ce qui est lié (un objectif, un ticket, une issue) : sa tuile, son titre, une ligne sous lui, sa pastille. */
@Composable
internal fun LinkedLine(
    @DrawableRes icon: Int,
    tone: StateTone,
    title: String,
    sub: String,
    modifier: Modifier = Modifier,
    pill: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = modifier.fillMaxWidth().then(if (onClick != null) Modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onClick) else Modifier),
    ) {
        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Tile(icon, tone, 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            if (pill != null) {
                Spacer(Modifier.width(8.dp))
                pill()
            }
            if (onClick != null) MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/**
 * La pull request liée, avec son statut : son état, la CI, la relecture, où elle en est ; [onOpen] mène à l'onglet Code
 * (le lot « Code » y montre la pull request et sa fusion).
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun PullCard(pull: Pull, checks: Checks?, review: Review?, now: Long, modifier: Modifier = Modifier, onOpen: (() -> Unit)? = null) {
    Surface(
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = modifier.fillMaxWidth().then(if (onOpen != null) Modifier.clip(RoundedCornerShape(12.dp)).clickable(onClick = onOpen) else Modifier),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Tile(R.drawable.ic_m_pr, pullTone(pull.state), 32.dp)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        pull.title.ifBlank { stringResource(R.string.proj_pull_n, pull.number) },
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(
                        listOf(stringResource(R.string.proj_pull_n, pull.number), since(pull.at, now)).filter { it.isNotBlank() }.joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                if (onOpen != null) MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Gap(8.dp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                StatePill(pullTone(pull.state), pull.stateLabel)
                if (checks != null) StatePill(checksTone(checks.state), stringResource(R.string.proj_pull_ci, checks.stateLabel))
                if (review != null) StatePill(if (review.ok) StateTone.DONE else StateTone.FAIL, review.label)
                if (pull.conflicts) StatePill(StateTone.FAIL, stringResource(R.string.proj_pull_conflicts))
                if (pull.changesAsked) StatePill(StateTone.YOU, stringResource(R.string.proj_pull_changes))
            }
            if (pull.words.isNotBlank()) {
                Gap(6.dp)
                Text(pull.words, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** Une bulle d'un fil : elle (rose, à gauche), toi (à droite), une autre personne (à gauche). */
@Composable
internal fun Bubble(authorKind: String, who: String, whenText: String, text: String, markdown: Boolean = false) {
    val scheme = MaterialTheme.colorScheme
    val mine = authorKind == "you"
    val bg = when (authorKind) {
        "self" -> mika.soft
        "you" -> scheme.primaryContainer
        else -> scheme.surfaceContainerHigh
    }
    val line = if (authorKind == "self") mika.line else Color.Transparent
    Column(Modifier.fillMaxWidth(), horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
        Text(
            listOf(who, whenText).filter { it.isNotBlank() }.joinToString(" · "),
            style = MaterialTheme.typography.labelSmall,
            color = if (authorKind == "self") mika.accent else scheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp),
        )
        Surface(shape = RoundedCornerShape(16.dp), color = bg, border = BorderStroke(1.dp, line), modifier = Modifier.widthIn(max = 320.dp)) {
            Box(Modifier.padding(horizontal = 12.dp, vertical = 9.dp)) {
                if (markdown) MdText(text) else Text(text, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

/** Une ligne de temps : une pastille à la couleur de ce qui s'est passé, reliée à la suivante, puis son contenu. */
@Composable
internal fun TimelineRow(tone: StateTone?, last: Boolean, content: @Composable ColumnScope.() -> Unit) {
    val line = MaterialTheme.colorScheme.outlineVariant
    val dot = tone?.let { toneOf(it).ink } ?: MaterialTheme.colorScheme.onSurfaceVariant
    Row(Modifier.fillMaxWidth().height(androidx.compose.foundation.layout.IntrinsicSize.Min)) {
        Box(
            Modifier.width(22.dp).fillMaxHeight().drawBehind {
                if (!last) drawLine(line, Offset(size.width / 2, 14.dp.toPx()), Offset(size.width / 2, size.height), strokeWidth = 1.5.dp.toPx())
                drawCircle(dot, radius = 4.dp.toPx(), center = Offset(size.width / 2, 9.dp.toPx()))
            },
        )
        Spacer(Modifier.width(8.dp))
        Column(Modifier.weight(1f).padding(bottom = 14.dp), content = content)
    }
}

/** Un code en chasse fixe (une empreinte, une commande, une branche), sur un fond léger. */
@Composable
internal fun Code(text: String, modifier: Modifier = Modifier) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace),
        color = MaterialTheme.colorScheme.onSurface,
        modifier = modifier.clip(RoundedCornerShape(5.dp)).background(MaterialTheme.colorScheme.surfaceContainerHigh).padding(horizontal = 5.dp, vertical = 1.dp),
    )
}
