package fr.qwartz.mika.data.phone

/** Une personne telle qu'une notification la nomme (`androidx.core.app.Person`), réduite à ce qui l'identifie. */
data class PostedPerson(val key: String? = null, val uri: String? = null, val name: String? = null) {
    /** Sa clé d'expéditeur (ADR 0120) : `key`, sinon `uri`, sinon le nom ; `null` si elle n'a rien de tout cela. */
    val senderKey: String? get() = key.nonBlank() ?: uri.nonBlank() ?: name.nonBlank()
}

/** Un message du `MessagingStyle` : son texte, son heure (ms), et qui l'a écrit (`null` : la personne elle-même). */
data class PostedMessage(val text: String, val time: Long, val person: PostedPerson?)

/** Le `MessagingStyle` d'une notification. [user] : la personne à qui appartient le téléphone, telle que l'appli la nomme. */
data class PostedStyle(
    val user: PostedPerson?,
    val conversationTitle: String?,
    val group: Boolean,
    val messages: List<PostedMessage>,
)

/**
 * Une notification postée, telle que le lecteur (`PhoneListenerService`) la décrit : le strict nécessaire, sans rien
 * d'Android, pour que le tri se teste sur la JVM.
 */
data class PostedNotification(
    val packageName: String,
    /** Un résumé de groupe (`FLAG_GROUP_SUMMARY`) : il redit ce que les notifications du groupe disent déjà. */
    val groupSummary: Boolean,
    val shortcutId: String?,
    val tag: String?,
    /** L'heure de la notification (ms) : celle d'un message qui n'a pas la sienne. */
    val postTime: Long,
    /** `null` : pas de `MessagingStyle` (une notification de service, de mise à jour…), rien à lire. */
    val style: PostedStyle?,
)

/** Ce qu'une notification apporte : sa conversation (pour garder son action « Répondre ») et ses messages. */
data class PhoneReadingResult(val app: PhoneApp, val thread: String, val group: Boolean, val messages: List<PhoneMessage>)

/** La forme d'une action de notification, pour choisir celle qui répond ([PhoneReading.pickReply]). */
data class ActionShape(val semanticAction: Int, val freeFormInputs: Int)

/**
 * Le tri des notifications (ADR 0120) : quelles notifications se lisent, et ce qui en part. Pur : le lecteur Android
 * ne fait que décrire la notification ([PostedNotification]) et garder l'action « Répondre ».
 */
object PhoneReading {
    /** Le texte d'un message, au plus : la porte du serveur écarte un texte plus long. */
    const val MAX_TEXT = 4_000

    /** `Notification.Action.SEMANTIC_ACTION_REPLY`. */
    const val SEMANTIC_ACTION_REPLY = 1

    /**
     * Les messages d'une notification, ou `null` quand elle ne se lit pas : une appli qui n'est pas cochée (ou
     * l'interrupteur coupé), un résumé de groupe, une notification sans `MessagingStyle`, un groupe quand « Les groupes
     * aussi » est coupé, une conversation qu'on ne sait pas nommer.
     *
     * La conversation est le `shortcutId` de la notification, sinon son `tag`, sinon le titre de la conversation, sinon
     * le nom de l'expéditeur. Un message sans expéditeur, ou dont l'expéditeur est la `user` du style, est de la
     * personne elle-même (`own`) : ni clé ni nom d'expéditeur.
     */
    fun read(notification: PostedNotification, gate: PhoneGate): PhoneReadingResult? {
        val app = PhoneApp.ofPackage(notification.packageName) ?: return null
        if (!gate.reads(app)) return null
        if (notification.groupSummary) return null
        val style = notification.style ?: return null
        if (style.group && !gate.groups) return null
        val pkg = notification.packageName
        val conversation = conversationOf(notification, style) ?: return null
        val thread = PhoneKeys.thread(pkg, conversation)
        val title = if (style.group) style.conversationTitle.nonBlank().orEmpty() else ""
        val messages = style.messages.mapNotNull { m ->
            val text = clip(m.text.trim(), MAX_TEXT)
            if (text.isEmpty()) return@mapNotNull null
            val own = isUser(m.person, style.user)
            val sender = if (own) "" else PhoneKeys.sender(pkg, m.person?.senderKey ?: conversation)
            val time = if (m.time > 0) m.time else notification.postTime
            PhoneMessage(
                id = PhoneKeys.id(pkg, thread, sender, time, text),
                app = app.code,
                thread = thread,
                title = title,
                group = style.group,
                sender = sender,
                name = if (own) "" else m.person?.name.nonBlank().orEmpty(),
                text = text,
                time = time,
                own = own,
            )
        }
        return PhoneReadingResult(app, thread, style.group, messages)
    }

    /**
     * L'action « Répondre » parmi celles d'une notification : une saisie libre (`RemoteInput` qui l'accepte), de
     * préférence déclarée comme réponse (`SEMANTIC_ACTION_REPLY`) ; `null` s'il n'y en a pas.
     */
    fun pickReply(actions: List<ActionShape>): Int? {
        val free = actions.withIndex().filter { it.value.freeFormInputs > 0 }
        return (free.firstOrNull { it.value.semanticAction == SEMANTIC_ACTION_REPLY } ?: free.firstOrNull())?.index
    }

    private fun conversationOf(n: PostedNotification, style: PostedStyle): String? =
        n.shortcutId.nonBlank()
            ?: n.tag.nonBlank()
            ?: style.conversationTitle.nonBlank()
            ?: style.messages.firstOrNull { !isUser(it.person, style.user) }?.person?.let { it.name.nonBlank() ?: it.senderKey }

    /**
     * Le message est-il de la personne elle-même ? Sans expéditeur, oui (la convention de `MessagingStyle`) ; sinon,
     * s'il est la `user` du style : même clé, ou — sans clé de part et d'autre — même nom et même adresse.
     */
    internal fun isUser(person: PostedPerson?, user: PostedPerson?): Boolean {
        if (person == null) return true
        if (user == null) return false
        val pk = person.key.nonBlank()
        val uk = user.key.nonBlank()
        if (pk != null || uk != null) return pk == uk
        val name = person.name.nonBlank() ?: return false
        return name == user.name.nonBlank() && person.uri.nonBlank() == user.uri.nonBlank()
    }

    /** Coupé à [max] caractères, jamais au milieu d'une paire de substitution (un émoji). */
    internal fun clip(text: String, max: Int): String {
        if (text.length <= max) return text
        var end = max
        if (Character.isHighSurrogate(text[end - 1])) end--
        return text.substring(0, end)
    }
}

internal fun String?.nonBlank(): String? = this?.trim()?.takeIf { it.isNotEmpty() }
