package fr.qwartz.mika.data.moi

import org.w3c.dom.Element
import java.io.File
import java.util.Locale
import javax.xml.parsers.DocumentBuilderFactory

/**
 * Les textes de l'app lus dans `src/main/res/values/strings.xml`, pour les tests JVM, qui n'ont pas les ressources
 * d'Android : un texte, ou l'élément d'un pluriel choisi comme Android le fait en français (« one » pour 0 et 1,
 * « many » pour les millions ronds, « other » sinon), ses échappements (`\'`) défaits. Les tests jugent ainsi les vrais
 * mots, pas une copie.
 */
object AppStrings {
    private val root: Element by lazy {
        DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(File("src/main/res/values/strings.xml")).documentElement
    }

    private fun named(tag: String, name: String): Element {
        val nodes = root.getElementsByTagName(tag)
        for (i in 0 until nodes.length) {
            val e = nodes.item(i) as Element
            if (e.getAttribute("name") == name) return e
        }
        error("« $name » n'est pas dans strings.xml")
    }

    private fun unescaped(text: String): String = Regex("""\\(.)""").replace(text) { m ->
        when (val c = m.groupValues[1]) {
            "n" -> "\n"
            "t" -> "\t"
            else -> c
        }
    }

    fun string(name: String): String = unescaped(named("string", name).textContent)

    fun plural(name: String, n: Int, vararg args: Any): String {
        val quantity = when {
            n == 0 || n == 1 -> "one"
            n % 1_000_000 == 0 -> "many"
            else -> "other"
        }
        val items = named("plurals", name).getElementsByTagName("item")
        val all = (0 until items.length).map { items.item(it) as Element }
        val item = all.firstOrNull { it.getAttribute("quantity") == quantity } ?: all.first { it.getAttribute("quantity") == "other" }
        return String.format(Locale.FRENCH, unescaped(item.textContent), *args)
    }
}

/** Les mots de « Corriger », tels que `rememberCorrectWords` les tire de `strings.xml`. */
val correctWords: CorrectWords by lazy {
    CorrectWords(
        empty = AppStrings.string("correct_empty"),
        none = AppStrings.string("correct_none"),
        untouched = AppStrings.string("correct_untouched"),
        moved = AppStrings.string("correct_moved"),
        off = AppStrings.string("correct_off"),
        fixed = { n -> AppStrings.plural("correct_done", n, n) },
        fixedDropped = { n, r -> AppStrings.plural("correct_dropped", r, AppStrings.plural("correct_done_part", n, n), r) },
    )
}
