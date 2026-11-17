package fr.qwartz.mika.ui.shell

import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.material3.TopAppBar
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.hue
import fr.qwartz.mika.data.moi.initials
import fr.qwartz.mika.data.moi.refusalText
import fr.qwartz.mika.data.moi.toFillRanges
import fr.qwartz.mika.ui.theme.mika
import fr.qwartz.mika.ui.theme.states

/*
 * Les petites formes que les rubriques de l'API par personne partagent (Mail, Teams…), celles de la maquette
 * (`maquette/maquette.css`) : un rond d'initiales, une marque, la ligne rose de ce qu'elle a préparé, une note
 * encadrée, le menu « ⋮ », la barre de recherche, une ligne de feuille, une petite fenêtre à un champ ; un refus en
 * mots, un texte et ses liens, ses passages à compléter.
 */

/** Ce qui distingue une session d'une autre : les écrans d'un autre compte ne reprennent rien de ceux d'avant. */
@Composable
internal fun rememberSessionKey(graph: AppGraph): String {
    val session by graph.auth.session.collectAsStateWithLifecycle()
    return (session as? Session.LoggedIn)?.let { "${it.base}|${it.profile.username}" }.orEmpty()
}

/** Un refus en mots, ce qu'il dit champ par champ compris. */
internal val MoiError.said: String get() = refusalText(message, fields)


// ── Les petites formes ──────────────────────────────────────────────────

/** Les teintes des ronds d'initiales (`.av.c0`…`.av.c7` de la maquette). */
private val AVATAR_COLORS = listOf(
    Color(0xFF4F46E5), Color(0xFFC2410C), Color(0xFF0F766E), Color(0xFF7C3AED),
    Color(0xFF475569), Color(0xFFB45309), Color(0xFF0369A1), Color(0xFFBE185D),
)

/** Un rond d'initiales, d'une teinte stable pour [key] (son adresse). */
@Composable
internal fun PersonAvatar(name: String, key: String, size: Dp = 40.dp) {
    val label = name.ifBlank { key }
    Box(
        Modifier.size(size).clip(CircleShape).background(AVATAR_COLORS[hue(key.ifBlank { label })]),
        contentAlignment = Alignment.Center,
    ) {
        Text(initials(label), color = Color.White, fontWeight = FontWeight.SemiBold, fontSize = (size.value * 0.36f).sp, maxLines = 1)
    }
}

/** Les couleurs d'une marque, selon son ton. */
@Composable
internal fun toneColors(tone: Tone): Pair<Color, Color> {
    val scheme = MaterialTheme.colorScheme
    return when (tone) {
        Tone.NEUTRAL -> scheme.surfaceContainerHigh to scheme.onSurfaceVariant
        Tone.WARN -> states.warnContainer to states.warn
        Tone.OK -> states.okContainer to states.ok
        Tone.DANGER -> scheme.errorContainer to scheme.onErrorContainer
        Tone.INFO -> scheme.primaryContainer to scheme.onPrimaryContainer
        Tone.MIKA -> mika.container to mika.onContainer
    }
}

/** Une marque (`.tag` de la maquette) : « Réponse attendue », « son brouillon », « attend ton accord »… */
@Composable
internal fun Tag(text: String, tone: Tone, @DrawableRes icon: Int? = null) {
    val (bg, fg) = toneColors(tone)
    Row(
        Modifier.heightIn(min = 22.dp).clip(RoundedCornerShape(6.dp)).background(bg).padding(horizontal = 8.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            MIcon(icon, null, size = 13.dp, tint = fg)
            Spacer(Modifier.width(4.dp))
        }
        Text(text, color = fg, style = MaterialTheme.typography.labelMedium, maxLines = 1)
    }
}

/** Ce qu'elle a fait, en rose sans fond (« lu par Mika »). */
@Composable
internal fun MikaMark(text: String, @DrawableRes icon: Int) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        MIcon(icon, null, size = 13.dp, tint = mika.accent)
        Spacer(Modifier.width(3.dp))
        Text(text, color = mika.accent, style = MaterialTheme.typography.labelSmall, maxLines = 1)
    }
}

/** Une pastille de compte : indigo pour ce que tu fais, rose pour ce qu'elle a fait. */
@Composable
internal fun CountPill(n: Int, pink: Boolean = false) {
    if (n <= 0) return
    val bg = if (pink) mika.fill else MaterialTheme.colorScheme.primary
    val fg = if (pink) mika.onFill else MaterialTheme.colorScheme.onPrimary
    Box(Modifier.heightIn(min = 20.dp).widthIn(min = 20.dp).clip(RoundedCornerShape(10.dp)).background(bg).padding(horizontal = 6.dp), contentAlignment = Alignment.Center) {
        Text(if (n > 99) "99+" else n.toString(), color = fg, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.SemiBold)
    }
}

/** La ligne rose de ce qu'elle a préparé (`.mk-line`) : ses brouillons, sa réponse à un mail. */
@Composable
internal fun MikaLine(@DrawableRes icon: Int, title: String, subtitle: String, modifier: Modifier = Modifier, count: Int = 0, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        shape = RoundedCornerShape(16.dp),
        color = mika.soft,
        border = BorderStroke(1.dp, mika.line),
        modifier = modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(horizontal = 14.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            MIcon(icon, null, tint = mika.accent)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                if (subtitle.isNotBlank()) {
                    Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            if (count > 0) {
                Spacer(Modifier.width(8.dp))
                CountPill(count, pink = true)
            } else {
                MIcon(R.drawable.ic_m_chev_right, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** Une note encadrée (`.note.box`) : ce qui bloque, ce qui attend quelqu'un d'autre. */
@Composable
internal fun NoteBox(text: String, @DrawableRes icon: Int, modifier: Modifier = Modifier, tone: Tone = Tone.NEUTRAL) {
    val (bg, fg) = if (tone == Tone.NEUTRAL) MaterialTheme.colorScheme.surfaceContainerLow to MaterialTheme.colorScheme.onSurfaceVariant else toneColors(tone)
    Row(modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(bg).padding(horizontal = 12.dp, vertical = 10.dp)) {
        MIcon(icon, null, size = 20.dp, tint = fg)
        Spacer(Modifier.width(10.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = fg)
    }
}

/** Un titre de groupe dans une liste (`.list-head`). */
@Composable
internal fun ListHead(text: String, pink: Boolean = false, muted: Boolean = false) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = if (muted) FontWeight.Normal else FontWeight.Medium,
        color = when {
            pink -> mika.accent
            muted -> MaterialTheme.colorScheme.onSurfaceVariant
            else -> MaterialTheme.colorScheme.primary
        },
        modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 16.dp, bottom = 6.dp),
    )
}

/** Une entrée d'un menu « ⋮ ». */
internal data class MenuEntry(val label: String, @param:DrawableRes val icon: Int, val onClick: () -> Unit)

/** Le bouton « ⋮ » d'une barre du haut et son menu ; rien sans entrée. */
@Composable
internal fun BarMenu(entries: List<MenuEntry>) {
    if (entries.isEmpty()) return
    var open by remember { mutableStateOf(false) }
    Box {
        BarAction(R.drawable.ic_m_more, stringResource(R.string.shell_more), { open = true })
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            for (e in entries) {
                DropdownMenuItem(
                    text = { Text(e.label) },
                    leadingIcon = { MIcon(e.icon, null, size = 20.dp) },
                    onClick = {
                        open = false
                        e.onClick()
                    },
                )
            }
        }
    }
}

// ── Les barres, les feuilles, les fenêtres ─────────────────────────────

/** La barre du haut pendant une recherche : le champ ([hint] dit ce qu'on cherche), et de quoi l'effacer ou en sortir. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun SearchBar(query: String, hint: String, onQuery: (String) -> Unit, onClose: () -> Unit) {
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { focus.requestFocus() }
    TopAppBar(
        navigationIcon = { BarAction(R.drawable.ic_m_back, stringResource(R.string.shell_search_close), onClose) },
        title = {
            TextField(
                value = query,
                onValueChange = onQuery,
                placeholder = { Text(hint) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { onQuery(query) }),
                colors = TextFieldDefaults.colors(
                    focusedContainerColor = Color.Transparent,
                    unfocusedContainerColor = Color.Transparent,
                    focusedIndicatorColor = Color.Transparent,
                    unfocusedIndicatorColor = Color.Transparent,
                ),
                modifier = Modifier.fillMaxWidth().focusRequester(focus),
            )
        },
        actions = {
            if (query.isNotEmpty()) BarAction(R.drawable.ic_m_x, stringResource(R.string.shell_search_clear), { onQuery("") })
        },
    )
}

/** Une ligne d'une feuille qui monte du titre : son icône, son nom, une ligne sous lui, son compte ; la vue ouverte
 *  est surlignée ([pink] : ce qui est à elle). */
@Composable
internal fun SheetLine(
    @DrawableRes icon: Int,
    title: String,
    subtitle: String,
    count: Int,
    selected: Boolean,
    onClick: () -> Unit,
    pink: Boolean = false,
    pinkCount: Boolean = false,
) {
    val scheme = MaterialTheme.colorScheme
    Surface(
        onClick = onClick,
        color = if (selected) scheme.secondaryContainer else Color.Transparent,
        shape = RoundedCornerShape(28.dp),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp),
    ) {
        Row(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(32.dp), contentAlignment = Alignment.Center) {
                MIcon(icon, null, tint = if (pink) mika.accent else scheme.onSurfaceVariant)
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis, color = if (pink) mika.accent else scheme.onSurface)
                if (subtitle.isNotBlank()) {
                    Text(subtitle, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            CountPill(count, pink = pinkCount)
        }
    }
}

/** Une petite fenêtre à un champ (une note, une consigne). */
@Composable
internal fun AskDialog(
    title: String,
    lede: String,
    label: String,
    placeholder: String,
    confirm: String,
    required: Boolean,
    max: Int,
    danger: Boolean,
    onDismiss: () -> Unit,
    onConfirm: (String) -> Unit,
) {
    var text by rememberSaveable { mutableStateOf("") }
    var error by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                Text(lede, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Gap(12.dp)
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it.take(max); error = false },
                    label = { Text(label) },
                    placeholder = { Text(placeholder) },
                    minLines = 3,
                    isError = error,
                    supportingText = if (error) {
                        { Text(stringResource(R.string.shell_ask_required)) }
                    } else {
                        null
                    },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    if (required && text.trim().length < 2) error = true else onConfirm(text)
                },
                colors = if (danger) ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error) else ButtonDefaults.textButtonColors(contentColor = mika.accent),
            ) { Text(confirm) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

// ── Le texte ────────────────────────────────────────────────────────────

private val URL = Regex("""\bhttps?://[^\s<>"']+""")

/** Un texte, ses adresses web en liens (sans la ponctuation qui les suit). */
internal fun linked(text: String, link: Color): AnnotatedString = buildAnnotatedString {
    var at = 0
    for (m in URL.findAll(text)) {
        val trail = Regex("""[.,;:!?)\]]+$""").find(m.value)?.value.orEmpty()
        val url = m.value.dropLast(trail.length)
        append(text.substring(at, m.range.first))
        withLink(LinkAnnotation.Url(url, TextLinkStyles(SpanStyle(color = link, textDecoration = TextDecoration.Underline)))) { append(url) }
        append(trail)
        at = m.range.last + 1
    }
    append(text.substring(at))
}

/** Un texte qui partira tel quel, chaque passage à compléter surligné (ambre, comme la maquette). */
@Composable
internal fun ToFillText(text: String, modifier: Modifier = Modifier) {
    val warn = states.warn
    val warnBg = states.warnContainer
    val shown = remember(text, warn, warnBg) {
        buildAnnotatedString {
            var at = 0
            for (r in toFillRanges(text)) {
                append(text.substring(at, r.first))
                withStyle(SpanStyle(background = warnBg, color = warn, fontWeight = FontWeight.Medium)) { append(text.substring(r.first, r.last + 1)) }
                at = r.last + 1
            }
            append(text.substring(at))
        }
    }
    Text(shown, style = MaterialTheme.typography.bodyLarge.copy(lineHeight = 21.sp), modifier = modifier)
}

/** Un espace vertical. */
@Composable
internal fun Gap(h: Dp) = Spacer(Modifier.height(h))
