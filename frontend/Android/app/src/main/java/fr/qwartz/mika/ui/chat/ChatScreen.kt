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
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.net.LinkState
import fr.qwartz.mika.avatar3d.LiveAvatar3D
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.ui.avatar.AvatarBackdrop
import fr.qwartz.mika.ui.avatar.AvatarStage
import fr.qwartz.mika.ui.avatar.auraColor
import fr.qwartz.mika.ui.avatar.rememberPortrait
import fr.qwartz.mika.ui.components.rememberFileActions
import kotlinx.coroutines.launch

/** Les types que le sélecteur de fichiers propose : la liste du client web (`ChatOverlay.ts`). */
private val DOCUMENT_TYPES = arrayOf(
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/ogg", "audio/webm",
    "text/plain", "text/csv", "text/markdown", "application/json",
    "application/pdf",
)

/** La conversation : la barre du haut, le fil, la barre de saisie et ses sources de fichiers. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    graph: AppGraph,
    onOpenMind: () -> Unit,
    onOpenSettings: () -> Unit,
    onOpenImage: (MessageAttachment) -> Unit,
) {
    val session by graph.auth.session.collectAsStateWithLifecycle()
    // Une conversation par compte : le brouillon d'une session ne passe pas à la suivante.
    val owner = chatOwner(session)
    val vm: ChatViewModel = viewModel(key = "chat:$owner") { ChatViewModel(graph, createSavedStateHandle(), owner) }
    val items by vm.items.collectAsStateWithLifecycle()
    val status by vm.status.collectAsStateWithLifecycle()
    val link by vm.link.collectAsStateWithLifecycle()
    val operator by vm.operator.collectAsStateWithLifecycle()
    val asked by vm.notificationsAsked.collectAsStateWithLifecycle()
    val approvals by vm.approvals.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val snackbar = remember { SnackbarHostState() }
    val files = rememberFileActions(graph, snackbar)
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    var sheet by rememberSaveable { mutableStateOf(false) }

    // Lue tant qu'elle est à l'écran : dès la reprise, et à chaque nouveau message.
    val lifecycle by LocalLifecycleOwner.current.lifecycle.currentStateAsState()
    val newest = items.lastOrNull { it is ChatItem.Bubble }?.key
    LaunchedEffect(newest, lifecycle) {
        if (lifecycle.isAtLeast(Lifecycle.State.RESUMED)) vm.markRead()
    }

    // Le sort d'une décision sur une carte d'accord, dit une fois.
    LaunchedEffect(vm) { vm.approvalMessages.collect { snackbar.showSnackbar(it) } }

    var notificationsGranted by remember { mutableStateOf(notificationsAllowed(context)) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        notificationsGranted = notificationsAllowed(context)
        vm.onShown()
    }
    LifecycleEventEffect(Lifecycle.Event.ON_PAUSE) { vm.onHidden() }

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

    val scene = avatar
    val state3d by vm.avatar3d.collectAsStateWithLifecycle()
    var keystrokes by remember { mutableIntStateOf(0) }
    LaunchedEffect(vm.input) { if (vm.input.isNotEmpty()) keystrokes++ }
    Box(Modifier.fillMaxSize()) {
        if (scene != null) {
            if (vm.has3d) {
                // Mika en 3D native ; le salut de retrouvailles devient son vrai geste (coucou ou hochement).
                AvatarStage(scene.aura, scene.asleep) {
                    LiveAvatar3D(
                        state3d,
                        wave = scene.greeting == AvatarDirector.Greeting.WAVE,
                        nod = scene.greeting == AvatarDirector.Greeting.NOD,
                        userTyping = keystrokes,
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
                    face = portrait.takeIf { scene != null },
                    faceTint = faceTint ?: MaterialTheme.colorScheme.primaryContainer,
                    transparent = scene != null,
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
                        modifier = Modifier.weight(1f),
                    )
                    ApprovalTray(approvals, onDecide = vm::decide, modifier = Modifier.heightIn(max = trayMax))
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

private fun notificationsAllowed(context: android.content.Context): Boolean =
    Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED
