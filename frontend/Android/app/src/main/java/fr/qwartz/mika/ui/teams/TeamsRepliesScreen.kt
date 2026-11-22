package fr.qwartz.mika.ui.teams

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.map
import fr.qwartz.mika.data.moi.teams.Kinds
import fr.qwartz.mika.data.moi.teams.ReplyStates
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.accountTitle
import fr.qwartz.mika.data.moi.teams.decidable
import fr.qwartz.mika.data.moi.teams.decides
import fr.qwartz.mika.data.moi.teams.modeLabel
import fr.qwartz.mika.data.moi.teams.replyBlocked
import fr.qwartz.mika.data.moi.teams.replyState
import fr.qwartz.mika.data.moi.teams.replyText
import fr.qwartz.mika.data.moi.teams.retouched
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.ToFillText
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.launch

/** Ses réponses dans tes comptes (ADR 0191), la plus récente d'abord, et tes comptes (qui décide de chacune). */
class TeamsRepliesViewModel(deps: TeamsDeps) : TeamsScreenModel(deps) {
    var replies by mutableStateOf<Load<List<TeamsReply>>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set

    fun load(quiet: Boolean = false) {
        if (!quiet && replies !is Load.Ready) replies = Load.Loading
        viewModelScope.launch { read(quiet) }
    }

    fun pull() {
        refreshing = true
        viewModelScope.launch {
            read(quiet = false)
            refreshing = false
        }
    }

    private suspend fun read(quiet: Boolean) {
        // le niveau de chaque compte décide de ce que les cartes offrent (décider ou non) : ses comptes d'abord
        loadAccounts()
        val got = api.replies().map { items -> items.distinctBy { it.id } }
        if (got is MoiApi.Result.Failed && replies is Load.Ready) {
            if (!quiet) say(got.error)
        } else {
            replies = Load.of(got)
        }
    }

    override suspend fun afterDecision(r: TeamsReply, redo: Boolean) = read(quiet = true)
}

/**
 * « Ses brouillons » de Teams (la maquette, `vueBrouillons`) : une carte par réponse — sa conversation, son texte, son
 * état, demandée ou d'elle-même, son heure. Toucher une carte ouvre sa discussion ; celle qui attend ta décision se
 * décide aussi d'ici (Refuser · Retoucher · Envoyer).
 */
@Composable
fun TeamsRepliesScreen(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: TeamsRepliesViewModel = viewModel(key = "teams.replies|$session") { TeamsRepliesViewModel(TeamsDeps(graph)) }
    LaunchedEffect(vm) { vm.load(quiet = true) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    var asking by remember { mutableStateOf<Pair<Ask, TeamsReply>?>(null) }
    val accounts = vm.accountList
    SectionScaffold(
        topBar = {
            MikaTopBar(
                title = stringResource(R.string.teams_her_replies),
                nav = BarNav.BACK,
                subtitle = accounts.singleOrNull()?.let { stringResource(R.string.teams_replies_sub, accountTitle(it)) }
                    ?: stringResource(R.string.teams_replies_sub_all),
            )
        },
    ) { modifier ->
        PullToRefreshBox(isRefreshing = vm.refreshing, onRefresh = vm::pull, modifier = modifier) {
            LoadBox(vm.replies, onRetry = { vm.load() }) { replies ->
                ReplyList(
                    replies = replies,
                    accounts = accounts,
                    busy = vm.deciding,
                    onOpen = { shell.navigate(Route.TeamsThread(it.conversation)) },
                    onAsk = { a, r -> asking = a to r },
                    onSend = vm::sendReply,
                )
            }
        }
    }
    asking?.let { (a, r) -> ReplyAskDialog(a, r, vm) { asking = null } }
}

@Composable
private fun ReplyList(
    replies: List<TeamsReply>,
    accounts: List<TeamsAccount>,
    busy: Boolean,
    onOpen: (TeamsReply) -> Unit,
    onAsk: (Ask, TeamsReply) -> Unit,
    onSend: (TeamsReply) -> Unit,
) {
    val now = rememberNow()
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (replies.isEmpty()) {
            item(key = "empty") {
                Text(
                    stringResource(R.string.teams_replies_none),
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(16.dp),
                )
            }
        }
        items(replies, key = { it.id }) { r ->
            val a = accounts.firstOrNull { it.key == r.account }
            ReplyItem(r, a, busy, now, onOpen = { onOpen(r) }, onAsk = { onAsk(it, r) }, onSend = { onSend(r) })
        }
        item(key = "note") {
            Text(
                stringResource(R.string.teams_replies_note),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 4.dp, vertical = 8.dp),
            )
        }
    }
}

/** Une carte (`.card.mk`) : sa discussion, demandée ou d'elle-même et quand, ce qu'elle a écrit (ce qui est parti, ou
 *  exactement ce qui partira), où ça en est, comment ça part ; la note de qui l'a refusée, ce qu'elle avait écrit
 *  quand ce qui est parti a été retouché. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ReplyItem(r: TeamsReply, account: TeamsAccount?, busy: Boolean, now: Long, onOpen: () -> Unit, onAsk: (Ask) -> Unit, onSend: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    // sur un compte qu'on te partage, celle qui attend attend son propriétaire, pas toi
    val (tone, label) = replyState(r, decides = decides(account))
    val source = stringResource(if (r.asked) R.string.teams_asked_by_you else R.string.teams_by_herself)
    Surface(
        onClick = onOpen,
        shape = RoundedCornerShape(16.dp),
        color = mika.soft,
        border = BorderStroke(1.dp, mika.line),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                ConversationAvatar(r.title, Kinds.OTHER, r.conversation, 28.dp)
                Spacer(Modifier.width(10.dp))
                Text(
                    r.title.ifBlank { stringResource(R.string.teams_discussion) },
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = FontWeight.Medium,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Text("$source · ${MoiDates.short(r.at, now)}", style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant)
            }
            val text = replyText(r)
            if (text.isNotBlank()) {
                Gap(8.dp)
                ToFillText("« $text »")
            }
            Gap(8.dp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Tag(label, tone)
                modeLabel(r.mode).takeIf { it.isNotBlank() }?.let { Tag(stringResource(R.string.teams_mode, it), Tone.NEUTRAL) }
            }
            if (r.note.isNotBlank()) {
                Gap(6.dp)
                Text(stringResource(R.string.teams_note, r.note), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            }
            if (r.state == ReplyStates.SENT && retouched(r) && r.sentText.isNotBlank() && r.body.isNotBlank()) {
                Gap(6.dp)
                Text(stringResource(R.string.teams_she_wrote, r.body), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            }
            if (decidable(r, account)) {
                val blocked = replyBlocked(r)
                if (blocked.isNotEmpty()) {
                    Gap(8.dp)
                    NoteBox(stringResource(R.string.teams_card_blocked, blocked), R.drawable.ic_m_alert, tone = Tone.WARN)
                }
                Gap(6.dp)
                ReplyButtons(r, busy, onAsk, onSend)
            } else if (r.waiting && !r.answered && account != null && !decides(account)) {
                // un compte qu'on te partage : comme la carte du fil, qui décide
                Gap(6.dp)
                Text(
                    stringResource(R.string.teams_card_owner_decides, account.ownerName.ifBlank { stringResource(R.string.teams_its_owner) }),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                )
            }
        }
    }
}
