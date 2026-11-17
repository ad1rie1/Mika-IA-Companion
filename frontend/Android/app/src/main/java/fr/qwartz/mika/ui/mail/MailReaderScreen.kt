package fr.qwartz.mika.ui.mail

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Caps
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.caps
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailPiece
import fr.qwartz.mika.data.moi.mail.ReadOnOpen
import fr.qwartz.mika.data.moi.mail.answerable
import fr.qwartz.mika.data.moi.mail.attachmentKind
import fr.qwartz.mika.data.moi.mail.boxTitle
import fr.qwartz.mika.data.moi.mail.draftState
import fr.qwartz.mika.data.moi.mail.howLabel
import fr.qwartz.mika.data.moi.mail.moveTargets
import fr.qwartz.mika.data.moi.mail.shareSentence
import fr.qwartz.mika.data.moi.mail.sizeLabel
import fr.qwartz.mika.data.moi.mail.toLine
import fr.qwartz.mika.data.moi.mail.voiceLabel
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaLine
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import java.util.UUID

/** Une réponse demandée : relire ses brouillons à ce rythme, tant que la liseuse reste sur le mail… */
private const val ASK_POLL_MS = 10_000L
/** …et au plus si longtemps (elle travaille à son prochain moment, qui peut tarder). */
private const val ASK_POLL_MAX_MS = 30 * 60_000L

/** Ce que la liseuse demande à son écran : revenir à la liste, ouvrir son brouillon. */
sealed interface ReaderOrder {
    data object Back : ReaderOrder
    data class OpenDraft(val id: String) : ReaderOrder
}

/**
 * La liseuse d'un mail (`Route.MailMessage`) : le mail entier, ses boîtes (son niveau, quand il devient lu), et son
 * brouillon pour ce mail s'il y en a un. Les gestes de « ranger » se disent à la liste ([MailChanges]). Le modèle sert
 * tous les mails de la session : un geste qui répond après qu'on a changé de mail ne pose rien sur le suivant, et ses
 * ordres ne suivent que l'écran de la visite où il a commencé.
 */
class MailReaderViewModel(deps: MailDeps) : MailScreenModel(deps) {
    var ref by mutableStateOf("")
        private set
    var mail by mutableStateOf<Load<MailFull>>(Load.Loading)
        private set
    var boxes by mutableStateOf<MailBoxes?>(null)
        private set
    /** Son brouillon qui attend pour ce mail. */
    var draft by mutableStateOf<MailDraft?>(null)
        private set
    /** Une réponse demandée, pas encore écrite (« Elle s'y met… »). */
    var asked by mutableStateOf(false)
        private set
    var busy by mutableStateOf(false)
        private set

    private val orders = VisitOrders<ReaderOrder>()

    /** Ce que l'écran de [visit] doit suivre : un geste qui le sort de la vue (archivé, corbeille, déplacé, non lu)
     *  ramène à la liste ; « Préremplir » qui trouve un brouillon l'ouvre. */
    fun orders(visit: String): Flow<ReaderOrder> = orders.of(visit)

    private var job: Job? = null

    fun open(r: String, visit: String) {
        orders.open(visit)
        if (r == ref && mail is Load.Ready) {
            load(quiet = true)
            return
        }
        ref = r
        mail = Load.Loading
        draft = null
        asked = false
        load(quiet = false)
    }

    fun retry() {
        mail = Load.Loading
        load(quiet = false)
    }

    private fun load(quiet: Boolean) {
        job?.cancel()
        val r = ref
        job = viewModelScope.launch {
            (api.boxes() as? MoiApi.Result.Ok)?.let { boxes = it.value }
            val got = api.message(r)
            if (r != ref) return@launch
            if (got is MoiApi.Result.Failed && quiet && mail is Load.Ready) return@launch
            mail = Load.of(got)
            val m = (got as? MoiApi.Result.Ok)?.value ?: return@launch
            val her = m.her
            asked = her?.asked == true && her.draft.isBlank()
            draft = her?.draft?.takeIf { it.isNotBlank() }?.let { findDraft(it) }
        }
    }

    private suspend fun findDraft(id: String): MailDraft? =
        (api.drafts() as? MoiApi.Result.Ok)?.value?.firstOrNull { it.id == id && it.waiting }

    val full: MailFull? get() = mail.valueOrNull?.takeIf { it.ref == ref }

    val box: MailBox? get() = full?.let { m -> boxes?.boxes?.firstOrNull { it.key == m.box } }

    val caps: Caps get() = caps(box?.level ?: Levels.READ)

    /** Dans combien de temps il devient lu (`read_on_open`, ADR 0175) ; `null` : pas de geste à poser. */
    val readDelay: Long?
        get() {
            val m = full ?: return null
            if (m.seen || !answerable(m) || !caps.write) return null
            return ReadOnOpen.delayMs(boxes?.readOnOpen.orEmpty())
        }

    /** Le « lu » posé de lui-même à l'ouverture : un échec ne se dit pas (ce n'est pas un geste de toi). */
    fun markRead() {
        val m = full ?: return
        if (m.seen) return
        viewModelScope.launch {
            if (api.tidy(listOf(m.ref), "read") is MoiApi.Result.Ok) {
                if (full?.ref == m.ref) mail = Load.Ready(m.copy(seen = true))
                MailChanges.tell(MailChanges.Change.Tidied(listOf(m.ref), "read"))
            }
        }
    }

    /** Un geste de « ranger » ; ceux qui le sortent de la vue ramènent à la liste. */
    fun tidy(gesture: String, folder: String = "") {
        val m = full ?: return
        if (busy) return
        busy = true
        val v = orders.visit
        viewModelScope.launch {
            when (val got = api.tidy(listOf(m.ref), gesture, folder)) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    MailChanges.tell(MailChanges.Change.Tidied(listOf(m.ref), gesture))
                    // la liseuse est passée à un autre mail entre-temps : celui-ci ne se pose pas sur lui
                    val still = full?.ref == m.ref
                    when (gesture) {
                        "flag", "unflag" -> if (still) mail = Load.Ready(m.copy(flagged = gesture == "flag"))
                        "read" -> if (still) mail = Load.Ready(m.copy(seen = true))
                        else -> orders.send(v, ReaderOrder.Back)
                    }
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
            busy = false
        }
    }

    /** « Préremplir avec Mika » : un brouillon qui attend déjà s'ouvre (si l'écran de ce mail est encore là) ; sinon
     *  elle l'écrira. */
    fun prefill(askedText: String) {
        val m = full ?: return
        if (busy) return
        busy = true
        val v = orders.visit
        viewModelScope.launch {
            when (val got = api.prefill(m.ref)) {
                is MoiApi.Result.Ok -> {
                    val id = got.value.draft
                    if (id.isNotBlank()) {
                        val found = findDraft(id)
                        if (ref == m.ref) draft = found
                        say(got.value.message)
                        orders.send(v, ReaderOrder.OpenDraft(id))
                    } else {
                        if (ref == m.ref) asked = true
                        say(if (got.value.message == ALREADY) got.value.message else askedText)
                    }
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
            busy = false
        }
    }

    /** Relit ses brouillons : sa réponse est-elle arrivée ? */
    suspend fun checkAsked(arrived: String): Boolean {
        val r = ref
        val d = (api.drafts() as? MoiApi.Result.Ok)?.value?.firstOrNull { it.inReplyTo == r && it.waiting } ?: return false
        if (r != ref) return true
        draft = d
        asked = false
        say(arrived)
        MailChanges.tell(MailChanges.Change.Drafts)
        return true
    }

    private companion object {
        /** Ce que le serveur dit d'une demande déjà en cours (`app/me/mail.py::prefill`). */
        const val ALREADY = "Elle y travaille déjà."
    }
}

/** La liseuse (la maquette, `vueLire`) : objet, marques, expéditeur, « Ce qu'elle en sait », le texte, ses pièces, son
 *  brouillon ; en haut, ranger ; en bas, répondre, transférer, et « Préremplir avec Mika ». Le HTML du mail
 *  (`/mail/frame`) n'est pas montré : son texte l'est. */
@Composable
fun MailReaderScreen(graph: AppGraph, ref: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: MailReaderViewModel = viewModel(key = "mail.reader|$session") { MailReaderViewModel(MailDeps(graph)) }
    // une visite par mail ouvert : rouvrir le même mail plus tard en est une autre (une rotation garde la sienne)
    val visit = rememberSaveable(ref) { UUID.randomUUID().toString() }
    LaunchedEffect(ref, visit) { vm.open(ref, visit) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm, visit) {
        vm.orders(visit).collect {
            when (it) {
                ReaderOrder.Back -> shell.back()
                is ReaderOrder.OpenDraft -> shell.navigate(Route.MailDraft(it.id))
            }
        }
    }
    val m = vm.full?.takeIf { it.ref == ref }
    val load = if (vm.ref == ref) vm.mail else Load.Loading
    var moving by remember { mutableStateOf(false) }

    // lu à l'ouverture, selon `read_on_open` — seulement tant qu'il est à l'écran, l'app au premier plan
    val delayMs = vm.readDelay
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(ref, m?.seen, delayMs) {
        if (m == null || delayMs == null) return@LaunchedEffect
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            delay(delayMs)
            vm.markRead()
        }
    }
    // une réponse demandée : ses brouillons se relisent jusqu'à ce qu'elle arrive
    val arrived = stringResource(R.string.mail_prefill_arrived)
    LaunchedEffect(ref, vm.asked) {
        if (!vm.asked) return@LaunchedEffect
        var waited = 0L
        while (waited < ASK_POLL_MAX_MS) {
            delay(ASK_POLL_MS)
            waited += ASK_POLL_MS
            if (vm.checkAsked(arrived)) break
        }
    }

    val c = vm.caps
    val canAnswer = m != null && c.write && answerable(m)
    val askedText = stringResource(R.string.mail_prefill_asked)
    SectionScaffold(
        topBar = {
            MikaTopBar(title = "", nav = BarNav.BACK, face = false) {
                if (m != null && c.write) {
                    BarAction(R.drawable.ic_m_archive, stringResource(R.string.mail_archive), { vm.tidy("archive") })
                    BarAction(R.drawable.ic_m_trash, stringResource(R.string.mail_trash), { vm.tidy("trash") })
                    if (m.seen) {
                        BarAction(R.drawable.ic_m_mail, stringResource(R.string.mail_mark_unread), { vm.tidy("unread") })
                    } else {
                        BarAction(R.drawable.ic_m_check, stringResource(R.string.mail_mark_read), { vm.tidy("read") })
                    }
                    BarMenu(
                        buildList {
                            add(MenuEntry(stringResource(if (m.flagged) R.string.mail_unflag else R.string.mail_flag), R.drawable.ic_m_flag) { vm.tidy(if (m.flagged) "unflag" else "flag") })
                            add(MenuEntry(stringResource(R.string.mail_move), R.drawable.ic_m_folder) { moving = true })
                            if (canAnswer) add(MenuEntry(stringResource(R.string.mail_reply_all), R.drawable.ic_m_reply_all) { shell.navigate(Route.MailCompose("reply_all", ref = m.ref)) })
                        },
                    )
                }
            }
        },
        bottomBar = {
            if (m != null && (c.write || c.prepare)) {
                ReaderActions(
                    canAnswer = canAnswer,
                    canForward = c.write,
                    canPrefill = c.prepare && !m.sent && vm.draft == null && !vm.asked,
                    busy = vm.busy,
                    onReply = { shell.navigate(Route.MailCompose("reply", ref = m.ref)) },
                    onForward = { shell.navigate(Route.MailCompose("forward", ref = m.ref)) },
                    onPrefill = { vm.prefill(askedText) },
                )
            }
        },
    ) { modifier ->
        LoadBox(load, onRetry = vm::retry, modifier = modifier) { mail ->
            ReaderBody(
                m = mail,
                box = vm.box,
                boxes = vm.boxes?.boxes.orEmpty(),
                draft = vm.draft,
                asked = vm.asked,
                canAnswer = canAnswer,
                graph = graph,
                modifier = modifier,
                onReply = { shell.navigate(Route.MailCompose("reply", ref = mail.ref)) },
                onDraft = { shell.navigate(Route.MailDraft(it)) },
            )
        }
    }
    val box = vm.box
    if (moving && m != null && box != null) {
        FolderPicker(box, moveTargets(box, m.folder), onPick = { f -> moving = false; vm.tidy("move", f.name) }, onDismiss = { moving = false })
    }
}

@Composable
private fun ReaderActions(
    canAnswer: Boolean,
    canForward: Boolean,
    canPrefill: Boolean,
    busy: Boolean,
    onReply: () -> Unit,
    onForward: () -> Unit,
    onPrefill: () -> Unit,
) {
    Surface(color = MaterialTheme.colorScheme.surface) {
        Column(Modifier.navigationBarsPadding()) {
            HorizontalDivider()
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (canAnswer) {
                    OutlinedButton(onClick = onReply, modifier = Modifier.weight(1f)) {
                        MIcon(R.drawable.ic_m_reply, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.mail_reply), maxLines = 1)
                    }
                }
                if (canForward) {
                    OutlinedButton(onClick = onForward, modifier = Modifier.weight(1f)) {
                        MIcon(R.drawable.ic_m_forward, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.mail_forward), maxLines = 1)
                    }
                }
                if (canPrefill) {
                    FilledTonalButton(
                        onClick = onPrefill,
                        enabled = !busy,
                        colors = ButtonDefaults.filledTonalButtonColors(containerColor = mika.container, contentColor = mika.onContainer),
                        modifier = if (canAnswer || canForward) Modifier else Modifier.weight(1f),
                    ) {
                        MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(if (canAnswer || canForward) R.string.mail_prefill_short else R.string.mail_prefill), maxLines = 1)
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ReaderBody(
    m: MailFull,
    box: MailBox?,
    boxes: List<MailBox>,
    draft: MailDraft?,
    asked: Boolean,
    canAnswer: Boolean,
    graph: AppGraph,
    modifier: Modifier,
    onReply: () -> Unit,
    onDraft: (String) -> Unit,
) {
    val now = rememberNow()
    val scheme = MaterialTheme.colorScheme
    val her = m.her
    Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 16.dp)) {
        if (box != null && !box.own) {
            NoteBox(
                stringResource(R.string.mail_shared_banner, ofName(box.ownerName.ifBlank { stringResource(R.string.mail_its_owner) }), shareSentence(box.level, box.ownerName)),
                R.drawable.ic_m_lock,
                Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
        }
        Text(
            m.subject.ifBlank { stringResource(R.string.mail_no_subject) },
            style = MaterialTheme.typography.headlineSmall.copy(fontSize = 22.sp, lineHeight = 28.sp),
            modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 6.dp),
        )
        FlowRow(
            Modifier.padding(horizontal = 16.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            if (her?.needsReply == true) Tag(stringResource(R.string.mail_needs_reply), Tone.WARN)
            if (box != null) Tag(boxTitle(box, boxes), Tone.NEUTRAL)
            if (her?.important == true) Tag(stringResource(R.string.mail_important), Tone.NEUTRAL, R.drawable.ic_m_star)
            if (m.flagged) Tag(stringResource(R.string.mail_flagged), Tone.INFO, R.drawable.ic_m_flag)
            if (m.answered) Tag(stringResource(R.string.mail_answered), Tone.NEUTRAL)
            if (m.sent) Tag(stringResource(R.string.mail_sent_from_yours), Tone.NEUTRAL, R.drawable.ic_m_send)
        }
        // l'expéditeur, à qui, quand
        val from = m.from.shown.ifBlank { stringResource(R.string.mail_no_sender) }
        Row(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            PersonAvatar(from, m.from.address)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(from, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                val addr = m.from.address.takeIf { it.isNotBlank() && it != from }
                Text(
                    listOfNotNull(addr, MoiDates.dayAndClock(m.date, now)).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (canAnswer) BarAction(R.drawable.ic_m_reply, stringResource(R.string.mail_reply), onReply)
        }
        val to = toLine(m, box)
        val cc = m.cc.joinToString(", ") { it.shown }
        if (to.isNotBlank() || cc.isNotBlank()) {
            Text(
                listOf(to, if (cc.isNotBlank()) "cc $cc" else "").filter { it.isNotBlank() }.joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
                modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 8.dp),
            )
        }
        // ce qu'elle en sait (en rose)
        val knows = her != null && (her.summary.isNotBlank() || her.noticed || her.read || asked)
        if (knows) {
            Surface(
                shape = RoundedCornerShape(16.dp),
                color = mika.soft,
                border = BorderStroke(1.dp, mika.line),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
            ) {
                Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
                    val state = when {
                        her.read -> " · " + howLabel(her.how).first
                        her.noticed -> " · " + stringResource(R.string.mail_her_noticed)
                        else -> ""
                    }
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.mail_her_knows) + state, style = MaterialTheme.typography.labelLarge, color = mika.accent)
                    }
                    if (her.summary.isNotBlank()) {
                        Gap(6.dp)
                        Text(her.summary, style = MaterialTheme.typography.bodyMedium)
                    }
                    if (asked && draft == null) {
                        Gap(6.dp)
                        Text(stringResource(R.string.mail_her_working), style = MaterialTheme.typography.bodySmall, color = mika.accent)
                    }
                }
            }
        }
        // le texte du mail
        Gap(8.dp)
        when {
            m.body.isNotBlank() -> MailBodyText(m.body, Modifier.padding(horizontal = 16.dp, vertical = 6.dp))
            m.html -> NoteBox(stringResource(R.string.mail_html_only), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp))
            else -> Text(stringResource(R.string.mail_no_text), color = scheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp))
        }
        if (!m.complete) {
            Gap(8.dp)
            NoteBox(stringResource(R.string.mail_partial), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp))
        }
        if (m.attachments.isNotEmpty()) {
            Gap(12.dp)
            Pieces(m.ref, m.attachments, graph)
        }
        if (draft != null) {
            Gap(12.dp)
            val (_, state) = draftState(draft)
            MikaLine(
                icon = R.drawable.ic_m_pen,
                title = stringResource(R.string.mail_her_reply_ready),
                subtitle = listOf(state, MoiDates.short(draft.at, now), voiceLabel(draft.voice)).filter { it.isNotBlank() }.joinToString(" · "),
                onClick = { onDraft(draft.id) },
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
    }
}

/** Ses pièces jointes : chacune s'enregistre dans Téléchargements, ou s'ouvre avec une autre application. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Pieces(ref: String, pieces: List<MailPiece>, graph: AppGraph) {
    val shell = LocalShell.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val files = remember(graph) { MailFiles(context, graph) { shell.toast(it) } }
    var busy by remember { mutableStateOf<String?>(null) }
    fun run(part: String, block: suspend () -> Unit) {
        if (busy != null) return
        busy = part
        scope.launch {
            try {
                block()
            } finally {
                busy = null
            }
        }
    }
    FlowRow(
        Modifier.padding(horizontal = 16.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        for (p in pieces) key(p.part) {
            var menu by remember { mutableStateOf(false) }
            Box {
                Surface(
                    onClick = { menu = true },
                    shape = RoundedCornerShape(12.dp),
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                    modifier = Modifier.widthIn(min = 150.dp, max = 280.dp),
                ) {
                    Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (busy == p.part) {
                            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        } else {
                            val image = p.mime.startsWith("image/")
                            MIcon(if (image) R.drawable.ic_m_image else R.drawable.ic_m_file, null, size = 20.dp, tint = MaterialTheme.colorScheme.error)
                        }
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(p.name.ifBlank { stringResource(R.string.mail_piece_unnamed) }, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(
                                listOf(attachmentKind(p.name, p.mime), sizeLabel(p.size)).filter { it.isNotBlank() }.joinToString(" · "),
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                }
                DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.mail_piece_save)) },
                        leadingIcon = { MIcon(R.drawable.ic_m_download, null, size = 20.dp) },
                        onClick = {
                            menu = false
                            run(p.part) { files.save(ref, p) }
                        },
                    )
                    DropdownMenuItem(
                        text = { Text(stringResource(R.string.file_open_with)) },
                        leadingIcon = { MIcon(R.drawable.ic_m_external, null, size = 20.dp) },
                        onClick = {
                            menu = false
                            run(p.part) { files.open(ref, p) }
                        },
                    )
                }
            }
        }
    }
}
