package fr.qwartz.mika.ui.carte

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import coil3.ImageLoader
import coil3.compose.AsyncImage
import coil3.compose.LocalPlatformContext
import coil3.disk.DiskCache
import coil3.memory.MemoryCache
import coil3.network.CacheStrategy
import coil3.network.NetworkRequest
import coil3.network.NetworkResponse
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.ImageRequest
import coil3.request.Options
import coil3.request.crossfade
import fr.qwartz.mika.R
import fr.qwartz.mika.core.AppGraph
import fr.qwartz.mika.data.moi.carte.CarteApi
import fr.qwartz.mika.data.moi.carte.LinkText
import fr.qwartz.mika.data.moi.carte.MapHttp
import fr.qwartz.mika.data.moi.carte.Photo
import fr.qwartz.mika.data.moi.carte.Scene
import fr.qwartz.mika.data.moi.carte.bandCredit
import fr.qwartz.mika.data.moi.carte.photoAlt
import fr.qwartz.mika.data.moi.carte.photoCount
import fr.qwartz.mika.data.moi.carte.photoCredit
import fr.qwartz.mika.data.moi.carte.photoFresh
import fr.qwartz.mika.data.moi.carte.photoMemoryKey
import fr.qwartz.mika.data.moi.carte.photoSource
import fr.qwartz.mika.data.moi.carte.photoWhy
import fr.qwartz.mika.ui.map.ScenePlan
import fr.qwartz.mika.ui.shell.MIcon
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okio.Path.Companion.toOkioPath
import java.io.File

/*
 * Les photos de la Carte (ADR 0259) : celles qu'un lieu ou un événement porte (l'office de tourisme, Google Maps),
 * relayées par ce serveur seul. Leur adresse se refait depuis leur référence (`CarteApi.photoUrl`), et le chargeur
 * qui les lit ([CartePhotos]) ne parle qu'au serveur de la session, avec le jeton du téléphone, sans suivre une
 * redirection : le client de la carte ([MapHttp]). Une photo ne se demande que quand elle paraît (une liste, une bande
 * qui défile : seules les lignes à l'écran se composent) — la première relève d'une photo de Google coûte un appel
 * compté —, et se garde ensuite le temps que le serveur dit (`private, max-age=86400` : [MaxAgeCacheStrategy], R2-A08),
 * en mémoire une heure au plus sans repasser par le disque ([photoMemoryKey], R3-11).
 * Chaque photo montre sa source, son crédit et sa licence, sur elle ; une vignette de liste, son crédit sous la ligne ;
 * la visionneuse, sa légende, son auteur (lié), sa licence.
 */

/**
 * Le cache disque des photos suit l'âge que le serveur leur donne (R2-A08) : la stratégie de Coil 3 par défaut ressert
 * ce qu'elle a gardé sans jamais lire `Cache-Control` — une photo dont les droits ont pris fin (le serveur répond 404)
 * resterait visible jusqu'à la déconnexion. Passé son `max-age` ([photoFresh]), elle se redemande ; ce qu'on garde
 * s'écrit comme Coil l'écrit d'habitude.
 */
internal class MaxAgeCacheStrategy(private val now: () -> Long = System::currentTimeMillis) : CacheStrategy {
    override suspend fun read(cacheResponse: NetworkResponse, networkRequest: NetworkRequest, options: Options): CacheStrategy.ReadResult =
        if (photoFresh(cacheResponse.headers["Cache-Control"], cacheResponse.responseMillis, now())) {
            CacheStrategy.ReadResult(cacheResponse)
        } else {
            CacheStrategy.ReadResult(networkRequest)
        }

    override suspend fun write(
        cacheResponse: NetworkResponse?,
        networkRequest: NetworkRequest,
        networkResponse: NetworkResponse,
        options: Options,
    ): CacheStrategy.WriteResult = CacheStrategy.DEFAULT.write(cacheResponse, networkRequest, networkResponse, options)
}

/** Le chargeur des photos de la Carte, un pour le processus ; son cache part avec la session. */
internal object CartePhotos {
    @Volatile private var loader: ImageLoader? = null

    fun loader(graph: AppGraph): ImageLoader = loader ?: synchronized(this) {
        loader ?: build(graph).also { built ->
            loader = built
            // comme les vignettes de Mika : ce qu'une session a vu ne reste pas à la suivante
            graph.onWipe += {
                withContext(Dispatchers.IO) {
                    built.memoryCache?.clear()
                    built.diskCache?.clear()
                }
            }
        }
    }

    private fun build(graph: AppGraph): ImageLoader {
        val client = MapHttp.client(graph.http) { graph.auth.credentials()?.let { it.base to it.token } }
        return ImageLoader.Builder(graph.context)
            .components { add(OkHttpNetworkFetcherFactory(callFactory = { client }, cacheStrategy = { MaxAgeCacheStrategy() })) }
            .diskCache {
                DiskCache.Builder()
                    .directory(File(graph.context.cacheDir, "carte-photos").toOkioPath())
                    .maxSizeBytes(50L * 1024 * 1024)
                    .build()
            }
            .memoryCache { MemoryCache.Builder().maxSizePercent(graph.context, 0.10).build() }
            .crossfade(true)
            .build()
    }
}

/**
 * Ce que le chargeur demande pour une photo relayée ([ref], `p:<hash>`) — `null` pour une autre forme : son adresse sur
 * ce serveur, et sa clé au cache mémoire, qui change chaque heure ([photoMemoryKey], R3-11) : passé ce temps, elle
 * repasse par le disque (son `max-age`), puis par le serveur.
 */
@Composable
private fun rememberPhotoRequest(graph: AppGraph, ref: String): ImageRequest? {
    val context = LocalPlatformContext.current
    return remember(ref, graph, context) {
        CarteApi(graph.moi).photoUrl(ref)?.toString()?.let { url ->
            ImageRequest.Builder(context).data(url).memoryCacheKey(photoMemoryKey(url, graph.clock.wallMs())).build()
        }
    }
}

/**
 * Une photo relayée par ce serveur, refaite depuis sa référence ([ref], `p:<hash>`) ; une autre forme ne se demande pas.
 * Sous elle, tant qu'elle n'est pas là (ou en échec), l'icône d'une image.
 */
@Composable
internal fun PhotoImage(graph: AppGraph, ref: String, description: String?, modifier: Modifier = Modifier, contentScale: ContentScale = ContentScale.Crop) {
    val request = rememberPhotoRequest(graph, ref)
    val scheme = MaterialTheme.colorScheme
    Box(modifier.background(scheme.surfaceContainerHigh), contentAlignment = Alignment.Center) {
        MIcon(R.drawable.ic_m_image, null, size = 24.dp, tint = scheme.onSurfaceVariant)
        if (request != null) {
            AsyncImage(
                model = request,
                contentDescription = description,
                imageLoader = CartePhotos.loader(graph),
                contentScale = contentScale,
                modifier = Modifier.matchParentSize(),
            )
        }
    }
}

/** La hauteur de la bande du haut d'une fiche (la maquette : 160). */
private val BAND = 160.dp

/** Une étiquette sur une photo (sa source, le plan, le compte) : du blanc sur un voile sombre. */
@Composable
private fun OnPhoto(text: String, modifier: Modifier = Modifier, icon: Int? = null) {
    Row(
        modifier.clip(RoundedCornerShape(6.dp)).background(Color.Black.copy(alpha = 0.58f)).padding(horizontal = 6.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (icon != null) {
            MIcon(icon, null, size = 12.dp, tint = Color.White)
            Spacer(Modifier.width(4.dp))
        }
        Text(text, style = MaterialTheme.typography.labelSmall, fontWeight = FontWeight.SemiBold, color = Color.White, maxLines = 1)
    }
}

/**
 * La bande du haut d'une fiche (`bande` de la maquette) : le plan d'abord (le lieu, et toi si on sait où tu es ; le compte
 * des photos dessus, qui défile avec lui : fixe, il passait sur la source des tuiles, R2-A05), puis les photos, chacune
 * avec sa source, son crédit (lié à son auteur) et sa licence ; une photo touchée s'ouvre dans la visionneuse. Sans
 * photo, le plan seul, sur toute la largeur.
 */
@Composable
internal fun PhotoBand(
    graph: AppGraph,
    scene: Scene,
    title: String,
    photos: List<Photo>,
    outside: Outside,
    onPhoto: (Int) -> Unit,
    modifier: Modifier = Modifier,
) {
    val planLabel = stringResource(R.string.fiche_plan)
    Box(modifier.fillMaxWidth().height(BAND)) {
        LazyRow(
            Modifier.fillMaxSize(),
            horizontalArrangement = Arrangement.spacedBy(4.dp),
            contentPadding = PaddingValues(0.dp),
        ) {
            item("plan") {
                Box(if (photos.isEmpty()) Modifier.fillParentMaxWidth().fillMaxHeight() else Modifier.width(150.dp).fillMaxHeight()) {
                    ScenePlan(scene, title, "", Modifier.fillMaxSize(), note = false)
                    OnPhoto(planLabel, Modifier.align(Alignment.TopStart).padding(6.dp), icon = R.drawable.ic_m_map)
                    // combien de photos : sur le plan, en bas (`.ph-count` du web, dans sa tuile du plan)
                    if (photos.size > 1) OnPhoto(photoCount(photos.size), Modifier.align(Alignment.BottomEnd).padding(6.dp), icon = R.drawable.ic_m_image)
                }
            }
            itemsIndexed(photos, key = { _, p -> p.ref }) { i, p ->
                PhotoTile(graph, p, i, outside, Modifier.width(230.dp).fillMaxHeight()) { onPhoto(i) }
            }
        }
    }
}

/** Une photo de la bande : elle-même, sa source en haut, son crédit en bas (lié à son auteur), puis sa licence. */
@Composable
private fun PhotoTile(graph: AppGraph, p: Photo, i: Int, outside: Outside, modifier: Modifier, onClick: () -> Unit) {
    val alt = photoAlt(p, i)
    val open = stringResource(R.string.fiche_photo_open, alt)
    Box(modifier.clickable(role = Role.Image, onClick = onClick).semantics { contentDescription = open }) {
        PhotoImage(graph, p.ref, null, Modifier.fillMaxSize())
        OnPhoto(photoSource(p), Modifier.align(Alignment.TopStart).padding(6.dp))
        val credit = bandCredit(p)
        if (credit.isNotEmpty()) {
            Box(
                Modifier.align(Alignment.BottomStart).fillMaxWidth()
                    .background(Brush.verticalGradient(listOf(Color.Transparent, Color.Black.copy(alpha = 0.62f))))
                    .padding(start = 8.dp, end = 8.dp, top = 14.dp, bottom = 5.dp),
            ) {
                val text = remember(credit) { linkedParts(credit, Color.White, outside) }
                Text(text, style = MaterialTheme.typography.labelSmall, color = Color.White, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

/**
 * Le crédit d'une vignette de liste, sous sa ligne (R2-A01) : « Photo : Camille R. · Google Maps », l'auteur lié ;
 * « Photo : Hello Lille · CC BY-NC-ND 4.0 · Office de tourisme ». Lisible, pas seulement pour un lecteur d'écran.
 */
@Composable
internal fun ThumbCredit(thumb: Photo, modifier: Modifier = Modifier) {
    val outside = rememberOutside()
    val scheme = MaterialTheme.colorScheme
    val credit = photoCredit(thumb)
    val parts = listOfNotNull(
        credit.author?.let { it.copy(text = "Photo : ${it.text}") },
        credit.licence.takeIf { it.isNotEmpty() }?.let { LinkText(it) },
        LinkText(credit.source),
    )
    val text = remember(parts, scheme.primary) { linkedParts(parts, scheme.primary, outside) }
    Text(text, style = MaterialTheme.typography.labelSmall, color = scheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = modifier)
}

/**
 * La visionneuse (`photo` de la maquette) : une photo en grand, sa légende, son auteur (lié), sa licence, d'où elle
 * vient et ce qu'on en garde, sa place dans la série ; on glisse de l'une à l'autre, ou « précédente », « suivante ».
 * Seule la photo montrée se demande.
 */
@Composable
internal fun PhotoViewer(graph: AppGraph, photos: List<Photo>, start: Int, outside: Outside, onDismiss: () -> Unit) {
    if (photos.isEmpty()) return
    val pager = rememberPagerState(initialPage = start.coerceIn(0, photos.size - 1)) { photos.size }
    val scope = rememberCoroutineScope()
    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Column(Modifier.fillMaxSize().background(Color.Black).statusBarsPadding().navigationBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(4.dp), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onDismiss) { MIcon(R.drawable.ic_m_x, stringResource(R.string.fiche_viewer_close), tint = Color.White) }
                Text(stringResource(R.string.fiche_viewer_title), style = MaterialTheme.typography.titleMedium, color = Color.White, modifier = Modifier.weight(1f))
                if (photos.size > 1) {
                    Text("${pager.currentPage + 1} / ${photos.size}", style = MaterialTheme.typography.labelLarge, color = Color.White.copy(alpha = 0.8f))
                    Spacer(Modifier.width(12.dp))
                }
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                HorizontalPager(state = pager, modifier = Modifier.fillMaxSize(), key = { photos[it].ref }) { page ->
                    val p = photos[page]
                    var failed by remember(p.ref) { mutableStateOf(false) }
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        if (failed) {
                            Text(stringResource(R.string.fiche_photo_failed), color = Color.White.copy(alpha = 0.7f), style = MaterialTheme.typography.bodyMedium)
                        }
                        val request = rememberPhotoRequest(graph, p.ref)
                        if (request != null) {
                            AsyncImage(
                                model = request,
                                contentDescription = photoAlt(p, page),
                                imageLoader = CartePhotos.loader(graph),
                                contentScale = ContentScale.Fit,
                                onError = { failed = true },
                                modifier = Modifier.fillMaxSize(),
                            )
                        }
                    }
                }
                if (photos.size > 1) {
                    IconButton(
                        onClick = { scope.launch { pager.animateScrollToPage((pager.currentPage - 1).mod(photos.size)) } },
                        modifier = Modifier.align(Alignment.CenterStart),
                    ) { MIcon(R.drawable.ic_m_chev_left, stringResource(R.string.fiche_viewer_prev), tint = Color.White) }
                    IconButton(
                        onClick = { scope.launch { pager.animateScrollToPage((pager.currentPage + 1).mod(photos.size)) } },
                        modifier = Modifier.align(Alignment.CenterEnd),
                    ) { MIcon(R.drawable.ic_m_chev_right, stringResource(R.string.fiche_viewer_next), tint = Color.White) }
                }
            }
            val p = photos[pager.currentPage.coerceIn(0, photos.size - 1)]
            val credit = photoCredit(p)
            Column(Modifier.fillMaxWidth().widthIn(max = 640.dp).padding(horizontal = 16.dp, vertical = 12.dp)) {
                if (p.caption.isNotBlank()) {
                    Text(p.caption.trim(), style = MaterialTheme.typography.bodyLarge, color = Color.White, maxLines = 3, overflow = TextOverflow.Ellipsis)
                    Spacer(Modifier.height(4.dp))
                }
                val parts = listOfNotNull(
                    credit.author?.let { it.copy(text = "Photo : ${it.text}") },
                    credit.licence.takeIf { it.isNotEmpty() }?.let { LinkText(it) },
                    LinkText(credit.source),
                )
                val linked = remember(parts) { linkedParts(parts, Color(0xFFB8C3FF), outside) }
                Text(linked, style = MaterialTheme.typography.bodySmall, color = Color.White)
                Text(photoWhy(p), style = MaterialTheme.typography.bodySmall, color = Color.White.copy(alpha = 0.7f), modifier = Modifier.padding(top = 2.dp))
            }
        }
    }
}
