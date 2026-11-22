package fr.qwartz.mika.data.moi.projects

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.decode
import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerializationException
import kotlinx.serialization.descriptors.PrimitiveKind
import kotlinx.serialization.descriptors.PrimitiveSerialDescriptor
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import okhttp3.MultipartBody
import okhttp3.RequestBody

/**
 * Les projets par l'API par personne (`backendv2/docs/protocole-moi.md` § 11), sous le jeton du téléphone, qui écrit
 * sans jeton CSRF (ADR 0235) : ses projets et ce qui l'y attend, la fiche, le registre, le diagramme, et ses gestes.
 *
 * Un geste est `POST /api/moi/projets/<projet>/<route>` ([gesture]) : sa route et son corps viennent de
 * [ProjectsRules][gestureRequest] — ce module ne décide de rien. Chaque écriture porte sa clé d'envoi : le même geste
 * redit ne refait rien. Un refus garde les mots du serveur (`error`, `fields`).
 *
 * Ouverte, pour que les modèles d'écran se testent contre une fausse API. Son code se lit ici aussi (`…/code/…`, ses
 * formes dans `CodeModels.kt`) ; modifier une pull request et y répondre passent par [gesture], **la fusionner par
 * [merge] seulement**. Sa documentation (`…/documentation/…`, `DocsModels.kt`), son activité (`…/activite/…`,
 * `…/executions`, `…/carnet`) et ses réglages (`…/reglages`, `ActivityModels.kt`) s'y lisent de même ; leurs écritures
 * passent par [gesture], sauf les deux qui partent en `multipart/form-data` : enregistrer une page ([saveDoc], qui nomme
 * la version lue) et téléverser une image ([uploadDocImage], par [uploads] : le client sans délai global).
 */
open class ProjectsApi(private val api: MoiApi, private val uploads: MoiApi = api) {
    // ── Lire ──

    /** Ses projets, ceux où quelque chose l'attend d'abord, et la première page d'« À faire ». */
    open suspend fun overview(): MoiApi.Result<Overview> = api.get(ROOT, reader = Overview.serializer())

    /** « À faire » pour tous ses projets, page par page ([page] : 1 d'abord). */
    open suspend fun todo(page: Int): MoiApi.Result<TodoPage> =
        api.get("$ROOT/a-faire", linkedMapOf("page" to page.toString()), TodoPage.serializer())

    /** Ce qui attend **son** accord dans un projet : exactement ce qui partirait, et son condensé. */
    open suspend fun approvals(project: Int): MoiApi.Result<Approvals> =
        api.get("$ROOT/accords", linkedMapOf("project" to project.toString()), Approvals.serializer())

    open suspend fun sheet(id: Int): MoiApi.Result<Sheet> = api.get("$ROOT/$id", reader = Sheet.serializer())

    /** Une page d'une liste du registre, les derniers touchés d'abord ; [state] : `open`, `closed`, ou rien. */
    open suspend fun elements(id: Int, list: String = TICKETS, state: String = "", q: String = "", size: Int = PAGE): MoiApi.Result<EntryPage> =
        api.get(
            "$ROOT/$id/elements",
            linkedMapOf("list" to list, "state" to state, "q" to q.trim().take(QUERY_MAX), "size" to size.toString()),
            EntryPage.serializer(),
        )

    /** Un élément ([item] : `#n` pour un ticket, sa clé sinon) : sa ligne, son texte, son fil, son parcours, ses gestes. */
    open suspend fun element(id: Int, list: String, item: String): MoiApi.Result<EntryDetail> =
        api.read("$ROOT/$id/element", linkedMapOf("list" to list, "item" to item)) { readEntry(it) }

    /** L'histoire des étapes d'un ticket, de la plus ancienne à la plus récente. */
    open suspend fun history(id: Int, item: String): MoiApi.Result<EntryHistory> =
        api.get("$ROOT/$id/element/historique", linkedMapOf("item" to item), EntryHistory.serializer())

    /**
     * Son fil d'activité, du plus récent au plus ancien ; [kind] : `run`, `commit`, `pull`, `ticket`, `gesture` ;
     * [objective], [ticket] : ce qui les concerne (0 : tout). Demande `rights.work`.
     */
    open suspend fun activity(id: Int, kind: String = "", objective: Int = 0, ticket: Int = 0, before: Long = 0): MoiApi.Result<ActivityPage> =
        api.get(
            "$ROOT/$id/activite",
            linkedMapOf(
                "kind" to kind,
                "objective" to objective.takeIf { it > 0 }?.toString(),
                "ticket" to ticket.takeIf { it > 0 }?.toString(),
                "before" to before.takeIf { it > 0 }?.toString(),
            ),
            ActivityPage.serializer(),
        )

    /** De quoi dessiner ses objectifs et leurs jalons, dans l'ordre du plan. */
    open suspend fun diagram(id: Int): MoiApi.Result<Diagram> = api.get("$ROOT/$id/diagramme", reader = Diagram.serializer())

    /** De quoi remplir « Nouveau projet ». */
    open suspend fun newProject(): MoiApi.Result<NewProject> = api.get("$ROOT/nouveau", reader = NewProject.serializer())

    // ── Lire son code (§ 11, « Le code d'un projet ») ──

    /** Le dépôt en bref : sa base, son dépôt distant, ce qu'elle peut en faire (`rights`), ses comptes. */
    open suspend fun code(id: Int): MoiApi.Result<CodeSummary> = api.get("$ROOT/$id/code", reader = CodeSummary.serializer())

    /** Un dossier à une référence ([ref] vide : la base), un niveau à la fois. Demande le droit sur ses fichiers. */
    open suspend fun tree(id: Int, ref: String = "", path: String = ""): MoiApi.Result<Tree> =
        api.get("$ROOT/$id/code/fichiers", linkedMapOf("ref" to ref, "path" to path), Tree.serializer())

    /** Un fichier : son texte s'il se lit, son dernier commit, son historique. Demande le droit sur ses fichiers. */
    open suspend fun blob(id: Int, ref: String, path: String): MoiApi.Result<Blob> =
        api.get("$ROOT/$id/code/fichier", linkedMapOf("path" to path, "ref" to ref), Blob.serializer())

    /** L'histoire d'une branche, ou de toutes sans [ref], du plus récent. */
    open suspend fun commits(id: Int, ref: String = "", page: Int = 1, size: Int = COMMITS_PAGE): MoiApi.Result<CommitPage> =
        api.get(
            "$ROOT/$id/code/commits",
            linkedMapOf("ref" to ref, "page" to page.takeIf { it > 1 }?.toString(), "size" to size.toString()),
            CommitPage.serializer(),
        )

    /** Un commit et son diff ; [path] : un seul fichier, relu en entier (un fichier coupé). */
    open suspend fun commit(id: Int, sha: String, path: String = ""): MoiApi.Result<CommitDetail> =
        api.read("$ROOT/$id/code/commit", linkedMapOf("sha" to sha, "path" to path)) { json ->
            diffed(MoiApi.Result.Ok(json), CommitHead.serializer()) { h, d -> CommitDetail(h.commit, h.linked, d) }
        }

    open suspend fun branches(id: Int): MoiApi.Result<BranchList> = api.get("$ROOT/$id/code/branches", reader = BranchList.serializer())

    /** Une branche : ce qu'elle a d'avance sur la base, ses fichiers changés avec leurs comptes. */
    open suspend fun branch(id: Int, name: String): MoiApi.Result<BranchDetail> =
        api.read("$ROOT/$id/code/branche", linkedMapOf("name" to name)) { json ->
            diffed(MoiApi.Result.Ok(json), BranchHead.serializer()) { h, d -> BranchDetail(h.branch, h.commits, d) }
        }

    /** Ses pull requests, les prêtes d'abord. */
    open suspend fun pulls(id: Int): MoiApi.Result<PullPage> =
        api.get("$ROOT/$id/code/pulls", linkedMapOf("size" to PAGE.toString()), PullPage.serializer())

    /**
     * Une pull request : par son numéro, ou par son objectif tant qu'elle n'en a pas ([number] : 0). Sa réponse porte
     * `pull.head`, le commit à nommer pour la fusionner ([MergeOrder]). [path] : un seul fichier de son diff.
     */
    open suspend fun pull(id: Int, number: Int, objective: Int = 0, path: String = ""): MoiApi.Result<PullDetail> =
        api.read(
            "$ROOT/$id/code/pull",
            if (number > 0) linkedMapOf("number" to number.toString(), "path" to path) else linkedMapOf("objective" to objective.toString(), "path" to path),
        ) { json -> diffed(MoiApi.Result.Ok(json), PullHead.serializer()) { h, d -> PullDetail(h.pull, h.commits, d) } }

    /** Ce que l'hôte dit d'une pull request, maintenant : son titre, son texte, ses échanges, ses vérifications. */
    open suspend fun pullHost(id: Int, number: Int): MoiApi.Result<PullHost> =
        api.get("$ROOT/$id/code/pull/hote", linkedMapOf("number" to number.toString()), PullHost.serializer())

    /** Les issues du dépôt, relues chez l'hôte, et celles que ses tickets connaissent. */
    open suspend fun issues(id: Int): MoiApi.Result<IssuePage> =
        api.get("$ROOT/$id/code/issues", linkedMapOf("size" to PAGE.toString()), IssuePage.serializer())

    open suspend fun issue(id: Int, number: Int): MoiApi.Result<Issue> =
        api.get("$ROOT/$id/code/issue", linkedMapOf("number" to number.toString()), Issue.serializer())

    /** Les vérifications que le moteur suit, par commit, les plus récentes d'abord. */
    open suspend fun checks(id: Int): MoiApi.Result<ChecksList> = api.get("$ROOT/$id/code/ci", reader = ChecksList.serializer())

    /** Les vérifications d'un commit, relues chez l'hôte : une à une, et la fin du journal d'un échec. */
    open suspend fun commitChecks(id: Int, sha: String): MoiApi.Result<HostChecks> =
        api.get("$ROOT/$id/code/ci/commit", linkedMapOf("sha" to sha), HostChecks.serializer())

    // ── Lire sa documentation (§ 11, « La documentation d'un projet ») ──

    /** L'espace en entier : ses droits, ses bornes, ses pages à plat, ses dossiers, ses images. */
    open suspend fun docs(id: Int): MoiApi.Result<DocSpace> = api.get("$ROOT/$id/$DOCS", reader = DocSpace.serializer())

    /** Une page : sa ligne, son Markdown, et si elle peut l'écrire. Sa `version` est celle qu'un enregistrement nomme. */
    open suspend fun docPage(id: Int, path: String): MoiApi.Result<DocPage> =
        api.get("$ROOT/$id/$DOCS/page", linkedMapOf("path" to path), DocPage.serializer())

    /** Les versions gardées d'une page, de la plus récente à la plus ancienne. */
    open suspend fun docHistory(id: Int, path: String): MoiApi.Result<DocHistory> =
        api.get("$ROOT/$id/$DOCS/historique", linkedMapOf("path" to path), DocHistory.serializer())

    /** Une version gardée, avec son texte. */
    open suspend fun docVersion(id: Int, path: String, n: Int): MoiApi.Result<DocVersion> =
        api.get("$ROOT/$id/$DOCS/version", linkedMapOf("path" to path, "n" to n.toString()), DocVersion.serializer())

    /** Les pages dont le chemin ou le texte contient ces mots, chacune avec le passage. */
    open suspend fun docSearch(id: Int, q: String): MoiApi.Result<DocFound> =
        api.get("$ROOT/$id/$DOCS/chercher", linkedMapOf("q" to q.trim().take(QUERY_MAX)), DocFound.serializer())

    /**
     * L'adresse des octets d'une image de l'espace, servie par ce serveur à qui peut lire la documentation : **la seule
     * adresse d'image qu'une page fait charger**, sous la session de l'app ; `null` hors session.
     */
    open fun docImageUrl(id: Int, name: String): String? = api.url("$ROOT/$id/$DOCS/image", linkedMapOf("name" to name))?.toString()

    /** Ses décisions techniques, toutes (aussi celles qu'une autre remplace), les plus récentes d'abord. */
    open suspend fun decisions(id: Int): MoiApi.Result<DecisionList> =
        api.get("$ROOT/$id/decisions", linkedMapOf("status" to "all"), DecisionList.serializer())

    /** Une décision : le choix, le contexte, les options écartées, la raison. */
    open suspend fun decision(id: Int, number: Int): MoiApi.Result<Decision> =
        api.get("$ROOT/$id/decision", linkedMapOf("number" to number.toString()), Decision.serializer())

    // ── Lire son activité (§ 11, « L'activité d'un projet ») ──

    /** Les trente derniers jours : un compte par sorte et par jour, qui a fait quoi. */
    open suspend fun activityDays(id: Int): MoiApi.Result<ActivityDays> = api.get("$ROOT/$id/activite/jours", reader = ActivityDays.serializer())

    /** Ses totaux sur toute son histoire, pour ce filtre ; les notes de son carnet, ses exécutions. */
    open suspend fun activityTotals(id: Int, objective: Int = 0): MoiApi.Result<ActivityTotals> =
        api.get("$ROOT/$id/activite/totaux", linkedMapOf("objective" to objective.takeIf { it > 0 }?.toString()), ActivityTotals.serializer())

    /** Ses exécutions, de la plus récente ; [before] : le curseur de la page d'avant. */
    open suspend fun runs(id: Int, before: Long = 0): MoiApi.Result<RunPage> =
        api.get("$ROOT/$id/executions", linkedMapOf("before" to before.takeIf { it > 0 }?.toString()), RunPage.serializer())

    /** Une exécution : son compte rendu entier, ce qu'elle a demandé, ce qu'elle a fait pas à pas. */
    open suspend fun run(id: Int, run: String): MoiApi.Result<Run> = api.get("$ROOT/$id/execution", linkedMapOf("id" to run), Run.serializer())

    /** Les notes de son carnet, les plus récentes d'abord ; [objective] : celles qui le visaient. */
    open suspend fun notebook(id: Int, objective: Int = 0, before: Long = 0): MoiApi.Result<NotebookPage> =
        api.get(
            "$ROOT/$id/carnet",
            linkedMapOf("objective" to objective.takeIf { it > 0 }?.toString(), "before" to before.takeIf { it > 0 }?.toString()),
            NotebookPage.serializer(),
        )

    // ── Gérer (§ 11, « Gérer un projet ») ──

    /** Ses réglages en sections : chaque champ avec son libellé, sa valeur, et si elle peut le changer. */
    open suspend fun settings(id: Int): MoiApi.Result<ProjectSettings> = api.get("$ROOT/$id/reglages", reader = ProjectSettings.serializer())

    /** Les projets archivés qu'elle peut restaurer. */
    open suspend fun archives(): MoiApi.Result<Archives> = api.get("$ROOT/archives", reader = Archives.serializer())

    // ── Écrire ──

    /**
     * Enregistrer une page : **une version de plus, partie de la version lue** ([DocSave.base] ; 0 : une page nouvelle).
     * Si quelqu'un l'a changée depuis, le serveur refuse (409, en mots) et rien n'est écrasé. En `multipart/form-data` :
     * un corps JSON est borné à 64 Kio, une page à 100 000 caractères.
     */
    open suspend fun saveDoc(id: Int, save: DocSave, key: String? = MoiApi.newKey()): MoiApi.Result<PageSaved> =
        api.postForm("$ROOT/$id/$DOCS/page/enregistrer", saveForm(save), key).decode(PageSaved.serializer())

    /** Téléverser une image : elle rejoint les images de l'espace, sous le nom que le serveur rend. */
    open suspend fun uploadDocImage(id: Int, image: DocUpload, key: String? = MoiApi.newKey()): MoiApi.Result<ImageSaved> =
        uploads.postForm("$ROOT/$id/$DOCS/image/televerser", imageForm(image), key).decode(ImageSaved.serializer())

    /** Lui confier un projet : il naît à cadrer → [GestureDone.project], à ouvrir. */
    open suspend fun create(body: JsonObject, key: String? = MoiApi.newKey()): MoiApi.Result<GestureDone> =
        api.post("$ROOT/nouveau/creer", body, key).decode(GestureDone.serializer())

    /**
     * Un geste dans un projet : `POST /api/moi/projets/<projet>/<route>`, avec sa clé d'envoi. **Jamais la fusion** : un
     * geste sans route, ou qui nomme celle de la fusion, ne part pas — elle n'a qu'un chemin, [merge].
     */
    open suspend fun gesture(project: Int, request: GestureRequest, key: String? = MoiApi.newKey()): MoiApi.Result<GestureDone> =
        if (request.route.isEmpty() || request.route == MERGE_ROUTE) {
            MoiApi.Result.Failed(MoiError(-1, NOT_A_GESTURE))
        } else {
            api.post("$ROOT/$project/${request.route}", request.body, key).decode(GestureDone.serializer())
        }

    /**
     * Fusionner une pull request : **le seul chemin de l'app vers `code/pull/fusionner`**. Il demande un [MergeOrder],
     * qui ne naît que d'une pull request qu'on vient de relire et que le serveur dit fusionnable : la demande nomme son
     * numéro et son commit de tête lu. Si la branche a bougé depuis, le serveur refuse (409) et rien ne part.
     */
    open suspend fun merge(project: Int, order: MergeOrder, key: String? = MoiApi.newKey()): MoiApi.Result<GestureDone> =
        api.post("$ROOT/$project/$MERGE_ROUTE", order.body, key).decode(GestureDone.serializer())

    companion object {
        const val ROOT = "/projets"
        /** La liste des tickets, dans le registre d'un projet. */
        const val TICKETS = "tickets"
        /** Les tickets lus d'un coup (le serveur en rend cent au plus). */
        const val PAGE = 100
        /** Ce qu'une recherche envoie au plus. */
        const val QUERY_MAX = 120
        /** Les commits lus d'un coup (le serveur en rend cent au plus). */
        const val COMMITS_PAGE = 50
        /** L'espace de documentation d'un projet, sous sa racine. */
        const val DOCS = "documentation"

        /** Le corps d'un enregistrement : `base` part toujours — un zéro (une page nouvelle) est une valeur, pas une absence. */
        internal fun saveForm(save: DocSave): MultipartBody {
            val b = MultipartBody.Builder().setType(MultipartBody.FORM)
                .addFormDataPart("path", save.path)
                .addFormDataPart("text", save.text)
                .addFormDataPart("base", save.base.toString())
            if (save.word.isNotEmpty()) b.addFormDataPart("word", save.word)
            return b.build()
        }

        /** Le corps d'un téléversement : un fichier, sous `files` (comme le formulaire du web). */
        internal fun imageForm(image: DocUpload): MultipartBody =
            MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("files", image.name, image.body()).build()

        /** Une réponse qui porte un diff à côté d'autre chose (`commit`, `branch`, `pull`) : lue deux fois — hors du fil principal (`MoiApi.read`). */
        internal fun <H, T> diffed(got: MoiApi.Result<JsonObject>, head: KSerializer<H>, make: (H, Diff) -> T): MoiApi.Result<T> = when (got) {
            is MoiApi.Result.Failed -> got
            is MoiApi.Result.Ok -> try {
                MoiApi.Result.Ok(make(MikaJson.decodeFromJsonElement(head, got.value), MikaJson.decodeFromJsonElement(Diff.serializer(), got.value)))
            } catch (_: SerializationException) {
                MoiApi.Result.Failed(MoiError(-1, UNREADABLE))
            } catch (_: IllegalArgumentException) {
                MoiApi.Result.Failed(MoiError(-1, UNREADABLE))
            }
        }

        /** Un élément lu deux fois dans la même réponse : sa ligne, puis ce qu'il dit de plus. */
        internal fun readEntry(json: JsonObject): MoiApi.Result<EntryDetail> = try {
            MoiApi.Result.Ok(
                EntryDetail(MikaJson.decodeFromJsonElement(Entry.serializer(), json), MikaJson.decodeFromJsonElement(EntryMore.serializer(), json)),
            )
        } catch (_: SerializationException) {
            MoiApi.Result.Failed(MoiError(-1, UNREADABLE))
        } catch (_: IllegalArgumentException) {
            MoiApi.Result.Failed(MoiError(-1, UNREADABLE))
        }

        private const val UNREADABLE = "La réponse du serveur ne se lit pas : mets l'application à jour."
        /** Ce qu'on dit d'un geste qui n'en est pas un : sans route, ou la fusion hors de sa confirmation. */
        const val NOT_A_GESTURE = "Ce geste ne part pas d'ici."
    }
}

/** Une image choisie dans le téléphone, prête à partir : son nom, son poids, et son contenu lu seulement au moment d'envoyer. */
class DocUpload(val name: String, val size: Long, val body: () -> RequestBody)

/** La valeur d'un champ servi, quelle que soit sa sorte JSON (un texte, un nombre, un booléen, rien) : son texte. */
internal object LooseText : KSerializer<String> {
    override val descriptor: SerialDescriptor = PrimitiveSerialDescriptor("LooseText", PrimitiveKind.STRING)

    override fun deserialize(decoder: Decoder): String {
        val element = (decoder as? JsonDecoder)?.decodeJsonElement() ?: return decoder.decodeString()
        return when (element) {
            is JsonNull -> ""
            is JsonPrimitive -> element.content
            else -> ""
        }
    }

    override fun serialize(encoder: Encoder, value: String) = encoder.encodeString(value)
}
