package fr.qwartz.mika.ui.chat

import android.net.Uri
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.core.content.FileProvider
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.approvals.Approvals
import fr.qwartz.mika.data.approvals.ApprovalView
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.data.chat.ChatRepository
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.files.StagedFile
import fr.qwartz.mika.data.mind.StatusLine
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.data.net.LinkState
import fr.qwartz.mika.data.net.MikaProtocol
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * La conversation vue de l'écran : le fil, la ligne d'état, la barre de saisie et ses pièces jointes
 * (brouillon gardé en base), l'appareil photo (son fichier noté dans le [SavedStateHandle] : l'app
 * peut mourir pendant la prise de vue), les partages reçus.
 */
class ChatViewModel(private val graph: AppGraph, private val saved: SavedStateHandle) : ViewModel() {
    val zone: ZoneId = ZoneId.systemDefault()

    val items: StateFlow<List<ChatItem>> = combine(
        graph.chat.observe(),
        graph.chatEngine.ephemeral,
        graph.chatEngine.truncated,
        graph.chatEngine.typing,
    ) { messages, ephemeral, truncated, typing ->
        ChatItems.build(messages, ephemeral, truncated, typing, graph.clock.wallMs(), zone)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /** Une seconde : le compte à rebours de « nouvel essai dans N s ». */
    private val tick = flow {
        while (true) {
            emit(Unit)
            delay(1_000)
        }
    }

    val status: StateFlow<String> = combine(
        graph.connection.link,
        graph.chatEngine.typing,
        graph.mind.state,
        tick,
    ) { link, typing, mind, _ ->
        StatusLine.of(link, typing, mind, graph.clock.elapsedMs())
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), "")

    val link: StateFlow<LinkState> = graph.connection.link

    /**
     * Les cartes d'accord à dessiner ([Approvals.view]), recalculées quand le temps change ce qu'elles
     * disent : le compte à rebours (toutes les 30 s, et à l'échéance), une décision restée sans réponse.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    val approvals: StateFlow<List<ApprovalView>> = combine(graph.approvals.state, graph.connection.link) { state, link ->
        state to (link == LinkState.Online)
    }.flatMapLatest { (state, online) ->
        flow {
            while (true) {
                val wall = graph.clock.wallMs()
                val elapsed = graph.clock.elapsedMs()
                emit(Approvals.views(state, online, wall, elapsed))
                if (state.cards.isEmpty()) break
                delay(Approvals.nextTickMs(state, wall, elapsed))
            }
        }
    }.distinctUntilChanged().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    /** Le sort d'une décision, à dire une fois (un Snackbar). */
    val approvalMessages: SharedFlow<String> = graph.approvals.messages

    /** Le salut de retrouvailles, le temps d'un geste (voir [onShown]). */
    private val greeting = MutableStateFlow(false)
    /** Quand on l'a quittée (ou vue arriver, la première fois) : l'horloge des retrouvailles. */
    private var lastSeenMs: Long? = null

    /**
     * Son portrait du moment ([AvatarDirector]) : `null` quand l'avatar est coupé dans les paramètres
     * ou que l'app a été construite sans portraits.
     */
    val avatar: StateFlow<AvatarDirector.Scene?> = combine(
        graph.settings.settings.map { it.avatar }.distinctUntilChanged(),
        flow { emit(graph.avatar.manifest()?.ids) },
        graph.mind.state,
        graph.chatEngine.typing,
        greeting,
    ) { on, ids, mind, typing, greet ->
        if (!on || ids == null) null else AvatarDirector.scene(mind, typing, greet, ids)
    }.distinctUntilChanged().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    /** Une opératrice voit le lien « ouvrir la console » sous une réponse ratée. */
    val operator: StateFlow<Boolean> = graph.auth.session
        .map { (it as? Session.LoggedIn)?.profile?.operator == true }
        .stateIn(viewModelScope, SharingStarted.Eagerly, false)

    val notificationsAsked: StateFlow<Boolean> = graph.settings.settings
        .map { it.notificationsAsked }
        .stateIn(viewModelScope, SharingStarted.Eagerly, true)

    var input by mutableStateOf("")
        private set
    val attachments = mutableStateListOf<StagedFile>()
    var notices by mutableStateOf<List<String>>(emptyList())
        private set
    /** Des fichiers sont en train d'être copiés ou réduits. */
    var staging by mutableStateOf(false)
        private set

    val canSend: Boolean get() = !staging && (input.isNotBlank() || attachments.isNotEmpty())

    private var restored = false

    init {
        // Ce modèle appartient à l'activité et survit à l'écran : session fermée, il oublie ce qui était
        // tapé et ne prend plus rien (un partage fait ensuite est pour la session suivante) ; rouverte
        // sur le même compte, il reprend le brouillon gardé.
        viewModelScope.launch {
            graph.auth.session
                .map { it is Session.LoggedIn }
                .distinctUntilChanged()
                .collectLatest { open -> if (open) runComposer() else closeComposer() }
        }
    }

    private suspend fun runComposer() = coroutineScope {
        val draft = ComposerDraft.decode(graph.store.kvGet(Kv.DRAFT))
        val present = withContext(Dispatchers.IO) { draft.files.filter { File(it.path).isFile } }
        if (input.isEmpty()) input = draft.text
        if (attachments.isEmpty()) attachments.addAll(present)
        restored = true
        // Ce qui attendait d'abord, puis seulement le ménage : un partage reçu hors session dort dans
        // la préparation depuis peut-être des heures, il ne doit pas passer pour un oubli.
        takeShared()
        withContext(Dispatchers.IO) {
            graph.files.pruneStaging(attachments.mapTo(HashSet()) { it.path }, graph.clock.wallMs())
        }
        // Ce qu'un partage dépose pendant que l'écran est ouvert.
        launch { graph.shareInbox.arrivals.collect { takeShared() } }
        saveDraftContinuously()
    }

    private fun closeComposer() {
        restored = false
        input = ""
        attachments.clear()
        notices = emptyList()
    }

    @OptIn(FlowPreview::class)
    private suspend fun saveDraftContinuously() {
        snapshotFlow { input to attachments.toList() }
            .drop(1)
            .debounce(DRAFT_DEBOUNCE_MS)
            .collect { saveDraft() }
    }

    private suspend fun saveDraft() {
        if (!restored) return
        val draft = ComposerDraft(input, attachments.toList())
        graph.store.kvPut(Kv.DRAFT, if (draft.isEmpty) null else draft.encode())
    }

    private suspend fun takeShared() {
        val shared = graph.shareInbox.take() ?: return
        val merge = ComposerDraft(input, attachments.toList()).merge(shared)
        input = merge.draft.text
        attachments.clear()
        attachments.addAll(merge.draft.files)
        notices = merge.notices
        withContext(Dispatchers.IO) { merge.dropped.forEach { graph.files.discardStaged(it.path) } }
        saveDraft()
    }

    fun onInput(text: String) {
        input = text.take(MikaProtocol.MAX_MESSAGE_CHARS)
    }

    fun addUris(uris: List<Uri>) = stage(uris, fromCamera = false, displayName = null)

    fun remove(file: StagedFile) {
        attachments.remove(file)
        notices = emptyList()
        viewModelScope.launch(Dispatchers.IO) { graph.files.discardStaged(file.path) }
    }

    fun dismissNotices() {
        notices = emptyList()
    }

    private fun stage(uris: List<Uri>, fromCamera: Boolean, displayName: String?, after: () -> Unit = {}) {
        if (uris.isEmpty()) return
        staging = true
        viewModelScope.launch {
            try {
                val result = graph.stager.stage(uris, attachments.toList(), fromCamera, displayName)
                attachments.addAll(result.files)
                notices = result.notices
            } finally {
                staging = false
                after()
            }
        }
    }

    /**
     * Où l'appareil photo écrira : un fichier de `cacheDir/camera`, exposé par notre FileProvider (pas
     * de permission CAMERA : c'est l'application photo qui prend la photo). Son chemin survit à la mort
     * du processus pendant la prise de vue.
     */
    fun cameraTarget(): Uri? = try {
        val dir = graph.cameraDir.apply { mkdirs() }
        val file = File.createTempFile("photo-", ".jpg", dir)
        saved[KEY_CAMERA] = file.absolutePath
        FileProvider.getUriForFile(graph.context, "${graph.context.packageName}.files", file)
    } catch (_: java.io.IOException) {
        null
    } catch (_: IllegalArgumentException) {
        null
    }

    fun onCameraResult(taken: Boolean) {
        val path = saved.get<String>(KEY_CAMERA) ?: return
        saved.remove<String>(KEY_CAMERA)
        val file = File(path)
        if (!taken || !file.isFile || file.length() == 0L) {
            file.delete()
            return
        }
        val name = "photo-" + PHOTO_NAME.format(java.time.LocalDateTime.now()) + ".jpg"
        stage(listOf(Uri.fromFile(file)), fromCamera = true, displayName = name) { file.delete() }
    }

    fun send() {
        val text = input.trim()
        val files = attachments.toList()
        if (!canSend) return
        input = ""
        attachments.clear()
        notices = emptyList()
        viewModelScope.launch {
            val result = graph.chat.send(text, files)
            if (result is ChatRepository.SendResult.Rejected) {
                // Rien n'est parti : tout revient dans la barre de saisie, avec la raison.
                notices = listOf(result.reason)
                if (input.isEmpty()) input = text
                if (attachments.isEmpty()) attachments.addAll(files)
            }
            saveDraft()
        }
    }

    fun retry(localId: Long) {
        viewModelScope.launch { graph.chat.retry(localId) }
    }

    /**
     * « Accepter » ou « Refuser » une carte, avec l'empreinte de la carte telle qu'elle est montrée.
     * Seul ce bouton décide : un « oui » tapé dans la conversation n'est jamais un accord.
     */
    fun decide(card: ApprovalView, decision: ApprovalDecision) {
        val allowed = if (decision == ApprovalDecision.ACCEPT) card.canAccept else card.canRefuse
        if (!allowed) return
        viewModelScope.launch {
            if (!graph.connection.decide(card.id, decision, card.digest)) graph.approvals.say(Approvals.NOT_SENT)
        }
    }

    /**
     * L'écran revient au premier plan : quand on la retrouve après un moment (ou pour la première fois
     * depuis le lancement), elle fait coucou de la main, le temps d'un geste.
     */
    fun onShown() {
        val now = graph.clock.elapsedMs()
        val last = lastSeenMs
        lastSeenMs = now
        if (last != null && now - last < GREETING_GAP_MS) return
        greeting.value = true
        viewModelScope.launch {
            delay(GREETING_MS)
            greeting.value = false
        }
    }

    /** L'écran passe à l'arrière-plan : c'est de là que se compte l'absence. */
    fun onHidden() {
        lastSeenMs = graph.clock.elapsedMs()
    }

    /** La conversation est à l'écran : tout est lu, et la notification n'a plus rien à dire. */
    fun markRead() {
        viewModelScope.launch {
            graph.chat.markRead(graph.chatEngine.cursor)
            graph.notifier.onChatOpened()
        }
    }

    fun notificationsAsked() {
        viewModelScope.launch { graph.settings.setNotificationsAsked() }
    }

    fun retryConnection() = graph.connection.retry()

    fun logout() {
        viewModelScope.launch { graph.auth.logout() }
    }

    /** Une page de la console, sur le serveur de la session (lien déjà filtré par `consoleHref`). */
    fun consoleUrl(href: String): String? = graph.auth.credentials()?.base?.http(href)?.toString()

    fun mikaImageUrl(att: MessageAttachment): String? = graph.downloads.absoluteUrl(att)

    fun ownFile(cid: String, local: String): File? = graph.files.locate(cid, local)

    private companion object {
        const val KEY_CAMERA = "camera_path"
        const val DRAFT_DEBOUNCE_MS = 400L
        const val GREETING_MS = 2_600L
        /** Revenir sur l'écran plus tôt n'est pas « se retrouver » : pas de nouveau salut. */
        const val GREETING_GAP_MS = 20 * 60_000L
        val PHOTO_NAME: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss", Locale.ROOT)
    }
}
