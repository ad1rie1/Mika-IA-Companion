package fr.qwartz.mika.data.moi.projects

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject

/*
 * L'activité d'un projet (`backendv2/docs/protocole-moi.md` § 11, « L'activité d'un projet » ; ADR 0290, 0293) — ses
 * trente derniers jours, ses totaux, ses exécutions et ce que l'une a fait pas à pas, son carnet — et **la gestion d'un
 * projet** (« Gérer un projet ») : ses réglages en sections, les projets archivés. Une ligne du fil ([Happening]) est
 * dans `ProjectsModels.kt`. Ce que le serveur dit et que l'app ne refait pas : les sortes et leurs mots, les verdicts,
 * `outside` sur un pas dont l'outil rend ce qui vient d'ailleurs, `can` et `why` de chaque champ d'un réglage.
 */

/** Qui a fait quoi, sur trente jours : `self`, `you`, `others`. */
@Serializable
data class ByWho(val who: String = "", val label: String = "", val count: Int = 0)

/** `GET …/activite/jours` : un jour porte `day`, un compte par sorte (sous son code) et `total`. */
@Serializable
data class ActivityDays(
    val days: List<JsonObject> = emptyList(),
    val totals: Map<String, Int> = emptyMap(),
    val total: Int = 0,
    val kinds: List<Coded> = emptyList(),
    val by: List<ByWho> = emptyList(),
    /** Trop d'événements : les jours les plus anciens sont incomplets. */
    val cut: Boolean = false,
)

/** `GET …/activite/totaux` : ses totaux sur toute son histoire, pour un filtre ; les notes de son carnet, ses exécutions. */
@Serializable
data class ActivityTotals(
    val kinds: List<StepCount> = emptyList(),
    val totals: Map<String, Int> = emptyMap(),
    val total: Int = 0,
    val cut: Boolean = false,
    val notes: Int = 0,
    @SerialName("notes_cut") val notesCut: Boolean = false,
    val runs: Int = 0,
)

/** L'objectif qu'une exécution, ou une note, visait. */
@Serializable
data class RunObjective(
    val id: Int = 0,
    val text: String = "",
    /** `once`, `constant` (une mission). */
    val kind: String = "",
    val ticket: Int = 0,
    val status: String = "",
    @SerialName("status_label") val statusLabel: String = "",
)

/** Un pas d'une exécution : l'outil en mots, ce qu'il visait (jamais ce qu'il a rendu), s'il a abouti. */
@Serializable
data class RunStep(
    val tool: String = "",
    val label: String = "",
    /** Ce qu'il visait, en une ligne ; vide sans le droit sur les fichiers du projet. */
    val aim: String = "",
    val ok: Boolean = true,
    val ran: Boolean = true,
    val ms: Long = 0,
    /** Il change quelque chose. */
    val acts: Boolean = false,
    /** Ce que cet outil rend vient d'ailleurs. */
    val outside: Boolean = false,
)

/** Une exécution ; avec `…/execution`, son compte rendu entier, ce qu'elle a demandé et ce qu'elle a fait pas à pas. */
@Serializable
data class Run(
    val id: String = "",
    val at: Long = 0,
    /** `frame` (cadrage), `run` (travail), `review` (relecture). */
    val sort: String = "",
    @SerialName("sort_label") val sortLabel: String = "",
    val objective: RunObjective? = null,
    val running: Boolean = false,
    val outcome: String = "",
    @SerialName("outcome_label") val outcomeLabel: String = "",
    val seconds: Long = 0,
    /** `continue`, `done`, `blocked`, `wait`, ou vide. */
    val verdict: String = "",
    @SerialName("verdict_label") val verdictLabel: String = "",
    val proven: Boolean = false,
    val summary: String = "",
    val commit: String = "",
    val branch: String = "",
    /** Elle a demandé quelque chose. */
    val asked: Boolean = false,
    val report: String = "",
    val need: String = "",
    val steps: List<RunStep> = emptyList(),
    @SerialName("steps_cut") val stepsCut: Boolean = false,
    /** Sa trace est encore gardée (quatorze jours). */
    @SerialName("steps_kept") val stepsKept: Boolean = true,
    /** Ce que chaque pas visait se dit ; sinon pourquoi. */
    @SerialName("steps_aims") val stepsAims: Boolean = true,
    @SerialName("steps_aims_why") val stepsAimsWhy: String = "",
)

@Serializable
data class RunPage(
    val total: Int = 0,
    val size: Int = 0,
    /** Le curseur à renvoyer dans `before` (0 : il n'y a plus rien). */
    val next: Long = 0,
    val sorts: List<Coded> = emptyList(),
    val items: List<Run> = emptyList(),
)

/** Une note de son carnet : ce qu'elle a écrit pour elle-même, et l'objectif qu'elle visait. */
@Serializable
data class NotebookNote(
    val seq: Long = 0,
    val at: Long = 0,
    val text: String = "",
    val objective: RunObjective? = null,
    val run: String = "",
)

@Serializable
data class NotebookPage(
    val size: Int = 0,
    val next: Long = 0,
    val items: List<NotebookNote> = emptyList(),
    val total: Int = 0,
    @SerialName("total_cut") val totalCut: Boolean = false,
)

// ── Gérer un projet ─────────────────────────────────────────────────────

/**
 * Un champ d'un réglage, décrit par le serveur : son libellé, son aide, ses choix sont les siens. [value] : sa valeur
 * actuelle, de la sorte qu'elle a (un texte, un nombre, un booléen, une liste). [can] : elle peut le changer — la garde
 * de l'enregistrement, dite d'avance ; sinon [why], en mots à afficher tels quels (un champ réservé à qui s'occupe d'elle).
 */
@Serializable
data class SettingField(
    val name: String = "",
    val label: String = "",
    val help: String = "",
    /** `text`, `textarea`, `select`, `bool`, `int`… */
    val kind: String = "text",
    val required: Boolean = false,
    val choices: List<Coded> = emptyList(),
    val value: JsonElement = JsonNull,
    val min: Double? = null,
    val max: Double? = null,
    /** Les valeurs d'un autre champ qui le rendent utile (vide : toujours). */
    val only: List<OnlyWhen> = emptyList(),
    val can: Boolean = true,
    val why: String = "",
)

/** Une section des réglages (`general`, `rythme`, `accords`, `depot`, `outils`) : son titre, elle en une ligne, ses champs. */
@Serializable
data class SettingsSection(
    val name: String = "",
    val title: String = "",
    val summary: String = "",
    /** Au moins un de ses champs se change ; sinon pourquoi. */
    val can: Boolean = true,
    val why: String = "",
    val fields: List<SettingField> = emptyList(),
)

/** `GET …/reglages` : ses réglages, si elle peut changer son cadre ([can], sinon [why]), s'il se renomme, s'il s'archive. */
@Serializable
data class ProjectSettings(
    val can: Boolean = false,
    val why: String = "",
    /** Un projet qu'elle a ouvert d'elle-même ne se renomme pas. */
    val renamable: Boolean = true,
    val archive: Allowed = Allowed(),
    val sections: List<SettingsSection> = emptyList(),
)

/** Un projet archivé qu'elle peut restaurer. */
@Serializable
data class Archived(
    val id: Int = 0,
    val title: String = "",
    @SerialName("archived_at") val archivedAt: Long = 0,
    @SerialName("owner_name") val ownerName: String = "",
)

@Serializable
data class Archives(val items: List<Archived> = emptyList())
