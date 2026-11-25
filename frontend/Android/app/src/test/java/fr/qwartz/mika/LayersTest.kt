package fr.qwartz.mika

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Les couches de l'app : `core/`, `data/` et `service/` ne dépendent jamais des écrans. Un de leurs fichiers qui importe
 * `fr.qwartz.mika.ui.…`, ou le nomme en entier dans son code, refuse le test. Le code est lu sans ses commentaires ni
 * ses chaînes : une doc qui cite un écran ne compte pas. Ce qui en dépend encore, faute de pouvoir le défaire sans
 * récrire, est listé ici nommément avec sa raison ; une exception qui ne sert plus refuse le test aussi.
 */
class LayersTest {
    /** Les paquets qui ne voient pas les écrans. */
    private val below = listOf("core/", "data/", "service/")

    /** Ce qu'un fichier de [below] prend encore des écrans, et pourquoi. */
    private val allowed: Map<Pair<String, String>, String> = mapOf(
        ("data/moi/mail/UnsentMail.kt" to "fr.qwartz.mika.ui.Route") to
            "un mail commencé attend sous son écriture, sa route (`Route.MailCompose` : même mode, même mail, même " +
            "brouillon) : la clé est une route, et en prendre une autre récrirait `UnsentMails`",
    )

    /** Un fichier sans ses commentaires ni ses chaînes (vidées en `""` ; ce qu'un gabarit `${…}` insère est gardé). */
    private fun code(text: String): String {
        val out = StringBuilder(text.length)
        var i = 0
        val n = text.length

        // une chaîne qui s'ouvre en [start] (après ses guillemets) : rend où elle finit ; ses gabarits vont dans [out]
        fun string(start: Int, raw: Boolean): Int {
            var k = start
            while (k < n) {
                when {
                    raw && text.startsWith("\"\"\"", k) -> {
                        var e = k + 3
                        while (e < n && text[e] == '"') e++
                        return e
                    }
                    !raw && text[k] == '\\' -> k += 2
                    !raw && text[k] == '"' -> return k + 1
                    text.startsWith("\${", k) -> {
                        var depth = 1
                        var e = k + 2
                        while (e < n && depth > 0) {
                            when (text[e]) {
                                '{' -> depth++
                                '}' -> depth--
                                '"' -> e = string(e + 1, false) - 1
                            }
                            e++
                        }
                        out.append(' ').append(code(text.substring(k + 2, (e - 1).coerceAtLeast(k + 2)))).append(' ')
                        k = e
                    }
                    else -> k++
                }
            }
            return n
        }

        while (i < n) {
            when {
                text.startsWith("//", i) -> while (i < n && text[i] != '\n') i++
                text.startsWith("/*", i) -> {
                    var depth = 1
                    i += 2
                    while (i < n && depth > 0) {
                        when {
                            text.startsWith("/*", i) -> { depth++; i += 2 }
                            text.startsWith("*/", i) -> { depth--; i += 2 }
                            else -> { if (text[i] == '\n') out.append('\n'); i++ }
                        }
                    }
                }
                text.startsWith("\"\"\"", i) -> { out.append("\"\""); i = string(i + 3, raw = true) }
                text[i] == '"' -> { out.append("\"\""); i = string(i + 1, raw = false) }
                // un caractère : 'x', '\n', '\u00e9' (un guillemet qu'il tient n'ouvre pas de chaîne)
                text[i] == '\'' && i + 3 < n && text[i + 1] == '\\' -> i += if (text[i + 2] == 'u') 8 else 4
                text[i] == '\'' && i + 2 < n && text[i + 2] == '\'' -> i += 3
                else -> { out.append(text[i]); i++ }
            }
        }
        return out.toString()
    }

    private val uiName = Regex("""\bfr\.qwartz\.mika\.ui\.[A-Za-z_][\w.]*""")

    /** Ce que [text] nomme des écrans dans son code : un import, ou un nom écrit en entier. */
    private fun uiNames(text: String): Set<String> = uiName.findAll(code(text)).map { it.value.removeSuffix(".") }.toSet()

    private val root: File by lazy {
        listOf(File("src/main/java/fr/qwartz/mika"), File("app/src/main/java/fr/qwartz/mika")).firstOrNull { it.isDirectory }
            ?: error("Le code de l'app est introuvable depuis ${File(".").absolutePath}")
    }

    private val sources: List<Pair<String, String>> by lazy {
        root.walkTopDown().filter { it.isFile && it.extension == "kt" }
            .map { it.relativeTo(root).invariantSeparatorsPath to it.readText() }.toList()
    }

    @Test fun `le lecteur ne voit ni les commentaires ni les chaînes, et trouve un import comme un nom écrit en entier`() {
        val text = """
            import fr.qwartz.mika.ui.Route
            import fr.qwartz.mika.data.moi.MoiApi
            // import fr.qwartz.mika.ui.mail.Commentaire
            /* fr.qwartz.mika.ui.Bloc /* emboîté : fr.qwartz.mika.ui.Dedans */ encore fr.qwartz.mika.ui.Apres */
            /** Pour [fr.qwartz.mika.ui.mail.MailFrame]. */
            val a = "fr.qwartz.mika.ui.Chaine"
            val b = '"'
            val e = '\''
            val g = '\u0022'
            val c = "dit ${'$'}{fr.qwartz.mika.ui.shell.Gabarit.nom} ici"
            val d = ""${'"'}fr.qwartz.mika.ui.Brute""${'"'}
            fun f() = fr.qwartz.mika.ui.theme.Ecrit.couleur
        """.trimIndent()
        assertEquals(setOf("fr.qwartz.mika.ui.Route", "fr.qwartz.mika.ui.shell.Gabarit.nom", "fr.qwartz.mika.ui.theme.Ecrit.couleur"), uiNames(text))
        assertTrue("le code de l'app n'a pas été lu", sources.size > 100)
    }

    @Test fun `core, data et service ne prennent rien des écrans, sauf ce qui est listé avec sa raison`() {
        val found = sources.filter { (file, _) -> below.any { file.startsWith(it) } }
            .flatMap { (file, text) -> uiNames(text).map { file to it } }.toSet()
        val extra = (found - allowed.keys).sortedBy { it.first }.map { (file, name) -> "$file → $name" }
        val stale = (allowed.keys - found).map { (file, name) -> "$file → $name (listé, plus servi)" }
        assertEquals("ce que core/, data/ et service/ prennent des écrans", emptyList<String>(), extra + stale)
    }
}
