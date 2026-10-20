package fr.qwartz.mika.core

import android.app.Notification
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
import fr.qwartz.mika.data.approvals.ApprovalsRepository
import fr.qwartz.mika.data.auth.AndroidKeystoreCipher
import fr.qwartz.mika.data.auth.AuthApi
import fr.qwartz.mika.data.auth.AuthRepository
import fr.qwartz.mika.data.auth.Session
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
import fr.qwartz.mika.data.location.WhereShare
import fr.qwartz.mika.data.mind.MindStateRepository
import fr.qwartz.mika.data.net.BearerInterceptor
import fr.qwartz.mika.data.net.LinkState
import fr.qwartz.mika.data.net.OkHttpWsTransport
import fr.qwartz.mika.data.phone.PhoneApi
import fr.qwartz.mika.data.phone.PhoneKv
import fr.qwartz.mika.data.phone.PhoneOutbox
import fr.qwartz.mika.data.phone.PhoneReading
import fr.qwartz.mika.data.phone.PostedNotification
import fr.qwartz.mika.data.phone.ReplyRegistry
import fr.qwartz.mika.data.push.PushPayload
import fr.qwartz.mika.data.push.PushRegistrar
import fr.qwartz.mika.data.settings.SettingsStore
import fr.qwartz.mika.push.FirebasePush
import fr.qwartz.mika.service.AndroidServiceController
import fr.qwartz.mika.service.ConnectionManager
import fr.qwartz.mika.service.MessageNotifier
import fr.qwartz.mika.service.PhoneDraftNotifier
import fr.qwartz.mika.service.PhoneListenerService
import fr.qwartz.mika.service.ReplySender
import fr.qwartz.mika.service.ServiceController
import fr.qwartz.mika.share.Shortcuts
import fr.qwartz.mika.ui.avatar.AvatarAssets
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineDispatcher
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.flow.map
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
     * processus (réponse depuis une notification, message Firebase) attend ce moment.
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

    /**
     * La socket : pas de délai de lecture (le battement applicatif juge du silence), mais un délai
     * d'écriture, par tranche de 64 Kio — c'est lui qui ferme une montée bloquée, que le battement ne
     * juge pas tant que la file d'OkHttp porte des octets (`MikaSocket.lastSignOfLife`). Un délai global
     * borne l'ouverture : sans lui, une réponse 101 qui ne vient jamais (serveur figé derrière un noyau qui
     * accepte, chemin mort après la connexion TCP) laisse « Connexion… » sans fin, puisque le battement
     * n'est armé qu'à l'ouverture. OkHttp le lève dès la montée en WebSocket : il ne coupe jamais une
     * socket ouverte.
     */
    private val wsHttp: OkHttpClient = http.newBuilder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .build()

    val database: MikaDatabase = MikaDatabase.open(this.context)
    val store = ChatStore(database)
    val files = OutboxFiles(this.context.filesDir)

    val foreground = AppForeground()
    val network = NetworkMonitor(this.context)
    /** La position du téléphone, écoutée seulement app au premier plan et si elle le permet (ADR 0119). */
    val location = LocationMonitor(this.context, clock, logger)

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
    /** Les cartes d'accord (ADR 0064) : en mémoire, le temps de la socket qui les a reçues. */
    val approvals = ApprovalsRepository(clock)

    /** Ses portraits, s'ils ont été rendus dans les assets (`portraits.py`). */
    val avatar = AvatarAssets(this.context, logger)

    /** Ce qu'il faut encore effacer à la déconnexion (caches d'images, notifications…). */
    val onWipe: MutableList<suspend () -> Unit> = mutableListOf()

    private val hooks: SessionHooks = object : SessionHooks {
        override suspend fun beforeSignOut() {
            serviceController.stop()
            connection.shutdown()
            // Le jeton Firebase et la clé des notifications partent avec la session (le serveur oublie le
            // téléphone avec son jeton rendu) : plus rien n'arrive ici d'une session close.
            push.forget()
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

    val chat: ChatRepository = ChatRepository(store, files, clock, engine, { connection.socket })

    val connection: ConnectionManager = ConnectionManager(
        scope = scope,
        engineContext = engine,
        auth = auth,
        chat = chatEngine,
        mind = mind,
        approvals = approvals,
        foreground = foreground.visible,
        network = network.status,
        clock = clock,
        transport = OkHttpWsTransport(wsHttp),
        userAgent = userAgent,
        logger = logger,
        // « Lui dire quand j'ai lu » : le fil à l'écran, « Marquer comme lu » — seulement si elle le permet
        reads = combine(settings.settings.map { it.shareReads }, chat.observeLastReadId()) { on, id ->
            id.takeIf { on }
        },
        // « Lui dire où je suis » (ADR 0119) : au premier plan seulement — pas tant que la socket est ouverte, car elle
        // le reste 30 s après le départ, et s'ouvre en arrière-plan pour une réponse depuis une notification
        wheres = WhereShare.follow(
            sharing = settings.settings.map { it.shareWhere }.distinctUntilChanged(),
            visible = foreground.visible,
            fixes = location::fixes,
        ),
    )

    /**
     * Le client HTTP des fichiers de Mika : le jeton seulement vers son serveur. Pas de délai global :
     * un fichier va jusqu'à `MikaProtocol.MAX_SHARE_BYTES`, et 60 s n'en portent pas 10 Mio sur une 4G
     * faible — chaque essai repartait de zéro et échouait pareil. Le délai par lecture (30 s, hérité)
     * suffit à juger une liaison morte.
     */
    val filesHttp: OkHttpClient by lazy {
        http.newBuilder()
            .callTimeout(0, TimeUnit.MILLISECONDS)
            .addInterceptor(BearerInterceptor { auth.credentials()?.let { it.base to it.token } })
            .build()
    }

    val stager = AttachmentStager(this.context.contentResolver, files, ImageCompressor { files.staging }, logger)
    val downloads: DownloadStore by lazy { DownloadStore(this.context, filesHttp, { auth.credentials() }, logger) }
    val shareInbox = ShareInbox(store)

    /** Le service au premier plan (`MikaConnectionService`), le temps d'une réponse partie d'une notification. */
    @Volatile var serviceController: ServiceController = AndroidServiceController(this.context, logger)

    val notifier = MessageNotifier(this.context, store, foreground.visible, { chatEngine.cursor }, clock::wallMs, logger)
    val replies = ReplySender(scope, chat, connection, notifier, { serviceController }, logger)

    /** Les notifications app fermée (ADR 0077) : où les recevoir, dit au serveur, et la clé qui les ouvre. */
    val push = PushRegistrar(
        port = FirebasePush(this.context),
        api = authApi,
        keys = TokenVault(
            PreferenceDataStoreFactory.create(produceFile = { this.context.preferencesDataStoreFile("push") }),
            AndroidKeystoreCipher(),
            name = TokenVault.PUSH_KEY_NAME,
            aad = TokenVault.PUSH_KEY_AAD,
            forgetKeyWhenUnreadable = false,
        ),
        settings = settings,
        credentials = { auth.credentials() },
        clock = clock,
        logger = logger,
    )

    /**
     * Un message Firebase, ouvert avec la clé de ce téléphone (hors session : rien) : une parole se montre comme une
     * parole reçue ; une réponse proposée pour WhatsApp ou Messages (ADR 0120), comme une demande d'autorisation.
     */
    suspend fun onPushed(data: Map<String, String>) {
        val key = push.key() ?: return
        when (val pushed = PushPayload.open(key, data)) {
            null -> logger.w(TAG, "message Firebase illisible : ignoré")
            is PushPayload.Pushed.Speech ->
                notifier.onPushed(pushed.message, online = connection.link.value == LinkState.Online)
            is PushPayload.Pushed.Draft -> phoneDrafts.onDraft(pushed.draft)
        }
    }

    /**
     * « Lui montrer mes messages » (ADR 0120) : les messages lus sur le téléphone attendent ici le serveur, dans une file
     * gardée en base (en 4G, le serveur de la maison ne répond pas). Un appel court par lot, jamais une connexion
     * gardée (ADR 0077) : un délai de connexion plus court que celui d'une connexion voulue, car c'est en 4G qu'il
     * échoue le plus.
     */
    private val phoneKv = object : PhoneKv {
        override suspend fun get(key: String): String? = store.kvGet(key)
        override suspend fun put(key: String, value: String?) = store.kvPut(key, value)
    }
    val phone = PhoneOutbox(
        kv = phoneKv,
        api = PhoneApi(
            http.newBuilder()
                .connectTimeout(10, TimeUnit.SECONDS)
                .callTimeout(30, TimeUnit.SECONDS)
                .build(),
        ),
        credentials = { auth.credentials() },
        enabled = { settings.current().phoneShare },
        online = { network.status.value.available },
        clock = clock,
        scope = scope,
        logger = logger,
    )

    /** L'action « Répondre » de chaque conversation du téléphone, en mémoire seulement (ADR 0120). */
    val phoneReplies = ReplyRegistry<Notification.Action>()

    /** Les réponses que Mika propose pour WhatsApp ou Messages, et le geste qui les autorise (ADR 0120). */
    val phoneDrafts = PhoneDraftNotifier(
        context = this.context,
        kv = phoneKv,
        replies = phoneReplies,
        outbox = phone,
        enabled = { settings.current().phoneShare },
        clock = clock::wallMs,
        logger = logger,
    )

    /**
     * Une notification de WhatsApp ou de Messages, décrite par le lecteur (`PhoneListenerService`) : triée selon les
     * réglages, son action « Répondre » gardée, ses messages neufs en file, puis envoyés bientôt.
     */
    suspend fun onPhoneNotification(posted: PostedNotification, reply: Notification.Action?) {
        if (auth.credentials() == null) return
        val reading = PhoneReading.read(posted, settings.current().phone) ?: return
        if (reply != null) phoneReplies.put(reading.thread, reply)
        if (phone.add(reading.messages) > 0) phone.flushSoon()
    }

    /** Les photos prises pour Mika, avant leur réduction (exposées par le FileProvider). */
    val cameraDir: File get() = File(context.cacheDir, "camera")

    init {
        onWipe += { notifier.wipe() }
        // La file des messages du téléphone et les propositions partent avec la session (la table kv est déjà vide) :
        // un autre compte n'en hérite jamais, et aucune réponse ne part plus par une action gardée d'avant.
        onWipe += {
            phone.clear()
            phoneReplies.clear()
            phoneDrafts.wipe()
        }
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
            // La file des messages du téléphone et les propositions (ADR 0120) ne sont pas la conversation : elles restent.
            chat.wipe(
                keepKeys = DRAFT_KEYS + setOf(Kv.OWNER, Kv.MIND_STATE, Kv.LAST_SEEN_WALL, Kv.PHONE_QUEUE, Kv.PHONE_DRAFTS),
                keepStaging = true,
            )
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
            // App ouverte, session ouverte (une connexion, ou le retour à l'écran) : dire au serveur où notifier ce
            // téléphone fermé, si besoin. Jamais app fermée : en 4G, un serveur de la maison ne répond pas.
            combine(foreground.visible, auth.session) { visible, session -> visible && session is Session.LoggedIn }
                .distinctUntilChanged()
                .filter { it }
                .collect {
                    // Une inscription en échec (base des réglages illisible…) n'arrête pas celles des ouvertures suivantes.
                    try {
                        push.sync()
                    } catch (e: CancellationException) {
                        throw e
                    } catch (e: Exception) {
                        logger.w(TAG, "inscription aux notifications en échec", e)
                    }
                }
        }
        scope.launch(Dispatchers.IO) { Shortcuts.publish(context) }
        startPhone()
    }

    /**
     * « Lui montrer mes messages » (ADR 0120). Coupé : la file se vide, les actions gardées et les propositions partent ;
     * allumé : Android rebranche le lecteur qu'il avait débranché à sa demande. Ce qui attend repart au retour du réseau
     * et quand l'app passe au premier plan — sans attendre la fin d'une attente d'après un échec ; jamais en boucle.
     */
    private fun startPhone() {
        scope.launch {
            ready.await()
            phone.init()
            phoneDrafts.prune()
            settings.settings.map { it.phoneShare }.distinctUntilChanged().collect { on ->
                if (on) {
                    PhoneListenerService.rebind(context)
                } else {
                    phone.clear()
                    phoneReplies.clear()
                    phoneDrafts.wipe()
                }
            }
        }
        scope.launch {
            ready.await()
            network.status.map { it.available to it.networkId }
                .distinctUntilChanged()
                .filter { (available, _) -> available }
                .collect { flushPhone(PhoneOutbox.Trigger.NETWORK) }
        }
        scope.launch {
            ready.await()
            foreground.visible.filter { it }.collect { flushPhone(PhoneOutbox.Trigger.FOREGROUND) }
        }
    }

    /** Un envoi en échec (base illisible…) n'arrête pas ceux des déclencheurs suivants. */
    private suspend fun flushPhone(trigger: PhoneOutbox.Trigger) {
        try {
            phone.flush(trigger)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logger.w(TAG, "envoi des messages du téléphone en échec", e)
        }
    }

    private companion object {
        const val TAG = "AppGraph"
        /** Ce qui attend dans la barre de saisie : gardé quand une session s'ouvre sur un autre compte. */
        val DRAFT_KEYS = setOf(Kv.DRAFT, Kv.SHARED_INBOX)
    }
}
