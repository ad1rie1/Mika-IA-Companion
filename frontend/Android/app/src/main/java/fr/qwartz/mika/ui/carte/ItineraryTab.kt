package fr.qwartz.mika.ui.carte

import androidx.activity.compose.BackHandler
import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.BottomSheetScaffold
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberBottomSheetScaffoldState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.carte.AVOIDS
import fr.qwartz.mika.data.moi.carte.AVOID_CHIPS
import fr.qwartz.mika.data.moi.carte.AVOID_LABELS
import fr.qwartz.mika.data.moi.carte.CarteLimits
import fr.qwartz.mika.data.moi.carte.MODES
import fr.qwartz.mika.data.moi.carte.MODE_LABELS
import fr.qwartz.mika.data.moi.carte.RouteChoice
import fr.qwartz.mika.data.moi.carte.avoidNote
import fr.qwartz.mika.data.moi.carte.chosenPoints
import fr.qwartz.mika.data.moi.carte.duration
import fr.qwartz.mika.data.moi.carte.km
import fr.qwartz.mika.data.moi.carte.pointLetter
import fr.qwartz.mika.data.moi.carte.routeFacts
import fr.qwartz.mika.data.moi.carte.routeSource
import fr.qwartz.mika.data.moi.carte.routeSteps
import fr.qwartz.mika.data.moi.carte.routeTitle
import fr.qwartz.mika.data.moi.carte.typedPoint
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.map.SceneMap
import fr.qwartz.mika.ui.map.ScenePlan
import fr.qwartz.mika.ui.map.rememberMapFond
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.NoteBox
import fr.qwartz.mika.ui.shell.said
import fr.qwartz.mika.ui.theme.mika
import kotlinx.coroutines.launch

/** La part de l'écran que la feuille d'Itinéraire prend d'abord (la maquette : un peu moins de la moitié). */
private const val SHEET_SHARE = 0.46f

/**
 * Itinéraire (la maquette, `vueItineraire`) : la carte prend l'écran, ses points et le résultat montent du bas — les
 * points (A, étapes, B ; « Ma position », un lieu, une adresse), voiture, vélo ou à pied, ce qu'il évite, le résumé
 * (durée, distance, arrivée), « En faire un voyage », le GPX, « À Mika », les consignes repliées. Le tracé sur la carte
 * tant qu'il est celui de ces points. Ce que Mika a calculé (un regard) se montre tel qu'elle l'a gardé, en rose.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ItineraryTab(graph: AppGraph, vm: ItineraryViewModel, links: CarteLinks, modifier: Modifier) {
    val shell = LocalShell.current
    val sheet = rememberBottomSheetScaffoldState()
    val scope = rememberCoroutineScope()
    val fonds = rememberMapFond(graph)
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    // « En faire un voyage » fini pendant que l'onglet est là : le voyage s'ouvre ; fini ailleurs, un toast l'offre
    DisposableEffect(vm) {
        vm.shown(true)
        onDispose { vm.shown(false) }
    }
    LaunchedEffect(vm) {
        vm.opened.collect { id ->
            shell.replace(Route.Carte(CarteTabs.TRIPS))
            shell.navigate(Route.Trip(id))
        }
    }
    // des propositions ouvertes : « retour » les replie
    BackHandler(enabled = vm.suggestFor != null) { vm.closeSuggestions() }
    BoxWithConstraints(modifier) {
        val peek = (maxHeight * SHEET_SHARE).coerceIn(180.dp, 380.dp)
        val title = routeTitle(chosenPoints(vm.points))
        BottomSheetScaffold(
            scaffoldState = sheet,
            sheetPeekHeight = peek,
            sheetContent = {
                ItinerarySheet(vm, links, Modifier.heightIn(min = peek), onField = { scope.launch { sheet.bottomSheetState.expand() } })
            },
            modifier = Modifier.fillMaxSize(),
        ) {
            Box(Modifier.fillMaxSize()) {
                val scene = vm.scene
                SceneMap(
                    graph,
                    scene,
                    title,
                    Modifier.fillMaxSize(),
                    control = vm.control,
                    insets = PaddingValues(bottom = peek),
                    plan = { why -> ScenePlan(scene, title, why, Modifier.fillMaxSize(), notePadding = Modifier.padding(bottom = peek)) },
                )
                if (vm.control.live) {
                    Attribution(fonds.fond?.attribution, Modifier.align(Alignment.TopStart).padding(8.dp))
                }
            }
        }
    }
}

/** La mention du fond servi, au coin de la carte (un texte, jamais un lien). */
@Composable
internal fun Attribution(text: String?, modifier: Modifier) {
    Text(
        text?.ifBlank { null } ?: "© OpenStreetMap",
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        maxLines = 1,
        modifier = modifier
            .clip(RoundedCornerShape(4.dp))
            .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.8f))
            .padding(horizontal = 5.dp, vertical = 1.dp),
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ItinerarySheet(vm: ItineraryViewModel, links: CarteLinks, modifier: Modifier, onField: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val focus = LocalFocusManager.current
    val n = vm.points.size
    // une poignée par place de point ; la main se pose après le dessin qui montre le point (une étape neuve, le suivant)
    val requesters = remember { List(CarteLimits.POINTS) { FocusRequester() } }
    var focusAt by remember { mutableIntStateOf(-1) }
    LaunchedEffect(focusAt, n) {
        if (focusAt in 0 until minOf(n, requesters.size)) runCatching { requesters[focusAt].requestFocus() }
        focusAt = -1
    }
    val moveFocus: (Int) -> Unit = { next ->
        if (next >= 0) {
            focusAt = next
        } else {
            focus.clearFocus()
        }
    }
    val now = LocalShell.current.graph.clock.wallMs()
    Column(modifier.fillMaxWidth().verticalScroll(rememberScrollState()).imePadding().padding(bottom = 24.dp)) {
        if (vm.routing) LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp))
        LookNotice(vm)
        // ── ses points ──
        vm.points.forEachIndexed { i, p ->
            PointRow(
                i = i,
                n = n,
                query = p.query,
                requester = requesters[i],
                onType = { vm.type(i, it) },
                onFocus = {
                    vm.focus(i)
                    onField()
                },
                onRemove = { vm.removeStep(i) },
                onDone = {
                    if (vm.suggestFor == i && vm.sugg.all.isNotEmpty()) moveFocus(vm.pick(i, 0)) else focus.clearFocus()
                },
            )
            if (vm.suggestFor == i) {
                SuggestionList(vm.sugg) { j -> moveFocus(vm.pick(i, j)) }
            }
        }
        Row(Modifier.padding(start = 40.dp, end = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = {
                val at = vm.addStep()
                if (at >= 0) focusAt = at
            }, enabled = n < CarteLimits.POINTS) {
                MIcon(R.drawable.ic_m_plus, null, size = 18.dp)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.carte_iti_add_step))
            }
            TextButton(onClick = vm::swap) {
                MIcon(R.drawable.ic_m_sort, null, size = 18.dp)
                Spacer(Modifier.width(6.dp))
                Text(stringResource(R.string.carte_iti_swap))
            }
        }
        // ── comment ──
        ModeRow(vm.mode) { vm.choose(RouteChoice.Mode(it)) }
        AvoidChips(vm.mode, vm.avoid) { a, on -> vm.choose(RouteChoice.Avoid(a, on)) }
        val note = avoidNote(vm.mode)
        if (note.isNotEmpty()) {
            Text(note, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 16.dp))
        }
        // ── le résultat ──
        Result(vm, links, now)
        // ── les consignes, repliées ──
        val r = vm.route
        if (r != null && !vm.stale) {
            val steps = routeSteps(r)
            if (steps.isNotEmpty()) Steps(steps)
            Text(
                routeSource(r),
                style = MaterialTheme.typography.bodySmall,
                color = scheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
            )
        }
    }
}

/** Le regard que la route demande, s'il se lit encore ou ne se lit pas (oublié : pourquoi ; une panne : réessayer). */
@Composable
private fun LookNotice(vm: ItineraryViewModel) {
    when (val load = vm.lookLoad) {
        Load.Loading -> NoteBox(stringResource(R.string.carte_iti_regard_loading), R.drawable.ic_m_sparkle, Modifier.padding(horizontal = 16.dp, vertical = 6.dp))
        is Load.Failed -> Column(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
            NoteBox(
                if (load.error.gone) stringResource(R.string.carte_iti_regard_gone) else stringResource(R.string.carte_iti_regard_failed, load.error.said),
                R.drawable.ic_m_alert,
                tone = Tone.WARN,
            )
            if (!load.error.gone) TextButton(onClick = vm::retryLook) { Text(stringResource(R.string.retry)) }
        }
        else -> Unit
    }
}

/** Un point : sa lettre (A, une étape, B), son champ (« Départ », « Étape 1 », « Arrivée ») et, pour une étape, son retrait. */
@Composable
private fun PointRow(
    i: Int,
    n: Int,
    query: String,
    requester: FocusRequester,
    onType: (String) -> Unit,
    onFocus: () -> Unit,
    onRemove: () -> Unit,
    onDone: () -> Unit,
) {
    val scheme = MaterialTheme.colorScheme
    val label = when (i) {
        0 -> stringResource(R.string.carte_iti_start)
        n - 1 -> stringResource(R.string.carte_iti_end)
        else -> stringResource(R.string.carte_iti_step, i)
    }
    Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 8.dp, top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        val end = i == n - 1
        Box(
            Modifier.size(24.dp).clip(CircleShape).background(if (end) scheme.tertiary else scheme.primary),
            contentAlignment = Alignment.Center,
        ) {
            Text(pointLetter(i, n), style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.Bold, color = if (end) scheme.onTertiary else scheme.onPrimary)
        }
        Spacer(Modifier.width(8.dp))
        OutlinedTextField(
            value = query,
            onValueChange = onType,
            placeholder = { Text(label, maxLines = 1) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
            keyboardActions = KeyboardActions(onDone = { onDone() }),
            modifier = Modifier
                .weight(1f)
                .focusRequester(requester)
                .onFocusChanged { if (it.isFocused) onFocus() }
                .semantics { contentDescription = label },
        )
        if (i in 1 until n - 1) {
            IconButton(onClick = onRemove) { MIcon(R.drawable.ic_m_x, stringResource(R.string.carte_iti_remove_step), size = 20.dp) }
        }
    }
}

/** Les propositions du point ouvert : sa position, les adresses, les lieux ; ce que les adresses n'ont pas pu dire. */
@Composable
private fun SuggestionList(sugg: Suggestions, onPick: (Int) -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Surface(
        shape = RoundedCornerShape(12.dp),
        color = scheme.surfaceContainerHigh,
        modifier = Modifier.fillMaxWidth().padding(start = 44.dp, end = 16.dp, top = 4.dp, bottom = 4.dp),
    ) {
        Column {
            sugg.all.forEachIndexed { j, s ->
                Row(
                    Modifier.fillMaxWidth().heightIn(min = 48.dp).clickable { onPick(j) }.padding(horizontal = 12.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    MIcon(if (s.mine) R.drawable.ic_m_locate else R.drawable.ic_m_search, null, size = 18.dp, tint = scheme.onSurfaceVariant)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(s.label.ifBlank { "—" }, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (s.sub.isNotBlank()) Text(s.sub, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
            if (sugg.note.isNotEmpty()) {
                NoteBox(stringResource(R.string.carte_iti_addresses_note, sugg.note), R.drawable.ic_m_alert, Modifier.padding(8.dp), tone = Tone.WARN)
            }
        }
    }
}

/** Voiture, vélo, à pied : un choix à trois boutons, leurs icônes. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ModeRow(mode: String, modifier: Modifier = Modifier, onMode: (String) -> Unit) {
    SingleChoiceSegmentedButtonRow(modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        MODES.forEachIndexed { i, m ->
            SegmentedButton(
                selected = m == mode,
                onClick = { onMode(m) },
                shape = SegmentedButtonDefaults.itemShape(i, MODES.size),
                icon = { MIcon(modeIcon(m), null, size = 18.dp) },
                label = { Text(MODE_LABELS[m] ?: m, maxLines = 1) },
            )
        }
    }
}

@DrawableRes
internal fun modeIcon(mode: String): Int = when (mode) {
    "velo" -> R.drawable.ic_m_bike
    "pied" -> R.drawable.ic_m_walk
    else -> R.drawable.ic_m_car
}

/** Ce qu'un trajet en voiture évite : des puces (« Sans péage »), qui ne se cochent qu'en voiture. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun AvoidChips(mode: String, avoid: List<String>, modifier: Modifier = Modifier, onAvoid: (String, Boolean) -> Unit) {
    val car = mode == "voiture"
    FlowRow(modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        for (a in AVOIDS) {
            val on = car && a in avoid
            val label = stringResource(R.string.carte_avoid_full, AVOID_LABELS[a] ?: a)
            FilterChip(
                selected = on,
                onClick = { onAvoid(a, !on) },
                enabled = car,
                label = { Text(AVOID_CHIPS[a] ?: a) },
                leadingIcon = if (on) {
                    { MIcon(R.drawable.ic_m_check, null, size = 16.dp) }
                } else {
                    null
                },
                modifier = Modifier.semantics { contentDescription = label },
            )
        }
    }
}

/**
 * Le résultat (`resultMarkup` du web) : le refus du serveur, de quoi choisir, le calcul en cours, ce que Mika a calculé
 * (son résumé, « Recalculer »), ou la durée, la distance et l'arrivée ; puis « En faire un voyage », le GPX, « À Mika ».
 * Passé (un point retapé, un trajet qui se recalcule), il pâlit, et le voyage et le GPX attendent.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Result(vm: ItineraryViewModel, links: CarteLinks, now: Long) {
    val scheme = MaterialTheme.colorScheme
    val chosen = chosenPoints(vm.points)
    val stale = vm.stale
    val pad = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
    when {
        vm.routeError.isNotEmpty() -> {
            Column(pad) {
                Text(stringResource(R.string.carte_iti_failed), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium)
                Text(vm.routeError, style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = Modifier.padding(top = 4.dp))
            }
            return
        }
        chosen.size < 2 -> {
            Hint(stringResource(R.string.carte_iti_choose))
            return
        }
    }
    val typed = typedPoint(vm.points)
    val r = vm.route
    val shown = vm.regard
    if (vm.routing && r == null && shown == null) {
        Text(stringResource(R.string.carte_iti_computing), style = MaterialTheme.typography.bodyMedium, color = scheme.onSurfaceVariant, modifier = pad)
        return
    }
    val dim = if (stale || vm.routing) Modifier.alpha(0.55f) else Modifier
    if (r == null && shown != null) {
        Surface(
            shape = RoundedCornerShape(16.dp),
            color = mika.soft,
            border = BorderStroke(1.dp, mika.line),
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).then(dim),
        ) {
            Column(Modifier.padding(14.dp)) {
                Summary(duration(shown.durationS), km(shown.distanceM), "")
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(top = 2.dp)) {
                    MIcon(R.drawable.ic_m_sparkle, null, size = 14.dp, tint = mika.accent)
                    Spacer(Modifier.width(4.dp))
                    Text(stringResource(R.string.carte_iti_regard, shown.title), style = MaterialTheme.typography.bodySmall, color = mika.accent)
                }
                Actions(vm, links, stale)
                TextButton(onClick = vm::recompute, enabled = !vm.routing) {
                    MIcon(R.drawable.ic_m_refresh, null, size = 16.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.carte_iti_recompute))
                }
            }
        }
    } else if (r != null) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).then(dim)) {
            Summary(duration(r.durationS), km(r.distanceM), routeFacts(r, vm.mode, now))
            Actions(vm, links, stale)
        }
    }
    if (stale && typed) Hint(stringResource(R.string.carte_iti_choose_each))
}

/** La durée en grand, la distance à côté, puis ce qu'on en sait. */
@Composable
private fun Summary(duration: String, distance: String, facts: String) {
    Row(verticalAlignment = Alignment.Bottom) {
        Text(duration.ifBlank { "—" }, style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.width(10.dp))
        Text(distance, style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(bottom = 2.dp))
    }
    if (facts.isNotBlank()) Text(facts, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

/** « En faire un voyage » · GPX · « À Mika » (la maquette) ; un trajet passé : le voyage et le GPX attendent. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Actions(vm: ItineraryViewModel, links: CarteLinks, stale: Boolean) {
    val shell = LocalShell.current
    val open = stringResource(R.string.carte_trip_open)
    // fini ailleurs : le toast, où qu'on soit, et « Ouvrir » y mène (sans lui, on reste où l'on est)
    val elsewhere = { id: String, text: String ->
        shell.offer(text, open) {
            shell.open(Route.Carte(CarteTabs.TRIPS))
            shell.navigate(Route.Trip(id))
        }
    }
    FlowRow(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        val small = PaddingValues(horizontal = 12.dp, vertical = 8.dp)
        Button(onClick = { vm.makeTrip(elsewhere) }, enabled = !stale && !vm.sendingTrip, contentPadding = small) {
            MIcon(R.drawable.ic_m_flag, null, size = 16.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.carte_iti_make_trip))
        }
        OutlinedButton(onClick = vm::gpx, enabled = !stale, contentPadding = small) {
            MIcon(R.drawable.ic_m_download, null, size = 16.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.carte_gpx))
        }
        val askLabel = stringResource(R.string.carte_iti_ask_full)
        OutlinedButton(
            onClick = { links.say(vm.askText()) },
            contentPadding = small,
            border = BorderStroke(1.dp, mika.line),
            colors = ButtonDefaults.outlinedButtonColors(contentColor = mika.accent),
            modifier = Modifier.semantics { contentDescription = askLabel },
        ) {
            MIcon(R.drawable.ic_m_send, null, size = 16.dp)
            Spacer(Modifier.width(6.dp))
            Text(stringResource(R.string.carte_iti_ask))
        }
    }
}

/** Les consignes, repliées sous leur titre (« Les consignes · 9 »). */
@Composable
private fun Steps(steps: List<fr.qwartz.mika.data.moi.carte.Step>) {
    val scheme = MaterialTheme.colorScheme
    var open by rememberSaveable { mutableStateOf(false) }
    Row(
        Modifier.fillMaxWidth().clickable { open = !open }.padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(stringResource(R.string.carte_iti_steps, steps.size), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
        MIcon(if (open) R.drawable.ic_m_chev_up else R.drawable.ic_m_chev_down, null, size = 18.dp, tint = scheme.onSurfaceVariant)
    }
    if (open) {
        steps.forEachIndexed { i, s ->
            Row(Modifier.fillMaxWidth().heightIn(min = 44.dp).padding(horizontal = 16.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("${i + 1}", style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant, modifier = Modifier.width(24.dp))
                Text(s.text, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                val d = km(s.distanceM)
                if (d.isNotEmpty()) {
                    Spacer(Modifier.width(8.dp))
                    Text(d, style = MaterialTheme.typography.labelMedium, color = scheme.onSurfaceVariant)
                }
            }
        }
    }
}

/** Une phrase discrète, son icône devant. */
@Composable
internal fun Hint(text: String) {
    Row(Modifier.padding(horizontal = 16.dp, vertical = 6.dp)) {
        MIcon(R.drawable.ic_m_info, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(6.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}
