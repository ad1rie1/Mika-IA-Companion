package fr.qwartz.mika.studio

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.data.avatar.AvatarDirector.Aura
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.mind.MindLabels
import fr.qwartz.mika.data.settings.ThemeMode
import fr.qwartz.mika.graph
import fr.qwartz.mika.ui.avatar.AvatarBackdrop
import fr.qwartz.mika.ui.avatar.auraColor
import fr.qwartz.mika.ui.avatar.rememberPortrait
import fr.qwartz.mika.ui.chat.ChatActions
import fr.qwartz.mika.ui.chat.ChatConversation
import fr.qwartz.mika.ui.chat.ChatItems
import fr.qwartz.mika.ui.chat.ChatTopBar
import fr.qwartz.mika.ui.theme.MikaTheme
import java.time.ZoneId

/**
 * Le studio de l'avatar, pour les versions de débogage : la conversation telle que l'app la dessine,
 * avec un faux fil et un sélecteur à la place de la barre de saisie — chaque portrait, le coucou, « Mika
 * écrit… », la fatigue, le sommeil. Sans serveur ni compte.
 *
 *     adb shell am start -n fr.qwartz.mika.debug/fr.qwartz.mika.studio.AvatarStudioActivity \
 *         --es portrait sad --ez dark true
 */
class AvatarStudioActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val start = intent.getStringExtra("portrait") ?: AvatarDirector.NEUTRAL
        val dark = intent.getBooleanExtra("dark", false)
        setContent {
            MikaTheme(if (dark) ThemeMode.DARK else ThemeMode.LIGHT, dynamicColor = false) {
                Surface(Modifier.fillMaxSize()) { Studio(graph, start) }
            }
        }
    }
}

/** La scène qu'on obtiendrait dans l'app pour ce portrait. */
private fun sceneOf(id: String): AvatarDirector.Scene = when (id) {
    AvatarDirector.SLEEP -> AvatarDirector.Scene(id, Aura.NIGHT, asleep = true)
    AvatarDirector.WAVE -> AvatarDirector.Scene(id, Aura.WARM)
    AvatarDirector.THINKING -> AvatarDirector.Scene(id, Aura.DUSK)
    AvatarDirector.TIRED -> AvatarDirector.Scene(id, Aura.NEUTRAL)
    else -> AvatarDirector.Scene(id, AvatarDirector.auraOf(id))
}

private fun statusOf(id: String): String = when (id) {
    AvatarDirector.SLEEP -> "endormie"
    AvatarDirector.WAVE -> "en ligne"
    AvatarDirector.THINKING -> "écrit…"
    AvatarDirector.TIRED -> "fatiguée"
    else -> MindLabels.emotionLower(id)
}

private fun sample(nowMs: Long, typing: Boolean, zone: ZoneId) = ChatItems.build(
    listOf(
        StoredMessage("Coucou Mika ! Tu as passé une bonne journée ?", Sender.USER, nowMs - 600_000, id = 1, status = MessageStatus.SENT),
        StoredMessage(
            "Plutôt oui ! J'ai fini de ranger mes carnets, et j'ai trouvé une **vieille photo** de nous deux.",
            Sender.MIKA, nowMs - 540_000, id = 2,
        ),
        StoredMessage("Ah oui ? Laquelle ?", Sender.USER, nowMs - 120_000, id = 3, status = MessageStatus.SENT),
        StoredMessage("Celle de la fête foraine, quand tu avais gagné la peluche. Je l'ai mise sur mon bureau.", Sender.MIKA, nowMs - 60_000, id = 4),
    ),
    typing = typing,
    nowMs = nowMs,
    zone = zone,
)

@Composable
private fun Studio(graph: AppGraph, start: String) {
    var id by rememberSaveable { mutableStateOf(start) }
    val ids by produceState(emptyList<String>()) { value = graph.avatar.manifest()?.ids?.toList().orEmpty() }
    val scene = sceneOf(id)
    val portrait by rememberPortrait(graph.avatar, scene.portrait)
    val zone = remember { ZoneId.systemDefault() }
    val items = remember(id) { sample(System.currentTimeMillis(), id == AvatarDirector.THINKING, zone) }
    val scheme = MaterialTheme.colorScheme
    val tint = auraColor(scene.aura, scheme.surface.luminance() < 0.5f, scheme.primaryContainer)
    Box(Modifier.fillMaxSize()) {
        AvatarBackdrop(scene, portrait)
        Scaffold(
            containerColor = Color.Transparent,
            topBar = { ChatTopBar(statusOf(id), {}, {}, face = portrait, faceTint = tint, transparent = true) },
            bottomBar = {
                Surface(tonalElevation = 2.dp) {
                    LazyRow(
                        Modifier.fillMaxWidth().navigationBarsPadding(),
                        contentPadding = PaddingValues(horizontal = 8.dp, vertical = 6.dp),
                        horizontalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        items(ids.sortedWith(compareBy({ it !in MindLabels.EMOTIONS }, { it }))) { p ->
                            FilterChip(
                                selected = p == id,
                                onClick = { id = p },
                                label = { Text(if (p in MindLabels.EMOTIONS) MindLabels.emotion(p) else p) },
                            )
                        }
                    }
                }
            },
        ) { padding ->
            ChatConversation(
                items = items,
                zone = zone,
                operator = false,
                busyFileId = null,
                actions = ChatActions(),
                overPortrait = true,
                modifier = Modifier.padding(padding).fillMaxSize(),
            )
        }
    }
}
