package fr.qwartz.mika.data.phone

/**
 * Ce qu'a donné un geste fait depuis l'écran Téléphone de l'app (ADR 0120, 0235) : ta réponse, ou la sienne, part par
 * l'action « Répondre » de la notification de WhatsApp ou de Messages gardée en mémoire ([ReplyRegistry]) ; sans elle,
 * le texte est copié et l'écran ouvre l'appli pour le coller. Le geste sur ce téléphone vaut accord, comme dans la
 * notification d'une proposition (`service/PhoneDraftNotifier`).
 */
enum class HereOutcome {
    /** Parti par l'action « Répondre » de l'appli. */
    SENT,
    /** L'action n'est plus là, ou l'appli l'a refusée : le texte est dans le presse-papier (l'écran ouvre l'appli). */
    COPIED,
    /** Ni parti ni copié (le presse-papier refusé). */
    FAILED,
    /** « Ignorer » : rien ne part, et Mika le saura. */
    IGNORED,
    /** La proposition n'attend plus sur ce téléphone (expirée, déjà réglée, effacée) : rien n'est fait. */
    GONE,
    /** Rien à envoyer (un texte vide). */
    NOTHING,
}

/** Les règles d'un geste d'ici, pures. */
object PhoneHere {
    /**
     * « Envoyer » depuis l'écran, après « Écrire autre chose » : ce que tu as tapé ([typed]), ou `null` si c'est sa
     * proposition telle quelle (inchangée, aux espaces près) — qui part alors comme « Envoyer » (`sent`), pas comme
     * « autre chose » (`other`).
     */
    fun typedOrNull(typed: String?, draft: PhoneDraft): String? =
        typed?.takeUnless { unchanged(it, draft.text) }?.trim()

    /** Le champ tient-il encore sa proposition telle qu'elle la proposait (aux espaces près) ? */
    fun unchanged(field: String, proposed: String): Boolean = field.trim() == proposed.trim()

    /** Deux noms de conversation sont-ils le même (casse et espaces mis à part) ? Un nom vide n'est celui de personne. */
    fun sameName(a: String, b: String): Boolean {
        val x = norm(a)
        return x.isNotEmpty() && x == norm(b)
    }

    /**
     * Ce qui part d'ici peut-il passer par l'action gardée ? Il en faut une ([keptName] : le nom que sa notification
     * donnait à la conversation ; `null` : aucune), et, quand l'écran dit à qui il répond ([expected] : le nom du fil
     * montré), que ce soit le même : sinon le texte est copié, et l'écran l'a dit avant le geste (R3-06). Le geste fait
     * dans la notification d'une proposition ([expected] `null`) ne se compare pas : sa notification nomme déjà à qui.
     */
    fun canDeliver(keptName: String?, expected: String?): Boolean =
        keptName != null && (expected == null || sameName(keptName, expected))

    private fun norm(s: String): String = s.trim().replace(Regex("\\s+"), " ").lowercase()
}

/**
 * Les gestes d'ici, tels que l'écran d'un fil les voit (`service/PhoneDraftNotifier` les fait ; sur la JVM, un faux) :
 * les propositions que ce téléphone tient, à qui part ce qu'on envoie d'ici, « Envoyer » et « Ignorer » sur sa
 * proposition, ton propre message, et faire partir leur sort au serveur.
 */
interface PhoneHereGestures {
    suspend fun waiting(): List<PhoneDraft>

    /** Le nom à qui répond l'action « Répondre » gardée pour [thread] (vide : sa notification ne le disait pas) ;
     *  `null` sans action gardée — ce qui part d'ici est copié. */
    fun replyTo(thread: String): String?

    /** « Envoyer » sa proposition ([typed] : ta version) ; [to] : le nom du fil montré, que l'action doit viser. */
    suspend fun sendHere(id: Long, typed: String?, to: String): HereOutcome

    suspend fun ignoreHere(id: Long): HereOutcome

    /** Ton propre message dans [thread] ; [to] : le nom du fil montré, que l'action doit viser. */
    suspend fun replyHere(thread: String, text: String, to: String): HereOutcome

    suspend fun flushNow()
}
