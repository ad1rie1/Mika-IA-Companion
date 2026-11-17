package fr.qwartz.mika.data.moi.tools

import fr.qwartz.mika.data.moi.settings.SendRules
import kotlinx.serialization.Serializable

/*
 * Les formes d'Outils dans l'API par personne : la matrice de tes droits (`GET /api/moi/rights`,
 * `backendv2/docs/protocole-moi.md` § 6 ; code `app/me/rights.py`, ADR 0208, 0209, 0219). Chaque case est la décision
 * même du moteur : l'app la montre, elle ne la recalcule jamais. Chaque champ a son défaut : `MikaJson` ignore ce qu'il
 * ne connaît pas, et un champ absent ne casse rien. Ses services (`GET …/mcp/services`, § 8) ont les formes de
 * Paramètres (`settings/SettingsModels.kt` : `Services`, `Service`, `ReceivedService`), lues une seule fois pour les deux.
 */

/** Un canal par où elle te parle (`web`, `salon`, `mobile`, `teams`, `courrier`), ou `seule` : quand elle travaille. */
@Serializable
data class RightsCanal(val key: String = "", val label: String = "")

/** Un moment : `reply` (quand elle te répond), `initiative` (d'elle-même), `work` (seule, quand elle travaille). */
@Serializable
data class RightsMoment(val key: String = "", val label: String = "")

/**
 * Une case : ce qu'elle fait de l'outil à ce moment, par ce canal. [level] : `seule`, `carte` (elle te demande, une
 * carte dans ton chat), `toi` (ton accord), `non`. [keep] : ce qu'elle garde de ce qu'il rend (`public`, `perso`,
 * `prive`, `rien`). [why] : pourquoi, dit à toi (ADR 0209). [reason] : ce qui le ferme avant ses lignes (`when`, sa
 * condition ; `needs`, son service n'est pas configuré ; `fits`, les accès de sa ressource). [owned] : ouvert parce
 * qu'une de ses ressources est à toi. [line] : la ligne même, pour une opératrice seulement (vide sinon).
 */
@Serializable
data class RightsCell(
    val level: String = RightsLevel.NO,
    val keep: String = Keeps.NOTHING,
    val why: String = "",
    val line: String = "",
    val reason: String = "",
    val owned: Boolean = false,
)

/**
 * Un outil : [label], ce qu'il fait, dit à toi (ADR 0208) — vide pour un outil venu d'ailleurs, que [description] nomme
 * alors ; [description], sa consigne au modèle (où « tu », c'est elle) ; [acts] : il change quelque chose ailleurs.
 * [cells] : `<canal>/<moment>` ; une case absente ou `null` : l'outil ne sert pas à ce moment.
 */
@Serializable
data class RightsTool(
    val name: String = "",
    val label: String = "",
    val description: String = "",
    val acts: Boolean = false,
    val cells: Map<String, RightsCell?> = emptyMap(),
)

/**
 * Une ressource : une famille de ses outils (`famille:<lot>`), un de tes comptes (`courrier:<boîte>`,
 * `teams:<compte>` : [kind], [address], sa famille [family] et la règle d'envoi qui vaut pour lui, [rules]), un service
 * (`mcp:<nom>`) ou une app de la Forge. [description] : ce qu'est une famille, le but d'un service qu'une personne a
 * branché ; vide pour un service de l'opératrice. [href] : la page de la console où se lit son tableau, pour une
 * opératrice seulement.
 */
@Serializable
data class RightsResource(
    val key: String = "",
    val title: String = "",
    val description: String = "",
    val href: String = "",
    val tools: List<RightsTool> = emptyList(),
    /** `mail` ou `teams` pour un de tes comptes ; vide sinon. */
    val kind: String = "",
    val address: String = "",
    val family: String = "",
    val rules: SendRules? = null,
)

/** Un groupe : `families` (ses propres outils), `accounts` (tes comptes), `services`, `apps` (de la Forge). */
@Serializable
data class RightsGroup(val key: String = "", val title: String = "", val resources: List<RightsResource> = emptyList())

/** `GET /api/moi/rights`. */
@Serializable
data class Rights(
    val canals: List<RightsCanal> = emptyList(),
    val moments: List<RightsMoment> = emptyList(),
    val groups: List<RightsGroup> = emptyList(),
)

/** Ce qu'elle fait d'un outil (`vocab.access`) : seule, elle te demande, ton accord, non. */
object RightsLevel {
    const val ALONE = "seule"
    const val CARD = "carte"
    const val YOU = "toi"
    const val NO = "non"
}

/** Ce qu'elle garde de ce qu'il rend : un savoir, un souvenir, une confidence, rien. */
object Keeps {
    const val PUBLIC = "public"
    const val PERSONAL = "perso"
    const val PRIVATE = "prive"
    const val NOTHING = "rien"
}

/** Ce qui ferme un outil avant ses lignes. */
object Reasons {
    const val WHEN = "when"
    const val NEEDS = "needs"
    const val FITS = "fits"
}

/** Les clés que la matrice porte : ses groupes, ses canaux, ses moments. */
object RightsKeys {
    const val FAMILIES = "families"
    const val ACCOUNTS = "accounts"
    const val SERVICES = "services"
    const val APPS = "apps"

    /** Un groupe de l'app, pas du serveur : la famille de ce téléphone (sa position), comme la maquette. */
    const val PHONE = "phone"

    const val MOBILE = "mobile"
    const val ALONE = "seule"

    const val REPLY = "reply"
    const val INITIATIVE = "initiative"
    const val WORK = "work"
}
