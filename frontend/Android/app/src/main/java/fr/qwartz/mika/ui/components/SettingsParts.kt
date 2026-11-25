package fr.qwartz.mika.ui.components

import android.content.ClipData
import android.content.ClipDescription
import android.os.Build
import android.os.PersistableBundle
import androidx.annotation.DrawableRes
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.Clipboard
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.settings.settingsApi
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.settings.SettingsApi
import fr.qwartz.mika.data.moi.settings.fieldErrors
import fr.qwartz.mika.data.moi.settings.refusalToast
import fr.qwartz.mika.data.moi.settings.unplaced
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LoadBox
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MIcon
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.SectionScaffold
import fr.qwartz.mika.ui.shell.Tag
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow

/*
 * Les pièces de Paramètres (ADR 0235, la maquette `ecrans/plus.js`), que les pages de chaque domaine partagent : ce que
 * leurs ViewModels partagent (l'API, le sort d'un geste, aller ailleurs), un titre de groupe et son groupe, une ligne qui
 * mène à une page, une ligne de réglage, un champ et son refus dessous, un choix à boutons ou en liste, la barre
 * « Enregistrer », une confirmation.
 */

// ── Les ViewModels ──────────────────────────────────────────────────────

/**
 * Ce que suivent les pages de Paramètres qui montrent une liste (ADR 0308, § 2 bis) : tes réglages (`settings` — qui
 * voit quoi, tes services, tes partages), l'état de tes boîtes (`mail`) et de tes comptes Teams (`teams`), tes
 * téléphones (`phone.phones`). Un formulaire ne se relit pas sous ta saisie : il se relit quand on le rouvre.
 */
internal object SettingsLive {
    val HOME = setOf(Topics.SETTINGS, Topics.MAIL, Topics.TEAMS, Topics.PHONE_PHONES, Topics.AGENDA)
    val BOXES = setOf(Topics.SETTINGS, Topics.MAIL)
    val TEAMS = setOf(Topics.SETTINGS, Topics.TEAMS)
    val PHONES = setOf(Topics.PHONE_PHONES)
    val SERVICES = setOf(Topics.SETTINGS)
    val SHARES = setOf(Topics.SETTINGS)
}

/**
 * Ce dont un modèle de Paramètres a besoin : l'API, ses textes (les chaînes `settings_*`), relire les pastilles du
 * tiroir. Sur la JVM, ses tests lui donnent une fausse API et des textes nommés.
 */
class SettingsDeps(
    val api: SettingsApi,
    val text: (Int, Array<out Any>) -> String,
    val refreshBadges: () -> Unit = {},
) {
    constructor(graph: AppGraph) : this(graph.settingsApi(), { id, args -> graph.context.getString(id, *args) }, { graph.me.refresh() })
}

/** Où va l'écran après un geste : en arrière (une boîte retirée), ou ailleurs à sa place (une boîte créée). */
internal sealed interface Move {
    data object Back : Move
    data class Replace(val route: Route) : Move
}

/**
 * Les « où aller après » d'un modèle de Paramètres, chacun pour l'ouverture de page qui a fait son geste. Un modèle sert
 * toutes les pages de sa sorte : un « Retirer » qui répond après qu'on a quitté sa page ne ferme pas (ni ne remplace) la
 * page suivante de la même sorte — une autre boîte.
 */
internal class PageMoves {
    private val channel = Channel<Move>(Channel.BUFFERED)
    val moved: Flow<Move> = channel.receiveAsFlow()

    /** Une nouvelle ouverture : ce qui attendait pour la précédente (sa page quittée avant la réponse) part. */
    fun reopened() {
        while (channel.tryReceive().isSuccess) Unit
    }

    /** [from] : l'ouverture où le geste a commencé ; [now] : celle de la page à l'écran. Rouverte depuis : rien. */
    fun send(m: Move, from: String, now: String) {
        if (from == now) channel.trySend(m)
    }
}

/**
 * Ce que tous les écrans de Paramètres ont : l'API, le sort d'un geste à dire, où aller après. Un modèle sert toutes
 * les pages de sa sorte (toutes les boîtes, tous les services) : un geste fige en commençant tout ce qu'il enverra et
 * l'ouverture où il a commencé ([opening]) ; quand il répond, rien ne se pose sur une page qui n'est plus la sienne
 * ([stillOn]) — son sort se dit en toast, nommé ([sayFor]).
 */
abstract class SettingsModel(protected val deps: SettingsDeps) : ViewModel() {
    constructor(graph: AppGraph) : this(SettingsDeps(graph))

    protected val api = deps.api
    private val notices = Channel<String>(Channel.BUFFERED)
    private val moves = PageMoves()

    /** Le sort des gestes, une fois chacun (l'écran le montre en toast). */
    val said: Flow<String> = notices.receiveAsFlow()
    internal val moved: Flow<Move> = moves.moved

    protected fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    protected fun say(error: MoiError) = say(error.said)

    /** Où aller après le geste commencé sur l'ouverture [from] ([opening] au moment du geste). */
    internal fun move(m: Move, from: String) {
        moves.send(m, from, openedFor)
    }

    /**
     * Pour quelle ouverture de sa page ce modèle tient-il ce qu'il montre : un passage sur la page ([entry], gardé par
     * `rememberSaveable`, le même après une rotation) et ce qu'elle règle ([what]). Un modèle sert toutes les pages de
     * sa sorte : tant qu'il n'a pas été rouvert pour celle-ci, elle ne montre rien de la précédente.
     */
    var openedFor by mutableStateOf("")
        private set

    /** L'ouverture de la page à l'écran : un geste la retient en commençant, pour [move] quand il finit. */
    protected val opening: String get() = openedFor

    /** Rouvrir pour cette page ; `true` : c'est une nouvelle ouverture (ce qu'il tenait est à oublier). */
    protected fun reopen(entry: String, what: String = ""): Boolean {
        val id = "$entry|$what"
        if (id == openedFor) return false
        openedFor = id
        moves.reopened()
        return true
    }

    fun isOpenFor(entry: String, what: String = ""): Boolean = openedFor == "$entry|$what"

    /** Un texte de l'app (ses chaînes `settings_*`). */
    protected fun text(id: Int, vararg args: Any): String = deps.text(id, args)

    /** Le geste commencé sur l'ouverture [from] a encore sa page à l'écran. */
    protected fun stillOn(from: String): Boolean = from == openedFor

    /** Le sort d'un geste : tel quel sur sa page ; sa page quittée avant la réponse, avec le nom de ce qu'il réglait
     *  ([what]) — il ne se lit pas comme celui de la page à l'écran. */
    protected fun sayFor(from: String, what: String, said: String) {
        if (said.isBlank()) return
        say(if (stillOn(from)) said else text(R.string.settings_elsewhere, what, said))
    }

    /**
     * Le refus d'un formulaire : ses champs sous les leurs tant que sa page est à l'écran ; quittée, tout se dit dans le
     * toast, nommé, et rien (`null`) ne se pose sous les champs d'une autre page.
     */
    protected fun refusedFor(from: String, what: String, error: MoiError, shown: Set<String>, labels: Map<String, String>): Map<String, String>? {
        if (stillOn(from)) return refused(error, shown, labels)
        sayFor(from, what, refusalToast(error.message, unplaced(fieldErrors(error.fields), emptySet(), labels)))
        return null
    }

    /**
     * Un refus d'un formulaire : ses champs sous les leurs ([shown] : ceux que le formulaire montre), et en toast son
     * message, avec ce qui n'a pas trouvé de place. Rend les messages par champ.
     */
    protected fun refused(error: MoiError, shown: Set<String>, labels: Map<String, String>): Map<String, String> {
        val errors = fieldErrors(error.fields)
        if (errors.isEmpty()) {
            say(error.said)
            return emptyMap()
        }
        say(refusalToast(error.message, unplaced(errors, shown, labels)))
        return errors.filterKeys { it in shown }
    }
}

/** Une page dont le modèle n'est pas encore rouvert pour elle : sa barre, et le rond qui tourne. */
@Composable
internal fun SettingsLoading(title: String) {
    SectionScaffold(topBar = { MikaTopBar(title, BarNav.BACK) }) { modifier -> LoadBox(Load.Loading, onRetry = {}, modifier = modifier) {} }
}

/** Le sort des gestes en toast, et où aller ensuite. */
@Composable
internal fun SettingsEffects(vm: SettingsModel) {
    val shell = LocalShell.current
    LaunchedEffect(vm) { vm.said.collect { shell.toast(it) } }
    LaunchedEffect(vm) {
        vm.moved.collect { m ->
            when (m) {
                Move.Back -> shell.back()
                is Move.Replace -> shell.replace(m.route)
            }
        }
    }
}

// ── Les groupes et leurs lignes ─────────────────────────────────────────

/** Un titre de groupe (`.set-h`). */
@Composable
internal fun SetHead(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleSmall,
        fontWeight = FontWeight.Medium,
        color = MaterialTheme.colorScheme.primary,
        modifier = Modifier.padding(start = 28.dp, end = 28.dp, top = 18.dp, bottom = 6.dp).semantics { heading() },
    )
}

/** Un groupe de lignes (`.set-group`) : un fond arrondi, un filet entre les lignes ([SetDivider]). */
@Composable
internal fun SetGroup(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        shape = RoundedCornerShape(16.dp),
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        modifier = modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
    ) {
        Column(content = content)
    }
}

@Composable
internal fun SetDivider() = HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.6f))

/** Une ligne qui mène ailleurs (`.li`) : son icône dans un carré, son nom, ce qu'elle dit, et au bout ce qu'on veut. */
@Composable
internal fun SetItem(
    @DrawableRes icon: Int?,
    title: String,
    subtitle: String = "",
    onClick: (() -> Unit)? = null,
    boxed: Boolean = true,
    lead: (@Composable () -> Unit)? = null,
    trailing: @Composable () -> Unit = {},
) {
    val clickable = if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier
    Row(
        Modifier.fillMaxWidth().then(clickable).heightIn(min = 56.dp).padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        when {
            lead != null -> lead()
            icon != null -> Box(
                Modifier.size(40.dp).clip(RoundedCornerShape(12.dp)).then(
                    if (boxed) Modifier.background(MaterialTheme.colorScheme.surfaceContainerHigh) else Modifier,
                ),
                contentAlignment = Alignment.Center,
            ) { MIcon(icon, null, tint = MaterialTheme.colorScheme.onSurfaceVariant) }
        }
        if (lead != null || icon != null) Spacer(Modifier.width(16.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle.isNotBlank()) {
                Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 3, overflow = TextOverflow.Ellipsis)
            }
        }
        Spacer(Modifier.width(8.dp))
        trailing()
    }
}

/** Une ligne de réglage (`.set-row`) : son nom, son aide, et ce qui le règle, dessous. */
@Composable
internal fun SetRow(title: String, help: String = "", content: @Composable ColumnScope.() -> Unit = {}) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 12.dp)) {
        if (title.isNotBlank()) Text(title, style = MaterialTheme.typography.bodyLarge)
        if (help.isNotBlank()) Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        content()
    }
}

/** Un réglage qui s'allume ou s'éteint : la ligne entière est l'interrupteur. */
@Composable
internal fun SetSwitch(title: String, help: String, checked: Boolean, onChange: (Boolean) -> Unit, enabled: Boolean = true, error: String? = null) {
    Column {
        Row(
            Modifier
                .fillMaxWidth()
                .heightIn(min = 56.dp)
                .toggleable(value = checked, enabled = enabled, role = Role.Switch, onValueChange = onChange)
                .padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f).padding(end = 16.dp)) {
                Text(title, style = MaterialTheme.typography.bodyLarge)
                if (help.isNotBlank()) Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            Switch(checked = checked, onCheckedChange = null, enabled = enabled)
        }
        if (error != null) FieldError(error, Modifier.padding(start = 14.dp, end = 14.dp, bottom = 8.dp))
    }
}

/** Le refus d'un champ, sous lui. */
@Composable
internal fun FieldError(text: String, modifier: Modifier = Modifier) {
    Row(modifier, verticalAlignment = Alignment.CenterVertically) {
        MIcon(R.drawable.ic_m_alert, null, size = 14.dp, tint = MaterialTheme.colorScheme.error)
        Spacer(Modifier.width(4.dp))
        Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
    }
}

/**
 * Un champ texte (`.tf`) : son nom, son aide ou son refus dessous ([error] l'emporte). [secret] : un mot de passe ;
 * [mono] : une adresse, un identifiant, une clé ; [number] : le clavier des chiffres.
 */
@Composable
internal fun SetField(
    label: String,
    value: String,
    onValue: (String) -> Unit,
    modifier: Modifier = Modifier,
    help: String = "",
    error: String? = null,
    placeholder: String = "",
    singleLine: Boolean = true,
    minLines: Int = 1,
    secret: Boolean = false,
    mono: Boolean = false,
    number: Boolean = false,
    keyboard: KeyboardType? = null,
    max: Int = Int.MAX_VALUE,
    enabled: Boolean = true,
) {
    OutlinedTextField(
        value = value,
        onValueChange = { onValue(it.take(max)) },
        label = { Text(label) },
        placeholder = if (placeholder.isNotEmpty()) ({ Text(placeholder) }) else null,
        singleLine = singleLine,
        minLines = if (singleLine) 1 else minLines,
        isError = error != null,
        enabled = enabled,
        supportingText = when {
            error != null -> ({ Text(error) })
            help.isNotBlank() -> ({ Text(help) })
            else -> null
        },
        visualTransformation = if (secret) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(
            keyboardType = keyboard ?: when {
                secret -> KeyboardType.Password
                number -> KeyboardType.Number
                else -> KeyboardType.Text
            },
            autoCorrectEnabled = !secret && !mono && !number,
        ),
        textStyle = if (mono) MaterialTheme.typography.bodyLarge.copy(fontFamily = FontFamily.Monospace, fontSize = 14.sp) else MaterialTheme.typography.bodyLarge,
        modifier = modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 4.dp),
    )
}

/** Un choix à boutons (`.seg`) ; [selected] vide : aucun (un outil qui attend son choix). */
@Composable
internal fun ChoiceSeg(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit, modifier: Modifier = Modifier) {
    SingleChoiceSegmentedButtonRow(modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp)) {
        options.forEachIndexed { i, (k, label) ->
            SegmentedButton(
                selected = k == selected,
                onClick = { onSelect(k) },
                shape = SegmentedButtonDefaults.itemShape(i, options.size),
                label = { Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            )
        }
    }
}

/** Un choix dans une liste : sa valeur, et la liste qui s'ouvre d'un toucher. Une valeur inconnue se montre telle. */
@Composable
internal fun PickField(label: String, options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit, error: String? = null, enabled: Boolean = true) {
    var open by remember { mutableStateOf(false) }
    val shown = options.firstOrNull { it.first == selected }?.second ?: selected
    Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp)) {
        Box {
            Surface(
                onClick = { open = true },
                enabled = enabled,
                shape = RoundedCornerShape(6.dp),
                color = MaterialTheme.colorScheme.surface,
                border = BorderStroke(1.dp, if (error != null) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.outline),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(Modifier.padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(shown, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                    MIcon(R.drawable.ic_m_chev_down, null, size = 20.dp, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
            DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                for ((k, l) in options) {
                    DropdownMenuItem(
                        text = { Text(l) },
                        leadingIcon = if (k == selected) ({ MIcon(R.drawable.ic_m_check, null, size = 18.dp) }) else null,
                        onClick = {
                            open = false
                            onSelect(k)
                        },
                    )
                }
            }
        }
        if (error != null) FieldError(error, Modifier.padding(top = 4.dp))
    }
}

/** La tête d'une page qui règle une chose : son icône, son nom, ce qu'elle est, son état. */
@Composable
internal fun HeadCard(@DrawableRes icon: Int, title: String, subtitle: String, tag: Pair<Tone, String>? = null) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(
            Modifier.size(48.dp).clip(RoundedCornerShape(14.dp)).background(MaterialTheme.colorScheme.primaryContainer),
            contentAlignment = Alignment.Center,
        ) { MIcon(icon, null, tint = MaterialTheme.colorScheme.onPrimaryContainer) }
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            if (subtitle.isNotBlank()) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (tag != null) {
            Spacer(Modifier.width(8.dp))
            Tag(tag.second, tag.first)
        }
    }
}

/** Un bouton qui retire, en bas d'une page. */
@Composable
internal fun DangerButton(text: String, onClick: () -> Unit, @DrawableRes icon: Int = R.drawable.ic_m_trash, enabled: Boolean = true) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.outlinedButtonColors(contentColor = MaterialTheme.colorScheme.error),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.error.copy(alpha = 0.6f)),
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
    ) {
        MIcon(icon, null, size = 18.dp)
        Spacer(Modifier.width(8.dp))
        Text(text)
    }
}

/** Un geste d'une page (tester, se connecter) : un bouton à contour, son icône, et rien tant qu'il travaille. */
@Composable
internal fun ActionButton(text: String, @DrawableRes icon: Int, onClick: () -> Unit, modifier: Modifier = Modifier, enabled: Boolean = true) {
    OutlinedButton(onClick = onClick, enabled = enabled, modifier = modifier) {
        MIcon(icon, null, size = 18.dp)
        Spacer(Modifier.width(8.dp))
        Text(text)
    }
}

/**
 * La barre d'un formulaire (une seule par page) : elle paraît dès qu'une valeur change, « Annuler » remet les valeurs
 * d'avant, « Enregistrer » envoie ce qui a changé. Ce qui n'est pas enregistré se perd en quittant la page. Pour une
 * création, [label] dit ce qu'elle crée, sans « Annuler » ([onCancel] nul : la flèche retour y suffit).
 */
@Composable
internal fun SaveBar(
    visible: Boolean,
    busy: Boolean,
    onCancel: (() -> Unit)?,
    onSave: () -> Unit,
    label: String = stringResource(R.string.settings_save),
    note: String = stringResource(R.string.settings_unsaved),
) {
    if (!visible) return
    Surface(color = MaterialTheme.colorScheme.surfaceContainer, tonalElevation = 3.dp, shadowElevation = 6.dp) {
        Row(
            Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(note, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
            if (onCancel != null) TextButton(onClick = onCancel, enabled = !busy) { Text(stringResource(R.string.cancel)) }
            Button(onClick = onSave, enabled = !busy) { Text(label) }
        }
    }
}

/** Une confirmation (se déconnecter, effacer, retirer) : [danger] la dit en rouge. */
@Composable
internal fun ConfirmDialog(title: String, text: String, confirm: String, onConfirm: () -> Unit, onDismiss: () -> Unit, danger: Boolean = false) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = { Text(text) },
        confirmButton = {
            TextButton(
                onClick = onConfirm,
                colors = if (danger) ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error) else ButtonDefaults.textButtonColors(),
            ) { Text(confirm) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

/** Copier un texte ; [sensitive] (une clé) : Android ne le montre pas dans son aperçu du presse-papiers. */
internal suspend fun copyText(clipboard: Clipboard, text: String, sensitive: Boolean = false) {
    val clip = ClipData.newPlainText("Mika", text)
    if (sensitive && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
        clip.description.extras = PersistableBundle().apply { putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true) }
    }
    clipboard.setClipEntry(ClipEntry(clip))
}

/** Une ligne de texte discret sous un groupe. */
@Composable
internal fun SetNote(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier.padding(horizontal = 28.dp, vertical = 8.dp),
    )
}
