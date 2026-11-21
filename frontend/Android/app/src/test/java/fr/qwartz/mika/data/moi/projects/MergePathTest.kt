package fr.qwartz.mika.data.moi.projects

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * **L'unique chemin vers la fusion.** Fusionner une pull request est le geste d'une personne, confirmé, qui nomme le
 * commit de tête lu : dans le code de l'app, la route de la fusion n'est écrite qu'une fois, un seul appel l'envoie
 * (`ProjectsApi.merge`), un seul endroit fabrique son ordre ([MergeOrder], depuis la pull request relue) et un seul
 * endroit le lance (la confirmation, `MergeFlow`).
 *
 * Le test lit le code de l'app **sans ses commentaires** (qui nomment justement ce qu'il ne faut pas faire) et à part
 * de ses chaînes : ce qu'il compte, ce sont de vrais usages. Ce que ces usages font se teste ailleurs (`CodeApiTest` :
 * un geste générique n'atteint jamais la route ; `CodeRulesTest` ; `CodeModelTest`).
 */
class MergePathTest {
    /** Un fichier Kotlin sans ses commentaires : son code (ses chaînes vidées), et ses chaînes à part. */
    private class Source(val file: String, val code: String, val strings: List<String>)

    private val template = Regex("\\$\\{([^}]*)}|\\$([A-Za-z_][A-Za-z0-9_]*)")

    private fun lex(file: String, text: String): Source {
        val code = StringBuilder()
        val strings = ArrayList<String>()
        // ce qu'une chaîne insère (`$nom`, `${expression}`) est du code : il compte comme tel
        fun keep(string: String) {
            strings += string
            code.append("\"\"")
            for (m in template.findAll(string)) code.append(' ').append(m.groupValues[1].ifEmpty { m.groupValues[2] }).append(' ')
        }
        var i = 0
        val n = text.length
        while (i < n) {
            val c = text[i]
            when {
                text.startsWith("//", i) -> {
                    while (i < n && text[i] != '\n') i++
                }
                text.startsWith("/*", i) -> {
                    // les commentaires de Kotlin s'emboîtent
                    var depth = 1
                    i += 2
                    while (i < n && depth > 0) {
                        when {
                            text.startsWith("/*", i) -> {
                                depth++
                                i += 2
                            }
                            text.startsWith("*/", i) -> {
                                depth--
                                i += 2
                            }
                            else -> i++
                        }
                    }
                }
                text.startsWith("\"\"\"", i) -> {
                    val end = text.indexOf("\"\"\"", i + 3).let { if (it < 0) n else it }
                    keep(text.substring(i + 3, end))
                    i = minOf(n, end + 3)
                }
                c == '"' -> {
                    val start = ++i
                    while (i < n && text[i] != '"') i += if (text[i] == '\\') 2 else 1
                    keep(text.substring(start, minOf(i, n)))
                    i++
                }
                c == '\'' -> {
                    // un caractère : 'x', '\n', '"'
                    val end = if (i + 1 < n && text[i + 1] == '\\') text.indexOf('\'', i + 3) else i + 2
                    code.append("' '")
                    i = (if (end < 0) n else end) + 1
                }
                else -> {
                    code.append(c)
                    i++
                }
            }
        }
        return Source(file, code.toString(), strings)
    }

    private val sources: List<Source> by lazy {
        val root = listOf(File("src/main/java"), File("app/src/main/java")).firstOrNull { it.isDirectory }
            ?: error("Le code de l'app est introuvable depuis ${File(".").absolutePath}")
        root.walkTopDown().filter { it.isFile && it.extension == "kt" }.map { lex(it.relativeTo(root).invariantSeparatorsPath, it.readText()) }.toList()
    }

    private fun filesWhere(found: (Source) -> Boolean): Set<String> = sources.filter(found).map { it.file.substringAfterLast('/') }.toSet()

    private fun uses(s: Source, word: Regex): Int = word.findAll(s.code).count()

    @Test fun `le lecteur de code ne compte ni les commentaires ni les chaînes`() {
        val s = lex(
            "x.kt",
            """
            // MERGE_ROUTE dans un commentaire
            /* api.merge(order) /* emboîté */ encore */
            val a = "code/pull/fusionner" // la route
            val b = '"'
            fun f() = api.merge(1, order) + MERGE_ROUTE.length
            val c = "racine/${'$'}MERGE_ROUTE"
            """.trimIndent(),
        )
        assertEquals(2, uses(s, Regex("\\bMERGE_ROUTE\\b")))
        assertEquals(1, uses(s, Regex("\\bapi\\.merge\\(")))
        assertEquals("code/pull/fusionner", s.strings.first())
        assertTrue(sources.size > 100)
    }

    @Test fun `la route de la fusion n'est écrite qu'une fois, dans les règles`() {
        assertEquals(setOf("ProjectsRules.kt"), filesWhere { s -> s.strings.any { "pull/fusionner" in it || it.endsWith("/fusionner") } })
        assertEquals(1, sources.sumOf { s -> s.strings.count { "fusionner" in it && "/" in it } })
    }

    @Test fun `seule l'API porte la route, et un seul de ses appels l'envoie`() {
        val named = Regex("\\bMERGE_ROUTE\\b")
        // les règles la nomment pour l'écarter des gestes génériques ; l'API pour la refuser à `gesture` et l'envoyer par `merge`
        assertEquals(setOf("ProjectsRules.kt", "ProjectsApi.kt"), filesWhere { uses(it, named) > 0 })
        val api = sources.single { it.file.endsWith("data/moi/projects/ProjectsApi.kt") }
        assertEquals(2, uses(api, named))
        // un seul envoi : la méthode `merge`, qui demande un ordre né d'une pull request relue
        assertEquals(1, uses(api, Regex("fun merge\\(project: Int, order: MergeOrder,")))
        val rules = sources.single { it.file.endsWith("data/moi/projects/ProjectsRules.kt") }
        // dans les règles, aucune requête n'est faite avec elle : `GestureRequest(MERGE_ROUTE…` n'existe pas
        assertEquals(0, uses(rules, Regex("GestureRequest\\(\\s*MERGE_ROUTE")))
        assertEquals(0, sources.sumOf { uses(it, Regex("GestureRequest\\(\\s*MERGE_ROUTE")) })
    }

    @Test fun `un seul endroit fabrique l'ordre de fusion et un seul le lance - la confirmation`() {
        // l'ordre ne se construit pas : son constructeur est privé, il naît de `MergeOrder.of(lecture)`
        val order = sources.single { it.file.endsWith("data/moi/projects/CodeRules.kt") }
        assertEquals(1, uses(order, Regex("class MergeOrder private constructor\\(")))
        assertEquals(setOf("CodeViewModels.kt"), filesWhere { uses(it, Regex("\\bMergeOrder\\.of\\(")) > 0 })
        assertEquals(1, sources.sumOf { uses(it, Regex("\\bMergeOrder\\.of\\(")) })
        // l'appel de l'API : une fois, dans `MergeFlow.confirm`
        assertEquals(setOf("CodeViewModels.kt"), filesWhere { uses(it, Regex("\\bapi\\.merge\\(")) > 0 })
        assertEquals(1, sources.sumOf { uses(it, Regex("\\bapi\\.merge\\(")) })
        // et la confirmation ne part que de deux écrans : la page d'une pull request, son attente d'« À faire »
        assertEquals(setOf("CodeViewModels.kt", "ProjectsViewModels.kt"), filesWhere { uses(it, Regex("\\bmerge\\.confirm\\(")) > 0 })
        assertEquals(setOf("CodeHostScreens.kt", "TodoScreen.kt"), filesWhere { uses(it, Regex("\\bMergeDialog\\(it,")) > 0 })
    }
}
