package fr.qwartz.mika.ui.map

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.ScenePin
import fr.qwartz.mika.data.moi.carte.cleanScene
import fr.qwartz.mika.data.moi.carte.hereRadiusDeg
import fr.qwartz.mika.data.moi.carte.hereSpan
import fr.qwartz.mika.data.moi.carte.sceneBounds
import fr.qwartz.mika.ui.theme.mika
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.asinh
import kotlin.math.max
import kotlin.math.min
import kotlin.math.tan

private fun mx(lon: Double) = (lon + 180) / 360
private fun my(lat: Double): Double {
    val r = max(-85.0, min(85.0, lat)) * PI / 180
    return (1 - asinh(tan(r)) / PI) / 2
}

/**
 * Le plan dessiné d'une scène, sans tuile ni MapLibre (porté de `frontendv2/src/map/drawn.ts`) : ce que la Carte montre
 * sans fond servi, quand ses tuiles échouent ou que MapLibre ne se charge pas. Ses tracés, ses épingles (les
 * secondaires plus petites, sans numéro) et la position avec le cercle de sa précision, à leur place (Mercator), sur un
 * fond quadrillé — un plan, pas une carte : aucune rue n'y est inventée. [why] : pourquoi un plan (`planWhy`), dit
 * dans sa note ([note] faux : une miniature, sans note).
 */
@Composable
internal fun ScenePlan(raw: Scene, title: String, why: String, modifier: Modifier = Modifier, notePadding: Modifier = Modifier, note: Boolean = true) {
    val scene = cleanScene(raw)
    val scheme = MaterialTheme.colorScheme
    val accent = scheme.primary
    val onAccent = scheme.onPrimary
    val pink = mika.fill
    val onPink = mika.onFill
    val raised = scheme.surface
    val ink = scheme.onSurface
    val grid = scheme.outlineVariant.copy(alpha = 0.55f)
    val background = scheme.surfaceContainerLow
    val measurer = rememberTextMeasurer()
    val label = TextStyle(fontSize = 10.sp, fontWeight = FontWeight.Bold)
    Box(modifier) {
        Canvas(Modifier.fillMaxSize().semantics { contentDescription = title }) {
            drawRect(background)
            for (i in 1..7) {
                val x = size.width * i / 8
                drawLine(grid, Offset(x, 0f), Offset(x, size.height), strokeWidth = 1.dp.toPx())
            }
            for (j in 1..3) {
                val y = size.height * j / 4
                drawLine(grid, Offset(0f, y), Offset(size.width, y), strokeWidth = 1.dp.toPx())
            }
            val b = sceneBounds(scene, hereSpan(scene)) ?: return@Canvas
            val pad = 32.dp.toPx()
            val x0 = mx(b.west)
            val x1 = mx(b.east)
            val y0 = my(b.north)
            val y1 = my(b.south)
            val scale = min((size.width - 2 * pad) / max(1e-9, x1 - x0), (size.height - 2 * pad) / max(1e-9, y1 - y0))
            val ox = (size.width - (x1 - x0) * scale) / 2
            val oy = (size.height - (y1 - y0) * scale) / 2
            fun at(lat: Double, lon: Double) = Offset((ox + (mx(lon) - x0) * scale).toFloat(), (oy + (my(lat) - y0) * scale).toFloat())
            // sa précision, sous les tracés et les épingles
            scene.here?.let { h ->
                val dLat = hereRadiusDeg(h)
                if (dLat > 0) {
                    val c = at(h.lat, h.lon)
                    val r = abs(c.y - at(h.lat + dLat, h.lon).y)
                    drawCircle(accent.copy(alpha = 0.14f), r, c)
                    drawCircle(accent.copy(alpha = 0.5f), r, c, style = Stroke(1.5.dp.toPx()))
                }
            }
            for (line in scene.lines) {
                val path = Path()
                line.points.forEachIndexed { i, p ->
                    val o = at(p.lat, p.lon)
                    if (i == 0) path.moveTo(o.x, o.y) else path.lineTo(o.x, o.y)
                }
                val color = if (line.mika) pink else accent
                if (line.straight) {
                    drawPath(path, color.copy(alpha = 0.75f), style = Stroke(2.5.dp.toPx(), cap = StrokeCap.Round,
                        pathEffect = PathEffect.dashPathEffect(floatArrayOf(4.dp.toPx(), 6.dp.toPx()))))
                } else {
                    drawPath(path, raised.copy(alpha = 0.9f), style = Stroke(7.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
                    drawPath(path, color, style = Stroke(4.dp.toPx(), cap = StrokeCap.Round, join = StrokeJoin.Round))
                }
            }
            scene.here?.let { h ->
                val c = at(h.lat, h.lon)
                drawCircle(accent.copy(alpha = 0.18f), 12.dp.toPx(), c)
                drawCircle(raised, 8.5.dp.toPx(), c)
                drawCircle(accent, 5.5.dp.toPx(), c)
            }
            // les secondaires dessous, petites et sans numéro ; l'épingle choisie par-dessus tout
            val rank = { p: ScenePin -> if (p.selected) 2 else if (p.minor) 0 else 1 }
            for (p in scene.pins.sortedBy(rank)) {
                val c = at(p.lat, p.lon)
                val text = if (p.minor) "" else p.label.take(3)
                val r = when {
                    p.minor -> 4.5.dp.toPx()
                    text.isNotEmpty() -> 9.dp.toPx()
                    else -> 6.dp.toPx()
                } * (if (p.selected) 1.35f else 1f)
                if (p.selected) drawCircle(ink, r + 3.dp.toPx(), c)
                if (p.minor) {
                    drawCircle(accent, r, c)
                    drawCircle(raised, r - 2.dp.toPx(), c)
                } else {
                    drawCircle(raised, r, c)
                    drawCircle(if (p.mika) pink else accent, r - 2.dp.toPx(), c)
                }
                if (text.isNotEmpty()) {
                    val measured = measurer.measure(text, label.copy(color = pinInk(p, onAccent, onPink)))
                    drawText(measured, topLeft = Offset(c.x - measured.size.width / 2f, c.y - measured.size.height / 2f))
                }
            }
        }
        // une miniature n'a pas la place de sa note : la carte qui la porte dit ce qu'elle montre
        if (note) Text(
            stringResource(R.string.map_plan_note, why),
            style = MaterialTheme.typography.labelSmall,
            color = scheme.onSurfaceVariant,
            modifier = notePadding
                .align(Alignment.BottomEnd)
                .padding(6.dp)
                .clip(RoundedCornerShape(6.dp))
                .background(scheme.surface.copy(alpha = 0.85f))
                .padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}
