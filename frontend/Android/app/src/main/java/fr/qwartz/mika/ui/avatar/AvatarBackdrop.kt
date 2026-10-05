package fr.qwartz.mika.ui.avatar

import android.provider.Settings
import androidx.compose.animation.Crossfade
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.AnimationVector1D
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.State
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.FilterQuality
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.min
import androidx.compose.ui.unit.sp
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.data.avatar.AvatarDirector.Aura
import fr.qwartz.mika.data.avatar.BlinkSchedule
import kotlinx.coroutines.delay
import kotlin.math.PI
import kotlin.math.max
import kotlin.math.sin
import kotlin.random.Random

/** La barre du haut de la conversation : son portrait commence juste dessous. */
private val TOP_BAR_HEIGHT = 64.dp

/** Au-delà, elle ne grandit plus (tablette, paysage) : un portrait, pas une affiche. */
private val MAX_PORTRAIT_WIDTH = 560.dp

/** Le haut du rendu est vide (l'air au-dessus de son nœud) : on le glisse sous la barre. */
private const val HEADROOM = 0.045f

/** Où son corps commence à se fondre dans le fond, en fraction de la hauteur du portrait. */
private const val FADE_FROM = 0.58f

/**
 * Son menton, en fraction de la hauteur du cadre : 0,347 avec le cadrage de la 3D (les yeux à 1,19 m, le menton vers
 * 1,10 m, vus par l'objectif d'[fr.qwartz.mika.avatar3d.AvatarSurface.frame]) — et les portraits ont le même.
 */
private const val CHIN = 0.347f

/** Sous le menton, ce qu'on laisse encore à son visage avant qu'une bulle n'arrive pleinement. */
private val CHIN_MARGIN = 22.dp

/** Le cadre où elle se tient (gauche, haut, largeur, hauteur) : la tête juste sous la barre du haut. */
data class StageFrame(val left: Dp, val top: Dp, val width: Dp, val height: Dp)

fun stageFrame(maxWidth: Dp, maxHeight: Dp, statusTop: Dp, ratio: Float = 4f / 3f): StageFrame {
    val width = min(min(maxWidth, MAX_PORTRAIT_WIDTH), maxHeight * 0.95f / ratio)
    val height = width * ratio
    return StageFrame((maxWidth - width) / 2, statusTop + TOP_BAR_HEIGHT - height * HEADROOM, width, height)
}

/** Jusqu'où, en partant du haut de l'écran, son visage a besoin de place : le fil s'efface avant. */
fun faceClearance(maxWidth: Dp, maxHeight: Dp, statusTop: Dp): Dp {
    val frame = stageFrame(maxWidth, maxHeight, statusTop)
    return frame.top + frame.height * CHIN + CHIN_MARGIN
}

/**
 * Le portrait que l'écran attend, chargé hors du fil principal. Tant que le suivant n'est pas prêt,
 * le précédent reste : jamais de trou entre deux humeurs.
 */
@Composable
fun rememberPortrait(assets: AvatarAssets, id: String?): State<LoadedPortrait?> =
    produceState<LoadedPortrait?>(null, id) {
        if (id == null) return@produceState
        value = assets.load(id) ?: assets.load(AvatarDirector.NEUTRAL) ?: value
    }

/** « Supprimer les animations » d'Android : alors elle tient la pose, ni souffle, ni clignement. */
@Composable
fun rememberReducedMotion(): Boolean {
    val context = LocalContext.current
    return remember {
        Settings.Global.getFloat(context.contentResolver, Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
}

/** La lumière autour d'elle, par famille d'émotion ; claire en thème clair, profonde en sombre. */
fun auraColor(aura: Aura, dark: Boolean, neutral: Color): Color = when (aura) {
    Aura.WARM -> if (dark) Color(0xFF5E2F45) else Color(0xFFFFD3CC)
    Aura.COOL -> if (dark) Color(0xFF1F3459) else Color(0xFFC9D7F4)
    Aura.DUSK -> if (dark) Color(0xFF392E68) else Color(0xFFDDD1F8)
    Aura.NIGHT -> if (dark) Color(0xFF0D1330) else Color(0xFFC2C8E6)
    Aura.NEUTRAL -> neutral
}

/**
 * Mika derrière la conversation : son portrait du moment dans une lumière qui suit son humeur, qui
 * respire, cligne des yeux, change de pose en fondu, et dort la nuit (lumière bleue, étoiles, « z »).
 * Un décor : rien ici n'est lu par un lecteur d'écran, la ligne d'état dit déjà comment elle va.
 */
@Composable
fun AvatarBackdrop(
    scene: AvatarDirector.Scene,
    portrait: LoadedPortrait?,
    modifier: Modifier = Modifier,
) {
    val motion = !rememberReducedMotion()
    val scheme = MaterialTheme.colorScheme
    val dark = scheme.surface.luminance() < 0.5f
    val tint by animateColorAsState(
        auraColor(scene.aura, dark, scheme.primaryContainer),
        tween(if (motion) 1_200 else 0),
        label = "aura",
    )
    val night by animateFloatAsState(if (scene.asleep) 1f else 0f, tween(if (motion) 1_800 else 0), label = "night")
    val density = LocalDensity.current
    val statusTop = with(density) { WindowInsets.statusBars.getTop(this).toDp() }

    BoxWithConstraints(modifier.fillMaxSize().background(scheme.surface).clearAndSetSemantics { }) {
        val ratio = portrait?.let { it.height.toFloat() / it.width } ?: (4f / 3f)
        val (left, top, width, height) = stageFrame(maxWidth, maxHeight, statusTop, ratio)
        val faceX = portrait?.entry?.faceX ?: 0.5f
        val faceY = portrait?.entry?.faceY ?: 0.25f
        val face = with(density) { Offset((left + width * faceX).toPx(), (top + height * faceY).toPx()) }

        Aura(tint, face, with(density) { width.toPx() }, night, dark, motion)
        val living = rememberLiving(motion, scene.asleep, portrait?.id)
        Box(
            Modifier
                .offset(left, top)
                .size(width, height)
                .livingLayer(living),
        ) {
            Crossfade(
                portrait,
                animationSpec = tween(if (motion) 480 else 0),
                label = "portrait",
            ) { p -> if (p != null) Portrait(p, scene, motion, night) }
            if (scene.asleep && motion) SleepZ(faceX, faceY, dark)
        }
    }
}

/**
 * La même scène que [AvatarBackdrop] — la lumière de l'humeur, la nuit, les « z » — autour d'un autre contenu :
 * Mika en 3D native ([fr.qwartz.mika.avatar3d.Avatar3D]), qui porte elle-même son souffle et ses gestes. Le cadre
 * est celui des portraits (3:4, la tête juste sous la barre), le bas du corps fondu dans le fond, une ombre bleue
 * sur elle la nuit.
 */
@Composable
fun AvatarStage(
    aura: Aura,
    asleep: Boolean,
    modifier: Modifier = Modifier,
    faceX: Float = 0.5f,
    faceY: Float = 0.25f,
    /** 1 : elle est là, au premier plan ; vers 0 : elle s'efface derrière le fil qu'on relit. */
    presence: Float = 1f,
    content: @Composable () -> Unit,
) {
    val motion = !rememberReducedMotion()
    val scheme = MaterialTheme.colorScheme
    val dark = scheme.surface.luminance() < 0.5f
    val tint by animateColorAsState(auraColor(aura, dark, scheme.primaryContainer), tween(if (motion) 1_200 else 0), label = "aura")
    val night by animateFloatAsState(if (asleep) 1f else 0f, tween(if (motion) 1_800 else 0), label = "night")
    val density = LocalDensity.current
    val statusTop = with(density) { WindowInsets.statusBars.getTop(this).toDp() }

    val shown by animateFloatAsState(presence, tween(if (motion) 650 else 0), label = "presence")

    BoxWithConstraints(modifier.fillMaxSize().background(scheme.surface).clearAndSetSemantics { }) {
        val (left, top, width, height) = stageFrame(maxWidth, maxHeight, statusTop)
        val face = with(density) { Offset((left + width * faceX).toPx(), (top + height * faceY).toPx()) }
        Box(Modifier.fillMaxSize().graphicsLayer { alpha = 0.45f + 0.55f * shown }) {
            Aura(tint, face, with(density) { width.toPx() }, night, dark, motion)
        }
        Box(
            Modifier
                .offset(left, top)
                .size(width, height)
                .graphicsLayer {
                    compositingStrategy = CompositingStrategy.Offscreen
                    // En retrait pendant qu'on relit le fil : là, mais derrière le texte.
                    alpha = shown
                    val s = 0.96f + 0.04f * shown
                    scaleX = s
                    scaleY = s
                    transformOrigin = TransformOrigin(0.5f, 0.25f)
                }
                .drawWithContent {
                    drawContent()
                    if (night > 0f) drawRect(Color(0xFF141B3D).copy(alpha = 0.32f * night), blendMode = BlendMode.SrcAtop)
                    drawRect(Brush.verticalGradient(FADE_FROM to Color.Black, 0.97f to Color.Transparent), blendMode = BlendMode.DstIn)
                },
        ) {
            content()
        }
        if (asleep && motion) {
            Box(Modifier.offset(left, top).size(width, height)) { SleepZ(faceX, faceY, dark) }
        }
    }
}

/** Le fond : sa surface, une lumière ronde derrière son visage, et la nuit quand elle dort. */
@Composable
private fun Aura(tint: Color, face: Offset, portraitWidth: Float, night: Float, dark: Boolean, motion: Boolean) {
    val twinkle = if (motion && night > 0f) {
        rememberInfiniteTransition(label = "stars").animateFloat(
            0f, 1f, infiniteRepeatable(tween(5_000, easing = LinearEasing)), label = "twinkle",
        )
    } else {
        remember { mutableFloatStateOf(0.5f) }
    }
    val stars = remember { List(STAR_COUNT) { Star(Random(it * 7919 + 13)) } }
    Canvas(Modifier.fillMaxSize()) {
        drawRect(Brush.verticalGradient(0f to tint.copy(alpha = 0.55f), 0.7f to tint.copy(alpha = 0.18f), 1f to Color.Transparent))
        drawCircle(
            Brush.radialGradient(
                listOf(tint, tint.copy(alpha = 0.45f), Color.Transparent),
                center = face,
                radius = portraitWidth * 0.62f,
            ),
            radius = portraitWidth * 0.62f,
            center = face,
        )
        // Des étoiles, seulement sur un fond assez sombre pour qu'elles se voient.
        if (dark && night > 0f) {
            for (s in stars) {
                val glow = 0.35f + 0.65f * (0.5f + 0.5f * sin(2 * PI * (twinkle.value + s.phase)).toFloat())
                drawCircle(
                    Color.White.copy(alpha = night * glow * s.brightness),
                    radius = s.radius * density,
                    center = Offset(s.x * size.width, s.y * size.height * 0.6f),
                )
            }
        }
    }
}

private const val STAR_COUNT = 26

private class Star(random: Random) {
    val x = random.nextFloat()
    val y = random.nextFloat()
    val radius = 0.6f + random.nextFloat() * 1.2f
    val brightness = 0.4f + random.nextFloat() * 0.6f
    val phase = random.nextFloat()
}

/**
 * Le souffle (0 → 1 → 0), le balancement (−1 → 1 → −1) et l'élan d'un changement de pose
 * (≈ 0,96 → 1), avec leur ampleur.
 */
private class Living(
    val breath: State<Float>,
    val sway: State<Float>,
    val pop: Animatable<Float, AnimationVector1D>,
    val depth: Float,
    val swayDegrees: Float,
    val swayShiftPx: Float,
)

/**
 * Ce qui la fait vivre sans changer d'image : un souffle (le haut du corps monte d'une quinzaine de
 * pixels, plus lent et plus profond endormie), un balancement d'un appui sur l'autre sur un autre
 * rythme que le souffle (les deux ne retombent jamais ensemble, rien ne se répète à l'identique), et
 * un petit élan quand elle change de pose. Plus discret, sur un téléphone posé, il ne se voyait pas.
 */
@Composable
private fun rememberLiving(motion: Boolean, asleep: Boolean, portraitId: String?): Living {
    val still = remember { mutableFloatStateOf(0f) }
    val transition = if (motion) rememberInfiniteTransition(label = "living") else null
    val breath = transition?.animateFloat(
        0f, 1f,
        infiniteRepeatable(tween(if (asleep) 5_400 else 3_600, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "breath",
    ) ?: still
    val sway = transition?.animateFloat(
        -1f, 1f,
        infiniteRepeatable(tween(if (asleep) 9_000 else 6_700, easing = FastOutSlowInEasing), RepeatMode.Reverse),
        label = "sway",
    ) ?: still
    val pop = remember { Animatable(1f) }
    LaunchedEffect(portraitId) {
        if (motion && portraitId != null) {
            pop.snapTo(0.96f)
            pop.animateTo(1f, spring(dampingRatio = 0.45f, stiffness = 260f))
        }
    }
    val density = LocalDensity.current.density
    return Living(
        breath = breath,
        sway = sway,
        pop = pop,
        depth = if (asleep) 0.02f else 0.016f,
        swayDegrees = if (asleep) 0.5f else 1.1f,
        swayShiftPx = (if (asleep) 2f else 5f) * density,
    )
}

/**
 * Le souffle, le balancement et l'élan, lus au dessin seulement (rien ne se recompose à chaque
 * image) — pivot au bas du portrait, comme un corps debout. Puis le bas du corps fondu dans le fond
 * pour que la conversation passe par-dessus sans couture.
 */
private fun Modifier.livingLayer(living: Living): Modifier = this
    .graphicsLayer {
        val b = living.breath.value
        val s = living.sway.value
        val pop = living.pop.value
        scaleY = pop * (1f + living.depth * b)
        scaleX = pop * (1f + living.depth * 0.35f * b)
        rotationZ = living.swayDegrees * s
        translationX = living.swayShiftPx * s
        transformOrigin = TransformOrigin(0.5f, 1f)
        compositingStrategy = CompositingStrategy.Offscreen
    }
    .drawWithContent {
        drawContent()
        drawRect(
            Brush.verticalGradient(FADE_FROM to Color.Black, 0.97f to Color.Transparent),
            blendMode = BlendMode.DstIn,
        )
    }

/** Le portrait et, le temps d'un clignement, ses yeux fermés posés pile dessus. */
@Composable
private fun Portrait(p: LoadedPortrait, scene: AvatarDirector.Scene, motion: Boolean, night: Float) {
    var closed by remember { mutableStateOf(false) }
    val blinks = motion && !scene.asleep && p.blink != null
    val tired = scene.portrait == AvatarDirector.TIRED
    LaunchedEffect(blinks, tired) {
        closed = false
        if (!blinks) return@LaunchedEffect
        val random = Random(System.nanoTime())
        while (true) {
            delay(BlinkSchedule.nextGapMs(random, tired))
            closed = true
            delay(BlinkSchedule.CLOSED_MS)
            closed = false
            if (BlinkSchedule.isDouble(random)) {
                delay(BlinkSchedule.DOUBLE_GAP_MS)
                closed = true
                delay(BlinkSchedule.CLOSED_MS)
                closed = false
            }
        }
    }
    // La nuit, une ombre bleue sur elle (la lumière du fond s'éteint aussi).
    val shade = if (night > 0f) ColorFilter.tint(Color(0xFF141B3D).copy(alpha = 0.32f * night), BlendMode.SrcAtop) else null
    Canvas(Modifier.fillMaxSize()) {
        drawScaled(p.image, 0f, 0f, size.width, size.height, shade)
        val b = p.entry.blink
        if (closed && b != null && p.blink != null) {
            val sx = size.width / p.width
            val sy = size.height / p.height
            drawScaled(p.blink, b.x * sx, b.y * sy, b.w * sx, b.h * sy, shade)
        }
    }
}

/** Une image étirée sur un rectangle en flottants : pas d'arrondi au pixel, donc pas de décalage entre portrait et clignement. */
private fun DrawScope.drawScaled(
    image: ImageBitmap,
    x: Float,
    y: Float,
    w: Float,
    h: Float,
    filter: ColorFilter?,
) {
    withTransform({
        translate(x, y)
        scale(w / image.width, h / image.height, pivot = Offset.Zero)
    }) {
        drawImage(image, colorFilter = filter)
    }
}

/** Trois « z » qui montent de sa tête quand elle dort. */
@Composable
private fun SleepZ(faceX: Float, faceY: Float, dark: Boolean) {
    val measurer = rememberTextMeasurer()
    val t by rememberInfiniteTransition(label = "z").animateFloat(
        0f, 1f, infiniteRepeatable(tween(4_200, easing = LinearEasing)), label = "zt",
    )
    val color = if (dark) Color(0xFFE6E8FF) else Color(0xFF3B3F78)
    Canvas(Modifier.fillMaxSize()) {
        for (i in 0 until 3) {
            val phase = (t + i / 3f) % 1f
            val alpha = sin(PI * phase).toFloat()
            val style = TextStyle(
                color = color.copy(alpha = alpha * 0.85f),
                fontSize = (13 + 11 * phase).sp,
                fontWeight = FontWeight.SemiBold,
            )
            val text = measurer.measure("z", style)
            translate(
                left = size.width * (faceX + 0.09f + 0.07f * phase) + 6 * sin(phase * 7f) * density,
                top = size.height * (faceY - 0.05f - 0.16f * phase),
            ) {
                drawText(text)
            }
        }
    }
}

/**
 * Son visage dans un cercle, découpé dans le portrait du moment : l'avatar de la barre du haut change
 * d'expression avec elle.
 */
@Composable
fun AvatarFace(portrait: LoadedPortrait, background: Color, size: Dp = 40.dp) {
    Crossfade(portrait, animationSpec = tween(400), label = "face") { p ->
        Canvas(Modifier.size(size).clip(CircleShape).background(background).clearAndSetSemantics { }) {
            val img = p.image
            val side = FACE_CROP * img.width
            val cx = p.entry.faceX * img.width
            val cy = p.entry.faceY * img.height + FACE_DROP * img.height
            val left = (cx - side / 2).coerceIn(0f, max(0f, img.width - side))
            val topY = (cy - side / 2).coerceIn(0f, max(0f, img.height - side))
            drawImage(
                img,
                srcOffset = IntOffset(left.toInt(), topY.toInt()),
                srcSize = IntSize(side.toInt(), side.toInt()),
                dstSize = IntSize(this.size.width.toInt(), this.size.height.toInt()),
                filterQuality = FilterQuality.High,
            )
        }
    }
}

/** Le cadrage du visage dans le portrait : un carré d'un quart de la largeur, centré un peu sous les yeux. */
private const val FACE_CROP = 0.25f
private const val FACE_DROP = 0.025f
