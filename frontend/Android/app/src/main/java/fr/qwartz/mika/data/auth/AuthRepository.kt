package fr.qwartz.mika.data.auth

import fr.qwartz.mika.core.Clock
import fr.qwartz.mika.data.net.ServerBase
import fr.qwartz.mika.data.settings.SettingsStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Le serveur et le jeton d'une session ; le jeton n'apparaît jamais dans `toString`. */
class Credentials(val base: ServerBase, val token: String) {
    override fun toString() = "Credentials(base=$base)"
}

sealed interface Session {
    data object Loading : Session
    /** Hors session ; [reason] dit pourquoi quand ce n'est pas un choix (session expirée…). */
    data class LoggedOut(val reason: String? = null) : Session
    data class LoggedIn(val base: ServerBase, val profile: Profile) : Session
}

/**
 * Ce qu'une session ouverte ou fermée doit faire ailleurs dans l'app : couper la connexion (et le
 * service) avant d'effacer quoi que ce soit, effacer ce que le téléphone garde, et savoir à qui
 * appartiennent les données locales (un autre compte ou un autre serveur les vide).
 */
interface SessionHooks {
    suspend fun beforeSignOut()

    /**
     * Effacer ce que le téléphone garde de la conversation. [keepDraft] : à l'ouverture d'une session
     * (autre compte ou autre serveur), ce qui attend dans la barre de saisie reste — un partage reçu
     * hors session est fait pour la session qui s'ouvre. À la fermeture, rien ne reste.
     */
    suspend fun wipeLocalData(keepDraft: Boolean)
    suspend fun localOwner(): String?
    suspend fun setLocalOwner(owner: String)
}

class AuthRepository(
    private val api: AuthApi,
    private val vault: TokenVault,
    private val settings: SettingsStore,
    private val hooks: SessionHooks,
    private val clock: Clock,
    /** « Android · <fabricant> <modèle> » : ce que la console › Comptes montre de cet appareil. */
    private val deviceLabel: String,
) {
    sealed interface LoginResult {
        data object Success : LoginResult
        data class Failure(val error: AuthError) : LoginResult
    }

    /** Après un 4401 : la session vaut-elle encore ? */
    enum class Check { VALID, EXPIRED, UNKNOWN }

    private val _session = MutableStateFlow<Session>(Session.Loading)
    val session: StateFlow<Session> = _session.asStateFlow()

    @Volatile private var credentials: Credentials? = null
    private val lock = Mutex()

    fun credentials(): Credentials? = credentials

    /** Au démarrage : rouvrir la session gardée, sans réseau. */
    suspend fun restore() = lock.withLock {
        val s = settings.current()
        val base = ServerBase.fromCanonical(s.serverUrl)
        val profile = s.profile
        when (val read = vault.read()) {
            is TokenVault.Read.Present -> if (base != null && profile != null) {
                credentials = Credentials(base, read.token)
                _session.value = Session.LoggedIn(base, profile)
            } else {
                vault.clear()
                _session.value = Session.LoggedOut()
            }
            TokenVault.Read.Invalid -> {
                settings.clearProfile()
                _session.value = Session.LoggedOut(AuthErrors.SESSION_TO_REOPEN)
            }
            TokenVault.Read.Absent -> _session.value = Session.LoggedOut()
        }
    }

    suspend fun login(serverInput: String, username: String, password: String): LoginResult {
        val base = when (val parsed = ServerBase.parse(serverInput)) {
            is ServerBase.Parsed.Ok -> parsed.base
            is ServerBase.Parsed.Error -> return LoginResult.Failure(AuthError(parsed.message))
        }
        val name = username.trim()
        if (name.isEmpty() || password.isEmpty()) {
            return LoginResult.Failure(AuthError("Nom d'utilisateur et mot de passe requis."))
        }
        return when (val r = api.login(base, name, password, deviceLabel.take(LABEL_MAX))) {
            is AuthApi.Result.Ok -> {
                val grant = r.value
                if (grant.token.isEmpty() || grant.personId.isEmpty()) {
                    LoginResult.Failure(AuthError("Réponse inattendue du serveur."))
                } else {
                    open(base, name, grant.token, grant.profile)
                    LoginResult.Success
                }
            }
            is AuthApi.Result.Http -> LoginResult.Failure(AuthErrors.forHttp(r.code, r.error, r.retryAfter, clock.wallMs()))
            is AuthApi.Result.Network -> LoginResult.Failure(AuthErrors.forException(r.error, base.hostPort))
        }
    }

    /** En débogage : un jeton créé par `mika token create … --client mobile`, vérifié par `whoami`. */
    suspend fun loginWithToken(serverInput: String, token: String): LoginResult {
        val base = when (val parsed = ServerBase.parse(serverInput)) {
            is ServerBase.Parsed.Ok -> parsed.base
            is ServerBase.Parsed.Error -> return LoginResult.Failure(AuthError(parsed.message))
        }
        val raw = token.trim()
        if (raw.isEmpty()) return LoginResult.Failure(AuthError("Colle un jeton."))
        return when (val r = api.whoami(base, raw)) {
            is AuthApi.Result.Ok -> if (r.value.authenticated && r.value.personId.isNotEmpty()) {
                open(base, r.value.username, raw, r.value.profile)
                LoginResult.Success
            } else {
                LoginResult.Failure(AuthError("Ce jeton n'ouvre aucune session sur ce serveur."))
            }
            is AuthApi.Result.Http -> LoginResult.Failure(AuthErrors.forHttp(r.code, r.error, r.retryAfter, clock.wallMs()))
            is AuthApi.Result.Network -> LoginResult.Failure(AuthErrors.forException(r.error, base.hostPort))
        }
    }

    private suspend fun open(base: ServerBase, username: String, token: String, profile: Profile) = lock.withLock {
        // Un autre compte, ou un autre serveur : ce que le téléphone garde n'est pas à lui.
        val owner = "${base.canonical}|${profile.personId}"
        if (hooks.localOwner() != owner) {
            hooks.wipeLocalData(keepDraft = true)
            hooks.setLocalOwner(owner)
        }
        vault.write(token)
        settings.saveLogin(base.canonical, username, profile)
        credentials = Credentials(base, token)
        _session.value = Session.LoggedIn(base, profile)
    }

    /**
     * Se déconnecter : couper la connexion, rendre le jeton au serveur (au mieux), l'oublier, effacer
     * les messages et fichiers du téléphone. L'adresse et le nom restent pour pré-remplir.
     */
    suspend fun logout() = signOut(revoke = true, reason = null)

    /** Après un 4401 : `whoami` avec le jeton dit si la session est finie ou si c'était autre chose. */
    suspend fun checkAfterUnauthorized(): Check {
        val c = credentials ?: return Check.EXPIRED
        return when (val r = api.whoami(c.base, c.token)) {
            is AuthApi.Result.Ok -> if (r.value.authenticated) {
                Check.VALID
            } else {
                signOut(revoke = false, reason = AuthErrors.SESSION_EXPIRED)
                Check.EXPIRED
            }
            is AuthApi.Result.Http -> if (r.code == 401) {
                signOut(revoke = false, reason = AuthErrors.SESSION_EXPIRED)
                Check.EXPIRED
            } else {
                Check.UNKNOWN
            }
            is AuthApi.Result.Network -> Check.UNKNOWN
        }
    }

    private suspend fun signOut(revoke: Boolean, reason: String?) = lock.withLock {
        val c = credentials
        hooks.beforeSignOut()
        if (revoke && c != null) api.revoke(c.base, c.token)
        credentials = null
        vault.clear()
        settings.clearProfile()
        // Un téléphone dont la session a été révoquée (perdu, prêté) ne garde rien non plus.
        hooks.wipeLocalData(keepDraft = false)
        _session.value = Session.LoggedOut(reason)
    }

    private companion object {
        const val LABEL_MAX = 60
    }
}
