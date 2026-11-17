package fr.qwartz.mika.ui.mail

import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Caps
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.caps
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.thousands
import fr.qwartz.mika.data.moi.mail.DraftReply
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailContact
import fr.qwartz.mika.data.moi.mail.MailDone
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.mail.MailFull
import fr.qwartz.mika.data.moi.mail.MailLimits
import fr.qwartz.mika.data.moi.mail.MailPerson
import fr.qwartz.mika.data.moi.mail.Outgoing
import fr.qwartz.mika.data.moi.mail.OutgoingPiece
import fr.qwartz.mika.data.moi.mail.addPieces
import fr.qwartz.mika.data.moi.mail.answerable
import fr.qwartz.mika.data.moi.mail.boxTitle
import fr.qwartz.mika.data.moi.mail.carriedPieces
import fr.qwartz.mika.data.moi.mail.checkOutgoing
import fr.qwartz.mika.data.moi.mail.clip
import fr.qwartz.mika.data.moi.mail.draftNotWaiting
import fr.qwartz.mika.data.moi.mail.draftReply
import fr.qwartz.mika.data.moi.mail.forwardSubject
import fr.qwartz.mika.data.moi.mail.outgoingPiece
import fr.qwartz.mika.data.moi.mail.parseAddresses
import fr.qwartz.mika.data.moi.mail.replySubject
import fr.qwartz.mika.data.moi.mail.replyTargets
import fr.qwartz.mika.data.moi.mail.sizeLabel
import fr.qwartz.mika.data.moi.mail.uniquePeople
import fr.qwartz.mika.data.moi.mail.writableBoxes
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Shell
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.launch
import java.util.UUID

/** Une réponse demandée depuis « Écrire » : ses brouillons se relisent à ce rythme, au plus si longtemps. */
private const val ASK_POLL_MS = 10_000L
private const val ASK_POLL_MAX_MS = 30 * 60_000L
/** Ses correspondants proposés sous un champ : au plus tant. */
private const val SUGGESTED = 6

/** Les champs de destinataires. */
enum class RecipientField { TO, CC, BCC }

/**
 * Écrire (`Route.MailCompose`) : un mail nouveau, une réponse (à tous), un transfert, ou la retouche d'un de ses
 * brouillons. De quelle boîte, à qui (ses correspondants proposés), l'objet, le texte, citer, les pièces ; « Préremplir
 * avec Mika » en réponse. Une clé d'envoi par geste : un double appui ne part qu'une fois.
 *
 * Le modèle sert toutes les écritures de la session : ce qui répond (un chargement, « Préremplir », un envoi) ne pose
 * rien que si l'écriture qui l'a demandé est toujours là — même route, même visite.
 */
class MailComposeViewModel(deps: MailDeps) : MailScreenModel(deps) {
    var route by mutableStateOf<Route.MailCompose?>(null)
        private set
    var setup by mutableStateOf<Load<Unit>>(Load.Loading)
        private set
    var boxes by mutableStateOf<List<MailBox>>(emptyList())
        private set
    var original by mutableStateOf<MailFull?>(null)
        private set
    var editing by mutableStateOf<MailDraft?>(null)
        private set

    var from by mutableStateOf("")
        private set
    val to = mutableStateListOf<MailPerson>()
    val cc = mutableStateListOf<MailPerson>()
    val bcc = mutableStateListOf<MailPerson>()
    var toText by mutableStateOf("")
        private set
    var ccText by mutableStateOf("")
        private set
    var bccText by mutableStateOf("")
        private set
    var showCc by mutableStateOf(false)
    var showBcc by mutableStateOf(false)
    var subject by mutableStateOf("")
        private set
    var body by mutableStateOf("")
        private set
    var quote by mutableStateOf(true)
        private set
    /** Un transfert : ses pièces d'origine repartent avec lui. */
    var carry by mutableStateOf(true)
        private set
    val pieces = mutableStateListOf<OutgoingPiece>()
    var problem by mutableStateOf("")
        private set
    var sending by mutableStateOf(false)
        private set
    /** Son brouillon repris ici (son identifiant) : il partira de là, et elle apprendra ce que tu y as changé. */
    var fromDraft by mutableStateOf("")
        private set
    /** Une réponse demandée, pas encore écrite. */
    var asked by mutableStateOf(false)
        private set
    var prefilling by mutableStateOf(false)
        private set
    var suggestions by mutableStateOf<List<MailContact>>(emptyList())
        private set
    var suggestFor by mutableStateOf<RecipientField?>(null)
        private set
    /** Quelque chose a été tapé ou choisi : quitter demande confirmation. */
    var touched by mutableStateOf(false)
        private set

    private val sendKey = SendKey()
    private val unsent = deps.unsent
    private var suggestJob: Job? = null
    /** Le chargement de l'écriture ouverte : une autre ouverte, ou « Réessayer », l'arrête. */
    private var loadJob: Job? = null
    /** La visite de l'écran : une rotation garde ce qui est écrit, une nouvelle ouverture repart de rien. */
    var visit by mutableStateOf("")
        private set
    private val finishing = VisitOrders<Unit>()
    /** L'écran de la visite ouverte est là ; une rotation le quitte un instant, puis le rouvre. */
    private var shown = false

    /** Parti (ou enregistré) : l'écran de cette visite revient en arrière ; jamais celui d'une écriture ouverte après. */
    fun finished(visit: String): Flow<Unit> = finishing.of(visit)

    /** L'écriture qui a demandé est toujours celle-ci (même route, même visite) : ce qui lui répond peut s'y poser. */
    private fun current(r: Route.MailCompose, v: String): Boolean = route == r && visit == v

    /** Ce qu'Écrire dit se dit où qu'on soit : un envoi peut finir après qu'on a quitté son écran. La session fermée
     *  entre-temps, rien : le compte suivant n'entend pas le sort d'un mail d'un autre. */
    override fun say(text: String) {
        if (deps.signedIn()) deps.notices.say(text)
    }

    val mode: String get() = route?.mode ?: MODE_NEW
    val replying: Boolean get() = mode == MODE_REPLY || mode == MODE_REPLY_ALL

    fun capsOf(key: String): Caps = caps(boxes.firstOrNull { it.key == key }?.level ?: Levels.READ)

    /** Elle peut lui préparer une réponse : en réponse, sur une boîte qui le permet, jamais à un mail parti de ta boîte. */
    val canPrefill: Boolean
        get() = replying && original?.let { capsOf(it.box).prepare && !it.sent } == true && fromDraft.isEmpty()

    fun prepare(r: Route.MailCompose, visit: String) {
        shown = true
        if (route == r && this.visit == visit) return
        // le chargement de l'écriture d'avant (quittée avant d'avoir fini) ne pose rien dans celle-ci
        loadJob?.cancel()
        finishing.open(visit)
        this.visit = visit
        route = r
        setup = Load.Loading
        original = null
        editing = null
        from = ""
        to.clear()
        cc.clear()
        bcc.clear()
        toText = ""
        ccText = ""
        bccText = ""
        showCc = false
        showBcc = false
        subject = ""
        body = ""
        quote = true
        carry = true
        pieces.clear()
        problem = ""
        fromDraft = ""
        asked = false
        suggestions = emptyList()
        suggestFor = null
        touched = false
        // un envoi ou une demande de l'écriture d'avant peut courir encore : il ne retient pas celle-ci
        sending = false
        prefilling = false
        loadJob = viewModelScope.launch { load(r, visit) }
    }

    fun retry() {
        val r = route ?: return
        val v = visit
        loadJob?.cancel()
        setup = Load.Loading
        loadJob = viewModelScope.launch { load(r, v) }
    }

    /** Ce qui commence une écriture, lu avant d'être posé. */
    private sealed interface Start {
        data class From(val mail: MailFull) : Start
        data class Edit(val draft: MailDraft) : Start
        data object New : Start
        data class Refused(val error: MoiError) : Start
    }

    /** Tout se lit d'abord ; rien ne se pose (De, les destinataires, l'objet, le texte) tant que l'écriture qui l'a
     *  demandé n'est pas sûrement encore là. */
    private suspend fun load(r: Route.MailCompose, v: String) {
        val listed = api.boxes()
        if (!current(r, v)) return
        when (listed) {
            is MoiApi.Result.Ok -> boxes = listed.value.boxes
            is MoiApi.Result.Failed -> {
                setup = Load.Failed(listed.error)
                return
            }
        }
        val start: Start = when (r.mode) {
            MODE_REPLY, MODE_REPLY_ALL, MODE_FORWARD -> when (val got = api.message(r.ref)) {
                is MoiApi.Result.Failed -> Start.Refused(got.error)
                is MoiApi.Result.Ok -> Start.From(got.value)
            }
            MODE_EDIT -> when (val got = api.drafts()) {
                is MoiApi.Result.Failed -> Start.Refused(got.error)
                is MoiApi.Result.Ok -> got.value.firstOrNull { it.id == r.draft && it.waiting }?.let { Start.Edit(it) }
                    ?: Start.Refused(MoiError(404, NOT_WAITING))
            }
            else -> Start.New
        }
        if (!current(r, v)) return
        val failure: MoiError? = when (start) {
            is Start.Refused -> start.error
            is Start.From -> startFrom(start.mail, r.mode)
            is Start.Edit -> startEdit(start.draft)
            Start.New -> {
                from = writableBoxes(boxes).firstOrNull()?.key.orEmpty()
                if (from.isEmpty()) MoiError(409, NO_BOX) else null
            }
        }
        // la même écriture, quittée sans être partie (un lien profond a remplacé la pile) : ce qui était écrit revient ;
        // plus là (son brouillon décidé ailleurs, le mail parti), il n'attend plus rien
        when {
            failure == null -> unsent.take(r)?.let { restore(it) }
            failure.gone -> unsent.drop(r)
        }
        setup = failure?.let { Load.Failed(it) } ?: Load.Ready(Unit)
    }

    private fun restore(u: UnsentMail) {
        from = u.from
        to.clear()
        to.addAll(u.to)
        cc.clear()
        cc.addAll(u.cc)
        bcc.clear()
        bcc.addAll(u.bcc)
        toText = u.toText
        ccText = u.ccText
        bccText = u.bccText
        showCc = u.showCc
        showBcc = u.showBcc
        subject = u.subject
        body = u.body
        quote = u.quote
        carry = u.carry
        pieces.clear()
        pieces.addAll(u.pieces)
        fromDraft = u.fromDraft
        asked = u.asked
        touched = true
    }

    /**
     * L'écran de cette visite s'en va (un lien profond, une rotation) : ce qui est écrit et pas parti attend sa route
     * pour la session. Rien de tapé, rien de gardé ; la session fermée (l'écran s'en va parce qu'elle se ferme, après
     * l'effacement), rien non plus : le compte suivant n'en hérite pas. En plein envoi, c'est son issue qui décide :
     * refusé, il attend ; parti, plus rien (une écriture rouverte entre-temps ne le reprend pas pour le renvoyer).
     */
    fun keepUnsent(visit: String) {
        val r = route ?: return
        if (this.visit != visit) return
        shown = false
        if (!touched || sending || !deps.signedIn()) return
        unsent.keep(r, snapshot())
    }

    private fun snapshot() = UnsentMail(
        from, to.toList(), cc.toList(), bcc.toList(), toText, ccText, bccText, showCc, showBcc,
        subject, body, quote, carry, pieces.toList(), fromDraft, asked,
    )

    /** « Abandonner » confirmé : ce qui était écrit part pour de bon. */
    fun discard() {
        route?.let { unsent.drop(it) }
        touched = false
    }

    private fun startFrom(m: MailFull, mode: String): MoiError? {
        original = m
        from = m.box
        if (!capsOf(m.box).write) return MoiError(403, READ_ONLY)
        if (mode == MODE_FORWARD) {
            subject = clip(forwardSubject(m.subject), MailLimits.SUBJECT)
            carry = m.attachments.isNotEmpty()
            return null
        }
        if (!answerable(m)) return MoiError(409, NOT_ANSWERABLE)
        val box = boxes.firstOrNull { it.key == m.box }
        val (people, copies) = replyTargets(m, box?.address.orEmpty(), mode == MODE_REPLY_ALL)
        // posés, jamais ajoutés : un second chargement de la même écriture ne double personne
        to.clear()
        to.addAll(people)
        cc.clear()
        cc.addAll(copies)
        showCc = copies.isNotEmpty()
        subject = clip(replySubject(m.subject), MailLimits.SUBJECT)
        return null
    }

    private fun startEdit(d: MailDraft): MoiError? {
        editing = d
        from = d.box
        to.clear()
        to.addAll(parseAddresses(d.to))
        cc.clear()
        cc.addAll(parseAddresses(d.cc))
        showCc = cc.isNotEmpty()
        subject = d.subject
        body = d.body
        quote = d.quote
        return null
    }

    // ── Les champs ──

    fun chooseFrom(key: String) {
        from = key
        touched = true
    }

    fun editSubject(text: String) {
        subject = text
        touched = true
    }

    fun editBody(text: String) {
        body = text
        touched = true
    }

    fun chooseQuote(on: Boolean) {
        quote = on
        touched = true
    }

    fun chooseCarry(on: Boolean) {
        carry = on
        touched = true
    }

    private fun peopleOf(f: RecipientField) = when (f) {
        RecipientField.TO -> to
        RecipientField.CC -> cc
        RecipientField.BCC -> bcc
    }

    fun typedOf(f: RecipientField): String = when (f) {
        RecipientField.TO -> toText
        RecipientField.CC -> ccText
        RecipientField.BCC -> bccText
    }

    private fun setTyped(f: RecipientField, text: String) {
        when (f) {
            RecipientField.TO -> toText = text
            RecipientField.CC -> ccText = text
            RecipientField.BCC -> bccText = text
        }
    }

    /** Ce qu'on tape dans un champ : une virgule ou un point-virgule pose la puce ; sinon ses correspondants sont
     *  proposés. */
    fun type(f: RecipientField, text: String) {
        touched = true
        if (text.endsWith(",") || text.endsWith(";")) {
            commit(f, text.dropLast(1))
            return
        }
        setTyped(f, text)
        suggest(f, text.trim())
    }

    /** Ce qui est tapé, s'il vaut une adresse, devient une puce ; rend faux si ce n'en est pas une. */
    fun commit(f: RecipientField, text: String = typedOf(f)): Boolean {
        val found = parseAddresses(text)
        if (found.isEmpty()) {
            setTyped(f, text)
            return text.isBlank()
        }
        add(f, found)
        setTyped(f, "")
        clearSuggestions()
        return true
    }

    fun pick(f: RecipientField, c: MailContact) {
        add(f, listOf(MailPerson(c.name, c.address)))
        setTyped(f, "")
        clearSuggestions()
    }

    fun remove(f: RecipientField, p: MailPerson) {
        peopleOf(f).remove(p)
        touched = true
    }

    private fun add(f: RecipientField, people: List<MailPerson>) {
        val list = peopleOf(f)
        val merged = uniquePeople(list + people)
        list.clear()
        list.addAll(merged)
        touched = true
    }

    private fun clearSuggestions() {
        suggestJob?.cancel()
        suggestions = emptyList()
        suggestFor = null
    }

    private fun suggest(f: RecipientField, text: String) {
        suggestJob?.cancel()
        if (text.isEmpty() || chars(text) > MailLimits.CONTACTS) {
            clearSuggestions()
            return
        }
        suggestJob = viewModelScope.launch {
            delay(SUGGEST_DEBOUNCE_MS)
            val got = api.contacts(text, SUGGESTED + 4)
            // pas deux fois la même personne : ce qui est déjà en puce n'est plus proposé
            val chosen = (to + cc + bcc).mapTo(HashSet()) { it.address.lowercase() }
            suggestions = (got as? MoiApi.Result.Ok)?.value.orEmpty().filter { it.address.lowercase() !in chosen }.take(SUGGESTED)
            suggestFor = f
        }
    }

    // ── Les pièces ──

    /** Joindre : dans les bornes de l'API (25 Mo par pièce, dix pièces, 50 Mo, celles d'un transfert comprises). */
    fun addPicked(picked: List<OutgoingPiece>, unreadable: String) {
        val carried = if (mode == MODE_FORWARD && carry) original?.let { carriedPieces(it) }.orEmpty() else emptyList()
        val got = addPieces(pieces.toList(), picked, carried)
        pieces.clear()
        pieces.addAll(got.pieces)
        problem = got.problem.ifEmpty { unreadable }
        touched = true
    }

    fun removePiece(p: OutgoingPiece) {
        pieces.remove(p)
        problem = ""
    }

    // ── Préremplir ──

    fun prefill(askedText: String, takenText: String) {
        val m = original ?: return
        val r = route ?: return
        val v = visit
        if (prefilling) return
        prefilling = true
        viewModelScope.launch {
            val got = api.prefill(m.ref)
            if (got is MoiApi.Result.Ok) MailChanges.tell(MailChanges.Change.Drafts)
            val id = (got as? MoiApi.Result.Ok)?.value?.draft.orEmpty()
            // l'écriture qui l'a demandé est partie (une autre ouverte depuis) : son brouillon ne se pose pas ailleurs
            if (!current(r, v)) return@launch
            val d = if (id.isNotBlank()) findDraft(id) else null
            if (!current(r, v)) return@launch
            when (got) {
                is MoiApi.Result.Ok -> {
                    when {
                        d != null -> {
                            take(d)
                            say(takenText)
                        }
                        id.isNotBlank() -> say(got.value.message)
                        else -> {
                            asked = true
                            say(if (got.value.message == ALREADY) got.value.message else askedText)
                        }
                    }
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
            prefilling = false
        }
    }

    private suspend fun findDraft(id: String): MailDraft? =
        (api.drafts() as? MoiApi.Result.Ok)?.value?.firstOrNull { it.id == id && it.waiting }

    /** Son brouillon, repris dans ta réponse ; ce que tu y avais joint, et ta copie cachée, ne se perdent pas. */
    private fun take(d: MailDraft) {
        val m = original ?: return
        val people = parseAddresses(d.to).ifEmpty { replyTargets(m, boxes.firstOrNull { it.key == m.box }?.address.orEmpty(), false).first }
        to.clear()
        to.addAll(people)
        cc.clear()
        cc.addAll(parseAddresses(d.cc))
        showCc = cc.isNotEmpty() || showCc
        subject = clip(d.subject.ifBlank { replySubject(m.subject) }, MailLimits.SUBJECT)
        body = d.body
        quote = d.quote
        fromDraft = d.id
        asked = false
        touched = true
    }

    /** « Effacer » ce qu'elle avait écrit : ta réponse repart de rien. */
    fun dropDraft() {
        fromDraft = ""
        body = ""
    }

    /** Une réponse demandée : est-elle arrivée ? Reprise si tu n'as rien écrit, sinon dite. */
    suspend fun checkAsked(arrived: String, waiting: String): Boolean {
        val m = original ?: return true
        val r = route ?: return true
        val v = visit
        val d = (api.drafts() as? MoiApi.Result.Ok)?.value?.firstOrNull { it.inReplyTo == m.ref && it.waiting } ?: return false
        if (!current(r, v)) return true
        if (body.isBlank()) {
            take(d)
            say(arrived)
        } else {
            asked = false
            say(waiting)
        }
        return true
    }

    // ── Envoyer ──

    /** Ce qui part, lu au moment d'envoyer : la suite ne relit plus l'écran, qu'une autre écriture a pu reprendre. */
    private class Sending(
        val route: Route.MailCompose,
        val from: String,
        val mail: Outgoing,
        val quote: Boolean,
        val carry: Boolean,
        val files: List<OutgoingPiece>,
        val fromDraft: String,
        val decide: Boolean,
        val editing: MailDraft?,
    )

    /**
     * Envoyer (ou enregistrer ta version). [notSent] : ce que dit un refus, en toast, même l'écran quitté — le motif
     * du serveur, et si ce qui était écrit attend qu'on rouvre la même écriture ([left] : son écran est parti).
     */
    fun send(notAnAddress: (String) -> String, notSent: (reason: String, left: Boolean) -> String) {
        val r = route ?: return
        val v = visit
        if (sending || setup !is Load.Ready) return
        for (f in RecipientField.entries) {
            val typed = typedOf(f)
            if (!commit(f, typed)) {
                problem = notAnAddress(typed.trim())
                return
            }
        }
        val checked = checkOutgoing(
            to.toList(), cc.toList(), bcc.toList(), subject, body,
            bodyRequired = mode != MODE_FORWARD,
            fillChecked = mode != MODE_EDIT,
        )
        val mail = checked.mail ?: run {
            problem = checked.problem
            return
        }
        problem = ""
        sending = true
        clearSuggestions()
        val key = sendKey.of(listOf(r, from, mail, quote, carry, pieces.map { it.name to it.size }))
        val what = Sending(r, from, mail, quote, carry, pieces.toList(), fromDraft, capsOf(from).decide, editing)
        val kept = snapshot()
        viewModelScope.launch {
            val got = deliver(what, key)
            sendKey.settled(networkFailure = got is MoiApi.Result.Failed && got.error.network)
            // l'écriture de cet envoi est-elle encore celle du modèle ? Sinon, rien ne se pose dans celle ouverte depuis
            val here = current(r, v)
            // son écran parti (←, une notification touchée), ce qui était écrit attend la même écriture, rouverte
            val left = !(here && shown) && deps.signedIn()
            if (here) sending = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    deps.refreshBadges()
                    MailChanges.tell(MailChanges.Change.Drafts)
                    // rien d'elle n'attend (pas gardée en plein envoi) ; ce qu'une écriture rouverte depuis a laissé
                    // n'est pas à elle : il reste
                    if (here) {
                        touched = false
                        unsent.drop(r)
                        finishing.send(v, Unit)
                    }
                }
                is MoiApi.Result.Failed -> {
                    if (left) unsent.keep(r, kept)
                    say(notSent(got.error.said, left))
                    if (here) problem = got.error.said
                }
            }
        }
    }

    private suspend fun deliver(s: Sending, key: String): MoiApi.Result<MailDone> {
        val r = s.route
        return when (r.mode) {
            MODE_REPLY, MODE_REPLY_ALL -> {
                // un brouillon part tel qu'il est lu : avec des pièces ou une copie cachée, c'est ta réponse qui part
                // (le sien est refusé dans le même geste) ; décider de ses brouillons reste à son propriétaire
                if (s.fromDraft.isNotEmpty() && s.files.isEmpty() && s.mail.bcc.isEmpty() && s.decide) {
                    throughDraft(s, key)
                } else {
                    api.reply(r.ref, s.mail, s.quote, s.files, key)
                }
            }
            MODE_FORWARD -> api.forward(r.ref, s.mail, s.carry, s.files, key)
            MODE_EDIT -> {
                val d = s.editing ?: return MoiApi.Result.Failed(MoiError(404, NOT_WAITING))
                api.draftEdit(d.id, s.mail, quote = d.inReplyTo.isNotEmpty() && s.quote, key = key)
            }
            else -> api.send(s.from, s.mail, s.files, key)
        }
    }

    /**
     * Ta réponse, partie de son brouillon : ta version d'abord (elle l'apprendra), puis l'envoi tel qu'il se lit. Son
     * brouillon se relit tel qu'il est : refusé ou plus là, ta réponse part comme une autre ; parti, approuvé ou en
     * échec, rien de plus ne part ; une lecture en panne est un échec (rien ne part, la clé reste pour réessayer).
     */
    private suspend fun throughDraft(s: Sending, key: String): MoiApi.Result<MailDone> {
        val id = s.fromDraft
        val mail = s.mail
        val listed = when (val got = api.drafts()) {
            is MoiApi.Result.Failed -> return got
            is MoiApi.Result.Ok -> got.value
        }
        val d = when (val w = draftReply(listed, id)) {
            DraftReply.Plain -> return api.reply(s.route.ref, mail, s.quote, emptyList(), key)
            is DraftReply.Stop -> return MoiApi.Result.Failed(MoiError(409, w.why))
            is DraftReply.Through -> w.draft
        }
        fun same(a: String, b: String) = parseAddresses(a).map { it.address } == parseAddresses(b).map { it.address }
        val changed = !same(d.to, mail.to) || !same(d.cc, mail.cc) || d.subject != mail.subject || d.body != mail.body || d.quote != s.quote
        if (changed) {
            val edited = api.draftEdit(id, mail, s.quote, key = "$key-edit")
            if (edited is MoiApi.Result.Failed) return edited
        }
        val now = when (val got = api.drafts()) {
            is MoiApi.Result.Failed -> return got
            is MoiApi.Result.Ok -> got.value.firstOrNull { it.id == id }
        }
        if (now == null || !now.waiting) return MoiApi.Result.Failed(MoiError(409, draftNotWaiting(now?.state.orEmpty())))
        val preview = now.preview ?: return MoiApi.Result.Failed(MoiError(409, draftNotWaiting("")))
        if (preview.blocked.isNotBlank()) return MoiApi.Result.Failed(MoiError(409, "Il ne peut pas partir tel quel : ${preview.blocked}."))
        return api.draftSend(id, preview.digest, key)
    }

    companion object {
        const val MODE_NEW = "new"
        const val MODE_REPLY = "reply"
        const val MODE_REPLY_ALL = "reply_all"
        const val MODE_FORWARD = "forward"
        const val MODE_EDIT = "edit"
        private const val SUGGEST_DEBOUNCE_MS = 150L
        private const val ALREADY = "Elle y travaille déjà."
        private const val NO_BOX = "Aucune de tes boîtes ne peut envoyer : sa connexion n'est pas prête (Paramètres › Boîtes mail)."
        private const val NOT_WAITING = "Ce brouillon n'attend plus de décision : il ne se retouche plus."
        private const val READ_ONLY = "Cette boîte ne t'est pas ouverte pour écrire."
        private const val NOT_ANSWERABLE = "On ne répond pas à un mail parti de ta boîte : transfère-le."
    }
}

/** Écrire (la maquette, `vueEcrire`) : De, À (Cc, Cci), l'objet, le texte ; joindre et envoyer en haut ;
 *  « Préremplir avec Mika » en bas, en réponse. */
@Composable
fun MailComposeScreen(graph: AppGraph, route: Route.MailCompose) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: MailComposeViewModel = viewModel(key = "mail.compose|$session") { MailComposeViewModel(MailDeps(graph)) }
    val context = LocalContext.current
    // une visite par écriture ouverte : une autre route au même endroit (un lien profond) en est une autre
    val visit = rememberSaveable(route) { UUID.randomUUID().toString() }
    LaunchedEffect(route, visit) { vm.prepare(route, visit) }
    // quittée sans envoi ni abandon (une notification, un partage vers Mika remplacent la pile) : rien ne se perd
    DisposableEffect(vm, visit) { onDispose { vm.keepUnsent(visit) } }
    // ce qu'Écrire dit passe par le cadre (`MailNotices`), pas par cet écran : un envoi fini après qu'on est parti se
    // dit quand même. Parti, l'écran de cette visite (et lui seul) revient en arrière.
    LaunchedEffect(vm, visit) { vm.finished(visit).collect { shell.back() } }
    var confirmLeave by remember { mutableStateOf(false) }
    val ours = vm.route == route && vm.visit == visit
    val stillGoing = stringResource(R.string.mail_leaving_while_sending)
    // la flèche du haut et le geste « retour » demandent avant de jeter ce qui est écrit ; en plein envoi, il n'y a
    // plus rien à abandonner : on sort, l'envoi va au bout et son sort se dit où qu'on soit
    val leave = remember(shell, vm, visit, stillGoing) {
        {
            when {
                vm.visit != visit || !vm.touched -> shell.back()
                vm.sending -> {
                    shell.toast(stillGoing)
                    shell.back()
                }
                else -> confirmLeave = true
            }
        }
    }
    val guarded = remember(shell, leave) {
        Shell(
            graph = shell.graph,
            navigate = shell.navigate,
            open = shell.open,
            replace = shell.replace,
            back = leave,
            openDrawer = shell.openDrawer,
            snackbar = shell.snackbar,
            toast = shell.toast,
        )
    }
    BackHandler(enabled = ours && vm.touched) { leave() }
    val unreadable = stringResource(R.string.mail_piece_unreadable)
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        val resolver = context.contentResolver
        val got = uris.map { resolver.outgoingPiece(it) }
        vm.addPicked(got.filterNotNull(), if (got.any { it == null }) unreadable else "")
    }
    val ready = ours && vm.setup is Load.Ready
    val title = stringResource(
        when (route.mode) {
            MailComposeViewModel.MODE_REPLY -> R.string.mail_compose_reply
            MailComposeViewModel.MODE_REPLY_ALL -> R.string.mail_compose_reply_all
            MailComposeViewModel.MODE_FORWARD -> R.string.mail_compose_forward
            MailComposeViewModel.MODE_EDIT -> R.string.mail_compose_edit
            else -> R.string.mail_compose_new
        },
    )
    val notAnAddress = stringResource(R.string.mail_not_an_address)
    val notSentText = stringResource(
        when (route.mode) {
            MailComposeViewModel.MODE_EDIT -> R.string.mail_not_saved
            MailComposeViewModel.MODE_REPLY, MailComposeViewModel.MODE_REPLY_ALL -> R.string.mail_reply_not_sent
            else -> R.string.mail_not_sent
        },
    )
    val keptText = stringResource(R.string.mail_not_sent_kept)
    val askedText = stringResource(R.string.mail_prefill_asked_here)
    val takenText = stringResource(R.string.mail_prefill_taken)
    CompositionLocalProvider(LocalShell provides guarded) {
        SectionScaffold(
            topBar = {
                MikaTopBar(title = title, nav = BarNav.BACK, face = false) {
                    if (ready && route.mode != MailComposeViewModel.MODE_EDIT) {
                        IconButton(onClick = { picker.launch(arrayOf("*/*")) }, enabled = !vm.sending) {
                            MIcon(R.drawable.ic_m_clip, stringResource(R.string.mail_attach))
                        }
                    }
                    if (vm.sending) {
                        Box(Modifier.size(48.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp) }
                    } else {
                        IconButton(
                            onClick = {
                                vm.send(
                                    notAnAddress = { notAnAddress.format(it) },
                                    notSent = { reason, left -> notSentText.format(reason) + if (left) " $keptText" else "" },
                                )
                            },
                            enabled = ready,
                        ) {
                            MIcon(
                                if (route.mode == MailComposeViewModel.MODE_EDIT) R.drawable.ic_m_check else R.drawable.ic_m_send,
                                stringResource(if (route.mode == MailComposeViewModel.MODE_EDIT) R.string.mail_save_version else R.string.mail_send),
                                tint = MaterialTheme.colorScheme.primary,
                            )
                        }
                    }
                }
            },
            bottomBar = {
                Surface(color = MaterialTheme.colorScheme.surface) {
                    Column(Modifier.navigationBarsPadding().imePadding()) {
                        if (ready && vm.canPrefill) {
                            HorizontalDivider()
                            OutlinedButton(
                                onClick = { vm.prefill(askedText, takenText) },
                                enabled = !vm.prefilling && !vm.asked,
                                border = BorderStroke(1.dp, mika.line),
                                colors = ButtonDefaults.outlinedButtonColors(contentColor = mika.accent),
                                modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 8.dp, bottom = 12.dp),
                            ) {
                                MIcon(R.drawable.ic_m_sparkle, null, size = 18.dp)
                                Spacer(Modifier.width(6.dp))
                                Text(stringResource(R.string.mail_prefill))
                            }
                        }
                    }
                }
            },
        ) { modifier ->
            LoadBox(if (ours) vm.setup else Load.Loading, onRetry = vm::retry, modifier = modifier) {
                ComposeForm(vm, modifier)
            }
        }
    }
    // une réponse demandée : ses brouillons se relisent jusqu'à ce qu'elle arrive
    val arrived = stringResource(R.string.mail_prefill_taken_arrived)
    val waiting = stringResource(R.string.mail_prefill_arrived_elsewhere)
    LaunchedEffect(route, vm.asked) {
        if (!vm.asked) return@LaunchedEffect
        var waited = 0L
        while (waited < ASK_POLL_MAX_MS) {
            delay(ASK_POLL_MS)
            waited += ASK_POLL_MS
            if (vm.checkAsked(arrived, waiting)) break
        }
    }
    // « Abandonner » ne s'offre jamais pendant un envoi : il partirait quand même
    if (confirmLeave && !vm.sending) {
        AlertDialog(
            onDismissRequest = { confirmLeave = false },
            title = { Text(stringResource(R.string.mail_discard_title)) },
            text = { Text(stringResource(R.string.mail_discard_text)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmLeave = false
                    vm.discard()
                    shell.back()
                }) { Text(stringResource(R.string.mail_discard)) }
            },
            dismissButton = { TextButton(onClick = { confirmLeave = false }) { Text(stringResource(R.string.mail_discard_keep)) } },
        )
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ComposeForm(vm: MailComposeViewModel, modifier: Modifier) {
    val scheme = MaterialTheme.colorScheme
    val editing = vm.mode == MailComposeViewModel.MODE_EDIT
    Column(modifier.verticalScroll(rememberScrollState())) {
        FromLine(vm)
        RecipientsLine(vm, RecipientField.TO, stringResource(R.string.mail_to)) {
            if (!vm.showCc) TextButton(onClick = { vm.showCc = true }) { Text(stringResource(R.string.mail_cc)) }
            if (!vm.showBcc && !editing) TextButton(onClick = { vm.showBcc = true }) { Text(stringResource(R.string.mail_bcc)) }
        }
        if (vm.showCc) RecipientsLine(vm, RecipientField.CC, stringResource(R.string.mail_cc))
        if (vm.showBcc && !editing) RecipientsLine(vm, RecipientField.BCC, stringResource(R.string.mail_bcc))
        LineField(stringResource(R.string.mail_subject)) {
            PlainField(vm.subject, vm::editSubject, stringResource(R.string.mail_subject), singleLine = true, max = MailLimits.SUBJECT)
        }
        if (vm.fromDraft.isNotEmpty()) {
            Row(
                Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, top = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.mail_draft_taken), style = MaterialTheme.typography.bodySmall, color = mika.accent, modifier = Modifier.weight(1f))
                TextButton(onClick = vm::dropDraft) { Text(stringResource(R.string.mail_draft_drop)) }
            }
        } else if (vm.asked) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.mail_her_working_here), style = MaterialTheme.typography.bodySmall, color = mika.accent)
            }
        }
        PlainField(
            vm.body,
            vm::editBody,
            stringResource(if (vm.mode == MailComposeViewModel.MODE_FORWARD) R.string.mail_body_forward_hint else R.string.mail_body_hint),
            singleLine = false,
            max = MailLimits.BODY,
            modifier = Modifier.fillMaxWidth().heightIn(min = 220.dp).padding(horizontal = 16.dp, vertical = 14.dp),
        )
        val n = chars(vm.body)
        if (n >= MailLimits.BODY * 8 / 10) {
            Text(
                "${thousands(n)} / ${thousands(MailLimits.BODY)}",
                style = MaterialTheme.typography.labelSmall,
                color = if (n >= MailLimits.BODY) scheme.error else scheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp),
            )
        }
        if (vm.pieces.isNotEmpty()) {
            FlowRow(
                Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                for (p in vm.pieces) {
                    InputChip(
                        selected = false,
                        onClick = { vm.removePiece(p) },
                        label = { Text("${p.name} · ${sizeLabel(p.size)}", maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 220.dp)) },
                        leadingIcon = { MIcon(R.drawable.ic_m_clip, null, size = 16.dp) },
                        trailingIcon = { MIcon(R.drawable.ic_m_x, stringResource(R.string.mail_piece_remove, p.name), size = 16.dp) },
                    )
                }
            }
        }
        val m = vm.original
        if (vm.mode == MailComposeViewModel.MODE_FORWARD && m != null) {
            if (m.attachments.isNotEmpty()) {
                CheckLine(pluralStringResource(R.plurals.mail_forward_pieces, m.attachments.size, m.attachments.size), vm.carry, vm::chooseCarry)
            }
            Text(stringResource(R.string.mail_forward_note), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
        }
        if (vm.replying || (editing && vm.editing?.inReplyTo?.isNotEmpty() == true)) {
            CheckLine(stringResource(R.string.mail_quote), vm.quote, vm::chooseQuote)
        }
        if (vm.problem.isNotBlank()) {
            NoteBox(vm.problem, R.drawable.ic_m_alert, Modifier.padding(16.dp), Tone.DANGER)
        }
        Gap(24.dp)
    }
}

/** « De » : la boîte d'où il part — à choisir pour un mail nouveau, imposée sinon (celle du mail, de son brouillon). */
@Composable
private fun FromLine(vm: MailComposeViewModel) {
    val box = vm.boxes.firstOrNull { it.key == vm.from }
    val choices = if (vm.mode == MailComposeViewModel.MODE_NEW) writableBoxes(vm.boxes) else emptyList()
    var open by remember { mutableStateOf(false) }
    LineField(stringResource(R.string.mail_from)) {
        Box(Modifier.weight(1f)) {
            Row(
                Modifier.fillMaxWidth().then(if (choices.size > 1) Modifier.clickable { open = true } else Modifier),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    box?.let { "${boxTitle(it, vm.boxes)} · ${it.address}" } ?: vm.from,
                    style = MaterialTheme.typography.bodyLarge,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.weight(1f),
                )
                if (choices.size > 1) MIcon(R.drawable.ic_m_chev_down, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                for (b in choices) {
                    DropdownMenuItem(
                        text = {
                            Column {
                                Text(boxTitle(b, vm.boxes))
                                Text(b.address, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        },
                        onClick = {
                            open = false
                            vm.chooseFrom(b.key)
                        },
                    )
                }
            }
        }
    }
}

/** Un champ de destinataires : ses puces, ce qu'on tape, et ses correspondants proposés juste dessous. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RecipientsLine(vm: MailComposeViewModel, field: RecipientField, label: String, trailing: @Composable () -> Unit = {}) {
    val people = when (field) {
        RecipientField.TO -> vm.to
        RecipientField.CC -> vm.cc
        RecipientField.BCC -> vm.bcc
    }
    LineField(label) {
        FlowRow(
            Modifier.weight(1f),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            for (p in people) {
                InputChip(
                    selected = false,
                    onClick = { vm.remove(field, p) },
                    label = { Text(p.shown, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 200.dp)) },
                    avatar = { PersonAvatar(p.shown, p.address, 24.dp) },
                    trailingIcon = { MIcon(R.drawable.ic_m_x, stringResource(R.string.mail_recipient_remove, p.shown), size = 16.dp) },
                )
            }
            PlainField(
                value = vm.typedOf(field),
                onValue = { vm.type(field, it) },
                placeholder = if (people.isEmpty()) stringResource(R.string.mail_recipient_hint) else "",
                singleLine = true,
                max = MailLimits.RECIPIENTS,
                keyboard = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next),
                actions = KeyboardActions(onNext = { vm.commit(field) }),
                modifier = Modifier
                    .widthIn(min = 120.dp)
                    .padding(vertical = 6.dp)
                    .onFocusChanged { if (!it.isFocused) vm.commit(field) },
            )
        }
        trailing()
    }
    if (vm.suggestFor == field && vm.suggestions.isNotEmpty() && vm.typedOf(field).isNotBlank()) {
        Surface(
            shape = RoundedCornerShape(12.dp),
            color = MaterialTheme.colorScheme.surfaceContainerHigh,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
        ) {
            Column {
                for (c in vm.suggestions) {
                    Row(
                        Modifier.fillMaxWidth().clickable { vm.pick(field, c) }.padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        PersonAvatar(c.name.ifBlank { c.address }, c.address, 32.dp)
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(c.name.ifBlank { c.address }, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(c.address, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
    }
}

/** Une ligne de la maquette (`.line-field`) : son nom à gauche, son contenu, un filet dessous. */
@Composable
private fun LineField(label: String, content: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit) {
    Column {
        Row(Modifier.fillMaxWidth().heightIn(min = 52.dp).padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(label, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.width(52.dp))
            content()
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
    }
}

/** Un champ sans cadre, borné à [max] caractères (ce que l'API refuserait au-delà). */
@Composable
private fun PlainField(
    value: String,
    onValue: (String) -> Unit,
    placeholder: String,
    singleLine: Boolean,
    max: Int,
    modifier: Modifier = Modifier,
    keyboard: KeyboardOptions = KeyboardOptions.Default,
    actions: KeyboardActions = KeyboardActions.Default,
) {
    val scheme = MaterialTheme.colorScheme
    BasicTextField(
        value = value,
        onValueChange = { if (chars(it) <= max) onValue(it) },
        singleLine = singleLine,
        keyboardOptions = keyboard,
        keyboardActions = actions,
        textStyle = TextStyle(color = scheme.onSurface, fontSize = 16.sp, lineHeight = 23.sp),
        cursorBrush = SolidColor(scheme.primary),
        modifier = modifier,
        decorationBox = { inner ->
            Box {
                if (value.isEmpty() && placeholder.isNotEmpty()) {
                    Text(placeholder, style = TextStyle(fontSize = 16.sp, lineHeight = 23.sp), color = scheme.onSurfaceVariant)
                }
                inner()
            }
        },
    )
}

/** Une case à cocher et ce qu'elle dit. */
@Composable
private fun CheckLine(text: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Checkbox(checked = checked, onCheckedChange = onChange)
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}
