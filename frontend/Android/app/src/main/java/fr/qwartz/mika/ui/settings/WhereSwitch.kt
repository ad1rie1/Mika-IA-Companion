package fr.qwartz.mika.ui.settings

import android.Manifest
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.core.LocationMonitor
import fr.qwartz.mika.data.settings.Settings as AppSettings
import kotlinx.coroutines.launch

/**
 * « Lui dire où je suis » (ADR 0119) tel que tout écran le montre — Paramètres, et la Position du Téléphone : le
 * réglage et l'autorisation de localisation ensemble. [checked] : allumé et permis ; [revoked] : allumé mais
 * l'autorisation retirée dans les réglages du téléphone (rien ne part) ; [refused] : refusée, Android ne redemande plus,
 * seuls ses réglages peuvent la donner ([openSettings]).
 */
class WhereSwitch(
    val checked: Boolean,
    val revoked: Boolean,
    val refused: Boolean,
    /** Couper ; allumer, en demandant l'autorisation s'il le faut (précise ou approximative : l'une suffit). */
    val onChange: (Boolean) -> Unit,
    val openSettings: () -> Unit,
)

/** L'interrupteur et sa demande d'autorisation, revue à chaque retour sur l'écran (elle se retire ailleurs). */
@Composable
fun rememberWhereSwitch(graph: AppGraph): WhereSwitch {
    val settings by graph.settings.settings.collectAsStateWithLifecycle(AppSettings())
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    // La localisation peut être retirée (ou donnée) dans les réglages du téléphone : revue à chaque retour.
    var granted by remember { mutableStateOf(LocationMonitor.permitted(context)) }
    var refused by rememberSaveable { mutableStateOf(false) }
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) {
        granted = LocationMonitor.permitted(context)
        if (granted) refused = false
    }
    // Précise ou approximative (Android 12 et plus laisse choisir) : l'une ou l'autre suffit pour l'allumer.
    val ask = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        granted = result.values.any { it } || LocationMonitor.permitted(context)
        refused = !granted
        if (granted) scope.launch { graph.settings.setShareWhere(true) }
    }
    return WhereSwitch(
        checked = settings.shareWhere && granted,
        revoked = settings.shareWhere && !granted,
        refused = refused && !granted,
        onChange = { on ->
            when {
                !on -> scope.launch { graph.settings.setShareWhere(false) }
                granted -> scope.launch { graph.settings.setShareWhere(true) }
                else -> ask.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
            }
        },
        openSettings = { openAppSettings(context) },
    )
}

/** La fiche de l'app dans les réglages du téléphone, où se donnent les autorisations qu'Android ne redemande plus. */
internal fun openAppSettings(context: Context) {
    val intent = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null))
    try {
        context.startActivity(intent)
    } catch (_: ActivityNotFoundException) {
    }
}
