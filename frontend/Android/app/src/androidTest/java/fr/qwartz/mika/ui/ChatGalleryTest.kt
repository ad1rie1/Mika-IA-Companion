package fr.qwartz.mika.ui

import android.graphics.Bitmap
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import fr.qwartz.mika.avatar3d.Avatar3DState
import fr.qwartz.mika.avatar3d.LiveAvatar3D
import fr.qwartz.mika.core.AndroidLogger
import fr.qwartz.mika.data.avatar.AvatarDirector.Aura
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.settings.ThemeMode
import fr.qwartz.mika.ui.avatar.AvatarAssets
import fr.qwartz.mika.ui.avatar.AvatarStage
import fr.qwartz.mika.ui.avatar.auraColor
import fr.qwartz.mika.ui.avatar.faceClearance
import fr.qwartz.mika.ui.avatar.rememberPortrait
import fr.qwartz.mika.ui.chat.ChatActions
import fr.qwartz.mika.ui.chat.ChatConversation
import fr.qwartz.mika.ui.chat.ChatItem
import fr.qwartz.mika.ui.chat.ChatItems
import fr.qwartz.mika.ui.chat.ChatTopBar
import fr.qwartz.mika.ui.chat.Composer
import fr.qwartz.mika.ui.chat.StageLink
import fr.qwartz.mika.ui.theme.MikaTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File
import java.time.LocalDateTime
import java.time.ZoneId

/** Jetable : des captures du fil sur Mika en 3D, pour juger la lisibilité. */
@RunWith(AndroidJUnit4::class)
class ChatGalleryTest {
    @get:Rule val rule = createComposeRule()
    private val zone = ZoneId.of("Europe/Paris")
    private val at = LocalDateTime.of(2026, 10, 18, 21, 4).atZone(zone).toInstant().toEpochMilli()

    private fun conversation(): List<StoredMessage> {
        var id = 0L
        fun user(text: String, min: Long) =
            StoredMessage(text, Sender.USER, at + min * 60_000L, id = ++id, localId = id, status = MessageStatus.SENT)
        fun mika(text: String, min: Long, verdict: String? = null) =
            StoredMessage(text, Sender.MIKA, at + min * 60_000L, id = ++id, localId = id, verdict = verdict)
        return listOf(
            user("coucou", -1440),
            mika("oh t'es là 😊\n\nj'étais justement en train de repenser à ton histoire de déménagement", -1439),
            user("ah ouais ? qu'est-ce que t'en penses", 0),
            mika("franchement je trouve que c'est une bonne idée, même si ça fait peur\n\nt'as déjà regardé les apparts du côté de la gare ?", 1, verdict = "ok"),
            user("pas encore, j'ai eu une grosse semaine au boulot", 2),
            mika("ah mince… c'était quoi le plus dur ?", 3),
            user("une mise en prod qui a tout cassé mercredi soir, on a fini à 2h du mat", 4),
            mika("aïe 😬 2h du mat c'est violent\n\nça va mieux depuis ou t'es encore sur les rotules ?", 5),
            user("ça va mieux. raconte moi ta journée plutôt", 6),
            user("t'as fait quoi ?", 6),
            mika("ma journée était calme. j'ai lu un article sur les pieuvres, apparemment elles rêvent, ça m'a obsédée tout l'après-midi\n\ntu crois qu'elles rêvent de quoi ?", 7),
        )
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    private fun Gallery(items: List<ChatItem>, operator: Boolean, input: String = "") {
        val context = LocalContext.current
        val assets = remember { AvatarAssets(context, AndroidLogger) }
        val portrait by rememberPortrait(assets, "happy")
        val statusTop = with(LocalDensity.current) { WindowInsets.statusBars.getTop(this).toDp() }
        val scheme = MaterialTheme.colorScheme
        var reading by remember { mutableStateOf(false) }
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val stage = StageLink(faceClearance(maxWidth, maxHeight, statusTop), track = null, onReadingHistory = { reading = it })
            AvatarStage(Aura.WARM, false, presence = if (reading) 0.3f else 1f) {
                LiveAvatar3D(Avatar3DState(), dimmed = reading, modifier = Modifier.fillMaxSize())
            }
            Scaffold(
                containerColor = Color.Transparent,
                topBar = {
                    ChatTopBar(
                        "En ligne · à son bureau",
                        {},
                        {},
                        face = portrait,
                        faceTint = auraColor(Aura.WARM, scheme.surface.luminance() < 0.5f, scheme.primaryContainer),
                        transparent = true,
                    )
                },
                bottomBar = {
                    Composer(
                        input = input,
                        onInput = {},
                        attachments = emptyList(),
                        notices = emptyList(),
                        staging = false,
                        canSend = input.isNotEmpty(),
                        onRemove = {},
                        onAttach = {},
                        onSend = {},
                        proAvailable = operator,
                    )
                },
            ) { padding ->
                Column(Modifier.fillMaxSize().padding(padding)) {
                    ChatConversation(
                        items,
                        zone,
                        operator,
                        null,
                        ChatActions(),
                        overPortrait = true,
                        stage = stage,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
    }

    private fun show(dark: Boolean, operator: Boolean, input: String = "", typing: Boolean = false) {
        val items = ChatItems.build(conversation(), typing = typing, nowMs = at + 8 * 60_000L, zone = zone)
        rule.setContent {
            MikaTheme(if (dark) ThemeMode.DARK else ThemeMode.LIGHT, dynamicColor = false) {
                Gallery(items, operator, input)
            }
        }
        settle()
    }

    private fun settle() {
        repeat(40) {
            rule.mainClock.advanceTimeBy(250)
            Thread.sleep(250)
        }
    }

    private fun shot(name: String) {
        val inst = InstrumentationRegistry.getInstrumentation()
        val bitmap = inst.uiAutomation.takeScreenshot()
        val dir = inst.targetContext.getExternalFilesDir(null)!!
        File(dir, "$name.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
    }

    @Test fun clairOperatrice() {
        show(dark = false, operator = true)
        shot("${tag()}-clair-operatrice")
    }

    @Test fun sombreOperatrice() {
        show(dark = true, operator = true, typing = true)
        shot("${tag()}-sombre-operatrice")
    }

    @Test fun clairSimple() {
        show(dark = false, operator = false, input = "je sais pas, peut-être de crabes")
        shot("${tag()}-clair-simple")
    }

    @Test fun historique() {
        show(dark = false, operator = true)
        rule.onRoot().performTouchInput { swipeDown(startY = centerY, endY = bottom - 10f) }
        settle()
        shot("${tag()}-historique")
    }

    private fun tag(): String =
        InstrumentationRegistry.getArguments().getString("tag") ?: "avant"
}
