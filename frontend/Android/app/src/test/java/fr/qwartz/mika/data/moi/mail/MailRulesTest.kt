package fr.qwartz.mika.data.moi.mail

import fr.qwartz.mika.data.moi.Caps
import fr.qwartz.mika.data.moi.Levels
import fr.qwartz.mika.data.moi.SendKey
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.moi.caps
import fr.qwartz.mika.data.moi.chars
import fr.qwartz.mika.data.moi.ofName
import fr.qwartz.mika.data.moi.refusalText
import fr.qwartz.mika.data.moi.toFill
import fr.qwartz.mika.data.moi.toFillRanges
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Les règles de Mail, portées du client web (`frontendv2/src/screens/mail/format.ts`, `markup.ts`) : ce qu'un niveau
 * ouvre, les vues et leurs paramètres (ADR 0200), à qui répondre, ce qui peut partir, ce qu'on peut joindre, les
 * passages à compléter, ses brouillons, la clé d'envoi d'un geste.
 */
class MailRulesTest {
    private fun box(
        key: String,
        level: String = Levels.OWNER,
        owner: String = "",
        unseen: Int = 0,
        waiting: Int = 0,
        folders: List<MailFolder> = listOf(MailFolder("INBOX", "Réception", "inbox", true, 10, unseen)),
    ) = MailBox(key = key, name = key.replaceFirstChar { it.uppercase() }, address = "$key@example.test", level = level, ownerName = owner, draftsWaiting = waiting, folders = folders, canSend = true)

    // ── les niveaux (ADR 0188) ──

    @Test fun `ce qu'un niveau ouvre`() {
        assertEquals(Caps(own = true, prepare = true, write = true, decide = true), caps(Levels.OWNER))
        assertEquals(Caps(own = false, prepare = true, write = true, decide = false), caps(Levels.USE))
        assertEquals(Caps(own = false, prepare = true, write = false, decide = false), caps(Levels.PREPARE))
        assertEquals(Caps(own = false, prepare = false, write = false, decide = false), caps(Levels.READ))
        assertEquals(Caps(own = false, prepare = false, write = false, decide = false), caps("autre"))
    }

    @Test fun `une forme sans niveau n'ouvre que la lecture`() {
        assertEquals(Levels.READ, MailBox().level)
    }

    @Test fun `de Léa, d'Adrien, d'Hélène, d'Élodie`() {
        assertEquals("de Léa", ofName("Léa"))
        assertEquals("d'Adrien", ofName("Adrien"))
        assertEquals("d'Hélène", ofName("Hélène"))
        assertEquals("d'Élodie", ofName("Élodie"))
        assertEquals("", ofName(""))
    }

    @Test fun `une boîte partagée se nomme à son propriétaire, son nom en plus s'il en partage plusieurs`() {
        val pro = box("pro", Levels.READ, "Adrien Moreau")
        val perso = box("perso", Levels.USE, "Adrien Moreau")
        assertEquals("Boîte d'Adrien", boxTitle(pro, listOf(pro)))
        assertEquals("Pro d'Adrien", boxTitle(pro, listOf(pro, perso)))
        assertEquals("Pro", boxTitle(box("pro"), emptyList()))
    }

    // ── les vues (ADR 0200) ──

    @Test fun `toutes les réceptions lisent INBOX, sauf Suivis et Réponse attendue qui valent pour tous les dossiers`() {
        assertEquals(
            mapOf("box" to null, "folder" to "INBOX", "state" to null, "q" to null, "page" to "1", "size" to "25"),
            messagesQuery(MailView.All, MailStates.ALL, "", 1, 25),
        )
        assertEquals("INBOX", messagesQuery(MailView.All, MailStates.UNREAD, "", 1, 25)["folder"])
        assertEquals("INBOX", messagesQuery(MailView.All, MailStates.NOTICED, "", 1, 25)["folder"])
        assertNull(messagesQuery(MailView.All, MailStates.FLAGGED, "", 1, 25)["folder"])
        assertNull(messagesQuery(MailView.All, MailStates.NEEDS_REPLY, "", 1, 25)["folder"])
    }

    @Test fun `un dossier se lit dans sa boîte, avec son filtre et la recherche`() {
        val q = messagesQuery(MailView.Folder("lea", "Archives"), MailStates.UNREAD, "  devis ", 3, 25)
        assertEquals("lea", q["box"])
        assertEquals("Archives", q["folder"])
        assertEquals("unread", q["state"])
        assertEquals("devis", q["q"])
        assertEquals("3", q["page"])
    }

    @Test fun `une boîte partagée en lecture reste hors des comptes communs`() {
        val boxes = listOf(box("pro", unseen = 2, waiting = 1), box("lea", Levels.READ, "Léa", unseen = 5, waiting = 3))
        assertEquals(2, allUnseen(boxes))
        assertEquals(listOf("pro"), commonBoxes(boxes).map { it.key })
        // ses brouillons ne comptent que dans tes boîtes : dans une boîte partagée, son propriétaire décide
        assertEquals(1, waitingYours(boxes))
        assertEquals(0, waitingYours(boxes, MailView.Folder("lea", "INBOX")))
        assertFalse(manyBoxes(MailView.All, boxes))
        assertTrue(manyBoxes(MailView.All, boxes + box("perso")))
    }

    @Test fun `le titre est la vue`() {
        val pro = box(
            "pro",
            folders = listOf(MailFolder("INBOX", "Réception", "inbox"), MailFolder("Archive", "Archives", "archive")),
        )
        val lea = box("lea", Levels.READ, "Léa Martin")
        val boxes = listOf(pro, lea)
        assertEquals("Toutes les réceptions", viewTitle(MailView.All, boxes))
        assertEquals("Pro", viewTitle(MailView.Folder("pro", "INBOX"), boxes))
        assertEquals("Archives", viewTitle(MailView.Folder("pro", "Archive"), boxes))
        assertEquals("Boîte de Léa", viewTitle(MailView.Folder("lea", "INBOX"), boxes))
        assertEquals("Envoyés", viewTitle(MailView.Sent("pro"), boxes))
    }

    @Test fun `les dossiers dans l'ordre de la maquette, et où déplacer`() {
        val b = box(
            "pro",
            folders = listOf(
                MailFolder("Clients", "Clients"), MailFolder("Trash", "Corbeille", "trash"), MailFolder("INBOX", "Réception", "inbox"),
                MailFolder("Sent", "Envoyés", "sent"), MailFolder("Drafts", "Brouillons", "drafts"), MailFolder("Archive", "Archives", "archive"),
            ),
        )
        assertEquals(listOf("INBOX", "Sent", "Drafts", "Archive", "Trash", "Clients"), orderedFolders(b).map { it.name })
        assertEquals(listOf("Archive", "Trash", "Clients"), moveTargets(b, "INBOX").map { it.name })
        assertEquals(MailView.Sent("pro"), viewOf(b, b.folders[3]))
        assertNull(viewOf(b, b.folders[4]))
        assertEquals(MailView.Folder("pro", "Clients"), viewOf(b, b.folders[0]))
    }

    // ── à qui répondre ──

    private fun mail(
        from: MailPerson = MailPerson("Léa Martin", "lea@example.test"),
        to: List<MailPerson> = listOf(MailPerson("", "pro@example.test"), MailPerson("Marc", "marc@example.test")),
        cc: List<MailPerson> = listOf(MailPerson("Nadia", "nadia@example.test")),
        replyTo: String = "",
        sent: Boolean = false,
        received: Boolean = false,
    ) = MailFull(ref = "pro:<1@x>", box = "pro", from = from, to = to, cc = cc, replyTo = replyTo, sent = sent, received = received, subject = "Maquettes")

    @Test fun `répondre à l'expéditeur, ou à son adresse de réponse`() {
        assertEquals(listOf("lea@example.test"), replyTargets(mail(), "pro@example.test", false).first.map { it.address })
        val (to, cc) = replyTargets(mail(replyTo = "Équipe <equipe@example.test>"), "pro@example.test", false)
        assertEquals(listOf(MailPerson("Équipe", "equipe@example.test")), to)
        assertTrue(cc.isEmpty())
    }

    @Test fun `répondre à tous met les autres en copie, sans la boîte elle-même`() {
        val (to, cc) = replyTargets(mail(), "pro@example.test", true)
        assertEquals(listOf("lea@example.test"), to.map { it.address })
        assertEquals(listOf("marc@example.test", "nadia@example.test"), cc.map { it.address })
    }

    @Test fun `un mail parti de ta boîte se répond à ses destinataires`() {
        val m = mail(from = MailPerson("", "pro@example.test"), sent = true, received = true)
        assertEquals(listOf("marc@example.test"), replyTargets(m, "pro@example.test", false).first.map { it.address })
        assertTrue(answerable(m))
        assertFalse(answerable(m.copy(received = false)))
    }

    @Test fun `Re et Tr une seule fois`() {
        assertEquals("Re: Maquettes", replySubject("Maquettes"))
        assertEquals("RE : Maquettes", replySubject("RE : Maquettes"))
        assertEquals("Ré: Maquettes", replySubject("Ré: Maquettes"))
        assertEquals("Tr : Maquettes", forwardSubject("Maquettes"))
        assertEquals("Fwd: Maquettes", forwardSubject("Fwd: Maquettes"))
    }

    // ── les adresses ──

    @Test fun `les destinataires d'un en-tête, noms cités compris`() {
        val got = parseAddresses("Léa <LEA@Example.test>, \"Dubois, Claire\" <c@x.fr>; nadia@x.fr, pas-une-adresse")
        assertEquals(
            listOf(MailPerson("Léa", "lea@example.test"), MailPerson("Dubois, Claire", "c@x.fr"), MailPerson("", "nadia@x.fr")),
            got,
        )
    }

    @Test fun `un nom à virgule se cite en le relisant`() {
        assertEquals("\"Dubois, Claire\" <c@x.fr>", addressText(MailPerson("Dubois, Claire", "c@x.fr")))
        assertEquals("c@x.fr", addressText(MailPerson("c@x.fr", "c@x.fr")))
        assertEquals("Léa <l@x.fr>", addressText(MailPerson("Léa", "l@x.fr")))
        assertEquals(parseAddresses(addressText(MailPerson("Dubois, Claire", "c@x.fr"))), listOf(MailPerson("Dubois, Claire", "c@x.fr")))
    }

    @Test fun `sans doublon d'adresse, en écartant celles qu'on dit`() {
        val people = listOf(MailPerson("A", "a@x"), MailPerson("A bis", "A@X"), MailPerson("B", "b@x"))
        assertEquals(listOf("a@x"), uniquePeople(people, listOf("b@x")).map { it.address })
    }

    // ── ce qui peut partir ──

    @Test fun `des caractères, pas des unités UTF-16`() {
        assertEquals(1, chars("😀"))
        assertEquals("abc…", clip("abcdef", 4))
        assertEquals("😀😀…", clip("😀😀😀😀", 3))
        assertEquals("abc", clip("abc", 3))
    }

    @Test fun `trop de destinataires nommés, leurs adresses seules, sinon rien`() {
        val people = (1..10).map { MailPerson("Quelqu'un au nom assez long n°$it", "p$it@example.test") }
        val got = recipientsText(people)!!
        assertFalse(got.contains("Quelqu'un"))
        assertNull(recipientsText((1..30).map { MailPerson("", "personne$it@example.test") }))
    }

    @Test fun `ce qui manque à un envoi se dit, dans l'ordre`() {
        val to = listOf(MailPerson("Léa", "lea@x.fr"))
        assertEquals("À qui ? Ajoute au moins un destinataire.", checkOutgoing(emptyList(), emptyList(), emptyList(), "Objet", "Texte").problem)
        assertEquals("Il lui faut un objet.", checkOutgoing(to, emptyList(), emptyList(), " ", "Texte").problem)
        assertEquals("Le message est vide.", checkOutgoing(to, emptyList(), emptyList(), "Objet", "  ").problem)
        assertNull(checkOutgoing(to, emptyList(), emptyList(), "Objet", "", bodyRequired = false).problem.ifEmpty { null })
        assertTrue(checkOutgoing(to, emptyList(), emptyList(), "Objet", "le [À COMPLÉTER : date]").problem.contains("COMPLÉTER"))
        assertTrue(checkOutgoing(to, emptyList(), emptyList(), "Objet", "le [À COMPLÉTER : date]", fillChecked = false).mail != null)
        assertTrue(checkOutgoing(to, emptyList(), emptyList(), "x".repeat(201), "Texte").problem.startsWith("L'objet est trop long : 200"))
        assertTrue(checkOutgoing(to, emptyList(), emptyList(), "Objet", "x".repeat(20_001)).problem.contains("20 000"))
    }

    @Test fun `un envoi prêt porte ses en-têtes`() {
        val got = checkOutgoing(listOf(MailPerson("Léa", "lea@x.fr")), listOf(MailPerson("", "m@x.fr")), emptyList(), " Bonjour ", "Texte").mail!!
        assertEquals(Outgoing("Léa <lea@x.fr>", "m@x.fr", "", "Bonjour", "Texte"), got)
    }

    // ── les pièces ──

    private data class P(override val name: String, override val size: Long) : Sized

    @Test fun `joindre dans les bornes, vide, trop grosse, trop nombreuses, trop lourdes`() {
        val mo = 1024L * 1024
        assertEquals("« vide.txt » est vide.", addPieces(emptyList(), listOf(P("vide.txt", 0))).problem)
        assertTrue(addPieces(emptyList(), listOf(P("gros.zip", 26 * mo))).problem.contains("25 Mo par pièce"))
        val ten = (1..10).map { P("f$it", 1) }
        assertTrue(addPieces(ten, listOf(P("onzième", 1))).problem.contains("10 pièces"))
        val heavy = addPieces(listOf(P("a", 24 * mo), P("b", 24 * mo)), listOf(P("c", 3 * mo), P("d", 1 * mo)))
        assertEquals(listOf("a", "b", "d"), heavy.pieces.map { it.name })
        assertTrue(heavy.problem.contains("50 Mo en tout"))
    }

    @Test fun `le même fichier ne compte qu'une fois, et un transfert compte ses pièces d'origine`() {
        val got = addPieces(listOf(P("a.pdf", 10)), listOf(P("a.pdf", 10), P("b.pdf", 20)))
        assertEquals(listOf("a.pdf", "b.pdf"), got.pieces.map { it.name })
        assertEquals("", got.problem)
        val carried = (1..10).map { P("o$it", 1) }
        assertTrue(addPieces(emptyList(), listOf(P("x", 1)), carried).problem.contains("celles du mail d'origine comprises"))
    }

    // ── à compléter ──

    @Test fun `un passage à compléter, sous toutes ses graphies`() {
        assertTrue(toFill("Nous pourrions démarrer le [À COMPLÉTER : date]."))
        assertTrue(toFill("[a completer]"))
        assertTrue(toFill("[ À remplir ]"))
        assertTrue(toFill("[à préciser]"))
        assertTrue(toFill("［À COMPLÉTER］"))
        assertFalse(toFill("A COMPLETER"))
        assertFalse(toFill("[complété]", "rien"))
    }

    @Test fun `les passages à compléter se surlignent, pas les autres crochets`() {
        val text = "Voir [annexe] puis le [À COMPLÉTER : date] et [à préciser"
        val ranges = toFillRanges(text)
        assertEquals(listOf("[À COMPLÉTER : date]", "[à préciser"), ranges.map { text.substring(it) })
    }

    // ── ses brouillons ──

    @Test fun `l'état d'un brouillon, en mots`() {
        assertEquals(Tone.WARN to "attend ton accord", draftState(MailDraft(state = DraftStates.WAITING, decides = true)))
        assertEquals(Tone.WARN to "attend son propriétaire", draftState(MailDraft(state = DraftStates.WAITING)))
        assertEquals(Tone.OK to "parti · retouché par toi", draftState(MailDraft(state = DraftStates.SENT, edited = true)))
        assertEquals(Tone.DANGER to "échec de l'envoi", draftState(MailDraft(state = DraftStates.FAILED)))
        assertEquals(Tone.NEUTRAL to "refusé", draftState(MailDraft(state = DraftStates.REFUSED, edited = true)))
    }

    @Test fun `ce qui bloque un brouillon`() {
        assertEquals("un [À COMPLÉTER] reste", draftBlocked(MailDraft(state = DraftStates.WAITING, preview = DraftPreview(blocked = "un [À COMPLÉTER] reste"))))
        assertEquals("il reste des passages à compléter", draftBlocked(MailDraft(state = DraftStates.WAITING, toFill = true, preview = DraftPreview())))
        assertEquals("", draftBlocked(MailDraft(state = DraftStates.SENT, toFill = true)))
    }

    @Test fun `ses brouillons se trient par filtre`() {
        val drafts = listOf(DraftStates.WAITING, DraftStates.APPROVED, DraftStates.SENT, DraftStates.REFUSED, DraftStates.FAILED).map { MailDraft(state = it) }
        assertEquals(1, drafts.count { DraftFilter.WAITING.holds(it) })
        assertEquals(2, drafts.count { DraftFilter.SENT.holds(it) })
        assertEquals(2, drafts.count { DraftFilter.REFUSED.holds(it) })
    }

    @Test fun `sa voix et ce qu'elle a fait, en mots`() {
        assertEquals("à ta place", voiceLabel("proprietaire"))
        assertEquals("en assistante", voiceLabel("assistante"))
        assertEquals("", voiceLabel("?"))
        assertEquals("lu par Mika" to "eye", howLabel(""))
        assertEquals("archivé par Mika" to "archive", howLabel("archivé"))
        assertEquals("mis à la corbeille par Mika" to "trash", howLabel("corbeille"))
    }

    @Test fun `ses destinataires à leur nom, sinon l'en-tête`() {
        assertEquals(listOf("Léa"), draftPeople(MailDraft(to = "lea@x.fr", toPeople = listOf(MailPerson("Léa", "lea@x.fr")))).map { it.shown })
        assertEquals(listOf("m@x.fr"), draftPeople(MailDraft(to = "m@x.fr")).map { it.shown })
    }

    @Test fun `le cœur d'un brouillon en une ligne`() {
        assertEquals("Merci pour ta relecture.", bodyLead("Salut Claire,\n\nMerci pour ta relecture.\n\nAdrien"))
        assertEquals("Un seul paragraphe assez long pour ne pas être une formule d'appel, voilà.", bodyLead("Un seul paragraphe assez long pour ne pas être une formule d'appel, voilà."))
    }

    @Test fun `à qui il est allé, ta boîte dite toi`() {
        val own = box("pro")
        assertEquals("à toi <pro@example.test>, Marc <marc@example.test>", toLine(mail(), own))
        val shared = box("pro", Levels.USE, "Adrien Moreau")
        assertTrue(toLine(mail(), shared).startsWith("à Adrien <pro@example.test>"))
    }

    // ── les refus ──

    @Test fun `un refus dit ses champs, seuls quand le message ne fait que les nommer`() {
        assertEquals("Message : 20000 caractères au plus", refusalText("« body » : 20000 caractères au plus.", mapOf("body" to "20000 caractères au plus")))
        assertEquals("Adresse invalide. (À : pas une adresse)", refusalText("Adresse invalide.", mapOf("to" to "pas une adresse")))
        assertEquals("Déjà décidé.", refusalText("Déjà décidé.", emptyMap()))
    }

    // ── ta réponse partie de son brouillon (R2-02) ──

    @Test fun `ta réponse partie de son brouillon - une réponse ordinaire seulement s'il est refusé ou plus là`() {
        val d = MailDraft(id = "d1", state = DraftStates.WAITING)
        assertEquals(DraftReply.Through(d), draftReply(listOf(d), "d1"))
        assertEquals(DraftReply.Plain, draftReply(listOf(d.copy(state = DraftStates.REFUSED)), "d1"))
        assertEquals(DraftReply.Plain, draftReply(listOf(d.copy(id = "d2")), "d1"))
        assertEquals(DraftReply.Plain, draftReply(emptyList(), "d1"))
        assertEquals(DraftReply.Stop("Son brouillon est déjà parti."), draftReply(listOf(d.copy(state = DraftStates.SENT)), "d1"))
        assertEquals(DraftReply.Stop("Son brouillon est déjà parti."), draftReply(listOf(d.copy(state = DraftStates.APPROVED)), "d1"))
        assertTrue(draftReply(listOf(d.copy(state = DraftStates.FAILED)), "d1") is DraftReply.Stop)
        assertTrue(draftReply(listOf(d.copy(state = "futur")), "d1") is DraftReply.Stop)
    }

    // ── la liste et sa page suivante (R2-06) ──

    @Test fun `un rangement change les lignes montrées - archivées, elles s'en vont`() {
        val rows = (1..4).map { MailRow(ref = "r$it", seen = false) }
        assertEquals(listOf("r1", "r4"), tidiedRows(rows, setOf("r2", "r3"), "archive").map { it.ref })
        assertEquals(listOf("r1", "r4"), tidiedRows(rows, setOf("r2", "r3"), "move").map { it.ref })
        assertEquals(listOf(false, true, false, false), tidiedRows(rows, setOf("r2"), "read").map { it.seen })
        assertEquals(listOf(false, false, true, false), tidiedRows(rows, setOf("r3"), "flag").map { it.flagged })
    }

    @Test fun `ce qui a pu quitter la vue du serveur - ce qui s'en va, et sous un filtre ce qui change`() {
        val rows = (1..4).map { MailRow(ref = "r$it") }
        assertEquals(2, leftView(rows, setOf("r1", "r2", "ailleurs"), "trash", MailStates.ALL))
        assertEquals(0, leftView(rows, setOf("r1"), "read", MailStates.ALL))
        assertEquals(1, leftView(rows, setOf("r1"), "read", MailStates.UNREAD))
    }

    @Test fun `la page où reprendre contient la première ligne pas encore lue, reculée de ce qui est parti`() {
        assertEquals(5, nextPage(read = 100, drift = 0, size = 25))
        // trois rangées : le 101ᵉ mail du serveur est devenu le 98ᵉ, dans la page 4
        assertEquals(4, nextPage(read = 97, drift = 3, size = 25))
        assertEquals(1, nextPage(read = 2, drift = 5, size = 25))
    }

    // ── la clé d'envoi ──

    @Test fun `un double appui garde la clé, une réponse du serveur en donne une neuve`() {
        var n = 0
        val keys = SendKey { "k${++n}" }
        val first = keys.of("mail A")
        assertEquals(first, keys.of("mail A"))
        keys.settled(networkFailure = true)
        assertEquals(first, keys.of("mail A"))
        assertNotEquals(first, keys.of("mail B"))
        val second = keys.of("mail B")
        keys.settled(networkFailure = false)
        assertNotEquals(second, keys.of("mail B"))
    }
}
