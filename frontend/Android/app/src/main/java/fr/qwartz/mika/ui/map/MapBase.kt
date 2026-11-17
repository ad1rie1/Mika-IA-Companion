package fr.qwartz.mika.ui.map

import android.content.Context
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import fr.qwartz.mika.BuildConfig
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.carte.Bounds
import fr.qwartz.mika.data.moi.carte.CarteApi
import fr.qwartz.mika.data.moi.carte.CarteStyle
import fr.qwartz.mika.data.moi.carte.FOND_TTL_MS
import fr.qwartz.mika.data.moi.carte.LatLon
import fr.qwartz.mika.data.moi.carte.LiveFailure
import fr.qwartz.mika.data.moi.carte.MapFond
import fr.qwartz.mika.data.moi.carte.MapHttp
import fr.qwartz.mika.ui.shell.rememberSessionKey
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.maplibre.android.MapLibre
import org.maplibre.android.module.http.HttpRequestUtil
import java.io.IOException

/*
 * Ce que toute carte de l'app partage (ADR 0193, 0235) : MapLibre, réglé une fois pour le processus — ses requêtes par
 * le client de la carte ([MapHttp] : ce serveur seul, avec le jeton), aucune clé, aucun service tiers, aucune tuile par
 * défaut ; le fond servi, lu pour toutes les cartes de la session et relu toutes les cinq minutes tant qu'une carte est
 * à l'écran ; les calques du style, lus une fois dans les assets ; et la poignée qu'un écran tient sur sa carte.
 */

/** MapLibre, réglé une fois pour le processus. */
internal object MapKit {
    @Volatile private var installed = false

    /**
     * MapLibre prêt à dessiner, ses requêtes par le client de la carte ; faux s'il ne se charge pas sur ce téléphone
     * (sa bibliothèque native absente ou refusée) : l'écran garde son plan.
     */
    fun install(context: Context, graph: AppGraph): Boolean = synchronized(this) {
        if (installed) return true
        try {
            MapLibre.getInstance(context.applicationContext)
            HttpRequestUtil.setOkHttpClient(MapHttp.client(graph.http) { graph.auth.credentials()?.let { it.base to it.token } })
            HttpRequestUtil.setLogEnabled(BuildConfig.DEBUG)
            HttpRequestUtil.setPrintRequestUrlOnFailure(false)
            installed = true
            true
        } catch (_: LinkageError) {
            false
        } catch (_: RuntimeException) {
            false
        }
    }
}

/** Les calques du style, tirés du web dans les assets (`tools/carte_style.mjs`), lus une fois par thème. */
internal object StyleAssets {
    private val cache = HashMap<Boolean, CarteStyle.Layers>()

    suspend fun load(context: Context, dark: Boolean): CarteStyle.Layers? {
        synchronized(cache) { cache[dark]?.let { return it } }
        val got = withContext(Dispatchers.IO) {
            try {
                context.assets.open(CarteStyle.asset(dark)).bufferedReader().use { CarteStyle.parse(it.readText()) }
            } catch (_: IOException) {
                null
            }
        } ?: return null
        synchronized(cache) { cache[dark] = got }
        return got
    }
}

/**
 * Le fond de toutes les cartes de la session (`GET /api/moi/carte/fond`) : lu à la première carte montrée, relu au plus
 * toutes les cinq minutes tant qu'une carte est à l'écran ; une relecture qui échoue garde ce qu'on savait. Ce qui ne
 * s'est pas dessiné n'est pas ici : chaque carte garde le sien ([LiveRefusal]).
 */
class MapFondViewModel(private val graph: AppGraph) : ViewModel() {
    private val api = CarteApi(graph.moi)

    var fond by mutableStateOf<MapFond?>(null)
        private set
    /** Pourquoi le fond ne se lit pas (rien de lu encore). */
    var error by mutableStateOf<MoiError?>(null)
        private set
    private var readAt = 0L
    private var job: Job? = null

    /** Lire le fond, s'il n'a pas été lu depuis cinq minutes ([force] : de suite). */
    fun load(force: Boolean = false) {
        val now = graph.clock.wallMs()
        if (!force && fond != null && now - readAt < FOND_TTL_MS) return
        if (job?.isActive == true) return
        job = viewModelScope.launch {
            when (val got = api.fond()) {
                is MoiApi.Result.Ok -> {
                    fond = got.value
                    error = null
                    readAt = graph.clock.wallMs()
                }
                is MoiApi.Result.Failed -> if (fond == null) error = got.error
            }
        }
    }
}

/**
 * Une carte qui ne s'est pas dessinée — ses tuiles en échec de suite, MapLibre qui ne se charge pas, son style — et
 * pourquoi, pour le fond qu'elle dessinait : le plan reprend sa place, sans réessayer, jusqu'à un autre fond servi. Une
 * par carte, comme le web (`live.ts` pour un écran, `minis.ts` pour une miniature) : un écran garde la sienne tant
 * qu'il est là (rouvert, il réessaie), une miniature la sienne dans sa liste ([MiniSlots.refusal]) ; l'échec de l'une
 * n'éteint pas les autres.
 */
@Stable
class LiveRefusal {
    private var failed by mutableStateOf<Pair<MapFond, LiveFailure>?>(null)

    /** Pourquoi elle ne se dessine pas, pour ce fond (rien : elle le peut ; un autre fond servi : elle réessaie). */
    fun failure(of: MapFond?): LiveFailure? = failed?.takeIf { of != null && it.first == of }?.second

    /** Elle ne se dessine pas, pour ce fond : le plan reprend sa place. */
    fun fail(of: MapFond, why: LiveFailure) {
        failed = of to why
    }
}

/** Le fond de la session, relu toutes les cinq minutes tant que l'écran qui l'appelle est au premier plan. */
@Composable
internal fun rememberMapFond(graph: AppGraph): MapFondViewModel {
    val session = rememberSessionKey(graph)
    val vm: MapFondViewModel = viewModel(key = "map.fond|$session") { MapFondViewModel(graph) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(vm, lifecycle) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.RESUMED) {
            while (true) {
                vm.load()
                delay(FOND_TTL_MS)
            }
        }
    }
    return vm
}

/**
 * La poignée qu'un écran tient sur sa carte : la recadrer sur sa scène ([fit], même inchangée : un cadrage demandé ne se
 * perd pas), lire ce qu'elle montre ([frame], la part que rien ne couvre), savoir si la vraie carte est là ([live]).
 */
@Stable
class MapControl {
    /** Change à chaque cadrage demandé. */
    var fitToken by mutableIntStateOf(0)
        private set
    /** Le dernier cadrage demandé, sur une scène vide : le fond de carte (sa zone, sinon la France). */
    var fitOrBase = false
        private set
    /** Un point à amener à l'écran (un lieu choisi dans la liste), et son jeton. */
    var focus by mutableStateOf<Pair<Int, LatLon>?>(null)
        private set
    /** La vraie carte est à l'écran (sinon le plan). */
    var live by mutableStateOf(false)
        internal set
    internal var frameReader: (() -> Bounds?)? = null

    fun fit(orBase: Boolean = false) {
        fitOrBase = orBase
        fitToken += 1
    }

    /** Amener ce point à l'écran, s'il n'y est pas déjà (au même zoom). */
    fun show(point: LatLon) {
        focus = (focus?.first ?: 0) + 1 to point
    }

    /** Ce que la vraie carte montre, sans ce que la recherche et la feuille couvrent ; sans carte, `null`. */
    fun frame(): Bounds? = frameReader?.invoke()
}
