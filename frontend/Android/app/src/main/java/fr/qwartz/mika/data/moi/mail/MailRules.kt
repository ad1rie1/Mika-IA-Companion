package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.caps
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.firstName
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.thousands
import fr.qwartz.mika.data.moi.toFill

/*
 * Les règles de Mail, pures (portées de `frontendv2/src/screens/mail/format.ts` et `markup.ts`, sans les réinventer) :
 * ce qu'un niveau de partage ouvre, le nom d'une boîte partagée, les vues de la liste, à qui répondre, ce qui peut
 * partir et ce qu'on peut joindre. Tout se teste sur la JVM.
 */

/** Les bornes que l'API tient (`app/domains/mail/api.py`, en caractères) : au-delà, elle refuse — elle ne coupe jamais. */
object MailLimits {
    const val RECIPIENTS = 300
    const val SUBJECT = 200
    const val BODY = 20_000
    const val NOTE = 500
    const val INSTRUCTION = 4000
    const val SEARCH = 200
    const val CONTACTS = 100

    /** Ce qu'un mail qu'on écrit peut joindre (ADR 0214). */
    const val PIECES = 10
    const val PIECE_BYTES = 25L * 1024 * 1024
    const val PIECES_BYTES = 50L * 1024 * 1024
}

// ── Les boîtes (ADR 0188) ───────────────────────────────────────────────

/** Le nom qu'on montre d'une boîte : la sienne, son nom ; partagée, « Boîte de Léa » (ADR 0188), son nom en plus si la
 *  même personne en partage plusieurs. */
fun boxTitle(box: MailBox, all: List<MailBox> = emptyList()): String {
    if (box.own || box.ownerName.isBlank()) return box.name.ifBlank { box.address }
    val first = firstName(box.ownerName)
    val same = all.count { !it.own && it.ownerName == box.ownerName }
    return if (same > 1) "${box.name} ${ofName(first)}" else "Boîte ${ofName(first)}"
}

/** Ce qu'un partage permet, en une phrase (le bandeau d'une boîte partagée). */
fun shareSentence(level: String, owner: String): String {
    val who = owner.ifBlank { "son propriétaire" }
    return when (level) {
        Levels.READ -> "partagée avec toi en lecture seule : tu la lis, sans y répondre ni la ranger."
        Levels.PREPARE -> "partagée avec toi en lecture et préparation : tu la lis, et Mika peut t'y préparer des réponses, que $who approuve."
        Levels.USE -> "partagée avec toi pour t'en servir : tu y réponds et tu la ranges ; ses brouillons, c'est $who qui en décide."
        else -> ""
    }
}

/** Les siennes d'abord, puis celles qu'on lui partage. */
fun orderedBoxes(boxes: List<MailBox>): List<MailBox> = boxes.filter { it.own } + boxes.filterNot { it.own }

/** Les boîtes des vues communes : une boîte qu'on ne lui partage qu'en lecture n'y entre pas (ADR 0200). */
fun commonBoxes(boxes: List<MailBox>): List<MailBox> = boxes.filter { it.level != Levels.READ }

/** Les boîtes d'où elle peut écrire elle-même (un mail nouveau). */
fun writableBoxes(boxes: List<MailBox>): List<MailBox> = orderedBoxes(boxes).filter { caps(it.level).write && it.canSend }

// ── Les dossiers ────────────────────────────────────────────────────────

private val ROLE_ORDER = listOf("inbox", "sent", "drafts", "archive", "junk", "trash")

/** La réception d'une boîte : son dossier `inbox`, sinon celui qui s'appelle `INBOX`. */
fun inboxOf(box: MailBox): MailFolder? = box.folders.firstOrNull { it.role == "inbox" } ?: box.folders.firstOrNull { it.name == INBOX }

/** Les non-lus de sa réception. */
fun unseenOf(box: MailBox): Int = inboxOf(box)?.unseen ?: 0

/** Ses dossiers dans l'ordre de la maquette : réception, envoyés, brouillons, archives, indésirables, corbeille, puis
 *  les autres dans l'ordre du serveur. */
fun orderedFolders(box: MailBox): List<MailFolder> =
    box.folders.sortedBy { f -> ROLE_ORDER.indexOf(f.role).let { if (it < 0) ROLE_ORDER.size else it } }

/** Où « Déplacer » range des mails d'une boîte (ADR 0200) : ses dossiers, sauf celui où ils sont déjà, « Envoyés » et
 *  « Brouillons » (l'app y montre ce qui est parti et ses brouillons à elle). */
fun moveTargets(box: MailBox, current: String): List<MailFolder> =
    orderedFolders(box).filter { it.name != current && it.role != "sent" && it.role != "drafts" }

/** Le dossier de réception que la vue commune lit (comme le client web). */
const val INBOX = "INBOX"

// ── Les vues de la liste ────────────────────────────────────────────────

/** Ce que montre la liste : toutes les réceptions, un dossier d'une boîte, ou ce qui en est parti. */
sealed interface MailView {
    data object All : MailView
    data class Folder(val box: String, val folder: String) : MailView
    data class Sent(val box: String) : MailView

    val boxKey: String? get() = when (this) {
        All -> null
        is Folder -> box
        is Sent -> box
    }
}

/** Le filtre d'une liste : un seul état à la fois (l'API n'en prend qu'un, `state`). */
object MailStates {
    const val ALL = ""
    const val NEEDS_REPLY = "needs_reply"
    const val UNREAD = "unread"
    const val FLAGGED = "flagged"
    const val NOTICED = "noticed"
}

/** La vue qu'ouvre un dossier : « Envoyés » montre ce qui est parti ; « Brouillons » (ses brouillons à elle) n'est pas
 *  une vue de la liste (`null` : l'écran « Ses brouillons »). */
fun viewOf(box: MailBox, folder: MailFolder): MailView? = when (folder.role) {
    "sent" -> MailView.Sent(box.key)
    "drafts" -> null
    else -> MailView.Folder(box.key, folder.name)
}

/** La vue d'une boîte : sa réception. */
fun inboxView(box: MailBox): MailView = MailView.Folder(box.key, inboxOf(box)?.name ?: INBOX)

/**
 * Les paramètres de `GET /mail/messages` pour une vue, son filtre et sa recherche. Toutes les réceptions lisent
 * `INBOX` de chaque boîte commune ; « Suivis » et « Réponse attendue » y valent pour tous les dossiers (comme les vues
 * du client web). Une boîte nommée se lit à son dossier, même partagée en lecture (ADR 0200).
 */
fun messagesQuery(view: MailView, state: String, q: String, page: Int, size: Int): Map<String, String?> {
    val (box, folder) = when (view) {
        MailView.All -> null to (if (state == MailStates.FLAGGED || state == MailStates.NEEDS_REPLY) null else INBOX)
        is MailView.Folder -> view.box to view.folder
        is MailView.Sent -> view.box to null
    }
    return linkedMapOf(
        "box" to box,
        "folder" to folder,
        "state" to state.ifEmpty { null },
        "q" to q.trim().ifEmpty { null },
        "page" to page.toString(),
        "size" to size.toString(),
    )
}

/** Le titre d'une vue : toutes les réceptions, une boîte (sa réception), un dossier, ses envoyés. */
fun viewTitle(view: MailView, boxes: List<MailBox>): String {
    val box = view.boxKey?.let { key -> boxes.firstOrNull { it.key == key } }
    val title = box?.let { boxTitle(it, boxes) } ?: view.boxKey.orEmpty()
    return when (view) {
        MailView.All -> "Toutes les réceptions"
        is MailView.Sent -> "Envoyés"
        is MailView.Folder -> {
            val f = box?.folders?.firstOrNull { it.name == view.folder }
            if (f == null || f.role == "inbox" || f.name == INBOX) title else f.shown
        }
    }
}

/** Ses brouillons qui attendent une décision que tu peux prendre (dans tes boîtes, ou celle de la vue). */
fun waitingYours(boxes: List<MailBox>, view: MailView = MailView.All): Int =
    boxes.filter { it.own && (view.boxKey == null || it.key == view.boxKey) }.sumOf { it.draftsWaiting }

/** Les non-lus de toutes les réceptions — sans les boîtes qu'on ne te partage qu'en lecture (ADR 0200). */
fun allUnseen(boxes: List<MailBox>): Int = commonBoxes(boxes).sumOf { unseenOf(it) }

/** Plusieurs boîtes dans la vue : chaque ligne dit la sienne. */
fun manyBoxes(view: MailView, boxes: List<MailBox>): Boolean = view == MailView.All && commonBoxes(boxes).size > 1

/** Les gestes de « ranger » qui sortent un mail de son dossier. */
private val LEAVING = setOf("archive", "trash", "move")

/** Une ligne se glisse vers la corbeille là où la barre de rangement la rangerait : dans une boîte où tu écris (pas
 *  celle qu'on ne te partage qu'en lecture), hors de la corbeille elle-même. */
fun swipeTrashable(row: MailRow, box: MailBox?): Boolean {
    if (box == null || !caps(box.level).write) return false
    return box.folders.firstOrNull { it.name == row.folder }?.role != "trash"
}

/**
 * Les lignes montrées avec [row] remise (« Annuler » une corbeille) : à sa place par sa date, la plus récente d'abord.
 * Déjà là, rien ne change ; plus vieille que toutes et la liste pas lue jusqu'au bout ([complete] faux), elle est dans
 * une page pas encore lue : elle y reviendra.
 */
fun restoredRows(rows: List<MailRow>, row: MailRow, complete: Boolean): List<MailRow> {
    if (rows.any { it.ref == row.ref }) return rows
    val at = rows.indexOfFirst { it.date < row.date }
    if (at < 0) return if (complete) rows + row else rows
    return rows.take(at) + row + rows.drop(at)
}

/** Ce qu'un geste de « ranger » change aux lignes montrées, sans tout relire : archivées, à la corbeille ou déplacées,
 *  elles s'en vont ; lues, non lues, suivies ou plus, elles changent. */
fun tidiedRows(rows: List<MailRow>, refs: Set<String>, gesture: String): List<MailRow> {
    if (gesture in LEAVING) return rows.filterNot { it.ref in refs }
    return rows.map { r ->
        if (r.ref !in refs) {
            r
        } else {
            when (gesture) {
                "read" -> r.copy(seen = true)
                "unread" -> r.copy(seen = false)
                "flag" -> r.copy(flagged = true)
                "unflag" -> r.copy(flagged = false)
                else -> r
            }
        }
    }
}

/** Combien des lignes montrées un geste a pu ôter de la vue du serveur : celles qui s'en vont ; sous un filtre, celles
 *  qui changent d'état (lues sous « Non lus »…), que la liste garde jusqu'à sa relecture. */
fun leftView(rows: List<MailRow>, refs: Set<String>, gesture: String, filter: String): Int =
    if (gesture in LEAVING || filter != MailStates.ALL) rows.count { it.ref in refs } else 0

/**
 * La page (de [size] lignes) où reprendre la liste après [read] lignes montrées, dont [drift] ont pu quitter la vue
 * du serveur depuis qu'elle a été lue d'un coup : elle commence au plus tard à la première ligne pas encore lue — rien
 * ne tombe entre deux pages ; ce qui revient en double s'écarte.
 */
fun nextPage(read: Int, drift: Int, size: Int): Int = (read - drift).coerceAtLeast(0) / size + 1

// ── Les personnes et les adresses ───────────────────────────────────────

fun sameAddress(a: String, b: String): Boolean = a.trim().equals(b.trim(), ignoreCase = true)

/** « Nom <adresse> » tel qu'il se relit (un nom qui porte une virgule ou des guillemets est cité). */
fun addressText(p: MailPerson): String {
    if (p.name.isBlank() || sameAddress(p.name, p.address)) return p.address
    val name = if (Regex("""[,;:<>@()\[\]"\\]""").containsMatchIn(p.name)) {
        "\"" + p.name.replace(Regex("""["\\]""")) { "\\" + it.value } + "\""
    } else {
        p.name
    }
    return "$name <${p.address}>"
}

/** Les destinataires d'un en-tête : « A <a@x>, "B, C" <b@x>, c@x » ; une entrée sans @ est écartée. */
fun parseAddresses(field: String): List<MailPerson> {
    val out = mutableListOf<MailPerson>()
    val part = StringBuilder()
    var quoted = false
    var angle = false
    fun flush() {
        val raw = part.toString().trim()
        part.clear()
        if (raw.isEmpty()) return
        val m = Regex("""^(.*?)<([^<>]+)>\s*$""").find(raw)
        val address = (m?.groupValues?.get(2) ?: raw).trim()
        if ('@' !in address) return
        var name = m?.groupValues?.get(1)?.trim().orEmpty()
        if (name.length >= 2 && name.startsWith('"') && name.endsWith('"')) {
            name = name.substring(1, name.length - 1).replace(Regex("""\\(.)"""), "$1")
        }
        out += MailPerson(name, address.lowercase())
    }
    var i = 0
    while (i < field.length) {
        val c = field[i]
        if (c == '\\' && quoted) {
            part.append(c)
            if (i + 1 < field.length) part.append(field[i + 1])
            i += 2
            continue
        }
        when {
            c == '"' -> quoted = !quoted
            c == '<' && !quoted -> angle = true
            c == '>' && !quoted -> angle = false
        }
        if ((c == ',' || c == ';') && !quoted && !angle) flush() else part.append(c)
        i++
    }
    flush()
    return out
}

/** Une liste sans doublon d'adresse, dans l'ordre ; [without] : des adresses à écarter. */
fun uniquePeople(people: List<MailPerson>, without: List<String> = emptyList()): List<MailPerson> {
    val seen = without.map { it.lowercase() }.toMutableSet()
    val out = mutableListOf<MailPerson>()
    for (p in people) {
        val key = p.address.lowercase()
        if (key.isEmpty() || !seen.add(key)) continue
        out += p
    }
    return out
}

/** On y répond (l'API aussi) : un mail reçu, ou une copie reçue d'un mail parti de ta boîte ; un mail parti sans copie
 *  reçue se transfère (`/mail/reply` : 409). */
fun answerable(m: MailFull): Boolean = !m.sent || m.received

/** À qui répondre : l'adresse de réponse, sinon l'expéditeur (un mail parti : ses destinataires) ; à tous, les autres
 *  en copie, sans la boîte elle-même. */
fun replyTargets(m: MailFull, boxAddress: String, all: Boolean): Pair<List<MailPerson>, List<MailPerson>> {
    val replyTo = parseAddresses(m.replyTo)
    val first = if (m.sent) m.to else replyTo.ifEmpty { listOf(m.from) }
    val to = uniquePeople(first.filter { it.address.isNotBlank() }, if (m.sent) listOf(boxAddress) else emptyList()).toMutableList()
    if (to.isEmpty() && m.from.address.isNotBlank()) to += m.from
    if (!all) return to to emptyList()
    val cc = uniquePeople((if (m.sent) emptyList() else listOf(m.from)) + m.to + m.cc, listOf(boxAddress) + to.map { it.address })
    return to to cc
}

/** « à toi <a@x>, Léa <l@x> +2 » : à qui le mail est allé, la boîte elle-même dite « toi » (ou du prénom de son
 *  propriétaire, pour une boîte qu'on te partage). */
fun toLine(m: MailFull, box: MailBox?): String {
    fun who(p: MailPerson): String {
        if (box == null || !sameAddress(p.address, box.address)) return p.shown
        return if (box.own) "toi" else firstName(box.ownerName).ifBlank { p.shown }
    }
    val people = m.to.ifEmpty { if (box != null) listOf(MailPerson("", box.address)) else emptyList() }
    if (people.isEmpty()) return ""
    val shown = people.take(3).joinToString(", ") { "${who(it)} <${it.address}>" }
    return "à $shown" + if (people.size > 3) " +${people.size - 3}" else ""
}

/** « Re: … » une fois, pas deux. */
fun replySubject(subject: String): String {
    val s = subject.trim()
    return if (Regex("""^(re|ré|aw|sv)\s*:""", RegexOption.IGNORE_CASE).containsMatchIn(s)) s else "Re: $s"
}

/** « Tr : … » une fois, pas deux. */
fun forwardSubject(subject: String): String {
    val s = subject.trim()
    return if (Regex("""^(tr|fw|fwd)\s*:""", RegexOption.IGNORE_CASE).containsMatchIn(s)) s else "Tr : $s"
}

// ── Les bornes d'un envoi ───────────────────────────────────────────────

/** Au plus [max] caractères, terminé d'une ellipse au besoin (l'objet dérivé « Re: … », qu'on ne tape pas). */
fun clip(text: String, max: Int): String {
    if (chars(text) <= max) return text
    val end = text.offsetByCodePoints(0, max - 1)
    return text.substring(0, end) + "…"
}

/** Les destinataires d'un en-tête dans leur borne : « Nom <adresse> » quand tout tient, sinon leurs seules adresses —
 *  aucun ne se perd ; `null` : même nues, elles la dépassent. */
fun recipientsText(people: List<MailPerson>, max: Int = MailLimits.RECIPIENTS): String? {
    val named = people.joinToString(", ") { addressText(it) }
    if (chars(named) <= max) return named
    val bare = people.joinToString(", ") { it.address }
    return if (chars(bare) <= max) bare else null
}

/** Ce qui part au serveur : les destinataires en en-têtes, l'objet, le corps. */
data class Outgoing(val to: String, val cc: String = "", val bcc: String = "", val subject: String, val body: String)

/** Un mail prêt à partir, ou pourquoi il ne peut pas partir tel quel (une phrase à dire sous le formulaire). */
data class Checked(val mail: Outgoing?, val problem: String = "")

/** Ce qu'un envoi doit avoir, et dans les bornes de l'API : le serveur refuserait de toute façon, rien ne part coupé.
 *  [bodyRequired] : faux pour un transfert ; [fillChecked] : un « [À COMPLÉTER » reste-t-il bloquant ici. */
fun checkOutgoing(
    to: List<MailPerson>,
    cc: List<MailPerson>,
    bcc: List<MailPerson>,
    subject: String,
    body: String,
    bodyRequired: Boolean = true,
    fillChecked: Boolean = true,
): Checked {
    if (to.isEmpty()) return Checked(null, "À qui ? Ajoute au moins un destinataire.")
    if (subject.isBlank()) return Checked(null, "Il lui faut un objet.")
    if (bodyRequired && body.isBlank()) return Checked(null, "Le message est vide.")
    if (fillChecked && toFill(subject, body)) return Checked(null, "Il reste des passages [À COMPLÉTER] à remplir.")
    fun crowded(field: String) = Checked(
        null,
        "Trop de destinataires dans « $field » : même sans leurs noms, leurs adresses dépassent " +
            "${thousands(MailLimits.RECIPIENTS)} caractères. Envoie-le en plusieurs fois.",
    )
    val toText = recipientsText(to) ?: return crowded("À")
    val ccText = recipientsText(cc) ?: return crowded("Cc")
    val bccText = recipientsText(bcc) ?: return crowded("Cci")
    val s = chars(subject)
    if (s > MailLimits.SUBJECT) {
        return Checked(null, "L'objet est trop long : ${thousands(MailLimits.SUBJECT)} caractères au plus (il en a ${thousands(s)}).")
    }
    val b = chars(body)
    if (b > MailLimits.BODY) {
        return Checked(null, "Le message est trop long : ${thousands(MailLimits.BODY)} caractères au plus (il en a ${thousands(b)}).")
    }
    return Checked(Outgoing(toText, ccText, bccText, subject.trim(), body))
}

// ── Les pièces d'un mail qu'on écrit ────────────────────────────────────

/** Ce qu'il faut savoir d'une pièce pour la borner : son nom et sa taille. */
interface Sized {
    val name: String
    val size: Long
}

/** Ce qui s'ajoute, et le premier refus en mots (les autres fichiers choisis passent quand même). */
data class Pieces<T : Sized>(val pieces: List<T>, val problem: String = "")

private fun megabytes(bytes: Long): String = "${bytes / (1024 * 1024)} Mo"

/**
 * Ceux de [picked] qui s'ajoutent à [current] dans les bornes de l'API ; le même fichier choisi deux fois (nom et
 * taille) ne compte qu'une fois. [carried] : les pièces d'origine d'un transfert, comptées dans le nombre et le total.
 */
fun <T : Sized> addPieces(current: List<T>, picked: List<T>, carried: List<Sized> = emptyList()): Pieces<T> {
    val pieces = current.toMutableList()
    var total = carried.sumOf { it.size } + pieces.sumOf { it.size }
    val also = if (carried.isNotEmpty()) ", celles du mail d'origine comprises" else ""
    var problem = ""
    for (file in picked) {
        if (pieces.any { it.name == file.name && it.size == file.size }) continue
        val refused = when {
            file.size <= 0 -> "« ${file.name} » est vide."
            file.size > MailLimits.PIECE_BYTES -> "« ${file.name} » est trop grosse : ${megabytes(MailLimits.PIECE_BYTES)} par pièce."
            pieces.size + carried.size >= MailLimits.PIECES -> "Un mail porte au plus ${MailLimits.PIECES} pièces$also."
            total + file.size > MailLimits.PIECES_BYTES ->
                "Ces pièces sont trop lourdes pour un seul mail : ${megabytes(MailLimits.PIECES_BYTES)} en tout$also."
            else -> ""
        }
        if (refused.isNotEmpty()) {
            if (problem.isEmpty()) problem = refused
            continue
        }
        pieces += file
        total += file.size
    }
    return Pieces(pieces, problem)
}

// ── Ses brouillons ──────────────────────────────────────────────────────

/** L'état d'un de ses brouillons, en mots, et son ton. */
fun draftState(d: MailDraft): Pair<Tone, String> {
    val (tone, label) = when (d.state) {
        DraftStates.WAITING -> Tone.WARN to (if (d.decides) "attend ton accord" else "attend son propriétaire")
        DraftStates.APPROVED -> Tone.INFO to "approuvé, en partance"
        DraftStates.SENT -> Tone.OK to "parti"
        DraftStates.REFUSED -> Tone.NEUTRAL to "refusé"
        DraftStates.FAILED -> Tone.DANGER to "échec de l'envoi"
        else -> Tone.NEUTRAL to d.state
    }
    val edited = d.edited && (d.state == DraftStates.SENT || d.state == DraftStates.APPROVED)
    return tone to (if (edited) "$label · retouché par toi" else label)
}

/** Il ne peut pas partir tel quel : ce que dit l'aperçu, ou un passage à compléter. */
fun draftBlocked(d: MailDraft): String = d.preview?.blocked?.takeIf { it.isNotBlank() }
    ?: if (d.waiting && d.toFill) "il reste des passages à compléter" else ""

/** Ce que devient ta réponse partie d'un de ses brouillons, d'après ce qu'il est devenu entre-temps. */
sealed interface DraftReply {
    /** Il attend : ta version passe par lui (elle apprendra ce que tu y as changé). */
    data class Through(val draft: MailDraft) : DraftReply

    /** Refusé, ou plus là : ta réponse part comme une réponse ordinaire. */
    data object Plain : DraftReply

    /** Parti, approuvé ou en échec : rien de plus ne part, [why] dit pourquoi. */
    data class Stop(val why: String) : DraftReply
}

/**
 * Ta réponse partie de son brouillon [id], d'après ses brouillons relus tels qu'ils sont (pas seulement ceux qui
 * attendent). Seul un brouillon refusé ou absent laisse partir une réponse ordinaire : parti (une réponse du serveur
 * perdue, puis ta retouche ; ou envoyé d'ailleurs), approuvé ou en échec, une seconde réponse partirait.
 */
fun draftReply(drafts: List<MailDraft>, id: String): DraftReply {
    val d = drafts.firstOrNull { it.id == id } ?: return DraftReply.Plain
    return when (d.state) {
        DraftStates.WAITING -> DraftReply.Through(d)
        DraftStates.REFUSED -> DraftReply.Plain
        else -> DraftReply.Stop(draftNotWaiting(d.state))
    }
}

/** Pourquoi rien ne part par un de ses brouillons qui n'attend plus ([state] : ce qu'il est devenu). */
fun draftNotWaiting(state: String): String = when (state) {
    DraftStates.SENT, DraftStates.APPROVED -> "Son brouillon est déjà parti."
    DraftStates.FAILED -> "L'envoi de son brouillon a échoué : regarde « Ses brouillons »."
    else -> "Son brouillon n'attend plus de décision : rien n'est parti."
}

/** Comment elle y écrit, en mots. */
fun voiceLabel(voice: String): String = when (voice) {
    "proprietaire" -> "à ta place"
    "assistante" -> "en assistante"
    "elle" -> "en son nom"
    else -> ""
}

/** Ses destinataires, à leur nom quand la boîte le connaît. */
fun draftPeople(d: MailDraft): List<MailPerson> =
    d.toPeople.ifEmpty { parseAddresses(d.preview?.to?.ifBlank { null } ?: d.to) }
        .ifEmpty { if (d.to.isBlank()) emptyList() else listOf(MailPerson(d.to, d.to)) }

/** Les filtres de « Ses brouillons ». */
enum class DraftFilter { WAITING, SENT, REFUSED }

fun DraftFilter.holds(d: MailDraft): Boolean = when (this) {
    DraftFilter.WAITING -> d.waiting
    DraftFilter.SENT -> d.state == DraftStates.SENT || d.state == DraftStates.APPROVED
    DraftFilter.REFUSED -> d.state == DraftStates.REFUSED || d.state == DraftStates.FAILED
}

/** Ce qu'elle en a fait, en mots : « lu par Mika », « archivé par Mika »… et le geste. */
fun howLabel(how: String): Pair<String, String> {
    val verb = if (how.isBlank() || how == "lu") "lu" else how
    val kind = when {
        verb.startsWith("archiv") -> "archive"
        verb == "corbeille" || verb == "supprimé" -> "trash"
        verb == "répondu" -> "reply"
        else -> "eye"
    }
    return (if (verb == "corbeille") "mis à la corbeille par Mika" else "$verb par Mika") to kind
}

// ── Son tri ─────────────────────────────────────────────────────────────

/** Où en est son tri d'un mail (le champ `triage` d'une ligne et du mail entier). */
enum class Triage {
    /** Son tri (le modèle) l'a lu. */
    READ,

    /** Remarqué, mais jugé par le seul repli (le modèle en panne, ou son quota) : son importance est devinée. */
    GUESSED,

    /** Un envoi en masse : remarqué sans être lu par le modèle, par choix. */
    BULK,

    /** Dans un dossier qu'elle relève, pas encore trié : il attend le relevé suivant. */
    WAITING,
    ;

    companion object {
        /** `null` : rien à dire (vide — un mail d'avant sa boîte, un autre dossier, un envoi —, ou une valeur inconnue). */
        fun of(value: String): Triage? = when (value) {
            "read" -> READ
            "guessed" -> GUESSED
            "bulk" -> BULK
            "waiting" -> WAITING
            else -> null
        }
    }
}

/** La marque de son tri sur une ligne de la liste : lu, en attente, deviné ; un envoi en masse n'en porte pas. */
fun triageMark(triage: String): Triage? = Triage.of(triage)?.takeIf { it != Triage.BULK }

/**
 * Le cadre « Ce qu'elle en sait » de la liseuse paraît : elle en a retenu, remarqué ou lu quelque chose, ou on lui a
 * demandé une réponse ([asked]) ; et même sans rien de cela, quand son tri ne l'a pas encore lu ou n'a fait que deviner
 * (il le dit), ou quand tes consignes de tri en ont fait quelque chose ([byRules]).
 */
fun knowsShown(her: HerMark?, triage: String, asked: Boolean): Boolean {
    val t = Triage.of(triage)
    if (t == Triage.WAITING || t == Triage.GUESSED || byRules(her) != null) return true
    return her != null && (her.summary.isNotBlank() || her.noticed || her.read || asked)
}

/** Ce que tes consignes de tri ont fait d'un mail (ADR 0243) : te prévenir ([alert]), le ranger dans [filed] (vide :
 *  pas rangé, ou plus là). */
data class ByRules(val alert: Boolean, val filed: String)

/** Ce que tes consignes de tri en ont fait, à dire dans le cadre « Ce qu'elle en sait » ; le dossier se nomme comme sa
 *  boîte le montre (son nom, s'il n'est pas connu). `null` : rien. */
fun byRules(her: HerMark?, box: MailBox? = null): ByRules? {
    if (her == null) return null
    val filed = her.filed.trim()
    if (!her.alert && filed.isEmpty()) return null
    val shown = if (filed.isEmpty()) "" else box?.folders?.firstOrNull { it.name == filed }?.shown ?: filed
    return ByRules(her.alert, shown)
}

/** Ce que dit le titre du cadre « Ce qu'elle en sait », après lui. */
sealed interface KnowsState {
    /** Ce qu'elle en a fait (`how` : « lu », « archivé »…). */
    data class Did(val how: String) : KnowsState

    /** Où en est son tri, à la place de « remarqué ». */
    data class Sorted(val triage: Triage) : KnowsState

    data object Noticed : KnowsState

    data object None : KnowsState
}

/** Ce qu'elle en a fait passe d'abord ; sinon où en est son tri ; sinon « remarqué », si elle l'a remarqué. */
fun knowsState(her: HerMark?, triage: String): KnowsState {
    if (her?.read == true) return KnowsState.Did(her.how)
    val t = Triage.of(triage)
    return when {
        t != null -> KnowsState.Sorted(t)
        her?.noticed == true -> KnowsState.Noticed
        else -> KnowsState.None
    }
}

/** Ce que le cadre en dit de plus : pas encore lu par son tri, ou son importance devinée ; `null` : rien. */
fun triageNote(triage: String): Triage? = Triage.of(triage)?.takeIf { it == Triage.WAITING || it == Triage.GUESSED }

/** Le cœur d'un brouillon en une ligne : le paragraphe après la formule d'appel. */
fun bodyLead(body: String): String {
    val paras = body.split(Regex("""\n\s*\n""")).map { it.replace(Regex("""\s+"""), " ").trim() }.filter { it.isNotEmpty() }
    if (paras.isEmpty()) return ""
    return if (paras.size > 1 && paras[0].length < 60) paras[1] else paras[0]
}
