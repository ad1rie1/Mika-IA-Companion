package fr.qwartz.mika.ui.chat

import androidx.annotation.DrawableRes
import fr.qwartz.mika.data.chat.StoredMessage
import fr.qwartz.mika.data.chat.Strands
import fr.qwartz.mika.data.net.StrandInfo
import fr.qwartz.mika.ui.Route
import java.text.Normalizer

/** Les puces de « Rechercher » : où chercher. */
enum class SearchChip { ALL, CHAT, MAIL, TEAMS, SCREENS }

/**
 * Un écran ou une page de l'app que la recherche propose : son titre (« Paramètres › Boîtes mail »), sa ligne, où il
 * mène ; [parent] : la rubrique à ouvrir d'abord (« retour » y ramène) ; [icon] ; [words] : d'autres mots qui y mènent.
 */
data class ScreenEntry(
    val title: String,
    val sub: String,
    val route: Route,
    val parent: Route? = null,
    @param:DrawableRes val icon: Int = 0,
    val words: String = "",
)

/** Un message de la conversation (ou d'un fil de travail) trouvé : [title] est le passage trouvé. */
data class MessageHit(val message: StoredMessage, val title: String, val strand: String?)

/** Un de ses fils de travail trouvé par son titre, sa description ou son premier message. */
data class StrandHit(val strand: StrandInfo, val title: String, val sub: String)

/**
 * « Rechercher » (le Ctrl K du frontendv2, `shell/palette.ts`, devenu un écran à puces) : ce qui se cherche où, et
 * comment se classe ce qui est trouvé. Sans accents ni casse ; un message se cherche dans tout son texte et montre le
 * passage trouvé ; dix par groupe au plus (des messages qui se ressemblent ne cachent pas le reste). Les messages : du
 * plus récent au plus ancien ; les écrans : le titre qui commence par ce qu'on cherche, puis un mot du titre, puis le
 * titre qui le contient, puis le reste (sa ligne, ses mots), chacun dans l'ordre du tiroir. Pur.
 */
object SearchRules {
    const val MAX_PER_GROUP = 10
    /** Mail et Teams ne se demandent au serveur qu'à partir de ce nombre de caractères, après une pause de frappe. */
    const val MIN_REMOTE_CHARS = 2
    const val DEBOUNCE_MS = 450L
    /** Ce que le serveur rend pour un groupe. */
    const val REMOTE_SIZE = 8
    private const val EXCERPT_WIDTH = 70
    private const val EXCERPT_BEFORE = 24
    private val MARKS = Regex("\\p{Mn}+")
    private val SPACES = Regex("\\s+")

    /** Sans accents ni casse, les espaces resserrées (`norm` de `shell/dom.ts`). */
    fun fold(text: String): String =
        MARKS.replace(Normalizer.normalize(text, Normalizer.Form.NFD), "").lowercase().replace(SPACES, " ").trim()

    /** La puce d'où l'on part : la loupe du chat cherche d'abord dans la conversation. */
    fun chipFor(scope: String): SearchChip = if (scope == "chat") SearchChip.CHAT else SearchChip.ALL

    fun showsChat(chip: SearchChip): Boolean = chip == SearchChip.ALL || chip == SearchChip.CHAT
    fun showsMail(chip: SearchChip): Boolean = chip == SearchChip.ALL || chip == SearchChip.MAIL
    fun showsTeams(chip: SearchChip): Boolean = chip == SearchChip.ALL || chip == SearchChip.TEAMS
    fun showsScreens(chip: SearchChip): Boolean = chip == SearchChip.ALL || chip == SearchChip.SCREENS

    /** Ce qui part au serveur : assez de caractères, et une puce qui le montre. */
    fun remoteQuery(query: String): String? = query.trim().replace(SPACES, " ").takeIf { it.length >= MIN_REMOTE_CHARS }

    /**
     * Les messages gardés sur le téléphone où se trouve [query] : ceux du fil avec elle ([strand] `null`), puis pour une
     * opératrice ceux de ses fils de travail — chacun le plus récent d'abord, dix au plus. Ni ses pensées à voix haute,
     * ni un message vide.
     */
    fun messages(all: List<StoredMessage>, query: String, operator: Boolean): Pair<List<MessageHit>, List<MessageHit>> {
        val q = fold(query)
        if (q.isEmpty()) return emptyList<MessageHit>() to emptyList()
        val found = all.asSequence()
            .filter { !it.inner && it.text.isNotBlank() && fold(it.text).contains(q) }
            .sortedByDescending { it.ts }
            .map { MessageHit(it, excerpt(it.text, q), it.strand) }
            .toList()
        val chat = found.filter { it.strand == null }.take(MAX_PER_GROUP)
        val strands = if (operator) found.filter { it.strand != null }.take(MAX_PER_GROUP) else emptyList()
        return chat to strands
    }

    /** Ses fils de travail dont le titre, la description ou le premier message parlent de [query] (une opératrice). */
    fun strands(all: List<StrandInfo>, query: String): List<StrandHit> {
        val q = fold(query)
        if (q.isEmpty()) return emptyList()
        return all.filter { fold("${Strands.label(it).orEmpty()} ${it.description} ${it.opener}").contains(q) }
            .take(MAX_PER_GROUP)
            .map { StrandHit(it, Strands.label(it).orEmpty(), it.description) }
    }

    /**
     * Les écrans et pages où [query] mène, classés ; sans rien de tapé, les rubriques du tiroir (les titres sans « › »).
     */
    fun screens(all: List<ScreenEntry>, query: String): List<ScreenEntry> {
        val q = fold(query)
        if (q.isEmpty()) return all.filter { "›" !in it.title }
        return all.mapIndexedNotNull { i, e -> rank(e, q)?.let { Triple(it, i, e) } }
            .sortedWith(compareBy({ it.first }, { it.second }))
            .take(MAX_PER_GROUP)
            .map { it.third }
    }

    /** 0 : le titre commence par ce qu'on cherche ; 1 : un de ses mots ; 2 : le titre le contient ; 3 : le reste ; `null` : rien. */
    private fun rank(e: ScreenEntry, q: String): Int? {
        val title = fold(e.title)
        // « Paramètres › Boîtes mail » : la page compte pour un titre à part entière
        val parts = listOf(title) + title.split("›").map { it.trim() }
        return when {
            parts.any { it.startsWith(q) } -> 0
            parts.any { p -> p.split(' ', '-', '\'', '’').any { it.startsWith(q) } } -> 1
            title.contains(q) -> 2
            fold("${e.sub} ${e.words}").contains(q) -> 3
            else -> null
        }
    }

    /**
     * Le passage de [text] où se trouve [q] (déjà replié par [fold]), d'environ 70 caractères, coupé entre deux mots,
     * « … » aux coupes (`palette.ts::excerpt`). Pas trouvé : le début du texte.
     */
    fun excerpt(text: String, q: String): String {
        val flat = text.replace(SPACES, " ").trim()
        val range = foldedRange(flat, q)
        if (range == null) return if (flat.length > EXCERPT_WIDTH) flat.take(EXCERPT_WIDTH - 1).trimEnd() + "…" else flat
        val (from, to) = range
        var start = maxOf(0, from - EXCERPT_BEFORE)
        if (start > 0) {
            val space = flat.indexOf(' ', start)
            if (space in 0 until from) start = space + 1
        }
        var end = maxOf(to, minOf(flat.length, start + EXCERPT_WIDTH))
        if (end < flat.length) {
            val space = flat.lastIndexOf(' ', end)
            if (space >= to) end = space
        }
        return (if (start > 0) "…" else "") + flat.substring(start, end).trim() + (if (end < flat.length) "…" else "")
    }

    /** Où [q] (déjà replié par [fold]) se trouve dans [text], pour le surligner ; absent : `null`. */
    fun matchRange(text: String, q: String): IntRange? = foldedRange(text, q)?.let { (from, to) -> from until to }

    /** Où [q] (déjà replié) commence et finit dans [text], en positions de [text] (fin exclue) ; absent : `null`. */
    private fun foldedRange(text: String, q: String): Pair<Int, Int>? {
        if (q.isEmpty()) return null
        val folded = StringBuilder()
        val starts = ArrayList<Int>()
        val ends = ArrayList<Int>()
        var i = 0
        while (i < text.length) {
            val cp = text.codePointAt(i)
            val len = Character.charCount(cp)
            val f = MARKS.replace(Normalizer.normalize(String(Character.toChars(cp)), Normalizer.Form.NFD), "").lowercase()
            for (k in f.indices) {
                starts += i
                ends += i + len
            }
            folded.append(f)
            i += len
        }
        val at = folded.indexOf(q)
        if (at < 0) return null
        return starts[at] to ends[at + q.length - 1]
    }
}
