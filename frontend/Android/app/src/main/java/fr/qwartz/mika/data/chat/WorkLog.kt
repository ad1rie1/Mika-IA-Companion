package fr.qwartz.mika.data.chat

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.data.net.ServerFrame
import fr.qwartz.mika.data.net.ToolUse
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.util.Locale

/**
 * Ses cartes de travail (ADR 0116) : ce qu'elle fait, outil par outil, pendant qu'elle écrit une réponse pro. Tenues
 * en mémoire seulement, jamais en base — les trames `tool` ne se gardent pas, et une carte ne survit pas à un
 * redémarrage (l'historique dit alors ses outils, en une ligne). Pur et immuable : chaque trame donne un nouvel état.
 */

/** Une étape de son travail : un outil, ou ce qu'elle a écrit entre deux. */
sealed interface WorkStep {
    data class Tool(
        val callId: String,
        val name: String,
        /** Les arguments en JSON (texte), montrés tels quels. */
        val args: String,
        /** `null` : il n'a pas encore fini (ou on ne l'a jamais su). */
        val ok: Boolean? = null,
        val result: String = "",
        val durationMs: Long? = null,
        /** Quand il est parti (ms Unix), pour une durée que le serveur n'aurait pas dite. */
        val startedAt: Long? = null,
    ) : WorkStep

    data class Note(val text: String) : WorkStep
}

/**
 * La carte d'une réponse pro : le message de la personne auquel elle répond ([replyTo]), ses étapes dans l'ordre,
 * l'issue de l'épisode ([outcome], `null` tant qu'il n'est pas fini). Quand sa réponse arrive ([answered]), la
 * carte se replie au-dessus de la bulle [answerId].
 */
data class WorkCard(
    val episode: String,
    val replyTo: Long?,
    val steps: List<WorkStep> = emptyList(),
    val outcome: String? = null,
    val firstAt: Long? = null,
    val lastAt: Long? = null,
    val answered: Boolean = false,
    val answerId: Long? = null,
    /** Les étapes écartées au-delà de [MikaProtocol.MAX_WORK_STEPS]. */
    val dropped: Int = 0,
) {
    val key: String get() = "w$episode"
    val done: Boolean get() = outcome != null

    /** Elle y est encore : l'épisode n'est pas fini et sa réponse n'est pas venue. */
    val running: Boolean get() = !done && !answered

    val tools: List<WorkStep.Tool> get() = steps.filterIsInstance<WorkStep.Tool>()

    /**
     * Le temps passé : de la première trame à la dernière (la fin de l'épisode), et au moins la somme des durées
     * de ses outils ; `null` si rien ne le dit.
     */
    val elapsedMs: Long?
        get() {
            val span = if (firstAt != null && lastAt != null) lastAt - firstAt else null
            val sum = tools.mapNotNull { it.durationMs }.takeIf { it.isNotEmpty() }?.sum()
            return listOfNotNull(span, sum).maxOrNull()
        }

    /** Une trame de cet épisode, appliquée. */
    internal fun step(f: ServerFrame.Tool): WorkCard {
        val at = f.at
        val timed = if (at == null) this else copy(
            firstAt = minOf(firstAt ?: at, at),
            lastAt = maxOf(lastAt ?: at, at),
        )
        return when (f.phase) {
            MikaProtocol.TOOL_START -> {
                val i = timed.indexOfTool(f.callId)
                if (i >= 0) {
                    val t = timed.steps[i] as WorkStep.Tool
                    timed.replace(i, t.copy(name = f.name.ifEmpty { t.name }, args = f.args.ifEmpty { t.args }))
                } else {
                    timed.append(WorkStep.Tool(f.callId, f.name, f.args, startedAt = at))
                }
            }
            MikaProtocol.TOOL_END -> {
                val i = timed.indexOfTool(f.callId)
                // Un `end` sans `start` (un appel refusé avant de partir) crée sa ligne.
                val t = if (i >= 0) timed.steps[i] as WorkStep.Tool else WorkStep.Tool(f.callId, f.name, f.args)
                val measured = t.startedAt?.let { start -> at?.let { it - start } }?.takeIf { it >= 0 }
                val ended = t.copy(
                    name = f.name.ifEmpty { t.name },
                    args = f.args.ifEmpty { t.args },
                    ok = f.ok ?: false,
                    result = f.result,
                    durationMs = f.durationMs ?: measured,
                )
                if (i >= 0) timed.replace(i, ended) else timed.append(ended)
            }
            MikaProtocol.TOOL_NOTE -> {
                val text = f.text.trim()
                if (text.isEmpty()) timed else timed.append(WorkStep.Note(text))
            }
            MikaProtocol.TOOL_DONE -> timed.copy(outcome = f.outcome.ifEmpty { MikaProtocol.TOOL_OUTCOME_DONE })
            else -> this
        }
    }

    /** La ligne de cet appel ; un appel sans identifiant n'en retrouve aucune. */
    private fun indexOfTool(callId: String): Int =
        if (callId.isEmpty()) -1 else steps.indexOfLast { it is WorkStep.Tool && it.callId == callId }

    private fun replace(i: Int, s: WorkStep) = copy(steps = steps.toMutableList().also { it[i] = s })

    private fun append(s: WorkStep) =
        if (steps.size >= MikaProtocol.MAX_WORK_STEPS) copy(dropped = dropped + 1) else copy(steps = steps + s)
}

/**
 * Les cartes en cours, de la plus ancienne à la plus récente, et les épisodes retirés : une réponse supplantée
 * peut être suivie d'un nouvel épisode pour le même message — sa carte remplace la précédente, et une trame
 * tardive de l'ancien épisode ne la fait pas revenir.
 */
data class WorkLog(
    val cards: List<WorkCard> = emptyList(),
    val retired: List<String> = emptyList(),
) {
    /**
     * Une trame `tool`. Un épisode inconnu ouvre sa carte (sauf sur un `done` seul : rien à montrer) ; au-delà de
     * [MikaProtocol.MAX_WORK_CARDS], la plus ancienne part.
     */
    fun apply(f: ServerFrame.Tool): WorkLog {
        if (f.episode in retired) return this
        val next = cards.toMutableList()
        val gone = retired.toMutableList()
        var i = next.indexOfFirst { it.episode == f.episode }
        if (i < 0) {
            if (f.phase == MikaProtocol.TOOL_DONE) return this
            val replyTo = f.replyTo
            if (replyTo != null) {
                val replaced = next.filter { it.replyTo == replyTo }
                next.removeAll(replaced)
                gone += replaced.map { it.episode }
            }
            next += WorkCard(f.episode, replyTo)
            i = next.lastIndex
        }
        next[i] = next[i].step(f)
        while (next.size > MikaProtocol.MAX_WORK_CARDS) gone += next.removeAt(0).episode
        return WorkLog(next, gone.takeLast(MAX_RETIRED))
    }

    /**
     * Sa réponse pro est arrivée ([messageId], en réponse à [userMessageId]) : la carte de ce message se replie
     * au-dessus d'elle. Sans message de la personne, la dernière carte sans message encore ouverte.
     */
    fun answer(userMessageId: Long?, messageId: Long?): WorkLog {
        val i = if (userMessageId != null) {
            cards.indexOfLast { it.replyTo == userMessageId }
        } else {
            cards.indexOfLast { it.replyTo == null && !it.answered }
        }
        if (i < 0) return this
        return copy(cards = cards.toMutableList().also { it[i] = it[i].copy(answered = true, answerId = messageId) })
    }

    /**
     * Elle a parlé (une `speech`) : sa réponse pro ([pro]) replie la carte de son message ([answer]), puis
     * [prune] fait le ménage. Celles où elle travaille encore restent.
     */
    fun settle(userMessageId: Long?, messageId: Long?, pro: Boolean): WorkLog =
        (if (pro) answer(userMessageId, messageId) else this).prune()

    /**
     * Les cartes finies sans réponse (supplantées, en échec, sans rien à dire…) n'ont plus rien à faire en bas du
     * fil une fois qu'elle a parlé ou qu'un nouveau message est parti : elles partent.
     */
    fun prune(): WorkLog {
        val (stale, kept) = cards.partition { it.done && !it.answered }
        if (stale.isEmpty()) return this
        return WorkLog(kept, (retired + stale.map { it.episode }).takeLast(MAX_RETIRED))
    }

    private companion object {
        const val MAX_RETIRED = 50
    }
}

/** Ce que l'écran écrit d'une carte et d'une ligne d'outils : pur, pour les tests. */
object WorkText {
    private val SPACES = Regex("\\s+")

    /**
     * Un aperçu court des arguments, sur une ligne : les valeurs d'un objet JSON séparées par des virgules
     * (`{"query": "anniversaire de Léa"}` → `anniversaire de Léa`), sinon le texte tel quel ; coupé à [max].
     */
    fun argsPreview(args: String, max: Int = 60): String {
        val raw = args.trim()
        if (raw.isEmpty()) return ""
        val parsed = try {
            MikaJson.parseToJsonElement(raw)
        } catch (_: IllegalArgumentException) {
            null
        }
        val text = when (parsed) {
            is JsonObject -> parsed.values.joinToString(", ") { v -> (v as? JsonPrimitive)?.content ?: v.toString() }
            is JsonArray -> parsed.joinToString(", ") { v -> (v as? JsonPrimitive)?.content ?: v.toString() }
            else -> raw
        }
        val line = text.replace(SPACES, " ").trim()
        return if (line.length <= max) line else line.take(max - 1).trimEnd() + "…"
    }

    /** « 182 ms », « 3,2 s », « 2 min 05 s ». */
    fun duration(ms: Long): String = when {
        ms < 1_000 -> "${ms.coerceAtLeast(0)} ms"
        ms < 60_000 -> String.format(Locale.FRENCH, "%.1f s", ms / 1_000.0)
        else -> {
            val s = ms / 1_000
            "${s / 60} min ${(s % 60).toString().padStart(2, '0')} s"
        }
    }

    /** La ligne discrète sous une réponse pro relue : « email_search ✓ · email_read ✗ ». */
    fun toolsLine(tools: List<ToolUse>): String =
        tools.joinToString(" · ") { "${it.name} ${if (it.ok) "✓" else "✗"}" }
}
