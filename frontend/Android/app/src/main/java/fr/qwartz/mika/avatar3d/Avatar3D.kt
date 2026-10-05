package fr.qwartz.mika.avatar3d

import android.content.Context
import android.view.TextureView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.LifecycleResumeEffect
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Où l'app range le VRM préparé (`frontend/Android/tools/vrm_mobile.py`), s'il a été construit avec. */
const val AVATAR_GLB = "avatar3d/mika.glb"

/** Le GLB des assets, dans un tampon direct (ce que gltfio lit) ; `null` s'il n'y est pas. */
fun readAvatarGlb(context: Context): ByteBuffer? = try {
    context.assets.open(AVATAR_GLB).use { input ->
        val bytes = input.readBytes()
        ByteBuffer.allocateDirect(bytes.size).order(ByteOrder.nativeOrder()).put(bytes).also { it.flip() }
    }
} catch (_: IOException) {
    null
}

/**
 * La vue 3D de Mika. Le modèle se charge hors du fil principal ; l'image ne tourne que quand l'écran est au premier
 * plan (une vue cachée ne coûte rien). [onSurface] reçoit la surface une fois créée, pour y brancher l'animation.
 */
@Composable
fun Avatar3D(modifier: Modifier = Modifier, onSurface: (AvatarSurface) -> Unit = {}) {
    var surface by remember { mutableStateOf<AvatarSurface?>(null) }
    val scope = rememberCoroutineScope()
    AndroidView(
        factory = { ctx ->
            TextureView(ctx).also { tv ->
                val s = AvatarSurface(ctx, tv)
                surface = s
                onSurface(s)
                scope.launch {
                    val glb = withContext(Dispatchers.IO) { readAvatarGlb(ctx) } ?: return@launch
                    s.load(glb)
                }
            }
        },
        modifier = modifier,
    )
    LifecycleResumeEffect(surface) {
        surface?.start()
        onPauseOrDispose { surface?.stop() }
    }
    DisposableEffect(Unit) {
        onDispose { surface?.destroy() }
    }
}

/**
 * Mika vivante : la vue 3D, ses mouvements chargés une fois, et ce qu'elle ressent appliqué à chaque changement de
 * [state]. Une nouvelle parole (même à la même émotion) peut déclencher un geste ; une humeur qui dérive ne change
 * que la posture. `userTyping` augmente à chaque frappe de la personne.
 */
@Composable
fun LiveAvatar3D(state: Avatar3DState, wave: Boolean = false, userTyping: Int = 0, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val library = remember { MotionLibrary(context) }
    var controller by remember { mutableStateOf<AvatarController?>(null) }
    val scope = rememberCoroutineScope()
    Avatar3D(modifier) { surface ->
        surface.onReady = {
            scope.launch {
                val manifest = library.manifest() ?: return@launch
                val clips = library.loadAll(manifest)
                val c = AvatarController(AvatarRig(surface.vrm ?: return@launch), manifest, clips)
                c.start()
                var last = 0L
                surface.onFrame = { now ->
                    val dt = if (last == 0L) 0f else ((now - last) / 1e9f).coerceIn(0f, 0.1f)
                    last = now
                    c.setViewer(surface.cameraPosition())
                    c.frame(dt)
                    surface.applyLocals(c.rigLocals())
                    c.springs.forEachLocal { n, t, r -> surface.applyNode(n, t, r) }
                    surface.setMorphs(c.morphs())
                }
                controller = c
            }
        }
    }
    val c = controller
    LaunchedEffect(c, state.emotion, state.moodAtMs, state.intensity) {
        c?.setEmotion(state.emotion, state.intensity, state.blend, ambient = !state.reply)
    }
    LaunchedEffect(c, state.sleepPhase) { c?.setSleepPhase(state.sleepPhase) }
    LaunchedEffect(c, state.energy) { c?.setEnergy(state.energy) }
    LaunchedEffect(c, state.replyPending) { c?.setReplyPending(state.replyPending) }
    LaunchedEffect(c, wave) { if (wave) c?.wave() }
    // Chaque frappe dans la barre de saisie : elle se sait écoutée, son regard se pose sur la personne.
    LaunchedEffect(c, userTyping) { if (userTyping > 0) c?.noteUserTyping() }
}
