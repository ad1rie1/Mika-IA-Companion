package fr.qwartz.mika.core

/** Les cibles qu'une notification ou un raccourci passe à `MainActivity`. */
object DeepLinks {
    const val EXTRA_OPEN = "fr.qwartz.mika.OPEN"
    const val CHAT = "chat"
    const val SETTINGS = "settings"
    const val MIND = "mind"
    const val MAIL_DRAFTS = "mail_drafts"
    const val TEAMS_REPLIES = "teams_replies"
    const val PHONE = "phone"
    /** L'Agenda ; `agenda:e:<événement>:<occurrence>` ou `agenda:p:<proposition>` ouvre ce qu'une notification dit. */
    const val AGENDA = "agenda"
}
