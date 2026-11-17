package fr.qwartz.mika.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance

/**
 * Le rose de Mika (ADR 0187, 0235) : ce qu'elle fait — ce qu'elle a lu, ce qu'elle propose, ce qu'elle a rédigé. Il
 * reste le même quand les couleurs dynamiques remplacent l'indigo : c'est un sens, pas un décor. Les valeurs sont
 * celles de la maquette (`frontend/Android/maquette/maquette.css`).
 */
data class MikaColors(
    /** Du texte, une icône. */
    val accent: Color,
    /** Un bouton plein, une pastille. */
    val fill: Color,
    val onFill: Color,
    /** Un fond de carte qui est à elle. */
    val container: Color,
    val onContainer: Color,
    /** Un fond très léger, et son filet. */
    val soft: Color,
    val line: Color,
)

private val Light = MikaColors(
    accent = Color(0xFFC8336A),
    fill = Color(0xFFDB3F76),
    onFill = Color.White,
    container = Color(0xFFFFD9E3),
    onContainer = Color(0xFF3E001D),
    soft = Color(0xFFFFF3F7),
    line = Color(0xFFF5C4D6),
)

private val Dark = MikaColors(
    accent = Color(0xFFFF8FB4),
    fill = Color(0xFFFF76A5),
    onFill = Color(0xFF3E001D),
    container = Color(0xFF6A2442),
    onContainer = Color(0xFFFFD9E3),
    soft = Color(0xFF2A1520),
    line = Color(0xFF5A2A40),
)

/** Ses couleurs, selon que le thème est clair ou sombre. */
val mika: MikaColors
    @Composable @ReadOnlyComposable
    get() = if (MaterialTheme.colorScheme.surface.luminance() < 0.5f) Dark else Light

/** Ce qui attend (un brouillon à décider), ce qui est fait : ambre et vert, comme dans la maquette. */
data class StateColors(val warn: Color, val warnContainer: Color, val ok: Color, val okContainer: Color)

val states: StateColors
    @Composable @ReadOnlyComposable
    get() = if (MaterialTheme.colorScheme.surface.luminance() < 0.5f) {
        StateColors(Color(0xFFF6BD5C), Color(0xFF3D2A05), Color(0xFF7AD99B), Color(0xFF12351F))
    } else {
        StateColors(Color(0xFF9A5A00), Color(0xFFFFE8C7), Color(0xFF1B7F3B), Color(0xFFD7F5DF))
    }
