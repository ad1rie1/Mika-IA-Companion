package fr.qwartz.mika.data.moi.tools

import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.settings.Replies
import fr.qwartz.mika.data.moi.settings.SendRules
import fr.qwartz.mika.data.moi.settings.shareWords
import fr.qwartz.mika.data.net.ServerBase
import okhttp3.HttpUrl

/*
 * Les règles pures d'Outils, portées du client web (`frontendv2/src/screens/outils/matrix.ts`) sans les réinventer :
 * les mots d'une case et de ce qu'elle garde, le canal dont la colonne se lit sur un téléphone (ADR 0209 : l'app
 * Android d'abord) et ses moments, le nom d'un outil pour toi (ADR 0208), ses ressources et leurs groupes, le résumé
 * d'une ressource pour le canal choisi, ce qui décide d'une case, ce qu'une opératrice voit de plus, les lignes de
 * « Services ». Rien n'y est recalculé : une case dit la décision du moteur. Tout se teste sur la JVM.
 */

// ── Les mots d'une case ─────────────────────────────────────────────────

/** Ce que dit une case : son ton, son mot (une pastille) et ce qu'il veut dire en entier ; [unused] : pas de case. */
data class LevelWords(val tone: Tone, val word: String, val long: String, val unused: Boolean = false)

private val LEVELS = mapOf(
    RightsLevel.ALONE to LevelWords(Tone.OK, "Seule", "Elle s'en sert seule, sans te demander."),
    RightsLevel.CARD to LevelWords(Tone.WARN, "Demande", "Elle te demande d'abord : une carte dans ton chat."),
    RightsLevel.YOU to LevelWords(Tone.WARN, "Accord", "Elle attend ton accord avant de s'en servir."),
    RightsLevel.NO to LevelWords(Tone.NEUTRAL, "Non", "Elle ne s'en sert pas."),
)

/** Une case absente : l'outil ne sert pas à ce moment. */
val UNUSED = LevelWords(Tone.NEUTRAL, "—", "Il ne sert pas à ce moment-là.", unused = true)

fun levelOf(cell: RightsCell?): LevelWords =
    if (cell == null) UNUSED else LEVELS[cell.level] ?: LevelWords(Tone.NEUTRAL, cell.level, cell.level)

/** Ce qu'elle garde de ce qu'il rend : un savoir, un souvenir, une confidence, rien. */
fun keepWords(keep: String): String = when (keep) {
    Keeps.PUBLIC -> "un savoir"
    Keeps.PERSONAL -> "un souvenir"
    Keeps.PRIVATE -> "une confidence"
    Keeps.NOTHING -> "rien"
    else -> keep
}

// ── Le canal choisi ─────────────────────────────────────────────────────

/** Le canal lu d'abord sur ce téléphone : l'app Android (la maquette ; le web, lui, lit le chat web d'abord). */
const val FIRST_CANAL = RightsKeys.MOBILE

/** Les canaux dans l'ordre de la feuille : l'app Android d'abord, puis ceux du serveur dans son ordre. */
fun canalOrder(canals: List<RightsCanal>): List<RightsCanal> = canals.sortedBy { if (it.key == FIRST_CANAL) 0 else 1 }

/** Le canal lu : celui qu'on a choisi s'il existe encore, sinon l'app Android, sinon le premier. */
fun chosenCanal(canals: List<RightsCanal>, wanted: String): String =
    canals.firstOrNull { it.key == wanted }?.key ?: canals.firstOrNull { it.key == FIRST_CANAL }?.key ?: canals.firstOrNull()?.key ?: wanted

/** Un mot de plus sous certains canaux, comme le web et la maquette. */
fun canalSub(key: String): String = when (key) {
    "web" -> "en privé"
    "salon" -> "à plusieurs"
    RightsKeys.ALONE -> "au travail"
    else -> ""
}

/** « Chat web · en privé », « App Android ». */
fun canalName(canal: RightsCanal): String = listOf(canal.label.ifBlank { canal.key }, canalSub(canal.key)).filter { it.isNotBlank() }.joinToString(" · ")

/** Les moments d'un canal : `reply` et `initiative` pour un canal qui parle, `work` pour elle seule. */
fun momentsOf(canal: String, moments: List<RightsMoment>): List<RightsMoment> =
    if (canal == RightsKeys.ALONE) moments.filter { it.key == RightsKeys.WORK } else moments.filter { it.key != RightsKeys.WORK }

fun cellKey(canal: String, moment: String): String = "$canal/$moment"

/** Une pastille d'un outil : son moment et sa case (`null` : il ne sert pas à ce moment). */
data class Pill(val moment: RightsMoment, val cell: RightsCell?)

/** Ses pastilles pour le canal choisi : quand tu lui parles et d'elle-même ; pour elle seule, quand elle travaille. */
fun pillsOf(tool: RightsTool, canal: String, moments: List<RightsMoment>): List<Pill> =
    momentsOf(canal, moments).map { Pill(it, tool.cells[cellKey(canal, it.key)]) }

// ── Un outil ────────────────────────────────────────────────────────────

private val FIRST_CLAUSE = Regex("""^(.{6,}?)(?:\s*[:;(]|\.\s|\.$|\s—\s)""")
private val COMMA = Regex(""",\s""")

/**
 * Le repli, pour un outil venu d'ailleurs (un service, une app) qui n'a pas de libellé : la première proposition de sa
 * description, sinon son nom. « Lister les mails d'une boîte ou d'un dossier, du plus récent… » → « Lister les mails
 * d'une boîte ou d'un dossier ».
 */
fun toolLabel(description: String, name: String): String {
    val flat = description.replace(Regex("""\s+"""), " ").trim()
    if (flat.isEmpty()) return name
    var label = (FIRST_CLAUSE.find(flat)?.groupValues?.get(1) ?: flat).trim()
    if (label.length > 56) {
        val comma = COMMA.find(label, 20)?.range?.first
        if (comma != null) label = label.substring(0, comma)
    }
    if (label.length > 72) label = label.substring(0, 71).trimEnd() + "…"
    return label.replaceFirstChar { it.uppercaseChar() }
}

/** Le nom d'un outil pour toi : son libellé (ADR 0208) ; un outil venu d'ailleurs, par sa description. */
fun labelOf(tool: RightsTool): String = tool.label.trim().ifEmpty { toolLabel(tool.description, tool.name) }

/** Ce que « Lui demander » pose dans le champ du chat, à relire avant d'envoyer. */
fun askFor(tool: RightsTool): String = "Tu peux te servir de « ${labelOf(tool)} » pour moi ?"

/** La condition qui le garde (ce que dit une case fermée par elle), s'il en a une. */
fun conditionOf(tool: RightsTool): String =
    tool.cells.values.firstOrNull { it != null && it.reason == Reasons.WHEN && it.why.isNotBlank() }?.why.orEmpty()

/** Ce qu'elle garde de ce qu'il rend, là où elle s'en sert (sans « rien »). */
fun keepsOf(tool: RightsTool): List<String> =
    tool.cells.values.filterNotNull().filter { it.level != RightsLevel.NO && it.keep != Keeps.NOTHING }.map { keepWords(it.keep) }.distinct()

/** Pourquoi une case, tel que le moteur le dit pour toi (sa condition, s'il en a une) ; ce qu'elle en garde. */
data class Why(val why: String, val keep: String)

fun whyOf(cell: RightsCell): Why {
    val said = cell.why.trim()
    val why = if (cell.reason == Reasons.WHEN && said.isNotEmpty()) "sa condition : $said" else said
    val keep = if (cell.level != RightsLevel.NO && cell.keep != Keeps.NOTHING) keepWords(cell.keep) else ""
    return Why(why, keep)
}

/** Un outil dont aucune case ne dit rien : il ne sert à aucun de ces moments (une séance à elle, un réveil…). */
fun idle(tool: RightsTool): Boolean = tool.cells.values.all { it == null }

/** Les outils montrés en lignes ; les autres se replient sous la carte, nommés pour toi. */
fun shownTools(tools: List<RightsTool>): List<RightsTool> = tools.filterNot(::idle)

/** Rien ne s'ouvre pour toi : seulement quand elle travaille, pour elle. */
fun internalOnly(tools: List<RightsTool>): Boolean =
    tools.isNotEmpty() && tools.all { t ->
        t.cells.all { (k, c) -> c == null || c.level == RightsLevel.NO || k.startsWith("${RightsKeys.ALONE}/") }
    }

/** Une case ouverte ailleurs que par le canal choisi : son mot, le canal et le moment, en mots du serveur. */
data class OpenCell(val level: LevelWords, val canal: String, val moment: String)

/** Où elle s'en sert pour toi par les autres canaux (la fiche d'un outil, quand une seule colonne se lit). */
fun openElsewhere(tool: RightsTool, rights: Rights, canal: String): List<OpenCell> =
    canalOrder(rights.canals).filter { it.key != canal }.flatMap { c ->
        momentsOf(c.key, rights.moments).mapNotNull { m ->
            val cell = tool.cells[cellKey(c.key, m.key)]
            if (cell == null || cell.level == RightsLevel.NO) null else OpenCell(levelOf(cell), canalName(c), m.label)
        }
    }

/** Ce qu'elle en fait pour un canal, en un mot : seule si une case l'est, sinon en te demandant, sinon non ; `null` :
 *  aucune case par ce canal. */
fun toolLevelIn(tool: RightsTool, canal: String, moments: List<RightsMoment>): String? {
    val levels = pillsOf(tool, canal, moments).mapNotNull { it.cell?.level }
    return when {
        levels.isEmpty() -> null
        RightsLevel.ALONE in levels -> RightsLevel.ALONE
        levels.any { it == RightsLevel.CARD || it == RightsLevel.YOU } -> RightsLevel.YOU
        else -> RightsLevel.NO
    }
}

/** Le résumé d'une ressource pour le canal choisi (la maquette) : chaque outil une fois — seule, en te demandant, non. */
data class Summary(val alone: Int, val ask: Int, val no: Int) {
    val empty: Boolean get() = alone + ask + no == 0
}

fun summaryOf(tools: List<RightsTool>, canal: String, moments: List<RightsMoment>): Summary {
    val levels = tools.mapNotNull { toolLevelIn(it, canal, moments) }
    return Summary(
        alone = levels.count { it == RightsLevel.ALONE },
        ask = levels.count { it == RightsLevel.YOU },
        no = levels.count { it == RightsLevel.NO },
    )
}

// ── Les ressources ──────────────────────────────────────────────────────

/** La famille d'un compte : sa clé et son nom (ses outils sont les siens). */
data class FamilyRef(val key: String, val title: String)

/**
 * Une ressource de la matrice, prête à montrer : son groupe, son nom (un compte y dit sa sorte : « Courrier · Pro »),
 * ce qu'on en dit dessous, son icône (un nom du jeu de la maquette), ses outils — vides pour un compte, dont les outils
 * sont ceux de sa famille —, la règle d'envoi d'un compte, la page de la console (une opératrice seulement).
 */
data class ToolsResource(
    val key: String,
    val group: String,
    val groupTitle: String,
    val title: String,
    val sub: String,
    val icon: String,
    /** Ce qu'elle seule utilise : aucune case ne s'ouvre ailleurs que quand elle travaille. */
    val aloneOnly: Boolean,
    val tools: List<RightsTool>,
    val rules: SendRules? = null,
    /** `mail` ou `teams` pour un compte. */
    val kind: String = "",
    val family: FamilyRef? = null,
    val href: String = "",
    val description: String = "",
) {
    val account: Boolean get() = group == RightsKeys.ACCOUNTS
}

/** Les icônes des familles, celles du web (`FAMILY_ICONS`), par leur nom dans le jeu de la maquette. */
private val FAMILY_ICONS = mapOf(
    "goals" to "clock", "camera" to "eye", "forge_signals" to "bell", "email" to "mail", "imaging" to "image",
    "shares" to "file", "rss" to "inbox", "identity" to "user", "workshop" to "terminal", "forge" to "code",
    "location" to "pin", "phone" to "phone", "memory" to "book", "attachments" to "clip", "projects" to "folder",
    "social" to "users", "wakeup" to "bolt", "attention" to "sparkle", "self" to "heart", "world" to "map",
    "teams" to "teams",
)

fun familyIcon(key: String): String = FAMILY_ICONS[key.removePrefix("famille:")] ?: "tools"

/** Le nom d'une ressource d'ailleurs, sans sa sorte (`mcp:meteo` → `meteo`). */
fun bare(key: String): String = key.replace(Regex("""^[a-z]+:"""), "")

/** La clé d'un de tes comptes, sans son canal (`courrier:pro` → `pro`) : celle de sa page de Paramètres. */
fun accountKey(res: ToolsResource): String = res.key.substringAfter(':')

/** « partagé avec toi par Adrien (s'en servir) ». */
fun receivedWords(r: ReceivedService): String =
    "partagé avec toi par ${r.ownerName.ifBlank { "quelqu'un" }} (${shareWords(r.level).lowercase()})"

/**
 * Ses ressources dans l'ordre de la matrice. Un compte n'a que ce qui est à lui — son adresse, à qui il est (les tiens
 * seulement : ceux qu'on te partage ne sont pas dans la matrice, leur règle est l'affaire de leur propriétaire), sa
 * règle d'envoi ; ses outils sont ceux de sa famille et ne se recopient pas sous lui (ADR 0209). Un service dit son but
 * et à qui il est, d'après ce que [services] en dit.
 */
fun resourcesOf(rights: Rights, services: Services? = null): List<ToolsResource> {
    val families = rights.groups.filter { it.key == RightsKeys.FAMILIES }.flatMap { it.resources }.associateBy { it.key }
    val own = services?.items.orEmpty().map { it.name }.toSet()
    val received = services?.received.orEmpty().associateBy { it.name }
    val out = mutableListOf<ToolsResource>()
    for (g in rights.groups) {
        for (r in g.resources) {
            when (g.key) {
                RightsKeys.ACCOUNTS -> {
                    val teams = r.kind == "teams"
                    val family = families[r.family]
                    out += ToolsResource(
                        key = r.key, group = g.key, groupTitle = g.title,
                        title = "${if (teams) "Teams" else "Courrier"} · ${r.title}",
                        sub = listOf(r.address, "à toi").filter { it.isNotBlank() }.joinToString(" · "),
                        icon = if (teams) "teams" else "mail", aloneOnly = false, tools = emptyList(), rules = r.rules,
                        kind = if (teams) "teams" else "mail", family = family?.let { FamilyRef(it.key, it.title) },
                    )
                }
                RightsKeys.SERVICES, RightsKeys.APPS -> {
                    val name = bare(r.key)
                    val app = g.key == RightsKeys.APPS
                    val whose = when {
                        !app && name in own -> "à toi"
                        !app && name in received -> receivedWords(received.getValue(name))
                        app -> "une app de la Forge"
                        else -> "un service de Mika"
                    }
                    out += ToolsResource(
                        key = r.key, group = g.key, groupTitle = g.title, title = r.title,
                        sub = listOf(r.description, whose).filter { it.isNotBlank() }.joinToString(" · "),
                        icon = if (app) "code" else if (name == "web") "globe" else "plug", aloneOnly = false,
                        tools = r.tools, href = r.href, description = r.description,
                    )
                }
                else -> {
                    val internal = internalOnly(r.tools)
                    val sub = if (internal) listOf(r.description, "ce qu'elle seule utilise").filter { it.isNotBlank() }.joinToString(" · ") else r.description
                    out += ToolsResource(
                        key = r.key, group = g.key, groupTitle = g.title, title = r.title, sub = sub,
                        icon = familyIcon(r.key), aloneOnly = internal, tools = r.tools, href = r.href, description = r.description,
                    )
                }
            }
        }
    }
    return out
}

/** Un groupe de cartes : ses propres outils, tes comptes, les services, les apps. */
data class ToolsGroup(val key: String, val title: String, val resources: List<ToolsResource>)

private val GROUP_ORDER = listOf(RightsKeys.FAMILIES, RightsKeys.ACCOUNTS, RightsKeys.SERVICES, RightsKeys.APPS)

/** Les groupes dans l'ordre de la matrice (un groupe inconnu après, dans l'ordre du serveur) ; un groupe vide ne se
 *  montre pas. */
fun groupsOf(resources: List<ToolsResource>): List<ToolsGroup> {
    val groups = linkedMapOf<String, MutableList<ToolsResource>>()
    for (r in resources) groups.getOrPut(r.group) { mutableListOf() } += r
    return groups.entries
        .sortedBy { (key, _) -> GROUP_ORDER.indexOf(key).let { if (it < 0) GROUP_ORDER.size else it } }
        .map { (key, items) -> ToolsGroup(key, items.first().groupTitle, items) }
}

/** D'où vient la règle d'envoi d'un compte : la sienne, celle de tout son canal (réglée dans la console), ou sa règle
 *  de départ (jamais réglée). */
enum class RulesOrigin { SET, COMMON, START }

fun rulesOrigin(rules: SendRules): RulesOrigin = when {
    rules.set -> RulesOrigin.SET
    rules.common -> RulesOrigin.COMMON
    else -> RulesOrigin.START
}

/** Le ton de « comment ça part » : seule en vert, ton accord en ambre, un brouillon à toi en indigo. */
fun replyTone(reply: String): Tone = when (reply) {
    Replies.ALONE -> Tone.OK
    Replies.ASK -> Tone.WARN
    Replies.DRAFT -> Tone.INFO
    else -> Tone.NEUTRAL
}

// ── Ce qu'une opératrice voit de plus (ADR 0209) ────────────────────────

/** Une page de la console, telle que le moteur la donne à une opératrice : rien d'autre ne s'ouvre d'ici. */
private val CONSOLE_PAGE = Regex("""^/admin/[\w\-/]*(\?[\w=%.\-&]*)?$""")

fun consoleHref(href: String): String? = href.trim().takeIf { CONSOLE_PAGE.matches(it) }

/** La ligne même d'une case (« ligne 2 — … ») : à une opératrice seulement ; vide sinon. */
fun lineFor(cell: RightsCell?, operator: Boolean): String = if (operator) cell?.line?.trim().orEmpty() else ""

/** La page de la console où se lit le tableau d'une ressource : à une opératrice seulement. */
fun consoleFor(res: ToolsResource, operator: Boolean): String? = if (operator) consoleHref(res.href) else null

/** L'adresse d'une page de la console sur le serveur de la session (son chemin et sa requête, déjà vérifiés). */
fun consoleUrl(base: ServerBase, href: String): HttpUrl? {
    val page = consoleHref(href) ?: return null
    val url = base.http(page.substringBefore('?'))
    val query = page.substringAfter('?', "")
    return if (query.isEmpty()) url else url.newBuilder().encodedQuery(query).build()
}

// ── Les services ────────────────────────────────────────────────────────

/** Une ligne de « Services » : dans la matrice (une case s'ouvre pour toi), à toi, ou qu'on te partage. */
data class ServiceRow(
    val key: String,
    val name: String,
    val resource: ToolsResource? = null,
    val own: Service? = null,
    val received: ReceivedService? = null,
)

/**
 * Les lignes de « Services » : ceux dont elle se sert pour toi (la matrice), ceux que tu as branchés, et ceux qu'on te
 * partage — même quand aucune case ne t'en ouvre encore (jamais joint, en panne, aucun outil servi).
 */
fun serviceRows(resources: List<ToolsResource>, own: List<Service>, received: List<ReceivedService>): List<ServiceRow> {
    val rows = resources.filter { it.group == RightsKeys.SERVICES || it.group == RightsKeys.APPS }.map { r ->
        val name = bare(r.key)
        val service = r.group == RightsKeys.SERVICES
        ServiceRow(
            key = r.key, name = name, resource = r,
            own = if (service) own.firstOrNull { it.name == name } else null,
            received = if (service) received.firstOrNull { it.name == name } else null,
        )
    }.toMutableList()
    for (s in own) if (rows.none { it.own == s }) rows += ServiceRow("mcp:${s.name}", s.name, own = s)
    for (s in received) if (rows.none { it.received == s }) rows += ServiceRow("mcp:${s.name}", s.name, received = s)
    return rows
}

fun serviceTitle(row: ServiceRow): String = row.resource?.title ?: "Service « ${row.name} »"

/** À qui il est : à toi, partagé avec toi (par qui, à quel niveau), une app de la Forge, un service de Mika. */
fun serviceWhose(row: ServiceRow): String = when {
    row.own != null -> "à toi"
    row.received != null -> receivedWords(row.received)
    row.resource?.group == RightsKeys.APPS -> "une app de la Forge"
    else -> "un service de Mika"
}

/** À quoi il lui sert : le but qu'une personne lui a donné, ou celui que le serveur écrit pour toi ; rien pour un
 *  service de l'opératrice (ADR 0209). */
fun servicePurpose(row: ServiceRow): String =
    row.own?.purpose?.takeIf { it.isNotBlank() } ?: row.received?.purpose?.takeIf { it.isNotBlank() } ?: row.resource?.description.orEmpty()

/** Son état : celui de ton service ou de celui qu'on te partage ; sinon, dans la matrice, « ouvert ». */
fun serviceState(row: ServiceRow): Pair<Tone, String> =
    (row.own?.state ?: row.received?.state)?.let { stateWords(it) } ?: (Tone.OK to "ouvert")

/** Ses outils pour toi : ceux qu'une case t'ouvre ; pour un service qui n'en ouvre encore aucun, ceux qu'il sert ;
 *  [review] : les tiens à regarder (jamais choisis, nouveaux, changés). */
data class ServiceTools(val open: Int, val total: Int, val review: Int)

fun serviceTools(row: ServiceRow): ServiceTools? {
    val review = row.own?.let { servedOf(it.tools).review } ?: 0
    val res = row.resource
    return when {
        res != null -> ServiceTools(res.tools.count { t -> t.cells.values.any { it != null && it.level != RightsLevel.NO } }, res.tools.size, review)
        row.own != null -> servedOf(row.own.tools).let { ServiceTools(it.served, it.total, review) }
        row.received != null && row.received.tools.isNotEmpty() -> ServiceTools(0, row.received.tools.size, 0)
        else -> null
    }
}

/** Où mène une ligne : sa page de Paramètres (un des tiens, ou qu'on te partage), ses droits (un service de Mika, une
 *  app), nulle part. */
sealed interface ServiceTarget {
    data class Settings(val name: String) : ServiceTarget
    data class Rights(val key: String) : ServiceTarget
    data object None : ServiceTarget
}

fun serviceTarget(row: ServiceRow): ServiceTarget = when {
    row.own != null || row.received != null -> ServiceTarget.Settings(row.name)
    row.resource != null -> ServiceTarget.Rights(row.key)
    else -> ServiceTarget.None
}

fun serviceIcon(row: ServiceRow): String = when {
    row.resource?.group == RightsKeys.APPS -> "code"
    row.name == "web" -> "globe"
    else -> "plug"
}
