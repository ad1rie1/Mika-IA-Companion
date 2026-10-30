package fr.qwartz.mika.ui.components

/**
 * Le Markdown d'une réponse pro (ADR 0116) : blocs de code (```), code en ligne, gras, italique, listes (`-`, `*`,
 * `1.`), titres (`#`), citations, filets, tableaux (en-tête, corps, alignement des colonnes) et liens — cliquables
 * seulement en http(s). Un petit analyseur, pas une implémentation de CommonMark : ce que les modèles écrivent
 * d'ordinaire, et rien qui ne puisse mal tourner. Rien n'est jamais interprété comme du HTML : une bulle ne montre
 * que du texte. Pur, sans Android ni Compose : le rendu (`AnnotatedString`) est dans `ProMarkdownText`.
 */
object ProMarkdown {
    /** Un morceau de texte et son style ; [url] : un lien, toujours en http(s). */
    data class Span(
        val text: String,
        val bold: Boolean = false,
        val italic: Boolean = false,
        val code: Boolean = false,
        val url: String? = null,
    )

    /** L'alignement d'une colonne, lu sur la ligne de séparation (`:---`, `:-:`, `--:`). */
    enum class Align { START, CENTER, END }

    sealed interface Block {
        data class Paragraph(val spans: List<Span>) : Block
        data class Heading(val level: Int, val spans: List<Span>) : Block

        /** Un élément de liste : sa marque (« • », « 2. »), sa profondeur (0 : au bord). */
        data class Item(val marker: String, val depth: Int, val spans: List<Span>) : Block
        data class Quote(val spans: List<Span>) : Block

        /**
         * Un tableau : son en-tête, l'alignement de chaque colonne et ses rangs, tous à la largeur de l'en-tête (une
         * cellule manquante est vide, une cellule de trop tombe).
         */
        data class Table(val header: List<List<Span>>, val align: List<Align>, val rows: List<List<List<Span>>>) : Block

        /** Un bloc de code (ou des lignes à barres sans séparation d'en-tête) : montré tel quel, en chasse fixe. */
        data class Code(val text: String, val lang: String) : Block
        data object Rule : Block
    }

    private val FENCE = Regex("""^ {0,3}(`{3,}|~{3,})[ \t]*([\w+#.\-]*).*$""")
    private val HEADING = Regex("""^ {0,3}(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$""")
    private val BULLET = Regex("""^([ \t]*)[-*+][ \t]+(.*)$""")
    private val ORDERED = Regex("""^([ \t]*)(\d{1,9})([.)])[ \t]+(.*)$""")
    private val QUOTE = Regex("""^ {0,3}>[ \t]?(.*)$""")
    private val RULE = Regex("""^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$""")
    private val TABLE = Regex("""^[ \t]*\|.*\|[ \t]*$""")
    private val TABLE_DELIMITER = Regex("""^ {0,3}\|?[ \t]*:?-+:?[ \t]*(?:\|[ \t]*:?-+:?[ \t]*)*\|?[ \t]*$""")
    private val CELL_BREAK = Regex("""<br\s*/?>""", RegexOption.IGNORE_CASE)
    private val SAFE_URL = Regex("""^https?://[^\s<>"'`]+$""", RegexOption.IGNORE_CASE)
    private const val ESCAPABLE = "\\`*_{}[]()#+-.!|>~"
    private val BULLETS = listOf("•", "◦", "▪")
    private const val MAX_DEPTH = 3

    /** Un lien qu'on peut ouvrir : http(s) seulement, sans espace ni guillemet. */
    fun isSafeUrl(url: String): Boolean = SAFE_URL.matches(url)

    fun parse(text: String): List<Block> {
        val lines = text.replace("\r\n", "\n").replace('\r', '\n').split('\n')
        val out = mutableListOf<Block>()
        val paragraph = mutableListOf<String>()
        var item: PendingItem? = null

        fun flush() {
            item?.let { out += Block.Item(it.marker, it.depth, inline(it.text.toString())) }
            item = null
            if (paragraph.isNotEmpty()) out += Block.Paragraph(inline(paragraph.joinToString("\n")))
            paragraph.clear()
        }

        var i = 0
        while (i < lines.size) {
            val line = lines[i]
            val fence = FENCE.matchEntire(line)
            if (fence != null) {
                flush()
                val marker = fence.groupValues[1]
                val rest = line.trim().removePrefix(marker)
                if (marker in rest) {
                    // ```ls -la``` sur une seule ligne : un bloc d'une ligne, pas le reste du texte en code
                    out += Block.Code(rest.substringBefore(marker).trim(), "")
                    i++
                    continue
                }
                val body = mutableListOf<String>()
                i++
                while (i < lines.size && !closesFence(lines[i], marker)) body += lines[i++]
                i++ // la clôture — ou la fin du texte : un bloc jamais fermé reste un bloc
                out += Block.Code(body.joinToString("\n"), fence.groupValues[2])
                continue
            }
            if (line.isBlank()) {
                flush()
                i++
                continue
            }
            if (RULE.matches(line)) {
                flush()
                out += Block.Rule
                i++
                continue
            }
            val heading = HEADING.matchEntire(line)
            if (heading != null) {
                flush()
                out += Block.Heading(heading.groupValues[1].length, inline(heading.groupValues[2]))
                i++
                continue
            }
            val align = tableAt(lines, i)
            if (align != null) {
                flush()
                val header = cells(line, align.size)
                val rows = mutableListOf<List<List<Span>>>()
                i += 2
                // le corps : les lignes à barres qui suivent, jusqu'à une ligne vide
                while (i < lines.size && lines[i].isNotBlank() && '|' in lines[i]) rows += cells(lines[i++], align.size)
                out += Block.Table(header, align, rows)
                continue
            }
            if (TABLE.matches(line)) {
                flush()
                val rows = mutableListOf<String>()
                while (i < lines.size && TABLE.matches(lines[i])) rows += lines[i++].trim()
                out += Block.Code(rows.joinToString("\n"), "")
                continue
            }
            val bullet = BULLET.matchEntire(line)
            val ordered = if (bullet == null) ORDERED.matchEntire(line) else null
            if (bullet != null || ordered != null) {
                flush()
                val indent = width((bullet ?: ordered)!!.groupValues[1])
                val depth = (indent / 2).coerceAtMost(MAX_DEPTH)
                item = if (bullet != null) {
                    PendingItem(BULLETS[depth.coerceAtMost(BULLETS.lastIndex)], depth, StringBuilder(bullet.groupValues[2]))
                } else {
                    val g = ordered!!.groupValues
                    PendingItem("${g[2]}${g[3]}", depth, StringBuilder(g[4]))
                }
                i++
                continue
            }
            val quote = QUOTE.matchEntire(line)
            if (quote != null) {
                flush()
                val quoted = mutableListOf<String>()
                while (i < lines.size) {
                    val q = QUOTE.matchEntire(lines[i]) ?: break
                    quoted += q.groupValues[1]
                    i++
                }
                out += Block.Quote(inline(quoted.joinToString("\n")))
                continue
            }
            val open = item
            if (open != null && (line.startsWith(" ") || line.startsWith("\t"))) {
                // la suite d'un élément de liste, indentée sous lui
                open.text.append(' ').append(line.trim())
            } else {
                if (open != null) flush()
                paragraph += line
            }
            i++
        }
        flush()
        return out
    }

    /**
     * Un tableau commence en [i] : une ligne à barres, suivie de sa ligne de séparation, avec autant de colonnes. Ses
     * alignements, ou `null`.
     */
    private fun tableAt(lines: List<String>, i: Int): List<Align>? {
        val delimiter = lines.getOrNull(i + 1) ?: return null
        if ('|' !in lines[i] || '|' !in delimiter || !TABLE_DELIMITER.matches(delimiter)) return null
        val align = split(delimiter).map {
            when {
                it.endsWith(':') && it.startsWith(':') -> Align.CENTER
                it.endsWith(':') -> Align.END
                else -> Align.START
            }
        }
        return align.takeIf { split(lines[i]).size == it.size }
    }

    /**
     * Les cellules d'une ligne de tableau sans les barres du bord ; `\|` est une barre dans la cellule (l'échappement
     * reste, [scan] le lit).
     */
    private fun split(line: String): List<String> {
        var row = line.trim()
        if (row.startsWith('|')) row = row.substring(1)
        if (row.endsWith('|') && !row.endsWith("\\|")) row = row.dropLast(1)
        val out = mutableListOf<String>()
        val cell = StringBuilder()
        var k = 0
        while (k < row.length) {
            when {
                row[k] == '\\' && k + 1 < row.length && row[k + 1] == '|' -> cell.append(row, k, k + 2).also { k++ }
                row[k] == '|' -> out += cell.toString().trim().also { cell.setLength(0) }
                else -> cell.append(row[k])
            }
            k++
        }
        out += cell.toString().trim()
        return out
    }

    /** Un rang de [columns] cellules mises en forme ; un `<br>` écrit dans une cellule y est un saut de ligne. */
    private fun cells(line: String, columns: Int): List<List<Span>> {
        val cells = split(line)
        return List(columns) { c -> inline(cells.getOrElse(c) { "" }.replace(CELL_BREAK, "\n")) }
    }

    private class PendingItem(val marker: String, val depth: Int, val text: StringBuilder)

    private fun closesFence(line: String, marker: String): Boolean {
        val t = line.trim()
        return t.length >= marker.length && t.all { it == marker[0] }
    }

    /** La largeur d'une indentation, une tabulation valant quatre espaces. */
    private fun width(indent: String): Int = indent.sumOf { if (it == '\t') 4 else 1 }

    // ── Le texte d'un bloc ──

    private data class Style(val bold: Boolean = false, val italic: Boolean = false)

    /** Le texte d'un bloc en morceaux stylés ; deux morceaux voisins de même style n'en font qu'un. */
    fun inline(text: String): List<Span> {
        val raw = mutableListOf<Span>()
        scan(text, Style(), raw)
        val out = mutableListOf<Span>()
        for (s in raw) {
            val last = out.lastOrNull()
            if (last != null && last.copy(text = "") == s.copy(text = "") && !s.code) {
                out[out.lastIndex] = last.copy(text = last.text + s.text)
            } else {
                out += s
            }
        }
        return out
    }

    private fun scan(s: String, style: Style, out: MutableList<Span>) {
        val buf = StringBuilder()
        fun flush() {
            if (buf.isNotEmpty()) out += Span(buf.toString(), style.bold, style.italic)
            buf.setLength(0)
        }

        var i = 0
        while (i < s.length) {
            val c = s[i]
            // Un caractère échappé est un caractère.
            if (c == '\\' && i + 1 < s.length && s[i + 1] in ESCAPABLE) {
                buf.append(s[i + 1])
                i += 2
                continue
            }
            // Du code en ligne : `…` (ou ``…`` pour y mettre un accent grave) ; rien n'y est interprété.
            if (c == '`') {
                val ticks = run(s, i, '`')
                val close = closingTicks(s, i + ticks, ticks)
                if (close > i + ticks) {
                    flush()
                    out += Span(s.substring(i + ticks, close).trim(), style.bold, style.italic, code = true)
                    i = close + ticks
                } else {
                    buf.append(s, i, i + ticks)
                    i += ticks
                }
                continue
            }
            // Un lien [texte](adresse) : cliquable en http(s) seulement, sinon son texte seul.
            if (c == '[') {
                val link = link(s, i)
                if (link != null) {
                    flush()
                    val (label, url, end) = link
                    if (isSafeUrl(url)) {
                        val inner = mutableListOf<Span>()
                        scan(label, style, inner)
                        inner.forEach { out += it.copy(url = url) }
                    } else {
                        scan(label, style, out)
                    }
                    i = end
                    continue
                }
            }
            // Une adresse nue.
            if ((c == 'h' || c == 'H') && (i == 0 || !s[i - 1].isLetterOrDigit()) &&
                (s.startsWith("http://", i, ignoreCase = true) || s.startsWith("https://", i, ignoreCase = true))
            ) {
                var end = i
                while (end < s.length && !s[end].isWhitespace() && s[end] !in "<>\"`") end++
                // la ponctuation qui la suit n'en fait pas partie
                while (end > i && s[end - 1] in ".,;:!?)]}'*_") end--
                val url = s.substring(i, end)
                if (isSafeUrl(url) && url.substringAfter("://").isNotEmpty()) {
                    flush()
                    out += Span(url, style.bold, style.italic, url = url)
                    i = end
                    continue
                }
            }
            // Le gras : **…** ou __…__.
            if ((c == '*' || c == '_') && i + 1 < s.length && s[i + 1] == c) {
                val marker = "$c$c"
                val close = closing(s, i, marker)
                if (close > 0) {
                    flush()
                    scan(s.substring(i + 2, close), style.copy(bold = true), out)
                    i = close + 2
                } else {
                    buf.append(marker)
                    i += 2
                }
                continue
            }
            // L'italique : *…* ou _…_ (jamais au milieu d'un mot pour `_` : memory_search reste tel quel).
            if (c == '*' || c == '_') {
                val close = closing(s, i, c.toString())
                if (close > 0) {
                    flush()
                    scan(s.substring(i + 1, close), style.copy(italic = true), out)
                    i = close + 1
                    continue
                }
            }
            buf.append(c)
            i++
        }
        flush()
    }

    /** Combien de fois [c] se répète à partir de [from]. */
    private fun run(s: String, from: Int, c: Char): Int {
        var n = 0
        while (from + n < s.length && s[from + n] == c) n++
        return n
    }

    /** La suite d'exactement [ticks] accents graves qui ferme un code en ligne ; -1 sans elle. */
    private fun closingTicks(s: String, from: Int, ticks: Int): Int {
        var j = from
        while (j < s.length) {
            if (s[j] == '`') {
                val n = run(s, j, '`')
                if (n == ticks) return j
                j += n
            } else {
                j++
            }
        }
        return -1
    }

    /**
     * Où se ferme la marque [marker] ouverte en [open] ; -1 si elle ne s'ouvre pas vraiment (suivie d'un blanc,
     * ou `_` collé à un mot) ou ne se ferme pas. Le code en ligne est sauté ; pour une marque simple, une marque
     * double rencontrée en chemin (un gras dans l'italique) aussi.
     */
    private fun closing(s: String, open: Int, marker: String): Int {
        val from = open + marker.length
        if (from >= s.length || s[from].isWhitespace()) return -1
        val underscore = marker[0] == '_'
        if (underscore && open > 0 && s[open - 1].isLetterOrDigit()) return -1
        var j = from + 1
        // une marque simple : un gras ouvert en chemin, que `***` fermera avec elle
        var inner = false
        while (j < s.length) {
            val ch = s[j]
            if (ch == '`') {
                val n = run(s, j, '`')
                val close = closingTicks(s, j + n, n)
                j = if (close > 0) close + n else j + n
                continue
            }
            if (ch == '\\') {
                j += 2
                continue
            }
            if (ch == marker[0]) {
                val n = run(s, j, ch)
                if (marker.length == 1 && n >= 2) {
                    if (n >= 3 && inner && !s[j - 1].isWhitespace()) return j + n - 1
                    if (n == 2) inner = !inner
                    j += n
                    continue
                }
                if (s.startsWith(marker, j) && !s[j - 1].isWhitespace()) {
                    // `***` qui ferme un gras dans un italique : le gras prend les deux dernières
                    val at = j + n - marker.length
                    val after = at + marker.length
                    val nextOk = !underscore || after >= s.length || !s[after].isLetterOrDigit()
                    if (nextOk) return at
                }
                j += n
                continue
            }
            j++
        }
        return -1
    }

    /** `[texte](adresse "titre")` à partir de [at] : le texte, l'adresse, et où reprendre ; `null` sinon. */
    private fun link(s: String, at: Int): Triple<String, String, Int>? {
        val close = s.indexOf(']', at + 1)
        if (close < 0 || close + 1 >= s.length || s[close + 1] != '(') return null
        val label = s.substring(at + 1, close)
        if (label.isEmpty() || '\n' in label || '[' in label) return null
        // la parenthèse qui ferme, les parenthèses de l'adresse comprises
        var depth = 1
        var end = close + 2
        while (end < s.length) {
            when (s[end]) {
                '\n' -> return null
                '(' -> depth++
                ')' -> if (--depth == 0) break
            }
            end++
        }
        if (end >= s.length) return null
        val target = s.substring(close + 2, end).trim()
        val url = target.substringBefore(' ').removePrefix("<").removeSuffix(">")
        return Triple(label, url, end + 1)
    }

    // ── Ce qu'on en dit ──

    /** Le texte sans ses marques, une ligne par bloc : ce qu'un lecteur d'écran dit, et ce qu'on copie. */
    fun plain(text: String): String = parse(text).mapNotNull { block ->
        when (block) {
            is Block.Paragraph -> join(block.spans)
            is Block.Heading -> join(block.spans)
            is Block.Item -> "  ".repeat(block.depth) + block.marker + " " + join(block.spans)
            is Block.Quote -> join(block.spans)
            // une ligne par rang, les cellules séparées d'une tabulation : ce qui se colle dans un tableur
            is Block.Table -> (listOf(block.header) + block.rows).joinToString("\n") { row ->
                row.joinToString("\t") { join(it).replace('\n', ' ') }
            }
            is Block.Code -> block.text
            Block.Rule -> null
        }
    }.joinToString("\n").trim()

    /** Ses liens cliquables, dans l'ordre (texte, adresse), sans doublon : des gestes pour le lecteur d'écran. */
    fun links(text: String): List<Pair<String, String>> = parse(text).flatMap { block ->
        when (block) {
            is Block.Paragraph -> block.spans
            is Block.Heading -> block.spans
            is Block.Item -> block.spans
            is Block.Quote -> block.spans
            is Block.Table -> (block.header + block.rows.flatten()).flatten()
            is Block.Code, Block.Rule -> emptyList()
        }
    }.mapNotNull { s -> s.url?.let { s.text to it } }.distinctBy { it.second }

    private fun join(spans: List<Span>): String = spans.joinToString("") { it.text }
}
