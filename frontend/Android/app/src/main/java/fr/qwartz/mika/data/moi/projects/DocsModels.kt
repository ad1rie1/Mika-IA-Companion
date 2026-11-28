package fr.qwartz.mika.data.moi.projects

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * La documentation d'un projet dans l'API par personne (`backendv2/docs/protocole-moi.md` § 11, « La documentation d'un
 * projet » ; ADR 0289) et ses décisions techniques (« Gérer un projet » ; ADR 0290). Un espace à part de son dépôt : des
 * pages en Markdown rangées en dossiers, leurs versions, des images. Le modèle est le client web
 * (`frontend/Web/src/api/projectDocs.ts`).
 *
 * Ce que le serveur dit et que l'app ne refait pas : `rights.write` et `can.write` (elle peut l'écrire), le titre d'une
 * page, ses dossiers, qui a écrit (`author`, selon la règle des noms ; `via_label`), les bornes (`limits`), ce qu'une
 * décision permet (`can`). Chaque champ a son défaut : un champ absent ou `null` ne casse rien.
 */

/** Une page de l'espace ; avec `…/page`, son texte ([text]) ; avec `…/chercher`, le passage trouvé ([excerpt]). */
@Serializable
data class DocPage(
    val path: String = "",
    val name: String = "",
    val folder: String = "",
    /** Son premier titre de niveau 1, sinon le nom du fichier. */
    val title: String = "",
    val version: Int = 0,
    val at: Long = 0,
    @SerialName("created_at") val createdAt: Long = 0,
    val chars: Int = 0,
    /** Les images qu'elle cite, par leur nom. */
    val images: List<String> = emptyList(),
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    /** `run` (elle, pendant une exécution), `web` (une personne), `mcp` (un outil), `console`. */
    val via: String = "",
    @SerialName("via_label") val viaLabel: String = "",
    val tool: String = "",
    val text: String = "",
    /** Son texte a été oublié. */
    val forgotten: Boolean = false,
    val can: DocCan = DocCan(),
    val excerpt: String = "",
)

@Serializable
data class DocCan(val write: Boolean = false)

@Serializable
data class DocImage(
    val name: String = "",
    /** Ce qu'une page écrit pour la citer : `images/<nom>`. */
    val path: String = "",
    val size: Long = 0,
    val mime: String = "",
    val at: Long = 0,
    /** Les pages qui la citent, par leur chemin. */
    @SerialName("used_by") val usedBy: List<String> = emptyList(),
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    val via: String = "",
    @SerialName("via_label") val viaLabel: String = "",
)

/** Les bornes de l'espace, dites par le serveur (0 : pas dite). */
@Serializable
data class DocLimits(
    @SerialName("page_chars") val pageChars: Int = 0,
    val pages: Int = 0,
    val versions: Int = 0,
    @SerialName("word_chars") val wordChars: Int = 0,
    @SerialName("image_bytes") val imageBytes: Long = 0,
    val images: Int = 0,
    @SerialName("space_bytes") val spaceBytes: Long = 0,
    /** Les sortes d'image que l'espace garde, par leur type MIME (`image/png`…) ; vide : pas dit. */
    @SerialName("image_kinds") val imageKinds: List<String> = emptyList(),
)

@Serializable
data class DocRights(val read: Boolean = false, val write: Boolean = false)

/** `GET …/documentation` : l'espace en entier — ses droits, ses bornes, ses pages à plat, ses dossiers, ses images. */
@Serializable
data class DocSpace(
    val project: Int = 0,
    val rights: DocRights = DocRights(),
    val limits: DocLimits = DocLimits(),
    val pages: List<DocPage> = emptyList(),
    val folders: List<String> = emptyList(),
    val images: List<DocImage> = emptyList(),
    @SerialName("space_used") val spaceUsed: Long = 0,
)

/** Une version gardée d'une page ; avec `…/version`, son texte. */
@Serializable
data class DocVersion(
    val n: Int = 0,
    val at: Long = 0,
    /** Le mot sur ce qui a changé. */
    val word: String = "",
    /** La version reprise ; 0 sinon. */
    val restored: Int = 0,
    val chars: Int = 0,
    val current: Boolean = false,
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    val via: String = "",
    @SerialName("via_label") val viaLabel: String = "",
    val tool: String = "",
    val path: String = "",
    val text: String = "",
    val forgotten: Boolean = false,
)

@Serializable
data class DocHistory(val path: String = "", val version: Int = 0, val kept: Int = 0, val versions: List<DocVersion> = emptyList())

@Serializable
data class DocFound(val q: String = "", val items: List<DocPage> = emptyList())

/** Ce que rend un enregistrement : la version écrite. */
@Serializable
data class PageSaved(val ok: Boolean = false, val message: String = "", val path: String = "", val version: Int = 0, val deduped: Boolean = false)

/** Ce que rend un téléversement : le nom que l'espace a donné à l'image, et ce qu'une page écrit pour la citer. */
@Serializable
data class ImageSaved(val ok: Boolean = false, val message: String = "", val name: String = "", val path: String = "", val deduped: Boolean = false)

// ── Ses décisions techniques ────────────────────────────────────────────

@Serializable
data class DecisionCan(
    val modify: Boolean = false,
    val replace: Boolean = false,
    val withdraw: Boolean = false,
    val restore: Boolean = false,
    val why: String = "",
)

/** Une décision technique ; avec `…/decision`, son contexte, ses options écartées et sa raison. */
@Serializable
data class Decision(
    val number: Int = 0,
    val title: String = "",
    val choice: String = "",
    /** `active` (en vigueur), `withdrawn`, `superseded`. */
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
    @SerialName("author_kind") val authorKind: String = "",
    val author: String = "",
    val at: Long = 0,
    /** Celle qu'elle remplace, celle qui la remplace ; 0 : aucune. */
    val replaces: Int = 0,
    @SerialName("replaced_by") val replacedBy: Int = 0,
    val objective: Int = 0,
    val can: DecisionCan = DecisionCan(),
    val context: String = "",
    /** Les options écartées : un seul texte, une par ligne. */
    val options: String = "",
    val reason: String = "",
)

@Serializable
data class DecisionList(
    val total: Int = 0,
    @SerialName("in_force") val inForce: Int = 0,
    val can: Boolean = false,
    val why: String = "",
    val items: List<Decision> = emptyList(),
)
