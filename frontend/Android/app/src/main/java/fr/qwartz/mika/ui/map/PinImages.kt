package fr.qwartz.mika.ui.map

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import androidx.core.graphics.createBitmap
import fr.qwartz.mika.data.moi.carte.ScenePin
import kotlin.math.ceil

/**
 * Les couleurs que la carte prend du thème, lues au moment de la poser : l'indigo (ce que tu fais), le rose de Mika (ce
 * qu'elle a fait), le fond « relevé » (le bord blanc d'une épingle) et l'encre (l'anneau de l'épingle choisie).
 */
internal data class MapColors(val accent: Int, val onAccent: Int, val mika: Int, val onMika: Int, val raised: Int, val ink: Int)

/**
 * L'encre du numéro d'une épingle : la couleur faite pour aller **sur** son corps — sur le rose de Mika, la sienne
 * (`mika.onFill`) ; sinon celle de l'indigo (`onPrimary`). Jamais un blanc fixe : en thème sombre, l'indigo et le rose
 * sont clairs. La vraie carte et le plan dessiné la prennent tous deux.
 */
internal fun <C> pinInk(pin: ScenePin, onAccent: C, onMika: C): C = if (pin.mika) onMika else onAccent

/**
 * Les épingles de la carte, dessinées en images que MapLibre pose dans un calque de symboles (sans police : les numéros
 * se dessinent ici, la carte n'a pas besoin des glyphes du serveur pour eux). Leurs mesures sont celles du web
 * (`frontend/Web/src/styles/ecrans/carte.css`, `.cm-pin-el`) : 22 dp numérotée, 14 dp sans numéro, 30 et 20 dp choisie
 * (cerclée d'encre), 12 et 16 dp secondaire (un anneau indigo sur le fond).
 */
internal object PinImages {
    /** Le nom de l'image d'une épingle : une par sorte, par numéro et par jeu de couleurs (un autre thème, d'autres). */
    fun name(pin: ScenePin, colors: MapColors): String {
        val kind = when {
            pin.minor -> "minor"
            pin.mika -> "mika"
            else -> "toi"
        }
        val label = if (pin.minor) "" else pin.label.take(3)
        return "mika-pin-$kind-${if (pin.selected) "sel" else "n"}-${colors.hashCode()}-$label"
    }

    /** L'image d'une épingle, à la densité de l'écran ([density] : pixels par dp). */
    fun bitmap(pin: ScenePin, colors: MapColors, density: Float): Bitmap {
        val label = if (pin.minor) "" else pin.label.take(3)
        val diameterDp = when {
            pin.minor -> if (pin.selected) 16f else 12f
            label.isNotEmpty() -> if (pin.selected) 30f else 22f
            else -> if (pin.selected) 20f else 14f
        }
        val ringDp = if (pin.selected) (if (pin.minor) 2f else 3f) else 0f
        val borderDp = if (pin.minor) 2.5f else 2f
        val outerDp = diameterDp + 2 * ringDp + 2f // un pixel de marge autour, pour l'anticrénelage
        val size = ceil(outerDp * density).toInt().coerceAtLeast(2)
        val bitmap = createBitmap(size, size)
        val canvas = Canvas(bitmap)
        val c = size / 2f
        val r = diameterDp / 2 * density
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        if (ringDp > 0f) {
            paint.style = Paint.Style.FILL
            paint.color = colors.ink
            canvas.drawCircle(c, c, r + ringDp * density, paint)
        }
        // le corps, puis son bord : blanc (le fond relevé) autour d'une épingle pleine, indigo autour d'une secondaire
        paint.color = if (pin.minor) colors.accent else colors.raised
        canvas.drawCircle(c, c, r, paint)
        paint.color = when {
            pin.minor -> colors.raised
            pin.mika -> colors.mika
            else -> colors.accent
        }
        canvas.drawCircle(c, c, r - borderDp * density, paint)
        if (label.isNotEmpty()) {
            paint.color = pinInk(pin, colors.onAccent, colors.onMika)
            paint.typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
            paint.textAlign = Paint.Align.CENTER
            paint.textSize = (if (pin.selected) 12.5f else 11f) * density
            val baseline = c - (paint.descent() + paint.ascent()) / 2
            canvas.drawText(label, c, baseline, paint)
        }
        return bitmap
    }

    /** Une image vide et transparente, pour une icône que la planche n'a pas (le style la demande, MapLibre s'en plaint). */
    fun blank(): Bitmap = createBitmap(1, 1)
}
