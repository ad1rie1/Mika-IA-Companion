package fr.qwartz.mika.data.moi.projects

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Le code d'un projet dans l'API par personne (`backendv2/docs/protocole-moi.md` § 11, « Le code d'un projet » ; ADR
 * 0288) : ses fichiers, ses commits et leur diff, ses branches, ses pull requests, ses issues, sa CI. Le modèle est le
 * client web (`frontendv2/src/api/projectCode.ts`).
 *
 * Rien n'est recalculé ici : les mots sont ceux du serveur (`…_label`, `why`, `files_why`, `cut_label`), ce qu'on peut
 * faire aussi (`rights`, `merge.can`). **Tout texte de l'hôte** arrive marqué — un [OutsideText], ou `null` — : le titre
 * et le texte d'une pull request ou d'une issue, une étiquette, le nom d'une vérification, la fin d'un journal, le
 * compte qui a écrit là-bas. Un commit venu du dépôt distant porte `outside`. Le contenu d'un fichier et les lignes d'un
 * diff sont du texte : l'écran les pose tels quels, jamais comme une mise en forme.
 *
 * Une forme sert là où le serveur en sert plusieurs qui s'emboîtent ([CodePull] : en bref, dans la liste, lue seule ;
 * [Issue] : dans la liste, lue seule ; [HostChecks] : celles d'une pull request, celles d'un commit) : ce qu'une réponse
 * ne dit pas garde son défaut.
 */

/** Un commit, partout où il apparaît. [outside] : venu du dépôt distant — son message et son auteur ne sont pas d'elle. */
@Serializable
data class Commit(
    val sha: String = "",
    val short: String = "",
    val title: String = "",
    val at: Long = 0,
    /** `self` : elle ; `other`. */
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    val outside: Boolean = false,
    val branch: String = "",
    val base: Boolean = false,
    /** Une fusion. */
    val merge: Boolean = false,
    val files: Int = 0,
    val insertions: Int = 0,
    val deletions: Int = 0,
    /** Ceux qui lui sont liés ; 0 : aucun. */
    val objective: Int = 0,
    val ticket: Int = 0,
    /** Sa page chez l'hôte, composée par le serveur ; vide sans dépôt distant. */
    val url: String = "",
    /** Lu seul (`…/code/commit`) : son message entier, ses parents. */
    val body: String = "",
    val parents: List<String> = emptyList(),
)

/** La relecture indépendante d'une pull request ; [ok] `null` : pas encore de verdict. */
@Serializable
data class CodeReview(
    val ok: Boolean? = null,
    val asked: Boolean = false,
    val label: String = "",
    val at: Long = 0,
    val commit: String = "",
    val refused: Int = 0,
    @SerialName("handed_over") val handedOver: Boolean = false,
    /** Sur une pull request lue seule : qui l'a relue, ses constats, son dernier refus. */
    val by: String = "",
    val text: String = "",
    @SerialName("last_refusal") val lastRefusal: String = "",
)

/** Peut-elle la fusionner : la garde de la route, dite d'avance ; et où en est une fusion déjà demandée. */
@Serializable
data class MergeState(
    val can: Boolean = false,
    /** Pourquoi non, en mots : ce n'est pas à elle, ou ce qui retient la pull request. */
    val why: String = "",
    /** Une fusion est en route : demandée, ou faite et pas encore relue chez l'hôte. */
    val asked: Boolean = false,
    @SerialName("asked_at") val askedAt: Long = 0,
    @SerialName("asked_by") val askedBy: String = "",
    /** Pourquoi la dernière demande n'a pas abouti, en mots. */
    val refused: String = "",
    @SerialName("refused_at") val refusedAt: Long = 0,
)

/**
 * Une pull request : en bref là où elle est liée à autre chose (son numéro, son titre, son état, sa branche, sa CI, sa
 * relecture), dans la liste (sa base, ses conflits, ce qui lui est lié, [merge]), et lue seule ([head] et la suite).
 */
@Serializable
data class CodePull(
    /** 0 : pas encore de numéro (proposée, elle attend un accord). */
    val number: Int = 0,
    val title: String = "",
    /** `proposed`, `open`, `ready` (prête à fusionner), `merged`, `closed`. */
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    val url: String = "",
    val branch: String = "",
    val checks: Checks? = null,
    val review: CodeReview? = null,
    // ── dans la liste ──
    val base: String = "",
    val at: Long = 0,
    val conflicts: Boolean = false,
    @SerialName("changes_asked") val changesAsked: Boolean = false,
    @SerialName("awaits_accord") val awaitsAccord: Int = 0,
    /** Un commit n'est pas encore envoyé. */
    val unsent: Boolean = false,
    val objective: LinkedObjective? = null,
    val ticket: TicketLine? = null,
    val merge: MergeState = MergeState(),
    // ── lue seule ──
    /** Le commit au bout de sa branche : **celui à nommer pour la fusionner**. */
    val head: String = "",
    /** D'où elle s'écarte de la base. */
    val fork: String = "",
    @SerialName("done_when") val doneWhen: String = "",
    val result: String = "",
    /** Les jalons de son objectif et leurs preuves, comme sur la fiche. */
    val milestones: List<Milestone> = emptyList(),
    /** Le dernier mot de l'hôte. */
    val said: OutsideText? = null,
)

/** Ce qui est lié à un commit, à une branche, à des vérifications : l'objectif, son ticket, sa pull request, sa CI. */
@Serializable
data class CodeLinked(
    val objective: LinkedObjective? = null,
    val ticket: TicketLine? = null,
    val pull: CodePull? = null,
    val checks: Checks? = null,
)

// ── Un diff ─────────────────────────────────────────────────────────────

@Serializable
data class DiffLine(
    /** `" "`, `"+"`, `"-"`. */
    val kind: String = " ",
    /** Ses numéros avant et après ; 0 quand la ligne n'y est pas. */
    val old: Int = 0,
    val new: Int = 0,
    val text: String = "",
)

@Serializable
data class Hunk(val header: String = "", val lines: List<DiffLine> = emptyList())

@Serializable
data class DiffFile(
    val path: String = "",
    /** `added`, `modified`, `deleted`. */
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    val insertions: Int = 0,
    val deletions: Int = 0,
    val binary: Boolean = false,
    /** Ses passages ne sont pas tous là (la borne du diff) : il se relit seul par `path=`. */
    val cut: Boolean = false,
    /** Un fichier caché : son chemin et ses comptes, sans ses passages ([why]). */
    val hidden: Boolean = false,
    val why: String = "",
    val hunks: List<Hunk> = emptyList(),
) {
    /**
     * Ses lignes mises en rangées ([diffLayout]), calculées une fois. Le modèle les demande **hors du fil principal**
     * dès que le diff est lu ([Diff.lay]) : l'écran ne fait que les poser.
     */
    val laid: DiffLayout by lazy { diffLayout(this) }
}

/** Un diff : ses fichiers, ses comptes, et s'il est coupé. [filesReadable] faux : elle ne lit pas ses fichiers. */
@Serializable
data class Diff(
    val files: List<DiffFile> = emptyList(),
    val cut: Boolean = false,
    @SerialName("cut_label") val cutLabel: String = "",
    val insertions: Int = 0,
    val deletions: Int = 0,
    @SerialName("files_readable") val filesReadable: Boolean = true,
    @SerialName("files_why") val filesWhy: String = "",
) {
    /** Mettre en rangées tous ses fichiers qui ont des lignes : à faire hors du fil principal, une fois le diff lu. */
    fun lay() {
        for (f in files) if (diffBody(f) == DiffBody.LINES) f.laid
    }
}

// ── Le dépôt, ses fichiers ──────────────────────────────────────────────

@Serializable
data class CodeRemote(
    val has: Boolean = false,
    /** Sa page chez l'hôte. */
    val web: String = "",
    val branch: String = "",
    val flow: String = "",
    /** Tout y entre par une pull request. */
    @SerialName("by_pulls") val byPulls: Boolean = false,
    @SerialName("synced_at") val syncedAt: Long = 0,
)

/** Ce qu'elle peut faire du code : lire ses fichiers, fusionner. */
@Serializable
data class CodeRights(val files: Boolean = false, val merge: Boolean = false)

@Serializable
data class CodeCounts(
    val commits: Int = 0,
    val branches: Int = 0,
    @SerialName("pulls_open") val pullsOpen: Int = 0,
    @SerialName("pulls_ready") val pullsReady: Int = 0,
    @SerialName("issues_open") val issuesOpen: Int = 0,
    @SerialName("checks_failed") val checksFailed: Int = 0,
)

/** `GET …/code` : le dépôt en bref. */
@Serializable
data class CodeSummary(
    @SerialName("has_repo") val hasRepo: Boolean = false,
    val base: String = "",
    /** La branche où l'atelier se trouve. */
    val current: String = "",
    val remote: CodeRemote = CodeRemote(),
    val rights: CodeRights = CodeRights(),
    val counts: CodeCounts = CodeCounts(),
    @SerialName("last_commit") val lastCommit: Commit? = null,
)

@Serializable
data class TreeEntry(
    val path: String = "",
    val name: String = "",
    /** `dir`, `file`, `link`, `module`. */
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    val size: Long = 0,
)

/** Un dossier à une référence, un niveau à la fois. */
@Serializable
data class Tree(
    val ref: String = "",
    val path: String = "",
    val parent: String? = null,
    /** Le chemin de son README, ou vide. */
    val readme: String = "",
    /** Les entrées cachées qu'il tait. */
    val hidden: Int = 0,
    val items: List<TreeEntry> = emptyList(),
    @SerialName("last_commit") val lastCommit: Commit? = null,
)

/** Un fichier : son texte s'il se lit ([readable]) ; sinon pourquoi, en mots ([why]). */
@Serializable
data class Blob(
    val ref: String = "",
    /** Le commit lu. */
    val sha: String = "",
    val path: String = "",
    val name: String = "",
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    val size: Long = 0,
    val binary: Boolean = false,
    @SerialName("too_big") val tooBig: Boolean = false,
    val readable: Boolean = false,
    val why: String = "",
    val text: String = "",
    val lines: Int = 0,
    @SerialName("last_commit") val lastCommit: Commit? = null,
    /** Les dix derniers commits qui l'ont touché. */
    val history: List<Commit> = emptyList(),
    @SerialName("history_total") val historyTotal: Int = 0,
    val url: String = "",
) {
    /**
     * Ses lignes telles qu'on les pose ([fileLines]), calculées une fois. Le modèle les demande **hors du fil
     * principal** dès que le fichier est lu : l'écran ne fait que les poser.
     */
    val laid: FileLines by lazy { fileLines(if (readable) text else "") }
}

// ── Commits, branches, pull requests ────────────────────────────────────

@Serializable
data class CommitPage(
    val ref: String = "",
    val total: Int = 0,
    val page: Int = 1,
    val size: Int = 0,
    val items: List<Commit> = emptyList(),
)

/** Un commit lu seul : lui, ce qui lui est lié, ses fichiers et leur diff. */
data class CommitDetail(val commit: Commit, val linked: CodeLinked, val diff: Diff)

@Serializable
internal data class CommitHead(val commit: Commit = Commit(), val linked: CodeLinked = CodeLinked())

/** Une branche, et ce qui lui est lié. */
@Serializable
data class Branch(
    val name: String = "",
    /** La branche par défaut. */
    val base: Boolean = false,
    val current: Boolean = false,
    /** Son avance et son retard sur la base. */
    val ahead: Int = 0,
    val behind: Int = 0,
    /** Son dernier commit. */
    val head: Commit = Commit(),
    val objective: LinkedObjective? = null,
    val ticket: TicketLine? = null,
    val pull: CodePull? = null,
    val checks: Checks? = null,
)

@Serializable
data class BranchList(val base: String = "", val items: List<Branch> = emptyList())

/** Une branche lue seule : ce qu'elle a d'avance, ses fichiers changés avec leurs comptes (sans leurs passages). */
data class BranchDetail(val branch: Branch, val commits: List<Commit>, val diff: Diff)

@Serializable
internal data class BranchHead(val branch: Branch = Branch(), val commits: List<Commit> = emptyList())

@Serializable
data class PullPage(val total: Int = 0, val page: Int = 1, val size: Int = 0, val items: List<CodePull> = emptyList())

/** Une pull request lue seule : elle, ses commits, ses fichiers et leur diff. */
data class PullDetail(val pull: CodePull, val commits: List<Commit>, val diff: Diff)

@Serializable
internal data class PullHead(val pull: CodePull = CodePull(), val commits: List<Commit> = emptyList())

// ── Ce que l'hôte est seul à savoir ─────────────────────────────────────

/** Un échange venu de l'hôte ; [fromHere] : publié d'ici, sous le compte du jeton. Toujours cité, jamais lu. */
@Serializable
data class Remark(
    @Serializable(with = LooseText::class) val id: String = "",
    val at: Long = 0,
    @SerialName("from_here") val fromHere: Boolean = false,
    val outside: Boolean = true,
    val account: OutsideText? = null,
    val text: String = "",
)

/** Une vérification ; son nom est celui que l'hôte donne. */
@Serializable
data class CheckRun(
    val name: OutsideText? = null,
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    val started: Long = 0,
    val at: Long = 0,
    val seconds: Double = 0.0,
)

/** La fin du journal de la première vérification en échec. */
@Serializable
data class CheckLog(val name: OutsideText? = null, val tail: OutsideText? = null)

/** Les vérifications d'un commit, relues chez l'hôte ; pour `…/ci/commit`, avec le commit et ce qui lui est lié. */
@Serializable
data class HostChecks(
    val sha: String = "",
    /** `none`, `pending`, `passed`, `failed`. */
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    /** L'hôte n'a pas répondu : pourquoi, en mots. */
    val error: String = "",
    val at: Long = 0,
    @SerialName("read_at") val readAt: Long = 0,
    val runs: List<CheckRun> = emptyList(),
    val failed: List<OutsideText> = emptyList(),
    val log: CheckLog? = null,
    val commit: Commit? = null,
    val linked: CodeLinked? = null,
)

/** Ce que l'hôte dit d'une pull request, maintenant. */
@Serializable
data class PullHost(
    val number: Int = 0,
    val error: String = "",
    val title: OutsideText? = null,
    val body: OutsideText? = null,
    val head: String = "",
    val mergeable: Boolean? = null,
    val state: String = "",
    val at: Long = 0,
    @SerialName("read_at") val readAt: Long = 0,
    val talk: List<Remark> = emptyList(),
    val checks: HostChecks? = null,
)

/**
 * Une issue du dépôt. Celle qu'aucun ticket accepté ne reflète est le texte d'un inconnu : son titre, ses étiquettes,
 * son texte et ses échanges ne sont servis qu'à qui peut la trancher (sinon [veiled], [title] `null`).
 */
@Serializable
data class Issue(
    val number: Int = 0,
    val url: String = "",
    val title: OutsideText? = null,
    val veiled: String = "",
    @SerialName("veiled_label") val veiledLabel: String = "",
    /** `open`, `closed`, ou vide si l'hôte ne l'a pas dite. */
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    val dropped: Boolean = false,
    val labels: List<OutsideText> = emptyList(),
    val comments: Int = 0,
    val at: Long = 0,
    /** Publiée d'ici, sous le compte du jeton. */
    @SerialName("from_here") val fromHere: Boolean = false,
    val account: OutsideText? = null,
    /** Le ticket qui la reflète, et son étape. */
    val ticket: TicketLine? = null,
    // ── lue seule ──
    val error: String = "",
    val body: OutsideText? = null,
    val talk: List<Remark> = emptyList(),
)

@Serializable
data class IssuePage(
    val total: Int = 0,
    val page: Int = 1,
    val size: Int = 0,
    /** L'hôte ne les a pas dites : pourquoi, en mots. */
    val error: String = "",
    val items: List<Issue> = emptyList(),
)

/** Les vérifications que le moteur suit, pour le commit d'une pull request. */
@Serializable
data class TrackedChecks(
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    val sha: String = "",
    val at: Long = 0,
    /** La fin du journal d'un échec. */
    val said: OutsideText? = null,
    val commit: Commit? = null,
    val branch: String = "",
    val objective: LinkedObjective? = null,
    val pull: CodePull? = null,
)

@Serializable
data class ChecksList(val items: List<TrackedChecks> = emptyList())
