package fr.qwartz.mika.data.moi.projects

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

/*
 * Les formes des projets dans l'API par personne (`backendv2/docs/protocole-moi.md` § 11 ; ADR 0282, 0290, 0293) : ses
 * projets, ce qui l'y attend (« À faire »), la fiche d'un projet, son registre (tickets), le diagramme de ses
 * objectifs. Le modèle est le client web (`frontendv2/src/api/projects.ts`).
 *
 * Ce que le serveur calcule et que l'app ne refait jamais : l'ordre d'« À faire », `mine` et `can` de chaque attente,
 * son geste (`gesture`), `rights` de la fiche, `can` d'un objet, `ticket_born`, `veiled`, `hand` / `yours`, tous les
 * `…_label`, la carte d'un projet (`card`), son prochain passage (`next`), le parcours d'un ticket (`journey`), ce que
 * ses formulaires proposent (`forms`). Un texte venu d'ailleurs porte `outside` (ou est un [OutsideText]). Chaque champ
 * a son défaut : `MikaJson` ignore ce qu'il ne connaît pas, un champ absent ou `null` ne casse rien. Les instants sont
 * en millisecondes (0 : jamais).
 *
 * Les lots suivants (Code, Documentation, Activité, Dépendances, Listes, Modifier le projet) ajoutent leurs formes à
 * côté, dans ce paquet : `Links` et `Repo` ne portent ici que ce que la Vue d'ensemble montre.
 */

/** Un texte venu d'ailleurs (un commentaire de l'hôte, la fin d'un journal, la sortie d'une commande) : cité, jamais lu. */
@Serializable
data class OutsideText(val text: String = "", val outside: Boolean = true)

/** Ce qu'elle peut faire, la garde de la route dite d'avance, et sinon pourquoi (en mots à afficher tels quels). */
@Serializable
data class Allowed(val can: Boolean = false, val why: String = "")

/** Un code et ses mots (un statut, une sorte, une priorité). */
@Serializable
data class Coded(val code: String = "", val label: String = "")

// ── À faire ─────────────────────────────────────────────────────────────

/**
 * Le geste qui règle une attente. [where] : `ici` (`POST /api/moi/projets/<projet>/<route>` avec [args], à compléter),
 * `console` (rien ici ne le fait), `hote` (chez l'hôte du dépôt). [url] : la page d'une pull request chez l'hôte,
 * composée par le serveur (vide : aucune).
 */
@Serializable
data class Gesture(
    val route: String = "",
    val args: JsonObject = JsonObject(emptyMap()),
    val label: String = "",
    val where: String = "",
    val url: String = "",
)

/** Une attente : ce qui attend quelqu'un dans un projet, et le geste qui la règle. */
@Serializable
data class Waiting(
    val project: Int = 0,
    @SerialName("project_title") val projectTitle: String = "",
    /** `approval`, `plan`, `need`, `stalled`, `blocked`, `ticket`, `checkpoint`, `review`, `item`. */
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    /** La capacité d'un accord, ce qu'un ticket attend (`accept`, `question`, `validation`, `merge`…), une liste. */
    val what: String = "",
    val about: String = "",
    val since: Long = 0,
    /** C'est elle qu'on attend. */
    val mine: Boolean = false,
    /** Elle peut le faire ici : la garde de la route, dite d'avance. */
    val can: Boolean = false,
    /** Pourquoi elle ne le peut pas, en mots (vide quand [can]) : le refus même que la route rendrait. */
    val why: String = "",
    @SerialName("waits_for") val waitsFor: String = "",
    val objective: Int = 0,
    val number: Int = 0,
    val key: String = "",
    /** Un élément qu'elle ne peut pas lire (ni titre ni clé). */
    val veiled: String = "",
    val outside: Boolean = false,
    val gesture: Gesture = Gesture(),
)

/** Ce qu'un lien donne : le voir, son détail, ses fichiers, sa documentation ; et comment ses demandes y entrent, en mots. */
@Serializable
data class Gives(
    val see: Boolean = false,
    val detail: Boolean = false,
    val files: Boolean = false,
    val docs: Boolean = false,
    val ask: String = "",
    @SerialName("ask_label") val askLabel: String = "",
)

/**
 * Une demande entre deux projets : du projet (`from` : `project`), ou un ticket qu'elle a ouvert elle-même chez le projet
 * lié (`you`). [title] est le titre du ticket — vide et [veiled] si elle ne le lit pas là-bas.
 */
@Serializable
data class Demand(
    /** L'autre projet (`null` : elle ne le voit pas). */
    val project: Int? = null,
    val title: String = "",
    val visible: Boolean = false,
    /** `sent`, `received`. */
    val direction: String = "",
    val from: String = "",
    /** 0 si elle ne voit pas le projet où vit le ticket. */
    val number: Int = 0,
    val veiled: Boolean = false,
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    val step: String = "",
    @SerialName("step_label") val stepLabel: String = "",
    val at: Long = 0,
    @SerialName("closed_at") val closedAt: Long = 0,
)

/** « Lui demander quelque chose » : ouvrir un ticket chez un projet lu (`POST /projets/<project>/<route>`). */
@Serializable
data class AskHere(
    val can: Boolean = false,
    val why: String = "",
    /** `open`, `proposed`, ou vide. */
    val born: String = "",
    val project: Int? = null,
    val route: String = "",
)

/**
 * Un projet lié : son numéro et son titre seulement si elle le voit elle-même. Sur une carte de la liste, rien d'autre ;
 * dans les dépendances d'une fiche (`links.reads`, `readers`, `candidates`), ce que le lien donne ([gives]), depuis quand
 * ([since]), le mot de son propriétaire ([why]), et pour un projet lu : s'il est suspendu, si ses demandes y entrent
 * directement ([direct]), le commit que montre la vue de son atelier, les demandes entre les deux, et si elle peut lui
 * demander quelque chose ([askHere]).
 */
@Serializable
data class Linked(
    val project: Int? = null,
    val title: String = "",
    val visible: Boolean = false,
    val suspended: Boolean = false,
    val direct: Boolean = false,
    val gives: Gives = Gives(),
    val since: Long = 0,
    val why: String = "",
    val commit: CommitBrief? = null,
    val asks: List<Demand> = emptyList(),
    @SerialName("ask_here") val askHere: AskHere? = null,
)

/** Un segment de la barre d'une carte : un objectif ponctuel, et où il en est (`done`, `doing`, `todo`, `blocked`). */
@Serializable
data class ProgressState(val id: Int = 0, val state: String = "", @SerialName("state_label") val stateLabel: String = "")

@Serializable
data class CardObjectives(
    val total: Int = 0,
    val done: Int = 0,
    val doing: Int = 0,
    val todo: Int = 0,
    val blocked: Int = 0,
    val states: List<ProgressState> = emptyList(),
)

/** La carte d'un projet (ADR 0293) : la progression de ses objectifs, ses compteurs, ses dépendances. */
@Serializable
data class ProjectCard(
    val objectives: CardObjectives = CardObjectives(),
    @SerialName("pulls_open") val pullsOpen: Int = 0,
    @SerialName("tickets_open") val ticketsOpen: Int = 0,
    val reads: List<Linked> = emptyList(),
    val readers: List<Linked> = emptyList(),
    /** Par qui il est mené : son nom à elle. */
    @SerialName("led_by") val ledBy: String = "",
    @SerialName("last_activity") val lastActivity: Long = 0,
)

/** La ligne d'un projet ; [description] seulement sur sa fiche, [card] seulement dans la liste (et avec le détail). */
@Serializable
data class ProjectHead(
    val id: Int = 0,
    val title: String = "",
    /** `active`, `paused`. */
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    val mine: Boolean = false,
    /** Un projet à Mika. */
    val hers: Boolean = false,
    @SerialName("owner_name") val ownerName: String = "",
    val steer: String = "",
    @SerialName("steer_label") val steerLabel: String = "",
    val detail: Boolean = false,
    val where: String = "",
    @SerialName("last_run") val lastRun: Long = 0,
    /** Vide sans plan, `to_frame`, `proposed`, `planned`. */
    val plan: String = "",
    @SerialName("plan_label") val planLabel: String = "",
    val waiting: Int = 0,
    val card: ProjectCard? = null,
    val description: String = "",
)

/** `GET /api/moi/projets` : ses projets, la première page d'« À faire », et si elle peut en confier un. */
@Serializable
data class Overview(
    val projects: List<ProjectHead> = emptyList(),
    val todo: List<Waiting> = emptyList(),
    @SerialName("todo_total") val todoTotal: Int = 0,
    val create: Allowed = Allowed(),
)

@Serializable
data class TodoPage(val total: Int = 0, val page: Int = 1, val size: Int = 0, val items: List<Waiting> = emptyList())

/** Un ticket en une ligne (sur un objectif, un accord) : son titre est vide s'il ne se lit pas. */
@Serializable
data class TicketLine(
    val number: Int = 0,
    val handle: String = "",
    val title: String = "",
    val veiled: String = "",
    @SerialName("veiled_label") val veiledLabel: String = "",
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    val step: String = "",
    @SerialName("step_label") val stepLabel: String = "",
    val open: Boolean = false,
    /** Là où il est lié au code (une branche, une pull request, une issue) : à qui la main, et si elle peut le trancher. */
    val hand: String = "",
    @SerialName("hand_label") val handLabel: String = "",
    val yours: Boolean = false,
)

/** Ce qu'un accord concerne : un objectif (0 : aucun), un ticket, une issue et une pull request de l'hôte (0 : aucune). */
@Serializable
data class Concerns(val objective: Int = 0, val ticket: TicketLine? = null, val issue: Int = 0, val pull: Int = 0)

/** Ce qui attend son accord : [text] est exactement ce qui partirait, [digest] le condensé à renvoyer (`seen`). */
@Serializable
data class Approval(
    val id: Int = 0,
    val project: Int = 0,
    @SerialName("project_title") val projectTitle: String = "",
    val capability: String = "",
    val label: String = "",
    val summary: String = "",
    val text: String = "",
    val digest: String = "",
    /** Pourquoi il ne peut pas partir tel quel (vide : il le peut). */
    val blocked: String = "",
    val at: Long = 0,
    val concerns: Concerns = Concerns(),
    /** Où cela part, en mots ; et sa page chez l'hôte, composée par le serveur (vide : aucune). */
    val where: String = "",
    @SerialName("where_url") val whereUrl: String = "",
    @SerialName("asked_by_kind") val askedByKind: String = "",
    @SerialName("asked_by") val askedBy: String = "",
    /** Les mots de la personne dont elle porte la demande (un pilotage demandé) ; vide ailleurs. */
    val why: String = "",
)

@Serializable
data class Approvals(val items: List<Approval> = emptyList())

// ── La fiche ────────────────────────────────────────────────────────────

/** Ce qu'elle peut faire d'un projet par les routes d'ici (§ 11, `rights`) : pas de bouton sans le droit servi. */
@Serializable
data class Rights(
    val steer: String = "",
    @SerialName("steer_label") val steerLabel: String = "",
    val detail: Boolean = false,
    /** En ouvrir un ; [ticketBorn] : `open`, `proposed` (il naîtra proposé), ou vide. */
    val ticket: Boolean = false,
    @SerialName("ticket_born") val ticketBorn: String = "",
    val note: Boolean = false,
    val status: Boolean = false,
    /** Trancher (un ticket, un point d'arrêt). */
    val settle: Boolean = false,
    /** Répondre à son plan. */
    val plan: Boolean = false,
    /** Consigne, lancer, pause, reprise. */
    val pilot: Boolean = false,
    val links: Boolean = false,
    val approve: Boolean = false,
    val files: Boolean = false,
    val merge: Boolean = false,
    /** Changer son cadre : ses réglages, l'archiver. */
    val frame: Boolean = false,
    /** Ses objectifs, ses jalons, ses tickets, ses décisions. */
    val edit: Boolean = false,
    @SerialName("pull_write") val pullWrite: Boolean = false,
    /** Lire son activité. */
    val work: Boolean = false,
)

/** Ce qu'elle peut faire d'un objectif ou d'une mission de la fiche. */
@Serializable
data class ObjectiveCan(
    val modify: Boolean = false,
    val reopen: Boolean = false,
    val done: Boolean = false,
    val drop: Boolean = false,
    /** Lui ajouter un jalon. */
    val milestone: Boolean = false,
    val why: String = "",
)

@Serializable
data class MilestoneCan(val modify: Boolean = false, val drop: Boolean = false, val why: String = "")

/** Ce qui déclenche une mission : sa clé et ses mots. */
@Serializable
data class TriggerRef(val key: String = "", val label: String = "")

/** Une mission : un objectif constant, qui revient à une cadence ou quand quelque chose bouge. */
@Serializable
data class Mission(
    val id: Int = 0,
    val text: String = "",
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    /** 0 : la cadence par défaut du projet. */
    @SerialName("cadence_hours") val cadenceHours: Int = 0,
    @SerialName("cadence_label") val cadenceLabel: String = "",
    val on: List<TriggerRef> = emptyList(),
    @SerialName("only_on_event") val onlyOnEvent: Boolean = false,
    @SerialName("last_run") val lastRun: Long = 0,
    val passes: Int = 0,
    @SerialName("each_pass") val eachPass: String = "",
    val need: String = "",
    val can: ObjectiveCan = ObjectiveCan(),
)

@Serializable
data class Milestone(
    val id: Int = 0,
    val text: String = "",
    /** `prose` (sa parole), `command`, `owner` (un point d'arrêt), `item`. */
    val check: String = "",
    @SerialName("check_label") val checkLabel: String = "",
    /** `open`, `reached`, `dropped`. */
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    /** Un point d'arrêt qui attend. */
    val ready: Boolean = false,
    @SerialName("ready_at") val readyAt: Long = 0,
    @SerialName("reached_at") val reachedAt: Long = 0,
    @SerialName("refused_at") val refusedAt: Long = 0,
    val how: String = "",
    val proof: OutsideText? = null,
    val reason: String = "",
    val commit: String = "",
    /** Elle s'y est mise : une exécution est partie depuis que le jalon d'avant est atteint. */
    val started: Boolean = false,
    @SerialName("item_list") val itemList: String = "",
    val item: String = "",
    @SerialName("item_status") val itemStatus: String = "",
    @SerialName("item_status_label") val itemStatusLabel: String = "",
    /** Sa commande, telle qu'on la taperait — seulement avec le droit sur ses fichiers. */
    val command: String = "",
    val can: MilestoneCan = MilestoneCan(),
)

@Serializable
data class Pull(
    val number: Int = 0,
    val title: String = "",
    val url: String = "",
    /** `open`, `merged`, `closed`. */
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    /** Où elle en est, en une ligne. */
    val words: String = "",
    @SerialName("changes_asked") val changesAsked: Boolean = false,
    val conflicts: Boolean = false,
    val at: Long = 0,
    @SerialName("awaits_accord") val awaitsAccord: Int = 0,
    val said: OutsideText? = null,
)

@Serializable
data class Checks(
    /** `pending`, `passed`, `failed`. */
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    val sha: String = "",
    val at: Long = 0,
    val said: OutsideText? = null,
)

@Serializable
data class Review(
    val ok: Boolean = false,
    val label: String = "",
    val at: Long = 0,
    val text: String = "",
    val refused: Int = 0,
    @SerialName("handed_over") val handedOver: Boolean = false,
    @SerialName("last_refusal") val lastRefusal: String = "",
)

@Serializable
data class Objective(
    val id: Int = 0,
    val text: String = "",
    /** `open`, `blocked`, `done`. */
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    @SerialName("done_when") val doneWhen: String = "",
    val ticket: Int = 0,
    val need: String = "",
    val note: String = "",
    val result: String = "",
    val runs: Int = 0,
    @SerialName("last_run") val lastRun: Long = 0,
    @SerialName("closed_at") val closedAt: Long = 0,
    val branch: String = "",
    val tickets: List<TicketLine> = emptyList(),
    val milestones: List<Milestone> = emptyList(),
    val pull: Pull? = null,
    val checks: Checks? = null,
    val review: Review? = null,
    val can: ObjectiveCan = ObjectiveCan(),
)

@Serializable
data class Plan(
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    val text: String = "",
    val questions: String = "",
    val at: Long = 0,
    val version: Int = 0,
    @SerialName("asked_by") val askedBy: String = "",
)

/** Une étape du parcours et son compte, pour la liste des tickets. */
@Serializable
data class StepCount(val code: String = "", val label: String = "", val count: Int = 0)

/** Une liste du registre : celle des tickets ([tickets]), ou une liste de suivi. */
@Serializable
data class Listing(
    val name: String = "",
    val title: String = "",
    val tickets: Boolean = false,
    val open: List<Coded> = emptyList(),
    val closed: List<Coded> = emptyList(),
    val counts: Map<String, Int> = emptyMap(),
    val total: Int = 0,
    /** Encore ouverts. */
    val living: Int = 0,
    /** Pour la liste des tickets : ses sortes et ses priorités (code et mots), et celles par défaut. */
    val kinds: List<Coded> = emptyList(),
    @SerialName("kind_default") val kindDefault: String = "",
    val priorities: List<Coded> = emptyList(),
    @SerialName("priority_default") val priorityDefault: String = "",
    /** La liste des tickets : ses tickets comptés par étape du parcours (les six). */
    val journey: List<StepCount> = emptyList(),
    /** À qui ses éléments sont d'office (`self`, `owner`), en mots. */
    val actor: String = "",
    @SerialName("actor_label") val actorLabel: String = "",
    /** Une liste de suivi : ce qu'elle peut y faire, et à qui un élément peut être (`self`, `owner`, avec leurs mots). */
    val can: ListCan = ListCan(),
    val actors: List<Coded> = emptyList(),
)

/** Ce qu'elle peut faire dans une liste de suivi : y ajouter un élément, changer à qui il est ; sinon pourquoi. */
@Serializable
data class ListCan(val add: Boolean = false, val assign: Boolean = false, val why: String = "")

/** Un commit en bref ; venu du dépôt distant, il porte [outside]. */
@Serializable
data class CommitBrief(
    val sha: String = "",
    val short: String = "",
    val title: String = "",
    val at: Long = 0,
    val outside: Boolean = false,
    val branch: String = "",
)

/** Les mots de la vue « Dépendances », servis par la fiche. */
@Serializable
data class LinkLabels(val title: String = "", val reads: String = "", val readers: String = "", val asks: String = "")

/**
 * Ses dépendances : ce qu'il lit ([reads]), ce que son plan demande à lire ([planAsks]), qui le lit ([readers]), ses
 * demandes à d'autres projets ([asks]) et celles qu'il a reçues ([received]), si elle peut poser ses liens ([can]), et
 * ceux qu'elle peut lui faire lire ([candidates]).
 */
@Serializable
data class Links(
    val reads: List<Linked> = emptyList(),
    @SerialName("plan_asks") val planAsks: List<Linked> = emptyList(),
    val readers: List<Linked> = emptyList(),
    val asks: List<Demand> = emptyList(),
    val received: List<Demand> = emptyList(),
    val can: Boolean = false,
    val candidates: List<Linked> = emptyList(),
    val labels: LinkLabels = LinkLabels(),
)

/** Son dépôt, tel que la Vue d'ensemble et un objectif le nomment (le lot « Code » lit le reste). */
@Serializable
data class Repo(
    @SerialName("has_remote") val hasRemote: Boolean = false,
    val branch: String = "",
    val flow: String = "",
    @SerialName("flow_label") val flowLabel: String = "",
    @SerialName("last_commit") val lastCommit: String = "",
    val commit: CommitBrief? = null,
)

/** L'objectif que vise un passage. */
@Serializable
data class GoalRef(val id: Int = 0, val text: String = "", val kind: String = "")

/** Son prochain passage (ADR 0293) : le moteur n'estime rien — sans date, [at] vaut 0. */
@Serializable
data class NextPass(
    val at: Long = 0,
    /** `due`, `running`, `paused`, `on_demand`, `idle`. */
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
    val sort: String = "",
    @SerialName("sort_label") val sortLabel: String = "",
    val objective: GoalRef? = null,
)

/** Son rythme en mots : son agenda, sa plage, les deux en une phrase. */
@Serializable
data class Rhythm(val schedule: String = "", val window: String = "", val summary: String = "")

/** Une consigne en attente : elle la lira à sa prochaine exécution. */
@Serializable
data class Instruction(
    val seq: Long = 0,
    val at: Long = 0,
    val text: String = "",
    /** D'un niveau qu'elle n'entend pas : le texte n'est pas servi. */
    val veiled: Boolean = false,
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
)

/** Ce qui peut déclencher une mission : sa clé s'envoie telle quelle dans `on`. */
@Serializable
data class Trigger(
    val key: String = "",
    val label: String = "",
    val sort: String = "",
    @SerialName("sort_label") val sortLabel: String = "",
)

/** Ce qu'il faut saisir pour une façon de vérifier un jalon. */
@Serializable
data class CheckField(val name: String = "", val label: String = "", val help: String = "", val required: Boolean = false)

/** Une façon de vérifier un jalon, avec ses mots et ce qu'il faut saisir pour elle. */
@Serializable
data class CheckKind(
    val code: String = "",
    val label: String = "",
    val help: String = "",
    val fields: List<CheckField> = emptyList(),
)

/** De quoi remplir les formulaires d'un objectif et d'un jalon. */
@Serializable
data class Forms(
    val can: Boolean = false,
    val why: String = "",
    val triggers: List<Trigger> = emptyList(),
    @SerialName("triggers_max") val triggersMax: Int = 0,
    val checks: List<CheckKind> = emptyList(),
)

/** La fiche. Qui ne fait que voir le projet reçoit `project`, `rights` et `todo`, rien d'autre. */
@Serializable
data class Sheet(
    val project: ProjectHead = ProjectHead(),
    val rights: Rights = Rights(),
    val todo: List<Waiting> = emptyList(),
    val missions: List<Mission> = emptyList(),
    val objectives: List<Objective> = emptyList(),
    val plan: Plan? = null,
    val lists: List<Listing> = emptyList(),
    val links: Links? = null,
    val repo: Repo? = null,
    val next: NextPass? = null,
    val rhythm: Rhythm? = null,
    val instructions: List<Instruction> = emptyList(),
    val forms: Forms = Forms(),
)

// ── Le registre : un ticket ─────────────────────────────────────────────

/** Une ligne d'une liste : un ticket, ou un élément d'une liste de suivi. */
@Serializable
data class Entry(
    val list: String = "",
    /** `#n` pour un ticket, sa clé sinon. */
    val handle: String = "",
    val number: Int = 0,
    val key: String = "",
    val title: String = "",
    /** Pourquoi ses textes ne se lisent pas (`proposed`, `level`) ; vide : ils se lisent. */
    val veiled: String = "",
    @SerialName("veiled_label") val veiledLabel: String = "",
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    val open: Boolean = false,
    val hand: String = "",
    @SerialName("hand_label") val handLabel: String = "",
    /** À elle, et elle peut trancher. */
    val yours: Boolean = false,
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    val priority: String = "",
    @SerialName("priority_label") val priorityLabel: String = "",
    val actor: String = "",
    @SerialName("actor_label") val actorLabel: String = "",
    /** `self` (elle), `you`, `person`, `project`, `host`. */
    @SerialName("author_kind") val authorKind: String = "",
    /** Qui l'a ouvert, en mots à afficher (un nom seulement si elle a le droit de le savoir). */
    val author: String = "",
    val outside: Boolean = false,
    val objective: Int = 0,
    val notes: Int = 0,
    val at: Long = 0,
    @SerialName("updated_at") val updatedAt: Long = 0,
    /** Le numéro de son plan (0 : aucun). */
    val plan: Int = 0,
    val issue: Int = 0,
    val pull: Int = 0,
    /** Son étape du parcours, parmi les six (vide : écarté, ou pas un ticket). */
    val step: String = "",
    @SerialName("step_label") val stepLabel: String = "",
    @SerialName("issue_state") val issueState: String = "",
    @SerialName("issue_state_label") val issueStateLabel: String = "",
)

@Serializable
data class EntryPage(
    val list: String = "",
    val total: Int = 0,
    val page: Int = 1,
    val size: Int = 0,
    val items: List<Entry> = emptyList(),
)

/** Une étape du parcours d'un ticket : `done` (passée), `current`, `todo`, `skipped`. */
@Serializable
data class JourneyStep(
    val code: String = "",
    val label: String = "",
    val state: String = "",
    @SerialName("state_label") val stateLabel: String = "",
)

/** Le parcours d'un ticket en six étapes (ADR 0293) ; l'étape fine est la précision de l'étape en cours. */
@Serializable
data class Journey(
    val steps: List<JourneyStep> = emptyList(),
    val current: String = "",
    @SerialName("current_label") val currentLabel: String = "",
    val fine: String = "",
    @SerialName("fine_label") val fineLabel: String = "",
    @SerialName("through_pull") val throughPull: Boolean = true,
    val skips: List<String> = emptyList(),
    @SerialName("skips_label") val skipsLabel: String = "",
    /** Vide, `treated`, `dismissed`. */
    val ended: String = "",
    @SerialName("ended_label") val endedLabel: String = "",
)

/** L'objectif qui tient un ticket. */
@Serializable
data class LinkedObjective(
    val id: Int = 0,
    val text: String = "",
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    /** `once`, `constant` (une mission) — servi là où il est lié au code. */
    val kind: String = "",
)

/** Ce qui est lié à un ticket : l'objectif qui le tient, sa pull request et ses vérifications (comme sur la fiche). */
@Serializable
data class EntryLinked(val objective: LinkedObjective? = null, val pull: Pull? = null, val checks: Checks? = null)

/** Une note du fil : sa sorte (`note`, `change`, `question`, `plan`), qui l'a écrite, et si elle vient d'ailleurs. */
@Serializable
data class ThreadNote(
    val seq: Long = 0,
    val at: Long = 0,
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    val text: String = "",
    val outside: Boolean = false,
)

/** Les gestes du moment sur un élément : ceux que le serveur ouvre, rien d'autre. */
@Serializable
data class EntryCan(
    val note: Boolean = false,
    val status: Boolean = false,
    val assign: Boolean = false,
    val accept: Boolean = false,
    val dismiss: Boolean = false,
    @SerialName("dismiss_needs_reason") val dismissNeedsReason: Boolean = false,
    val validate: Boolean = false,
    val refuse: Boolean = false,
    val modify: Boolean = false,
    /** Le fermer comme traité. */
    val close: Boolean = false,
    val reopen: Boolean = false,
)

/** Ce qu'un élément dit de plus que sa ligne (`GET …/element`). */
@Serializable
data class EntryMore(
    val body: String = "",
    val link: String = "",
    val thread: List<ThreadNote> = emptyList(),
    /** Le plan à lire avant de le valider. */
    @SerialName("plan_text") val planText: String = "",
    val small: Boolean = false,
    val statuses: List<Coded> = emptyList(),
    /** Pour un ticket (sinon `null`). */
    val journey: Journey? = null,
    val linked: EntryLinked = EntryLinked(),
    val can: EntryCan = EntryCan(),
)

/** Un élément : sa ligne ([line], les mêmes champs que dans la liste) et son détail ([more]). */
data class EntryDetail(val line: Entry, val more: EntryMore)

/** Un passage de l'histoire d'un ticket : l'étape où il entre, celle qu'il quitte, qui l'y a fait passer. */
@Serializable
data class Passage(
    val seq: Long = 0,
    val at: Long = 0,
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    /** Vide : sa naissance. */
    val was: String = "",
    @SerialName("was_label") val wasLabel: String = "",
    val step: String = "",
    @SerialName("step_label") val stepLabel: String = "",
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    val outside: Boolean = false,
)

@Serializable
data class EntryHistory(val item: String = "", val cut: Boolean = false, val items: List<Passage> = emptyList())

// ── Son activité (ce que les vues de ce lot en lisent) ──────────────────

/** Une ligne du fil d'activité : une exécution, un commit, ce qui arrive à une pull request, à un ticket, un geste. */
@Serializable
data class Happening(
    val seq: Long = 0,
    val at: Long = 0,
    /** `run`, `commit`, `pull`, `ticket`, `gesture`. */
    val kind: String = "",
    @SerialName("kind_label") val kindLabel: String = "",
    val what: String = "",
    val title: String = "",
    val sub: String = "",
    val objective: Int = 0,
    val ticket: Int = 0,
    val pull: Int = 0,
    val sha: String = "",
    val verdict: String = "",
    @SerialName("verdict_label") val verdictLabel: String = "",
    /** L'exécution à ouvrir. */
    val run: String = "",
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    val outside: Boolean = false,
    /** Un texte d'un niveau qu'elle n'entend pas ici (ADR 0292). */
    val veiled: Boolean = false,
)

@Serializable
data class ActivityPage(
    val kinds: List<Coded> = emptyList(),
    val size: Int = 0,
    /** Le curseur à renvoyer dans `before` (0 : il n'y a plus rien). */
    val next: Long = 0,
    val items: List<Happening> = emptyList(),
)

// ── Le diagramme ────────────────────────────────────────────────────────

/** Un jalon du diagramme : de vraies dates seulement (0 : pas encore arrivé). */
@Serializable
data class DiagramMilestone(
    val id: Int = 0,
    val text: String = "",
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    val check: String = "",
    @SerialName("check_label") val checkLabel: String = "",
    val ready: Boolean = false,
    @SerialName("added_at") val addedAt: Long = 0,
    @SerialName("started_at") val startedAt: Long = 0,
    @SerialName("ready_at") val readyAt: Long = 0,
    @SerialName("reached_at") val reachedAt: Long = 0,
    val runs: Int = 0,
)

@Serializable
data class DiagramObjective(
    val id: Int = 0,
    val text: String = "",
    /** `once`, `constant` (une mission). */
    val kind: String = "",
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    /** L'objectif dont il dépend (0 : aucun). */
    val after: Int = 0,
    val rank: Int = 0,
    val ticket: Int = 0,
    @SerialName("added_at") val addedAt: Long = 0,
    @SerialName("started_at") val startedAt: Long = 0,
    @SerialName("last_run") val lastRun: Long = 0,
    @SerialName("closed_at") val closedAt: Long = 0,
    val runs: Int = 0,
    val reached: Int = 0,
    @SerialName("milestones_total") val milestonesTotal: Int = 0,
    /** Les passages d'une mission. */
    val passes: List<Long> = emptyList(),
    val milestones: List<DiagramMilestone> = emptyList(),
)

@Serializable
data class Diagram(
    val now: Long = 0,
    val from: Long = 0,
    val cut: Boolean = false,
    val objectives: List<DiagramObjective> = emptyList(),
)

// ── Gérer : un champ servi, un geste fait ───────────────────────────────

/**
 * Un champ d'une action de la console, décrit par elle : l'app n'écrit aucun libellé. [kind] : `text`, `textarea`,
 * `select`, `bool`, `int`… ; [value] : sa valeur actuelle, en texte (un booléen : `true` / `false`).
 */
@Serializable
data class Field(
    val name: String = "",
    val label: String = "",
    val help: String = "",
    val kind: String = "text",
    val required: Boolean = false,
    val choices: List<Coded> = emptyList(),
    @Serializable(with = LooseText::class) val value: String = "",
    /** Les valeurs d'un autre champ qui le rendent utile (vide : toujours). */
    val only: List<OnlyWhen> = emptyList(),
)

/** Un champ ne sert que pour certaines valeurs d'un autre. */
@Serializable
data class OnlyWhen(val field: String = "", val values: List<@Serializable(with = LooseText::class) String> = emptyList())

/** De quoi remplir « Nouveau projet » (`GET …/projets/nouveau`). */
@Serializable
data class NewProject(val can: Boolean = false, val why: String = "", val fields: List<Field> = emptyList())

/**
 * Ce que rend un geste : son message, et selon lui `number` et `proposed` (un ticket ouvert), `status` (un accord
 * décidé), `project` (un projet confié), `objective` (un objectif ajouté), `list` et `key` (un élément ajouté).
 */
@Serializable
data class GestureDone(
    val ok: Boolean = false,
    val message: String = "",
    val deduped: Boolean = false,
    val number: Int = 0,
    val proposed: Boolean = false,
    val status: String = "",
    val project: Int = 0,
    val objective: Int = 0,
    /** Un élément ajouté à une liste : sa liste, sa clé. */
    val list: String = "",
    val key: String = "",
)
