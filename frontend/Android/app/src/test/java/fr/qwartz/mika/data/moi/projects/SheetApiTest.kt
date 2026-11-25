package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.data.auth.Credentials
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.net.ServerBase
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

/**
 * La documentation, l'activité et la gestion d'un projet sur l'API par personne (`protocole-moi.md` § 11) : leurs
 * réponses lues telles que le serveur les écrit (`backendv2/src/mika/app/domains/projects/api/docs.py`, `activity.py`,
 * `manage.py`), ce que chaque lecture demande, et **l'enregistrement d'une page** — en `multipart/form-data`,
 * sous le jeton, sans jeton CSRF, avec sa clé d'envoi, **en nommant la version lue** (`base` ; `0` pour une page
 * nouvelle) ; son conflit garde les mots du serveur.
 */
class SheetApiTest {
    private val server = MockWebServer()
    private val client = OkHttpClient.Builder().connectTimeout(2, TimeUnit.SECONDS).readTimeout(2, TimeUnit.SECONDS).build()
    private lateinit var api: ProjectsApi

    @Before fun start() {
        server.start()
        val base = (ServerBase.parse(server.url("/").toString()) as ServerBase.Parsed.Ok).base
        api = ProjectsApi(MoiApi(client, { Credentials(base, "mw_secret") }, {}, Dispatchers.IO))
    }

    @After fun stop() = server.close()

    private fun ok(body: String) = server.enqueue(MockResponse.Builder().body(body).build())

    private fun refused(code: Int, body: String) = server.enqueue(MockResponse.Builder().code(code).body(body).build())

    /** Les champs d'un corps `multipart/form-data`, par leur nom (un fichier : son contenu), et les noms de fichier. */
    private class Form(val fields: Map<String, String>, val files: Map<String, String>)

    private fun form(contentType: String, body: String): Form {
        val boundary = contentType.substringAfter("boundary=").trim('"')
        val fields = LinkedHashMap<String, String>()
        val files = LinkedHashMap<String, String>()
        for (part in body.split("--$boundary").drop(1)) {
            if (part.startsWith("--")) break
            val head = part.substringBefore("\r\n\r\n")
            val value = part.substringAfter("\r\n\r\n").removeSuffix("\r\n")
            val name = Regex("name=\"([^\"]*)\"").find(head)?.groupValues?.get(1) ?: continue
            fields[name] = value
            Regex("filename=\"([^\"]*)\"").find(head)?.let { files[name] = it.groupValues[1] }
        }
        return Form(fields, files)
    }

    private val who = """"author_kind":"self","author":"Mika","via":"run","via_label":"pendant une exécution","tool":"""""
    private val pageLine = """"path":"guide/installation.md","name":"installation.md","folder":"guide","title":"Installation","version":4,
        "at":1790790000000,"created_at":1790000000000,"chars":812,"images":["schema-reseau.png"],$who"""

    // ── La documentation ──

    @Test fun `l'espace - ses droits, ses bornes, ses pages, ses dossiers, ses images`() = runBlocking {
        ok(
            """{"project":3,"rights":{"read":true,"write":true},
                "limits":{"page_chars":100000,"pages":200,"versions":50,"path_chars":160,"depth":6,"word_chars":200,"image_bytes":5242880,"images":200,
                          "space_bytes":104857600,"image_kinds":["image/gif","image/jpeg","image/png","image/webp"]},
                "pages":[{$pageLine}],"folders":["guide"],
                "images":[{"name":"schema-reseau.png","path":"images/schema-reseau.png","size":18432,"mime":"image/png","at":1790790000000,
                           "used_by":["guide/installation.md"],"author_kind":"you","author":"toi","via":"web","via_label":"dans le navigateur","tool":""}],
                "space_used":18432,"futur":true}""",
        )
        val s = (api.docs(3) as MoiApi.Result.Ok).value
        val req = server.takeRequest()
        assertEquals("/api/moi/projets/3/documentation", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertNull(req.headers["Origin"])
        assertTrue(s.rights.read && s.rights.write)
        assertEquals(listOf(5_242_880L, 104_857_600L), listOf(s.limits.imageBytes, s.limits.spaceBytes))
        assertEquals(200, s.limits.wordChars)
        // les sortes d'image que l'espace garde : une photo d'une autre sorte est réencodée avant de partir
        assertEquals(listOf("image/gif", "image/jpeg", "image/png", "image/webp"), s.limits.imageKinds)
        val p = s.pages.single()
        assertEquals(listOf("guide/installation.md", "Installation", "pendant une exécution", "Mika"), listOf(p.path, p.title, p.viaLabel, p.author))
        assertEquals(4, p.version)
        assertEquals(listOf("guide/installation.md"), s.images.single().usedBy)
        assertEquals("images/schema-reseau.png", s.images.single().path)
        // qui lit sans pouvoir écrire, ou une réponse qui dit peu : aucun droit n'est supposé
        ok("""{"project":3,"rights":{"read":true,"write":false},"pages":[],"images":[]}""")
        val read = (api.docs(3) as MoiApi.Result.Ok).value
        assertFalse(read.rights.write)
        assertEquals(0L, read.limits.imageBytes)
        // la documentation ne lui est pas ouverte : les mots du serveur
        refused(403, """{"error":"Ce projet ne t'ouvre pas sa documentation."}""")
        assertEquals("Ce projet ne t'ouvre pas sa documentation.", (api.docs(3) as MoiApi.Result.Failed).error.message)
    }

    @Test fun `une page, ses versions, une version, la recherche - ce que chaque lecture demande`() = runBlocking {
        ok("""{$pageLine,"text":"# Installation\n\n![Le schéma](images/schema-reseau.png)","forgotten":false,"can":{"write":true}}""")
        val page = (api.docPage(3, "guide/installation.md") as MoiApi.Result.Ok).value
        val asked = server.takeRequest().url
        assertEquals("/api/moi/projets/3/documentation/page", asked.encodedPath)
        assertEquals("guide/installation.md", asked.queryParameter("path"))
        assertTrue(page.can.write && !page.forgotten)
        assertEquals(4, page.version)
        assertTrue(page.text.startsWith("# Installation"))

        ok(
            """{"path":"guide/installation.md","version":4,"kept":50,"versions":[
                {"n":4,"at":1790790000000,"word":"Note pour Windows","restored":0,"chars":812,"current":true,"author_kind":"person","author":"une autre personne","via":"mcp","via_label":"un outil, par MCP","tool":""},
                {"n":3,"at":1790700000000,"word":"Retour à la version 1","restored":1,"chars":700,"current":false,$who}]}""",
        )
        val history = (api.docHistory(3, "guide/installation.md") as MoiApi.Result.Ok).value
        assertEquals("/api/moi/projets/3/documentation/historique", server.takeRequest().url.encodedPath)
        assertEquals(listOf(4, 3), history.versions.map { it.n })
        assertTrue(history.versions[0].current)
        assertEquals(1, history.versions[1].restored)
        assertEquals("une autre personne", history.versions[0].author)

        ok("""{"path":"guide/installation.md","n":3,"at":1790700000000,"word":"","restored":0,"chars":700,"current":false,$who,"text":"# Avant","forgotten":false}""")
        val version = (api.docVersion(3, "guide/installation.md", 3) as MoiApi.Result.Ok).value
        val v = server.takeRequest().url
        assertEquals("/api/moi/projets/3/documentation/version", v.encodedPath)
        assertEquals("3", v.queryParameter("n"))
        assertEquals("# Avant", version.text)

        ok("""{"q":"pare-feu","items":[{$pageLine,"excerpt":"… si le pare-feu Windows est en profil public …"}]}""")
        val found = (api.docSearch(3, "  pare-feu ") as MoiApi.Result.Ok).value
        val q = server.takeRequest().url
        assertEquals("/api/moi/projets/3/documentation/chercher", q.encodedPath)
        assertEquals("pare-feu", q.queryParameter("q"))
        assertTrue(found.items.single().excerpt.contains("pare-feu"))
    }

    @Test fun `l'adresse d'une image est celle de l'API, sur le serveur de la session, et nulle part ailleurs`() {
        val url = api.docImageUrl(3, "schema reseau.png")!!.toHttpUrl()
        assertEquals(server.url("/").host, url.host)
        assertEquals(server.url("/").port, url.port)
        assertEquals("/api/moi/projets/3/documentation/image", url.encodedPath)
        assertEquals("schema reseau.png", url.queryParameter("name"))
        // hors session : aucune adresse
        assertNull(ProjectsApi(MoiApi(client, { null }, {})).docImageUrl(3, "a.png"))
    }

    @Test fun `enregistrer une page - en multipart, sous le jeton, sans CSRF, avec sa clé d'envoi, en nommant la version lue`() = runBlocking {
        ok("""{"ok":true,"message":"Page enregistrée : version 5.","deduped":false,"path":"guide/installation.md","version":5}""")
        val text = "# Installation\n\nUne ligne « accentuée ».\n"
        val saved = (api.saveDoc(3, DocSave("guide/installation.md", text, "Note pour Windows", 4), "cle-1") as MoiApi.Result.Ok).value
        val req = server.takeRequest()
        assertEquals("POST", req.method)
        assertEquals("/api/moi/projets/3/documentation/page/enregistrer", req.url.encodedPath)
        assertEquals("Bearer mw_secret", req.headers["Authorization"])
        assertEquals("cle-1", req.headers["Idempotency-Key"])
        assertNull(req.headers["Origin"])
        assertNull(req.headers["X-CSRFToken"])
        val type = req.headers["Content-Type"].orEmpty()
        assertTrue(type.startsWith("multipart/form-data"))
        val sent = form(type, req.body!!.utf8())
        assertEquals(setOf("path", "text", "base", "word"), sent.fields.keys)
        assertEquals("4", sent.fields["base"])
        assertEquals(text, sent.fields["text"])
        assertEquals("guide/installation.md", sent.fields["path"])
        assertEquals("Note pour Windows", sent.fields["word"])
        assertEquals(5, saved.version)
        assertEquals("Page enregistrée : version 5.", saved.message)

        // une page nouvelle : `base` vaut 0, et part quand même ; sans mot, pas de champ `word`
        ok("""{"ok":true,"message":"Page créée.","path":"guide/depannage.md","version":1}""")
        api.saveDoc(3, DocSave("guide/depannage.md", "# Dépannage\n", "", 0), "cle-2")
        val fresh = server.takeRequest()
        val born = form(fresh.headers["Content-Type"].orEmpty(), fresh.body!!.utf8())
        assertEquals(setOf("path", "text", "base"), born.fields.keys)
        assertEquals("0", born.fields["base"])
    }

    @Test fun `un enregistrement refusé garde les mots du serveur - la page a changé, elle ne peut pas l'écrire, un chemin refusé`() = runBlocking {
        val words = "Cette page a changé depuis ta lecture : elle en est à la version 6, écrite par une autre personne."
        refused(409, """{"error":"$words"}""")
        val moved = (api.saveDoc(3, DocSave("a.md", "x", "", 4)) as MoiApi.Result.Failed).error
        assertTrue(moved.conflict)
        assertEquals(words, moved.message)
        refused(403, """{"error":"Tu lis la documentation de ce projet sans pouvoir l'écrire."}""")
        assertEquals(403, (api.saveDoc(3, DocSave("a.md", "x", "", 4)) as MoiApi.Result.Failed).error.code)
        refused(400, """{"error":"Ce chemin ne convient pas.","fields":{"path":"des minuscules, des chiffres, des tirets"}}""")
        assertEquals("des minuscules, des chiffres, des tirets", (api.saveDoc(3, DocSave("A.md", "x", "", 0)) as MoiApi.Result.Failed).error.fields["path"])
        assertEquals(3, server.requestCount)
    }

    @Test fun `téléverser une image - un fichier en multipart, le nom que le serveur lui donne - les gestes d'une page partent en JSON`() = runBlocking {
        ok("""{"ok":true,"message":"Image ajoutée.","name":"schema-2.png","path":"images/schema-2.png"}""")
        val image = (api.uploadDocImage(3, DocUpload("schema.png", 4) { "PNG!".toRequestBody() }, "cle-3") as MoiApi.Result.Ok).value
        val req = server.takeRequest()
        assertEquals("/api/moi/projets/3/documentation/image/televerser", req.url.encodedPath)
        assertEquals("cle-3", req.headers["Idempotency-Key"])
        val sent = form(req.headers["Content-Type"].orEmpty(), req.body!!.utf8())
        assertEquals(mapOf("files" to "schema.png"), sent.files)
        assertEquals("PNG!", sent.fields["files"])
        assertEquals("schema-2.png", image.name)
        assertEquals("images/schema-2.png", image.path)
        refused(409, """{"error":"Cette image dépasse 5 Mio."}""")
        assertEquals("Cette image dépasse 5 Mio.", (api.uploadDocImage(3, DocUpload("gros.png", 9) { "x".toRequestBody() }) as MoiApi.Result.Failed).error.message)
        server.takeRequest()

        // revenir à une version : un geste comme les autres, qui nomme la version lue
        ok("""{"ok":true,"message":"Retour à la version 2.","path":"a.md","version":6}""")
        api.gesture(3, docRestoreRequest("a.md", 2, 5), "cle-4")
        val restore = server.takeRequest()
        assertEquals("/api/moi/projets/3/documentation/page/revenir", restore.url.encodedPath)
        assertEquals("""{"path":"a.md","version":2,"base":5}""", restore.body!!.utf8())
    }

    @Test fun `ses décisions - toutes, puis l'une en entier`() = runBlocking {
        val line = """"number":3,"title":"Le journal des refus est un fichier JSON Lines","choice":"Une ligne par refus.","status":"active","status_label":"en vigueur",
            "author_kind":"self","author":"Mika","at":1790790000000,"replaces":1,"replaced_by":0,"objective":2,
            "can":{"modify":true,"replace":true,"withdraw":true,"restore":false,"why":""}"""
        ok("""{"total":1,"in_force":1,"can":true,"why":"","items":[{$line}]}""")
        val list = (api.decisions(3) as MoiApi.Result.Ok).value
        val asked = server.takeRequest().url
        assertEquals("/api/moi/projets/3/decisions", asked.encodedPath)
        assertEquals("all", asked.queryParameter("status"))
        assertEquals(1, list.inForce)
        assertEquals("en vigueur", list.items.single().statusLabel)
        ok("""{$line,"context":"Le collecteur lit ligne à ligne.","options":"Un fichier texte libre : illisible\nUne base SQLite","reason":"Se lit sans outil."}""")
        val d = (api.decision(3, 3) as MoiApi.Result.Ok).value
        assertEquals("3", server.takeRequest().url.queryParameter("number"))
        assertEquals(listOf(1, 0, 2), listOf(d.replaces, d.replacedBy, d.objective))
        assertEquals(2, optionLines(d.options).size)
        assertTrue(d.can.modify && !d.can.restore)
    }

    // ── L'activité ──

    @Test fun `ses trente jours, ses totaux, ses exécutions, l'une pas à pas, son carnet`() = runBlocking {
        ok(
            """{"days":[{"day":"2026-11-20","run":2,"commit":1,"pull":0,"ticket":0,"gesture":1,"total":4},{"day":"2026-11-21","run":0,"commit":0,"pull":0,"ticket":0,"gesture":0,"total":0}],
                "totals":{"run":2,"commit":1,"pull":0,"ticket":0,"gesture":1},"total":4,"cut":false,
                "kinds":[{"code":"run","label":"exécutions"},{"code":"commit","label":"commits"}],
                "by":[{"who":"self","label":"Mika","count":3},{"who":"you","label":"toi","count":1},{"who":"others","label":"d'autres","count":0}]}""",
        )
        val days = (api.activityDays(3) as MoiApi.Result.Ok).value
        assertEquals("/api/moi/projets/3/activite/jours", server.takeRequest().url.encodedPath)
        assertEquals(listOf(4, 0), days.days.map { dayCount(it) })
        assertEquals(2, dayCount(days.days[0], "run"))
        assertEquals(listOf("self", "you", "others"), days.by.map { it.who })

        ok("""{"kinds":[{"code":"run","label":"exécutions","count":10}],"totals":{"run":10,"commit":12},"total":39,"cut":true,"notes":6,"notes_cut":false,"runs":10}""")
        val totals = (api.activityTotals(3, objective = 2) as MoiApi.Result.Ok).value
        val t = server.takeRequest().url
        assertEquals("/api/moi/projets/3/activite/totaux", t.encodedPath)
        assertEquals("2", t.queryParameter("objective"))
        assertEquals(listOf(39, 6, 10), listOf(totals.total, totals.notes, totals.runs))
        assertTrue(totals.cut)

        val runLine = """"id":"ep-59","at":1790790000000,"sort":"run","sort_label":"travail",
            "objective":{"id":2,"text":"Créer un module RDP","kind":"once","ticket":6,"status":"open","status_label":"en cours"},
            "running":false,"outcome":"ok","outcome_label":"aboutie","seconds":240,"verdict":"wait","verdict_label":"te demande","proven":false,
            "summary":"Issue n° 9 lue.","commit":"cdd07ae46e31","branch":"objectif-2-module-rdp","asked":true"""
        ok("""{"total":10,"size":25,"next":4100,"sorts":[{"code":"run","label":"travail"}],"items":[{$runLine},{"id":"ep-1","sort":"frame","sort_label":"cadrage","objective":null}]}""")
        val runs = (api.runs(3, before = 4200) as MoiApi.Result.Ok).value
        assertEquals("4200", server.takeRequest().url.queryParameter("before"))
        assertEquals(4100L, runs.next)
        assertNull(runs.items[1].objective)
        assertEquals(240L, runs.items[0].seconds)

        ok(
            """{$runLine,"report":"Issue n° 9 lue et reproduite.","need":"Je voudrais répondre à son auteur.",
                "steps":[{"tool":"host_issue","label":"L'issue n° 9 chez l'hôte","aim":"","ok":true,"ran":true,"ms":60000,"acts":false,"outside":true},
                         {"tool":"sandbox_run","label":"Lancer une commande","aim":"pytest tests/test_rdp.py","ok":false,"ran":true,"ms":120000,"acts":true,"outside":false}],
                "steps_cut":false,"steps_kept":true,"steps_aims":false,"steps_aims_why":"Ce que chaque pas visait ne se dit qu'avec le droit sur ses fichiers."}""",
        )
        val run = (api.run(3, "ep-59") as MoiApi.Result.Ok).value
        val r = server.takeRequest().url
        assertEquals("/api/moi/projets/3/execution", r.encodedPath)
        assertEquals("ep-59", r.queryParameter("id"))
        assertEquals(2, run.steps.size)
        // ce que rend le premier outil vient d'ailleurs : c'est marqué, pas deviné
        assertTrue(run.steps[0].outside && !run.steps[1].outside)
        assertFalse(run.steps[1].ok)
        assertFalse(run.stepsAims)
        assertTrue(run.stepsAimsWhy.isNotBlank())
        assertEquals("Je voudrais répondre à son auteur.", run.need)

        ok("""{"size":50,"next":0,"total":6,"total_cut":false,"items":[{"seq":88,"at":1790790000000,"text":"Ne jamais écrire le mot de passe.","objective":null,"run":"ep-59"}]}""")
        val notes = (api.notebook(3, objective = 2) as MoiApi.Result.Ok).value
        val n = server.takeRequest().url
        assertEquals("/api/moi/projets/3/carnet", n.encodedPath)
        assertEquals("2", n.queryParameter("objective"))
        assertNull(n.queryParameter("before"))
        assertEquals(6, notes.total)
        assertNull(notes.items.single().objective)
    }

    // ── Gérer ──

    @Test fun `ses réglages - chaque champ dans sa sorte, avec ce qu'elle peut en changer - et les projets archivés`() = runBlocking {
        ok(
            """{"project":3,"can":true,"why":"","renamable":false,"archive":{"can":true,"why":""},"sections":[
                {"name":"rythme","title":"Rythme","summary":"Une fois par jour · de 08:00 à 20:00","can":true,"why":"","fields":[
                  {"name":"days","label":"Les jours","help":"","kind":"select","required":false,"choices":[{"code":"mon","label":"Lun"}],"value":["mon"],"min":null,"max":null,"only":[],"can":true,"why":""},
                  {"name":"runs_per_day","label":"Passages par jour","help":"","kind":"int","required":false,"choices":[],"value":2,"min":1,"max":24,"only":[],"can":true,"why":""}]},
                {"name":"accords","title":"Accords et relecture","summary":"ce qui sort attend ton accord","can":false,"why":"Ce réglage ouvre autre chose que ce projet.","fields":[
                  {"name":"approval","label":"Ce qui sort attend ton accord","help":"","kind":"bool","required":false,"choices":[],"value":true,"min":null,"max":null,"only":[],"can":false,
                   "why":"Ce réglage ouvre autre chose que ce projet."}]}]}""",
        )
        val s = (api.settings(3) as MoiApi.Result.Ok).value
        assertEquals("/api/moi/projets/3/reglages", server.takeRequest().url.encodedPath)
        assertTrue(s.can && s.archive.can && !s.renamable)
        val days = s.sections[0].fields[0]
        assertEquals(JsonArray(listOf(JsonPrimitive("mon"))), days.value)
        assertEquals(24.0, s.sections[0].fields[1].max)
        val reserved = s.sections[1].fields.single()
        assertFalse(reserved.can)
        assertEquals("Ce réglage ouvre autre chose que ce projet.", reserved.why)
        assertFalse(s.sections[1].can)
        // qui ne change pas son cadre : tout se lit, rien ne s'offre
        ok("""{"project":3,"can":false,"why":"Seul le propriétaire du projet change son cadre.","archive":{"can":false,"why":"Seul le propriétaire du projet change son cadre."},"sections":[]}""")
        val locked = (api.settings(3) as MoiApi.Result.Ok).value
        assertFalse(locked.can || locked.archive.can)
        server.takeRequest()

        ok("""{"items":[{"id":9,"title":"Site de l'association","archived_at":1790000000000,"owner_name":""}]}""")
        val archived = (api.archives() as MoiApi.Result.Ok).value
        assertEquals("/api/moi/projets/archives", server.takeRequest().url.encodedPath)
        assertEquals(9, archived.items.single().id)

        // enregistrer une section, archiver, désarchiver : des gestes comme les autres
        ok("""{"ok":true,"message":"Réglages enregistrés."}""")
        api.gesture(3, settingsRequest("rythme", s.sections[0].fields, mapOf("runs_per_day" to JsonPrimitive("3"))), "cle")
        val save = server.takeRequest()
        assertEquals("/api/moi/projets/3/reglages/enregistrer", save.url.encodedPath)
        assertEquals("""{"section":"rythme","values":{"runs_per_day":3}}""", save.body!!.utf8())
        refused(403, """{"error":"Ce réglage ouvre autre chose que ce projet.","fields":{"approval":"réservé à qui s'occupe d'elle"}}""")
        val no = (api.gesture(3, GestureRequest("reglages/enregistrer", bodyOf("section" to "accords")), "cle") as MoiApi.Result.Failed).error
        assertEquals("réservé à qui s'occupe d'elle", no.fields["approval"])
        server.takeRequest()
        ok("""{"ok":true,"message":"Projet restauré."}""")
        api.gesture(9, restoreRequest(), "cle")
        assertEquals("/api/moi/projets/9/restaurer", server.takeRequest().url.encodedPath)
    }
}
