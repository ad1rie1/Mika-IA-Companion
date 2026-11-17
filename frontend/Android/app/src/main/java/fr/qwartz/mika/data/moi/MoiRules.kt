package fr.qwartz.mika.data.moi

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.text.Normalizer
import java.util.UUID

/*
 * Les règles pures que les domaines de l'API par personne partagent (Mail, Teams…), portées du client web sans les
 * réinventer : ce qu'un niveau de partage ouvre, un nom en français, ce que le serveur compte d'un texte, un passage
 * « [À COMPLÉTER », le ton d'une marque, un refus en mots, la clé d'envoi d'un geste. Tout se teste sur la JVM.
 */

// ── Les niveaux (ADR 0188) ──────────────────────────────────────────────

/** Son niveau sur une ressource (une boîte, un compte Teams) : la sienne, ou ce qu'on lui en partage (ADR 0188). */
object Levels {
    const val OWNER = "proprietaire"
    const val USE = "servir"
    const val PREPARE = "preparer"
    const val READ = "lire"
}

/** Ce qu'un niveau ouvre. */
data class Caps(
    /** La sienne : la régler, décider de ses brouillons. */
    val own: Boolean,
    /** « Préremplir avec Mika » (ses brouillons attendent alors l'accord du propriétaire). */
    val prepare: Boolean,
    /** Écrire, répondre, transférer, ranger. */
    val write: Boolean,
    /** Décider de ses brouillons : le propriétaire seulement. */
    val decide: Boolean,
)

/** La sienne, tout ; `servir`, comme elle sauf décider ; `preparer`, préremplir ; `lire` (ou l'inconnu), lire. */
fun caps(level: String): Caps {
    val own = level == Levels.OWNER
    val write = own || level == Levels.USE
    return Caps(own = own, prepare = write || level == Levels.PREPARE, write = write, decide = own)
}

/** L'étiquette courte d'un partage ; vide pour la sienne. */
fun levelTag(level: String): String = when (level) {
    Levels.READ -> "lecture seule"
    Levels.PREPARE -> "préparer"
    Levels.USE -> "s'en servir"
    else -> ""
}

/** Le prénom : « Adrien Moreau » → « Adrien ». */
fun firstName(full: String): String = full.trim().split(Regex("\\s+")).firstOrNull().orEmpty()

/** « de Léa », « d'Adrien », « d'Hélène » : l'élision devant une voyelle ou un h muet ; vide pour un nom vide. */
fun ofName(name: String): String {
    val n = name.trim()
    if (n.isEmpty()) return ""
    val first = unaccented(n).firstOrNull()?.lowercaseChar() ?: return "de $n"
    return if (first in "aeiouyh") "d'$n" else "de $n"
}

// ── Ce que le serveur compte ────────────────────────────────────────────

/** Ce qu'en compte le serveur (`len` en Python) : des caractères, pas des unités UTF-16 (un emoji compte pour un). */
fun chars(text: String): Int = text.codePointCount(0, text.length)

/** « 20 000 » : les milliers séparés d'une espace, comme en français. */
fun thousands(n: Int): String = n.toString().reversed().chunked(3).joinToString(" ").reversed()

// ── Le texte à compléter ────────────────────────────────────────────────

private val TO_FILL = Regex("""\[\s*(?:a\s*)?(?:completer|remplir|preciser)\b""")
private val BRACKETED = Regex("""\[[^\]\n]{0,300}(?:\]|$)""", RegexOption.MULTILINE)

/** Sans accents ni casse, les ligatures et les crochets pleine chasse dépliés (comme `kernel/text.py::fold`). */
internal fun fold(text: String): String =
    Normalizer.normalize(text, Normalizer.Form.NFKD).replace(Regex("\\p{M}+"), "").lowercase().replace("œ", "oe").replace("æ", "ae")

private fun unaccented(text: String): String =
    Normalizer.normalize(text, Normalizer.Form.NFD).replace(Regex("\\p{M}+"), "")

/** Reste-t-il un « [À COMPLÉTER » (sous toutes ses graphies, comme `ports/drafts.py::to_fill`) ? */
fun toFill(vararg texts: String): Boolean = texts.any { TO_FILL.containsMatchIn(fold(it)) }

/** Les passages à compléter d'un texte (pour les surligner) : chaque `[…]` qui en est un. */
fun toFillRanges(text: String): List<IntRange> =
    BRACKETED.findAll(text).filter { toFill(it.value) }.map { it.range }.toList()

// ── Les marques ─────────────────────────────────────────────────────────

/** Le ton d'une marque : neutre, ce qui attend, ce qui est fait, ce qui a échoué, ce qui part, ce qui est à elle. */
enum class Tone { NEUTRAL, WARN, OK, DANGER, INFO, MIKA }

// ── Les refus ───────────────────────────────────────────────────────────

private val FIELD_LABEL = mapOf(
    "to" to "À", "cc" to "Cc", "bcc" to "Cci", "files" to "Pièces", "subject" to "Objet", "body" to "Message",
    "instruction" to "Consigne", "note" to "Note", "q" to "Recherche", "box" to "Boîte", "folder" to "Dossier",
    "conversation" to "Discussion", "reply_to" to "Réponse à",
)

/** Le texte d'un refus : son message, et ce qu'il dit champ par champ — le champ seul quand le message ne fait que le
 *  nommer (« « body » : 20000 caractères au plus. » devient « Message : 20000 caractères au plus »). */
fun refusalText(message: String, fields: Map<String, String>): String {
    if (fields.isEmpty()) return message
    val said = fields.entries.joinToString(" · ") { (k, v) -> "${FIELD_LABEL[k] ?: k} : $v" }
    return if (fields.keys.any { "« $it »" in message }) said else "$message ($said)"
}

// ── Les écritures ───────────────────────────────────────────────────────

/** Le corps JSON d'une écriture : un booléen et un nombre restent tels, le reste devient une chaîne. */
internal fun jsonOf(fields: List<Pair<String, Any>>): JsonObject = JsonObject(
    fields.associate { (k, v) ->
        k to when (v) {
            is Boolean -> JsonPrimitive(v)
            is Number -> JsonPrimitive(v)
            else -> JsonPrimitive(v.toString())
        }
    },
)

/** Une lecture, mise sous une autre forme ; un refus reste un refus. */
fun <T, R> MoiApi.Result<T>.map(f: (T) -> R): MoiApi.Result<R> = when (this) {
    is MoiApi.Result.Ok -> MoiApi.Result.Ok(f(value))
    is MoiApi.Result.Failed -> this
}

// ── La clé d'envoi d'un geste ───────────────────────────────────────────

/**
 * La clé d'envoi d'un geste (`Idempotency-Key`, protocole § 1) : un double appui ne part qu'une fois. La même clé
 * revient tant que le geste n'a pas eu de réponse du serveur et que ce qu'il envoie n'a pas changé (le réseau a
 * coupé : on ne sait pas s'il est parti, le redire ne le refait pas) ; une réponse du serveur, ou un autre contenu,
 * en donne une neuve — un refus consomme la clé côté serveur, la redire répondrait « déjà envoyé ».
 */
class SendKey(private val fresh: () -> String = { UUID.randomUUID().toString() }) {
    private var key: String? = null
    private var content: Any? = null

    fun of(sending: Any): String {
        val known = key
        if (known != null && content == sending) return known
        return fresh().also {
            key = it
            content = sending
        }
    }

    /** Le serveur a répondu (fait ou refusé) : le prochain geste a sa propre clé. Une coupure du réseau garde celle-ci. */
    fun settled(networkFailure: Boolean) {
        if (!networkFailure) {
            key = null
            content = null
        }
    }
}
