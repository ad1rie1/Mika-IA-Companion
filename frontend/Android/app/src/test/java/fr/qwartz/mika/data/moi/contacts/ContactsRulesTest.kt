package fr.qwartz.mika.data.moi.contacts

import fr.qwartz.mika.data.moi.mail.MailContact
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Les règles de Contacts (ADR 0298, la maquette validée `ecrans/contacts.js`) : ce qu'une ligne et une fiche disent,
 * ce qui l'identifie (une adresse générique le dit), d'où vient un fait, où vous vous croisez ; et les destinataires
 * proposés quand on écrit — tous tes contacts, une ligne par adresse, une adresse générique marquée et après les
 * personnes, ce qui est déjà en puce écarté.
 */
class ContactsRulesTest {
    private val zone = ZoneId.systemDefault()
    private fun at(h: Int, m: Int, day: Int = 22) = LocalDateTime.of(2026, 11, day, h, m).atZone(zone).toInstant().toEpochMilli()
    private val now = at(15, 0)

    private val lumen = ContactRef(3, "Lumen Conseil")
    private val claire = ContactLine(
        id = 12, name = "Claire Dubois", title = "Cheffe de projet", department = "Conseil", organisation = lumen, last = at(13, 41),
        sources = listOf(ContactSource("teams", label = "Teams", count = 64), ContactSource("mail", "pro", "Pro", 23)),
        identifiers = listOf(ContactIdent("email", "c.dubois@lumen-conseil.fr"), ContactIdent("teams", "Claire Dubois")),
    )
    private val karim = ContactLine(
        id = 14, name = "Karim Haddad", title = "Développeur", organisation = lumen,
        sources = listOf(ContactSource("teams", label = "Teams", count = 18)),
        identifiers = listOf(ContactIdent("email", "k.haddad@lumen-conseil.fr"), ContactIdent("teams", "Karim Haddad")),
    )
    private val sophie = ContactLine(
        id = 15, name = "Sophie Laurent", organisation = lumen,
        sources = listOf(ContactSource("teams", label = "Teams", count = 30), ContactSource("mail", "pro", "Pro", 6), ContactSource("mail", "perso", "Perso", 2)),
        identifiers = listOf(ContactIdent("email", "s.laurent@lumen-conseil.fr"), ContactIdent("email", "sophie.laurent@gmail.com"), ContactIdent("phone", "+33652110874")),
    )
    private val lumenOrg = ContactLine(
        id = 3, kind = ContactKinds.ORG, name = "Lumen Conseil", members = 5,
        sources = listOf(ContactSource("teams", label = "Teams", count = 214), ContactSource("mail", "pro", "Pro", 120)),
        identifiers = listOf(ContactIdent("domain", "lumen-conseil.fr"), ContactIdent("email", "accueil@lumen-conseil.fr"), ContactIdent("email", "noreply@lumen-conseil.fr")),
    )
    private val thomas = ContactLine(id = 20, name = "Thomas G.", sources = listOf(ContactSource("whatsapp", label = "WhatsApp", count = 3)))

    // ── La liste ──

    @Test fun `une ligne dit son poste et son organisation, une organisation ses personnes`() {
        assertEquals("Cheffe de projet · Lumen Conseil", lineSub(claire))
        assertEquals("Organisation · 5 personnes", lineSub(lumenOrg))
        assertEquals("Organisation", lineSub(lumenOrg.copy(members = 0)))
        assertEquals("Organisation · 1 personne", lineSub(lumenOrg.copy(members = 1)))
        // sans poste : son service ; sans rien : un identifiant, sinon s'il a un compte
        assertEquals("Conseil", lineSub(claire.copy(title = "", organisation = null)))
        assertEquals("+33652110874", lineSub(ContactLine(identifiers = listOf(ContactIdent("phone", "+33652110874")))))
        assertEquals("parle aussi à Mika", lineSub(ContactLine(linked = true, talks = true)))
        assertEquals("a un compte", lineSub(ContactLine(linked = true)))
        assertEquals("", lineSub(thomas))
    }

    @Test fun `les choix de la liste et leurs nombres, la recherche bornée comme l'API`() {
        val counts = ContactsCounts(all = 7, person = 6, org = 1)
        assertEquals(listOf(7, 6, 1), CONTACT_KIND_CHOICES.map { counts.of(it) })
        assertEquals(200, clippedQuery("é".repeat(250)).length)
        // un emoji compte pour un caractère, comme côté serveur
        assertEquals(200, clippedQuery("🙂".repeat(201)).codePointCount(0, clippedQuery("🙂".repeat(201)).length))
        assertEquals("claire", clippedQuery("claire"))
    }

    // ── La fiche ──

    @Test fun `la tête dit son poste et son service, une organisation ses personnes parmi tes contacts`() {
        assertEquals("Cheffe de projet · Conseil", headLine(ContactSheet(title = "Cheffe de projet", department = "Conseil")))
        assertEquals("Organisation · 5 personnes parmi tes contacts", headLine(ContactSheet(kind = ContactKinds.ORG, membersTotal = 5)))
        assertEquals("Organisation", headLine(ContactSheet(kind = ContactKinds.ORG)))
        assertEquals("dernier échange 13:41", lastExchange(at(13, 41), now))
        assertEquals("dernier échange hier", lastExchange(at(18, 0, day = 21), now))
        assertEquals("", lastExchange(0, now))
    }

    @Test fun `une adresse générique le dit dans sa ligne, et on n'y écrit pas d'ici`() {
        val generic = ContactIdentifier("email", "E-mail", "noreply@lumen-conseil.fr", where = listOf("Pro"), generic = true)
        val own = ContactIdentifier("email", "E-mail", "c.dubois@lumen-conseil.fr", where = listOf("Pro", "son profil Teams"))
        assertEquals("Adresse générique · Pro · sans personne derrière", identifierSub(generic))
        assertEquals("E-mail · Pro, son profil Teams", identifierSub(own))
        val canWrite = ContactSheet(write = ContactWrite("c.dubois@lumen-conseil.fr", "Claire Dubois"))
        assertTrue(writableAt(canWrite, own))
        assertFalse(writableAt(canWrite, generic))
        // aucune de tes boîtes n'envoie (`write` nul) : pas d'écriture, même vers une personne
        assertFalse(writableAt(ContactSheet(), own))
        assertFalse(writableAt(canWrite, ContactIdentifier("phone", "Téléphone", "+33600000000")))
    }

    @Test fun `un contact du téléphone se dit par le nom de ton carnet, jamais par sa clé, et ne se copie pas`() {
        val app = ContactIdentifier("phone_app", "Contact WhatsApp", "", name = "Thomas G.", where = listOf("ton téléphone"))
        assertEquals("Thomas G.", identifierShown(app))
        assertEquals("hors de ton carnet", identifierShown(app.copy(name = "")))
        assertEquals("", copied(app))
        assertEquals("+33600000000", copied(ContactIdentifier("phone", value = "+33600000000")))
    }

    @Test fun `ce que Mika en sait, son profil, puis ses faits, chacun d'où et sûre à combien`() {
        val s = ContactSheet(
            facts = listOf(
                ContactFact("title", "Poste", "Cheffe de projet", from = "son profil Teams"),
                ContactFact("note", value = "Elle préfère les points courts.", id = 41, from = "ses messages dans Teams", place = "en tête-à-tête", confidence = 0.6, forget = true),
                ContactFact("organisation", "Organisation", "Lumen Conseil", id = 3, from = "son adresse e-mail"),
            ),
        )
        assertEquals(listOf("title", "organisation"), profileFacts(s).map { it.kind })
        assertEquals(listOf(41), noteFacts(s).map { it.id })
        assertEquals("d'après ses messages dans Teams · en tête-à-tête · sûre à 60 %", noteSource(noteFacts(s).single()))
        // ce que tu lui as raconté n'est pas une lecture : pas de confiance
        assertEquals("d'après ce que tu lui as raconté", noteSource(ContactFact("note", value = "x", from = "ce que tu lui as raconté")))
        assertEquals("d'après son profil Teams", profileFrom(profileFacts(s).first()))
    }

    @Test fun `d'où vient ce qu'elle en sait, en une phrase`() {
        assertEquals(
            "Ce que Mika sait de Claire vient de tes comptes et de ce que tu lui as dit : elle n'en parle qu'à toi.",
            privacyNote("Claire", ContactSheet.PRIVACY_MINE),
        )
        assertTrue(privacyNote("Maman", ContactSheet.PRIVACY_SHARED).contains("d'autres que toi peuvent le lire"))
    }

    @Test fun `où vous vous croisez, Teams, un mail, le téléphone, comme la maquette`() {
        val teams = placeLine(ContactPlace(source = "teams", conversation = "pro~1", title = "Claire Dubois", kind = "dm", count = 41, last = at(13, 41)), "Claire", now)
        assertEquals(PlaceLine(PlaceIcon.TEAMS, "Claire Dubois", "tête-à-tête · 41 messages · 13:41"), teams)
        val mail = placeLine(ContactPlace(source = "mail", boxName = "Pro", count = 23, last = at(13, 40), ref = "pro:<m@x>", subject = "Re: Présentation de jeudi"), "Claire", now)
        assertEquals(PlaceLine(PlaceIcon.MAIL, "Re: Présentation de jeudi", "Pro · 23 mails · 13:40"), mail)
        // sans mail reçu de lui : le titre dit combien
        assertEquals("2 mails", placeLine(ContactPlace(source = "mail", boxName = "Pro", count = 2), "Claire", now).title)
        val group = placeLine(ContactPlace(source = "phone", app = "whatsapp", appName = "WhatsApp", title = "Rando dimanche", group = true, count = 3, last = at(13, 47)), "Thomas", now)
        assertEquals(PlaceLine(PlaceIcon.CHAT, "Rando dimanche", "groupe WhatsApp · 3 messages · 13:47"), group)
        val sms = placeLine(ContactPlace(source = "phone", app = "sms", appName = "Messages", count = 1, last = 0), "Maman", now)
        assertEquals(PlaceLine(PlaceIcon.PHONE, "Maman", "Messages · 1 message"), sms)
    }

    @Test fun `oublier, ce que demandent les confirmations`() {
        assertTrue(forgetQuestion("Claire").startsWith("Mika oubliera Claire : sa fiche"))
        assertEquals("Mika oubliera ce qu'elle avait compris : « Elle part. »", forgetFactQuestion("Elle part."))
    }

    // ── Écrire : les destinataires proposés ──

    @Test fun `tous tes contacts proposés, une ligne par adresse, les génériques après les personnes`() {
        // l'ordre du serveur : l'organisation vue la première
        val got = proposals(listOf(lumenOrg, claire, karim, sophie), chosen = emptySet(), max = 10)
        assertEquals(
            listOf(
                "c.dubois@lumen-conseil.fr", "k.haddad@lumen-conseil.fr", "s.laurent@lumen-conseil.fr", "sophie.laurent@gmail.com",
                "accueil@lumen-conseil.fr", "noreply@lumen-conseil.fr",
            ),
            got.map { it.address },
        )
        // une adresse d'une organisation est générique (l'annuaire ne la range jamais à une personne), son carré avec
        val generic = got.filter { it.generic }
        assertEquals(setOf("accueil@lumen-conseil.fr", "noreply@lumen-conseil.fr"), generic.map { it.address }.toSet())
        assertTrue(generic.all { it.org && it.name == "Lumen Conseil" && it.about.isEmpty() })
        assertTrue(got.filterNot { it.generic }.none { it.org })
        // une personne dit son organisation à côté de son nom ; sans organisation, son poste
        assertEquals("Lumen Conseil", got.first().about)
        assertEquals("Développeur", proposals(listOf(karim.copy(organisation = null)), emptySet()).single().about)
        assertEquals(12, got.first().contact)
    }

    @Test fun `ce qui est déjà en puce n'est plus proposé, une même adresse une fois, six au plus`() {
        val got = proposals(listOf(claire, sophie, claire), chosen = setOf("s.laurent@lumen-conseil.fr"))
        assertEquals(listOf("c.dubois@lumen-conseil.fr", "sophie.laurent@gmail.com"), got.map { it.address })
        val many = (1..10).map { ContactLine(id = it, name = "P$it", identifiers = listOf(ContactIdent("email", "p$it@x.fr"))) }
        assertEquals(PROPOSED, proposals(many, emptySet()).size)
        // un contact sans adresse (un contact du téléphone) ne propose rien
        assertTrue(proposals(listOf(thomas), emptySet()).isEmpty())
    }

    @Test fun `à droite, d'où vient l'adresse`() {
        // une seule adresse : la boîte où elle la voit le plus, et combien de mails
        assertEquals(ProposalHint(teams = false, top = "Pro", bottom = "23 mails"), proposalHint(claire))
        assertEquals("1 mail", proposalHint(claire.copy(sources = listOf(ContactSource("mail", "pro", "Pro", 1))))!!.bottom)
        // vue seulement par Teams : son profil
        assertEquals(ProposalHint(teams = true, top = "Teams", bottom = "son profil"), proposalHint(karim))
        // deux adresses : ses boîtes, sans compte (la liste ne dit pas quel mail vient de quelle adresse)
        assertEquals(ProposalHint(teams = false, top = "Pro, Perso", bottom = ""), proposalHint(sophie))
        // une organisation : ses boîtes, sans le compte de son domaine
        assertEquals(ProposalHint(teams = false, top = "Pro", bottom = ""), proposalHint(lumenOrg))
        assertNull(proposalHint(thomas))
    }

    @Test fun `sans annuaire, tes correspondants du courrier comme avant`() {
        val got = proposalsFromMail(
            listOf(MailContact("lea@x.fr", "Léa", received = 6, sent = 2), MailContact("paul@x.fr", ""), MailContact("LEA@x.fr", "Léa bis")),
            chosen = setOf("paul@x.fr"),
        )
        assertEquals(listOf("lea@x.fr"), got.map { it.address })
        assertEquals("8 mails", got.single().hint!!.bottom)
        assertFalse(got.single().generic)
        assertEquals("paul@x.fr", proposalsFromMail(listOf(MailContact("paul@x.fr", "")), emptySet()).single().shown)
    }
}
