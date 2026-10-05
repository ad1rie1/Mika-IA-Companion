package fr.qwartz.mika.studio

import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.avatar3d.Avatar3D
import fr.qwartz.mika.avatar3d.AvatarController
import fr.qwartz.mika.avatar3d.AvatarRig
import fr.qwartz.mika.avatar3d.AvatarSurface
import fr.qwartz.mika.avatar3d.MotionLibrary
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.data.mind.MindLabels
import fr.qwartz.mika.data.settings.ThemeMode
import fr.qwartz.mika.ui.avatar.AvatarStage
import fr.qwartz.mika.ui.theme.MikaTheme
import kotlinx.coroutines.launch

/**
 * Le studio de l'avatar 3D natif (versions de débogage) : Mika rendue par Filament, sans serveur ni compte. Une
 * émotion « dite » (geste permis) ou « en dérive » (posture seulement), le sommeil, la fatigue.
 * `adb shell am start -n fr.qwartz.mika.debug/fr.qwartz.mika.studio.Avatar3DStudioActivity [--ez dark true]`
 */
class Avatar3DStudioActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val dark = intent.getBooleanExtra("dark", false)
        val library = MotionLibrary(this)
        setContent {
            MikaTheme(if (dark) ThemeMode.DARK else ThemeMode.LIGHT, dynamicColor = false) {
                Surface(Modifier.fillMaxSize()) {
                    val scope = rememberCoroutineScope()
                    var controller by remember { mutableStateOf<AvatarController?>(null) }
                    var emotion by remember { mutableStateOf("neutral") }
                    var drift by remember { mutableStateOf(false) }
                    var sleep by remember { mutableStateOf("awake") }
                    var tired by remember { mutableStateOf(false) }
                    val aura = if (sleep != "awake") AvatarDirector.Aura.NIGHT else AvatarDirector.auraOf(emotion)
                    Box(Modifier.fillMaxSize()) {
                        AvatarStage(aura, asleep = sleep != "awake") {
                            Avatar3D(Modifier.fillMaxSize()) { surface: AvatarSurface ->
                                surface.onReady = {
                                    scope.launch {
                                        val manifest = library.manifest() ?: return@launch Unit.also { Log.w(TAG, "pas de manifeste") }
                                        val t0 = System.nanoTime()
                                        val clips = library.loadAll(manifest)
                                        Log.i(TAG, "modèle en ${surface.loadMillis} ms ; ${clips.size} mouvements en ${(System.nanoTime() - t0) / 1_000_000} ms")
                                        val c = AvatarController(AvatarRig(surface.vrm!!), manifest, clips)
                                        c.start()
                                        controller = c
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
                                    }
                                }
                            }
                        }
                        Column(Modifier.fillMaxWidth().align(Alignment.BottomCenter).navigationBarsPadding()) {
                            Chips(listOf("dite", "dérive", "fatiguée", "awake", "light_sleep", "rem", "deep_sleep"), selected = {
                                (it == "dérive" && drift) || (it == "dite" && !drift) || (it == "fatiguée" && tired) || it == sleep
                            }) {
                                when (it) {
                                    "dite" -> drift = false
                                    "dérive" -> drift = true
                                    "fatiguée" -> {
                                        tired = !tired
                                        controller?.setEnergy(if (tired) 0.1f else 0.8f)
                                    }
                                    else -> {
                                        sleep = it
                                        controller?.setSleepPhase(it)
                                    }
                                }
                            }
                            Chips(MindLabels.EMOTIONS.keys.toList(), selected = { it == emotion }, label = { MindLabels.emotion(it) }) {
                                emotion = it
                                controller?.setEmotion(it, 0.9f, ambient = drift)
                            }
                        }
                    }
                }
            }
        }
    }

    private companion object {
        const val TAG = "Mika.Studio3D"
    }
}

@androidx.compose.runtime.Composable
private fun Chips(items: List<String>, selected: (String) -> Boolean, label: (String) -> String = { it }, onClick: (String) -> Unit) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        items(items) { i -> FilterChip(selected = selected(i), onClick = { onClick(i) }, label = { Text(label(i)) }) }
    }
}
