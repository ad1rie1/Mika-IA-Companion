package fr.qwartz.mika.data.moi.projects

import java.text.Normalizer

/*
 * Les règles pures de l'onglet Documentation (ADR 0296), portées du client web (`frontendv2/src/screens/projets/` :
 * `docparts.ts`, `docmd.ts`) : ses volets, l'arborescence des pages, le chemin d'une page nouvelle, ce qu'une page
 * montre (son Markdown, et ses images — celles de l'espace seulement), **le brouillon d'une page** (ce qui est tapé, la
 * version lue, l'enregistrement et son conflit : un refus ne fait jamais perdre ce qui a été écrit), ses gestes, l'ordre
 * des décisions. Et ce que le web laisse à sa bibliothèque d'édition : **les transformations de la barre d'outils**
 * ([MdEdit]), des fonctions de (texte, sélection) vers (texte, sélection). Aucune règle du serveur n'est refaite ici.
 */

// ── Les volets ──────────────────────────────────────────────────────────

/** Les volets de l'onglet Documentation (`documentation/<volet>`). */
object DocTabs {
    const val PAGES = "pages"
    const val IMAGES = "images"
    const val DECISIONS = "decisions"
    val ALL = listOf(PAGES, IMAGES, DECISIONS)

    /** Le volet d'une adresse ; inconnu ou vide : les pages. */
    fun of(sub: String): String = sub.substringBefore('/').let { if (it in ALL) it else PAGES }

    fun tab(sub: String): String = if (sub == PAGES) SheetTabs.DOCS else "${SheetTabs.DOCS}/$sub"
}

// ── L'arborescence ──────────────────────────────────────────────────────

/** Une ligne de l'arborescence : un dossier ([page] `null`) ou une page, à sa profondeur. */
data class DocNode(val name: String, val path: String, val depth: Int, val page: DocPage?)

private const val HOME = "accueil.md"

/**
 * Les pages à plat, en lignes d'arbre : dans chaque dossier ses sous-dossiers d'abord, puis ses pages, `accueil.md` en
 * tête, le reste par ordre alphabétique ; un dossier replié ([closed] : son chemin) cache ce qu'il contient.
 */
fun docRows(pages: List<DocPage>, closed: Set<String> = emptySet()): List<DocNode> {
    val out = mutableListOf<DocNode>()
    fun walk(folder: String, depth: Int) {
        val prefix = if (folder.isEmpty()) "" else "$folder/"
        val inside = pages.filter { it.path.startsWith(prefix) }
        val folders = inside.mapNotNull { p -> p.path.removePrefix(prefix).takeIf { '/' in it }?.substringBefore('/') }.distinct().sorted()
        for (name in folders) {
            val path = prefix + name
            out += DocNode(name, path, depth, null)
            if (path !in closed) walk(path, depth + 1)
        }
        val leaves = inside.filter { '/' !in it.path.removePrefix(prefix) }
        for (p in leaves.sortedWith(compareBy<DocPage> { nameOf(it.path) != HOME }.thenBy { nameOf(it.path) })) {
            out += DocNode(nameOf(p.path), p.path, depth, p)
        }
    }
    walk("", 0)
    return out
}

// ── Le chemin d'une page ────────────────────────────────────────────────

private val MARKS = Regex("\\p{M}+")
private val NOT_SLUG = Regex("[^a-z0-9]+")

/** Un nom replié comme le serveur l'attend (il ne corrige rien) : minuscules, chiffres, tirets ; sans accents. */
fun slug(text: String): String =
    Normalizer.normalize(text, Normalizer.Form.NFD).replace(MARKS, "").lowercase().removeSuffix(".md").replace(NOT_SLUG, "-").trim('-')

/** Un dossier tapé (`Guide/Avancé`) replié segment par segment ; vide : la racine. */
fun folderPath(text: String): String = text.split('/').map(::slug).filter { it.isNotEmpty() }.joinToString("/")

/** Le chemin d'une page dans un dossier : `guide/depannage.md` ; vide si le nom ne donne rien. */
fun pagePath(folder: String, name: String): String {
    val leaf = slug(name)
    return if (leaf.isEmpty()) "" else (if (folder.isEmpty()) "" else "$folder/") + "$leaf.md"
}

fun folderOf(path: String): String = path.substringBeforeLast('/', "")

fun nameOf(path: String): String = path.substringAfterLast('/')

/** Le texte d'une image dans une page, depuis son nom de fichier : `schema-reseau.png` → « schema reseau ». */
fun imageAlt(name: String): String = name.replace(Regex("\\.[A-Za-z0-9]+$"), "").replace('-', ' ')

/** Ce qu'une page écrit pour citer une image de l'espace : la référence à coller. */
fun imageMarkdown(name: String): String = "![${imageAlt(name)}](images/$name)"

private val SPACE_IMAGE = Regex("^(?:\\./)?images/([A-Za-z0-9][A-Za-z0-9._-]*)$")

/** Le nom d'une image de l'espace, depuis l'adresse qu'une page écrit (`images/<nom>`) ; vide : elle vient d'ailleurs. */
fun spaceImage(src: String): String = SPACE_IMAGE.find(src.trim())?.groupValues?.get(1).orEmpty()

// ── Ce qu'une page montre ───────────────────────────────────────────────

/**
 * Un morceau d'une page rendue. Son Markdown se pose par le rendu de l'app, qui ne pose que du texte ; **une image ne se
 * charge que si elle est de l'espace** ([Image], servie par l'API sous la session) — toute autre adresse se dit
 * ([Elsewhere]), sans être chargée.
 */
sealed interface DocBlock {
    data class Text(val markdown: String) : DocBlock
    data class Image(val name: String, val alt: String) : DocBlock
    data class Elsewhere(val src: String, val alt: String) : DocBlock
}

private val IMAGE = Regex("!\\[([^\\]]*)]\\(([^)\\s]+)(?:\\s+\"([^\"]*)\")?\\)")
private val FENCE = Regex("^ {0,3}(```|~~~)")
private val TASK_BOX = Regex("^(\\s*(?:[-*+]|\\d+[.)])\\s+)\\[( |x|X)]\\s+")

/**
 * Une page en morceaux : son texte, coupé là où elle cite une image. Dans un bloc de code rien n'est lu ; une case à
 * cocher (`- [ ]`, `- [x]`) devient son signe.
 */
fun docBlocks(text: String): List<DocBlock> {
    val out = mutableListOf<DocBlock>()
    val buf = StringBuilder()
    fun flush() {
        if (buf.isNotBlank()) out += DocBlock.Text(buf.toString().trim('\n'))
        buf.setLength(0)
    }
    var fence = ""
    for (line in text.replace("\r\n", "\n").replace('\r', '\n').split('\n')) {
        val mark = FENCE.find(line)?.groupValues?.get(1)
        if (mark != null) {
            if (fence.isEmpty()) fence = mark else if (fence == mark) fence = ""
            buf.append(line).append('\n')
            continue
        }
        if (fence.isNotEmpty() || !IMAGE.containsMatchIn(line)) {
            buf.append(if (fence.isEmpty()) TASK_BOX.replace(line) { m -> m.groupValues[1] + (if (m.groupValues[2] == " ") "☐ " else "☑ ") } else line).append('\n')
            continue
        }
        var at = 0
        for (m in IMAGE.findAll(line)) {
            val before = line.substring(at, m.range.first)
            if (before.isNotBlank()) buf.append(before.trimEnd()).append('\n')
            flush()
            val alt = m.groupValues[3].ifBlank { m.groupValues[1] }
            val name = spaceImage(m.groupValues[2])
            out += if (name.isNotEmpty()) DocBlock.Image(name, alt) else DocBlock.Elsewhere(m.groupValues[2], alt)
            at = m.range.last + 1
        }
        val rest = line.substring(at)
        if (rest.isNotBlank()) buf.append(rest.trimStart()).append('\n')
    }
    flush()
    return out
}

/** Les titres d'une page, hors de ses blocs de code : son sommaire. */
fun headingsOf(text: String): List<Pair<Int, String>> {
    var fence = ""
    val out = mutableListOf<Pair<Int, String>>()
    for (line in text.split('\n')) {
        val mark = FENCE.find(line)?.groupValues?.get(1)
        if (mark != null) {
            if (fence.isEmpty()) fence = mark else if (fence == mark) fence = ""
            continue
        }
        if (fence.isNotEmpty()) continue
        val m = Regex("^(#{1,4})\\s+(.*)$").find(line) ?: continue
        out += m.groupValues[1].length to m.groupValues[2].replace(Regex("[`*_\\\\]"), "").trim()
    }
    return out
}

// ── Le brouillon d'une page ─────────────────────────────────────────────

/**
 * Ce qu'on écrit d'une page, tant que ce n'est pas enregistré : la version lue ([base], celle que l'enregistrement
 * nomme ; 0 : une page nouvelle), le texte lu à cette version ([read]) et ce qui est tapé depuis ([text]) ; un refus du
 * serveur avec ses mots ([refusal]), et s'il dit que la page a changé depuis la lecture ([conflict], 409).
 */
data class Draft(
    val path: String,
    val base: Int,
    val read: String,
    val text: String,
    val refusal: String = "",
    val conflict: Boolean = false,
) {
    /** La page a-t-elle été modifiée sans être enregistrée ? */
    val dirty: Boolean get() = text != read

    /** Ce qui vient d'être tapé ; le refus d'avant reste dit tant qu'on n'a pas relu ni réenregistré. */
    fun typed(now: String): Draft = copy(text = now)

    /** Enregistré : la version rendue devient la version lue, plus rien n'est en attente. */
    fun saved(version: Int): Draft = copy(base = version, read = text, refusal = "", conflict = false)

    /** Refusé : les mots du serveur se disent, et **ce qui est écrit reste**. Un 409 est un conflit : rien n'est écrasé. */
    fun refused(code: Int, words: String): Draft = copy(refusal = words, conflict = code == 409)

    /**
     * Reprendre après un conflit, une fois la version actuelle relue : elle devient la version de départ, le texte tapé
     * reste entier. L'enregistrement qui suit en fait une version de plus, sans rien écraser à l'aveugle.
     */
    fun rebased(current: DocPage): Draft = copy(base = current.version, read = current.text, refusal = "", conflict = false)

    companion object {
        fun of(page: DocPage): Draft = Draft(page.path, page.version, page.text, page.text)

        /** Une page nouvelle : rien n'est lu (`base` 0), son premier texte est déjà à enregistrer. */
        fun fresh(path: String, text: String = ""): Draft = Draft(path, 0, "", text)
    }
}

/** Ce que l'enregistrement envoie : le Markdown, le mot sur ce qui a changé, et **la version lue**. */
data class DocSave(val path: String, val text: String, val word: String, val base: Int)

const val WORD_MAX = 200

fun saveOf(d: Draft, word: String): DocSave = DocSave(d.path, d.text, word.trim().take(WORD_MAX), d.base)

// ── Les gestes sur une page, une image ──────────────────────────────────

fun docMoveRequest(path: String, to: String): GestureRequest = GestureRequest("documentation/page/deplacer", bodyOf("path" to path, "to" to to))

fun docRemoveRequest(path: String): GestureRequest = GestureRequest("documentation/page/supprimer", bodyOf("path" to path))

/** Revenir à une version gardée : une version de plus, partie de la version courante lue ([base]). */
fun docRestoreRequest(path: String, version: Int, base: Int): GestureRequest =
    GestureRequest("documentation/page/revenir", bodyOf("path" to path, "version" to version, "base" to base))

fun docImageRemoveRequest(name: String): GestureRequest = GestureRequest("documentation/image/retirer", bodyOf("name" to name))

// ── Les décisions techniques ────────────────────────────────────────────

/** Les décisions dans l'ordre de la liste : celles en vigueur, puis les retirées, puis les remplacées. */
fun decisionOrder(items: List<Decision>): List<Decision> = items.sortedBy {
    when (it.status) {
        "active" -> 0
        "withdrawn" -> 1
        else -> 2
    }
}

fun decisionTone(status: String): StateTone = if (status == "active") StateTone.DONE else StateTone.WAIT

/** Les options écartées, une par ligne non vide (le serveur les garde en un seul texte) : son titre, et pourquoi. */
fun optionLines(options: String): List<Pair<String, String>> = options.split('\n').map { it.trim() }.filter { it.isNotEmpty() }.map { l ->
    val i = l.indexOf(" : ")
    if (i > 0) l.substring(0, i).trim() to l.substring(i + 3).trim() else l to ""
}

// ── L'éditeur : les transformations de la barre d'outils ────────────────

/** Ce qui est écrit dans l'éditeur, et ce qui y est choisi ([start] ≤ [end] ; égaux : le curseur). */
data class Edit(val text: String, val start: Int, val end: Int = start) {
    val selected: String get() = text.substring(start, end)

    companion object {
        /** Un état sûr : une sélection hors du texte ou à l'envers est remise dans ses bornes. */
        fun of(text: String, a: Int, b: Int = a): Edit {
            val x = a.coerceIn(0, text.length)
            val y = b.coerceIn(0, text.length)
            return Edit(text, minOf(x, y), maxOf(x, y))
        }
    }
}

/**
 * Les gestes de la barre d'outils d'une page, en Markdown : chacun agit sur la sélection (ou sur la ligne du curseur),
 * se défait en le refaisant, et rend le texte avec la sélection où l'on continue d'écrire. Pur : l'écran ne fait que
 * poser le résultat dans son champ.
 */
object MdEdit {
    private val TASK = Regex("^(\\s*)[-*+] \\[[ xX]] ")
    private val BULLET = Regex("^(\\s*)[-*+] ")
    private val NUMBER = Regex("^(\\s*)(\\d+)([.)]) ")
    private val QUOTE = Regex("^(\\s*)> ?")
    private val HEAD = Regex("^#{1,6} +")

    enum class ListKind { BULLET, NUMBER, TASK }

    private fun lineStart(text: String, at: Int): Int = text.lastIndexOf('\n', at - 1) + 1

    private fun lineEnd(text: String, at: Int): Int = text.indexOf('\n', at).let { if (it < 0) text.length else it }

    /** Les lignes que touche la sélection : du début de la première à la fin de la dernière (une sélection qui finit en début de ligne ne prend pas cette ligne). */
    private fun block(e: Edit): IntRange {
        val last = if (e.end > e.start && e.end > 0 && e.text[e.end - 1] == '\n') e.end - 1 else e.end
        return lineStart(e.text, e.start) until lineEnd(e.text, last)
    }

    /** Refaire les lignes de la sélection : le curseur suit sa ligne, une sélection couvre les lignes refaites. */
    private fun lines(e: Edit, change: (List<String>) -> List<String>): Edit {
        val range = block(e)
        val from = range.first
        val to = range.last + 1
        val before = e.text.substring(from, to).split('\n')
        val after = change(before)
        val joined = after.joinToString("\n")
        val text = e.text.substring(0, from) + joined + e.text.substring(to)
        if (e.start != e.end) return Edit(text, from, from + joined.length)
        // le curseur garde sa place dans sa ligne, décalée de ce que le début de la ligne a gagné ou perdu
        val delta = after.first().length - before.first().length
        return Edit.of(text, maxOf(from, e.start + delta))
    }

    private fun stripList(line: String): Pair<String, String> {
        val m = TASK.find(line) ?: BULLET.find(line) ?: NUMBER.find(line) ?: return "" to line
        return m.groupValues[1] to line.substring(m.range.last + 1)
    }

    private fun kindOf(line: String): ListKind? = when {
        TASK.containsMatchIn(line) -> ListKind.TASK
        BULLET.containsMatchIn(line) -> ListKind.BULLET
        NUMBER.containsMatchIn(line) -> ListKind.NUMBER
        else -> null
    }

    /** Une liste à puces, numérotée ou à cocher sur les lignes choisies ; déjà de cette sorte, elles redeviennent du texte. */
    fun list(e: Edit, kind: ListKind): Edit = lines(e) { all ->
        val real = all.filter { it.isNotBlank() }
        val off = real.isNotEmpty() && real.all { kindOf(it) == kind }
        var n = 0
        all.map { line ->
            if (line.isBlank() && all.size > 1) return@map line
            val (indent, rest) = if (kindOf(line) != null) stripList(line) else line.takeWhile { it == ' ' || it == '\t' }.let { it to line.substring(it.length) }
            if (off) {
                indent + rest
            } else {
                n++
                indent + when (kind) {
                    ListKind.BULLET -> "- "
                    ListKind.NUMBER -> "$n. "
                    ListKind.TASK -> "- [ ] "
                } + rest
            }
        }
    }

    /** Une citation sur les lignes choisies ; déjà citées, elles ne le sont plus. */
    fun quote(e: Edit): Edit = lines(e) { all ->
        val real = all.filter { it.isNotBlank() }
        val off = real.isNotEmpty() && real.all { QUOTE.containsMatchIn(it) && it.trimStart().startsWith(">") }
        all.map { line ->
            when {
                line.isBlank() && all.size > 1 -> line
                off -> QUOTE.replaceFirst(line, "$1")
                else -> "> $line"
            }
        }
    }

    /** Un titre de niveau [level] (1 à 3) sur les lignes choisies ; 0, ou le même niveau redit : du texte. */
    fun heading(e: Edit, level: Int): Edit = lines(e) { all ->
        val mark = "#".repeat(level.coerceIn(0, 6))
        val real = all.filter { it.isNotBlank() }
        val off = level <= 0 || (real.isNotEmpty() && real.all { it.startsWith("$mark ") })
        all.map { line ->
            if (line.isBlank() && all.size > 1) return@map line
            val bare = HEAD.replaceFirst(line, "")
            if (off) bare else "$mark $bare"
        }
    }

    /** Le titre suivant, sur la ligne du curseur : du texte, puis un titre 1, 2, 3, puis du texte de nouveau. */
    fun headingNext(e: Edit): Edit = heading(e, (headingAt(e).coerceAtMost(3) + 1) % 4)

    /** Le niveau de titre de la ligne du curseur (0 : du texte). */
    fun headingAt(e: Edit): Int {
        val line = e.text.substring(lineStart(e.text, e.start), lineEnd(e.text, e.start))
        return HEAD.find(line)?.value?.trim()?.length ?: 0
    }

    private fun stars(text: String, from: Int, step: Int): Int {
        var n = 0
        var i = from
        while (i in text.indices && text[i] == '*') {
            n++
            i += step
        }
        return n
    }

    /** Ce texte est-il entouré de [mark] ? L'italique (`*`) ne se confond pas avec le gras (`**`) : un nombre impair d'étoiles. */
    private fun wraps(mark: String, lead: Int, trail: Int): Boolean = when (mark) {
        "*" -> lead % 2 == 1 && trail % 2 == 1
        "**" -> lead >= 2 && trail >= 2
        else -> lead >= 1 && trail >= 1
    }

    private fun wrap(e: Edit, mark: String): Edit {
        val t = e.text
        val k = mark.length
        // les marques juste autour de la sélection (ou du curseur)
        val lead = if (mark == "`") (if (e.start >= 1 && t[e.start - 1] == '`') 1 else 0) else stars(t, e.start - 1, -1)
        val trail = if (mark == "`") (if (e.end < t.length && t[e.end] == '`') 1 else 0) else stars(t, e.end, 1)
        val around = e.start >= k && t.startsWith(mark, e.start - k) && t.startsWith(mark, e.end) && wraps(mark, lead, trail)
        if (e.start == e.end) {
            // le curseur entre deux marques vides : elles s'en vont ; sinon elles se posent, le curseur au milieu
            return if (around) {
                Edit(t.removeRange(e.start - k, e.start + k), e.start - k)
            } else {
                Edit(t.substring(0, e.start) + mark + mark + t.substring(e.start), e.start + k)
            }
        }
        val sel = e.selected
        val inner = if (mark == "`") (if (sel.startsWith("`")) 1 else 0) else stars(sel, 0, 1)
        val innerEnd = if (mark == "`") (if (sel.endsWith("`")) 1 else 0) else stars(sel, sel.length - 1, -1)
        if (sel.length >= 2 * k && sel.startsWith(mark) && sel.endsWith(mark) && wraps(mark, inner, innerEnd)) {
            val bare = sel.substring(k, sel.length - k)
            return Edit(t.substring(0, e.start) + bare + t.substring(e.end), e.start, e.start + bare.length)
        }
        if (around) {
            return Edit(t.substring(0, e.start - k) + sel + t.substring(e.end + k), e.start - k, e.end - k)
        }
        // les marques se collent au texte : un blanc au bord de la sélection reste dehors
        val a = e.start + (sel.length - sel.trimStart().length)
        val b = e.end - (sel.length - sel.trimEnd().length)
        if (a >= b) return e
        return Edit(t.substring(0, a) + mark + t.substring(a, b) + mark + t.substring(b), a + k, b + k)
    }

    fun bold(e: Edit): Edit = wrap(e, "**")

    fun italic(e: Edit): Edit = wrap(e, "*")

    /** Du code : en ligne dans une phrase ; un bloc quand la sélection tient sur plusieurs lignes, ou sur une ligne vide. */
    fun code(e: Edit): Edit {
        val t = e.text
        val sel = e.selected
        val alone = e.start == e.end && lineStart(t, e.start) == lineEnd(t, e.start)
        if ('\n' !in sel && !alone) return wrap(e, "`")
        val body = sel.trim('\n')
        // le bloc prend ses propres lignes : un blanc resté au bord de la coupe s'en va
        val head = t.substring(0, e.start).trimEnd(' ', '\t').let { if (it.isEmpty() || it.endsWith("\n")) it else "$it\n" }
        val tail = t.substring(e.end).trimStart(' ', '\t').let { if (it.isEmpty() || it.startsWith("\n")) it else "\n$it" }
        val open = "$head```\n"
        return Edit("$open$body\n```$tail", open.length, open.length + body.length)
    }

    /**
     * Un lien vers [url] : son texte est la sélection, ou l'adresse si rien n'est choisi — alors ce texte est
     * sélectionné, pour l'écrire par-dessus.
     */
    fun link(e: Edit, url: String): Edit {
        val address = url.trim()
        if (address.isEmpty()) return e
        val raw = e.selected
        val label = raw.trim().replace('\n', ' ')
        val shown = label.ifEmpty { address }
        // un blanc au bord de la sélection reste hors du lien
        val a = if (label.isEmpty()) e.start else e.start + (raw.length - raw.trimStart().length)
        val b = if (label.isEmpty()) e.end else e.end - (raw.length - raw.trimEnd().length)
        val head = e.text.substring(0, a)
        val text = "$head[$shown]($address)${e.text.substring(b)}"
        return if (label.isEmpty()) Edit(text, head.length + 1, head.length + 1 + shown.length) else Edit(text, head.length + shown.length + address.length + 4)
    }

    /** Une image de l'espace, sur sa propre ligne, là où est le curseur ; on continue d'écrire dessous. */
    fun image(e: Edit, name: String): Edit {
        val before = e.text.substring(0, e.start)
        val after = e.text.substring(e.end)
        val pre = when {
            before.isEmpty() || before.endsWith("\n\n") -> ""
            before.endsWith("\n") -> "\n"
            else -> "\n\n"
        }
        val post = when {
            after.startsWith("\n\n") -> ""
            after.startsWith("\n") || after.isEmpty() -> "\n"
            else -> "\n\n"
        }
        val head = before + pre + imageMarkdown(name) + post
        return Edit(head + after, head.length)
    }

    private fun inFence(text: String, at: Int): Boolean = text.substring(0, at).split('\n').count { FENCE.containsMatchIn(it) } % 2 == 1

    /**
     * Ce que « Entrée » fait dans une liste ou une citation : [after] est [before] avec un saut de ligne de plus. La
     * ligne suivante reprend la marque (le numéro d'après, une case vide) ; sur un élément resté vide, la marque s'en va
     * — c'est la fin de la liste. Ailleurs, rien ne change.
     */
    fun continued(before: Edit, after: Edit): Edit {
        val p = after.start
        if (after.end != p || p != before.start + 1 || after.text.length != before.text.length - (before.end - before.start) + 1) return after
        if (after.text[p - 1] != '\n' || !after.text.regionMatches(0, before.text, 0, before.start) || after.text.substring(p) != before.text.substring(before.end)) return after
        val from = lineStart(after.text, p - 1)
        val line = after.text.substring(from, p - 1)
        if (inFence(after.text, from)) return after
        val task = TASK.find(line)
        val bullet = if (task == null) BULLET.find(line) else null
        val number = if (task == null && bullet == null) NUMBER.find(line) else null
        val quote = if (task == null && bullet == null && number == null) QUOTE.find(line)?.takeIf { it.value.trimStart().startsWith(">") } else null
        val found = task ?: bullet ?: number ?: quote ?: return after
        if (line.substring(found.range.last + 1).isBlank()) {
            // un élément vide : sa marque s'en va, le curseur reste sur sa ligne
            return Edit(after.text.substring(0, from) + after.text.substring(p), from)
        }
        val indent = found.groupValues[1]
        val next = when {
            task != null -> "$indent- [ ] "
            bullet != null -> indent + line.trimStart().first() + " "
            number != null -> "$indent${(number.groupValues[2].toIntOrNull() ?: 0) + 1}${number.groupValues[3]} "
            else -> "$indent> "
        }
        return Edit(after.text.substring(0, p) + next + after.text.substring(p), p + next.length)
    }
}
