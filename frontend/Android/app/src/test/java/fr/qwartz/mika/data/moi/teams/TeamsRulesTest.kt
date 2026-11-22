package fr.qwartz.mika.data.moi.teams

import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.ago
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Les règles de Teams, portées du client web (`frontendv2/src/screens/teams/format.ts`, ses tests `teams.test.ts`) :
 * qui a écrit, l'état de ses réponses et de tes messages en attente, les jours et les mentions du fil, ce qui reste du
 * champ, ce qui empêche d'écrire ou de préremplir.
 */
class TeamsRulesTest {
    private val paris = ZoneId.of("Europe/Paris")
    private fun at(y: Int, mo: Int, d: Int, h: Int, mi: Int = 0): Long =
        LocalDateTime.of(y, mo, d, h, mi).atZone(paris).toInstant().toEpochMilli()

    private val now = at(2026, 11, 4, 15) // un mercredi
    private val min = 60_000L

    private fun reply(
        state: String = ReplyStates.WAITING,
        sentText: String = "",
        edited: Boolean = false,
        expires: Long = 0,
        answered: Boolean = false,
        decidedAt: Long = 0,
        id: String = "r1",
        account: String = "principal",
        toFill: Boolean = false,
        preview: ReplyPreview? = ReplyPreview("Oui, 15 h me va.\n— Mika", "d1", ""),
    ) = TeamsReply(
        id = id, account = account, conversation = "19:marc", title = "Marc Delmas", inReplyTo = "t1", state = state,
        mode = ReplyModes.APPROVAL, at = now - 5 * min, decidedAt = decidedAt, expires = expires, answered = answered,
        edited = edited, body = "Oui, 15 h me va.", sentText = sentText, toFill = toFill, preview = preview,
    )

    private fun msg(at: Long = now - 30 * min, own: Boolean = false, author: String = "Marc Delmas", id: String = "8:marc", text: String = "Salut") =
        TeamsMessage(ref = "t$at", author = author, authorId = id, at = at, text = text, own = own)

    private fun account(level: String = Levels.OWNER, owner: String = "", self: String = "Adrien Moreau", lastBatch: Long = now - min, enabled: Boolean = true) =
        TeamsAccount(key = "principal", name = "Atelier", level = level, selfName = self, ownerName = owner, lastBatch = lastBatch, enabled = enabled)

    // ── l'état de ses réponses ──

    @Test fun `chaque état de ses réponses, en mots`() {
        assertEquals(Tone.WARN to "attend ton accord", replyState(reply(), paris))
        assertEquals("en file", replyState(reply(ReplyStates.QUEUED), paris).second)
        assertEquals("posée dans Teams", replyState(reply(ReplyStates.PLACED), paris).second)
        assertEquals(Tone.OK to "partie", replyState(reply(ReplyStates.SENT, sentText = "Oui, 15 h me va.\n— Mika"), paris))
        assertEquals(Tone.OK to "partie · retouchée", replyState(reply(ReplyStates.SENT, sentText = "Plutôt 16 h ?"), paris))
        assertEquals("partie · retouchée", replyState(reply(ReplyStates.SENT, edited = true), paris).second)
        assertEquals(Tone.DANGER to "pas servie", replyState(reply(ReplyStates.UNUSED), paris))
        assertEquals("refusée", replyState(reply(ReplyStates.REFUSED), paris).second)
        assertEquals("expirée", replyState(reply(ReplyStates.EXPIRED), paris).second)
        assertEquals(Tone.DANGER to "échec", replyState(reply(ReplyStates.FAILED), paris))
    }

    @Test fun `une carte d'accord dit jusqu'à quand`() {
        val r = reply(expires = at(2026, 11, 4, 15, 42))
        assertEquals("attend ton accord · jusqu'à 15:42", replyState(r, paris).second)
        assertEquals(Tone.WARN to "Ton accord : elle part quand tu l'acceptes, ici · jusqu'à 15:42", cardState(r, paris))
        assertEquals("Posée dans la zone de saisie de Teams : tu l'envoies là-bas", cardState(reply(ReplyStates.PLACED), paris).second)
        assertEquals("", cardState(reply(ReplyStates.SENT), paris).second)
    }

    @Test fun `retouchée, ce qui est parti n'est pas ce qu'elle avait écrit`() {
        assertFalse(retouched(reply(ReplyStates.SENT, sentText = "")))
        assertFalse(retouched(reply(ReplyStates.SENT, sentText = "Oui,  15 h me va. — Mika")))
        assertTrue(retouched(reply(ReplyStates.SENT, sentText = "Plutôt 16 h")))
        assertEquals("brouillon", modeLabel(ReplyModes.DRAFT))
        assertEquals("ton accord", modeLabel(ReplyModes.APPROVAL))
        assertEquals("seule", modeLabel(ReplyModes.ALONE))
    }

    @Test fun `ce qu'on montre d'une réponse, et ce qui la bloque`() {
        assertEquals("Oui, 15 h me va.\n— Mika", replyText(reply()))
        assertEquals("Plutôt 16 h", replyText(reply(ReplyStates.SENT, sentText = "Plutôt 16 h")))
        assertEquals("Oui, 15 h me va.", replyText(reply(preview = null)))
        assertEquals("il reste des passages à compléter", replyBlocked(reply(toFill = true, preview = null)))
        assertEquals("un passage", replyBlocked(reply(preview = ReplyPreview("x", "d", "un passage"))))
        assertEquals("", replyBlocked(reply(ReplyStates.SENT, toFill = true, preview = null)))
    }

    // ── répondu autrement (ADR 0199) ──

    @Test fun `répondu autrement, la carte le dit, sans plus rien à décider`() {
        val answered = reply(ReplyStates.REFUSED, answered = true, decidedAt = now - 2 * min, preview = null)
        assertEquals("répondu autrement", replyState(reply(answered = true), paris).second)
        assertEquals("refusée · répondu autrement", replyState(answered, paris).second)
        assertFalse(decidable(reply(answered = true), account()))
        // le fil la montre tant que rien n'est venu depuis
        assertEquals(listOf(answered), threadCards(listOf(answered), now - 5 * min))
        assertEquals(emptyList<TeamsReply>(), threadCards(listOf(answered), now))
        assertEquals(emptyList<TeamsReply>(), threadCards(listOf(reply(ReplyStates.REFUSED, id = "r9")), 0))
        assertEquals(1, threadCards(listOf(reply()), now).size) // en chemin : toujours
    }

    // ── qui a écrit ──

    @Test fun `« Toi » seulement sur un compte à toi, sinon la personne du compte, ou son propriétaire`() {
        val mine = msg(own = true, author = "Adrien Moreau", id = "8:a")
        assertEquals(YOU, authorLabel(mine, account()))
        assertTrue(fromYou(mine, account()))
        val shared = account(Levels.READ, owner = "Adrien Moreau", self = "")
        assertEquals("Adrien Moreau", authorLabel(mine, shared))
        assertFalse(fromYou(mine, shared))
        assertEquals("Adrien M.", authorLabel(mine, account(Levels.USE, owner = "Adrien Moreau", self = "Adrien M.")))
        // un compte qu'on ne connaît pas : on ne t'attribue jamais un message sans le savoir
        assertFalse(fromYou(mine, null))
        assertEquals("Adrien Moreau", authorLabel(mine, null))
        assertEquals("Marc Delmas", authorLabel(msg(), account()))
        assertEquals("?", authorLabel(msg(author = ""), account()))
    }

    @Test fun `sous quel nom ça part, et qui a les mentions`() {
        assertEquals("Adrien Moreau", selfName(account(), "Léa"))
        assertEquals("Léa", selfName(account(self = ""), "Léa"))
        assertEquals("Adrien Moreau", selfName(account(Levels.USE, owner = "Adrien Moreau", self = ""), "Léa"))
        assertEquals("", selfName(null, "Léa"))
    }

    @Test fun `le nom d'un compte, la ligne d'une discussion`() {
        assertEquals("Atelier", accountTitle(account()))
        assertEquals("Atelier d'Adrien Moreau", accountTitle(account(Levels.READ, owner = "Adrien Moreau")))
        val c = Conversation(key = "19:lumen", title = "Projet Lumen", kind = Kinds.GROUP, last = msg(text = "la démo tourne", author = "Karim Haddad"))
        assertEquals("Karim : ", lastPrefix(c, account()))
        assertEquals("Toi : ", lastPrefix(c.copy(last = msg(own = true, author = "Adrien Moreau")), account()))
        assertEquals("Adrien : ", lastPrefix(c.copy(last = msg(own = true, author = "x")), account(Levels.READ, owner = "Adrien Moreau", self = "")))
        assertEquals("", lastPrefix(c.copy(kind = Kinds.DM), account()))
        assertEquals("attend ton accord", herMark(ReplyStates.WAITING))
        assertEquals("en file", herMark(ReplyStates.APPROVED))
        assertTrue(isGroup(Kinds.CHANNEL))
        assertFalse(isGroup(Kinds.DM))
        assertEquals("groupe · compte Atelier d'Adrien Moreau", threadSubtitle(Kinds.GROUP, account(Levels.READ, owner = "Adrien Moreau"), 1))
        assertEquals("tête-à-tête", threadSubtitle(Kinds.DM, account(), 1))
        assertEquals("réunion · compte Atelier", threadSubtitle(Kinds.MEETING, account(), 2))
    }

    @Test fun `ce qui attend ta décision, sur tes comptes seulement`() {
        val accounts = listOf(account().copy(draftsWaiting = 2), account(Levels.USE, owner = "Léa").copy(key = "lea", draftsWaiting = 3))
        assertEquals(2, waitingYours(accounts))
        assertEquals(0, waitingYours(accounts, "lea"))
        val replies = listOf(reply(), reply(id = "r2", answered = true), reply(id = "r3", account = "lea"), reply(ReplyStates.SENT, id = "r4"))
        assertEquals(1, waitingCount(replies, accounts))
        assertTrue(decidable(reply(), account()))
        assertFalse(decidable(reply(), account(Levels.USE, owner = "Léa")))
        assertFalse(decidable(reply(), null))
    }

    // ── le fil ──

    @Test fun `les repères de jour, et la suite d'un même auteur`() {
        val yesterday = at(2026, 11, 3, 21, 55)
        val marks = threadMarks(
            listOf(msg(yesterday), msg(yesterday + min), msg(now - 30 * min), msg(now - 29 * min, own = true, author = "Adrien", id = "8:a")),
            now,
            paris,
        )
        assertEquals(listOf("Hier", "", "Aujourd'hui", ""), marks.map { it.day })
        assertEquals(listOf(false, true, false, false), marks.map { it.suite })
        // au-delà de dix minutes, le même auteur se redit
        assertFalse(threadMarks(listOf(msg(now - 30 * min), msg(now - 15 * min)), now, paris)[1].suite)
        assertEquals("lundi 2 novembre", dayLabel(at(2026, 11, 2, 10), now, paris))
        assertEquals("lundi 1er décembre 2025", dayLabel(at(2025, 12, 1, 10), now, paris))
    }

    @Test fun `ta mention en valeur, et seulement elle`() {
        val text = "@Adrien tu peux valider ?"
        assertEquals(listOf("@Adrien"), mentionRanges(text, "Adrien Moreau", true).map { text.substring(it) })
        val full = "@Adrien Moreau ok, et @Adrien aussi"
        assertEquals(listOf("@Adrien Moreau", "@Adrien"), mentionRanges(full, "Adrien Moreau", true).map { full.substring(it) })
        assertEquals(emptyList<IntRange>(), mentionRanges(text, "Adrien Moreau", false))
        assertEquals(emptyList<IntRange>(), mentionRanges(text, " ", true))
        // un nom qui porte des signes de regex ne casse rien
        assertEquals(listOf("@J.-P. (Jo)"), mentionRanges("@J.-P. (Jo) ?", "J.-P. (Jo)", true).map { "@J.-P. (Jo) ?".substring(it) })
    }

    @Test fun `ce que tu as envoyé et qu'elle avait préparé, « rédigé avec Mika »`() {
        val parti = reply(ReplyStates.SENT, sentText = "Oui, 15 h me va.")
        assertTrue(fromHer(msg(own = true, text = "Oui, 15 h me va."), listOf(parti)))
        assertFalse(fromHer(msg(own = false, text = "Oui, 15 h me va."), listOf(parti)))
        assertFalse(fromHer(msg(own = true, text = "Autre chose"), listOf(parti)))
        assertTrue(fromHer(msg(own = true, text = "Oui, 15 h me va."), listOf(reply(ReplyStates.SENT, sentText = "Oui, 15 h me va.\n— Mika"))))
    }

    @Test fun `le dernier message de quelqu'un d'autre`() {
        val got = lastReceived(listOf(msg(now - 3 * min, text = "a"), msg(now - 2 * min, text = "b"), msg(now - min, own = true, text = "c")))
        assertEquals("b", got?.text)
        assertNull(lastReceived(listOf(msg(own = true))))
    }

    // ── tes messages en attente (ADR 0189) ──

    private fun own(state: String, at: Long = now - 10 * min, body: String = "ok $state", reason: String = "") =
        OwnPending(id = "p-$state", body = body, at = at, state = state, by = "user_1", reason = reason)

    private val base = ConversationThread(key = "19:marc", account = "principal", title = "Marc Delmas", kind = Kinds.DM, messages = listOf(msg()))

    @Test fun `en file, en cours d'envoi, posé, puis pas parti`() {
        assertEquals("en file : l'extension l'envoie dans Teams, sous ton nom" to false, pendingNote(OwnStates.QUEUED))
        assertFalse(pendingNote(OwnStates.SENDING).second)
        assertTrue(pendingNote(OwnStates.PLACED).first.contains("zone de saisie de Teams"))
        assertTrue(pendingNote(OwnStates.UNUSED).second)
        assertTrue(pendingNote(OwnStates.UNUSED).first.contains("pas parti"))
        assertEquals(
            "pas parti : l'envoi a échoué (envoi sans nouvelles de l'extension)" to true,
            pendingNote(OwnStates.FAILED, "envoi sans nouvelles de l'extension"),
        )
    }

    @Test fun `le moteur fait foi pour ce qu'il connaît`() {
        val sent = listOf(SentHere("19:marc", "ok 👍", now - min), SentHere("19:autre", "x", now - min))
        // lue avant que l'envoi ne soit accepté : il reste
        assertEquals(2, stillSentHere(sent, base.copy(pending = emptyList()), now - 2 * min).size)
        // lue après : le moteur le dit (ou l'a déjà rendu) — celle d'une autre discussion reste
        assertEquals(listOf(sent[1]), stillSentHere(sent, base.copy(pending = listOf(own(OwnStates.QUEUED, body = "ok 👍"))), now))
        assertEquals(listOf(sent[1]), stillSentHere(sent, base.copy(pending = emptyList()), now))
        // un moteur qui ne dit pas `pending` : l'envoi s'efface quand le même texte revient de toi dans le fil
        assertEquals(2, stillSentHere(sent, base, now).size)
        assertEquals(listOf(sent[1]), stillSentHere(sent, base.copy(messages = listOf(msg(now, own = true, text = "OK 👍 "))), now))
    }

    @Test fun `les bulles, celles du moteur de la plus ancienne à la plus récente, puis les envois d'ici`() {
        val bubbles = ownBubbles(
            listOf(own(OwnStates.UNUSED, at = now - 5 * min), own(OwnStates.QUEUED, at = now - 9 * min)),
            listOf(SentHere("19:marc", "tout neuf", now)),
        )
        assertEquals(listOf("p-en_file" to false, "p-inutilise" to true, "" to false), bubbles.map { it.id to it.failed })
        assertEquals(emptyList<OwnBubble>(), ownBubbles(null, emptyList()))
    }

    @Test fun `sur un compte qu'on te partage, ce qui part part sous le nom de sa personne, et elle attend son propriétaire`() {
        // « Atelier de Léa », partagé pour t'en servir : Léa Martin y est la personne du compte
        val lea = account(level = Levels.USE, owner = "Léa Martin", self = "Léa Martin")
        assertEquals("sous le nom de Léa Martin", sentUnder(lea))
        assertEquals("sous le nom de Léa Martin", sentUnder(account(level = Levels.USE, owner = "Léa Martin", self = "")))
        assertEquals("sous ton nom", sentUnder(account()))
        assertEquals("sous le nom du compte", sentUnder(null))
        // ta bulle en file, sous la ligne « part par l'extension, sous le nom de Léa Martin »
        assertEquals(
            "en file : l'extension l'envoie dans Teams, sous le nom de Léa Martin" to false,
            pendingNote(OwnStates.QUEUED, under = sentUnder(lea)),
        )
        val bubbles = ownBubbles(listOf(own(OwnStates.QUEUED)), listOf(SentHere("19:marc", "ok pour jeudi", now)), sentUnder(lea))
        assertTrue(bubbles.all { it.note == "en file : l'extension l'envoie dans Teams, sous le nom de Léa Martin" })
        assertEquals(
            "En file : l'extension l'envoie dans Teams, sous le nom de Léa Martin",
            cardState(reply(ReplyStates.QUEUED), paris, under = sentUnder(lea)).second,
        )
        // partagé pour préparer : sa réponse attend Léa, pas toi
        val prepare = account(level = Levels.PREPARE, owner = "Léa Martin", self = "Léa Martin")
        assertFalse(decides(prepare))
        assertTrue(decides(account()))
        assertEquals(Tone.WARN to "attend l'accord de son propriétaire", replyState(reply(), paris, decides = decides(prepare)))
        assertEquals("attend l'accord de son propriétaire", herMark(ReplyStates.WAITING, decides(prepare)))
        assertEquals("attend ton accord", herMark(ReplyStates.WAITING, decides(account())))
        assertTrue(cardState(reply(), paris, decides = false).second.startsWith("L'accord de son propriétaire"))
    }

    @Test fun `le texte parti se retire du champ, ce qu'on a tapé pendant l'envoi reste`() {
        assertEquals("", withoutSent("Je regarde ça", "Je regarde ça"))
        assertEquals("et je te redis", withoutSent("  Je regarde ça et je te redis", "Je regarde ça"))
        assertNull(withoutSent("Autre chose", "Je regarde ça"))
        assertNull(withoutSent("", "Je regarde ça"))
    }

    @Test fun `ce qui empêche ton message de partir`() {
        assertEquals("", messageProblem("Je regarde ça"))
        assertEquals("Il reste des passages [À COMPLÉTER] à remplir.", messageProblem("On se voit [À COMPLÉTER : jour]"))
        assertEquals("", messageProblem("😀".repeat(TeamsLimits.BODY)))
        assertEquals("Ton message est trop long : 4 000 caractères au plus (il en a 4 001).", messageProblem("a".repeat(4001)))
    }

    // ── ce qui part, et ce qu'elle prépare ──

    @Test fun `ce qui retient ce qui part, et pourquoi préremplir ne servirait à rien`() {
        assertEquals("", quietLine(true, account(), now))
        assertEquals("Teams est désactivé : rien ne part.", quietLine(false, account(), now))
        assertEquals("Ce compte Teams est décoché : rien n'en part.", quietLine(true, account(enabled = false), now))
        assertTrue(quietLine(true, account(lastBatch = 0), now).startsWith("L'extension de ce compte ne s'est encore jamais manifestée"))
        assertEquals(
            "L'extension ne s'est pas manifestée depuis 3 h : ce qui part attend que Teams web soit ouvert avec elle.",
            quietLine(true, account(lastBatch = now - 3 * 3600_000L), now),
        )
        assertEquals("", prefillOff(true, account()))
        assertEquals("Ce compte Teams est décoché : elle n'y prépare rien.", prefillOff(true, account(enabled = false)))
        assertEquals("Teams est désactivé : elle n'y prépare rien.", prefillOff(false, null))
    }

    @Test fun `un compte qu'on ne te partage pas pour t'en servir le dit`() {
        assertEquals(
            "Ce compte t'est partagé en lecture et préparation : Mika peut t'y préparer une réponse, que Adrien Moreau approuve.",
            readOnlyLine(Levels.PREPARE, "Adrien Moreau"),
        )
        assertEquals("Ce compte t'est partagé en lecture : tu lis ses discussions, sans y écrire.", readOnlyLine(Levels.READ, ""))
    }

    // ── la citation (ADR 0305) ──

    @Test fun `« Citer » s'offre dans un tête-à-tête ou un groupe, sur un compte où tu écris, d'un message qui a sa référence`() {
        val m = msg()
        assertTrue(citable(m, Kinds.GROUP, account()))
        assertTrue(citable(m, Kinds.DM, account()))
        // tes propres messages se citent aussi, comme dans Teams
        assertTrue(citable(msg(own = true), Kinds.DM, account()))
        // un partage pour t'en servir : tu y écris, donc tu y cites
        assertTrue(citable(m, Kinds.GROUP, account(level = Levels.USE, owner = "Léa")))
        // un canal ou une réunion : une réponse y est un fil, le serveur n'y cite pas
        assertFalse(citable(m, Kinds.CHANNEL, account()))
        assertFalse(citable(m, Kinds.MEETING, account()))
        assertFalse(citable(m, Kinds.OTHER, account()))
        // en lecture (ou un compte pas encore lu), pas de champ : rien ne se cite
        assertFalse(citable(m, Kinds.GROUP, account(level = Levels.READ)))
        assertFalse(citable(m, Kinds.GROUP, account(level = Levels.PREPARE)))
        assertFalse(citable(m, Kinds.GROUP, null))
        assertFalse(citable(m.copy(ref = " "), Kinds.GROUP, account()))
    }

    @Test fun `l'extrait d'un message cité tient sur une ligne, et son heure en petit`() {
        assertEquals("On se voit à 15 h ? Dis-moi.", quoteExcerpt("  On se voit\nà 15 h ?\n\n  Dis-moi. "))
        assertEquals("", quoteExcerpt(" \n "))
        assertEquals("14:30", quoteWhen(at(2026, 11, 4, 14, 30), now, paris))
        assertEquals("hier 21:41", quoteWhen(at(2026, 11, 3, 21, 41), now, paris))
        assertEquals("lun. 08:12", quoteWhen(at(2026, 11, 2, 8, 12), now, paris))
        assertEquals("28 oct. 13:31", quoteWhen(at(2026, 10, 28, 13, 31), now, paris))
        assertEquals("", quoteWhen(0, now, paris))
    }

    @Test fun `une citation mène au message cité quand il est chargé, son auteur sinon celui du message`() {
        val loaded = listOf(msg(at = now - 3 * min, text = "La démo ?"), msg(at = now - min, own = true, text = "Je regarde"))
        val cited = TeamsQuote(author = "Marc Delmas", authorId = "8:marc", preview = "La démo ?", at = now - 3 * min, ref = loaded[0].ref)
        assertEquals(loaded[0].ref, quoteTarget(cited, loaded))
        // pas chez Mika (`ref` vide), ou plus ancien que ce qui est chargé : nulle part
        assertNull(quoteTarget(cited.copy(ref = ""), loaded))
        assertNull(quoteTarget(cited.copy(ref = "t-ailleurs"), loaded))
        assertEquals("Marc Delmas", quoteAuthor(cited, loaded, account()))
        // une citation sans nom : celui du message qu'elle désigne, comme le fil le nomme (« Toi » sur un compte à toi)
        assertEquals("Toi", quoteAuthor(TeamsQuote(ref = loaded[1].ref), loaded, account()))
        assertEquals("Quelqu'un", quoteAuthor(TeamsQuote(ref = ""), loaded, account()))
    }

    @Test fun `depuis quand, en mots`() {
        assertEquals("jamais", ago(0, now))
        assertEquals("à l'instant", ago(now - 30_000, now))
        assertEquals("il y a 5 min", ago(now - 5 * min, now))
        assertEquals("il y a 3 h", ago(now - 3 * 3600_000L, now))
        assertEquals("il y a 2 j", ago(now - 48 * 3600_000L, now))
    }
}
