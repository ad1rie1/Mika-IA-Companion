package fr.qwartz.mika.ui.projects

import android.content.ClipData
import android.os.Build
import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.FlowRowScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.ReadOnlyComposable
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextMeasurer
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.projects.Checks
import fr.qwartz.mika.data.moi.projects.CheckRun
import fr.qwartz.mika.data.moi.projects.CodeLinked
import fr.qwartz.mika.data.moi.projects.CodePages
import fr.qwartz.mika.data.moi.projects.CodePull
import fr.qwartz.mika.data.moi.projects.CodeTabs
import fr.qwartz.mika.data.moi.projects.Commit
import fr.qwartz.mika.data.moi.projects.Diff
import fr.qwartz.mika.data.moi.projects.DiffBody
import fr.qwartz.mika.data.moi.projects.DiffFile
import fr.qwartz.mika.data.moi.projects.DiffLine
import fr.qwartz.mika.data.moi.projects.DiffRow
import fr.qwartz.mika.data.moi.projects.LinkedObjective
import fr.qwartz.mika.data.moi.projects.MergeStage
import fr.qwartz.mika.data.moi.projects.Remark
import fr.qwartz.mika.data.moi.projects.StateTone
import fr.qwartz.mika.data.moi.projects.TicketLine
import fr.qwartz.mika.data.moi.projects.TokenKind
import fr.qwartz.mika.data.moi.projects.askedWords
import fr.qwartz.mika.data.moi.projects.canReadWhole
import fr.qwartz.mika.data.moi.projects.checkIcon
import fr.qwartz.mika.data.moi.projects.checksTone
import fr.qwartz.mika.data.moi.projects.commitAbout
import fr.qwartz.mika.data.moi.projects.diffBody
import fr.qwartz.mika.data.moi.projects.duration
import fr.qwartz.mika.data.moi.projects.filesWords
import fr.qwartz.mika.data.moi.projects.hostText
import fr.qwartz.mika.data.moi.projects.lineNumber
import fr.qwartz.mika.data.moi.projects.mergeStage
import fr.qwartz.mika.data.moi.projects.mergeStateWords
import fr.qwartz.mika.data.moi.projects.mergedWords
import fr.qwartz.mika.data.moi.projects.objectiveTone
import fr.qwartz.mika.data.moi.projects.plural
import fr.qwartz.mika.data.moi.projects.pullColor
import fr.qwartz.mika.data.moi.projects.pullKey
import fr.qwartz.mika.data.moi.projects.pullLive
import fr.qwartz.mika.data.moi.projects.pullTitle
import fr.qwartz.mika.data.moi.projects.refusedWords
import fr.qwartz.mika.data.moi.projects.remarkSource
import fr.qwartz.mika.data.moi.projects.reviewTone
import fr.qwartz.mika.data.moi.projects.safeLink
import fr.qwartz.mika.data.moi.projects.shownLine
import fr.qwartz.mika.data.moi.projects.since
import fr.qwartz.mika.data.moi.projects.ticketTone
import fr.qwartz.mika.data.moi.projects.tokens
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.components.ProMarkdown
import fr.qwartz.mika.ui.components.ProMarkdownBlocks
import fr.qwartz.mika.ui.components.rememberNow
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Gap
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.Notice
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Shell
import fr.qwartz.mika.ui.shell.rememberSessionKey
import fr.qwartz.mika.ui.theme.states
import kotlinx.coroutines.launch
import java.util.IdentityHashMap

/*
 * Ce que les vues de l'onglet Code partagent (ADR 0296), d'après la maquette validée en largeur de téléphone : la page
 * d'un détail (son en-tête, ses volets qui restent en haut, puis son contenu), le code en chasse fixe avec ses numéros
 * de ligne, un diff unifié replié fichier par fichier, les lignes d'un commit, ce qui est lié, la confirmation d'une
 * fusion.
 *
 * **Le contenu d'un fichier et les lignes d'un diff sont du texte** : ils se posent tels quels, en chasse fixe — seules
 * des couleurs s'y ajoutent, par la sorte du jeton ; rien n'y est lu comme une mise en forme ni comme un lien. Ils
 * défilent en largeur **dans leur cadre**, jamais la page : chaque ligne défile sous ses numéros, qui restent en place,
 * et toutes les lignes d'un même fichier défilent ensemble.
 */

// ── Les modèles et le cadre d'une page ──────────────────────────────────

/** Le modèle de l'onglet Code d'un projet, que ses volets et ses pages partagent : un par projet et par session. */
@Composable
internal fun rememberCodeModel(graph: AppGraph, id: Int): CodeViewModel {
    val session = rememberSessionKey(graph)
    return viewModel(key = "code|$session|$id") { CodeViewModel(ProjectsDeps(graph), id) }
}

/** Le sort des gestes d'un modèle, dit en toast par le cadre. */
@Composable
internal fun Toasts(runner: GestureRunner) {
    val shell = LocalShell.current
    LaunchedEffect(runner) { runner.said.collect { shell.toast(it) } }
}

/** Ce qu'un écran relit à chaque fois qu'il revient devant. */
@Composable
internal fun OnResume(key: Any?, block: () -> Unit) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(key, lifecycle) { lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) { block() } }
}

/** Ce qu'une page du code tient du cadre : aller ailleurs, la fiche du projet (ses droits), l'onglet Code (son dépôt), l'heure. */
internal class CodeFrame(val shell: Shell, val project: ProjectViewModel, val code: CodeViewModel, val now: Long)

@Composable
internal fun rememberCodeFrame(graph: AppGraph, id: Int): CodeFrame {
    val shell = LocalShell.current
    val project = rememberProjectModel(graph, id)
    val code = rememberCodeModel(graph, id)
    Toasts(code.gestures)
    OnResume(code) {
        project.resume()
        code.resume()
    }
    return CodeFrame(shell, project, code, rememberNow(wallMs = graph.clock::wallMs))
}

/** Le nom d'un volet de l'onglet Code. */
@Composable
internal fun codeTabLabel(sub: String): String = stringResource(
    when (sub) {
        CodeTabs.COMMITS -> R.string.proj_code_tab_commits
        CodeTabs.PULLS -> R.string.proj_code_tab_pulls
        CodeTabs.BRANCHES -> R.string.proj_code_tab_branches
        CodeTabs.ISSUES -> R.string.proj_code_tab_issues
        CodeTabs.CI -> R.string.proj_code_tab_ci
        else -> R.string.proj_code_tab_files
    },
)

/**
 * Une page de détail du code : la barre (le volet d'où elle vient, et le retour), son en-tête, ses volets — qui restent
 * en haut quand le contenu défile —, puis le contenu du volet montré. Un seul défilement vertical ; le code et les
 * diffs défilent en largeur dans leur cadre.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun <T> CodePage(
    home: String,
    projectTitle: String?,
    load: Load<T>?,
    onRetry: () -> Unit,
    panes: @Composable (T) -> List<Pane>,
    pane: String,
    onPane: (String) -> Unit,
    head: @Composable (T) -> Unit,
    bottomBar: @Composable (T) -> Unit = {},
    notice: @Composable (T) -> Unit = {},
    body: LazyListScope.(T) -> Unit,
) = DetailPage(codeTabLabel(home), projectTitle, load, onRetry, panes, pane, onPane, head, bottomBar, notice, body = body)

/**
 * Une page de détail d'une fiche, quel que soit son onglet (une pull request, une page de documentation, une exécution,
 * un lien) : la barre ([title] : d'où elle vient ; [actions] : ses gestes), son en-tête, ses volets collants, son
 * contenu.
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun <T> DetailPage(
    title: String,
    projectTitle: String?,
    load: Load<T>?,
    onRetry: () -> Unit,
    panes: @Composable (T) -> List<Pane>,
    pane: String,
    onPane: (String) -> Unit,
    head: @Composable (T) -> Unit,
    bottomBar: @Composable (T) -> Unit = {},
    notice: @Composable (T) -> Unit = {},
    actions: @Composable RowScope.() -> Unit = {},
    body: LazyListScope.(T) -> Unit,
) {
    val list = rememberLazyListState()
    // un autre volet : il se lit depuis son début, ses onglets en haut
    LaunchedEffect(pane) { if (list.firstVisibleItemIndex > 1) list.scrollToItem(1) }
    SectionScaffold(
        topBar = { MikaTopBar(title = title, nav = BarNav.BACK, subtitle = projectTitle, actions = actions) },
        bottomBar = { load?.valueOrNull?.let { bottomBar(it) } },
    ) { modifier ->
        when (load) {
            null, Load.Loading -> Box(modifier, contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            is Load.Failed -> Notice(load.error.message, modifier, action = stringResource(R.string.retry), onAction = onRetry)
            is Load.Ready -> {
                val value = load.value
                val tabs = panes(value)
                LazyColumn(modifier, state = list, contentPadding = PaddingValues(bottom = 32.dp)) {
                    item(key = "head", contentType = "head") { head(value) }
                    if (tabs.size > 1) {
                        stickyHeader(key = "panes", contentType = "panes") { _ ->
                            Surface(color = MaterialTheme.colorScheme.surface) { PaneTabs(tabs, pane, onPane) }
                        }
                    } else {
                        item(key = "rule", contentType = "rule") { HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant) }
                    }
                    item(key = "notice", contentType = "notice") { notice(value) }
                    body(value)
                }
            }
        }
    }
}

/** Un bloc de contenu d'un volet (ce qui n'est ni du code ni un diff) : ses parties l'une sous l'autre, à la marge de l'écran. */
internal fun LazyListScope.paneBlock(key: String, content: @Composable ColumnScope.() -> Unit) {
    item(key = key, contentType = "block") {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(10.dp), content = content)
    }
}

/** L'en-tête d'une page : sa tuile à la couleur de son état, ce que c'est, son titre, une rangée de faits, puis ses boutons. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun CodeHead(
    @DrawableRes icon: Int,
    tone: StateTone,
    over: String,
    title: String,
    mono: Boolean = false,
    meta: @Composable FlowRowScope.() -> Unit = {},
    actions: (@Composable RowScope.() -> Unit)? = null,
) {
    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 10.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Tile(icon, tone, 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(over.uppercase(), style = MaterialTheme.typography.labelMedium, fontWeight = FontWeight.Bold, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(
                    title,
                    style = MaterialTheme.typography.titleMedium.let { if (mono) it.copy(fontFamily = FontFamily.Monospace) else it },
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.semantics { heading() },
                )
                Gap(6.dp)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically, content = meta)
            }
        }
        if (actions != null) {
            Gap(10.dp)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically, content = actions)
        }
    }
}

/** Un mot de l'en-tête (qui, quand), en petit. */
@Composable
internal fun MetaText(text: String) {
    if (text.isNotBlank()) Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

/** Un bandeau à la couleur d'un état : où en est une fusion, ce que l'hôte n'a pas dit. */
@Composable
internal fun Banner(tone: StateTone, @DrawableRes icon: Int, text: String, modifier: Modifier = Modifier) {
    if (text.isBlank()) return
    val c = toneOf(tone)
    Row(modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.container).padding(horizontal = 12.dp, vertical = 10.dp)) {
        MIcon(icon, null, size = 18.dp, tint = c.ink)
        Spacer(Modifier.width(10.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium, color = c.ink)
    }
}

/** Une ligne grisée : rien à montrer ici, dit en une phrase. */
@Composable
internal fun Muted(text: String) {
    if (text.isNotBlank()) Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
}

/** Une branche, en chasse fixe sur un fond léger. */
@Composable
internal fun BranchChip(name: String, modifier: Modifier = Modifier) {
    if (name.isBlank()) return
    Row(
        modifier.clip(RoundedCornerShape(6.dp)).background(MaterialTheme.colorScheme.secondaryContainer).padding(horizontal = 6.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        MIcon(R.drawable.ic_m_branch, null, size = 12.dp, tint = MaterialTheme.colorScheme.onSecondaryContainer)
        Spacer(Modifier.width(4.dp))
        Text(
            name,
            style = MaterialTheme.typography.labelMedium.copy(fontFamily = FontFamily.Monospace),
            color = MaterialTheme.colorScheme.onSecondaryContainer,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

/** Les lignes ajoutées et retirées : « +14 −2 ». */
@Composable
internal fun PlusMinus(insertions: Int, deletions: Int) {
    val style = MaterialTheme.typography.labelMedium.copy(fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold)
    Row {
        Text("+$insertions", style = style, color = states.ok, maxLines = 1)
        Spacer(Modifier.width(6.dp))
        Text("−$deletions", style = style, color = MaterialTheme.colorScheme.error, maxLines = 1)
    }
}

/** Copier un texte (un chemin, une empreinte) ; avant Android 13, qui le confirme lui-même, un toast le dit. */
@Composable
internal fun rememberCopy(): (String) -> Unit {
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val shell = LocalShell.current
    val copied = stringResource(R.string.proj_code_copied)
    return { text ->
        scope.launch {
            clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Mika", text)))
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) shell.toast(copied)
        }
    }
}

/** « Voir chez l'hôte » : la page que le serveur a composée, dans le navigateur — rien sans elle. */
@Composable
internal fun HostButton(url: String, modifier: Modifier = Modifier) {
    val safe = safeLink(url)
    if (safe.isEmpty()) return
    val context = LocalContext.current
    val shell = LocalShell.current
    val noBrowser = stringResource(R.string.proj_no_browser)
    OutlinedButton(onClick = { if (!openOutside(context, safe)) shell.toast(noBrowser) }, modifier = modifier) {
        MIcon(R.drawable.ic_m_external, null, size = 18.dp)
        Spacer(Modifier.width(6.dp))
        Text(stringResource(R.string.proj_code_at_host), maxLines = 1)
    }
}

// ── Le code, en chasse fixe ─────────────────────────────────────────────

/** Le style du code : une chasse fixe, des lignes serrées. */
@Composable
@ReadOnlyComposable
internal fun codeStyle(): TextStyle = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace, fontSize = 12.sp, lineHeight = 18.sp)

/** Les couleurs des jetons d'une ligne de code (un commentaire, une chaîne, un décorateur, un mot-clé, un nombre). */
@Composable
@ReadOnlyComposable
internal fun codePalette(): Map<TokenKind, Color> {
    val dark = MaterialTheme.colorScheme.surface.luminance() < 0.5f
    return if (dark) {
        mapOf(
            TokenKind.COMMENT to Color(0xFF8FBF8F), TokenKind.STRING to Color(0xFF9CD6A0), TokenKind.DECORATOR to Color(0xFFFF9E9E),
            TokenKind.KEYWORD to Color(0xFFA8B8FF), TokenKind.NUMBER to Color(0xFFF6BD5C),
        )
    } else {
        mapOf(
            TokenKind.COMMENT to Color(0xFF1B7F3B), TokenKind.STRING to Color(0xFF1B7F3B), TokenKind.DECORATOR to Color(0xFFB3261E),
            TokenKind.KEYWORD to Color(0xFF3F3DC9), TokenKind.NUMBER to Color(0xFFB45309),
        )
    }
}

/** Une ligne de code en couleurs : son texte tel quel, jeton après jeton — rien d'autre que des couleurs ne s'y pose. */
internal fun codeLine(shown: String, path: String, palette: Map<TokenKind, Color>): AnnotatedString = buildAnnotatedString {
    for (t in tokens(shown, path)) {
        val color = palette[t.kind]
        // une couleur, rien d'autre : une graisse élargirait la ligne, que son cadre mesure sans elle
        if (color == null) append(t.text) else withStyle(SpanStyle(color = color)) { append(t.text) }
    }
}

/** La largeur d'un caractère en chasse fixe, et celle de la ligne la plus large d'un texte : le cadre où il défile. */
internal class CodeMeasure(private val measurer: TextMeasurer, private val density: Density, val style: TextStyle) {
    val char: Dp = with(density) { measurer.measure("0", style).size.width.toDp() }

    /**
     * La largeur du contenu : celle de sa ligne la plus large ([widest], que le modèle a trouvée hors du fil
     * principal — ici on ne mesure qu'elle), et un peu d'air au bout.
     */
    fun width(widest: String): Dp =
        with(density) { measurer.measure(widest, style, softWrap = false, maxLines = 1).size.width.toDp() } + 24.dp

    /** La largeur d'une colonne de numéros de [digits] chiffres. */
    fun numbers(digits: Int): Dp = char * digits + 10.dp
}

@Composable
internal fun rememberCodeMeasure(): CodeMeasure {
    val measurer = rememberTextMeasurer()
    val density = LocalDensity.current
    val style = codeStyle()
    return remember(measurer, density, style) { CodeMeasure(measurer, density, style) }
}

/**
 * Les lignes d'un fichier : son numéro, qui reste en place, puis la ligne, qui défile en largeur avec toutes les autres
 * ([scroll], le même pour tout le fichier) dans un cadre de la largeur de la plus longue ([width]). [shownLines] :
 * ses lignes déjà mises en place par le modèle (`Blob.laid`).
 */
internal fun LazyListScope.sourceLines(shownLines: List<String>, path: String, width: Dp, numbers: Dp, scroll: ScrollState) {
    itemsIndexed(shownLines, key = { i, _ -> "src$i" }, contentType = { _, _ -> "src" }) { i, line ->
        val style = codeStyle()
        val palette = codePalette()
        val text = remember(line, path, palette) { codeLine(line, path, palette) }
        Row(Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerLowest)) {
            Text(
                (i + 1).toString(),
                style = style,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.End,
                maxLines = 1,
                modifier = Modifier.width(numbers + 12.dp).padding(end = 10.dp),
            )
            Box(Modifier.weight(1f).horizontalScroll(scroll)) {
                Text(text, style = style, softWrap = false, maxLines = 1, modifier = Modifier.width(width))
            }
        }
    }
}

// ── Un diff unifié, replié fichier par fichier ──────────────────────────

/**
 * Ce qu'un diff garde à l'écran : ses fichiers dépliés (un diff d'un seul fichier s'ouvre d'office), le défilement en
 * largeur de chacun, et ses lignes mises en rangées — calculées une fois par fichier.
 */
internal class DiffUi(private val measure: CodeMeasure) {
    val style: TextStyle get() = measure.style
    private val opened = mutableStateMapOf<String, Boolean>()
    private val scrolls = HashMap<String, ScrollState>()
    private val laid = IdentityHashMap<DiffFile, Laid>()

    /** Un fichier mis en rangées : ses lignes telles qu'on les pose, la largeur de son cadre, celle de ses numéros. */
    class Laid(val rows: List<DiffRow>, val width: Dp, val numbers: Dp)

    fun open(path: String, alone: Boolean): Boolean = opened[path] ?: alone

    fun toggle(path: String, alone: Boolean) {
        opened[path] = !open(path, alone)
    }

    fun scroll(path: String): ScrollState = scrolls.getOrPut(path) { ScrollState(0) }

    /** Ses rangées sont celles que le modèle a calculées en lisant le diff (`DiffFile.laid`) : ici, seule sa ligne la plus large se mesure. */
    fun laid(f: DiffFile): Laid = laid.getOrPut(f) {
        val layout = f.laid
        Laid(layout.rows, measure.width(layout.widest), measure.numbers(layout.digits))
    }
}

@Composable
internal fun rememberDiffUi(): DiffUi {
    val measure = rememberCodeMeasure()
    return remember(measure) { DiffUi(measure) }
}

/**
 * Les fichiers d'un diff, l'un sous l'autre : chacun a sa ligne (son chemin, ce qui lui arrive, ses comptes), qu'on
 * touche pour déplier son diff. Sans le droit sur ses fichiers, les mots du serveur. Un diff coupé le dit, et un
 * fichier coupé se relit seul ([whole], [onWhole]).
 */
internal fun LazyListScope.diffZone(diff: Diff, ui: DiffUi, whole: Map<String, Load<DiffFile>>, onWhole: (String) -> Unit) {
    if (!diff.filesReadable) {
        item(key = "diff-closed") { EmptyNote(R.drawable.ic_m_lock, stringResource(R.string.proj_code_files_closed), diff.filesWhy) }
        return
    }
    if (diff.files.isEmpty()) {
        paneBlock("diff-none") { Muted(stringResource(R.string.proj_code_diff_none)) }
        return
    }
    val alone = diff.files.size == 1
    item(key = "diff-sum", contentType = "diff-sum") {
        Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (diff.cut) Banner(StateTone.WAIT, R.drawable.ic_m_info, diff.cutLabel)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(filesWords(diff), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Spacer(Modifier.width(10.dp))
                PlusMinus(diff.insertions, diff.deletions)
            }
        }
    }
    diff.files.forEachIndexed { i, served ->
        val open = ui.open(served.path, alone)
        item(key = "df$i", contentType = "diff-file") { DiffFileHead(served, open) { ui.toggle(served.path, alone) } }
        if (!open) return@forEachIndexed
        val read = whole[served.path]
        val f = (read as? Load.Ready)?.value ?: served
        when (diffBody(f)) {
            DiffBody.HIDDEN -> paneBlock("df$i-hidden") { Muted(f.why.ifBlank { stringResource(R.string.proj_code_diff_hidden) }) }
            DiffBody.BINARY -> paneBlock("df$i-binary") { Muted(stringResource(R.string.proj_code_diff_binary)) }
            DiffBody.NOTHING -> Unit
            DiffBody.LINES -> {
                val laid = ui.laid(f)
                val scroll = ui.scroll(f.path)
                itemsIndexed(laid.rows, key = { j, _ -> "df$i-$j" }, contentType = { _, r -> if (r is DiffRow.Head) "diff-head" else "diff-line" }) { _, row ->
                    when (row) {
                        is DiffRow.Head -> DiffHunkHead(row.header, ui.style)
                        is DiffRow.Line -> DiffLineRow(row.line, f.path, laid, scroll, ui.style)
                    }
                }
            }
        }
        if (canReadWhole(f)) {
            paneBlock("df$i-cut") {
                Muted(stringResource(if (f.hunks.isNotEmpty()) R.string.proj_code_diff_cut_some else R.string.proj_code_diff_cut_all))
                if (read is Load.Failed) RefusalNote(read.error.message)
                // relu seul et encore coupé (un fichier plus long que la borne du serveur) : il n'y a pas plus à demander
                if (read !is Load.Ready) {
                    OutlinedButton(onClick = { onWhole(f.path) }, enabled = read !is Load.Loading) {
                        Text(stringResource(if (read is Load.Loading) R.string.proj_code_reading else R.string.proj_code_diff_whole))
                    }
                }
            }
        }
        if (diffBody(f) == DiffBody.LINES && !alone) {
            item(key = "df$i-fold", contentType = "diff-fold") {
                TextButton(onClick = { ui.toggle(served.path, alone) }, modifier = Modifier.padding(horizontal = 8.dp)) {
                    MIcon(R.drawable.ic_m_chev_up, null, size = 16.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.proj_code_diff_fold))
                }
            }
        }
    }
}

/** La ligne d'un fichier d'un diff : déplié ou non, son chemin en chasse fixe, ce qui lui arrive (les mots du serveur), ses comptes. */
@Composable
private fun DiffFileHead(f: DiffFile, open: Boolean, onToggle: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClickLabel = stringResource(R.string.proj_code_diff_toggle), onClick = onToggle)) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Row(
            Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surfaceContainerLow).padding(start = 12.dp, end = 16.dp, top = 10.dp, bottom = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            MIcon(if (open) R.drawable.ic_m_chev_down else R.drawable.ic_m_chev_right, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.width(6.dp))
            Column(Modifier.weight(1f)) {
                Text(f.path, style = codeStyle(), fontWeight = FontWeight.SemiBold)
                if (f.status != "modified" && f.statusLabel.isNotBlank()) {
                    Gap(3.dp)
                    StatePill(if (f.status == "deleted") StateTone.FAIL else StateTone.DONE, f.statusLabel)
                }
            }
            Spacer(Modifier.width(10.dp))
            PlusMinus(f.insertions, f.deletions)
        }
    }
}

/** L'en-tête d'un passage (« @@ -1,9 +1,22 @@ ») : du texte, comme le reste. */
@Composable
private fun DiffHunkHead(header: String, style: TextStyle) {
    val c = toneOf(StateTone.WORK)
    Text(
        header,
        style = style,
        color = c.ink,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier.fillMaxWidth().background(c.container.copy(alpha = 0.55f)).padding(horizontal = 12.dp, vertical = 2.dp),
    )
}

/** Une ligne d'un diff : ses deux numéros (avant, après), son signe, puis son texte, qui défile en largeur avec le fichier. */
@Composable
private fun DiffLineRow(line: DiffLine, path: String, laid: DiffUi.Laid, scroll: ScrollState, style: TextStyle) {
    val palette = codePalette()
    val text = remember(line, path, palette) { codeLine(shownLine(line.text), path, palette) }
    val tone = when (line.kind) {
        "+" -> toneOf(StateTone.DONE)
        "-" -> toneOf(StateTone.FAIL)
        else -> null
    }
    val faint = MaterialTheme.colorScheme.onSurfaceVariant
    Row(Modifier.fillMaxWidth().background(tone?.container?.copy(alpha = 0.6f) ?: MaterialTheme.colorScheme.surfaceContainerLowest)) {
        Text(lineNumber(line.old), style = style, color = faint, textAlign = TextAlign.End, maxLines = 1, modifier = Modifier.width(laid.numbers))
        Text(lineNumber(line.new), style = style, color = faint, textAlign = TextAlign.End, maxLines = 1, modifier = Modifier.width(laid.numbers))
        Text(line.kind.trim(), style = style, color = tone?.ink ?: faint, textAlign = TextAlign.Center, maxLines = 1, modifier = Modifier.width(18.dp))
        Box(Modifier.weight(1f).horizontalScroll(scroll)) {
            Text(text, style = style, softWrap = false, maxLines = 1, modifier = Modifier.width(laid.width))
        }
    }
}

// ── Un fichier Markdown du dépôt, rendu ─────────────────────────────────

/**
 * Les blocs d'un fichier Markdown du dépôt, tels qu'on les montre : ceux du rendu du mode pro, **sans un lien qui
 * s'ouvre** — le contenu d'un fichier peut venir d'ailleurs, une adresse qu'il contient ne devient jamais un bouton. Le
 * rendu ne charge aucune image et n'exécute rien : il ne pose que du texte.
 */
internal fun repoMarkdown(text: String): List<ProMarkdown.Block> {
    fun plain(spans: List<ProMarkdown.Span>) = spans.map { it.copy(url = null) }
    return ProMarkdown.parse(text).map { block ->
        when (block) {
            is ProMarkdown.Block.Paragraph -> block.copy(spans = plain(block.spans))
            is ProMarkdown.Block.Heading -> block.copy(spans = plain(block.spans))
            is ProMarkdown.Block.Item -> block.copy(spans = plain(block.spans))
            is ProMarkdown.Block.Quote -> block.copy(spans = plain(block.spans))
            is ProMarkdown.Block.Table -> block.copy(header = block.header.map(::plain), rows = block.rows.map { row -> row.map(::plain) })
            is ProMarkdown.Block.Code, ProMarkdown.Block.Rule -> block
        }
    }
}

/** Un fichier Markdown rendu : ses blocs, que le modèle a lus hors du fil principal (`FileViewModel.rendered`). */
@Composable
internal fun RepoMarkdown(blocks: List<ProMarkdown.Block>, modifier: Modifier = Modifier) {
    ProMarkdownBlocks(blocks, MaterialTheme.colorScheme.onSurface, modifier)
}

// ── Les commits ─────────────────────────────────────────────────────────

/** Un commit dans une ligne de temps : son message, son empreinte, sa branche, ce qu'il concerne, ses comptes. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun CommitRow(c: Commit, last: Boolean, onClick: () -> Unit) {
    Box(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = 12.dp, end = 16.dp, top = 6.dp)) {
        TimelineRow(if (c.merge) StateTone.DONE else StateTone.WORK, last) {
            Text(c.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Gap(4.dp)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                Code(c.short)
                BranchChip(c.branch)
                MetaText(commitAbout(c))
                if (c.outside) OutsideMark()
                if (c.merge && c.files == 0) MetaText(stringResource(R.string.proj_code_merge_commit)) else PlusMinus(c.insertions, c.deletions)
            }
        }
    }
}

/** Un commit en une ligne (un dernier commit, un historique, ce qu'une branche a d'avance) : son message, son empreinte, quand. */
@Composable
internal fun CommitLine(c: Commit, now: Long, onClick: (() -> Unit)? = null) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier).padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Tile(if (c.merge) R.drawable.ic_m_merge else R.drawable.ic_m_commit, if (c.merge) StateTone.DONE else StateTone.WORK, 32.dp)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(c.title, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Row(verticalAlignment = Alignment.CenterVertically) {
                Code(c.short)
                Spacer(Modifier.width(8.dp))
                MetaText(listOf(c.author, since(c.at, now)).filter { it.isNotBlank() }.joinToString(" · "))
                if (c.outside) {
                    Spacer(Modifier.width(8.dp))
                    OutsideMark()
                }
            }
        }
        if (onClick != null) MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

// ── Ce qui est lié ──────────────────────────────────────────────────────

@Composable
internal fun ObjectiveLinked(project: Int, o: LinkedObjective?) {
    if (o == null) return
    val shell = LocalShell.current
    val mission = o.kind == "constant"
    val tone = objectiveTone(o.status)
    LinkedLine(
        R.drawable.ic_m_target, tone, o.text.ifBlank { stringResource(R.string.proj_goal_n, o.id) }, stringResource(R.string.proj_goal_n, o.id),
        pill = { StatePill(tone, o.statusLabel) },
        onClick = { shell.navigate(Route.ProjectGoal(project, (if (mission) "m" else "o") + o.id)) },
    )
}

@Composable
internal fun TicketLinked(project: Int, t: TicketLine?) {
    if (t == null) return
    val shell = LocalShell.current
    val tone = ticketTone(t.status, t.open, t.yours)
    LinkedLine(
        R.drawable.ic_m_ticket, tone, t.title.ifBlank { t.veiledLabel.ifBlank { stringResource(R.string.proj_ticket) } }, "#${t.number}",
        pill = { StatePill(tone, t.statusLabel) },
        onClick = { shell.navigate(Route.ProjectTicket(project, t.number)) },
    )
}

/** Une pull request liée, avec son statut : son état, sa CI, sa relecture — les mots du serveur. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun PullLinked(project: Int, p: CodePull?, objective: LinkedObjective? = null) {
    if (p == null) return
    val shell = LocalShell.current
    val tone = pullColor(p)
    val named = if (p.objective == null && objective != null) p.copy(objective = objective) else p
    Surface(
        shape = RoundedCornerShape(12.dp),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).clickable { shell.navigate(Route.ProjectCode(project, CodePages.PULL, pullKey(named))) },
    ) {
        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.Top) {
            Tile(if (p.state == "merged") R.drawable.ic_m_merge else R.drawable.ic_m_pr, tone, 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(pullTitle(named), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                MetaText(listOf(if (p.number > 0) stringResource(R.string.proj_number, p.number) else "", p.branch).filter { it.isNotBlank() }.joinToString(" · "))
                Gap(6.dp)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    StatePill(tone, p.stateLabel)
                    if (pullLive(p)) {
                        p.checks?.let { StatePill(checksTone(it.state), stringResource(R.string.proj_pull_ci, it.stateLabel)) }
                        p.review?.let { StatePill(reviewTone(it), it.label) }
                    }
                }
            }
            MIcon(R.drawable.ic_m_chev_right, null, size = 18.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
internal fun ChecksLinked(project: Int, c: Checks?, now: Long) {
    if (c == null || c.sha.isBlank()) return
    val shell = LocalShell.current
    val tone = checksTone(c.state)
    LinkedLine(
        R.drawable.ic_m_bolt, tone, stringResource(R.string.proj_code_side_checks), listOf(c.sha.take(7), since(c.at, now)).filter { it.isNotBlank() }.joinToString(" · "),
        pill = { StatePill(tone, c.stateLabel) },
        onClick = { shell.navigate(Route.ProjectCode(project, CodePages.CHECKS, c.sha)) },
    )
}

/** Ce qui est lié à un commit ou à une branche : l'objectif, son ticket, sa pull request, ses vérifications. */
@Composable
internal fun LinkedCode(project: Int, l: CodeLinked, now: Long, none: String = stringResource(R.string.proj_linked_none)) {
    if (l.objective == null && l.ticket == null && l.pull == null && l.checks == null) {
        Muted(none)
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        ObjectiveLinked(project, l.objective)
        TicketLinked(project, l.ticket)
        PullLinked(project, l.pull, l.objective)
        ChecksLinked(project, l.checks, now)
    }
}

// ── Ce qui vient de l'hôte ──────────────────────────────────────────────

/** Un échange venu de l'hôte : cité tel quel, sous le compte qui l'a écrit là-bas. */
@Composable
internal fun RemarkView(x: Remark, now: Long) {
    OutsideBlock(remarkSource(x, now), x.text)
}

/** Les vérifications une à une ; leurs noms sont ceux que l'hôte donne, posés tels quels. */
@Composable
internal fun RunsList(runs: List<CheckRun>, big: Boolean = false) {
    Column {
        for (r in runs) {
            val tone = checksTone(r.state)
            val c = toneOf(tone)
            Row(Modifier.fillMaxWidth().padding(vertical = if (big) 9.dp else 5.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(if (big) 28.dp else 22.dp).background(c.container, CircleShape), contentAlignment = Alignment.Center) {
                    MIcon(projectIcon(checkIcon(r.state)), null, size = if (big) 15.dp else 12.dp, tint = c.ink)
                }
                Spacer(Modifier.width(10.dp))
                Text(
                    hostText(r.name).ifBlank { stringResource(R.string.proj_code_ci_run) },
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = if (big) FontWeight.SemiBold else FontWeight.Normal,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                MetaText(duration(r.seconds).ifBlank { if (big) "" else r.stateLabel })
                if (big) {
                    Spacer(Modifier.width(8.dp))
                    StatePill(tone, r.stateLabel)
                }
            }
        }
    }
}

// ── Fusionner ───────────────────────────────────────────────────────────

/** Où en est une fusion, sans son bouton : faite, demandée, refusée par l'hôte, possible — avec les mots du serveur. */
@Composable
internal fun MergeStatus(p: CodePull, now: Long, held: Boolean = true) {
    val stage = mergeStage(p)
    if (stage == MergeStage.MERGED) {
        Banner(StateTone.DONE, R.drawable.ic_m_merge, mergedWords(p, now))
        return
    }
    if (stage == MergeStage.ASKED) Banner(StateTone.WORK, R.drawable.ic_m_clock, askedWords(p, now))
    Banner(StateTone.FAIL, R.drawable.ic_m_alert, refusedWords(p, now))
    when {
        stage == MergeStage.READY -> Banner(StateTone.YOU, R.drawable.ic_m_check, stringResource(R.string.proj_code_merge_ready))
        stage != MergeStage.ASKED && held -> Banner(StateTone.WAIT, R.drawable.ic_m_clock, p.merge.why)
    }
}

/** Le bouton de la fusion : seulement s'il est servi ([canMerge]), actif seulement si le serveur le dit (`merge.can`). */
@Composable
internal fun MergeButton(p: CodePull, busy: Boolean, onMerge: () -> Unit, modifier: Modifier = Modifier) {
    Button(onClick = onMerge, enabled = p.merge.can && !busy, modifier = modifier.fillMaxWidth()) {
        MIcon(R.drawable.ic_m_merge, null, size = 18.dp)
        Spacer(Modifier.width(8.dp))
        Text(if (p.base.isBlank()) stringResource(R.string.proj_code_merge) else stringResource(R.string.proj_code_merge_into, p.base), maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/**
 * La confirmation d'une fusion : ce qui va être fusionné — son titre, sa branche et sa base, ses commits, ses fichiers,
 * où elle en est — et le commit de tête que la demande nommera. Rien ne part sans elle.
 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun MergeDialog(asking: MergeFlow.Asking, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    val f = asking.facts
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { MIcon(R.drawable.ic_m_merge, null) },
        title = { Text(stringResource(R.string.proj_code_merge_title, f.number)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(f.title, style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.Bold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                    BranchChip(f.branch)
                    MIcon(R.drawable.ic_m_chev_right, null, size = 14.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    BranchChip(f.base)
                }
                MergeFact(R.drawable.ic_m_commit, plural(f.commits, "commit", "commits"))
                if (f.counted) MergeFact(R.drawable.ic_m_file, stringResource(R.string.proj_code_merge_files, plural(f.files, "fichier", "fichiers"), f.insertions, f.deletions))
                MergeFact(R.drawable.ic_m_check, mergeStateWords(f))
                Text(stringResource(R.string.proj_code_merge_head, f.head.take(12)), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(stringResource(R.string.proj_code_merge_yours), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        },
        confirmButton = { Button(onClick = onConfirm) { Text(stringResource(R.string.proj_code_merge_into, f.base), maxLines = 1, overflow = TextOverflow.Ellipsis) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
private fun MergeFact(@DrawableRes icon: Int, text: String) {
    if (text.isBlank()) return
    Row(verticalAlignment = Alignment.CenterVertically) {
        MIcon(icon, null, size = 16.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        Spacer(Modifier.width(8.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}
