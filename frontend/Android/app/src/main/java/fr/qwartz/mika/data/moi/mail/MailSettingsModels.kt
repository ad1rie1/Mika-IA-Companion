package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.data.moi.settings.SendRules
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes des réglages d'une boîte dans l'API par personne (`backendv2/docs/protocole-moi.md` § 7 ; code
 * `app/domains/mail/box_settings.py`) : ce que Paramètres › Boîtes mail lit et écrit. Chaque champ a son défaut :
 * `MikaJson` ignore ce qu'il ne connaît pas, et un champ absent ne casse rien. Un secret n'est jamais rendu : seulement
 * le fait qu'il est gardé. Sa règle d'envoi a la forme commune (`settings/SettingsModels.kt`, `SendRules`).
 */

// ── Une boîte (§ 7) ─────────────────────────────────────────────────────

/** Ce qu'une personne règle d'une boîte (`MailAccount`, sans `owner` ni `shares` ni ses secrets). Les noms sont ceux du
 *  moteur : ils partent tels quels dans `values` (`mail/box/save`). */
@Serializable
data class BoxValues(
    val label: String = "",
    val address: String = "",
    val enabled: Boolean = true,
    /** `password` ou `microsoft`. */
    val auth: String = Auths.PASSWORD,
    @SerialName("imap_host") val imapHost: String = "",
    @SerialName("imap_port") val imapPort: Int = 993,
    @SerialName("imap_ssl") val imapSsl: Boolean = true,
    val user: String = "",
    val folders: List<String> = listOf("INBOX"),
    @SerialName("sync_all") val syncAll: Boolean = false,
    /** Tout garder en local (ADR 0249) : tous les dossiers, sauf indésirables et corbeille, et leur historique. */
    @SerialName("keep_all") val keepAll: Boolean = false,
    @SerialName("since_days") val sinceDays: Int = 2,
    /** Ses consignes de tri (ADR 0243) : ce que son tri fait de chaque mail qui arrive dans un dossier relevé. */
    @SerialName("triage_instructions") val triageInstructions: String = "",
    @SerialName("oauth_client_id") val oauthClientId: String = "",
    @SerialName("oauth_tenant") val oauthTenant: String = "",
    @SerialName("smtp_host") val smtpHost: String = "",
    @SerialName("smtp_port") val smtpPort: Int = 587,
    /** `starttls`, `ssl`, `none`. */
    @SerialName("smtp_security") val smtpSecurity: String = "starttls",
    @SerialName("smtp_user") val smtpUser: String = "",
    @SerialName("save_sent") val saveSent: Boolean = true,
    /** Comment elle y écrit : `elle`, `assistante`, `proprietaire`. */
    val voice: String = Voices.HER,
    @SerialName("display_name") val displayName: String = "",
    @SerialName("sender_name") val senderName: String = "",
    val tone: String = "",
    val instructions: String = "",
    val signature: String = "",
)

object Auths {
    const val PASSWORD = "password"
    const val MICROSOFT = "microsoft"
}

object Voices {
    const val HER = "elle"
    const val ASSISTANT = "assistante"
    const val OWNER = "proprietaire"
}

/** Ses secrets gardés (jamais rendus). */
@Serializable
data class BoxSecrets(
    val password: Boolean = false,
    @SerialName("smtp_password") val smtpPassword: Boolean = false,
)

/** Où en est la connexion Microsoft d'une boîte (ADR 0166). */
@Serializable
data class SignIn(
    /** `connectee`, `en_attente` (un code à entrer chez Microsoft), ou autre chose (pas connectée). */
    val state: String = "",
    val code: String = "",
    val url: String = "",
    /** Jusqu'à quand le code vaut. */
    val until: Long = 0,
    val error: String = "",
) {
    val connected: Boolean get() = state == CONNECTED
    val waiting: Boolean get() = state == WAITING

    companion object {
        const val CONNECTED = "connectee"
        const val WAITING = "en_attente"
    }
}

/** `GET …/mail/box` : les réglages d'une de ses boîtes. */
@Serializable
data class BoxSettings(
    val box: String = "",
    val values: BoxValues = BoxValues(),
    val secrets: BoxSecrets = BoxSecrets(),
    val ready: Boolean = false,
    @SerialName("can_send") val canSend: Boolean = false,
    val microsoft: Boolean = false,
    val signin: SignIn? = null,
    val rules: SendRules = SendRules(),
)
