package fr.qwartz.mika.data.chat

import fr.qwartz.mika.data.net.AttachmentRef
import fr.qwartz.mika.data.net.HistoryEntry
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.RejectedAttachment
import fr.qwartz.mika.data.net.Timestamps
import fr.qwartz.mika.data.net.ToolUse
import kotlinx.serialization.Serializable
import java.util.concurrent.atomic.AtomicInteger

/**
 * Réconcilier ce que l'écran montre avec ce que le serveur garde — portage fonction par fonction de
 * `frontend/Web/src/ui/chatSync.ts`. Des fonctions pures sur une liste de messages, à part de toute
 * vue et de toute base : c'est ici qu'est la substance (une fusion à trois cas et un ordre total),
 * `ChatStore` ne fait que charger et écrire autour.
 */

enum class Sender { USER, MIKA }

/**
 * Ce qu'est devenu un message envoyé : `PENDING` (peint ici, encore dans la file d'envoi), `SENT`
 * (le serveur l'a reçu — pas forcément répondu), `FAILED` (refusé : il ne sera jamais répondu).
 */
enum class MessageStatus { PENDING, SENT, FAILED }

/** Une pièce jointe d'un message, dans un sens ou dans l'autre. */
@Serializable
data class MessageAttachment(
    val name: String,
    /** `image` | `audio` | `file` */
    val kind: String = "file",
    val mime: String? = null,
    val size: Long? = null,
    /** Un fichier de Mika : son identifiant et sa route de téléchargement (`/files/<id>`). */
    val id: String? = null,
    val url: String? = null,
    val available: Boolean? = null,
    /** Un fichier envoyé d'ici : son nom sur le disque, sous le dossier de son message (`OutboxFiles`). */
    val local: String? = null,
) {
    companion object {
        fun of(ref: AttachmentRef) =
            MessageAttachment(ref.name, ref.kind, ref.mime, ref.size, ref.id, ref.url, ref.available)
    }
}

/**
 * Un message du fil. Mutable comme son modèle TypeScript : les fonctions de [ChatSync] le modifient
 * en place, et `ChatStore` compare avant/après pour n'écrire que ce qui a changé.
 */
data class StoredMessage(
    var text: String,
    val sender: Sender,
    var ts: Long,
    /** L'identifiant serveur ; le plus haut présent est le curseur de synchronisation. */
    var id: Long? = null,
    /** L'identifiant de corrélation de nos propres bulles. */
    var cid: String? = null,
    var status: MessageStatus? = null,
    /** Ce qui a été tapé, quand la bulle montre autre chose (`texte [photo.png]`). */
    var matchText: String? = null,
    /** Pourquoi un message a échoué, en français. */
    var reason: String? = null,
    /** Ce que le serveur a écarté d'un envoi accepté, affiché sous la bulle. */
    var note: String? = null,
    /** Où ranger un message qui n'aura jamais d'identifiant : juste après ce curseur. */
    var after: Long? = null,
    /** Pensée murmurée pour elle-même : jamais en base, affichée en italique. */
    var inner: Boolean = false,
    /** La réponse ne viendra pas (`no_reply`) : dit sous la bulle, le message restant envoyé. */
    var replyNote: String? = null,
    var replyHref: String? = null,
    /** `asleep` : elle dort, la réponse attend son réveil. `seen` : elle l'a lu et a choisi de se taire. */
    var waiting: String? = null,
    // ── Propres à l'app ──
    /** La clé locale (Room) ; 0 tant que le message n'est pas écrit. */
    var localId: Long = 0,
    var attachments: List<MessageAttachment> = emptyList(),
    var source: String? = null,
    var emotion: String? = null,
    var emotionIntensity: Double? = null,
    /** L'avis de l'opératrice sur cette réponse (ADR 0113, `ok` | `ko`), et ce qu'elle aurait dû dire. */
    var verdict: String? = null,
    var verdictNote: String? = null,
    /** `pro` : écrit en mode pro (ADR 0116) — gardé à l'envoi pour ses messages, dit par le serveur pour les siens. */
    var mode: String? = null,
    /** Une réponse pro : les outils dont elle s'est servie, tels que l'historique les dit (`null` : rien de dit). */
    var tools: List<ToolUse>? = null,
) {
    val isPro: Boolean get() = mode == MikaProtocol.CHAT_MODE_PRO
}

object ChatSync {

    /**
     * Pourquoi un message a été refusé. Un statut absent d'ici reste un refus (un client ne doit
     * jamais lire un statut inconnu comme un succès), avec la formule générique. Recopiés tels quels
     * du client web.
     */
    val ACK_REASONS: Map<String, String> = mapOf(
        "rate_limited" to "trop de messages d'affilée",
        "empty" to "message vide",
        "overloaded" to "Mika est saturée, réessaie dans un instant",
        "too_long" to "message trop long",
        "attachments_rejected" to "pièces jointes refusées (format ou taille)",
        "frame_too_large" to "envoi trop volumineux — retire une pièce jointe",
        "send_abandoned" to "envoi abandonné après plusieurs tentatives",
        "unauthorized" to "session expirée — reconnecte-toi",
    )

    /** Refus que seule l'app peut constater (ils n'atteignent jamais le serveur). */
    private val APP_ACK_REASONS: Map<String, String> = mapOf(
        MikaProtocol.ACK_CONNECTION_REFUSED to "le serveur refuse la connexion",
        MikaProtocol.ACK_FILES_MISSING to "fichiers introuvables sur le téléphone",
    )

    fun ackReason(status: String): String =
        ACK_REASONS[status] ?: APP_ACK_REASONS[status] ?: "refusé par le serveur"

    /** Pourquoi une pièce jointe n'est pas passée (`protocol.py::validate_attachments`). */
    private val REJECT_REASONS: Map<String, String> = mapOf(
        "too_large" to "trop volumineux",
        "too_many" to "au-delà de la limite de pièces jointes",
        "invalid" to "illisible",
    )

    fun rejectedNote(rejected: List<RejectedAttachment>): String {
        val noms = rejected.joinToString(", ") { "${it.name} (${REJECT_REASONS[it.reason] ?: "refusé"})" }
        return "Non transmis à Mika : $noms"
    }

    private val cidCounter = AtomicInteger(0)

    /** Un identifiant de corrélation par message — `c<ms en base 36>-<n>`, unique dans ce processus. */
    fun nextClientMsgId(nowMs: Long): String = "c${nowMs.toString(36)}-${cidCounter.incrementAndGet()}"

    private val PROSODY = Regex("""\[(?:PAUSE(?::\d+)?|SIGH|LAUGH|BREATH)]""", RegexOption.IGNORE_CASE)
    private val EMOTION_TAG = Regex("""\[EMOTION:[^\]]*]""", RegexOption.IGNORE_CASE)
    private val SPACES = Regex("""[ \t]{2,}""")
    private val SPACE_BEFORE_PUNCT = Regex(""" +([,.!?;:])""")

    /**
     * Les jetons de prosodie (`[SIGH]`, `[PAUSE:400]`…) sont des indications pour la voix, jamais à
     * montrer. Mange aussi l'espace français légitime avant `! ? ; :` — comportement du web, gardé tel
     * quel parce qu'il décide de la lecture de chaque bulle.
     */
    fun stripProsody(text: String): String = text
        .replace(PROSODY, " ")
        .replace(EMOTION_TAG, " ")
        .replace(SPACES, " ")
        .replace(SPACE_BEFORE_PUNCT, "$1")
        .trim()

    /** Le mode d'un message tel qu'on le garde : `pro`, ou `null` (toute autre valeur vaut « ordinaire »). */
    fun modeOf(raw: String?): String? = raw?.takeIf { it == MikaProtocol.CHAT_MODE_PRO }

    /**
     * Le texte qu'une bulle d'elle montre. Une réponse pro (ADR 0116) ne passe pas par [stripProsody] : elle
     * n'est jamais lue à voix haute, et resserrer ses espaces casserait l'indentation de ses blocs de code.
     */
    fun mikaText(text: String, mode: String?): String =
        if (modeOf(mode) != null) text.trim() else stripProsody(text)

    /** Le plus haut identifiant serveur reçu : dérivé du fil, jamais tenu à part. */
    fun cursorOf(history: List<StoredMessage>): Long {
        var max = 0L
        for (m in history) {
            val id = m.id
            if (id != null && id > max) max = id
        }
        return max
    }

    /**
     * L'ordre chronologique, avec les identifiants serveur pour autorité : les horloges du téléphone
     * et du serveur ne s'accordent pas. Sans identifiant, un message est le plus récent (il n'est pas
     * encore écrit) ; un message qui n'en aura jamais se range juste après le curseur noté à son
     * arrivée.
     */
    private fun orderKey(m: StoredMessage): Double {
        m.id?.let { return it.toDouble() }
        m.after?.let { return it + 0.5 }
        return Double.POSITIVE_INFINITY
    }

    private val ORDER = Comparator<StoredMessage> { a, b ->
        val ka = orderKey(a)
        val kb = orderKey(b)
        if (ka != kb) ka.compareTo(kb) else a.ts.compareTo(b.ts)
    }

    /** Trie en place (tri stable, comme `Array.prototype.sort`) et rend la même liste. */
    fun sortMessages(history: MutableList<StoredMessage>): MutableList<StoredMessage> {
        history.sortWith(ORDER)
        return history
    }

    fun coerceStatus(raw: String?): MessageStatus? = when (raw) {
        "sent" -> MessageStatus.SENT
        "pending" -> MessageStatus.PENDING
        "failed" -> MessageStatus.FAILED
        else -> null
    }

    /** Pourquoi une bulle restée « en attente d'envoi » ne l'est plus après un redémarrage. */
    const val RESTORED_PENDING_REASON = "non envoyé — l'application a été fermée"

    data class Restored(val status: MessageStatus?, val reason: String? = null)

    /**
     * Ce qu'un statut relu au démarrage doit devenir. Contrairement au navigateur, la file d'envoi
     * survit ici à la mort du processus (table `outbox`) : un `PENDING` qui y a sa ligne partira à la
     * prochaine connexion. Sans ligne, plus rien ne le ferait avancer : il devient un échec, avec sa
     * raison, plutôt que d'afficher « en attente d'envoi » pour toujours.
     */
    fun restoredStatus(raw: String?, hasOutbox: Boolean): Restored {
        val status = coerceStatus(raw)
        if (status == MessageStatus.PENDING && !hasOutbox) {
            return Restored(MessageStatus.FAILED, RESTORED_PENDING_REASON)
        }
        return Restored(status)
    }

    const val NO_REPLY = MikaProtocol.ACK_NO_REPLY

    /** La note posée sous la bulle quand la réponse ne viendra pas. */
    fun noReplyNote(reason: String? = null, detail: String? = null): String {
        val base = if (reason == "too_late") {
            "Mika n'a pas pu répondre à temps — redis-le-lui si c'est encore d'actualité."
        } else {
            "Mika n'a pas pu répondre — réessaie."
        }
        val cause = detail?.trim().orEmpty()
        return if (cause.isNotEmpty()) "$base ($cause)" else base
    }

    private val CONSOLE_HREF = Regex("""^/inspecteur/[\w\-/]*$""")

    /** Une page de la console, et rien d'autre : un lien sous une bulle ne mène jamais ailleurs. */
    fun consoleHref(href: String?): String? = href?.takeIf { CONSOLE_HREF.matches(it) }

    data class AckResult(val changed: Boolean, val failed: Boolean, val settled: Boolean)

    /**
     * Ce que le serveur dit d'un message envoyé. `failed` : refusé, il ne l'a jamais reçue.
     * `settled` : aucune réponse ne viendra (un refus, ou un `no_reply` sur un message reçu).
     */
    fun applyAck(
        history: List<StoredMessage>,
        cid: String,
        status: String,
        rejected: List<RejectedAttachment>? = null,
        reason: String? = null,
        detail: String? = null,
        href: String? = null,
    ): AckResult {
        val msg = history.firstOrNull { it.cid == cid } ?: return AckResult(false, false, false)
        if (status == NO_REPLY || status == "too_late") {
            msg.status = MessageStatus.SENT
            msg.reason = null
            msg.waiting = null
            msg.replyNote = noReplyNote(if (status == "too_late") "too_late" else reason, detail)
            msg.replyHref = consoleHref(href)
            return AckResult(changed = true, failed = false, settled = true)
        }
        val failed = status != MikaProtocol.ACK_ACCEPTED
        msg.status = if (failed) MessageStatus.FAILED else MessageStatus.SENT
        msg.reason = if (failed) ackReason(status) else null
        msg.note = if (!rejected.isNullOrEmpty()) rejectedNote(rejected) else null
        return AckResult(changed = true, failed = failed, settled = failed)
    }

    const val ASLEEP = "asleep"
    const val ASLEEP_NOTE = "Mika dort — elle te répondra à son réveil."

    /** Une trame `speech` sans texte, `voice_reason: "asleep"` : la réponse attend son réveil. */
    fun markAsleep(history: List<StoredMessage>, cid: String): Boolean {
        val msg = history.firstOrNull { it.cid == cid } ?: return false
        if (msg.waiting == ASLEEP) return false
        msg.waiting = ASLEEP
        return true
    }

    const val SEEN = "seen"

    /**
     * Une trame `speech` sans texte, `voice_reason: "silence"` : elle l'a lu et n'a rien ajouté — la
     * bulle se voit « lu », comme dans une messagerie. Si c'était une panne, l'accusé `no_reply` qui
     * suit l'efface ([applyAck]) : une réponse impossible n'est pas une lecture.
     */
    fun markSeen(history: List<StoredMessage>, cid: String): Boolean {
        val msg = history.firstOrNull { it.cid == cid } ?: return false
        if (msg.waiting == SEEN) return false
        msg.waiting = SEEN
        return true
    }

    /** La note de sommeil ne vaut que tant qu'elle n'a rien dit depuis (un murmure ne compte pas). */
    fun asleepNoteShown(history: List<StoredMessage>, index: Int): Boolean {
        val msg = history.getOrNull(index) ?: return false
        if (msg.waiting != ASLEEP) return false
        return history.subList(index + 1, history.size).none { it.sender == Sender.MIKA && !it.inner }
    }

    /**
     * Rattacher l'identifiant serveur à la bulle à laquelle une réponse répond. Si un rattrapage a déjà
     * posé ce message à part (une bulle qu'il n'a pas reconnue), cette ligne se fond dans la bulle : deux
     * lignes au même identifiant feraient échouer l'index unique, et toute l'écriture de la réponse avec.
     */
    fun bindServerId(history: MutableList<StoredMessage>, cid: String, userId: Long?): Boolean {
        val msg = history.firstOrNull { it.cid == cid } ?: return false
        val twin = userId?.let { id -> history.firstOrNull { it !== msg && it.id == id } }
        if (twin != null && twin.sender == Sender.USER) {
            history.remove(twin)
            msg.ts = twin.ts
        }
        // Un identifiant déjà tenu par une réponse d'elle n'est pas celui de la question : on ne le pose pas.
        if (userId != null && (twin == null || twin.sender == Sender.USER)) msg.id = userId
        msg.status = MessageStatus.SENT
        msg.waiting = null
        return true
    }

    /** La longueur d'un nom de fichier gardé par le serveur (`protocol.py::FILENAME_MAX`), en points de code. */
    private const val FILENAME_MAX = 80
    private val FILENAME_CONTROL = Regex("""[\x00-\x1f\x7f]+""")
    /** Les blancs que `str.split()` coupe en Python, au-delà de ceux de `\s` (U+00A0, U+202F…). */
    private val FILENAME_BLANKS = Regex("""[\s\u0085   -     　]+""")

    /**
     * Un nom de fichier tel que le serveur le garde (`protocol.py::sanitize_filename`) : contrôles en espaces,
     * blancs fusionnés, 80 points de code, `fichier` s'il est vide. Appliqué avant l'envoi, il rend la bulle
     * identique à la ligne que l'historique relira — sans quoi elle n'est jamais adoptée. Le blanc qu'une
     * coupure laisse au bout part aussi : le serveur le retirerait en relisant ce nom.
     */
    fun fileName(name: String): String {
        val text = FILENAME_BLANKS.replace(FILENAME_CONTROL.replace(name, " "), " ").trim(' ').ifEmpty { "fichier" }
        if (text.codePointCount(0, text.length) <= FILENAME_MAX) return text
        return text.substring(0, text.offsetByCodePoints(0, FILENAME_MAX)).trimEnd(' ')
    }

    /** `texte [a.png, b.pdf]`, ou `[a.png]` sans légende : la même composition à l'envoi et à la relecture. */
    fun withAttachments(text: String, names: List<String>): String {
        val label = names.filter { it.isNotEmpty() }.joinToString(", ")
        if (label.isEmpty()) return text
        return if (text.isNotEmpty()) "$text [$label]" else "[$label]"
    }

    /**
     * Cette ligne du serveur appartient-elle à une bulle peinte ici ? L'égalité exacte de ce qui est
     * montré, ou — pour une bulle de la personne — ce qui a été tapé (`matchText`), qui adopte encore
     * une bulle dont un fichier n'est pas passé. Jamais une bulle sans légende : rien où s'ancrer.
     */
    private fun matches(msg: StoredMessage, display: String, typed: String): Boolean {
        if (msg.text == display) return true
        if (msg.sender != Sender.USER || msg.matchText.isNullOrEmpty()) return false
        return typed == msg.matchText
    }

    data class MergeResult(
        val history: MutableList<StoredMessage>,
        val added: Int,
        val adopted: Int,
        val sawReply: Boolean,
        /** Ses réponses déjà là dont l'avis a changé (donné d'un autre appareil, ADR 0113). */
        val judged: Int = 0,
        /** Des lignes déjà là dont le mode ou les outils ont été dits par le serveur (ADR 0116). */
        val reworked: Int = 0,
    )

    /** L'avis d'une ligne du fil, tel que le serveur le dit (`null` : pas d'avis). */
    private fun verdictOf(entry: HistoryEntry): Pair<String?, String?> {
        val verdict = entry.verdict?.takeIf { it == MikaProtocol.VERDICT_OK || it == MikaProtocol.VERDICT_KO }
        return verdict to entry.verdictNote?.takeIf { verdict != null && it.isNotEmpty() }
    }

    const val VERDICT_NOT_SENT = "Hors ligne : ton avis n'est pas parti."

    /** Ce qu'un refus d'avis veut dire, en français. */
    fun verdictError(status: String): String = when (status) {
        "forbidden" -> "Seule une opératrice peut juger ses réponses."
        "invalid" -> "Ce message ne peut pas être jugé (il a peut-être été oublié)."
        else -> "L'avis n'a pas été enregistré : réessaie."
    }

    /** Un clic sur 👍 ou 👎 : l'avis choisi, ou retiré (vide) si c'était déjà le sien. */
    fun nextVerdict(current: String?, clicked: String): String = if (current == clicked) "" else clicked

    /** Pose l'avis sur sa réponse [messageId] ; `false` si elle n'est pas dans le fil. */
    fun applyVerdict(thread: List<StoredMessage>, messageId: Long, verdict: String, note: String): Boolean {
        val m = thread.firstOrNull { it.id == messageId && it.sender == Sender.MIKA } ?: return false
        m.verdict = verdict.ifEmpty { null }
        m.verdictNote = note.trim().takeIf { verdict.isNotEmpty() && it.isNotEmpty() }
        return true
    }

    /**
     * Fondre la version du serveur dans ce qui est montré. Trois cas par ligne reçue : déjà là (par
     * identifiant) → ignorée ; correspond à une bulle peinte ici sans identifiant → elle l'adopte ;
     * sinon → nouvelle. Trie, et ne garde que les [maxMessages] plus récents.
     */
    fun mergeHistory(
        history: MutableList<StoredMessage>,
        entries: List<HistoryEntry>?,
        maxMessages: Int,
        nowMs: Long = System.currentTimeMillis(),
    ): MergeResult {
        val known = history.mapNotNullTo(HashSet()) { it.id }
        var added = 0
        var adopted = 0
        var sawReply = false
        var judged = 0
        var reworked = 0

        for (entry in entries.orEmpty()) {
            val id = entry.id ?: continue
            if (id in known) {
                // une ligne déjà là ne change pas — sauf l'avis de l'opératrice, qui peut venir d'un autre appareil
                val shown = if (entry.role == MikaProtocol.ROLE_USER) null else history.firstOrNull { it.id == id }
                val (verdict, note) = verdictOf(entry)
                if (shown != null && (shown.verdict != verdict || shown.verdictNote != note)) {
                    shown.verdict = verdict
                    shown.verdictNote = note
                    judged += 1
                }
                // …et son mode et ses outils (ADR 0116) : une réponse reçue en direct n'apprend ses outils qu'ici
                if (rework(history.firstOrNull { it.id == id }, entry)) reworked += 1
                continue
            }
            val sender = if (entry.role == MikaProtocol.ROLE_USER) Sender.USER else Sender.MIKA
            val typed = entry.text
            val text = if (sender == Sender.MIKA) {
                mikaText(typed, entry.mode)
            } else {
                withAttachments(typed, entry.attachments.map { it.name })
            }
            if (text.isEmpty()) continue

            if (sender == Sender.MIKA) sawReply = true
            val ts = entry.ts?.let { Timestamps.normalize(it, nowMs) }

            val mine = history.firstOrNull { it.id == null && it.sender == sender && matches(it, text, typed) }
            if (mine != null) {
                mine.id = id
                mine.ts = ts ?: mine.ts
                if (sender == Sender.USER) {
                    mine.status = MessageStatus.SENT
                    mine.reason = null
                }
                rework(mine, entry)
                adopted += 1
            } else {
                history.add(
                    StoredMessage(
                        text = text,
                        sender = sender,
                        ts = ts ?: nowMs,
                        id = id,
                        status = if (sender == Sender.USER) MessageStatus.SENT else null,
                        attachments = entry.attachments.map(MessageAttachment::of),
                        source = entry.source,
                        emotion = entry.emotion?.takeIf { it.isNotEmpty() },
                        emotionIntensity = entry.emotionIntensity,
                        verdict = if (sender == Sender.MIKA) verdictOf(entry).first else null,
                        verdictNote = if (sender == Sender.MIKA) verdictOf(entry).second else null,
                        mode = modeOf(entry.mode),
                        tools = toolsOf(entry, sender),
                    ),
                )
                added += 1
            }
            known.add(id)
        }

        sortMessages(history)
        val out = if (history.size > maxMessages) {
            history.subList(history.size - maxMessages, history.size).toMutableList()
        } else {
            history
        }
        return MergeResult(out, added, adopted, sawReply, judged, reworked)
    }

    /** Les outils d'une ligne : seulement pour une réponse pro d'elle (ADR 0116). */
    private fun toolsOf(entry: HistoryEntry, sender: Sender): List<ToolUse>? =
        entry.tools?.takeIf { sender == Sender.MIKA && modeOf(entry.mode) != null }

    /**
     * Le mode et les outils d'une ligne déjà montrée, tels que le serveur les dit (il est la référence : un
     * message qu'il n'a pas reçu en mode pro ne l'est pas). Des outils absents de la ligne ne retirent pas ceux
     * qu'on connaît déjà. `true` si quelque chose a changé.
     */
    private fun rework(shown: StoredMessage?, entry: HistoryEntry): Boolean {
        if (shown == null) return false
        val mode = modeOf(entry.mode)
        val tools = toolsOf(entry, shown.sender) ?: shown.tools.takeIf { mode != null }
        if (shown.mode == mode && shown.tools == tools) return false
        shown.mode = mode
        shown.tools = tools
        return true
    }

    // ── Le fil d'une autre vie (ADR 0056) ──

    /**
     * Ce que montre l'écran vient-il d'une autre vie que celle qui parle ? Oui quand le serveur le dit
     * (`reset`), ou quand son empreinte n'est pas celle gardée ici (y compris une empreinte vide :
     * un fil d'avant l'empreinte). Un serveur qui n'envoie pas d'empreinte ne fait rien vider.
     */
    fun fromAnotherLife(cachedLife: String, life: String?, reset: Boolean?): Boolean {
        if (reset == true) return true
        return !life.isNullOrEmpty() && life != cachedLife
    }

    /** Ce qui survit au changement de vie : les messages encore en partance, rien d'autre. */
    fun keepAcrossLives(history: List<StoredMessage>): MutableList<StoredMessage> =
        history.filterTo(mutableListOf()) {
            it.sender == Sender.USER && it.id == null && it.status == MessageStatus.PENDING
        }
}
