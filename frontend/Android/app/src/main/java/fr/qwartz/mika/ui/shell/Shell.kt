package fr.qwartz.mika.ui.shell

import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.avatar.AvatarDirector
import fr.qwartz.mika.data.mind.StatusLine
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.avatar.AvatarFace
import fr.qwartz.mika.ui.avatar.auraColor
import fr.qwartz.mika.ui.avatar.rememberPortrait
import fr.qwartz.mika.ui.components.MikaAvatar
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.theme.mika

/**
 * Ce que chaque écran reçoit du cadre (ADR 0235) : aller ailleurs, revenir, ouvrir le tiroir. Les écrans d'une
 * rubrique le lisent par [LocalShell] plutôt que de se faire passer une rappel par geste.
 */
class Shell(
    val graph: AppGraph,
    /** Un écran par-dessus celui-ci (un mail, un fil, une page de réglages). */
    val navigate: (Route) -> Unit,
    /** Une rubrique du tiroir, juste au-dessus du chat. */
    val open: (Route) -> Unit,
    /** Le même écran sous une autre forme (un autre onglet). */
    val replace: (Route) -> Unit,
    val back: () -> Unit,
    val openDrawer: () -> Unit,
    /** Les messages furtifs de l'écran (le sort d'un geste : « Envoyé », un refus). */
    val snackbar: SnackbarHostState = SnackbarHostState(),
    /** Dire le sort d'un geste, sans attendre qu'il soit lu. */
    val toast: (String) -> Unit = {},
    /**
     * Dire le sort d'un geste fini ailleurs, où qu'on soit, avec de quoi y aller ([action], « Ouvrir ») ou le défaire
     * (« Annuler », une ligne de Mail glissée à la corbeille) : [onAction] seulement si on le touche — rien ne se fait
     * tout seul.
     */
    val offer: (text: String, action: String, onAction: () -> Unit) -> Unit = { text, _, _ -> toast(text) },
)

val LocalShell = staticCompositionLocalOf<Shell> { error("pas de cadre : l'écran doit être dans SignedIn") }

/** Une icône du jeu de la maquette (`tools/icones.py`, `ic_m_*`), teintée par Compose. */
@Composable
fun MIcon(@DrawableRes id: Int, contentDescription: String?, modifier: Modifier = Modifier, tint: Color? = null, size: Dp = 24.dp) {
    if (tint == null) {
        Icon(painterResource(id), contentDescription, modifier.size(size))
    } else {
        Icon(painterResource(id), contentDescription, modifier.size(size), tint = tint)
    }
}

/** Un bouton-icône de barre du haut, son nom dit à l'accessibilité. */
@Composable
fun BarAction(@DrawableRes icon: Int, label: String, onClick: () -> Unit, tint: Color? = null) {
    IconButton(onClick = onClick) { MIcon(icon, label, tint = tint) }
}

/** Comment la barre du haut mène ailleurs : le tiroir (une rubrique), la flèche retour, ou rien. */
enum class BarNav { DRAWER, BACK, NONE }

/**
 * La barre du haut de chaque écran (ADR 0235) : le tiroir ou la flèche, le titre (et une ligne sous lui), les actions,
 * et au bout le visage de Mika, qui ouvre « Ce qu'elle fait ». [onTitle] fait du titre un bouton (un sélecteur) ;
 * [titleIcon] : le chevron sous lui (vers le bas : une feuille s'ouvre ; vers la droite : un écran, un état qui mène
 * ailleurs). [titleDescription] : ce que le titre-bouton dit à un lecteur d'écran, s'il en dit plus que lui.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MikaTopBar(
    title: String,
    nav: BarNav,
    subtitle: String? = null,
    onTitle: (() -> Unit)? = null,
    @DrawableRes titleIcon: Int = R.drawable.ic_m_chev_down,
    titleDescription: String? = null,
    face: Boolean = true,
    actions: @Composable RowScope.() -> Unit = {},
) {
    val shell = LocalShell.current
    TopAppBar(
        navigationIcon = {
            when (nav) {
                BarNav.DRAWER -> MenuButton(shell.openDrawer)
                BarNav.BACK -> BarAction(R.drawable.ic_m_back, stringResource(R.string.shell_back), shell.back)
                BarNav.NONE -> Unit
            }
        },
        title = {
            val inner: @Composable () -> Unit = {
                Column {
                    Text(
                        title,
                        style = MaterialTheme.typography.titleLarge,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.semantics { heading() },
                    )
                    if (!subtitle.isNullOrBlank()) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                subtitle,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                                modifier = Modifier.weight(1f, fill = false),
                            )
                            if (onTitle != null) {
                                MIcon(titleIcon, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                            }
                        }
                    }
                }
            }
            if (onTitle != null) {
                val described = if (titleDescription != null) Modifier.semantics { contentDescription = titleDescription } else Modifier
                Box(Modifier.clickable(onClick = onTitle).then(described).padding(vertical = 4.dp)) { inner() }
            } else {
                inner()
            }
        },
        actions = {
            actions()
            if (face) MikaFaceButton()
        },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
    )
}

/**
 * ☰ : le tiroir. Hors du chat, une pastille rose dit qu'un accord y attend ou qu'elle y a écrit depuis ton dernier lu
 * ([LocalChatCue]) — sans elle, rien ne le disait tant que l'app restait ouverte ailleurs.
 */
@Composable
internal fun MenuButton(onClick: () -> Unit) {
    val cue = LocalChatCue.current
    val label = stringResource(if (cue) R.string.shell_menu_waiting else R.string.shell_menu)
    IconButton(onClick = onClick) {
        BadgedBox(badge = { if (cue) Badge(containerColor = mika.fill) }) { MIcon(R.drawable.ic_m_menu, label) }
    }
}

/** Son visage du moment : le portrait de son humeur ([AvatarDirector]) sur l'aura, sinon le monogramme. */
@Composable
fun MikaFace(size: Dp) {
    val graph = LocalShell.current.graph
    val mind by graph.mind.state.collectAsStateWithLifecycle()
    val typing by graph.chatEngine.typing.collectAsStateWithLifecycle()
    val ids by produceState<Set<String>?>(null) { value = graph.avatar.manifest()?.ids }
    val scene = remember(mind, typing, ids) { AvatarDirector.scene(mind, typing, AvatarDirector.Greeting.NONE, ids.orEmpty()) }
    val portrait by rememberPortrait(graph.avatar, scene.portrait.takeIf { ids != null })
    val scheme = MaterialTheme.colorScheme
    val tint = auraColor(scene.aura, scheme.surface.luminance() < 0.5f, scheme.primaryContainer)
    Box {
        val p = portrait
        if (p != null) AvatarFace(p, tint, size) else MikaAvatar(size)
        Box(
            Modifier
                .align(Alignment.BottomEnd)
                .size(size * 0.28f)
                .border(2.dp, scheme.surface, CircleShape)
                .background(ONLINE, CircleShape),
        )
    }
}

/** Le bouton de son visage, au bout de chaque barre du haut. */
@Composable
fun MikaFaceButton() {
    val shell = LocalShell.current
    val label = stringResource(R.string.chat_open_mind)
    IconButton(onClick = { shell.navigate(Route.Mind) }, modifier = Modifier.semantics { contentDescription = label }) {
        MikaFace(32.dp)
    }
}

/** Sa ligne d'état (« travaille à son bureau », « écrit… »), comme sous son nom dans le chat. */
@Composable
fun rememberMikaStatus(): String {
    val graph = LocalShell.current.graph
    val link by graph.connection.link.collectAsStateWithLifecycle()
    val typing by graph.chatEngine.typing.collectAsStateWithLifecycle()
    val mind by graph.mind.state.collectAsStateWithLifecycle()
    val now = rememberNow()
    return remember(link, typing, mind, now) { StatusLine.of(link, typing, mind, graph.clock.elapsedMs(), graph.clock.wallMs()) }
}

/** Un écran de rubrique, dans son cadre : sa barre du haut, puis son contenu. */
@Composable
fun SectionScaffold(
    topBar: @Composable () -> Unit,
    floatingActionButton: @Composable () -> Unit = {},
    bottomBar: @Composable () -> Unit = {},
    content: @Composable (Modifier) -> Unit,
) {
    Scaffold(
        topBar = topBar,
        floatingActionButton = floatingActionButton,
        bottomBar = bottomBar,
        snackbarHost = { SnackbarHost(LocalShell.current.snackbar) },
    ) { padding ->
        content(Modifier.padding(padding).fillMaxSize())
    }
}

/** Ce qui n'est pas encore écrit dans ce lot du chantier : dit tel quel, jamais une page vide. */
@Composable
fun ComingScreen(title: String, nav: BarNav, what: String) {
    SectionScaffold(topBar = { MikaTopBar(title, nav) }) { modifier ->
        Column(
            modifier.padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(what, style = MaterialTheme.typography.bodyLarge, textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Le point vert de sa présence, sur son visage. */
private val ONLINE = Color(0xFF2FB35E)
