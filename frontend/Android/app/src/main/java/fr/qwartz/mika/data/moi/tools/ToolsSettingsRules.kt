package fr.qwartz.mika.data.moi.tools

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.settings.shareWords
import fr.qwartz.mika.data.moi.settings.text
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.net.URI
import java.net.URISyntaxException

/*
 * Les règles pures de Paramètres › Services MCP, portées du client web (`frontend/Web/src/screens/outils/words.ts` et
 * `settings.ts`) : l'état d'un service et de ses outils (ADR 0129), les choix qui partent, ce qu'un service réglé envoie
 * et les en-têtes à redonner (ADR 0236), son nom et son adresse, ses lignes d'accès, ce qu'on te partage. Les mots du
 * serveur sont ceux de `app/domains/tools/api.py`. Tout se teste sur la JVM.
 */

// ── Les services MCP (ADR 0192) ─────────────────────────────────────────

fun stateWords(state: String): Pair<Tone, String> = when (state) {
    "connecte" -> Tone.OK to "connecté"
    "jamais" -> Tone.NEUTRAL to "jamais joint"
    "erreur" -> Tone.DANGER to "erreur"
    "panne" -> Tone.DANGER to "en panne"
    "incomplet" -> Tone.WARN to "incomplet"
    "inactif" -> Tone.NEUTRAL to "inactif"
    else -> Tone.NEUTRAL to state
}

/** Un état qui dit une panne : son détail se montre. */
fun serviceTrouble(state: String): Boolean = state == "erreur" || state == "panne" || state == "incomplet"

/** Ses outils servis (il lit ou il agit), sur combien, et combien attendent qu'on les regarde (jamais choisis, changés). */
data class Served(val served: Int, val total: Int, val review: Int)

fun servedOf(tools: List<ServiceTool>): Served = Served(
    served = tools.count { it.choice == ToolChoices.READ || it.choice == ToolChoices.ACT },
    total = tools.size,
    review = tools.count { it.choice.isEmpty() || it.waiting },
)

val CHOICES: List<Pair<String, String>> = listOf(
    ToolChoices.OFF to "Coupé",
    ToolChoices.READ to "Il lit",
    ToolChoices.ACT to "Il agit",
)

fun choiceWords(choice: String): String = CHOICES.firstOrNull { it.first == choice }?.second ?: choice

/** L'état d'un outil : nouveau, changé, coupé, servi. */
fun toolState(t: ServiceTool): Pair<Tone, String> = when {
    t.new -> Tone.INFO to "nouveau"
    t.changed -> Tone.WARN to "changé"
    t.choice == ToolChoices.OFF -> Tone.NEUTRAL to "coupé"
    else -> Tone.OK to "servi"
}

/** Le choix qu'un outil montre : aucun s'il attend (nouveau, changé) — le choisir, même comme avant, le décide. */
fun shownChoice(t: ServiceTool): String = if (t.waiting) "" else t.choice

/** Les choix d'outils qui partent : ceux qui ne sont plus ceux que l'outil montrait. */
fun toolChoiceChanges(tools: List<ServiceTool>, picked: Map<String, String>): Map<String, String> =
    tools.mapNotNull { t ->
        val p = picked[t.remote] ?: return@mapNotNull null
        if (p in ToolChoices.ALL && p != shownChoice(t)) t.remote to p else null
    }.toMap()

/**
 * Ce qui part d'un service réglé : ce qui a changé ; des en-têtes seulement s'ils sont tapés (vides : gardés) ;
 * [clearHeaders] : les retirer (ADR 0236), sauf si d'autres sont tapés à leur place.
 */
fun serviceChanges(
    before: Service,
    purpose: String,
    whenToUse: String,
    url: String,
    enabled: Boolean,
    headers: String,
    clearHeaders: Boolean = false,
): JsonObject {
    val out = linkedMapOf<String, JsonElement>()
    if (purpose != before.purpose) out["purpose"] = JsonPrimitive(purpose)
    if (whenToUse != before.whenToUse) out["when_to_use"] = JsonPrimitive(whenToUse)
    if (url.trim() != before.url) out["url"] = JsonPrimitive(url.trim())
    if (enabled != before.enabled) out["enabled"] = JsonPrimitive(enabled)
    if (headers.isNotBlank()) out["secret_headers"] = JsonPrimitive(headers)
    else if (clearHeaders && before.headers) out["clear_headers"] = JsonPrimitive(true)
    return JsonObject(out)
}

/** Où une adresse mène : son schéma, son hôte, son port (celui du schéma s'il n'en dit pas). Illisible : elle-même. */
fun urlOrigin(url: String): String = try {
    val u = URI(url.trim())
    val scheme = u.scheme?.lowercase().orEmpty()
    val host = (u.host ?: u.rawAuthority?.substringAfterLast('@')?.substringBefore(':')).orEmpty().lowercase()
    val port = if (u.port >= 0) u.port else DEFAULT_PORTS[scheme] ?: -1
    "$scheme://$host:$port"
} catch (_: URISyntaxException) {
    url.trim().lowercase()
}

private val DEFAULT_PORTS = mapOf("https" to 443, "http" to 80)

/** Ce que dit le champ des en-têtes quand l'adresse mène ailleurs (les mots du serveur, `app/domains/tools/api.py`). */
const val HEADERS_TO_RETYPE = "à redonner : l'adresse a changé (ou à retirer)"

/**
 * Les en-têtes gardés d'un service à redonner avant d'envoyer [changes] (ADR 0236) : son adresse mène ailleurs — un
 * autre hôte, schéma ou port — et ni de nouveaux en-têtes ni leur retrait ne partent ; le serveur refuserait (400). Un
 * autre chemin sur le même serveur, ou un service sans en-têtes gardés, ne redemande rien.
 */
fun headersToRetype(before: Service, changes: JsonObject): Map<String, String> {
    if (!before.headers || "url" !in changes || "secret_headers" in changes || "clear_headers" in changes) return emptyMap()
    return if (urlOrigin(changes.text("url").orEmpty()) == urlOrigin(before.url)) emptyMap() else mapOf("secret_headers" to HEADERS_TO_RETYPE)
}

/** Les bornes de l'API pour brancher un service (en caractères) : au-delà, elle refuse. */
object McpLimits {
    const val NAME = 24
    const val PURPOSE = 1024
    const val URL = 500
    const val HEADERS = 8000
}

private val SERVICE_NAME = Regex("^[a-z][a-z0-9_]{0,23}$")

/** Le nom d'un service : il entre dans le nom de ses outils (`mcp_<nom>_<outil>`). */
fun serviceNameProblem(name: String): String = when {
    name.isEmpty() -> "Un nom court."
    SERVICE_NAME.matches(name) -> ""
    else -> "Des minuscules, chiffres et _, en commençant par une lettre (24 au plus)."
}

fun urlProblem(url: String): String = when {
    url.isBlank() -> "Son adresse."
    Regex("""^https://\S+$""", RegexOption.IGNORE_CASE).matches(url.trim()) -> ""
    else -> "Une adresse https://… (l'adresse MCP « streamable HTTP » du service)."
}

/** Qui une ligne désigne : « toi » pour la tienne — l'API le dit (`mine`), jamais un nom comparé. */
fun whoWords(a: AccessLine): String = if (a.mine) "toi" else a.who.ifBlank { "tout le monde" }

/** Avec qui il est partagé : ses lignes qui ne sont pas la tienne. */
fun sharedWith(s: Service): String = s.access.filter { it.who.isNotBlank() && !it.mine }.joinToString(", ") { it.who }

/** La ligne par défaut d'un service : fermée (personne d'autre), ou ce qu'elle ouvre. */
fun defaultWords(d: AccessLine?): String =
    if (d == null || (d.read == "non" && d.act == "non")) "fermé : personne d'autre"
    else "il lit : ${d.readWords} · il agit : ${d.actWords} · ${d.keepWords}"

/** Ce que son niveau lui ouvre d'un service qu'on lui partage, en une phrase. */
fun receivedSentence(r: ReceivedService): String {
    val owner = r.ownerName.ifBlank { "Son propriétaire" }
    val what = if (r.level == Levels.USE) {
        "Mika s'en sert pour toi : ses outils qui lisent, et ceux qui agissent."
    } else {
        "Mika s'en sert pour toi, seulement ses outils qui lisent."
    }
    return "$owner te l'a ouvert : ${shareWords(r.level).lowercase()}. $what Seul son propriétaire le règle."
}

/** Pour toi, ce qu'elle fait d'un outil servi d'un service partagé : ce que dit ta ligne. */
fun forYou(r: ReceivedService, choice: String): String =
    (if (choice == ToolChoices.ACT) r.line.actWords else r.line.readWords).ifBlank { "non" }

// ── Ses formulaires ─────────────────────────────────────────────────────

val SERVICE_LABELS: Map<String, String> = mapOf(
    "name" to "Son nom", "purpose" to "À quoi il lui sert", "when_to_use" to "Quand y penser", "url" to "Adresse",
    "headers" to "En-têtes secrets", "secret_headers" to "En-têtes secrets", "enabled" to "Actif",
)
