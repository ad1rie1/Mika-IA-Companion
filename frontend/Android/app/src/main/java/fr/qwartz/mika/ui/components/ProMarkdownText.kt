package fr.qwartz.mika.ui.components

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
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp

/**
 * Une réponse pro (ADR 0116) mise en forme : le Markdown de [ProMarkdown], bloc par bloc — titres en gras, listes
 * à marque suspendue, citations, blocs de code (et tableaux) dans une surface à chasse fixe qui défile de côté.
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
                ProMarkdown.Block.Rule -> HorizontalDivider(color = color.copy(alpha = 0.3f))
            }
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
