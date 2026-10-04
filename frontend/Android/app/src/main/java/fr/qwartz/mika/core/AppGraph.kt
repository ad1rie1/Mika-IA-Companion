package fr.qwartz.mika.core

import android.content.Context
import android.os.Build
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.preferencesDataStoreFile
import coil3.ImageLoader
import coil3.SingletonImageLoader
import coil3.disk.DiskCache
import coil3.memory.MemoryCache
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import coil3.request.crossfade
import fr.qwartz.mika.BuildConfig
import fr.qwartz.mika.data.auth.AndroidKeystoreCipher
import fr.qwartz.mika.data.auth.AuthApi
import fr.qwartz.mika.data.auth.AuthRepository
import fr.qwartz.mika.data.auth.SessionHooks
import fr.qwartz.mika.data.auth.TokenVault
import fr.qwartz.mika.data.chat.ChatEngine
import fr.qwartz.mika.data.chat.ChatRepository
import fr.qwartz.mika.data.db.ChatStore
import fr.qwartz.mika.data.db.Kv
import fr.qwartz.mika.data.db.MikaDatabase
import fr.qwartz.mika.data.files.AttachmentStager
import fr.qwartz.mika.data.files.DownloadStore
import fr.qwartz.mika.data.files.ImageCompressor
import fr.qwartz.mika.data.files.OutboxFiles
import fr.qwartz.mika.data.files.ShareInbox
import fr.qwartz.mika.data.mind.MindStateRepository
import fr.qwartz.mika.data.net.BearerInterceptor
import fr.qwartz.mika.data.net.OkHttpWsTransport
import fr.qwartz.mika.data.settings.SettingsStore
import fr.qwartz.mika.service.AndroidServiceController
import fr.qwartz.mika.service.ConnectionManager
import fr.qwartz.mika.service.MessageNotifier
import fr.qwartz.mika.service.ReplySender
import fr.qwartz.mika.service.ServiceController
import fr.qwartz.mika.share.Shortcuts
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okio.Path.Companion.toOkioPath
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Le graphe de l'app, à la main (pas de Hilt) : un objet par processus, créé par `MikaApp`.
 *
 * Tout l'état de la socket et du fil vit dans un seul contexte sérialisé ([engine]) : les rappels
 * d'OkHttp n'y font que poster, une trame est traitée jusqu'au bout avant la suivante.
 */
class AppGraph(context: Context) {
    /** Le contexte de l'application (jamais celui d'une activité : le graphe vit autant que le processus). */
    val context: Context = context.applicationContext
    val clock: Clock = AndroidClock
    val logger: Logger = AndroidLogger

    val engine: CoroutineDispatcher = Dispatchers.Default.limitedParallelism(1)
    val scope = CoroutineScope(
        SupervisorJob() + engine + CoroutineExceptionHandler { _, e -> logger.e(TAG, "coroutine en échec", e) },
    )

    /**
     * Complété quand la session est restaurée et la file d'envoi relue : un récepteur qui réveille le
     * processus (réponse depuis une notification, démarrage du téléphone) attend ce moment.
     */
    val ready = CompletableDeferred<Unit>()

    /** « Android · Google Pixel 8 » : ce que la console › Comptes montre de cet appareil. */
    val deviceLabel = "Android · ${Build.MANUFACTURER} ${Build.MODEL}".take(60)
    val userAgent = "Mika-Android/${BuildConfig.VERSION_NAME} (Android ${Build.VERSION.RELEASE}; ${Build.MODEL})"

    /** Les appels HTTP courts (connexion, whoami). */
    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .callTimeout(60, TimeUnit.SECONDS)
        .build()

    /** La socket : pas de délai de lecture (le battement applicatif juge du silence). */
    private val wsHttp: OkHttpClient = http.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .callTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    val database: MikaDatabase = MikaDatabase.open(this.context)
    val store = ChatStore(database)
    val files = OutboxFiles(this.context.filesDir)

    val foreground = AppForeground()
    val network = NetworkMonitor(this.context)

    val settings = SettingsStore(
        PreferenceDataStoreFactory.create(produceFile = { this.context.preferencesDataStoreFile("settings") }),
    )
    val tokenVault = TokenVault(
        PreferenceDataStoreFactory.create(produceFile = { this.context.preferencesDataStoreFile("auth") }),
        AndroidKeystoreCipher(),
    )
    val authApi = AuthApi(http)

    val chatEngine = ChatEngine(store, files, clock, scope, logger)
    val mind = MindStateRepository(store, clock)

    /** Ce qu'il faut encore effacer à la déconnexion (caches d'images, notifications…). */
    val onWipe: MutableList<suspend () -> Unit> = mutableListOf()

    private val hooks: SessionHooks = object : SessionHooks {
        override suspend fun beforeSignOut() {
            serviceController.stop()
            connection.shutdown()
        }

        override suspend fun wipeLocalData(keepDraft: Boolean) {
            connection.shutdown()
            chat.wipe(keepKeys = if (keepDraft) DRAFT_KEYS else emptySet(), keepStaging = keepDraft)
            for (wipe in onWipe) {
                try {
                    wipe()
                } catch (e: Exception) {
                    logger.w(TAG, "effacement incomplet", e)
                }
            }
        }

        override suspend fun localOwner(): String? = store.kvGet(Kv.OWNER)
        override suspend fun setLocalOwner(owner: String) = store.kvPut(Kv.OWNER, owner)
    }

    val auth: AuthRepository = AuthRepository(authApi, tokenVault, settings, hooks, clock, deviceLabel)

    val connection: ConnectionManager = ConnectionManager(
        scope = scope,
        engineContext = engine,
        auth = auth,
        chat = chatEngine,
        mind = mind,
        foreground = foreground.visible,
        network = network.status,
        clock = clock,
        transport = OkHttpWsTransport(wsHttp),
        userAgent = userAgent,
        logger = logger,
    )

    val chat: ChatRepository = ChatRepository(store, files, clock, engine, { connection.socket })

    /** Le client HTTP des fichiers de Mika : le jeton seulement vers son serveur. */
    val filesHttp: OkHttpClient by lazy {
        http.newBuilder()
            .addInterceptor(BearerInterceptor { auth.credentials()?.let { it.base to it.token } })
            .build()
    }

    val stager = AttachmentStager(this.context.contentResolver, files, ImageCompressor { files.staging }, logger)
    val downloads: DownloadStore by lazy { DownloadStore(this.context, filesHttp, { auth.credentials() }, logger) }
    val shareInbox = ShareInbox(store)

    /** Le service au premier plan (`MikaConnectionService`), d'après la session et les réglages. */
    @Volatile var serviceController: ServiceController = AndroidServiceController(this.context, scope, settings, auth.session, logger)

    val notifier = MessageNotifier(this.context, store, foreground.visible, { chatEngine.cursor }, clock::wallMs, logger)
    val replies = ReplySender(scope, chat, connection, notifier, settings, { serviceController }, logger)

    /** Les photos prises pour Mika, avant leur réduction (exposées par le FileProvider). */
    val cameraDir: File get() = File(context.cacheDir, "camera")

    init {
        onWipe += { notifier.wipe() }
        onWipe += { withContext(Dispatchers.IO) { downloads.clear() } }
        onWipe += { withContext(Dispatchers.IO) { cameraDir.deleteRecursively() } }
        onWipe += {
            // Les vignettes de Mika ne survivent pas à la session qui les a téléchargées.
            withContext(Dispatchers.IO) {
                val loader = SingletonImageLoader.get(context)
                loader.memoryCache?.clear()
                loader.diskCache?.clear()
            }
        }
    }

    /**
     * Le chargeur d'images de l'app (Coil) : le client authentifié, un cache disque de 100 Mo dans
     * `cacheDir/coil`, vidé à la déconnexion. Les réponses de `/files` disent `no-store`, mais la
     * stratégie par défaut de Coil 3 garde ce qu'elle a téléchargé : une vignette ne se recharge pas
     * à chaque défilement.
     */
    fun newImageLoader(context: Context): ImageLoader = ImageLoader.Builder(context)
        .components { add(OkHttpNetworkFetcherFactory(callFactory = { filesHttp })) }
        .diskCache {
            DiskCache.Builder()
                .directory(File(context.cacheDir, "coil").toOkioPath())
                .maxSizeBytes(100L * 1024 * 1024)
                .build()
        }
        .memoryCache { MemoryCache.Builder().maxSizePercent(context, 0.15).build() }
        .crossfade(true)
        .build()

    /**
     * « Effacer les messages de ce téléphone » : la conversation part (elle reste sur le serveur et
     * revient à la prochaine synchronisation, sans notification), la session et le brouillon restent.
     */
    suspend fun clearLocalMessages() {
        connection.clearThread {
            chat.wipe(keepKeys = DRAFT_KEYS + setOf(Kv.OWNER, Kv.MIND_STATE), keepStaging = true)
            notifier.wipe()
        }
    }

    fun start() {
        foreground.install()
        network.install()
        // Avant toute trame : une annonce émise sans abonné serait perdue.
        notifier.start(scope, chatEngine.events)
        scope.launch {
            try {
                chatEngine.init()
                mind.init()
                auth.restore()
                chat.restore()
                connection.start()
            } finally {
                ready.complete(Unit)
            }
            (serviceController as? AndroidServiceController)?.watch(foreground.visible)
        }
        scope.launch(Dispatchers.IO) { Shortcuts.publish(context) }
    }

    private companion object {
        const val TAG = "AppGraph"
        /** Ce qui attend dans la barre de saisie : gardé quand une session s'ouvre sur un autre compte. */
        val DRAFT_KEYS = setOf(Kv.DRAFT, Kv.SHARED_INBOX)
    }
}
