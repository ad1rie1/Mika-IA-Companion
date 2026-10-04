package fr.qwartz.mika.core

import kotlinx.serialization.json.Json

/**
 * Un seul réglage JSON pour tout ce qui vient du serveur ou dort en base : une clé inconnue est
 * ignorée (le serveur grandit plus vite que l'app), un `null` sur un champ à défaut prend le défaut.
 */
val MikaJson: Json = Json {
    ignoreUnknownKeys = true
    explicitNulls = false
    coerceInputValues = true
    encodeDefaults = true
}
