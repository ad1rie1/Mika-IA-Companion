package fr.qwartz.mika.ui.settings

import android.content.ActivityNotFoundException
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.net.toUri
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.levelTag
import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.settings.AUTHS
import fr.qwartz.mika.data.moi.settings.Auths
import fr.qwartz.mika.data.moi.settings.BOX_LABELS
import fr.qwartz.mika.data.moi.settings.BoxSettings
import fr.qwartz.mika.data.moi.settings.BoxValues
import fr.qwartz.mika.data.moi.settings.GivenShare
import fr.qwartz.mika.data.moi.settings.NewBox
import fr.qwartz.mika.data.moi.settings.Provider
import fr.qwartz.mika.data.moi.settings.Replies
import fr.qwartz.mika.data.moi.settings.RuleEdit
import fr.qwartz.mika.data.moi.settings.RulesKind
import fr.qwartz.mika.data.moi.settings.SMTP_SECURITY
import fr.qwartz.mika.data.moi.settings.ShareKinds
import fr.qwartz.mika.data.moi.settings.SignIn
import fr.qwartz.mika.data.moi.settings.VOICES
import fr.qwartz.mika.data.moi.settings.Voices
import fr.qwartz.mika.data.moi.settings.authWords
import fr.qwartz.mika.data.moi.settings.boxChanges
import fr.qwartz.mika.data.moi.settings.boxShownFields
import fr.qwartz.mika.data.moi.settings.boxState
import fr.qwartz.mika.data.moi.settings.boxStatusLine
import fr.qwartz.mika.data.moi.settings.doneText
import fr.qwartz.mika.data.moi.settings.edit
import fr.qwartz.mika.data.moi.settings.folderChoices
import fr.qwartz.mika.data.moi.settings.foldersOf
import fr.qwartz.mika.data.moi.settings.newBoxProblems
import fr.qwartz.mika.data.moi.settings.newBoxValues
import fr.qwartz.mika.data.moi.settings.providersFor
import fr.qwartz.mika.data.moi.settings.rangeProblems
import fr.qwartz.mika.data.moi.settings.ruleBody
import fr.qwartz.mika.data.moi.settings.ruleChanged
import fr.qwartz.mika.data.moi.settings.secretsToRetype
import fr.qwartz.mika.data.moi.settings.shareWords
import fr.qwartz.mika.data.moi.settings.sharedBoxSentence
import fr.qwartz.mika.data.moi.settings.sharedBoxTitle
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/*
 * Paramètres › Boîtes mail (ADR 0185, 0187) : tes boîtes et celles qu'on te partage ; une boîte (ses réglages —
 * la boîte, la connexion de lecture, l'envoi, ce que Mika en fait —, la tester, la connecter à Microsoft, comment part
 * ce que Mika y prépare, la partager, la retirer) ; en ajouter une. Porté de `frontendv2/src/screens/parametres/mail.ts`
 * sans changer ses règles : un secret ne repart jamais (laissé vide, il reste), une connexion qui change le redemande.
 */

/** Relire où en est une connexion Microsoft, tant que son code attend. */
private const val SIGNIN_EVERY_MS = 3_000L

/** Partager cette ressource : la page des partages, sa fenêtre ouverte sur elle. */
internal fun shareRoute(kind: String, key: String): Route = settingsPage(SettingsPages.SHARES, "$kind:$key")

// ── La liste ────────────────────────────────────────────────────────────

class BoxesViewModel(graph: AppGraph) : SettingsModel(graph) {
    var load by mutableStateOf<Load<MailBoxes>>(Load.Loading)
        private set

    /** Relue à chaque retour sur la page (une boîte vient peut-être d'être retirée ou renommée). */
    fun resume() {
        viewModelScope.launch {
            when (val got = api.boxes()) {
                is MoiApi.Result.Ok -> load = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (load !is Load.Ready) load = Load.Failed(got.error) else say(got.error)
            }
        }
    }

    fun retry() {
        load = Load.Loading
        resume()
    }
}

@Composable
internal fun BoxesPage(graph: AppGraph) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: BoxesViewModel = viewModel(key = "settings.boxes|$session") { BoxesViewModel(graph) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) { lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { vm.resume() } }
    SettingsEffects(vm)
    val now = graph.clock.wallMs()
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_boxes), BarNav.BACK) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { shell.navigate(settingsPage(SettingsPages.BOX)) },
                icon = { MIcon(R.drawable.ic_m_plus, null) },
                text = { Text(stringResource(R.string.settings_add)) },
            )
        },
    ) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) { got ->
            val own = got.boxes.filter { it.own }
            val shared = got.boxes.filterNot { it.own }
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 96.dp)) {
                if (!got.plugged) NoteBox(stringResource(R.string.settings_boxes_unplugged), R.drawable.ic_m_info, Modifier.padding(16.dp))
                SetHead(stringResource(R.string.settings_yours))
                SetGroup {
                    if (own.isEmpty()) {
                        SetRow(stringResource(R.string.settings_boxes_none), stringResource(R.string.settings_boxes_none_help))
                    }
                    own.forEachIndexed { i, b ->
                        if (i > 0) SetDivider()
                        SetItem(
                            R.drawable.ic_m_mail,
                            b.name.ifBlank { b.key },
                            listOf(b.address, boxStatusLine(b, now)).filter { it.isNotBlank() }.joinToString(" · "),
                            onClick = { shell.navigate(settingsPage(SettingsPages.BOX, b.key)) },
                        ) { boxState(b).let { (tone, words) -> Tag(words, tone) } }
                    }
                }
                if (shared.isNotEmpty()) {
                    SetHead(stringResource(R.string.settings_shared_with_you))
                    SetGroup {
                        shared.forEachIndexed { i, b ->
                            if (i > 0) SetDivider()
                            SetItem(
                                R.drawable.ic_m_lock,
                                sharedBoxTitle(b),
                                listOf(b.address, levelTag(b.level)).filter { it.isNotBlank() }.joinToString(" · "),
                                onClick = { shell.navigate(settingsPage(SettingsPages.BOX, b.key)) },
                            )
                        }
                    }
                }
                SetNote(stringResource(R.string.settings_boxes_note))
            }
        }
    }
}

// ── Une boîte ───────────────────────────────────────────────────────────

/**
 * Une de tes boîtes : ses réglages tels que le serveur les a ([settings]) et tels qu'on les tape ([values], les nombres
 * en texte), ses secrets tapés (vides : gardés), sa règle d'envoi ; une seule barre « Enregistrer » envoie les deux
 * (les réglages, puis la règle). Tester et se connecter à Microsoft enregistrent d'abord ce qui a changé.
 *
 * Un modèle pour toutes les boîtes de la session : une lecture d'une ouverture précédente est annulée et ne pose rien
 * (R3-07) ; un enregistrement fige avant de partir la boîte, ce qui a changé et le corps de la règle, et ne pose rien
 * (refus, relecture, geste qui attendait) sur la page d'une autre boîte ouverte avant sa réponse (R3-01) ; une règle
 * changée ailleurs entre-temps (409) se relit, le reste du formulaire gardé (R3-10).
 */
class BoxViewModel(deps: SettingsDeps) : SettingsModel(deps) {
    var load by mutableStateOf<Load<Unit>>(Load.Loading)
        private set
    var key = ""
        private set
    /** Sa ligne dans la liste (état, relève, erreur, dossiers) ; `null` : pas à toi. */
    var box by mutableStateOf<MailBox?>(null)
        private set
    /** Une boîte qu'on te partage : seul son propriétaire la règle. */
    var shared by mutableStateOf<MailBox?>(null)
        private set
    var settings by mutableStateOf<BoxSettings?>(null)
        private set
    var signin by mutableStateOf<SignIn?>(null)
        private set
    var given by mutableStateOf<List<GivenShare>>(emptyList())
        private set

    var values by mutableStateOf(BoxValues())
        private set
    var imapPort by mutableStateOf("")
        private set
    var smtpPort by mutableStateOf("")
        private set
    var sinceDays by mutableStateOf("")
        private set
    var password by mutableStateOf("")
        private set
    var smtpPassword by mutableStateOf("")
        private set
    /** Les dossiers tapés à la main, tant que le serveur n'en connaît aucun (avant la première relève). */
    var foldersText by mutableStateOf("")
        private set
    var lines by mutableStateOf<List<RuleEdit>>(emptyList())
        private set
    var default by mutableStateOf(RuleEdit(false, Replies.ASK))
        private set
    var errors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    /** L'ouverture dont un enregistrement est en route : seule sa page attend (une autre boîte se règle librement). */
    private var busyFor by mutableStateOf<String?>(null)
    val busy: Boolean get() = busyFor != null && busyFor == openedFor
    private var loading: Job? = null

    fun open(key: String, entry: String) {
        if (!reopen(entry, key)) return
        this.key = key
        box = null
        shared = null
        settings = null
        signin = null
        given = emptyList()
        errors = emptyMap()
        reload(full = true)
    }

    fun retry() = reload(full = true)

    /** Relire la boîte ; une relecture qui n'est pas la première ne touche pas une saisie en cours. Celle d'avant est
     *  annulée, et rien de ce qu'elle rendrait encore ne se pose sur une autre ouverture. */
    private fun reload(full: Boolean) {
        loading?.cancel()
        val from = opening
        val k = key
        loading = viewModelScope.launch {
            if (full) load = Load.Loading
            val list = api.boxes()
            if (!stillOn(from)) return@launch
            if (list is MoiApi.Result.Failed) {
                if (full) load = Load.Failed(list.error) else say(list.error)
                return@launch
            }
            val all = (list as MoiApi.Result.Ok).value.boxes
            val mine = all.firstOrNull { it.key == k && it.own }
            box = mine
            if (mine == null) {
                shared = all.firstOrNull { it.key == k }
                load = if (shared != null) Load.Ready(Unit) else Load.Failed(MoiError(404, text(R.string.settings_box_not_yours)))
                return@launch
            }
            val got = api.box(k)
            if (!stillOn(from)) return@launch
            when (got) {
                is MoiApi.Result.Ok -> {
                    if (full || !dirty) fill(got.value) else signin = got.value.signin
                    load = Load.Ready(Unit)
                }
                is MoiApi.Result.Failed -> if (full) load = Load.Failed(got.error) else say(got.error)
            }
            val s = api.shares()
            if (stillOn(from) && s is MoiApi.Result.Ok) given = s.value.given.filter { it.kind == ShareKinds.MAIL && it.key == k }
        }
    }

    private fun fill(s: BoxSettings) {
        settings = s
        signin = s.signin
        values = s.values
        imapPort = s.values.imapPort.toString()
        smtpPort = s.values.smtpPort.toString()
        sinceDays = s.values.sinceDays.toString()
        password = ""
        smtpPassword = ""
        foldersText = s.values.folders.joinToString(", ")
        lines = s.rules.lines.map { it.edit }
        default = s.rules.default.edit
        errors = emptyMap()
    }

    /** Les dossiers se cochent dès que le serveur en connaît ; avant, ils se tapent. */
    val foldersKnown: Boolean get() = box?.folders.orEmpty().isNotEmpty()

    private fun current(): BoxValues {
        val s = settings?.values ?: values
        return values.copy(
            imapPort = imapPort.trim().toIntOrNull() ?: s.imapPort,
            smtpPort = smtpPort.trim().toIntOrNull() ?: s.smtpPort,
            sinceDays = sinceDays.trim().toIntOrNull() ?: s.sinceDays,
            folders = if (foldersKnown) values.folders else foldersOf(foldersText),
        )
    }

    private val microsoft: Boolean get() = values.auth == Auths.MICROSOFT

    val dirty: Boolean
        get() {
            val s = settings ?: return false
            return boxChanges(s.values, current(), password, smtpPassword).isNotEmpty() ||
                imapPort.trim() != s.values.imapPort.toString() || smtpPort.trim() != s.values.smtpPort.toString() ||
                sinceDays.trim() != s.values.sinceDays.toString() || ruleChanged(s.rules, lines, default)
        }

    /** Le nom de la boîte à l'écran, pour dire le sort d'un geste qui répond ailleurs. */
    private fun named(k: String): String = box?.takeIf { it.key == k }?.name?.ifBlank { k } ?: k

    fun edit(field: String, f: (BoxValues) -> BoxValues) {
        values = f(values)
        errors = errors - field
    }

    fun onImapPort(v: String) { imapPort = v.filter(Char::isDigit).take(5); errors = errors - "imap_port" }
    fun onSmtpPort(v: String) { smtpPort = v.filter(Char::isDigit).take(5); errors = errors - "smtp_port" }
    fun onSinceDays(v: String) { sinceDays = v.filter(Char::isDigit).take(3); errors = errors - "since_days" }
    fun onPassword(v: String) { password = v.take(200); errors = errors - "password" }
    fun onSmtpPassword(v: String) { smtpPassword = v.take(200); errors = errors - "smtp_password" }
    fun onFoldersText(v: String) { foldersText = v.take(1000); errors = errors - "folders" }

    fun toggleFolder(name: String, on: Boolean) = edit("folders") { v ->
        v.copy(folders = if (on) (v.folders + name).distinct() else v.folders - name)
    }

    fun onLine(i: Int, e: RuleEdit) {
        lines = lines.toMutableList().also { if (i in it.indices) it[i] = e }
    }

    fun onDefault(e: RuleEdit) {
        default = e
    }

    fun cancel() {
        settings?.let(::fill)
    }

    /**
     * Enregistrer ce qui a changé (les réglages, puis la règle) ; [then] : le geste qui attendait, s'il est fait et que
     * sa page est encore à l'écran. Tout ce qui part est figé ici, avant le premier appel : la boîte, ses changements,
     * le corps de la règle et sa version.
     */
    fun save(then: (suspend () -> Unit)? = null) {
        if (busy) return
        val s = settings ?: return
        val ranges = rangeProblems(mapOf("imap_port" to imapPort, "smtp_port" to smtpPort, "since_days" to sinceDays))
        if (ranges.isNotEmpty()) {
            errors = ranges
            say(text(R.string.settings_form_errors))
            return
        }
        val now = current()
        val sent = boxChanges(s.values, now, if (microsoft) "" else password, if (microsoft) "" else smtpPassword)
        val ruleMoved = ruleChanged(s.rules, lines, default)
        if (sent.isEmpty() && !ruleMoved) {
            if (then != null) viewModelScope.launch { then() }
            return
        }
        // la connexion change : ses secrets gardés se redonnent (le serveur refuserait sinon), dit sous leurs champs
        val retype = secretsToRetype(sent, s.secrets, now.auth, now.imapHost, now.smtpHost)
        if (retype.isNotEmpty()) {
            errors = retype
            say(text(R.string.settings_box_retype))
            return
        }
        val rules = if (ruleMoved) ruleBody(s.rules, lines, default) ?: return say(text(R.string.settings_rules_mismatch)) else null
        val from = opening
        val k = key
        val what = named(k)
        val shown = boxShownFields(now)
        busyFor = from
        viewModelScope.launch {
            val said = mutableListOf<String>()
            var savedBox = false
            var ok = true
            var conflict: MoiError? = null
            if (sent.isNotEmpty()) {
                when (val got = api.saveBox(sent, k)) {
                    is MoiApi.Result.Ok -> {
                        savedBox = true
                        said += got.value.message
                    }
                    is MoiApi.Result.Failed -> {
                        ok = false
                        refusedFor(from, what, got.error, shown, BOX_LABELS)?.let { errors = it }
                    }
                }
            }
            if (ok && rules != null) {
                when (val got = api.saveRules(rules)) {
                    is MoiApi.Result.Ok -> said += got.value.message
                    is MoiApi.Result.Failed -> {
                        ok = false
                        if (got.error.conflict) conflict = got.error else sayFor(from, what, got.error.said)
                    }
                }
            }
            if (ok) sayFor(from, what, said.filter { it.isNotBlank() }.joinToString(" ").ifBlank { text(R.string.settings_saved) })
            // fait (ou la règle refusée après des réglages gardés) : relu tel qu'il est ; la règle changée ailleurs : elle
            // seule se relit, le reste du formulaire gardé — sur sa page seulement
            when {
                !stillOn(from) -> conflict?.let { sayFor(from, what, it.said) }
                ok || savedBox -> refresh(k, from)
                conflict != null -> rulesAgain(k, from)
            }
            if (conflict != null && stillOn(from)) say((said.filter { it.isNotBlank() } + text(R.string.settings_rules_reread)).joinToString(" "))
            if (busyFor == from) busyFor = null
            if (ok && then != null && stillOn(from)) then()
        }
    }

    /** Relire la boîte telle qu'elle est enregistrée, et la remontrer (sur sa page seulement). */
    private suspend fun refresh(k: String, from: String) {
        val list = api.boxes()
        if (stillOn(from)) (list as? MoiApi.Result.Ok)?.let { l -> l.value.boxes.firstOrNull { it.key == k && it.own }?.let { box = it } }
        val got = api.box(k)
        if (stillOn(from)) (got as? MoiApi.Result.Ok)?.let { fill(it.value) }
    }

    /** Sa règle changée ailleurs entre-temps (409) : relue telle qu'elle est (sa version comprise) ; le reste du
     *  formulaire ne bouge pas. Tes choix sur l'ancienne sont à refaire : ses lignes ont pu changer. */
    private suspend fun rulesAgain(k: String, from: String) {
        val got = api.box(k) as? MoiApi.Result.Ok ?: return
        if (!stillOn(from)) return
        val fresh = got.value.rules
        settings = settings?.copy(rules = fresh)
        lines = fresh.lines.map { it.edit }
        default = fresh.default.edit
    }

    /** Un geste qui agit sur ce qui est enregistré : les modifications d'abord, sinon il partirait avec les anciennes.
     *  La boîte et l'ouverture sont figées au toucher. */
    private fun savedFirst(gesture: suspend (k: String, from: String) -> Unit) {
        val k = key
        val from = opening
        if (dirty) save { gesture(k, from) } else viewModelScope.launch { gesture(k, from) }
    }

    fun test() = savedFirst { k, from ->
        val what = named(k)
        say(text(R.string.settings_testing))
        when (val got = api.testBox(k)) {
            is MoiApi.Result.Ok -> sayFor(from, what, doneText(got.value.message, text(R.string.settings_box_answers)))
            is MoiApi.Result.Failed -> sayFor(from, what, got.error.said)
        }
        val list = api.boxes()
        if (stillOn(from)) (list as? MoiApi.Result.Ok)?.let { l -> l.value.boxes.firstOrNull { it.key == k && it.own }?.let { box = it } }
    }

    fun poll() {
        val k = key
        val from = opening
        val what = named(k)
        viewModelScope.launch {
            when (val got = api.pollBox(k)) {
                is MoiApi.Result.Ok -> sayFor(from, what, doneText(got.value.message, text(R.string.settings_box_polled)))
                is MoiApi.Result.Failed -> sayFor(from, what, got.error.said)
            }
        }
    }

    fun connectMicrosoft() = savedFirst { k, from ->
        val what = named(k)
        when (val got = api.connectMicrosoft(k)) {
            is MoiApi.Result.Ok -> sayFor(from, what, doneText(got.value.message, text(R.string.settings_ms_code_waits)))
            is MoiApi.Result.Failed -> sayFor(from, what, got.error.said)
        }
        val got = api.box(k)
        if (stillOn(from)) (got as? MoiApi.Result.Ok)?.let { signin = it.value.signin }
    }

    /** Où en est la connexion Microsoft ; `true` tant qu'un code attend. Connectée : dit, et la boîte relue. */
    suspend fun pollSignin(): Boolean {
        val k = key
        val from = opening
        val got = api.box(k) as? MoiApi.Result.Ok ?: return true
        if (!stillOn(from)) return false
        val now = got.value.signin
        signin = now
        if (now?.connected == true) {
            say(text(R.string.settings_ms_connected))
            val list = api.boxes()
            if (!stillOn(from)) return false
            (list as? MoiApi.Result.Ok)?.let { l -> l.value.boxes.firstOrNull { it.key == k && it.own }?.let { box = it } }
            if (!dirty) fill(got.value)
        }
        return now?.waiting == true
    }

    fun remove() {
        val from = opening
        val k = key
        val what = named(k)
        viewModelScope.launch {
            when (val got = api.removeBox(k)) {
                is MoiApi.Result.Ok -> {
                    sayFor(from, what, doneText(got.value.message, text(R.string.settings_box_removed)))
                    move(Move.Back, from)
                }
                is MoiApi.Result.Failed -> sayFor(from, what, got.error.said)
            }
        }
    }
}

@Composable
internal fun BoxPage(graph: AppGraph, key: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: BoxViewModel = viewModel(key = "settings.box|$session") { BoxViewModel(SettingsDeps(graph)) }
    val entry = rememberSaveable { MoiApi.newKey() }
    LaunchedEffect(vm, key, entry) { vm.open(key, entry) }
    SettingsEffects(vm)
    var confirmRemove by rememberSaveable { mutableStateOf(false) }
    if (!vm.isOpenFor(entry, key)) return SettingsLoading(stringResource(R.string.settings_box))
    val waiting = vm.signin?.waiting == true
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, waiting, lifecycle) {
        if (waiting) {
            lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
                while (true) {
                    delay(SIGNIN_EVERY_MS)
                    if (!vm.pollSignin()) break
                }
            }
        }
    }
    val box = vm.box
    SectionScaffold(
        topBar = {
            MikaTopBar(box?.name?.ifBlank { box.key } ?: vm.shared?.let { sharedBoxTitle(it) } ?: stringResource(R.string.settings_box), BarNav.BACK) {
                if (box != null) {
                    BarMenu(
                        listOf(
                            MenuEntry(stringResource(R.string.settings_box_poll), R.drawable.ic_m_refresh, vm::poll),
                            MenuEntry(stringResource(R.string.settings_test), R.drawable.ic_m_plug) { vm.test() },
                            MenuEntry(stringResource(R.string.settings_share_this), R.drawable.ic_m_users) { shell.navigate(shareRoute(ShareKinds.MAIL, key)) },
                            MenuEntry(stringResource(R.string.settings_box_remove), R.drawable.ic_m_trash) { confirmRemove = true },
                        ),
                    )
                }
            }
        },
        bottomBar = { SaveBar(vm.dirty, vm.busy, vm::cancel, { vm.save() }) },
    ) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) {
            val s = vm.settings
            val sharedBox = vm.shared
            when {
                box == null && sharedBox != null -> SharedBoxView(sharedBox, modifier)
                box != null && s != null -> BoxForm(vm, box, s, modifier, onRemove = { confirmRemove = true })
            }
        }
    }
    if (confirmRemove) {
        ConfirmDialog(
            title = stringResource(R.string.settings_box_remove),
            text = stringResource(R.string.settings_box_remove_text, box?.name?.ifBlank { key } ?: key),
            confirm = stringResource(R.string.settings_remove),
            danger = true,
            onConfirm = {
                confirmRemove = false
                vm.remove()
            },
            onDismiss = { confirmRemove = false },
        )
    }
}

/** Une boîte qu'on te partage : ce que son niveau t'ouvre ; seul son propriétaire la règle. */
@Composable
private fun SharedBoxView(b: MailBox, modifier: Modifier) {
    val shell = LocalShell.current
    Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        HeadCard(R.drawable.ic_m_lock, sharedBoxTitle(b), listOf(b.name, b.address).filter { it.isNotBlank() }.joinToString(" · "), Tone.NEUTRAL to shareWords(b.level))
        NoteBox(sharedBoxSentence(b), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        SetNote(stringResource(R.string.settings_box_owner_only))
        ActionButton(stringResource(R.string.settings_open_mail), R.drawable.ic_m_mail, { shell.open(Route.Mail) }, Modifier.padding(horizontal = 16.dp))
    }
}

@Composable
private fun BoxForm(vm: BoxViewModel, box: MailBox, s: BoxSettings, modifier: Modifier, onRemove: () -> Unit) {
    val shell = LocalShell.current
    val v = vm.values
    val e = vm.errors
    val microsoft = v.auth == Auths.MICROSOFT
    Column(modifier.imePadding().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        HeadCard(R.drawable.ic_m_mail, box.name.ifBlank { box.key }, "${box.address} · ${authWords(s.values.auth)}", boxState(box))
        if (box.error.isNotBlank()) NoteBox(box.error, R.drawable.ic_m_alert, Modifier.padding(horizontal = 16.dp, vertical = 4.dp), Tone.DANGER)
        if (s.microsoft) SigninCard(vm.signin, onConnect = vm::connectMicrosoft)
        if (v.smtpHost.isBlank()) NoteBox(stringResource(R.string.settings_box_read_only), R.drawable.ic_m_info, Modifier.padding(horizontal = 16.dp, vertical = 4.dp))

        SetHead(stringResource(R.string.settings_box_group_box))
        SetGroup {
            Gap(6.dp)
            SetField(BOX_LABELS.getValue("address"), v.address, { x -> vm.edit("address") { it.copy(address = x) } }, help = stringResource(R.string.settings_box_address_help), error = e["address"], keyboard = KeyboardType.Email, max = 300)
            SetField(BOX_LABELS.getValue("label"), v.label, { x -> vm.edit("label") { it.copy(label = x) } }, help = stringResource(R.string.settings_box_label_help), error = e["label"], max = 120)
            SetSwitch(BOX_LABELS.getValue("enabled"), stringResource(R.string.settings_box_enabled_help), v.enabled, { x -> vm.edit("enabled") { it.copy(enabled = x) } }, error = e["enabled"])
        }

        SetHead(stringResource(R.string.settings_box_group_read))
        SetGroup {
            Gap(6.dp)
            PickField(BOX_LABELS.getValue("auth"), AUTHS, v.auth, { x -> vm.edit("auth") { it.copy(auth = x) } }, error = e["auth"])
            SetNote(stringResource(R.string.settings_box_auth_help))
            SetField(BOX_LABELS.getValue("user"), v.user, { x -> vm.edit("user") { it.copy(user = x) } }, help = stringResource(R.string.settings_box_user_help), error = e["user"], mono = true, max = 300)
            if (!microsoft) {
                SetField(
                    BOX_LABELS.getValue("password"), vm.password, vm::onPassword, error = e["password"], secret = true,
                    help = stringResource(if (s.secrets.password) R.string.settings_secret_kept else R.string.settings_box_password_help),
                )
            } else {
                SetField(BOX_LABELS.getValue("oauth_client_id"), v.oauthClientId, { x -> vm.edit("oauth_client_id") { it.copy(oauthClientId = x) } }, help = stringResource(R.string.settings_box_client_help), error = e["oauth_client_id"], mono = true, placeholder = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", max = 200)
                SetField(BOX_LABELS.getValue("oauth_tenant"), v.oauthTenant, { x -> vm.edit("oauth_tenant") { it.copy(oauthTenant = x) } }, help = stringResource(R.string.settings_box_tenant_help), error = e["oauth_tenant"], mono = true, max = 200)
                if (!s.microsoft) SetNote(stringResource(R.string.settings_ms_save_first))
            }
            SetField(BOX_LABELS.getValue("imap_host"), v.imapHost, { x -> vm.edit("imap_host") { it.copy(imapHost = x) } }, help = stringResource(R.string.settings_box_imap_help), error = e["imap_host"], mono = true, keyboard = KeyboardType.Uri, max = 255)
            SetField(BOX_LABELS.getValue("imap_port"), vm.imapPort, vm::onImapPort, error = e["imap_port"], number = true)
            SetSwitch(stringResource(R.string.settings_box_ssl), stringResource(R.string.settings_box_ssl_help), v.imapSsl, { x -> vm.edit("imap_ssl") { it.copy(imapSsl = x) } }, error = e["imap_ssl"])
            Row(Modifier.padding(horizontal = 14.dp, vertical = 8.dp)) {
                ActionButton(stringResource(R.string.settings_box_test), R.drawable.ic_m_refresh, { vm.test() }, enabled = !vm.busy)
            }
        }

        SetHead(stringResource(R.string.settings_box_group_send))
        SetGroup {
            Gap(6.dp)
            SetField(BOX_LABELS.getValue("smtp_host"), v.smtpHost, { x -> vm.edit("smtp_host") { it.copy(smtpHost = x) } }, help = stringResource(R.string.settings_box_smtp_help), error = e["smtp_host"], mono = true, keyboard = KeyboardType.Uri, max = 255)
            SetField(BOX_LABELS.getValue("smtp_port"), vm.smtpPort, vm::onSmtpPort, error = e["smtp_port"], number = true)
            PickField(BOX_LABELS.getValue("smtp_security"), SMTP_SECURITY, v.smtpSecurity, { x -> vm.edit("smtp_security") { it.copy(smtpSecurity = x) } }, error = e["smtp_security"])
            SetField(BOX_LABELS.getValue("smtp_user"), v.smtpUser, { x -> vm.edit("smtp_user") { it.copy(smtpUser = x) } }, help = stringResource(R.string.settings_box_same_as_read), error = e["smtp_user"], mono = true, max = 300)
            if (!microsoft) {
                SetField(
                    BOX_LABELS.getValue("smtp_password"), vm.smtpPassword, vm::onSmtpPassword, error = e["smtp_password"], secret = true,
                    help = stringResource(if (s.secrets.smtpPassword) R.string.settings_secret_kept else R.string.settings_box_same_as_read),
                )
            }
            SetSwitch(stringResource(R.string.settings_box_save_sent), stringResource(R.string.settings_box_save_sent_help), v.saveSent, { x -> vm.edit("save_sent") { it.copy(saveSent = x) } }, error = e["save_sent"])
        }

        SetHead(stringResource(R.string.settings_box_group_mika))
        SetGroup {
            SetRow(BOX_LABELS.getValue("folders"), stringResource(R.string.settings_box_folders_help))
            if (vm.foldersKnown) {
                for ((name, label) in folderChoices(box, v.folders)) {
                    val on = name in v.folders
                    Row(
                        Modifier.fillMaxWidth().heightIn(min = 44.dp)
                            .toggleable(value = on, role = Role.Checkbox, onValueChange = { vm.toggleFolder(name, it) })
                            .padding(horizontal = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Checkbox(checked = on, onCheckedChange = null)
                        Spacer(Modifier.width(12.dp))
                        Text(label, style = MaterialTheme.typography.bodyMedium)
                    }
                }
                e["folders"]?.let { FieldError(it, Modifier.padding(horizontal = 14.dp)) }
            } else {
                SetField(BOX_LABELS.getValue("folders"), vm.foldersText, vm::onFoldersText, help = stringResource(R.string.settings_box_folders_typed), error = e["folders"], placeholder = "INBOX")
            }
            SetSwitch(BOX_LABELS.getValue("sync_all"), stringResource(R.string.settings_box_sync_all_help), v.syncAll, { x -> vm.edit("sync_all") { it.copy(syncAll = x) } }, error = e["sync_all"])
            SetSwitch(BOX_LABELS.getValue("keep_all"), stringResource(R.string.settings_box_keep_all_help), v.keepAll, { x -> vm.edit("keep_all") { it.copy(keepAll = x) } }, error = e["keep_all"])
            SetField(BOX_LABELS.getValue("since_days"), vm.sinceDays, vm::onSinceDays, help = stringResource(R.string.settings_box_since_help), error = e["since_days"], number = true)
            SetField(BOX_LABELS.getValue("triage_instructions"), v.triageInstructions, { x -> vm.edit("triage_instructions") { it.copy(triageInstructions = x) } }, help = stringResource(R.string.settings_box_triage_instructions_help), error = e["triage_instructions"], singleLine = false, minLines = 3, max = 4000)
            SetDivider()
            SetRow(BOX_LABELS.getValue("voice"), stringResource(R.string.settings_box_voice_help))
            ChoiceSeg(VOICES, v.voice, { x -> vm.edit("voice") { it.copy(voice = x) } })
            e["voice"]?.let { FieldError(it, Modifier.padding(horizontal = 14.dp)) }
            if (v.voice == Voices.HER) {
                SetField(BOX_LABELS.getValue("sender_name"), v.senderName, { x -> vm.edit("sender_name") { it.copy(senderName = x) } }, help = stringResource(R.string.settings_box_sender_help), error = e["sender_name"], max = 120)
            } else {
                SetField(BOX_LABELS.getValue("display_name"), v.displayName, { x -> vm.edit("display_name") { it.copy(displayName = x) } }, help = stringResource(R.string.settings_box_display_help), error = e["display_name"], max = 120)
            }
            SetField(BOX_LABELS.getValue("tone"), v.tone, { x -> vm.edit("tone") { it.copy(tone = x) } }, help = stringResource(R.string.settings_box_tone_help), error = e["tone"], singleLine = false, minLines = 2, max = 2000)
            SetField(BOX_LABELS.getValue("instructions"), v.instructions, { x -> vm.edit("instructions") { it.copy(instructions = x) } }, help = stringResource(R.string.settings_box_instructions_help), error = e["instructions"], singleLine = false, minLines = 3, max = 4000)
            SetField(BOX_LABELS.getValue("signature"), v.signature, { x -> vm.edit("signature") { it.copy(signature = x) } }, help = stringResource(R.string.settings_box_signature_help), error = e["signature"], singleLine = false, minLines = 2, max = 2000)
            Gap(8.dp)
        }

        RulesEditor(s.rules, RulesKind.MAIL, vm.lines, vm.default, vm::onLine, vm::onDefault)

        SharedWithGroup(vm.given) { shell.navigate(shareRoute(ShareKinds.MAIL, box.key)) }
        Gap(8.dp)
        DangerButton(stringResource(R.string.settings_box_remove), onRemove)
    }
}

/** Avec qui une ressource est partagée, et « Partager… ». */
@Composable
internal fun SharedWithGroup(given: List<GivenShare>, onShare: () -> Unit) {
    SetHead(stringResource(R.string.settings_share_group))
    SetGroup {
        SetItem(
            R.drawable.ic_m_users,
            if (given.isEmpty()) stringResource(R.string.settings_share_nobody) else given.joinToString(", ") { "${it.name} · ${shareWords(it.level).lowercase()}" },
            stringResource(R.string.settings_share_help),
            onClick = onShare,
        ) { MIcon(R.drawable.ic_m_chev_right, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant) }
    }
}

/**
 * La connexion Microsoft d'une boîte (ADR 0166) : connectée ; un code attend (l'adresse à ouvrir, le code à copier,
 * jusqu'à quand — la page la relit toutes les trois secondes) ; ou pas connectée, et pourquoi, avec « Se connecter ».
 */
@Composable
private fun SigninCard(s: SignIn?, onConnect: () -> Unit) {
    val context = LocalContext.current
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val shell = LocalShell.current
    val copied = stringResource(R.string.settings_copied)
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceContainerHigh,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                MIcon(R.drawable.ic_m_key, null, size = 20.dp)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.settings_ms_account), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                when {
                    s == null -> Tag(stringResource(R.string.settings_ms_not_yet), Tone.NEUTRAL)
                    s.connected -> Tag(stringResource(R.string.settings_ms_connected_tag), Tone.OK, R.drawable.ic_m_check)
                    s.waiting -> Tag(stringResource(R.string.settings_ms_waiting_tag), Tone.WARN)
                    else -> Tag(stringResource(R.string.settings_ms_off_tag), Tone.WARN)
                }
            }
            if (s != null && s.waiting && s.code.isNotBlank()) {
                Text(stringResource(R.string.settings_ms_enter, s.url.ifBlank { stringResource(R.string.settings_ms_page) }), style = MaterialTheme.typography.bodyMedium)
                Text(s.code, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.SemiBold, fontSize = 26.sp, letterSpacing = 2.sp)
                if (s.until > 0) {
                    Text(stringResource(R.string.settings_ms_until, MoiDates.clock(s.until)), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    ActionButton(stringResource(R.string.settings_copy_code), R.drawable.ic_m_copy, {
                        scope.launch {
                            copyText(clipboard, s.code)
                            shell.toast(copied)
                        }
                    })
                    // un lien seulement vers une page https (celle de Microsoft) : rien d'autre ne s'ouvre d'ici
                    if (Regex("""^https://[^\s"'<>]+$""", RegexOption.IGNORE_CASE).matches(s.url)) {
                        ActionButton(stringResource(R.string.settings_ms_open), R.drawable.ic_m_external, {
                            try {
                                context.startActivity(Intent(Intent.ACTION_VIEW, s.url.toUri()).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                            } catch (_: ActivityNotFoundException) {
                            }
                        })
                    }
                }
            } else if (s?.connected != true) {
                val why = s?.error?.takeIf { it.isNotBlank() }
                Text(
                    if (why != null) stringResource(R.string.settings_ms_not_connected_why, why) else stringResource(R.string.settings_ms_not_connected),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                ActionButton(stringResource(R.string.settings_ms_connect), R.drawable.ic_m_key, onConnect)
            }
        }
    }
}

// ── Une boîte nouvelle ──────────────────────────────────────────────────

/**
 * Ajouter une boîte : son fournisseur (Microsoft, Exchange pro pour une opératrice, Gmail, une autre), puis ce qu'il
 * demande. Une clé d'envoi par création : redite (le réseau a coupé), elle ne fait pas de doublon. Créée, une boîte
 * Microsoft demande son code tout de suite, une autre se teste ; puis sa page s'ouvre à la place de celle-ci.
 * Quand l'instance a son application Microsoft (ADR 0238), une boîte Microsoft ne demande que son adresse et son
 * nom : l'application et l'annuaire se rangent sous « Avancé ».
 */
class NewBoxViewModel(graph: AppGraph) : SettingsModel(graph) {
    var provider by mutableStateOf<Provider?>(null)
        private set
    var typed by mutableStateOf(NewBox())
        private set
    var errors by mutableStateOf<Map<String, String>>(emptyMap())
        private set
    var busy by mutableStateOf(false)
        private set

    /** L'instance a son application Microsoft : l'application et l'annuaire d'une boîte se rangent sous « Avancé ». */
    var instanceApp by mutableStateOf(false)
        private set

    /** « Avancé » est ouvert. */
    var advanced by mutableStateOf(false)
        private set
    private var createKey = MoiApi.newKey()

    fun open(entry: String) {
        if (!reopen(entry)) return
        provider = null
        typed = NewBox()
        errors = emptyMap()
        advanced = false
        createKey = MoiApi.newKey()
        val from = opening
        viewModelScope.launch {
            val got = api.boxes()
            if (opening == from && got is MoiApi.Result.Ok) instanceApp = got.value.microsoftApp
        }
    }

    fun toggleAdvanced() {
        advanced = !advanced
    }

    fun choose(p: Provider) {
        if (p == provider) return
        provider = p
        typed = NewBox.of(p)
        errors = emptyMap()
    }

    fun edit(field: String, f: (NewBox) -> NewBox) {
        typed = f(typed)
        errors = errors - field
    }

    private fun shown(p: Provider): Set<String> =
        if (p == Provider.MICROSOFT) setOf("address", "label", "oauth_client_id", "oauth_tenant")
        else setOf("address", "label", "user", "password", "imap_host", "imap_port", "smtp_host", "smtp_port")

    fun create() {
        val p = provider ?: return
        if (busy) return
        val problems = newBoxProblems(p, typed)
        if (problems.isNotEmpty()) {
            errors = problems
            return
        }
        busy = true
        val from = opening
        viewModelScope.launch {
            when (val got = api.saveBox(newBoxValues(p, typed), "", createKey)) {
                is MoiApi.Result.Ok -> {
                    createKey = MoiApi.newKey()
                    val made = got.value.box
                    if (p == Provider.MICROSOFT) {
                        when (val c = api.connectMicrosoft(made)) {
                            is MoiApi.Result.Ok -> say(text(R.string.settings_box_added_ms))
                            is MoiApi.Result.Failed -> say(text(R.string.settings_box_added_ms_failed, c.error.said))
                        }
                    } else {
                        when (val t = api.testBox(made)) {
                            is MoiApi.Result.Ok -> say(text(R.string.settings_box_added_tested, t.value.message).trim())
                            is MoiApi.Result.Failed -> say(text(R.string.settings_box_added_untested, t.error.said))
                        }
                    }
                    move(if (made.isNotBlank()) Move.Replace(settingsPage(SettingsPages.BOX, made)) else Move.Back, from)
                }
                // une coupure du réseau garde la clé : redit, l'envoi ne fera pas de doublon
                is MoiApi.Result.Failed -> {
                    errors = refused(got.error, shown(p), BOX_LABELS)
                    // un refus qui porte sur un champ rangé sous « Avancé » l'ouvre : il se voit
                    if ("oauth_client_id" in errors || "oauth_tenant" in errors) advanced = true
                }
            }
            busy = false
        }
    }
}

@Composable
internal fun NewBoxPage(graph: AppGraph) {
    val session = rememberSessionKey(graph)
    val vm: NewBoxViewModel = viewModel(key = "settings.box.new|$session") { NewBoxViewModel(graph) }
    val entry = rememberSaveable { MoiApi.newKey() }
    LaunchedEffect(vm, entry) { vm.open(entry) }
    SettingsEffects(vm)
    if (!vm.isOpenFor(entry)) return SettingsLoading(stringResource(R.string.settings_box_new))
    val me by graph.me.me.collectAsStateWithLifecycle()
    val p = vm.provider
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_box_new), BarNav.BACK) },
        bottomBar = { SaveBar(p != null, vm.busy, null, vm::create, label = stringResource(R.string.settings_box_add), note = p?.title.orEmpty()) },
    ) { modifier ->
        Column(modifier.imePadding().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
            SetHead(stringResource(R.string.settings_box_provider))
            SetGroup {
                providersFor(me?.operator).forEachIndexed { i, prov ->
                    if (i > 0) SetDivider()
                    val icon = when (prov) {
                        Provider.MICROSOFT -> R.drawable.ic_m_globe
                        Provider.DAVMAIL -> R.drawable.ic_m_terminal
                        Provider.GMAIL -> R.drawable.ic_m_mail
                        Provider.IMAP -> R.drawable.ic_m_settings
                    }
                    SetItem(icon, prov.title, prov.description, onClick = { vm.choose(prov) }) {
                        if (prov == p) MIcon(R.drawable.ic_m_check, null, tint = MaterialTheme.colorScheme.primary)
                    }
                }
            }
            if (p != null) {
                val t = vm.typed
                val e = vm.errors
                SetHead(p.title)
                SetGroup {
                    Gap(6.dp)
                    SetField(BOX_LABELS.getValue("address"), t.address, { x -> vm.edit("address") { it.copy(address = x) } }, error = e["address"], placeholder = "toi@exemple.fr", keyboard = KeyboardType.Email, max = 300)
                    SetField(BOX_LABELS.getValue("label"), t.label, { x -> vm.edit("label") { it.copy(label = x) } }, help = stringResource(R.string.settings_box_label_new_help), error = e["label"], placeholder = "Pro, Perso…", max = 120)
                    if (p == Provider.MICROSOFT) {
                        if (vm.instanceApp) {
                            SetItem(null, stringResource(R.string.settings_box_advanced), stringResource(R.string.settings_box_advanced_help), onClick = vm::toggleAdvanced, boxed = false) {
                                MIcon(if (vm.advanced) R.drawable.ic_m_chev_up else R.drawable.ic_m_chev_down, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                        if (!vm.instanceApp || vm.advanced) {
                            SetField(BOX_LABELS.getValue("oauth_client_id"), t.oauthClientId, { x -> vm.edit("oauth_client_id") { it.copy(oauthClientId = x) } }, help = stringResource(if (vm.instanceApp) R.string.settings_box_client_help else R.string.settings_box_client_new_help), error = e["oauth_client_id"], mono = true, placeholder = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx", max = 200)
                            SetField(BOX_LABELS.getValue("oauth_tenant"), t.oauthTenant, { x -> vm.edit("oauth_tenant") { it.copy(oauthTenant = x) } }, help = stringResource(R.string.settings_box_tenant_new_help), error = e["oauth_tenant"], mono = true, max = 200)
                        }
                        SetNote(stringResource(R.string.settings_box_ms_next))
                    } else {
                        SetField(BOX_LABELS.getValue("user"), t.user, { x -> vm.edit("user") { it.copy(user = x) } }, help = stringResource(R.string.settings_box_user_new_help), error = e["user"], mono = true, max = 300)
                        SetField(
                            BOX_LABELS.getValue("password"), t.password, { x -> vm.edit("password") { it.copy(password = x.take(200)) } }, error = e["password"], secret = true,
                            help = if (p == Provider.GMAIL) stringResource(R.string.settings_box_gmail_password) else "",
                        )
                        SetField(BOX_LABELS.getValue("imap_host"), t.imapHost, { x -> vm.edit("imap_host") { it.copy(imapHost = x) } }, help = if (p == Provider.DAVMAIL) stringResource(R.string.settings_box_davmail_help) else "", error = e["imap_host"], mono = true, placeholder = "imap.exemple.fr", keyboard = KeyboardType.Uri, max = 255)
                        SetField(BOX_LABELS.getValue("imap_port"), t.imapPort, { x -> vm.edit("imap_port") { it.copy(imapPort = x.filter(Char::isDigit).take(5)) } }, error = e["imap_port"], number = true)
                        SetField(BOX_LABELS.getValue("smtp_host"), t.smtpHost, { x -> vm.edit("smtp_host") { it.copy(smtpHost = x) } }, help = stringResource(R.string.settings_box_smtp_help), error = e["smtp_host"], mono = true, placeholder = "smtp.exemple.fr", keyboard = KeyboardType.Uri, max = 255)
                        SetField(BOX_LABELS.getValue("smtp_port"), t.smtpPort, { x -> vm.edit("smtp_port") { it.copy(smtpPort = x.filter(Char::isDigit).take(5)) } }, error = e["smtp_port"], number = true)
                    }
                    Gap(8.dp)
                }
                SetNote(stringResource(R.string.settings_box_new_note))
            }
        }
    }
}
