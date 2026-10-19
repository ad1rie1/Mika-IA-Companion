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
import fr.qwartz.mika.data.chat.ChatSync
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.FrameCodec
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.FilterChip
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
import fr.qwartz.mika.ui.components.ProMarkdown
import fr.qwartz.mika.ui.components.ProMarkdownText
import fr.qwartz.mika.data.chat.WorkCard
import fr.qwartz.mika.data.chat.WorkStep
import fr.qwartz.mika.data.chat.WorkText
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontFamily
import fr.qwartz.mika.ui.avatar.AvatarFace
import fr.qwartz.mika.ui.avatar.LoadedPortrait
import fr.qwartz.mika.ui.components.MikaAvatar
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.time.ZoneId
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.BlendMode
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.CompositingStrategy
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.layout.positionInRoot
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Dp
import fr.qwartz.mika.avatar3d.Utterance
import fr.qwartz.mika.ui.avatar.rememberReducedMotion
import kotlin.math.PI
import kotlin.math.sin

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
    /** Juger une de ses réponses (ADR 0113) : `ok`, `ko`, ou vide pour retirer l'avis ; puis ce qu'elle aurait dû dire. */
    val judge: (messageId: Long, verdict: String, comment: String) -> Unit = { _, _, _ -> },
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
 * Ce que le fil sait de Mika quand elle se tient derrière lui : où commence son visage, ce qu'elle est en train de
 * dire, et à qui signaler qu'on relit l'historique (elle s'efface alors).
 */
class StageLink(
    /** Depuis le haut de l'écran, la place que demande son visage : les bulles s'effacent avant. */
    val faceClearance: Dp,
    /** Ce qu'elle dit (la 3D seulement : un portrait n'a pas de bouche qui bouge). */
    val track: SpeechTrack?,
    val onReadingHistory: (Boolean) -> Unit,
)

/**
 * Le fil, du plus ancien (en haut) au plus récent (en bas). Une liste à l'envers : l'arrivée d'un
 * message reste collée en bas ; remontée dans l'historique, une puce « ↓ N nouveaux » compte ce qui
 * arrive et y ramène.
 *
 * Avec Mika derrière ([stage]), le fil et elle se partagent l'écran : au repos, les derniers messages tiennent dans
 * une bande en bas et s'effacent en montant, avant son visage ; remonter dans l'historique rend tout l'écran au texte,
 * et elle se met en retrait.
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
    stage: StageLink? = null,
    /** Ce qu'un refus a dit d'un avis sur une de ses réponses, par message (ADR 0113). */
    verdictErrors: Map<Long, String> = emptyMap(),
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
    val density = LocalDensity.current
    val reversed = remember(items) { items.asReversed() }
    val atBottom by remember { derivedStateOf { listState.firstVisibleItemIndex <= 1 } }
    // Relire l'historique : quitter vraiment le bas du fil, pas l'effleurer.
    val readingHistory by remember {
        derivedStateOf {
            listState.firstVisibleItemIndex > 0 ||
                listState.firstVisibleItemScrollOffset > with(density) { HISTORY_THRESHOLD.toPx() }
        }
    }
    LaunchedEffect(readingHistory, stage) { stage?.onReadingHistory?.invoke(readingHistory) }
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
    // Sa carte de travail qui apparaît en bas du fil (ADR 0116) : on la suit, si l'on y était.
    val workAtBottom = (items.lastOrNull() as? ChatItem.Work)?.key
    LaunchedEffect(workAtBottom) { if (workAtBottom != null && atBottom) listState.animateScrollToItem(0) }

    var ownTop by remember { mutableFloatStateOf(Float.NaN) }
    BoxWithConstraints(modifier.fillMaxWidth().onGloballyPositioned { ownTop = it.positionInRoot().y }) {
        // La bande du fil quand elle est là : sous son visage, au moins MIN_BAND, environ deux cinquièmes de la place.
        val inset = if (stage == null || ownTop.isNaN()) {
            0.dp
        } else {
            val top = with(density) { ownTop.toDp() }
            val bottom = top + maxHeight
            val band = maxOf(MIN_BAND, maxHeight * BAND_SHARE)
            val boundary = minOf(maxOf(stage.faceClearance, bottom - band), bottom - MIN_BAND)
            (boundary - FADE_HEIGHT - top).coerceAtLeast(0.dp)
        }
        val topInset by animateDpAsState(
            if (readingHistory) 0.dp else inset,
            spring(stiffness = Spring.StiffnessMediumLow),
            label = "band",
        )
        LazyColumn(
            state = listState,
            reverseLayout = true,
            verticalArrangement = Arrangement.spacedBy(4.dp),
            contentPadding = PaddingValues(start = 12.dp, end = 12.dp, top = if (stage != null) FADE_HEIGHT else 8.dp, bottom = 8.dp),
            // Toute la hauteur : un fil court part du bas, comme dans une messagerie (sinon il se colle en
            // haut — sur son visage quand elle est en fond).
            modifier = Modifier
                .fillMaxSize()
                .padding(top = topInset)
                .then(if (stage != null) Modifier.fadeTop(FADE_HEIGHT) else Modifier),
        ) {
            items(reversed, key = { it.key }) { item ->
                Box(Modifier.animateItem(fadeInSpec = tween(220), fadeOutSpec = tween(160))) {
                    when (item) {
                        is ChatItem.DateSeparator -> Centered(item.label, overPortrait, heading = true)
                        ChatItem.TruncatedNote -> Centered(stringResource(R.string.chat_truncated), overPortrait)
                        is ChatItem.Bubble -> Bubble(
                            item,
                            zone,
                            busyFileId,
                            actions,
                            utterance = stage?.track?.of(item.key),
                            onSkip = { stage?.track?.skip(item.key) },
                            operator = operator,
                            verdictError = item.message.id?.let { verdictErrors[it] },
                        )
                        is ChatItem.Note -> Backed(overPortrait) { Note(item, operator, actions) }
                        is ChatItem.Looked -> LookedChip(item, zone, overPortrait)
                        is ChatItem.Thought -> Backed(overPortrait) { Thought(item.message) }
                        is ChatItem.SystemNote -> Centered(item.text, overPortrait)
                        is ChatItem.Work -> WorkCardView(item, overPortrait)
                        ChatItem.Typing -> TypingBubble()
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

/** Au-delà de ce défilement depuis le bas, on relit l'historique. */
private val HISTORY_THRESHOLD = 24.dp

/** La bande du fil, quand elle est là : jamais moins, quoi que demande son visage. */
private val MIN_BAND = 168.dp

/** …et sinon cette part de la hauteur du fil : assez pour quelques bulles, assez peu pour la voir jusqu'aux mains. */
private const val BAND_SHARE = 0.42f

/** Le haut de la bande, où les bulles s'effacent en montant vers elle. */
private val FADE_HEIGHT = 40.dp

/** Le haut du contenu s'efface sur `height` : une bulle qui monte vers son visage se dissout au lieu d'être coupée. */
private fun Modifier.fadeTop(height: Dp): Modifier = this
    .graphicsLayer { compositingStrategy = CompositingStrategy.Offscreen }
    .drawWithContent {
        drawContent()
        drawRect(
            Brush.verticalGradient(listOf(Color.Transparent, Color.Black), startY = 0f, endY = height.toPx()),
            blendMode = BlendMode.DstIn,
        )
    }

/**
 * « Mika écrit… » : une bulle à elle, aux trois points qui respirent, là où sa réponse va s'écrire. Le lecteur
 * d'écran entend la phrase, une fois.
 */
@Composable
private fun TypingBubble() {
    val label = stringResource(R.string.chat_typing)
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Surface(
            shape = RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp),
            color = MaterialTheme.colorScheme.secondaryContainer,
            modifier = Modifier.semantics {
                contentDescription = label
                liveRegion = LiveRegionMode.Polite
            },
        ) {
            TypingDots(MaterialTheme.colorScheme.onSecondaryContainer, Modifier.padding(horizontal = 14.dp, vertical = 12.dp))
        }
    }
}

/** Trois points qui montent et descendent l'un après l'autre (immobiles si l'on a coupé les animations). */
@Composable
private fun TypingDots(color: Color, modifier: Modifier = Modifier) {
    val motion = !rememberReducedMotion()
    val phase = if (motion) {
        rememberInfiniteTransition(label = "dots").animateFloat(
            0f, 1f, infiniteRepeatable(tween(1_100, easing = LinearEasing)), label = "dotsPhase",
        )
    } else {
        remember { mutableFloatStateOf(0f) }
    }
    Canvas(modifier.size(width = 34.dp, height = 10.dp).clearAndSetSemantics { }) {
        val r = size.height * 0.32f
        for (i in 0 until 3) {
            val t = ((phase.value - i * 0.18f) % 1f + 1f) % 1f
            val lift = if (t < 0.5f) sin(t * 2 * PI).toFloat() else 0f
            drawCircle(
                color.copy(alpha = 0.45f + 0.45f * lift),
                radius = r,
                center = Offset(r + i * (size.width - 2 * r) / 2, size.height / 2 - lift * size.height * 0.3f),
            )
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

/**
 * Sa petite bulle juste avant sa réponse (ADR 0119) : « 📍 Mika a regardé où tu es · lieu · position de 14:10 ». Discrète,
 * de son côté, plus petite que ses bulles ; le lieu manque une fois la position oubliée, l'heure quand elle était
 * fraîche. Le lecteur d'écran l'entend en mots, sans l'épingle.
 */
@Composable
private fun LookedChip(item: ChatItem.Looked, zone: ZoneId, overPortrait: Boolean) {
    val age = remember(item.note.at, item.messageTs, zone) { LookedNote.age(item.note.at, item.messageTs, zone) }
    val place = item.note.text.trim().takeIf { it.isNotEmpty() }
    val shownFix = when (age) {
        LookedNote.FixAge.Fresh -> null
        is LookedNote.FixAge.SameDay -> stringResource(R.string.chat_looked_fix_time, age.time)
        is LookedNote.FixAge.OtherDay -> stringResource(R.string.chat_looked_fix_day, age.date, age.time)
    }
    val saidFix = when (age) {
        LookedNote.FixAge.Fresh -> null
        is LookedNote.FixAge.SameDay -> stringResource(R.string.chat_looked_fix_time, age.spokenTime)
        is LookedNote.FixAge.OtherDay -> stringResource(R.string.chat_looked_fix_day, age.spokenDate, age.spokenTime)
    }
    val shown = listOfNotNull(stringResource(R.string.chat_looked_where), place, shownFix).joinToString(" · ")
    val said = listOfNotNull(stringResource(R.string.chat_looked_where_spoken), place, saidFix).joinToString(", ")
    Row(Modifier.fillMaxWidth().padding(top = 2.dp)) {
        Box(Modifier.fillMaxWidth(0.85f)) {
            Surface(
                shape = RoundedCornerShape(10.dp),
                color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = if (overPortrait) 0.92f else 0.85f),
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.clearAndSetSemantics { contentDescription = said },
            ) {
                Text(
                    shown,
                    style = MaterialTheme.typography.labelSmall,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
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
private fun Bubble(
    item: ChatItem.Bubble,
    zone: ZoneId,
    busyFileId: String?,
    actions: ChatActions,
    /** Sa réplique, si elle est en train de la dire : le texte s'écrit à son rythme. */
    utterance: Utterance? = null,
    onSkip: () -> Unit = {},
    /** Une opératrice : sous ses réponses, son avis (ADR 0113). */
    operator: Boolean = false,
    verdictError: String? = null,
) {
    val m = item.message
    val reveal = utterance?.let { rememberReveal(it) }
    val mine = m.sender == Sender.USER
    // Une réponse pro (ADR 0116) : une seule bulle, plus large, son Markdown rendu ; ni rythme de frappe ni voix.
    val proReply = m.isPro && !mine
    val container = if (mine) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.secondaryContainer
    val content = if (mine) MaterialTheme.colorScheme.onPrimary else MaterialTheme.colorScheme.onSecondaryContainer
    val body = item.part ?: BubbleContent.text(m)
    // Ce qu'on copie : le texte lu, sans les astérisques du Markdown.
    val copyText = remember(body, proReply) { if (proReply) ProMarkdown.plain(body) else InlineMarkup.plain(body) }
    val description = BubbleContent.describe(m, item.read, zone, item.part, item.toolsLine)
    val copyLabel = stringResource(R.string.chat_copy)
    val retryLabel = stringResource(R.string.chat_retry)
    // Ses liens, des gestes pour le lecteur d'écran (la bulle est un seul nœud).
    val links = remember(body, proReply) { if (proReply) ProMarkdown.links(body).take(MAX_LINK_ACTIONS) else emptyList() }
    val uriHandler = LocalUriHandler.current
    val openLink = stringResource(R.string.pro_open_link)
    val failed = mine && m.status == MessageStatus.FAILED
    val shape = if (mine) {
        RoundedCornerShape(16.dp, 16.dp, 4.dp, 16.dp)
    } else {
        RoundedCornerShape(16.dp, 16.dp, 16.dp, 4.dp)
    }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (mine) Arrangement.End else Arrangement.Start) {
        Column(
            Modifier.fillMaxWidth(if (proReply) 0.96f else 0.85f),
            horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
        ) {
            Surface(shape = shape, color = container) {
                Column(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    if (item.last && m.attachments.isNotEmpty()) {
                        Attachments(m, mine, content, busyFileId, actions)
                    }
                    // Un nœud pour le lecteur d'écran : qui, quand, l'état, le texte ; copier et réessayer
                    // en actions. Les pièces jointes, au-dessus, restent chacune atteignable.
                    val revealing = reveal != null
                    Column(
                        Modifier
                            .pointerInput(copyText, revealing) {
                                // Toucher une réponse qui s'écrit : tout s'affiche, elle se tait.
                                detectTapGestures(
                                    onTap = if (revealing) ({ _ -> onSkip() }) else null,
                                    onLongPress = { actions.copy(copyText) },
                                )
                            }
                            .clearAndSetSemantics {
                                contentDescription = description
                                customActions = buildList {
                                    if (body.isNotEmpty()) add(CustomAccessibilityAction(copyLabel) { actions.copy(copyText); true })
                                    if (failed) add(CustomAccessibilityAction(retryLabel) { actions.retry(m.localId); true })
                                    for ((label, url) in links) {
                                        add(CustomAccessibilityAction("$openLink : $label") { uriHandler.openUri(url); true })
                                    }
                                }
                            },
                    ) {
                        if (body.isNotEmpty()) {
                            Box {
                                if (proReply) {
                                    ProMarkdownText(body, content)
                                } else {
                                    InlineMarkupText(body, content, reveal = reveal)
                                }
                                // Une réplique qui attend son tour derrière la précédente : les trois points, à sa place.
                                if (reveal != null && reveal <= 0f) TypingDots(content, Modifier.padding(top = 6.dp))
                            }
                        }
                        // ses outils, relus de l'historique quand la carte de travail n'est plus là (ADR 0116)
                        item.toolsLine?.let { tools ->
                            Text(
                                stringResource(R.string.pro_tools_line, tools),
                                style = MaterialTheme.typography.labelSmall,
                                color = content.copy(alpha = 0.75f),
                                modifier = Modifier.padding(top = 4.dp),
                            )
                        }
                        // l'heure sous la dernière bulle d'une réponse, comme une messagerie
                        if (item.last) {
                            Row(Modifier.align(Alignment.End), verticalAlignment = Alignment.CenterVertically) {
                                if (m.isPro) ProMark(content)
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
            }
            val judged = m.id
            if (operator && item.last && !mine && !m.inner && judged != null) {
                VerdictBar(m, judged, actions, verdictError)
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

/**
 * Sous une de ses réponses, pour l'opératrice (ADR 0113) : 👍 ou 👎 (toucher de nouveau retire l'avis), et ce
 * qu'elle aurait dû dire — le champ s'ouvre de lui-même sur 👎, à la demande sur 👍. L'avis s'affiche aussitôt ;
 * un refus du serveur le remet comme avant et le dit ([error]).
 */
@Composable
private fun VerdictBar(m: StoredMessage, id: Long, actions: ChatActions, error: String?) {
    var editing by rememberSaveable(id) { mutableStateOf(false) }
    var draft by rememberSaveable(id) { mutableStateOf("") }
    val choices = listOf(
        Triple(MikaProtocol.VERDICT_OK, "👍", stringResource(R.string.verdict_ok)),
        Triple(MikaProtocol.VERDICT_KO, "👎", stringResource(R.string.verdict_ko)),
    )
    Column(Modifier.padding(top = 2.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            for ((verdict, icon, label) in choices) {
                val pressed = m.verdict == verdict
                val said = if (pressed) stringResource(R.string.verdict_withdraw, label) else label
                FilterChip(
                    selected = pressed,
                    onClick = {
                        val next = ChatSync.nextVerdict(m.verdict, verdict)
                        actions.judge(id, next, if (next.isEmpty()) "" else m.verdictNote.orEmpty())
                        editing = next == MikaProtocol.VERDICT_KO && m.verdictNote.isNullOrEmpty()
                        if (editing) draft = ""
                    },
                    label = { Text(icon) },
                    modifier = Modifier.semantics { contentDescription = said },
                )
            }
            if (m.verdict != null && !editing) {
                TextButton(onClick = {
                    draft = m.verdictNote.orEmpty()
                    editing = true
                }) {
                    Text(stringResource(if (m.verdictNote.isNullOrEmpty()) R.string.verdict_write else R.string.verdict_edit))
                }
            }
        }
        val note = m.verdictNote
        if (!note.isNullOrEmpty() && !editing) {
            Text(note, style = MaterialTheme.typography.bodySmall, fontStyle = FontStyle.Italic)
        }
        if (editing) {
            OutlinedTextField(
                value = draft,
                onValueChange = { draft = it.take(FrameCodec.MAX_COMMENT_CHARS) },
                placeholder = { Text(stringResource(R.string.verdict_placeholder)) },
                minLines = 2,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Button(onClick = {
                    m.verdict?.let { actions.judge(id, it, draft) }
                    editing = false
                }) { Text(stringResource(R.string.verdict_save)) }
                TextButton(onClick = { editing = false }) { Text(stringResource(R.string.verdict_close)) }
            }
        }
        if (error != null) {
            Text(error, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
    }
}

/** Les liens d'une réponse pro offerts en gestes au lecteur d'écran, au plus. */
private const val MAX_LINK_ACTIONS = 8

/** La petite marque « pro » d'un message écrit en mode pro (ADR 0116), à côté de l'heure ; la bulle le dit déjà. */
@Composable
private fun ProMark(color: Color) {
    Surface(
        shape = RoundedCornerShape(4.dp),
        color = color.copy(alpha = 0.16f),
        contentColor = color,
        modifier = Modifier.padding(end = 6.dp).clearAndSetSemantics { },
    ) {
        Text(
            stringResource(R.string.pro_mark),
            style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(horizontal = 5.dp),
        )
    }
}

/**
 * Sa carte de travail pendant une réponse pro (ADR 0116) : ses outils dans l'ordre — un indicateur qui tourne tant
 * qu'il travaille, ✓ ou ✗, le nom, un aperçu des arguments, la durée — et ce qu'elle écrit entre deux, en italique.
 * Toucher un outil déplie ses arguments et son résultat, en texte brut. Repliée ([ChatItem.Work.folded]) au-dessus
 * de sa réponse, elle se résume (« 4 outils · 3,2 s ») et se déplie au toucher. En mémoire seulement.
 */
@Composable
private fun WorkCardView(item: ChatItem.Work, overPortrait: Boolean) {
    val card = item.card
    // Repliée quand sa réponse arrive : l'état se refait à ce moment-là.
    var open by rememberSaveable(card.key, item.folded) { mutableStateOf(!item.folded) }
    val scheme = MaterialTheme.colorScheme
    val color = scheme.onSurfaceVariant
    val count = card.tools.size
    val tools = pluralStringResource(R.plurals.work_tools, count, count)
    val elapsed = card.elapsedMs?.let(WorkText::duration)
    val summary = if (card.running) {
        stringResource(R.string.work_running_summary, tools)
    } else {
        elapsed?.let { stringResource(R.string.work_summary, tools, it) } ?: tools
    }
    val toggleLabel = stringResource(if (open) R.string.work_collapse else R.string.work_expand)
    val title = stringResource(R.string.work_title)
    Row(Modifier.fillMaxWidth()) {
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = scheme.surfaceVariant.copy(alpha = if (overPortrait) 0.92f else 1f),
            contentColor = color,
            modifier = Modifier.fillMaxWidth(0.96f),
        ) {
            Column(Modifier.padding(horizontal = 12.dp, vertical = 6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(
                    Modifier
                        .fillMaxWidth()
                        .heightIn(min = 40.dp)
                        .clickable(onClickLabel = toggleLabel) { open = !open }
                        .semantics {
                            contentDescription = "$title : $summary"
                            if (card.running) liveRegion = LiveRegionMode.Polite
                        },
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (card.running) {
                        CircularProgressIndicator(Modifier.size(14.dp).clearAndSetSemantics { }, strokeWidth = 2.dp, color = color)
                    }
                    Text(
                        summary,
                        style = MaterialTheme.typography.labelLarge,
                        modifier = Modifier.weight(1f).clearAndSetSemantics { },
                    )
                    Text(if (open) "▾" else "▸", modifier = Modifier.clearAndSetSemantics { })
                }
                if (open) {
                    card.steps.forEachIndexed { index, step ->
                        when (step) {
                            is WorkStep.Tool -> ToolRow(card, index, step, color)
                            is WorkStep.Note -> Text(
                                step.text,
                                style = MaterialTheme.typography.bodySmall,
                                fontStyle = FontStyle.Italic,
                                modifier = Modifier.padding(vertical = 2.dp),
                            )
                        }
                    }
                    if (card.dropped > 0) {
                        Text(
                            pluralStringResource(R.plurals.work_dropped, card.dropped, card.dropped),
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                }
                val outcome = card.outcome
                if (outcome != null && outcome != MikaProtocol.TOOL_OUTCOME_DONE) {
                    Text(
                        outcomeLabel(outcome),
                        style = MaterialTheme.typography.bodySmall,
                        color = if (outcome == OUTCOME_FAILED || outcome == OUTCOME_TIMEOUT) scheme.error else color,
                        modifier = Modifier.padding(bottom = 2.dp),
                    )
                }
            }
        }
    }
}

private const val OUTCOME_FAILED = "failed"
private const val OUTCOME_TIMEOUT = "timeout"

/** L'issue d'un épisode qui n'a pas répondu normalement, en mots. */
@Composable
private fun outcomeLabel(outcome: String): String = when (outcome) {
    OUTCOME_FAILED -> stringResource(R.string.work_outcome_failed)
    OUTCOME_TIMEOUT -> stringResource(R.string.work_outcome_timeout)
    "abstained" -> stringResource(R.string.work_outcome_abstained)
    "superseded" -> stringResource(R.string.work_outcome_superseded)
    "preempted", "cancelled", "interrupted" -> stringResource(R.string.work_outcome_interrupted)
    else -> stringResource(R.string.work_outcome_other, outcome)
}

/** Une ligne d'outil ; touchée, ses arguments et son résultat, tels quels. */
@Composable
private fun ToolRow(card: WorkCard, index: Int, tool: WorkStep.Tool, color: Color) {
    var open by rememberSaveable(card.key, index) { mutableStateOf(false) }
    val running = tool.ok == null && card.running
    val status = stringResource(
        when {
            running -> R.string.work_tool_running
            tool.ok == true -> R.string.work_tool_ok
            tool.ok == false -> R.string.work_tool_failed
            else -> R.string.work_tool_unfinished
        },
    )
    val preview = remember(tool.args) { WorkText.argsPreview(tool.args) }
    val duration = tool.durationMs?.let(WorkText::duration)
    val name = tool.name.ifEmpty { "?" }
    val description = listOfNotNull(name, status, duration, preview.ifEmpty { null }).joinToString(", ")
    val toggleLabel = stringResource(if (open) R.string.work_detail_hide else R.string.work_detail_show)
    Column {
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 36.dp)
                .clickable(onClickLabel = toggleLabel) { open = !open }
                .semantics { contentDescription = description },
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Box(Modifier.size(16.dp).clearAndSetSemantics { }, contentAlignment = Alignment.Center) {
                when {
                    running -> CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 1.5.dp, color = color)
                    tool.ok == true -> Text("✓", color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.labelLarge)
                    tool.ok == false -> Text("✗", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelLarge)
                    else -> Text("–", style = MaterialTheme.typography.labelLarge)
                }
            }
            Text(
                name,
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.labelMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.widthIn(max = 160.dp).clearAndSetSemantics { },
            )
            Text(
                preview,
                style = MaterialTheme.typography.bodySmall,
                color = color.copy(alpha = 0.75f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).clearAndSetSemantics { },
            )
            if (duration != null) {
                Text(
                    duration,
                    style = MaterialTheme.typography.labelSmall,
                    color = color.copy(alpha = 0.75f),
                    modifier = Modifier.clearAndSetSemantics { },
                )
            }
        }
        if (open) {
            RawBlock(stringResource(R.string.work_args), tool.args, color)
            if (tool.ok != null) RawBlock(stringResource(R.string.work_result), tool.result, color)
        }
    }
}

/** Un texte venu d'un outil : brut, à chasse fixe, qui défile dans les deux sens — jamais interprété. */
@Composable
private fun RawBlock(label: String, text: String, color: Color) {
    Text(label, style = MaterialTheme.typography.labelSmall, color = color, modifier = Modifier.padding(top = 4.dp))
    Surface(shape = RoundedCornerShape(8.dp), color = color.copy(alpha = 0.08f), modifier = Modifier.fillMaxWidth()) {
        Box(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
            Text(
                text.ifEmpty { "—" },
                color = color,
                fontFamily = FontFamily.Monospace,
                style = MaterialTheme.typography.bodySmall,
                softWrap = false,
                modifier = Modifier.horizontalScroll(rememberScrollState()).padding(8.dp),
            )
        }
    }
}

/**
 * Combien de caractères de sa réplique sont dits, image par image, sur l'horloge qu'elle partage avec la bouche de
 * l'avatar ; null une fois tout dit (la bulle redevient un texte ordinaire). Sans animations : tout, tout de suite.
 */
@Composable
private fun rememberReveal(u: Utterance): Float? {
    val motion = !rememberReducedMotion()
    val initial = System.nanoTime().let { now -> if (motion && !u.finished(now)) u.revealAt(now) else null }
    val reveal by produceState(initial, u, motion) {
        if (initial == null) return@produceState
        while (true) {
            val now = withFrameNanos { it }
            if (u.finished(now)) {
                value = null
                break
            }
            value = u.revealAt(now)
        }
    }
    return reveal
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
