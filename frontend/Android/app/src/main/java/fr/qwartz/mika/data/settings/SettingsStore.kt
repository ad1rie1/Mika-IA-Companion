package fr.qwartz.mika.data.settings

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
import androidx.datastore.preferences.core.stringPreferencesKey
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Profile
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

enum class ThemeMode { SYSTEM, LIGHT, DARK }

/**
 * Les réglages de l'app. L'adresse et le nom restent après une déconnexion, pour pré-remplir.
 *
 * Il n'y a plus de « connexion en arrière-plan » (ADR 0077) : l'app ne se connecte qu'ouverte, et ses messages
 * arrivent app fermée par Firebase. Les clés `background` et `start_on_boot` d'avant restent lues par personne.
 */
data class Settings(
    /** L'adresse canonique du serveur (`ServerBase.canonical`), vide avant la première connexion. */
    val serverUrl: String = "",
    val username: String = "",
    /** Le compte connecté ; `null` hors session. */
    val profile: Profile? = null,
    val theme: ThemeMode = ThemeMode.SYSTEM,
    /** « Couleurs dynamiques » (Android 12 et plus). */
    val dynamicColor: Boolean = true,
    /** « Mika en fond » : son portrait, qui suit son humeur, derrière la conversation. */
    val avatar: Boolean = true,
    /** La permission de notifier a été demandée une fois (accordée ou non) : on ne la redemande pas d'office. */
    val notificationsAsked: Boolean = false,
    /** « Lui dire quand j'ai lu » : jusqu'où la conversation a été lue part au serveur ; coupé, rien ne part. */
    val shareReads: Boolean = true,
    /**
     * L'interrupteur « Pro » de la barre de saisie (ADR 0116), retenu sur l'appareil. Il ne vaut que pour une
     * opératrice : ailleurs il n'apparaît pas et rien ne part en mode pro.
     */
    val proMode: Boolean = false,
    /**
     * « Lui dire où je suis » (ADR 0119) : app au premier plan, la position de ce téléphone part à Mika. Coupé par
     * défaut, et remis à zéro à la fin de la session : un autre compte n'en hérite jamais.
     */
    val shareWhere: Boolean = false,
)

class SettingsStore(private val store: DataStore<Preferences>) {

    val settings: Flow<Settings> = store.data.map { p ->
        Settings(
            serverUrl = p[SERVER].orEmpty(),
            username = p[USERNAME].orEmpty(),
            profile = p[PROFILE]?.let(::decodeProfile),
            theme = p[THEME]?.let { runCatching { ThemeMode.valueOf(it) }.getOrNull() } ?: ThemeMode.SYSTEM,
            dynamicColor = p[DYNAMIC_COLOR] ?: true,
            avatar = p[AVATAR] ?: true,
            notificationsAsked = p[NOTIFICATIONS_ASKED] ?: false,
            shareReads = p[SHARE_READS] ?: true,
            proMode = p[PRO_MODE] ?: false,
            shareWhere = p[SHARE_WHERE] ?: false,
        )
    }

    suspend fun current(): Settings = settings.first()

    suspend fun saveLogin(serverUrl: String, username: String, profile: Profile) = store.edit {
        it[SERVER] = serverUrl
        it[USERNAME] = username
        it[PROFILE] = MikaJson.encodeToString(Profile.serializer(), profile)
    }

    /**
     * Hors session : le compte part, et ce qu'il permettait de dire de lui (« Lui dire où je suis », ADR 0119) ;
     * l'adresse et le nom restent pour la prochaine connexion.
     */
    suspend fun clearProfile() = store.edit {
        it.remove(PROFILE)
        it.remove(SHARE_WHERE)
    }

    /** Ce que le téléphone a dit au serveur pour être notifié (ADR 0077), et quand. */
    data class PushMemo(val fingerprint: String = "", val at: Long = 0, val serverReady: Boolean = false)

    suspend fun pushMemo(): PushMemo = store.data.first().let { p ->
        PushMemo(p[PUSH_FINGERPRINT].orEmpty(), p[PUSH_AT] ?: 0L, p[PUSH_SERVER_READY] ?: false)
    }

    suspend fun savePushMemo(memo: PushMemo) = store.edit {
        it[PUSH_FINGERPRINT] = memo.fingerprint
        it[PUSH_AT] = memo.at
        it[PUSH_SERVER_READY] = memo.serverReady
    }

    suspend fun clearPushMemo() = store.edit {
        it.remove(PUSH_FINGERPRINT)
        it.remove(PUSH_AT)
        it.remove(PUSH_SERVER_READY)
    }
    suspend fun setTheme(mode: ThemeMode) = store.edit { it[THEME] = mode.name }
    suspend fun setDynamicColor(on: Boolean) = store.edit { it[DYNAMIC_COLOR] = on }
    suspend fun setAvatar(on: Boolean) = store.edit { it[AVATAR] = on }
    suspend fun setNotificationsAsked() = store.edit { it[NOTIFICATIONS_ASKED] = true }
    suspend fun setShareReads(on: Boolean) = store.edit { it[SHARE_READS] = on }
    suspend fun setProMode(on: Boolean) = store.edit { it[PRO_MODE] = on }
    suspend fun setShareWhere(on: Boolean) = store.edit { it[SHARE_WHERE] = on }

    private fun decodeProfile(raw: String): Profile? = try {
        MikaJson.decodeFromString(Profile.serializer(), raw)
    } catch (_: IllegalArgumentException) {
        null
    }

    private companion object {
        val SERVER = stringPreferencesKey("server_url")
        val USERNAME = stringPreferencesKey("username")
        val PROFILE = stringPreferencesKey("profile")
        val PUSH_FINGERPRINT = stringPreferencesKey("push_fingerprint")
        val PUSH_AT = longPreferencesKey("push_at")
        val PUSH_SERVER_READY = booleanPreferencesKey("push_server_ready")
        val THEME = stringPreferencesKey("theme")
        val DYNAMIC_COLOR = booleanPreferencesKey("dynamic_color")
        val AVATAR = booleanPreferencesKey("avatar")
        val NOTIFICATIONS_ASKED = booleanPreferencesKey("notifications_asked")
        val SHARE_READS = booleanPreferencesKey("share_reads")
        val PRO_MODE = booleanPreferencesKey("pro_mode")
        val SHARE_WHERE = booleanPreferencesKey("share_where")
    }
}
