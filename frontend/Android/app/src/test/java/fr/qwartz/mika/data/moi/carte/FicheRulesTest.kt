package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.core.MikaJson
import fr.qwartz.mika.data.moi.Tone
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDateTime
import java.time.ZoneId

/**
 * Ce que montre la fiche d'un lieu et une liste notée (ADR 0259) : les liens du dehors (http ou https seulement), les
 * numéros, les notes et les avis, les dates de lecture, la couverture, les photos et leur crédit, ce que chaque bloc
 * montre — et ses attributions, toujours là —, les filtres d'une liste et la ligne d'un lieu.
 */
class FicheRulesTest {
    private val paris: ZoneId = ZoneId.of("Europe/Paris")
    /** Le vendredi 20 novembre 2026, 23:00 à Paris. */
    private val now = LocalDateTime.of(2026, 11, 20, 23, 0).atZone(paris).toInstant().toEpochMilli()
    private val nbsp = "\u00A0"

    private fun fiche(): PlaceFiche = MikaJson.decodeFromString(
        PlaceFiche.serializer(),
        requireNotNull(javaClass.classLoader?.getResource("carte/contrat/fiche.json")).readText(),
    )

    private fun ms(day: Int, hour: Int, minute: Int = 0, month: Int = 11, year: Int = 2026) =
        LocalDateTime.of(year, month, day, hour, minute).atZone(paris).toInstant().toEpochMilli()

    // ── Les liens ───────────────────────────────────────────────────────

    @Test fun `un lien du dehors ne s'ouvre qu'en http ou https`() {
        assertEquals("https://maps.google.com/?cid=1234567890", safeHref("https://maps.google.com/?cid=1234567890"))
        assertEquals("http://exemple.fr/agenda", safeHref(" http://exemple.fr/agenda "))
        // un domaine nu (un site d'OpenStreetMap) devient https
        assertEquals("https://magmatic.fr/", safeHref("magmatic.fr"))
        assertEquals("https://www.lille.fr/agenda", safeHref("www.lille.fr/agenda"))
        for (bad in listOf(
            "javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,<b>x</b>", "intent://x#Intent;end", "ftp://x.fr/a",
            "file:///etc/passwd", "mailto:a@b.fr", "tel:0320000000", "content://fr.qwartz.mika/x", "//evil.example/x",
            "/api/moi/carte/photo/p:00", "https://", "https://exemple .fr", "pas un lien", "", null,
        )) {
            assertNull(bad, safeHref(bad))
        }
        assertEquals("magmatic.fr", siteLabel("https://www.magmatic.fr/carte"))
        assertEquals("", siteLabel("javascript:alert(1)"))
        assertEquals(LinkText("Camille R.", null), linkText("Camille R.", "javascript:alert(1)"))
    }

    @Test fun `un numéro s'appelle par ses chiffres, le plus du début gardé`() {
        assertEquals("tel:+33320000000", telHref("+33 3 20 00 00 00"))
        assertEquals("tel:0320000000", telHref("03.20.00.00.00"))
        assertNull(telHref("12"))
        assertNull(telHref(""))
        assertNull(telHref("appeler l'accueil"))
    }

    // ── Les mots ────────────────────────────────────────────────────────

    @Test fun `une note, ses étoiles, le nombre d'avis`() {
        assertEquals("4,8", ratingWords(4.8))
        assertEquals("4", ratingWords(4.0))
        assertEquals("3,7", ratingWords(3.66))
        assertEquals("", ratingWords(null))
        assertEquals("15${nbsp}235 avis", countWords(15235))
        assertEquals("1 avis", countWords(1))
        assertEquals("", countWords(null))
        assertEquals(List(5) { StarFill.FULL }, starFills(4.8))
        assertEquals(listOf(StarFill.FULL, StarFill.FULL, StarFill.FULL, StarFill.FULL, StarFill.HALF), starFills(4.5))
        assertEquals(listOf(StarFill.FULL, StarFill.FULL, StarFill.FULL, StarFill.EMPTY, StarFill.EMPTY), starFills(3.2))
        assertEquals(List(5) { StarFill.EMPTY }, starFills(null))
    }

    @Test fun `quand une source a été lue, en mots`() {
        assertEquals("aujourd'hui à 22:00", readWhen(ms(20, 22), now, paris))
        assertEquals("hier à 09:10", readWhen(ms(19, 9, 10), now, paris))
        assertEquals("le 18 novembre", readWhen(ms(18, 9), now, paris))
        assertEquals("le 1er mars 2025", readWhen(ms(1, 9, month = 3, year = 2025), now, paris))
        assertEquals("", readWhen(0, now, paris))
        assertEquals("16 novembre", isoWords("2026-11-16", now, paris))
        assertEquals("3 juin 2025", isoWords("2025-06-03", now, paris))
        assertEquals("", isoWords("hier", now, paris))
    }

    @Test fun `la couverture d'une liste, sa note telle quelle, sinon quand elle a été lue`() {
        val note = "Cette zone n'est lue qu'en partie (cases lues : 9 sur 11) : la suite se lit à la prochaine recherche, ou ce soir."
        assertEquals(note, coverageLine(Coverage(ready = true, cells = 11, loaded = 9, oldest = ms(20, 8), note = note), EVENTS_READ, now, paris))
        assertEquals("Notes Google Maps lues aujourd'hui à 08:00", coverageLine(Coverage(true, 1, 1, ms(20, 8), ""), REVIEWS_READ, now, paris))
        assertEquals("", coverageLine(Coverage(ready = false), REVIEWS_READ, now, paris))
        assertEquals("", coverageLine(null, REVIEWS_READ, now, paris))
        // les notes de ma case arrivent au prochain affichage : la liste se relit une fois
        assertTrue(wantsReread(Coverage(ready = true, cells = 9, loaded = 3), aroundMe = true))
        assertFalse(wantsReread(Coverage(ready = true, cells = 9, loaded = 9), aroundMe = true))
        assertFalse(wantsReread(Coverage(ready = true, cells = 9, loaded = 3), aroundMe = false))
        assertFalse(wantsReread(Coverage(ready = false, cells = 9, loaded = 3), aroundMe = true))
    }

    // ── Les photos ──────────────────────────────────────────────────────

    @Test fun `les photos montrées, une référence de ce serveur, sans doublon, l'office d'abord`() {
        val f = fiche()
        val shown = shownPhotos(f.tourism?.photos, f.reviews?.photos)
        assertEquals(listOf("datatourisme", "google"), shown.map { it.source })
        val again = shownPhotos(f.reviews?.photos, f.reviews?.photos, listOf(Photo(ref = "https://lh3.googleusercontent.com/x"), Photo(ref = "")))
        assertEquals(1, again.size)
        assertEquals("11 photos", photoCount(11))
        assertEquals("1 photo", photoCount(1))
    }

    @Test fun `chaque photo cite son auteur, sa licence, d'où elle vient`() {
        val f = fiche()
        val google = photoCredit(f.reviews!!.photos.single())
        assertEquals(LinkText("Camille R.", "https://www.google.com/maps/contrib/100000000000000000001"), google.author)
        assertEquals("Google Maps", google.source)
        assertEquals("Photo : Camille R. · Google Maps", google.line)
        val office = photoCredit(f.tourism!!.photos.single())
        assertEquals(LinkText("Hello Lille", null), office.author)
        assertEquals("Photo : Hello Lille · CC BY-NC-ND 4.0 · Office de tourisme", office.line)
        assertTrue(photoWhy(f.reviews!!.photos.single()).contains("Google Maps"))
        assertTrue(photoWhy(f.tourism!!.photos.single()).contains("DATAtourisme"))
        // un lien d'auteur douteux : le nom reste, le lien s'en va
        assertEquals(LinkText("X", null), photoCredit(Photo(ref = "p:0", credit = "X", creditUrl = "javascript:alert(1)")).author)
        assertEquals("Photo 2, de Camille R.", photoAlt(f.reviews!!.photos.single(), 1))
    }

    // ── La fiche ────────────────────────────────────────────────────────

    @Test fun `les étiquettes, ouvert à sa couleur, la cuisine, le prix, la note de Google`() {
        val f = fiche()
        val tags = placeTags(f.place, f.reviews)
        assertEquals(listOf(TagKind.OPEN, TagKind.CUISINE, TagKind.PRICE, TagKind.RATING), tags.map { it.kind })
        assertEquals(Tone.OK, tags[0].tone)
        assertEquals("4,8", tags[3].text)
        assertEquals(Tone.DANGER, placeTags(Place(openText = "Fermé · ouvre à 19:00", openState = "closed"), null).single().tone)
        assertEquals(Tone.WARN, placeTags(Place(openText = "Horaires : voir le site", openState = "unknown"), null).single().tone)
        assertTrue(placeTags(Place(name = "Rien"), null).isEmpty())
    }

    @Test fun `appeler et le site, d'OpenStreetMap d'abord, sinon de l'office`() {
        val f = fiche()
        assertEquals(PlaceContacts("+33 3 20 00 00 00", "tel:+33320000000", "https://magmatic.example/"), placeContacts(f))
        val office = f.copy(osm = f.osm!!.copy(phone = "", website = "javascript:alert(1)"))
        assertEquals("tel:+33320000000", placeContacts(office).tel)
        assertNull(placeContacts(office).site)
        assertEquals(PlaceContacts("", null, null), placeContacts(null))
    }

    @Test fun `un fait ouvre un numéro ou une adresse web, rien d'autre`() {
        assertEquals("tel:+33320000000", factLink(Fact("Téléphone", "+33 3 20 00 00 00")))
        assertEquals("https://magmatic.fr/menu", factLink(Fact("Site web", "https://magmatic.fr/menu")))
        assertEquals("magmatic.fr", factText(Fact("Site web", "https://www.magmatic.fr/menu")))
        assertNull(factLink(Fact("Site", "javascript:alert(1)")))
        assertEquals("javascript:alert(1)", factText(Fact("Site", "javascript:alert(1)")))
        assertNull(factLink(Fact("Terrasse", "oui")))
    }

    @Test fun `le bloc Google Maps, son nom et son lien, la note, l'auteur et la date de chaque avis`() {
        val g = googleShown(fiche().reviews!!, now, paris)
        assertTrue(g.found)
        assertEquals("Google Maps", g.label)
        assertEquals("https://maps.google.com/?cid=1234567890", g.link)
        assertEquals(4.8, g.rating!!, 0.0)
        assertEquals("15${nbsp}235 avis", g.count)
        assertEquals("€€ · 30–50 €", g.price)
        assertEquals("Pizzas au feu de bois dans une salle animée.", g.summary)
        assertEquals(listOf(Fact("Végétarien", "oui (selon Google)")), g.facts)
        val r = g.reviews.single()
        assertEquals(LinkText("Camille R.", "https://www.google.com/maps/contrib/100000000000000000001"), r.author)
        assertEquals("il y a 2 semaines", r.relative)
        assertEquals(listOf("Pâte légère, service rapide.", "On reviendra."), r.paragraphs)
        assertFalse(r.long)
        assertTrue(g.cached.startsWith("Lu "))
        assertTrue(g.cached.endsWith("gardé sur ce serveur"))
    }

    @Test fun `un avis sans auteur ou au lien douteux garde une attribution, sans lien`() {
        val base = fiche().reviews!!
        val r = base.copy(reviews = listOf(Review(rating = 2.0, text = "x".repeat(LONG_REVIEW + 1), author = "", authorUrl = "https://a.b/c"),
            Review(rating = 5.0, text = "Bien", author = "Léa", authorUrl = "javascript:alert(1)")))
        val g = googleShown(r, now, paris)
        assertEquals(LinkText("Un visiteur"), g.reviews[0].author)
        assertTrue(g.reviews[0].long)
        assertEquals(LinkText("Léa", null), g.reviews[1].author)
        // un lien de page douteux : le nom « Google Maps » reste, sans lien
        assertNull(googleShown(base.copy(url = "javascript:alert(1)"), now, paris).link)
    }

    @Test fun `Google n'a rien de ce lieu, sa note le dit, sans note ni lien`() {
        val note = "Rien trouvé sur Google sous ce nom à moins de 100 m (cherché le 20 novembre)."
        val g = googleShown(ReviewsPart(source = "google", sourceLabel = "Google Maps", found = false, note = note), now, paris)
        assertFalse(g.found)
        assertEquals(note, g.note)
        assertNull(g.link)
        assertTrue(g.reviews.isEmpty())
        assertEquals("Google Maps", g.label)
        assertEquals(GOOGLE_NOTHING, googleShown(ReviewsPart(found = false), now, paris).note)
        assertEquals(GOOGLE_LABEL, googleShown(ReviewsPart(found = false), now, paris).label)
    }

    @Test fun `les infos pratiques d'OpenStreetMap portent toujours sa mention`() {
        val o = osmShown(fiche().osm, now, paris)!!
        assertEquals(listOf("Adresse", "Cuisine", "Horaires", "Terrasse", "Téléphone", "Site"), o.rows.map { it.label })
        assertEquals(LinkText("© les contributeurs d'OpenStreetMap", "https://www.openstreetmap.org/copyright"), o.attribution)
        assertEquals("extrait du 16 novembre, dans l'index de ce serveur", o.extract)
        assertEquals(LinkText("Corriger sur OpenStreetMap", "https://www.openstreetmap.org/node/4021153781"), o.fix)
        // sans mention du serveur : la sienne, jamais rien
        val bare = osmShown(OsmPart(address = "1 rue X", attribution = ""), now, paris)!!
        assertEquals(OSM_CREDIT, bare.attribution.text)
        assertNull(osmShown(OsmPart(), now, paris))
        assertNull(osmShown(null, now, paris))
    }

    @Test fun `l'office de tourisme, qui l'a écrit et quand, sa licence`() {
        val t = tourismShown(fiche().tourism)!!
        assertEquals(listOf("Pizzeria napolitaine du Vieux-Lille.", "Pâte maturée 48 heures."), t.paragraphs)
        assertEquals(listOf("Qualité Tourisme"), t.labels)
        assertEquals(listOf("Tarifs", "Téléphone"), t.rows.map { it.label })
        assertEquals("DATAtourisme · Hello Lille, mis à jour le 3 juin 2025", t.attribution)
        assertEquals(LinkText("Licence Ouverte 2.0", "https://www.etalab.gouv.fr/licence-ouverte-open-licence/"), t.licence)
        assertEquals("https://data.datatourisme.fr/6b0e2f4a", t.fiche?.url)
        assertEquals(TOURISM_SOURCE, tourismShown(TourismPart(description = "Un texte."))!!.attribution)
        assertNull(tourismShown(TourismPart()))
    }

    @Test fun `un événement tout près, et la ligne sous le nom d'une fiche`() {
        val f = fiche()
        assertEquals("sam. 21 nov. · 19:00–22:00 · 780 m · 12/8€ - Gratuit moins de 18 ans", nearEventLine(f.events.single()))
        assertEquals("Restaurant · Lille", ficheSub(f.place))
        assertEquals("Restaurant · Lille · à 240 m", ficheSub(f.place.copy(distanceM = 240.0)))
    }

    // ── Une liste ───────────────────────────────────────────────────────

    @Test fun `la ligne d'un lieu, sa note d'abord, sinon ce qu'il est, ouvert ou fermé`() {
        val found = MikaJson.decodeFromString(
            PlacesFound.serializer(),
            requireNotNull(javaClass.classLoader?.getResource("carte/contrat/lieux.json")).readText(),
        )
        val rated = placeRow(found.places[0])
        assertEquals(4.8, rated.rating!!, 0.0)
        assertEquals("(15${nbsp}235)", rated.count)
        assertEquals("€€ · Pizza", rated.line)
        assertEquals("Ouvert · ferme à 22:30", rated.open)
        assertEquals(Tone.OK, rated.openTone)
        val plain = placeRow(found.places[1])
        assertNull(plain.rating)
        assertEquals("", plain.count)
        assertEquals("Restaurant · Lille · Régionale", plain.line)
        assertEquals("", plain.open)
    }

    @Test fun `la fiche d'un lieu s'ouvre par son objet OSM, sinon sa ligne, une adresse n'en a pas`() {
        assertEquals("n4021153781", ficheId(Place(id = "l22871", osm = "n4021153781")))
        assertEquals("l22871", ficheId(Place(id = "l22871")))
        assertEquals("t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", ficheId(Place(id = "t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10")))
        assertNull(ficheId(Place(id = "a:3", category = "adresse")))
        assertNull(ficheId(Place(id = "")))
    }

    @Test fun `les filtres, posés ou non, une puce de plus ou de moins, l'ordre suivant`() {
        assertFalse(filtersOn(PlaceFilters(sort = SORT_RATING)))
        assertTrue(filtersOn(PlaceFilters(open = true)))
        assertTrue(filtersOn(PlaceFilters(minRating = MIN_RATING)))
        assertTrue(filtersOn(PlaceFilters(cuisine = "pizza")))
        val one = toggledFeature(PlaceFilters(), "terrasse")
        assertEquals(listOf("terrasse"), one.features)
        assertEquals(listOf("terrasse", "vegan"), toggledFeature(one, "vegan").features)
        assertTrue(toggledFeature(one, "terrasse").features.isEmpty())
        val sorts = listOf(Category("distance", "Les plus proches"), Category("rating", "Les mieux notés"))
        assertEquals("rating", nextSort(sorts, "distance"))
        assertEquals("distance", nextSort(sorts, "rating"))
        assertEquals("distance", nextSort(sorts, "inconnu"))
        assertEquals("Les mieux notés", sortLabel(sorts, "rating"))
        assertEquals("Les plus proches", sortLabel(sorts, "?"))
        assertEquals("distance", nextSort(sorts.take(1), "distance"))
    }

    @Test fun `les cuisines du filtre, celles de la liste, les plus fréquentes d'abord, la choisie toujours`() {
        val places = listOf(
            Place(cuisine = "Pizza"), Place(cuisine = "italienne, pizza"), Place(cuisine = "Française"), Place(cuisine = ""),
            Place(cuisine = "x".repeat(41)),
        )
        assertEquals(listOf("Pizza", "Française", "Italienne"), cuisineChoices(places))
        assertEquals(listOf("Thaï", "Pizza", "Française", "Italienne"), cuisineChoices(places, "Thaï"))
        assertEquals(listOf("Pizza", "Française", "Italienne"), cuisineChoices(places, "pizza"))
        assertEquals(12, cuisineChoices((1..20).map { Place(cuisine = "Cuisine $it") }).size)
    }

    @Test fun `les attributions sont là sur la fiche entière du contrat`() {
        val f = fiche()
        assertNotNull(googleShown(f.reviews!!, now, paris).link)
        assertTrue(googleShown(f.reviews!!, now, paris).reviews.all { it.author.text.isNotBlank() && it.relative.isNotBlank() })
        assertTrue(shownPhotos(f.tourism?.photos, f.reviews?.photos).all { photoCredit(it).author != null })
        assertTrue(osmShown(f.osm, now, paris)!!.attribution.text.startsWith("©"))
        assertTrue(tourismShown(f.tourism)!!.attribution.contains("Hello Lille"))
    }

    // ── Ce qu'une liste cite (R2) ───────────────────────────────────────

    private fun listed(): List<Place> = MikaJson.decodeFromString(
        PlacesFound.serializer(),
        requireNotNull(javaClass.classLoader?.getResource("carte/contrat/lieux.json")).readText(),
    ).places

    @Test fun `une vignette de liste porte l'auteur de sa photo, sans lui, pas de vignette (R2-A01)`() {
        val magmatic = listed().first()
        val thumb = listThumb(magmatic)!!
        assertEquals("p:3f1c9a0e5b7d2c4e6f8a1b3c5d7e9f02", thumb.ref)
        assertEquals(LinkText("Camille R.", "https://www.google.com/maps/contrib/100000000000000000001"), photoCredit(thumb).author)
        assertEquals("Photo : Camille R. · Google Maps", photoCredit(thumb).line)
        // un regard de Mika (qui ne garde pas de crédit), un serveur d'avant : l'icône de la catégorie
        assertNull(listThumb(magmatic.copy(photoCredit = "")))
        assertNull(listThumb(magmatic.copy(photo = "https://lh3.googleusercontent.com/x")))
        assertNull(listThumb(listed()[1]))
        val concert = EventItem(id = "e:450c81b3-6ffa-3d4e-9c1b-2a7f0e5d8c41", name = "Éclats du rire !", photo = "p:8e2d4c6b0a1f3e5d7c9b2a4f6e8d0c13",
            photoSource = "datatourisme", photoCredit = "Hello Lille", photoLicence = "CC BY-NC-ND 4.0")
        assertEquals("Photo : Hello Lille · CC BY-NC-ND 4.0 · Office de tourisme", photoCredit(listThumb(concert)!!).line)
        assertNull(listThumb(concert.copy(photoCredit = " ")))
    }

    @Test fun `la bande d'une fiche cite l'auteur, puis la licence d'une photo de l'office (R2-A02)`() {
        val f = fiche()
        assertEquals(listOf(LinkText("Hello Lille", null), LinkText("CC BY-NC-ND 4.0")), bandCredit(f.tourism!!.photos.single()))
        assertEquals(listOf(LinkText("Camille R.", "https://www.google.com/maps/contrib/100000000000000000001")), bandCredit(f.reviews!!.photos.single()))
        assertEquals(emptyList<LinkText>(), bandCredit(Photo(ref = "p:0")))
    }

    @Test fun `« Google Maps » partout où une note Google se montre (R2-A03)`() {
        val rated = listOf(Place(rating = 4.8, reviews = 15235))
        assertEquals("Notes : Google Maps", ratingsLine(rated, null, now, paris))
        assertEquals("Notes : Google Maps", ratingsLine(rated, Coverage(ready = true, cells = 0, loaded = 0), now, paris))
        assertEquals(
            "Notes : Google Maps · Les notes de cet endroit ne sont pas encore toutes lues.",
            ratingsLine(rated, Coverage(ready = true, cells = 4, loaded = 1, note = "Les notes de cet endroit ne sont pas encore toutes lues."), now, paris),
        )
        assertEquals("Notes Google Maps lues hier à 22:00", ratingsLine(rated, Coverage(ready = true, cells = 1, loaded = 1, oldest = ms(19, 22)), now, paris))
        // rien de noté, rien de lu : rien à citer
        assertEquals("", ratingsLine(listOf(Place()), null, now, paris))
        // l'étiquette de note d'une fiche avant son bloc Google le dit ; avec lui, le bloc le dit
        assertEquals(GOOGLE_LABEL, placeTags(Place(rating = 4.8), null).single { it.kind == TagKind.RATING }.from)
        assertEquals("", placeTags(Place(rating = 4.8), fiche().reviews).single { it.kind == TagKind.RATING }.from)
    }

    @Test fun `après « Actualiser », la ligne de la liste prend la note relue, sa distance gardée (R2-A06)`() {
        val row = Place(id = "l22871", osm = "n4021153781", name = "Magmatic", rating = 4.7, reviews = 1200, distanceM = 240.0)
        val other = Place(id = "l22918", osm = "w45911888", name = "Le Coq Hardi", distanceM = 310.0)
        val fresh = Place(id = "l22871", osm = "n4021153781", name = "Magmatic", rating = 4.8, reviews = 1260)
        val got = withRefreshed(listOf(row, other), "n4021153781", fresh)
        assertEquals(listOf(4.8, null), got.map { it.rating })
        assertEquals(1260L, got[0].reviews)
        assertEquals(240.0, got[0].distanceM!!, 0.0)
        assertEquals(other, got[1])
    }

    @Test fun `un regard s'ouvre dans son onglet - des événements dans Événements (R2-A04)`() {
        assertEquals("evenements", regardTab(Regard(kind = Regard.KIND_LOOK, what = Regard.WHAT_EVENTS)))
        assertEquals("itineraire", regardTab(Regard(kind = Regard.KIND_LOOK, what = Regard.WHAT_ROUTE)))
        assertEquals("explorer", regardTab(Regard(kind = Regard.KIND_LOOK, what = "lieux")))
        assertEquals("explorer", regardTab(Regard(kind = Regard.KIND_MAP)))
        // la miniature lue suit la même règle
        assertEquals("evenements", regardMini("840", Regard(kind = Regard.KIND_LOOK, what = Regard.WHAT_EVENTS)).opens.tab)
    }

    @Test fun `un lieu des données touristiques d'un regard rouvre sa fiche par son identifiant entier (R2-M01)`() {
        assertEquals("t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", ficheId(Place(id = "t:6b0e2f4a-8c1d-3e5f-9a7b-0c2d4e6f8a10", name = "Le Lys")))
        // coupé comme le serveur le gardait avant : pas de fiche
        assertNull(ficheId(Place(id = "t:6b0e2f4a-8c1d-3e5", name = "Le Lys")))
    }
}
