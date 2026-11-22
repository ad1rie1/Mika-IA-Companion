package fr.qwartz.mika.ui.projects

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.MoiApi
import fr.qwartz.mika.data.moi.MoiError
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.projects.ActivityDays
import fr.qwartz.mika.data.moi.projects.ActivityPage
import fr.qwartz.mika.data.moi.projects.ActivityTabs
import fr.qwartz.mika.data.moi.projects.ActivityTotals
import fr.qwartz.mika.data.moi.projects.DecisionList
import fr.qwartz.mika.data.moi.projects.DocFound
import fr.qwartz.mika.data.moi.projects.DocHistory
import fr.qwartz.mika.data.moi.projects.DocPage
import fr.qwartz.mika.data.moi.projects.DocSpace
import fr.qwartz.mika.data.moi.projects.DocTabs
import fr.qwartz.mika.data.moi.projects.DocUpload
import fr.qwartz.mika.data.moi.projects.DocVersion
import fr.qwartz.mika.data.moi.projects.Draft
import fr.qwartz.mika.data.moi.projects.Edit
import fr.qwartz.mika.data.moi.projects.Entry
import fr.qwartz.mika.data.moi.projects.EntryDetail
import fr.qwartz.mika.data.moi.projects.EntryPage
import fr.qwartz.mika.data.moi.projects.GestureDone
import fr.qwartz.mika.data.moi.projects.Happening
import fr.qwartz.mika.data.moi.projects.MdEdit
import fr.qwartz.mika.data.moi.projects.NotebookNote
import fr.qwartz.mika.data.moi.projects.NotebookPage
import fr.qwartz.mika.data.moi.projects.PageSaved
import fr.qwartz.mika.data.moi.projects.ProjectSettings
import fr.qwartz.mika.data.moi.projects.Run
import fr.qwartz.mika.data.moi.projects.RunPage
import fr.qwartz.mika.data.moi.projects.SettingsSection
import fr.qwartz.mika.data.moi.projects.archiveRequest
import fr.qwartz.mika.data.moi.projects.docImageRemoveRequest
import fr.qwartz.mika.data.moi.projects.docMoveRequest
import fr.qwartz.mika.data.moi.projects.docRemoveRequest
import fr.qwartz.mika.data.moi.projects.docRestoreRequest
import fr.qwartz.mika.data.moi.projects.itemAddRequest
import fr.qwartz.mika.data.moi.projects.itemAssignRequest
import fr.qwartz.mika.data.moi.projects.itemStatusRequest
import fr.qwartz.mika.data.moi.projects.newPageSave
import fr.qwartz.mika.data.moi.projects.noteRequest
import fr.qwartz.mika.data.moi.projects.olderKept
import fr.qwartz.mika.data.moi.projects.refusalWords
import fr.qwartz.mika.data.moi.projects.sameHappening
import fr.qwartz.mika.data.moi.projects.saveOf
import fr.qwartz.mika.data.moi.projects.settingsChanged
import fr.qwartz.mika.data.moi.projects.settingsRequest
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement
import fr.qwartz.mika.data.moi.projects.headingsOf

/*
 * Les modèles des onglets Documentation, Activité et Listes, et de « Modifier le projet » (ADR 0296) : ce que chaque vue
 * a lu, ce qui y est choisi, ses gestes. Aucun ne décide de ce qu'on peut faire : `rights`, `can` et `why` viennent du
 * serveur, un refus se dit sur place avec ses mots. **Le brouillon d'une page** ([DocEditViewModel]) vit dans son
 * modèle : il survit à une rotation et à un aller-retour, et un refus à l'enregistrement — le conflit d'une page changée
 * depuis la lecture — ne lui fait rien perdre. Tous prennent ce qu'il leur faut par [ProjectsDeps] et se testent sur la
 * JVM contre une fausse API.
 */

// ── La documentation ────────────────────────────────────────────────────

/**
 * L'onglet Documentation d'un projet, un par projet et par session : l'espace (ses pages, ses images, ses droits), ce
 * que la recherche a trouvé, ses décisions techniques, et les gestes sur ses images.
 */
class DocsViewModel(private val deps: ProjectsDeps, val id: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val space: Kept<DocSpace> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.docs(id) }
    val decisions: Kept<DecisionList> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.decisions(id) }

    /** Les dossiers repliés de l'arborescence. */
    var closed by mutableStateOf<Set<String>>(emptySet())
        private set
    var query by mutableStateOf("")
        private set
    /** Ce que la recherche a trouvé ; `null` : on ne cherche pas. */
    var found by mutableStateOf<Load<DocFound>?>(null)
        private set
    /** Une image part ; son nom, une fois ajoutée (à dire, une fois). */
    var uploading by mutableStateOf(false)
        private set

    /** La page qui vient d'être créée : son chemin (elle s'ouvre en écriture, une fois, puis [createdSeen]). */
    var created by mutableStateOf("")
        private set

    private var searchJob: Job? = null
    private val uploadKey = SendKey()
    /** L'onglet est à l'écran : quitté, un geste qui aboutit plus tard n'y ouvre plus rien. */
    private var watched = true

    /** Le volet montré s'ouvre : ce qu'il lit se lit une fois, puis à chaque retour. */
    fun show(sub: String) {
        watched = true
        if (sub == DocTabs.DECISIONS) decisions.open() else space.open()
    }

    fun resume() {
        watched = true
        space.again()
        decisions.again()
    }

    /** L'onglet quitté pour de bon (pas une rotation) : ce qui devait s'y ouvrir ne s'ouvrira pas à son retour. */
    fun leave() {
        watched = false
        created = ""
    }

    /**
     * « Nouvelle page », validée : **la page se crée tout de suite** (son titre pour premier texte, comme le client
     * web), et le serveur juge son chemin — trop long, trop profond, déjà pris — avant qu'on ait écrit quoi que ce
     * soit : son refus se dit dans la feuille ([NEW]). Créée, elle s'ouvre en écriture ([created]).
     */
    fun create(path: String, title: String): Boolean {
        val sending = newPageSave(path, title)
        return gestures.run(NEW, sending, { key -> deps.api.saveDoc(id, sending, key).done() }, failed = { space.read() }) {
            space.read()
            if (watched) created = path
        }
    }

    fun createdSeen() {
        created = ""
    }

    /** Après un geste (ici ou sur une page) : ce qui était lu se relit. */
    fun reload() {
        space.again()
        decisions.again()
        if (query.isNotBlank()) search(query, 0)
    }

    fun fold(folder: String) {
        closed = if (folder in closed) closed - folder else closed + folder
    }

    /** Chercher : la liste se relit après une pause de frappe ; un champ vidé revient à l'arborescence. */
    fun search(words: String, pauseMs: Long = ProjectViewModel.SEARCH_PAUSE_MS) {
        query = words
        searchJob?.cancel()
        if (words.isBlank()) {
            found = null
            return
        }
        searchJob = viewModelScope.launch {
            if (pauseMs > 0) delay(pauseMs)
            if (found == null) found = Load.Loading
            val got = deps.api.docSearch(id, words)
            if (got is MoiApi.Result.Ok || found !is Load.Ready) found = Load.of(got)
        }
    }

    /** Téléverser une image : elle rejoint l'espace ; [done] reçoit le nom que le serveur lui a donné. */
    fun upload(image: DocUpload, done: (String) -> Unit = {}) {
        if (uploading) return
        uploading = true
        gestures.forget(IMAGES)
        viewModelScope.launch {
            val got = deps.api.uploadDocImage(id, image, uploadKey.of(image))
            uploadKey.settled(networkFailure = (got as? MoiApi.Result.Failed)?.error?.network == true)
            uploading = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    gestures.say(got.value.message)
                    space.read()
                    if (got.value.name.isNotEmpty()) done(got.value.name)
                }
                is MoiApi.Result.Failed -> gestures.refuse(IMAGES, got.error)
            }
        }
    }

    fun removeImage(name: String) {
        gestures.send(id, docImageRemoveRequest(name), IMAGES) { space.read() }
    }

    companion object {
        /** Les gestes sur les images, dits en tête de leur volet. */
        const val IMAGES = "doc-images"
        /** « Nouvelle page » : son refus se dit dans sa feuille. */
        const val NEW = "doc-new"
    }
}

/** Un enregistrement vu comme un geste : fait, avec les mots du serveur ; refusé, tel quel. */
private fun MoiApi.Result<PageSaved>.done(): MoiApi.Result<GestureDone> = when (this) {
    is MoiApi.Result.Ok -> MoiApi.Result.Ok(GestureDone(ok = true, message = value.message))
    is MoiApi.Result.Failed -> this
}

/**
 * Une page de documentation ouverte : son texte, ses versions, la version gardée qu'on regarde, et ses gestes — revenir
 * à une version (une version de plus, partie de la version lue), la renommer ou la déplacer, la supprimer. [revision]
 * compte ses gestes aboutis : l'onglet se relit alors.
 */
class DocPageViewModel(private val deps: ProjectsDeps, val project: Int, val path: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)

    /** La page découpée pour l'écran ([docPieces]) et son sommaire : calculés hors du fil principal, avant qu'elle soit montrée. */
    var body by mutableStateOf<List<DocPiece>>(emptyList())
        private set
    var outline by mutableStateOf<List<Pair<Int, String>>>(emptyList())
        private set
    /** La version gardée qu'on regarde, découpée de même. */
    var versionBody by mutableStateOf<List<DocPiece>>(emptyList())
        private set

    val page: Kept<DocPage> = Kept(viewModelScope, deps.now, gestures::say) {
        val got = deps.api.docPage(project, path)
        got.weighed(deps.compute) { docPieces(it.text) to headingsOf(it.text) }?.let { (pieces, titles) ->
            body = pieces
            outline = titles
        }
        got
    }
    val history: Kept<DocHistory> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.docHistory(project, path) }

    /** La version gardée qu'on regarde ; `null` : la page elle-même. */
    var version by mutableStateOf<Load<DocVersion>?>(null)
        private set
    var revision by mutableIntStateOf(0)
        private set
    /** Où la page vit maintenant, une fois déplacée ; et si elle a été supprimée. */
    var moved by mutableStateOf("")
        private set
    var removed by mutableStateOf(false)
        private set
    /** La page est à l'écran : quittée, un geste qui aboutit plus tard ne le déplace ni ne le referme à son retour. */
    private var watched = true

    fun resume() {
        watched = true
        if (page.load == null) page.read() else page.again()
        history.again()
    }

    /** L'écran quitté pour de bon (pas une rotation). */
    fun leave() {
        watched = false
        gone()
    }

    fun openHistory() = history.open()

    private var versionJob: Job? = null

    /**
     * Regarder une version gardée ([n] ≤ 0 : revenir à la page). La lecture d'avant s'abandonne : une version demandée
     * puis quittée, ou une autre choisie entre-temps, ne revient pas quand sa réponse arrive.
     */
    fun showVersion(n: Int) {
        versionJob?.cancel()
        if (n <= 0) {
            version = null
            return
        }
        version = Load.Loading
        versionJob = viewModelScope.launch {
            val got = deps.api.docVersion(project, path, n)
            versionBody = got.weighed(deps.compute) { docPieces(it.text) }.orEmpty()
            version = Load.of(got)
        }
    }

    /**
     * Revenir à une version gardée : la demande nomme la version courante lue. Il n'y a pas de version 0 : sans numéro,
     * rien ne part. Refusée (la page a changé depuis), la page et ses versions se relisent.
     */
    fun restore(n: Int) {
        val base = page.value?.version ?: return
        if (n <= 0) return
        gestures.send(project, docRestoreRequest(path, n, base), HERE, failed = {
            page.read()
            history.again()
        }) {
            showVersion(0)
            revision++
            page.read()
            history.again()
        }
    }

    fun move(to: String) {
        gestures.send(project, docMoveRequest(path, to), MOVE) {
            revision++
            if (watched) moved = to
        }
    }

    /** L'écran a suivi la page déplacée, ou quitté la page supprimée. */
    fun gone() {
        moved = ""
        removed = false
    }

    fun remove() {
        gestures.send(project, docRemoveRequest(path), HERE) {
            revision++
            if (watched) removed = true
        }
    }

    companion object {
        const val HERE = "doc-page"
        const val MOVE = "doc-move"
    }
}

/**
 * L'éditeur d'une page : **son brouillon** — la version lue, le texte lu, ce qui est tapé depuis — et la sélection du
 * champ. Enregistrer nomme la version lue (`base`) ; si la page a changé depuis, le serveur refuse : ses mots se disent,
 * le texte reste, et l'on reprend sur la version actuelle ([rebase]) ou on la prend ([takeCurrent]). **Un 409 n'est un
 * conflit que si la page existe et n'en est plus à la version lue** : après lui la page se relit pour le savoir ; un
 * autre refus (le même texte, une page disparue, une borne) se dit avec les mots du serveur, sans rien à reprendre. Si
 * elle ne se relit pas (le réseau, une panne — pas une page introuvable), on ne le sait pas : de quoi reprendre reste.
 */
class DocEditViewModel(private val deps: ProjectsDeps, val project: Int, val path: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val space: Kept<DocSpace> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.docs(project) }

    /** La page se lit avant qu'on l'écrive ; refusée, elle le dit. */
    var load by mutableStateOf<Load<Unit>>(Load.Loading)
        private set
    var draft by mutableStateOf<Draft?>(null)
        private set
    /** Ce qui est écrit, et ce qui y est choisi. */
    var edit by mutableStateOf(Edit("", 0))
        private set
    var saving by mutableStateOf(false)
        private set
    var uploading by mutableStateOf(false)
        private set
    /** La page telle qu'elle est maintenant, relue après un conflit. */
    var current by mutableStateOf<DocPage?>(null)
        private set
    /** La version actuelle ne s'est pas relue : les mots de l'erreur, dits à sa place (plutôt qu'une attente sans fin). */
    var currentRefusal by mutableStateOf("")
        private set
    /** Les enregistrements aboutis : l'onglet et la page se relisent alors. */
    var saved by mutableIntStateOf(0)
        private set
    /** Un enregistrement vient d'aboutir : l'écran revient à la page (une fois, puis [savedSeen]). */
    var justSaved by mutableStateOf(false)
        private set

    private val saveKey = SendKey()
    private val uploadKey = SendKey()
    private var started = false
    /** L'éditeur est à l'écran : quitté, un enregistrement qui aboutit plus tard ne le referme pas à son retour. */
    private var watched = true

    val dirty: Boolean get() = draft?.dirty == true

    /**
     * L'écran s'ouvre : la page se lit ; **un brouillon déjà commencé reste tel quel** (une rotation, un aller-retour).
     * Sans rien d'écrit en attente, elle se relit : elle a pu changer depuis.
     */
    fun open() {
        watched = true
        space.open()
        if (started) {
            // même avec un texte en attente : la page a pu être supprimée, ou recréée, depuis qu'on l'a quittée
            if (!saving) read()
            return
        }
        started = true
        read()
    }

    /** L'écran quitté pour de bon (pas une rotation) : ce qui devait le refermer ne le refermera pas à son retour. */
    fun leave() {
        watched = false
        justSaved = false
    }

    fun savedSeen() {
        justSaved = false
    }

    fun retry() {
        load = Load.Loading
        read()
    }

    private fun read() {
        viewModelScope.launch {
            when (val got = deps.api.docPage(project, path)) {
                // ce qui a été tapé pendant la lecture reste : la page lue ne remplace qu'un brouillon intact — ou
                // celui d'une autre page : supprimée puis recréée sous ce chemin, ce qu'on avait de l'ancienne n'est
                // pas d'elle, et ne ressort pas
                is MoiApi.Result.Ok -> if (draft?.takeIf { it.dirty }?.isOf(got.value) != true) start(Draft.of(got.value))
                is MoiApi.Result.Failed -> when {
                    draft == null -> load = Load.Failed(got.error)
                    got.error.code != 404 -> Unit
                    // la page n'existe plus : sans rien d'écrit en attente, son ancien texte ne ressort pas
                    !dirty -> {
                        draft = null
                        current = null
                        load = Load.Failed(got.error)
                    }
                    // ce qui est écrit reste, et on dit qu'elle n'est plus là : rien à reprendre
                    else -> draft = draft?.refused(refusalWords(got.error.message, got.error.fields))
                }
            }
        }
    }

    private fun start(d: Draft) {
        draft = d
        edit = Edit(d.text, d.text.length)
        load = Load.Ready(Unit)
    }

    private fun put(e: Edit) {
        edit = e
        draft = draft?.typed(e.text)
    }

    /** Ce que le champ vient de recevoir : une frappe, une sélection ; « Entrée » poursuit une liste. */
    fun type(e: Edit) = put(if (e.text == edit.text) e else MdEdit.continued(edit, e))

    /** Un geste de la barre d'outils, sur la sélection. */
    fun change(how: (Edit) -> Edit) = put(how(edit))

    /** Enregistrer : une version de plus, partie de la version lue. Un double appui ne part qu'une fois. */
    fun save(word: String) {
        val d = draft ?: return
        if (saving) return
        val sending = saveOf(d, word)
        saving = true
        viewModelScope.launch {
            val got = deps.api.saveDoc(project, sending, saveKey.of(sending))
            saveKey.settled(networkFailure = (got as? MoiApi.Result.Failed)?.error?.network == true)
            when (got) {
                is MoiApi.Result.Ok -> {
                    // ce qui a été tapé pendant l'envoi reste à enregistrer
                    draft = draft?.copy(base = got.value.version, read = sending.text, refusal = "", conflict = false)
                    current = null
                    saved++
                    if (watched) justSaved = true
                    gestures.say(got.value.message)
                }
                is MoiApi.Result.Failed -> {
                    // un 409 n'est un conflit que si la page a bougé : le serveur le répond aussi au même texte, à une
                    // page disparue, à une borne atteinte. On la relit pour le savoir ; introuvable, ce n'en est pas
                    // un — ses mots se disent, sans rien à reprendre. Injoignable (le réseau, une panne), on ne le
                    // sait pas : de quoi reprendre reste offert, et la version actuelle se relira à la demande
                    val reread = if (got.error.code == 409) deps.api.docPage(project, path) else null
                    val now = (reread as? MoiApi.Result.Ok)?.value
                    val unknown = reread is MoiApi.Result.Failed && reread.error.code != 404
                    val moved = draft?.movedOn(now) == true
                    current = now.takeIf { moved }
                    currentRefusal = ""
                    draft = draft?.refused(refusalWords(got.error.message, got.error.fields), moved || unknown)
                }
            }
            saving = false
        }
    }

    /** Après un conflit : relire la page telle qu'elle est maintenant, pour la montrer. */
    fun readCurrent() {
        currentRefusal = ""
        viewModelScope.launch {
            when (val got = deps.api.docPage(project, path)) {
                is MoiApi.Result.Ok -> current = got.value
                is MoiApi.Result.Failed -> unread(got.error)
            }
        }
    }

    /**
     * La version actuelle ne s'est pas relue : l'erreur se dit avec ses mots. Si la page n'existe plus, il n'y a plus
     * de conflit à reprendre — ce qui est écrit reste.
     */
    private fun unread(error: MoiError) {
        val words = refusalWords(error.message, error.fields)
        currentRefusal = words
        if (error.code == 404) {
            current = null
            draft = draft?.refused(words)
        } else {
            gestures.say(error.said)
        }
    }

    /** Reprendre sur la version actuelle : elle devient la version de départ, **le texte tapé reste entier**. */
    fun rebase() {
        viewModelScope.launch {
            when (val got = deps.api.docPage(project, path)) {
                is MoiApi.Result.Ok -> {
                    current = got.value
                    currentRefusal = ""
                    draft = draft?.rebased(got.value)
                }
                is MoiApi.Result.Failed -> unread(got.error)
            }
        }
    }

    /** Prendre la version actuelle à la place de ce qui est écrit. */
    fun takeCurrent() {
        val now = current ?: return
        start(Draft.of(now))
        current = null
        currentRefusal = ""
    }

    /** Jeter ce qui est écrit depuis la lecture. */
    fun discard() {
        val d = draft ?: return
        start(d.copy(text = d.read, refusal = "", conflict = false))
    }

    /** Une image choisie dans le téléphone : elle part au serveur, puis se cite là où est le curseur. */
    fun upload(image: DocUpload) {
        if (uploading) return
        uploading = true
        gestures.forget(IMAGE)
        viewModelScope.launch {
            val got = deps.api.uploadDocImage(project, image, uploadKey.of(image))
            uploadKey.settled(networkFailure = (got as? MoiApi.Result.Failed)?.error?.network == true)
            uploading = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    gestures.say(got.value.message)
                    space.read()
                    if (got.value.name.isNotEmpty()) change { MdEdit.image(it, got.value.name) }
                }
                is MoiApi.Result.Failed -> gestures.refuse(IMAGE, got.error)
            }
        }
    }

    companion object {
        /** Le refus d'un téléversement, dit dans la feuille des images. */
        const val IMAGE = "doc-edit-image"
    }
}

// ── L'activité ──────────────────────────────────────────────────────────

/**
 * L'onglet Activité d'un projet, un par projet et par session : son fil (ses filtres par sorte et par objectif, sa
 * suite à la demande), ses trente derniers jours, ses totaux, ses exécutions, son carnet.
 */
class ActivityViewModel(private val deps: ProjectsDeps, val id: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val days: Kept<ActivityDays> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.activityDays(id) }
    /** Les totaux de toute son histoire (les comptes des volets), et ceux de l'objectif filtré (les pastilles du fil). */
    val totals: Kept<ActivityTotals> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.activityTotals(id) }
    val filtered: Kept<ActivityTotals> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.activityTotals(id, objective) }
    /** Les exécutions : chaque lecture de leur première page (ouverte, relue, réessayée) pose aussi le curseur de la suite. */
    val runs: Kept<RunPage> = Kept(viewModelScope, deps.now, gestures::say) {
        deps.api.runs(id).also { got -> if (got is MoiApi.Result.Ok) runsRead(got.value) }
    }

    // ── Le fil ──
    var kind by mutableStateOf("")
        private set
    var objective by mutableIntStateOf(0)
        private set
    var feed by mutableStateOf<Load<ActivityPage>?>(null)
        private set
    /** La suite du fil, page après page, et le curseur de la page suivante (0 : il n'y a plus rien). */
    var more by mutableStateOf<List<Happening>>(emptyList())
        private set
    var cursor by mutableLongStateOf(0L)
        private set
    var loadingMore by mutableStateOf(false)
        private set

    // ── Les exécutions ──
    var moreRuns by mutableStateOf<List<Run>>(emptyList())
        private set
    var runsCursor by mutableLongStateOf(0L)
        private set

    // ── Le carnet ──
    var notebookObjective by mutableIntStateOf(0)
        private set
    var notes by mutableStateOf<Load<NotebookPage>?>(null)
        private set
    var moreNotes by mutableStateOf<List<NotebookNote>>(emptyList())
        private set
    var notesCursor by mutableLongStateOf(0L)
        private set

    private var feedJob: Job? = null
    private var notesJob: Job? = null

    val items: List<Happening> get() = feed?.valueOrNull?.items.orEmpty() + more
    val allRuns: List<Run> get() = runs.value?.items.orEmpty() + moreRuns
    val allNotes: List<NotebookNote> get() = notes?.valueOrNull?.items.orEmpty() + moreNotes

    /** Le volet montré s'ouvre : ce qu'il lit se lit une fois. */
    fun show(sub: String) {
        totals.open()
        when (sub) {
            ActivityTabs.RUNS -> runs.open()
            ActivityTabs.NOTEBOOK -> if (notes == null) loadNotes()
            else -> {
                if (feed == null) loadFeed()
                filtered.open()
            }
        }
    }

    fun openDays() = days.open()

    fun resume() {
        totals.again()
        days.again()
        if (feed != null) loadFeed()
        runs.again()
        if (notes != null) loadNotes()
        filtered.again()
    }

    /** Le fil d'une sorte (vide : tout). */
    fun pickKind(code: String) {
        if (kind == code) return
        kind = code
        feed = Load.Loading
        loadFeed()
    }

    fun pickObjective(objective: Int) {
        if (this.objective == objective) return
        this.objective = objective
        feed = Load.Loading
        loadFeed()
        filtered.read()
    }

    /**
     * Le fil se lit, ou se relit. **Relu en place** (un retour sur l'écran, tirer), la suite déjà chargée reste tant
     * que la page relue la rejoint ([olderKept]) ; sous un autre filtre, ou s'il manquerait des lignes entre les deux,
     * elle repart de la page relue.
     */
    fun loadFeed(): Job {
        feedJob?.cancel()
        if (feed == null) feed = Load.Loading
        val keep = feed is Load.Ready
        return viewModelScope.launch {
            val got = deps.api.activity(id, kind = kind, objective = objective)
            if (got is MoiApi.Result.Ok) {
                val older = if (keep) olderKept(items, got.value.items, ::sameHappening) else emptyList()
                if (older.isEmpty()) cursor = got.value.next
                more = older
            }
            if (got is MoiApi.Result.Ok || feed !is Load.Ready) feed = Load.of(got)
        }.also { feedJob = it }
    }

    /** La suite du fil : la page d'avant le curseur, sans redire ce qu'on a déjà. */
    fun more() {
        if (loadingMore || cursor <= 0) return
        loadingMore = true
        val asked = Triple(kind, objective, cursor)
        viewModelScope.launch {
            when (val got = deps.api.activity(id, kind = kind, objective = objective, before = cursor)) {
                // une réponse tardive — un autre filtre, une suite repartie entre-temps — ne s'ajoute pas
                is MoiApi.Result.Ok -> if (asked == Triple(kind, objective, cursor)) {
                    val known = items.map { it.seq }.toSet()
                    more = more + got.value.items.filterNot { it.seq in known }
                    cursor = got.value.next
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
            loadingMore = false
        }
    }

    /** La première page des exécutions vient d'être lue : la suite déjà chargée reste si elle la rejoint, et le curseur suit. */
    private fun runsRead(fresh: RunPage) {
        val older = olderKept(allRuns, fresh.items) { a, b -> a.id == b.id }
        if (older.isEmpty()) runsCursor = fresh.next
        moreRuns = older
    }

    fun moreRuns() {
        if (loadingMore || runsCursor <= 0) return
        loadingMore = true
        val asked = runsCursor
        viewModelScope.launch {
            when (val got = deps.api.runs(id, runsCursor)) {
                // une suite repartie entre-temps (la première page relue ne la rejoignait plus) : la réponse ne s'ajoute pas
                is MoiApi.Result.Ok -> if (asked == runsCursor) {
                    val known = allRuns.map { it.id }.toSet()
                    moreRuns = moreRuns + got.value.items.filterNot { it.id in known }
                    runsCursor = got.value.next
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
            loadingMore = false
        }
    }

    /** Les notes qui visaient un objectif (0 : tout le carnet). */
    fun pickNotebook(objective: Int) {
        if (notebookObjective == objective) return
        notebookObjective = objective
        retryNotes()
    }

    fun retryNotes() {
        notes = Load.Loading
        loadNotes()
    }

    private fun loadNotes() {
        notesJob?.cancel()
        if (notes == null) notes = Load.Loading
        val keep = notes is Load.Ready
        notesJob = viewModelScope.launch {
            val got = deps.api.notebook(id, notebookObjective)
            if (got is MoiApi.Result.Ok) {
                val older = if (keep) olderKept(allNotes, got.value.items) { a, b -> a.seq == b.seq } else emptyList()
                if (older.isEmpty()) notesCursor = got.value.next
                moreNotes = older
            }
            if (got is MoiApi.Result.Ok || notes !is Load.Ready) notes = Load.of(got)
        }
    }

    fun moreNotes() {
        if (loadingMore || notesCursor <= 0) return
        loadingMore = true
        val asked = notebookObjective to notesCursor
        viewModelScope.launch {
            when (val got = deps.api.notebook(id, notebookObjective, notesCursor)) {
                // une réponse tardive — un autre objectif, une suite repartie entre-temps — ne s'ajoute pas
                is MoiApi.Result.Ok -> if (asked == notebookObjective to notesCursor) {
                    val known = allNotes.map { it.seq }.toSet()
                    moreNotes = moreNotes + got.value.items.filterNot { it.seq in known }
                    notesCursor = got.value.next
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
            loadingMore = false
        }
    }
}

// ── Les listes ──────────────────────────────────────────────────────────

/**
 * L'onglet Listes d'un projet, un par projet et par session : les éléments de chaque liste de suivi, lus quand elle
 * s'ouvre, et ses gestes — ajouter un élément, changer son statut, changer à qui il est. [revision] compte ses gestes
 * aboutis : la fiche se relit alors (ses comptes).
 */
class ListsViewModel(private val deps: ProjectsDeps, val id: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    var pages by mutableStateOf<Map<String, Load<EntryPage>>>(emptyMap())
        private set
    var revision by mutableIntStateOf(0)
        private set
    /** L'élément qui vient d'être ajouté : sa liste et sa clé (à ouvrir, une fois). */
    var added by mutableStateOf<Pair<String, String>?>(null)
        private set
    /**
     * Les listes dont ce qu'on montre date d'avant — l'écran revient devant, un geste vient d'aboutir ou d'être refusé —
     * et se relit : tant que le serveur n'a pas redit où en sont leurs éléments, aucun geste ne s'y offre.
     */
    var stale by mutableStateOf<Set<String>>(emptySet())
        private set
    /** Les relectures qui ont échoué, par liste : on le dit, et « Réessayer » ([load]). */
    var staleErrors by mutableStateOf<Map<String, MoiError>>(emptyMap())
        private set

    private val jobs = HashMap<String, Job>()
    /** L'onglet est à l'écran : quitté, un ajout qui aboutit plus tard n'y ouvre plus rien. */
    private var watched = true

    fun show(list: String) {
        watched = true
        if (list.isNotEmpty() && list !in pages) load(list)
    }

    fun resume() {
        watched = true
        pages.keys.toList().forEach(::load)
    }

    /** L'onglet quitté pour de bon (pas une rotation). */
    fun leave() {
        watched = false
        added = null
    }

    fun load(list: String): Job {
        jobs[list]?.cancel()
        if (pages[list] is Load.Ready) stale = stale + list else pages = pages + (list to Load.Loading)
        staleErrors = staleErrors - list
        return viewModelScope.launch {
            when (val got = deps.api.elements(id, list = list)) {
                is MoiApi.Result.Ok -> {
                    pages = pages + (list to Load.Ready(got.value))
                    stale = stale - list
                }
                is MoiApi.Result.Failed ->
                    if (pages[list] is Load.Ready) staleErrors = staleErrors + (list to got.error) else pages = pages + (list to Load.Failed(got.error))
            }
        }.also { jobs[list] = it }
    }

    private fun changed(list: String) {
        revision++
        load(list)
    }

    // Un geste refusé relit la liste comme un geste abouti : un refus dit le plus souvent que la situation a changé.

    fun setStatus(e: Entry, status: String) {
        if (e.list in stale) return
        gestures.send(id, itemStatusRequest(e, status), where(e.list), failed = { load(e.list) }) { changed(e.list) }
    }

    fun assign(e: Entry, actor: String) {
        if (e.list in stale) return
        gestures.send(id, itemAssignRequest(e, actor), where(e.list), failed = { load(e.list) }) { changed(e.list) }
    }

    fun add(list: String, title: String, text: String, status: String, actor: String) {
        gestures.send(id, itemAddRequest(list, title, text, status, actor), ADD) { done ->
            changed(list)
            if (watched && done.key.isNotEmpty()) added = (done.list.ifEmpty { list }) to done.key
        }
    }

    fun addedSeen() {
        added = null
    }

    companion object {
        const val ADD = "item-add"

        /** Les gestes sur les éléments d'une liste, dits en tête de la liste. */
        fun where(list: String): String = "list:$list"
    }
}

/** Un élément d'une liste de suivi, ouvert : son texte, son fil (ce qui lui est arrivé), ses gestes du moment. */
class ItemViewModel(private val deps: ProjectsDeps, val project: Int, val list: String, val key: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    var element by mutableStateOf<Load<EntryDetail>?>(null)
        private set
    var note by mutableStateOf("")
    var revision by mutableIntStateOf(0)
        private set
    /**
     * L'élément montré date d'avant — l'écran revient devant, un geste vient d'aboutir ou d'être refusé — et se relit :
     * tant que le serveur n'a pas redit où il en est, aucun geste ne s'y offre (rien ne se décide sur l'ancienne lecture).
     */
    var stale by mutableStateOf(false)
        private set
    /** Sa relecture a échoué : on le dit, et « Réessayer » ([reread]). */
    var staleError by mutableStateOf<MoiError?>(null)
        private set

    private var job: Job? = null

    /** L'écran s'ouvre, ou revient devant : l'élément montre ce que le serveur dit maintenant. */
    fun resume() {
        load(quiet = true)
    }

    fun retry() {
        element = Load.Loading
        load(quiet = false)
    }

    /** « Réessayer », après une relecture qui a échoué. */
    fun reread() {
        load(quiet = false)
    }

    private fun load(quiet: Boolean): Job {
        job?.cancel()
        // ce qu'on montre date d'avant cette lecture : rien ne s'y décide tant qu'elle n'a pas abouti
        if (element is Load.Ready) stale = true else element = Load.Loading
        staleError = null
        return viewModelScope.launch {
            when (val got = deps.api.element(project, list, key)) {
                is MoiApi.Result.Ok -> {
                    element = Load.Ready(got.value)
                    stale = false
                }
                is MoiApi.Result.Failed -> if (element is Load.Ready) {
                    staleError = got.error
                    if (!quiet) gestures.say(got.error.said)
                } else {
                    element = Load.Failed(got.error)
                }
            }
        }.also { job = it }
    }

    private fun changed() {
        revision++
        load(quiet = true)
    }

    // Un geste refusé relit l'élément comme un geste abouti : un refus dit le plus souvent que la situation a changé.

    fun setStatus(status: String) {
        val e = element?.valueOrNull ?: return
        if (stale) return
        gestures.send(project, itemStatusRequest(e.line, status), HERE, failed = { load(quiet = true) }) { changed() }
    }

    fun assign(actor: String) {
        val e = element?.valueOrNull ?: return
        if (stale) return
        gestures.send(project, itemAssignRequest(e.line, actor), HERE, failed = { load(quiet = true) }) { changed() }
    }

    fun sendNote() {
        val e = element?.valueOrNull ?: return
        if (note.isBlank() || stale) return
        gestures.send(project, noteRequest(e.line, note), HERE, failed = { load(quiet = true) }) {
            note = ""
            changed()
        }
    }

    companion object {
        const val HERE = "item"
    }
}

// ── Modifier le projet ──────────────────────────────────────────────────

/**
 * Les réglages d'un projet (`GET …/reglages`) : ses sections, ce qui est saisi dans chacune, et ses gestes —
 * enregistrer une section (seulement ce qui change), l'archiver. Un champ que le serveur réserve ne part jamais.
 */
class SettingsViewModel(private val deps: ProjectsDeps, val id: Int) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val settings: Kept<ProjectSettings> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.settings(id) }

    /** Ce qui est saisi, par section puis par champ. */
    var typed by mutableStateOf<Map<String, Map<String, JsonElement>>>(emptyMap())
        private set
    var revision by mutableIntStateOf(0)
        private set
    var archived by mutableStateOf(false)
        private set
    /** L'écran est devant : quitté, un archivage qui aboutit plus tard ne ramène pas à la rubrique à son retour. */
    private var watched = true

    fun resume() {
        watched = true
        if (settings.load == null) settings.read() else settings.again()
    }

    /**
     * La page d'une section quittée pour de bon (pas une rotation ; [section] vide : la liste des sections) : ce qu'on
     * y avait saisi sans l'enregistrer, et ce qu'on y avait dit, ne valent pas pour la visite suivante.
     */
    fun leave(section: String) {
        watched = false
        archived = false
        typed = typed - section
        gestures.forget(where(section))
    }

    fun typedIn(section: String): Map<String, JsonElement> = typed[section].orEmpty()

    fun set(section: String, field: String, value: JsonElement) {
        typed = typed + (section to (typedIn(section) + (field to value)))
    }

    /** Ce qui change dans une section, vu ce qui est servi : rien, tant que rien n'est saisi d'autre. */
    fun changes(section: SettingsSection): Map<String, JsonElement> = settingsChanged(section.fields, typedIn(section.name))

    /**
     * Enregistrer une section : seulement ce qui change de ce que le serveur sert. Rien ne part tant que ses réglages
     * se relisent ([Kept.stale] : l'écran revient devant, une section vient d'être enregistrée) — ce qui change se
     * compte sur ce qu'il sert maintenant, pas sur l'ancienne lecture. Faux : rien n'est parti.
     */
    fun save(section: SettingsSection): Boolean {
        if (settings.stale || changes(section).isEmpty()) return false
        return gestures.send(id, settingsRequest(section.name, section.fields, typedIn(section.name)), where(section.name)) {
            typed = typed - section.name
            revision++
            settings.read()
        }
    }

    /** L'archiver : pas plus que le reste tant que ses réglages se relisent (le droit de l'archiver en vient). */
    fun archive(): Boolean =
        !settings.stale && gestures.send(id, archiveRequest(), PROJECT) { if (watched) archived = true }

    fun archivedSeen() {
        archived = false
    }

    companion object {
        /** Les gestes sur le projet lui-même (l'archiver, la pause), dits sous ses sections. */
        const val PROJECT = "settings-project"

        fun where(section: String): String = "settings:$section"
    }
}
