package fr.qwartz.mika.ui.chat

import android.Manifest
import android.content.ClipData
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.provider.MediaStore
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.core.content.ContextCompat
import androidx.core.net.toUri
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.compose.currentStateAsState
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.createSavedStateHandle
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.agenda.CAPABILITY_AGENDA_WRITE
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.net.LinkState
import fr.qwartz.mika.data.net.StrandInfo
import fr.qwartz.mika.avatar3d.LiveAvatar3D
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.ui.avatar.AvatarBackdrop
import fr.qwartz.mika.ui.avatar.AvatarStage
import fr.qwartz.mika.ui.avatar.auraColor
import fr.qwartz.mika.ui.avatar.rememberPortrait
import fr.qwartz.mika.ui.components.rememberFileActions
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.statusBars
import androidx.compose.ui.platform.LocalDensity
import fr.qwartz.mika.ui.avatar.faceClearance
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.carte.MapNoteCard
import fr.qwartz.mika.ui.carte.rememberCarteStore
import fr.qwartz.mika.ui.map.MiniSlots
import fr.qwartz.mika.ui.shell.MenuEntry
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** Les types que le sélecteur de fichiers propose : la liste du client web (`ChatOverlay.ts`). */
private val DOCUMENT_TYPES = arrayOf(
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm",
    "text/plain", "text/csv", "text/markdown", "application/json",
    "application/pdf",
)

/**
 * Le modèle de la conversation du compte ouvert — un par compte : le brouillon d'une session ne passe pas à la suivante.
 * La recherche et « Fichiers échangés » le lisent aussi (le même, celui de l'activité) pour y ramener sur un message.
 */
@Composable
internal fun rememberChatModel(graph: AppGraph): ChatViewModel {
    val session by graph.auth.session.collectAsStateWithLifecycle()
    val owner = chatOwner(session)
    return viewModel(key = "chat:$owner") { ChatViewModel(graph, createSavedStateHandle(), owner) }
}

/**
 * La conversation : la barre du haut (la loupe, ⋮), le fil (ses notes de carte en miniatures), ce qui attend ta décision
 * replié au-dessus du champ, la barre de saisie et ses sources de fichiers.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    graph: AppGraph,
    onOpenMind: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenImage: (MessageAttachment) -> Unit,
    onMenu: (() -> Unit)? = null,
    onOpenSearch: (() -> Unit)? = null,
    onOpenFiles: (() -> Unit)? = null,
    onOpen: (Route) -> Unit = {},
) {
    val session by graph.auth.session.collectAsStateWithLifecycle()
    // Une conversation par compte : le brouillon d'une session ne passe pas à la suivante.
    val owner = chatOwner(session)
    val vm = rememberChatModel(graph)
    val items by vm.items.collectAsStateWithLifecycle()
    val verdictErrors by vm.verdictErrors.collectAsStateWithLifecycle()
    val status by vm.status.collectAsStateWithLifecycle()
    val link by vm.link.collectAsStateWithLifecycle()
    val operator by vm.operator.collectAsStateWithLifecycle()
    val proMode by vm.proMode.collectAsStateWithLifecycle()
    val asked by vm.notificationsAsked.collectAsStateWithLifecycle()
    val approvals by vm.approvals.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    val files = rememberFileActions(graph, snackbar)
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    var sheet by rememberSaveable { mutableStateOf(false) }
    // les fils de travail du mode pro (ADR 0164) : leur liste, le fil ouvert, la feuille et le réglage
    val strands by vm.strands.collectAsStateWithLifecycle()
    val activeStrand by vm.activeStrand.collectAsStateWithLifecycle()
    var strandSheet by rememberSaveable { mutableStateOf(false) }
    var strandEdit by rememberSaveable { mutableStateOf(false) }
    val currentStrand = activeStrand?.let { id -> strands.firstOrNull { it.id == id } ?: StrandInfo(id) }

    // Lue tant qu'elle est à l'écran : dès la reprise, et à chaque nouveau message.
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val newest = items.lastOrNull { it is ChatItem.Bubble }?.key
    LaunchedEffect(newest, lifecycle) {
        if (lifecycle.isAtLeast(Lifecycle.State.RESUMED)) vm.markRead()
    }

    // Le sort d'une décision sur une carte d'accord, dit une fois.
    LaunchedEffect(vm) { vm.approvalMessages.collect { snackbar.showSnackbar(it) } }

    // Ce qui attend ta décision au-dessus du champ (ADR 0235, point 4) : les cartes, les pastilles, ses brouillons lus.
    val me by graph.me.me.collectAsStateWithLifecycle()
    val counts = me?.counts
    // relue à chaque nouvelle liste : la liste des cartes se recalcule elle-même toutes les 30 s et à chaque échéance
    val now = graph.clock.wallMs()
    val tray = ChatTray.build(approvals, counts, vm.trayMail, vm.trayTeams, now)
    val mailCards = approvals.filter { ChatTray.place(it) == DraftPlace.MAIL }.map { it.id }
    val teamsCards = approvals.filter { ChatTray.place(it) == DraftPlace.TEAMS }.map { it.id }
    // ses brouillons se relisent quand les pastilles ou les cartes changent, et quand on déplie la ligne
    val wantsMail = (counts?.mail ?: 0) > 0 || mailCards.isNotEmpty()
    val wantsTeams = (counts?.teams ?: 0) > 0 || teamsCards.isNotEmpty()
    LaunchedEffect(counts?.mail, counts?.teams, mailCards, teamsCards) {
        if (wantsMail || wantsTeams || vm.trayMail != null || vm.trayTeams != null) vm.loadTrayDrafts(wantsMail, wantsTeams)
    }
    LaunchedEffect(vm.trayOpen) {
        if (vm.trayOpen && (wantsMail || wantsTeams)) vm.loadTrayDrafts(wantsMail, wantsTeams)
    }
    // les ajouts à l'agenda (ADR 0309) : l'événement de chaque carte, relu quand les cartes changent
    val agendaCards = approvals.filter { it.capability == CAPABILITY_AGENDA_WRITE }.map { it.id.toInt() }
    LaunchedEffect(agendaCards) { vm.loadTrayAgenda(agendaCards) }
    // plus rien n'attend (vu sur cet écran : une liste encore vide à son ouverture ne la replie pas) : elle repart repliée
    var trayShown by remember { mutableStateOf(false) }
    LaunchedEffect(tray.isEmpty) {
        if (tray.isEmpty && trayShown) vm.foldTray()
        trayShown = !tray.isEmpty
    }

    // Le message que la recherche demande de montrer : parti entre-temps (ou dans un fil qui ne s'ouvre pas), on le dit.
    val focus = vm.focus
    val focusGone = stringResource(R.string.chat_focus_gone)
    LaunchedEffect(focus) {
        if (focus == null) return@LaunchedEffect
        delay(FOCUS_WAIT_MS)
        if (vm.focus == focus) {
            vm.focusDone()
            snackbar.showSnackbar(focusGone)
        }
    }

    var notificationsGranted by remember { mutableStateOf(notificationsAllowed(context)) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        notificationsGranted = notificationsAllowed(context)
        vm.onShown()
    }
    LifecycleEventEffect(Lifecycle.Event.ON_PAUSE) { vm.onHidden() }
    // Un écran interne (« Ce qu'elle fait », réglages, image) la remplace sans pause : l'absence se compte
    // de là, sinon le retour rejoue des retrouvailles. Pas quand l'activité s'en va : la pause l'a déjà dit.
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(vm, lifecycleOwner) {
        onDispose {
            if (lifecycleOwner.lifecycle.currentState.isAtLeast(Lifecycle.State.RESUMED)) vm.onHidden()
        }
    }

    // Mika en fond : son portrait du moment, et son visage dans la barre du haut.
    val avatar by vm.avatar.collectAsStateWithLifecycle()
    val portrait by rememberPortrait(graph.avatar, avatar?.portrait)
    val scheme = MaterialTheme.colorScheme
    val faceTint = avatar?.let { auraColor(it.aura, scheme.surface.luminance() < 0.5f, scheme.primaryContainer) }
    val askNotifications = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        notificationsGranted = granted
        vm.notificationsAsked()
    }

    val pickPhotos = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(5)) { uris ->
        vm.addUris(uris)
    }
    val pickDocuments = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        vm.addUris(uris)
    }
    val takePicture = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { taken ->
        vm.onCameraResult(taken)
    }
    val cameraAvailable = remember {
        Intent(MediaStore.ACTION_IMAGE_CAPTURE).resolveActivity(context.packageManager) != null
    }

    val copied = stringResource(R.string.chat_copied)
    val actions = remember(vm, files) {
        ChatActions(
            retry = vm::retry,
            resend = vm::resend,
            judge = vm::judge,
            copy = { text ->
                scope.launch {
                    clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Mika", text)))
                    // Android 13 et plus confirme lui-même la copie.
                    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) snackbar.showSnackbar(copied)
                }
            },
            openImage = onOpenImage,
            save = files::save,
            open = files::open,
            openConsole = { href ->
                vm.consoleUrl(href)?.let { url ->
                    try {
                        context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri()))
                    } catch (_: android.content.ActivityNotFoundException) {
                    }
                }
            },
            imageUrl = vm::mikaImageUrl,
            ownFile = vm::ownFile,
        )
    }

    // ses cartes miniatures (ADR 0196) : leurs places vivantes, pour ce fil
    val slots = remember(owner) { MiniSlots() }

    // En mode pro (ADR 0116), le travail prend tout l'écran : Mika quitte le fond (sa 3D ne tourne plus), le fil n'a
    // plus de bande sous son visage, ses réponses et ses cartes prennent toute la largeur. Son visage reste en haut.
    val scene = avatar.takeIf { !proMode }
    val state3d by vm.avatar3d.collectAsStateWithLifecycle()
    var keystrokes by remember { mutableIntStateOf(0) }
    LaunchedEffect(vm.input) { if (vm.input.isNotEmpty()) keystrokes++ }

    // Ce que le fil lui dit : sa réponse qui arrive, elle la dit ; un message qui part, elle le lit. Pas en mode
    // pro, où elle n'est pas là pour le jouer.
    val talk = rememberConversationStage(
        items,
        watching = lifecycle.isAtLeast(Lifecycle.State.RESUMED) && !proMode,
        speaks = vm.has3d,
        key = owner,
    )
    val statusTop = with(LocalDensity.current) { WindowInsets.statusBars.getTop(this).toDp() }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val stage = scene?.let {
            StageLink(
                faceClearance = faceClearance(maxWidth, maxHeight, statusTop),
                track = talk.track.takeIf { vm.has3d },
                onReadingHistory = { talk.readingHistory = it },
            )
        }
        if (scene != null) {
            if (vm.has3d) {
                // Mika en 3D native ; le salut de retrouvailles devient son vrai geste (coucou ou hochement).
                AvatarStage(scene.aura, scene.asleep, presence = if (talk.readingHistory) 0.3f else 1f) {
                    LiveAvatar3D(
                        state3d,
                        wave = scene.greeting == AvatarDirector.Greeting.WAVE,
                        nod = scene.greeting == AvatarDirector.Greeting.NOD,
                        userTyping = keystrokes,
                        speech = talk.track.utterances,
                        reading = talk.reading,
                        dimmed = talk.readingHistory,
                        modifier = Modifier.fillMaxSize(),
                    )
                }
            } else {
                AvatarBackdrop(scene, portrait)
            }
        }
        Scaffold(
            // Sur son portrait, l'écran laisse passer le fond ; la barre de saisie, elle, reste pleine.
            containerColor = if (scene != null) Color.Transparent else MaterialTheme.colorScheme.background,
            topBar = {
                ChatTopBar(
                    status,
                    onOpenMind,
                    onOpenSettings,
                    face = portrait.takeIf { avatar != null },
                    faceTint = faceTint ?: MaterialTheme.colorScheme.primaryContainer,
                    transparent = scene != null,
                    onMenu = onMenu,
                    onSearch = onOpenSearch,
                    onFiles = onOpenFiles,
                    extra = if (proMode) {
                        strandEntries(
                            currentStrand,
                            onList = { strandSheet = true },
                            onEdit = { if (currentStrand != null) strandEdit = true },
                            onArchive = { s -> vm.saveStrand(s.id, s.title, s.description, !s.archived) },
                        )
                    } else {
                        emptyList()
                    },
                )
            },
            snackbarHost = { SnackbarHost(snackbar) },
            bottomBar = {
                Composer(
                    input = vm.input,
                    onInput = vm::onInput,
                    attachments = vm.attachments,
                    notices = vm.notices,
                    staging = vm.staging,
                    canSend = vm.canSend,
                    onRemove = vm::remove,
                    onAttach = { sheet = true },
                    onSend = vm::send,
                    proAvailable = operator,
                    pro = proMode,
                    onPro = vm::setProMode,
                )
            },
        ) { padding ->
            BoxWithConstraints(Modifier.fillMaxSize().padding(padding)) {
                // Les cartes d'accord, au-dessus de la barre de saisie : la moitié de la place au plus.
                val trayMax = maxHeight * 0.5f
                Column(Modifier.fillMaxSize()) {
                    if (link is LinkState.Refused) {
                        RefusedBanner(onRetry = vm::retryConnection, onLogout = { confirmLogout = true })
                    }
                    // en mode pro, le fil de travail ouvert ; le fil avec elle est caché (ADR 0164)
                    if (proMode) {
                        StrandBar(
                            currentStrand,
                            onList = { strandSheet = true },
                            onEdit = { if (currentStrand != null) strandEdit = true },
                            onNew = vm::newStrand,
                        )
                    }
                    val needsPrompt = Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !asked && !notificationsGranted
                    if (needsPrompt) {
                        NotificationPrompt(
                            onAllow = { askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS) },
                            onLater = vm::notificationsAsked,
                        )
                    }
                    ChatConversation(
                        items = items,
                        zone = vm.zone,
                        operator = operator,
                        busyFileId = files.busy,
                        actions = actions,
                        overPortrait = scene != null,
                        stage = stage,
                        verdictErrors = verdictErrors,
                        wide = proMode,
                        emptyText = if (proMode) stringResource(R.string.strand_empty) else null,
                        modifier = Modifier.weight(1f),
                        focus = focus,
                        onFocused = vm::focusDone,
                        mapCard = { item -> ChatMapCard(graph, slots, item) },
                    )
                    ChatTrayBand(
                        tray,
                        open = vm.trayOpen,
                        nowWallMs = now,
                        onToggle = vm::toggleTray,
                        onDecide = vm::decide,
                        onOpen = onOpen,
                        modifier = Modifier.heightIn(max = trayMax),
                        acceptAll = ChatTray.offersAcceptAll(proMode, operator, tray),
                        acceptingAll = vm.acceptingAll,
                        onAcceptAll = { vm.acceptAll(tray.accords) },
                        agenda = vm.trayAgenda,
                    )
                }
            }
        }
    }

    if (sheet) {
        AttachSheet(
            cameraAvailable = cameraAvailable,
            onDismiss = { sheet = false },
            onPhotos = {
                sheet = false
                pickPhotos.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            },
            onCamera = {
                sheet = false
                vm.cameraTarget()?.let(takePicture::launch)
            },
            onDocuments = {
                sheet = false
                pickDocuments.launch(DOCUMENT_TYPES)
            },
        )
    }

    if (strandSheet && proMode) {
        StrandSheet(
            strands = strands,
            active = activeStrand,
            onDismiss = { strandSheet = false },
            onOpen = { id ->
                strandSheet = false
                vm.openStrand(id)
            },
            onNew = {
                strandSheet = false
                vm.newStrand()
            },
        )
    }

    val editing = currentStrand
    if (strandEdit && proMode && editing != null) {
        StrandEditDialog(
            editing,
            onDismiss = { strandEdit = false },
            onSave = { title, description, archived ->
                strandEdit = false
                vm.saveStrand(editing.id, title, description, archived)
            },
        )
    }

    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            title = { Text(stringResource(R.string.logout_confirm_title)) },
            text = { Text(stringResource(R.string.logout_confirm_text)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmLogout = false
                    vm.logout()
                }) { Text(stringResource(R.string.menu_logout)) }
            },
            dismissButton = {
                TextButton(onClick = { confirmLogout = false }) { Text(stringResource(R.string.cancel)) }
            },
        )
    }
}

/** Le temps qu'on attend le message à montrer (le fil peut changer de vue d'abord) avant de dire qu'il n'est plus là. */
private const val FOCUS_WAIT_MS = 2_500L

/**
 * Une de ses notes de carte sous ses bulles (ADR 0196) : la miniature de la Carte (`MapNoteCard`), lue une fois pour la
 * session. Un voyage dont la note dit un changement plus récent que ce qu'on en a lu se relit (sa note porte l'instant
 * de son dernier changement) — une fois par note.
 */
@Composable
private fun ChatMapCard(graph: AppGraph, slots: MiniSlots, item: ChatItem.MapCard) {
    val note = item.note
    if (note.kind == MikaProtocol.NOTE_TRIP && note.at > 0) {
        val store = rememberCarteStore(graph)
        LaunchedEffect(note.id, note.at) { store.minis.seen(note.id, note.at) }
    }
    MapNoteCard(graph, slots, item.owner, note.kind, note.ref, note.text)
}

/** En mode pro, le haut de ⋮ : ses fils de travail, régler et archiver le fil ouvert (ADR 0164). */
@Composable
private fun strandEntries(
    current: StrandInfo?,
    onList: () -> Unit,
    onEdit: () -> Unit,
    onArchive: (StrandInfo) -> Unit,
): List<MenuEntry> {
    val list = MenuEntry(stringResource(R.string.chat_menu_strands), R.drawable.ic_m_threads, onList)
    if (current == null) return listOf(list)
    val archive = stringResource(if (current.archived) R.string.chat_menu_strand_unarchive else R.string.chat_menu_strand_archive)
    return listOf(
        list,
        MenuEntry(stringResource(R.string.chat_menu_strand_edit), R.drawable.ic_m_pen, onEdit),
        MenuEntry(archive, R.drawable.ic_m_archive) { onArchive(current) },
    )
}

private fun notificationsAllowed(context: android.content.Context): Boolean =
    Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
