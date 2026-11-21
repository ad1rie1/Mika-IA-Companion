package fr.qwartz.mika.ui.projects

import android.content.Context
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.DrawableRes
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.files.ImageCompressor
import fr.qwartz.mika.data.moi.mail.outgoingPiece
import fr.qwartz.mika.data.moi.projects.DocImage
import fr.qwartz.mika.data.moi.projects.DocUpload
import fr.qwartz.mika.data.moi.projects.Edit
import fr.qwartz.mika.data.moi.projects.MdEdit
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.WORD_MAX
import fr.qwartz.mika.data.moi.projects.folderOf
import fr.qwartz.mika.data.moi.projects.moment
import fr.qwartz.mika.data.moi.projects.nameOf
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Shell
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.RequestBody.Companion.asRequestBody
import java.io.File
import java.io.IOException

/*
 * L'éditeur d'une page de documentation (ADR 0296) : **natif**, pas une vue web. On y écrit du Markdown dans un champ
 * qui prend l'écran ; **une barre d'outils reste juste au-dessus du clavier** (titre, gras, italique, liste, liste à
 * cocher, liste numérotée, citation, code, lien, image) et agit sur la sélection — ses transformations sont des
 * fonctions pures ([MdEdit]) ; « Entrée » poursuit une liste. Une bascule **Écrire | Aperçu** montre la page telle
 * qu'elle se lira. Une image se choisit dans le téléphone par le sélecteur de photos du système (aucune permission), part
 * au serveur, puis se cite là où est le curseur.
 *
 * **Enregistrer** demande un mot sur ce qui a changé et nomme la version lue : si la page a changé depuis, le serveur
 * refuse — ses mots se disent, **rien de ce qui est écrit n'est perdu**, et l'on choisit : reprendre sur la version
 * actuelle (le texte tapé reste), ou la prendre. Le brouillon vit dans son modèle : il survit à une rotation et à un
 * aller-retour.
 */

private const val ASK_SAVE = "save"
private const val ASK_LEAVE = "leave"
private const val ASK_LINK = "link"
private const val ASK_IMAGES = "images"
private const val ASK_CURRENT = "current"

@Composable
internal fun DocEditScreen(graph: AppGraph, route: Route.ProjectPage) {
    val outer = LocalShell.current
    val session = rememberSessionKey(graph)
    val fresh = route.kind == SheetPages.NEW
    val vm: DocEditViewModel = viewModel(key = "doc-edit|$session|${route.id}|${route.key}") {
        DocEditViewModel(ProjectsDeps(graph), route.id, route.key, if (fresh) route.ref else null)
    }
    val docs = rememberDocsModel(graph, route.id)
    val now = rememberNow(wallMs = graph.clock::wallMs)
    Toasts(vm.gestures)
    LaunchedEffect(vm) { vm.open() }
    var preview by rememberSaveable { mutableStateOf(false) }
    var asking by rememberSaveable { mutableStateOf("") }
    // enregistrée : l'onglet se relit, et l'écran revient à la page
    LaunchedEffect(vm.justSaved) {
        if (vm.justSaved) {
            vm.savedSeen()
            docs.reload()
            if (fresh) outer.replace(Route.ProjectPage(route.id, SheetPages.PAGE, route.key)) else outer.back()
        }
    }
    // quitter avec un texte pas enregistré : on le dit d'abord (le brouillon reste, si on le garde)
    val leave by rememberUpdatedState<() -> Unit> { if (vm.dirty) asking = ASK_LEAVE else outer.back() }
    val shell = remember(outer) {
        Shell(graph = outer.graph, navigate = outer.navigate, open = outer.open, replace = outer.replace, back = { leave() }, openDrawer = outer.openDrawer, snackbar = outer.snackbar, toast = outer.toast)
    }
    BackHandler(enabled = vm.dirty && asking.isEmpty()) { asking = ASK_LEAVE }
    val focus = remember { FocusRequester() }
    val images = vm.space.value?.images.orEmpty()
    CompositionLocalProvider(LocalShell provides shell) {
        SectionScaffold(
            topBar = {
                MikaTopBar(
                    title = nameOf(route.key),
                    nav = BarNav.BACK,
                    subtitle = folderOf(route.key).ifEmpty { stringResource(R.string.proj_doc_root) },
                    face = false,
                    actions = {
                        Button(onClick = { asking = ASK_SAVE }, enabled = vm.dirty && !vm.saving, modifier = Modifier.padding(end = 8.dp)) {
                            if (vm.saving) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp) else MIcon(R.drawable.ic_m_check, null, size = 18.dp)
                            Spacer(Modifier.width(6.dp))
                            Text(stringResource(R.string.proj_save))
                        }
                    },
                )
            },
        ) { modifier ->
            LoadBox(vm.load, vm::retry, modifier) {
                Column(modifier.imePadding()) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        SingleChoiceSegmentedButtonRow {
                            SegmentedButton(selected = !preview, onClick = { preview = false }, shape = SegmentedButtonDefaults.itemShape(0, 2), label = { Text(stringResource(R.string.proj_doc_write), maxLines = 1) })
                            SegmentedButton(selected = preview, onClick = { preview = true }, shape = SegmentedButtonDefaults.itemShape(1, 2), label = { Text(stringResource(R.string.proj_doc_preview), maxLines = 1) })
                        }
                        Spacer(Modifier.weight(1f))
                        if (vm.dirty) StatePill(StateTone.YOU, stringResource(R.string.proj_doc_unsaved))
                    }
                    ConflictNote(vm, onSee = {
                        vm.readCurrent()
                        asking = ASK_CURRENT
                    })
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                    if (preview) {
                        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp)) {
                            if (vm.edit.text.isBlank()) Muted(stringResource(R.string.proj_doc_preview_empty))
                            DocText(graph, route.id, vm.edit.text, vm.space.value?.images?.associateBy { it.name })
                        }
                    } else {
                        PageField(vm, focus, Modifier.weight(1f).fillMaxWidth())
                        ToolBar(vm, onLink = { asking = ASK_LINK }, onImage = { asking = ASK_IMAGES })
                    }
                }
            }
        }
    }
    when (asking) {
        ASK_SAVE -> SaveDialog(route.key, vm.space.value?.limits?.wordChars?.takeIf { it > 0 } ?: WORD_MAX, onDismiss = { asking = "" }) { word ->
            asking = ""
            vm.save(word)
        }
        ASK_LEAVE -> AlertDialog(
            onDismissRequest = { asking = "" },
            title = { Text(stringResource(R.string.proj_doc_leave_title)) },
            text = { Text(stringResource(R.string.proj_doc_leave_text)) },
            confirmButton = {
                TextButton(onClick = {
                    asking = ""
                    outer.back()
                }) { Text(stringResource(R.string.proj_doc_leave_keep)) }
            },
            dismissButton = {
                TextButton(onClick = {
                    asking = ""
                    vm.discard()
                    outer.back()
                }) { Text(stringResource(R.string.proj_doc_leave_drop), color = MaterialTheme.colorScheme.error) }
            },
        )
        ASK_LINK -> LinkDialog(vm.edit.selected, onDismiss = {
            asking = ""
            focus.requestFocus()
        }) { url ->
            asking = ""
            vm.change { MdEdit.link(it, url) }
            focus.requestFocus()
        }
        ASK_IMAGES -> ImagesSheet(graph, vm, images, onDismiss = { asking = "" })
        ASK_CURRENT -> CurrentSheet(graph, vm, now, onDismiss = { asking = "" })
    }
}

/**
 * Le champ de la page. Il garde sa propre valeur (la composition du clavier y reste intacte pendant qu'on tape) ; ce que
 * le modèle change — un geste de la barre d'outils, une liste poursuivie, une version reprise — y revient.
 */
@Composable
private fun PageField(vm: DocEditViewModel, focus: FocusRequester, modifier: Modifier) {
    val e = vm.edit
    var field by remember { mutableStateOf(TextFieldValue(e.text, TextRange(e.start, e.end))) }
    val shown = if (field.text == e.text && field.selection.min == e.start && field.selection.max == e.end) field else TextFieldValue(e.text, TextRange(e.start, e.end))
    BasicTextField(
        value = shown,
        onValueChange = {
            field = it
            vm.type(Edit.of(it.text, it.selection.start, it.selection.end))
        },
        textStyle = MaterialTheme.typography.bodyLarge.copy(color = MaterialTheme.colorScheme.onSurface),
        cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
        modifier = modifier.focusRequester(focus).padding(horizontal = 16.dp, vertical = 12.dp),
        decorationBox = { inner ->
            Box(Modifier.fillMaxSize()) {
                if (shown.text.isEmpty()) Text(stringResource(R.string.proj_doc_write_hint), style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                inner()
            }
        },
    )
}

/** Un refus à l'enregistrement, avec les mots du serveur ; pour un conflit, de quoi relire la version actuelle et reprendre. */
@Composable
private fun ConflictNote(vm: DocEditViewModel, onSee: () -> Unit) {
    val d = vm.draft ?: return
    val current = vm.current
    if (d.refusal.isBlank()) {
        // reparti de la version actuelle : le texte tapé est gardé, l'enregistrement en fera la version suivante
        if (current != null && d.base == current.version && d.dirty) {
            Hint(stringResource(R.string.proj_doc_rebased, current.version), R.drawable.ic_m_history, Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
        }
        return
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
        RefusalNote(d.refusal)
        if (d.conflict) {
            Text(stringResource(R.string.proj_doc_conflict_kept), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = onSee) { Text(stringResource(R.string.proj_doc_conflict_see), maxLines = 1) }
                Button(onClick = vm::rebase) { Text(stringResource(R.string.proj_doc_conflict_rebase), maxLines = 1) }
            }
        }
    }
}

// ── La barre d'outils ───────────────────────────────────────────────────

/**
 * La barre d'outils, au-dessus du clavier : elle défile en largeur. Chaque touche agit sur la sélection du champ, qui
 * garde la main (le clavier ne se ferme pas).
 */
@Composable
private fun ToolBar(vm: DocEditViewModel, onLink: () -> Unit, onImage: () -> Unit) {
    val level = MdEdit.headingAt(vm.edit)
    Surface(color = MaterialTheme.colorScheme.surfaceContainer, tonalElevation = 2.dp) {
        Row(
            Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 6.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            // le titre tourne : texte, titre 1, 2, 3, texte — sans menu, qui prendrait la main au clavier
            ToolKey(stringResource(R.string.proj_doc_tool_heading), text = if (level in 1..3) "T$level" else "T", on = level > 0) { vm.change(MdEdit::headingNext) }
            ToolKey(stringResource(R.string.proj_doc_tool_bold), text = "G", weight = FontWeight.Black) { vm.change(MdEdit::bold) }
            ToolKey(stringResource(R.string.proj_doc_tool_italic), text = "I", italic = true) { vm.change(MdEdit::italic) }
            ToolKey(stringResource(R.string.proj_doc_tool_list), text = "•") { vm.change { MdEdit.list(it, MdEdit.ListKind.BULLET) } }
            ToolKey(stringResource(R.string.proj_doc_tool_tasks), icon = R.drawable.ic_m_checks) { vm.change { MdEdit.list(it, MdEdit.ListKind.TASK) } }
            ToolKey(stringResource(R.string.proj_doc_tool_numbers), text = "1.") { vm.change { MdEdit.list(it, MdEdit.ListKind.NUMBER) } }
            ToolKey(stringResource(R.string.proj_doc_tool_quote), text = "❯") { vm.change(MdEdit::quote) }
            ToolKey(stringResource(R.string.proj_doc_tool_code), icon = R.drawable.ic_m_code) { vm.change(MdEdit::code) }
            ToolKey(stringResource(R.string.proj_doc_tool_link), icon = R.drawable.ic_m_link, onClick = onLink)
            ToolKey(stringResource(R.string.proj_doc_tool_image), icon = R.drawable.ic_m_image, onClick = onImage)
        }
    }
}

/** Une touche de la barre : une icône du jeu, ou une lettre ; son nom est dit au lecteur d'écran. */
@Composable
private fun ToolKey(
    label: String,
    text: String = "",
    @DrawableRes icon: Int = 0,
    weight: FontWeight = FontWeight.SemiBold,
    italic: Boolean = false,
    on: Boolean = false,
    onClick: () -> Unit,
) {
    Box(
        Modifier
            .size(44.dp)
            .clip(RoundedCornerShape(10.dp))
            .background(if (on) MaterialTheme.colorScheme.primaryContainer else Color.Transparent)
            .clickable(onClickLabel = label, onClick = onClick)
            .semantics { contentDescription = label },
        contentAlignment = Alignment.Center,
    ) {
        val tint = if (on) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurface
        if (icon != 0) {
            MIcon(icon, null, size = 22.dp, tint = tint)
        } else {
            Text(text, style = MaterialTheme.typography.titleMedium, fontWeight = weight, fontStyle = if (italic) FontStyle.Italic else FontStyle.Normal, color = tint, maxLines = 1)
        }
    }
}

// ── Ses fenêtres ────────────────────────────────────────────────────────

/** « Enregistrer la page » : un mot sur ce qui a changé ; une version naît dans l'espace, le dépôt du code n'est pas touché. */
@Composable
private fun SaveDialog(path: String, max: Int, onDismiss: () -> Unit, onSave: (String) -> Unit) {
    var word by rememberSaveable { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.proj_doc_save_title)) },
        text = {
            Column {
                Text(path, style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace), color = MaterialTheme.colorScheme.onSurfaceVariant)
                Gap(10.dp)
                OutlinedTextField(
                    value = word,
                    onValueChange = { word = it.take(max) },
                    label = { Text(stringResource(R.string.proj_doc_save_word)) },
                    placeholder = { Text(stringResource(R.string.proj_doc_save_word_hint)) },
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                    maxLines = 3,
                    modifier = Modifier.fillMaxWidth(),
                )
                Gap(10.dp)
                Text(stringResource(R.string.proj_doc_save_note), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        },
        confirmButton = { TextButton(onClick = { onSave(word) }) { Text(stringResource(R.string.proj_save)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** L'adresse d'un lien : ce qui est sélectionné devient son texte. */
@Composable
private fun LinkDialog(selected: String, onDismiss: () -> Unit, onLink: (String) -> Unit) {
    val picked = selected.trim()
    var url by rememberSaveable { mutableStateOf(if (picked.startsWith("http://") || picked.startsWith("https://")) picked else "https://") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.proj_doc_link_title)) },
        text = {
            OutlinedTextField(
                value = url,
                onValueChange = { url = it.take(2000) },
                label = { Text(stringResource(R.string.proj_doc_link_url)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        },
        confirmButton = { TextButton(onClick = { onLink(url) }, enabled = url.trim().length > "https://".length) { Text(stringResource(R.string.proj_doc_link_ok)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** Les images : en choisir une dans le téléphone (elle part, puis se cite au curseur), ou citer une image de l'espace. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ImagesSheet(graph: AppGraph, vm: DocEditViewModel, images: List<DocImage>, onDismiss: () -> Unit) {
    val shell = LocalShell.current
    val unreadable = stringResource(R.string.proj_doc_image_unreadable)
    val pick = rememberImagePicker(vm.space.value?.limits?.imageBytes ?: 0, onPicked = vm::upload, onUnreadable = { shell.toast(unreadable) })
    // l'image téléversée est citée dans la page : la feuille se ferme
    var sent by remember { mutableStateOf(false) }
    LaunchedEffect(vm.uploading) {
        if (vm.uploading) sent = true else if (sent && vm.gestures.refusalAt(DocEditViewModel.IMAGE).isEmpty()) onDismiss()
    }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(
            Modifier.fillMaxWidth().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(stringResource(R.string.proj_doc_tool_image), style = MaterialTheme.typography.titleLarge)
            RefusalNote(vm.gestures.refusalAt(DocEditViewModel.IMAGE))
            Button(onClick = pick, enabled = !vm.uploading) {
                if (vm.uploading) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp) else MIcon(R.drawable.ic_m_plus, null, size = 18.dp)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(if (vm.uploading) R.string.proj_doc_image_sending else R.string.proj_doc_image_pick))
            }
            if (images.isNotEmpty()) SideTitle(stringResource(R.string.proj_doc_images_of_space))
            for (image in images) {
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable {
                        vm.change { MdEdit.image(it, image.name) }
                        onDismiss()
                    }.padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    DocPicture(graph, vm.project, image.name, image.name, image.at, Modifier.size(56.dp), crop = true)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(image.name, style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(weight(image.size), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
    }
}

/** La page telle qu'elle est maintenant, relue après un conflit : qui l'a écrite, son texte ; la prendre jette ce qu'on a écrit. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CurrentSheet(graph: AppGraph, vm: DocEditViewModel, now: Long, onDismiss: () -> Unit) {
    var taking by rememberSaveable { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(
            Modifier.fillMaxWidth().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            val p = vm.current
            if (p == null) {
                Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            } else {
                Text(stringResource(R.string.proj_doc_current_title, p.version), style = MaterialTheme.typography.titleLarge)
                Text(listOf(p.author, p.viaLabel, moment(p.at, now)).filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                OutlinedButton(onClick = { taking = true }) { Text(stringResource(R.string.proj_doc_current_take)) }
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                DocText(graph, vm.project, p.text, vm.space.value?.images?.associateBy { it.name })
            }
        }
    }
    if (taking) {
        ConfirmDialog(
            stringResource(R.string.proj_doc_current_take),
            stringResource(R.string.proj_doc_current_take_text),
            stringResource(R.string.proj_doc_current_take_ok),
            onDismiss = { taking = false },
        ) {
            vm.takeCurrent()
            onDismiss()
        }
    }
}

// ── Choisir une image dans le téléphone ─────────────────────────────────

/**
 * Le sélecteur de photos du système (aucune permission). L'image choisie se prépare hors du fil de l'écran ; illisible
 * (un fournisseur muet), on le dit. [maxBytes] : ce que l'espace garde d'une image, dit par le serveur (0 : pas dit).
 */
@Composable
internal fun rememberImagePicker(maxBytes: Long, onPicked: (DocUpload) -> Unit, onUnreadable: () -> Unit): () -> Unit {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) {
            scope.launch {
                val picked = withContext(Dispatchers.IO) { pickedImage(context.applicationContext, uri, maxBytes) }
                if (picked == null) onUnreadable() else onPicked(picked)
            }
        }
    }
    return { launcher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
}

/**
 * Une image choisie, prête à partir. Plus lourde que ce que l'espace garde, elle est réencodée en JPEG sous cette borne
 * (comme une photo jointe à la conversation : orientation appliquée, plus aucune métadonnée) ; si rien n'y tient, elle
 * part telle quelle et le serveur dira non, avec ses mots.
 */
private fun pickedImage(context: Context, uri: Uri, maxBytes: Long): DocUpload? {
    val resolver = context.contentResolver
    val piece = resolver.outgoingPiece(uri) ?: return null
    if (maxBytes <= 0 || piece.size <= maxBytes) return DocUpload(piece.name, piece.size, piece.body)
    val dir = File(context.cacheDir, "doc-images").apply { mkdirs() }
    dir.listFiles()?.forEach { it.delete() }
    val source = File(dir, "source")
    return try {
        val copied = resolver.openInputStream(uri)?.use { input -> source.outputStream().use { input.copyTo(it) } }
        val small = if (copied == null) null else ImageCompressor { dir }.reencode(source, maxBytes)
        if (small == null) {
            DocUpload(piece.name, piece.size, piece.body)
        } else {
            DocUpload(piece.name.substringBeforeLast('.') + ".jpg", small.length()) { small.asRequestBody("image/jpeg".toMediaType()) }
        }
    } catch (_: IOException) {
        null
    } catch (_: SecurityException) {
        null
    } finally {
        source.delete()
    }
}
