package fr.qwartz.mika.data.moi.phone

import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.phone.PhoneDraft
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Les règles du Téléphone, portées du client web (`frontendv2/src/screens/telephone/view.ts`, ses tests
 * `view.test.ts`) : le sort d'une proposition et ce qui s'en décide d'ici, l'appli, le fil et ses jours, l'état de tes
 * téléphones (ADR 0233) et « ce téléphone », la position, son plan et le regard de Mika.
 */
class PhoneRulesTest {
    private val paris = ZoneId.of("Europe/Paris")
    private fun at(d: Int, h: Int, mi: Int = 0): Long = LocalDateTime.of(2026, 11, d, h, mi).atZone(paris).toInstant().toEpochMilli()

    private val now = at(4, 15) // un mercredi
    private val min = 60_000L
    private val thread = "611ae22e6d5c431f8b537e638278435d"
    private val key = "whatsapp|$thread"

    private fun conv(her: HerReply? = null, group: Boolean = false, last: ReadMessage? = ReadMessage("p34", at(4, 12, 52), false, "Julien Roux", "Dis-moi vite")) =
        PhoneConversation(key, "whatsapp", "WhatsApp", group, "Julien Roux", 2, at(4, 12, 52), last, her)

    private fun offer(state: String = OfferStates.OFFERED, id: Long = 7, at: Long = at(4, 14, 20)) =
        PhoneOffer(id, state, at, at(4, 16, 20), 0, "", "p34", "Oui !")

    private fun draft(id: Long = 7, exp: Long = at(4, 16, 20), thread: String = this.thread, app: String = "whatsapp") =
        PhoneDraft(id, app, thread, "Julien", "Oui ! j'arrive", exp, at(4, 14, 20))

    private fun phone(id: Long, label: String = "Android · samsung SM-S931B", lastUsed: Long = now - 4 * min, push: Boolean = true, revoked: Boolean = false) =
        PhoneDevice(id, label, at(1, 9), lastUsed, revoked, push)

    // ── Ses propositions ──

    @Test fun `chaque sort d'une proposition se dit en français, avec son ton`() {
        assertEquals(Tone.MIKA to "préparée", offerWords("prepared"))
        assertEquals(Tone.WARN to "au téléphone — attend ton geste", offerWords("offered"))
        assertEquals(Tone.OK to "envoyée", offerWords("sent"))
        assertEquals("tu as écrit autre chose", offerWords("other").second)
        assertEquals("copiée", offerWords("copied").second)
        assertEquals("laissée", offerWords("ignored").second)
        assertEquals(Tone.DANGER to "échec", offerWords("failed"))
        assertEquals("expirée", offerWords("expired").second)
        assertEquals(Tone.NEUTRAL to "inconnu", offerWords("inconnu"))
        assertTrue(underWay("prepared") && underWay("offered"))
        assertFalse(underWay("sent"))
        assertEquals("Mika propose de répondre", offerTitle("offered"))
        assertEquals("Réponse de Mika", offerTitle("copied"))
        assertEquals("Réponse de Mika, non partie", offerTitle("expired"))
    }

    @Test fun `une conversation se marque d'après sa réponse, seulement quand c'est une nouvelle`() {
        assertEquals(Tone.MIKA to "réponse proposée", herMark("prepared"))
        assertEquals(Tone.MIKA to "réponse proposée", herMark("offered"))
        assertEquals(Tone.OK to "Mika a répondu", herMark("sent"))
        assertEquals(Tone.INFO to "copiée", herMark("copied"))
        assertEquals(Tone.DANGER to "échec", herMark("failed"))
        for (state in listOf("other", "ignored", "expired")) assertNull(herMark(state))
        assertNull(herMark(null))
    }

    @Test fun `la clé d'une conversation donne son appli et le fil de l'action « Répondre »`() {
        assertEquals("whatsapp", appPart(key))
        assertEquals(thread, threadPart(key))
        assertEquals("", threadPart("sans-barre"))
    }

    @Test fun `seule une proposition offerte et tenue par ce téléphone se décide d'ici`() {
        val waiting = listOf(draft())
        assertEquals(draft(), decidableHere(offer(), key, waiting, now))
        // pas encore au téléphone, ou déjà réglée
        assertNull(decidableHere(offer(OfferStates.PREPARED), key, waiting, now))
        assertNull(decidableHere(offer(OfferStates.SENT), key, waiting, now))
        // un autre téléphone l'a reçue : celui-ci ne la tient pas
        assertNull(decidableHere(offer(), key, emptyList(), now))
        assertNull(decidableHere(offer(id = 8), key, waiting, now))
        // expirée, ou pour une autre conversation, une autre appli
        assertNull(decidableHere(offer(), key, waiting, at(4, 16, 20)))
        assertNull(decidableHere(offer(), key, listOf(draft(thread = "0".repeat(32))), now))
        assertNull(decidableHere(offer(), key, listOf(draft(app = "messages")), now))
    }

    @Test fun `ce que tu as décidé d'ici se montre tant que le serveur dit qu'elle attend`() {
        val decided = mapOf(7L to OfferStates.SENT)
        assertEquals(OfferStates.SENT, shownState(offer(), decided))
        assertEquals(OfferStates.OFFERED, shownState(offer(), emptyMap()))
        // le serveur l'a appris (ou dit autre chose) : sa parole reprend
        assertEquals(OfferStates.EXPIRED, shownState(offer(OfferStates.EXPIRED), decided))
    }

    @Test fun `le bandeau dit la conversation, et ce que ce téléphone tient, le début du texte et l'échéance`() {
        val offered = conv(HerReply(OfferStates.OFFERED, 7))
        val list = listOf(conv(), offered.copy(key = "whatsapp|${"a".repeat(32)}", her = HerReply("prepared", 9)), offered)
        assertEquals(2, proposals(list).size)
        assertEquals(draft(), draftFor(offered, listOf(draft())))
        assertNull(draftFor(conv(), listOf(draft())))
        assertEquals("Julien Roux · « Oui ! j'arrive » · expire dans 1 h 20", proposalLine(offered, draft(), now))
        assertEquals("Julien Roux", proposalLine(offered, null, now))
    }

    @Test fun `le début d'un texte tient sur une ligne, coupé sans casser un émoji`() {
        assertEquals("court", lead("court", 10))
        assertEquals("première…", lead("première\nseconde", 20))
        assertEquals("abcde…", lead("abcdefgh", 5))
        assertEquals("ab👍…", lead("ab👍👍👍", 3))
    }

    // ── Les conversations ──

    @Test fun `le dernier message dit qui l'a écrit, dans un groupe ou quand c'est toi`() {
        assertEquals("Dis-moi vite", snippetOf(conv()))
        assertEquals("Thomas : Dis-moi vite", snippetOf(conv(group = true, last = ReadMessage("p1", 0, false, "Thomas Girard", "Dis-moi vite"))))
        assertEquals("Toi : Dis-moi vite", snippetOf(conv(last = ReadMessage("p1", 0, true, "", "Dis-moi vite"))))
        assertEquals("", snippetOf(conv(last = null)))
    }

    @Test fun `une conversation sans nom prend celui de son appli`() {
        assertEquals("Julien Roux", conversationTitle(conv()))
        assertEquals("WhatsApp", conversationTitle(" ", "WhatsApp"))
        assertEquals("Conversation", conversationTitle("", ""))
    }

    @Test fun `un fil se nomme comme la liste, et dit son appli et qui écrit dans un groupe`() {
        val solo = PhoneThread(key, "whatsapp", "WhatsApp", false, "", listOf(ReadMessage("p1", at(4, 9), false, "Léa", "coucou"), ReadMessage("p2", at(4, 10), true, "", "salut")))
        assertEquals("Léa", threadTitle(solo))
        assertEquals("WhatsApp", threadSubtitle(solo))
        val group = PhoneThread(
            key, "whatsapp", "WhatsApp", true, "Rando dimanche 🥾",
            listOf("Thomas Girard", "Camille", "Julien Roux", "Thomas Girard").mapIndexed { i, n -> ReadMessage("p$i", at(4, 10 + i), false, n, "…") },
        )
        assertEquals("Rando dimanche 🥾", threadTitle(group))
        assertEquals("WhatsApp · Thomas, Julien, Camille", threadSubtitle(group))
        assertEquals("Groupe Messages", threadSubtitle(group.copy(appName = "Messages", messages = emptyList())))
    }

    @Test fun `chaque appli a sa couleur et sa lettre`() {
        assertEquals(AppBadge(AppKind.WHATSAPP, "W"), appBadge("whatsapp_business", "WhatsApp Business"))
        assertEquals(AppBadge(AppKind.MESSAGES, "M"), appBadge("samsung_messages", "Messages"))
        assertEquals(AppBadge(AppKind.MESSENGER, "M"), appBadge("messenger", "Messenger"))
        assertEquals(AppBadge(AppKind.OTHER, "S"), appBadge("signal", "son téléphone"))
        assertEquals(AppBadge(AppKind.OTHER, "?"), appBadge("x", " "))
    }

    // ── Le fil ──

    @Test fun `le fil range messages et propositions dans le temps, un repère par jour, la suite d'un même auteur serrée`() {
        val messages = listOf(
            ReadMessage("p1", at(3, 19, 2), false, "Julien", "t'es chaud ?"),
            ReadMessage("p2", at(4, 14, 8), false, "Julien", "alors, tu viens ?"),
            ReadMessage("p3", at(4, 14, 9), false, "Julien", "départ 8h30"),
            ReadMessage("p4", at(4, 14, 20), true, "", "je regarde"),
        )
        val items = timeline(messages, listOf(offer(at = at(4, 14, 20))), now, paris)
        assertEquals(
            listOf("Day:Hier", "p1", "Day:Aujourd'hui", "p2", "p3+", "p4", "offer:7"),
            items.map {
                when (it) {
                    is ThreadItem.Day -> "Day:${it.label}"
                    is ThreadItem.Message -> it.m.id + if (it.suite) "+" else ""
                    is ThreadItem.Offer -> "offer:${it.o.id}"
                }
            },
        )
    }

    @Test fun `ton message parti d'ici reste montré jusqu'à ce que le fil le dise, dix minutes au plus`() {
        val sent = SentHere(key, "J'arrive  à 9h", now - min)
        val other = SentHere("messages|${"b".repeat(32)}", "ok", now - min)
        val t = PhoneThread(key, "whatsapp", "WhatsApp", messages = listOf(ReadMessage("p9", now - 2 * min, true, "", "vieux")))
        assertEquals(listOf(sent, other), stillSentHere(listOf(sent, other), t, now))
        val back = t.copy(messages = t.messages + ReadMessage("p10", now - min + 5_000, true, "", "J'arrive à 9h"))
        assertEquals(listOf(other), stillSentHere(listOf(sent, other), back, now))
        assertTrue(stillSentHere(listOf(sent, other), t, now + SENT_HERE_MS).isEmpty())
    }

    // ── Tes téléphones (ADR 0233) ──

    @Test fun `ce téléphone est celui qui porte le nom que l'app compose, le plus récent s'ils sont deux`() {
        val label = "Android · samsung SM-S931B"
        assertEquals(2L, thisPhone(listOf(phone(1, lastUsed = now - 60 * min), phone(2), phone(3, "Android · Google Pixel 7a")), label, null)?.id)
        assertNull(thisPhone(listOf(phone(1, revoked = true)), label, null))
        assertNull(thisPhone(listOf(phone(3, "Android · Google Pixel 7a")), label, null))
        assertEquals("samsung SM-S931B", shortPhone(label))
        assertEquals("Téléphone", shortPhone(""))
    }

    @Test fun `la barre dit ce téléphone, sans redire qu'on le voit à l'instant, et s'il manque les notifications`() {
        val label = "Android · samsung SM-S931B"
        val one = phoneBar(listOf(phone(1)), label, null, now)
        assertEquals("Ce téléphone · samsung SM-S931B", one.line)
        assertFalse(one.warn)
        assertEquals("Ce téléphone (samsung SM-S931B), reçoit les notifications — Paramètres › Téléphones", one.description)
        val mute = phoneBar(listOf(phone(1, push = false)), label, null, now)
        assertEquals("Ce téléphone · samsung SM-S931B · ne reçoit pas les notifications", mute.line)
        assertTrue(mute.warn)
        // un autre téléphone seul (le nom a changé) : quand on l'a vu
        assertEquals("Google Pixel 7a · vu il y a 4 min", phoneBar(listOf(phone(3, "Android · Google Pixel 7a")), label, null, now).line)
    }

    @Test fun `plusieurs téléphones se comptent, révoqués à part, et aucun se dit`() {
        val label = "Android · samsung SM-S931B"
        val pixel = phone(3, "Android · Google Pixel 7a", lastUsed = at(3, 22, 10))
        val two = phoneBar(listOf(phone(1), pixel, phone(4, revoked = true)), label, null, now)
        assertEquals("2 téléphones · dont celui-ci", two.line)
        assertTrue(two.description.contains("ce téléphone (samsung SM-S931B) : reçoit les notifications"))
        assertTrue(two.description.contains("Google Pixel 7a : vu il y a 17 h, reçoit les notifications"))
        assertEquals("2 téléphones · 1 sur 2 ne reçoit pas les notifications", phoneBar(listOf(phone(1), pixel.copy(push = false)), label, null, now).line)
        assertEquals("aucun ne reçoit les notifications", pushNotes(listOf(phone(1, push = false), pixel.copy(push = false))))
        assertEquals("Aucun téléphone", phoneBar(listOf(phone(1, revoked = true)), label, null, now).line)
    }

    // ── Quand rien ne vient ──

    @Test fun `Messages vide dit pourquoi, pas propriétaire, la lecture coupée ici, ou rien encore`() {
        assertEquals(EmptyWhy.NOT_OWNER, emptyWhy(false, readingHere = true))
        assertEquals(EmptyWhy.READING_OFF, emptyWhy(true, readingHere = false))
        // son compte pas encore lu : le conseil d'une propriétaire
        assertEquals(EmptyWhy.READING_OFF, emptyWhy(null, readingHere = false))
        assertEquals(EmptyWhy.NOTHING_YET, emptyWhy(true, readingHere = true))
    }

    // ── La position ──

    @Test fun `une distance, des coordonnées, la fiche d'une position`() {
        assertEquals("12 m", distanceWords(12.0))
        assertEquals("1,3 km", distanceWords(1250.0))
        assertEquals("2 km", distanceWords(2000.0))
        assertEquals("", distanceWords(0.0))
        assertEquals("50.636512, 3.058271", coordsText(PhoneCoords(50.636512, 3.058271)))
        val p = PhonePosition(true, PhoneCoords(50.636512, 3.058271), "rue Nationale, Lille", 12.0, at(4, 14, 10))
        assertEquals("±12 m · mesurée à 14:10 · 50.636512, 3.058271", positionLine(p, now, paris))
        assertEquals("mesurée hier à 22:05", measuredWords(at(3, 22, 5), now, paris))
        assertEquals("mesurée lundi 2 novembre à 08:12", measuredWords(at(2, 8, 12), now, paris))
        assertEquals("", positionLine(PhonePosition(true, null, "", 0.0, 0), now, paris))
    }

    @Test fun `le plan montre 300 m au moins, quelques fois sa précision, et sa barre d'échelle d'un pas rond`() {
        val street = planScale(12.0, 300f)
        assertEquals(1.0, street.metersPerPx, 1e-9)
        assertEquals(12f, street.radiusPx, 1e-4f)
        assertEquals(100, street.stepM)
        assertEquals(100f, street.stepPx, 1e-4f)
        val wide = planScale(1500.0, 600f)
        assertEquals(7500.0 / 600, wide.metersPerPx, 1e-9)
        assertEquals(2000, wide.stepM)
        assertEquals(0f, planScale(0.0, 300f).radiusPx)
        assertEquals(0f, planScale(Double.NaN, 300f).radiusPx)
    }

    @Test fun `son regard se reconnaît à l'instant de la mesure qu'elle a regardée`() {
        val fix = at(4, 14, 10)
        val looks = listOf(Look(at(3, 9), at(3, 9, 2)), Look(fix + 400, at(4, 14, 12)), Look(fix, at(4, 14, 30)))
        val looked = lookedAt(looks, fix)
        assertEquals(at(4, 14, 30), looked.thisFix?.at)
        assertEquals(at(4, 14, 30), looked.last?.at)
        val other = lookedAt(looks.take(1), fix)
        assertNull(other.thisFix)
        assertEquals(at(3, 9, 2), other.last?.at)
        assertEquals(Looked(null, null), lookedAt(emptyList(), fix))
        assertEquals("à 14:12", whenWords(at(4, 14, 12), now, paris))
        assertEquals("hier à 09:02", whenWords(at(3, 9, 2), now, paris))
    }

    @Test fun `ce téléphone, reconnu au jeton de sa session plutôt qu'à son nom (R3-03)`() {
        val label = "Android · samsung SM-S931B"
        // le perdu (1) a servi après le neuf (2) : par son nom, on prendrait le mauvais
        val phones = listOf(phone(1, lastUsed = now - min), phone(2, lastUsed = now - 60 * min))
        assertEquals(1L, thisPhone(phones, label, null)?.id)
        assertEquals(2L, thisPhone(phones, label, 2)?.id)
        assertEquals("2 téléphones · dont celui-ci", phoneBar(phones, label, 2, now).line)
        // un jeton qui n'est pas parmi les actifs (révoqué) : aucun, jamais deviné
        assertNull(thisPhone(listOf(phone(2, revoked = true), phone(1)), label, 2))
    }

    @Test fun `à qui part ce qu'on envoie d'ici - l'action gardée, si elle répond à ce fil (R3-06)`() {
        val t = PhoneThread(key, "messages", "Messages", messages = listOf(
            ReadMessage("p1", now - 5 * min, false, "Maman", "Tu passes dimanche ?"),
            ReadMessage("p2", now - min, false, "Plombier", "Je passe demain à 8h"),
        ))
        assertEquals("Plombier", replyName(t))
        assertEquals(ReplyWay.Action("Plombier"), replyWay("Plombier", t))
        // deux téléphones, une même clé : l'action gardée ici répond à Maman, pas au Plombier en tête du fil
        assertEquals(ReplyWay.Other("Maman", "Plombier"), replyWay("Maman", t))
        assertEquals(ReplyWay.Copy, replyWay(null, t))
        assertEquals("Rando", replyName(PhoneThread(key, group = true, title = "Rando", messages = t.messages)))
    }
}
