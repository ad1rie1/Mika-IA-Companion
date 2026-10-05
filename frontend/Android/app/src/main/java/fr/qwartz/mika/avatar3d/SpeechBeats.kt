package fr.qwartz.mika.avatar3d

/** La nature d'un temps fort de la parole ; `rank` départage deux temps forts tombés sur le même caractère. */
enum class BeatKind(internal val rank: Int) {
    /** Premier mot d'une proposition : une prise d'air rapide, la tête se relève un peu. */
    PHRASE_START(0),

    /** Un mot plein appuyé : un petit hochement. */
    STRESS(2),

    /** L'insistance — un intensif, des MAJUSCULES, un *mot*, une exclamation : un hochement plus franc, les sourcils qui sautent. */
    EMPHASIS(5),

    /** Virgule, deux-points, point-virgule : la tête se réoriente, une prise d'air. */
    PAUSE(1),

    /** « … » — la phrase qui traîne : une inclinaison douce. */
    TRAIL(3),

    /** Dernier mot d'une question : le menton levé, la tête penchée, les sourcils tenus levés. */
    QUESTION(6),

    /** Dernier mot d'une affirmation : le hochement qui la ferme. */
    FINAL(4),
}

/** Un temps fort : où il tombe (indice de caractère dans le texte COMPLET de la réplique), sa nature, sa force 0…1. */
data class SpeechBeat(val at: Int, val kind: BeatKind, val strength: Float)

/** Un jeton de prosodie que la voix « jouerait » : un soupir, un rire, une inspiration. */
enum class SpeechCueKind { SIGH, LAUGH, BREATH }

/** Un jeton de prosodie et l'indice de son `[` dans le texte complet. */
data class SpeechCue(val at: Int, val kind: SpeechCueKind)

/**
 * Où le corps ponctue une phrase — de l'analyse de texte pure, port de `speechBeats.ts`.
 *
 * On ne parle pas avec une tête immobile posée sur une boucle enregistrée : la tête plonge sur les mots qu'on appuie,
 * les sourcils sautent sur l'insistance, une question finit menton levé et tête penchée, une affirmation se pose d'un
 * petit hochement, et chaque proposition commence sur une prise d'air. Ce sont ces temps forts qu'un auditeur lit
 * comme « elle pense ce qu'elle dit » (les gestes de battement de McNeill ; Graf et al. 2002 sur la tête et la
 * prosodie).
 *
 * Il n'y a aucune prosodie à lire (le web n'a pas l'audio de sa synthèse, l'app n'a pas de voix du tout) : les temps
 * forts sont placés sur le TEXTE et partent quand le curseur — le caractère que la bouche prononce, ici celui que la
 * bulle affiche — les atteint. Les indices sont des positions dans le texte complet de la réplique, le même contrat
 * que le lip-sync.
 *
 * Ce qui est propre au français : l'accent tombe à la FIN d'un groupe rythmique (le dernier mot plein avant une pause
 * porte le battement), et l'accent d'insistance va aux intensifs et aux mots écrits en capitales.
 */
object SpeechBeats {
    /** Le plan des temps forts, trié, un seul par caractère (le plus fort l'emporte). */
    fun plan(text: String): List<SpeechBeat> {
        val masked = maskTokens(text)
        val beats = ArrayList<SpeechBeat>()
        // Les phrases finissent sur . ! ? … (en série, regroupés) ; le terminateur décide du battement qui ferme. Le
        // texte après le dernier terminateur est une phrase aussi.
        for (m in SENTENCE.findAll(masked)) {
            if (m.value.isBlank()) continue
            planSentence(m.range.first, m.value, beats)
        }
        val sorted = beats.sortedWith(compareBy<SpeechBeat> { it.at }.thenByDescending { it.kind.rank })
        // Un seul temps fort par position : le premier après le tri, donc le plus fort.
        return sorted.filterIndexed { i, b -> i == 0 || sorted[i - 1].at != b.at }
    }

    /**
     * Les jetons de prosodie de la réplique, dans l'ordre : ce que la voix du web joue (`[SIGH]`, `[LAUGH]`,
     * `[BREATH]`, sans égard à la casse, comme `TTSService`). `[PAUSE:ms]` n'en est pas un : c'est un silence, pas un
     * geste.
     */
    fun cues(text: String): List<SpeechCue> = CUE.findAll(text).map { m ->
        val kind = when (m.groupValues[1].uppercase()) {
            "SIGH" -> SpeechCueKind.SIGH
            "LAUGH" -> SpeechCueKind.LAUGH
            else -> SpeechCueKind.BREATH
        }
        SpeechCue(m.range.first, kind)
    }.toList()

    /**
     * Les jetons que la voix ne dit pas (`[SIGH]`, `[PAUSE:300]`…) deviennent des espaces de même longueur : aucun
     * battement ne tombe dedans, et les indices restent ceux du texte complet.
     */
    internal fun maskTokens(text: String): String = TOKEN.replace(text) { " ".repeat(it.value.length) }

    private class Word(val text: String, val start: Int, val shouted: Boolean)

    private fun planSentence(offset: Int, sentence: String, out: MutableList<SpeechBeat>) {
        val words = WORD.findAll(sentence).map { w ->
            val raw = w.value
            val starred = raw.length > 2 && raw.startsWith("*") && raw.endsWith("*")
            val clean = raw.replace("*", "")
            val letters = clean.replace(NON_LETTER, "")
            val shouted = starred ||
                (letters.length >= 2 && letters == letters.uppercase() && letters != letters.lowercase())
            Word(clean, offset + w.range.first + (if (raw.startsWith("*")) 1 else 0), shouted)
        }.toList()
        if (words.isEmpty()) return

        val terminator = TERMINATOR.find(sentence.trimEnd())?.value ?: ""
        val exclaim = '!' in terminator

        out.add(SpeechBeat(words[0].start, BeatKind.PHRASE_START, 0.6f))

        var lastBeat = words[0].start
        for ((i, word) in words.withIndex()) {
            val lower = word.text.lowercase().replace(ELISION, "")
            val content = lower !in STOPWORDS && lower.length >= 4
            val gap = word.start - lastBeat

            if (word.shouted || lower in INTENSIFIERS) {
                if (gap >= 6 || i == 0) {
                    out.add(SpeechBeat(word.start, BeatKind.EMPHASIS, if (word.shouted) 1f else 0.8f))
                    lastBeat = word.start
                }
                continue
            }

            // Une ponctuation de proposition juste après ce mot : il ferme un groupe rythmique — c'est là que le
            // français met l'accent.
            val end = word.start - offset + word.text.length
            val rest = sentence.substring(end)
            val after = AFTER.find(rest)?.groupValues?.get(1) ?: ""
            if (after == "," || after == ";" || after == ":") {
                if (content && gap >= 6) {
                    out.add(SpeechBeat(word.start, BeatKind.STRESS, 0.75f))
                    lastBeat = word.start
                }
                out.add(SpeechBeat(offset + end + rest.indexOf(after), BeatKind.PAUSE, 0.6f))
                continue
            }

            if (content && (gap >= STRESS_GAP || (gap >= FORCE_GAP && lower.length >= 3))) {
                out.add(SpeechBeat(word.start, BeatKind.STRESS, minOf(1f, 0.45f + lower.length * 0.05f)))
                lastBeat = word.start
            }
        }

        // Le battement qui ferme tombe sur le dernier mot : la tête bouge AVEC lui, pas une fois la voix tue.
        val last = words.last()
        val kind = when {
            '?' in terminator -> BeatKind.QUESTION
            '…' in terminator || terminator.startsWith("...") -> BeatKind.TRAIL
            exclaim -> BeatKind.EMPHASIS
            else -> BeatKind.FINAL
        }
        // Ce qui est déjà posé à quelques caractères du battement final ne ferait que le brouiller. Comme le web, le
        // balayage porte sur tout le plan : une phrase d'un mot juste après une autre efface la fin de la précédente.
        out.removeAll { b ->
            b.at >= last.start - 5 && b.at <= last.start + last.text.length && b.kind != BeatKind.PHRASE_START
        }
        out.add(SpeechBeat(last.start, kind, if (kind == BeatKind.EMPHASIS) 0.9f else 0.8f))
    }

    /** Au moins tant de caractères entre deux accents ; et l'écart au-delà duquel un mot plein en reçoit un quoi qu'il arrive (une longue proposition bouge encore). */
    private const val STRESS_GAP = 10
    private const val FORCE_GAP = 30

    /**
     * Les jetons de contrôle que la voix ne dit pas. Le motif du web (`[A-Z_]+`, en capitales), plus les jetons de
     * la voix sans égard à la casse — `TTSService` les reconnaît en minuscules aussi, et un `[sigh]` lu comme un mot
     * recevrait un battement.
     */
    private val TOKEN = Regex("""\[[A-Z_]+(?::[^\]]*)?]|\[(?i:pause(?::\d+)?|sigh|laugh|breath)]""")
    private val CUE = Regex("""\[(?i)(sigh|laugh|breath)]""")

    // `\z` plutôt que `$` : en Java, `$` s'arrête aussi devant un dernier saut de ligne. `(?U)` : `\s` comme en
    // JavaScript, espaces insécables compris — le français en met devant « : ; ? ! ».
    private val SENTENCE = Regex("""[^.!?…]+(?:[.!?…]+|\z)""")
    private val WORD = Regex("""\*?[\p{L}\p{N}][\p{L}\p{N}'’-]*\*?""")
    private val NON_LETTER = Regex("""[^\p{L}]""")
    private val TERMINATOR = Regex("""[.!?…]+\z""")
    private val ELISION = Regex("""^[dlmtsjcnq][’']""")
    private val AFTER = Regex("""(?U)^\s*([,;:]|\.\.\.|…)?""")

    private val STOPWORDS: Set<String> = setOf(
        "le", "la", "les", "un", "une", "des", "de", "du", "d", "l", "et", "ou", "mais",
        "donc", "or", "ni", "car", "que", "qu", "qui", "quoi", "je", "j", "tu", "il",
        "elle", "on", "nous", "vous", "ils", "elles", "me", "m", "te", "t", "se", "s",
        "ma", "ta", "sa", "mon", "ton", "son", "mes", "tes", "ses", "notre", "votre",
        "nos", "vos", "leur", "leurs", "ce", "cet", "cette", "ces", "c", "ça", "ca",
        "en", "y", "à", "a", "au", "aux", "dans", "par", "pour", "sur", "avec", "sans",
        "sous", "chez", "ne", "n", "pas", "plus", "est", "es", "suis", "sont", "ai",
        "as", "avait", "était", "être", "avoir", "fait", "faire", "dit", "lui", "moi",
        "toi", "si", "comme", "quand", "alors", "aussi", "bien", "oui", "non", "là",
        "the", "an", "and", "to", "of", "in", "is", "it", "you", "i",
    )

    private val INTENSIFIERS: Set<String> = setOf(
        "très", "vraiment", "trop", "tellement", "super", "jamais", "absolument",
        "carrément", "grave", "hyper", "énormément", "toujours", "rien", "tout",
        "totalement", "complètement", "franchement", "adore", "déteste", "génial",
        "incroyable", "magnifique", "horrible", "énorme",
    )
}
