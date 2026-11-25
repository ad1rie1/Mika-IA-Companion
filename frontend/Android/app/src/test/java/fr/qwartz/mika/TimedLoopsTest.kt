package fr.qwartz.mika

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Rien ne se relit à intervalles (ADR 0308) : ce qui change ce que montrent les écrans est poussé par le direct
 * (`data/moi/Live`). Toute boucle de l'app qui attend (`while`, `do … while`, `for`, `repeat` dont le corps appelle
 * `delay(…)`), et toute fonction qui attend puis se rappelle (`suspend fun f() { …; delay(x); f() }`, ou un
 * `launch { delay(x); f() }` en elle), est listée ici avec sa raison — un affichage local, la connexion elle-même, une
 * attente que le serveur ne pousse pas — et son nombre : une seconde boucle identique dans le même fichier, comme une
 * boucle neuve qui relirait l'API, refuse le test. Ni `ticker`, ni `Timer`, ni `postDelayed`. Le code est examiné sans
 * ses commentaires ni ses chaînes : une doc qui nomme ce qu'il ne faut pas faire ne compte pas. Et un écran qui montre
 * un âge (« il y a 3 min ») prend son heure de `rememberNow`, pas d'une lecture figée de l'horloge.
 */
class TimedLoopsTest {
    /** Une attente admise : combien de fois elle paraît dans son fichier, et pourquoi. */
    private class Allowed(val count: Int, val why: String)

    private fun once(why: String) = Allowed(1, why)

    /** Les attentes admises, par fichier et par ce qu'elles attendent (l'argument de `delay`) : combien, et pourquoi. */
    private val allowed: Map<Pair<String, String>, Allowed> = mapOf(
        // la connexion elle-même : un battement applicatif, et la place que la file d'OkHttp fait (rien de l'API)
        "data/net/MikaSocket.kt" to "MikaProtocol.HEARTBEAT_INTERVAL_MS" to
            once("le battement de la socket : un ping toutes les 20 s, jamais une lecture de l'API"),
        "data/net/MikaSocket.kt" to "MikaProtocol.QUEUE_POLL_MS" to
            once("un envoi attend que la file d'OkHttp se vide assez (sondée en mémoire, sans réseau)"),
        // des affichages d'ici, sans rien relire
        "ui/avatar/AvatarBackdrop.kt" to "BlinkSchedule.nextGapMs(random, tired)" to once("son clignement d'yeux"),
        "ui/avatar/AvatarBackdrop.kt" to "BlinkSchedule.CLOSED_MS" to Allowed(2, "son clignement d'yeux, simple ou double"),
        "ui/avatar/AvatarBackdrop.kt" to "BlinkSchedule.DOUBLE_GAP_MS" to once("son clignement d'yeux, deux fois"),
        "ui/chat/ChatViewModel.kt" to "1_000" to once("le compte à rebours de « nouvel essai dans N s »"),
        "ui/chat/ChatViewModel.kt" to "Approvals.nextTickMs(state, wall, elapsed)" to
            once("l'échéance des cartes d'accord, recalculée sur l'horloge (les cartes viennent de la socket)"),
        "ui/components/Components.kt" to "intervalMs" to once("`rememberNow` : « il y a 3 min » avance tout seul"),
        "ui/components/WorkLine.kt" to "1_000L - Math.floorMod(now - since, 1_000L)" to
            once("le chrono de « elle s'y met » (ADR 0306), entre deux étapes poussées"),
        "ui/login/LoginScreen.kt" to "1000" to once("l'attente après trop d'essais de connexion, en secondes"),
        // des attentes que le direct ne peut pas pousser : rien ne passe par le journal
        "ui/mail/BoxPages.kt" to "SIGNIN_EVERY_MS" to
            once("la connexion Microsoft d'une boîte : `save_mail_grant` écrit hors du journal, rien n'est poussé"),
        "ui/projects/CodeViewModels.kt" to "wait" to
            once("après un geste chez l'hôte du code (GitHub…), deux relectures bornées : l'hôte n'est pas dans le journal"),
        "ui/carte/ExplorerViewModel.kt" to "PRELOAD_REREAD_MS" to
            once("après « Autour de moi », les notes que le serveur précharge d'un service extérieur : `search` se rappelle une fois (`reread`), rien du journal ne le dit"),
    )

    /** Un fichier sans ses commentaires ni ses chaînes (les gabarits `${…}` gardés : c'est du code). */
    private fun code(text: String): String {
        val out = StringBuilder(text.length)
        var i = 0
        val n = text.length

        fun newlines(from: Int, to: Int) {
            for (k in from until minOf(to, n)) if (text[k] == '\n') out.append('\n')
        }

        // une chaîne qui commence en [start] (après ses guillemets) : rend où elle finit ; ses gabarits vont dans [out]
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
                        // le code du gabarit, jusqu'à son accolade (les chaînes qu'il contient sont sautées)
                        var depth = 1
                        k += 2
                        out.append(' ')
                        while (k < n && depth > 0) {
                            val c = text[k]
                            when {
                                c == '"' -> {
                                    val r = text.startsWith("\"\"\"", k)
                                    val e = string(k + if (r) 3 else 1, r)
                                    out.append("\"\"")
                                    newlines(k, e)
                                    k = e
                                    continue
                                }
                                c == '{' -> depth++
                                c == '}' -> depth--
                            }
                            if (depth > 0) out.append(c)
                            k++
                        }
                        out.append(' ')
                    }
                    else -> {
                        if (text[k] == '\n') out.append('\n')
                        k++
                    }
                }
            }
            return n
        }

        while (i < n) {
            val c = text[i]
            when {
                text.startsWith("//", i) -> {
                    val e = text.indexOf('\n', i)
                    i = if (e < 0) n else e
                }
                text.startsWith("/*", i) -> {
                    var depth = 1
                    var e = i + 2
                    while (e < n && depth > 0) {
                        when {
                            text.startsWith("/*", e) -> { depth++; e += 2 }
                            text.startsWith("*/", e) -> { depth--; e += 2 }
                            else -> e++
                        }
                    }
                    newlines(i, e)
                    i = e
                }
                c == '"' -> {
                    val raw = text.startsWith("\"\"\"", i)
                    out.append("\"\"")
                    i = string(i + if (raw) 3 else 1, raw)
                }
                c == '\'' -> {
                    // un caractère : 'x', '\n', '\''
                    val e = if (i + 1 < n && text[i + 1] == '\\') text.indexOf('\'', i + 3) else text.indexOf('\'', i + 1)
                    out.append("' '")
                    i = (if (e < 0) n else e) + 1
                }
                else -> {
                    out.append(c)
                    i++
                }
            }
        }
        return out.toString()
    }

    /** L'indice de ce qui ferme [open] ouvert en [at] (−1 : rien). */
    private fun closing(s: String, at: Int, open: Char, close: Char): Int {
        var depth = 0
        for (k in at until s.length) {
            if (s[k] == open) depth++ else if (s[k] == close) {
                depth--
                if (depth == 0) return k
            }
        }
        return -1
    }

    /** Une attente : son fichier, ce qu'elle attend (l'argument de `delay`, espaces réduits), sa ligne. */
    private data class Wait(val file: String, val what: String, val line: Int)

    private val loop = Regex("\\b(while|for|repeat)\\s*\\(|\\bdo\\s*\\{")
    private val delayCall = Regex("\\bdelay\\s*\\(")
    private val function = Regex("\\bfun\\s+(?:<[^>]*>\\s*)?(?:[\\w.]+\\.)?(\\w+)\\s*\\(")

    /** Chaque `delay(…)` de [body] (qui commence en [at] dans le fichier) : où il est dans le fichier, et ce qu'il attend. */
    private fun delaysIn(body: String, at: Int): List<Pair<Int, String>> = delayCall.findAll(body).mapNotNull { d ->
        val close = closing(body, d.range.last, '(', ')')
        if (close < 0) null else (at + d.range.first) to body.substring(d.range.last + 1, close).split(Regex("\\s+")).filter { it.isNotEmpty() }.joinToString(" ")
    }.toList()

    /** Le corps d'une fonction dont la liste de paramètres se ferme en [params] : son bloc `{ … }`, ou son expression
     *  `= …` (jusqu'au bout de sa ligne, ce qu'elle ouvre compris) ; `null` : sans corps (abstraite). Rend son début. */
    private fun bodyOf(s: String, params: Int): Pair<Int, String>? {
        var k = params + 1
        while (k < s.length && s[k].isWhitespace()) k++
        if (k < s.length && s[k] == ':') {
            // son type de retour (des génériques et des parenthèses compris)
            var depth = 0
            k++
            while (k < s.length) {
                val c = s[k]
                if (s.startsWith("->", k)) k++ // un type de fonction : sa flèche n'ouvre ni ne ferme rien
                else if (c == '<' || c == '(') depth++ else if (c == '>' || c == ')') depth--
                else if (depth == 0 && (c == '{' || c == '=' || c == '\n')) break
                k++
            }
            while (k < s.length && (s[k] == ' ' || s[k] == '\t')) k++
        }
        if (k >= s.length) return null
        return when (s[k]) {
            '{' -> closing(s, k, '{', '}').takeIf { it >= 0 }?.let { k to s.substring(k, it) }
            '=' -> {
                var j = k + 1
                var depth = 0
                while (j < s.length) {
                    val c = s[j]
                    if (c == '(' || c == '{' || c == '[') depth++ else if (c == ')' || c == '}' || c == ']') depth--
                    else if (c == '\n' && depth <= 0) break
                    j++
                }
                k to s.substring(k, j)
            }
            else -> null
        }
    }

    /** Les fonctions qui attendent puis se rappellent : chaque `delay(…)` d'une fonction dont le corps l'appelle. */
    private fun recursions(s: String): List<Pair<Int, String>> = function.findAll(s).flatMap { m ->
        val name = m.groupValues[1]
        val params = closing(s, m.range.last, '(', ')')
        val (at, body) = (if (params < 0) null else bodyOf(s, params)) ?: return@flatMap emptyList()
        val calls = Regex("(?<![\\w.])" + Regex.escape(name) + "\\s*\\(|\\bthis\\." + Regex.escape(name) + "\\s*\\(")
        if (calls.containsMatchIn(body)) delaysIn(body, at) else emptyList()
    }.toList()

    /** Les attentes d'un fichier : les `delay(…)` d'une boucle ou d'une fonction qui se rappelle, chacun une fois (une
     *  boucle dans une boucle ne le compte pas deux fois). */
    private fun waits(file: String, text: String): List<Wait> {
        val s = code(text)
        val found = LinkedHashMap<Int, String>()
        for (m in loop.findAll(s)) {
            val open = if (m.value.startsWith("do")) {
                m.range.last
            } else {
                val parens = closing(s, m.range.last, '(', ')')
                if (parens < 0) continue
                var k = parens + 1
                while (k < s.length && s[k].isWhitespace()) k++
                if (k >= s.length || s[k] != '{') continue
                k
            }
            val end = closing(s, open, '{', '}')
            if (end < 0) continue
            for ((at, what) in delaysIn(s.substring(open, end), open)) found.putIfAbsent(at, what)
        }
        for ((at, what) in recursions(s)) found.putIfAbsent(at, what)
        return found.entries.sortedBy { it.key }.map { (at, what) -> Wait(file, what, s.substring(0, at).count { it == '\n' } + 1) }
    }

    /** Ce que [found] a de plus ou de moins que [allowed] : une attente non listée, ou plus de fois que listé ; une
     *  exception qui ne sert plus, ou moins de fois. */
    private fun mismatches(found: List<Wait>, allowed: Map<Pair<String, String>, Allowed>): Pair<List<String>, List<String>> {
        val counted = found.groupBy { it.file to it.what }
        val extra = counted.filter { (key, waits) -> waits.size > (allowed[key]?.count ?: 0) }
            .flatMap { (key, waits) -> waits.drop(allowed[key]?.count ?: 0).map { "${it.file}:${it.line} delay(${it.what})" + if (key in allowed) " (une de plus que listé)" else "" } }
        val stale = allowed.filter { (key, a) -> (counted[key]?.size ?: 0) < a.count }
            .map { (key, a) -> "${key.first} delay(${key.second}) : ${counted[key]?.size ?: 0} au lieu de ${a.count}" }
        return extra to stale
    }

    private val root: File by lazy {
        listOf(File("src/main/java/fr/qwartz/mika"), File("app/src/main/java/fr/qwartz/mika")).firstOrNull { it.isDirectory }
            ?: error("Le code de l'app est introuvable depuis ${File(".").absolutePath}")
    }

    private val sources: List<Pair<String, String>> by lazy {
        root.walkTopDown().filter { it.isFile && it.extension == "kt" }
            .map { it.relativeTo(root).invariantSeparatorsPath to it.readText() }.toList()
    }

    @Test fun `le lecteur ne voit ni les commentaires ni les chaînes, et trouve chaque boucle qui attend`() {
        val text = """
            // while (true) { delay(REFRESH_MS); load() } dans un commentaire
            /* while (true) { /* emboîté */ delay(1) } */
            val doc = "while (true) { delay(2) }"
            val tpl = "relu ${'$'}{if (a) "x" else "y"} fois"
            fun poll() {
                while (true) {
                    vm.load()
                    delay(REFRESH_MS)
                }
            }
            fun once() = scope.launch { delay(SOON) }
            fun tick() = flow { do { emit(Unit); delay( 1_000 ) } while (true) }
            fun bounded() { for (wait in SETTLES) { delay(wait); read() } }
            fun twice() { repeat(2) { delay(GAP) } }
            fun nested() { while (on) { repeat(3) { delay(INNER) } } }
            suspend fun poll2() { vm.load(); delay(EVERY); poll2() }
            fun later(): Job = scope.launch { delay(SOON); this.later() }
            fun notMe() = scope.launch { delay(SOON); later2() }
        """.trimIndent()
        val found = waits("x.kt", text)
        assertEquals(listOf("REFRESH_MS", "1_000", "wait", "GAP", "INNER", "EVERY", "SOON"), found.map { it.what })
        assertEquals(listOf(8, 12, 13, 14, 15, 16, 17), found.map { it.line })
        assertTrue("le code de l'app n'a pas été lu", sources.size > 100)
    }

    @Test fun `chaque attente compte - une seconde boucle identique dans le même fichier se voit`() {
        val listed = mapOf(("x.kt" to "EVERY") to once("une"), ("x.kt" to "GAP") to Allowed(2, "deux"))
        val two = waits("x.kt", "fun a() { while (true) { delay(EVERY) } }\nfun b() { while (true) { delay(EVERY) } }\nfun c() { repeat(2) { delay(GAP) } }")
        val (extra, stale) = mismatches(two, listed)
        assertEquals(listOf("x.kt:2 delay(EVERY) (une de plus que listé)"), extra)
        assertEquals(listOf("x.kt delay(GAP) : 1 au lieu de 2"), stale)
    }

    @Test fun `aucune boucle ne relit l'API à intervalles - chaque attente est listée avec sa raison et son nombre`() {
        val found = sources.flatMap { (file, text) -> waits(file, text) }
        val (unknown, stale) = mismatches(found, allowed)
        assertTrue(
            "Une attente n'est pas listée, ou plus de fois que listé (le direct, ADR 0308, pousse ce qui change : " +
                "s'abonner plutôt que relire à intervalles) :\n" + unknown.joinToString("\n"),
            unknown.isEmpty(),
        )
        assertTrue("Une exception ne sert plus, ou moins de fois (à corriger) :\n" + stale.joinToString("\n"), stale.isEmpty())
        for ((key, a) in allowed) assertTrue("${key.first} : sa raison", a.why.length > 10)
    }

    /** Ce qui écrit un âge à l'écran : « il y a 3 min », « relevée il y a », « dernier envoi », « vu il y a », l'extension
     *  Teams qui se tait. */
    private val ages = Regex("\\b(ago|boxStatusLine|batchWords|phoneBar|quietLine)\\s*\\(")
    private val wallClock = Regex("\\bclock\\.wallMs\\s*\\(\\s*\\)|\\bcurrentTimeMillis\\s*\\(")

    @Test fun `un âge affiché avance tout seul - un écran qui en montre prend son heure de rememberNow`() {
        val showing = sources.filter { (file, text) -> file.startsWith("ui/") && ages.containsMatchIn(code(text)) }
        assertTrue("aucun écran ne montre d'âge : la garde ne voit rien", showing.size >= 4)
        val frozen = showing.filter { (_, text) -> wallClock.containsMatchIn(code(text)) }.map { it.first }
        assertTrue(
            "Un écran montre un âge sur une heure lue une fois (il n'avancerait qu'à un changement) : " +
                "`rememberNow(wallMs = graph.clock::wallMs)` plutôt que `graph.clock.wallMs()` :\n" + frozen.joinToString("\n"),
            frozen.isEmpty(),
        )
    }

    @Test fun `ni ticker, ni Timer, ni postDelayed`() {
        val banned = Regex("\\b(ticker|fixedRateTimer|scheduleAtFixedRate|postDelayed|Timer)\\s*\\(")
        val hits = sources.flatMap { (file, text) -> banned.findAll(code(text)).map { "$file : ${it.value}" }.toList() }
        assertTrue(hits.joinToString("\n"), hits.isEmpty())
    }
}
