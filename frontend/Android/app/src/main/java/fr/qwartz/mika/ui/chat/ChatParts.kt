package fr.qwartz.mika.ui.chat

import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SmallFloatingActionButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.derivedStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.CustomAccessibilityAction
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import fr.qwartz.mika.R
import fr.qwartz.mika.data.chat.MessageAttachment
import fr.qwartz.mika.data.chat.MessageStatus
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.files.AttachmentPolicy
import fr.qwartz.mika.data.files.MikaFileRefs
import fr.qwartz.mika.ui.components.InlineMarkup
import fr.qwartz.mika.ui.components.InlineMarkupText
import fr.qwartz.mika.ui.avatar.AvatarFace
import fr.qwartz.mika.ui.avatar.LoadedPortrait
import fr.qwartz.mika.ui.components.MikaAvatar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.time.ZoneId

/** Ce que le fil sait faire ; des défauts muets pour les tests d'écran. */
class ChatActions(
    val retry: (Long) -> Unit = {},
    val resend: (Long) -> Unit = {},
    val copy: (String) -> Unit = {},
    val openImage: (MessageAttachment) -> Unit = {},
    val save: (MessageAttachment) -> Unit = {},
    val open: (MessageAttachment) -> Unit = {},
    val openConsole: (String) -> Unit = {},
    val imageUrl: (MessageAttachment) -> String? = { null },
    val ownFile: (cid: String, local: String) -> File? = { _, _ -> null },
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ChatTopBar(
    status: String,
    onOpenMind: () -> Unit,
    onOpenSettings: () -> Unit,
    face: LoadedPortrait? = null,
    faceTint: Color = MaterialTheme.colorScheme.primaryContainer,
    transparent: Boolean = false,
) {
    var menu by remember { mutableStateOf(false) }
    val openMindLabel = stringResource(R.string.chat_open_mind)
    TopAppBar(
        // Sur son portrait, la barre laisse passer la lumière du fond.
        colors = if (transparent) {
            TopAppBarDefaults.topAppBarColors(containerColor = Color.Transparent, scrolledContainerColor = Color.Transparent)
        } else {
            TopAppBarDefaults.topAppBarColors()
        },
        title = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .heightIn(min = 48.dp)
                    .clickable(onClickLabel = openMindLabel, onClick = onOpenMind),
            ) {
                if (face != null) AvatarFace(face, faceTint) else MikaAvatar()
                Column(Modifier.padding(start = 12.dp)) {
                    Text(
                        stringResource(R.string.mika),
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.semantics { heading() },
                    )
                    // Pas de région vivante ici : le compte à rebours de reconnexion change chaque seconde.
                    Text(
                        status,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        },
        actions = {
            IconButton(onClick = { menu = true }) {
                Icon(painterResource(R.drawable.ic_more_vert), stringResource(R.string.chat_more))
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.menu_status)) },
                    onClick = {
                        menu = false
                        onOpenMind()
                    },
                )
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.menu_settings)) },
                    onClick = {
                        menu = false
                        onOpenSettings()
                    },
                )
            }
        },
    )
}

@Composable
internal fun RefusedBanner(onRetry: () -> Unit, onLogout: () -> Unit) {
    Surface(color = MaterialTheme.colorScheme.errorContainer, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.banner_refused), modifier = Modifier.weight(1f))
            TextButton(onClick = onRetry) { Text(stringResource(R.string.banner_retry)) }
            TextButton(onClick = onLogout) { Text(stringResource(R.string.menu_logout)) }
        }
    }
}

/** Demandée une fois, à la première ouverture, avec une explication : jamais une fenêtre système sans contexte. */
@Composable
internal fun NotificationPrompt(onAllow: () -> Unit, onLater: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.secondaryContainer),
        modifier = Modifier.fillMaxWidth().padding(12.dp),
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                stringResource(R.string.notif_prompt_title),
                style = MaterialTheme.typography.titleSmall,
                modifier = Modifier.semantics { heading() },
            )
            Text(stringResource(R.string.notif_prompt_text), style = MaterialTheme.typography.bodyMedium)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                TextButton(onClick = onLater) { Text(stringResource(R.string.notif_prompt_later)) }
                Button(onClick = onAllow) { Text(stringResource(R.string.notif_prompt_allow)) }
            }
        }
    }
}

/**
 * Le fil, du plus ancien (en haut) au plus récent (en bas). Une liste à l'envers : l'arrivée d'un
 * message reste collée en bas ; remontée dans l'historique, une puce « ↓ N nouveaux » compte ce qui
 * arrive et y ramène.
 */
@Composable
internal fun ChatConversation(
    items: List<ChatItem>,
    zone: ZoneId,
    operator: Boolean,
    busyFileId: String?,
    actions: ChatActions,
    modifier: Modifier = Modifier,
    /** Le fil passe sur son portrait : ce qui n'est pas une bulle prend un fond, pour rester lisible. */
    overPortrait: Boolean = false,
) {
    if (items.isEmpty()) {
        // Sur son portrait, l'invitation se met sous elle plutôt qu'en travers.
        Box(
            modifier.fillMaxWidth().padding(bottom = if (overPortrait) 24.dp else 0.dp),
            contentAlignment = if (overPortrait) Alignment.BottomCenter else Alignment.Center,
        ) {
            Backed(overPortrait) {
                Text(stringResource(R.string.chat_empty), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        return
    }
    val listState = rememberLazyListState()
    val scope = rememberCoroutineScope()
    val reversed = remember(items) { items.asReversed() }
    val atBottom by remember { derivedStateOf { listState.firstVisibleItemIndex <= 1 } }
    var unseen by remember { mutableIntStateOf(0) }
    val newest = items.lastOrNull { it is ChatItem.Bubble } as ChatItem.Bubble?
    LaunchedEffect(newest?.key) {
        if (newest == null) return@LaunchedEffect
        if (atBottom || newest.message.sender == Sender.USER) {
            listState.animateScrollToItem(0)
        } else {
            unseen += 1
        }
    }
    LaunchedEffect(atBottom) { if (atBottom) unseen = 0 }

    Box(modifier.fillMaxWidth()) {
        LazyColumn(
            state = listState,
            reverseLayout = true,
            verticalArrangement = Arrangement.spacedBy(4.dp),
            contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
            // Toute la hauteur : un fil court part du bas, comme dans une messagerie (sinon il se colle en
            // haut — sur son visage quand elle est en fond).
            modifier = Modifier.fillMaxSize(),
        ) {
            items(reversed, key = { it.key }) { item ->
                when (item) {
                    is ChatItem.DateSeparator -> Centered(item.label, overPortrait, heading = true)
                    ChatItem.TruncatedNote -> Centered(stringResource(R.string.chat_truncated), overPortrait)
                    is ChatItem.Bubble -> Bubble(item, zone, busyFileId, actions)
                    is ChatItem.Note -> Backed(overPortrait) { Note(item, operator, actions) }
                    is ChatItem.Thought -> Backed(overPortrait) { Thought(item.message) }
                    is ChatItem.SystemNote -> Centered(item.text, overPortrait)
                    ChatItem.Typing -> Box(Modifier.padding(vertical = 4.dp)) {
                        Backed(overPortrait) {
                            Text(
                                stringResource(R.string.chat_typing),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                modifier = Modifier.padding(8.dp).semantics { liveRegion = LiveRegionMode.Polite },
                            )
                        }
                    }
                }
            }
        }
        if (unseen > 0 && !atBottom) {
            SmallFloatingActionButton(
                onClick = {
                    unseen = 0
                    scope.launch { listState.animateScrollToItem(0) }
                },
                modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 12.dp),
            ) {
                Text(
                    pluralStringResource(R.plurals.chat_new_messages, unseen, unseen),
                    modifier = Modifier.padding(horizontal = 12.dp),
                )
            }
        }
    }
}

@Composable
private fun Centered(text: String, overPortrait: Boolean, heading: Boolean = false) {
    Box(Modifier.fillMaxWidth().padding(vertical = 6.dp), contentAlignment = Alignment.Center) {
        Backed(overPortrait) {
            Text(
                text,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier
                    .padding(horizontal = if (overPortrait) 10.dp else 0.dp, vertical = if (overPortrait) 3.dp else 0.dp)
                    .then(if (heading) Modifier.semantics { heading() } else Modifier),
            )
        }
    }
}

/** Sur son portrait, un fond voilé derrière le texte libre du fil ; sinon rien. */
@Composable
private fun Backed(on: Boolean, content: @Composable () -> Unit) {
    if (!on) return content()
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = MaterialTheme.colorScheme.surface.copy(alpha = 0.82f),
    ) { content() }
}

@Composable
private fun Note(item: ChatItem.Note, operator: Boolean, actions: ChatActions) {
    val resendLabel = stringResource(R.string.chat_resend)
    val resend = item.resendLocalId
    Column(Modifier.fillMaxWidth().padding(horizontal = 8.dp)) {
        Text(
            item.text,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            // La note dit « réessaie » : le lecteur d'écran trouve le geste sur elle aussi.
            modifier = if (resend != null) {
                Modifier.semantics {
                    customActions = listOf(CustomAccessibilityAction(resendLabel) { actions.resend(resend); true })
                }
            } else {
                Modifier
            },
        )
        if (resend != null) {
            TextButton(onClick = { actions.resend(resend) }) { Text(resendLabel) }
        }
        val href = item.href
        if (operator && href != null) {
            TextButton(onClick = { actions.openConsole(href) }) { Text(stringResource(R.string.chat_open_console)) }
        }
    }
}

@Composable
private fun Thought(m: StoredMessage) {
    val label = stringResource(R.string.chat_thought)
    Column(
        Modifier
            .fillMaxWidth()
            .padding(horizontal = 8.dp, vertical = 2.dp)
            .clearAndSetSemantics { contentDescription = "Mika, $label : ${m.text}" },
    ) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(m.text, fontStyle = FontStyle.Italic, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Bubble(item: ChatItem.Bubble, zone: ZoneId, busyFileId: String?, actions: ChatActions) {
    val m = item.message
    val mine = m.sender == Sender.USER
    val container = if (mine) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.secondaryContainer
    val content = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSecondaryContainer
    val body = BubbleContent.text(m)
    // Ce qu'on copie : le texte lu, sans les astérisques du Markdown.
    val copyText = remember(body) { InlineMarkup.plain(body) }
    val description = BubbleContent.describe(m, item.read, zone)
    val copyLabel = stringResource(R.string.chat_copy)
    val retryLabel = stringResource(R.string.chat_retry)
    val failed = mine && m.status == MessageStatus.FAILED
    val shape = if (mine) {
        RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp)
    } else {
        RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Column(
            Modifier.fillMaxWidth(0.85f),
            horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
        ) {
            Surface(shape = shape, color = container) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (m.attachments.isNotEmpty()) {
                        Attachments(m, mine, content, busyFileId, actions)
                    }
                    // Un nœud pour le lecteur d'écran : qui, quand, l'état, le texte ; copier et réessayer
                    // en actions. Les pièces jointes, au-dessus, restent chacune atteignable.
                    Column(
                        Modifier
                            .pointerInput(copyText) { detectTapGestures(onLongPress = { actions.copy(copyText) }) }
                            .clearAndSetSemantics {
                                contentDescription = description
                                customActions = buildList {
                                    if (body.isNotEmpty()) add(CustomAccessibilityAction(copyLabel) { actions.copy(copyText); true })
                                    if (failed) add(CustomAccessibilityAction(retryLabel) { actions.retry(m.localId); true })
                                }
                            },
                    ) {
                        if (body.isNotEmpty()) InlineMarkupText(body, content)
                        Row(Modifier.align(Alignment.End), verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                BubbleContent.time(m.ts, zone),
                                style = MaterialTheme.typography.labelSmall,
                                color = content.copy(alpha = 0.8f),
                            )
                            if (mine) StatusIcon(m.status, item.read, content)
                        }
                    }
                }
            }
            if (failed) {
                Text(
                    stringResource(R.string.status_failed, m.reason ?: stringResource(R.string.status_refused_default)),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
                TextButton(onClick = { actions.retry(m.localId) }) { Text(retryLabel) }
            }
        }
    }
}

@Composable
private fun StatusIcon(status: MessageStatus?, read: Boolean, tint: Color) {
    val (icon, label) = when {
        status == MessageStatus.PENDING -> R.drawable.ic_schedule to R.string.status_pending
        status == MessageStatus.FAILED -> R.drawable.ic_error to R.string.status_refused
        read -> R.drawable.ic_done_all to R.string.status_read
        else -> R.drawable.ic_done to R.string.status_sent
    }
    Spacer(Modifier.width(4.dp))
    Icon(
        painterResource(icon),
        contentDescription = stringResource(label),
        tint = tint.copy(alpha = if (status == MessageStatus.PENDING) 0.55f else 1f),
        modifier = Modifier.size(14.dp),
    )
}

@Composable
private fun Attachments(m: StoredMessage, mine: Boolean, color: Color, busyFileId: String?, actions: ChatActions) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        for (att in m.attachments) {
            if (mine) OwnAttachment(m, att, color, actions) else MikaAttachment(att, color, busyFileId, actions)
        }
    }
}

/** Une photo qu'on a envoyée : sa vignette tant que le fichier est encore sur le téléphone, sinon son nom. */
@Composable
private fun OwnAttachment(m: StoredMessage, att: MessageAttachment, color: Color, actions: ChatActions) {
    val cid = m.cid
    val local = att.local
    val file by produceState<File?>(null, cid, local) {
        value = if (cid != null && local != null && MikaFileRefs.isImage(att)) {
            withContext(Dispatchers.IO) { actions.ownFile(cid, local) }
        } else {
            null
        }
    }
    val current = file
    if (current != null) {
        AsyncImage(
            model = current,
            contentDescription = stringResource(R.string.file_image_sent, att.name),
            contentScale = ContentScale.Crop,
            modifier = Modifier.sizeIn(maxWidth = 220.dp, maxHeight = 220.dp).clip(RoundedCornerShape(12.dp)),
        )
    } else {
        FileChip(att.name, att.size?.let(AttachmentPolicy::humanSize), color, enabled = true, onClick = null)
    }
}

/** Un fichier de Mika : une vignette pour une image (touchée, elle s'agrandit), une puce sinon. */
@Composable
private fun MikaAttachment(att: MessageAttachment, color: Color, busyFileId: String?, actions: ChatActions) {
    if (MikaFileRefs.isRemoved(att)) {
        FileChip(att.name, stringResource(R.string.file_removed), color, enabled = false, onClick = null)
        return
    }
    val url = actions.imageUrl(att)
    if (MikaFileRefs.isImage(att) && url != null) {
        val label = stringResource(R.string.file_enlarge)
        AsyncImage(
            model = url,
            contentDescription = stringResource(R.string.file_image_of_mika, att.name),
            contentScale = ContentScale.Crop,
            placeholder = painterResource(R.drawable.ic_image),
            error = painterResource(R.drawable.ic_image),
            modifier = Modifier
                .sizeIn(minWidth = 96.dp, minHeight = 96.dp, maxWidth = 240.dp, maxHeight = 240.dp)
                .clip(RoundedCornerShape(12.dp))
                .clickable(onClickLabel = label) { actions.openImage(att) },
        )
        return
    }
    var menu by remember { mutableStateOf(false) }
    val busy = busyFileId != null && busyFileId == att.id
    Box {
        FileChip(
            att.name,
            att.size?.let(AttachmentPolicy::humanSize),
            color,
            enabled = !busy && MikaFileRefs.isMikaFile(att),
            onClick = { menu = true },
        )
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.file_save)) },
                onClick = {
                    menu = false
                    actions.save(att)
                },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.file_open_with)) },
                onClick = {
                    menu = false
                    actions.open(att)
                },
            )
        }
    }
}

@Composable
internal fun FileChip(name: String, detail: String?, color: Color, enabled: Boolean, onClick: (() -> Unit)?) {
    val shape = RoundedCornerShape(12.dp)
    val inner = @Composable {
        Row(
            Modifier.heightIn(min = 48.dp).padding(horizontal = 10.dp, vertical = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(painterResource(R.drawable.ic_description), contentDescription = null, tint = color, modifier = Modifier.size(20.dp))
            Column(Modifier.padding(start = 8.dp).widthIn(max = 200.dp)) {
                Text(name, color = color, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                if (detail != null) Text(detail, color = color.copy(alpha = 0.75f), style = MaterialTheme.typography.labelSmall)
            }
        }
    }
    val tone = color.copy(alpha = if (enabled) 0.12f else 0.06f)
    if (onClick != null) {
        Surface(onClick = onClick, enabled = enabled, shape = shape, color = tone) { inner() }
    } else {
        Surface(shape = shape, color = tone) { inner() }
    }
}
