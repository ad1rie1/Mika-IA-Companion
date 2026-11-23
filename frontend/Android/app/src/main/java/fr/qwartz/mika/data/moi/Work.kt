package fr.qwartz.mika.data.moi

import kotlinx.serialization.Serializable

/*
 * Où elle en est d'une réponse qu'elle prépare (ADR 0306) : la ligne au-dessus de la saisie, dans Teams et dans Mail.
 * Une seule ligne — l'étape (elle s'y met, elle réfléchit, tel outil tourne) et son chrono, qui court entre deux
 * relectures. Le moteur la dit dans `work` (`backendv2/docs/protocole-moi.md`, « `work`, en direct ») ; rien n'en est
 * gardé. Porté de `frontendv2/src/mika/work.ts`, pur et testé sur la JVM.
 */

/** Les étapes de [Work]. */
object WorkSteps {
    /** Demandée, pas encore commencée : elle s'y met. */
    const val WAITING = "waiting"
    /** Elle réfléchit : elle compose, le modèle écrit. */
    const val THINKING = "thinking"
    /** Un de ses outils tourne ([Work.label] : son libellé). */
    const val TOOL = "tool"
}

/** Où elle en est, tel que le serveur le dit (`{"step", "label", "since", "started"}`, en ms). */
@Serializable
data class Work(
    val step: String = WorkSteps.WAITING,
    /** Le libellé de l'outil (`tool`) ; vide sinon. */
    val label: String = "",
    /** Le début de l'étape (ms). */
    val since: Long = 0,
    /** Le début du travail (ms ; pour `waiting`, la demande). */
    val started: Long = 0,
) {
    companion object {
        /** Juste après un « Préremplir » réussi : elle s'y met, depuis maintenant — la relecture suivante la corrige. */
        fun waiting(now: Long) = Work(WorkSteps.WAITING, "", now, now)
    }
}

/** Ce qu'on relit toutes les deux secondes tant qu'elle y travaille (`…/teams/work`, `…/mail/work`)… */
const val WORK_POLL_MS = 2_000L

/** …au plus si longtemps : au-delà, on cesse de guetter ici (la relecture ordinaire de l'écran la verra arriver). */
const val WORK_WATCH_MAX_MS = 30 * 60_000L

/** Le libellé d'un outil sans nom. */
private const val SOME_TOOL = "Un de ses outils"

/** L'étape en mots : « Elle s'y met… », « Réflexion en cours… », « Relire une de tes conversations Teams… » — jamais deux
 *  points de suspension ; un outil sans libellé, « Un de ses outils… ». Une étape inconnue (un serveur plus récent) se
 *  dit comme l'attente. */
fun workText(w: Work): String = when (w.step) {
    WorkSteps.TOOL -> w.label.trim().ifEmpty { SOME_TOOL }.trimEnd('.', '…') + "…"
    WorkSteps.THINKING -> "Réflexion en cours…"
    else -> "Elle s'y met…"
}

/** Un chrono : « 0:07 », « 1:30 », puis « 1:02:05 » au-delà d'une heure — jamais négatif (une horloge un peu en avance
 *  donne « 0:00 »). */
fun elapsed(ms: Long): String {
    val total = maxOf(0L, ms / 1000)
    val s = total % 60
    val m = total / 60 % 60
    val hours = total / 3600
    val ss = s.toString().padStart(2, '0')
    return if (hours > 0) "$hours:${m.toString().padStart(2, '0')}:$ss" else "$m:$ss"
}

/** Ce que dit une relecture de `…/work`. */
enum class WorkTurn {
    /** Sa réponse est arrivée (une réponse en chemin dans Teams, son brouillon dans Mail) : l'écran la relit. */
    ARRIVED,

    /** Elle a fini sans en rendre, ou y a renoncé : plus rien n'est en cours ni demandé ici. */
    ENDED,

    /** Elle y travaille encore (ou s'y met) : seule la ligne change. */
    GOING,
}

/** La relecture de `…/work` : [arrived] (sa réponse est là), sinon rien de demandé ni d'en cours, sinon elle continue. */
fun workTurn(arrived: Boolean, asked: Boolean, work: Work?): WorkTurn = when {
    arrived -> WorkTurn.ARRIVED
    !asked && work == null -> WorkTurn.ENDED
    else -> WorkTurn.GOING
}

/** On guette où elle en est (toutes les deux secondes) : une réponse demandée ou qu'elle prépare d'elle-même
 *  ([work] non nul), pas encore arrivée ([arrived]), sans avoir passé le plafond ([gaveUp]). */
fun watchWork(asked: Boolean, work: Work?, arrived: Boolean, gaveUp: Boolean): Boolean =
    !arrived && !gaveUp && (asked || work != null)

/** Le plafond est passé : guetté depuis [since], il est [now]. */
fun workGaveUp(since: Long, now: Long): Boolean = now - since > WORK_WATCH_MAX_MS
