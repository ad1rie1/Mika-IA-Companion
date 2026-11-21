package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.core.MikaJson
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId

/**
 * Les règles pures de l'onglet Code : ses volets et leurs adresses, la coloration d'une ligne (qui ne change jamais son
 * texte), la mise en lignes d'un diff unifié, l'arborescence un dossier à la fois, les jours d'une ligne de temps, et
 * les requêtes d'une pull request — la fusionner seulement sur ce que le serveur ouvre, en nommant le commit de tête
 * lu ; la modifier sans rien envoyer qui ne change ; y répondre.
 */
class CodeRulesTest {
    private val zone = ZoneId.of("Europe/Paris")
    private val now = 1_795_600_000_000L
    private val head = "8f41c2e09d77a1b2c3d4e5f60718293a4b5c6d7e"

    private fun pull(json: String): CodePull = MikaJson.decodeFromString(CodePull.serializer(), json)

    private fun detail(p: CodePull, commits: Int = 2, diff: Diff = Diff()) = PullDetail(p, (1..commits).map { Commit(sha = "c$it") }, diff)

    private val ready = pull(
        """{"number":11,"title":"objectif 4","state":"ready","state_label":"prête à fusionner","branch":"ticket-2-export-csv","base":"main",
            "head":"$head","objective":{"id":4,"text":"Exporter la liste des hôtes en CSV","kind":"once"},
            "checks":{"state":"passed","state_label":"passée"},"review":{"ok":true,"label":"rien à redire"},
            "merge":{"can":true,"why":""}}""",
    )

    // ── Les volets, les adresses ──

    @Test fun `un volet inconnu ou vide est Fichiers, et l'adresse d'un onglet peut nommer son volet`() {
        assertEquals(CodeTabs.FILES, CodeTabs.of(""))
        assertEquals(CodeTabs.FILES, CodeTabs.of("nope"))
        assertEquals(CodeTabs.PULLS, CodeTabs.of("pulls"))
        assertEquals("code/pulls", CodeTabs.tab(CodeTabs.PULLS))
        val sheet = Sheet(rights = Rights(detail = true))
        assertEquals(SheetTabs.CODE, SheetTabs.shown(sheet, "code/pulls"))
        assertEquals("pulls", SheetTabs.sub("code/pulls"))
        assertEquals("", SheetTabs.sub("code"))
        // qui ne fait que voir le projet n'a pas l'onglet, quel que soit le volet nommé
        assertEquals(SheetTabs.OVERVIEW, SheetTabs.shown(Sheet(), "code/pulls"))
    }

    @Test fun `les comptes de la barre - ceux du serveur, la CI seulement quand elle a des échecs`() {
        val c = CodeCounts(commits = 12, branches = 4, pullsOpen = 3, issuesOpen = 2, checksFailed = 0)
        assertNull(CodeTabs.count(CodeTabs.FILES, c))
        assertEquals(12, CodeTabs.count(CodeTabs.COMMITS, c))
        assertEquals(3, CodeTabs.count(CodeTabs.PULLS, c))
        assertNull(CodeTabs.count(CodeTabs.CI, c))
        assertEquals(1, CodeTabs.count(CodeTabs.CI, c.copy(checksFailed = 1)))
    }

    @Test fun `la clé d'une pull request - son numéro, ou son objectif tant qu'elle n'en a pas`() {
        assertEquals("11", pullKey(ready))
        assertEquals("o4", pullKey(ready.copy(number = 0)))
        assertEquals(PullName(11, 0), parsePullKey("11"))
        assertEquals(PullName(0, 4), parsePullKey("o4"))
        assertEquals(PullName(0, 0), parsePullKey("../etc"))
        assertEquals(CodeTabs.PULLS, CodePages.home(CodePages.PULL))
        assertEquals(CodeTabs.FILES, CodePages.home("inconnu"))
        assertEquals(PullPanes.SUMMARY, PullPanes.of(""))
        assertEquals(PullPanes.FILES, PullPanes.of("fichiers"))
    }

    // ── Le code, en jetons ──

    @Test fun `une ligne en jetons redonne la ligne même, caractère pour caractère`() {
        val lines = listOf(
            "    \"\"\"Se connecter en RDP à un hôte.\"\"\"  # et garder la trace",
            "@dataclass(frozen=True)",
            "def connect(host: str, port: int = PORT, timeout: float = 2.5) -> None:",
            "PORT = 3389",
            "<script>alert('x')</script> [lien](https://exemple.invalid)",
            "",
        )
        for (path in listOf("a.py", "b.ts", "c.toml", "README.md", "sans-extension")) {
            for (line in lines) assertEquals(line, tokens(line, path).joinToString("") { it.text })
        }
    }

    @Test fun `la coloration ne pose que des sortes de jeton - mot-clé, chaîne, commentaire, nombre`() {
        val got = tokens("def f(x): return 42  # fin", "f.py")
        assertEquals(TokenKind.KEYWORD, got.first().kind)
        assertEquals("def", got.first().text)
        assertTrue(got.any { it.kind == TokenKind.NUMBER && it.text == "42" })
        assertEquals(TokenKind.COMMENT, got.last().kind)
        // un fichier sans grammaire connue, ou une ligne démesurée : un seul jeton, tel quel
        assertEquals(listOf(Token(TokenKind.PLAIN, "def f(x): return 42")), tokens("def f(x): return 42", "notes.txt"))
        val huge = "x = 1;".repeat(600)
        assertEquals(listOf(Token(TokenKind.PLAIN, huge)), tokens(huge, "min.js"))
    }

    @Test fun `ce qu'une ligne montre - ses tabulations en espaces, coupée au-delà, la plus large mesurée`() {
        assertEquals("    if x:", shownLine("\tif x:"))
        val long = "a".repeat(LINE_SHOWN + 50)
        assertEquals(LINE_SHOWN + 2, shownLine(long).length)
        assertTrue(anyLineCut(listOf("court", long)))
        assertFalse(anyLineCut(listOf("court")))
        // un caractère large compte double : la ligne la plus large n'est pas toujours la plus longue
        assertEquals("日本語日本語", widestLine(listOf("abcdefghij", "日本語日本語")))
        assertEquals("", widestLine(emptyList()))
    }

    @Test fun `les mots d'un fichier - ses lignes, son poids, son langage, s'il est en Markdown`() {
        assertEquals(listOf("a", "b"), linesOf("a\r\nb\n"))
        assertEquals(listOf("a", "", "b"), linesOf("a\n\nb"))
        assertEquals(listOf(""), linesOf(""))
        assertEquals("812 o", sizeWords(812))
        assertEquals("1,3 Ko", sizeWords(1331))
        assertEquals("2 Mo", sizeWords(2_097_152))
        assertEquals("Python", languageOf("outils_reseau/rdp.py"))
        assertEquals("texte", languageOf("LICENSE"))
        assertTrue(isMarkdown("README.md"))
        assertTrue(isMarkdown("docs/GUIDE.Markdown"))
        assertFalse(isMarkdown("md.py"))
    }

    // ── Un diff ──

    private val hunks = listOf(
        Hunk("@@ -1,3 +1,4 @@", listOf(DiffLine(" ", 1, 1, "import json"), DiffLine("-", 2, 0, "PORT = 22"), DiffLine("+", 0, 2, "PORT = 3389"), DiffLine("+", 0, 3, "TIMEOUT = 2"))),
        Hunk("@@ -98,2 +99,2 @@ def connect", listOf(DiffLine(" ", 98, 99, "    pass"), DiffLine(" ", 99, 100, ""))),
    )

    @Test fun `un diff unifié - l'en-tête de chaque passage puis ses lignes, leurs deux numéros, rien quand la ligne n'y est pas`() {
        val rows = unifiedRows(hunks)
        assertEquals(8, rows.size)
        assertEquals(DiffRow.Head("@@ -1,3 +1,4 @@"), rows[0])
        assertEquals(DiffRow.Head("@@ -98,2 +99,2 @@ def connect"), rows[5])
        val removed = (rows[2] as DiffRow.Line).line
        assertEquals("2", lineNumber(removed.old))
        assertEquals("", lineNumber(removed.new))
        val added = (rows[3] as DiffRow.Line).line
        assertEquals("", lineNumber(added.old))
        assertEquals("2", lineNumber(added.new))
        // la largeur des colonnes de numéros suit le plus grand (deux chiffres au moins)
        assertEquals(3, numberDigits(hunks))
        assertEquals(2, numberDigits(hunks.take(1)))
        assertEquals(2, numberDigits(emptyList()))
    }

    @Test fun `un fichier de diff dit ce qu'il montre - caché, binaire, coupé - sans rien inventer`() {
        assertEquals(DiffBody.LINES, diffBody(DiffFile(path = "a.py", hunks = hunks)))
        assertEquals(DiffBody.HIDDEN, diffBody(DiffFile(path = ".env", hidden = true, why = "Un fichier caché.", hunks = hunks)))
        assertEquals(DiffBody.BINARY, diffBody(DiffFile(path = "logo.png", binary = true)))
        assertEquals(DiffBody.NOTHING, diffBody(DiffFile(path = "gros.py", cut = true)))
        assertTrue(canReadWhole(DiffFile(path = "gros.py", cut = true)))
        assertFalse(canReadWhole(DiffFile(path = ".env", cut = true, hidden = true)))
        assertFalse(canReadWhole(DiffFile(path = "a.py")))
        assertEquals("3 fichiers", filesWords(Diff(files = List(3) { DiffFile(path = "f$it") })))
    }

    // ── L'arborescence ──

    @Test fun `l'arborescence un dossier à la fois - un dossier ouvert montre les siens, pas encore lu il le dit`() {
        val root = Tree(items = listOf(TreeEntry("src", "src", "dir"), TreeEntry("README.md", "README.md", "file")), hidden = 2)
        val src = Tree(path = "src", items = listOf(TreeEntry("src/a.py", "a.py", "file")))
        val trees = mapOf("" to root, "src" to src)
        // replié : la racine seule, et ce qu'elle tait
        val folded = treeRows("", { trees[it] }, { "" }, emptySet())
        assertEquals(listOf("src", "README.md"), folded.filterIsInstance<TreeRow.Node>().map { it.entry.name })
        assertEquals(TreeRow.Hidden("", 0, 2), folded.last())
        // ouvert et lu : ses entrées en retrait
        val open = treeRows("", { trees[it] }, { "" }, setOf("src"))
        assertEquals(listOf(0, 1, 0, 0), open.map { it.depth })
        assertTrue((open[0] as TreeRow.Node).open)
        assertEquals("a.py", (open[1] as TreeRow.Node).entry.name)
        // ouvert, pas encore lu, ou refusé avec les mots du serveur
        val pending = treeRows("", { if (it == "") root else null }, { "" }, setOf("src"))
        assertEquals(TreeRow.Pending("src", 1, ""), pending[1])
        val failed = treeRows("", { if (it == "") root else null }, { "Ce projet ne t'ouvre pas ses fichiers…" }, setOf("src"))
        assertEquals("Ce projet ne t'ouvre pas ses fichiers…", (failed[1] as TreeRow.Pending).error)
    }

    // ── Les mots ──

    @Test fun `les commits par jour, dans l'ordre où ils viennent`() {
        val day = 86_400_000L
        val items = listOf(Commit(sha = "a", at = now - 1000), Commit(sha = "b", at = now - 2000), Commit(sha = "c", at = now - day), Commit(sha = "d", at = now - 20 * day))
        val groups = byDay(items, { it.at }, now, zone)
        assertEquals(listOf("Aujourd'hui", "Hier"), groups.take(2).map { it.label })
        assertEquals(listOf(listOf("a", "b"), listOf("c"), listOf("d")), groups.map { g -> g.items.map { it.sha } })
        assertTrue(byDay(emptyList<Commit>(), { it.at }, now, zone).isEmpty())
    }

    @Test fun `ce qu'un commit et une branche disent d'eux`() {
        assertEquals("#5", commitAbout(Commit(ticket = 5, objective = 2)))
        assertEquals("obj. 2", commitAbout(Commit(objective = 2)))
        assertEquals("", commitAbout(Commit()))
        assertEquals("La suite.\n\nEt la fin.", messageRest(Commit(title = "rdp : squelette", body = "rdp : squelette\n\nLa suite.\n\nEt la fin.\n")))
        assertEquals("", messageRest(Commit(title = "rdp : squelette", body = "rdp : squelette")))
        assertEquals("2 commits d'avance sur main, 0 de retard", aheadBehind(Branch(name = "ticket-2", ahead = 2), "main"))
        assertEquals("la branche par défaut", aheadBehind(Branch(name = "main", base = true), "main"))
        assertEquals("Ticket #2", branchAbout(Branch(ticket = TicketLine(number = 2), objective = LinkedObjective(id = 4))))
        assertEquals("Objectif n° 4", branchAbout(Branch(objective = LinkedObjective(id = 4))))
        assertEquals("48 s", duration(48.0))
        assertEquals("12 min", duration(700.0))
        assertEquals("1 h 05", duration(3900.0))
        assertEquals("", duration(0.0))
        assertEquals("1/3", runsPassed(listOf(CheckRun(state = "passed"), CheckRun(state = "failed"), CheckRun(state = "failed"))))
    }

    @Test fun `une pull request - son titre, sa couleur, où en est sa fusion avec les mots du serveur`() {
        assertEquals("Exporter la liste des hôtes en CSV", pullTitle(ready))
        assertEquals("objectif 4", pullTitle(ready.copy(objective = null)))
        assertEquals(StateTone.YOU, pullColor(ready))
        assertEquals(StateTone.FAIL, pullColor(ready.copy(state = "open", checks = Checks(state = "failed"))))
        assertEquals(StateTone.WAIT, reviewTone(CodeReview()))
        assertEquals(StateTone.FAIL, reviewTone(CodeReview(ok = false)))
        assertEquals(MergeStage.READY, mergeStage(ready))
        assertEquals(MergeStage.MERGED, mergeStage(ready.copy(state = "merged")))
        val asked = ready.copy(merge = MergeState(asked = true, askedBy = "Adrien", why = "Une fusion est déjà demandée."))
        assertEquals(MergeStage.ASKED, mergeStage(asked))
        assertEquals("Une fusion est déjà demandée. Demandée par Adrien.", askedWords(asked, now, zone))
        val refused = ready.copy(merge = MergeState(can = false, why = "La CI tourne encore sur le dernier commit.", refused = "L'hôte a refusé : la branche est protégée."))
        assertEquals(MergeStage.REFUSED, mergeStage(refused))
        assertEquals("L'hôte a refusé : la branche est protégée.", refusedWords(refused, now, zone))
        assertEquals(MergeStage.HELD, mergeStage(refused.copy(merge = MergeState(why = "La CI tourne encore sur le dernier commit."))))
        assertEquals("", refusedWords(ready, now, zone))
        assertEquals("Fusionnée dans main par Adrien.", mergedWords(ready.copy(merge = MergeState(askedBy = "Adrien")), now, zone))
        assertEquals("avec main · des changements sont demandés · un commit n'est pas encore envoyé", conflictsWords(ready.copy(changesAsked = true, unsent = true)))
    }

    @Test fun `une issue qui ne se lit pas ne dit que pourquoi, un texte de l'hôte reste un texte`() {
        val veiled = MikaJson.decodeFromString(Issue.serializer(), """{"number":9,"title":null,"veiled":"proposed","veiled_label":"Une issue d'un inconnu, pas encore acceptée.","state":"open"}""")
        assertEquals("Une issue d'un inconnu, pas encore acceptée.", issueTitle(veiled))
        val read = MikaJson.decodeFromString(
            Issue.serializer(),
            """{"number":9,"title":{"text":"<b>Le scan plante</b> [ici](https://exemple.invalid)","outside":true},"account":{"text":"netfan42","outside":true},"from_here":false}""",
        )
        // le titre est celui de l'hôte, tel quel : rien n'y est interprété
        assertEquals("<b>Le scan plante</b> [ici](https://exemple.invalid)", issueTitle(read))
        assertEquals("netfan42, chez l'hôte", issueSource(read))
        assertEquals("publiée d'ici, sous le compte mika-bot", issueSource(read.copy(fromHere = true, account = OutsideText("mika-bot"))))
        assertEquals("Issue n° 9", issueTitle(Issue(number = 9)))
        assertEquals("quelqu'un, chez l'hôte", remarkSource(Remark(), now, zone))
        assertEquals("publié d'ici, sous le compte mika-bot", remarkSource(Remark(fromHere = true, account = OutsideText("mika-bot")), now, zone))
    }

    @Test fun `les vérifications d'un commit - ce que l'hôte dit maintenant, sinon ce que le moteur suit`() {
        val tracked = TrackedChecks(state = "failed", stateLabel = "en échec", sha = "abc1234", at = 5, said = OutsideText("FAILED tests/test_scan.py"))
        val live = HostChecks(sha = "abc1234", state = "passed", stateLabel = "passée", at = 9)
        assertEquals(ChecksShown("passed", "passée", 9), checksShown(tracked, live))
        // l'hôte muet : ce que le moteur suit reste montré
        assertEquals(ChecksShown("failed", "en échec", 5), checksShown(tracked, live.copy(error = "L'hôte ne répond pas.")))
        assertEquals(ChecksShown("none", "", 0), checksShown(null, null))
        assertEquals("FAILED tests/test_scan.py", checksTail(tracked, live))
        assertEquals("E assert 2.0 == 0.5", checksTail(tracked, live.copy(log = CheckLog(OutsideText("pytest"), OutsideText("E assert 2.0 == 0.5")))))
        assertEquals(tracked, bySha(listOf(tracked), "abc12") { it.sha })
        assertNull(bySha(listOf(tracked), "zzz") { it.sha })
    }

    // ── La fusion, modifier, répondre ──

    @Test fun `l'ordre de fusion ne naît que d'une pull request relue que le serveur ouvre, et nomme son commit de tête`() {
        val order = MergeOrder.of(detail(ready))
        assertNotNull(order)
        assertEquals(11, order!!.number)
        assertEquals(head, order.head)
        assertEquals(JsonPrimitive(11), order.body["number"])
        assertEquals(JsonPrimitive(head), order.body["head"])
        assertEquals(setOf("number", "head"), order.body.keys)
        // le serveur ne l'ouvre pas : pas d'ordre, quoi que l'écran pense
        assertNull(MergeOrder.of(detail(ready.copy(merge = MergeState(can = false, why = "La CI tourne encore.")))))
        // pas de commit de tête lu, une empreinte courte, pas de numéro : rien à nommer
        assertNull(MergeOrder.of(detail(ready.copy(head = ""))))
        assertNull(MergeOrder.of(detail(ready.copy(head = "8f41c2e"))))
        assertNull(MergeOrder.of(detail(ready.copy(number = 0))))
    }

    @Test fun `la confirmation dit ce qui va être fusionné, lu sur la pull request relue`() {
        val diff = Diff(files = List(3) { DiffFile(path = "f$it") }, insertions = 38, deletions = 1)
        val f = mergeFacts(detail(ready, commits = 2, diff = diff))
        assertEquals(11, f.number)
        assertEquals("Exporter la liste des hôtes en CSV", f.title)
        assertEquals("ticket-2-export-csv" to "main", f.branch to f.base)
        assertEquals(head, f.head)
        assertEquals(listOf(2, 3, 38, 1), listOf(f.commits, f.files, f.insertions, f.deletions))
        assertTrue(f.counted)
        assertEquals("relecture : rien à redire · vérifications : passée · aucun conflit", mergeStateWords(f))
        // sans le droit sur ses fichiers, ses comptes ne se disent pas
        assertFalse(mergeFacts(detail(ready, diff = Diff(filesReadable = false, filesWhy = "Ce projet ne t'ouvre pas ses fichiers."))).counted)
        assertEquals("des conflits", mergeStateWords(f.copy(review = "", checks = "", conflicts = true)))
    }

    @Test fun `un geste générique ne porte jamais la route de la fusion - un verdict tranche le ticket, le reste ne part pas`() {
        val w = MikaJson.decodeFromString(
            Waiting.serializer(),
            """{"project":3,"kind":"ticket","what":"merge","number":2,"mine":true,"can":true,
                "gesture":{"route":"code/pull/fusionner","args":{"number":11},"label":"Fusionner","where":"ici"}}""",
        )
        assertTrue(isMerge(w))
        assertEquals(11, mergeNumber(w))
        assertEquals(0, mergeNumber(w.copy(gesture = Gesture(route = "ticket/trancher"))))
        for (action in listOf("", "go", "answer", "merge", "accept", "dismiss", "validate", "refuse", "done", "reopen", "fusionner")) {
            val direct = gestureRequest(w, action, "pourquoi")
            assertFalse("$action → ${direct.route}", direct.route == MERGE_ROUTE)
            val viaTodo = todoRequest(w, action, "pourquoi", null, null)
            assertFalse("$action → ${viaTodo.route}", viaTodo.route == MERGE_ROUTE)
        }
        assertEquals("ticket/trancher", gestureRequest(w, "dismiss", "hors sujet").route)
        assertEquals(JsonPrimitive("#2"), gestureRequest(w, "dismiss", "hors sujet").body["item"])
        // ce qui n'est pas un verdict n'a pas de route : rien ne part
        assertEquals("", gestureRequest(w, "go").route)
        assertTrue(gestureRequest(w, "go").body.isEmpty())
    }

    @Test fun `modifier une pull request n'envoie que ce qui change de ce qu'on a relu, répondre envoie son texte`() {
        val both = pullEditRequest(11, "  Exporter en CSV  ", "Nouveau texte", "Exporter la liste", "Ancien texte")
        assertEquals("code/pull/modifier", both.route)
        assertEquals(JsonPrimitive(11), both.body["number"])
        assertEquals(JsonPrimitive("Exporter en CSV"), both.body["title"])
        assertEquals(JsonPrimitive("Nouveau texte"), both.body["body"])
        // le titre inchangé ne part pas ; un champ vidé ne change rien (le serveur : « un champ vide ne change pas »)
        val one = pullEditRequest(11, "Exporter la liste", "Nouveau texte", "Exporter la liste", "Ancien texte")
        assertEquals(setOf("number", "body"), one.body.keys)
        assertEquals(setOf("number"), pullEditRequest(11, "Exporter la liste", "", "Exporter la liste", "Ancien texte").body.keys)
        val reply = pullCommentRequest(11, "  Oui, j'ajoute le test.  ")
        assertEquals("code/pull/commenter", reply.route)
        assertEquals(JsonPrimitive("Oui, j'ajoute le test."), reply.body["text"])
    }
}
