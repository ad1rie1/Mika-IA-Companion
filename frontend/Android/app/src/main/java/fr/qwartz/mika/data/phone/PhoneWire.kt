package fr.qwartz.mika.data.phone

import kotlinx.serialization.Serializable

/**
 * Un message lu sur le téléphone, tel qu'il part à `POST /api/phone/inbox` (ADR 0120) et tel qu'il attend dans la file.
 * La conversation et l'expéditeur sont des clés opaques ([PhoneKeys]) ; le nom affiché et le texte partent en clair,
 * c'est ce que Mika lit.
 */
@Serializable
data class PhoneMessage(
    /** L'empreinte du message ([PhoneKeys.id]) : le serveur dédoublonne par elle. */
    val id: String,
    /** Le code de l'appli ([PhoneApp.code]). */
    val app: String,
    /** La conversation ([PhoneKeys.thread]). */
    val thread: String,
    /** Le nom du groupe ; vide en tête-à-tête. */
    val title: String = "",
    val group: Boolean = false,
    /** L'expéditeur ([PhoneKeys.sender]) ; vide quand c'est la personne elle-même qui a écrit. */
    val sender: String = "",
    /** Le nom affiché de l'expéditeur ; vide quand c'est la personne. */
    val name: String = "",
    val text: String,
    /** L'heure du message (ms depuis l'époque). */
    val time: Long,
    /** C'est la personne elle-même qui a écrit (sa réponse, depuis la notification ou l'appli). */
    val own: Boolean = false,
)

/** Le sort d'une réponse proposée, tel qu'il part à `POST /api/phone/settled` (ADR 0120). */
@Serializable
data class PhoneSettled(val id: Long, val result: String, val reason: String = "")

/** Ce que la personne a fait d'une proposition (le `result` de [PhoneSettled]). */
enum class Settlement(val wire: String) {
    /** Partie telle quelle, par l'action « Répondre » de l'appli. */
    SENT("sent"),
    /** La personne a écrit autre chose, parti par la même action. */
    OTHER("other"),
    /** L'action n'existait plus : le texte est dans le presse-papier, l'appli s'ouvre au toucher. */
    COPIED("copied"),
    IGNORED("ignored"),
    FAILED("failed"),
}

/** Pourquoi une proposition n'est pas partie par l'appli (le `reason` de [PhoneSettled]). */
enum class SettleReason(val wire: String) {
    NONE(""),
    /** Pas d'action « Répondre » gardée pour cette conversation (notification balayée, appli redémarrée). */
    NO_ACTION("no_action"),
    /** L'action existait mais l'appli l'a refusée (`PendingIntent.CanceledException`). */
    SEND_ERROR("send_error"),
}
