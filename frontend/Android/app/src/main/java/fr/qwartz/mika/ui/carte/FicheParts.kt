package fr.qwartz.mika.ui.carte

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withLink
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.carte.Fact
import fr.qwartz.mika.data.moi.carte.FicheTag
import fr.qwartz.mika.data.moi.carte.LinkText
import fr.qwartz.mika.data.moi.carte.StarFill
import fr.qwartz.mika.data.moi.carte.TagKind
import fr.qwartz.mika.data.moi.carte.factLink
import fr.qwartz.mika.data.moi.carte.factText
import fr.qwartz.mika.data.moi.carte.ratingWords
import fr.qwartz.mika.data.moi.carte.safeHref
import fr.qwartz.mika.data.moi.carte.starFills
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.theme.mika

/*
 * Les petites formes des fiches de la Carte (ADR 0259 ; la maquette `ecrans/carte-avis.js` et ses styles en fin de
 * `maquette.css`) : les étoiles d'une note, les étiquettes, des faits en lignes (« libellé : valeur » ; un numéro
 * s'appelle, un site s'ouvre), la ligne d'une source sous ce qu'elle dit (ses liens compris), le titre d'une partie, et
 * ce qui ouvre un lien du dehors dans le navigateur du téléphone — http ou https seulement ([Outside]).
 */

/** La couleur des étoiles d'une note (celle de Google), la même en clair et en sombre. */
internal val STAR = Color(0xFFF2B01E)

/**
 * Ce qui sort de l'app vers le dehors : une adresse web dans le navigateur du téléphone (http ou https seulement :
 * `safeHref` ; une autre ne s'ouvre pas), un numéro dans le composeur (jamais un appel lancé sans toi).
 */
internal class Outside(private val context: Context) {
    fun open(url: String?) {
        val href = safeHref(url) ?: return
        start(Intent(Intent.ACTION_VIEW, href.toUri()).addCategory(Intent.CATEGORY_BROWSABLE))
    }

    fun dial(tel: String?) {
        if (tel == null || !tel.startsWith("tel:")) return
        start(Intent(Intent.ACTION_DIAL, tel.toUri()))
    }

    /** Un fait : son numéro dans le composeur, son adresse web dans le navigateur. */
    fun fact(link: String) = if (link.startsWith("tel:")) dial(link) else open(link)

    private fun start(intent: Intent) {
        try {
            context.startActivity(intent)
        } catch (_: ActivityNotFoundException) {
            // rien pour l'ouvrir : le lien reste où il est
        }
    }
}

@Composable
internal fun rememberOutside(): Outside {
    val context = LocalContext.current
    return remember(context) { Outside(context) }
}

/** Cinq étoiles (pleines, à moitié, vides) ; un lecteur d'écran lit « 4,5 sur 5 ». */
@Composable
internal fun Stars(rating: Double?, modifier: Modifier = Modifier, size: Dp = 16.dp) {
    val said = "${ratingWords(rating)} sur 5"
    Row(modifier.clearAndSetSemantics { contentDescription = said }, horizontalArrangement = Arrangement.spacedBy(1.dp)) {
        for (fill in starFills(rating)) {
            Box(Modifier.size(size)) {
                MIcon(R.drawable.ic_m_star, null, size = size, tint = STAR)
                when (fill) {
                    StarFill.FULL -> MIcon(R.drawable.ic_m_star_fill, null, size = size, tint = STAR)
                    StarFill.HALF -> MIcon(
                        R.drawable.ic_m_star_fill,
                        null,
                        size = size,
                        tint = STAR,
                        modifier = Modifier.drawWithContent {
                            clipRect(right = this.size.width / 2) { this@drawWithContent.drawContent() }
                        },
                    )
                    StarFill.EMPTY -> Unit
                }
            }
        }
    }
}

/** L'icône d'une étiquette de fiche. */
@DrawableRes
private fun tagIcon(kind: TagKind): Int? = when (kind) {
    TagKind.OPEN -> R.drawable.ic_m_clock
    TagKind.WHEN -> R.drawable.ic_m_calendar
    TagKind.DISTANCE -> R.drawable.ic_m_pin
    else -> null
}

/** Les étiquettes d'une fiche : ouvert ou fermé à sa couleur, la cuisine, le prix, la note en étoiles. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun FicheTags(tags: List<FicheTag>, modifier: Modifier = Modifier) {
    if (tags.isEmpty()) return
    val scheme = MaterialTheme.colorScheme
    FlowRow(modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (t in tags) {
            if (t.kind == TagKind.RATING) {
                Row(
                    Modifier.heightIn(min = 22.dp).clip(RoundedCornerShape(6.dp)).background(scheme.surfaceContainerHigh)
                        .padding(horizontal = 8.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Stars(t.rating, size = 12.dp)
                    Spacer(Modifier.width(4.dp))
                    Text(t.text + (if (t.from.isNotEmpty()) " · ${t.from}" else ""), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant, maxLines = 1)
                }
            } else {
                Tag(t.text, t.tone, tagIcon(t.kind))
            }
        }
    }
}

/** Le titre d'une partie d'une fiche (`.list-head` de la maquette) ; [count] : combien, en petit. */
@Composable
internal fun FicheHead(text: String, modifier: Modifier = Modifier, count: Int? = null, pink: Boolean = false) {
    val scheme = MaterialTheme.colorScheme
    Row(modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            text,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.Medium,
            color = if (pink) mika.accent else scheme.primary,
        )
        if (count != null) {
            Spacer(Modifier.width(6.dp))
            Text(count.toString(), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
        }
    }
}

/**
 * Des faits en lignes (`.kv` de la maquette) : le libellé en gris, la valeur ; un numéro s'appelle, une adresse web
 * s'ouvre dehors (le reste n'ouvre rien).
 */
@Composable
internal fun FactRows(facts: List<Fact>, outside: Outside, modifier: Modifier = Modifier) {
    val scheme = MaterialTheme.colorScheme
    Column(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (f in facts) {
            val link = factLink(f)
            Row(Modifier.fillMaxWidth()) {
                Text(
                    f.label.trim(),
                    style = MaterialTheme.typography.bodyMedium,
                    color = scheme.onSurfaceVariant,
                    modifier = Modifier.width(104.dp).padding(end = 8.dp),
                )
                val value = factText(f)
                if (link != null) {
                    Text(
                        value,
                        style = MaterialTheme.typography.bodyMedium,
                        color = scheme.primary,
                        modifier = Modifier.weight(1f).clickable(role = Role.Button) { outside.fact(link) },
                    )
                } else {
                    Text(value, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                }
            }
        }
    }
}

/** Des morceaux de texte, chacun lié s'il a une adresse sûre, séparés par « · » ; un toucher ouvre le lien dehors. */
internal fun linkedParts(parts: List<LinkText>, link: Color, outside: Outside, separator: String = " · "): AnnotatedString =
    buildAnnotatedString {
        parts.filter { it.text.isNotBlank() }.forEachIndexed { i, p ->
            if (i > 0) append(separator)
            val url = p.url
            if (url != null) {
                withLink(LinkAnnotation.Clickable(url, TextLinkStyles(SpanStyle(color = link))) { outside.open(url) }) { append(p.text) }
            } else {
                append(p.text)
            }
        }
    }

/** Un texte qui ouvre un lien dehors s'il en a un (l'auteur d'un avis, d'une photo), sinon un texte. */
@Composable
internal fun LinkedText(part: LinkText, outside: Outside, style: TextStyle, color: Color, linkColor: Color, modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE) {
    val text = remember(part, linkColor) { linkedParts(listOf(part), linkColor, outside) }
    Text(text, style = style, color = color, maxLines = maxLines, modifier = modifier)
}

/**
 * La ligne d'une source, en petit, sous ce qu'elle dit (`.src-line` de la maquette) : « © les contributeurs
 * d'OpenStreetMap · extrait du 16 novembre · Corriger sur OpenStreetMap », ses liens ouverts dehors.
 */
@Composable
internal fun SourceLine(parts: List<LinkText>, outside: Outside, modifier: Modifier = Modifier, @DrawableRes icon: Int = R.drawable.ic_m_info) {
    val shown = parts.filter { it.text.isNotBlank() }
    if (shown.isEmpty()) return
    val scheme = MaterialTheme.colorScheme
    val text = remember(shown, scheme.primary) { linkedParts(shown, scheme.primary, outside) }
    Row(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        MIcon(icon, null, size = 13.dp, tint = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.labelSmall.copy(lineHeight = MaterialTheme.typography.labelSmall.fontSize * 1.4f), color = scheme.onSurfaceVariant)
    }
}
