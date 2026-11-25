package fr.qwartz.mika.data.moi.tools

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/*
 * Les formes des services MCP dans l'API par personne (`backendv2/docs/protocole-moi.md` § 8 ; code
 * `app/domains/tools/api.py`) : ce que Paramètres › Services MCP règle, et que les Outils lisent aussi
 * (`ToolsApi.services`). Chaque champ a son défaut : `MikaJson` ignore ce qu'il ne connaît pas, et un champ absent ne
 * casse rien. Un secret n'est jamais rendu : seulement le fait qu'il est gardé.
 */

// ── Ses services MCP (§ 8) ──────────────────────────────────────────────

/** Ce qu'on choisit pour un outil (ADR 0129) : coupé, servi en lecture, servi en action ; vide : jamais choisi. */
object ToolChoices {
    const val OFF = "non"
    const val READ = "lecture"
    const val ACT = "action"
    val ALL = listOf(OFF, READ, ACT)
}

@Serializable
data class ServiceTool(
    val remote: String = "",
    /** Son nom chez Mika (vide : jamais regardé). */
    val name: String = "",
    val description: String = "",
    val choice: String = "",
    val new: Boolean = false,
    val changed: Boolean = false,
) {
    /** Nouveau ou changé : il ne sert pas tant qu'on ne l'a pas choisi. */
    val waiting: Boolean get() = new || changed
}

/** Une ligne d'accès, en codes et en mots ; [mine] : elle ne désigne que toi (ta ligne, pas un partage). */
@Serializable
data class AccessLine(
    val who: String = "",
    @SerialName("when") val whenWords: String = "",
    val mine: Boolean = false,
    val read: String = "",
    val act: String = "",
    val keep: String = "",
    @SerialName("read_words") val readWords: String = "",
    @SerialName("act_words") val actWords: String = "",
    @SerialName("keep_words") val keepWords: String = "",
    val tools: List<String> = emptyList(),
)

/** Un de tes services : distant, à toi ; [headers] : des en-têtes sont gardés (jamais rendus). */
@Serializable
data class Service(
    val name: String = "",
    val purpose: String = "",
    @SerialName("when_to_use") val whenToUse: String = "",
    val enabled: Boolean = true,
    val url: String = "",
    val headers: Boolean = false,
    /** `jamais`, `connecte`, `erreur`, `panne`, `incomplet`, `inactif`. */
    val state: String = "jamais",
    val detail: String = "",
    val tools: List<ServiceTool> = emptyList(),
    val access: List<AccessLine> = emptyList(),
    val default: AccessLine? = null,
)

/** Un outil servi d'un service qu'on te partage. */
@Serializable
data class SharedTool(
    val remote: String = "",
    val name: String = "",
    val description: String = "",
    val choice: String = "",
)

/** Un service qu'une autre personne te partage, en lecture : ni son adresse, ni ses en-têtes, ni le détail d'une panne. */
@Serializable
data class ReceivedService(
    val name: String = "",
    val purpose: String = "",
    val enabled: Boolean = true,
    val state: String = "jamais",
    val tools: List<SharedTool> = emptyList(),
    /** `lire` : ses outils qui lisent ; `servir` : aussi ceux qui agissent. */
    val level: String = "lire",
    val line: AccessLine = AccessLine(),
    @SerialName("owner_name") val ownerName: String = "",
)

@Serializable
data class Services(
    val plugged: Boolean = true,
    val items: List<Service> = emptyList(),
    val received: List<ReceivedService> = emptyList(),
)

/** Ce que dit un essai de service : il répond, ou pas (et pourquoi). */
@Serializable
data class ServiceTest(val ok: Boolean = false, val message: String = "")
