package fr.qwartz.mika.ui.components

/**
 * Mise en forme légère d'une réponse — portage de `frontend/Web/src/ui/inlineMarkup.ts` : blocs de
 * code (```), code en ligne (`x`) et gras (`**texte**`). Les modèles écrivent du Markdown qu'une bulle
 * montrerait sinon tel quel. Pur : le rendu (AnnotatedString) se fait dans l'écran.
 */
object InlineMarkup {
    sealed interface Block {
        data class Text(val text: String) : Block
        data class Code(val text: String, val lang: String) : Block
    }

    sealed interface Inline {
        data class Text(val text: String) : Inline
        data class Bold(val text: String) : Inline
        data class Code(val text: String) : Inline
    }

    private val FENCE = Regex("""```([\w+-]*)[ \t]*\n?([\s\S]*?)\n?```""")
    private val INLINE = Regex("""`([^`\n]+)`|\*\*(?=\S)([\s\S]*?\S)\*\*""")

    fun parseBlocks(text: String): List<Block> {
        val out = mutableListOf<Block>()
        var last = 0
        for (m in FENCE.findAll(text)) {
            if (m.range.first > last) out += Block.Text(text.substring(last, m.range.first))
            out += Block.Code(m.groupValues[2], m.groupValues[1])
            last = m.range.last + 1
        }
        if (last < text.length) out += Block.Text(text.substring(last))
        return out
    }

    fun parseInline(text: String): List<Inline> {
        val out = mutableListOf<Inline>()
        var last = 0
        for (m in INLINE.findAll(text)) {
            if (m.range.first > last) out += Inline.Text(text.substring(last, m.range.first))
            out += if (m.groups[1] != null) Inline.Code(m.groupValues[1]) else Inline.Bold(m.groupValues[2])
            last = m.range.last + 1
        }
        if (last < text.length) out += Inline.Text(text.substring(last))
        return out
    }

    /** Les sauts de ligne qui entourent un bloc de code sont portés par le bloc lui-même. */
    fun trimAroundBlocks(text: String): String = text.trimStart('\n').trimEnd('\n')

    /**
     * Le texte sans ses marques (astérisques, accents graves) : ce qu'un lecteur d'écran doit dire, et
     * ce qu'on copie. Les blocs de code restent, sur leurs propres lignes.
     */
    fun plain(text: String): String = parseBlocks(text).joinToString("\n") { block ->
        when (block) {
            is Block.Code -> block.text
            is Block.Text -> parseInline(trimAroundBlocks(block.text)).joinToString("") {
                when (it) {
                    is Inline.Text -> it.text
                    is Inline.Bold -> it.text
                    is Inline.Code -> it.text
                }
            }
        }
    }.trim()
}
