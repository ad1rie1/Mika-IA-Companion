package fr.qwartz.mika.ui.contacts

import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.ComposerDraft
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiDates
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.contacts.ContactFact
import fr.qwartz.mika.data.moi.contacts.ContactPlace
import fr.qwartz.mika.data.moi.contacts.ContactSheet
import fr.qwartz.mika.data.moi.contacts.ContactsDone
import fr.qwartz.mika.data.moi.contacts.FactKinds
import fr.qwartz.mika.data.moi.contacts.PlaceSources
import fr.qwartz.mika.data.moi.contacts.copied
import fr.qwartz.mika.data.moi.contacts.forgetFactQuestion
import fr.qwartz.mika.data.moi.contacts.forgetQuestion
import fr.qwartz.mika.data.moi.contacts.headLine
import fr.qwartz.mika.data.moi.contacts.identifierShown
import fr.qwartz.mika.data.moi.contacts.identifierSub
import fr.qwartz.mika.data.moi.contacts.idea
import fr.qwartz.mika.data.moi.contacts.lastExchange
import fr.qwartz.mika.data.moi.contacts.linkedWords
import fr.qwartz.mika.data.moi.contacts.noteFacts
import fr.qwartz.mika.data.moi.contacts.noteSource
import fr.qwartz.mika.data.moi.contacts.placeLine
import fr.qwartz.mika.data.moi.contacts.privacyNote
import fr.qwartz.mika.data.moi.contacts.profileFacts
import fr.qwartz.mika.data.moi.contacts.profileFrom
import fr.qwartz.mika.data.moi.contacts.writableAt
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.settings.DangerButton
import fr.qwartz.mika.ui.settings.SetDivider
import fr.qwartz.mika.ui.settings.SetGroup
import fr.qwartz.mika.ui.settings.SetHead
import fr.qwartz.mika.ui.settings.SetItem
import fr.qwartz.mika.ui.settings.copyText
import fr.qwartz.mika.ui.shell.BarMenu
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MenuEntry
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/**
 * La fiche d'un contact (`Route.Contact`), un modèle par contact : sa lecture (relue à chaque retour sur l'écran, ce
 * qui était montré gardé pendant la relecture), l'oublier, qu'elle oublie un fait — un geste à la fois, chacun sa clé
 * d'envoi (un double appui ne part qu'une fois). Oublié (ou déjà parti : 404), il quitte la liste et l'écran y revient.
 * Ce que le serveur refuse se dit avec ses mots ; la fiche se relit alors (elle a pu changer).
 */
class ContactSheetViewModel(deps: ContactsDeps) : ViewModel() {
    private val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des gestes, une fois chacun. */
    val said: Flow<String> = notices.receiveAsFlow()

    var id by mutableIntStateOf(0)
        private set
    var sheet by mutableStateOf<Load<ContactSheet>>(Load.Loading)
        private set
    /** Un oubli en route : ses boutons s'éteignent. */
    var busy by mutableStateOf(false)
        private set
    /** Oublié : l'écran revient à la liste (une fois, [leave]). */
    var gone by mutableStateOf(false)
        private set

    private var generation = 0
    private val forgetKey = SendKey()
    private val factKey = SendKey()

    private fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    /** L'écran s'ouvre ou revient : la première fois tout lire, ensuite relire sans bruit. */
    fun open(contact: Int) {
        if (contact == id && sheet !is Load.Failed) {
            load(keep = true)
            return
        }
        id = contact
        load(keep = false)
    }

    fun retry() = load(keep = false)

    /** Le direct (ADR 0308) : ses contacts ont changé (`contacts` : tout le domaine) — la fiche se relit sans bruit.
     *  Rend la main quand c'est relu. */
    suspend fun onLive(signal: LiveSignal) {
        if (id > 0 && signal.touches(Topics.CONTACTS)) load(keep = true).join()
    }

    /** L'écran est revenu à la liste. */
    fun leave() {
        gone = false
    }

    private fun load(keep: Boolean): Job {
        val gen = ++generation
        val contact = id
        if (!keep || sheet !is Load.Ready) sheet = Load.Loading
        return viewModelScope.launch {
            val got = api.sheet(contact)
            if (gen != generation) return@launch
            when (got) {
                is MoiApi.Result.Ok -> sheet = Load.Ready(got.value)
                // une relecture qui échoue garde ce qui était montré, sauf s'il n'est plus là
                is MoiApi.Result.Failed -> if (!keep || sheet !is Load.Ready || got.error.gone) sheet = Load.Failed(got.error)
            }
        }
    }

    /** « Oublier ce contact », confirmé : seulement ce que le serveur permet d'ici (`forget.allowed`). */
    fun forget() {
        val s = sheet.valueOrNull ?: return
        if (busy || !s.forget.allowed) return
        busy = true
        val key = forgetKey.of(listOf("forget", s.id))
        viewModelScope.launch {
            val got = api.forget(s.id, key)
            forgetKey.settled(networkFailure = got is MoiApi.Result.Failed && got.error.network)
            busy = false
            when (got) {
                is MoiApi.Result.Ok -> left(s.id, got.value)
                is MoiApi.Result.Failed -> {
                    say(got.error.said)
                    // déjà oublié (404) : il n'y a plus rien à montrer ; refusé (403), la fiche a pu changer
                    if (got.error.gone) left(s.id, null) else if (!got.error.network) load(keep = true)
                }
            }
        }
    }

    private fun left(contact: Int, done: ContactsDone?) {
        if (done != null) say(done.message)
        ContactsChanges.forgot(contact)
        gone = true
    }

    /** La croix d'un fait, confirmée : qu'elle l'oublie (un fait d'un de tes comptes) ; la fiche se relit. */
    fun forgetFact(fact: Int) {
        val s = sheet.valueOrNull ?: return
        if (busy || s.facts.none { it.note && it.id == fact && it.forget }) return
        busy = true
        val key = factKey.of(listOf("fact", fact))
        viewModelScope.launch {
            val got = api.forgetFact(fact, key)
            factKey.settled(networkFailure = got is MoiApi.Result.Failed && got.error.network)
            busy = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    say(got.value.message)
                    load(keep = true)
                }
                is MoiApi.Result.Failed -> {
                    say(got.error.said)
                    if (!got.error.network) load(keep = true)
                }
            }
        }
    }
}

/** Ce que demande une feuille ouverte : l'oubli du contact, ou celui d'un fait (son identifiant). */
private sealed interface Ask {
    data object Contact : Ask
    data class Fact(val id: Int) : Ask
}

/**
 * La fiche d'un contact (ADR 0298, la maquette validée `ecrans/contacts.js`), en page : sa tête (son rond, son nom, son
 * poste et son organisation — qui ouvre sa fiche —, « parle aussi à Mika » ou « a un compte »), Écrire · Teams ·
 * Message (seulement ceux que le serveur donne), d'où elle le connaît et le dernier échange ; ses personnes (une
 * organisation) ; ce qui l'identifie (un appui long copie, ✉ écrit à cette adresse) ; ce que Mika en sait, en rose
 * (une personne : son profil, puis ce qu'elle a compris de ses messages, × l'oublie après une feuille qui confirme) ;
 * où vous vous croisez ; d'où vient ce qu'elle en sait ; « Oublier ce contact », ou pourquoi on ne le peut pas d'ici.
 */
@Composable
fun ContactSheetScreen(graph: AppGraph, route: Route.Contact) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: ContactSheetViewModel = viewModel(key = "contacts.sheet|${route.id}|$session") { ContactSheetViewModel(ContactsDeps(graph)) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    // lue à l'ouverture, relue à chaque retour, et quand le direct dit que ses contacts ont changé (ADR 0308)
    FollowLive(graph.live, CONTACTS_TOPICS, vm, route.id, onShown = { vm.open(route.id) }) { vm.onLive(it) }
    LaunchedEffect(vm.gone) {
        if (vm.gone) {
            vm.leave()
            shell.back()
        }
    }
    var ask by rememberSaveable(stateSaver = AskSaver) { mutableStateOf<Ask?>(null) }
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val copiedText = stringResource(R.string.contacts_copied)
    val s = vm.sheet.valueOrNull?.takeIf { it.id == route.id }
    val talkAbout = { name: String ->
        graph.scope.launch { graph.shareInbox.deposit(ComposerDraft(text = "À propos de $name : ")) }
        shell.open(Route.Chat)
    }
    val copy = { text: String ->
        scope.launch {
            copyText(clipboard, text)
            shell.toast(copiedText.format(text))
        }
        Unit
    }
    SectionScaffold(
        topBar = {
            MikaTopBar(title = "", nav = BarNav.BACK, face = false) {
                if (s != null) {
                    BarMenu(
                        listOfNotNull(
                            MenuEntry(stringResource(R.string.contacts_menu_ask), R.drawable.ic_m_chat) { talkAbout(s.name) },
                            s.write?.let { w -> MenuEntry(stringResource(R.string.contacts_menu_copy), R.drawable.ic_m_copy) { copy(w.address) } },
                            MenuEntry(stringResource(R.string.contacts_forget), R.drawable.ic_m_trash) { ask = Ask.Contact },
                        ),
                    )
                }
            }
        },
    ) { modifier ->
        LoadBox(if (s != null) Load.Ready(s) else if (vm.sheet is Load.Failed) vm.sheet else Load.Loading, onRetry = vm::retry, modifier = modifier) { sheet ->
            SheetBody(
                s = sheet,
                busy = vm.busy,
                modifier = modifier,
                onOpen = shell.navigate,
                onCopy = copy,
                onAskFact = { ask = Ask.Fact(it) },
                onAskForget = { ask = Ask.Contact },
            )
        }
    }
    val asked = ask
    if (s != null && asked != null) {
        when (asked) {
            Ask.Contact -> ForgetContactSheet(s, vm.busy, onDismiss = { ask = null }) {
                ask = null
                vm.forget()
            }
            is Ask.Fact -> {
                val f = s.facts.firstOrNull { it.note && it.id == asked.id }
                if (f == null) {
                    // le fait n'est plus sur la fiche (oublié, relu) : la feuille n'a plus d'objet
                    LaunchedEffect(asked) { ask = null }
                } else {
                    ForgetFactSheet(f, vm.busy, onDismiss = { ask = null }) {
                        ask = null
                        vm.forgetFact(f.id)
                    }
                }
            }
        }
    }
}

/** Une feuille ouverte survit à une rotation. */
private val AskSaver = androidx.compose.runtime.saveable.Saver<Ask?, Int>(
    save = { a -> when (a) { null -> -1; Ask.Contact -> 0; is Ask.Fact -> a.id + 1 } },
    restore = { n -> when { n < 0 -> null; n == 0 -> Ask.Contact; else -> Ask.Fact(n - 1) } },
)

@Composable
private fun SheetBody(
    s: ContactSheet,
    busy: Boolean,
    modifier: Modifier,
    onOpen: (Route) -> Unit,
    onCopy: (String) -> Unit,
    onAskFact: (Int) -> Unit,
    onAskForget: () -> Unit,
) {
    val now = rememberNow()
    Column(modifier.verticalScroll(rememberScrollState()).padding(bottom = 8.dp)) {
        Hero(s, now, onOpen)
        if (s.org) Members(s, now, onOpen)
        Identifiers(s, onOpen, onCopy)
        if (!s.org) Knows(s, busy, onOpen, onAskFact)
        Places(s, now, onOpen)
        Row(Modifier.fillMaxWidth().padding(start = 24.dp, end = 24.dp, top = 16.dp, bottom = 4.dp)) {
            MIcon(R.drawable.ic_m_lock, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
            Spacer(Modifier.width(8.dp))
            Text(privacyNote(s.name, s.privacy), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Gap(8.dp)
        DangerButton(stringResource(R.string.contacts_forget), onAskForget, enabled = !busy)
        Gap(20.dp)
    }
}

/** La tête (`.cx-hero`), les gestes (`.cx-acts`) et d'où elle le connaît (`.cx-facts`). */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Hero(s: ContactSheet, now: Long, onOpen: (Route) -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Column(Modifier.fillMaxWidth().padding(start = 24.dp, end = 24.dp, bottom = 14.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        ContactAvatar(s.name, contactKey(s.id), s.org, 80.dp)
        Gap(8.dp)
        Text(s.name, fontSize = 24.sp, lineHeight = 32.sp, textAlign = TextAlign.Center, modifier = Modifier.semantics { heading() })
        val line = headLine(s)
        val org = s.organisation
        if (line.isNotBlank() || org != null) {
            FlowRow(horizontalArrangement = Arrangement.Center, modifier = Modifier.padding(top = 2.dp)) {
                if (line.isNotBlank()) Text(line, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, textAlign = TextAlign.Center)
                if (line.isNotBlank() && org != null) Text(" · ", style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant)
                if (org != null) OrgLink(org.name) { onOpen(Route.Contact(org.id)) }
            }
        }
        val linked = linkedWords(s.linked, s.talks)
        if (linked.isNotEmpty()) {
            Gap(6.dp)
            Tag(linked, if (s.talks) Tone.OK else Tone.NEUTRAL)
        }
    }
    val write = s.write
    val acts = listOfNotNull(
        write?.let { Act(R.drawable.ic_m_mail, R.string.contacts_write, main = true) { onOpen(Route.MailCompose(to = it.address, toName = it.name)) } },
        s.teams.takeIf { it.isNotBlank() }?.let { Act(R.drawable.ic_m_teams, R.string.contacts_teams) { onOpen(Route.TeamsThread(it)) } },
        s.message.takeIf { it.isNotBlank() }?.let { Act(R.drawable.ic_m_phone, R.string.contacts_message) { onOpen(Route.PhoneThread(it)) } },
    )
    if (acts.isNotEmpty()) {
        Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 14.dp), horizontalArrangement = Arrangement.spacedBy(24.dp, Alignment.CenterHorizontally)) {
            for (a in acts) ActButton(a)
        }
    }
    val last = lastExchange(s.last, now)
    if (s.sources.isNotEmpty() || last.isNotEmpty()) {
        FlowRow(
            Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 4.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            for (src in s.sources) Tag(if (src.count > 0) "${src.label} · ${src.count}" else src.label, Tone.NEUTRAL, sourceIcon(src.source))
            if (last.isNotEmpty()) Tag(last, Tone.NEUTRAL, R.drawable.ic_m_clock)
        }
    }
}

/** Le nom d'une organisation, qui ouvre sa fiche (`.cx-link`). */
@Composable
private fun OrgLink(name: String, onClick: () -> Unit) {
    val label = stringResource(R.string.contacts_open_org, name)
    Text(
        name,
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.primary,
        fontWeight = FontWeight.Medium,
        modifier = Modifier.clickable(role = Role.Button, onClickLabel = label, onClick = onClick),
    )
}

/** Un geste de la tête : Écrire (le principal), Teams, Message. */
private class Act(@param:DrawableRes val icon: Int, @param:StringRes val label: Int, val main: Boolean = false, val onClick: () -> Unit)

@Composable
private fun ActButton(a: Act) {
    val scheme = MaterialTheme.colorScheme
    Column(
        Modifier.widthIn(min = 64.dp).clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = a.onClick).padding(4.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Box(
            Modifier.size(width = 56.dp, height = 40.dp).clip(RoundedCornerShape(20.dp))
                .background(if (a.main) scheme.primaryContainer else scheme.secondaryContainer),
            contentAlignment = Alignment.Center,
        ) { MIcon(a.icon, null, tint = if (a.main) scheme.onPrimaryContainer else scheme.onSecondaryContainer) }
        Gap(6.dp)
        Text(stringResource(a.label), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
    }
}

/** Ses personnes parmi tes contacts (une organisation) : celles dont tu vois la preuve qu'elles en sont. */
@Composable
private fun Members(s: ContactSheet, now: Long, onOpen: (Route) -> Unit) {
    if (s.members.isEmpty()) return
    SetHead(stringResource(R.string.contacts_members))
    SetGroup {
        s.members.forEachIndexed { i, m ->
            if (i > 0) SetDivider()
            SetItem(
                icon = null,
                title = m.name,
                subtitle = idea(m.title, m.department).ifBlank { linkedWords(m.linked, m.talks) },
                onClick = { onOpen(Route.Contact(m.id)) },
                lead = { ContactAvatar(m.name, contactKey(m.id), org = false, size = 32.dp) },
            ) { Text(MoiDates.short(m.last, now), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
    }
    val rest = s.membersTotal - s.members.size
    if (rest > 0) Note(pluralStringResource(R.plurals.contacts_members_more, rest, rest))
}

/** Ce qui l'identifie : la sorte, la valeur, d'où elle la tient ; une adresse générique le dit ; ✉ écrit à cette
 *  adresse (une personne, quand une de tes boîtes envoie) ; un appui long copie. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun Identifiers(s: ContactSheet, onOpen: (Route) -> Unit, onCopy: (String) -> Unit) {
    val scheme = MaterialTheme.colorScheme
    SetHead(stringResource(R.string.contacts_identifies))
    if (s.identifiers.isEmpty()) {
        Note(stringResource(if (s.org) R.string.contacts_no_ways_org else R.string.contacts_no_ways))
        return
    }
    SetGroup {
        s.identifiers.forEachIndexed { n, i ->
            if (n > 0) SetDivider()
            val write = writableAt(s, i)
            val value = copied(i)
            val toWrite = { onOpen(Route.MailCompose(to = i.value, toName = s.name)) }
            Row(
                Modifier.fillMaxWidth()
                    .combinedClickable(
                        enabled = write || value.isNotEmpty(),
                        onClick = { if (write) toWrite() },
                        onLongClick = if (value.isNotEmpty()) ({ onCopy(value) }) else null,
                    )
                    .heightIn(min = 56.dp)
                    .padding(start = 14.dp, end = 6.dp, top = 10.dp, bottom = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(40.dp), contentAlignment = Alignment.Center) { MIcon(identIcon(i.kind), null, tint = scheme.onSurfaceVariant) }
                Spacer(Modifier.width(16.dp))
                Column(Modifier.weight(1f)) {
                    Text(identifierShown(i), style = MaterialTheme.typography.bodyLarge)
                    val sub = identifierSub(i)
                    if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                if (write) {
                    IconButton(onClick = toWrite) { MIcon(R.drawable.ic_m_send, stringResource(R.string.contacts_write_at, i.value), size = 20.dp, tint = scheme.primary) }
                }
            }
        }
    }
}

/** Ce que Mika en sait, en rose (`.set-group.mk`) : son profil, puis ce qu'elle a compris de ses derniers messages. */
@Composable
private fun Knows(s: ContactSheet, busy: Boolean, onOpen: (Route) -> Unit, onAskFact: (Int) -> Unit) {
    Row(
        Modifier.padding(start = 28.dp, end = 28.dp, top = 18.dp, bottom = 6.dp).semantics(mergeDescendants = true) { heading() },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(R.drawable.ic_m_sparkle, null, size = 16.dp, tint = mika.accent)
        Spacer(Modifier.width(6.dp))
        Text(stringResource(R.string.contacts_knows), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium, color = mika.accent)
    }
    val profile = profileFacts(s)
    val notes = noteFacts(s)
    if (profile.isEmpty() && notes.isEmpty()) {
        Note(stringResource(R.string.contacts_knows_nothing))
        return
    }
    PinkGroup {
        var first = true
        for (f in profile) {
            if (!first) HorizontalDivider(color = mika.line)
            first = false
            ProfileFact(f, onOpen)
        }
        for (f in notes) {
            if (!first) HorizontalDivider(color = mika.line)
            first = false
            NoteFact(f, busy) { onAskFact(f.id) }
        }
    }
}

@Composable
private fun PinkGroup(content: @Composable ColumnScope.() -> Unit) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = mika.soft,
        border = BorderStroke(1.dp, mika.line),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
    ) { Column(content = content) }
}

/** Un fait de son profil (`.cx-kv`) : son nom à gauche, sa valeur — son organisation ouvre sa fiche —, d'après quoi. */
@Composable
private fun ProfileFact(f: ContactFact, onOpen: (Route) -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 11.dp)) {
        Text(f.label, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.width(96.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            if (f.kind == FactKinds.ORGANISATION && f.id > 0) OrgLink(f.value) { onOpen(Route.Contact(f.id)) } else Text(f.value, style = MaterialTheme.typography.bodyMedium)
            val from = profileFrom(f)
            if (from.isNotBlank()) Text(from, style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant)
        }
    }
}

/** Ce qu'elle a compris de ses messages (`.cx-fait`) : la phrase, d'où et sûre à combien ; × l'oublie, un cadenas dit
 *  pourquoi elle ne le peut pas d'ici (un compte qui n'est pas à toi). */
@Composable
private fun NoteFact(f: ContactFact, busy: Boolean, onAsk: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Row(Modifier.fillMaxWidth().padding(start = 14.dp, end = 2.dp, top = 11.dp, bottom = 11.dp), verticalAlignment = Alignment.Top) {
        Column(Modifier.weight(1f)) {
            Text(f.value, style = MaterialTheme.typography.bodyMedium)
            val from = noteSource(f)
            if (from.isNotBlank()) Text(from, style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 2.dp))
        }
        IconButton(onClick = onAsk, enabled = !busy, modifier = Modifier.size(40.dp)) {
            MIcon(
                if (f.forget) R.drawable.ic_m_x else R.drawable.ic_m_lock,
                stringResource(if (f.forget) R.string.contacts_fact_forget_label else R.string.contacts_fact_locked_label),
                size = 16.dp,
                tint = scheme.onSurfaceVariant,
            )
        }
    }
}

/** Où vous vous croisez : chaque ligne ouvre sa discussion Teams, son mail, sa conversation du téléphone. */
@Composable
private fun Places(s: ContactSheet, now: Long, onOpen: (Route) -> Unit) {
    if (s.places.isEmpty()) return
    SetHead(stringResource(R.string.contacts_crossed))
    SetGroup {
        s.places.forEachIndexed { i, p ->
            if (i > 0) SetDivider()
            val line = placeLine(p, s.name, now)
            SetItem(placeIcon(line.icon), line.title, line.detail, onClick = { onOpen(placeRoute(p)) }) {
                MIcon(R.drawable.ic_m_chev_right, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

/** L'écran qu'ouvre un lieu : sa discussion Teams, son dernier mail (sans mail reçu de lui, Mail), sa conversation du
 *  téléphone. */
private fun placeRoute(p: ContactPlace): Route = when (p.source) {
    PlaceSources.TEAMS -> Route.TeamsThread(p.conversation)
    PlaceSources.MAIL -> if (p.ref.isNotBlank()) Route.MailMessage(p.ref) else Route.Mail
    else -> Route.PhoneThread(p.conversation)
}

/** Une ligne de texte discret sous un titre de groupe. */
@Composable
private fun Note(text: String) {
    Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(start = 28.dp, end = 28.dp, top = 4.dp))
}

// ── Les feuilles ────────────────────────────────────────────────────────

/** « Oublier ce contact » : confirmé dans une feuille ; refusé d'ici (`forget.allowed` faux), ses mots et « Compris ». */
@Composable
private fun ForgetContactSheet(s: ContactSheet, busy: Boolean, onDismiss: () -> Unit, onForget: () -> Unit) {
    if (!s.forget.allowed) {
        AskSheet(stringResource(R.string.contacts_forget_refused_title, s.name), listOf(s.forget.reason), onDismiss, confirm = null, onConfirm = {})
    } else {
        AskSheet(
            stringResource(R.string.contacts_forget_title, s.name),
            listOf(forgetQuestion(s.name)),
            onDismiss,
            confirm = stringResource(R.string.contacts_forget_confirm),
            icon = R.drawable.ic_m_trash,
            enabled = !busy,
            onConfirm = onForget,
        )
    }
}

/** La croix d'un fait : « Oublier ce fait ? » ; un fait d'un compte qui n'est pas à toi, pourquoi pas d'ici. */
@Composable
private fun ForgetFactSheet(f: ContactFact, busy: Boolean, onDismiss: () -> Unit, onForget: () -> Unit) {
    if (!f.forget) {
        AskSheet(stringResource(R.string.contacts_forget_fact_locked_title), listOf("« ${f.value} »", stringResource(R.string.contacts_not_your_fact)), onDismiss, confirm = null, onConfirm = {})
    } else {
        AskSheet(
            stringResource(R.string.contacts_forget_fact_title),
            listOf(forgetFactQuestion(f.value), stringResource(R.string.contacts_forget_fact_after)),
            onDismiss,
            confirm = stringResource(R.string.contacts_forget_confirm),
            icon = R.drawable.ic_m_x,
            enabled = !busy,
            onConfirm = onForget,
        )
    }
}

/** Une feuille de la maquette (`A.sheet`) : son titre, ses paragraphes, « Annuler » et le geste en rouge — ou
 *  « Compris » seul ([confirm] nul). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun AskSheet(
    title: String,
    paragraphs: List<String>,
    onDismiss: () -> Unit,
    confirm: String?,
    onConfirm: () -> Unit,
    @DrawableRes icon: Int? = null,
    enabled: Boolean = true,
) {
    val state = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = state) {
        Column(Modifier.navigationBarsPadding().padding(bottom = 6.dp)) {
            Text(title, style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = 24.dp, end = 24.dp, bottom = 12.dp).semantics { heading() })
            for (p in paragraphs.filter { it.isNotBlank() }) {
                Text(p, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(start = 24.dp, end = 24.dp, bottom = 10.dp))
            }
            Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End)) {
                TextButton(onClick = onDismiss) { Text(stringResource(if (confirm != null) R.string.cancel else R.string.contacts_understood)) }
                if (confirm != null) {
                    Button(
                        onClick = onConfirm,
                        enabled = enabled,
                        colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error, contentColor = MaterialTheme.colorScheme.onError),
                        modifier = Modifier.semantics { contentDescription = confirm },
                    ) {
                        if (icon != null) {
                            MIcon(icon, null, size = 18.dp)
                            Spacer(Modifier.width(6.dp))
                        }
                        Text(confirm)
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}
