package fr.qwartz.mika.data.moi

import fr.qwartz.mika.data.moi.mail.MailBox
import fr.qwartz.mika.data.moi.mail.MailView
import fr.qwartz.mika.data.net.Topics

/*
 * Ce qu'un signal du direct fait relire à chaque écran (ADR 0308) : la colonne « Ce qu'on relit » de
 * `backendv2/docs/protocole-moi.md`, § 2 bis, écran par écran. Pur : l'écran relit, ceci décide.
 */

/** Mail : ses boîtes, la page affichée, le mail ouvert, ses brouillons, où elle en est d'une réponse. */
object MailLive {
    /** La liste : ses boîtes et la page affichée (`mail`), le bandeau de ses brouillons — un compte de ses boîtes. */
    val LIST = setOf(Topics.MAIL, Topics.MAIL_DRAFTS)
    /** La liseuse : le mail ouvert et sa boîte, son brouillon pour ce mail, où elle en est d'une réponse. */
    val READER = setOf(Topics.MAIL, Topics.MAIL_DRAFTS, Topics.MAIL_WORK)
    /** « Écrire » : où elle en est d'une réponse au mail d'origine (ce que tu tapes ne se relit jamais). */
    val COMPOSE = setOf(Topics.MAIL_WORK)
    /** « Ses brouillons » et la page d'un brouillon. */
    val DRAFTS = setOf(Topics.MAIL_DRAFTS)

    /** Les boîtes (leurs non-lus, leurs brouillons qui attendent, leur état) se relisent : `mail` ou `mail.drafts`. */
    fun boxes(s: LiveSignal): Boolean = s.touchesAny(Topics.MAIL, Topics.MAIL_DRAFTS)

    /**
     * La page de messages affichée relit-elle ? Toutes tes réceptions : sur tout `mail` ; une boîte (un dossier, ce
     * qui en est parti) : si elle est nommée. Ses brouillons ont leur sujet à eux (`mail.drafts`).
     */
    fun pageShows(view: MailView, s: LiveSignal): Boolean = when (view) {
        MailView.All -> s.touches(Topics.MAIL)
        is MailView.Folder -> s.names(Topics.MAIL, view.box)
        is MailView.Sent -> s.names(Topics.MAIL, view.box)
    }

    /** Le mail ouvert (dans la boîte [box]) se relit-il ? Sa boîte nommée par `mail`, ou ses brouillons qui changent. */
    fun openShows(box: String?, s: LiveSignal): Boolean =
        s.names(Topics.MAIL, box) || s.names(Topics.MAIL_DRAFTS, box)

    /** Où elle en est d'une réponse au mail [ref] se relit-il (`mail.work`, s'il est nommé) ? */
    fun workShows(ref: String?, s: LiveSignal): Boolean = s.names(Topics.MAIL_WORK, ref)

    /**
     * La vue ne tient plus à ses boîtes relues : la boîte qu'elle montre n'est plus à toi (retirée, plus partagée), ou
     * son dossier n'y est plus — retour à toutes les réceptions, plutôt qu'une page « introuvable ». Une boîte dont les
     * dossiers ne se disent pas (pas encore lus, en panne) garde sa vue.
     */
    fun viewGone(view: MailView, boxes: List<MailBox>): Boolean {
        val key = view.boxKey ?: return false
        val box = boxes.firstOrNull { it.key == key } ?: return true
        return view is MailView.Folder && box.folders.isNotEmpty() && box.folders.none { it.name == view.folder }
    }

    /** Le mail ouvert (dans la boîte [box]) n'est plus d'une de tes boîtes : la liseuse revient à la liste. */
    fun openGone(box: String?, boxes: List<MailBox>): Boolean = !box.isNullOrEmpty() && boxes.none { it.key == box }
}

/** Teams : ses comptes, les discussions, le fil ouvert, ses réponses, où elle en est. */
object TeamsLive {
    /** La liste : ses comptes et les discussions (`teams`), le bandeau de ses réponses qui attendent. */
    val LIST = setOf(Topics.TEAMS, Topics.TEAMS_REPLIES)
    /** Le fil ouvert, ses réponses (elles sont dans le fil), où elle en est d'une réponse. */
    val THREAD = setOf(Topics.TEAMS, Topics.TEAMS_WORK)
    /** « Ses brouillons » : ses réponses, et les comptes qui décident de chacune. */
    val REPLIES = setOf(Topics.TEAMS_REPLIES, Topics.TEAMS)

    /** Le fil ouvert se relit-il ? S'il est nommé — sous la clé demandée ou celle que le serveur a rendue. */
    fun threadShows(keys: Collection<String>, s: LiveSignal): Boolean = s.namesAny(Topics.TEAMS, keys)

    /** Où elle en est d'une réponse dans le fil ouvert se relit-il (`teams.work`, s'il est nommé) ? */
    fun workShows(keys: Collection<String>, s: LiveSignal): Boolean = s.namesAny(Topics.TEAMS_WORK, keys)

    /** « Ses brouillons » se relisent : ses réponses ont changé, ou un compte (qui décide). */
    fun repliesShow(s: LiveSignal): Boolean = s.touchesAny(Topics.TEAMS_REPLIES, Topics.TEAMS)

    /** Le fil ouvert n'est plus d'un de tes comptes relus ([accounts] : leurs clés ; retiré, plus partagé) : il revient
     *  à la liste, plutôt qu'un fil figé qu'aucune relecture ne suivrait plus. */
    fun threadGone(account: String?, accounts: Collection<String>): Boolean = !account.isNullOrEmpty() && account !in accounts
}

/** Téléphone : ses conversations, le fil ouvert (ses propositions avec), ta position, tes téléphones. */
object PhoneLive {
    val MESSAGES = setOf(Topics.PHONE)
    val THREAD = setOf(Topics.PHONE)
    val POSITION = setOf(Topics.PHONE_POSITION)
    val PHONES = setOf(Topics.PHONE_PHONES)

    /** Le fil ouvert ([key] : `<appli>|<fil>`) se relit-il ? S'il est nommé. */
    fun threadShows(key: String?, s: LiveSignal): Boolean = s.names(Topics.PHONE, key)
}

/** Projets : la liste et « À faire », la fiche ouverte et ses onglets, ses pages. */
object ProjectsLive {
    val TOPICS = setOf(Topics.PROJECTS)

    /** La fiche du projet [id] (ou une de ses pages) se relit-elle ? S'il est nommé — un numéro, lu comme du texte. */
    fun shows(id: Int, s: LiveSignal): Boolean = id > 0 && s.names(Topics.PROJECTS, id.toString())
}
