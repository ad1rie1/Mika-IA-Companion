package fr.qwartz.mika.ui.phone

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.initials
import fr.qwartz.mika.data.moi.phone.AppKind
import fr.qwartz.mika.data.moi.phone.PhoneBar
import fr.qwartz.mika.data.moi.phone.PhoneDevices
import fr.qwartz.mika.data.moi.phone.PhoneMoiApi
import fr.qwartz.mika.data.moi.phone.appBadge
import fr.qwartz.mika.data.moi.phone.phoneBar
import fr.qwartz.mika.data.net.Topics
import fr.qwartz.mika.data.phone.PhoneApp
import fr.qwartz.mika.ui.Route
import fr.qwartz.mika.ui.shell.BarNav
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.LocalShell
import fr.qwartz.mika.ui.shell.MikaTopBar
import fr.qwartz.mika.ui.shell.PersonAvatar
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.launch

/*
 * Ce que les écrans du Téléphone partagent (ADR 0235, la maquette `ecrans/telephone.js`) : l'API, le sort d'un geste à
 * dire, l'état de tes téléphones dans la barre de titre (ADR 0233) et les onglets, la pastille d'une appli et le rond
 * d'une conversation, ouvrir l'appli d'une conversation.
 */

/** Le Téléphone sur l'API de ce téléphone. */
internal fun AppGraph.phoneApi(): PhoneMoiApi = PhoneMoiApi(moi)

/** Ce que tous les écrans du Téléphone ont : l'API, et le sort d'un geste à dire (l'écran le montre en toast). */
abstract class PhoneModel(protected val graph: AppGraph) : ViewModel() {
    protected val api = graph.phoneApi()
    private val notices = Channel<String>(Channel.BUFFERED)

    /** Le sort des gestes et des relectures demandées, une fois chacun. */
    val said: Flow<String> = notices.receiveAsFlow()

    protected fun say(text: String) {
        if (text.isNotBlank()) notices.trySend(text)
    }

    protected fun say(error: MoiError) = say(error.said)
}

/** Tes téléphones (`phone/phones`), pour la barre de titre des deux onglets ; relus avec l'écran, et quand le direct
 *  dit qu'ils ont changé (`phone.phones`, ADR 0308). */
class PhonesViewModel(graph: AppGraph) : PhoneModel(graph) {
    var phones by mutableStateOf<Load<PhoneDevices>>(Load.Loading)
        private set

    /** Le direct : relus sans bruit ; rend la main quand c'est relu. */
    suspend fun onLive(signal: LiveSignal) {
        if (signal.touches(Topics.PHONE_PHONES)) load().join()
    }

    fun load(): Job {
        return viewModelScope.launch {
            when (val got = api.phones()) {
                is MoiApi.Result.Ok -> phones = Load.Ready(got.value)
                // une relecture qui échoue garde ce qu'on savait ; la barre n'en dit rien de faux
                is MoiApi.Result.Failed -> if (phones !is Load.Ready) phones = Load.Failed(got.error)
            }
        }
    }

    /** L'état dans la barre ; `null` tant que la liste n'est pas lue. */
    fun bar(now: Long): PhoneBar? = phones.valueOrNull?.let { phoneBar(it.items, graph.deviceLabel, graph.auth.tokenId(), now) }
}

/** Les onglets du Téléphone : Messages et Position. Pas de Notifications tant que l'application ne lit que les
 *  messageries (ADR 0233) : une ancienne adresse retombe sur Messages. */
internal object PhoneTabs {
    const val MESSAGES = "messages"
    const val POSITION = "position"

    fun of(tab: String): String = if (tab == POSITION) POSITION else MESSAGES
}

/**
 * La barre du Téléphone : le titre, et dessous l'état de tes téléphones (lequel, vu quand, s'il reçoit les
 * notifications) — un état qui mène à Paramètres › Téléphones, pas un sélecteur (ADR 0233) ; puis les onglets, qui se
 * remplacent l'un l'autre sans s'empiler.
 */
@Composable
internal fun PhoneTopBar(bar: PhoneBar?, tab: String) {
    val shell = LocalShell.current
    Column {
        MikaTopBar(
            title = stringResource(R.string.nav_phone),
            nav = BarNav.DRAWER,
            subtitle = bar?.line,
            onTitle = { shell.navigate(Route.SettingsPage("telephones")) },
            titleIcon = R.drawable.ic_m_chev_right,
            titleDescription = bar?.description,
        )
        val tabs = listOf(PhoneTabs.MESSAGES to R.string.phone_tab_messages, PhoneTabs.POSITION to R.string.phone_tab_position)
        PrimaryTabRow(selectedTabIndex = tabs.indexOfFirst { it.first == tab }.coerceAtLeast(0)) {
            for ((id, label) in tabs) {
                Tab(
                    selected = id == tab,
                    onClick = { if (id != tab) shell.replace(Route.Phone(id)) },
                    text = { Text(stringResource(label)) },
                )
            }
        }
    }
}

/** Les teintes des applis (la feuille de la maquette : `.app-b.whatsapp`, `.app-b.messenger`, `.app-b.sms`). */
private val WHATSAPP = SolidColor(Color(0xFF25D366))
private val MESSAGES = SolidColor(Color(0xFF1A73E8))
/** Le dégradé de Messenger (ADR 0299) : son « M » ne se confond pas avec le « M » bleu de Messages. */
private val MESSENGER = Brush.linearGradient(listOf(Color(0xFF0099FF), Color(0xFFA033FF), Color(0xFFFF5280)))

/** La pastille d'une appli : sa couleur et sa lettre (W, M), son nom dit à l'accessibilité. */
@Composable
internal fun AppDot(app: String, appName: String, size: Dp = 18.dp) {
    val badge = appBadge(app, appName)
    val bg = when (badge.kind) {
        AppKind.WHATSAPP -> WHATSAPP
        AppKind.MESSENGER -> MESSENGER
        AppKind.MESSAGES -> MESSAGES
        AppKind.OTHER -> SolidColor(MaterialTheme.colorScheme.outline)
    }
    Box(
        Modifier
            .size(size)
            .border(2.dp, MaterialTheme.colorScheme.surface, CircleShape)
            .clip(CircleShape)
            .background(bg)
            .semantics { contentDescription = appName },
        contentAlignment = Alignment.Center,
    ) {
        Text(badge.letter, color = Color.White, fontWeight = FontWeight.Bold, fontSize = (size.value * 0.5f).sp, maxLines = 1)
    }
}

/** Le rond d'une conversation : la personne d'un tête-à-tête, un carré d'initiales pour un groupe, et au coin la
 *  pastille de son appli. */
@Composable
internal fun ConversationFace(title: String, group: Boolean, key: String, app: String, appName: String, size: Dp = 44.dp) {
    Box(Modifier.size(size + 4.dp)) {
        if (group) {
            val scheme = MaterialTheme.colorScheme
            Box(
                Modifier.size(size).clip(RoundedCornerShape(size * 0.3f)).background(scheme.secondaryContainer),
                contentAlignment = Alignment.Center,
            ) {
                val letters = initials(title.replace(Regex("""[^\p{L}\p{N}\s]"""), " "))
                Text(letters, color = scheme.onSecondaryContainer, fontWeight = FontWeight.SemiBold, fontSize = (size.value * 0.34f).sp)
            }
        } else {
            PersonAvatar(title.ifBlank { "?" }, title.ifBlank { key }, size)
        }
        Box(Modifier.align(Alignment.BottomEnd)) { AppDot(app, appName) }
    }
}

/** Le nom qu'une appli porte dans l'app (celui de ses notifications de propositions). */
internal fun appLabelRes(app: String): Int = when (PhoneApp.ofCode(app)) {
    PhoneApp.WHATSAPP -> R.string.phone_app_whatsapp
    PhoneApp.WHATSAPP_BUSINESS -> R.string.phone_app_whatsapp_business
    PhoneApp.MESSENGER -> R.string.phone_app_messenger
    else -> R.string.phone_app_messages
}

/** Le nom d'une appli : celui que dit le serveur, sinon (une ancienne réponse) celui que l'app lui donne. */
@Composable
internal fun appLabel(app: String, appName: String): String = appName.ifBlank { stringResource(appLabelRes(app)) }

/** Ouvrir l'appli d'une conversation (pour y coller ce qui vient d'être copié) ; `false` si elle n'est pas là. */
internal fun openApp(context: Context, app: String): Boolean {
    val pkg = PhoneApp.ofCode(app)?.packageName ?: return false
    val launch = context.packageManager.getLaunchIntentForPackage(pkg) ?: return false
    return try {
        context.startActivity(launch.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        true
    } catch (_: ActivityNotFoundException) {
        false
    } catch (_: SecurityException) {
        false
    }
}
