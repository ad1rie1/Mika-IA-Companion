package fr.qwartz.mika.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Une réponse pro (ADR 0116) mise en forme : le Markdown de [ProMarkdown], bloc par bloc — titres en gras, listes
 * à marque suspendue, citations, tableaux, blocs de code dans une surface à chasse fixe ; ce qui est plus large que
 * la bulle (un bloc de code, un tableau) défile de côté.
 * Les liens http(s) s'ouvrent au toucher ; aucun autre n'est cliquable. Jamais de HTML interprété : rien que du texte.
 */
@Composable
fun ProMarkdownText(text: String, color: Color, modifier: Modifier = Modifier) {
    val blocks = remember(text) { ProMarkdown.parse(text) }
    val codeBackground = color.copy(alpha = 0.12f)
    val typography = MaterialTheme.typography
    Column(modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (block in blocks) {
            when (block) {
                is ProMarkdown.Block.Paragraph -> Text(proAnnotated(block.spans, codeBackground), color = color)
                is ProMarkdown.Block.Heading -> Text(
                    proAnnotated(block.spans, codeBackground),
                    color = color,
                    fontWeight = FontWeight.Bold,
                    style = if (block.level <= 2) typography.titleMedium else typography.titleSmall,
                )
                is ProMarkdown.Block.Item -> Row(Modifier.padding(start = 14.dp * block.depth)) {
                    Text(block.marker, color = color, modifier = Modifier.widthIn(min = 20.dp).padding(end = 4.dp))
                    Text(proAnnotated(block.spans, codeBackground), color = color)
                }
                is ProMarkdown.Block.Quote -> Row(Modifier.height(IntrinsicSize.Min)) {
                    Box(Modifier.width(3.dp).fillMaxHeight().background(color.copy(alpha = 0.4f)))
                    Text(
                        proAnnotated(block.spans, codeBackground),
                        color = color,
                        fontStyle = FontStyle.Italic,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                }
                is ProMarkdown.Block.Code -> Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = codeBackground,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        block.text,
                        color = color,
                        fontFamily = FontFamily.Monospace,
                        style = typography.bodySmall,
                        softWrap = false,
                        modifier = Modifier.horizontalScroll(rememberScrollState()).padding(8.dp),
                    )
                }
                is ProMarkdown.Block.Table -> TableBlock(block, color, codeBackground)
                ProMarkdown.Block.Rule -> HorizontalDivider(color = color.copy(alpha = 0.3f))
            }
        }
    }
}

/** Au-delà, une cellule passe à la ligne plutôt que d'élargir sa colonne. */
private val CELL_MAX_WIDTH = 220.dp
private val CELL_PADDING_H = 8.dp
private val CELL_PADDING_V = 4.dp

/**
 * Un tableau : chaque colonne à la largeur de sa plus longue cellule (plafonnée par [CELL_MAX_WIDTH]), les cellules
 * d'un rang à la même hauteur, l'en-tête en gras sur un fond ; plus large que la bulle, il défile de côté.
 */
@Composable
private fun TableBlock(table: ProMarkdown.Block.Table, color: Color, codeBackground: Color) {
    val style = MaterialTheme.typography.bodySmall
    val headerStyle = style.copy(fontWeight = FontWeight.Bold)
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val widths = remember(table, style, density) {
        table.align.indices.map { c ->
            val natural = (listOf(table.header[c] to headerStyle) + table.rows.map { it[c] to style }).maxOf { (spans, s) ->
                measurer.measure(proAnnotated(spans, codeBackground), s, softWrap = false).size.width
            }
            with(density) { natural.toDp() }.coerceAtMost(CELL_MAX_WIDTH) + CELL_PADDING_H * 2
        }
    }
    val rule = color.copy(alpha = 0.2f)
    Surface(
        shape = RoundedCornerShape(8.dp),
        color = Color.Transparent,
        border = BorderStroke(1.dp, rule),
    ) {
        Column(Modifier.horizontalScroll(rememberScrollState()).width(IntrinsicSize.Max)) {
            TableRow(table.header, table.align, widths, color, codeBackground, headerStyle, Modifier.background(codeBackground))
            for (row in table.rows) {
                HorizontalDivider(color = rule)
                TableRow(row, table.align, widths, color, codeBackground, style)
            }
        }
    }
}

@Composable
private fun TableRow(
    cells: List<List<ProMarkdown.Span>>,
    align: List<ProMarkdown.Align>,
    widths: List<Dp>,
    color: Color,
    codeBackground: Color,
    style: TextStyle,
    modifier: Modifier = Modifier,
) {
    Row(modifier.height(IntrinsicSize.Min)) {
        cells.forEachIndexed { c, spans ->
            Text(
                proAnnotated(spans, codeBackground),
                color = color,
                style = style,
                textAlign = when (align[c]) {
                    ProMarkdown.Align.START -> TextAlign.Start
                    ProMarkdown.Align.CENTER -> TextAlign.Center
                    ProMarkdown.Align.END -> TextAlign.End
                },
                modifier = Modifier.width(widths[c]).fillMaxHeight().padding(CELL_PADDING_H, CELL_PADDING_V),
            )
        }
    }
}

/** Les morceaux stylés d'un bloc ; un lien (toujours http(s), [ProMarkdown.isSafeUrl]) est souligné et s'ouvre. */
fun proAnnotated(spans: List<ProMarkdown.Span>, codeBackground: Color): AnnotatedString = buildAnnotatedString {
    for (s in spans) {
        val style = SpanStyle(
            fontWeight = if (s.bold) FontWeight.Bold else null,
            fontStyle = if (s.italic) FontStyle.Italic else null,
            fontFamily = if (s.code) FontFamily.Monospace else null,
            background = if (s.code) codeBackground else Color.Unspecified,
        )
        val url = s.url?.takeIf(ProMarkdown::isSafeUrl)
        if (url != null) {
            withLink(LinkAnnotation.Url(url, TextLinkStyles(SpanStyle(textDecoration = TextDecoration.Underline)))) {
                withStyle(style) { append(s.text) }
            }
        } else {
            withStyle(style) { append(s.text) }
        }
    }
}
