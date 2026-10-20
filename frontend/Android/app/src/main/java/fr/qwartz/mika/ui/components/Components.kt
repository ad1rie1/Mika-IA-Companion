package fr.qwartz.mika.ui.components

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay

/** Le monogramme « M » de Mika : décoratif, son nom est écrit à côté. */
@Composable
fun MikaAvatar(size: Dp = 40.dp) {
    Surface(
        shape = CircleShape,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.size(size).clearAndSetSemantics { },
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text("M", color = MaterialTheme.colorScheme.onPrimary, style = MaterialTheme.typography.titleMedium)
        }
    }
}

/**
 * Le texte d'une réponse, mis en forme comme sur le web (`inlineMarkup.ts`) : gras, code en ligne,
 * blocs de code dans une surface à chasse fixe qui défile de côté. Jamais de HTML interprété.
 */
@Composable
fun InlineMarkupText(text: String, color: Color, modifier: Modifier = Modifier) {
    val blocks = remember(text) { InlineMarkup.parseBlocks(text) }
    val codeBackground = color.copy(alpha = 0.12f)
    Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        for (block in blocks) {
            when (block) {
                is InlineMarkup.Block.Text -> {
                    val body = InlineMarkup.trimAroundBlocks(block.text)
                    if (body.isNotEmpty()) Text(annotate(body, codeBackground), color = color)
                }
                is InlineMarkup.Block.Code -> Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = codeBackground,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        block.text,
                        color = color,
                        fontFamily = FontFamily.Monospace,
                        style = MaterialTheme.typography.bodySmall,
                        softWrap = false,
                        modifier = Modifier.horizontalScroll(rememberScrollState()).padding(8.dp),
                    )
                }
            }
        }
    }
}

fun annotate(text: String, codeBackground: Color): AnnotatedString = buildAnnotatedString {
    for (segment in InlineMarkup.parseInline(text)) {
        when (segment) {
            is InlineMarkup.Inline.Text -> append(segment.text)
            is InlineMarkup.Inline.Bold -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { append(segment.text) }
            is InlineMarkup.Inline.Code ->
                withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = codeBackground)) { append(segment.text) }
        }
    }
}

/** Une carte titrée ; le titre est un intitulé pour les lecteurs d'écran (on saute de carte en carte). */
@Composable
fun TitledCard(title: String, modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Card(modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.semantics { heading() })
            content()
        }
    }
}

/** L'heure murale, rafraîchie toutes les [intervalMs] : « il y a 3 min » avance tout seul. */
@Composable
fun rememberNow(intervalMs: Long = 30_000L, wallMs: () -> Long = System::currentTimeMillis): Long {
    var now by remember { mutableLongStateOf(wallMs()) }
    LaunchedEffect(intervalMs) {
        while (true) {
            now = wallMs()
            delay(intervalMs)
        }
    }
    return now
}
