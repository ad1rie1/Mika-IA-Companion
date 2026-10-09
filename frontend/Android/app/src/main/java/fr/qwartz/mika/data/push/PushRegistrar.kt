package fr.qwartz.mika.data.push

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.core.Logger
import fr.qwartz.mika.data.auth.AuthApi
import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.auth.TokenVault
import fr.qwartz.mika.data.settings.SettingsStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import java.security.MessageDigest
import java.util.Base64

/** Firebase, vu de l'app : de quoi le remplacer dans les tests. */
interface PushPort {
    /** Firebase est dans cette version de l'app (`google-services.json` à la construction). */
    val available: Boolean

    /** Le jeton Firebase de ce téléphone, créé au besoin ; `null` : Firebase ne l'a pas donné. */
    suspend fun token(): String?

    /** Oublier le jeton (déconnexion) : plus rien n'arrive à ce téléphone tant qu'une session ne s'ouvre pas. */
    suspend fun forget()
}

/** Où en sont les notifications app fermée, pour les paramètres. */
sealed interface PushState {
    /** Cette version de l'app est construite sans Firebase. */
    data object Unavailable : PushState
    data object LoggedOut : PushState
    /** Pas encore dit au serveur (il n'était pas joignable) : ce sera fait à la prochaine ouverture. */
    data object Pending : PushState
    data object Active : PushState
    /** Le serveur n'a pas de clé Firebase : rien ne partira tant qu'un opérateur ne l'a pas posée. */
    data object ServerWithoutKey : PushState
    data class Failed(val reason: String) : PushState
}

/**
 * Dire au serveur où notifier ce téléphone fermé (ADR 0077) : son jeton Firebase et une clé tirée ici, gardée
 * chiffrée par le Keystore, avec laquelle le serveur scelle chaque message. Fait à chaque ouverture de l'app (jamais
 * fermée : en 4G, un serveur de la maison ne répond pas), au plus toutes les [REFRESH_MS] tant que rien ne change —
 * un serveur qui a oublié ce téléphone (une base restaurée, une clé Firebase corrigée) le réapprend à l'ouverture
 * suivante. Le jeton, la clé ou le serveur changés, ou un serveur sans clé Firebase : tout de suite.
 */
class PushRegistrar(
    private val port: PushPort,
    private val api: AuthApi,
    private val keys: TokenVault,
    private val settings: SettingsStore,
    private val credentials: () -> Credentials?,
    private val clock: Clock,
    private val logger: Logger = Logger.NONE,
) {
    private val lock = Mutex()
    private val _state = MutableStateFlow<PushState>(if (port.available) PushState.LoggedOut else PushState.Unavailable)
    val state: StateFlow<PushState> = _state.asStateFlow()

    /** L'app est ouverte (ou Firebase a changé le jeton) : le dire au serveur si besoin. */
    suspend fun sync(force: Boolean = false) = lock.withLock {
        if (!port.available) {
            _state.value = PushState.Unavailable
            return@withLock
        }
        val c = credentials() ?: run {
            _state.value = PushState.LoggedOut
            return@withLock
        }
        val key = keyLocked()
        val device = try {
            withTimeoutOrNull(TOKEN_WAIT_MS) { port.token() }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logger.w(TAG, "jeton Firebase indisponible : ${e.javaClass.simpleName}")
            null
        }
        if (device.isNullOrEmpty()) {
            _state.value = PushState.Failed("Firebase n'a pas donné de jeton (pas de réseau, ou services Google absents).")
            return@withLock
        }
        val fingerprint = fingerprint(c.base.canonical, device, key)
        val memo = settings.pushMemo()
        val known = memo.fingerprint == fingerprint
        if (!force && known && memo.serverReady && clock.wallMs() - memo.at in 0 until REFRESH_MS) {
            _state.value = PushState.Active
            return@withLock
        }
        _state.value = when (val r = api.registerPush(c.base, c.token, device, key)) {
            is AuthApi.Result.Ok -> {
                settings.savePushMemo(SettingsStore.PushMemo(fingerprint, clock.wallMs(), r.value.available))
                if (r.value.available) PushState.Active else PushState.ServerWithoutKey
            }
            is AuthApi.Result.Http -> {
                logger.w(TAG, "inscription refusée (HTTP ${r.code})")
                PushState.Failed(
                    if (r.code == 404) "Ce serveur ne sait pas encore notifier un téléphone : mets Mika à jour."
                    else r.error ?: "Le serveur a refusé l'inscription (HTTP ${r.code}).",
                )
            }
            // Hors de portée : ce qui a été dit avant vaut toujours, sinon ce sera à la prochaine ouverture.
            is AuthApi.Result.Network -> when {
                known && memo.serverReady -> PushState.Active
                known -> PushState.ServerWithoutKey
                else -> PushState.Pending
            }
        }
    }

    /** La clé qui ouvre une notification ; `null` hors session ou sans clé (rien n'a été dit au serveur). */
    suspend fun key(): ByteArray? {
        if (credentials() == null) return null
        return when (val read = keys.read()) {
            is TokenVault.Read.Present -> decode(read.token)
            else -> null
        }
    }

    /**
     * Déconnexion : le jeton Firebase, la clé et ce qui a été dit au serveur partent. Sans attendre une inscription en
     * cours (elle porte un jeton que la déconnexion rend : le serveur l'ignore), et sans plus de [FORGET_WAIT_MS] pour
     * Firebase — une déconnexion hors ligne ne traîne pas.
     */
    suspend fun forget() {
        keys.clear()
        settings.clearPushMemo()
        _state.value = if (port.available) PushState.LoggedOut else PushState.Unavailable
        if (!port.available) return
        try {
            withTimeoutOrNull(FORGET_WAIT_MS) { port.forget() }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            logger.w(TAG, "jeton Firebase non oublié : ${e.javaClass.simpleName}")
        }
    }

    /** La clé en base64, tirée la première fois ; illisible (Keystore changé), une neuve. */
    private suspend fun keyLocked(): String {
        (keys.read() as? TokenVault.Read.Present)?.token?.takeIf { decode(it) != null }?.let { return it }
        val fresh = Base64.getEncoder().encodeToString(PushPayload.newKey())
        keys.write(fresh)
        return fresh
    }

    private fun decode(b64: String): ByteArray? = try {
        Base64.getDecoder().decode(b64).takeIf { it.size == PushPayload.KEY_BYTES }
    } catch (_: IllegalArgumentException) {
        null
    }

    companion object {
        private const val TAG = "Push"
        /** Redire au serveur où notifier : à chaque ouverture, au plus toutes les 15 min tant que rien ne change. */
        const val REFRESH_MS = 15L * 60 * 1000
        private const val TOKEN_WAIT_MS = 20_000L
        private const val FORGET_WAIT_MS = 5_000L

        /** Ce qui a été dit : le serveur, le jeton Firebase, la clé — en empreinte, jamais la clé elle-même. */
        fun fingerprint(server: String, device: String, key: String): String {
            val digest = MessageDigest.getInstance("SHA-256").digest("$server\n$device\n$key".toByteArray(Charsets.UTF_8))
            return digest.joinToString("") { "%02x".format(it) }
        }
    }
}
