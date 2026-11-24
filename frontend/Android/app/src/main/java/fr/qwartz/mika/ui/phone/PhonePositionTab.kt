package fr.qwartz.mika.ui.phone

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.chat.Sender
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.SceneHere
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.PhoneLive
import fr.qwartz.mika.data.moi.phone.Look
import fr.qwartz.mika.data.moi.phone.PhoneCoords
import fr.qwartz.mika.data.moi.phone.PhonePosition
import fr.qwartz.mika.data.moi.phone.lookedAt
import fr.qwartz.mika.data.moi.phone.positionLine
import fr.qwartz.mika.data.moi.phone.whenWords
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.map.MapControl
import fr.qwartz.mika.ui.map.SceneMap
import fr.qwartz.mika.ui.settings.WhereSwitch
import fr.qwartz.mika.ui.settings.rememberWhereSwitch
import fr.qwartz.mika.ui.shell.FollowLive
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/**
 * Position (`Route.Phone("position")`) : ta dernière position (`phone/position`) et les regards de Mika sur elle, tels
 * que ses bulles 📍 les gardent dans le chat (l'instant de la mesure regardée, celui de sa réponse).
 */
class PhonePositionViewModel(graph: AppGraph) : PhoneModel(graph) {
    var position by mutableStateOf<Load<PhonePosition>>(Load.Loading)
        private set
    var refreshing by mutableStateOf(false)
        private set

    /** Ses regards sur ta position, lus dans le fil gardé sur ce téléphone (les notes `location` de ses réponses). */
    val looks: StateFlow<List<Look>> = graph.store.observe()
        .map { messages ->
            messages.filter { it.sender == Sender.MIKA }.flatMap { m ->
                m.notes.orEmpty().filter { it.kind == MikaProtocol.NOTE_LOCATION }.map { Look(it.at, m.ts) }
            }
        }
        .distinctUntilChanged()
        .flowOn(Dispatchers.Default)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    private var started = false
    private var job: Job? = null

    // allumer ou couper « Lui dire où je suis » change ce que le serveur sait : il le pousse (`phone.position`)

    fun resume() {
        if (!started) {
            started = true
            load(quiet = false)
        } else {
            load(quiet = true)
        }
    }

    fun pull() {
        refreshing = true
        viewModelScope.launch {
            load(quiet = false).join()
            refreshing = false
        }
    }

    fun retry() {
        position = Load.Loading
        load(quiet = false)
    }

    /** Le direct (ADR 0308) : ta position a changé chez Mika (`phone.position`) : relue sans bruit. Rend la main quand
     *  c'est relu. */
    suspend fun onLive(signal: LiveSignal) {
        if (started && signal.touches(Topics.PHONE_POSITION)) load(quiet = true).join()
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        return viewModelScope.launch {
            when (val got = api.position()) {
                is MoiApi.Result.Ok -> position = Load.Ready(got.value)
                is MoiApi.Result.Failed -> if (position is Load.Ready) {
                    if (!quiet) say(got.error)
                } else {
                    position = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }
}

/**
 * L'onglet Position (la maquette, `vuePosition`) : la carte de ta dernière position (le point et le cercle de sa
 * précision : `PositionMap`, la vraie carte, ou son plan dessiné), sa fiche — le lieu, la précision, l'heure de la mesure, les coordonnées — et si Mika l'a
 * regardée ; l'interrupteur « Lui dire où je suis », le même réglage et la même demande d'autorisation que dans
 * Paramètres ; « Ouvrir dans Carte ».
 */
@Composable
internal fun PositionTab(graph: AppGraph, session: String, modifier: Modifier, onPull: () -> Unit) {
    val shell = LocalShell.current
    val vm: PhonePositionViewModel = viewModel(key = "phone.position|$session") { PhonePositionViewModel(graph) }
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    FollowLive(graph.live, PhoneLive.POSITION, vm, onShown = { vm.resume() }) { vm.onLive(it) }
    val looks by vm.looks.collectAsStateWithLifecycle()
    val where = rememberWhereSwitch(graph)
    PullToRefreshBox(
        isRefreshing = vm.refreshing,
        onRefresh = {
            vm.pull()
            onPull()
        },
        modifier = modifier,
    ) {
        LoadBox(vm.position, onRetry = vm::retry) { p ->
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) {
                if (p.known) {
                    PositionMap(
                        graph,
                        p,
                        p.label.ifBlank { stringResource(R.string.phone_position_unnamed) },
                        Modifier.fillMaxWidth().height(300.dp),
                    )
                }
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (p.known) {
                        PositionCard(p, looks, onChat = { shell.open(Route.Chat) })
                    } else {
                        UnknownCard()
                    }
                    WhereCard(where)
                    if (p.known) {
                        TextButton(onClick = { shell.open(Route.Carte()) }) {
                            MIcon(R.drawable.ic_m_map, null, size = 18.dp)
                            Spacer(Modifier.width(8.dp))
                            Text(stringResource(R.string.phone_open_map))
                        }
                    }
                }
            }
        }
    }
}

/** La fiche de sa dernière position : le lieu, « ±12 m · mesurée à 14:10 · coordonnées », et le regard de Mika. */
@Composable
private fun PositionCard(p: PhonePosition, looks: List<Look>, onChat: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val now = rememberNow()
    val looked = lookedAt(looks, p.at)
    Surface(shape = RoundedCornerShape(16.dp), color = scheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(stringResource(R.string.phone_position_title), style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
            Text(
                p.label.ifBlank { stringResource(R.string.phone_position_unnamed) },
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.padding(top = 2.dp),
            )
            val line = positionLine(p, now)
            if (line.isNotBlank()) Text(line, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            Spacer(Modifier.height(10.dp))
            val seen = looked.thisFix
            val last = looked.last
            when {
                seen != null -> Row(
                    Modifier.clickable(onClick = onChat).padding(vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    MIcon(R.drawable.ic_m_eye, null, size = 16.dp, tint = mika.accent)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.phone_position_looked, whenWords(seen.at, now)), style = MaterialTheme.typography.bodySmall, color = mika.accent)
                }
                last != null -> Text(
                    stringResource(R.string.phone_position_looked_before, whenWords(last.at, now)),
                    style = MaterialTheme.typography.bodySmall,
                    color = scheme.onSurfaceVariant,
                )
                else -> Text(stringResource(R.string.phone_position_never), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            }
        }
    }
}

/** Mika ne sait pas où tu es : son téléphone ne l'a pas dit, ou c'est effacé. */
@Composable
private fun UnknownCard() {
    val scheme = MaterialTheme.colorScheme
    Surface(shape = RoundedCornerShape(16.dp), color = scheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(16.dp)) {
            MIcon(R.drawable.ic_m_pin, null, tint = scheme.onSurfaceVariant)
            Spacer(Modifier.width(12.dp))
            Column {
                Text(stringResource(R.string.phone_position_unknown_title), style = MaterialTheme.typography.titleMedium)
                Text(stringResource(R.string.phone_position_unknown), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
            }
        }
    }
}

/** « Lui dire où je suis » : l'interrupteur de Paramètres, ici aussi (ADR 0119). Refusée, l'autorisation se donne dans
 *  les réglages du téléphone. */
@Composable
private fun WhereCard(where: WhereSwitch) {
    val scheme = MaterialTheme.colorScheme
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = scheme.surface,
        border = BorderStroke(1.dp, scheme.outlineVariant),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column {
            Row(
                Modifier
                    .fillMaxWidth()
                    .heightIn(min = 56.dp)
                    .toggleable(value = where.checked, role = Role.Switch, onValueChange = where.onChange)
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f).padding(end = 16.dp)) {
                    Text(stringResource(R.string.settings_where_title), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium)
                    Text(
                        stringResource(if (where.revoked) R.string.settings_where_revoked else R.string.phone_where_summary),
                        style = MaterialTheme.typography.bodySmall,
                        color = scheme.onSurfaceVariant,
                    )
                }
                // le rang entier est l'interrupteur : le Switch lui-même ne capte rien
                Switch(checked = where.checked, onCheckedChange = null)
            }
            if (where.refused) {
                Column(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp)) {
                    Text(stringResource(R.string.settings_where_refused), style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant)
                    OutlinedButton(onClick = where.openSettings, modifier = Modifier.padding(top = 8.dp)) {
                        Text(stringResource(R.string.settings_where_open_settings))
                    }
                }
            }
        }
    }
}

/**
 * La carte de ta dernière position (ADR 0119, 0193) : la vraie — le fond servi, centrée sur ton point au zoom qui montre
 * le cercle de sa précision — quand le fond est prêt et couvre ta position ; sinon le plan dessiné ([PositionPlan]) et
 * sa note, qui dit pourquoi. Dans la page qui défile : le doigt reste à la carte.
 */
@Composable
private fun PositionMap(graph: AppGraph, p: PhonePosition, label: String, modifier: Modifier) {
    val scene = remember(p.coords, p.accuracyM) { positionScene(p) }
    val control = remember { MapControl() }
    // la carte suit ta position : elle ne se recentre que si tu as bougé (son zoom reste le tien)
    val seen = remember { arrayOfNulls<PhoneCoords>(1) }
    LaunchedEffect(p.coords) {
        val before = seen[0]
        seen[0] = p.coords
        if (before != null && p.coords != null && before != p.coords) control.fit()
    }
    SceneMap(
        graph,
        scene,
        stringResource(R.string.phone_plan_around, label),
        modifier,
        control = control,
        needsHere = true,
        nested = true,
        plan = { why -> PositionPlan(p.coords, p.accuracyM, label, modifier, why.takeIf { p.coords != null }) },
    )
}

/** Ce que la carte de la position montre : son point et le cercle de sa précision, rien d'autre ; sans coordonnées, rien. */
internal fun positionScene(p: PhonePosition): Scene =
    Scene(here = p.coords?.let { SceneHere(it.lat, it.lon, p.accuracyM) })
