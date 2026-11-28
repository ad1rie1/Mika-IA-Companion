package fr.qwartz.mika.data.moi.carte

import fr.qwartz.mika.data.moi.Tone
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.text.Collator
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit
import java.util.Locale
import kotlin.math.roundToLong

/*
 * Ce que disent les sources d'un lieu, et comment on les cite (ADR 0259 ; `protocole-moi.md` § 10, « Ce qu'un client
 * montre avec » ; le contrat : `output/carte-avis/SUIVI.md`), sans Compose ni réseau, portés de
 * `frontend/Web/src/screens/carte/sources.ts`, `fiche.ts`, `view.ts` et `format.ts` sans changer leurs règles : un lien
 * vers le dehors (http ou https seulement), un numéro à appeler, une note et le nombre d'avis, une date de lecture en
 * mots, la ligne de couverture d'une liste, une photo et son crédit, ce que chaque bloc d'une fiche montre (Google Maps,
 * OpenStreetMap, l'office de tourisme), les filtres d'une liste et la ligne d'un lieu. Les attributions ne manquent
 * jamais : un bloc sans elles ne se forme pas.
 */

// ── Les liens vers le dehors ────────────────────────────────────────────

/** Un nom de domaine sans protocole (« magmatic.fr », « www.lille.fr/agenda ») : OpenStreetMap en a. */
private val BARE_DOMAIN = Regex("""^(?:[a-z0-9-]+\.)+[a-z]{2,}(?:[/?#].*)?$""", RegexOption.IGNORE_CASE)
private val SCHEME = Regex("""^[a-z][a-z0-9+.-]*:""", RegexOption.IGNORE_CASE)

/**
 * Une adresse du dehors qu'on peut ouvrir dans le navigateur : http ou https seulement — ni `javascript:`, ni `data:`,
 * ni `intent:`, ni un chemin de ce serveur. Un domaine sans protocole (un site d'OpenStreetMap) devient https. Sinon
 * `null`, et le texte reste du texte.
 */
fun safeHref(url: String?): String? {
    var text = url?.trim().orEmpty()
    if (text.isEmpty() || text.any { it.isWhitespace() }) return null
    if (!SCHEME.containsMatchIn(text)) {
        if (!BARE_DOMAIN.matches(text)) return null
        text = "https://$text"
    }
    // l'analyseur d'OkHttp ne connaît que http et https : tout autre schéma rend `null`
    val u = text.toHttpUrlOrNull() ?: return null
    return if (u.host.isBlank()) null else u.toString()
}

/** Un numéro à appeler : `tel:` de ses chiffres (le « + » du début gardé), sinon `null`. */
fun telHref(phone: String?): String? {
    val text = phone?.trim().orEmpty()
    val digits = text.filter { it in '0'..'9' }
    if (digits.length !in 3..20) return null
    return "tel:${if (text.startsWith("+")) "+" else ""}$digits"
}

/** Le site d'un lieu en court, pour un bouton ou une ligne : « magmatic.fr » ; rien qui s'ouvre : vide. */
fun siteLabel(url: String?): String {
    val href = safeHref(url) ?: return ""
    return (href.toHttpUrlOrNull()?.host ?: return "").removePrefix("www.")
}

/** Un texte et, s'il en a un sûr, le lien qu'il ouvre dehors (http ou https). */
data class LinkText(val text: String, val url: String? = null)

/** Un lien sûr, ou le texte seul. */
fun linkText(text: String, url: String?): LinkText = LinkText(text, safeHref(url))

// ── Les textes et les nombres ───────────────────────────────────────────

/** Un texte en paragraphes (un avis, une description) : une ligne, un paragraphe ; les vides s'en vont. */
fun paragraphs(text: String?): List<String> = text.orEmpty().split(Regex("\n+")).map { it.trim() }.filter { it.isNotEmpty() }

private const val NBSP = "\u00A0"

/** Un nombre, ses milliers séparés d'une espace insécable : « 15 235 ». */
fun thousands(n: Long): String {
    if (n < 0) return "-" + thousands(-n)
    return n.toString().reversed().chunked(3).joinToString(NBSP).reversed()
}

/** Une note sur 5, à la française : « 4,8 », « 4 » ; inconnue : vide. */
fun ratingWords(n: Double?): String {
    if (n == null || !n.isFinite()) return ""
    val r = (n * 10).roundToLong() / 10.0
    return if (r == Math.floor(r)) r.toLong().toString() else String.format(Locale.ROOT, "%.1f", r).replace('.', ',')
}

/** « 15 235 avis », « 1 avis » ; inconnu : vide. */
fun countWords(n: Long?): String = if (n == null || n < 0) "" else "${thousands(n)} avis"

/** Combien d'étoiles pleines, à moitié, vides pour une note (comme le web : une moitié dès 0,25, pleine dès 0,75). */
enum class StarFill { FULL, HALF, EMPTY }

fun starFills(rating: Double?): List<StarFill> {
    val v = (rating ?: 0.0).takeIf { it.isFinite() }?.coerceIn(0.0, 5.0) ?: 0.0
    return (1..5).map { i ->
        when {
            v >= i - 0.25 -> StarFill.FULL
            v >= i - 0.75 -> StarFill.HALF
            else -> StarFill.EMPTY
        }
    }
}

// ── Les dates de lecture ────────────────────────────────────────────────

private val MONTHS_LONG = listOf(
    "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre",
)

private fun localDay(ms: Long, zone: ZoneId): LocalDate = Instant.ofEpochMilli(ms).atZone(zone).toLocalDate()

/** « 18 novembre », « 1er mars », et l'année si ce n'est pas celle de [today]. */
fun dayWords(d: LocalDate, today: LocalDate): String {
    val n = if (d.dayOfMonth == 1) "1er" else d.dayOfMonth.toString()
    return "$n ${MONTHS_LONG[d.monthValue - 1]}${if (d.year != today.year) " ${d.year}" else ""}"
}

/** Quand une source a été lue : « aujourd'hui à 22:00 », « hier à 09:10 », « le 18 novembre » ; inconnu : vide. */
fun readWhen(ms: Long, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (ms <= 0) return ""
    val t = Instant.ofEpochMilli(ms).atZone(zone)
    val today = localDay(now, zone)
    val clock = String.format(Locale.ROOT, "%02d:%02d", t.hour, t.minute)
    return when (ChronoUnit.DAYS.between(t.toLocalDate(), today)) {
        in Long.MIN_VALUE..0L -> "aujourd'hui à $clock"
        1L -> "hier à $clock"
        else -> "le ${dayWords(t.toLocalDate(), today)}"
    }
}

/** « 16 novembre » d'une date `AAAA-MM-JJ` (l'extrait d'OpenStreetMap, la mise à jour d'une fiche) ; illisible : vide. */
fun isoWords(iso: String?, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val d = isoDay(iso.orEmpty().take(10)) ?: return ""
    return dayWords(d, localDay(now, zone))
}

/** Ce qu'on dit d'une liste de lieux notée, et d'une liste d'événements, quand rien d'autre n'est à en dire. */
const val REVIEWS_READ = "Notes Google Maps lues"
const val EVENTS_READ = "Événements des offices de tourisme lus"

/**
 * La ligne de couverture d'une liste : sa `note` quand elle en a une (telle quelle : « lue en partie… », un quota
 * atteint), sinon quand la source a été lue ([what] : « Notes Google Maps lues » → « … le 18 novembre »). Rien de prêt :
 * vide.
 */
fun coverageLine(c: Coverage?, what: String, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    if (c == null) return ""
    c.note.trim().takeIf { it.isNotEmpty() }?.let { return it }
    if (!c.ready || c.oldest <= 0) return ""
    return "$what ${readWhen(c.oldest, now, zone)}"
}

/**
 * La ligne des notes d'une liste de lieux (R2-A03) : « Google Maps » dès qu'un de ses lieux a une note, quelle que soit
 * la couverture — « Notes Google Maps lues le 18 novembre » quand on sait quand, sinon « Notes : Google Maps » —, puis la
 * `note` de la couverture, telle quelle. Ni note ni couverture : vide (rien à citer).
 */
fun ratingsLine(places: List<Place>, c: Coverage?, now: Long, zone: ZoneId = ZoneId.systemDefault()): String {
    val rated = places.any { it.rating?.isFinite() == true }
    val read = if (c != null && c.ready && c.oldest > 0) "$REVIEWS_READ ${readWhen(c.oldest, now, zone)}" else ""
    val head = read.ifEmpty { if (rated) "Notes : $GOOGLE_LABEL" else "" }
    return listOf(head, c?.note?.trim().orEmpty()).filter { it.isNotEmpty() }.joinToString(" · ")
}

/**
 * La liste après « Actualiser » (R2-A06) : la ligne du lieu relu (même fiche, [id]) prend ce que la fiche relue en dit —
 * sa note, son nombre d'avis, sa photo… —, en gardant sa distance et sa place le long d'un trajet, que la fiche ne sait pas.
 */
fun withRefreshed(places: List<Place>, id: String, fresh: Place): List<Place> =
    places.map { p -> if (ficheId(p) == id) fresh.copy(distanceM = p.distanceM, alongM = p.alongM) else p }

/**
 * Après « Autour de moi », le serveur a mis en file les notes de ta case : elles arrivent au prochain affichage — la
 * liste se relit une fois, [PRELOAD_REREAD_MS] plus tard, si la couverture dit des cases pas encore toutes lues.
 */
fun wantsReread(found: Coverage?, aroundMe: Boolean): Boolean =
    aroundMe && found != null && found.ready && found.loaded < found.cells

const val PRELOAD_REREAD_MS = 6_000L

// ── Les photos ──────────────────────────────────────────────────────────

const val SOURCE_GOOGLE = "google"
const val SOURCE_TOURISM = "datatourisme"

/** D'où vient une photo, en mots : « Google Maps », « Office de tourisme ». */
fun photoSource(p: Photo): String = when (p.source) {
    SOURCE_GOOGLE -> "Google Maps"
    SOURCE_TOURISM -> "Office de tourisme"
    else -> "Photo"
}

/**
 * Les photos qu'on peut montrer (une référence de ce serveur), sans doublon, dans l'ordre des listes : l'office de
 * tourisme, puis Google. Une photo sans référence valide ne se montre pas : son adresse ne se referait pas.
 */
fun shownPhotos(vararg lists: List<Photo>?): List<Photo> {
    val out = ArrayList<Photo>()
    val known = HashSet<String>()
    for (list in lists) for (p in list.orEmpty()) {
        val ref = photoRef(p.ref) ?: continue
        if (known.add(ref)) out += p
    }
    return out
}

/** Ce qu'on cite d'une photo, toujours avec elle : son auteur (lié), sa licence (l'office de tourisme), d'où elle vient. */
data class PhotoCredit(val author: LinkText?, val licence: String, val source: String) {
    /** En une ligne, pour un lecteur d'écran et la visionneuse : « Photo : Camille R. · Google Maps ». */
    val line: String
        get() = listOfNotNull(author?.let { "Photo : ${it.text}" }, licence.ifBlank { null }, source).joinToString(" · ")
}

fun photoCredit(p: Photo): PhotoCredit = PhotoCredit(
    author = p.credit.trim().takeIf { it.isNotEmpty() }?.let { linkText(it, p.creditUrl) },
    licence = p.licence.trim(),
    source = photoSource(p),
)

/** Ce que la visionneuse dit d'une photo : d'où elle vient et ce qu'on en garde. */
fun photoWhy(p: Photo): String = if (p.source == SOURCE_GOOGLE) {
    "Publiée sur Google Maps, gardée sur ce serveur le temps du cache."
} else {
    "De l'office de tourisme, par DATAtourisme : son crédit et sa licence se montrent toujours."
}

/**
 * Ce qu'une photo de la bande d'une fiche dit sur elle (R2-A02) : son auteur (lié), puis sa licence — celle d'une photo
 * de l'office de tourisme se montre là où elle se montre, pas seulement dans la visionneuse.
 */
fun bandCredit(p: Photo): List<LinkText> = listOfNotNull(
    p.credit.trim().takeIf { it.isNotEmpty() }?.let { linkText(it, p.creditUrl) },
    p.licence.trim().takeIf { it.isNotEmpty() }?.let { LinkText(it) },
)

/**
 * La vignette d'une ligne de liste (R2-A01) : sa première photo, seulement avec son auteur — il se montre sur la ligne,
 * jamais dans le seul texte alternatif ; sans lui (un regard de Mika, qui ne garde pas de crédit ; un serveur d'avant),
 * pas de vignette. Une référence qui n'est pas de ce serveur : pas de vignette non plus.
 */
fun listThumb(p: Place): Photo? = thumbOf(p.photo, p.photoSource, p.photoCredit, p.photoCreditUrl, p.photoLicence)

fun listThumb(e: EventItem): Photo? = thumbOf(e.photo, e.photoSource, e.photoCredit, e.photoCreditUrl, e.photoLicence)

private fun thumbOf(ref: String, source: String, credit: String, creditUrl: String, licence: String): Photo? {
    val r = photoRef(ref) ?: return null
    val who = credit.trim().ifEmpty { return null }
    return Photo(ref = r, source = source, credit = who, creditUrl = creditUrl, licence = licence.trim())
}

/**
 * Le cache disque des photos (R2-A08) : ce qu'il garde se ressert tant que l'âge que le serveur lui a donné
 * (`Cache-Control: max-age`) n'est pas passé — au-delà, ou sans âge dit, ou qu'il ne faut pas garder (`no-store`,
 * `no-cache`), il se redemande (une photo dont les droits ont pris fin répond alors 404).
 */
fun photoFresh(cacheControl: String?, responseMillis: Long, now: Long): Boolean {
    val parts = cacheControl.orEmpty().split(',').map { it.trim().lowercase(Locale.ROOT) }
    if (parts.any { it == "no-store" || it == "no-cache" }) return false
    val maxAge = parts.firstNotNullOfOrNull { it.removePrefix("max-age=").takeIf { v -> v != it }?.toLongOrNull() } ?: return false
    val age = now - responseMillis
    return age >= 0 && age < maxAge * 1000
}

/** Le temps qu'une photo reste au cache mémoire avant de repasser par le disque (R3-11). */
const val PHOTO_MEMORY_MS = 3_600_000L

/**
 * La clé d'une photo au cache mémoire (R3-11) : le cache mémoire de Coil 3 ressert une image avant toute requête, sans
 * passer par la stratégie du disque ([photoFresh]) — une photo aux droits finis restait visible tant que l'application
 * vivait. Sa clé change chaque heure : passé ce temps, la photo repasse par le disque (son `max-age`), puis par le
 * serveur (son 404).
 */
fun photoMemoryKey(url: String, now: Long): String = "$url#${Math.floorDiv(now, PHOTO_MEMORY_MS)}"

/** Ce qu'une photo dit à un lecteur d'écran : sa légende, sinon « Photo 2, de Camille R. ». */
fun photoAlt(p: Photo, i: Int): String =
    p.caption.trim().ifEmpty { "Photo ${i + 1}${if (p.credit.isNotBlank()) ", de ${p.credit.trim()}" else ""}" }

/** « 11 photos », « 1 photo ». */
fun photoCount(n: Int): String = "$n photo${if (n > 1) "s" else ""}"

// ── La fiche d'un lieu ──────────────────────────────────────────────────

/** Ce qu'une étiquette de la fiche dit : ouvert ou fermé, la cuisine, le prix, la note. */
enum class TagKind { OPEN, CUISINE, PRICE, RATING, WHEN, DISTANCE }

/** Une étiquette ; [from] : d'où vient ce qu'elle dit, quand rien d'autre sur l'écran ne le nomme (« Google Maps »). */
data class FicheTag(val kind: TagKind, val text: String, val tone: Tone = Tone.NEUTRAL, val rating: Double? = null, val from: String = "")

/** Ouvert (vert), fermé (rouge), ou des horaires qu'on ne comprend pas (ambre). */
fun openTone(state: String): Tone = when (state) {
    "open" -> Tone.OK
    "closed" -> Tone.DANGER
    else -> Tone.WARN
}

/**
 * Les étiquettes d'un lieu : ouvert ou fermé, sa cuisine, son prix, sa note (celles de Google, s'il en a une fiche). Une
 * note qui ne vient pas du bloc Google de la fiche (celle de la liste, en attendant la fiche) dit d'où elle vient (R2).
 */
fun placeTags(p: Place, r: ReviewsPart?): List<FicheTag> {
    val fromBlock = r?.found == true && r.rating != null
    val rating = if (fromBlock) r!!.rating else p.rating
    val price = if (r?.found == true && r.price.isNotBlank()) r.price else p.price
    return buildList {
        p.openText.trim().takeIf { it.isNotEmpty() }?.let { add(FicheTag(TagKind.OPEN, it, openTone(p.openState))) }
        p.cuisine.trim().takeIf { it.isNotEmpty() }?.let { add(FicheTag(TagKind.CUISINE, it)) }
        price.trim().takeIf { it.isNotEmpty() }?.let { add(FicheTag(TagKind.PRICE, it)) }
        if (rating != null && rating.isFinite()) {
            add(FicheTag(TagKind.RATING, ratingWords(rating), rating = rating, from = if (fromBlock) "" else GOOGLE_LABEL))
        }
    }
}

private val PHONE_LABEL = Regex("t[ée]l[ée]phone|portable|fax", RegexOption.IGNORE_CASE)
private val SITE_LABEL = Regex("site|web", RegexOption.IGNORE_CASE)

/** Le numéro et le site d'un lieu : d'OpenStreetMap d'abord, sinon de l'office de tourisme. */
data class PlaceContacts(val phone: String, val tel: String?, val site: String?)

fun placeContacts(f: PlaceFiche?): PlaceContacts {
    val contacts = f?.tourism?.contacts.orEmpty()
    val phone = f?.osm?.phone?.trim()?.ifEmpty { null }
        ?: contacts.firstOrNull { PHONE_LABEL.containsMatchIn(it.label) }?.value?.trim().orEmpty()
    val site = safeHref(f?.osm?.website) ?: safeHref(contacts.firstOrNull { SITE_LABEL.containsMatchIn(it.label) }?.value)
    return PlaceContacts(phone, telHref(phone), site)
}

/** Des faits qu'on montre : un libellé et une valeur, tous deux écrits. */
fun shownFacts(facts: List<Fact>): List<Fact> = facts.filter { it.label.isNotBlank() && it.value.isNotBlank() }

/** Ce qu'un fait ouvre : un numéro s'appelle, une adresse web s'ouvre dehors ; le reste n'ouvre rien. */
fun factLink(f: Fact): String? {
    val value = f.value.trim()
    if (PHONE_LABEL.containsMatchIn(f.label)) return telHref(value)
    if (value.startsWith("http://", ignoreCase = true) || value.startsWith("https://", ignoreCase = true)) return safeHref(value)
    return null
}

/** Ce qu'un fait montre : une adresse web en court (« magmatic.fr »), le reste tel quel. */
fun factText(f: Fact): String {
    val value = f.value.trim()
    val link = factLink(f)
    return if (link != null && !link.startsWith("tel:")) siteLabel(link).ifEmpty { value } else value
}

/** Au-delà de tant de caractères, un avis se replie (« Lire la suite »). */
const val LONG_REVIEW = 320

/** Un avis tel qu'on le montre : sa note, son auteur (lié à sa page), sa date en mots, son texte en paragraphes. */
data class ReviewShown(
    val rating: Double?,
    val author: LinkText,
    val relative: String,
    val paragraphs: List<String>,
    val long: Boolean,
)

/**
 * Le bloc « Google Maps » : son nom et son lien (« Voir sur Google Maps »), la note, le nombre d'avis, le prix et sa
 * fourchette, le résumé, ce que Google ajoute à la fiche d'OpenStreetMap, les avis (chacun avec son auteur, son lien et
 * sa date en mots), sa `note`, et quand ce serveur l'a lu. [found] faux : seulement pourquoi ([note]) — rien trouvé sous
 * ce nom, ou pourquoi on n'a pas pu chercher.
 */
data class GoogleShown(
    val label: String,
    val found: Boolean,
    val link: String?,
    val rating: Double?,
    val count: String,
    val price: String,
    val summary: String,
    val facts: List<Fact>,
    val reviews: List<ReviewShown>,
    val note: String,
    val cached: String,
)

const val GOOGLE_LABEL = "Google Maps"
const val GOOGLE_NOTHING = "Google n'a rien de ce lieu."

fun googleShown(r: ReviewsPart, now: Long, zone: ZoneId = ZoneId.systemDefault()): GoogleShown {
    val label = r.sourceLabel.trim().ifEmpty { GOOGLE_LABEL }
    val cached = if (r.cached > 0) "Lu ${readWhen(r.cached, now, zone)} · gardé sur ce serveur" else ""
    if (!r.found) {
        return GoogleShown(label, false, null, null, "", "", "", emptyList(), emptyList(), r.note.trim().ifEmpty { GOOGLE_NOTHING }, cached)
    }
    val reviews = r.reviews.map { x ->
        ReviewShown(
            rating = x.rating?.takeIf { it.isFinite() },
            author = x.author.trim().takeIf { it.isNotEmpty() }?.let { linkText(it, x.authorUrl) } ?: LinkText("Un visiteur"),
            relative = x.relative.trim(),
            paragraphs = paragraphs(x.text),
            long = x.text.length > LONG_REVIEW,
        )
    }
    return GoogleShown(
        label = label,
        found = true,
        link = safeHref(r.url),
        rating = r.rating?.takeIf { it.isFinite() },
        count = countWords(r.count),
        price = listOf(r.price, r.priceRange).map { it.trim() }.filter { it.isNotEmpty() }.joinToString(" · "),
        summary = r.summary.trim(),
        facts = shownFacts(r.facts),
        reviews = reviews,
        note = r.note.trim(),
        cached = cached,
    )
}

/** Les infos pratiques d'OpenStreetMap, et leur source : sa mention (liée à sa licence), la date de l'extrait, « Corriger ». */
data class OsmShown(val rows: List<Fact>, val attribution: LinkText, val extract: String, val fix: LinkText?)

const val OSM_CREDIT = "© les contributeurs d'OpenStreetMap"

/** Ce que montre le bloc d'OpenStreetMap ; rien à y montrer : `null` (et sa mention avec). */
fun osmShown(o: OsmPart?, now: Long, zone: ZoneId = ZoneId.systemDefault()): OsmShown? {
    o ?: return null
    val labels = o.facts.map { it.label.trim().lowercase(Locale.FRENCH) }.toSet()
    val rows = buildList {
        if (o.address.isNotBlank() && "adresse" !in labels) add(Fact("Adresse", o.address.trim()))
        addAll(o.facts)
        if (o.phone.isNotBlank() && "téléphone" !in labels) add(Fact("Téléphone", o.phone.trim()))
        safeHref(o.website)?.let { if ("site" !in labels) add(Fact("Site", it)) }
        if (o.email.isNotBlank() && "courriel" !in labels) add(Fact("Courriel", o.email.trim()))
    }.let(::shownFacts)
    if (rows.isEmpty()) return null
    val extract = isoWords(o.extract, now, zone)
    return OsmShown(
        rows = rows,
        attribution = linkText(o.attribution.trim().ifEmpty { OSM_CREDIT }, o.licenceUrl),
        extract = if (extract.isEmpty()) "" else "extrait du $extract, dans l'index de ce serveur",
        fix = safeHref(o.url)?.let { LinkText("Corriger sur OpenStreetMap", it) },
    )
}

/** Ce qu'en dit l'office de tourisme : la description, les labels, les tarifs et les contacts, et qui l'a écrit, quand. */
data class TourismShown(
    val paragraphs: List<String>,
    val labels: List<String>,
    val rows: List<Fact>,
    val attribution: String,
    val licence: LinkText,
    val fiche: LinkText?,
)

const val TOURISM_SOURCE = "DATAtourisme"
const val TOURISM_LICENCE = "Licence Ouverte"

/** Ce que montre le bloc de l'office de tourisme ; rien à y montrer : `null` (et son attribution avec). */
fun tourismShown(t: TourismPart?): TourismShown? {
    t ?: return null
    val desc = paragraphs(t.description)
    val labels = t.labels.map { it.trim() }.filter { it.isNotEmpty() }
    val rows = shownFacts(listOfNotNull(t.prices.trim().takeIf { it.isNotEmpty() }?.let { Fact("Tarifs", it) }) + t.contacts)
    if (desc.isEmpty() && labels.isEmpty() && rows.isEmpty()) return null
    return TourismShown(
        paragraphs = desc,
        labels = labels,
        rows = rows,
        attribution = t.attribution.trim().ifEmpty { TOURISM_SOURCE },
        licence = linkText(t.licence.trim().ifEmpty { TOURISM_LICENCE }, t.licenceUrl),
        fiche = safeHref(t.url)?.let { LinkText("Sa fiche", it) },
    )
}

/** La ligne d'un événement tout près, dans la fiche d'un lieu : « sam. 21 nov. · 19:00–22:00 · 780 m · 12/8 € ». */
fun nearEventLine(e: EventItem): String =
    listOf(e.whenText, km(e.distanceM), if (e.free == true) "gratuit" else e.price)
        .map { it.trim() }.filter { it.isNotEmpty() }.joinToString(" · ")

/** La ligne sous le nom d'une fiche : « Restaurant · Lille · à 240 m ». */
fun ficheSub(p: Place): String = listOf(placeWhat(p), km(p.distanceM).let { if (it.isEmpty()) "" else "à $it" })
    .filter { it.isNotEmpty() }.joinToString(" · ")

/** « En parler à Mika » d'une fiche : la même phrase qu'Explorer. */
fun askAboutFiche(p: Place): String = askAboutPlace(p)

// ── Une liste de lieux ──────────────────────────────────────────────────

/** « 4 et plus » : la note minimale du filtre. */
const val MIN_RATING = 4.0

/** Un filtre au moins est posé (l'ordre n'en est pas un). */
fun filtersOn(f: PlaceFilters): Boolean = f.open || f.features.isNotEmpty() || f.minRating != null || f.cuisine.isNotBlank()

/** Ce filtre-là ajouté, ou retiré s'il y était. */
fun toggledFeature(f: PlaceFilters, id: String): PlaceFilters =
    f.copy(features = if (id in f.features) f.features - id else f.features + id)

/** L'ordre suivant d'une liste (« Les plus proches » → « Les mieux notés » → …) ; un seul ordre : le même. */
fun nextSort(sorts: List<Category>, current: String): String {
    if (sorts.size < 2) return current
    val i = sorts.indexOfFirst { it.id == current }
    return sorts[(i + 1).mod(sorts.size)].id
}

/** Le nom d'un ordre (« Les plus proches ») ; inconnu : celui du premier. */
fun sortLabel(sorts: List<Category>, current: String): String =
    (sorts.firstOrNull { it.id == current } ?: sorts.firstOrNull())?.label.orEmpty()

/**
 * Les cuisines qu'on propose au filtre : celles de la liste montrée (« Italienne, pizza » en donne deux), les plus
 * fréquentes d'abord (douze au plus), et celle qu'on a choisie, toujours (en tête si la liste ne l'a plus).
 */
fun cuisineChoices(places: List<Place>, current: String = ""): List<String> {
    val counts = LinkedHashMap<String, Pair<String, Int>>()
    for (p in places) for (raw in p.cuisine.split(',', ';')) {
        val label = raw.trim()
        if (label.isEmpty() || label.length > CUISINE_MAX) continue
        val key = label.lowercase(Locale.FRENCH)
        val seen = counts[key]
        counts[key] = if (seen != null) seen.first to seen.second + 1 else label.replaceFirstChar { it.titlecase(Locale.FRENCH) } to 1
    }
    val collator = Collator.getInstance(Locale.FRENCH)
    val out = counts.values.sortedWith { a, b -> if (a.second != b.second) b.second - a.second else collator.compare(a.first, b.first) }
        .take(12).map { it.first }.toMutableList()
    val chosen = current.trim()
    if (chosen.isNotEmpty() && out.none { it.equals(chosen, ignoreCase = true) }) out.add(0, chosen)
    return out
}

/**
 * L'identifiant par lequel ouvrir la fiche d'un lieu : son objet d'OpenStreetMap (stable d'un index à l'autre), sinon sa
 * ligne de l'index ou son lieu des données touristiques ; une adresse, un point nommé : `null` (pas de fiche).
 */
fun ficheId(p: Place): String? = placeRef(p.osm) ?: placeRef(p.id)

/**
 * Ce que la ligne d'un lieu montre sous son nom : sa note Google et le nombre d'avis ([rating], [count] : « (15 235) »),
 * puis son prix et sa cuisine (sinon ce qu'il est) ; sans note, ce qu'il est et où, son prix, sa cuisine. Dessous,
 * ouvert ou fermé ([open], à la couleur de [openTone]).
 */
data class PlaceRow(val rating: Double?, val count: String, val line: String, val open: String, val openTone: Tone)

fun placeRow(p: Place): PlaceRow {
    val rating = p.rating?.takeIf { it.isFinite() }
    val parts = if (rating != null) {
        listOf(p.price, p.cuisine.ifBlank { p.kindFr })
    } else {
        listOf(placeWhat(p), p.price, p.cuisine)
    }
    return PlaceRow(
        rating = rating,
        count = p.reviews?.takeIf { it >= 0 }?.let { "(${thousands(it)})" }.orEmpty(),
        line = parts.map { it.trim() }.filter { it.isNotEmpty() }.joinToString(" · "),
        open = p.openText.trim(),
        openTone = openTone(p.openState),
    )
}
