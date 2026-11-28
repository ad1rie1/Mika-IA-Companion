package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.data.moi.MoiDates
import kotlinx.serialization.json.JsonObject
import java.time.ZoneId
import kotlin.math.floor
import kotlin.math.roundToInt

/*
 * L'onglet Code d'une fiche : ce qui se calcule sans écran, porté du client web (`frontend/Web/src/screens/projets/
 * codeparts.ts`, et ce que ses vues `views/code.ts`, `views/codehost.ts` composent en mots). Les volets et leurs
 * adresses, la coloration simple d'une ligne (des jetons de texte, jamais une mise en forme lue dans le fichier), la
 * mise en lignes d'un diff unifié, l'arborescence un dossier à la fois, et les requêtes d'une pull request : la
 * fusionner en nommant le commit de tête lu ([MergeOrder]), la modifier, y répondre.
 *
 * Aucune règle n'est refaite ici : ce qu'on peut faire vient du serveur (`merge.can`, `merge.why`, `rights`). Tout se
 * teste sur la JVM.
 */

// ── Les volets de l'onglet, les pages de détail ─────────────────────────

/** Les six volets de l'onglet Code, dans l'ordre de la maquette. */
object CodeTabs {
    const val FILES = "fichiers"
    const val COMMITS = "commits"
    const val PULLS = "pulls"
    const val BRANCHES = "branches"
    const val ISSUES = "issues"
    const val CI = "ci"

    val ALL = listOf(FILES, COMMITS, PULLS, BRANCHES, ISSUES, CI)

    /** Le volet que nomme une adresse ; inconnu ou vide : Fichiers. */
    fun of(sub: String): String = if (sub in ALL) sub else FILES

    /** L'onglet de la fiche ouvert sur ce volet (`code/pulls`). */
    fun tab(sub: String): String = "${SheetTabs.CODE}/$sub"

    /** Le compte que porte un volet dans sa barre ; `null` : pas de compte. */
    fun count(sub: String, c: CodeCounts): Int? = when (sub) {
        COMMITS -> c.commits
        PULLS -> c.pullsOpen
        BRANCHES -> c.branches
        ISSUES -> c.issuesOpen
        CI -> c.checksFailed.takeIf { it > 0 }
        else -> null
    }
}

/** Les pages de détail du code (`Route.ProjectCode.kind`) : chacune s'ouvre depuis la liste de son volet. */
object CodePages {
    const val FILE = "fichier"
    const val COMMIT = "commit"
    const val PULL = "pull"
    const val BRANCH = "branche"
    const val ISSUE = "issue"
    const val CHECKS = "ci"

    /** Le volet d'où vient une page : son retour, et son titre dans la barre. */
    fun home(kind: String): String = when (kind) {
        COMMIT -> CodeTabs.COMMITS
        PULL -> CodeTabs.PULLS
        BRANCH -> CodeTabs.BRANCHES
        ISSUE -> CodeTabs.ISSUES
        CHECKS -> CodeTabs.CI
        else -> CodeTabs.FILES
    }
}

/** Les volets d'une pull request ; « Infos » est ce que le web met dans son panneau latéral. */
object PullPanes {
    const val SUMMARY = "resume"
    const val COMMITS = "commits"
    const val FILES = "fichiers"
    const val TALK = "echanges"
    const val INFOS = "infos"

    fun of(pane: String): String = if (pane in listOf(COMMITS, FILES, TALK, INFOS)) pane else SUMMARY
}

/** La clé d'une pull request dans son adresse : son numéro ; `o<objectif>` tant qu'elle n'en a pas (proposée). */
fun pullKey(p: CodePull): String = if (p.number > 0) p.number.toString() else "o${p.objective?.id ?: 0}"

/** Ce que nomme la clé d'une pull request : son numéro, ou son objectif. */
data class PullName(val number: Int, val objective: Int)

fun parsePullKey(key: String): PullName {
    Regex("^o(\\d{1,9})$").matchEntire(key)?.let { return PullName(0, it.groupValues[1].toInt()) }
    return PullName(if (Regex("^\\d{1,9}$").matches(key)) key.toInt() else 0, 0)
}

// ── Les mots ────────────────────────────────────────────────────────────

/** Le texte d'un objet venu de l'hôte ; vide s'il n'y en a pas. */
fun hostText(x: OutsideText?): String = x?.text.orEmpty()

/** Le titre qu'on montre d'une pull request : le texte de son objectif, sinon celui que le moteur compose. */
fun pullTitle(p: CodePull): String = p.objective?.text?.takeIf { it.isNotBlank() } ?: p.title

/** Une pull request encore en cours chez l'hôte : ouverte, ou prête. */
fun pullLive(p: CodePull): Boolean = p.state == "open" || p.state == "ready"

/** La couleur d'une pull request : celle de son état ; ouverte avec une CI en échec, elle le montre. */
fun pullColor(p: CodePull): StateTone = if (p.state == "open" && p.checks?.state == "failed") StateTone.FAIL else pullTone(p.state)

fun reviewTone(r: CodeReview): StateTone = when (r.ok) {
    true -> StateTone.DONE
    false -> StateTone.FAIL
    null -> StateTone.WAIT
}

fun issueTone(state: String): StateTone = if (state == "closed") StateTone.DONE else StateTone.WAIT

/** Le titre qu'on montre d'une issue : celui de l'hôte si elle se lit, sinon pourquoi elle ne se lit pas, sinon son numéro. */
fun issueTitle(x: Issue): String = hostText(x.title).ifBlank { x.veiledLabel.ifBlank { "Issue n° ${x.number}" } }

/** D'où vient le texte d'une issue : publiée d'ici (sous quel compte), ou écrite chez l'hôte (par qui). */
fun issueSource(x: Issue): String {
    val who = hostText(x.account)
    return if (x.fromHere) "publiée d'ici" + (if (who.isBlank()) "" else ", sous le compte $who") else "${who.ifBlank { "quelqu'un" }}, chez l'hôte"
}

/** D'où vient un échange de l'hôte, et depuis quand : « netfan42, chez l'hôte · il y a 1 h ». */
fun remarkSource(x: Remark, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val who = hostText(x.account).ifBlank { "quelqu'un" }
    val from = if (x.fromHere) "publié d'ici, sous le compte $who" else "$who, chez l'hôte"
    return listOf(from, since(x.at, now, zone)).filter { it.isNotBlank() }.joinToString(" · ")
}

/** Ce qu'un commit concerne, en court : son ticket (`#5`), sinon son objectif (`obj. 2`). */
fun commitAbout(c: Commit): String = when {
    c.ticket != 0 -> "#${c.ticket}"
    c.objective != 0 -> "obj. ${c.objective}"
    else -> ""
}

/** Le message d'un commit sans sa première ligne (son titre) : ce qu'il dit de plus. */
fun messageRest(c: Commit): String = (if (c.body.startsWith(c.title)) c.body.substring(c.title.length) else c.body).trim()

/** L'avance et le retard d'une branche sur la base, en mots. */
fun aheadBehind(b: Branch, base: String): String =
    if (b.base) "la branche par défaut" else "${plural(b.ahead, "commit", "commits")} d'avance sur $base, ${b.behind} de retard"

/** Pour quoi une branche existe : son ticket, sinon son objectif. */
fun branchAbout(b: Branch): String = when {
    b.ticket != null -> "Ticket #${b.ticket.number}"
    b.objective != null -> "Objectif n° ${b.objective.id}"
    else -> ""
}

/** Une durée en secondes : « 45 s », « 12 min », « 1 h 05 ». */
fun duration(seconds: Double): String {
    if (seconds.isNaN() || seconds.isInfinite() || seconds <= 0) return ""
    if (seconds < 60) return "${seconds.roundToInt()} s"
    val minutes = (seconds / 60).roundToInt()
    return if (minutes < 60) "$minutes min" else "${minutes / 60} h ${(minutes % 60).toString().padStart(2, '0')}"
}

/** Les vérifications passées sur celles lancées : « 1/3 » ; vide sans vérification. */
fun runsPassed(runs: List<CheckRun>): String = if (runs.isEmpty()) "" else "${runs.count { it.state == "passed" }}/${runs.size}"

/** L'icône d'une vérification, d'après son état : un nom du jeu de la maquette. */
fun checkIcon(state: String): String = when (state) {
    "passed" -> "check"
    "failed" -> "x"
    "pending" -> "refresh"
    else -> "clock"
}

/** L'adresse d'un dépôt chez l'hôte, sans son schéma : ce qu'on en montre. */
fun hostName(web: String): String = safeLink(web).replace(Regex("^https?://", RegexOption.IGNORE_CASE), "")

/** Un fichier Markdown du dépôt : il peut se lire rendu, ou en source. */
fun isMarkdown(path: String): Boolean = Regex("\\.(md|markdown)$", RegexOption.IGNORE_CASE).containsMatchIn(path)

private val LANGUAGES = mapOf(
    "py" to "Python", "toml" to "TOML", "yml" to "YAML", "yaml" to "YAML", "md" to "Markdown", "json" to "JSON", "js" to "JavaScript",
    "ts" to "TypeScript", "tsx" to "TypeScript", "sh" to "Shell", "css" to "CSS", "html" to "HTML", "rs" to "Rust", "go" to "Go",
    "java" to "Java", "kt" to "Kotlin", "c" to "C", "h" to "C", "cpp" to "C++", "cs" to "C#", "txt" to "texte",
)

private fun extension(path: String): String = Regex("\\.([A-Za-z0-9]+)$").find(path)?.groupValues?.get(1)?.lowercase().orEmpty()

/** Le langage d'un fichier, d'après son extension ; « texte » sinon. */
fun languageOf(path: String): String = LANGUAGES[extension(path)] ?: "texte"

/** Un poids en octets, en mots : « 812 o », « 1,3 Ko », « 2,4 Mo ». */
fun sizeWords(bytes: Long): String {
    if (bytes < 0) return ""
    if (bytes < 1024) return "$bytes o"
    fun comma(n: Double): String = ((n * 10).roundToInt() / 10.0).let { if (it == floor(it)) it.toInt().toString() else it.toString().replace('.', ',') }
    return if (bytes < 1_048_576) "${comma(bytes / 1024.0)} Ko" else "${comma(bytes / 1_048_576.0)} Mo"
}

/** Les lignes d'un texte : la dernière, vide après un saut final, ne compte pas. */
fun linesOf(text: String): List<String> {
    val lines = text.replace("\r\n", "\n").replace('\r', '\n').split('\n')
    return if (lines.size > 1 && lines.last().isEmpty()) lines.dropLast(1) else lines
}

/** Ce qu'une ligne montre au plus : au-delà, elle est coupée à l'affichage (un fichier minifié), et l'écran le dit. */
const val LINE_SHOWN = 2000

/** Une ligne telle qu'on la pose à l'écran : ses tabulations en quatre espaces, coupée à [LINE_SHOWN] caractères. */
fun shownLine(text: String): String {
    val flat = text.replace("\t", "    ")
    return if (flat.length > LINE_SHOWN) flat.take(LINE_SHOWN) + " …" else flat
}

/**
 * Un fichier mis en lignes, une fois : ses lignes telles qu'on les pose ([lines]), la plus large (pour mesurer le cadre
 * où elles défilent, [widest]), et si l'une d'elles est coupée à l'affichage ([cut]).
 */
class FileLines(val lines: List<String>, val widest: String, val cut: Boolean)

fun fileLines(text: String): FileLines {
    if (text.isEmpty()) return FileLines(emptyList(), "", false)
    val raw = linesOf(text)
    val shown = raw.map(::shownLine)
    return FileLines(shown, widestLine(shown), anyLineCut(raw))
}

/** Une ligne au moins est coupée à l'affichage. */
fun anyLineCut(lines: List<String>): Boolean = lines.any { it.length > LINE_SHOWN }

/**
 * La ligne la plus large d'un texte en chasse fixe, pour mesurer le cadre où il défile : un caractère large (un
 * idéogramme, une émoticône) y compte double.
 */
fun widestLine(lines: List<String>): String = lines.maxByOrNull { line -> line.sumOf { c -> if (c.code >= 0x1100) 2L else 1L } }.orEmpty()

// ── Le code : une coloration simple ─────────────────────────────────────

/** La sorte d'un jeton d'une ligne de code. */
enum class TokenKind { PLAIN, COMMENT, STRING, DECORATOR, KEYWORD, NUMBER }

/** Un jeton d'une ligne : sa sorte et son texte. */
data class Token(val kind: TokenKind, val text: String)

private val RE_PY = Regex(
    "(#.*\$)|(\"\"\"[\\s\\S]*?\"\"\"|\"(?:[^\"\\\\]|\\\\.)*\"|'(?:[^'\\\\]|\\\\.)*')|(@\\w+)|\\b(def|class|import|from|return|if|elif|else|for|in|with|as|try|" +
        "except|raise|continue|not|and|or|is|lambda|None|True|False|pass|while|yield|async|await|break|finally|global|assert)\\b|\\b(\\d+(?:\\.\\d+)?)\\b",
)
private val RE_CONF = Regex("(#.*\$)|(\"(?:[^\"\\\\]|\\\\.)*\"|'(?:[^'\\\\]|\\\\.)*')|(^\\s*-?\\s*[\\w.-]+(?=\\s*[:=]))|(^\\[[\\w.-]+\\])|\\b(\\d+(?:\\.\\d+)?)\\b")
private val RE_C = Regex(
    "(//.*\$|/\\*.*?\\*/)|(\"(?:[^\"\\\\]|\\\\.)*\"|'(?:[^'\\\\]|\\\\.)*'|`(?:[^`\\\\]|\\\\.)*`)|(@\\w+)|\\b(const|let|var|function|return|if|else|for|while|do|switch|" +
        "case|break|continue|class|extends|implements|interface|type|enum|import|export|from|default|new|this|super|try|catch|finally|throw|async|await|static|" +
        "public|private|protected|readonly|void|null|undefined|true|false|typeof|instanceof|fn|pub|use|mod|struct|impl|trait|match|package|func|defer|val|fun|" +
        "namespace|using)\\b|\\b(\\d+(?:\\.\\d+)?)\\b",
)
private val CONF_EXT = setOf("toml", "yml", "yaml", "ini", "cfg", "sh", "bash", "env")
private val C_EXT = setOf("js", "mjs", "cjs", "ts", "tsx", "jsx", "json", "c", "h", "cpp", "java", "go", "rs", "cs", "kt", "swift", "php", "css")
private val TOKEN_KINDS = listOf(TokenKind.COMMENT, TokenKind.STRING, TokenKind.DECORATOR, TokenKind.KEYWORD, TokenKind.NUMBER)

private fun grammar(path: String): Regex? = when (extension(path)) {
    "py" -> RE_PY
    in CONF_EXT -> RE_CONF
    in C_EXT -> RE_C
    else -> null
}

/**
 * Une ligne de code en jetons : leur texte, mis bout à bout, est la ligne même, caractère pour caractère. Rien n'y est
 * une mise en forme lue dans le fichier : seules des couleurs s'y posent, par la sorte du jeton.
 */
fun tokens(line: String, path: String): List<Token> {
    // une ligne démesurée (un fichier minifié) ne se colore pas
    val re = if (line.length > LINE_SHOWN + 2) null else grammar(path)
    if (re == null) return if (line.isEmpty()) emptyList() else listOf(Token(TokenKind.PLAIN, line))
    val out = ArrayList<Token>()
    var at = 0
    for (m in re.findAll(line)) {
        if (m.value.isEmpty()) continue
        if (m.range.first > at) out += Token(TokenKind.PLAIN, line.substring(at, m.range.first))
        val group = (1..TOKEN_KINDS.size).firstOrNull { m.groups[it] != null }
        out += Token(if (group == null) TokenKind.PLAIN else TOKEN_KINDS[group - 1], m.value)
        at = m.range.last + 1
    }
    if (at < line.length) out += Token(TokenKind.PLAIN, line.substring(at))
    return out
}

// ── Un diff, mis en lignes ──────────────────────────────────────────────

/** Une rangée du diff unifié : l'en-tête d'un passage, ou une ligne avec ses deux numéros (0 : elle n'y est pas). */
sealed interface DiffRow {
    data class Head(val header: String) : DiffRow
    data class Line(val line: DiffLine) : DiffRow
}

/** Le diff unifié d'un fichier : chaque passage, son en-tête puis ses lignes, dans l'ordre servi. */
fun unifiedRows(hunks: List<Hunk>): List<DiffRow> = hunks.flatMap { hunk -> listOf<DiffRow>(DiffRow.Head(hunk.header)) + hunk.lines.map { DiffRow.Line(it) } }

/**
 * Un fichier de diff mis en rangées, une fois : ses rangées, sa ligne la plus large telle qu'on la pose (pour mesurer
 * son cadre), et la largeur de ses colonnes de numéros, en chiffres.
 */
class DiffLayout(val rows: List<DiffRow>, val widest: String, val digits: Int)

fun diffLayout(f: DiffFile): DiffLayout {
    val rows = unifiedRows(f.hunks)
    return DiffLayout(rows, widestLine(rows.mapNotNull { (it as? DiffRow.Line)?.line?.text?.let(::shownLine) }), numberDigits(f.hunks))
}

/** Le numéro d'une ligne dans sa colonne : rien quand la ligne n'y est pas (0). */
fun lineNumber(n: Int): String = if (n > 0) n.toString() else ""

/** La largeur, en chiffres, des colonnes de numéros d'un fichier de diff : celle de son plus grand numéro (deux au moins). */
fun numberDigits(hunks: List<Hunk>): Int = maxOf(2, (hunks.flatMap { it.lines }.maxOfOrNull { maxOf(it.old, it.new) } ?: 0).toString().length)

/** Ce qu'un fichier de diff montre à la place de ses lignes, quand il n'en a pas à montrer. */
enum class DiffBody { LINES, HIDDEN, BINARY, NOTHING }

fun diffBody(f: DiffFile): DiffBody = when {
    f.hidden -> DiffBody.HIDDEN
    f.binary -> DiffBody.BINARY
    f.hunks.isNotEmpty() -> DiffBody.LINES
    else -> DiffBody.NOTHING
}

/** Un fichier coupé qui peut se relire seul (`path=`) : ni caché, ni binaire. */
fun canReadWhole(f: DiffFile): Boolean = f.cut && !f.hidden && !f.binary

/** Les comptes d'un diff, en mots courts : « 3 fichiers ». */
fun filesWords(d: Diff): String = plural(d.files.size, "fichier", "fichiers")

// ── Les jours d'une ligne de temps ──────────────────────────────────────

/** Les commits d'un même jour, sous son nom (« Aujourd'hui », « Hier », « lundi 2 novembre »). */
data class DayGroup<T>(val label: String, val items: List<T>)

/** Une liste datée, rangée par jour dans l'ordre où elle vient (du plus récent au plus ancien). */
fun <T> byDay(items: List<T>, at: (T) -> Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): List<DayGroup<T>> {
    val out = ArrayList<DayGroup<T>>()
    var label: String? = null
    var bucket = ArrayList<T>()
    for (x in items) {
        val day = MoiDates.dayLabel(at(x), now, zone)
        if (day != label) {
            if (label != null) out += DayGroup(label, bucket)
            label = day
            bucket = ArrayList()
        }
        bucket += x
    }
    if (label != null) out += DayGroup(label, bucket)
    return out
}

// ── L'arborescence, un dossier à la fois ────────────────────────────────

/** Une ligne de l'arborescence : une entrée (un dossier ouvert ou non, un fichier), un dossier qui se lit encore ou ne se lit pas, ce qu'il tait. */
sealed interface TreeRow {
    val depth: Int

    data class Node(val entry: TreeEntry, override val depth: Int, val open: Boolean) : TreeRow

    /** Un dossier ouvert pas encore lu ([error] vide), ou illisible ([error] : les mots du serveur). */
    data class Pending(val dir: String, override val depth: Int, val error: String) : TreeRow

    /** Les entrées cachées qu'un dossier tait. */
    data class Hidden(val dir: String, override val depth: Int, val count: Int) : TreeRow
}

/**
 * L'arborescence à plat, depuis [dir] : chaque dossier lu ([read]) donne ses entrées (les dossiers d'abord, dans l'ordre
 * servi) ; un dossier ouvert ([open]) est suivi des siennes, en retrait. Un dossier ne se lit qu'en s'ouvrant.
 */
fun treeRows(dir: String, read: (String) -> Tree?, failed: (String) -> String, open: Set<String>, depth: Int = 0): List<TreeRow> {
    val tree = read(dir) ?: return listOf(TreeRow.Pending(dir, depth, failed(dir)))
    val out = ArrayList<TreeRow>()
    for (e in tree.items) {
        val unfolded = e.kind == "dir" && e.path in open
        out += TreeRow.Node(e, depth, unfolded)
        if (unfolded) out += treeRows(e.path, read, failed, open, depth + 1)
    }
    if (tree.hidden > 0) out += TreeRow.Hidden(dir, depth, tree.hidden)
    return out
}

// ── Une pull request : sa fusion ────────────────────────────────────────

/** Où en est sa fusion, pour choisir ce qu'on en dit : faite, demandée, refusée par l'hôte, possible, retenue. */
enum class MergeStage { MERGED, ASKED, REFUSED, READY, HELD }

fun mergeStage(p: CodePull): MergeStage = when {
    p.state == "merged" -> MergeStage.MERGED
    p.merge.asked -> MergeStage.ASKED
    p.merge.can -> MergeStage.READY
    p.merge.refused.isNotBlank() -> MergeStage.REFUSED
    else -> MergeStage.HELD
}

/** Ce que la confirmation dit de ce qui va être fusionné : lu sur la pull request qu'on vient de relire. */
data class MergeFacts(
    val number: Int,
    val title: String,
    val branch: String,
    val base: String,
    /** Le commit de tête, entier : celui que la demande nomme. */
    val head: String,
    val commits: Int,
    val files: Int,
    val insertions: Int,
    val deletions: Int,
    /** Ses comptes sont lisibles (elle lit ses fichiers). */
    val counted: Boolean,
    /** Ce que le serveur dit de sa relecture et de ses vérifications. */
    val review: String,
    val checks: String,
    val conflicts: Boolean,
)

fun mergeFacts(d: PullDetail): MergeFacts {
    val p = d.pull
    return MergeFacts(
        number = p.number, title = pullTitle(p), branch = p.branch, base = p.base, head = p.head, commits = d.commits.size,
        files = d.diff.files.size, insertions = d.diff.insertions, deletions = d.diff.deletions, counted = d.diff.filesReadable,
        review = p.review?.label.orEmpty(), checks = p.checks?.stateLabel.orEmpty(), conflicts = p.conflicts,
    )
}

/** Où elle en est, en une ligne de la confirmation : sa relecture, ses vérifications, ses conflits — les mots du serveur. */
fun mergeStateWords(f: MergeFacts): String = listOf(
    if (f.review.isBlank()) "" else "relecture : ${f.review}",
    if (f.checks.isBlank()) "" else "vérifications : ${f.checks}",
    if (f.conflicts) "des conflits" else "aucun conflit",
).filter { it.isNotBlank() }.joinToString(" · ")

private val FULL_SHA = Regex("^[0-9a-f]{40}$")

/**
 * L'ordre de fusionner une pull request. Il ne se fabrique pas : il naît d'une pull request **qu'on vient de relire**
 * ([of]), que le serveur dit fusionnable par elle (`merge.can`), et il nomme son numéro et **son commit de tête lu**
 * (`pull.head`, entier). C'est le seul argument de `ProjectsApi.merge`, le seul chemin de l'app vers la route de la
 * fusion : si la branche bouge après la lecture, le serveur refuse (409) et rien ne part.
 */
class MergeOrder private constructor(val number: Int, val head: String) {
    /** Le corps de la demande : `number`, `head`. */
    val body: JsonObject get() = bodyOf("number" to number, "head" to head)

    override fun toString(): String = "MergeOrder(n° $number, ${head.take(12)})"

    companion object {
        /** `null` : rien à demander — pas de numéro, pas de commit de tête lu, ou le serveur ne l'ouvre pas (`merge.why`). */
        fun of(read: PullDetail): MergeOrder? {
            val p = read.pull
            return if (p.number > 0 && p.merge.can && FULL_SHA.matches(p.head)) MergeOrder(p.number, p.head) else null
        }
    }
}

/** Ce qu'on dit quand une pull request relue n'a plus de quoi être fusionnée et que le serveur n'en dit pas plus. */
const val MERGE_NOT_NOW = "Cette pull request ne peut pas être fusionnée pour l'instant : relis-la."

/** Modifier son titre et son texte chez l'hôte : seulement ce qui change de ce qu'on a relu (un champ vide ne change rien). */
fun pullEditRequest(number: Int, title: String, body: String, beforeTitle: String, beforeBody: String): GestureRequest {
    val after = linkedMapOf<String, Any?>("title" to title.trim(), "body" to body)
    val before = mapOf<String, Any?>("title" to beforeTitle, "body" to beforeBody)
    return GestureRequest("code/pull/modifier", filled("number" to number, *changed(before, after).toTypedArray()))
}

/** Répondre dans une pull request : le commentaire part chez l'hôte, du compte du jeton. */
fun pullCommentRequest(number: Int, text: String): GestureRequest = GestureRequest("code/pull/commenter", bodyOf("number" to number, "text" to text.trim()))

/** Ce qu'une réponse porte au plus (le serveur : 4 000 caractères). */
const val COMMENT_MAX = 4000

// ── Les vérifications d'un commit ───────────────────────────────────────

/** Ce qu'on montre des vérifications d'un commit : ce que l'hôte en dit maintenant, sinon ce que le moteur suit. */
data class ChecksShown(val state: String, val label: String, val at: Long)

fun checksShown(tracked: TrackedChecks?, live: HostChecks?): ChecksShown = when {
    live != null && live.error.isBlank() -> ChecksShown(live.state, live.stateLabel, live.at)
    tracked != null -> ChecksShown(tracked.state, tracked.stateLabel, tracked.at)
    else -> ChecksShown("none", "", 0)
}

/** La fin du journal d'un échec : celle que l'hôte rend maintenant, sinon celle que le moteur a gardée. */
fun checksTail(tracked: TrackedChecks?, live: HostChecks?): String = hostText(live?.log?.tail).ifBlank { hostText(tracked?.said) }

/** Ce qui est lié à des vérifications : ce que l'hôte en rend, sinon l'objectif et la pull request que le moteur suit. */
fun checksLinked(tracked: TrackedChecks?, live: HostChecks?): CodeLinked? =
    live?.linked ?: tracked?.let { CodeLinked(objective = it.objective, pull = it.pull) }

/** Le commit d'une liste que nomme une empreinte, courte ou entière. */
fun <T> bySha(items: List<T>, said: String, sha: (T) -> String): T? {
    val s = said.lowercase()
    return if (Regex("^[0-9a-f]{4,40}$").matches(s)) items.firstOrNull { sha(it).startsWith(s) } else null
}

// ── Où en est une pull request, en mots ─────────────────────────────────

/** Depuis quand une pull request est dans son état : « ouverte hier », « fusionnée lundi », « fermée il y a 3 h ». */
fun pullWhen(p: CodePull, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (p.at <= 0) return ""
    val what = when (p.state) {
        "merged" -> "fusionnée"
        "closed" -> "fermée"
        else -> "ouverte"
    }
    return "$what ${since(p.at, now, zone)}"
}

/** Une fusion faite : dans quelle branche, par qui, quand — ce que le serveur en sert. */
fun mergedWords(p: CodePull, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val m = p.merge
    return "Fusionnée dans ${p.base}" + (if (m.askedBy.isBlank()) "" else " par ${m.askedBy}") + (if (m.askedAt > 0) ", ${moment(m.askedAt, now, zone)}" else "") + "."
}

/** Une fusion en route : les mots du serveur (`merge.why`), sinon qu'elle est demandée ; puis par qui, et quand. */
fun askedWords(p: CodePull, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val m = p.merge
    val by = if (m.askedBy.isBlank()) "" else " Demandée par ${m.askedBy}" + (if (m.askedAt > 0) ", ${moment(m.askedAt, now, zone)}" else "") + "."
    return m.why.ifBlank { "La fusion est demandée chez l'hôte." } + by
}

/** Pourquoi la dernière demande de fusion n'a pas abouti : les mots du serveur, et quand. */
fun refusedWords(p: CodePull, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val m = p.merge
    return if (m.refused.isBlank()) "" else m.refused + (if (m.refusedAt > 0) " (${moment(m.refusedAt, now, zone)})" else "")
}

/** Ce qui entoure ses conflits : avec quelle branche, et ce qui la retient encore. */
fun conflictsWords(p: CodePull): String =
    "avec ${p.base}" + (if (p.changesAsked) " · des changements sont demandés" else "") + (if (p.unsent) " · un commit n'est pas encore envoyé" else "")

/** Sa branche, en une ligne : ce qu'elle a d'avance, et son commit de tête. */
fun pullBranchWords(d: PullDetail): String =
    "${plural(d.commits.size, "commit", "commits")} d'avance" + (if (d.pull.head.isBlank()) "" else " · tête ${d.pull.head.take(7)}")

/** Ce qu'un dossier tait : « 2 entrées cachées ». */
fun hiddenWords(count: Int): String = plural(count, "entrée cachée", "entrées cachées")
