package fr.qwartz.mika.data.files

import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.db.ThreadStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * La boîte aux lettres entre « Partager vers Mika » et la barre de saisie. Le partage y dépose, la
 * conversation y prend (et le fond dans son brouillon). Séparée du brouillon pour qu'une barre de
 * saisie ouverte n'écrase jamais, en enregistrant le sien, ce qu'un partage vient de déposer.
 * Gardée en base : un partage reçu hors session attend la connexion.
 */
class ShareInbox(private val store: ThreadStore) {
    private val lock = Mutex()
    private val _arrivals = MutableStateFlow(0L)
    /** Change à chaque dépôt : la conversation ouverte vient prendre. */
    val arrivals: StateFlow<Long> = _arrivals.asStateFlow()

    suspend fun deposit(shared: ComposerDraft) {
        if (shared.isEmpty && shared.notices.isEmpty()) return
        lock.withLock {
            val current = ComposerDraft.decode(store.kvGet(Kv.SHARED_INBOX))
            val merged = ComposerDraft(
                text = listOf(current.text, shared.text).filter { it.isNotBlank() }.joinToString("\n"),
                files = current.files + shared.files,
                notices = current.notices + shared.notices,
            )
            store.kvPut(Kv.SHARED_INBOX, merged.encode())
        }
        _arrivals.value += 1
    }

    /** Prendre tout ce qui attend (et vider la boîte) ; `null` s'il n'y a rien. */
    suspend fun take(): ComposerDraft? = lock.withLock {
        val raw = store.kvGet(Kv.SHARED_INBOX) ?: return@withLock null
        store.kvPut(Kv.SHARED_INBOX, null)
        ComposerDraft.decode(raw).takeIf { !it.isEmpty || it.notices.isNotEmpty() }
    }
}
