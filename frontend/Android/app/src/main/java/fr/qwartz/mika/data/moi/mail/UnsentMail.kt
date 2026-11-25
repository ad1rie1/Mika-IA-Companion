package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.ui.Route

/** Ce qu'« Écrire » tenait, champ par champ, quand on l'a quitté sans l'envoyer. */
data class UnsentMail(
    val from: String,
    val to: List<MailPerson>,
    val cc: List<MailPerson>,
    val bcc: List<MailPerson>,
    val toText: String,
    val ccText: String,
    val bccText: String,
    val showCc: Boolean,
    val showBcc: Boolean,
    val subject: String,
    val body: String,
    val quote: Boolean,
    val carry: Boolean,
    val pieces: List<OutgoingPiece>,
    val fromDraft: String,
    val asked: Boolean,
)

/**
 * Les mails commencés et pas envoyés de la session, chacun sous son écriture : la route (même mode, même mail, même
 * brouillon). Un lien profond (une notification, un partage vers Mika) remplace la pile sans demander : ce qui était
 * écrit attend ici, en mémoire seulement, et revient quand on rouvre la même écriture. Effacé à l'envoi, à l'abandon
 * confirmé et à la déconnexion (`AppGraph.onWipe`).
 */
class UnsentMails {
    private val kept = HashMap<Route.MailCompose, UnsentMail>()

    /** L'écran s'en va sans que rien soit parti : ce qui est écrit attend sa route. */
    fun keep(route: Route.MailCompose, mail: UnsentMail) = synchronized(kept) { kept[route] = mail }

    /** La même écriture rouverte : ce qu'elle tenait, rendu une fois. */
    fun take(route: Route.MailCompose): UnsentMail? = synchronized(kept) { kept.remove(route) }

    /** Parti, ou abandonné : rien n'attend plus. */
    fun drop(route: Route.MailCompose) {
        synchronized(kept) { kept.remove(route) }
    }

    fun clear() = synchronized(kept) { kept.clear() }
}
