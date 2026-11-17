package fr.qwartz.mika.ui.chat

import fr.qwartz.mika.data.approvals.ApprovalView
import fr.qwartz.mika.data.moi.Counts
import fr.qwartz.mika.data.moi.mail.MailDraft
import fr.qwartz.mika.data.moi.teams.TeamsReply
import fr.qwartz.mika.data.net.ApprovalCard
import fr.qwartz.mika.data.net.MikaProtocol
import fr.qwartz.mika.ui.Route

/** Où se relit et se décide ce qu'elle a préparé : Mail (un brouillon de sa boîte) ou Teams (une réponse). */
enum class DraftPlace { MAIL, TEAMS }

/**
 * Un brouillon à relire, tel que la ligne dépliée le montre : un lien vers l'écran où il se décide. [id] : le
 * brouillon ou la réponse ; vide, la ligne mène à la liste (« Ses brouillons ») et [count] dit combien y attendent.
 */
data class TrayDraft(
    val place: DraftPlace,
    val id: String,
    val title: String,
    val detail: String,
    val route: Route,
    val count: Int = 0,
)

/**
 * Ce qui attend ta décision au-dessus du champ (ADR 0235, point 4) : les cartes d'accord qui se décident ici
 * ([accords], inchangées : exactement ce qui partira), les brouillons qui se décident dans Mail ou Teams ([drafts] —
 * ADR 0191 : jamais leurs boutons ici), combien de brouillons en tout ([draftCount]), et l'échéance la plus proche d'un
 * accord encore décidable ([soonest], en ms).
 */
data class TrayView(
    val accords: List<ApprovalView> = emptyList(),
    val drafts: List<TrayDraft> = emptyList(),
    val draftCount: Int = 0,
    val soonest: Long? = null,
) {
    val isEmpty: Boolean get() = accords.isEmpty() && draftCount == 0
}

/**
 * La ligne repliée au-dessus du champ et ce qu'elle déplie, sans Compose : quelles cartes se décident ici, lesquelles
 * sont des brouillons à relire ailleurs (`frontendv2/src/screens/chat/markup.ts::elsewhere`, ADR 0191), combien de
 * brouillons attendent (les pastilles de `GET /api/moi` et ses brouillons lus, sans compter deux fois le même), le
 * compte à rebours, et ce que « Tout accepter » prend (ADR 0170 : seulement ce que « Accepter » permettrait, une à une,
 * jamais un brouillon).
 */
object ChatTray {
    /** Au-delà, un lien vers la liste (« Ses brouillons ») dit le reste. */
    const val MAX_DRAFTS_PER_PLACE = 4
    /** En deçà, le compte à rebours se montre en ambre. */
    const val URGENT_MS = 5 * 60_000L
    private const val MINUTE_MS = 60_000L
    private const val DETAIL_CHARS = 60

    // ── Où se décide une carte ────────────────────────────────────────────────

    /**
     * Une carte qui se décide là où elle partira (ADR 0191) : un mail de sa boîte qui nomme son brouillon, une réponse
     * Teams (même sans brouillon nommé : la liste de ses réponses). Sinon `null` : elle se décide ici.
     */
    fun place(capability: String, draft: String): DraftPlace? = when {
        capability == MikaProtocol.CAPABILITY_EMAIL_SEND && draft.isNotEmpty() -> DraftPlace.MAIL
        capability == MikaProtocol.CAPABILITY_TEAMS_SEND -> DraftPlace.TEAMS
        else -> null
    }

    fun place(card: ApprovalView): DraftPlace? = place(card.capability, card.draft)

    fun place(card: ApprovalCard): DraftPlace? = place(card.capability, card.draft)

    // ── La ligne et ce qu'elle déplie ─────────────────────────────────────────

    /**
     * Ce que montre la bande au-dessus du champ. [counts] : les pastilles (`null` : pas encore lues) ; [mail] et
     * [teams] : ses brouillons et ses réponses lus pour la ligne (`null` : pas lus, ou la lecture a échoué — les
     * pastilles et les cartes suffisent alors). Un brouillon que nomme une carte et que la liste porte aussi ne compte
     * qu'une fois ; les pastilles disent au moins combien attendent (une liste lue plus tôt peut être en retard).
     */
    fun build(views: List<ApprovalView>, counts: Counts?, mail: List<MailDraft>?, teams: List<TeamsReply>?, nowWallMs: Long): TrayView {
        val accords = views.filter { place(it) == null }
        val cards = views.filter { place(it) != null }
        val mailDrafts = mailLinks(cards.filter { place(it) == DraftPlace.MAIL }, mail)
        val teamsDrafts = teamsLinks(cards.filter { place(it) == DraftPlace.TEAMS }, teams)
        val mailCount = maxOf(mailDrafts.size, counts?.mail ?: 0)
        val teamsCount = maxOf(teamsDrafts.size, counts?.teams ?: 0)
        val drafts = capped(mailDrafts, mailCount, DraftPlace.MAIL) + capped(teamsDrafts, teamsCount, DraftPlace.TEAMS)
        val soonest = accords.filter { !it.expired }.mapNotNull { it.expiresAt }.filter { it > nowWallMs }.minOrNull()
        return TrayView(accords, drafts, mailCount + teamsCount, soonest)
    }

    /** Ses brouillons de mail qui attendent ta décision, puis ceux que nomme une carte et que la liste n'a pas. */
    private fun mailLinks(cards: List<ApprovalView>, mail: List<MailDraft>?): List<TrayDraft> {
        val waiting = mail.orEmpty().filter { it.waiting && it.decides }
        val out = waiting.mapTo(ArrayList()) { d ->
            val to = d.toPeople.firstOrNull()?.shown ?: d.to
            TrayDraft(DraftPlace.MAIL, d.id, d.subject.ifBlank { NO_SUBJECT }, if (to.isBlank()) "" else "→ $to", Route.MailDraft(d.id))
        }
        for (c in cards) {
            if (out.none { it.id == c.draft }) out += TrayDraft(DraftPlace.MAIL, c.draft, c.title, "", Route.MailDraft(c.draft))
        }
        return out
    }

    /**
     * Ses réponses dans Teams qui attendent ta décision (pas une à laquelle on a répondu autrement), puis celles que
     * nomme une carte. Chacune mène à sa discussion, où sa carte rose se décide ; sans discussion connue, à la liste.
     */
    private fun teamsLinks(cards: List<ApprovalView>, teams: List<TeamsReply>?): List<TrayDraft> {
        val all = teams.orEmpty()
        fun routeOf(r: TeamsReply?): Route = r?.conversation?.takeIf { it.isNotBlank() }?.let { Route.TeamsThread(it) } ?: Route.TeamsReplies
        val out = all.filter { it.waiting && !it.answered }.mapTo(ArrayList()) { r ->
            TrayDraft(DraftPlace.TEAMS, r.id, r.title.ifBlank { NO_TITLE }, quoted(r.preview?.text?.ifBlank { null } ?: r.body), routeOf(r))
        }
        for (c in cards) {
            if (c.draft.isNotEmpty() && out.any { it.id == c.draft }) continue
            out += TrayDraft(DraftPlace.TEAMS, c.draft, c.title, "", routeOf(all.firstOrNull { it.id == c.draft && c.draft.isNotEmpty() }))
        }
        return out
    }

    /** Les premiers d'un lieu ; s'il en attend plus que la ligne n'en montre, un lien vers sa liste dit combien. */
    private fun capped(links: List<TrayDraft>, count: Int, place: DraftPlace): List<TrayDraft> {
        val shown = links.take(MAX_DRAFTS_PER_PLACE)
        if (count <= shown.size) return shown
        val list = when (place) {
            DraftPlace.MAIL -> TrayDraft(place, "", "", "", Route.MailDrafts, count)
            DraftPlace.TEAMS -> TrayDraft(place, "", "", "", Route.TeamsReplies, count)
        }
        return shown + list
    }

    private fun quoted(text: String): String {
        val flat = text.replace(Regex("\\s+"), " ").trim()
        if (flat.isEmpty()) return ""
        val cut = if (flat.length > DETAIL_CHARS) flat.take(DETAIL_CHARS - 1).trimEnd() + "…" else flat
        return "« $cut »"
    }

    /** Le compte à rebours de la ligne, arrondi à la minute supérieure : « 4 min », « 2 h 05 », « 3 j » ; passé : `null`. */
    fun countdown(expiresAt: Long?, nowWallMs: Long): String? {
        if (expiresAt == null) return null
        val left = expiresAt - nowWallMs
        if (left <= 0) return null
        if (left < MINUTE_MS) return "< 1 min"
        val minutes = (left + MINUTE_MS - 1) / MINUTE_MS
        return when {
            minutes < 60 -> "$minutes min"
            minutes < 24 * 60 -> {
                val m = minutes % 60
                if (m == 0L) "${minutes / 60} h" else "${minutes / 60} h ${m.toString().padStart(2, '0')}"
            }
            else -> "${minutes / (24 * 60)} j"
        }
    }

    fun urgent(expiresAt: Long?, nowWallMs: Long): Boolean = expiresAt != null && expiresAt - nowWallMs in 1..URGENT_MS

    // ── Repliée, dépliée ─────────────────────────────────────────────────────

    /** Les accords de cette liste qu'on n'avait jamais vus : la ligne se déplie toute seule pour eux. */
    fun newAccords(cards: List<ApprovalCard>, seen: Set<Long>): Set<Long> =
        cards.filter { place(it) == null && it.id !in seen }.mapTo(HashSet()) { it.id }

    // ── « Tout accepter » (ADR 0170) ─────────────────────────────────────────

    /** Il se propose en mode pro, à une opératrice, quand deux accords ou plus attendent. */
    fun offersAcceptAll(pro: Boolean, operator: Boolean, tray: TrayView): Boolean = pro && operator && tray.accords.size >= 2

    /** Ce qu'il prend : chaque accord que « Accepter » permettrait (ni bloqué, ni expiré, ni hors ligne…), jamais un brouillon. */
    fun acceptAllTargets(views: List<ApprovalView>): List<ApprovalView> = views.filter { place(it) == null && it.canAccept }

    /**
     * Au moment de l'envoyer, la carte telle qu'elle est maintenant, si elle est encore celle qu'on a vue (même
     * empreinte) et que « Accepter » la permet toujours ; sinon `null` : elle reste à la personne.
     */
    fun stillAcceptable(target: ApprovalView, now: List<ApprovalView>): ApprovalView? =
        now.firstOrNull { it.id == target.id }?.takeIf { it.digest == target.digest && it.canAccept && place(it) == null }

    private const val NO_SUBJECT = "(sans objet)"
    private const val NO_TITLE = "Une discussion"
}
