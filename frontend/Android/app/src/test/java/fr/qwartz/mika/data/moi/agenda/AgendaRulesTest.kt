package fr.qwartz.mika.data.moi.agenda

import fr.qwartz.mika.data.moi.LiveSignal
import fr.qwartz.mika.data.moi.Tone
import fr.qwartz.mika.data.net.Topics
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.OffsetDateTime

/**
 * Les règles de l'Agenda (portées de `frontendv2/src/screens/agenda/agenda.test.ts`, et celles du téléphone : les cinq
 * vues, le titre de la barre, le Planning et sa ligne de l'heure, les cases du mois, « À décider », ce que notifie le
 * canal « Agenda », la carte d'un ajout dans le chat, l'état d'un compte, le tableau de droits d'un agenda).
 */
class AgendaRulesTest {
    private val paris = "Europe/Paris"

    /** Un instant de Paris (heure d'hiver, UTC+1). */
    private fun at(day: String, hhmm: String): Long = OffsetDateTime.parse("${day}T$hhmm:00+01:00").toInstant().toEpochMilli()

    private fun item(
        event: Int = 1,
        start: Long = at("2026-11-24", "17:30"),
        end: Long = at("2026-11-24", "18:00"),
        allDay: Boolean = false,
        firstDay: String = "",
        lastDay: String = "",
        title: String = "Dentiste",
        masked: Boolean = false,
        invitation: Boolean = false,
        response: String = "",
        calendar: String = "moi:a~mon-agenda",
    ) = AgendaItem(
        event = event, calendar = calendar, title = title, masked = masked, start = start, end = end, allDay = allDay,
        firstDay = firstDay, lastDay = lastDay, zone = paris, invitation = invitation, response = response,
    )

    private fun cal(
        key: String = "moi:a~mon-agenda",
        kind: String = AgendaKinds.SYSTEM,
        level: String = AgendaLevels.OWNER,
        group: String = AgendaGroups.MINE,
        color: String = "",
        primary: Boolean = true,
        name: String = "Mon agenda",
        ownerName: String = "",
        writable: Boolean = true,
    ) = AgendaCalendar(
        key = key, account = "moi:a", name = name, kind = kind, level = level, group = group, color = color, primary = primary,
        ownerName = ownerName, writable = writable, reminder = "30", can = CalendarCan(write = writable, settings = true, share = true, rights = true, remind = true),
    )

    // ── les dates ──

    @Test fun `les jours se comptent sans heure d'ete, la semaine commence le lundi`() {
        assertEquals("2026-10-26", addDays("2026-10-24", 2))
        assertEquals(8, daysFrom("2026-11-23", "2026-12-01"))
        assertEquals("2026-11-23", mondayOf("2026-11-29"))
        assertEquals("2026-11-23", mondayOf("2026-11-23"))
    }

    @Test fun `chaque vue a ses bornes - trois jours compris`() {
        assertEquals("2026-11-23" to "2026-11-30", bounds(AgendaView.WEEK, "2026-11-25"))
        assertEquals("2026-11-25" to "2026-11-26", bounds(AgendaView.DAY, "2026-11-25"))
        assertEquals("2026-11-25" to "2026-11-28", bounds(AgendaView.THREE, "2026-11-25"))
        assertEquals("2026-10-26" to "2026-12-07", bounds(AgendaView.MONTH, "2026-11-25"))
        assertEquals("2026-11-24" to "2026-12-22", bounds(AgendaView.PLANNING, "2026-11-24"))
        assertEquals(listOf("2026-11-25", "2026-11-26", "2026-11-27"), gridDays(AgendaView.THREE, "2026-11-25"))
        assertEquals(7, gridDays(AgendaView.WEEK, "2026-11-25").size)
    }

    @Test fun `un pas change la periode, un mois qui revient a celui d'aujourd'hui y revient a aujourd'hui`() {
        assertEquals("2026-11-24", step(AgendaView.MONTH, "2026-10-03", 1, "2026-11-24"))
        assertEquals("2026-12-01", step(AgendaView.MONTH, "2026-11-24", 1, "2026-11-24"))
        assertEquals("2026-11-17", step(AgendaView.WEEK, "2026-11-24", -1, "2026-11-24"))
        assertEquals("2026-11-27", step(AgendaView.THREE, "2026-11-24", 1, "2026-11-24"))
        assertEquals("2026-12-22", step(AgendaView.PLANNING, "2026-11-24", 1, "2026-11-24"))
    }

    @Test fun `le titre de la barre - le mois, deux mois en court, l'annee si ce n'est pas la notre, le mois deplie`() {
        assertEquals("Novembre", barTitle(AgendaView.PLANNING, "2026-11-24", "2026-11-24"))
        assertEquals("Nov. – déc.", barTitle(AgendaView.WEEK, "2026-12-01", "2026-11-24"))
        assertEquals("Novembre", barTitle(AgendaView.WEEK, "2026-11-24", "2026-11-24"))
        assertEquals("Janvier 2027", barTitle(AgendaView.DAY, "2027-01-04", "2026-11-24"))
        assertEquals("Déc. – janv. 2027", barTitle(AgendaView.THREE, "2026-12-31", "2026-11-24"))
        assertEquals("Mars 2027", barTitle(AgendaView.MONTH, "2026-11-24", "2026-11-24", mini = "2027-03-01"))
    }

    @Test fun `le mini-mois a cinq ou six semaines a partir du lundi`() {
        val nov = monthDays("2026-11-12")
        assertEquals("2026-10-26", nov.first())
        assertEquals(42, nov.size)
        val feb = monthDays("2027-02-10")
        assertEquals(35, feb.size)
        assertEquals("2027-02-01", feb.first())
    }

    @Test fun `la vue Mois lit autant de semaines qu'elle en dessine`() {
        assertEquals("2027-02-01" to "2027-03-08", bounds(AgendaView.MONTH, "2027-02-01"))
        var month = "2026-01-01"
        repeat(36) {
            for (day in listOf(month, addDays(month, 14), addDays(month, 27))) {
                val drawn = monthDays(day)
                val (first, after) = bounds(AgendaView.MONTH, day)
                assertEquals(day, drawn.first() to addDays(drawn.last(), 1), first to after)
            }
            month = addMonths(month, 1)
        }
    }

    @Test fun `un instant se lit a l'heure du serveur, son decalage en mots`() {
        assertEquals(Local("2026-11-24", 17 * 60 + 30), localOf(OffsetDateTime.parse("2026-11-24T16:30:00Z").toInstant().toEpochMilli(), paris))
        assertEquals("2026-11-25", localOf(OffsetDateTime.parse("2026-11-24T23:30:00Z").toInstant().toEpochMilli(), paris).day)
        assertEquals("2026-07-01T10:00", localInput(OffsetDateTime.parse("2026-07-01T08:00:00Z").toInstant().toEpochMilli(), paris))
        assertEquals("UTC+1", offsetWords(paris, OffsetDateTime.parse("2026-11-24T12:00:00Z").toInstant().toEpochMilli()))
        assertEquals("UTC+2", offsetWords(paris, OffsetDateTime.parse("2026-07-01T12:00:00Z").toInstant().toEpochMilli()))
        assertEquals("UTC+5:30", offsetWords("Asia/Kolkata", OffsetDateTime.parse("2026-07-01T12:00:00Z").toInstant().toEpochMilli()))
        assertEquals("UTC", offsetWords("n'importe quoi", 0))
    }

    // ── ce que l'Agenda montre ──

    @Test fun `un rendez-vous, une journee entiere, plusieurs jours, un prive d'une autre`() {
        val o = occOfItem(item(), paris)
        assertEquals(listOf("2026-11-24", "2026-11-24", false, 1050, 1080), listOf(o.day, o.last, o.allDay, o.start, o.end))
        val d = occOfItem(item(allDay = true, firstDay = "2026-12-05", lastDay = "2026-12-06"), paris)
        assertEquals(listOf("2026-12-05", "2026-12-06", true), listOf(d.day, d.last, d.allDay))
        val long = occOfItem(item(start = at("2026-11-24", "09:00"), end = at("2026-11-26", "18:00")), paris)
        assertEquals(listOf("2026-11-24", "2026-11-26", true), listOf(long.day, long.last, long.allDay))
        val late = occOfItem(item(start = at("2026-11-24", "22:00"), end = at("2026-11-25", "01:00")), paris)
        assertEquals("2026-11-24", late.day)
        assertEquals(1440, late.end)
        assertEquals("Occupé", occOfItem(item(masked = true, title = ""), paris).title)
    }

    @Test fun `la sorte d'une occurrence - invitation, peut-etre, proposition de Mika, sa memoire`() {
        assertEquals(Sort.INVITED, sortOf(occOfItem(item(invitation = true, response = "attente"), paris)))
        assertEquals(Sort.MAYBE, sortOf(occOfItem(item(response = "peut"), paris)))
        val p = Proposal(id = 7, op = Proposal.ADD, calendar = "c", draft = ProposalDraft("Dîner", at("2026-11-28", "20:00"), at("2026-11-28", "23:00"), zone = paris))
        val o = occOfProposal(p, paris)!!
        assertEquals(Sort.PROPOSED, sortOf(o))
        assertEquals(1200, o.start)
        assertEquals("rose", occColor(o, emptyList()))
        val her = occOfHer(HerDate(ref = "r", kind = "promesse", title = "Relire", start = at("2026-11-24", "00:00"), allDay = true, day = "2026-11-24"), paris)
        assertEquals(Sort.MIKA, sortOf(her))
        assertTrue(her.allDay)
        assertNull(occOfProposal(Proposal(id = 8, op = Proposal.RESPOND), paris))
    }

    @Test fun `ce qui se chevauche partage la largeur, les journees vont en bandes`() {
        val a = occOfItem(item(event = 1, start = at("2026-11-24", "10:00"), end = at("2026-11-24", "11:00")), paris)
        val b = occOfItem(item(event = 2, start = at("2026-11-24", "10:30"), end = at("2026-11-24", "12:00")), paris)
        val c = occOfItem(item(event = 3, start = at("2026-11-24", "14:00"), end = at("2026-11-24", "15:00")), paris)
        assertEquals(listOf(Triple(1, 0, 2), Triple(2, 1, 2), Triple(3, 0, 1)), columns(listOf(a, b, c)).map { Triple(it.o.item!!.event, it.col, it.cols) })
        val d1 = occOfItem(item(event = 4, allDay = true, firstDay = "2026-11-23", lastDay = "2026-11-25"), paris)
        val d2 = occOfItem(item(event = 5, allDay = true, firstDay = "2026-11-24", lastDay = "2026-11-24"), paris)
        assertEquals(listOf(Triple(0, 2, 0), Triple(1, 1, 1)), lanes(listOf(d1, d2), "2026-11-23", 7).map { Triple(it.from, it.to, it.lane) })
    }

    @Test fun `ou en est un rendez-vous par rapport a maintenant`() {
        val o = occOfItem(item(), paris)
        assertEquals(Tone.INFO to "dans 30 min", relative(o, "2026-11-24", 17 * 60))
        assertEquals(Tone.OK to "en cours", relative(o, "2026-11-24", 17 * 60 + 40))
        assertEquals(Tone.NEUTRAL to "passé", relative(o, "2026-11-24", 19 * 60))
        assertEquals(Tone.NEUTRAL to "dans 2 jours", relative(o, "2026-11-22", 600))
        assertEquals(Tone.NEUTRAL to "demain", relative(o, "2026-11-23", 600))
    }

    @Test fun `le Planning - un jour par ligne, aujourd'hui toujours la, la ligne de l'heure avant ce qui n'a pas commence`() {
        val a = occOfItem(item(event = 1, start = at("2026-11-24", "09:00"), end = at("2026-11-24", "09:30")), paris)
        val b = occOfItem(item(event = 2, start = at("2026-11-24", "14:00"), end = at("2026-11-24", "15:00")), paris)
        val multi = occOfItem(item(event = 3, allDay = true, firstDay = "2026-11-25", lastDay = "2026-11-26"), paris)
        val days = planningDays(sortOccs(listOf(b, a, multi)), "2026-11-23", "2026-12-21", "2026-11-24", 10 * 60)
        assertEquals(listOf("2026-11-24", "2026-11-25", "2026-11-26"), days.map { it.day })
        assertEquals(listOf(1, 2), days[0].occs.map { it.item!!.event })
        assertEquals(1, days[0].nowAt)
        assertEquals(-1, days[1].nowAt)
        // aujourd'hui sans rien : il est là, la ligne de l'heure seule
        val empty = planningDays(emptyList(), "2026-11-24", "2026-12-22", "2026-11-24", 600)
        assertEquals(listOf(PlanningDay("2026-11-24", emptyList(), 0)), empty)
    }

    @Test fun `le mois - quatre lignes au plus, puis trois et plus N`() {
        val many = (1..6).map { occOfItem(item(event = it, start = at("2026-11-24", "0$it:00"), end = at("2026-11-24", "0$it:30")), paris) }
        val cell = monthCells(many, "2026-11-24", "2026-11-24").first { it.day == "2026-11-24" }
        assertEquals(3, cell.shown.size)
        assertEquals(3, cell.more)
        assertTrue(cell.today)
        assertTrue(cell.inMonth)
        assertFalse(monthCells(many, "2026-11-24", "2026-11-24").first().inMonth)
        assertEquals(setOf("2026-11-24"), busyDays(many))
    }

    @Test fun `la couleur du fournisseur se rapproche de la palette, Mon agenda est indigo, le rose est a Mika`() {
        assertEquals("bleu", nearestColor("#1f6fd0"))
        assertEquals("vert", nearestColor("#7BD148"))
        assertEquals("", nearestColor("pas une couleur"))
        assertEquals("indigo", colorOf(cal()))
        assertEquals("ambre", colorOf(cal(color = "ambre")))
        assertEquals("rose", colorOf(cal(kind = AgendaKinds.MIKA)))
        assertNotEquals("rose", colorOf(cal(level = AgendaLevels.READ, key = "moi:b~mon-agenda")))
    }

    @Test fun `ce qui s'affiche - decoche ici, masque dans Parametres, celui de Mika sauf decoche`() {
        val list = listOf(cal(), cal(key = "g~perso", kind = AgendaKinds.GOOGLE).copy(hidden = true))
        assertTrue(shownHere("moi:a~mon-agenda", list, emptySet()))
        assertFalse(shownHere("moi:a~mon-agenda", list, setOf("moi:a~mon-agenda")))
        assertFalse(shownHere("g~perso", list, emptySet()))
        assertTrue(shownHere(AgendaKinds.MIKA, list, emptySet()))
        assertFalse(shownHere(AgendaKinds.MIKA, list, setOf(AgendaKinds.MIKA)))
        assertEquals(listOf("moi:a~mon-agenda", AgendaKinds.MIKA), readKeys(list))
        assertEquals("moi:a~mon-agenda", defaultCalendar(list + cal(key = "c~x", kind = AgendaKinds.CALDAV, primary = false)))
    }

    // ── la répétition, les rappels ──

    @Test fun `la regle d'un choix, le choix d'une regle, ses mots`() {
        assertEquals("FREQ=WEEKLY;BYDAY=TU", ruleOf(RepeatChoice.WEEKLY, "2026-11-24"))
        assertEquals("FREQ=MONTHLY;BYMONTHDAY=24", ruleOf(RepeatChoice.MONTHLY, "2026-11-24"))
        assertEquals(RepeatChoice.WEEKLY, choiceOf("FREQ=WEEKLY;BYDAY=TU", "2026-11-24"))
        assertEquals(RepeatChoice.CUSTOM, choiceOf("FREQ=WEEKLY", "2026-11-24"))
        val rule = ruleOf(RepeatChoice.CUSTOM, "2026-11-24", CustomRule(2, "semaines", listOf(1, 4), "le", "2027-06-30", 5))
        assertEquals("FREQ=WEEKLY;INTERVAL=2;BYDAY=MO,TH;UNTIL=20270630", rule)
        val back = customOf(rule, "2026-11-24")
        assertEquals(listOf(2, 1, 4), listOf(back.interval) + back.days)
        assertEquals("le" to "2027-06-30", back.ends to back.until)
        assertEquals("Toutes les 2 semaines, le lundi et jeudi, jusqu'au mercredi 30 juin 2027", ruleWords(rule, "2026-11-24", "2026-11-24"))
        assertEquals("Chaque année, le 28 novembre", ruleWords("FREQ=YEARLY", "2026-11-28", "2026-11-24"))
        assertEquals("Chaque lundi, 5 fois", ruleWords("FREQ=WEEKLY;COUNT=5;BYDAY=MO", "2026-11-23", "2026-11-24"))
        assertEquals("Chaque semaine, le mardi", repeatChoices("2026-11-24")[2].second)
    }

    @Test fun `un rappel du fournisseur en mots, Mika te le rappelle en mots`() {
        assertEquals("e-mail 1 jour avant", alertWords(Alert(Alert.EMAIL, 1440)))
        assertEquals("notification 10 min avant", alertWords(Alert(Alert.NOTIFICATION, 10)))
        assertEquals("notification 2 h avant", alertWords(Alert(Alert.NOTIFICATION, 120)))
        assertEquals("Mika te le rappelle la veille au soir", mikaReminderLine("veille"))
        assertEquals("Mika ne te le rappelle pas", mikaReminderLine("non"))
        assertEquals("" to "Comme l'agenda (30 min avant)", remindChoices(cal()).first())
    }

    // ── ce que le formulaire envoie ──

    private val start = FormValues(
        calendar = "c", title = "Coiffeur", d1 = "2026-11-24", h1 = 18 * 60, d2 = "2026-11-24", h2 = 18 * 60 + 30, zone = paris,
        reminders = listOf(Alert(Alert.NOTIFICATION, 30)),
    )

    @Test fun `une creation envoie tout, sans les rappels du fournisseur qu'on n'a pas touches`() {
        val f = fieldsOf(FormModes.NEW, start, start, owner = true)
        assertEquals("Coiffeur", f.title)
        assertEquals("2026-11-24T18:00" to "2026-11-24T18:30", f.start to f.end)
        assertEquals(false, f.allDay)
        assertEquals(paris, f.zone)
        assertEquals("", f.rule)
        assertEquals("", f.remind)
        assertNull(f.reminders)
        assertEquals(emptyList<Alert>(), fieldsOf(FormModes.NEW, start.copy(remindersTouched = true, reminders = emptyList()), start, true).reminders)
        val day = fieldsOf(FormModes.NEW, start.copy(allDay = true, d2 = "2026-11-23"), start, false)
        assertEquals(Triple("2026-11-24", "2026-11-24", true), Triple(day.start, day.end, day.allDay))
        assertNull(day.zone)
        // « Mika te le rappelle » : son propriétaire seulement
        assertNull(fieldsOf(FormModes.NEW, start, start, false).remind)
        assertFalse(fieldsOf(FormModes.NEW, start, start, false).json().containsKey("remind"))
    }

    @Test fun `une modification n'envoie que ce qui a change, un moment change part en entier`() {
        assertTrue(fieldsOf(FormModes.EDIT, start, start, true).empty)
        assertEquals(EventFields(title = "Coiffeur · Paul"), fieldsOf(FormModes.EDIT, start.copy(title = "Coiffeur · Paul"), start, true))
        assertEquals(
            EventFields(start = "2026-11-24T17:00", end = "2026-11-24T18:30", allDay = false, zone = paris),
            fieldsOf(FormModes.EDIT, start.copy(h1 = 17 * 60), start, true),
        )
        assertEquals(EventFields(rule = "FREQ=DAILY"), fieldsOf(FormModes.EDIT, start.copy(repeat = RepeatChoice.DAILY), start, true))
        assertEquals(
            EventFields(reminders = listOf(Alert(Alert.EMAIL, 60))),
            fieldsOf(FormModes.EDIT, start.copy(remindersTouched = true, reminders = listOf(Alert(Alert.EMAIL, 60))), start, true),
        )
        assertEquals(EventFields(invite = listOf("lea@x.fr")), fieldsOf(FormModes.EDIT, start.copy(invite = listOf(Guest("Léa", "lea@x.fr"))), start, true))
    }

    @Test fun `le formulaire - l'heure de debut emporte la fin, le jour de debut aussi, la fin avant le debut se dit`() {
        assertEquals(19 * 60 + 30, withStartMinute(start, 19 * 60).h2)
        val late = withStartMinute(start, 23 * 60 + 30)
        assertEquals("2026-11-25" to 0, late.d2 to late.h2)
        // un rendez-vous qui passe minuit (23 h → 1 h) garde ses deux heures, avancé ou reculé
        val night = start.copy(h1 = 23 * 60, d2 = "2026-11-25", h2 = 60)
        val earlier = withStartMinute(night, 22 * 60 + 30)
        assertEquals(Triple(22 * 60 + 30, "2026-11-25", 30), Triple(earlier.h1, earlier.d2, earlier.h2))
        val sooner = withStartMinute(night, 20 * 60)
        assertEquals("2026-11-24" to 22 * 60, sooner.d2 to sooner.h2)
        // sur plusieurs jours aussi
        val long = withStartMinute(start.copy(h1 = 10 * 60, d2 = "2026-11-26", h2 = 10 * 60), 11 * 60)
        assertEquals("2026-11-26" to 11 * 60, long.d2 to long.h2)
        assertEquals("2026-11-26", withStartDay(start, "2026-11-26").d2)
        assertEquals("La fin est avant le début.", formProblem(start.copy(h2 = 17 * 60)))
        assertNull(formProblem(start))
        assertEquals(listOf(0, 30), hourChoices(false, 0).take(2).map { it.minute })
        assertEquals("30 min", hourChoices(true, 600).first().duration)
        assertEquals("1 h 30", hourChoices(true, 600)[2].duration)
    }

    @Test fun `les valeurs de depart - un creneau touche, aujourd'hui la demi-heure qui vient, une copie`() {
        val slot = initialValues(FormModes.NEW, "c", paris, "2026-11-24", 14 * 60 + 20, listOf(cal(key = "c")), day = "2026-11-26", slotMinute = 9 * 60)
        assertEquals(Triple("2026-11-26", 9 * 60, 10 * 60), Triple(slot.d1, slot.h1, slot.h2))
        val now = initialValues(FormModes.NEW, "c", paris, "2026-11-24", 14 * 60 + 20, listOf(cal(key = "c")))
        assertEquals(14 * 60 + 30, now.h1)
        val other = initialValues(FormModes.NEW, "c", paris, "2026-11-24", 14 * 60 + 20, emptyList(), day = "2026-11-30")
        assertEquals(600, other.h1)
        val o = occOfItem(item(calendar = "c"), paris)
        val copy = initialValues(FormModes.COPY, "c", paris, "2026-11-24", 600, emptyList(), o)
        assertEquals("Dentiste (copie)", copy.title)
        assertEquals(17 * 60 + 30, copy.h1)
        // copier un « Occupé » (le privé d'une autre) ou un événement oublié : le mot qu'il montre, jamais un titre vide
        val busy = occOfItem(item(calendar = "x", title = "", masked = true), paris)
        assertEquals("Occupé", initialValues(FormModes.COPY, "c", paris, "2026-11-24", 600, emptyList(), busy).title)
        val gone = occOfItem(item(calendar = "x", title = ""), paris)
        assertEquals(NO_TITLE, initialValues(FormModes.COPY, "c", paris, "2026-11-24", 600, emptyList(), gone).title)
        assertEquals("", initialValues(FormModes.EDIT, "x", paris, "2026-11-24", 600, emptyList(), gone).title)
    }

    // ── les noms et les droits d'un agenda ──

    @Test fun `Mon agenda d'une autre se dit Agenda de Lea`() {
        assertEquals("Agenda de Léa", shownName(cal(group = AgendaGroups.SHARED, level = AgendaLevels.READ, ownerName = "Léa Moreau")))
        assertEquals("Agenda d'Adrien", shownName(cal(group = AgendaGroups.SHARED, level = AgendaLevels.READ, ownerName = "Adrien Moreau")))
        assertEquals("Mon agenda", shownName(cal()))
        assertEquals("Perso", shownName(cal(group = AgendaGroups.SHARED, kind = AgendaKinds.GOOGLE, name = "Perso", ownerName = "Léa")))
    }

    private fun line(who: List<String>, moment: List<String>, read: Boolean, write: String, respond: String) =
        AgendaRule(who = who, moment = moment, read = read, write = write, respond = respond)

    private val table = AgendaRights(
        calendar = "c",
        lines = listOf(
            line(listOf("personne:user_1"), listOf("conversation"), true, "accord", "accord"),
            line(listOf("personne:user_1"), listOf("initiative"), true, "non", "non"),
            line(listOf("elle"), emptyList(), true, "non", "accord"),
            line(listOf("personne:user_2"), emptyList(), true, "non", "non"),
        ),
    )

    @Test fun `ce que Mika fait d'un agenda, en une ligne et en pastilles`() {
        assertEquals(
            "Avec toi, elle le lit, y ajoute avec ton accord, prépare tes réponses ; elle te rappelle ses rendez-vous · aussi avec Léa",
            rightsSummary(table, "user_1", listOf(AgendaShare("user_2", "Léa Moreau", AgendaLevels.READ))),
        )
        assertEquals("", rightsSummary(table, "user_9"))
        assertEquals("Avec toi, elle le lit ; elle te rappelle ses rendez-vous", rightsSummary(table, "user_1", writable = false))
        assertEquals(RightsPills(alone = 1, ask = 2, no = 0), rightsPills(table, "user_1"))
        assertEquals("Toi", ruleWho(table.lines[0], "user_1"))
        assertEquals("Mika", ruleWho(table.lines[2], "user_1"))
        val shared = cal(key = "c").copy(shares = listOf(AgendaShare("user_2", "Léa", AgendaLevels.READ)))
        assertEquals("user_2", sharedPerson(shared, table.lines[3]))
        assertEquals("", sharedPerson(shared, table.lines[0]))
        assertEquals("seule", RightsColumns.set(table.lines[0], RightsColumns.WRITE, "seule").write)
        assertFalse(RightsColumns.set(table.lines[0], RightsColumns.READ, "non").read)
        assertTrue(rightsRules(shared, table).any { it.startsWith("Partagé dans Mika avec Léa") })
    }

    // ── la fiche ──

    @Test fun `les participants - l'organisateur d'abord, leurs reponses, ce qu'on en dit`() {
        val i = item().copy(
            organizer = AgendaPerson("karim@x.fr", "Karim Haddad", response = "oui"),
            participants = listOf(
                AgendaPerson("karim@x.fr", "Karim Haddad", response = "oui"),
                AgendaPerson("claire@x.fr", "Claire", response = "oui"),
                AgendaPerson("marc@x.fr", "Marc", response = "peut"),
                AgendaPerson("a@x.fr", "Adrien", response = "attente", me = true),
            ),
            organized = false,
        )
        val rows = peopleOf(i)
        assertEquals(listOf("organise", "oui", "peut-être", "sans réponse"), rows.map { it.word })
        assertEquals("2 oui · 1 peut-être · 1 sans réponse", peopleSummary(rows))
        assertTrue(rows.last().me)
        assertEquals("Karim Haddad", inviter(i))
        assertTrue(removesInvitation(i))
        assertEquals(emptyList<PersonRow>(), peopleOf(item()))
    }

    @Test fun `le pied de la fiche et les rappels du fournisseur`() {
        assertEquals("Une modification part tout de suite sur ce serveur.", ficheFoot(item(), cal()))
        assertEquals("Une modification part tout de suite chez Google, puis l'agenda se relit.", ficheFoot(item(), cal(kind = AgendaKinds.GOOGLE)))
        assertEquals("Un événement privé : tu n'en vois que le créneau.", ficheFoot(item(masked = true), cal()))
        assertTrue(ficheFoot(item(), cal(group = AgendaGroups.SHARED, level = AgendaLevels.READ, writable = false, ownerName = "Léa")).startsWith("Léa partage cet agenda avec toi en lecture"))
        assertEquals(listOf("L'agenda du système n'envoie rien lui-même : c'est Mika qui te le rappelle."), providerReminderLines(item(), cal()))
        val g = cal(kind = AgendaKinds.GOOGLE).copy(providerReminders = ProviderReminders(max = 5))
        assertEquals(listOf("Notification 10 min avant, par Google · le réglage de l'agenda"), providerReminderLines(item().copy(reminders = listOf(Alert(minutes = 10)), remindersDefault = true), g))
        assertEquals(listOf("Aucun rappel par Google"), providerReminderLines(item(), g))
    }

    @Test fun `la reponse que Mika a preparee, en mots`() {
        assertEquals("Refuser, avec un mot : « Désolé ! »", preparedWords(Proposal(answer = "non", comment = "Désolé !")))
        assertEquals("Accepter", preparedWords(Proposal(answer = "oui")))
    }

    // ── À décider, le canal « Agenda », la carte du chat ──

    private val diner = Proposal(
        id = 12, op = Proposal.ADD, calendar = "moi:a~mon-agenda", decides = true, remind = "veille",
        draft = ProposalDraft("Dîner chez Léa", at("2026-11-28", "20:00"), at("2026-11-28", "23:00"), zone = paris, location = "rue de Gand"),
    )

    @Test fun `a decider - ce que Mika propose dont tu decides, et les invitations`() {
        assertEquals(listOf(12), pendingAdds(listOf(diner, diner.copy(id = 13, decides = false), diner.copy(id = 14, op = Proposal.RESPOND))).map { it.id })
        assertEquals("Mika propose « Dîner chez Léa » · 2 invitations", decideSummary(listOf(diner), 2))
        assertEquals("1 invitation", decideSummary(emptyList(), 1))
        assertEquals("Sam. 28 nov. · 20:00 – 23:00", proposalWhen(occOfProposal(diner, paris)!!))
    }

    @Test fun `le canal Agenda - une note par invitation et par ajout propose, ce qu'elle ouvre`() {
        val inv = item(event = 42, title = "Entretien annuel", invitation = true, response = "attente").copy(
            occurrence = "",
            location = "Salle RH · 2e étage",
            organizer = AgendaPerson("nadia@x.fr", "Nadia Benkacem"),
            prepared = Proposal(id = 5, op = Proposal.RESPOND, decides = true, answer = "oui", comment = "C'est noté"),
        )
        val notes = agendaNotes(listOf(inv), listOf(diner), listOf(cal()), paris, "2026-11-24")
        assertEquals(listOf("i:42:", "p:12"), notes.map { it.key })
        assertEquals("Nadia Benkacem t'invite : Entretien annuel", notes[0].title)
        assertEquals("Mardi 24 novembre · 17:30 – 18:00 · Salle RH. Mika a préparé : accepter, avec un mot : « C'est noté ».", notes[0].text)
        assertEquals(AgendaTarget.Event(42, ""), notes[0].target)
        assertEquals("Ajouter « Dîner chez Léa » à Mon agenda ?", notes[1].title)
        assertEquals("Sam. 28 nov. · 20:00 – 23:00 · rue de Gand. Elle te le rappellera la veille au soir.", notes[1].text)
        for (t in listOf(AgendaTarget.Event(42, "20261125T130000Z"), AgendaTarget.Event(3, ""), AgendaTarget.Ask(9))) {
            assertEquals(t, AgendaTarget.decode(t.encode()))
        }
        assertNull(AgendaTarget.decode("chat"))
        assertNull(AgendaTarget.decode("agenda:e:x"))
    }

    @Test fun `la carte d'un ajout dit l'evenement, son agenda et le rappel de Mika`() {
        val got = agendaCards(listOf(diner, diner.copy(id = 13, op = Proposal.RESPOND, draft = null)), listOf(cal()), paris, at("2026-11-24", "13:00"))
        assertEquals(setOf(12), got.keys)
        val c = got.getValue(12)
        assertEquals("Mon agenda", c.calendar)
        assertEquals("indigo", c.color)
        assertEquals("Dîner chez Léa", c.title)
        assertEquals("rue de Gand", c.place)
        assertEquals("la veille au soir", c.remind)
        assertEquals("Samedi 28 novembre · 20:00 – 23:00", c.whenWords)
    }

    // ── ses comptes ──

    @Test fun `l'etat d'un compte et la ligne de Parametres`() {
        val sys = AgendaAccount(key = "moi:a", kind = AgendaKinds.SYSTEM, system = true)
        val google = AgendaAccount(key = "g", kind = AgendaKinds.GOOGLE, label = "Google", signin = AgendaSignin(state = AgendaSignin.CONNECTED), syncedAt = 1)
        val outlook = AgendaAccount(key = "o", kind = AgendaKinds.MICROSOFT, label = "Outlook.com", signin = AgendaSignin(state = AgendaSignin.TODO))
        val dav = AgendaAccount(key = "d", kind = AgendaKinds.CALDAV, error = "Le serveur ne répond pas.")
        assertEquals(Tone.OK to "à jour", accountState(sys))
        assertEquals(Tone.OK to "synchronisé", accountState(google))
        assertEquals(Tone.WARN to "à connecter", accountState(outlook))
        assertEquals(Tone.WARN to "en panne", accountState(dav))
        assertTrue(needsSignin(outlook))
        assertFalse(needsSignin(google))
        assertEquals("4 comptes · 2 à reconnecter", accountsSummary(listOf(sys, google, outlook, dav)))
        assertEquals("1 compte", accountsSummary(listOf(sys)))
        assertEquals("Le serveur ne répond pas.", accountLine(dav, 0))
        assertEquals("À reconnecter", accountLine(outlook, 0))
        assertEquals("Outlook.com / Microsoft 365", kindLong(AgendaKinds.MICROSOFT))
    }

    // ── le direct ──

    @Test fun `repondre - une serie dit que la reponse vaut pour toute la serie, sans reponse possible on dit pourquoi`() {
        val can = ItemCan(respond = true)
        val series = item(invitation = true, response = "attente").copy(recurring = true, can = can)
        assertEquals(AnswerNote.SERIES, answerNote(series))
        assertEquals(AnswerNote.NONE, answerNote(item(invitation = true, response = "attente").copy(can = can)))
        val told = item(invitation = true, response = "attente").copy(recurring = true, respondWhy = "Son serveur ne transmet pas les réponses.")
        assertEquals(AnswerNote.WHY, answerNote(told))
        assertEquals(AnswerNote.NONE, answerNote(item()))
    }

    @Test fun `Google - en retour direct, l'adresse de la page du serveur se colle aussi`() {
        val direct = googleReturn(direct = true)
        assertTrue(direct.pastes && direct.waits) // sans session, le serveur demande de coller son adresse ici
        assertTrue(direct.example.startsWith("https://") && "/agenda/google/retour?" in direct.example)
        val pasted = googleReturn(direct = false)
        assertTrue(pasted.pastes && !pasted.waits)
        assertTrue(pasted.example.startsWith("http://127.0.0.1/"))
    }

    @Test fun `le direct - la periode affichee et l'evenement ouvert se relisent si leur agenda est nomme`() {
        val keyed = LiveSignal.of(Topics.AGENDA to setOf("g~perso"))
        assertTrue(AgendaLive.periodShows(listOf("moi:a~mon-agenda", "g~perso"), keyed))
        assertFalse(AgendaLive.periodShows(listOf("moi:a~mon-agenda"), keyed))
        assertTrue(AgendaLive.periodShows(listOf("moi:a~mon-agenda"), LiveSignal.of(Topics.AGENDA to null)))
        assertTrue(AgendaLive.eventShows("g~perso", keyed))
        assertFalse(AgendaLive.eventShows("moi:a~mon-agenda", keyed))
        assertTrue(AgendaLive.eventShows("x", LiveSignal.RESYNC))
        assertFalse(AgendaLive.eventShows("g~perso", LiveSignal.of(Topics.MAIL to null)))
    }
}
