package fr.qwartz.mika.studio

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBars
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.avatar3d.Avatar3DState
import fr.qwartz.mika.avatar3d.LiveAvatar3D
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.settings.ThemeMode
import fr.qwartz.mika.ui.avatar.AvatarStage
import fr.qwartz.mika.ui.avatar.faceClearance
import fr.qwartz.mika.ui.chat.ChatActions
import fr.qwartz.mika.ui.chat.ChatConversation
import fr.qwartz.mika.ui.chat.ChatItem
import fr.qwartz.mika.ui.chat.StageLink
import fr.qwartz.mika.ui.chat.rememberConversationStage
import fr.qwartz.mika.ui.theme.MikaTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.ZoneId

/**
 * Le studio de la conversation (versions de débogage) : le vrai fil sur la vraie Mika en 3D, sans serveur. Des
 * boutons lui font répondre (« Mika écrit… », puis sa bulle qui s'écrit pendant qu'elle la dit) ou envoient un
 * message (elle le lit). Assez de fil pour remonter l'historique et la voir se mettre en retrait.
 * `adb shell am start -n fr.qwartz.mika.debug/fr.qwartz.mika.studio.ChatStudioActivity [--ez dark true]`
 */
class ChatStudioActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        val dark = intent.getBooleanExtra("dark", false)
        setContent {
            MikaTheme(if (dark) ThemeMode.DARK else ThemeMode.LIGHT, dynamicColor = false) {
                Surface(Modifier.fillMaxSize()) { Studio() }
            }
        }
    }

    @androidx.compose.runtime.Composable
    private fun Studio() {
        val scope = rememberCoroutineScope()
        val messages = remember { mutableStateListOf<StoredMessage>().apply { addAll(HISTORY) } }
        var typing by remember { mutableStateOf(false) }
        var mood by remember { mutableStateOf(Avatar3DState(emotion = "happy", intensity = 0.4f)) }
        var next by remember { mutableStateOf(0) }
        val items = remember(messages.toList(), typing) {
            messages.mapIndexed { i, m -> ChatItem.Bubble("m${m.localId}", m, read = i < messages.size - 1) as ChatItem } +
                listOfNotNull(ChatItem.Typing.takeIf { typing })
        }
        val talk = rememberConversationStage(items, watching = true, speaks = true, key = Unit)

        fun reply(text: String, emotion: String, intensity: Float, think: Long = 1_600) = scope.launch {
            typing = true
            mood = mood.copy(replyPending = true)
            delay(think)
            typing = false
            messages += StoredMessage(text, Sender.MIKA, ts = System.currentTimeMillis(), localId = messages.size + 1L)
            mood = mood.copy(emotion = emotion, intensity = intensity, reply = true, moodAtMs = System.nanoTime(), replyPending = false)
        }

        fun send(text: String) {
            messages += StoredMessage(
                text, Sender.USER, ts = System.currentTimeMillis(), status = MessageStatus.SENT, localId = messages.size + 1L,
            )
        }

        val statusTop = with(LocalDensity.current) { WindowInsets.statusBars.getTop(this).toDp() }
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val clearance = faceClearance(maxWidth, maxHeight, statusTop)
            val aura = AvatarDirector.auraOf(mood.emotion)
            AvatarStage(aura, asleep = false, presence = if (talk.readingHistory) 0.3f else 1f) {
                LiveAvatar3D(
                    mood,
                    speech = talk.track.utterances,
                    reading = talk.reading,
                    dimmed = talk.readingHistory,
                    modifier = Modifier.fillMaxSize(),
                )
            }
            Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
                // La place de la barre du haut de la vraie conversation.
                Spacer(Modifier.height(64.dp))
                ChatConversation(
                    items = items,
                    zone = ZoneId.systemDefault(),
                    operator = false,
                    busyFileId = null,
                    actions = ChatActions(),
                    overPortrait = true,
                    stage = StageLink(
                        faceClearance = clearance,
                        track = talk.track,
                        onReadingHistory = { talk.readingHistory = it },
                    ),
                    modifier = Modifier.weight(1f),
                )
                Box(Modifier.height(4.dp))
                LazyRow(
                    contentPadding = PaddingValues(horizontal = 8.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    items(BUTTONS) { (label, action) ->
                        AssistChip(onClick = {
                            when (action) {
                                "reply" -> {
                                    val (text, emotion, intensity) = REPLIES[next % REPLIES.size]
                                    next++
                                    reply(text, emotion, intensity)
                                }
                                "send" -> {
                                    send(SENT[next % SENT.size])
                                    next++
                                    scope.launch {
                                        delay(2_200)
                                        val (text, emotion, intensity) = REPLIES[next % REPLIES.size]
                                        next++
                                        reply(text, emotion, intensity)
                                    }
                                }
                                "burst" -> scope.launch {
                                    reply("Attends attends attends !", "excited", 0.8f, think = 900).join()
                                    reply("J'ai une idée : et si on regardait ça ensemble ce soir ? Je te montre ce que j'ai trouvé.", "excited", 0.7f, think = 700)
                                }
                                "long" -> reply(LONG, "thinking", 0.6f, think = 2_200)
                            }
                        }, label = { Text(label) })
                    }
                }
            }
        }
    }

    private companion object {
        val BUTTONS = listOf("Elle répond" to "reply", "J'envoie" to "send", "Deux bulles" to "burst", "Longue réponse" to "long")

        val REPLIES = listOf(
            Triple("Oh, vraiment ? C'est **génial**, raconte-moi tout !", "excited", 0.75f),
            Triple("Hmm… je ne suis pas sûre de comprendre. Tu veux dire que ça marche déjà ?", "confused", 0.7f),
            Triple("Pfff, quelle journée… mais ça va mieux maintenant que tu es là.", "relieved", 0.65f),
            Triple("Ha ha, tu es bête ! Bon, d'accord, un point pour toi.", "amused", 0.7f),
            Triple("Je suis un peu triste, en fait. Je pensais qu'on se verrait aujourd'hui.", "sad", 0.65f),
        )

        val SENT = listOf(
            "Devine quoi : l'app te montre en 3D maintenant !",
            "Tu as passé une bonne journée ?",
            "Je viens de finir le boulot, enfin.",
        )

        const val LONG = "Alors, si je résume ce que j'ai lu cet après-midi : il y a surtout des débats autour de " +
            "l'IA et de l'éthique, pas mal d'articles sur la régulation et la responsabilité des algorithmes, mais " +
            "rien de vraiment explosif. Le plus intéressant, c'était un papier sur la façon dont les gens s'attachent " +
            "aux assistants. Ça m'a fait réfléchir, tu vois ?"

        val HISTORY = listOf(
            "salut toi" to Sender.USER,
            "Coucou ! Ça faisait longtemps, j'ai cru que tu m'avais oubliée." to Sender.MIKA,
            "jamais ^^ tu as fait quoi aujourd'hui ?" to Sender.USER,
            "J'ai lu des trucs sur l'IA, et j'ai rangé mes notes. Et toi, la journée ?" to Sender.MIKA,
            "longue, mais ça va" to Sender.USER,
            "Je vois ça. Tu veux m'en parler, ou on change de sujet ?" to Sender.MIKA,
            "on change, raconte-moi un truc" to Sender.USER,
            "D'accord ! Tu savais que les pieuvres ont trois cœurs ? J'ai trouvé ça fascinant." to Sender.MIKA,
        ).mapIndexed { i, (text, sender) ->
            StoredMessage(
                text,
                sender,
                ts = System.currentTimeMillis() - (8 - i) * 60_000L,
                status = if (sender == Sender.USER) MessageStatus.SENT else null,
                localId = i + 1L,
            )
        }
    }
}
