package fr.qwartz.mika.data.moi.mail

/*
 * Ce que Mail écrit d'une taille, d'une pièce et d'un texte : en français, comme le client web
 * (`frontend/Web/src/screens/mail/`), pur et testé sur la JVM. Les instants et les personnes : `data/moi/MoiText.kt`.
 */

/** « 512 o », « 212 Ko », « 1,8 Mo ». */
fun sizeLabel(bytes: Long): String = when {
    bytes < 0 -> ""
    bytes < 1024 -> "$bytes o"
    bytes < 1024 * 1024 -> "${Math.round(bytes / 1024.0)} Ko"
    else -> {
        val mo = Math.round(bytes / (1024.0 * 1024.0) * 10) / 10.0
        (if (mo % 1.0 == 0.0) mo.toLong().toString() else mo.toString().replace('.', ',')) + " Mo"
    }
}

/** La sorte d'une pièce, en court : son extension (« PDF »), sinon son type (« JPEG »), sinon « FICHIER ». */
fun attachmentKind(name: String, mime: String): String {
    Regex("""\.([a-z0-9]{1,5})$""", RegexOption.IGNORE_CASE).find(name)?.let { return it.groupValues[1].uppercase() }
    val sub = mime.substringAfter('/', "")
    val head = sub.split(Regex("""[.+;-]""")).firstOrNull().orEmpty()
    return head.take(5).uppercase().ifEmpty { "FICHIER" }
}

/** Un bloc du texte d'un mail : un paragraphe ([depth] 0), ou ce qu'il cite (« > », [depth] ≥ 1, imbriqué). */
data class BodyBlock(val depth: Int, val text: String)

/**
 * Le texte d'un mail en blocs : ses paragraphes (une ligne vide les sépare), ses retours à la ligne gardés, et ce
 * qu'il cite (« > ») à part, à sa profondeur. Les blancs du début et de la fin d'un bloc sont retirés.
 */
fun bodyBlocks(body: String): List<BodyBlock> {
    val out = mutableListOf<BodyBlock>()
    var depth = 0
    val lines = mutableListOf<String>()
    fun flush() {
        val text = lines.joinToString("\n").trim('\n', ' ', '\t')
        if (text.isNotBlank()) out += BodyBlock(depth, text)
        lines.clear()
    }
    for (raw in body.replace("\r\n", "\n").replace('\r', '\n').split('\n')) {
        var line = raw
        var d = 0
        while (true) {
            val m = Regex("""^\s*> ?""").find(line) ?: break
            line = line.substring(m.range.last + 1)
            d++
        }
        if (d != depth) {
            flush()
            depth = d
        }
        if (d == 0 && line.isBlank()) {
            flush()
            continue
        }
        lines += line
    }
    flush()
    return out
}
