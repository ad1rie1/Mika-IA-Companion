package fr.qwartz.mika.ui.phone

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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.phone.PhoneCoords
import fr.qwartz.mika.data.moi.phone.distanceWords
import fr.qwartz.mika.data.moi.phone.planScale
import kotlin.math.ceil
import kotlin.math.min

/**
 * Le plan de ta position, dessiné (ADR 0119) : le point au milieu et le cercle de sa précision, à l'échelle (quelques
 * fois son rayon, 300 m au moins sur le côté le plus court, `planScale`), sur un quadrillage et sa barre d'échelle —
 * un plan, pas une carte : aucune rue, aucune rivière n'y est inventée. Sans coordonnées, le plan vide.
 *
 * C'est le repli de la vraie carte (`PositionMap` : MapLibre sur le fond que sert le serveur, ADR 0193) : sans fond
 * prêt, hors de sa zone, ou quand elle ne se dessine pas ici — [why] le dit alors dans sa note.
 */
@Composable
internal fun PositionPlan(coords: PhoneCoords?, accuracyM: Double, label: String, modifier: Modifier = Modifier, why: String? = null) {
    val scheme = MaterialTheme.colorScheme
    val measurer = rememberTextMeasurer()
    val scaleStyle = MaterialTheme.typography.labelSmall.copy(color = scheme.onSurfaceVariant)
    val described = if (coords != null) stringResource(R.string.phone_plan_around, label) else stringResource(R.string.phone_plan_empty)
    val background = scheme.surfaceContainerLow
    val grid = scheme.outlineVariant.copy(alpha = 0.55f)
    val accent = scheme.primary
    val ink = scheme.onSurfaceVariant
    Box(modifier) {
        Canvas(Modifier.fillMaxSize().semantics { contentDescription = described }) {
            drawRect(background)
            if (coords == null) return@Canvas
            val s = planScale(accuracyM, min(size.width, size.height))
            val c = center
            // le quadrillage, centré sur la position : un pas de la barre d'échelle
            val step = s.stepPx
            if (step > 4f) {
                val nx = ceil(size.width / 2 / step).toInt()
                val ny = ceil(size.height / 2 / step).toInt()
                for (i in -nx..nx) {
                    val x = c.x + i * step
                    drawLine(grid, Offset(x, 0f), Offset(x, size.height), strokeWidth = 1.dp.toPx())
                }
                for (j in -ny..ny) {
                    val y = c.y + j * step
                    drawLine(grid, Offset(0f, y), Offset(size.width, y), strokeWidth = 1.dp.toPx())
                }
            }
            // sa précision, puis le point
            if (s.radiusPx > 0f) {
                drawCircle(accent.copy(alpha = 0.14f), s.radiusPx, c)
                drawCircle(accent.copy(alpha = 0.6f), s.radiusPx, c, style = Stroke(1.5.dp.toPx()))
            }
            drawCircle(Color.White, 9.dp.toPx(), c)
            drawCircle(accent, 6.5.dp.toPx(), c)
            // la barre d'échelle, en bas à gauche
            val x0 = 16.dp.toPx()
            val y0 = size.height - 18.dp.toPx()
            val tick = 4.dp.toPx()
            val width = 2.dp.toPx()
            drawLine(ink, Offset(x0, y0), Offset(x0 + step, y0), strokeWidth = width)
            drawLine(ink, Offset(x0, y0 - tick), Offset(x0, y0 + tick), strokeWidth = width)
            drawLine(ink, Offset(x0 + step, y0 - tick), Offset(x0 + step, y0 + tick), strokeWidth = width)
            val text = measurer.measure(distanceWords(s.stepM.toDouble()), scaleStyle)
            drawText(text, topLeft = Offset(x0, y0 - tick - text.size.height - 2.dp.toPx()))
        }
        Text(
            if (why.isNullOrBlank()) stringResource(R.string.phone_plan_note) else stringResource(R.string.map_plan_note, why),
            style = MaterialTheme.typography.labelSmall,
            color = ink,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .padding(6.dp)
                .clip(RoundedCornerShape(6.dp))
                .background(scheme.surface.copy(alpha = 0.8f))
                .padding(horizontal = 6.dp, vertical = 2.dp),
        )
    }
}
