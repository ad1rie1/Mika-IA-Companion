package fr.qwartz.mika.data.mind

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.db.ThreadStore
import fr.qwartz.mika.data.net.InnerState
import fr.qwartz.mika.data.net.ServerFrame
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Ce que l'app sait de son état (sommeil, lieu, humeur, pensées…), plié trame après trame et gardé
 * en base : rouverte hors ligne, l'app montre la dernière chose connue, datée.
 */
class MindStateRepository(private val store: ThreadStore, private val clock: Clock) {
    private val _state = MutableStateFlow<MindState?>(null)
    val state: StateFlow<MindState?> = _state.asStateFlow()

    suspend fun init() {
        _state.value = store.kvGet(Kv.MIND_STATE)?.let {
            try {
                MikaJson.decodeFromString(MindState.serializer(), it)
            } catch (_: IllegalArgumentException) {
                null
            }
        }
    }

    suspend fun onInnerState(state: InnerState) =
        save(InnerStateReducer.apply(_state.value ?: MindState(), state, clock.wallMs()))

    suspend fun onEmotion(f: ServerFrame.EmotionUpdate) = save(
        InnerStateReducer.applyMood(_state.value ?: MindState(), f.emotion, f.emotionIntensity, f.emotionBlend, clock.wallMs()),
    )

    /** Une parole porte aussi son émotion ; une pensée à voix haute, celle d'un instant, non. */
    suspend fun onSpeech(f: ServerFrame.Speech) {
        if (f.isInner || f.text.isEmpty()) return
        save(InnerStateReducer.applyMood(_state.value ?: MindState(), f.emotion, f.emotionIntensity, f.emotionBlend, clock.wallMs()))
    }

    fun reset() {
        _state.value = null
    }

    private suspend fun save(next: MindState) {
        if (next == _state.value) return
        _state.value = next
        store.kvPut(Kv.MIND_STATE, MikaJson.encodeToString(MindState.serializer(), next))
    }
}
