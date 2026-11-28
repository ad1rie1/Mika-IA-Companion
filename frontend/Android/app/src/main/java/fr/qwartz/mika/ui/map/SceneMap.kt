package fr.qwartz.mika.ui.map

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.calculateEndPadding
import androidx.compose.foundation.layout.calculateStartPadding
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.carte.CarteStyle
import fr.qwartz.mika.data.moi.carte.LiveFailure
import fr.qwartz.mika.data.moi.carte.MapFond
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.liveWanted
import fr.qwartz.mika.data.moi.carte.planWhy
import fr.qwartz.mika.ui.theme.mika

/**
 * Une carte d'un écran (ADR 0193, 0194, 0235) : la vraie — le fond servi par ce serveur, MapLibre, et la scène de
 * l'écran par-dessus — quand le fond est prêt, qu'il couvre ce que la scène montre et qu'elle ne s'est pas refusée ici ;
 * sinon le plan dessiné ([plan], par défaut [ScenePlan]) et sa note, qui dit pourquoi. Le même cycle de vie pour la
 * Carte et la Position du Téléphone (`frontend/Web/src/map/live.ts`) : ses tuiles en échec de suite, MapLibre qui ne se
 * charge pas ou un style qui ne se lit pas laissent le plan de **cette** carte ([refusal]), sans réessayer tant que
 * l'écran est là, jusqu'à un autre fond servi ; les autres cartes de la session n'en savent rien.
 *
 * [control] : la poignée de l'écran (cadrer, lire ce qu'elle montre) ; [insets] : ce que l'écran pose par-dessus (la
 * recherche, la feuille), que les cadrages évitent ; [needsHere] : la Position, sans laquelle rien ne se montre ;
 * [nested] : dans une page qui défile (une vue de texture plutôt qu'une surface ; le doigt reste à la carte si elle est
 * [interactive], sinon il va à la page — une miniature) ; [refusal] : ce qui ne s'est pas dessiné ici (par défaut, celui de
 * l'écran, oublié quand il s'en va ; une miniature passe le sien, gardé par sa liste).
 */
@Composable
internal fun SceneMap(
    graph: AppGraph,
    scene: Scene,
    title: String,
    modifier: Modifier = Modifier,
    control: MapControl = remember { MapControl() },
    interactive: Boolean = true,
    needsHere: Boolean = false,
    nested: Boolean = false,
    insets: PaddingValues = PaddingValues(),
    onPin: ((String) -> Unit)? = null,
    onMove: (() -> Unit)? = null,
    plan: (@Composable (why: String) -> Unit)? = null,
    refusal: LiveRefusal = remember { LiveRefusal() },
) {
    val fonds = rememberMapFond(graph)
    val fond = fonds.fond
    val failure = refusal.failure(fond)
    val live = fond != null && liveWanted(fond, scene, failure != null, needsHere)
    SideEffect { control.live = live }
    if (live && fond != null) {
        LiveMap(graph, fond, scene, title, control, interactive, nested, insets, onPin, onMove, modifier) { why -> refusal.fail(fond, why) }
    } else {
        val why = planWhy(fond, fonds.error, failure, here = needsHere)
        if (plan != null) plan(why) else ScenePlan(scene, title, why, modifier)
    }
}

/** La vraie carte : une vue MapLibre tenue le temps que l'écran la montre, son cycle de vie celui de l'écran. */
@Composable
private fun LiveMap(
    graph: AppGraph,
    fond: MapFond,
    scene: Scene,
    title: String,
    control: MapControl,
    interactive: Boolean,
    nested: Boolean,
    insets: PaddingValues,
    onPin: ((String) -> Unit)?,
    onMove: (() -> Unit)?,
    modifier: Modifier,
    onFail: (LiveFailure) -> Unit,
) {
    val context = LocalContext.current
    val density = LocalDensity.current
    val direction = LocalLayoutDirection.current
    val scheme = MaterialTheme.colorScheme
    val dark = scheme.surface.luminance() < 0.5f
    val colors = MapColors(
        accent = scheme.primary.toArgb(),
        onAccent = scheme.onPrimary.toArgb(),
        mika = mika.fill.toArgb(),
        onMika = mika.onFill.toArgb(),
        raised = scheme.surface.toArgb(),
        ink = scheme.onSurface.toArgb(),
    )
    val fail by rememberUpdatedState(onFail)
    val pin by rememberUpdatedState(onPin)
    val move by rememberUpdatedState(onMove)
    val base = graph.auth.credentials()?.base?.canonical
    val ready = remember { MapKit.install(context, graph) }
    if (base == null || !ready) {
        // MapLibre ne se charge pas sur ce téléphone (ou la session s'est fermée) : le plan, pour ce fond
        LaunchedEffect(Unit) { fail(LiveFailure.LOAD) }
        return
    }
    val view = remember { LiveMapHolder.create(context, scene, fond, interactive, nested) }
    if (view == null) {
        LaunchedEffect(Unit) { fail(LiveFailure.LOAD) }
        return
    }
    val holder = remember(view) {
        LiveMapHolder(view, interactive, density.density).also { h ->
            h.onPin = { id -> pin?.invoke(id) }
            h.onMove = { move?.invoke() }
            h.onFail = { why -> fail(why) }
            // une carte qui ne répond pas au doigt (une miniature) le laisse à la liste qui défile
            if (nested && interactive) LiveMapHolder.holdTouches(view)
            view.contentDescription = title
        }
    }
    // le cycle de vie de l'écran : la carte ne dessine rien quand il n'est plus au premier plan, et se rend en partant
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle, view) {
        var started = false
        var resumed = false
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> if (!started) { view.onStart(); started = true }
                Lifecycle.Event.ON_RESUME -> if (!resumed) { view.onResume(); resumed = true }
                Lifecycle.Event.ON_PAUSE -> if (resumed) { view.onPause(); resumed = false }
                Lifecycle.Event.ON_STOP -> if (started) { view.onStop(); started = false }
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        control.frameReader = { holder.frame() }
        onDispose {
            lifecycle.removeObserver(observer)
            control.frameReader = null
            if (resumed) view.onPause()
            if (started) view.onStop()
            view.onDestroy()
        }
    }
    // les calques du style, lus une fois par thème ; le style de ce fond sur ce serveur
    val layers by produceState<CarteStyle.Layers?>(null, dark, fond.kind) {
        value = if (fond.kind == MapFond.KIND_IMAGE) null else StyleAssets.load(context, dark)
    }
    val style = remember(fond, base, layers) { CarteStyle.build(fond, base, layers) }
    LaunchedEffect(style, fond, dark) {
        when {
            style != null -> holder.setStyle(style, fond)
            // un style vectoriel sans ses calques : l'asset ne se lit pas, la carte ne se dessinera pas
            fond.kind != MapFond.KIND_IMAGE && StyleAssets.load(context, dark) == null -> fail(LiveFailure.STYLE)
        }
    }
    val px = with(density) {
        MapInsets(
            left = insets.calculateStartPadding(direction).roundToPx(),
            top = insets.calculateTopPadding().roundToPx(),
            right = insets.calculateEndPadding(direction).roundToPx(),
            bottom = insets.calculateBottomPadding().roundToPx(),
        )
    }
    SideEffect {
        holder.insets = px
        holder.setColors(colors)
        holder.show(scene)
    }
    LaunchedEffect(holder, control.fitToken) {
        if (control.fitToken > 0) holder.fit(animate = true, orBase = control.fitOrBase)
    }
    LaunchedEffect(holder, control.focus) {
        control.focus?.let { holder.reveal(it.second) }
    }
    Box(modifier) {
        AndroidView(factory = { view }, modifier = Modifier.fillMaxSize())
    }
}
