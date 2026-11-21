package fr.qwartz.mika.ui.projects

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import fr.qwartz.mika.data.moi.MoiApi
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
import fr.qwartz.mika.data.moi.projects.Happening
import fr.qwartz.mika.data.moi.projects.MdEdit
import fr.qwartz.mika.data.moi.projects.NotebookNote
import fr.qwartz.mika.data.moi.projects.NotebookPage
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
import fr.qwartz.mika.data.moi.projects.noteRequest
import fr.qwartz.mika.data.moi.projects.refusalWords
import fr.qwartz.mika.data.moi.projects.saveOf
import fr.qwartz.mika.data.moi.projects.settingsChanged
import fr.qwartz.mika.data.moi.projects.settingsRequest
import fr.qwartz.mika.ui.shell.Load
import fr.qwartz.mika.ui.shell.said
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonElement

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

    private var searchJob: Job? = null
    private val uploadKey = SendKey()

    /** Le volet montré s'ouvre : ce qu'il lit se lit une fois, puis à chaque retour. */
    fun show(sub: String) {
        if (sub == DocTabs.DECISIONS) decisions.open() else space.open()
    }

    fun resume() {
        space.again()
        decisions.again()
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
    }
}

/**
 * Une page de documentation ouverte : son texte, ses versions, la version gardée qu'on regarde, et ses gestes — revenir
 * à une version (une version de plus, partie de la version lue), la renommer ou la déplacer, la supprimer. [revision]
 * compte ses gestes aboutis : l'onglet se relit alors.
 */
class DocPageViewModel(private val deps: ProjectsDeps, val project: Int, val path: String) : ViewModel() {
    val gestures = GestureRunner(deps, viewModelScope)
    val page: Kept<DocPage> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.docPage(project, path) }
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

    fun resume() {
        if (page.load == null) page.read() else page.again()
        history.again()
    }

    fun openHistory() = history.open()

    fun showVersion(n: Int) {
        if (n <= 0) {
            version = null
            return
        }
        version = Load.Loading
        viewModelScope.launch { version = Load.of(deps.api.docVersion(project, path, n)) }
    }

    /** Revenir à une version gardée : la demande nomme la version courante lue. */
    fun restore(n: Int) {
        val base = page.value?.version ?: return
        gestures.send(project, docRestoreRequest(path, n, base), HERE) {
            version = null
            revision++
            page.read()
            history.again()
        }
    }

    fun move(to: String) {
        gestures.send(project, docMoveRequest(path, to), MOVE) {
            revision++
            moved = to
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
            removed = true
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
 * le texte reste, et l'on reprend sur la version actuelle ([rebase]) ou on la prend ([takeCurrent]). [title] : une page
 * nouvelle, qui naît à son premier enregistrement (`base` 0).
 */
class DocEditViewModel(private val deps: ProjectsDeps, val project: Int, val path: String, private val title: String? = null) : ViewModel() {
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
    /** Les enregistrements aboutis : l'onglet et la page se relisent alors. */
    var saved by mutableIntStateOf(0)
        private set
    /** Un enregistrement vient d'aboutir : l'écran revient à la page (une fois, puis [savedSeen]). */
    var justSaved by mutableStateOf(false)
        private set

    private val saveKey = SendKey()
    private val uploadKey = SendKey()
    private var started = false

    val dirty: Boolean get() = draft?.dirty == true

    /**
     * L'écran s'ouvre : la page se lit ; **un brouillon déjà commencé reste tel quel** (une rotation, un aller-retour).
     * Sans rien d'écrit en attente, elle se relit : elle a pu changer depuis.
     */
    fun open() {
        space.open()
        if (started) {
            if (!dirty && !saving) read()
            return
        }
        started = true
        if (title != null) {
            start(Draft.fresh(path, if (title.isBlank()) "" else "# ${title.trim()}\n\n"))
            return
        }
        read()
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
                // ce qui a été tapé pendant la lecture reste : la page lue ne remplace qu'un brouillon intact
                is MoiApi.Result.Ok -> if (!dirty) start(Draft.of(got.value))
                is MoiApi.Result.Failed -> if (draft == null) load = Load.Failed(got.error)
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
            saving = false
            when (got) {
                is MoiApi.Result.Ok -> {
                    // ce qui a été tapé pendant l'envoi reste à enregistrer
                    draft = draft?.copy(base = got.value.version, read = sending.text, refusal = "", conflict = false)
                    current = null
                    saved++
                    justSaved = true
                    gestures.say(got.value.message)
                }
                is MoiApi.Result.Failed -> draft = draft?.refused(got.error.code, refusalWords(got.error.message, got.error.fields))
            }
        }
    }

    /** Après un conflit : relire la page telle qu'elle est maintenant, pour la montrer. */
    fun readCurrent() {
        viewModelScope.launch {
            when (val got = deps.api.docPage(project, path)) {
                is MoiApi.Result.Ok -> current = got.value
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
        }
    }

    /** Reprendre sur la version actuelle : elle devient la version de départ, **le texte tapé reste entier**. */
    fun rebase() {
        viewModelScope.launch {
            when (val got = deps.api.docPage(project, path)) {
                is MoiApi.Result.Ok -> {
                    current = got.value
                    draft = draft?.rebased(got.value)
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
        }
    }

    /** Prendre la version actuelle à la place de ce qui est écrit. */
    fun takeCurrent() {
        val now = current ?: return
        start(Draft.of(now))
        current = null
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
    val runs: Kept<RunPage> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.runs(id) }

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
            ActivityTabs.RUNS -> if (runs.load == null) loadRuns()
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
        if (runs.load != null) loadRuns()
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

    fun loadFeed(): Job {
        feedJob?.cancel()
        if (feed == null) feed = Load.Loading
        return viewModelScope.launch {
            val got = deps.api.activity(id, kind = kind, objective = objective)
            if (got is MoiApi.Result.Ok) {
                more = emptyList()
                cursor = got.value.next
            }
            if (got is MoiApi.Result.Ok || feed !is Load.Ready) feed = Load.of(got)
        }.also { feedJob = it }
    }

    /** La suite du fil : la page d'avant le curseur, sans redire ce qu'on a déjà. */
    fun more() {
        if (loadingMore || cursor <= 0) return
        loadingMore = true
        val asked = kind to objective
        viewModelScope.launch {
            when (val got = deps.api.activity(id, kind = kind, objective = objective, before = cursor)) {
                is MoiApi.Result.Ok -> if (asked == kind to objective) {
                    val known = items.map { it.seq }.toSet()
                    more = more + got.value.items.filterNot { it.seq in known }
                    cursor = got.value.next
                }
                is MoiApi.Result.Failed -> gestures.say(got.error.said)
            }
            loadingMore = false
        }
    }

    private fun loadRuns() {
        runs.read().invokeOnCompletion {
            moreRuns = emptyList()
            runsCursor = runs.value?.next ?: 0
        }
    }

    fun moreRuns() {
        if (loadingMore || runsCursor <= 0) return
        loadingMore = true
        viewModelScope.launch {
            when (val got = deps.api.runs(id, runsCursor)) {
                is MoiApi.Result.Ok -> {
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
        notesJob = viewModelScope.launch {
            val got = deps.api.notebook(id, notebookObjective)
            if (got is MoiApi.Result.Ok) {
                moreNotes = emptyList()
                notesCursor = got.value.next
            }
            if (got is MoiApi.Result.Ok || notes !is Load.Ready) notes = Load.of(got)
        }
    }

    fun moreNotes() {
        if (loadingMore || notesCursor <= 0) return
        loadingMore = true
        viewModelScope.launch {
            when (val got = deps.api.notebook(id, notebookObjective, notesCursor)) {
                is MoiApi.Result.Ok -> {
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

    fun show(list: String) {
        if (list.isNotEmpty() && list !in pages) load(list)
    }

    fun resume() {
        pages.keys.toList().forEach(::load)
    }

    fun load(list: String): Job {
        if (list !in pages) pages = pages + (list to Load.Loading)
        return viewModelScope.launch {
            val got = deps.api.elements(id, list = list)
            if (got is MoiApi.Result.Ok || pages[list] !is Load.Ready) pages = pages + (list to Load.of(got))
        }
    }

    private fun changed(list: String) {
        revision++
        load(list)
    }

    fun setStatus(e: Entry, status: String) {
        gestures.send(id, itemStatusRequest(e, status), where(e.list)) { changed(e.list) }
    }

    fun assign(e: Entry, actor: String) {
        gestures.send(id, itemAssignRequest(e, actor), where(e.list)) { changed(e.list) }
    }

    fun add(list: String, title: String, text: String, status: String, actor: String) {
        gestures.send(id, itemAddRequest(list, title, text, status, actor), ADD) { done ->
            changed(list)
            if (done.key.isNotEmpty()) added = (done.list.ifEmpty { list }) to done.key
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
    val element: Kept<EntryDetail> = Kept(viewModelScope, deps.now, gestures::say) { deps.api.element(project, list, key) }
    var note by mutableStateOf("")
    var revision by mutableIntStateOf(0)
        private set

    fun resume() {
        if (element.load == null) element.read() else element.again()
    }

    private fun changed() {
        revision++
        element.read()
    }

    fun setStatus(status: String) {
        val e = element.value ?: return
        gestures.send(project, itemStatusRequest(e.line, status), HERE) { changed() }
    }

    fun assign(actor: String) {
        val e = element.value ?: return
        gestures.send(project, itemAssignRequest(e.line, actor), HERE) { changed() }
    }

    fun sendNote() {
        val e = element.value ?: return
        if (note.isBlank()) return
        gestures.send(project, noteRequest(e.line, note), HERE) {
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

    fun resume() {
        if (settings.load == null) settings.read() else settings.again()
    }

    fun typedIn(section: String): Map<String, JsonElement> = typed[section].orEmpty()

    fun set(section: String, field: String, value: JsonElement) {
        typed = typed + (section to (typedIn(section) + (field to value)))
    }

    /** Ce qui change dans une section, vu ce qui est servi : rien, tant que rien n'est saisi d'autre. */
    fun changes(section: SettingsSection): Map<String, JsonElement> = settingsChanged(section.fields, typedIn(section.name))

    fun save(section: SettingsSection) {
        if (changes(section).isEmpty()) return
        gestures.send(id, settingsRequest(section.name, section.fields, typedIn(section.name)), where(section.name)) {
            typed = typed - section.name
            revision++
            settings.read()
        }
    }

    fun archive() {
        gestures.send(id, archiveRequest(), PROJECT) { archived = true }
    }

    fun archivedSeen() {
        archived = false
    }

    companion object {
        /** Les gestes sur le projet lui-même (l'archiver, la pause), dits sous ses sections. */
        const val PROJECT = "settings-project"

        fun where(section: String): String = "settings:$section"
    }
}
