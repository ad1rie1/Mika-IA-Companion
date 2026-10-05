package fr.qwartz.mika.ui.chat

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import fr.qwartz.mika.avatar3d.ReadingCue
import fr.qwartz.mika.avatar3d.Utterance
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.ui.components.InlineMarkup

/**
 * Ce que le fil dit à Mika quand il bouge : une réponse d'elle qui arrive (elle la dit, [Cue.Speak]), un message de
 * la personne qui part (elle le lit, [Cue.Read]). Pur : le fil est comparé à celui de la fois d'avant.
 *
 * Seul ce qui arrive SOUS SES YEUX compte. Le premier fil vu (l'ouverture de l'écran, un rattrapage après une
 * coupure) n'est pas une conversation en cours : elle ne va pas réciter d'un coup ce qu'elle a écrit pendant qu'on
 * n'était pas là. Plusieurs bulles nouvelles d'un coup, c'est aussi un rattrapage.
 */
class ConversationCues {
    sealed interface Cue {
        val key: String

        /** Sa réponse vient d'arriver : elle la dit, et la bulle s'écrit à son rythme. */
        data class Speak(override val key: String, val text: String) : Cue

        /** La personne vient d'envoyer : elle lit, puis hoche la tête. */
        data class Read(override val key: String, val chars: Int) : Cue
    }

    private var primed = false
    private val known = HashSet<String>()

    /**
     * Le fil a changé ; `watching` : l'écran est au premier plan. Rend le signal à donner, ou null. Les bulles vues
     * pendant qu'on ne regardait pas sont notées sans signal.
     */
    fun onItems(items: List<ChatItem>, watching: Boolean): Cue? {
        val bubbles = items.filterIsInstance<ChatItem.Bubble>()
        val fresh = bubbles.filter { it.key !in known }
        bubbles.forEach { known.add(it.key) }
        if (!primed) {
            primed = true
            return null
        }
        if (!watching || fresh.size != 1) return null
        val bubble = fresh.single()
        if (bubble !== bubbles.last()) return null
        val m = bubble.message
        val body = InlineMarkup.plain(BubbleContent.text(m))
        return when (m.sender) {
            Sender.MIKA -> if (body.isBlank()) null else Cue.Speak(bubble.key, body)
            Sender.USER -> Cue.Read(bubble.key, body.length + 12 * m.attachments.size)
        }
    }

    companion object {
        /**
         * Le temps de lire un message (s) : un coup d'œil pour trois mots, quelques secondes pour un paragraphe — on
         * lit plus vite qu'on ne parle, et elle n'a pas à tout lire avant de répondre.
         */
        fun readingSeconds(chars: Int): Float = (0.9f + chars * 0.035f).coerceIn(1.1f, 3.5f)
    }
}

/**
 * Les répliques qu'elle dit, dans l'ordre : deux bulles qui arrivent coup sur coup se disent l'une après l'autre, pas
 * en même temps. L'état est observable (Compose) : la bulle qui s'écrit et l'avatar lisent la même liste.
 */
class SpeechTrack(private val clock: () -> Long = System::nanoTime) {
    var utterances: List<Utterance> by mutableStateOf(emptyList())
        private set

    /** Elle dit `text` (la bulle `key`) : maintenant, ou juste après la réplique en cours. */
    fun say(key: String, text: String) {
        val now = clock()
        val live = utterances.filter { !it.finished(now - KEEP_NANOS) }
        val after = live.maxOfOrNull { it.endNanos }?.let { it + Utterance.GAP_NANOS } ?: now
        live.filter { it.key != key }.let { kept ->
            utterances = kept + Utterance(key, text, maxOf(now, after), Utterance.charsPerSecond(text.length))
        }
    }

    /** La personne a touché la bulle : tout s'affiche, elle se tait — et ce qui attendait derrière vient aussitôt. */
    fun skip(key: String) {
        val now = clock()
        var shift = 0L
        utterances = utterances.map { u ->
            when {
                u.key == key && !u.finished(now) -> {
                    shift = maxOf(0L, u.endNanos - now)
                    u.copy(skippedAtNanos = now)
                }
                shift > 0L && u.startNanos > now -> u.copy(startNanos = maxOf(now, u.startNanos - shift))
                else -> u
            }
        }
    }

    /** Tout ce qui reste à dire s'affiche d'un coup (la personne écrit à son tour). */
    fun skipAll() {
        val now = clock()
        utterances = utterances.map { if (it.finished(now)) it else it.copy(skippedAtNanos = now) }
    }

    /** La réplique d'une bulle, tant qu'elle n'est pas finie depuis longtemps. */
    fun of(key: String): Utterance? = utterances.firstOrNull { it.key == key }

    private companion object {
        /** On garde une réplique finie un moment : la bulle a besoin de savoir qu'elle a fini de s'écrire. */
        const val KEEP_NANOS = 2_000_000_000L
    }
}

/** Ce que le fil donne à Mika, gardé par l'écran : ce qu'elle dit, ce qu'elle lit, et si l'on relit l'historique. */
class ConversationStage {
    val cues = ConversationCues()
    val track = SpeechTrack()

    /** Le dernier message qu'elle lit (un nouveau à chaque envoi). */
    var reading: ReadingCue? by mutableStateOf(null)
        internal set

    /** On a remonté le fil : elle se met en retrait. */
    var readingHistory: Boolean by mutableStateOf(false)

    /** Le fil a changé : sa réponse qui arrive, elle la dit (si elle a une bouche) ; un message qui part, elle le lit. */
    fun onItems(items: List<ChatItem>, watching: Boolean, speaks: Boolean) {
        when (val cue = cues.onItems(items, watching)) {
            is ConversationCues.Cue.Speak -> if (speaks) track.say(cue.key, cue.text)
            is ConversationCues.Cue.Read -> {
                // Elle se tait pour lire : ce qu'elle disait s'affiche d'un coup.
                track.skipAll()
                reading = ReadingCue(cue.key, ConversationCues.readingSeconds(cue.chars))
            }
            null -> Unit
        }
    }
}

/** Le [ConversationStage] d'un fil (`key` : le compte ; un autre compte, une autre conversation), nourri à chaque changement. */
@Composable
fun rememberConversationStage(items: List<ChatItem>, watching: Boolean, speaks: Boolean, key: Any?): ConversationStage {
    val stage = remember(key) { ConversationStage() }
    val isWatching by rememberUpdatedState(watching)
    LaunchedEffect(stage, items) { stage.onItems(items, isWatching, speaks) }
    return stage
}
