package fr.qwartz.mika.ui.mail

import android.content.ClipData
import android.os.Build
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.mail.DraftFilter
import fr.qwartz.mika.data.moi.mail.DraftStates
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailDone
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailLimits
import fr.qwartz.mika.data.moi.mail.boxTitle
import fr.qwartz.mika.data.moi.mail.draftBlocked
import fr.qwartz.mika.data.moi.mail.draftPeople
import fr.qwartz.mika.data.moi.mail.draftState
import fr.qwartz.mika.data.moi.mail.holds
import fr.qwartz.mika.data.moi.mail.voiceLabel
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.AskDialog
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.ListHead
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.ToFillText
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import java.util.UUID

/** Ses brouillons, toutes boîtes, et leurs boîtes (leur nom) : la liste et la page d'un brouillon les lisent pareil. */
class MailDraftsViewModel(deps: MailDeps) : MailScreenModel(deps) {
    var drafts by mutableStateOf<Load<List<MailDraft>>>(Load.Loading)
        private set
    var boxes by mutableStateOf<List<MailBox>>(emptyList())
        private set
    var refreshing by mutableStateOf(false)
        private set
    var filter by mutableStateOf(DraftFilter.WAITING)
    var busy by mutableStateOf(false)
        private set
    /** Une relecture en cours : un brouillon pas encore dans la liste lue n'est pas encore dit « plus là ». */
    private var reloading by mutableStateOf(false)

    private val leaving = VisitOrders<Unit>()

    /** Une décision prise : la page de ce brouillon revient en arrière — celle de la visite où elle a été prise,
     *  jamais une page rouverte plus tard sur le même brouillon. */
    fun leave(visit: String): Flow<Unit> = leaving.of(visit)

    /** La page d'un brouillon s'ouvre (une rotation garde sa visite). */
    fun opened(visit: String) = leaving.open(visit)

    init {
        viewModelScope.launch {
            MailChanges.flow.collect { if (it == MailChanges.Change.Drafts) load(quiet = true) }
        }
    }

    fun load(quiet: Boolean = false) {
        if (!quiet && drafts !is Load.Ready) drafts = Load.Loading
        reloading = true
        viewModelScope.launch {
            (api.boxes() as? MoiApi.Result.Ok)?.let { boxes = it.value.boxes }
            val got = api.drafts()
            if (got is MoiApi.Result.Failed && drafts is Load.Ready) {
                if (!quiet) say(got.error)
            } else {
                drafts = Load.of(got)
            }
            reloading = false
        }
    }

    fun pull() {
        refreshing = true
        viewModelScope.launch {
            (api.boxes() as? MoiApi.Result.Ok)?.let { boxes = it.value.boxes }
            when (val got = api.drafts()) {
                is MoiApi.Result.Ok -> drafts = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (drafts is Load.Ready) say(got.error) else drafts = Load.Failed(got.error)
            }
            refreshing = false
        }
    }

    fun boxOf(key: String): MailBox? = boxes.firstOrNull { it.key == key }

    /** Un brouillon de la liste lue ; absent d'une liste lue : `404`. */
    fun one(id: String): Load<MailDraft> = when (val d = drafts) {
        Load.Loading -> Load.Loading
        is Load.Failed -> d
        is Load.Ready -> d.value.firstOrNull { it.id == id }?.let { Load.Ready(it) }
            ?: if (reloading) Load.Loading else Load.Failed(MoiError(404, GONE))
    }

    /** L'envoyer tel qu'il a été lu : le `digest` de l'aperçu montré. */
    fun send(d: MailDraft) {
        val seen = d.preview?.digest ?: return
        decide(d.id) { api.draftSend(d.id, seen) }
    }

    fun refuse(d: MailDraft, note: String) = decide(d.id) { api.draftRefuse(d.id, note.trim()) }

    fun redo(d: MailDraft, instruction: String) = decide(d.id) { api.draftRedo(d.id, instruction.trim()) }

    /** Une décision : une à la fois ; faite, les pastilles se relisent et la page revient en arrière. */
    private fun decide(id: String, call: suspend () -> MoiApi.Result<MailDone>) {
        if (busy) return
        busy = true
        val v = leaving.visit
        viewModelScope.launch {
            when (val got = call()) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    deps.refreshBadges()
                    MailChanges.tell(MailChanges.Change.Drafts)
                    leaving.send(v, Unit)
                }
                is MoiApi.Result.Failed -> {
                    say(got.error)
                    // déjà décidé ailleurs, ou plus là : la page montre ce qu'il est devenu
                    if (got.error.conflict || got.error.gone) load(quiet = true)
                }
            }
            busy = false
        }
    }

    private companion object {
        const val GONE = "Ce brouillon n'est plus là."
    }
}

@Composable
private fun rememberDraftsModel(graph: AppGraph): MailDraftsViewModel {
    val session = rememberSessionKey(graph)
    return viewModel(key = "mail.drafts|$session") { MailDraftsViewModel(MailDeps(graph)) }
}

/** « Ses brouillons » (la maquette, `vueBrouillons`) : ce qui attend ta décision, ce qui attend leur propriétaire, ce
 *  qui est parti, ce qui est refusé ; une ligne mène à exactement ce qui partira. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MailDraftsScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val vm = rememberDraftsModel(graph)
    LaunchedEffect(vm) { vm.load(quiet = true) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.mail_her_drafts), BarNav.BACK, subtitle = stringResource(R.string.mail_drafts_all_boxes)) },
    ) { modifier ->
        Column(modifier) {
            val all = vm.drafts.valueOrNull.orEmpty()
            Row(
                Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                for ((f, label) in listOf(
                    DraftFilter.WAITING to R.string.mail_drafts_waiting,
                    DraftFilter.SENT to R.string.mail_drafts_sent,
                    DraftFilter.REFUSED to R.string.mail_drafts_refused,
                )) {
                    val n = all.count { f.holds(it) }
                    FilterChip(
                        selected = vm.filter == f,
                        onClick = { vm.filter = f },
                        label = { Text(if (n > 0) "${stringResource(label)}  $n" else stringResource(label)) },
                    )
                }
            }
            PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = Modifier.fillMaxSize()) {
                LoadBox(vm.drafts, onRetry = { vm.load() }) { drafts ->
                    DraftList(vm, drafts, onOpen = { shell.navigate(Route.MailDraft(it)) })
                }
            }
        }
    }
}

@Composable
private fun DraftList(vm: MailDraftsViewModel, drafts: List<MailDraft>, onOpen: (String) -> Unit) {
    val now = rememberNow()
    val shown = drafts.filter { vm.filter.holds(it) }
    val groups = when (vm.filter) {
        DraftFilter.WAITING -> listOf(
            stringResource(R.string.mail_drafts_group_yours) to shown.filter { it.decides },
            stringResource(R.string.mail_drafts_group_owner) to shown.filterNot { it.decides },
        )
        DraftFilter.SENT -> listOf(stringResource(R.string.mail_drafts_group_sent) to shown)
        DraftFilter.REFUSED -> listOf(stringResource(R.string.mail_drafts_group_refused) to shown)
    }
    LazyColumn(Modifier.fillMaxSize()) {
        if (shown.isEmpty()) {
            item(key = "empty") {
                Text(
                    stringResource(if (vm.filter == DraftFilter.WAITING) R.string.mail_drafts_none_waiting else R.string.mail_drafts_none),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(32.dp),
                )
            }
        }
        for ((title, list) in groups) {
            if (list.isEmpty()) continue
            item(key = "head:$title") { ListHead(title, pink = true) }
            items(list, key = { it.id }) { d -> DraftRow(d, vm.boxOf(d.box), vm.boxes, now) { onOpen(d.id) } }
        }
        item(key = "note") {
            Text(
                stringResource(R.string.mail_drafts_note),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(16.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DraftRow(d: MailDraft, box: MailBox?, boxes: List<MailBox>, now: Long, onClick: () -> Unit) {
    val (tone, label) = draftState(d)
    val people = draftPeople(d).joinToString(", ") { it.shown }
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp)) {
        Box(Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).background(mika.soft), contentAlignment = Alignment.Center) {
            MIcon(R.drawable.ic_m_pen, null, tint = mika.accent)
        }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    d.subject.ifBlank { stringResource(R.string.mail_no_subject) },
                    style = MaterialTheme.typography.bodyLarge,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Text(MoiDates.short(d.at, now), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Text(
                listOfNotNull(people.ifBlank { null }, box?.let { boxTitle(it, boxes) }).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            FlowRow(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Tag(label, tone)
                if (d.waiting && draftBlocked(d).isNotEmpty()) Tag(stringResource(R.string.mail_to_fill), Tone.DANGER)
            }
        }
    }
}

/** Un de ses brouillons (la maquette, `vueBrouillon`) : exactement ce qui partira, pourquoi elle l'a écrit, sa voix, le
 *  passage à compléter qui bloque l'envoi, le mail d'origine ; Refuser · Retoucher · Envoyer. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun MailDraftScreen(graph: AppGraph, id: String) {
    val shell = LocalShell.current
    val vm = rememberDraftsModel(graph)
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    // une visite par page ouverte : rouvrir le même brouillon plus tard en est une autre
    val visit = rememberSaveable(id) { UUID.randomUUID().toString() }
    LaunchedEffect(vm, visit) {
        vm.opened(visit)
        vm.load(quiet = true)
    }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm, visit) { vm.leave(visit).collect { shell.back() } }
    var refusing by rememberSaveable { mutableStateOf(false) }
    var redoing by rememberSaveable { mutableStateOf(false) }
    val load = vm.one(id)
    val d = load.valueOrNull
    val box = d?.let { vm.boxOf(it.box) }
    val copied = stringResource(R.string.mail_copied)
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = stringResource(R.string.mail_her_draft),
                nav = BarNav.BACK,
                subtitle = box?.let { boxTitle(it, vm.boxes) },
                face = false,
            ) {
                if (d != null) {
                    BarMenu(
                        buildList {
                            if (d.waiting && d.decides && d.inReplyTo.isNotBlank()) {
                                add(MenuEntry(stringResource(R.string.mail_draft_redo), R.drawable.ic_m_refresh) { redoing = true })
                            }
                            add(
                                MenuEntry(stringResource(R.string.mail_copy_text), R.drawable.ic_m_copy) {
                                    scope.launch {
                                        clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Mika", d.preview?.text ?: d.body)))
                                        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) shell.toast(copied)
                                    }
                                },
                            )
                        },
                    )
                }
            }
        },
        bottomBar = {
            if (d != null && d.waiting && d.decides) {
                Surface(color = MaterialTheme.colorScheme.surface) {
                    Column(Modifier.navigationBarsPadding()) {
                        HorizontalDivider()
                        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            TextButton(onClick = { refusing = true }, enabled = !vm.busy, colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
                                Text(stringResource(R.string.mail_draft_refuse))
                            }
                            OutlinedButton(onClick = { shell.navigate(Route.MailCompose("edit", draft = d.id)) }, enabled = !vm.busy, modifier = Modifier.weight(1f)) {
                                MIcon(R.drawable.ic_m_pen, null, size = 18.dp)
                                Spacer(Modifier.width(6.dp))
                                Text(stringResource(R.string.mail_draft_edit), maxLines = 1)
                            }
                            Button(onClick = { vm.send(d) }, enabled = !vm.busy && d.preview != null && draftBlocked(d).isEmpty(), modifier = Modifier.weight(1f)) {
                                MIcon(R.drawable.ic_m_send, null, size = 18.dp)
                                Spacer(Modifier.width(6.dp))
                                Text(stringResource(R.string.mail_send), maxLines = 1)
                            }
                        }
                    }
                }
            }
        },
    ) { modifier ->
        LoadBox(load, onRetry = { vm.load() }, modifier = modifier) { draft ->
            DraftBody(draft, box, vm.boxes, modifier, onOriginal = { shell.navigate(Route.MailMessage(it)) })
        }
    }
    if (refusing && d != null) {
        AskDialog(
            title = stringResource(R.string.mail_draft_refuse_title),
            lede = stringResource(R.string.mail_draft_refuse_lede, d.subject.ifBlank { stringResource(R.string.mail_no_subject) }),
            label = stringResource(R.string.mail_draft_refuse_label),
            placeholder = stringResource(R.string.mail_draft_refuse_hint),
            confirm = stringResource(R.string.mail_draft_refuse),
            required = false,
            max = MailLimits.NOTE,
            danger = true,
            onDismiss = { refusing = false },
        ) { note ->
            refusing = false
            vm.refuse(d, note)
        }
    }
    if (redoing && d != null) {
        AskDialog(
            title = stringResource(R.string.mail_draft_redo),
            lede = stringResource(R.string.mail_draft_redo_lede),
            label = stringResource(R.string.mail_draft_redo_label),
            placeholder = stringResource(R.string.mail_draft_redo_hint),
            confirm = stringResource(R.string.mail_draft_redo_confirm),
            required = true,
            max = MailLimits.INSTRUCTION,
            danger = false,
            onDismiss = { redoing = false },
        ) { instruction ->
            redoing = false
            vm.redo(d, instruction)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DraftBody(d: MailDraft, box: MailBox?, boxes: List<MailBox>, modifier: Modifier, onOriginal: (String) -> Unit) {
    val now = rememberNow()
    val scheme = MaterialTheme.colorScheme
    val (tone, label) = draftState(d)
    val blocked = draftBlocked(d)
    Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 16.dp)) {
        FlowRow(
            Modifier.padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 10.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Tag(label, tone)
            voiceLabel(d.voice).takeIf { it.isNotBlank() }?.let { Tag(it, Tone.MIKA, R.drawable.ic_m_sparkle) }
            if (d.waiting && blocked.isNotEmpty()) Tag(stringResource(R.string.mail_to_fill), Tone.DANGER)
        }
        Text(
            stringResource(if (d.asked) R.string.mail_draft_why_asked else R.string.mail_draft_why_herself),
            style = MaterialTheme.typography.bodyMedium,
            color = scheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 16.dp),
        )
        Text(
            stringResource(
                when (d.state) {
                    DraftStates.WAITING -> R.string.mail_draft_exact
                    DraftStates.SENT -> R.string.mail_draft_gone
                    else -> R.string.mail_draft_text
                },
            ),
            style = MaterialTheme.typography.labelLarge,
            color = scheme.onSurfaceVariant,
            modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 8.dp),
        )
        // exactement ce qui partira : l'aperçu tant qu'il attend, sinon ce qu'il porte
        val p = d.preview
        Surface(
            shape = RoundedCornerShape(16.dp),
            border = BorderStroke(1.dp, mika.line),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
        ) {
            Column {
                Column(Modifier.fillMaxWidth().background(mika.soft).padding(horizontal = 14.dp, vertical = 10.dp)) {
                    val sender = p?.sender?.ifBlank { null } ?: box?.address
                    if (!sender.isNullOrBlank()) HeadLine(stringResource(R.string.mail_from), sender)
                    HeadLine(stringResource(R.string.mail_to), p?.to?.ifBlank { null } ?: d.to.ifBlank { "—" })
                    val cc = p?.cc?.ifBlank { null } ?: d.cc
                    if (cc.isNotBlank()) HeadLine(stringResource(R.string.mail_cc), cc)
                    HeadLine(stringResource(R.string.mail_subject), p?.subject?.ifBlank { null } ?: d.subject)
                }
                HorizontalDivider(color = mika.line)
                ToFillText(p?.text ?: d.body, Modifier.padding(14.dp))
            }
        }
        if (d.inReplyTo.isNotBlank()) {
            val o = d.original
            Row(
                Modifier.fillMaxWidth().clickable { onOriginal(d.inReplyTo) }.padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                PersonAvatar(o?.from ?: "?", o?.from ?: d.inReplyTo, 32.dp)
                Spacer(Modifier.width(12.dp))
                Column(Modifier.weight(1f)) {
                    Text(
                        if (o != null) stringResource(R.string.mail_draft_in_reply_to, o.from) else stringResource(R.string.mail_draft_original),
                        style = MaterialTheme.typography.bodyMedium,
                        fontWeight = FontWeight.Medium,
                    )
                    if (o != null) Text(o.subject.ifBlank { stringResource(R.string.mail_no_subject) }, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                MIcon(R.drawable.ic_m_chev_right, null, size = 20.dp, tint = scheme.onSurfaceVariant)
            }
        }
        when {
            d.waiting && blocked.isNotEmpty() -> NoteBox(stringResource(R.string.mail_draft_blocked, blocked), R.drawable.ic_m_alert, Modifier.padding(16.dp), Tone.WARN)
            d.waiting && !d.decides -> NoteBox(
                stringResource(R.string.mail_draft_owner_decides, box?.ownerName?.ifBlank { null } ?: stringResource(R.string.mail_its_owner)),
                R.drawable.ic_m_lock,
                Modifier.padding(16.dp),
            )
            !d.waiting -> {
                val decided = if (d.decidedAt > 0) " · " + MoiDates.dayAndClock(d.decidedAt, now) else ""
                val note = if (d.note.isNotBlank()) " " + stringResource(R.string.mail_draft_note, d.note) else ""
                Text(
                    label.replaceFirstChar { it.uppercase() } + decided + "." + note,
                    style = MaterialTheme.typography.bodyMedium,
                    color = scheme.onSurfaceVariant,
                    modifier = Modifier.padding(16.dp),
                )
            }
        }
        if (d.waiting && d.decides) {
            Text(
                stringResource(R.string.mail_draft_learns),
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
    }
}
