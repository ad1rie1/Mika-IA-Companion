package fr.qwartz.mika.data.settings

import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.auth.Profile
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

enum class ThemeMode { SYSTEM, LIGHT, DARK }

/** Les réglages de l'app. L'adresse et le nom restent après une déconnexion, pour pré-remplir. */
data class Settings(
    /** L'adresse canonique du serveur (`ServerBase.canonical`), vide avant la première connexion. */
    val serverUrl: String = "",
    val username: String = "",
    /** Le compte connecté ; `null` hors session. */
    val profile: Profile? = null,
    /** « Rester connectée en arrière-plan » : le service garde la socket pour recevoir ses messages. */
    val background: Boolean = true,
    /** « Démarrer avec le téléphone ». */
    val startOnBoot: Boolean = false,
    val theme: ThemeMode = ThemeMode.SYSTEM,
    /** « Couleurs dynamiques » (Android 12 et plus). */
    val dynamicColor: Boolean = true,
    /** La permission de notifier a été demandée une fois (accordée ou non) : on ne la redemande pas d'office. */
    val notificationsAsked: Boolean = false,
)

class SettingsStore(private val store: DataStore<Preferences>) {

    val settings: Flow<Settings> = store.data.map { p ->
        Settings(
            serverUrl = p[SERVER].orEmpty(),
            username = p[USERNAME].orEmpty(),
            profile = p[PROFILE]?.let(::decodeProfile),
            background = p[BACKGROUND] ?: true,
            startOnBoot = p[START_ON_BOOT] ?: false,
            theme = p[THEME]?.let { runCatching { ThemeMode.valueOf(it) }.getOrNull() } ?: ThemeMode.SYSTEM,
            dynamicColor = p[DYNAMIC_COLOR] ?: true,
            notificationsAsked = p[NOTIFICATIONS_ASKED] ?: false,
        )
    }

    suspend fun current(): Settings = settings.first()

    suspend fun saveLogin(serverUrl: String, username: String, profile: Profile) = store.edit {
        it[SERVER] = serverUrl
        it[USERNAME] = username
        it[PROFILE] = MikaJson.encodeToString(Profile.serializer(), profile)
    }

    /** Hors session : le compte part, l'adresse et le nom restent pour la prochaine connexion. */
    suspend fun clearProfile() = store.edit { it.remove(PROFILE) }

    suspend fun setBackground(on: Boolean) = store.edit { it[BACKGROUND] = on }
    suspend fun setStartOnBoot(on: Boolean) = store.edit { it[START_ON_BOOT] = on }
    suspend fun setTheme(mode: ThemeMode) = store.edit { it[THEME] = mode.name }
    suspend fun setDynamicColor(on: Boolean) = store.edit { it[DYNAMIC_COLOR] = on }
    suspend fun setNotificationsAsked() = store.edit { it[NOTIFICATIONS_ASKED] = true }

    private fun decodeProfile(raw: String): Profile? = try {
        MikaJson.decodeFromString(Profile.serializer(), raw)
    } catch (_: IllegalArgumentException) {
        null
    }

    private companion object {
        val SERVER = stringPreferencesKey("server_url")
        val USERNAME = stringPreferencesKey("username")
        val PROFILE = stringPreferencesKey("profile")
        val BACKGROUND = booleanPreferencesKey("background")
        val START_ON_BOOT = booleanPreferencesKey("start_on_boot")
        val THEME = stringPreferencesKey("theme")
        val DYNAMIC_COLOR = booleanPreferencesKey("dynamic_color")
        val NOTIFICATIONS_ASKED = booleanPreferencesKey("notifications_asked")
    }
}
