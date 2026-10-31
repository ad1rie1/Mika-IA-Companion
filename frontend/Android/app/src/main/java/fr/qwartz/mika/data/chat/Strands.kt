package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.StrandInfo
import kotlin.random.Random

/**
 * Les fils de travail du mode pro (ADR 0164), sans écran ni base — portage de `frontend/Web/src/ui/strands.ts` : un
 * identifiant neuf, la liste à montrer, le nom d'un fil, les commandes tapées dans le champ.
 *
 * En mode pro, la conversation devient un client à plusieurs fils, chacun son contexte, le fil avec Mika caché. Un fil
 * s'ouvre en choisissant un identifiant neuf et en y écrivant ; rien ne s'efface, un fil se range en l'archivant. Le
 * serveur ne connaît un fil qu'à son premier message (ou à son premier réglage) : jusque-là, il n'existe qu'ici.
 */
object Strands {
    /** Un réglage de fil qui n'a pas pu partir : la socket était fermée. */
    const val NOT_SENT = "Hors ligne : le fil n'a pas été réglé. Réessaie une fois reconnecté."

    /** Ce qu'un refus de réglage veut dire, en français. */
    fun resultNotice(status: String): String = when (status) {
        "forbidden" -> "Seule une opératrice peut régler ses fils de travail."
        "invalid" -> "Ce réglage n'a pas été accepté (un titre ou une description trop long ?)."
        else -> "Le fil n'a pas été réglé : réessaie."
    }

    fun isValidId(id: String?): Boolean = id != null && MikaProtocol.STRAND_ID.matches(id)

    /** Un identifiant neuf : `s`, l'instant en base 36, puis six caractères de hasard en base 36. */
    fun newId(nowMs: Long, random: Random = Random.Default): String {
        val noise = buildString { repeat(6) { append(ALPHABET[random.nextInt(ALPHABET.length)]) } }
        return "s${nowMs.coerceAtLeast(0).toString(36)}$noise"
    }

    private const val ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
    /** Le nom d'un fil sans titre, tiré de son premier message : au plus. */
    private const val LABEL_MAX = 48

    /**
     * Le nom d'un fil à l'écran : son titre, sinon le début de son premier message, sinon `null` (l'écran dit alors
     * « Nouveau fil », depuis ses ressources).
     */
    fun label(strand: StrandInfo?): String? {
        val title = strand?.title?.trim().orEmpty()
        if (title.isNotEmpty()) return title
        val opener = strand?.opener?.replace(Regex("\\s+"), " ")?.trim().orEmpty()
        if (opener.isEmpty()) return null
        return if (opener.length <= LABEL_MAX) opener else opener.take(LABEL_MAX - 1).trimEnd() + "…"
    }

    /**
     * Les fils à montrer, du plus récemment actif au plus ancien : la liste du serveur ([server]), et ceux qu'il ne
     * connaît pas encore — un fil ouvert ici sans encore rien dedans ([active]), un fil dont des messages sont déjà
     * là avant que sa liste n'arrive ([messages], nommé par son premier message). Un fil local que le serveur connaît
     * désormais prend sa ligne.
     */
    fun visible(
        server: List<StrandInfo>,
        messages: List<StoredMessage>,
        active: String?,
        nowMs: Long,
    ): List<StrandInfo> {
        val known = server.mapTo(HashSet()) { it.id }
        val local = LinkedHashMap<String, StrandInfo>()
        for (m in ChatSync.sortMessages(messages.toMutableList())) {
            val id = m.strand ?: continue
            if (id in known) continue
            val seen = local[id]
            local[id] = if (seen == null) {
                StrandInfo(id, count = 1, firstAt = m.ts, lastAt = m.ts,
                    opener = if (m.sender == Sender.USER) m.matchText ?: m.text else "")
            } else {
                seen.copy(count = seen.count + 1, lastAt = maxOf(seen.lastAt, m.ts),
                    opener = seen.opener.ifEmpty { if (m.sender == Sender.USER) m.matchText ?: m.text else "" })
            }
        }
        if (active != null && active !in known && active !in local) local[active] = StrandInfo(active, lastAt = nowMs)
        return (server + local.values).sortedWith(compareByDescending<StrandInfo> { it.lastAt }.thenBy { it.id })
    }

    /** Les messages d'un fil que ce téléphone a déjà ([strand]) — de quoi savoir s'il faut les demander. */
    fun localCount(messages: List<StoredMessage>, strand: String): Int = messages.count { it.strand == strand }

    // ── Les commandes du champ ──

    sealed interface Command {
        data object Clear : Command
        data class Rename(val title: String) : Command
        data class Describe(val text: String) : Command
        data object Archive : Command
        data object Unarchive : Command
        data object Help : Command
        data class Unknown(val typed: String) : Command
    }

    /** Ce que chaque commande fait, pour l'aide. */
    val HELP: List<String> = listOf(
        "/clear — ouvrir un fil neuf (l'actuel reste dans la liste)",
        "/renommer <titre> — donner un titre à ce fil",
        "/description <texte> — ce qu'elle relit en tête de ce fil",
        "/archiver — ranger ce fil",
        "/desarchiver — le sortir des archives",
        "/aide — ces commandes",
    )

    /**
     * Une commande tapée dans le champ (`/renommer Devis IN`), ou `null` pour un message ordinaire. Un `//` en tête
     * échappe : le message part avec un seul `/` ([unescape]), sans être lu comme une commande.
     */
    fun parse(text: String): Command? {
        val typed = text.trim()
        if (!typed.startsWith("/") || typed.startsWith("//")) return null
        val body = typed.substring(1)
        val head = body.split(Regex("\\s+"), limit = 2)[0]
        val arg = body.substring(head.length).trim()
        return when (head.lowercase()) {
            "clear", "nouveau" -> Command.Clear
            "renommer" -> Command.Rename(arg)
            "description" -> Command.Describe(arg)
            "archiver" -> Command.Archive
            "desarchiver", "désarchiver" -> Command.Unarchive
            "aide", "help" -> Command.Help
            else -> Command.Unknown("/$head")
        }
    }

    /** Le message à envoyer pour un texte qui commence par `//` : un seul `/`. */
    fun unescape(text: String): String {
        val typed = text.trimStart()
        return if (typed.startsWith("//")) typed.substring(1) else text
    }

    /** La note d'une commande inconnue. */
    fun unknownNotice(typed: String): String = "Commande inconnue : $typed — /aide pour la liste."
}
