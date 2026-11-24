package fr.qwartz.mika.ui.teams

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AndroidClock
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.initials
import fr.qwartz.mika.data.moi.teams.Kinds
import fr.qwartz.mika.data.moi.teams.ReplyStates
import fr.qwartz.mika.data.moi.teams.TeamsAccount
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.data.moi.teams.TeamsApi
import fr.qwartz.mika.data.moi.teams.TeamsDone
import fr.qwartz.mika.data.moi.teams.TeamsLimits
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.moi.teams.cardState
import fr.qwartz.mika.data.moi.teams.decidable
import fr.qwartz.mika.data.moi.teams.decides
import fr.qwartz.mika.data.moi.teams.isGroup
import fr.qwartz.mika.data.moi.teams.replyBlocked
import fr.qwartz.mika.data.moi.teams.replyState
import fr.qwartz.mika.data.moi.teams.replyText
import fr.qwartz.mika.data.moi.teams.sentUnder
import fr.qwartz.mika.ui.shell.AskDialog
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.ToFillText
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Ce que les écrans de Teams partagent (ADR 0235, la maquette `ecrans/teams.js`) : l'API, ses comptes, les décisions
 * sur ses réponses (une clé d'envoi par geste), la carte rose d'une réponse, le rond d'une conversation, les petites
 * fenêtres (refuser, retoucher, la reprendre).
 */

/** Teams sur l'API du téléphone ; « Corriger » par le client qui attend la fin d'une correction. */
internal fun AppGraph.teamsApi(): TeamsApi = TeamsApi(moi, moiCorrect)

/** Ce que les écrans de Teams prennent de la session : l'API, relire les pastilles, l'heure. Un test JVM les donne sans
 *  le graphe de l'app. */
class TeamsDeps(
    val api: TeamsApi,
    val refreshBadges: () -> Unit = {},
    val now: () -> Long = AndroidClock::wallMs,
) {
    constructor(graph: AppGraph) : this(graph.teamsApi(), { graph.me.refresh() }, graph.clock::wallMs)
}

/**
 * Ce que tous les écrans de Teams ont : l'API, ses comptes (leur niveau décide de ce qui s'offre), le sort d'un geste
 * à dire (l'écran le montre en toast), et les décisions sur ses réponses — une à la fois, une clé d'envoi par geste ;
 * faites, les pastilles se relisent ([afterDecision] : ce que l'écran relit de plus).
 */
abstract class TeamsScreenModel(protected val deps: TeamsDeps) : ViewModel() {
    protected val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des gestes, une fois chacun. */
    val said: Flow<String> = notices.receiveAsFlow()

    protected fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    protected fun say(error: MoiError) = say(error.said)

    /** Ses comptes ; `null` : pas encore lus (rien ne s'offre de plus que lire). */
    var accounts by mutableStateOf<TeamsAccounts?>(null)
        protected set

    val accountList: List<TeamsAccount> get() = accounts?.accounts.orEmpty()

    fun account(key: String): TeamsAccount? = accountList.firstOrNull { it.key == key }

    /** Ses comptes relus ; une lecture qui échoue garde les derniers connus. */
    protected suspend fun loadAccounts(): MoiApi.Result<TeamsAccounts> {
        val got = api.accounts()
        if (got is MoiApi.Result.Ok) accounts = got.value
        return got
    }

    /** Une décision en cours (ses boutons s'éteignent). */
    var deciding by mutableStateOf(false)
        private set
    private val decisionKey = SendKey()

    /** L'envoyer telle qu'elle a été lue : le `digest` de l'aperçu montré. */
    fun sendReply(r: TeamsReply) {
        val seen = r.preview?.digest ?: return
        decide(r, listOf("send", r.id, seen)) { api.replySend(r.id, seen, it) }
    }

    fun refuse(r: TeamsReply, note: String) =
        decide(r, listOf("refuse", r.id, note.trim())) { api.replyRefuse(r.id, note.trim(), it) }

    fun edit(r: TeamsReply, body: String) =
        decide(r, listOf("edit", r.id, body.trim())) { api.replyEdit(r.id, body.trim(), it) }

    fun redo(r: TeamsReply, instruction: String) =
        decide(r, listOf("redo", r.id, instruction.trim())) { api.replyRedo(r.id, instruction.trim(), it) }

    private fun decide(r: TeamsReply, content: List<String>, call: suspend (String) -> MoiApi.Result<TeamsDone>) {
        if (deciding) return
        deciding = true
        val key = decisionKey.of(content)
        viewModelScope.launch {
            val got = call(key)
            decisionKey.settled(networkFailure = got is MoiApi.Result.Failed && got.error.network)
            when (got) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    deps.refreshBadges()
                    afterDecision(r, redo = content.first() == "redo")
                }
                is MoiApi.Result.Failed -> {
                    say(got.error)
                    // déjà décidée ailleurs, ou plus là : l'écran montre ce qu'elle est devenue
                    if (got.error.conflict || got.error.gone) afterDecision(r, redo = false)
                }
            }
            deciding = false
        }
    }

    /** Ce que l'écran relit après une décision ([redo] : elle en écrit une autre, on la guette). */
    protected abstract suspend fun afterDecision(r: TeamsReply, redo: Boolean)
}

// ── Les petites formes ──────────────────────────────────────────────────

/** Le rond d'une conversation : la personne d'un tête-à-tête, un carré pour un groupe, l'agenda pour une réunion. */
@Composable
internal fun ConversationAvatar(title: String, kind: String, key: String, size: Dp = 40.dp) {
    if (!isGroup(kind)) {
        PersonAvatar(title.ifBlank { "?" }, title.ifBlank { key }, size)
        return
    }
    val scheme = MaterialTheme.colorScheme
    Box(
        Modifier.size(size).clip(RoundedCornerShape(size * 0.3f)).background(scheme.secondaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        val letters = initials(title.replace(Regex("""[^\p{L}\p{N}\s]"""), "")).takeIf { it != "?" }
        when {
            kind == Kinds.MEETING -> MIcon(R.drawable.ic_m_calendar, null, size = size * 0.5f, tint = scheme.onSecondaryContainer)
            letters != null -> Text(letters, color = scheme.onSecondaryContainer, fontWeight = FontWeight.SemiBold, fontSize = (size.value * 0.36f).sp)
            else -> MIcon(R.drawable.ic_m_users, null, size = size * 0.5f, tint = scheme.onSecondaryContainer)
        }
    }
}

/** Ce qu'on demande avant une décision : une note pour refuser, ta version, une consigne pour la reprendre. */
internal enum class Ask { REFUSE, EDIT, REDO }

/** La fenêtre d'une décision ; [onDone] la referme. */
@Composable
internal fun ReplyAskDialog(ask: Ask, r: TeamsReply, vm: TeamsScreenModel, onDone: () -> Unit) {
    when (ask) {
        Ask.REFUSE -> AskDialog(
            title = stringResource(R.string.teams_refuse_title),
            lede = stringResource(R.string.teams_refuse_lede, r.body.take(140)),
            label = stringResource(R.string.teams_refuse_label),
            placeholder = stringResource(R.string.teams_refuse_hint),
            confirm = stringResource(R.string.teams_refuse),
            required = false,
            max = TeamsLimits.NOTE,
            danger = true,
            onDismiss = onDone,
        ) { note ->
            onDone()
            vm.refuse(r, note)
        }
        Ask.REDO -> AskDialog(
            title = stringResource(R.string.teams_redo),
            lede = stringResource(R.string.teams_redo_lede),
            label = stringResource(R.string.teams_redo_label),
            placeholder = stringResource(R.string.teams_redo_hint),
            confirm = stringResource(R.string.teams_redo_confirm),
            required = true,
            max = TeamsLimits.INSTRUCTION,
            danger = false,
            onDismiss = onDone,
        ) { instruction ->
            onDone()
            vm.redo(r, instruction)
        }
        Ask.EDIT -> EditReplyDialog(r.body, onDismiss = onDone) { body ->
            onDone()
            vm.edit(r, body)
        }
    }
}

/** Retoucher sa réponse : ta version remplace la sienne (elle apprendra de la différence), sans sa signature. */
@Composable
private fun EditReplyDialog(body: String, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var text by rememberSaveable { mutableStateOf(body) }
    var empty by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.teams_edit_title)) },
        text = {
            Column {
                Text(stringResource(R.string.teams_edit_lede), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Gap(12.dp)
                OutlinedTextField(
                    value = text,
                    onValueChange = {
                        if (chars(it) <= TeamsLimits.BODY) text = it
                        empty = false
                    },
                    label = { Text(stringResource(R.string.teams_edit_label)) },
                    minLines = 4,
                    maxLines = 10,
                    isError = empty,
                    supportingText = { Text(stringResource(if (empty) R.string.teams_edit_empty else R.string.teams_edit_note)) },
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = {
            TextButton(onClick = { if (text.isBlank()) empty = true else onSave(text) }) { Text(stringResource(R.string.teams_edit_confirm)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** Refuser · Retoucher · Envoyer : ce que tu décides d'une réponse qui attend (Envoyer : telle qu'elle a été lue). */
@Composable
internal fun ReplyButtons(r: TeamsReply, busy: Boolean, onAsk: (Ask) -> Unit, onSend: () -> Unit) {
    val blocked = replyBlocked(r)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End), verticalAlignment = Alignment.CenterVertically) {
        TextButton(onClick = { onAsk(Ask.REFUSE) }, enabled = !busy, colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error)) {
            Text(stringResource(R.string.teams_refuse), maxLines = 1)
        }
        OutlinedButton(onClick = { onAsk(Ask.EDIT) }, enabled = !busy) {
            Text(stringResource(R.string.teams_edit), maxLines = 1)
        }
        Button(onClick = onSend, enabled = !busy && r.preview != null && blocked.isEmpty()) {
            MIcon(R.drawable.ic_m_send, null, size = 16.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.teams_send), maxLines = 1)
        }
    }
}

/**
 * Sa réponse en carte rose, au-dessus du champ de sa conversation (la maquette, `.approval`) : ce qu'elle a préparé et
 * où ça en est. Qui l'attend décide d'ici (Refuser · Retoucher · Envoyer, « Lui demander de la reprendre » dans ⋮) ;
 * sur un compte qu'on te partage, son propriétaire décide. Répondu autrement : elle ne partira pas, la carte le dit
 * (ADR 0199).
 */
@Composable
internal fun ReplyCard(r: TeamsReply, account: TeamsAccount?, busy: Boolean, now: Long, onAsk: (Ask) -> Unit, onSend: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val decide = decidable(r, account)
    val title = stringResource(
        when {
            r.answered -> R.string.teams_card_answered
            r.state == ReplyStates.WAITING -> R.string.teams_card_waiting
            r.state == ReplyStates.PLACED -> R.string.teams_card_placed
            else -> R.string.teams_card_queued
        },
    )
    // sur un compte qu'on te partage, elle attend son propriétaire, et ce qui part, part sous son nom
    val sub = when {
        r.answered -> listOf(replyState(r).second, MoiDates.clock(r.decidedAt.takeIf { it > 0 } ?: r.at))
        r.state == ReplyStates.WAITING -> listOf(replyState(r, decides = decides(account)).second, MoiDates.short(r.at, now))
        else -> listOf(cardState(r, under = sentUnder(account)).second, MoiDates.short(r.at, now))
    }.filter { it.isNotBlank() }.joinToString(" · ")
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = scheme.surface,
        border = BorderStroke(1.dp, mika.line),
        shadowElevation = 2.dp,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 14.dp, vertical = 12.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                MIcon(R.drawable.ic_m_pen, null, size = 20.dp, tint = mika.accent, modifier = Modifier.padding(top = 1.dp))
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                    if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                }
                if (decide && r.inReplyTo.isNotBlank()) CardMenu(onRedo = { onAsk(Ask.REDO) }, enabled = !busy)
            }
            val text = replyText(r)
            if (text.isNotBlank()) {
                Gap(8.dp)
                Box(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(mika.soft).padding(horizontal = 10.dp, vertical = 8.dp)) {
                    ToFillText(text)
                }
            }
            val blocked = replyBlocked(r)
            when {
                r.answered -> {
                    Gap(8.dp)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_check, null, size = 16.dp, tint = scheme.onSurfaceVariant)
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.teams_card_answered_why), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                    }
                }
                decide -> {
                    if (blocked.isNotEmpty()) {
                        Gap(8.dp)
                        NoteBox(stringResource(R.string.teams_card_blocked, blocked), R.drawable.ic_m_alert, tone = Tone.WARN)
                    }
                    Gap(8.dp)
                    ReplyButtons(r, busy, onAsk, onSend)
                }
                r.waiting -> {
                    Gap(8.dp)
                    Text(
                        stringResource(R.string.teams_card_owner_decides, account?.ownerName?.ifBlank { null } ?: stringResource(R.string.teams_its_owner)),
                        style = MaterialTheme.typography.bodySmall,
                        color = scheme.onSurfaceVariant,
                    )
                }
            }
        }
    }
}

/** Le « ⋮ » d'une carte : lui demander de la reprendre (celle-ci refusée, elle en écrit une autre). */
@Composable
private fun CardMenu(onRedo: () -> Unit, enabled: Boolean) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }, enabled = enabled, modifier = Modifier.size(32.dp)) {
            MIcon(R.drawable.ic_m_more, stringResource(R.string.shell_more), size = 20.dp)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.teams_redo)) },
                leadingIcon = { MIcon(R.drawable.ic_m_refresh, null, size = 20.dp) },
                onClick = {
                    open = false
                    onRedo()
                },
            )
        }
    }
}
