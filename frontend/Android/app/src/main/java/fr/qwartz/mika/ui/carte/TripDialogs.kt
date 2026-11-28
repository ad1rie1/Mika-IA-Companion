package fr.qwartz.mika.ui.carte

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import fr.qwartz.mika.R
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.ADDRESS_WAIT_MS
import fr.qwartz.mika.data.moi.carte.CarteLimits
import fr.qwartz.mika.data.moi.carte.LatLon
import fr.qwartz.mika.data.moi.carte.Place
import fr.qwartz.mika.data.moi.carte.Trip
import fr.qwartz.mika.data.moi.carte.TripForm
import fr.qwartz.mika.data.moi.carte.TripValues
import fr.qwartz.mika.data.moi.carte.dayLabel
import fr.qwartz.mika.data.moi.carte.isoDay
import fr.qwartz.mika.data.moi.carte.newTripValues
import fr.qwartz.mika.data.moi.carte.placeIntent
import fr.qwartz.mika.data.moi.carte.placeWhat
import fr.qwartz.mika.data.moi.carte.refused
import fr.qwartz.mika.data.moi.carte.tripChanges
import fr.qwartz.mika.data.moi.carte.tripPins
import fr.qwartz.mika.data.moi.carte.TripSummary
import fr.qwartz.mika.data.moi.carte.tripSpan
import fr.qwartz.mika.data.moi.carte.tripTitleFor
import fr.qwartz.mika.data.moi.carte.validPoint
import fr.qwartz.mika.data.moi.carte.wantsAddress
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset
import kotlin.math.max

/*
 * Les fenêtres d'un voyage (`frontend/Web/src/screens/carte/modals.ts`, la maquette : « nouveau-voyage », les feuilles
 * « ajouter-voyage » et « ajouter-arret ») : « Nouveau voyage » (depuis Voyages, ou « Ajouter au voyage » d'Explorer avec
 * son premier arrêt) et « Le voyage » (ce qu'on en change) — le même formulaire ; « Ajouter au voyage » (tes voyages, leurs
 * dates en court) ; « Ajouter un arrêt » à un jour (un lieu de l'index, une adresse, ta position). Chaque écriture porte
 * sa clé, gardée le temps de la fenêtre : redite après une panne, elle ne se refait pas ; refusée, la suivante en a une
 * autre.
 */

/** La date choisie d'un sélecteur (minuit UTC) en `AAAA-MM-JJ`. */
private fun isoOfPicker(ms: Long): String = Instant.ofEpochMilli(ms).atZone(ZoneOffset.UTC).toLocalDate().toString()

/** Une date `AAAA-MM-JJ` pour le sélecteur (minuit UTC). */
private fun pickerOf(iso: String): Long? = isoDay(iso)?.atStartOfDay(ZoneOffset.UTC)?.toInstant()?.toEpochMilli()

/**
 * « Nouveau voyage » ([edit] `null` ; [first] : son premier arrêt, depuis un lieu) ou « Le voyage » ([edit]) : un titre,
 * une date de départ (facultative ; vidée : sans date), un mode, ce qu'il évite en voiture (ses puces ne se montrent qu'en
 * voiture, et un voyage qui la quitte ne les envoie plus). [submit] écrit (ses clés : celle du voyage, celle du premier
 * arrêt) et rend son refus (`null` : fait) ; la fenêtre se ferme alors.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun TripFormDialog(
    edit: Trip?,
    first: Place? = null,
    onDismiss: () -> Unit,
    submit: suspend (values: TripValues, key: String, firstKey: String) -> MoiError?,
) {
    val scope = rememberCoroutineScope()
    var title by rememberSaveable { mutableStateOf(edit?.title ?: first?.let { tripTitleFor(it) }.orEmpty()) }
    var start by rememberSaveable { mutableStateOf(edit?.start.orEmpty()) }
    var mode by rememberSaveable { mutableStateOf(edit?.mode ?: "voiture") }
    var avoid by rememberSaveable { mutableStateOf(edit?.avoid.orEmpty()) }
    var error by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var picking by remember { mutableStateOf(false) }
    // les clés de cette fenêtre : « Créer » redit après une panne rend le même voyage, et son premier arrêt une fois
    var key by remember { mutableStateOf(MoiApi.newKey()) }
    var firstKey by remember { mutableStateOf(MoiApi.newKey()) }
    val needTitle = stringResource(R.string.carte_trip_need_title)
    val now = LocalShell.current.graph.clock.wallMs()
    val send: () -> Unit = send@{
        if (busy) return@send
        val form = TripForm(title, start, mode, avoid)
        if (form.title.isBlank()) {
            error = needTitle
            return@send
        }
        val values = if (edit != null) tripChanges(edit, form) else newTripValues(form)
        if (edit != null && values.isEmpty) {
            onDismiss()
            return@send
        }
        busy = true
        scope.launch {
            val refusal = submit(values, key, firstKey)
            busy = false
            if (refusal == null) {
                onDismiss()
            } else {
                // refusé (un titre, la borne des voyages) : la prochaine fois est une autre demande
                if (refused(refusal)) {
                    key = MoiApi.newKey()
                    firstKey = MoiApi.newKey()
                }
                error = refusal.said
            }
        }
    }
    AlertDialog(
        onDismissRequest = { if (!busy) onDismiss() },
        title = { Text(stringResource(if (edit != null) R.string.carte_trip_form_edit else R.string.carte_trip_form_new)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                OutlinedTextField(
                    value = title,
                    onValueChange = {
                        title = it.take(CarteLimits.TITLE)
                        error = ""
                    },
                    label = { Text(stringResource(R.string.carte_trip_form_title)) },
                    placeholder = { Text(stringResource(R.string.carte_trip_form_title_hint)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                // le départ : un sélecteur de date ; vidé, le voyage n'a pas de date
                Surface(
                    onClick = { picking = true },
                    shape = RoundedCornerShape(6.dp),
                    color = MaterialTheme.colorScheme.surface,
                    border = androidx.compose.foundation.BorderStroke(1.dp, MaterialTheme.colorScheme.outline),
                    modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
                ) {
                    Row(Modifier.padding(start = 14.dp, end = 4.dp, top = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        MIcon(R.drawable.ic_m_calendar, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                        Spacer(Modifier.width(10.dp))
                        Column(Modifier.weight(1f).padding(vertical = 8.dp)) {
                            Text(stringResource(R.string.carte_trip_form_start), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                            Text(
                                if (start.isBlank()) stringResource(R.string.carte_trip_form_no_date) else dayLabel(start, now),
                                style = MaterialTheme.typography.bodyLarge,
                            )
                        }
                        if (start.isNotBlank()) {
                            IconButton(onClick = { start = "" }) { MIcon(R.drawable.ic_m_x, stringResource(R.string.carte_trip_form_clear_date), size = 18.dp) }
                        }
                    }
                }
                ModeRow(mode, Modifier.padding(top = 8.dp)) {
                    mode = it
                    error = ""
                }
                if (mode == "voiture") {
                    Text(
                        stringResource(R.string.carte_trip_form_avoid),
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(start = 16.dp, top = 4.dp),
                    )
                    AvoidChips(mode, avoid) { a, on -> avoid = if (on) avoid + a else avoid - a }
                }
                if (first != null) {
                    Text(
                        stringResource(R.string.carte_trip_form_first, listOf(first.name, first.town).filter { it.isNotBlank() }.joinToString(", ")),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 8.dp),
                    )
                }
                if (error.isNotEmpty()) {
                    Text(error, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 8.dp))
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { send() }, enabled = !busy) {
                Text(stringResource(if (edit != null) R.string.carte_trip_form_save else R.string.carte_trip_form_create))
            }
        },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !busy) { Text(stringResource(R.string.cancel)) } },
    )
    if (picking) {
        val state = rememberDatePickerState(initialSelectedDateMillis = pickerOf(start) ?: pickerOf(LocalDate.now().toString()))
        DatePickerDialog(
            onDismissRequest = { picking = false },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let { start = isoOfPicker(it) }
                    picking = false
                }) { Text(stringResource(R.string.carte_trip_form_pick)) }
            },
            dismissButton = { TextButton(onClick = { picking = false }) { Text(stringResource(R.string.cancel)) } },
        ) {
            DatePicker(state = state)
        }
    }
}

/**
 * « Ajouter au voyage » (Explorer, une fiche) : tes voyages (huit au plus, les plus récemment changés), leurs dates en
 * court (« 3–7 avr. ») ; un toucher ajoute le lieu à la fin de son dernier jour — ou du jour que [dayOf] dit (un
 * événement tombe un jour précis : « jour 2 ») —, avec une clé par voyage gardée le temps de la feuille (un double appui
 * ne l'ajoute qu'une fois) ; « Nouveau voyage… » ouvre la fenêtre, le lieu pour premier arrêt.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AddToTripSheet(
    store: CarteStore,
    place: Place,
    onDismiss: () -> Unit,
    onNew: () -> Unit,
    dayOf: ((TripSummary) -> Int)? = null,
) {
    val shell = LocalShell.current
    val scope = rememberCoroutineScope()
    val keys = remember { mutableStateMapOf<String, String>() }
    var busy by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) { store.loadList() }
    val now = shell.graph.clock.wallMs()
    val untitled = stringResource(R.string.carte_untitled_lc)
    val addedTo = stringResource(R.string.carte_added_to)
    val already = stringResource(R.string.carte_added_already)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().padding(bottom = 24.dp)) {
            Text(stringResource(R.string.carte_place_trip_full), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 24.dp))
            Text(place.name, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp, vertical = 2.dp))
            when (val list = store.list) {
                Load.Loading -> CircularProgressIndicator(Modifier.padding(24.dp).align(Alignment.CenterHorizontally))
                is Load.Failed -> Column(Modifier.padding(horizontal = 24.dp, vertical = 8.dp)) {
                    Text(list.error.said, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    TextButton(onClick = store::retryList) { Text(stringResource(R.string.retry)) }
                }
                is Load.Ready -> for (t in list.value.take(8)) {
                    // le jour que l'événement dit, s'il tombe dans le voyage ; sinon le dernier
                    val said = dayOf?.invoke(t)?.takeIf { it > 0 }
                    SheetRow(
                        icon = R.drawable.ic_m_flag,
                        title = t.title.ifBlank { stringResource(R.string.carte_untitled) },
                        sub = listOfNotNull(tripSpan(t.start, t.days, now).ifBlank { null }, said?.let { "jour $it" }).joinToString(" · "),
                        enabled = busy == null,
                    ) {
                        val key = keys.getOrPut(t.id) { MoiApi.newKey() }
                        busy = t.id
                        scope.launch {
                            val name = t.title.ifBlank { untitled }
                            when (val got = store.addPlaceAsync(t.id, place, said ?: max(1, t.days), -1, key).await()) {
                                is AddOutcome.Added -> {
                                    shell.toast(if (got.deduped) already.format(name) else addedTo.format(name, got.day))
                                    onDismiss()
                                }
                                is AddOutcome.Refused -> {
                                    if (refused(got.error)) keys.remove(t.id)
                                    shell.toast(got.error.said)
                                }
                            }
                            busy = null
                        }
                    }
                }
            }
            SheetRow(R.drawable.ic_m_plus, stringResource(R.string.carte_trip_new_more), "", enabled = busy == null, onClick = onNew)
        }
    }
}

/** Une ligne d'une feuille : son icône, son titre, ce qu'elle dit de plus. */
@Composable
private fun SheetRow(icon: Int, title: String, sub: String, enabled: Boolean = true, onClick: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp).clickable(enabled = enabled, onClick = onClick).padding(horizontal = 24.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(icon, null, size = 20.dp, tint = scheme.onSurfaceVariant)
        Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            if (sub.isNotBlank()) Text(sub, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/**
 * « Ajouter un arrêt » à un jour (à la fin) : un lieu de l'index cherché près de ce jour du voyage (son dernier arrêt,
 * sinon celui d'avant ; un voyage vide : près de toi), une adresse (si le texte en a l'air, après une pause de la saisie,
 * une fois par texte), ta position ; une note facultative. Chaque lieu choisi a sa clé, gardée le temps de la feuille.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AddStopSheet(store: CarteStore, vm: TripViewModel, trip: Trip, day: Int, onDismiss: () -> Unit) {
    val scheme = MaterialTheme.colorScheme
    val graph = LocalShell.current.graph
    val scope = rememberCoroutineScope()
    var q by rememberSaveable { mutableStateOf("") }
    var note by rememberSaveable { mutableStateOf("") }
    var typedAt by remember { mutableLongStateOf(0L) }
    var found by remember { mutableStateOf<List<Place>>(emptyList()) }
    var message by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    val keys = remember { HashMap<String, String>() }
    val here = store.here
    // chercher près de ce jour du voyage (son dernier arrêt, sinon celui d'avant) ; un voyage vide : près de toi
    val near: LatLon? = remember(trip, day, here) {
        val before = trip.days.filter { it.n <= day }.flatMap { it.stops }.filter { validPoint(it.lat, it.lon) }
        before.lastOrNull()?.let { LatLon(it.lat!!, it.lon!!) } ?: tripPins(trip).firstOrNull()?.let { LatLon(it.lat, it.lon) } ?: here?.at
    }
    val nothing = stringResource(R.string.carte_stop_search_none)
    val addressesSaid = stringResource(R.string.carte_stop_search_addresses)
    LaunchedEffect(Unit) {
        store.loadInfo()
        store.loadPosition()
    }
    LaunchedEffect(q) {
        val text = q.trim()
        if (text.length < 2) {
            found = emptyList()
            message = ""
            return@LaunchedEffect
        }
        delay(300)
        var placesError = ""
        val places = when (val got = store.api.places(q = text, near = near, limit = 8)) {
            is MoiApi.Result.Ok -> got.value.filter { it.at != null }
            is MoiApi.Result.Failed -> {
                placesError = got.error.said
                emptyList()
            }
        }
        // une adresse, si le texte en a l'air : gardée par texte, demandée une fois la saisie arrêtée
        val wanted = store.info.valueOrNull?.addresses?.ready == true && wantsAddress(text)
        val known = if (wanted) store.book.peek(text) else null
        found = known.orEmpty().take(4) + places
        val waiting = wanted && known == null
        message = placesError.ifEmpty { if (found.isEmpty() && !waiting) nothing else "" }
        if (!waiting) return@LaunchedEffect
        delay(max(0L, typedAt + ADDRESS_WAIT_MS - graph.clock.wallMs()))
        var addrError = ""
        val addresses = when (val got = store.book.lookup(text)) {
            is MoiApi.Result.Ok -> got.value
            is MoiApi.Result.Failed -> {
                addrError = addressesSaid.format(got.error.said)
                emptyList()
            }
        }
        found = addresses.take(4) + places
        message = listOf(placesError, addrError).filter { it.isNotEmpty() }.joinToString(" ").ifEmpty { if (found.isEmpty()) nothing else "" }
    }
    val choose: (Place) -> Unit = { p ->
        if (!sending) {
            // une clé par lieu choisi : un double appui, un réessai après une panne ne l'ajoutent qu'une fois
            val intent = placeIntent(p)
            val key = keys.getOrPut(intent) { MoiApi.newKey() }
            sending = true
            scope.launch {
                val (ok, error) = vm.addStopAsync(p, day, key, note).await()
                sending = false
                if (ok) onDismiss() else if (refused(error)) keys.remove(intent)
            }
        }
    }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.fillMaxWidth().imePadding().padding(bottom = 24.dp)) {
            Text(stringResource(R.string.carte_stop_add_title, day), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 24.dp))
            val label = stringResource(R.string.carte_search_label)
            OutlinedTextField(
                value = q,
                onValueChange = {
                    q = it.take(200)
                    typedAt = graph.clock.wallMs()
                },
                placeholder = { Text(stringResource(R.string.carte_stop_search_hint)) },
                leadingIcon = { MIcon(R.drawable.ic_m_search, null, size = 18.dp) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp).semantics { contentDescription = label },
            )
            if (here != null && q.isBlank()) {
                SheetRow(R.drawable.ic_m_locate, stringResource(R.string.carte_my_position), here.label.ifBlank { stringResource(R.string.carte_last_position) }, enabled = !sending) {
                    choose(Place(name = here.label.ifBlank { graph.context.getString(R.string.carte_my_position) }, kindFr = graph.context.getString(R.string.carte_your_position), lat = here.lat, lon = here.lon))
                }
            }
            if (message.isNotEmpty()) {
                Text(message, style = MaterialTheme.typography.bodySmall, color = scheme.onSurfaceVariant, modifier = Modifier.padding(horizontal = 24.dp, vertical = 4.dp))
            }
            for (p in found) {
                SheetRow(R.drawable.ic_m_pin, p.name.ifBlank { "—" }, placeWhat(p), enabled = !sending) { choose(p) }
            }
            OutlinedTextField(
                value = note,
                onValueChange = { note = it.take(CarteLimits.NOTE) },
                label = { Text(stringResource(R.string.carte_stop_add_note)) },
                placeholder = { Text(stringResource(R.string.carte_stop_note_hint)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp),
            )
            if (sending) CircularProgressIndicator(Modifier.padding(8.dp).align(Alignment.CenterHorizontally))
        }
    }
}
