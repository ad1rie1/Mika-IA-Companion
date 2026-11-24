package fr.qwartz.mika.ui.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExtendedFloatingActionButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.mail.MailBoxes
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.settings.GivenShare
import fr.qwartz.mika.data.moi.settings.People
import fr.qwartz.mika.data.moi.settings.Person
import fr.qwartz.mika.data.moi.settings.Services
import fr.qwartz.mika.data.moi.settings.ShareKinds
import fr.qwartz.mika.data.moi.settings.ShareOpens
import fr.qwartz.mika.data.moi.settings.Shareable
import fr.qwartz.mika.data.moi.settings.Shares
import fr.qwartz.mika.data.moi.settings.doneText
import fr.qwartz.mika.data.moi.settings.openOf
import fr.qwartz.mika.data.moi.settings.shareGone
import fr.qwartz.mika.data.moi.settings.shareLevelsFor
import fr.qwartz.mika.data.moi.settings.sharePeople
import fr.qwartz.mika.data.moi.settings.sharePhrase
import fr.qwartz.mika.data.moi.settings.shareWords
import fr.qwartz.mika.data.moi.settings.shareables
import fr.qwartz.mika.data.moi.settings.whatLabel
import fr.qwartz.mika.data.moi.teams.TeamsAccounts
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.BarAction
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.launch

/*
 * Paramètres › Partages (ADR 0188) : ce que tu partages — tes boîtes, tes comptes Teams, tes services — avec qui et à
 * quel niveau (lire ; lire et préparer ; s'en servir), ce qu'on te partage, et « Partager ». Seul le propriétaire
 * partage, et seulement avec une personne qui a un compte (`app/me/sharing.py`). Porté de
 * `frontendv2/src/screens/parametres/shares.ts`.
 */

/** La fenêtre « Partager » : ce qu'on partage, à qui, à quel niveau ; [editing] : un partage qu'on change. */
data class ShareDraft(
    val kind: String,
    val key: String,
    val title: String,
    val person: String,
    val name: String,
    val level: String,
    val editing: Boolean,
)

class SharesViewModel(deps: SettingsDeps) : SettingsModel(deps) {
    var load by mutableStateOf<Load<Shares>>(Load.Loading)
        private set
    var boxes by mutableStateOf<MailBoxes?>(null)
        private set
    var accounts by mutableStateOf<TeamsAccounts?>(null)
        private set
    var services by mutableStateOf<Services?>(null)
        private set
    var people by mutableStateOf<People?>(null)
        private set
    var draft by mutableStateOf<ShareDraft?>(null)
        private set
    /** Rien à partager, ou personne à qui : la fenêtre le dit. */
    var nothing by mutableStateOf<String?>(null)
        private set
    var busy by mutableStateOf(false)
        private set
    /**
     * Le partage à retirer, tel qu'il a été touché — sa sorte, sa clé, sa personne —, jamais un rang de la liste : la
     * confirmation le nomme et retire celui-là, même si la liste se relit entre-temps (R3-11).
     */
    var withdrawing by mutableStateOf<GivenShare?>(null)
        private set
    private var preset = ""

    val things: List<Shareable>
        get() = shareables(boxes?.boxes.orEmpty(), accounts?.accounts.orEmpty(), services?.items.orEmpty())

    /** Ouverte depuis une ressource (`<sorte>:<clé>`) : sa fenêtre s'ouvre une fois tout lu. */
    fun open(preset: String, entry: String) {
        if (!reopen(entry, preset)) return
        this.preset = preset
        draft = null
        nothing = null
        withdrawing = null
    }

    fun resume() {
        viewModelScope.launch { read() }
    }

    /** Relu sans bruit : un retour sur la page, ou le direct (ADR 0308) qui dit que ce qu'elle montre a changé. */
    suspend fun read() {
        val got = api.shares()
        when (got) {
            is MoiApi.Result.Ok -> load = Load.Ready(got.value)
            is MoiApi.Result.Failed -> if (load !is Load.Ready) load = Load.Failed(got.error) else say(got.error)
        }
        (api.boxes() as? MoiApi.Result.Ok)?.let { boxes = it.value }
        (api.teamsAccounts() as? MoiApi.Result.Ok)?.let { accounts = it.value }
        (api.services() as? MoiApi.Result.Ok)?.let { services = it.value }
        when (val p = api.people()) {
            is MoiApi.Result.Ok -> people = p.value
            is MoiApi.Result.Failed -> if (people == null && preset.isNotEmpty()) say(p.error)
        }
        if (preset.isNotEmpty() && got is MoiApi.Result.Ok && people != null) {
            val (kind, key) = preset.substringBefore(':') to preset.substringAfter(':')
            preset = ""
            startNew(kind, key)
        }
    }

    fun retry() {
        load = Load.Loading
        resume()
    }

    private fun allowed(thing: Shareable?): List<Person> =
        sharePeople(thing?.common == true, people?.items.orEmpty())

    /** « Partager » : la ressource demandée (depuis sa page), sinon la première ; la première personne possible. */
    fun startNew(kind: String = "", key: String = "") {
        val all = things
        if (people == null) {
            say(text(R.string.settings_share_people_unread))
            return
        }
        val thing = all.firstOrNull { it.kind == kind && it.key == key } ?: all.firstOrNull()
        val whom = allowed(thing)
        if (thing == null || people?.items.orEmpty().isEmpty()) {
            nothing = text(if (thing == null) R.string.settings_share_nothing else R.string.settings_share_nobody_else)
            return
        }
        val person = whom.firstOrNull()
        draft = ShareDraft(thing.kind, thing.key, thing.title, person?.person.orEmpty(), person?.name.orEmpty(), Levels.READ, editing = false)
    }

    /** Changer un partage : sa ressource et sa personne restent les siennes (jamais ce que montrent les listes). */
    fun startEdit(g: GivenShare) {
        draft = ShareDraft(g.kind, g.key, g.title, g.person, g.name, g.level, editing = true)
    }

    fun pickThing(kind: String, key: String) {
        val d = draft ?: return
        if (d.editing) return
        val thing = things.firstOrNull { it.kind == kind && it.key == key } ?: return
        val whom = allowed(thing)
        val person = whom.firstOrNull { it.person == d.person } ?: whom.firstOrNull()
        val level = if (shareLevelsFor(kind).any { it.first == d.level }) d.level else shareLevelsFor(kind).first().first
        draft = d.copy(kind = kind, key = key, title = thing.title, person = person?.person.orEmpty(), name = person?.name.orEmpty(), level = level)
    }

    fun pickPerson(person: String) {
        val d = draft ?: return
        if (d.editing) return
        val p = people?.items.orEmpty().firstOrNull { it.person == person } ?: return
        draft = d.copy(person = p.person, name = p.name)
    }

    fun pickLevel(level: String) {
        draft = draft?.copy(level = level)
    }

    fun close() {
        draft = null
        nothing = null
    }

    /** Ce partage ne se change plus (sa personne n'a plus de compte, ou elle en est devenue propriétaire) : il se retire. */
    fun gone(d: ShareDraft): Boolean {
        if (!d.editing) return false
        val common = things.firstOrNull { it.kind == d.kind && it.key == d.key }?.common == true
        return shareGone(GivenShare(d.kind, d.key, d.title, d.person, d.name, d.level), people?.items.orEmpty(), common)
    }

    fun submit() {
        val d = draft ?: return
        if (busy || d.person.isEmpty()) return
        val removing = gone(d)
        busy = true
        viewModelScope.launch {
            when (val got = api.setShare(d.kind, d.key, d.person, if (removing) "" else d.level)) {
                is MoiApi.Result.Ok -> {
                    draft = null
                    say(doneText(got.value.message, text(if (removing) R.string.settings_share_removed else R.string.settings_share_done)))
                }
                is MoiApi.Result.Failed -> say(got.error)
            }
            busy = false
            resume()
        }
    }

    /** 🗑 sur un partage : la confirmation s'ouvre sur lui. */
    fun askWithdraw(g: GivenShare) {
        withdrawing = g
    }

    fun cancelWithdraw() {
        withdrawing = null
    }

    /** Confirmé : celui qui a été touché part, quelle que soit sa place dans la liste relue depuis. */
    fun confirmWithdraw() {
        val g = withdrawing ?: return
        withdrawing = null
        withdraw(g)
    }

    private fun withdraw(g: GivenShare) {
        viewModelScope.launch {
            when (val got = api.setShare(g.kind, g.key, g.person, "")) {
                is MoiApi.Result.Ok -> say(doneText(got.value.message, text(R.string.settings_share_removed)))
                is MoiApi.Result.Failed -> say(got.error)
            }
            resume()
        }
    }
}

internal fun kindIcon(kind: String): Int = when (kind) {
    ShareKinds.TEAMS -> R.drawable.ic_m_teams
    ShareKinds.MCP -> R.drawable.ic_m_plug
    ShareKinds.AGENDA -> R.drawable.ic_m_agenda
    else -> R.drawable.ic_m_mail
}

@Composable
internal fun SharesPage(graph: AppGraph, preset: String) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: SharesViewModel = viewModel(key = "settings.shares|$session") { SharesViewModel(SettingsDeps(graph)) }
    val entry = rememberSaveable { MoiApi.newKey() }
    LaunchedEffect(vm, entry) { vm.open(preset, entry) }
    FollowLive(graph.live, SettingsLive.SHARES, vm, entry, onShown = { vm.resume() }) { vm.read() }
    SettingsEffects(vm)
    SectionScaffold(
        topBar = { MikaTopBar(stringResource(R.string.settings_shares), BarNav.BACK) },
        floatingActionButton = {
            ExtendedFloatingActionButton(
                onClick = { vm.startNew() },
                icon = { MIcon(R.drawable.ic_m_share, null) },
                text = { Text(stringResource(R.string.settings_share)) },
            )
        },
    ) { modifier ->
        LoadBox(vm.load, onRetry = vm::retry, modifier = modifier) { shares ->
            Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 96.dp)) {
                SetNote(stringResource(R.string.settings_shares_lede))
                SetHead(stringResource(R.string.settings_shares_given))
                SetGroup {
                    if (shares.given.isEmpty()) SetRow("", stringResource(R.string.settings_shares_given_none))
                    shares.given.forEachIndexed { i, g ->
                        if (i > 0) SetDivider()
                        SetItem(kindIcon(g.kind), whatLabel(g.kind, g.title), "${g.name} · ${shareWords(g.level)}", onClick = { vm.startEdit(g) }) {
                            BarAction(R.drawable.ic_m_trash, stringResource(R.string.settings_share_withdraw), { vm.askWithdraw(g) })
                        }
                    }
                }
                SetHead(stringResource(R.string.settings_shared_with_you))
                SetGroup {
                    if (shares.received.isEmpty()) SetRow("", stringResource(R.string.settings_shares_received_none))
                    shares.received.forEachIndexed { i, r ->
                        if (i > 0) SetDivider()
                        SetItem(
                            kindIcon(r.kind),
                            whatLabel(r.kind, r.title),
                            listOf(ofName(r.ownerName), shareWords(r.level)).filter { it.isNotBlank() }.joinToString(" · "),
                            onClick = {
                                when (openOf(r.kind)) {
                                    ShareOpens.MAIL -> shell.open(Route.Mail)
                                    ShareOpens.TEAMS -> shell.open(Route.Teams)
                                    ShareOpens.SERVICE -> shell.navigate(settingsPage(SettingsPages.SERVICE, r.key))
                                    ShareOpens.AGENDA -> shell.open(Route.Agenda)
                                }
                            },
                        ) { Tag(shareWords(r.level), Tone.NEUTRAL) }
                    }
                }
            }
        }
    }
    val fresh = vm.isOpenFor(entry, preset)
    vm.draft?.takeIf { fresh }?.let { ShareDialog(vm, it) }
    vm.nothing?.takeIf { fresh }?.let { said ->
        AlertDialog(
            onDismissRequest = vm::close,
            title = { Text(stringResource(R.string.settings_share)) },
            text = { Text(said) },
            confirmButton = { TextButton(onClick = vm::close) { Text(stringResource(R.string.settings_close)) } },
        )
    }
    vm.withdrawing?.takeIf { fresh }?.let { g ->
        ConfirmDialog(
            title = stringResource(R.string.settings_share_withdraw),
            text = stringResource(R.string.settings_share_withdraw_text, g.name, g.title),
            confirm = stringResource(R.string.settings_remove),
            danger = true,
            onConfirm = vm::confirmWithdraw,
            onDismiss = vm::cancelWithdraw,
        )
    }
}

/** Partager (ou changer un partage) : quoi, avec qui, ce que la personne pourra — dit en une phrase. */
@Composable
private fun ShareDialog(vm: SharesViewModel, d: ShareDraft) {
    val things = vm.things
    val people = vm.people?.items.orEmpty()
    val thing = things.firstOrNull { it.kind == d.kind && it.key == d.key }
    val whom = if (d.editing) people else sharePeople(thing?.common == true, people)
    val gone = vm.gone(d)
    AlertDialog(
        onDismissRequest = { if (!vm.busy) vm.close() },
        title = { Text(stringResource(if (d.editing) R.string.settings_share_edit else R.string.settings_share)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                // en modification, la ressource et la personne du partage même, telles que le serveur les dit
                val thingOptions = (if (thing == null) listOf("${d.kind}:${d.key}" to whatLabel(d.kind, d.title)) else emptyList()) +
                    things.map { "${it.kind}:${it.key}" to whatLabel(it.kind, it.title) }
                PickField(
                    stringResource(R.string.settings_share_what), thingOptions, "${d.kind}:${d.key}",
                    { v -> vm.pickThing(v.substringBefore(':'), v.substringAfter(':')) }, enabled = !d.editing,
                )
                val personOptions = (if (whom.none { it.person == d.person } && d.person.isNotEmpty()) listOf(d.person to d.name.ifBlank { d.person }) else emptyList()) +
                    whom.map { it.person to it.name }
                if (personOptions.isEmpty()) {
                    NoteBox(stringResource(R.string.settings_share_owners_only), R.drawable.ic_m_info, Modifier.padding(horizontal = 14.dp, vertical = 6.dp))
                } else {
                    PickField(stringResource(R.string.settings_share_whom), personOptions, d.person, vm::pickPerson, enabled = !d.editing)
                }
                if (gone) {
                    val name = d.name.ifBlank { d.person }
                    val owner = people.firstOrNull { it.person == d.person }?.owner == true
                    NoteBox(
                        stringResource(if (owner) R.string.settings_share_gone_owner else R.string.settings_share_gone, name),
                        R.drawable.ic_m_alert,
                        Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                        Tone.WARN,
                    )
                } else if (d.person.isNotEmpty()) {
                    Text(
                        stringResource(R.string.settings_share_can),
                        style = MaterialTheme.typography.labelLarge,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp),
                    )
                    Column(Modifier.selectableGroup()) {
                        for ((k, label) in shareLevelsFor(d.kind)) {
                            Row(
                                Modifier.fillMaxWidth().heightIn(min = 44.dp)
                                    .selectable(selected = k == d.level, role = Role.RadioButton, onClick = { vm.pickLevel(k) })
                                    .padding(horizontal = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                RadioButton(selected = k == d.level, onClick = null)
                                Text(label, modifier = Modifier.padding(start = 12.dp))
                            }
                        }
                    }
                    NoteBox(sharePhrase(d.kind, d.title, d.name, d.level), R.drawable.ic_m_info, Modifier.padding(horizontal = 14.dp, vertical = 6.dp))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = vm::submit, enabled = !vm.busy && d.person.isNotEmpty()) {
                Text(
                    stringResource(
                        when {
                            gone -> R.string.settings_share_remove_this
                            d.editing -> R.string.settings_save
                            else -> R.string.settings_share
                        },
                    ),
                    color = if (gone) MaterialTheme.colorScheme.error else Color.Unspecified,
                )
            }
        },
        dismissButton = { TextButton(onClick = vm::close, enabled = !vm.busy) { Text(stringResource(R.string.cancel)) } },
    )
}
