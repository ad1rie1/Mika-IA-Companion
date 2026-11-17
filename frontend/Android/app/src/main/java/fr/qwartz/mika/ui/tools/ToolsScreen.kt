package fr.qwartz.mika.ui.tools

import androidx.annotation.DrawableRes
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.settings.Services
import fr.qwartz.mika.data.moi.tools.FIRST_CANAL
import fr.qwartz.mika.data.moi.tools.Rights
import fr.qwartz.mika.data.moi.tools.ToolsApi
import fr.qwartz.mika.data.moi.tools.resourcesOf
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.async
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Outils (ADR 0235, la maquette `ecrans/outils.js`, variante tiroir ; ADR 0208, 0209, 0219) : ce que Mika peut faire
 * pour toi. Trois onglets qui se remplacent sans s'empiler : Droits (la matrice même du moteur, un canal à la fois),
 * Services (ceux qui lui sont ouverts, les tiens, ceux qu'on te partage), Accords (où ils se décident).
 */

/** Les onglets d'Outils ; une adresse inconnue retombe sur Droits. */
internal object ToolsTabs {
    const val RIGHTS = "droits"
    const val SERVICES = "services"
    const val AGREEMENTS = "accords"

    fun of(tab: String): String = if (tab == SERVICES || tab == AGREEMENTS) tab else RIGHTS
}

/**
 * Ce que les trois onglets lisent, une fois pour la session (un modèle par session, pas par onglet) : la matrice et
 * tes services, le canal dont la colonne se lit — l'app Android d'abord, retenu tant que la session dure —, les cartes
 * dépliées, et celle à montrer (depuis Services, ou un compte vers sa famille).
 */
class ToolsViewModel(private val graph: AppGraph) : ViewModel() {
    private val api = ToolsApi(graph.moi)
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des relectures demandées, une fois chacun (l'écran le montre en toast). */
    val said: Flow<String> = notices.receiveAsFlow()

    var rights by mutableStateOf<Load<Rights>>(Load.Loading)
        private set
    /** Tes services et ceux qu'on te partage ; `null` tant qu'ils ne se sont pas lus. */
    var services by mutableStateOf<Services?>(null)
        private set
    /** Pourquoi tes services ne se lisent pas (la matrice, elle, se montre quand même). */
    var servicesError by mutableStateOf<MoiError?>(null)
        private set
    var refreshing by mutableStateOf(false)
        private set
    var canal by mutableStateOf(FIRST_CANAL)
        private set
    /** Les cartes dépliées ; `null` avant la première lecture, qui déplie la première (la maquette). */
    var opened by mutableStateOf<Set<String>?>(null)
        private set
    /** La carte à faire venir à l'écran, une fois. */
    var focus by mutableStateOf<String?>(null)
        private set

    private var started = false
    private var job: Job? = null

    /** L'écran revient : tout lire la première fois, sinon relire sans bruit (les droits changent dans la console). */
    fun resume() {
        if (!started) {
            started = true
            load(quiet = false)
        } else {
            load(quiet = true)
        }
    }

    /** Tirer pour relire : ce qui est montré reste jusqu'à ce que la relecture arrive. */
    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(quiet = false).join()
            refreshing = false
        }
    }

    fun retry() {
        rights = Load.Loading
        load(quiet = false)
    }

    fun choose(key: String) {
        canal = key
    }

    fun toggle(key: String) {
        val now = opened.orEmpty()
        opened = if (key in now) now - key else now + key
    }

    /** Déplier une carte et la faire venir à l'écran. */
    fun show(key: String) {
        opened = opened.orEmpty() + key
        focus = key
    }

    fun focused() {
        focus = null
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            val matrix = async { api.rights() }
            val mine = async { api.services() }
            when (val got = matrix.await()) {
                is MoiApi.Result.Ok -> {
                    rights = Load.Ready(got.value)
                    if (opened == null) opened = setOfNotNull(resourcesOf(got.value).firstOrNull()?.key)
                }
                is MoiApi.Result.Failed -> if (rights is Load.Ready) {
                    if (!quiet) notices.trySend(got.error.said)
                } else {
                    rights = Load.Failed(got.error)
                }
            }
            when (val got = mine.await()) {
                is MoiApi.Result.Ok -> {
                    services = got.value
                    servicesError = null
                }
                // une relecture qui échoue garde ce qu'on savait
                is MoiApi.Result.Failed -> if (services == null) servicesError = got.error
            }
        }.also { job = it }
    }
}

/**
 * Outils, la rubrique du tiroir (`Route.Tools(tab)`) ; [nav] : le tiroir depuis le tiroir, la flèche quand un autre
 * écran y mène (« Comment ça part » de Teams, la règle d'envoi de Paramètres). Les lectures se refont à chaque retour
 * sur l'écran, sans minuterie (les droits ne bougent que dans la console).
 */
@Composable
fun ToolsScreen(graph: AppGraph, tab: String, nav: BarNav) {
    val shell = LocalShell.current
    val session = rememberSessionKey(graph)
    val vm: ToolsViewModel = viewModel(key = "tools|$session") { ToolsViewModel(graph) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { vm.resume() }
    }
    val shown = ToolsTabs.of(tab)
    SectionScaffold(topBar = { ToolsTopBar(shown, nav) }) { modifier ->
        when (shown) {
            ToolsTabs.SERVICES -> ServicesTab(vm, modifier, onRights = { key ->
                vm.show(key)
                shell.replace(Route.Tools(ToolsTabs.RIGHTS))
            })
            ToolsTabs.AGREEMENTS -> AgreementsTab(graph, modifier)
            else -> RightsTab(graph, vm, modifier)
        }
    }
}

/** La barre d'Outils : son titre, puis les trois onglets, qui se remplacent l'un l'autre sans s'empiler. */
@Composable
private fun ToolsTopBar(tab: String, nav: BarNav) {
    val shell = LocalShell.current
    Column {
        MikaTopBar(title = stringResource(R.string.nav_tools), nav = nav)
        val tabs = listOf(
            ToolsTabs.RIGHTS to R.string.tools_tab_rights,
            ToolsTabs.SERVICES to R.string.tools_tab_services,
            ToolsTabs.AGREEMENTS to R.string.tools_tab_agreements,
        )
        PrimaryTabRow(selectedTabIndex = tabs.indexOfFirst { it.first == tab }.coerceAtLeast(0)) {
            for ((id, label) in tabs) {
                Tab(
                    selected = id == tab,
                    onClick = { if (id != tab) shell.replace(Route.Tools(id)) },
                    text = { Text(stringResource(label)) },
                )
            }
        }
    }
}

/** L'icône d'une ressource, par son nom dans le jeu de la maquette (`ToolsRules`) ; un nom inconnu : la clé. */
@DrawableRes
internal fun toolIcon(name: String): Int = when (name) {
    "clock" -> R.drawable.ic_m_clock
    "eye" -> R.drawable.ic_m_eye
    "bell" -> R.drawable.ic_m_bell
    "mail" -> R.drawable.ic_m_mail
    "image" -> R.drawable.ic_m_image
    "file" -> R.drawable.ic_m_file
    "inbox" -> R.drawable.ic_m_inbox
    "user" -> R.drawable.ic_m_user
    "terminal" -> R.drawable.ic_m_terminal
    "code" -> R.drawable.ic_m_code
    "pin" -> R.drawable.ic_m_pin
    "phone" -> R.drawable.ic_m_phone
    "book" -> R.drawable.ic_m_book
    "clip" -> R.drawable.ic_m_clip
    "folder" -> R.drawable.ic_m_folder
    "users" -> R.drawable.ic_m_users
    "bolt" -> R.drawable.ic_m_bolt
    "sparkle" -> R.drawable.ic_m_sparkle
    "heart" -> R.drawable.ic_m_heart
    "map" -> R.drawable.ic_m_map
    "teams" -> R.drawable.ic_m_teams
    "globe" -> R.drawable.ic_m_globe
    "plug" -> R.drawable.ic_m_plug
    else -> R.drawable.ic_m_tools
}

/** L'icône d'un canal (la feuille de la maquette) : ce téléphone, Teams, le courrier, elle seule, le chat. */
@DrawableRes
internal fun canalIcon(key: String): Int = when (key) {
    "mobile" -> R.drawable.ic_m_phone
    "teams" -> R.drawable.ic_m_teams
    "courrier" -> R.drawable.ic_m_mail
    "seule" -> R.drawable.ic_m_sparkle
    else -> R.drawable.ic_m_chat
}
