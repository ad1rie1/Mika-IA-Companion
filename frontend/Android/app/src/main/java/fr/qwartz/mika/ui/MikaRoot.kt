package fr.qwartz.mika.ui

import androidx.activity.compose.BackHandler
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DrawerValue
import androidx.compose.material3.ModalNavigationDrawer
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDrawerState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.key
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.res.stringResource
import fr.qwartz.mika.R
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.ChatCue
import fr.qwartz.mika.ui.shell.LocalChatCue
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MikaDrawerSheet
import fr.qwartz.mika.ui.shell.Shell
import fr.qwartz.mika.ui.shell.rememberMikaStatus
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.launch
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.auth.Session
import fr.qwartz.mika.data.files.MikaFileRefs
import fr.qwartz.mika.data.settings.Settings
import fr.qwartz.mika.ui.agenda.AgendaEventScreen
import fr.qwartz.mika.ui.agenda.AgendaFormScreen
import fr.qwartz.mika.ui.agenda.AgendaHerScreen
import fr.qwartz.mika.ui.agenda.AgendaInvitationsScreen
import fr.qwartz.mika.ui.agenda.AgendaProposalScreen
import fr.qwartz.mika.ui.agenda.AgendaScreen
import fr.qwartz.mika.ui.agenda.AgendaSearchScreen
import fr.qwartz.mika.ui.agenda.CalendarRightsScreen
import fr.qwartz.mika.ui.carte.CarteScreen
import fr.qwartz.mika.ui.carte.EventFicheScreen
import fr.qwartz.mika.ui.carte.PlaceFicheScreen
import fr.qwartz.mika.ui.carte.TripScreen
import fr.qwartz.mika.ui.chat.ChatScreen
import fr.qwartz.mika.ui.chat.FilesScreen
import fr.qwartz.mika.ui.chat.SearchScreen
import fr.qwartz.mika.ui.contacts.ContactSheetScreen
import fr.qwartz.mika.ui.contacts.ContactsScreen
import fr.qwartz.mika.ui.login.LoginScreen
import fr.qwartz.mika.ui.mail.MailComposeScreen
import fr.qwartz.mika.ui.mail.MailDraftScreen
import fr.qwartz.mika.ui.mail.MailDraftsScreen
import fr.qwartz.mika.ui.mail.MailListScreen
import fr.qwartz.mika.ui.mail.MailReaderScreen
import fr.qwartz.mika.ui.mind.MindScreen
import fr.qwartz.mika.ui.phone.PhoneScreen
import fr.qwartz.mika.ui.phone.PhoneThreadScreen
import fr.qwartz.mika.ui.projects.CodeScreen
import fr.qwartz.mika.ui.projects.GoalScreen
import fr.qwartz.mika.ui.projects.ProjectScreen
import fr.qwartz.mika.ui.projects.SheetPageScreen
import fr.qwartz.mika.ui.projects.ProjectsScreen
import fr.qwartz.mika.ui.projects.TicketScreen
import fr.qwartz.mika.ui.projects.TodoScreen
import fr.qwartz.mika.ui.settings.SettingsPageScreen
import fr.qwartz.mika.ui.settings.SettingsScreen
import fr.qwartz.mika.ui.teams.TeamsListScreen
import fr.qwartz.mika.ui.teams.TeamsRepliesScreen
import fr.qwartz.mika.ui.teams.TeamsThreadScreen
import fr.qwartz.mika.ui.theme.MikaTheme
import fr.qwartz.mika.ui.tools.ToolsScreen
import fr.qwartz.mika.ui.viewer.ImageViewerScreen

/** La porte de l'app : la session décide de l'écran ; une fois connectée, une petite pile d'écrans. */
@Composable
fun MikaRoot(graph: AppGraph, deepLink: String?, onDeepLinkHandled: () -> Unit) {
    val settings by graph.settings.settings.collectAsStateWithLifecycle(Settings())
    MikaTheme(settings.theme, settings.dynamicColor) {
        Surface(Modifier.fillMaxSize()) {
            val session by graph.auth.session.collectAsStateWithLifecycle()
            when (val s = session) {
                Session.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator()
                }
                is Session.LoggedOut -> LoginScreen(graph, s.reason)
                is Session.LoggedIn -> SignedIn(graph, deepLink, onDeepLinkHandled)
            }
        }
    }
}

private val StackSaver = Saver<BackStack, String>(save = { it.encode() }, restore = { BackStack.decode(it) })

/** Ce que suit le cadre : qui est connecté, et ses pastilles (ADR 0200, 0308). */
private val ME_TOPICS = setOf(Topics.ME)

/** Ce que suit le canal « Agenda » : l'agenda (ADR 0309). */
private val AGENDA_NOTIFY_TOPICS = setOf(Topics.AGENDA)

/** Un écran de l'Agenda est au sommet (ce qui y arrive se voit : rien ne se notifie). */
private val Route.isAgenda: Boolean
    get() = this == Route.Agenda || this is Route.AgendaEvent || this is Route.AgendaProposal || this is Route.AgendaHer ||
        this is Route.AgendaForm || this == Route.AgendaInvitations || this == Route.AgendaSearch

@Composable
private fun SignedIn(graph: AppGraph, deepLink: String?, onDeepLinkHandled: () -> Unit) {
    var stack by rememberSaveable(stateSaver = StackSaver) { mutableStateOf(BackStack()) }
    var confirmLogout by rememberSaveable { mutableStateOf(false) }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val me by graph.me.me.collectAsStateWithLifecycle()
    // La conversation est-elle au sommet ? Les notifications le demandent (`AppForeground.chatOnScreen`) : dans Mail ou
    // Teams, l'app ouverte ne montre pas sa réponse. Hors session (ce cadre parti), elle n'y est pas.
    val chatShown = stack.showsChat
    DisposableEffect(graph, chatShown) {
        graph.foreground.onTop(chat = chatShown)
        onDispose { graph.foreground.onTop(chat = false) }
    }
    // Hors du chat, ce qui y attend : un accord, ou ce qu'elle a écrit depuis ton dernier lu (la pastille de ☰).
    val lastFromMika by remember(graph) { graph.chat.observeLastFromMika() }.collectAsStateWithLifecycle(0L)
    val lastRead by remember(graph) { graph.chat.observeLastReadId() }.collectAsStateWithLifecycle(0L)
    val approvals by graph.approvals.state.collectAsStateWithLifecycle()
    val now = rememberNow(wallMs = graph.clock::wallMs)
    val chatCue = !chatShown && ChatCue.waiting(lastFromMika, lastRead, approvals, now, graph.clock.elapsedMs())
    LaunchedEffect(deepLink) {
        if (deepLink != null) {
            stack = BackStack.forDeepLink(deepLink)
            onDeepLinkHandled()
        }
    }
    // qui est connecté et ce qui attend sa décision : à l'ouverture et à chaque retour de l'app au premier plan, puis
    // quand le direct dit `me` (ADR 0308) — une rafale, une lecture en vol et une seule après
    FollowLive(graph.live, ME_TOPICS, graph.me, onShown = { graph.me.refresh() }) { graph.me.refresh() }
    // le canal « Agenda » (ADR 0309) : une invitation, un ajout que Mika propose, arrivés pendant que l'app est ouverte
    // ailleurs que dans l'Agenda (là, la vue se relit en direct et rien ne se notifie)
    val session = rememberSessionKey(graph)
    LaunchedEffect(session) { graph.agendaPrefs.open(session) }
    val agendaShown = stack.top.isAgenda
    DisposableEffect(graph, agendaShown) {
        graph.agendaNotifier.shown = agendaShown
        onDispose { graph.agendaNotifier.shown = false }
    }
    FollowLive(graph.live, AGENDA_NOTIFY_TOPICS, session, onShown = { graph.scope.launch { graph.agendaNotifier.check() } }) { graph.agendaNotifier.check() }
    val snackbar = remember { SnackbarHostState() }
    val shell = remember(graph) {
        Shell(
            graph = graph,
            snackbar = snackbar,
            toast = { text -> scope.launch { snackbar.currentSnackbarData?.dismiss(); snackbar.showSnackbar(text) } },
            offer = { text, action, onAction ->
                scope.launch {
                    snackbar.currentSnackbarData?.dismiss()
                    val got = snackbar.showSnackbar(text, actionLabel = action, duration = SnackbarDuration.Long)
                    if (got == SnackbarResult.ActionPerformed) onAction()
                }
            },
            navigate = { route -> stack = stack.push(route) },
            open = { route ->
                stack = stack.open(route)
                scope.launch { drawer.close() }
            },
            replace = { route -> stack = stack.replaceTop(route) },
            back = { stack.pop()?.let { stack = it } },
            openDrawer = { scope.launch { drawer.open() } },
        )
    }
    // le sort d'un envoi de Mail fini après qu'on a quitté « Écrire » : dit où qu'on soit
    LaunchedEffect(graph, shell) { graph.mailNotices.flow.collect { shell.toast(it) } }
    // Le geste « retour » (prédictif depuis Android 14) dépile ; à la racine, il sort de l'app. Déclaré avant l'écran :
    // ceux de l'écran (une sélection, une recherche, « Écrire » commencé) passent devant lui.
    BackHandler(enabled = stack.canPop && !drawer.isOpen) { stack.pop()?.let { stack = it } }
    CompositionLocalProvider(LocalShell provides shell, LocalChatCue provides chatCue) {
        ModalNavigationDrawer(
            drawerState = drawer,
            // le tiroir s'ouvre d'un glissé depuis une rubrique ; sur un écran par-dessus, la flèche ramène d'abord
            gesturesEnabled = stack.top.isTopLevel || drawer.isOpen,
            drawerContent = {
                MikaDrawerSheet(
                    section = stack.section,
                    me = me,
                    status = rememberMikaStatus(),
                    chatCue = chatCue,
                    onOpen = shell.open,
                    onMind = { scope.launch { drawer.close() }; stack = stack.push(Route.Mind) },
                    onSearch = { scope.launch { drawer.close() }; stack = stack.push(Route.Search()) },
                    onAccount = { stack = stack.open(Route.Settings).push(Route.SettingsPage("compte")); scope.launch { drawer.close() } },
                    onLogout = { scope.launch { drawer.close() }; confirmLogout = true },
                )
            },
        ) {
            Screen(graph, stack, shell)
            // Tiroir ouvert, « retour » le ferme d'abord, quel que soit l'écran dessous : le dernier inscrit passe devant,
            // d'où ce gestionnaire après l'écran, et réinscrit à chaque nouvel écran (sinon les siens, inscrits après,
            // effaceraient une sélection derrière le tiroir).
            key(stack.top) { BackHandler(enabled = drawer.isOpen) { scope.launch { drawer.close() } } }
        }
    }
    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            title = { Text(stringResource(R.string.logout_confirm_title)) },
            text = { Text(stringResource(R.string.logout_confirm_text)) },
            confirmButton = {
                TextButton(onClick = {
                    confirmLogout = false
                    // dans la portée du graphe : la session qui se ferme retire cet écran, la déconnexion va au bout
                    graph.scope.launch { graph.auth.logout() }
                }) { Text(stringResource(R.string.menu_logout)) }
            },
            dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

/** L'écran du sommet de la pile. */
@Composable
private fun Screen(graph: AppGraph, stack: BackStack, shell: Shell) {
    when (val top = stack.top) {
        Route.Chat -> ChatScreen(
            graph,
            onOpenMind = { shell.navigate(Route.Mind) },
            onOpenSettings = { shell.open(Route.Settings) },
            onOpenImage = { att ->
                val path = MikaFileRefs.path(att)
                if (path != null && att.id != null) {
                    shell.navigate(Route.Viewer(att.id, att.name, path, att.mime, att.size))
                }
            },
            onMenu = shell.openDrawer,
            // la loupe cherche d'abord dans la conversation ; ⋮ › Fichiers échangés ; ses brouillons, là où ils se décident
            onOpenSearch = { shell.navigate(Route.Search("chat")) },
            onOpenFiles = { shell.navigate(Route.Files) },
            onOpen = shell.navigate,
        )
        Route.Mind -> MindScreen(graph, onBack = shell.back)
        Route.Settings -> SettingsScreen(graph)
        is Route.Viewer -> ImageViewerScreen(graph, top, onBack = shell.back)
        // Projets (ADR 0296) : la rubrique, puis une liste ouvre son détail en page
        is Route.Projects -> ProjectsScreen(graph, top.tab, if (stack.routes.size <= 2) BarNav.DRAWER else BarNav.BACK)
        is Route.ProjectTodo -> TodoScreen(graph, top)
        is Route.Project -> ProjectScreen(graph, top)
        is Route.ProjectGoal -> GoalScreen(graph, top)
        is Route.ProjectTicket -> TicketScreen(graph, top)
        is Route.ProjectCode -> CodeScreen(graph, top)
        is Route.ProjectPage -> SheetPageScreen(graph, top)
        Route.Mail -> MailListScreen(graph)
        is Route.MailMessage -> MailReaderScreen(graph, top.ref)
        Route.MailDrafts -> MailDraftsScreen(graph)
        is Route.MailDraft -> MailDraftScreen(graph, top.id)
        is Route.MailCompose -> MailComposeScreen(graph, top)
        Route.Teams -> TeamsListScreen(graph)
        is Route.TeamsThread -> TeamsThreadScreen(graph, top.key)
        Route.TeamsReplies -> TeamsRepliesScreen(graph)
        // l'Agenda (ADR 0309) : la rubrique, puis la fiche, le formulaire, les invitations, chercher en page
        Route.Agenda -> AgendaScreen(graph)
        is Route.AgendaEvent -> AgendaEventScreen(graph, top)
        is Route.AgendaProposal -> AgendaProposalScreen(graph, top)
        is Route.AgendaHer -> AgendaHerScreen(graph, top)
        is Route.AgendaForm -> AgendaFormScreen(graph, top)
        Route.AgendaInvitations -> AgendaInvitationsScreen(graph)
        Route.AgendaSearch -> AgendaSearchScreen(graph)
        is Route.CalendarRights -> CalendarRightsScreen(graph, top)
        // le tiroir depuis le tiroir ; la flèche quand un autre écran y mène
        is Route.Carte -> CarteScreen(graph, top, if (stack.routes.size <= 2) BarNav.DRAWER else BarNav.BACK)
        is Route.Trip -> TripScreen(graph, top)
        is Route.PlaceFiche -> PlaceFicheScreen(graph, top)
        is Route.EventFiche -> EventFicheScreen(graph, top)
        is Route.Phone -> PhoneScreen(graph, top.tab)
        is Route.PhoneThread -> PhoneThreadScreen(graph, top.key)
        Route.Contacts -> ContactsScreen(graph, if (stack.routes.size <= 2) BarNav.DRAWER else BarNav.BACK)
        is Route.Contact -> ContactSheetScreen(graph, top)
        // le tiroir depuis le tiroir ; la flèche quand un autre écran y mène (« Comment ça part » de Teams…)
        is Route.Tools -> ToolsScreen(graph, top.tab, if (stack.routes.size <= 2) BarNav.DRAWER else BarNav.BACK)
        is Route.SettingsPage -> SettingsPageScreen(graph, top)
        is Route.Search -> SearchScreen(graph, top.scope)
        Route.Files -> FilesScreen(graph)
    }
}
