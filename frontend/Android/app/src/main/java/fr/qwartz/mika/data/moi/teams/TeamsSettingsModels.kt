package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.data.moi.settings.SendRules
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes des réglages d'un compte Teams dans l'API par personne (`backendv2/docs/protocole-moi.md` § 7 ; code
 * `app/domains/teams/account_settings.py`) : ce que Paramètres › Comptes Teams lit et écrit. Chaque champ a son
 * défaut : `MikaJson` ignore ce qu'il ne connaît pas, et un champ absent ne casse rien. Sa règle d'envoi a la forme
 * commune (`settings/SettingsModels.kt`, `SendRules`).
 */

// ── Un compte Teams (§ 7) ───────────────────────────────────────────────

@Serializable
data class TeamsValues(
    val label: String = "",
    val enabled: Boolean = true,
    @SerialName("display_name") val displayName: String = "",
    val tone: String = "",
    val instructions: String = "",
    val sign: Boolean = false,
    val signature: String = "",
)

/** `GET …/teams/account` : les réglages d'un de ses comptes Teams. */
@Serializable
data class TeamsSettings(
    val account: String = "",
    val values: TeamsValues = TeamsValues(),
    @SerialName("extension_key") val extensionKey: ExtensionKey? = null,
    val rules: SendRules = SendRules(),
)
