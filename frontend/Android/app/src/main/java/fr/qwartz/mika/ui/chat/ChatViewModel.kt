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
import fr.qwartz.mika.avatar3d.Avatar3DState
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.data.chat.ChatRepository
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.chat.Strands
import fr.qwartz.mika.data.chat.WorkCard
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.files.StagedFile
import fr.qwartz.mika.data.mind.StatusLine
import fr.qwartz.mika.data.net.ApprovalDecision
import fr.qwartz.mika.data.net.LinkState
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.StrandInfo
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.FlowPreview
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.debounce
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.first
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
 * peut mourir pendant la prise de vue), les partages reçus. Un modèle par compte ([owner], voir
 * [chatOwner]) : seul celui de la session ouverte tient la barre de saisie.
 */
class ChatViewModel(
    private val graph: AppGraph,
    private val saved: SavedStateHandle,
    private val owner: String,
) : ViewModel() {
    val zone: ZoneId = ZoneId.systemDefault()

    /** Une opératrice voit le lien « ouvrir la console » sous une réponse ratée. */
    val operator: StateFlow<Boolean> = graph.auth.session
        .map { (it as? Session.LoggedIn)?.profile?.operator == true }
        .stateIn(viewModelScope, SharingStarted.Eagerly, false)

    /**
     * Le mode pro (ADR 0116) : l'interrupteur « Pro » de la barre de saisie, retenu sur l'appareil, qui ne vaut que
     * pour une opératrice — ailleurs il n'apparaît pas, et rien ne part en mode pro.
     */
    val proMode: StateFlow<Boolean> = combine(
        operator,
        graph.settings.settings.map { it.proMode }.distinctUntilChanged(),
    ) { op, on -> op && on }.stateIn(viewModelScope, SharingStarted.Eagerly, false)

    /** Le fil de travail ouvert en mode pro (ADR 0164), retenu sur l'appareil ; `null` : aucun encore. */
    val activeStrand: StateFlow<String?> = graph.store.observeKv(Kv.ACTIVE_STRAND)
        .map { it?.takeIf(Strands::isValidId) }
        .stateIn(viewModelScope, SharingStarted.Eagerly, null)

    /**
     * Ce que l'écran montre : en mode pro, le fil de travail ouvert, seul — le fil avec Mika est caché ; sinon, le fil
     * avec elle, seul (aucun message d'un fil de travail). `null` : le fil avec elle.
     */
    private val view: StateFlow<String?> = combine(proMode, activeStrand) { pro, active ->
        // en mode pro sans fil encore (le temps d'en ouvrir un) : un fil vide, jamais le fil avec elle
        if (pro) active ?: NO_STRAND else null
    }.stateIn(viewModelScope, SharingStarted.Eagerly, null)

    /** Le fil vu, les messages relus d'un coup : ce que [items] et [strands] lisent. */
    private val thread = graph.chat.observe()

    val items: StateFlow<List<ChatItem>> = combine(
        combine(
            thread,
            graph.chatEngine.ephemeral,
            graph.chatEngine.truncated,
            graph.chatEngine.typing,
            // ses cartes de travail (ADR 0116) : en mémoire seulement
            graph.chatEngine.work,
        ) { messages, ephemeral, truncated, typing, work -> Snapshot(messages, ephemeral, truncated, typing, work.cards) },
        view,
        proMode,
        graph.chatEngine.typingIn,
    ) { snap, strand, pro, typingIn ->
        val ordinary = !pro
        ChatItems.build(
            messages = snap.messages.filter { it.strand == strand },
            // ses pensées et les notes de la machine sont du fil avec elle ; la troncature aussi
            ephemeral = if (ordinary) snap.ephemeral else emptyList(),
            truncated = ordinary && snap.truncated,
            typing = snap.typing && typingIn == strand,
            nowMs = graph.clock.wallMs(),
            zone = zone,
            work = snap.work.filter { it.strand == strand },
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private class Snapshot(
        val messages: List<StoredMessage>,
        val ephemeral: List<StoredMessage>,
        val truncated: Boolean,
        val typing: Boolean,
        val work: List<WorkCard>,
    )

    /**
     * Ses fils de travail à lister (ADR 0164) : la liste du serveur, plus ceux qu'il ne connaît pas encore (le fil
     * ouvert ici, encore vide ; un fil dont les messages sont arrivés avant sa liste).
     */
    val strands: StateFlow<List<StrandInfo>> = combine(graph.chatEngine.strands, thread, activeStrand) { server, all, active ->
        Strands.visible(server, all, active, graph.clock.wallMs())
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
        StatusLine.of(link, typing, mind, graph.clock.elapsedMs(), graph.clock.wallMs())
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
    private val greeting = MutableStateFlow(AvatarDirector.Greeting.NONE)
    /**
     * Quand on l'a quittée (ou vue arriver, la première fois), en heure murale : l'horloge des retrouvailles.
     * Gardée aussi en base ([Kv.LAST_SEEN_WALL]) : Android tue souvent le processus d'une app laissée en
     * arrière-plan, et la rouvrir deux minutes après n'est pas se retrouver.
     */
    private var lastSeenWallMs: Long? = null

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
        // La 3D native n'a pas besoin des portraits ; la scène porte alors seulement la lumière et le sommeil.
        if (!on || (ids == null && !has3d)) null else AvatarDirector.scene(mind, typing, greet, ids.orEmpty())
    }.distinctUntilChanged().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), null)

    /** Ce qu'un refus a dit d'un avis sur une de ses réponses, par message (ADR 0113). */
    val verdictErrors: StateFlow<Map<Long, String>> = graph.chatEngine.verdictErrors

    /** Juger une de ses réponses : `ok`, `ko`, ou vide pour retirer l'avis ; [comment] : ce qu'elle aurait dû dire. */
    fun judge(messageId: Long, verdict: String, comment: String) {
        viewModelScope.launch { graph.connection.judge(messageId, verdict, comment) }
    }

    /** L'app a-t-elle Mika en 3D native (le VRM préparé dans ses assets) ? */
    val has3d: Boolean = Avatar3DState.available(graph.context)

    /** Ce que l'avatar 3D doit savoir d'elle. */
    val avatar3d: StateFlow<Avatar3DState> = combine(graph.mind.state, graph.chatEngine.typing) { mind, typing ->
        Avatar3DState.of(mind, typing)
    }.distinctUntilChanged().stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), Avatar3DState())

    fun setProMode(on: Boolean) {
        viewModelScope.launch { graph.settings.setProMode(on) }
    }

    /**
     * Le fil choisi ici en dernier (ouvert, ou neuf) : la base le retient, mais l'écran l'apprend un instant plus
     * tard — un message tapé juste après `/clear` va déjà au fil neuf.
     */
    private var chosen: String? = null

    /** Le fil de travail ouvert, s'il y en a un ; sinon un fil neuf, qui devient le fil ouvert. */
    private suspend fun ensureStrand(): String {
        (chosen ?: activeStrand.value)?.let { return it }
        return choose(Strands.newId(graph.clock.wallMs()))
    }

    private suspend fun choose(id: String): String {
        chosen = id
        graph.store.kvPut(Kv.ACTIVE_STRAND, id)
        return id
    }

    /**
     * Ouvrir un de ses fils de travail. S'il a au serveur des messages que ce téléphone n'a pas (un fil ouvert sur la
     * page web, ou plus ancien que ce qu'on garde), on les demande.
     */
    fun openStrand(id: String) {
        if (!Strands.isValidId(id)) return
        viewModelScope.launch {
            choose(id)
            val known = graph.chatEngine.strands.value.firstOrNull { it.id == id }?.count ?: 0
            val here = Strands.localCount(graph.chat.observe().first(), id)
            if (known > here) graph.connection.requestStrandHistory(id)
        }
    }

    /** Un fil neuf (`/clear`) : rien ne s'efface, l'ancien reste dans la liste. */
    fun newStrand() {
        viewModelScope.launch { choose(Strands.newId(graph.clock.wallMs())) }
    }

    /** Régler un fil : son réglage entier (titre, description, archivé). Un refus se dit dans la barre de saisie. */
    fun saveStrand(id: String, title: String, description: String, archived: Boolean) {
        viewModelScope.launch { graph.connection.setStrand(id, title, description, archived) }
    }

    /** Ce qu'on sait du réglage d'un fil (pour une commande qui n'en change qu'une partie). */
    private fun settingOf(id: String): StrandInfo = strands.value.firstOrNull { it.id == id } ?: StrandInfo(id)

    /**
     * Une commande tapée en mode pro (`/clear`, `/renommer`…) : elle s'exécute ici, rien ne part dans le fil. Les
     * fichiers en préparation restent dans la barre.
     */
    private fun runCommand(command: Strands.Command) {
        input = ""
        composingIdle?.cancel()
        composingIdle = null
        graph.connection.composing(false)
        notices = emptyList()
        when (command) {
            Strands.Command.Clear -> newStrand()
            Strands.Command.Help -> notices = Strands.HELP
            is Strands.Command.Unknown -> notices = listOf(Strands.unknownNotice(command.typed))
            is Strands.Command.Rename -> if (command.title.isBlank()) {
                notices = listOf(USAGE_RENAME)
            } else {
                viewModelScope.launch {
                    val id = ensureStrand()
                    val s = settingOf(id)
                    graph.connection.setStrand(id, command.title, s.description, s.archived)
                }
            }
            is Strands.Command.Describe -> if (command.text.isBlank()) {
                notices = listOf(USAGE_DESCRIBE)
            } else {
                viewModelScope.launch {
                    val id = ensureStrand()
                    val s = settingOf(id)
                    graph.connection.setStrand(id, s.title, command.text, s.archived)
                }
            }
            Strands.Command.Archive, Strands.Command.Unarchive -> viewModelScope.launch {
                val id = ensureStrand()
                val s = settingOf(id)
                graph.connection.setStrand(id, s.title, s.description, command == Strands.Command.Archive)
            }
        }
    }

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
    /** Ce qui clôt la saisie faute de frappe ([MikaProtocol.COMPOSING_IDLE_MS]). */
    private var composingIdle: Job? = null

    init {
        // Un réglage de fil refusé, ou parti hors ligne : dit dans la barre de saisie (ADR 0164).
        viewModelScope.launch { graph.chatEngine.strandNotices.collect { notices = listOf(it) } }
        // Le mode pro s'ouvre toujours sur un fil de travail : le dernier ouvert, sinon un neuf.
        // (lu de la base même, pas de [activeStrand] : sa valeur de départ, nulle, n'est pas « aucun fil »)
        viewModelScope.launch {
            val stored = graph.store.observeKv(Kv.ACTIVE_STRAND).map { it?.takeIf(Strands::isValidId) }
            combine(proMode, stored) { pro, active -> pro && active == null }
                .distinctUntilChanged()
                .collect { missing -> if (missing && chosen == null) choose(Strands.newId(graph.clock.wallMs())) }
        }
        // Ce modèle appartient à l'activité et survit à l'écran : session fermée, il oublie ce qui était
        // tapé et ne prend plus rien (un partage fait ensuite est pour la session suivante) ; rouverte
        // sur le même compte, il reprend le brouillon gardé. Ouverte sur un autre compte, ce n'est pas
        // la sienne : le modèle de ce compte-là s'en charge, celui-ci reste fermé (deux barres vivantes
        // se disputeraient les partages, le brouillon et le ménage de la préparation).
        viewModelScope.launch {
            graph.auth.session
                .map { it is Session.LoggedIn && chatOwner(it) == owner }
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
        composingIdle?.cancel()
        composingIdle = null
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
        composing(input.isNotBlank())
    }

    /**
     * Dire au serveur que la personne écrit, ou plus (trame `composing`) — le début et la fin d'une saisie,
     * jamais une frappe : un champ non vide l'ouvre et relance son délai ; vidé, ou sans frappe depuis
     * [MikaProtocol.COMPOSING_IDLE_MS], elle se clôt. L'envoi d'un message la clôt de lui-même. Rien ne
     * s'affiche : c'est pour qu'elle ne réponde pas à la moitié d'une pensée.
     */
    private fun composing(on: Boolean) {
        composingIdle?.cancel()
        composingIdle = null
        graph.connection.composing(on)
        if (!on) return
        composingIdle = viewModelScope.launch {
            delay(MikaProtocol.COMPOSING_IDLE_MS)
            composingIdle = null
            graph.connection.composing(false)
        }
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
        if (!canSend) return
        val pro = proMode.value
        // en mode pro, une commande (`/clear`…) s'exécute ici ; `//` en tête échappe (ADR 0164)
        if (pro) Strands.parse(input)?.let { return runCommand(it) }
        val text = (if (pro) Strands.unescape(input) else input).trim()
        val files = attachments.toList()
        // le mode qu'avait le message à l'envoi : il le garde, renvoi compris ; son fil de travail aussi
        val mode = if (pro) MikaProtocol.CHAT_MODE_PRO else null
        // le message clôt la saisie de lui-même (la socket le sait) : son délai n'a plus rien à clore
        composingIdle?.cancel()
        composingIdle = null
        input = ""
        attachments.clear()
        notices = emptyList()
        viewModelScope.launch {
            val strand = if (pro) ensureStrand() else null
            val result = graph.chat.send(text, files, mode, strand)
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
        viewModelScope.launch {
            val result = graph.chat.retry(localId)
            if (result is ChatRepository.SendResult.Rejected) notices = listOf(result.reason)
        }
    }

    /** Les bulles en train d'être redemandées : un double appui ne pose pas la question deux fois. */
    private val resending = HashSet<Long>()

    /** « Le lui redemander » : la même question part comme un nouveau message ; un refus se dit dans la barre. */
    fun resend(localId: Long) {
        if (!resending.add(localId)) return
        viewModelScope.launch {
            try {
                val result = graph.chat.resend(localId)
                if (result is ChatRepository.SendResult.Rejected) notices = listOf(result.reason)
            } finally {
                resending.remove(localId)
            }
        }
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
     * L'écran revient au premier plan : des retrouvailles à la mesure de l'absence
     * ([AvatarDirector.greeting]) — rien après un instant, un hochement après un moment, un coucou de
     * la main après sa nuit ou une longue absence —, le temps d'un geste. Son humeur peut encore
     * adoucir le coucou ([AvatarDirector.scene]).
     */
    fun onShown() {
        val now = graph.clock.wallMs()
        val known = lastSeenWallMs
        lastSeenWallMs = now
        viewModelScope.launch {
            // Un processus neuf ne se souvient de rien : la base, elle, sait quand on l'a quittée.
            val last = known ?: graph.store.kvGet(Kv.LAST_SEEN_WALL)?.toLongOrNull()
            val level = AvatarDirector.greeting(last, now, zone)
            if (level == AvatarDirector.Greeting.NONE) return@launch
            greeting.value = level
            delay(GREETING_MS)
            greeting.value = AvatarDirector.Greeting.NONE
        }
    }

    /** L'écran passe à l'arrière-plan : c'est de là que se compte l'absence, gardée pour un processus tué. */
    fun onHidden() {
        val now = graph.clock.wallMs()
        lastSeenWallMs = now
        // Hors de la portée du modèle : quitter l'app depuis les récentes le détruit juste après.
        graph.scope.launch { graph.store.kvPut(Kv.LAST_SEEN_WALL, now.toString()) }
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
        /** Une vue de fil de travail sans fil encore : aucun message n'y est (un identifiant n'est jamais vide). */
        const val NO_STRAND = ""
        const val USAGE_RENAME = "Écris le titre après la commande : /renommer Devis IN"
        const val USAGE_DESCRIBE = "Écris la description après la commande : /description Le commercial d'IN, montants HT"
        const val KEY_CAMERA = "camera_path"
        const val DRAFT_DEBOUNCE_MS = 400L
        const val GREETING_MS = 2_600L
        val PHOTO_NAME: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss", Locale.ROOT)
    }
}

/** À qui appartient une conversation : le compte et son serveur, vide hors session. */
fun chatOwner(session: Session): String =
    (session as? Session.LoggedIn)?.let { "${it.base}|${it.profile.personId}" }.orEmpty()
